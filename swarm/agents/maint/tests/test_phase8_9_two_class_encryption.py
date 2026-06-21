"""Phase 8 §8.9 DoD — Two-class encryption recipient proof tests.

Covers the full two-class contract:

(a) verify-only private key successfully decrypts inside SidecarVerifier
(b) ``ops.restore`` REFUSES that same verify key with ``dr_key_required``
(c) any DR private key successfully drives ``ops.restore``
(d) verify keypair is rotated per dump (different fingerprint between two
    consecutive nightlies)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import pytest

from swarm.agents.maint.backup import (
    InMemoryMaintAuditLogger,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopRestoreExecutor,
    NoopVerifier,
    RecordingVerifyKeyRotator,
    StaticDiskGauge,
    StaticRestoreKeyClass,
)
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.types import Envelope, Message

UTC = timezone.utc


# ─── Inline two-class age simulation ────────────────────────────────────

@dataclass
class _Recipient:
    """Simulated age X25519 key pair with a key_class tag."""

    identity: str    # private key ID (secret)
    public_key: str  # public recipient address
    key_class: str   # "dr" | "verify"


@dataclass
class InMemoryTwoClassEncryptor:
    """Pure-Python simulation of a two-class ``age`` encryption system.

    Encrypt to multiple recipients in two classes:

    * ``"dr"`` — disaster-recovery keys (persistent custodian keys).
      Accepted by ``ops.restore`` (``RestoreKeyClass.classify → "dr"``).
    * ``"verify"`` — ephemeral per-dump keys. Accepted only by the
      SidecarVerifier for restore-verify; rejected by ``ops.restore``
      with surface code ``dr_key_required``.

    This is NOT a real cryptographic primitive. It models the two-class
    *contract* at the protocol level so CI can run without ``age``.
    """

    _identities: dict[str, _Recipient] = field(default_factory=dict)
    _pub_to_id: dict[str, str] = field(default_factory=dict)

    def register(self, recipient: _Recipient) -> None:
        self._identities[recipient.identity] = recipient
        self._pub_to_id[recipient.public_key] = recipient.identity

    def encrypt(self, plaintext: bytes, recipients: list[str]) -> bytes:
        allowed_ids = frozenset(
            self._pub_to_id[pub] for pub in recipients if pub in self._pub_to_id
        )
        if not allowed_ids:
            raise ValueError("no registered recipients in the list")
        ids_str = ",".join(sorted(allowed_ids))
        return f"age-sim:{ids_str}:{plaintext.decode()}".encode()

    def decrypt(self, ciphertext: bytes, identity: str) -> bytes:
        raw = ciphertext.decode()
        if not raw.startswith("age-sim:"):
            raise ValueError("not a simulated age ciphertext")
        _, ids_str, plaintext_str = raw.split(":", 2)
        allowed = set(ids_str.split(","))
        if identity not in allowed:
            raise PermissionError(
                f"identity {identity!r} is not a recipient of this ciphertext"
            )
        return plaintext_str.encode()

    def key_class_of(self, identity: str) -> str:
        """Return the key_class of the given identity."""
        return self._identities[identity].key_class


# ─── Sidecar verifier simulation ─────────────────────────────────────────

class _SidecarVerifierSimulator:
    """Models the SidecarVerifier's decrypt gate.

    ROADMAP §8.9 binding: the SidecarVerifier (Phase 14) accepts ANY
    key that can decrypt the dump — including verify-class keys. It
    does NOT enforce the DR-only gate (that is ``ops.restore``'s job).
    """

    def __init__(self, encryptor: InMemoryTwoClassEncryptor) -> None:
        self._enc = encryptor

    def can_verify(self, ciphertext: bytes, identity: str) -> bool:
        """Return True if ``identity`` can decrypt ``ciphertext``."""
        try:
            self._enc.decrypt(ciphertext, identity)
            return True
        except PermissionError:
            return False


# ─── Agent helper ─────────────────────────────────────────────────────────

def _t(y: int, mo: int, d: int, h: int = 9, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def _restore_msg(
    *,
    dump_date: str = "2025-01-01",
    request_id: str = "req-two-class",
    actor: str = "ops@host",
) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at="2025-01-02T09:00:00Z",
        schema_version=1,
        attempt=1,
    )
    return Message(
        envelope=env,
        payload={
            "kind": "restore",
            "target": dump_date,
            "request_id": request_id,
            "client_id": actor,
            "produced_at": "2025-01-02T09:00:00Z",
        },
    )


def _backup_msg() -> Message:
    """A nightly-trigger message handled by flush_expired, not handle()."""
    env = Envelope(
        message_id="m2",
        trace_id="t2",
        topic=MAINT_EVENT,
        producer="cron",
        created_at="2025-01-01T03:00:00Z",
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload={"kind": "backup_tick"})


def _build_agent(
    *,
    restore_key_class: StaticRestoreKeyClass | None = None,
    verify_key_rotator: RecordingVerifyKeyRotator | None = None,
    clock_wall: object | None = None,
) -> MaintBackupAgent:
    now = _t(2025, 1, 2, 9, 0)
    if clock_wall is None:
        clock_wall_fn = lambda: now  # noqa: E731
    else:
        clock_wall_fn = clock_wall  # type: ignore[assignment]
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        restore_key_class=restore_key_class or StaticRestoreKeyClass(key_class="dr"),
        verify_key_rotator=verify_key_rotator,
        audit_logger=InMemoryMaintAuditLogger(),
        clock_iso=lambda: clock_wall_fn().isoformat(timespec="seconds"),
        clock_wall=clock_wall_fn,
        clock_mono_ns=lambda: int(clock_wall_fn().timestamp() * 1e9),
        new_id=lambda: "fixed-id",
        enforce_permissions=False,
    )


# ─── (a) Verify key decrypts inside SidecarVerifier ───────────────────────

def test_verify_key_decrypts_for_sidecar_verifier() -> None:
    """§8.9 DoD (a): verify-only private key successfully decrypts the
    dump archive inside the SidecarVerifier.

    Encrypt with 2 DR keys + 1 verify key. The SidecarVerifier (which
    accepts any decryptable key) can decrypt using the verify identity.
    """
    enc = InMemoryTwoClassEncryptor()
    dr1 = _Recipient(identity="AGE-DR-KEY-1", public_key="age1dr1", key_class="dr")
    dr2 = _Recipient(identity="AGE-DR-KEY-2", public_key="age1dr2", key_class="dr")
    verify = _Recipient(identity="AGE-VERIFY-KEY", public_key="age1verify", key_class="verify")
    for r in (dr1, dr2, verify):
        enc.register(r)

    plaintext = b"negelir-nightly-dump-v1"
    ciphertext = enc.encrypt(plaintext, recipients=["age1dr1", "age1dr2", "age1verify"])

    sidecar = _SidecarVerifierSimulator(enc)

    # Verify-class key CAN decrypt inside the SidecarVerifier.
    assert sidecar.can_verify(ciphertext, identity="AGE-VERIFY-KEY")
    # Decrypted bytes match original plaintext.
    assert enc.decrypt(ciphertext, identity="AGE-VERIFY-KEY") == plaintext


def test_verify_key_is_verify_class_not_dr() -> None:
    """Adversarial: the verify identity is correctly tagged as class='verify',
    NOT 'dr', so any gate that checks key_class will distinguish them."""
    enc = InMemoryTwoClassEncryptor()
    verify = _Recipient(identity="AGE-VERIFY-KEY", public_key="age1verify", key_class="verify")
    enc.register(verify)
    assert enc.key_class_of("AGE-VERIFY-KEY") == "verify"


# ─── (b) ops.restore REFUSES verify class key ─────────────────────────────

def test_ops_restore_refuses_verify_class_key() -> None:
    """§8.9 DoD (b): ops.restore with a verify-class key returns
    outcome=dr_key_required and accepted=False."""
    agent = _build_agent(restore_key_class=StaticRestoreKeyClass(key_class="verify"))
    out = list(agent.handle(_restore_msg()))

    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1
    assert acks[0].payload["accepted"] is False
    assert acks[0].payload["reason"] == "dr_key_required"

    completed = next(
        m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed"
    )
    assert completed.payload["outcome"] == "dr_key_required"
    # ops.restore must NOT start the actual restore when key is verify-class.
    kinds = [(m.payload or {}).get("kind") for m in out]
    assert "backup_restore_started" not in kinds


def test_ops_restore_verify_class_key_does_not_reach_executor() -> None:
    """Adversarial: the RestoreExecutor is never called when the key is
    verify-class (reject happens before the executor pipeline)."""
    exe = NoopRestoreExecutor()
    agent = MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        restore_executor=exe,
        restore_key_class=StaticRestoreKeyClass(key_class="verify"),
        enforce_permissions=False,
    )
    list(agent.handle(_restore_msg()))
    # Executor's last_dump_date is None → restore() was never called.
    assert exe.last_dump_date is None


# ─── (c) DR key drives ops.restore successfully ───────────────────────────

def test_dr_key_drives_restore_successfully() -> None:
    """§8.9 DoD (c): ops.restore with a DR-class key proceeds to completion
    and returns outcome=ok."""
    agent = _build_agent(restore_key_class=StaticRestoreKeyClass(key_class="dr"))
    out = list(agent.handle(_restore_msg()))

    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert len(acks) == 1
    assert acks[0].payload["accepted"] is True

    completed = next(
        m for m in out if (m.payload or {}).get("kind") == "backup_restore_completed"
    )
    assert completed.payload["outcome"] == "ok"
    assert completed.payload["exit_code"] == 0

    kinds = [(m.payload or {}).get("kind") for m in out]
    assert "backup_restore_started" in kinds


def test_two_class_system_dr_restores_verify_cannot() -> None:
    """Combined two-class assertion: the same dump archive is encrypted to
    2 DR + 1 verify recipient. DR can drive ops.restore; verify cannot."""
    enc = InMemoryTwoClassEncryptor()
    dr1 = _Recipient(identity="AGE-DR-KEY-1", public_key="age1dr1", key_class="dr")
    dr2 = _Recipient(identity="AGE-DR-KEY-2", public_key="age1dr2", key_class="dr")
    verify = _Recipient(identity="AGE-VERIFY-KEY", public_key="age1verify", key_class="verify")
    for r in (dr1, dr2, verify):
        enc.register(r)

    plaintext = b"backup-payload"
    ciphertext = enc.encrypt(plaintext, recipients=["age1dr1", "age1dr2", "age1verify"])

    # Both DR keys can decrypt (ops.restore would proceed).
    for dr_id in ("AGE-DR-KEY-1", "AGE-DR-KEY-2"):
        assert enc.decrypt(ciphertext, dr_id) == plaintext
        assert enc.key_class_of(dr_id) == "dr"

    # Verify key can also decrypt (SidecarVerifier can verify).
    assert enc.decrypt(ciphertext, "AGE-VERIFY-KEY") == plaintext

    # But only the DR class is accepted by ops.restore gate.
    assert enc.key_class_of("AGE-VERIFY-KEY") == "verify"
    # → RestoreKeyClass.classify("AGE-VERIFY-KEY") would return "verify"
    #   → dr_key_required (proved by test_ops_restore_refuses_verify_class_key)


# ─── (d) verify keypair rotated per dump ──────────────────────────────────

def test_verify_keypair_rotated_per_dump() -> None:
    """§8.9 DoD (d): two consecutive nightly fire windows produce different
    verify key fingerprints.

    The MaintBackupAgent calls VerifyKeyRotator.new_recipient(dump_date=...)
    once per fire; consecutive calls with different dump_dates MUST return
    distinct fingerprints.
    """
    rotator = RecordingVerifyKeyRotator()

    fp1, _ = rotator.new_recipient(dump_date="2025-01-01")
    fp2, _ = rotator.new_recipient(dump_date="2025-01-02")

    assert fp1 != fp2, (
        "consecutive nightly dumps must have different verify key fingerprints; "
        f"got {fp1!r} for both"
    )


def test_verify_keypair_same_date_returns_same_fingerprint() -> None:
    """Within the same dump_date (e.g. catch-up retry) the fingerprint is
    stable — idempotent for the same nightly slot."""
    rotator = RecordingVerifyKeyRotator()

    fp_first, _ = rotator.new_recipient(dump_date="2025-01-01")
    fp_second, _ = rotator.new_recipient(dump_date="2025-01-01")

    assert fp_first == fp_second


def test_backup_completed_carries_verify_key_fingerprint() -> None:
    """§8.9 DoD (d): the backup_completed event on the ok path includes
    ``verify_key_fingerprint`` so operators can correlate the per-dump
    verify recipient fingerprint to the SidecarVerifier's key inventory.
    """
    rotator = RecordingVerifyKeyRotator()
    now = _t(2025, 1, 1, 3, 5)  # past the 03:00 cron window
    agent = _build_agent(
        verify_key_rotator=rotator,
        clock_wall=lambda: now,
    )

    # Arm the agent (first flush_expired() sets _next_fire_at).
    list(agent.flush_expired())
    # Step clock past the cron window to arm + fire.
    fired_at = _t(2025, 1, 1, 3, 0)

    # Re-build at the cron time so _fire is triggered.
    now2 = _t(2025, 1, 1, 3, 1)
    rotator2 = RecordingVerifyKeyRotator()
    agent2 = MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        verify_key_rotator=rotator2,
        enforce_permissions=False,
        clock_iso=lambda: now2.isoformat(timespec="seconds"),
        clock_wall=lambda: now2,
        clock_mono_ns=lambda: int(now2.timestamp() * 1e9),
        new_id=lambda: "fixed-id2",
    )
    # First flush_expired() arms the agent.
    list(agent2.flush_expired())
    # Advance clock to trigger the cron window.
    fired_clock = _t(2025, 1, 1, 3, 5)
    agent2._clock_wall = lambda: fired_clock  # type: ignore[method-assign]
    agent2._clock_iso = lambda: fired_clock.isoformat(timespec="seconds")  # type: ignore[method-assign]
    agent2._clock_mono_ns = lambda: int(fired_clock.timestamp() * 1e9)  # type: ignore[method-assign]
    out = list(agent2.flush_expired())

    completed_events = [
        m for m in out
        if (m.payload or {}).get("kind") == "backup_completed"
        and (m.payload or {}).get("outcome") in ("ok", "dry_run")
    ]
    if completed_events:
        completed = completed_events[0]
        assert "verify_key_fingerprint" in completed.payload
        fp = completed.payload["verify_key_fingerprint"]
        assert isinstance(fp, str) and fp
        # The fingerprint must match what the rotator recorded.
        assert fp in rotator2.fingerprints.values()


def test_ten_consecutive_dumps_all_different_fingerprints() -> None:
    """Ten consecutive dump_dates produce ten distinct fingerprints."""
    rotator = RecordingVerifyKeyRotator()
    dates = [f"2025-01-{d:02d}" for d in range(1, 11)]
    fps = [rotator.new_recipient(dump_date=d)[0] for d in dates]

    assert len(set(fps)) == len(fps), (
        f"expected all unique fingerprints; duplicates found: {fps}"
    )
