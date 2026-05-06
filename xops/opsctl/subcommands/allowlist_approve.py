"""``ops.allowlist-approve`` — Phase 8 §8.1 / §8.7.

Operator promotes a ``pattern_allowlist`` row from state ``'p'``
(pending) to ``'a'`` (active). Publishes
``maint.event.v1{kind=allowlist_approve, target='<source>:<rule_id>'}``;
consumed by ``maint.sec.v1`` (lands in §8.7 — until then, exit
code 5 ``no_consumer_for_kind: pending Phase 8.7``).

Reversible via the §8.7 demote / expire surface; NOT in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`.
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "allowlist-approve"
KIND = "allowlist_approve"

_TARGET_RE = re.compile(r"^[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+$")


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Promote a pattern_allowlist row from pending to active.",
        description=(
            "Publishes maint.event.v1{kind=allowlist_approve}. Target "
            "is '<source>:<rule_id>' per §8.7 row addressing."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="'<source>:<rule_id>' (e.g. 'mackolik:rule_42').",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Justification recorded on the audit row.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if not _TARGET_RE.match(target):
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: --target must be '<source>:<rule_id>'; got {target!r}\n"
        )
        return 64

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
