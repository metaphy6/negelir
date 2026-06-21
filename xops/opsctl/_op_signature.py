"""xops.opsctl - Publisher-side operator-key management (Phase 8 S8.14.4).

Every opsctl-published envelope carries
    op_signature = HMAC-SHA256(key=<per-operator-key>,
                               msg=f"{request_id}|{kind}|{target}|{produced_at}")

The per-operator key lives at ``~/.negelir/opsctl_key`` (mode 0600,
32 random bytes). Canonical key_id derivation is defined in
``xops.maint.key_id`` (Phase 8 §8.16.14).

``make ops.bootstrap-key`` generates the key file on first run via
:func:`bootstrap_key`.

Boundary rule: this module MUST NOT import ``redis`` directly.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from common.config import Config
from xops.maint.key_id import derive

_KEY_LEN = 32  # bytes
_DEFAULT_KEY_PATH = Path.home() / ".negelir" / "opsctl_key"


def key_id_from_bytes(raw_key: bytes, operator_email: str) -> str:
        """Derive the public key-id via the canonical Phase 8 §8.16.14 formula.

        Canonical formula:
            ``sha256("negelir-opsctl-key-v1|<operator_email>|<base64(key_bytes)>")[:16]``
        """
        return derive(operator_email=operator_email, key_bytes=raw_key)


def _resolve_key_path(cfg: Config) -> Path:
    p = cfg.opsctl_key_path.strip()
    return Path(p).expanduser() if p else _DEFAULT_KEY_PATH


def load_operator_key(cfg: Config) -> bytes:
    """Read the 32-byte operator key from disk (mode 0600 required).

    Exits with a message on stderr if the key file is missing or has
    wrong permissions.  Call :func:`bootstrap_key` on first run.
    """
    path = _resolve_key_path(cfg)
    if not path.exists():
        sys.stderr.write(
            f"opsctl: operator key not found at {path}\n"
            "  Run: make ops.bootstrap-key\n"
        )
        raise FileNotFoundError(f"opsctl_key missing: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        sys.stderr.write(
            f"opsctl: key file {path} has unsafe permissions "
            f"({oct(mode)}) — must be 0600\n"
        )
        raise PermissionError(f"opsctl_key permissions unsafe: {path}")
    raw = path.read_bytes()
    if len(raw) < _KEY_LEN:
        raise ValueError(
            f"opsctl_key too short: expected {_KEY_LEN} bytes, "
            f"got {len(raw)} at {path}"
        )
    return raw[:_KEY_LEN]


def compute_signature(
    key: bytes,
    request_id: str,
    kind: str,
    target: str,
    produced_at: str,
) -> str:
    """Return HMAC-SHA256 hex over the canonical message fields.

    The preimage is ``f"{request_id}|{kind}|{target}|{produced_at}"``.
    All fields are part of the payload so consumers can recompute the
    MAC without any out-of-band state.
    """
    msg = f"{request_id}|{kind}|{target}|{produced_at}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def inject_signature(payload: dict, cfg: Config) -> Optional[str]:
    """Load key, compute op_signature and inject into ``payload`` in place.

    Returns the key_id that signed the envelope, or ``None`` if signature
    is disabled (``cfg.opsctl_require_signature=False``).

    Mutates ``payload`` directly (payload is a mutable dict; the
    ``Message`` dataclass is frozen but its payload dict is not).
    """
    if not cfg.opsctl_require_signature:
        return None
    key = load_operator_key(cfg)
    operator_email = str(payload.get("client_id", "opsctl"))
    kid = key_id_from_bytes(key, operator_email=operator_email)
    sig = compute_signature(
        key,
        request_id=str(payload.get("request_id", "")),
        kind=str(payload.get("kind", "")),
        target=str(payload.get("target", "")),
        produced_at=str(payload.get("produced_at", "")),
    )
    payload["op_signature"] = sig
    payload["op_key_id"] = kid
    return kid


def bootstrap_key(cfg: Config, operator_email: str) -> str:
    """Generate a fresh 32-byte key and write it to the key path (mode 0600).

    Prints the key_id to stdout and instructions to add it to
    ``infra/maint/opsctl_operators.json``.

    Returns the key_id string.
    """
    normalized_email = operator_email.strip().lower()
    if not normalized_email:
        raise ValueError("operator_email is required")

    added_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    path = _resolve_key_path(cfg)
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise PermissionError(
                f"opsctl_key has unsafe mode {oct(mode)} at {path}; expected 0o600"
            )
        existing_key = path.read_bytes()
        kid = key_id_from_bytes(existing_key[:_KEY_LEN], operator_email=normalized_email)
        sys.stdout.write(
            f"opsctl: key already exists at {path} (key_id={kid})\n"
            "  To regenerate, delete the file and re-run.\n"
            "  Add to infra/maint/opsctl_operators.json:\n"
            f'    "{kid}": {{"email": "{normalized_email}", "added_at": "{added_at}", "revoked_at": null}}\n'
        )
        return kid
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    raw = secrets.token_bytes(_KEY_LEN)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    kid = key_id_from_bytes(raw, operator_email=normalized_email)
    sys.stdout.write(
        f"opsctl: key generated at {path} (key_id={kid})\n"
        "  Add to infra/maint/opsctl_operators.json:\n"
        f'    "{kid}": {{"email": "{normalized_email}", "added_at": "{added_at}", "revoked_at": null}}\n'
        "  Then commit infra/maint/opsctl_operators.json.\n"
    )
    return kid


__all__ = [
    "key_id_from_bytes",
    "load_operator_key",
    "compute_signature",
    "inject_signature",
    "bootstrap_key",
]
