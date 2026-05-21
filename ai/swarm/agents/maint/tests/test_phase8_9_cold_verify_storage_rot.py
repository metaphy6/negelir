"""Phase 8 §8.9 — weekly cold-verify catches storage rot (bit-flip proof).

Bullet (ROADMAP §8.9):

> **Weekly cold-verify catches storage rot.** Bit-flip a single byte in
> an older retained dump's middle file; cold-verify fires
> ``kind=backup_cold_verify_failed`` + ``severity=critical`` alert;
> nightly continues unaffected; the corrupted dump is NOT auto-pruned.

What this asserts (binding):

* A ``ChecksumVerifier`` reads ``negelir.checksum.txt`` and re-computes
  the SHA-256 of ``dump.tar.age``; returns empty mapping on mismatch
  (signals failure to the agent state machine).
* Agent emits ``kind=backup_cold_verify_failed`` and a
  ``sec.alert.v1{kind=backup_verify_failed, severity=critical}``
  when cold-verify detects corruption.
* The nightly backup fires normally in the same tick — cold-verify
  failure does NOT block the nightly state machine.
* The corrupted dump directory is NOT removed (cold-verify NEVER
  prunes; operator decides).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pytest

from common.config import cfg as _cfg
from ai.swarm.agents.maint.backup import (
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    StaticDiskGauge,
)
from ai.swarm.agents.topics import MAINT_EVENT, SEC_ALERT
from xops.backup.executors import CHECKSUM_NAME, ENCRYPTED_NAME

UTC = timezone.utc


# ── Helpers ─────────────────────────────────────────────────────────────


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


@dataclass
class ChecksumVerifier:
    """Test verifier that validates ``dump.tar.age`` against the sibling
    ``negelir.checksum.txt``.

    Returns a non-empty row-count dict on success (checksum matches), or
    an empty dict on corruption (checksum mismatch or missing file). Uses
    the ``dump_date`` encoded in ``fire_window_id`` to locate the dump
    directory under ``backup_dir``.
    """

    backup_dir: str
    success_summary: dict = field(
        default_factory=lambda: {"matches": 0, "_schema_max_version": 11},
    )
    orphans: tuple = ()

    def verify(
        self, *, fire_window_id: str, mode: str = "full",
    ) -> Mapping:
        # fire_window_id: cold:<pod_id>:<dump_date> or <pod_id>:<dump_date>
        # dump_date is always the last colon-separated token.
        dump_date = fire_window_id.split(":")[-1]
        base = Path(self.backup_dir)
        dump_dir: Path | None = None
        try:
            for entry in base.iterdir():
                if entry.is_dir() and dump_date in entry.name:
                    dump_dir = entry
                    break
        except OSError:
            return {}
        if dump_dir is None:
            return {}
        encrypted_path = dump_dir / ENCRYPTED_NAME
        checksum_path = dump_dir / CHECKSUM_NAME
        if not encrypted_path.exists() or not checksum_path.exists():
            return {}
        expected = checksum_path.read_text().strip()
        actual = hashlib.sha256(encrypted_path.read_bytes()).hexdigest()
        if actual != expected:
            return {}
        return dict(self.success_summary)

    def sweep_orphans(self) -> tuple:
        return self.orphans


def _mk_healthy_dump_dir(base: Path, name: str) -> Path:
    """Create a dump dir with a valid ``dump.tar.age`` + SHA-256 checksum."""
    p = base / name
    p.mkdir()
    # Representative multi-byte payload; 1 088 bytes so the middle byte
    # lands well inside the payload rather than at position 0.
    content = b"negelir-mock-dump\x01" * 64
    (p / ENCRYPTED_NAME).write_bytes(content)
    (p / CHECKSUM_NAME).write_text(hashlib.sha256(content).hexdigest())
    return p


def _bit_flip_middle_byte(dump_dir: Path) -> None:
    """XOR the middle byte of ``dump.tar.age`` to simulate storage rot."""
    path = dump_dir / ENCRYPTED_NAME
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def _build_agent(
    *,
    clock: _StubClock,
    verifier: ChecksumVerifier,
    backup_dir: str,
) -> MaintBackupAgent:
    prior = _cfg.maint_backup_dir
    _cfg.maint_backup_dir = backup_dir  # type: ignore[attr-defined]
    try:
        agent = MaintBackupAgent(
            dump=NoopDumpExecutor(bytes_written=4096),
            verifier=verifier,
            pruner=InMemoryPrunerStorage(counts={}),
            quarantine=InMemoryQuarantineStore(rows_per_client={}),
            disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3, last_dump_bytes=0),
            clock_iso=lambda: clock.wall().isoformat(timespec="seconds"),
            clock_wall=clock.wall,
            clock_mono_ns=clock.mono_ns,
            new_id=lambda: "fixed-id",
            enforce_permissions=False,
        )
    finally:
        _cfg.maint_backup_dir = prior  # type: ignore[attr-defined]
    return agent


@pytest.fixture(autouse=True)
def _force_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_cfg, "maint_backup_dry_run", False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", "/test/keys", raising=False,
    )


# ── Tests ────────────────────────────────────────────────────────────────


def test_cold_verify_detects_bit_flip_emits_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bit-flip the middle byte of a Sunday dump → agent emits
    ``backup_cold_verify_failed`` with the correct dump_date in the payload."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    dump_dir = _mk_healthy_dump_dir(tmp_path, "pod_2025-04-13")
    _bit_flip_middle_byte(dump_dir)

    clock = _StubClock(_t(2025, 4, 12, 12, 0))  # Saturday — arm
    verifier = ChecksumVerifier(backup_dir=str(tmp_path))
    agent = _build_agent(clock=clock, verifier=verifier, backup_dir=str(tmp_path))
    list(agent.flush_expired())  # arm both crons

    clock.set(_t(2025, 4, 13, 5, 1))  # Sunday 05:01 — cold-verify fires
    msgs = list(agent.flush_expired())

    failed = [
        m.payload for m in msgs
        if m.envelope.topic == MAINT_EVENT
        and m.payload.get("kind") == "backup_cold_verify_failed"
    ]
    assert len(failed) == 1, [m.payload.get("kind") for m in msgs]
    assert failed[0]["dump_date"] == "2025-04-13"
    assert failed[0]["error"]


def test_cold_verify_bit_flip_emits_critical_sec_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bit-flip in a Sunday dump → ``sec.alert.v1{kind=backup_verify_failed,
    severity=critical, scope=cold}`` emitted."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    dump_dir = _mk_healthy_dump_dir(tmp_path, "pod_2025-04-13")
    _bit_flip_middle_byte(dump_dir)

    clock = _StubClock(_t(2025, 4, 12, 12, 0))
    verifier = ChecksumVerifier(backup_dir=str(tmp_path))
    agent = _build_agent(clock=clock, verifier=verifier, backup_dir=str(tmp_path))
    list(agent.flush_expired())
    clock.set(_t(2025, 4, 13, 5, 1))
    msgs = list(agent.flush_expired())

    cold_alerts = [
        m.payload for m in msgs
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "backup_verify_failed"
        and "scope=cold" in str(m.payload.get("reason", ""))
    ]
    assert len(cold_alerts) == 1, [
        (m.envelope.topic, m.payload.get("kind")) for m in msgs
    ]
    assert cold_alerts[0]["severity"] == "critical"
    assert "2025-04-13" in cold_alerts[0]["reason"]


def test_cold_verify_bit_flip_corrupted_dump_not_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold-verify failure must NOT remove the corrupted dump — the
    operator decides what to do with forensic evidence."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    dump_dir = _mk_healthy_dump_dir(tmp_path, "pod_2025-04-13")
    _bit_flip_middle_byte(dump_dir)

    clock = _StubClock(_t(2025, 4, 12, 12, 0))
    verifier = ChecksumVerifier(backup_dir=str(tmp_path))
    agent = _build_agent(clock=clock, verifier=verifier, backup_dir=str(tmp_path))
    list(agent.flush_expired())
    clock.set(_t(2025, 4, 13, 5, 1))
    list(agent.flush_expired())

    assert dump_dir.exists(), "Corrupted dump dir must not be auto-pruned"


def test_cold_verify_failure_does_not_block_nightly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cold-verify fails (bit-flip), the nightly backup state machine
    fires normally in the same tick and emits ``backup_completed``."""
    monkeypatch.setattr(_cfg, "maint_backup_dir", str(tmp_path))
    dump_dir = _mk_healthy_dump_dir(tmp_path, "pod_2025-04-13")
    _bit_flip_middle_byte(dump_dir)

    # Arm on Saturday; Sunday 05:01 fires both nightly (03:00 missed,
    # catch-up fires) and cold-verify (05:00) in the same flush_expired().
    clock = _StubClock(_t(2025, 4, 12, 12, 0))
    verifier = ChecksumVerifier(backup_dir=str(tmp_path))
    agent = _build_agent(clock=clock, verifier=verifier, backup_dir=str(tmp_path))
    list(agent.flush_expired())

    clock.set(_t(2025, 4, 13, 5, 1))
    msgs = list(agent.flush_expired())

    maint_kinds = [
        m.payload.get("kind") for m in msgs
        if m.envelope.topic == MAINT_EVENT
    ]
    assert "backup_started" in maint_kinds, maint_kinds
    assert "backup_completed" in maint_kinds, maint_kinds
    # Cold-verify failure present alongside nightly success.
    assert "backup_cold_verify_failed" in maint_kinds, maint_kinds
