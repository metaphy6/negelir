"""``ops.dlq-unfreeze`` — Phase 8 §8.5 C2.

Operator lifts a poison-pattern freeze on a single DLQ topic.
Publishes ``maint.event.v1{kind=dlq_unfreeze, target}`` and waits
for the ack from ``maint.dlq.v1``.

Idempotent: the supervisor returns ``accepted=true`` even when the
topic was not frozen (per §8.13.5 idempotency posture). Reversible
(the next poison burst re-freezes), so SAFE tier.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "dlq-unfreeze"
KIND = "dlq_unfreeze"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Lift a maint.dlq.v1 poison-pattern freeze on a DLQ topic.",
        description=(
            "Publishes maint.event.v1{kind=dlq_unfreeze}. The "
            "supervisor drops the topic from its frozen set and "
            "resets the per-topic poison-window log."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="DLQ topic to unfreeze (must end in '.dlq').",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text justification carried in the envelope.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if not target.endswith(".dlq"):
        import sys

        sys.stderr.write(
            f"opsctl {NAME}: --target must end in '.dlq' (got {target!r})\n"
        )
        from .._exit_codes import ExitCode

        return int(ExitCode.BAD_USAGE)

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
