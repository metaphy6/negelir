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
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterable

from ..sdk.types import Message
from common.config import cfg
from .topics import (
    FRESHNESS_EVENTS,
    MATCH_NORMALIZED,
    MATCH_STORED,
    MODEL_TRAINED,
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PREDICT_VOTE,
    PROOF_FLAG,
    SCRAPE_CLASSIFIED,
    SCRAPE_RAW,
    SCRAPE_REQUEST,
    TELEMETRY,
)

_log = logging.getLogger(__name__)


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
)


class _Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.msgs_by_topic: dict[str, int] = defaultdict(int)
        self.dlq_by_topic: dict[str, int] = defaultdict(int)
        self.last_seen: dict[str, str] = {}
        self.latency_ms_total: dict[str, float] = defaultdict(float)
        self.latency_n: dict[str, int] = defaultdict(int)

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
            lines.append("")
            return "\n".join(lines)


class _MetricsHandler(BaseHTTPRequestHandler):  # pragma: no cover - thin HTTP shim
    counters: "_Counters"

    def do_GET(self) -> None:  # noqa: N802 — http.server contract
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = self.counters.render_prometheus().encode("utf-8")
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
        self.counters.observe(str(msg.envelope.topic), latency_ms=latency_ms)
        return ()

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
            {"counters": self.counters},
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
