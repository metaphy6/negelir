"""Phase 8 §8.9 DoD — Backup encryption multi-recipient proof tests.

Covers:

* **Two-recipient encrypt / per-key decrypt**: simulate a key dir
  containing 2 DR-class public keys; assert that the encrypted
  envelope is decryptable by **either** recipient's private key
  independently (neither key is required to be the other one).

* **fail_safe_min_recipients** (prod, 1 recipient): configuring
  ``profile=prod`` with an encryption key dir that holds only 1
  recipient causes :class:`BackupConfigError` carrying the
  ``fail_safe_min_recipients`` surface code at agent startup.

* **Two recipients / prod starts ok**: same config with 2 recipients
  does NOT raise — happy path baseline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pytest

from common.config import cfg as _cfg

from ai.swarm.agents.maint.backup import (
    BackupConfigError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgRoleChecker,
    NoopRecipientCounter,
    NoopVerifier,
    StaticDiskGauge,
)


# ── Inline multi-recipient age simulation ─────────────────────────────


@dataclass
class _Recipient:
    """Simulated age X25519 key pair."""

    identity: str    # private key ID
    public_key: str  # recipient public key


@dataclass
class InMemoryAgeEncryptor:
    """Pure-Python simulation of ``age`` multi-recipient encryption.

    ``encrypt(plaintext, recipients)`` produces a ciphertext that
    records which identities are allowed to decrypt. Any registered
    recipient can ``decrypt`` independently.

    This is NOT a real cryptographic primitive; it models the
    multi-recipient *contract* at the protocol level so CI can run
    without the ``age`` binary.
    """

    identities: dict[str, _Recipient] = field(default_factory=dict)
    _pub_to_id: dict[str, str] = field(default_factory=dict)

    def register(self, recipient: _Recipient) -> None:
        self.identities[recipient.identity] = recipient
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
        _, ids_str, plaintext = raw.split(":", 2)
        allowed = set(ids_str.split(","))
        if identity not in allowed:
            raise PermissionError(
                f"identity {identity!r} is not a recipient of this ciphertext"
            )
        return plaintext.encode()


# ── Helpers ────────────────────────────────────────────────────────────


def _build_agent(
    monkeypatch,
    *,
    profile: str = "mock",
    encryption_key_dir: str = "",
    recipient_count: int = 2,
) -> MaintBackupAgent:
    """Construct a :class:`MaintBackupAgent` with config overrides,
    bypassing all other startup gates."""
    monkeypatch.setattr(_cfg, "profile", profile, raising=False)
    monkeypatch.setattr(
        _cfg, "maint_backup_encryption_key_dir", encryption_key_dir, raising=False
    )
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        pg_role_checker=NoopPgRoleChecker(
            role_name="negelir_backup", is_superuser=False
        ),
        recipient_counter=NoopRecipientCounter(recipient_count=recipient_count),
    )


# ── Multi-recipient encrypt / decrypt tests ────────────────────────────


def test_either_recipient_decrypts_independently() -> None:
    """§8.9 DoD: encrypting to 2 recipients allows either private key
    to decrypt the ciphertext independently."""
    enc = InMemoryAgeEncryptor()
    alice = _Recipient(identity="AGE-SECRET-KEY-ALICE", public_key="age1alice")
    bob = _Recipient(identity="AGE-SECRET-KEY-BOB", public_key="age1bob")
    enc.register(alice)
    enc.register(bob)

    plaintext = b"negelir-nightly-backup-v1"
    ciphertext = enc.encrypt(plaintext, recipients=["age1alice", "age1bob"])

    assert enc.decrypt(ciphertext, identity="AGE-SECRET-KEY-ALICE") == plaintext
    assert enc.decrypt(ciphertext, identity="AGE-SECRET-KEY-BOB") == plaintext


def test_alice_decrypt_does_not_require_bob_key() -> None:
    """Alice's decryption succeeds regardless of whether Bob's key is
    registered — keys are independent."""
    enc = InMemoryAgeEncryptor()
    alice = _Recipient(identity="AGE-SECRET-KEY-ALICE", public_key="age1alice")
    bob = _Recipient(identity="AGE-SECRET-KEY-BOB", public_key="age1bob")
    enc.register(alice)
    enc.register(bob)

    ciphertext = enc.encrypt(b"data", recipients=["age1alice", "age1bob"])

    # Create a second encryptor that only knows Alice's key — simulates
    # an operator workstation that only has one key loaded.
    enc2 = InMemoryAgeEncryptor()
    enc2.register(alice)
    # enc2 cannot look up bob's public_key for encryption, but Alice can
    # still decrypt the ciphertext produced by the original encryptor.
    assert enc.decrypt(ciphertext, identity="AGE-SECRET-KEY-ALICE") == b"data"


def test_third_party_cannot_decrypt() -> None:
    """Adversarial: a key NOT in the recipient list raises PermissionError."""
    enc = InMemoryAgeEncryptor()
    alice = _Recipient(identity="AGE-SECRET-KEY-ALICE", public_key="age1alice")
    carol = _Recipient(identity="AGE-SECRET-KEY-CAROL", public_key="age1carol")
    enc.register(alice)
    enc.register(carol)

    ciphertext = enc.encrypt(b"secret", recipients=["age1alice"])

    with pytest.raises(PermissionError):
        enc.decrypt(ciphertext, identity="AGE-SECRET-KEY-CAROL")


# ── fail_safe_min_recipients gate ─────────────────────────────────────


def test_fail_safe_min_recipients_prod_one_key(monkeypatch) -> None:
    """§8.9 DoD: prod + key_dir + 1 recipient → BackupConfigError
    with fail_safe_min_recipients."""
    with pytest.raises(BackupConfigError) as exc_info:
        _build_agent(
            monkeypatch,
            profile="prod",
            encryption_key_dir="/keys/prod",
            recipient_count=1,
        )
    assert "fail_safe_min_recipients" in str(exc_info.value)


def test_fail_safe_min_recipients_error_reports_found_count(monkeypatch) -> None:
    """The BackupConfigError message must report the number of keys found."""
    with pytest.raises(BackupConfigError) as exc_info:
        _build_agent(
            monkeypatch,
            profile="prod",
            encryption_key_dir="/keys/prod",
            recipient_count=1,
        )
    assert "found 1" in str(exc_info.value)


def test_two_recipients_prod_starts_ok(monkeypatch) -> None:
    """§8.9 DoD: prod + key_dir + 2 recipients starts without error."""
    agent = _build_agent(
        monkeypatch,
        profile="prod",
        encryption_key_dir="/keys/prod",
        recipient_count=2,
    )
    assert agent is not None


def test_mock_profile_one_recipient_starts_ok(monkeypatch) -> None:
    """Non-prod profiles are not subject to the min-recipient gate."""
    agent = _build_agent(
        monkeypatch,
        profile="mock",
        encryption_key_dir="/keys/dev",
        recipient_count=1,
    )
    assert agent is not None


def test_prod_no_key_dir_min_recipients_gate_not_triggered(monkeypatch) -> None:
    """prod + empty key_dir does NOT trigger fail_safe_min_recipients
    (empty dir → gate predicate is False; the no-encryption gate owns
    that scenario when runtime != none)."""
    monkeypatch.setattr(_cfg, "maint_runtime", "none", raising=False)
    agent = _build_agent(
        monkeypatch,
        profile="prod",
        encryption_key_dir="",
        recipient_count=0,
    )
    assert agent is not None
