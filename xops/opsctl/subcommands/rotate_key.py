"""``ops.rotate-key`` — Phase 8 §8.15.4.

Operator rotates a per-operator HMAC key. Records the old key_id as
revoked and prompts the operator to add the new key_id (generated
via ``make ops.bootstrap-key``) to ``infra/maint/opsctl_operators.json``.

Emits ``maint.event.v1{kind=opsctl_key_rotated, prev_key_id, new_key_id,
operator_email}`` through the destructive-token gate.

ALWAYS_DESTRUCTIVE: rotation marks the previous key irrevocably revoked.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "rotate-key"
KIND = "opsctl_key_rotated"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Rotate an operator HMAC key (DESTRUCTIVE).",
        description=(
            "Publishes maint.event.v1{kind=opsctl_key_rotated}. "
            "The operator must also: (1) run make ops.bootstrap-key to generate "
            "the new key, (2) add new_key_id to infra/maint/opsctl_operators.json, "
            "(3) run ops.revoke-key to mark the old key revoked, "
            "(4) commit the updated file. ALWAYS DESTRUCTIVE."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Free-form label (e.g. \'scheduled-rotation-Q2-2026\').",
    )
    parser.add_argument(
        "--prev-key-id",
        required=True,
        help="16-hex-char public key_id of the key being rotated out.",
    )
    parser.add_argument(
        "--new-key-id",
        required=True,
        help="16-hex-char public key_id of the replacement key.",
    )
    parser.add_argument(
        "--operator-email",
        required=True,
        help="Email of the operator whose key is being rotated.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Optional reason for rotation (scheduled, compromise, etc.).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    prev_key_id = str(args.prev_key_id).strip()
    new_key_id = str(args.new_key_id).strip()
    if len(prev_key_id) != 16 or len(new_key_id) != 16:
        sys.stderr.write(
            f"opsctl {NAME}: --prev-key-id and --new-key-id must each be exactly 16 hex chars\n"
        )
        return 64

    if prev_key_id == new_key_id:
        sys.stderr.write(
            f"opsctl {NAME}: --prev-key-id and --new-key-id must differ\n"
        )
        return 64

    extra_payload: dict[str, Any] = {
        "prev_key_id": prev_key_id,
        "new_key_id": new_key_id,
        "operator_email": str(args.operator_email),
    }
    reason = str(getattr(args, "reason", "") or "")
    if reason:
        extra_payload["reason"] = reason

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
