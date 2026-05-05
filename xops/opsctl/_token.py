"""xops.opsctl — typed-token derivation for destructive ops (Phase 8 §8.1).

Per ROADMAP §8.1 binding, destructive subcommands MUST refuse to
publish without ``--confirm <token>`` where ``<token>`` equals
``sha256(f"{cmd}|{target}|{salient_args}")[:8]``. The CLI prints the
expected token on first attempt (when ``--confirm`` is missing or
mismatched) so the operator copy-pastes — defeats accidental
shell-history re-runs while preserving runbook ergonomics.

The derivation is deliberately deterministic and stable across CLI
invocations on the same operator host: the token is a function of
the *command shape*, not of wall-clock or random salt. Two operators
on different hosts targeting the same denylist subnet will compute
the **same** token; this is intentional — the token is a guard
against fat-fingered shell-history, not a per-operator authn factor.
A future §8.15.4 lands per-operator HMAC-keyed signatures that
**do** key on operator identity.

Salient args are subcommand-specific; each subcommand picks the
fields that meaningfully change the operation's blast radius (e.g.
``replicas`` for ``ops.scale``, ``drop`` for ``ops.dlq-replay``).
``None`` and empty string are dropped to keep the canonical form
deterministic across argparse defaults.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping

#: Length of the printed token (hex chars from sha256). 8 hex chars
#: ≈ 32 bits of preimage resistance — sufficient for shell-history
#: defense; not a security boundary against an active attacker.
TOKEN_LEN: int = 8


def _canonicalize(value: Any) -> str:
    """Render a salient-arg value deterministically.

    Booleans → ``"true"``/``"false"`` (so ``--drop`` flips the token).
    Numbers → ``str(value)``; sequences → comma-joined sorted strings;
    mappings → ``"k=v"`` pairs sorted by key. Empty string and ``None``
    are sentinel-rendered as ``""`` (caller drops them upstream).
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return ",".join(f"{k}={_canonicalize(v)}" for k, v in sorted(value.items()))
    if isinstance(value, Iterable):
        return ",".join(sorted(_canonicalize(v) for v in value))
    return str(value)


def derive_confirm_token(
    *,
    subcommand: str,
    target: str,
    salient_args: Mapping[str, Any] | None = None,
) -> str:
    """Return the 8-char hex token expected for ``--confirm``.

    The pipe-joined preimage is
    ``"{subcommand}|{target}|k1=v1,k2=v2,..."`` with salient args
    sorted by key and falsy/None values dropped. Stable across CLI
    invocations.
    """
    sa = salient_args or {}
    canon_pairs = []
    for k in sorted(sa.keys()):
        v = sa[k]
        rendered = _canonicalize(v)
        if rendered == "":
            # Dropping empty values keeps default-arg invocations
            # collapsed onto the bare-target token.
            continue
        canon_pairs.append(f"{k}={rendered}")
    preimage = f"{subcommand}|{target}|{','.join(canon_pairs)}"
    digest = hashlib.sha256(preimage.encode("utf-8")).hexdigest()
    return digest[:TOKEN_LEN]


__all__ = ["TOKEN_LEN", "derive_confirm_token"]
