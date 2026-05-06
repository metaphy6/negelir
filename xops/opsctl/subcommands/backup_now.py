"""``ops.backup-now`` — Phase 8 §8.1 / §8.3.

Operator forces an immediate nightly-shape PG dump + restore-verify
cycle outside the cron window. Publishes
``maint.event.v1{kind=backup_now, target='pg'}``; consumed by
``maint.backup.v1`` (lands in §8.3 — until then, exit code 5
``no_consumer_for_kind: pending Phase 8.3``).

Reversible (the consumer simply runs the standard pipeline and
the resulting artefact is additive); NOT in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "backup-now"
KIND = "backup_now"

# v1 only recognises 'pg' — multiple-DB support widens the
# consumer-side allow-list, not the schema. Validating here keeps
# bad targets from reaching the bus.
_RECOGNISED_TARGETS = frozenset({"pg"})


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Force an immediate PG dump + restore-verify (operator override).",
        description=(
            "Publishes maint.event.v1{kind=backup_now}. Reversible — "
            "the consumer runs the standard nightly pipeline outside "
            "its cron window. Pass --skip-prune to keep the §8.3 TTL "
            "prune phase off (useful for emergency snapshots)."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Database key (v1: 'pg' is the only recognised value).",
    )
    parser.add_argument(
        "--skip-prune",
        action="store_true",
        help="Run dump + verify but skip the §8.3 TTL prune phase.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text justification (e.g. 'pre-deploy snapshot').",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if target not in _RECOGNISED_TARGETS:
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: unknown target {target!r}; "
            f"expected one of {sorted(_RECOGNISED_TARGETS)}\n"
        )
        return 64  # ExitCode.BAD_USAGE

    skip_prune = bool(getattr(args, "skip_prune", False))
    reason = str(getattr(args, "reason", "") or "")
    extra_payload: dict[str, Any] = {}
    if skip_prune:
        extra_payload["skip_prune"] = True
    if reason:
        extra_payload["reason"] = reason

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args={"skip_prune": skip_prune} if skip_prune else {},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
