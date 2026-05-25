"""ops.allowlist-rehash - Phase 8 S8.16.10.

Operator-triggered legacy SHA -> HMAC re-fingerprint request.
Publishes maint.event.v1{kind=allowlist_rehash}.
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "allowlist-rehash"
KIND = "allowlist_rehash"

_TARGET_RE = re.compile(r"^(all|[a-zA-Z0-9_.-]+)$")


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Trigger allowlist legacy-row rehash (SHA -> HMAC).",
        description=(
            "Publishes maint.event.v1{kind=allowlist_rehash}. "
            "Target is 'all' or a source id."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="'all' or a source id (e.g. 'mackolik').",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Optional per-run row batch size; 0 lets consumer default.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text operator note for the audit trail.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if not _TARGET_RE.match(target):
        import sys

        sys.stderr.write(
            f"opsctl {NAME}: --target must be 'all' or '<source>'; got {target!r}\n"
        )
        return 64

    batch_size = int(getattr(args, "batch_size", 0) or 0)
    if batch_size < 0:
        import sys

        sys.stderr.write(
            f"opsctl {NAME}: --batch-size must be >= 0; got {batch_size}\n"
        )
        return 64

    extra_payload: dict[str, Any] = {}
    if batch_size:
        extra_payload["batch_size"] = batch_size
    reason = str(getattr(args, "reason", "") or "")
    if reason:
        extra_payload["reason"] = reason

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args={"batch_size": batch_size} if batch_size else {},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)
