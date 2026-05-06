"""``ops.backup-rotate-key`` — Phase 8 §8.1 / §8.3 / §8.13.6.

Operator triggers backup encryption-key rotation. ALWAYS_DESTRUCTIVE
(see :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`): a botched
rotation can render existing dumps unrecoverable, so the operator
must pass the typed ``--confirm`` token.

`scope` is the binding policy switch:

* ``verify`` — rotates the per-dump verify keypair (low blast radius;
  only affects subsequent restore-verify cycles).
* ``dr`` — rotates the long-term DR-class recipients per the
  §8.13.6 doctrine (operator runbook lives at
  ``docs/guides/backup_key_compromise_runbook.md``).

Consumed by ``maint.backup.v1`` (lands in §8.3 — until then, exit
code 5 ``no_consumer_for_kind: pending Phase 8.3``).
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "backup-rotate-key"
KIND = "backup_rotate_key"

_RECOGNISED_SCOPES = frozenset({"verify", "dr"})


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Rotate backup encryption keys (DESTRUCTIVE).",
        description=(
            "Publishes maint.event.v1{kind=backup_rotate_key}. "
            "Destructive — passes through ALWAYS_DESTRUCTIVE token gate."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Free-form audit label (e.g. 'verify-2026-Q3').",
    )
    parser.add_argument(
        "--scope",
        required=True,
        choices=sorted(_RECOGNISED_SCOPES),
        help="'verify' (per-dump verify keypair) or 'dr' (long-term DR recipients).",
    )
    parser.add_argument(
        "--add-recipient",
        default="",
        help="Optional age recipient public key to add when --scope=dr.",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text justification (compromise scenario, scheduled, …).",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    scope = str(args.scope)
    add_recipient = str(getattr(args, "add_recipient", "") or "")
    reason = str(getattr(args, "reason", "") or "")

    if add_recipient and scope != "dr":
        import sys
        sys.stderr.write(
            f"opsctl {NAME}: --add-recipient is only valid with --scope=dr\n"
        )
        return 64

    extra_payload: dict[str, Any] = {"scope": scope}
    if add_recipient:
        extra_payload["add_recipient"] = add_recipient
    if reason:
        extra_payload["reason"] = reason

    salient: dict[str, Any] = {"scope": scope}
    if add_recipient:
        salient["add_recipient"] = add_recipient

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=str(args.target),
        client_id=str(args.client_id),
        salient_args=salient,
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
