"""``ops.dlq-show`` — Phase 8 §8.16.12 read-only DLQ inspector.

Lists entries from a DLQ topic without replaying or acknowledging them.
When ``--qa-correlation-id`` is provided, only entries whose original
payload carries that correlation marker are returned.

The current swarm bus stores DLQ entries as wrappers around the original
payload (`{"original_topic", "reason", "attempts", "payload"}`), so the
correlation probe reads the nested ``payload`` body. The marker may live
either at the top level (future additive schema) or under
``payload.metadata.qa_correlation_id`` (current compatibility shim).

The probe is intentionally field-whitelisted: ``qa_correlation_id`` is an
envelope identifier copied from ``qa.request.v1.envelope.message_id``, not a
bridge into free-text request content. ``ops.dlq-show`` never derives it from
text-bearing fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, Optional

from ai.common.config import Config
from ai.swarm.sdk.bus import InMemoryBus, RedisStreamsBus
from ai.swarm.sdk.types import Message, Topic

from .._exit_codes import ExitCode

NAME = "dlq-show"


def add_parser(
    subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        NAME,
        help="List DLQ entries without replaying them.",
        description=(
            "Read-only DLQ inspection for operators. Supports optional "
            "filtering by qa_correlation_id carried on the original payload. "
            "The correlation id is an envelope id only and never mined from "
            "text-bearing fields."
        ),
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="DLQ topic to inspect (must end in '.dlq').",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Cap the number of entries shown (default: 100).",
    )
    parser.add_argument(
        "--qa-correlation-id",
        default="",
        help=(
            "Only return entries whose original payload carries this QA "
            "correlation id (copied envelope id, not QA text)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout (deterministic).",
    )
    parser.set_defaults(func=run)
    return parser


def _coerce_qa_correlation_id(value: Any) -> str:
    """Return only a flat envelope id string.

    ``qa_correlation_id`` is a copied envelope identifier, so malformed
    objects, lists, or other text-bearing structures are ignored instead of
    being stringified into operator output.
    """

    if not isinstance(value, str):
        return ""
    return value.strip()


def _extract_qa_correlation_id(msg: Message) -> str:
    wrapper = msg.payload if isinstance(msg.payload, dict) else {}
    inner = wrapper.get("payload")
    if not isinstance(inner, dict):
        inner = wrapper
    direct = _coerce_qa_correlation_id(inner.get("qa_correlation_id"))
    if direct:
        return direct
    metadata = inner.get("metadata")
    if isinstance(metadata, dict):
        return _coerce_qa_correlation_id(metadata.get("qa_correlation_id"))
    return ""


def _entry_row(handle: str, msg: Message) -> dict[str, Any]:
    wrapper = msg.payload if isinstance(msg.payload, dict) else {}
    inner = wrapper.get("payload")
    if not isinstance(inner, dict):
        inner = wrapper
    return {
        "handle": handle,
        "message_id": msg.envelope.message_id,
        "producer": msg.envelope.producer,
        "created_at": msg.envelope.created_at,
        "original_topic": wrapper.get("original_topic", str(msg.envelope.topic)),
        "reason": wrapper.get("reason", ""),
        "attempts": int(wrapper.get("attempts", 0) or 0),
        "request_id": str(inner.get("request_id", "") or ""),
        "match_id": str(inner.get("match_id", "") or ""),
        "market": str(inner.get("market", "") or ""),
        "qa_correlation_id": _extract_qa_correlation_id(msg),
    }


def _snapshot_inmemory(bus: InMemoryBus, topic: str, limit: int) -> list[tuple[str, Message]]:
    with bus._lock:  # type: ignore[attr-defined]
        raw_entries = list(bus._streams[Topic(topic)])[-limit:]  # type: ignore[attr-defined]
        codec = bus._codec  # type: ignore[attr-defined]
    return [(handle, codec.decode(raw)) for handle, raw in raw_entries]


def _snapshot_redis(bus: RedisStreamsBus, topic: str, limit: int) -> list[tuple[str, Message]]:
    entries = bus._client.xrange(topic, count=limit)  # type: ignore[attr-defined]
    out: list[tuple[str, Message]] = []
    for entry_id, fields in entries:
        raw = fields.get(b"data") if isinstance(fields, dict) else None
        if raw is None and isinstance(fields, dict):
            raw = fields.get("data")
        if raw is None:
            continue
        handle = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
        out.append((handle, bus._codec.decode(raw)))  # type: ignore[attr-defined]
    return out


def _snapshot(bus: Any, topic: str, limit: int) -> list[tuple[str, Message]]:
    if isinstance(bus, InMemoryBus):
        return _snapshot_inmemory(bus, topic, limit)
    if isinstance(bus, RedisStreamsBus):
        return _snapshot_redis(bus, topic, limit)
    raise TypeError(f"unsupported bus for {NAME}: {type(bus)!r}")


def _default_bus(cfg: Config) -> RedisStreamsBus:
    return RedisStreamsBus(
        host=cfg.redis_host,
        port=cfg.redis_port,
        socket_timeout=float(cfg.redis_socket_timeout),
    )


def _render_plain(topic: str, qa_correlation_id: str, rows: Iterable[dict[str, Any]]) -> None:
    rows_l = list(rows)
    suffix = f" qa_correlation_id={qa_correlation_id}" if qa_correlation_id else ""
    sys.stdout.write(f"opsctl {NAME} topic={topic} count={len(rows_l)}{suffix}\n")
    for row in rows_l:
        corr = row.get("qa_correlation_id") or "-"
        sys.stdout.write(
            f"  {row['handle']} request_id={row['request_id']} match_id={row['match_id']} "
            f"market={row['market']} qa_correlation_id={corr} reason={row['reason']}\n"
        )


def run(args: argparse.Namespace, *, bus: Optional[Any] = None) -> int:
    cfg = Config()
    topic = str(getattr(args, "topic", "") or "")
    if not topic.endswith(".dlq"):
        sys.stderr.write(
            f"opsctl {NAME}: --topic must end in '.dlq' (got {topic!r})\n"
        )
        return int(ExitCode.BAD_USAGE)

    limit = max(1, int(getattr(args, "limit", 100) or 100))
    qa_correlation_id = str(getattr(args, "qa_correlation_id", "") or "")
    active_bus = bus or _default_bus(cfg)
    rows = [_entry_row(handle, msg) for handle, msg in _snapshot(active_bus, topic, limit)]
    if qa_correlation_id:
        rows = [row for row in rows if row["qa_correlation_id"] == qa_correlation_id]

    doc = {
        "op": NAME,
        "topic": topic,
        "qa_correlation_id": qa_correlation_id,
        "count": len(rows),
        "entries": rows,
    }
    if bool(getattr(args, "json", False)):
        sys.stdout.write(json.dumps(doc, sort_keys=True, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        _render_plain(topic, qa_correlation_id, rows)
    return int(ExitCode.OK)


__all__ = ["NAME", "add_parser", "run"]