"""``ops.bootstrap-key`` — Phase 8 §8.14.4 per-operator HMAC key generator.

Generates a 32-byte random key at ``~/.negelir/opsctl_key`` (mode 0600)
and prints the key_id (sha256(key_bytes)[:16]) to stdout.

If a key already exists, prints its key_id without overwriting.
The operator must then add the key_id to
``infra/maint/opsctl_operators.json`` and commit.
"""
from __future__ import annotations

import argparse
from typing import Optional

from .._exit_codes import ExitCode
from .._op_signature import bootstrap_key

NAME = "bootstrap-key"


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        NAME,
        help="Phase 8 §8.14.4 — generate per-operator HMAC key (mode 0600).",
    )
    p.add_argument(
        "--operator-email",
        required=True,
        help="Operator email used for canonical key_id derivation.",
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace, *, bus: Optional[object] = None) -> int:
    """Generate the operator key or print the existing key_id."""
    from ai.common.config import Config  # noqa: PLC0415

    cfg = Config()
    try:
        bootstrap_key(cfg, operator_email=str(args.operator_email))
    except (OSError, PermissionError, ValueError) as exc:
        import sys  # noqa: PLC0415

        sys.stderr.write(f"ops.bootstrap-key: {exc}\n")
        return int(ExitCode.GENERIC_FAILURE)
    return int(ExitCode.OK)
