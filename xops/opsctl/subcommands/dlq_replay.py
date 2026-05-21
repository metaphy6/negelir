"""``ops.dlq-replay`` — Phase 8 §8.5.

Operator-driven DLQ replay request. Publishes
``maint.event.v1{kind=dlq_replay, target, max_msgs}`` and waits for
the ack from ``maint.dlq.v1`` (the DLQ supervisor).

Per ROADMAP §8.5 + :mod:`xops.opsctl._classify`:

* ``--target`` MUST end in ``.dlq``. The supervisor refuses topics
  in its hardcoded ``DENY_PREFIXES`` (``maint.``, ``sec.``,
  ``auth.``, ``payment.``, ``patcher.``) unless the operator
  passed ``--confirm-pii`` AND the topic is in the
  cfg ``maint_dlq_replay_allow_overrides`` list.
* ``--drop`` flips the request from "replay" to "drop poison and
  acknowledge"; the supervisor emits ``kind=dlq_dropped`` per
  §8.16.9. Always destructive (CONFIRM tier).
* The CLI does NOT touch Redis; classifier inspection is
  string-prefix only. Authoritative deny enforcement lives in
  :mod:`ai.swarm.agents.maint.dlq.replay_policy`.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, run_publish

NAME = "dlq-replay"
KIND = "dlq_replay"

# Mirrors ai.swarm.agents.maint.dlq.replay_policy.DENY_PREFIXES (kept
# in sync via test_dlq_replay_policy_parity).
# qa.* added in Phase 8 §8.9 DoD: qa.request.v1.dlq is in
# RECURSION_DENY_SET; operator must attest PII awareness.
_DENY_PREFIXES = ("maint.", "sec.", "auth.", "payment.", "patcher.", "qa.")


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Replay a topic's DLQ via the maint.dlq.v1 supervisor.",
        description=(
            "Publishes maint.event.v1{kind=dlq_replay}. The supervisor "
            "drains up to --max-msgs entries from the named DLQ and "
            "re-publishes them on the live topic. PII-bearing topics "
            "(qa.*, sec.*, auth.*, payment.*) are denied unless an "
            "operator-attested override is in cfg."
        ),
    )
    parser.add_argument(
        "--target",
        required=True,
        help="DLQ topic to replay (must end in '.dlq').",
    )
    parser.add_argument(
        "--max-msgs",
        type=int,
        default=0,
        help="Cap on messages replayed; 0 uses cfg.maint_dlq_max_replays_per_tick.",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help=(
            "Drop poison entries instead of replaying. Always "
            "destructive: emits maint.event.v1{kind=dlq_dropped}."
        ),
    )
    parser.add_argument(
        "--confirm-pii",
        action="store_true",
        help=(
            "Acknowledge that the target topic carries PII (qa.*, "
            "sec.*, auth.*, payment.*, patcher.*); without this flag "
            "the classifier REFUSES the request."
        ),
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Free-text justification carried in the envelope.",
    )
    parser.add_argument(
        "--client-id",
        default="opsctl",
        help="Operator identity tag (default: opsctl).",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help="Typed confirmation token (required for --drop or PII).",
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


def _topic_is_pii(topic: str) -> bool:
    return any(topic.startswith(p) for p in _DENY_PREFIXES)


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    target = str(args.target)
    if not target.endswith(".dlq"):
        import sys

        sys.stderr.write(
            f"opsctl {NAME}: --target must end in '.dlq' (got {target!r})\n"
        )
        from .._exit_codes import ExitCode

        return int(ExitCode.BAD_USAGE)

    max_msgs = int(getattr(args, "max_msgs", 0) or 0)
    drop = bool(getattr(args, "drop", False))
    confirm_pii = bool(getattr(args, "confirm_pii", False))
    reason = str(getattr(args, "reason", "") or "")

    flags: set[str] = set()
    if drop:
        flags.add("drop")
    if _topic_is_pii(target):
        flags.add("topic_sec")
    if confirm_pii:
        flags.add("confirm_pii")

    extra_payload: dict[str, Any] = {}
    if max_msgs > 0:
        extra_payload["max_msgs"] = max_msgs
    if reason:
        extra_payload["reason"] = reason
    if drop:
        # The supervisor differentiates replay vs drop on this flag in
        # the payload; the schema accepts unknown bool fields only via
        # explicit additionalProperties=true changes — keep the
        # ``reason`` field as the carrier for now to satisfy the
        # additionalProperties=false sub-schema.
        extra_payload["reason"] = (reason or "drop")

    salient = {"max_msgs": max_msgs, "drop": drop}

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=target,
        client_id=str(args.client_id),
        salient_args=salient,
        extra_flags=frozenset(flags),
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
