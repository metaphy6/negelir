"""``ops.denylist-clear`` — Phase 7 §7.3 / Phase 8 §8.1.

Operator override clearing a single ``sec.rate.v1`` denylist entry.
Publishes ``maint.event.v1{kind=denylist_clear, target, ...}`` and
waits for the ack from ``sec.rate.v1`` (the only consumer per
:mod:`ai.swarm.agents.maint._ack_routing`).

Reversible (the rate limiter will re-deny on the next abuse signal),
so this subcommand is **not** in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`. It is, however,
audited and protected by the per-(host, kind, target) re-entrancy
lock from :mod:`xops.opsctl._lock`.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "denylist-clear"
KIND = "denylist_clear"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Clear a sec.rate.v1 denylist entry (operator override).",
        description=(
            "Publishes maint.event.v1{kind=denylist_clear} and waits "
            "for ack from sec.rate.v1. Target is the masked subject "
            "(e.g. '203.0.113.0/24', '2001:db8::/64'). Reversible."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Masked subject string per server/internal/sec/xff.go SubjectKey.",
    )
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
