"""``ops.verify-key-id`` -- Phase 8 §8.16.14 self-verification.

Reads the local operator key file + caller-supplied email, recomputes
the canonical key_id, and asserts it matches the entry in
``infra/maint/opsctl_operators.json``.

Exit codes:
  * ``OK`` (0)            -- key_id matches the registry entry
  * ``KEY_ID_DRIFT`` (13) -- computed key_id does not match registry entry, or
                             the operator is not in the registry
  * ``GENERIC_FAILURE``    -- key file missing / bad permissions /
                             registry file unreadable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .._exit_codes import ExitCode

NAME = "verify-key-id"

_OPERATORS_JSON = (
    Path(__file__).resolve().parents[4] / "infra" / "maint" / "opsctl_operators.json"
)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        NAME,
        help=(
            "Phase 8 §8.16.14 -- verify local key matches the registry entry. "
            "Exits KEY_ID_DRIFT (13) on mismatch."
        ),
    )
    p.add_argument(
        "--operator-email",
        required=True,
        metavar="EMAIL",
        help="Operator email whose key_id entry is checked in opsctl_operators.json.",
    )
    p.add_argument(
        "--operators-json",
        default=None,
        metavar="PATH",
        help=f"Override path to opsctl_operators.json (default: {_OPERATORS_JSON})",
    )
    p.set_defaults(func=run)
    return p


def run(args: argparse.Namespace, *, bus: Optional[object] = None) -> int:
    """Recompute key_id and assert it matches the registry."""
    from common.config import Config  # noqa: PLC0415
    from xops.opsctl._op_signature import key_id_from_bytes, load_operator_key  # noqa: PLC0415

    operator_email = str(args.operator_email).strip().lower()
    if not operator_email:
        sys.stderr.write("ops.verify-key-id: --operator-email is required\n")
        return int(ExitCode.BAD_USAGE)

    cfg = Config()
    try:
        raw_key = load_operator_key(cfg)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        sys.stderr.write(f"ops.verify-key-id: {exc}\n")
        sys.stderr.write("  Run: make ops.bootstrap-key OPERATOR=<email>\n")
        return int(ExitCode.GENERIC_FAILURE)

    computed_kid = key_id_from_bytes(raw_key, operator_email=operator_email)

    registry_path = Path(args.operators_json) if args.operators_json else _OPERATORS_JSON
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(
            f"ops.verify-key-id: cannot read {registry_path}: {exc}\n"
        )
        return int(ExitCode.GENERIC_FAILURE)

    operators: dict = registry.get("operators", {})
    if computed_kid not in operators:
        _drift(
            computed_kid,
            operator_email,
            reason=f"computed key_id '{computed_kid}' not found in registry",
        )
        return int(ExitCode.KEY_ID_DRIFT)

    entry = operators[computed_kid]
    registered_email = str(entry.get("email", "")).strip().lower()
    if registered_email != operator_email:
        _drift(
            computed_kid,
            operator_email,
            reason=(
                f"registry email '{registered_email}' "
                f"does not match supplied email '{operator_email}'"
            ),
        )
        return int(ExitCode.KEY_ID_DRIFT)

    revoked_at = entry.get("revoked_at")
    if revoked_at:
        sys.stderr.write(
            f"ops.verify-key-id: key_id '{computed_kid}' is revoked "
            f"(revoked_at={revoked_at})\n"
        )
        return int(ExitCode.KEY_ID_DRIFT)

    sys.stdout.write(
        f"ops.verify-key-id: OK -- key_id='{computed_kid}' matches registry "
        f"for '{operator_email}'\n"
    )
    return int(ExitCode.OK)


def _drift(computed_kid: str, operator_email: str, *, reason: str) -> None:
    sys.stderr.write(
        f"ops.verify-key-id: key_id_drift -- {reason}\n"
        "  Runbook: your local key does not match the registry entry.\n"
        f"  Recomputed key_id : {computed_kid}\n"
        f"  Operator email    : {operator_email}\n"
        "  Resolution options:\n"
        "    1. If your key was regenerated: re-run 'make ops.bootstrap-key "
        "OPERATOR=<email>' and update infra/maint/opsctl_operators.json.\n"
        "    2. If the registry was updated without your knowledge: contact "
        "a co-signer to verify the PR history.\n"
        "    3. If you are new: 'make ops.bootstrap-key OPERATOR=<email>' "
        "to generate your key, then add the printed entry to the registry.\n"
    )
