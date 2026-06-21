"""Phase 8 §8.13.6 Encryption-key compromise runbook — combined proof tests.

Covers all three scenarios required by the §8.13.6 DoD bullet:

* **(a) Verify-key rotation:** After rotating the per-dump verify key,
  the OLD verify key cannot decrypt the *new* nightly's ciphertext.
  The *new* verify key CAN. The DR key can decrypt both (persistent).

* **(b) DR-key revocation:** Encrypt old dump to [k1, k2, k3]. Revoke
  k1 (remove from active recipients). Encrypt next nightly to [k2, k3]
  only. Assertions:
  - new dump decryptable by k2, k3 ✓
  - new dump NOT decryptable by k1 (revoked) ✓
  - old dump still decryptable by k1, k2, k3 (no re-encryption per runbook) ✓

* **(c) PG-secret age refusal:** ``pg_secret_age_days=121`` (> default
  cap 120) causes the agent to refuse startup with
  ``fail_safe_pg_secret_expired``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from swarm.agents.maint.backup import (
    BackupPermissionError,
    InMemoryPrunerStorage,
    InMemoryQuarantineStore,
    MaintBackupAgent,
    NoopDumpExecutor,
    NoopPgSecretAgeChecker,
    NoopVerifier,
    StaticDiskGauge,
)

# ─── Minimal in-memory age-like encryption simulator ─────────────────────────
#
# This is NOT a cryptographic primitive.  It models the *recipient* contract
# of ``age`` at the protocol level so the CI can run without the ``age``
# binary.  Each registered identity maps to exactly one public key; encrypt
# writes the allowed identity set into the ciphertext; decrypt checks
# membership.


@dataclass
class _InMemoryEncryptor:
    """Pure-Python simulation of multi-recipient symmetric-box encryption.

    Enough to prove the runbook invariants at the protocol level without
    shelling out to ``age``.
    """

    _pub_to_id: dict[str, str] = field(default_factory=dict)

    def register(self, identity: str, public_key: str) -> None:
        """Register a (identity, public_key) pair."""
        self._pub_to_id[public_key] = identity

    def encrypt(self, plaintext: bytes, recipients: list[str]) -> bytes:
        """Return a simulated ciphertext encrypted to ``recipients`` (public keys)."""
        ids = sorted(
            self._pub_to_id[pub] for pub in recipients if pub in self._pub_to_id
        )
        if not ids:
            raise ValueError("no registered recipients in the list")
        ids_str = ",".join(ids)
        return f"age-sim:{ids_str}:{plaintext.decode()}".encode()

    def decrypt(self, ciphertext: bytes, identity: str) -> bytes:
        """Decrypt ``ciphertext`` using ``identity``; raise PermissionError if
        the identity was not a recipient."""
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


# ─── (a) Verify-key rotation ──────────────────────────────────────────────────


def test_verify_key_rotation_old_cannot_decrypt_fresh_nightly() -> None:
    """§8.13.6 (a): After the per-dump verify key is rotated, the old
    verify identity can no longer decrypt the new nightly's ciphertext.
    The new verify identity and the persistent DR key both succeed.
    """
    enc = _InMemoryEncryptor()

    # Persistent DR recipient (survives across rotations).
    dr_pub, dr_id = "age1dr-persistent", "AGE-DR-PERSISTENT"
    enc.register(dr_id, dr_pub)

    # Verify key for nightly 1 (old, about to be rotated).
    verify_old_pub, verify_old_id = "age1verify-0001", "AGE-VERIFY-0001"
    enc.register(verify_old_id, verify_old_pub)

    # ── Nightly 1 (encrypted to DR + old verify key) ──────────────────
    nightly1 = enc.encrypt(b"nightly-dump-2025-01-01", [dr_pub, verify_old_pub])

    # Old verify CAN decrypt nightly 1 (it was a recipient).
    assert enc.decrypt(nightly1, verify_old_id) == b"nightly-dump-2025-01-01"

    # ── Key rotation: new per-dump verify key for nightly 2 ───────────
    verify_new_pub, verify_new_id = "age1verify-0002", "AGE-VERIFY-0002"
    enc.register(verify_new_id, verify_new_pub)

    # ── Nightly 2 (encrypted to DR + NEW verify key; old verify NOT included) ──
    nightly2 = enc.encrypt(b"nightly-dump-2025-01-02", [dr_pub, verify_new_pub])

    # New verify CAN decrypt nightly 2.
    assert enc.decrypt(nightly2, verify_new_id) == b"nightly-dump-2025-01-02"

    # DR key CAN decrypt nightly 2 (persistent recipient).
    assert enc.decrypt(nightly2, dr_id) == b"nightly-dump-2025-01-02"

    # ── Old verify key CANNOT decrypt nightly 2 ───────────────────────
    with pytest.raises(PermissionError):
        enc.decrypt(nightly2, verify_old_id)


def test_verify_key_rotation_old_dump_still_decryptable_by_old_key() -> None:
    """Complementary adversarial: the old verify key still decrypts its
    own nightly (no re-encryption of past dumps on rotation)."""
    enc = _InMemoryEncryptor()

    dr_pub, dr_id = "age1dr-persistent", "AGE-DR-PERSISTENT"
    verify_old_pub, verify_old_id = "age1verify-0001", "AGE-VERIFY-0001"
    verify_new_pub, _ = "age1verify-0002", "AGE-VERIFY-0002"

    enc.register(dr_id, dr_pub)
    enc.register(verify_old_id, verify_old_pub)

    nightly1 = enc.encrypt(b"nightly-dump-2025-01-01", [dr_pub, verify_old_pub])

    # Rotate (nightly 2 uses new key — this test focuses on nightly 1).
    enc.register("AGE-VERIFY-0002", verify_new_pub)

    # Old verify STILL decrypts its own nightly after rotation.
    assert enc.decrypt(nightly1, verify_old_id) == b"nightly-dump-2025-01-01"


# ─── (b) DR-key revocation ────────────────────────────────────────────────────


def test_dr_key_revocation_new_dump_not_decryptable_by_revoked_key() -> None:
    """§8.13.6 (b): Revoking k1 means the NEXT nightly is encrypted to
    k2 + k3 only; k1 cannot decrypt the new dump.
    """
    enc = _InMemoryEncryptor()

    k1_pub, k1_id = "age1dr1", "AGE-DR-KEY-1"
    k2_pub, k2_id = "age1dr2", "AGE-DR-KEY-2"
    k3_pub, k3_id = "age1dr3", "AGE-DR-KEY-3"

    for identity, pub in [(k1_id, k1_pub), (k2_id, k2_pub), (k3_id, k3_pub)]:
        enc.register(identity, pub)

    # ── Old dump: encrypted to all three keys ─────────────────────────
    old_dump = enc.encrypt(b"old-nightly-2025-01-01", [k1_pub, k2_pub, k3_pub])

    # ── Revoke k1: remove from active recipients list ─────────────────
    active_recipients = [k2_pub, k3_pub]  # k1_pub no longer included

    # ── New dump: encrypted to k2 + k3 only ───────────────────────────
    new_dump = enc.encrypt(b"new-nightly-2025-01-02", active_recipients)

    # New dump decryptable by k2 and k3.
    assert enc.decrypt(new_dump, k2_id) == b"new-nightly-2025-01-02"
    assert enc.decrypt(new_dump, k3_id) == b"new-nightly-2025-01-02"

    # ── k1 CANNOT decrypt new dump (revoked — not a recipient) ────────
    with pytest.raises(PermissionError):
        enc.decrypt(new_dump, k1_id)


def test_dr_key_revocation_old_dump_still_decryptable_by_all_three() -> None:
    """§8.13.6 (b) — no re-encryption: old dump remains decryptable by k1,
    k2, and k3 even after k1 is revoked (runbook doctrine: old archives
    are not re-encrypted; they are treated as 'trusted but compromised')."""
    enc = _InMemoryEncryptor()

    k1_pub, k1_id = "age1dr1", "AGE-DR-KEY-1"
    k2_pub, k2_id = "age1dr2", "AGE-DR-KEY-2"
    k3_pub, k3_id = "age1dr3", "AGE-DR-KEY-3"

    for identity, pub in [(k1_id, k1_pub), (k2_id, k2_pub), (k3_id, k3_pub)]:
        enc.register(identity, pub)

    old_dump = enc.encrypt(b"old-nightly-2025-01-01", [k1_pub, k2_pub, k3_pub])

    # Even after revocation (k1 excluded from new encryptions), the
    # already-encrypted old dump still contains k1 as a recipient.
    assert enc.decrypt(old_dump, k1_id) == b"old-nightly-2025-01-01"
    assert enc.decrypt(old_dump, k2_id) == b"old-nightly-2025-01-01"
    assert enc.decrypt(old_dump, k3_id) == b"old-nightly-2025-01-01"


# ─── (c) PG-secret age refusal ────────────────────────────────────────────────


def _build_agent_pg_age(pg_secret_age_checker: NoopPgSecretAgeChecker) -> MaintBackupAgent:
    """Build an agent with all other checks bypassed; only the PG-age gate under test."""
    return MaintBackupAgent(
        dump=NoopDumpExecutor(),
        verifier=NoopVerifier(),
        pruner=InMemoryPrunerStorage(),
        quarantine=InMemoryQuarantineStore(),
        disk=StaticDiskGauge(free_bytes=64 * 1024 ** 3),
        enforce_permissions=False,
        pg_secret_age_checker=pg_secret_age_checker,
    )


def test_pg_secret_age_121_refuses_with_fail_safe_token() -> None:
    """§8.13.6 (c): pg_secret_age_days=121 (> default cap 120) causes the
    agent to raise BackupPermissionError carrying fail_safe_pg_secret_expired."""
    checker = NoopPgSecretAgeChecker(age_days=121)
    with pytest.raises(BackupPermissionError) as exc_info:
        _build_agent_pg_age(checker)
    assert "fail_safe_pg_secret_expired" in str(exc_info.value)


def test_pg_secret_age_121_error_message_carries_observed_age() -> None:
    """§8.13.6 (c) adversarial: the error message includes the observed age
    (121) so the operator knows exactly what to rotate."""
    checker = NoopPgSecretAgeChecker(age_days=121)
    with pytest.raises(BackupPermissionError) as exc_info:
        _build_agent_pg_age(checker)
    msg = str(exc_info.value)
    assert "121" in msg, f"observed age not in message: {msg!r}"
