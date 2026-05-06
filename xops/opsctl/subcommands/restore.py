"""``ops.restore`` — Phase 8 §8.1 / §8.3 / §8.12.

Operator-driven restore from a stored backup. ALWAYS_DESTRUCTIVE
(see :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`): without
``--destination-conn`` this REPLACES the live primary database
contents with the chosen dump. Even with ``--destination-conn``
(DR-drill mode), the operator must pass the typed ``--confirm``
token so a stray invocation cannot rewind production by accident.

`target` is the dump date in ``YYYY-MM-DD`` form — the consumer
(``maint.backup.v1``, lands in §8.3) resolves it to the on-disk
artefact (or pulls from the off-host replica when
``--from-offsite`` is set, per §8.12).

Until the backup agent ships, the publisher will exit with code 5
(``no_consumer_for_kind: pending Phase 8.3``); the audit row is
still written.
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "restore"
KIND = "restore"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Restore PG from a stored backup (DESTRUCTIVE — replaces live data).",
        description=(
            "Publishes maint.event.v1{kind=restore}. Destructive — "
            "passes through ALWAYS_DESTRUCTIVE token gate. "
            "Pass --destination-conn for non-destructive DR drills "
            "into a fresh PG instance (still requires --confirm)."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Dump date in YYYY-MM-DD form.",
    )
    parser.add_argument(
        "--from-offsite",
        action="store_true",
        help="Pull dump from the off-host replica (§8.12) instead of on-host PVC.",
    )
    parser.add_argument(
        "--destination-conn",
        default="",
        help=(
            "Override DSN — restore into a fresh PG instance instead "
            "of the live primary (DR-drill mode per §8.12)."
        ),
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Operator narration for the audit trail.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if not _DATE_RE.match(target):
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: --target must be YYYY-MM-DD; got {target!r}\n"
        )
        return 64

    from_offsite = bool(getattr(args, "from_offsite", False))
    destination_conn = str(getattr(args, "destination_conn", "") or "")
    reason = str(getattr(args, "reason", "") or "")

    extra_payload: dict[str, Any] = {}
    if from_offsite:
        extra_payload["from_offsite"] = True
    if destination_conn:
        extra_payload["destination_conn"] = destination_conn
    if reason:
        extra_payload["reason"] = reason

    salient: dict[str, Any] = {}
    if from_offsite:
        salient["from_offsite"] = True
    if destination_conn:
        # Folded into the typed-token preimage so the operator
        # cannot accidentally promote a DR-drill confirmation
        # into a production restore by dropping the flag.
        salient["destination_conn"] = destination_conn

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args=salient,
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
