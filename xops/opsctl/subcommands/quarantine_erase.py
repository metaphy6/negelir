"""``ops.quarantine-erase`` — Phase 7 §7.1 / Phase 8 §8.1, §8.3.

Destructive operator command: drops a quarantine sample from the
``storage.v1`` agent's ``quarantine_samples`` table. Listed in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE` — requires
``--confirm`` (typed token; future §8.15.4 lands HMAC-keyed
operator approval, which this baseline accepts as a string match).

Publishes ``maint.event.v1{kind=quarantine_erase, target=<sample_id>, ...}``
and waits for the ack from ``storage.v1``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

from ai.common.config import Config

from .._audit import append_audit_row, make_row
from .._classify import Action, ClassifyRequest, classify
from .._exit_codes import ExitCode
from .._publish import build_envelope, publish_event

NAME = "quarantine-erase"
KIND = "quarantine_erase"
CONFIRM_TOKEN = "i-understand-this-is-destructive"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Erase a quarantine sample (DESTRUCTIVE; storage.v1 ack).",
        description=(
            "Publishes maint.event.v1{kind=quarantine_erase}. Drops the "
            "named sample from quarantine_samples. Irreversible at the "
            "row level. Requires --confirm with the typed token."
        ),
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Sample id to erase.",
    )
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag carried in the envelope payload.",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Typed confirmation token (must equal {CONFIRM_TOKEN!r}).",
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

    decision = classify(
        ClassifyRequest(
            subcommand=NAME,
            critical_agents=cfg.opsctl_critical_agents_set,
        )
    )
    if decision is Action.CONFIRM and args.confirm != CONFIRM_TOKEN:
        note = "missing or wrong --confirm token (refused before publish)"
        append_audit_row(
            cfg.opsctl_audit_path_resolved,
            make_row(
                op=NAME,
                target=target,
                request_id="-",
                exit_code=int(ExitCode.BAD_USAGE),
                expected_acks=0,
                received_acks=0,
                note=note,
                host=os.uname().nodename,
            ),
        )
        sys.stderr.write(
            f"opsctl {NAME}: refused — destructive operation requires "
            f"--confirm '{CONFIRM_TOKEN}'\n"
        )
        return int(ExitCode.BAD_USAGE)

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


__all__ = ["CONFIRM_TOKEN", "KIND", "NAME", "add_parser", "run"]
