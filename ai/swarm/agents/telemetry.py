"""Phase 4.6 — Telemetry agent.

Wildcard consumer over every Phase 4 topic. Counts messages, error
rates (DLQ), and per-topic latency, exposes a Prometheus text page on
``cfg.telemetry_metrics_port`` (default 9101), and (optionally) writes
to the ``telemetry_events`` Postgres table for forensic queries.

The Prometheus exposition is deliberately tiny — no client lib so the
SDK stays stdlib-only. Production deployments add the
``prometheus_client`` extra later if richer metrics are needed.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Iterable

from ..sdk.types import Message
from common.config import cfg
from .topics import (
    FRESHNESS_EVENTS,
    MAINT_ACK,
    MAINT_EVENT,
    MATCH_NORMALIZED,
    MATCH_OUTCOME,
    MATCH_STORED,
    MODEL_TRAINED,
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PREDICT_VOTE,
    PROOF_FLAG,
    PROOFREADER_VERDICT,
    QA_REQUEST,
    QA_REQUEST_V1,
    SCRAPE_CLASSIFIED,
    SCRAPE_RAW,
    SCRAPE_REQUEST,
    SEC_ALERT,
    SEC_DENYLIST,
    SEC_QUARANTINE,
    TELEMETRY,
)

_log = logging.getLogger(__name__)

_METRIC_KEY_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?$"
)


_WATCHED_TOPICS = (
    SCRAPE_REQUEST,
    SCRAPE_RAW,
    SCRAPE_CLASSIFIED,
    MATCH_NORMALIZED,
    MATCH_STORED,
    FRESHNESS_EVENTS,
    PROOF_FLAG,
    TELEMETRY,
    # Phase 5 — predictor swarm topics. Telemetry is the single
    # observability surface; missing these meant Phase 5 traffic was
    # invisible in the Prometheus page.
    PREDICT_REQUEST,
    PREDICT_VOTE,
    PREDICT_FINAL,
    MODEL_TRAINED,
    # Phase 6 (Wave A.1) — proofreader-approved, user-visible predictions.
    PREDICT_APPROVED,
    # Phase 6 (Wave A.2/A.3) — close the §6.5 telemetry follow-up:
    # individual proofreader verdicts, drift-emitted maintenance
    # events, and the storage-emitted match outcomes that drift
    # consumes. Without these, the proofreader gauntlet and drift
    # window were invisible in the Prometheus page.
    PROOFREADER_VERDICT,
    MAINT_EVENT,
    MATCH_OUTCOME,
    # Phase 7 — Defense-agent envelopes (foundation; agent logic lands
    # in §7.1-7.3). Telemetry watches the wire surface from day-1 so
    # the Prometheus page sees the topic counters even before the
    # producers turn on. `qa.request` is the unversioned control-plane
    # raw escalation (§7.5 binding); `qa.request.v1` is the data-plane
    # sanitized envelope. `sec.alert.v1` carries the open-enum `kind`
    # — telemetry counts by topic only (cardinality bound), the
    # `kind` dimension is exposed via dedicated counters in the
    # security dashboard, never as a metric label here.
    QA_REQUEST,
    QA_REQUEST_V1,
    SEC_ALERT,
    SEC_QUARANTINE,
    SEC_DENYLIST,
    # Phase 8 — per-consumer ack acknowledgements. Telemetry counts
    # accepted/rejected ratios and ack latency per consumer so the
    # ops console can surface degraded consumers (§8.9 visibility).
    MAINT_ACK,
)


class _Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.msgs_by_topic: dict[str, int] = defaultdict(int)
        self.dlq_by_topic: dict[str, int] = defaultdict(int)
        self.last_seen: dict[str, str] = {}
        self.latency_ms_total: dict[str, float] = defaultdict(float)
        self.latency_n: dict[str, int] = defaultdict(int)
        # Phase 8 §8.9 — per-consumer ack counters for maint.ack.v1.
        # Keyed by `accepted_by` (consumer identity string). These power
        # the per-consumer ack latency and accepted/rejected ratio gauges
        # on the Prometheus page so the ops console can surface degraded
        # or slow consumers without log-grepping.
        self.ack_accepted_by_consumer: dict[str, int] = defaultdict(int)
        self.ack_rejected_by_consumer: dict[str, int] = defaultdict(int)
        self.ack_latency_ms_total_by_consumer: dict[str, float] = defaultdict(float)
        self.ack_latency_n_by_consumer: dict[str, int] = defaultdict(int)

    def observe_ack(
        self, *, consumer: str, accepted: bool, latency_ms: float
    ) -> None:
        """Record one `maint.ack.v1` observation.

        ``consumer`` is the ``accepted_by`` field from the payload;
        must be non-empty (callers skip observations with missing /
        empty consumer identity).
        """
        with self._lock:
            if accepted:
                self.ack_accepted_by_consumer[consumer] += 1
            else:
                self.ack_rejected_by_consumer[consumer] += 1
            self.ack_latency_ms_total_by_consumer[consumer] += latency_ms
            self.ack_latency_n_by_consumer[consumer] += 1

    def observe(self, topic: str, *, latency_ms: float) -> None:
        with self._lock:
            self.msgs_by_topic[topic] += 1
            self.latency_ms_total[topic] += latency_ms
            self.latency_n[topic] += 1
            self.last_seen[topic] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if topic.endswith(".dlq"):
                # Strip suffix to attribute to source topic.
                self.dlq_by_topic[topic[:-4]] += 1

    def render_prometheus(self) -> str:
        with self._lock:
            lines: list[str] = []
            lines.append("# HELP negelir_bus_messages_total Messages observed per topic.")
            lines.append("# TYPE negelir_bus_messages_total counter")
            for topic, n in sorted(self.msgs_by_topic.items()):
                lines.append(f'negelir_bus_messages_total{{topic="{topic}"}} {n}')
            lines.append("# HELP negelir_bus_dlq_total Messages in DLQ per source topic.")
            lines.append("# TYPE negelir_bus_dlq_total counter")
            for topic, n in sorted(self.dlq_by_topic.items()):
                lines.append(f'negelir_bus_dlq_total{{topic="{topic}"}} {n}')
            lines.append("# HELP negelir_bus_latency_ms_avg Average end-to-end latency.")
            lines.append("# TYPE negelir_bus_latency_ms_avg gauge")
            for topic, total in sorted(self.latency_ms_total.items()):
                n = self.latency_n[topic] or 1
                lines.append(
                    f'negelir_bus_latency_ms_avg{{topic="{topic}"}} {total / n:.3f}'
                )
            # Third-pass audit (N3): expose `last_seen` so operators can
            # tell whether a topic is silent vs the swarm being down.
            # Value is a Unix epoch second so Prometheus can compute
            # `time() - negelir_bus_last_seen_epoch{topic=...}` for
            # silence-window alerts. The ISO string is kept on the
            # in-memory counter for forensics, not exported here
            # (label cardinality on a string field is dangerous).
            lines.append("# HELP negelir_bus_last_seen_epoch Epoch seconds of last message per topic.")
            lines.append("# TYPE negelir_bus_last_seen_epoch gauge")
            for topic, iso in sorted(self.last_seen.items()):
                try:
                    epoch = datetime.fromisoformat(iso).timestamp()
                except ValueError:
                    continue
                lines.append(
                    f'negelir_bus_last_seen_epoch{{topic="{topic}"}} {epoch:.0f}'
                )
            # Phase 8 §8.9 — maint.ack.v1 per-consumer counters.
            all_ack_consumers = sorted(
                set(self.ack_accepted_by_consumer)
                | set(self.ack_rejected_by_consumer)
            )
            if all_ack_consumers:
                lines.append(
                    "# HELP negelir_maint_ack_accepted_total"
                    " maint.ack.v1 accepted=true count per consumer."
                )
                lines.append("# TYPE negelir_maint_ack_accepted_total counter")
                for c in all_ack_consumers:
                    n = self.ack_accepted_by_consumer.get(c, 0)
                    lines.append(
                        f'negelir_maint_ack_accepted_total{{consumer="{_quote_label_value(c)}"}}'  # noqa: E501
                        f" {n}"
                    )
                lines.append(
                    "# HELP negelir_maint_ack_rejected_total"
                    " maint.ack.v1 accepted=false count per consumer."
                )
                lines.append("# TYPE negelir_maint_ack_rejected_total counter")
                for c in all_ack_consumers:
                    n = self.ack_rejected_by_consumer.get(c, 0)
                    lines.append(
                        f'negelir_maint_ack_rejected_total{{consumer="{_quote_label_value(c)}"}}'  # noqa: E501
                        f" {n}"
                    )
                lines.append(
                    "# HELP negelir_maint_ack_latency_ms_avg"
                    " Average maint.ack.v1 processing latency per consumer."
                )
                lines.append("# TYPE negelir_maint_ack_latency_ms_avg gauge")
                for c in all_ack_consumers:
                    total = self.ack_latency_ms_total_by_consumer.get(c, 0.0)
                    n = self.ack_latency_n_by_consumer.get(c, 0) or 1
                    lines.append(
                        f'negelir_maint_ack_latency_ms_avg{{consumer="{_quote_label_value(c)}"}}'  # noqa: E501
                        f" {total / n:.3f}"
                    )
            lines.append("")
            return "\n".join(lines)


def _quote_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_flat_snapshot(snapshot: dict[str, float]) -> str:
    """Render ``{"metric{a=b}": n}`` into Prometheus text lines.

    The maint reactors expose snapshots in flat-key form. Telemetry
    parses that shape and quotes label values so the resulting text is
    valid Prometheus exposition.
    """
    lines: list[str] = []
    for raw_key in sorted(snapshot.keys()):
        m = _METRIC_KEY_RE.match(str(raw_key))
        if m is None:
            continue
        name = m.group("name")
        raw_labels = (m.group("labels") or "").strip()
        labels: list[str] = []
        if raw_labels:
            for part in raw_labels.split(","):
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                k = k.strip()
                if not k:
                    continue
                labels.append(f'{k}="{_quote_label_value(v.strip())}"')
        label_block = "{" + ",".join(labels) + "}" if labels else ""
        lines.append(f"{name}{label_block} {float(snapshot[raw_key]):g}")
    return "\n".join(lines)


class _MetricsHandler(BaseHTTPRequestHandler):  # pragma: no cover - thin HTTP shim
    render: Callable[[], str]

    def do_GET(self) -> None:  # noqa: N802 — http.server contract
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = self.render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return  # silence default access logging


class TelemetryAgent:
    name = "telemetry.v1"
    subscribes = tuple(_WATCHED_TOPICS)
    publishes: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.counters = _Counters()
        self._extra_metric_sources: list[Callable[[], dict[str, float]]] = []
        self._server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    @classmethod
    def from_config(cls, *, start_http: bool = False) -> "TelemetryAgent":
        """Build an agent with the metrics exposer wired from `cfg`.

        Centralizes the (port, bind) plumbing so callers cannot drop
        the bind hardening on the floor. Pass ``start_http=True`` to
        spin up the exposer in the same call.
        """
        agent = cls()
        if start_http:
            agent.start_http(
                int(cfg.telemetry_metrics_port),
                bind=str(cfg.telemetry_metrics_bind),
            )
        return agent

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        # Latency from envelope creation to observation. Naive
        # timestamps are treated as UTC so latency math doesn't
        # silently swing across local-vs-UTC boundaries.
        try:
            ts = datetime.fromisoformat(msg.envelope.created_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            latency_ms = max(
                0.0,
                (datetime.now(timezone.utc) - ts).total_seconds() * 1000.0,
            )
        except ValueError:
            latency_ms = 0.0
        topic_str = str(msg.envelope.topic)
        self.counters.observe(topic_str, latency_ms=latency_ms)
        # Phase 8 §8.9 — ack-specific per-consumer counters.
        if topic_str == str(MAINT_ACK):
            consumer = str(msg.payload.get("accepted_by", "")).strip()
            if consumer:
                accepted = bool(msg.payload.get("accepted", False))
                self.counters.observe_ack(
                    consumer=consumer,
                    accepted=accepted,
                    latency_ms=latency_ms,
                )
        return ()

    def register_metric_source(
        self,
        source: Callable[[], dict[str, float]],
    ) -> None:
        """Register an extra metrics snapshot source.

        Sources are rendered on every scrape and must return a flat
        numeric snapshot (e.g. ``MaintScaler.metrics_snapshot``).
        """
        self._extra_metric_sources.append(source)

    def render_prometheus(self) -> str:
        body = self.counters.render_prometheus().rstrip("\n")
        extra_chunks: list[str] = []
        for source in self._extra_metric_sources:
            try:
                snap = source()
            except Exception:
                _log.exception("telemetry: metric source failed")
                continue
            extra = _render_flat_snapshot(snap)
            if extra:
                extra_chunks.append(extra)
        if not extra_chunks:
            return body + "\n"
        return body + "\n" + "\n".join(extra_chunks) + "\n"

    # ── Optional HTTP exposer ───────────────────────────────────────
    def start_http(self, port: int, *, bind: str = "127.0.0.1") -> None:
        """Start a tiny /metrics HTTP server. Idempotent.

        Defaults to ``127.0.0.1`` so an unauthenticated metrics
        endpoint is **not** exposed on every interface (OWASP A05).
        Container deployments that need cross-pod scrape pass
        ``bind="0.0.0.0"`` explicitly and rely on network policy /
        firewalling for protection.
        """
        if self._server is not None:
            return
        handler = type(
            "_BoundHandler",
            (_MetricsHandler,),
            {"render": self.render_prometheus},
        )
        self._server = HTTPServer((bind, port), handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="telemetry-metrics",
            daemon=True,
        )
        self._server_thread.start()
        _log.info("%s: prometheus exposer on %s:%d/metrics", self.name, bind, port)

    def stop_http(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._server_thread = None


# Re-export the topic tuple so tests can iterate.
WATCHED_TOPICS = _WATCHED_TOPICS

__all__ = ["TelemetryAgent", "WATCHED_TOPICS"]
