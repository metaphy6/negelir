"""``ops.nlp-flame-capture`` — Phase 10 §10.32.15.

Publishes ``maint.event.v1{kind=nlp_flame_armed}`` for operator-triggered
per-request NLP flame capture arms. On successful publish, also emits
``sec.alert.v1{kind=nlp_flame_armed}`` from the ops_console source so
operator actions are auditable per the dual-emit doctrine.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from typing import Any, Optional

from swarm.agents.payloads import SecAlert
from swarm.agents.topics import SEC_ALERT
from swarm.sdk.types import Message
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import OPS_CONSOLE_PRODUCER
from xops.opsctl._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "nlp-flame-capture"
KIND = "nlp_flame_armed"
TARGET = "nlp.flame_capture"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Arm a one-shot NLP flame capture for a specific request or QA correlation.",
        description=(
            "Publishes maint.event.v1{kind=nlp_flame_armed} and a paired "
            "sec.alert.v1{kind=nlp_flame_armed}. The next matching request "
            "or QA correlation triggers per-stage NLP flame capture."
        ),
    )
    parser.add_argument(
        "--operator-id-h",
        required=True,
        help="Operator identity hash carried in the armed event and audit alert.",
    )
    parser.add_argument(
        "--request-id",
        default="",
        help="Exact request_id to arm for capture.",
    )
    parser.add_argument(
        "--qa-correlation-id",
        default="",
        help="Exact qa_correlation_id to arm for capture.",
    )
    parser.add_argument(
        "--ttl-h",
        type=int,
        required=True,
        help="Time-to-live for the flame capture arm in hours.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Operator justification for the flame capture arm.",
    )
    add_common_publish_args(parser, target_help="Operator command target identifier.")
    parser.set_defaults(func=run)
    return parser


def _emit_sec_alert(
    *,
    bus: Any,
    request_id: str,
    qa_correlation_id: str,
    client_id: str,
    operator_id_h: str,
    reason: str,
) -> None:
    alert_payload = {
        "kind": KIND,
        "severity": "warn",
        "source": OPS_CONSOLE_PRODUCER,
        "reason": reason,
        "subject": operator_id_h,
        "request_id": request_id,
        "qa_correlation_id": qa_correlation_id,
        "client_id": client_id,
        "produced_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    bus.publish(Message.new(topic=SEC_ALERT, payload=alert_payload, producer=OPS_CONSOLE_PRODUCER))


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    operator_id_h = str(getattr(args, "operator_id_h", "") or "")
    request_id = str(getattr(args, "request_id", "") or "")
    qa_correlation_id = str(getattr(args, "qa_correlation_id", "") or "")
    ttl_h = int(getattr(args, "ttl_h", 0) or 0)
    reason = str(getattr(args, "reason", "") or "")

    if not request_id and not qa_correlation_id:
        sys.stderr.write("opsctl nlp-flame-capture: either --request-id or --qa-correlation-id is required\n")
        return int(ExitCode.BAD_USAGE)

    extra_payload: dict[str, Any] = {
        "operator_id_h": operator_id_h,
        "request_id": request_id,
        "qa_correlation_id": qa_correlation_id,
        "ttl_h": ttl_h,
        "reason": reason,
    }

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=TARGET,
        client_id=str(getattr(args, "client_id", "opsctl") or "opsctl"),
        salient_args={
            "operator_id_h": operator_id_h,
            "request_id": request_id,
            "qa_correlation_id": qa_correlation_id,
            "ttl_h": ttl_h,
        },
        extra_payload=extra_payload,
        json_output=bool(getattr(args, "json", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        confirm=str(getattr(args, "confirm", "") or ""),
    )
    exit_code = run_publish(spec, bus=bus)
    if exit_code != int(ExitCode.OK) or getattr(args, "dry_run", False) or bus is None:
        return exit_code

    try:
        _emit_sec_alert(
            bus=bus,
            request_id=request_id,
            qa_correlation_id=qa_correlation_id,
            client_id=spec.client_id,
            operator_id_h=operator_id_h,
            reason=reason,
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"opsctl {NAME}: sec.alert publish failed: {exc}\n")
    return exit_code


__all__ = ["KIND", "NAME", "add_parser", "run"]
