"""Phase 8 §8.16.5 proof tests — multipart upload-id TTL + lifecycle assertion.

(a) Stub list_parts to raise NoSuchUploadError; assert resume deletes state file
    + emits backup_offsite_upload_id_expired event.

(b) State file mtime older than max_age_h; assert restart-from-scratch without
    calling list_parts.

(c) check_bucket_lifecycle with DaysAfterInitiation=1 + min_days=2; assert
    returns False (caller should alert).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state(tmp_path: Path, upload_id: str = "test-uid-123") -> Path:
    state = {
        "upload_id": upload_id,
        "dump_date": "2026-05-22",
        "bucket": "test-bucket",
        "key": "backups/dump.tar.gz",
    }
    p = tmp_path / ".offsite_state.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# (a) NoSuchUpload → restart + audit event emitted
# ---------------------------------------------------------------------------


def test_no_such_upload_restarts_and_emits_event(tmp_path: Path) -> None:
    """Stub list_parts to raise NoSuchUploadError; assert resume deletes state
    file + emits backup_offsite_upload_id_expired audit event."""
    from xops.backup.multipart_resume import (
        MultipartResumeManager,
        NoSuchUploadError,
    )

    state_path = _write_state(tmp_path, upload_id="stale-uid-001")
    assert state_path.exists()

    # Build a stub S3 client whose list_parts raises NoSuchUploadError.
    stub_s3 = MagicMock()
    stub_s3.list_parts.side_effect = NoSuchUploadError("NoSuchUpload")

    emitted: list[dict] = []

    mgr = MultipartResumeManager()
    with patch.object(mgr, "_emit_expired_event", side_effect=lambda **kw: emitted.append(kw)):
        result = mgr.resume_or_restart(
            state_path=state_path,
            s3_client=stub_s3,
            bucket="test-bucket",
            key="backups/dump.tar.gz",
        )

    # resume should be False (restart from scratch)
    assert result.should_resume is False
    assert result.upload_id is None
    assert result.reason == "no_such_upload"

    # state file must be gone
    assert not state_path.exists(), "state file was not deleted after NoSuchUpload"

    # audit event must have been emitted
    assert len(emitted) == 1, f"expected 1 audit event, got {len(emitted)}"
    evt = emitted[0]
    assert evt["reason"] == "no_such_upload"
    assert evt["upload_id"] == "stale-uid-001"
    assert evt["bucket"] == "test-bucket"

    # list_parts was called (probe happened before NoSuchUpload path)
    stub_s3.list_parts.assert_called_once()


# ---------------------------------------------------------------------------
# (b) Stale mtime → restart without probing
# ---------------------------------------------------------------------------


def test_stale_state_file_restarts_without_probe(tmp_path: Path) -> None:
    """State file mtime older than max_age_h; assert restart without calling
    list_parts at all."""
    from xops.backup.multipart_resume import MultipartResumeManager

    state_path = _write_state(tmp_path, upload_id="stale-uid-002")

    # Force mtime to 20 hours ago (default max_age_h = 18).
    past_mtime = time.time() - (20 * 3600)
    import os
    os.utime(state_path, (past_mtime, past_mtime))

    stub_s3 = MagicMock()

    emitted: list[dict] = []
    mgr = MultipartResumeManager()

    with patch("common.config.cfg") as mock_cfg:
        mock_cfg.maint_backup_offsite_state_max_age_h = 18
        with patch.object(mgr, "_emit_expired_event", side_effect=lambda **kw: emitted.append(kw)):
            result = mgr.resume_or_restart(
                state_path=state_path,
                s3_client=stub_s3,
                bucket="test-bucket",
                key="backups/dump.tar.gz",
            )

    # restart from scratch
    assert result.should_resume is False
    assert result.reason == "state_file_stale"

    # state file deleted
    assert not state_path.exists()

    # list_parts must NOT have been called (staleness short-circuits probe)
    stub_s3.list_parts.assert_not_called()

    # audit event emitted with correct reason
    assert len(emitted) == 1
    assert emitted[0]["reason"] == "state_file_stale"


# ---------------------------------------------------------------------------
# (c) check_bucket_lifecycle — too-aggressive lifecycle → False
# ---------------------------------------------------------------------------


def test_check_bucket_lifecycle_too_aggressive() -> None:
    """check_bucket_lifecycle with DaysAfterInitiation=1, min_days=2 returns False."""
    from xops.backup.multipart_resume import check_bucket_lifecycle

    stub_s3 = MagicMock()
    stub_s3.get_bucket_lifecycle_configuration.return_value = {
        "Rules": [
            {
                "Status": "Enabled",
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
            }
        ]
    }

    result = check_bucket_lifecycle(stub_s3, bucket="my-bucket", min_days=2)

    assert result is False, (
        "check_bucket_lifecycle must return False when DaysAfterInitiation < min_days"
    )
    stub_s3.get_bucket_lifecycle_configuration.assert_called_once_with(Bucket="my-bucket")


def test_check_bucket_lifecycle_acceptable() -> None:
    """DaysAfterInitiation=7 with min_days=2 → True (safe)."""
    from xops.backup.multipart_resume import check_bucket_lifecycle

    stub_s3 = MagicMock()
    stub_s3.get_bucket_lifecycle_configuration.return_value = {
        "Rules": [
            {
                "Status": "Enabled",
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
            }
        ]
    }

    result = check_bucket_lifecycle(stub_s3, bucket="my-bucket", min_days=2)
    assert result is True


def test_check_bucket_lifecycle_no_rule_returns_true() -> None:
    """No lifecycle configuration at all → True (upload-id never expires)."""
    from xops.backup.multipart_resume import (
        check_bucket_lifecycle,
        _is_no_such_lifecycle_configuration,
    )

    class _NoLifecycleError(Exception):
        response = {"Error": {"Code": "NoSuchLifecycleConfiguration"}}

    stub_s3 = MagicMock()
    stub_s3.get_bucket_lifecycle_configuration.side_effect = _NoLifecycleError()

    result = check_bucket_lifecycle(stub_s3, bucket="my-bucket", min_days=2)
    assert result is True


# ---------------------------------------------------------------------------
# Kind registration boundary guards
# ---------------------------------------------------------------------------


def test_backup_offsite_upload_id_expired_in_known_maint_kinds() -> None:
    """backup_offsite_upload_id_expired must be in KNOWN_MAINT_EVENT_KINDS."""
    from swarm.agents.maint._ack_routing import KNOWN_MAINT_EVENT_KINDS

    assert "backup_offsite_upload_id_expired" in KNOWN_MAINT_EVENT_KINDS


def test_backup_offsite_lifecycle_too_aggressive_in_sec_alert_kinds() -> None:
    """backup_offsite_lifecycle_too_aggressive must be in KNOWN_SEC_ALERT_KINDS."""
    from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS

    assert "backup_offsite_lifecycle_too_aggressive" in KNOWN_SEC_ALERT_KINDS


def test_config_knobs_have_expected_defaults() -> None:
    """maint_backup_offsite_state_max_age_h default 18, lifecycle_min_days default 2."""
    from common.config import Config

    c = Config()
    assert c.maint_backup_offsite_state_max_age_h == 18
    assert c.maint_backup_offsite_lifecycle_min_days == 2
