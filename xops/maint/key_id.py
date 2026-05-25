"""Canonical opsctl operator key-id derivation helpers.

Phase 8 §8.16.14 pins a reproducible formula so reviewers can
mechanically validate ``infra/maint/opsctl_operators.json`` entries.
"""

from __future__ import annotations

import base64
import hashlib

DOMAIN_SEPARATOR = "negelir-opsctl-key-v1"


def derive(operator_email: str, key_bytes: bytes) -> str:
    """Return canonical key_id (16 hex chars) for an operator key.

    Formula:
      sha256("negelir-opsctl-key-v1|<email>|<base64(key_bytes)>")[:16]
    """
    email = operator_email.strip().lower()
    if not email:
        raise ValueError("operator_email is required for canonical key_id derivation")
    key_b64 = base64.b64encode(key_bytes).decode("ascii")
    preimage = f"{DOMAIN_SEPARATOR}|{email}|{key_b64}".encode("utf-8")
    return hashlib.sha256(preimage).hexdigest()[:16]


def derive_operator_key_id(operator_email: str, key_bytes: bytes) -> str:
    """Backward-compatible alias for the canonical key-id derivation helper."""
    return derive(operator_email=operator_email, key_bytes=key_bytes)


__all__ = ["DOMAIN_SEPARATOR", "derive", "derive_operator_key_id"]
