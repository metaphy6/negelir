"""``ops.dlq-resume`` — Phase 8 §8.1 / §8.5 / §8.13.5.

Canonical alias of :mod:`xops.opsctl.subcommands.dlq_unfreeze`.

The §8.13.5 idempotency-matrix doctrine uses the verb ``resume``
across the maint plane (paired with ``maint-pause`` / ``maint-resume``);
the original §8.5 implementation shipped under the verb ``unfreeze``
because it lifts a poison-pattern *freeze*. Both names are kept on
the CLI surface so operator runbooks that branch on either verb keep
working — they publish the SAME ``maint.event.v1{kind=dlq_unfreeze}``
envelope and the same consumer (``maint.dlq.v1``) acks both. Adding
a third name later is forbidden — pick one and deprecate the other
in a doctrine bump.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from . import dlq_unfreeze

# Re-export the underlying KIND so registry tests treat the alias as
# the same wire kind. Adding a new KIND for the alias would split
# the consumer's idempotency ledger and break the §8.13.5 matrix.
KIND = dlq_unfreeze.KIND
NAME = "dlq-resume"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Lift a maint.dlq.v1 poison-pattern freeze (alias of dlq-unfreeze).",
        description=(
            "Canonical alias of ops.dlq-unfreeze per §8.13.5 idempotency "
            "matrix doctrine. Publishes the SAME maint.event.v1 envelope; "
            "operator runbooks may use either verb."
        ),
    )
    # Re-use the underlying parser layout exactly — same flags,
    # same defaults, same target syntax. The trick: rebuild the
    # arg surface here rather than calling dlq_unfreeze.add_parser
    # (which would register the wrong NAME).
    parser.add_argument(
        "--target",
        required=True,
        help="DLQ topic name (e.g. 'predict.vote.dlq').",
    )
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag (default: opsctl).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Reserved (alias inherits dlq-unfreeze's SAFE classification).",
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
    # Delegate straight through — same envelope, same consumer.
    return dlq_unfreeze.run(args, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
