"""``ops.allowlist-show`` — Phase 8 §8.1 / §8.7.

Operator queries the active ``pattern_allowlist`` surface. Per the
§8.1 "no bypass channels" rule the CLI does NOT read PG directly;
instead it publishes ``maint.event.v1{kind=allowlist_show}`` and
the consumer (``maint.sec.v1``, lands in §8.7) responds with the
matching rows in ``maint.ack.v1.details.rows[]`` (capped per the
§8.15.5 details budget — oversize → operator narrows the filter or
queries the audit table out-of-band).

ALWAYS_SAFE (read-only query — see
:data:`xops.opsctl._classify.ALWAYS_SAFE`); no token required.
Until the §8.7 consumer ships, the publisher will exit with code
5 (``no_consumer_for_kind: pending Phase 8.7``); the audit row is
still written.
"""
from __future__ import annotations

import argparse
import re
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "allowlist-show"
KIND = "allowlist_show"

# Accept 'all', a bare source id, or '<source>:<rule_id>'.
_TARGET_RE = re.compile(r"^(all|[a-zA-Z0-9_.-]+(:[a-zA-Z0-9_.-]+)?)$")


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Show active pattern_allowlist rows (read-only).",
        description=(
            "Publishes maint.event.v1{kind=allowlist_show}. The CLI "
            "does NOT read PG directly — the §8.7 consumer responds "
            "in maint.ack.v1.details.rows[]. Filter via --target: "
            "'all', '<source>', or '<source>:<rule_id>'."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="'all', a source id, or '<source>:<rule_id>'.",
    )
    parser.add_argument(
        "--include-expired",
        action="store_true",
        help="Include rows in state='e' (expired). Default: active only.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if not _TARGET_RE.match(target):
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: --target must be 'all', '<source>', or "
            f"'<source>:<rule_id>'; got {target!r}\n"
        )
        return 64

    include_expired = bool(getattr(args, "include_expired", False))
    extra_payload: dict[str, Any] = {}
    if include_expired:
        extra_payload["include_expired"] = True

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
