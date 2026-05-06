"""``ops.denylist-decimate-now`` — Phase 8 §8.8.

Operator forces an immediate denylist decimation sweep. Publishes
``maint.event.v1{kind=denylist_decimate_now, target}`` and waits
for the ack from ``maint.sec.v1``.

The sweep normally runs autonomously when the Redis denylist
crosses ``cfg.sec_denylist_decimate_threshold``. This subcommand
short-circuits the threshold (operator-attested capacity-pressure
relief or end-of-incident clean-up).

SAFE tier — the sweeper only halves TTL of the oldest decile per
§7.3 sub-bullet (b); critical-agent gate is N/A (target is a Redis
key prefix, not an agent id).
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, run_publish

NAME = "denylist-decimate-now"
KIND = "denylist_decimate_now"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Force an immediate denylist decimation sweep.",
        description=(
            "Publishes maint.event.v1{kind=denylist_decimate_now}. "
            "maint.sec.v1 halves the TTL on the oldest decile of "
            "denylist keys matching --target."
        ),
    )
    parser.add_argument(
        "--target",
        default="all",
        help="Sweep scope: 'all' or a specific subject prefix (default: all).",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text justification carried in the envelope.",
    )
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag (default: opsctl).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Typed confirmation token (unused at SAFE tier; kept for symmetry).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate + print envelope; do NOT publish.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    reason = str(getattr(args, "reason", "") or "")
    extra_payload: dict[str, Any] = {}
    if reason:
        extra_payload["reason"] = reason

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args={},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
