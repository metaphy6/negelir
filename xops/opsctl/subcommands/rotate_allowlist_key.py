"""ops.rotate-allowlist-key - Phase 8 S8.16.10.

Operator-triggered allowlist HMAC key rotation request.
Publishes maint.event.v1{kind=allowlist_rotate_key}.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "rotate-allowlist-key"
KIND = "allowlist_rotate_key"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Trigger allowlist HMAC key rotation.",
        description=(
            "Publishes maint.event.v1{kind=allowlist_rotate_key}. "
            "Consumer rotates key material and re-fingerprints active rows."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Rotation label (default: 'allowlist_hmac').",
    )
    parser.set_defaults(target="allowlist_hmac")
    parser.add_argument(
        "--no-rehash",
        action="store_true",
        help="Request key rotation without immediate rehash pass.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text operator note for the audit trail.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(getattr(args, "target", "") or "").strip()
    if not target:
        import sys

        sys.stderr.write(f"opsctl {NAME}: --target must be non-empty\n")
        return 64

    rehash = not bool(getattr(args, "no_rehash", False))
    reason = str(getattr(args, "reason", "") or "")

    extra_payload: dict[str, Any] = {"rehash": rehash}
    if reason:
        extra_payload["reason"] = reason

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args={"rehash": rehash},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)
