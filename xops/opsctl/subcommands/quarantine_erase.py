"""``ops.quarantine-erase`` — Phase 7 §7.1 / Phase 8 §8.1, §8.3.

Destructive operator command: drops a quarantine sample from the
``storage.v1`` agent's ``quarantine_samples`` table. Listed in
:data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE` — refused without
``--confirm <token>`` where ``<token>`` is the per-command
``sha256(cmd|target)[:8]`` derivation printed by the CLI on
mismatch (see :mod:`xops.opsctl._token`).

Publishes ``maint.event.v1{kind=quarantine_erase, target=<sample_id>, ...}``
and waits for the ack from ``storage.v1``.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "quarantine-erase"
KIND = "quarantine_erase"


def add_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Erase a quarantine sample (DESTRUCTIVE; storage.v1 ack).",
        description=(
            "Publishes maint.event.v1{kind=quarantine_erase}. Drops the "
            "named sample from quarantine_samples. Irreversible at the "
            "row level. Requires --confirm <typed-token>; the CLI "
            "prints the expected token on first attempt."
        ),
    )
    add_common_publish_args(parser, target_help="Sample id to erase.")
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
