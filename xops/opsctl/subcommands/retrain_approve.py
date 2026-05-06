"""``ops.retrain-approve`` — Phase 8 §8.1.

Operator override that authorizes a trainer run. Publishes
``maint.event.v1{kind=retrain_approve, target=<predictor_id>}``;
the trainer-as-agent (Phase 5.x — not yet landed) consumes it and
joins the optional ``details.drift_request_id`` to the originating
``retrain_request`` envelope.

Until the trainer agent ships, the consumer set is empty (see
``KINDS_PENDING_CONSUMER_LANDING`` in
:mod:`ai.swarm.agents.maint._ack_routing`); the publisher will
exit with code 5 (``no_consumer_for_kind: pending Phase 5.x``) but
the audit row is still written. This is the intended pre-landing
behaviour per the §8.0 routing doctrine.

Reversible (the trainer can be paused / its output rejected), so
NOT in :data:`xops.opsctl._classify.ALWAYS_DESTRUCTIVE`.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from .._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "retrain-approve"
KIND = "retrain_approve"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Authorize a trainer run for a predictor (operator override).",
        description=(
            "Publishes maint.event.v1{kind=retrain_approve}. The "
            "trainer agent (Phase 5.x — not yet landed) consumes it. "
            "Pass --drift-request-id to correlate the approval to a "
            "specific retrain_request envelope."
        ),
    )
    add_common_publish_args(
        parser,
        target_help="Predictor id (e.g. 'pred.elo.v1', 'pred.poisson.v1').",
    )
    parser.add_argument(
        "--drift-request-id",
        default="",
        help=(
            "Optional UUID of the originating retrain_request envelope; "
            "carried in payload.details.drift_request_id."
        ),
    )
    parser.add_argument(
        "--note",
        default="",
        help="Free-text justification carried in payload.details.note.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    drift_request_id = str(getattr(args, "drift_request_id", "") or "")
    note = str(getattr(args, "note", "") or "")
    details: dict[str, Any] = {}
    if drift_request_id:
        details["drift_request_id"] = drift_request_id
    if note:
        details["note"] = note
    extra_payload: dict[str, Any] = {"details": details} if details else {}

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=str(args.target),
        client_id=str(args.client_id),
        salient_args={"drift_request_id": drift_request_id} if drift_request_id else {},
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    return run_publish(spec, bus=bus)


__all__ = ["KIND", "NAME", "add_parser", "run"]
