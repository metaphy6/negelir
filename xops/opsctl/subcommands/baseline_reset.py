"""``ops.baseline-reset`` — Phase 7 §7.2 / Phase 8 §8.1.

Operator override resetting a single ``sec.scrape.v1`` source
fingerprint baseline (Welford running stats + SimHash). Used after
a deliberate upstream change — operator confirms the new shape is
legitimate and that the baseline should re-learn from scratch.

Reversible (the agent will re-baseline from the next batch of
samples), so **not** in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`. Audited; lock
protects against concurrent operator shells.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "baseline-reset"
KIND = "baseline_reset"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Reset a sec.scrape.v1 source baseline (operator override).",
        description=(
            "Publishes maint.event.v1{kind=baseline_reset} and waits "
            "for ack from sec.scrape.v1. Target is the source id "
            "(e.g. 'mackolik', 'nesine'). Reversible (agent rebuilds "
            "the baseline from subsequent samples)."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Source id (e.g. 'mackolik', 'nesine', 'tff').",
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
