"""Phase 8 §8.9 — Backup TTL prune batched-transaction lock-hold-time test.

What this asserts (binding):

* ``BatchedPrunerStorage.prune()`` issues DELETE batches of at most
  ``batch_size`` rows each.
* No single batch's simulated lock hold time (rows × ms_per_row) exceeds
  ``max_lock_ms`` (cfg.maint_backup_prune_max_lock_ms default 500 ms).
* ``BatchLockBudgetExceeded`` is raised before any mutation when a batch
  *would* breach the budget, so the caller can shrink the batch_size.
* The agent-level plumbing: when ``BatchedPrunerStorage`` is wired into
  ``MaintBackupAgent``, the full cron tick still emits
  ``prune_started`` / ``prune_completed`` and all batch constraints are
  respected end-to-end.
* Config key ``maint_backup_prune_max_lock_ms`` is present with a
  default of 500 and the triangle-test validates its bounds.
"""
from __future__ import annotations

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    BatchedPrunerStorage,
    BatchLockBudgetExceeded,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)

# ── Unit: BatchedPrunerStorage ──────────────────────────────────────────


def test_batched_prune_honours_batch_size() -> None:
    """All batches must have row count ≤ batch_size."""
    pruner = BatchedPrunerStorage(
        counts={"maint_audit_log": 1_000},
        batch_size=300,
        ms_per_row=0.0,
        max_lock_ms=500.0,
    )
    result = pruner.prune(dry_run=False)
    assert result["maint_audit_log"] == 1_000
    batch_sizes = [rows for (_, rows, _) in pruner.batches]
    assert all(rows <= 300 for rows in batch_sizes), (
        f"batch(es) exceed batch_size=300: {batch_sizes}"
    )
    # 1000 / 300 = 3 full batches + 1 remainder
    assert len(pruner.batches) == 4
    assert sum(batch_sizes) == 1_000


def test_batched_prune_lock_hold_time_within_budget() -> None:
    """Simulated lock hold per batch stays ≤ max_lock_ms (500 ms default)."""
    # 10k rows total; batch_size=200; each row costs 2 ms/row →
    # 200 × 2 = 400 ms per batch < 500 ms budget.  50 batches.
    pruner = BatchedPrunerStorage(
        counts={"opsctl_audit": 10_000},
        batch_size=200,
        ms_per_row=2.0,
        max_lock_ms=500.0,
    )
    result = pruner.prune(dry_run=False)
    assert result["opsctl_audit"] == 10_000
    for table, rows, elapsed_ms in pruner.batches:
        assert rows <= 200, f"batch exceeds batch_size: {rows}"
        assert elapsed_ms <= 500.0, (
            f"{table}: batch held lock for {elapsed_ms:.1f} ms > 500 ms budget"
        )
    assert len(pruner.batches) == 50


def test_batched_prune_raises_before_mutation_on_budget_breach() -> None:
    """BatchLockBudgetExceeded must be raised BEFORE any mutation."""
    pruner = BatchedPrunerStorage(
        counts={"maint_audit_log": 100},
        batch_size=100,
        ms_per_row=6.0,      # 100 × 6 = 600 ms > 500 ms budget
        max_lock_ms=500.0,
    )
    with pytest.raises(BatchLockBudgetExceeded) as exc_info:
        pruner.prune(dry_run=False)
    err = exc_info.value
    assert err.table == "maint_audit_log"
    assert err.batch_rows == 100
    assert err.simulated_ms == pytest.approx(600.0)
    assert err.max_lock_ms == 500.0
    # No mutation: counts should be unchanged because we raised pre-apply.
    assert pruner.counts == {"maint_audit_log": 100}
    assert pruner.batches == []


def test_batched_prune_dry_run_validates_but_does_not_mutate() -> None:
    """dry_run=True validates batch constraints but leaves counts intact."""
    pruner = BatchedPrunerStorage(
        counts={"schema_snapshots": 500},
        batch_size=250,
        ms_per_row=1.0,
        max_lock_ms=500.0,
    )
    result = pruner.prune(dry_run=True)
    # Returns the same totals as a real run would.
    assert result["schema_snapshots"] == 500
    # Counts are NOT cleared on dry_run.
    assert pruner.counts == {"schema_snapshots": 500}
    # Batches are recorded (for inspection).
    assert len(pruner.batches) == 2
    assert all(rows <= 250 for (_, rows, _) in pruner.batches)


def test_batched_prune_dry_run_raises_on_budget_breach() -> None:
    """dry_run=True also raises on budget breach (pre-flight check)."""
    pruner = BatchedPrunerStorage(
        counts={"opsctl_audit": 50},
        batch_size=50,
        ms_per_row=11.0,    # 50 × 11 = 550 ms > 500 ms
        max_lock_ms=500.0,
    )
    with pytest.raises(BatchLockBudgetExceeded):
        pruner.prune(dry_run=True)
    # Counts intact because raise was pre-mutation.
    assert pruner.counts["opsctl_audit"] == 50


def test_batched_prune_empty_table_is_noop() -> None:
    pruner = BatchedPrunerStorage(counts={}, batch_size=100, ms_per_row=0.0, max_lock_ms=500.0)
    assert pruner.prune(dry_run=False) == {}
    assert pruner.batches == []


def test_batched_prune_zero_row_table_skipped() -> None:
    pruner = BatchedPrunerStorage(
        counts={"maint_audit_log": 0},
        batch_size=100,
        ms_per_row=5.0,
        max_lock_ms=500.0,
    )
    result = pruner.prune(dry_run=False)
    assert result["maint_audit_log"] == 0
    assert pruner.batches == []


def test_batched_prune_multi_table_all_batches_within_budget() -> None:
    """Multiple tables — every batch across all tables respects budget."""
    pruner = BatchedPrunerStorage(
        counts={"maint_audit_log": 1_500, "schema_snapshots": 800},
        batch_size=400,
        ms_per_row=1.2,    # 400 × 1.2 = 480 ms < 500 ms budget
        max_lock_ms=500.0,
    )
    result = pruner.prune(dry_run=False)
    assert result["maint_audit_log"] == 1_500
    assert result["schema_snapshots"] == 800
    for table, rows, elapsed_ms in pruner.batches:
        assert rows <= 400, f"{table}: batch {rows} > batch_size"
        assert elapsed_ms <= 500.0, f"{table}: lock held {elapsed_ms:.1f} ms"
    # 1500 → 4 batches (400+400+400+300); 800 → 2 batches (400+400)
    assert len(pruner.batches) == 6


# ── Config contract ─────────────────────────────────────────────────────


def test_cfg_has_maint_backup_prune_max_lock_ms_default_500() -> None:
    """cfg.maint_backup_prune_max_lock_ms must default to 500.

    We test the coded default by instantiating a fresh Config() directly
    (no env var set) rather than reloading the module, so this test has
    zero side-effects on the shared singleton.
    """
    import os

    from common.config import Config  # type: ignore[attr-defined]
    old = os.environ.pop("NEGELIR_MAINT_BACKUP_PRUNE_MAX_LOCK_MS", None)
    try:
        fresh = Config()
        assert fresh.maint_backup_prune_max_lock_ms == 500
    finally:
        if old is not None:
            os.environ["NEGELIR_MAINT_BACKUP_PRUNE_MAX_LOCK_MS"] = old


def test_cfg_maint_backup_prune_max_lock_ms_is_bounded() -> None:
    """validate(strict=True) must reject 0 for maint_backup_prune_max_lock_ms.

    We mutate a fresh Config() instance in-place rather than reloading
    the module, to avoid polluting the global singleton and other tests.
    """
    from common.config import Config  # type: ignore[attr-defined]
    fresh = Config()
    # Force an out-of-range value on the fresh instance.
    object.__setattr__(fresh, "maint_backup_prune_max_lock_ms", 0)
    with pytest.raises(ValueError, match="maint_backup_prune_max_lock_ms"):
        fresh.validate(strict=True)


# ── Agent-level integration ─────────────────────────────────────────────


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0):
    from datetime import datetime, timezone
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class _StubClock:
    def __init__(self, start) -> None:
        self.now = start

    def wall(self):
        return self.now

    def mono_ns(self) -> int:
        return int(self.now.timestamp() * 1e9)

    def set(self, when) -> None:
        self.now = when


def _build_agent_with_batched_pruner(
    *,
    clock: _StubClock,
    pruner: BatchedPrunerStorage,
) -> MaintBackupAgent:
    prior = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = "/nonexistent/negelir_test_backup"  # type: ignore[attr-defined]
    try:
        return MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=NoopVerifier(),
            pruner=pruner,
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3, last_dump_bytes=0),
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "batched-test-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = prior  # type: ignore[attr-defined]


def test_agent_cron_tick_with_batched_pruner_emits_prune_events() -> None:
    """Agent wired with BatchedPrunerStorage still emits prune_started/completed."""
    pruner = BatchedPrunerStorage(
        counts={"maint_audit_log": 1_000, "schema_snapshots": 500},
        batch_size=300,
        ms_per_row=0.0,
        max_lock_ms=500.0,
    )
    clock = _StubClock(_t(2025, 6, 1, 2, 30))
    agent = _build_agent_with_batched_pruner(clock=clock, pruner=pruner)
    list(agent.flush_expired())  # arm

    clock.set(_t(2025, 6, 1, 3, 0))
    msgs = list(agent.flush_expired())
    kinds = [(m.payload or {}).get("kind") for m in msgs]

    assert "prune_started" in kinds
    assert "prune_completed" in kinds
    # BatchedPrunerStorage was called — batches recorded.
    assert len(pruner.batches) > 0
    # Every batch respects batch_size.
    assert all(rows <= 300 for (_, rows, _) in pruner.batches)


def test_agent_cron_tick_with_batched_pruner_all_rows_deleted() -> None:
    """All rows across tables are accounted for in prune_completed event."""
    pruner = BatchedPrunerStorage(
        counts={"maint_audit_log": 600, "opsctl_audit": 400},
        batch_size=200,
        ms_per_row=0.0,
        max_lock_ms=500.0,
    )
    clock = _StubClock(_t(2025, 7, 1, 2, 30))
    agent = _build_agent_with_batched_pruner(clock=clock, pruner=pruner)
    list(agent.flush_expired())

    clock.set(_t(2025, 7, 1, 3, 0))
    msgs = list(agent.flush_expired())

    prune_completed = next(
        m for m in msgs if (m.payload or {}).get("kind") == "prune_completed"
    )
    dpt = prune_completed.payload["deleted_per_table"]
    assert dpt.get("maint_audit_log", 0) == 600
    assert dpt.get("opsctl_audit", 0) == 400
