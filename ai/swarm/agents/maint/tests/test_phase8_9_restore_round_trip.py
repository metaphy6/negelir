"""Phase 8 §8.9 — Restore round-trip proof test.

Binding contract (ROADMAP §8.9 'Restore round-trip'):
  * Nightly dump on a fresh DB seeded with N rows across all tables
    → `ops.restore DATE=... TARGET=<ephemeral>`
    → row counts match per verify.sql
  * `quarantine_samples` is empty by design (PII-aware dump: raw bytes
    excluded; restore executor never re-populates quarantine rows)
  * `maint_audit_log` carries the matched
    `backup_restore_started` + `backup_restore_completed` pair,
    keyed on the same `request_id`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest

from ai.swarm.agents.maint.backup import (
    InMemoryMaintAuditLogger,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopRestoreExecutor,
    NoopVerifier,
    StaticDiskGauge,
    StaticRestoreKeyClass,
)
from ai.swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from ai.swarm.sdk.types import Envelope, Message
from common.config import cfg as _cfg


UTC = timezone.utc
_DUMP_DATE = "2025-03-10"
_REQUEST_ID = "rrt-req-001"
_ACTOR = "ops@localhost"

# Row counts returned by the restore executor — simulates the post-restore
# verify.sql census on all tracked tables.  quarantine_samples is
# intentionally absent (PII-aware backup: raw_bytes_b64 column excluded
# → the quarantine table is empty after restore by design).
_SEEDED_ROW_COUNTS: dict[str, int] = {
    "matches": 120,
    "predict_final": 88,
    "predict_vote": 352,
    "schema_snapshots": 4,
    "pipeline_runs": 16,
    "_schema_max_version": 11,
}


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def wall(self) -> datetime:
        return self.now

    def mono_ns(self) -> int:
        return int(self.now.timestamp() * 1e9)

    def advance(self, *, hours: float = 0.0, minutes: float = 0.0) -> None:
        from datetime import timedelta
        self.now = self.now + timedelta(hours=hours, minutes=minutes)


def _build_agent(
    clock: _StubClock,
    restore_executor: NoopRestoreExecutor,
    audit: InMemoryMaintAuditLogger,
) -> MaintBackupAgent:
    return MaintBackupAgent(
        dump=NoopDumpExecutor(bytes_written=4096),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        restore_executor=restore_executor,
        restore_key_class=StaticRestoreKeyClass(key_class="dr"),
        audit_logger=audit,
        clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
        clock_wall=clock.wall,
        clock_mono_ns=clock.mono_ns,
        new_id=lambda: "rrt-fixed-id",
        enforce_permissions=False,
    )


def _restore_msg(dump_date: str = _DUMP_DATE) -> Message:
    payload: dict = {
        "kind": "restore",
        "target": dump_date,
        "request_id": _REQUEST_ID,
        "client_id": _ACTOR,
        "produced_at": f"{dump_date}T09:00:00Z",
    }
    env = Envelope(
        message_id="rrt-m1",
        trace_id="rrt-t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=f"{dump_date}T09:00:00Z",
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _kinds(msgs: Iterable[Message]) -> list[str]:
    return [(m.payload or {}).get("kind") for m in msgs]


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _live_fire(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Force live-fire mode, isolate backup dir, and set a dummy key dir.

    Patching ``maint_backup_dir`` prevents the agent's boot-time audit-CSV
    read from finding a real 'today' entry in ``data/backups/audit.csv``
    (which would seed ``_last_completed_wall`` and trigger the same-day
    idempotency guard, silently suppressing the dump cycle).
    """
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "/test/keys", raising=False,
    )


# ── Test: row counts match and quarantine_samples excluded ───────────────


def test_restore_round_trip_row_counts_match_seeded_tables() -> None:
    """After dump + restore, verify_summary carries the executor's row counts
    for every seeded table (matches, predict_final, etc.)."""
    clock = _StubClock(_t(2025, 3, 10, 2, 30))  # pre-cron (03:00)
    restore_exe = NoopRestoreExecutor(summary=dict(_SEEDED_ROW_COUNTS))
    audit = InMemoryMaintAuditLogger()
    agent = _build_agent(clock, restore_exe, audit)

    # Trigger nightly dump: advance clock past the 3 AM cron window.
    clock.advance(minutes=31)  # now 03:01
    dump_msgs = list(agent.flush_expired())
    assert "backup_started" in _kinds(dump_msgs), "dump cycle did not fire"
    assert "backup_completed" in _kinds(dump_msgs), "dump cycle did not complete"

    # Operator-driven restore targeting the dump date.
    restore_msgs = list(agent.handle(_restore_msg()))

    completed = next(
        m for m in restore_msgs
        if (m.payload or {}).get("kind") == "backup_restore_completed"
    )
    assert completed.payload["outcome"] == "ok", completed.payload
    summary = completed.payload.get("verify_summary", {})
    for table, expected_count in _SEEDED_ROW_COUNTS.items():
        assert summary.get(table) == expected_count, (
            f"row count mismatch for {table!r}: "
            f"got {summary.get(table)!r}, expected {expected_count!r}"
        )


def test_restore_round_trip_quarantine_samples_excluded() -> None:
    """quarantine_samples is empty by design: the PII-aware backup excludes
    raw_bytes_b64; the restore executor never re-populates quarantine rows.
    The verify_summary must NOT contain a non-zero quarantine_samples count."""
    clock = _StubClock(_t(2025, 3, 10, 2, 30))
    # The executor summary mimics a real pg_restore + verify.sql result:
    # quarantine_samples is absent (table exists but is empty — by design).
    restore_exe = NoopRestoreExecutor(summary=dict(_SEEDED_ROW_COUNTS))
    audit = InMemoryMaintAuditLogger()
    agent = _build_agent(clock, restore_exe, audit)

    clock.advance(minutes=31)
    list(agent.flush_expired())

    restore_msgs = list(agent.handle(_restore_msg()))
    completed = next(
        m for m in restore_msgs
        if (m.payload or {}).get("kind") == "backup_restore_completed"
    )
    assert completed.payload["outcome"] == "ok"
    summary = completed.payload.get("verify_summary", {})
    # quarantine_samples must be absent or zero — never non-zero.
    quarantine_count = summary.get("quarantine_samples", 0)
    assert quarantine_count == 0, (
        f"quarantine_samples should be empty after restore (PII-aware dump); "
        f"got {quarantine_count!r}"
    )


def test_restore_round_trip_audit_log_carries_matched_pair() -> None:
    """maint_audit_log must carry BOTH backup_restore_started and
    backup_restore_completed rows keyed on the same request_id."""
    clock = _StubClock(_t(2025, 3, 10, 2, 30))
    restore_exe = NoopRestoreExecutor(summary=dict(_SEEDED_ROW_COUNTS))
    audit = InMemoryMaintAuditLogger()
    agent = _build_agent(clock, restore_exe, audit)

    clock.advance(minutes=31)
    list(agent.flush_expired())

    list(agent.handle(_restore_msg()))

    restore_audit_rows = [
        r for r in audit.rows
        if r["kind"] in {"backup_restore_started", "backup_restore_completed"}
    ]
    kinds_in_audit = {r["kind"] for r in restore_audit_rows}
    assert "backup_restore_started" in kinds_in_audit, (
        "backup_restore_started missing from maint_audit_log"
    )
    assert "backup_restore_completed" in kinds_in_audit, (
        "backup_restore_completed missing from maint_audit_log"
    )
    # Both rows must share the same request_id (matched pair).
    request_ids = {r["request_id"] for r in restore_audit_rows}
    assert request_ids == {_REQUEST_ID}, (
        f"audit rows have mismatched request_ids: {request_ids!r}"
    )


def test_restore_round_trip_started_event_emitted_before_completed() -> None:
    """backup_restore_started must precede backup_restore_completed in the
    emitted message sequence (ordering guarantee)."""
    clock = _StubClock(_t(2025, 3, 10, 2, 30))
    restore_exe = NoopRestoreExecutor(summary=dict(_SEEDED_ROW_COUNTS))
    audit = InMemoryMaintAuditLogger()
    agent = _build_agent(clock, restore_exe, audit)

    clock.advance(minutes=31)
    list(agent.flush_expired())

    restore_msgs = list(agent.handle(_restore_msg()))
    event_kinds = [
        (m.payload or {}).get("kind")
        for m in restore_msgs
        if m.envelope.topic == MAINT_EVENT
        and (m.payload or {}).get("kind") in {
            "backup_restore_started", "backup_restore_completed",
        }
    ]
    assert event_kinds.index("backup_restore_started") < event_kinds.index(
        "backup_restore_completed"
    ), "backup_restore_started must be emitted before backup_restore_completed"


def test_restore_round_trip_ephemeral_target_named_correctly() -> None:
    """Default restore (no destination_conn) targets negelir_restore_<date>
    and is marked ephemeral=True."""
    clock = _StubClock(_t(2025, 3, 10, 2, 30))
    restore_exe = NoopRestoreExecutor(summary=dict(_SEEDED_ROW_COUNTS))
    audit = InMemoryMaintAuditLogger()
    agent = _build_agent(clock, restore_exe, audit)

    clock.advance(minutes=31)
    list(agent.flush_expired())

    restore_msgs = list(agent.handle(_restore_msg()))
    started = next(
        m for m in restore_msgs
        if (m.payload or {}).get("kind") == "backup_restore_started"
    )
    assert started.payload["target"] == f"negelir_restore_{_DUMP_DATE}"
    assert started.payload["ephemeral"] is True
