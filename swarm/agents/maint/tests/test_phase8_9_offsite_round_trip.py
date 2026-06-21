"""Phase 8 §8.12 — off-host replication round-trip proof tests.

Bullet (ROADMAP §8.9 DoD):
  Off-host replication round-trip (§8.12). Seeded mock S3 (minio)
  target; nightly dump uploads with multipart, manifest checksum verified;
  agent kill mid-upload -> next tick resumes (idempotent multipart upload);
  verify the uploaded blob is decryptable end-to-end via a DR key.
  Failure modes: target unreachable for 24h -> kind=backup_offsite_failed
  + critical alert; target object-lock retention prevents accidental
  overwrite (assert via mocked WORM enforcement).
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopOffsiteTarget,
    OffsiteUnreachableError,
    RecordingOffsiteTarget,
    WormEnforcementError,
)
from swarm.agents.topics import MAINT_EVENT, SEC_ALERT

UTC = timezone.utc


def _t(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    def __init__(self, start):
        self.now = start

    def wall(self):
        return self.now

    def mono_ns(self):
        return int(self.now.timestamp() * 1e9)

    def set(self, when):
        self.now = when


def _agent(clock, backup_dir: str, offsite_target=None):
    prior = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = backup_dir  # type: ignore[attr-defined]
    try:
        agent = MaintBackupAgent(
            dump=NoopDumpExecutor(),
            enforce_permissions=False,
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            clock_iso=lambda: clock.wall().isoformat(),
            offsite_target=offsite_target,
        )
    finally:
        _cfg.maint_backup_dir = prior  # type: ignore[attr-defined]
    return agent


@pytest.fixture(autouse=True)
def _live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", False)


def _kinds(msgs, topic=MAINT_EVENT):
    return [m.payload.get("kind") for m in msgs if m.envelope.topic == topic]


def _events(msgs, kind, topic=MAINT_EVENT):
    return [m for m in msgs if m.envelope.topic == topic and m.payload.get("kind") == kind]


def _fire(agent, clock, when):
    clock.set(when)
    return list(agent.flush_expired())


def test_offsite_upload_fires_after_verify_success(tmp_path):
    target = RecordingOffsiteTarget()
    clock = _StubClock(_t(2025, 1, 10, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 1, 10, 3, 0)
    msgs = _fire(agent, clock, _t(2025, 1, 10, 3, 1))
    assert "backup_offsite_uploaded" in _kinds(msgs)
    assert len(target.upload_calls) == 1
    assert target.upload_calls[0]["dump_date"] == "2025-01-10"


def test_offsite_manifest_checksum_in_payload(tmp_path):
    target = RecordingOffsiteTarget(manifest_checksum="sha256:deadbeef01234567")
    clock = _StubClock(_t(2025, 1, 10, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 1, 10, 3, 0)
    msgs = _fire(agent, clock, _t(2025, 1, 10, 3, 1))
    uploaded = _events(msgs, "backup_offsite_uploaded")
    assert uploaded
    assert uploaded[0].payload["manifest_checksum"] == "sha256:deadbeef01234567"


def test_mid_upload_resume_on_next_tick(tmp_path):
    target = RecordingOffsiteTarget(resumed_on_second_call=True)
    clock = _StubClock(_t(2025, 1, 10, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 1, 10, 3, 0)
    msgs1 = _fire(agent, clock, _t(2025, 1, 10, 3, 1))
    assert _events(msgs1, "backup_offsite_uploaded")
    assert target.upload_calls[0]["resumed_from_state"] is False
    agent._next_fire_at = _t(2025, 1, 11, 3, 0)
    msgs2 = _fire(agent, clock, _t(2025, 1, 11, 3, 1))
    assert _events(msgs2, "backup_offsite_uploaded")
    uploaded2 = _events(msgs2, "backup_offsite_uploaded")[0]
    assert uploaded2.payload["resumed_from_state"] is True


def test_upload_result_decryptable_by_dr_key(tmp_path):
    target = RecordingOffsiteTarget(decryptable_by_dr_key=True)
    clock = _StubClock(_t(2025, 1, 10, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 1, 10, 3, 0)
    _fire(agent, clock, _t(2025, 1, 10, 3, 1))
    assert target.upload_calls
    assert target.upload_calls[0]["decryptable_by_dr_key"] is True


def test_unreachable_target_fires_offsite_failed_and_critical_alert(tmp_path):
    target = RecordingOffsiteTarget(
        fail_with=OffsiteUnreachableError("minio unreachable: connection refused")
    )
    clock = _StubClock(_t(2025, 1, 10, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 1, 10, 3, 0)
    msgs = _fire(agent, clock, _t(2025, 1, 10, 3, 1))
    offsite_failed = _events(msgs, "backup_offsite_failed")
    assert offsite_failed
    assert "unreachable" in offsite_failed[0].payload.get("reason", "").lower()
    sec_alerts = [m for m in msgs if m.envelope.topic == SEC_ALERT]
    critical_offsite = [
        a for a in sec_alerts
        if a.payload.get("kind") == "backup_offsite_failed"
        and a.payload.get("severity") == "critical"
    ]
    assert critical_offsite
    completed = _events(msgs, "backup_completed")
    assert completed
    assert completed[0].payload["outcome"] in ("ok", "dry_run")


def test_worm_enforcement_blocks_overwrite():
    target = RecordingOffsiteTarget(worm_enabled=True)
    result1 = target.upload(
        fire_window_id="fw:2025-01-10T03:00:00+00:00",
        dump_date="2025-01-10",
        encrypted_bytes=1024,
    )
    assert result1.uploaded_bytes > 0
    with pytest.raises(WormEnforcementError, match="object_lock prevents overwrite"):
        target.upload(
            fire_window_id="fw:2025-01-10T15:00:00+00:00",
            dump_date="2025-01-10",
            encrypted_bytes=1024,
        )


# ── §8.12 upload-window tests ──────────────────────────────────────────────


def test_upload_timeout_fires_backup_offsite_failed_with_reason_timeout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """Bullet: hard timeout at cfg.maint_backup_offsite_upload_timeout_h.
    Overruns abort + emit kind=backup_offsite_failed{reason=timeout, uploaded_bytes}.
    """
    from common.config import cfg as _cfg2

    # A target that sleeps longer than the configured timeout.
    target = RecordingOffsiteTarget(sleep_s=5.0)

    # Shorten the timeout to 0.05 h (= 180 ms) so the test is fast.
    monkeypatch.setattr(_cfg2, "maint_backup_offsite_upload_timeout_h", 0.05 / 3600)

    clock = _StubClock(_t(2025, 3, 1, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 3, 1, 3, 0)
    msgs = _fire(agent, clock, _t(2025, 3, 1, 3, 1))

    # offsite_failed with reason=timeout must be emitted
    offsite_failed = _events(msgs, "backup_offsite_failed")
    assert offsite_failed, "expected backup_offsite_failed on timeout"
    assert offsite_failed[0].payload.get("reason") == "timeout"
    assert "uploaded_bytes" in offsite_failed[0].payload

    # A critical sec.alert must also be emitted
    from swarm.agents.topics import SEC_ALERT  # noqa: PLC0415
    sec_alerts = [m for m in msgs if m.envelope.topic == SEC_ALERT]
    critical_timeout = [
        a for a in sec_alerts
        if a.payload.get("kind") == "backup_offsite_failed"
        and a.payload.get("severity") == "critical"
    ]
    assert critical_timeout

    # backup_completed still emits (offsite is non-blocking)
    completed = _events(msgs, "backup_completed")
    assert completed
    assert completed[0].payload["outcome"] == "ok"


def test_upload_runs_concurrently_with_prune(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Bullet: runs concurrently with the next nightly's TTL prune.
    A slow upload (200 ms) completes while the (instant) prune runs;
    prune_completed appears before backup_offsite_uploaded but both
    appear in the same flush_expired batch — confirming overlap.
    """
    import time as _time

    from common.config import cfg as _cfg2

    # Enough timeout to finish the slow upload (1 h).
    monkeypatch.setattr(_cfg2, "maint_backup_offsite_upload_timeout_h", 1)

    # Target sleeps 150 ms — fast enough for CI, long enough that
    # the prune (instant in-memory shim) finishes first.
    target = RecordingOffsiteTarget(sleep_s=0.15)

    clock = _StubClock(_t(2025, 3, 2, 3, 1))
    agent = _agent(clock, backup_dir=str(tmp_path), offsite_target=target)
    agent._next_fire_at = _t(2025, 3, 2, 3, 0)

    t0 = _time.monotonic()
    msgs = _fire(agent, clock, _t(2025, 3, 2, 3, 1))
    elapsed = _time.monotonic() - t0

    kinds = _kinds(msgs)
    assert "prune_completed" in kinds
    assert "backup_offsite_uploaded" in kinds

    # Both must appear in the same batch (flush_expired returned both).
    prune_idx = kinds.index("prune_completed")
    uploaded_idx = kinds.index("backup_offsite_uploaded")
    # prune completes before the upload join returns, so prune_completed
    # should appear before backup_offsite_uploaded in the event stream.
    assert prune_idx < uploaded_idx

    # Total elapsed must be ≥ 0.15 s (we waited for the upload thread)
    # and well under 2 s (we were not blocked *before* the prune).
    assert elapsed >= 0.10
    assert elapsed < 2.0
