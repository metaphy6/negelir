"""``ops.quarantine-clear`` — Phase 7 §7.5 / Phase 8 §8.1, §8.7.

Operator-driven false-positive clearance: clears a quarantined
sample AND signals the §8.7 ``maint.sec.v1`` reactor to evaluate
the rule + source for allowlist promotion (autolearn-on) or
operator-approval queueing (autolearn-off, default).

The §8.7 consumer agent has not landed yet; until it does, this
subcommand publishes the envelope but exits with
:attr:`ExitCode.NO_CONSUMER_FOR_KIND` (5) — the routing table at
:mod:`ai.swarm.agents.maint._ack_routing` documents the pending
landing in ``KINDS_PENDING_CONSUMER_LANDING`` so this is intentional,
not a regression.

Operators can still use ``--dry-run`` today to validate envelope
shape against the per-kind sub-schema.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "quarantine-clear"
KIND = "quarantine_clear"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Clear a quarantine sample AS false-positive (Phase 8.7 consumer pending).",
        description=(
            "Publishes maint.event.v1{kind=quarantine_clear}. The §8.7 "
            "maint.sec.v1 reactor (allowlist FP feedback loop) has not "
            "landed yet, so this currently exits 5 (no_consumer_for_kind) "
            "after publish. Use --dry-run for envelope validation."
        ),
    )
    add_common_publish_args(parser, target_help="Sample id to clear.")
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=args.target,
        client_id=args.client_id,
        salient_args={},
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
