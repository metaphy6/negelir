"""``ops.allowlist-extend`` — Phase 8 §8.1 / §8.7.

Operator extends the lifetime of a ``pattern_allowlist`` row
(resets its TTL clock). Publishes
``maint.event.v1{kind=allowlist_extend, target='<source>:<rule_id>'}``;
consumed by ``maint.sec.v1`` (lands in §8.7 — until then, exit
code 5 ``no_consumer_for_kind: pending Phase 8.7``).

Reversible (the row simply ages out again at the new TTL); NOT in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`.
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "allowlist-extend"
KIND = "allowlist_extend"

_TARGET_RE = re.compile(r"^[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+$")
_TTL_MAX_S = 7_776_000  # 90 days, matches sub-schema cap


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Extend the TTL of a pattern_allowlist row (operator override).",
        description=(
            "Publishes maint.event.v1{kind=allowlist_extend}. Target "
            "is '<source>:<rule_id>' per §8.7 row addressing."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="'<source>:<rule_id>' (e.g. 'mackolik:rule_42').",
    )
    parser.add_argument(
        "--ttl-s",
        type=int,
        default=0,
        help=(
            "New TTL in seconds (1..7776000 = 90d). 0 lets the consumer "
            "apply its default."
        ),
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text operator note carried in the envelope.",
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

    ttl_s = int(getattr(args, "ttl_s", 0) or 0)
    if ttl_s and (ttl_s < 1 or ttl_s > _TTL_MAX_S):
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: --ttl-s must be 1..{_TTL_MAX_S} (90d); got {ttl_s}\n"
        )
        return 64

    reason = str(getattr(args, "reason", "") or "")
    extra_payload: dict[str, Any] = {}
    if ttl_s:
        extra_payload["ttl_s"] = ttl_s
    if reason:
        extra_payload["reason"] = reason

    salient: dict[str, Any] = {}
    if ttl_s:
        salient["ttl_s"] = ttl_s

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
