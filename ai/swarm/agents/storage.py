"""Phase 4.4 — Storage agent.

Subscribes `match.normalized`; performs an idempotent upsert keyed on
``(source, source_match_id, record_type)`` (matches the migration
``match_normalized`` UNIQUE). Emits `match.stored` with the resulting
row id and a ``change_kind`` of ``created`` / ``updated`` /
``unchanged``. Also emits a `freshness.events.v1` row for
``created``/``updated`` outcomes so reactors can react.

Persistence is abstracted behind ``RecordStore`` so tests can swap in
``InMemoryRecordStore``. The Postgres implementation lives in
``ai/swarm/agents/storage_pg.py`` (added when Phase 4.4.b lands the
real DB wiring).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from ..sdk.types import Message
from .payloads import (
    FreshnessEvent,
    MatchOutcome,
    MatchStored,
    NormalizedRecord,
    TERMINAL_MATCH_STATUSES,
    derive_match_outcome,
)
from .topics import (
    FRESHNESS_EVENTS,
    MATCH_NORMALIZED,
    MATCH_OUTCOME,
    MATCH_STORED,
)

_log = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class StoreOutcome:
    """Result of an upsert: (record_id, change_kind, diff).

    Frozen so callers can't quietly mutate the change_kind / diff
    after the storage agent has handed it off.
    """

    record_id: int
    change_kind: str            # 'created' | 'updated' | 'unchanged'
    diff: dict[str, Any] = field(default_factory=dict)


class RecordStore(Protocol):
    def upsert(self, rec: NormalizedRecord) -> StoreOutcome: ...


class InMemoryRecordStore:
    """Single-writer in-memory store for tests + swarm.demo.

    Thread-safe so the runner's worker pool cannot lose updates.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        # Map (source, source_match_id, record_type) -> (id, payload, version)
        self._rows: dict[tuple[str, str, str], tuple[int, dict, int]] = {}

    def upsert(self, rec: NormalizedRecord) -> StoreOutcome:
        key = (rec.source, rec.source_match_id, rec.record_type)
        with self._lock:
            existing = self._rows.get(key)
            if existing is None:
                row_id = self._next_id
                self._next_id += 1
                self._rows[key] = (row_id, dict(rec.payload), rec.canonical_version)
                return StoreOutcome(row_id, "created")

            row_id, prev_payload, _prev_ver = existing
            if prev_payload == rec.payload:
                return StoreOutcome(row_id, "unchanged")

            diff = _shallow_diff(prev_payload, rec.payload)
            self._rows[key] = (row_id, dict(rec.payload), rec.canonical_version)
            return StoreOutcome(row_id, "updated", diff=diff)

    def get(self, source: str, source_match_id: str, record_type: str) -> dict | None:
        with self._lock:
            row = self._rows.get((source, source_match_id, record_type))
            return None if row is None else dict(row[1])

    def all_rows(self) -> list[tuple[int, dict]]:
        with self._lock:
            return [(rid, dict(payload)) for rid, payload, _ in self._rows.values()]


def _shallow_diff(before: dict, after: dict) -> dict:
    """Full key-level diff between two payload snapshots.

    Pre-Phase-6 audit A5: returns the **complete** diff. Earlier
    versions truncated to ``{"_truncated": True, "n_changed": N}``
    once more than 16 fields changed, but that lost the actual
    keys — the freshness reactors look at ``ev.diff`` to find
    e.g. ``league_id`` and route plane-bounded side effects, so
    truncating produces silent misroutes. Truncation must happen
    in the telemetry projection (see ``summarize_diff_for_telemetry``)
    where it is observed, not in the producer.
    """
    changed: dict[str, list] = {}
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            changed[key] = [before.get(key), after.get(key)]
    return changed


def summarize_diff_for_telemetry(diff: dict, *, max_fields: int = 16) -> dict:
    """Bounded projection of a `_shallow_diff` for low-cardinality
    telemetry sinks. Keep full data on the bus; truncate only here."""
    if len(diff) <= max_fields:
        return dict(diff)
    return {"_truncated": True, "n_changed": len(diff)}


# ── Agent ────────────────────────────────────────────────────────


class StorageAgent:
    name = "storage.v1"
    subscribes = (MATCH_NORMALIZED,)
    publishes = (MATCH_STORED, FRESHNESS_EVENTS, MATCH_OUTCOME)

    def __init__(self, store: RecordStore | None = None) -> None:
        # Explicit None check — see CacheAgent for the same foot-gun
        # (a backend that defines __len__ is falsy when empty).
        self.store: RecordStore = InMemoryRecordStore() if store is None else store

    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            rec = NormalizedRecord.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed match.normalized: %s", self.name, exc)
            return ()

        outcome = self.store.upsert(rec)
        now = _utc_now_iso()

        stored = MatchStored(
            record_id=outcome.record_id,
            record_type=rec.record_type,
            plane=rec.plane,
            source=rec.source,
            stable_id=rec.stable_id,
            change_kind=outcome.change_kind,
            stored_at=now,
        )
        out: list[Message] = [
            Message.new(
                MATCH_STORED,
                stored.as_dict(),
                producer=self.name,
                trace_id=msg.envelope.trace_id,
            )
        ]
        if outcome.change_kind in ("created", "updated"):
            event_id = FreshnessEvent.derive_event_id(
                source=rec.source,
                stable_id=rec.stable_id,
                record_type=rec.record_type,
                change_kind=outcome.change_kind,
                diff=outcome.diff,
            )
            ev = FreshnessEvent(
                event_id=event_id,
                record_id=outcome.record_id,
                source=rec.source,
                stable_id=rec.stable_id,
                record_type=rec.record_type,
                plane=rec.plane,
                change_kind=outcome.change_kind,
                diff=outcome.diff,
                emitted_at=now,
            )
            out.append(
                Message.new(
                    FRESHNESS_EVENTS,
                    ev.as_dict(),
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                )
            )

            # Phase 5+ — emit `match.outcome.v1` when the upsert lands a
            # match_detail record carrying a terminal status with both
            # final scores. We rely on the storage upsert path's
            # `unchanged` short-circuit for single-emission: a re-scrape
            # of the same final score yields `unchanged` and no
            # outcome message (mirrors the freshness suppression
            # contract). Phase 6 drift / proofreader can subscribe
            # without worrying about duplicate ground-truth events.
            outcome_msg = self._maybe_match_outcome(
                rec=rec, record_id=outcome.record_id, settled_at=now,
                trace_id=msg.envelope.trace_id,
            )
            if outcome_msg is not None:
                out.append(outcome_msg)
        return out

    def _maybe_match_outcome(
        self,
        *,
        rec: NormalizedRecord,
        record_id: int,
        settled_at: str,
        trace_id: str,
    ) -> Message | None:
        if rec.record_type != "match_detail":
            return None
        payload = rec.payload
        status_raw = str(payload.get("status") or "").strip().lower()
        if status_raw not in TERMINAL_MATCH_STATUSES:
            return None
        # Final scores may live under a few common keys; storage agent
        # is intentionally lenient here so producers picking different
        # extractor conventions all wire through.
        final_home = payload.get("final_home")
        final_away = payload.get("final_away")
        if final_home is None or final_away is None:
            score = payload.get("score") or {}
            if isinstance(score, dict):
                final_home = final_home if final_home is not None else score.get("home")
                final_away = final_away if final_away is not None else score.get("away")
        if final_home is None or final_away is None:
            _log.debug(
                "%s: terminal status %r but no final scores; skipping match.outcome.v1",
                self.name, status_raw,
            )
            return None
        try:
            fh = int(final_home)
            fa = int(final_away)
        except (TypeError, ValueError):
            _log.warning(
                "%s: terminal payload has non-integer scores home=%r away=%r",
                self.name, final_home, final_away,
            )
            return None
        outcomes = derive_match_outcome(final_home=fh, final_away=fa)
        mo = MatchOutcome(
            match_id=rec.source_match_id,
            stable_id=rec.stable_id,
            source=rec.source,
            final_home=fh,
            final_away=fa,
            outcome_1x2=outcomes["outcome_1x2"],
            outcome_ou_2_5=outcomes["outcome_ou_2_5"],
            outcome_btts=outcomes["outcome_btts"],
            settled_at=settled_at,
            league_id=rec.league_id,
            competition_id=rec.competition_id,
            record_id=record_id,
        )
        return Message.new(
            MATCH_OUTCOME,
            mo.as_dict(),
            producer=self.name,
            trace_id=trace_id,
        )


__all__ = [
    "InMemoryRecordStore",
    "RecordStore",
    "StorageAgent",
    "StoreOutcome",
]
