"""Phase 8 §8.9 DoD — Safety / hard-caps bullet: backup safety proof tests.

Covers three proof requirements from the §8.9 DoD safety bullet:

* **Mock-profile dry-run defaults to true.** When ``NEGELIR_PROFILE`` is
  not set (defaulting to ``mock``) and ``NEGELIR_MAINT_BACKUP_DRY_RUN`` is
  not set, ``cfg.maint_backup_dry_run`` must be ``True``.

* **PII-aware dump TOC.** After a backup fire the ``backup_completed``
  event must carry ``pii_excluded_columns`` containing
  ``"quarantine_samples.raw_bytes_b64"`` (the §8.9 binding default), and
  the ``NoopDumpExecutor.dump_toc`` must mirror that same list so a real
  executor can be validated at the Protocol level.

* **Backup file mode 0600, parent dir 0700 — proof test stats the
  artifacts.** ``_enforce_startup_permissions`` sets ``os.umask(0o077)``
  at agent boot; a live backup fire then writes ``audit.csv`` via
  ``_record_audit → xops.backup.audit.append_row``.  The test stats both
  the backup directory (expected 0700) and the written file (expected
  0600) so the permission contract is verified end-to-end rather than
  only through the ``check_permissions`` audit method alone.

The remaining sub-bullets of the §8.9 safety bullet
(disk-pressure refusal, restore-verify failure quarantines + critical
alert) are already proven in ``test_phase8_3_backup.py``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from common.config import cfg as _cfg
from swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopVerifier,
    StaticDiskGauge,
)
from xops.backup import migration_state as _migration_state

UTC = timezone.utc


def _t(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class _StubClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def wall(self) -> datetime:
        return self.now

    def mono_ns(self) -> int:
        return int(self.now.timestamp() * 1e9)

    def set(self, when: datetime) -> None:
        self.now = when


class _AlwaysLeader:
    name = "test-always-leader"

    def is_leader(self) -> bool:
        return True

    def shed(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_backup_test_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Reset mutable backup config + one-shot sentinels per test.

    These tests rely on deterministic backup-agent behavior and can be
    affected by prior modules mutating the shared cfg singleton.
    """
    monkeypatch.setattr(_cfg, "profile", "mock", raising=False)
    monkeypatch.setattr(_cfg, "maint_runtime", "compose", raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_cron", "0 3 * * *", raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_cold_verify_cron", "0 5 * * 0", raising=False,
    )
    monkeypatch.setattr(_cfg, "maint_backup_verify_mode", "full", raising=False)
    monkeypatch.setattr(
        _cfg,
        "maint_backup_pii_excluded_columns",
        "quarantine_samples.raw_bytes_b64",
        raising=False,
    )
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "/test/keys", raising=False,
    )
    monkeypatch.setattr(_cfg, "model_dir", str(tmp_path / "models"), raising=False)
    monkeypatch.setattr(_migration_state, "_COMMIT_SHA_ALERT_EMITTED", False)


def _build_agent_nodry(
    *,
    clock: _StubClock,
    dump: NoopDumpExecutor | None = None,
) -> MaintBackupAgent:
    """Build a backup agent; only patches maint_backup_dir (needed at
    construction time). Callers are responsible for patching dry_run
    around the entire fire sequence."""
    prior_dir = _cfg.maint_backup_dir
    prior_cron = _cfg.maint_backup_cron
    prior_cold_cron = _cfg.maint_backup_cold_verify_cron
    _cfg.maint_backup_dir = f"/tmp/negelir_test_backup_{uuid4().hex}"  # type: ignore[attr-defined]
    _cfg.maint_backup_cron = "0 3 * * *"  # type: ignore[attr-defined]
    _cfg.maint_backup_cold_verify_cron = "0 5 * * 0"  # type: ignore[attr-defined]
    try:
        return MaintBackupAgent(
            dump=dump or NoopDumpExecutor(bytes_written=4096),
            verifier=NoopVerifier(),
            pruner=InMemoryPrunerStorage(),
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            leader=_AlwaysLeader(),
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "fixed-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = prior_dir  # type: ignore[attr-defined]
        _cfg.maint_backup_cron = prior_cron  # type: ignore[attr-defined]
        _cfg.maint_backup_cold_verify_cron = prior_cold_cron  # type: ignore[attr-defined]


# ── Mock-profile dry-run default ────────────────────────────────────────


def test_mock_profile_dry_run_defaults_true() -> None:
    """§8.9 DoD: when NEGELIR_PROFILE is unset (defaults to 'mock') and
    NEGELIR_MAINT_BACKUP_DRY_RUN is not explicitly set, the config must
    default dry_run to True so dev/CI never run destructive prune.
    """
    from common.config import Config  # type: ignore[attr-defined]

    old_profile = os.environ.pop("NEGELIR_PROFILE", None)
    old_dry = os.environ.pop("NEGELIR_MAINT_BACKUP_DRY_RUN", None)
    try:
        fresh = Config()
        assert fresh.maint_backup_dry_run is True, (
            "maint_backup_dry_run must default to True when NEGELIR_PROFILE "
            "is unset (mock is the default profile)"
        )
    finally:
        if old_profile is not None:
            os.environ["NEGELIR_PROFILE"] = old_profile
        if old_dry is not None:
            os.environ["NEGELIR_MAINT_BACKUP_DRY_RUN"] = old_dry


def test_prod_profile_dry_run_defaults_false() -> None:
    """§8.9 DoD (symmetry): when NEGELIR_PROFILE=prod and
    NEGELIR_MAINT_BACKUP_DRY_RUN is not set, dry_run must default to False
    so production actually runs the backup.
    """
    from common.config import Config  # type: ignore[attr-defined]

    old_profile = os.environ.pop("NEGELIR_PROFILE", None)
    old_dry = os.environ.pop("NEGELIR_MAINT_BACKUP_DRY_RUN", None)
    try:
        os.environ["NEGELIR_PROFILE"] = "prod"
        fresh = Config()
        assert fresh.maint_backup_dry_run is False, (
            "maint_backup_dry_run must default to False when NEGELIR_PROFILE=prod"
        )
    finally:
        if old_profile is not None:
            os.environ["NEGELIR_PROFILE"] = old_profile
        else:
            os.environ.pop("NEGELIR_PROFILE", None)
        if old_dry is not None:
            os.environ["NEGELIR_MAINT_BACKUP_DRY_RUN"] = old_dry


def test_explicit_env_overrides_profile_default() -> None:
    """An explicit NEGELIR_MAINT_BACKUP_DRY_RUN=false must win over the
    mock-profile default of true.
    """
    from common.config import Config  # type: ignore[attr-defined]

    old_profile = os.environ.pop("NEGELIR_PROFILE", None)
    old_dry = os.environ.pop("NEGELIR_MAINT_BACKUP_DRY_RUN", None)
    try:
        # mock profile but explicit override to false
        os.environ["NEGELIR_MAINT_BACKUP_DRY_RUN"] = "false"
        fresh = Config()
        assert fresh.maint_backup_dry_run is False
    finally:
        if old_profile is not None:
            os.environ["NEGELIR_PROFILE"] = old_profile
        os.environ.pop("NEGELIR_MAINT_BACKUP_DRY_RUN", None)
        if old_dry is not None:
            os.environ["NEGELIR_MAINT_BACKUP_DRY_RUN"] = old_dry


# ── PII-aware dump TOC ───────────────────────────────────────────────────


def test_pii_excluded_columns_default_contains_raw_bytes_b64() -> None:
    """§8.9 DoD: cfg.maint_backup_pii_excluded_columns must include
    'quarantine_samples.raw_bytes_b64' by default.
    """
    from common.config import Config  # type: ignore[attr-defined]

    old = os.environ.pop("NEGELIR_MAINT_BACKUP_PII_EXCLUDED_COLUMNS", None)
    try:
        fresh = Config()
        cols = [c.strip() for c in fresh.maint_backup_pii_excluded_columns.split(",") if c.strip()]
        assert "quarantine_samples.raw_bytes_b64" in cols, (
            "quarantine_samples.raw_bytes_b64 must be in the default PII exclusion list"
        )
    finally:
        if old is not None:
            os.environ["NEGELIR_MAINT_BACKUP_PII_EXCLUDED_COLUMNS"] = old


def test_pii_aware_dump_toc_excludes_raw_bytes_b64() -> None:
    """§8.9 DoD proof test: the backup_completed event must carry
    ``pii_excluded_columns`` containing 'quarantine_samples.raw_bytes_b64',
    and the NoopDumpExecutor.dump_toc must mirror the same list.

    This is the 'proof test reads the dump TOC and asserts the column is
    excluded' requirement from the §8.9 safety/hard-caps bullet.
    """
    prior_pii = _cfg.maint_backup_pii_excluded_columns
    prior_dry = _cfg.maint_backup_dry_run
    # Both must stay set for the ENTIRE fire sequence, not just construction.
    _cfg.maint_backup_pii_excluded_columns = "quarantine_samples.raw_bytes_b64"  # type: ignore[attr-defined]
    _cfg.maint_backup_dry_run = False  # type: ignore[attr-defined]
    try:
        dump_exec = NoopDumpExecutor(bytes_written=4096)
        clock = _StubClock(_t(2025, 1, 1, 2, 30))
        agent = _build_agent_nodry(clock=clock, dump=dump_exec)
        list(agent.flush_expired())  # arm
        clock.set(_t(2025, 1, 1, 3, 0))
        msgs = list(agent.flush_expired())

        # ── 1. Read the dump TOC (NoopDumpExecutor.dump_toc) ──────────
        assert "quarantine_samples.raw_bytes_b64" in dump_exec.dump_toc, (
            "NoopDumpExecutor.dump_toc must record 'quarantine_samples.raw_bytes_b64' "
            "after the agent fires a backup (§8.9 PII-aware dump contract)"
        )

        # ── 2. Read the backup_completed event TOC ─────────────────────
        completed = next(
            m.payload for m in msgs if m.payload.get("kind") == "backup_completed"
        )
        assert completed["outcome"] == "ok"
        pii_cols = completed["pii_excluded_columns"]
        assert isinstance(pii_cols, list), "pii_excluded_columns must be a list"
        assert "quarantine_samples.raw_bytes_b64" in pii_cols, (
            "backup_completed.pii_excluded_columns must contain "
            "'quarantine_samples.raw_bytes_b64' (§8.9 PII-aware dump TOC)"
        )
    finally:
        _cfg.maint_backup_pii_excluded_columns = prior_pii  # type: ignore[attr-defined]
        _cfg.maint_backup_dry_run = prior_dry  # type: ignore[attr-defined]


# ── File-mode proof test (§8.9 safety bullet) ───────────────────────────


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits required")
def test_backup_file_0600_and_dir_0700_proof_test_stats_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.9 DoD safety bullet: Backup file mode 0600, parent dir 0700.

    Proof test that stats the artifacts written during a live backup fire:

    * ``audit.csv`` (written via ``_record_audit → xops.backup.audit.
      append_row``) must have mode 0600.
    * ``maint_backup_dir`` (created by the agent's first write's
      ``mkdir(parents=True)``) must have mode 0700.

    Mechanism: ``_enforce_startup_permissions`` calls
    ``os.umask(0o077)`` at boot so subsequent ``os.open(..., 0o600)``
    calls and ``mkdir(mode=0o777)`` calls produce the correct
    restricted permissions.
    """
    # Point to a path that does NOT yet exist so check_permissions()
    # returns [] at construction (missing dir → first run, no violation).
    backup_dir = tmp_path / "backup_artifacts_probe"
    assert not backup_dir.exists(), "precondition: dir must not exist yet"

    monkeypatch.setattr(_cfg, "maint_backup_dir", str(backup_dir), raising=False)
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", False, raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_pii_excluded_columns", "", raising=False
    )

    prev_umask = os.umask(0o022)  # establish a known-loose umask first
    try:
        clock = _StubClock(_t(2025, 1, 1, 2, 30))
        # enforce_permissions=True → _enforce_startup_permissions →
        # os.umask(0o077).  backup_dir absent → check_permissions() → [].
        agent = MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=NoopVerifier(),
            pruner=InMemoryPrunerStorage(),
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "fixed-id",
            enforce_permissions=True,  # sets umask 0o077
        )
        # Arm on first tick (arms _next_fire_at to next 3:00 AM).
        list(agent.flush_expired())
        # Advance to cron time: fires the dump → verify → prune pipeline
        # and writes audit.csv (via _record_audit → append_row).
        clock.set(_t(2025, 1, 1, 3, 0))
        list(agent.flush_expired())
    finally:
        os.umask(prev_umask)  # restore so subsequent tests are unaffected

    # ── stat the artifacts ───────────────────────────────────────────────
    audit_csv = backup_dir / "audit.csv"
    assert audit_csv.exists(), (
        "audit.csv must be written by the agent during a backup fire "
        "(via _record_audit → xops.backup.audit.append_row)"
    )

    dir_mode = backup_dir.stat().st_mode & 0o777
    file_mode = audit_csv.stat().st_mode & 0o777

    assert dir_mode == 0o700, (
        f"backup dir mode {oct(dir_mode)} must be 0o700 "
        "(§8.9 parent dir 0700 contract; umask 0o077 + mkdir mode=0o777)"
    )
    assert file_mode == 0o600, (
        f"audit.csv mode {oct(file_mode)} must be 0o600 "
        "(§8.9 backup file 0600 contract; os.open(..., 0o600) under umask 0o077)"
    )


# ── Checksum proof tests (§8.9 safety bullet) ───────────────────────────


def test_pre_restore_checksum_verify_fail_rejected() -> None:
    """§8.9 DoD: backup checksum re-verified pre-restore.

    When the ChecksumStore returns False (simulating a missing/corrupt
    checksum — e.g. dump file written but checksum not yet persisted),
    the restore must be rejected with outcome='checksum_verify_failed'
    and ack accepted=False. The restore executor must NOT be called.
    """
    from swarm.agents.maint.backup import (
        RESTORE_OUTCOMES,
        NoopChecksumStore,
    )
    from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
    from swarm.sdk.types import Envelope, Message

    # A ChecksumStore that never trusts anything (always_trust=False,
    # no write() calls) — simulates a missing checksum file on disk.
    empty_store = NoopChecksumStore(always_trust=False)

    clock = _StubClock(_t(2025, 1, 2, 9, 0))
    agent = MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        checksum_store=empty_store,
        clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
        clock_wall=clock.wall,
        clock_mono_ns=clock.mono_ns,
        new_id=lambda: "fixed-id",
        enforce_permissions=False,
    )

    restore_payload: dict = {
        "kind": "restore",
        "target": "2025-01-01",
        "request_id": "req-checksum-1",
        "client_id": "ops@host",
        "produced_at": "2025-01-02T09:00:00Z",
    }
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at="2025-01-02T09:00:00Z",
        schema_version=1,
        attempt=1,
    )
    msg = Message(envelope=env, payload=restore_payload)
    out = list(agent.handle(msg))

    # Ack must be rejected.
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1
    assert acks[0].payload["accepted"] is False
    assert acks[0].payload["reason"] == "checksum_verify_failed", (
        "restore with missing checksum must be rejected with "
        "reason='checksum_verify_failed' (§8.9 pre-restore checksum gate)"
    )

    # backup_restore_completed must surface the outcome.
    completed = next(
        (m.payload for m in out
         if (m.payload or {}).get("kind") == "backup_restore_completed"),
        None,
    )
    assert completed is not None, "backup_restore_completed must be emitted"
    assert completed["outcome"] == "checksum_verify_failed"
    assert completed["exit_code"] != 0

    # restore_started must NOT be emitted (restore was refused before start).
    assert not any(
        (m.payload or {}).get("kind") == "backup_restore_started"
        for m in out
    ), "backup_restore_started must not be emitted when checksum verify fails"

    # Taxonomy: checksum_verify_failed must be in RESTORE_OUTCOMES.
    assert "checksum_verify_failed" in RESTORE_OUTCOMES


def test_kill9_mid_dump_partial_dump_re_runs(tmp_path: Path) -> None:
    """§8.9 DoD kill-9 mid-dump test: post-restart, the partial dump is
    detected via missing checksum and the agent re-runs.

    Scenario:
    1. A previous agent run wrote audit.csv with outcome='ok' for today
       (simulating a run that completed the audit write).
    2. The checksum was NOT persisted (kill-9 before checksum.write()
       — simulated by using NoopChecksumStore(always_trust=False) with
       no prior write() calls).
    3. A new agent instance boots, reads audit.csv: seeded_fwid exists.
    4. Cross-check: checksum.verify(seeded_fwid) → False.
    5. Agent does NOT seed _last_completed_wall → treats today as not done.
    6. On the next flush_expired() call at cron time, the agent re-fires
       (backup_started + backup_completed emitted).
    """
    from pathlib import Path

    from swarm.agents.maint.backup import NoopChecksumStore
    from xops.backup.audit import AuditRow, append_row

    backup_dir = tmp_path / "backup_kill9_test"
    backup_dir.mkdir(mode=0o700, parents=True)
    audit_csv = backup_dir / "audit.csv"

    # ── Step 1: write a "completed today" audit row ──────────────────────
    fire_date = _t(2025, 1, 1, 3, 0)
    append_row(
        audit_csv,
        AuditRow(
            wall_clock_utc=fire_date.isoformat(),
            monotonic_ns_at_fire=int(fire_date.timestamp() * 1e9),
            fire_window_id="simulated_prev_run:2025-01-01T03:00:00+00:00",
            outcome="ok",
            verified=True,
            catch_up=False,
        ),
    )

    # ── Step 2: empty checksum store = simulates kill-9 before write ────
    empty_checksum = NoopChecksumStore(always_trust=False)

    # ── Step 3: "restart" — new agent, reads audit.csv ──────────────────
    clock = _StubClock(_t(2025, 1, 1, 3, 30))  # same day, 30m after cron

    prior_dir = _cfg.maint_backup_dir
    try:
        _cfg.maint_backup_dir = str(backup_dir)  # type: ignore[attr-defined]
        agent = MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=NoopVerifier(),
            pruner=InMemoryPrunerStorage(),
            quarantine=InMemoryQuarantineStore(),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
            checksum_store=empty_checksum,
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "fixed-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = prior_dir  # type: ignore[attr-defined]

    # ── Step 4-5: agent must NOT have seeded from audit (checksum bad) ──
    assert agent._last_completed_wall is None, (
        "_last_completed_wall must be None when boot checksum verify fails "
        "(§8.9 kill-9 mid-dump guard: partial dump not considered completed)"
    )

    # ── Step 6: assert re-fires on first flush_expired() call ──────────
    # Clock is at 03:30 AM, already past the 03:00 cron slot.
    # Since _last_completed_wall is None (checksum failed at boot), the
    # agent arms _next_fire_at to 03:00 AM and fires immediately via the
    # catch-up branch (now=03:30 >= _next_fire_at=03:00).
    prior_dry = _cfg.maint_backup_dry_run
    try:
        _cfg.maint_backup_dry_run = False  # type: ignore[attr-defined]
        msgs = list(agent.flush_expired())
    finally:
        _cfg.maint_backup_dry_run = prior_dry  # type: ignore[attr-defined]

    kinds = [(m.payload or {}).get("kind") for m in msgs]
    assert "backup_started" in kinds, (
        "agent must emit backup_started on re-fire after kill-9 partial dump "
        "(§8.9 kill-9 mid-dump: re-run not skipped)"
    )
    assert "backup_completed" in kinds, (
        "agent must emit backup_completed after re-running the dump"
    )
    completed = next(m.payload for m in msgs if m.payload.get("kind") == "backup_completed")
    assert completed["outcome"] in ("ok", "dry_run"), (
        f"backup_completed.outcome={completed['outcome']!r} must be ok/dry_run"
    )

