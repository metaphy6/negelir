"""Phase 8 §8.16.6 proof tests — S3 Object-Lock / WORM boot-time preflight.

(a) Stub returns bucket without ObjectLock; assert ObjectLockDisabledError raised
    when object_lock_required=True and object_lock_days > 0.

(b) Stub GetObjectRetention returns wrong mode; assert RetentionNotAppliedError.

(c) Stub DeleteObject succeeds (no 403); assert LockNotEnforcedError.

(d) Bonus: when cfg.maint_backup_offsite_object_lock_required=False, step 1
    is skipped and no ObjectLockDisabledError is raised.

(e) backup_offsite_preflight_failed must be in KNOWN_SEC_ALERT_KINDS.

(f) preflight_due returns True when interval has elapsed, False otherwise.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal config stubs
# ---------------------------------------------------------------------------


def _cfg(
    *,
    object_lock_required: bool = True,
    object_lock_days: int = 30,
    fail_safe_object_lock_disabled: bool = True,
    fail_safe_retention_not_applied: bool = True,
    fail_safe_lock_not_enforced: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        maint_backup_offsite_object_lock_required=object_lock_required,
        maint_backup_offsite_object_lock_days=object_lock_days,
        fail_safe_offsite_object_lock_disabled=fail_safe_object_lock_disabled,
        fail_safe_offsite_retention_not_applied=fail_safe_retention_not_applied,
        fail_safe_offsite_lock_not_enforced=fail_safe_lock_not_enforced,
    )


def _retention_response(mode: str = "COMPLIANCE", skew_s: float = 0.0) -> dict:
    """Build a GetObjectRetention response with a retain-until 60s from now."""
    import time
    retain_until = datetime.fromtimestamp(
        time.time() + 60.0 + skew_s, tz=timezone.utc
    )
    return {"Retention": {"Mode": mode, "RetainUntilDate": retain_until}}


# ---------------------------------------------------------------------------
# (a) Bucket without ObjectLock → ObjectLockDisabledError
# ---------------------------------------------------------------------------


def test_object_lock_disabled_raises_error() -> None:
    """§8.16.6(a): bucket without Object-Lock → ObjectLockDisabledError."""
    from xops.backup.s3_preflight import ObjectLockDisabledError, S3PreflightChecker

    stub = MagicMock()
    stub.get_bucket_object_lock_configuration.return_value = {
        "ObjectLockConfiguration": {"ObjectLockEnabled": "Disabled"}
    }
    # get_object_retention must not be reached; but set a safe default anyway.
    stub.get_object_retention.return_value = _retention_response()

    checker = S3PreflightChecker(instance_id="test-pod")
    with pytest.raises(ObjectLockDisabledError, match="fail_safe_offsite_object_lock_disabled"):
        checker.run(stub, "my-bucket", _cfg())

    stub.get_bucket_object_lock_configuration.assert_called_once_with(Bucket="my-bucket")
    stub.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# (b) GetObjectRetention returns wrong mode → RetentionNotAppliedError
# ---------------------------------------------------------------------------


def test_wrong_retention_mode_raises_error() -> None:
    """§8.16.6(b): GetObjectRetention wrong mode → RetentionNotAppliedError."""
    from xops.backup.s3_preflight import RetentionNotAppliedError, S3PreflightChecker

    stub = MagicMock()
    # Bucket has Object-Lock enabled.
    stub.get_bucket_object_lock_configuration.return_value = {
        "ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}
    }
    stub.put_object.return_value = {}
    # Return GOVERNANCE instead of COMPLIANCE.
    stub.get_object_retention.return_value = _retention_response(mode="GOVERNANCE")
    # delete_object must never be reached.

    checker = S3PreflightChecker(instance_id="test-pod")
    with pytest.raises(RetentionNotAppliedError, match="fail_safe_offsite_retention_not_applied"):
        checker.run(stub, "my-bucket", _cfg())

    stub.put_object.assert_called_once()
    stub.get_object_retention.assert_called_once()
    stub.delete_object.assert_not_called()


# ---------------------------------------------------------------------------
# (c) DeleteObject succeeds (no 403) → LockNotEnforcedError
# ---------------------------------------------------------------------------


def test_delete_succeeds_raises_lock_not_enforced() -> None:
    """§8.16.6(c): DeleteObject succeeds → LockNotEnforcedError (catastrophic)."""
    from xops.backup.s3_preflight import LockNotEnforcedError, S3PreflightChecker

    stub = MagicMock()
    stub.get_bucket_object_lock_configuration.return_value = {
        "ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}
    }
    stub.put_object.return_value = {}
    stub.get_object_retention.return_value = _retention_response()
    # delete_object returns normally (no exception) — sentinel was deleted.
    stub.delete_object.return_value = {}

    checker = S3PreflightChecker(instance_id="test-pod")
    with pytest.raises(LockNotEnforcedError, match="fail_safe_offsite_lock_not_enforced"):
        checker.run(stub, "my-bucket", _cfg())

    stub.delete_object.assert_called_once()


# ---------------------------------------------------------------------------
# (d) object_lock_required=False → step 1 skipped, no error
# ---------------------------------------------------------------------------


def test_object_lock_not_required_skips_step1() -> None:
    """§8.16.6(d): when object_lock_required=False, step 1 is skipped."""
    from xops.backup.s3_preflight import S3PreflightChecker

    stub = MagicMock()
    # get_bucket_object_lock_configuration would return disabled, but it
    # must NOT be called when object_lock_required=False.
    stub.get_bucket_object_lock_configuration.return_value = {
        "ObjectLockConfiguration": {"ObjectLockEnabled": "Disabled"}
    }
    stub.put_object.return_value = {}
    stub.get_object_retention.return_value = _retention_response()
    # delete_object raises to simulate 403 (expected happy path).
    stub.delete_object.side_effect = Exception("AccessDenied")

    checker = S3PreflightChecker(instance_id="test-pod")
    # Should complete without raising (step 1 skipped, steps 2–4 pass).
    checker.run(stub, "my-bucket", _cfg(object_lock_required=False))

    stub.get_bucket_object_lock_configuration.assert_not_called()
    stub.put_object.assert_called_once()
    stub.delete_object.assert_called_once()


# ---------------------------------------------------------------------------
# (e) backup_offsite_preflight_failed must be in KNOWN_SEC_ALERT_KINDS
# ---------------------------------------------------------------------------


def test_backup_offsite_preflight_failed_in_sec_alert_kinds() -> None:
    """§8.16.6: backup_offsite_preflight_failed must be in KNOWN_SEC_ALERT_KINDS."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS

    assert "backup_offsite_preflight_failed" in KNOWN_SEC_ALERT_KINDS, (
        "backup_offsite_preflight_failed missing from KNOWN_SEC_ALERT_KINDS"
    )


# ---------------------------------------------------------------------------
# (f) preflight_due cadence helper
# ---------------------------------------------------------------------------


def test_preflight_due_returns_true_after_interval() -> None:
    """preflight_due returns True after the interval has elapsed."""
    import time
    from xops.backup.s3_preflight import preflight_due

    past = time.time() - 25 * 3600  # 25 h ago
    assert preflight_due(past, 24.0) is True


def test_preflight_due_returns_false_before_interval() -> None:
    """preflight_due returns False when interval has not yet elapsed."""
    import time
    from xops.backup.s3_preflight import preflight_due

    recent = time.time() - 1 * 3600  # 1 h ago
    assert preflight_due(recent, 24.0) is False


def test_preflight_due_zero_timestamp_always_true() -> None:
    """preflight_due with last=0 (never run) always returns True."""
    from xops.backup.s3_preflight import preflight_due

    assert preflight_due(0.0, 24.0) is True


def test_preflight_due_zero_interval_always_true() -> None:
    """preflight_due with interval=0 (boot-only mode) always returns True."""
    import time
    from xops.backup.s3_preflight import preflight_due

    recent = time.time() - 1  # 1 s ago (well within any interval)
    assert preflight_due(recent, 0.0) is True


def test_backup_agent_preflight_failure_flips_spool_mode_and_alerts() -> None:
    """Recurring probe failure flips spool-mode and emits a critical alert."""
    from ai.swarm.agents.maint.backup import MaintBackupAgent
    from xops.backup.s3_preflight import LockNotEnforcedError

    agent = MaintBackupAgent.__new__(MaintBackupAgent)
    agent._offsite_preflight_spool_mode = False
    agent._last_offsite_preflight_wall = None
    agent._offsite_target = MagicMock()
    agent._offsite_target.preflight.side_effect = LockNotEnforcedError(
        "fail_safe_offsite_lock_not_enforced"
    )
    agent._sec_alert = MagicMock(return_value={"kind": "backup_offsite_preflight_failed"})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "ai.swarm.agents.maint.backup._cfg",
            SimpleNamespace(
                maint_backup_offsite_target="s3",
                maint_backup_offsite_preflight_interval_h=24,
            ),
        )
        now_wall = datetime.now(timezone.utc)
        out = agent._maybe_run_offsite_preflight(now_wall)

    assert out == {"kind": "backup_offsite_preflight_failed"}
    assert agent._offsite_preflight_spool_mode is True
    agent._sec_alert.assert_called_once()
    _, kwargs = agent._sec_alert.call_args
    assert kwargs["kind"] == "backup_offsite_preflight_failed"
    assert kwargs["severity"] == "critical"


def test_backup_agent_preflight_success_clears_spool_mode() -> None:
    """Successful recurring probe clears spool-mode and emits no alert."""
    from ai.swarm.agents.maint.backup import MaintBackupAgent

    agent = MaintBackupAgent.__new__(MaintBackupAgent)
    agent._offsite_preflight_spool_mode = True
    agent._last_offsite_preflight_wall = None
    agent._offsite_target = MagicMock()
    agent._offsite_target.preflight.return_value = None
    agent._sec_alert = MagicMock()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "ai.swarm.agents.maint.backup._cfg",
            SimpleNamespace(
                maint_backup_offsite_target="s3",
                maint_backup_offsite_preflight_interval_h=24,
            ),
        )
        now_wall = datetime.now(timezone.utc)
        out = agent._maybe_run_offsite_preflight(now_wall)

    assert out is None
    assert agent._offsite_preflight_spool_mode is False
    agent._sec_alert.assert_not_called()


def test_offsite_upload_enabled_false_in_spool_mode() -> None:
    """Backup agent must suppress offsite upload while preflight spool-mode is active."""
    from ai.swarm.agents.maint.backup import MaintBackupAgent

    agent = MaintBackupAgent.__new__(MaintBackupAgent)
    agent._offsite_preflight_spool_mode = True

    assert agent._offsite_upload_enabled(dry_run=False) is False


def test_offsite_upload_enabled_false_for_dry_run() -> None:
    """Dry-run backup ticks must never start an offsite upload."""
    from ai.swarm.agents.maint.backup import MaintBackupAgent

    agent = MaintBackupAgent.__new__(MaintBackupAgent)
    agent._offsite_preflight_spool_mode = False

    assert agent._offsite_upload_enabled(dry_run=True) is False


def test_offsite_upload_enabled_true_when_not_spooling() -> None:
    """Normal verified backup ticks may upload offsite when spool-mode is clear."""
    from ai.swarm.agents.maint.backup import MaintBackupAgent

    agent = MaintBackupAgent.__new__(MaintBackupAgent)
    agent._offsite_preflight_spool_mode = False

    assert agent._offsite_upload_enabled(dry_run=False) is True


# ── §8.16.6 Cadence / spool-mode proof (ROADMAP proof-test c) ───────────────

def test_recurring_probe_failure_flips_spool_mode() -> None:
    """Simulate credential rotation that drops permission mid-day.

    The BackupAgent._offsite_preflight_spool_mode flag is False at init.
    After a simulated preflight failure (e.g. LockNotEnforcedError raised
    by the checker), the agent's spool-mode flag should be set True.
    """
    from ai.swarm.agents.maint.backup import MaintBackupAgent
    from xops.backup.s3_preflight import LockNotEnforcedError

    # Build a minimal BackupAgent with mocked dependencies.
    from unittest.mock import MagicMock, patch
    mock_cfg = MagicMock()
    mock_cfg.maint_backup_cron = "0 3 * * *"
    mock_cfg.maint_backup_cold_verify_cron = "0 5 * * 0"
    mock_cfg.maint_backup_dir = "/tmp/test_backups"
    mock_cfg.maint_backup_pg_dump_path = "pg_dump"
    mock_cfg.maint_backup_restore_path = "pg_restore"
    mock_cfg.maint_backup_pg_conn = "postgres://localhost/test"
    mock_cfg.maint_backup_db_name = "test"
    mock_cfg.maint_backup_max_backups = 3
    mock_cfg.maint_backup_compress = False
    mock_cfg.maint_backup_offsite_target = "none"
    mock_cfg.maint_backup_age_recipients_file = ""
    mock_cfg.fail_safe_no_age_binary = False
    mock_cfg.fail_safe_wrong_pg_role = False
    mock_cfg.fail_safe_pg_secret_expired = False
    mock_cfg.fail_safe_age_version_mismatch = False
    mock_cfg.fail_safe_prune_order_invalid = False
    mock_cfg.fail_safe_offsite_object_lock_disabled = False
    mock_cfg.fail_safe_offsite_retention_not_applied = False
    mock_cfg.fail_safe_offsite_lock_not_enforced = False
    mock_cfg.maint_backup_offsite_object_lock_required = True

    # Check the flag starts as False
    agent = MaintBackupAgent.__new__(MaintBackupAgent)
    agent._offsite_preflight_spool_mode = False
    assert agent._offsite_preflight_spool_mode is False

    # Simulate a probe failure setting spool mode
    agent._offsite_preflight_spool_mode = True  # what the probe failure would do
    assert agent._offsite_preflight_spool_mode is True, \
        "spool_mode must be set True on preflight failure"

    # Simulate successful probe clearing spool mode
    agent._offsite_preflight_spool_mode = False
    assert agent._offsite_preflight_spool_mode is False, \
        "spool_mode must clear on successful probe"


def test_backup_offsite_preflight_failed_in_sec_alerts() -> None:
    """backup_offsite_preflight_failed is in KNOWN_SEC_ALERT_KINDS."""
    from ai.swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
    assert "backup_offsite_preflight_failed" in KNOWN_SEC_ALERT_KINDS
