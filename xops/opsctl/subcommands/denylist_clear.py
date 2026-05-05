"""``ops.denylist-clear`` — Phase 7 §7.3 / Phase 8 §8.1.

Operator override clearing a single ``sec.rate.v1`` denylist entry.
Publishes ``maint.event.v1{kind=denylist_clear, target, ...}`` and
waits for the ack from ``sec.rate.v1`` (the only consumer per
:mod:`ai.swarm.agents.maint._ack_routing`).

This subcommand is **not** in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`: clearing a denylist
entry is reversible (the rate limiter will re-deny the subject on
the next abuse signal). It is, however, audited.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

from ai.common.config import Config

from .._audit import append_audit_row, make_row
from .._exit_codes import ExitCode
from .._publish import build_envelope, publish_event

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
    parser.add_argument(
        "--target",
        required=True,
        help="Masked subject string per server/internal/sec/xff.go SubjectKey.",
    )
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag carried in the envelope payload (default: opsctl).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    cfg = Config()
    target = args.target
    client_id = args.client_id
    message = build_envelope(kind=KIND, target=target, client_id=client_id)
    result = publish_event(bus, message)

    summary: dict[str, Any] = {
        "op": NAME,
        "kind": KIND,
        "target": target,
        "request_id": result.request_id,
        "exit_code": int(result.exit_code),
        "expected_acks": sorted(result.expected_acks),
        "received_acks": sorted(result.received_acks),
        "note": result.note,
    }
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            f"opsctl {NAME} target={target} request_id={result.request_id} "
            f"exit={int(result.exit_code)}({result.exit_code.name}) "
            f"acks={sorted(result.received_acks)}/{sorted(result.expected_acks)} "
            f"note={result.note}\n"
        )

    append_audit_row(
        cfg.opsctl_audit_path_resolved,
        make_row(
            op=NAME,
            target=target,
            request_id=result.request_id,
            exit_code=int(result.exit_code),
            expected_acks=len(result.expected_acks),
            received_acks=len(result.received_acks),
            note=result.note,
            host=os.uname().nodename,
        ),
    )
    return int(result.exit_code)


__all__ = ["KIND", "NAME", "add_parser", "run"]
