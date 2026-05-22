"""``ops.revoke-key`` — Phase 8 §8.15.4.

Operator revokes a per-operator HMAC key. Emits
``maint.event.v1{kind=opsctl_key_revoked, key_id, revoked_by, reason}``
and records ``revoked_at`` + ``revocation_reason`` in
``infra/maint/opsctl_operators.json`` (the operator must commit the
updated file after running this command).

ALWAYS_DESTRUCTIVE (see :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`):
a revoked key cannot be un-revoked via opsctl (only a manual JSON edit can
re-activate it, which requires a reviewer and a git commit).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "revoke-key"
KIND = "opsctl_key_revoked"

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_OPERATORS_FILE = _REPO_ROOT / "infra" / "maint" / "opsctl_operators.json"


def _resolve_operators_file(args: argparse.Namespace) -> Path:
    path_str = getattr(args, "operators_file", "") or ""
    return Path(path_str).expanduser() if path_str else _DEFAULT_OPERATORS_FILE


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Revoke an operator HMAC key (DESTRUCTIVE).",
        description=(
            "Publishes maint.event.v1{kind=opsctl_key_revoked}. "
            "Sets revoked_at in infra/maint/opsctl_operators.json. "
            "Operator must commit the updated file. ALWAYS DESTRUCTIVE."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Free-form label (e.g. \'operator-email-departure\').",
    )
    parser.add_argument(
        "--key-id",
        required=True,
        help="16-hex-char public key_id to revoke (from opsctl_operators.json).",
    )
    parser.add_argument(
        "--revoked-by",
        required=True,
        help="Operator email authorising the revocation.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Justification for revocation (e.g. \'employee departure\').",
    )
    parser.add_argument(
        "--operators-file",
        default="",
        help=(
            "Override path to opsctl_operators.json "
            "(default: infra/maint/opsctl_operators.json)."
        ),
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    key_id = str(args.key_id).strip()
    if len(key_id) != 16:
        sys.stderr.write(
            f"opsctl {NAME}: --key-id must be exactly 16 hex chars, got {len(key_id)}\n"
        )
        return 64

    ops_path = _resolve_operators_file(args)
    if not ops_path.exists():
        sys.stderr.write(
            f"opsctl {NAME}: operators file not found: {ops_path}\n"
        )
        return 1

    try:
        data = json.loads(ops_path.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"opsctl {NAME}: cannot read operators file: {exc}\n")
        return 1

    operators: dict = data.get("operators", {})
    if key_id not in operators:
        sys.stderr.write(
            f"opsctl {NAME}: key_id {key_id!r} not found in operators file\n"
        )
        return 1

    if operators[key_id].get("revoked_at") is not None:
        sys.stderr.write(
            f"opsctl {NAME}: key_id {key_id!r} is already revoked\n"
        )
        return 1

    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    operators[key_id]["revoked_at"] = now_utc
    operators[key_id]["revocation_reason"] = str(args.reason)

    # Atomic write (temp+rename; the file is small)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=ops_path.parent, prefix=".opsctl_operators_", suffix=".json.tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, ops_path)
    except Exception as exc:
        with contextlib.suppress(Exception):
            os.unlink(tmp_path)
        sys.stderr.write(f"opsctl {NAME}: failed to update operators file: {exc}\n")
        return 1

    sys.stdout.write(
        f"opsctl {NAME}: key_id={key_id} revoked_at={now_utc}\n"
        f"  Commit infra/maint/opsctl_operators.json to persist the revocation.\n"
    )

    extra_payload: dict[str, Any] = {
        "key_id": key_id,
        "revoked_by": str(args.revoked_by),
        "reason": str(args.reason),
    }

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=str(args.target),
        client_id="opsctl",
        extra_payload=extra_payload,
        json_output=getattr(args, "json", False),
        dry_run=getattr(args, "dry_run", False),
        confirm=getattr(args, "confirm", ""),
    )
    return run_publish(spec, bus=bus)
