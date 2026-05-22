"""Phase 8 §8.16.3 — proof tests: prune-order doctrine + state machine.

Three mandatory proof cases:

(a) ``PruneOrderViolation`` — synthesize an FK map that violates
    PRUNE_ORDER (e.g. ``opsctl_audit`` FK-references ``maint_audit_log``,
    but ``opsctl_audit`` is pruned BEFORE ``maint_audit_log`` which means
    ``opsctl_audit`` references a table that outlives it during the prune
    window).  Assert that :class:`PruneOrderValidator` raises
    :class:`PruneOrderViolation` (the ``fail_safe_prune_order_invalid``
    condition).

(b) State machine: simulate dump failure.  Assert prune phase never
    enters; verify the event chain is:
    ``backup_started → backup_completed(verified=False) → prune_skipped(reason="dump_failed")``.

(c) ``--prune-only`` is forbidden: assert that calling
    :meth:`BackupStateMachine.prune_only` raises
    :class:`PruneOnlyForbiddenError` (maps to exit code
    ``PRUNE_ONLY_FORBIDDEN = 10``).
"""
from __future__ import annotations

import pytest

from xops.maint.prune_order import (
    PRUNE_ORDER,
    PruneOrderValidator,
    PruneOrderViolation,
)
from xops.maint.backup_state_machine import (
    BackupPhase,
    BackupStateMachine,
    BackupStateMachineError,
    PruneOnlyForbiddenError,
)
from xops.opsctl._exit_codes import ExitCode


# ── (a) PruneOrderViolation ──────────────────────────────────────────────────


class TestPruneOrderValidator:
    """PruneOrderValidator proof tests (fail_safe_prune_order_invalid)."""

    def test_valid_fk_map_passes(self) -> None:
        """A FK map consistent with PRUNE_ORDER must not raise."""
        # opsctl_audit FK-references maint_audit_log (opsctl_audit is idx=0,
        # maint_audit_log is idx=5 — opsctl_audit pruned first, fine).
        fk_map = {
            "opsctl_audit": ["maint_audit_log"],
            "pattern_allowlist": ["maint_audit_log"],
            "quarantine_samples": ["maint_audit_log"],
        }
        validator = PruneOrderValidator()
        validator.validate_from_schema_dict(fk_map)  # must not raise

    def test_violation_opsctl_audit_references_maint_audit_log_reversed(
        self,
    ) -> None:
        """PRUNE_ORDER violation: maint_audit_log FK-references opsctl_audit.

        ``maint_audit_log`` is pruned LAST (idx=5).  If it held an FK
        pointing at ``opsctl_audit`` (idx=0 — pruned first), pruning
        ``opsctl_audit`` while ``maint_audit_log`` rows still reference it
        would cause a FK violation.  Validator must catch this.
        """
        fk_map = {
            # maint_audit_log (idx=5) FK-references opsctl_audit (idx=0).
            # maint_audit_log is pruned AFTER opsctl_audit →
            # maint_audit_log must be pruned BEFORE opsctl_audit, not after.
            "maint_audit_log": ["opsctl_audit"],
        }
        validator = PruneOrderValidator()
        with pytest.raises(PruneOrderViolation, match="prune-order violation"):
            validator.validate_from_schema_dict(fk_map)

    def test_violation_table_missing_from_prune_order(self) -> None:
        """A table in the FK map but absent from PRUNE_ORDER raises."""
        fk_map = {
            "unknown_table": ["maint_audit_log"],
        }
        validator = PruneOrderValidator()
        with pytest.raises(PruneOrderViolation):
            validator.validate_from_schema_dict(fk_map)

    def test_violation_referenced_table_not_in_prune_order(self) -> None:
        """A table referenced in an FK but absent from PRUNE_ORDER raises."""
        fk_map = {
            "opsctl_audit": ["nonexistent_table"],
        }
        validator = PruneOrderValidator()
        with pytest.raises(PruneOrderViolation):
            validator.validate_from_schema_dict(fk_map)

    def test_prune_order_violation_is_prune_order_error(self) -> None:
        """PruneOrderViolation is the same class as PruneOrderError."""
        from xops.maint.prune_order import PruneOrderError
        assert PruneOrderViolation is PruneOrderError

    def test_empty_fk_map_passes(self) -> None:
        """An empty FK map (no FK constraints) is trivially valid."""
        validator = PruneOrderValidator()
        validator.validate_from_schema_dict({})  # must not raise


# ── (b) BackupStateMachine — dump failure blocks prune ───────────────────────


class TestBackupStateMachineDumpFailure:
    """State machine: dump failure must block the prune phase."""

    def test_dump_failure_prune_never_entered(self) -> None:
        """After dump_complete(verified=False) the machine is IDLE, not PRUNE."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=False)
        assert sm.phase is BackupPhase.IDLE

    def test_dump_failure_event_chain(self) -> None:
        """Event chain: backup_started → backup_completed → prune_skipped."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=False)

        kinds = [e["kind"] for e in sm.events]
        assert kinds == ["backup_started", "backup_completed", "prune_skipped"]

    def test_dump_failure_backup_completed_verified_false(self) -> None:
        """backup_completed event carries verified=False after dump failure."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=False)

        completed = next(e for e in sm.events if e["kind"] == "backup_completed")
        assert completed["verified"] is False

    def test_dump_failure_prune_skipped_reason_dump_failed(self) -> None:
        """prune_skipped event carries reason='dump_failed' after dump failure."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=False)

        skipped = next(e for e in sm.events if e["kind"] == "prune_skipped")
        assert skipped["reason"] == "dump_failed"

    def test_successful_dump_enters_prune(self) -> None:
        """After dump_complete(verified=True) the machine enters PRUNE."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=True)
        assert sm.phase is BackupPhase.PRUNE

    def test_successful_dump_event_chain(self) -> None:
        """Successful dump: backup_started → backup_completed → prune_started."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=True)

        kinds = [e["kind"] for e in sm.events]
        assert kinds == ["backup_started", "backup_completed", "prune_started"]

    def test_full_happy_path_event_chain(self) -> None:
        """Full cycle: backup_started → backup_completed → prune_started → prune_completed."""
        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=True)
        sm.prune_complete()

        kinds = [e["kind"] for e in sm.events]
        assert kinds == [
            "backup_started",
            "backup_completed",
            "prune_started",
            "prune_completed",
        ]
        assert sm.phase is BackupPhase.IDLE

    def test_skip_prune_flag_skips_prune_on_success(self) -> None:
        """skip_prune=True: even a verified dump does not enter PRUNE."""
        sm = BackupStateMachine(skip_prune=True)
        sm.start_dump()
        sm.dump_complete(verified=True)
        assert sm.phase is BackupPhase.IDLE
        skipped = next(e for e in sm.events if e["kind"] == "prune_skipped")
        assert skipped["reason"] == "skip_prune_flag"

    def test_invalid_transition_raises(self) -> None:
        """Calling prune_complete in IDLE phase raises BackupStateMachineError."""
        sm = BackupStateMachine()
        with pytest.raises(BackupStateMachineError, match="prune_complete"):
            sm.prune_complete()

    def test_double_start_dump_raises(self) -> None:
        """Calling start_dump twice raises BackupStateMachineError."""
        sm = BackupStateMachine()
        sm.start_dump()
        with pytest.raises(BackupStateMachineError, match="start_dump"):
            sm.start_dump()


# ── (c) --prune-only is FORBIDDEN ────────────────────────────────────────────


class TestPruneOnlyForbidden:
    """--prune-only is unconditionally forbidden (exit code 10)."""

    def test_prune_only_raises_error(self) -> None:
        """BackupStateMachine.prune_only() raises PruneOnlyForbiddenError."""
        with pytest.raises(PruneOnlyForbiddenError):
            BackupStateMachine.prune_only()

    def test_prune_only_exit_code(self) -> None:
        """Exit code PRUNE_ONLY_FORBIDDEN is 10."""
        assert ExitCode.PRUNE_ONLY_FORBIDDEN == 10

    def test_prune_only_error_message_contains_doctrine_name(self) -> None:
        """PruneOnlyForbiddenError message references the doctrine name."""
        with pytest.raises(PruneOnlyForbiddenError, match="PRUNE_ONLY_FORBIDDEN"):
            BackupStateMachine.prune_only()

    def test_prune_only_is_runtime_error(self) -> None:
        """PruneOnlyForbiddenError is a RuntimeError."""
        assert issubclass(PruneOnlyForbiddenError, RuntimeError)


# ── PruneMetrics tests (Bullet 4 coverage) ──────────────────────────────────
from unittest.mock import MagicMock, patch

from xops.maint.prune_metrics import PruneMetrics


class TestPruneMetricsHappyPath:
    """PruneMetrics happy path: mocked Redis receives expected stream entries."""

    def test_record_prune_seconds_emits_xadd(self) -> None:
        mock_redis = MagicMock()
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = mock_redis
        m._max_stream_len = 1000
        m.record_prune_seconds(table="opsctl_audit", outcome="ok", elapsed_s=0.5)
        assert mock_redis.xadd.call_count == 1
        _, kwargs = mock_redis.xadd.call_args
        entry = mock_redis.xadd.call_args[0][1]
        assert entry["table"] == "opsctl_audit"
        assert entry["outcome"] == "ok"

    def test_record_prune_rows_emits_xadd(self) -> None:
        mock_redis = MagicMock()
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = mock_redis
        m._max_stream_len = 1000
        m.record_prune_rows(table="quarantine_samples", rows=42)
        assert mock_redis.xadd.call_count == 1
        entry = mock_redis.xadd.call_args[0][1]
        assert entry["table"] == "quarantine_samples"
        assert entry["rows"] == "42"

    def test_enabled_true_when_redis_connected(self) -> None:
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = MagicMock()
        assert m.enabled is True


class TestPruneMetricsRedisUnavailable:
    """PruneMetrics degrades gracefully when Redis is unavailable."""

    def test_init_redis_unavailable_sets_redis_none(self) -> None:
        """Constructor sets _redis=None and does not raise when Redis is down."""
        # Pass a mock config object with an unreachable host/port
        mock_cfg = MagicMock()
        mock_cfg.redis_host = "127.0.0.1"
        mock_cfg.redis_port = 9999  # nothing listening here
        mock_cfg.telemetry_max_stream_len = 1000
        mock_cfg.redis_socket_timeout = 1
        m = PruneMetrics(config=mock_cfg)
        assert m._redis is None

    def test_enabled_false_when_redis_unavailable(self) -> None:
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = None
        assert m.enabled is False

    def test_record_prune_seconds_noop_when_disabled(self) -> None:
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = None
        # Must not raise
        m.record_prune_seconds(table="maint_audit_log", outcome="ok", elapsed_s=1.0)

    def test_record_prune_rows_noop_when_disabled(self) -> None:
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = None
        m.record_prune_rows(table="maint_audit_log", rows=0)

    def test_record_prune_seconds_redis_error_is_swallowed(self) -> None:
        """xadd failure during recording must not propagate."""
        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = RuntimeError("connection reset")
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = mock_redis
        m._max_stream_len = 1000
        # Must not raise
        m.record_prune_seconds(table="dlq_entries", outcome="error", elapsed_s=0.1)

    def test_record_prune_rows_redis_error_is_swallowed(self) -> None:
        """xadd failure during record_prune_rows must not propagate."""
        mock_redis = MagicMock()
        mock_redis.xadd.side_effect = RuntimeError("connection reset")
        m = PruneMetrics.__new__(PruneMetrics)
        m._redis = mock_redis
        m._max_stream_len = 1000
        # Must not raise
        m.record_prune_rows(table="maint_audit_log", rows=5)
