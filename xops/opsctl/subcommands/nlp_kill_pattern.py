"""``ops.nlp-kill-pattern`` — Phase 10 §10.27.

Publishes ``maint.event.v1{kind=nlp_kill_pattern_armed}`` for operator kill-pattern
arms. On a successful publish, also emits ``sec.alert.v1{kind=nlp_kill_pattern_armed}``
from the ops_console source so the action is auditable per the dual-emit doctrine.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
import uuid
from typing import Any, Optional

from swarm.agents.payloads import SecAlert
from swarm.agents.topics import SEC_ALERT
from swarm.sdk.types import Message
from xops.opsctl._exit_codes import ExitCode
from xops.opsctl._publish import OPS_CONSOLE_PRODUCER
from xops.opsctl._runner import SubcommandSpec, add_common_publish_args, run_publish

NAME = "nlp-kill-pattern"
KIND = "nlp_kill_pattern_armed"
TARGET = "nlp.kill_pattern"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="Arm an NLP kill-pattern to rewrite matching in-flight or cached answers.",
        description=(
            "Publishes maint.event.v1{kind=nlp_kill_pattern_armed} and a paired "
            "sec.alert.v1{kind=nlp_kill_pattern_armed}. The event is consumed by "
            "nlp.answer.v1 replicas to rewrite matching answers until TTL expiry."
        ),
    )
    parser.add_argument(
        "--operator-id-h",
        required=True,
        help="Operator identity hash carried in the armed event and audit alert.",
    )
    parser.add_argument(
        "--pattern-pack-sha8",
        required=True,
        help="Identifier of the operator-supplied kill-pattern pack.",
    )
    parser.add_argument(
        "--ttl-s",
        type=int,
        required=True,
        help="Time-to-live for the armed kill pattern in seconds.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Operator justification for arming the kill pattern.",
    )
    parser.add_argument(
        "--match-id",
        default="",
        help="Optional match_id filter for the target kill pattern.",
    )
    parser.add_argument(
        "--request-id",
        default="",
        help="Optional request_id filter for the target kill pattern.",
    )
    parser.add_argument(
        "--intent-class",
        default="",
        help="Optional intent_class filter for the target kill pattern.",
    )
    parser.add_argument(
        "--template-id",
        default="",
        help="Optional template_id filter for the target kill pattern.",
    )
    parser.add_argument(
        "--lexicon-hit",
        default="",
        help="Optional lexicon_hit filter for the target kill pattern.",
    )
    parser.add_argument(
        "--body-substring-sha8",
        default="",
        help="Optional body_substring_sha8 filter for the target kill pattern."
    )
    add_common_publish_args(parser, target_help="Operator command target identifier.")
    parser.set_defaults(func=run)
    return parser


def _emit_sec_alert(
    *,
    bus: Any,
    request_id: str,
    client_id: str,
    operator_id_h: str,
    reason: str,
) -> None:
    alert = SecAlert(
        alert_id=uuid.uuid4().hex,
        kind=KIND,
        severity="warn",
        source=OPS_CONSOLE_PRODUCER,
        reason=reason,
        produced_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        subject=operator_id_h,
        request_id=request_id,
        client_id=client_id,
    )
    bus.publish(Message.new(topic=SEC_ALERT, payload=alert.as_dict(), producer=OPS_CONSOLE_PRODUCER))


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    operator_id_h = str(getattr(args, "operator_id_h", "") or "")
    pattern_pack_sha8 = str(getattr(args, "pattern_pack_sha8", "") or "")
    ttl_s = int(getattr(args, "ttl_s", 0) or 0)
    reason = str(getattr(args, "reason", "") or "")
    extra_payload: dict[str, Any] = {
        "operator_id_h": operator_id_h,
        "pattern_pack_sha8": pattern_pack_sha8,
        "ttl_s": ttl_s,
        "reason": reason,
    }
    for field_name in (
        "match_id",
        "request_id",
        "intent_class",
        "template_id",
        "lexicon_hit",
        "body_substring_sha8",
    ):
        value = str(getattr(args, field_name, "") or "")
        if value:
            extra_payload[field_name] = value

    spec = SubcommandSpec(
        name=NAME,
        kind=KIND,
        target=TARGET,
        client_id=str(getattr(args, "client_id", "opsctl") or "opsctl"),
        salient_args={
            "operator_id_h": operator_id_h,
            "pattern_pack_sha8": pattern_pack_sha8,
            "ttl_s": ttl_s,
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
            request_id=spec.extra_payload.get("request_id", ""),
            client_id=spec.client_id,
            operator_id_h=operator_id_h,
            reason=reason,
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"opsctl {NAME}: sec.alert publish failed: {exc}\n")
    return exit_code


__all__ = ["KIND", "NAME", "add_parser", "run"]
