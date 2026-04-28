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
from typing import Iterable, Protocol

from ..sdk.types import Message
from .payloads import FreshnessEvent, MatchStored, NormalizedRecord
from .topics import FRESHNESS_EVENTS, MATCH_NORMALIZED, MATCH_STORED

_log = logging.getLogger(__name__)


class StoreOutcome:
    """Result of an upsert: (record_id, change_kind, diff)."""

    __slots__ = ("record_id", "change_kind", "diff")

    def __init__(self, record_id: int, change_kind: str, diff: dict | None = None) -> None:
        self.record_id = record_id
        self.change_kind = change_kind
        self.diff = diff or {}


class RecordStore(Protocol):
    def upsert(self, rec: NormalizedRecord) -> StoreOutcome: ...


class InMemoryRecordStore:
    """Single-writer in-memory store for tests + swarm-demo.

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
            return StoreOutcome(row_id, "updated", diff)

    def get(self, source: str, source_match_id: str, record_type: str) -> dict | None:
        with self._lock:
            row = self._rows.get((source, source_match_id, record_type))
            return None if row is None else dict(row[1])

    def all_rows(self) -> list[tuple[int, dict]]:
        with self._lock:
            return [(rid, dict(payload)) for rid, payload, _ in self._rows.values()]


def _shallow_diff(before: dict, after: dict) -> dict:
    """Return a tiny diff summary suitable for the freshness event."""
    changed: dict[str, list] = {}
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            changed[key] = [before.get(key), after.get(key)]
    # Trim large diffs — the bus is for control, not bulk.
    if len(changed) > 16:
        return {"_truncated": True, "n_changed": len(changed)}
    return changed


# ── Agent ────────────────────────────────────────────────────────


class StorageAgent:
    name = "storage.v1"
    subscribes = [MATCH_NORMALIZED]
    publishes = [MATCH_STORED, FRESHNESS_EVENTS]

    def __init__(self, store: RecordStore | None = None) -> None:
        self.store: RecordStore = store or InMemoryRecordStore()

    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            rec = NormalizedRecord.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed match.normalized: %s", self.name, exc)
            return ()

        outcome = self.store.upsert(rec)

        stored = MatchStored(
            record_id=outcome.record_id,
            record_type=rec.record_type,
            plane=rec.plane,
            source=rec.source,
            stable_id=rec.stable_id,
            change_kind=outcome.change_kind,
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
            ev = FreshnessEvent(
                record_id=outcome.record_id,
                plane=rec.plane,
                record_type=rec.record_type,
                change_kind=outcome.change_kind,
                diff_summary=outcome.diff,
            )
            out.append(
                Message.new(
                    FRESHNESS_EVENTS,
                    ev.as_dict(),
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                )
            )
        return out


__all__ = [
    "InMemoryRecordStore",
    "RecordStore",
    "StorageAgent",
    "StoreOutcome",
]
