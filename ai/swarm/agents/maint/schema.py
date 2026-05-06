"""Phase 8 §8.6 — `maint.schema.v1` schema sentinel.

Detector A only in v1: samples bus payloads at a token-bucket rate
and re-validates them against their topic's JSON Schema. Mismatches
emit ``maint.event.v1{kind=schema_drift_detected}`` with a debounced
sec.alert.v1 sibling for repeated offenders.

Detectors B (PG column drift) and C (dataclass-vs-schema AST scan)
are stubbed as `_detect_b_pending()` / `_detect_c_pending()` so the
follow-up slice is a single function-body fill-in.

Sample-rate cap: ``cfg.maint_schema_sample_rate_per_s`` tokens per
second per topic, with a `maint_schema_burst` cap. Per ROADMAP
§8.14.7 binding, the cap is per-topic so a hot topic cannot starve
sampling on a quiet one.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk import schemas as _schemas
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck
from ..topics import MAINT_ACK, MAINT_EVENT
from . import _schema_drift as _drift
from ._pause_state import PauseState

_log = logging.getLogger("swarm.agents.maint.schema")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


@dataclass
class _TopicBucket:
    """Per-topic token bucket + last-drift cache."""

    tokens: float = 0.0
    last_refill: float = 0.0
    last_drift_at: float = 0.0
    seen: int = 0
    drifted: int = 0


class MaintSchemaSentinel:
    """`maint.schema.v1` reactor — Detector A.

    Subscribes any topic the swarm bootstrap wires it to (test wires
    explicit topics; production wiring lands with the bus tap when
    ``Bus.tap()`` ships). Publishes ``maint.event.v1`` notifications
    only — operator commands are deferred to §8.6b.
    """

    name = "maint.schema.v1"
    # Subscribes MAINT_EVENT for operator-driven maint_pause /
    # maint_resume per §8.10/§8.13.5; sample taps for Detector A
    # are still wired by the bootstrap via :meth:`observe`.
    subscribes: tuple[Topic, ...] = (MAINT_EVENT,)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK)

    def __init__(
        self,
        *,
        clock_iso: Callable[[], str] | None = None,
        clock_mono: Callable[[], float] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._clock_iso = clock_iso or _utc_iso
        self._clock_mono = clock_mono or time.monotonic
        self._new_id = new_id or _new_id
        self._buckets: dict[str, _TopicBucket] = defaultdict(_TopicBucket)
        # Bounded LRU of (topic, sha256) → last_drift_at to debounce.
        self._drift_lru: "OrderedDict[tuple[str, str], float]" = OrderedDict()
        # §8.6 Detector B — throttle to ``cfg.maint_schema_pg_check_interval_s``.
        # ``-inf`` means the first call always fires; subsequent calls
        # honor the cadence.
        self._last_pg_check_at: float = float("-inf")
        # §8.13.5 pause/isolation matrix.
        self._pause = PauseState()

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        # Operator-driven maint_pause / maint_resume on MAINT_EVENT.
        if msg.envelope.topic == MAINT_EVENT:
            payload = msg.payload or {}
            kind = payload.get("kind")
            if kind == "maint_pause":
                return list(self._handle_pause(msg, payload, paused=True))
            if kind == "maint_resume":
                return list(self._handle_pause(msg, payload, paused=False))
            # Other maint kinds: still subject to Detector A sampling.
            return self.observe(msg)
        # Sample taps forward through :meth:`observe`.
        return self.observe(msg)

    # ── maint_pause / maint_resume (§8.13.5 idempotency matrix) ──
    def _handle_pause(self, msg: Message, payload: dict, *, paused: bool) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target = str(payload.get("target") or "")
        if not request_id:
            return
        if target not in ("all", self.name):
            yield self._ack(msg, request_id, accepted=True, reason="not_targeted")
            return
        now_ns = int(self._clock_mono() * 1_000_000_000)
        self._pause.expire_if_due(now_ns)
        if paused:
            ttl_s = int(payload.get("ttl_s") or 0) or int(_cfg.maint_pause_default_ttl_s)
            res = self._pause.apply_pause(ttl_s=ttl_s, now_ns=now_ns)
        else:
            res = self._pause.apply_resume()
        details = None
        if res.deadline_ns is not None:
            details = {"ttl_s": (res.deadline_ns - now_ns) // 1_000_000_000}
        yield self._ack(msg, request_id, accepted=res.accepted,
                        reason=res.reason, details=details)

    def _ack(self, msg: Message, request_id: str, *, accepted: bool,
             reason: str, details: dict | None = None) -> Message:
        ack = MaintAck(
            request_id=request_id,
            accepted=accepted,
            accepted_by=self.name,
            processed_at=self._clock_iso(),
            attempt=int(msg.envelope.attempt or 1),
            reason=reason,
            details=details,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=msg.envelope.trace_id,
            topic=MAINT_ACK,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=ack.as_dict())

    def observe(self, msg: Message) -> Iterable[Message]:
        """Sample the message; emit a drift notification if the
        payload fails its topic schema and the bucket allows it."""
        topic = str(msg.envelope.topic)
        if not topic:
            return
        bucket = self._buckets[topic]
        if not self._consume_token(bucket):
            return
        bucket.seen += 1
        # Validate payload against the topic schema (kind-discriminated
        # topics use validate_kind; flat topics use validate).
        errors = self._validate(topic, msg.payload or {})
        if not errors:
            return
        bucket.drifted += 1
        # Debounce: dedupe same (topic, error-shape) inside a window.
        sig = self._error_signature(errors)
        key = (topic, sig)
        debounce_s = max(1, int(_cfg.maint_schema_drift_debounce_s))
        now = self._clock_mono()
        last = self._drift_lru.get(key)
        if last is not None and (now - last) < debounce_s:
            return
        self._drift_lru[key] = now
        # LRU bound.
        max_lru = max(64, int(_cfg.maint_schema_drift_lru))
        while len(self._drift_lru) > max_lru:
            self._drift_lru.popitem(last=False)
        yield self._notify_drift(topic, errors)

    # ── Token bucket ─────────────────────────────────────────────
    def _consume_token(self, bucket: _TopicBucket) -> bool:
        rate = max(0.001, float(_cfg.maint_schema_sample_rate_per_s))
        burst = max(1, int(_cfg.maint_schema_burst))
        now = self._clock_mono()
        if bucket.last_refill == 0.0:
            bucket.last_refill = now
            bucket.tokens = float(burst)
        else:
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(float(burst), bucket.tokens + elapsed * rate)
            bucket.last_refill = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    # ── Validation indirection (kind-discriminated aware) ────────
    def _validate(self, topic: str, payload: dict) -> list[str]:
        try:
            kind_topics = _schemas.kind_discriminated_topics()
        except Exception:  # noqa: BLE001 — sentinel must never crash the producer
            kind_topics = frozenset()
        if topic in kind_topics:
            try:
                return _schemas.validate_kind(Topic(topic), payload)
            except Exception as exc:  # noqa: BLE001
                return [f"validate_kind_error: {exc}"]
        try:
            return _schemas.validate(Topic(topic), payload)
        except Exception as exc:  # noqa: BLE001
            return [f"validate_error: {exc}"]

    def _error_signature(self, errors: list[str]) -> str:
        # Compact deterministic signature for debounce dedup.
        first = errors[0] if errors else ""
        # Strip variable trailing values; first 80 chars is enough.
        return first[:80]

    # ── Detector B (PG column drift) ──────────────────────────
    def detect_b(
        self,
        *,
        fetch_columns: Callable[[], dict[str, set[str]]],
        migrations_dir: "Path | None" = None,
        force: bool = False,
    ) -> list[Message]:
        """Compare live PG columns to migration-derived expected set.

        Caller-supplied ``fetch_columns`` returns
        ``{table_name: {col1, col2, ...}}`` — kept as a callable so
        the agent has zero psycopg dependency at the unit-test
        boundary (the production wiring lives in the runner).

        Throttled to ``cfg.maint_schema_pg_check_interval_s`` between
        runs unless ``force=True``. Drift is emitted as
        ``maint.event.v1{kind=schema_drift_detected, detector="B",
        target=<table>, drift_kind, columns}`` events. When the
        migration parser flagged a table in ``unknown_constructs``,
        events for that table carry ``severity="info"`` and a
        ``parser_uncertain: true`` field; otherwise ``severity="warn"``.
        """
        from pathlib import Path as _Path
        now = self._clock_mono()
        interval = max(60, int(_cfg.maint_schema_pg_check_interval_s))
        if not force and (now - self._last_pg_check_at) < interval:
            return []
        self._last_pg_check_at = now
        mig_path = migrations_dir or _Path("migrations")
        digest = _drift.parse_migrations_dir(mig_path)
        try:
            observed = fetch_columns() or {}
        except Exception as exc:  # noqa: BLE001 — sentinel never crashes
            _log.warning("detector B fetch_columns failed: %s", exc)
            return []
        # Lower-case observed names so set diffs are case-insensitive
        # (PG is case-insensitive for unquoted identifiers).
        observed_norm = {
            k.lower(): {c.lower() for c in v}
            for k, v in observed.items()
        }
        diffs = _drift.diff_columns(digest.tables, observed_norm)
        out: list[Message] = []
        for table, drift_kind, details in diffs:
            uncertain = table in digest.unknown_constructs
            severity = "info" if uncertain else "warn"
            out.append(self._notify_drift_b(
                table=table,
                drift_kind=drift_kind,
                details=details,
                severity=severity,
                parser_uncertain=uncertain,
            ))
        return out

    def _notify_drift_b(self, *, table: str, drift_kind: str,
                        details: list[str], severity: str,
                        parser_uncertain: bool) -> Message:
        payload: dict = {
            "kind": "schema_drift_detected",
            "target": table,
            "produced_at": self._clock_iso(),
            "detector": "B",
            "drift_kind": drift_kind,
            "details": list(details)[:64],
            "severity": severity,
            "parser_uncertain": bool(parser_uncertain),
        }
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)

    # ── Detector C (dataclass vs schema) ──────────────────────
    def detect_c(
        self,
        *,
        payloads_path: "Path | None" = None,
        dataclass_schema_map: "dict[str, tuple[set[str], set[str]]] | None" = None,
    ) -> list[Message]:
        """Run a one-shot AST parity check between dataclasses in
        ``payloads_path`` and a caller-supplied
        ``{class_name: (schema_properties, schema_required)}`` map.

        Classes absent from the map are skipped (forward-compatible —
        the curator grows the map over time). Drift events fire one
        per offending class with ``detector="C"``. Severity is always
        ``critical`` per §8.6 (dataclass-vs-schema mismatch is a
        release bug, not a runtime drift).
        """
        from pathlib import Path as _Path
        path = payloads_path or _Path(__file__).resolve().parents[2] / "agents" / "payloads.py"
        digest = _drift.parse_payloads_dataclasses(path)
        out: list[Message] = []
        if not dataclass_schema_map:
            return out
        for cls_name, (props, required) in dataclass_schema_map.items():
            if cls_name not in digest.classes:
                out.append(self._notify_drift_c(
                    target=cls_name,
                    errors=["dataclass not found in payloads module"],
                ))
                continue
            errors = _drift.diff_dataclass_vs_schema(
                dataclass_fields=digest.classes[cls_name],
                schema_properties=set(props),
                schema_required=set(required),
            )
            if errors:
                out.append(self._notify_drift_c(target=cls_name,
                                                 errors=errors))
        return out

    def _notify_drift_c(self, *, target: str, errors: list[str]) -> Message:
        payload: dict = {
            "kind": "schema_drift_detected",
            "target": target,
            "produced_at": self._clock_iso(),
            "detector": "C",
            "severity": "critical",
            "errors": list(errors)[:16],
        }
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)

    # ── Emission helper ─────────────────────────────────────────
    def _notify_drift(self, topic: str, errors: list[str]) -> Message:
        payload: dict = {
            "kind": "schema_drift_detected",
            "target": topic,
            "produced_at": self._clock_iso(),
            "detector": "A",
            "error_count": len(errors),
            "first_error": errors[0][:240] if errors else "",
        }
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)


__all__ = ["MaintSchemaSentinel"]
