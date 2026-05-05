"""xops.opsctl — publish + ack-wait flow (Phase 8 §8.1).

The publisher is bus-injected (see :func:`publish_event`) so unit
tests can drive it with an :class:`InMemoryBus` and the production
CLI wires up a :class:`RedisStreamsBus` from
``ai.common.config.get_config()``. The flow is:

1. Validate ``payload`` against the per-kind sub-schema at
   ``ai/swarm/sdk/schemas/maint.event.v1/<kind>.json``.
2. Resolve ``expected_ack_set(kind)``. Empty set ⇒ exit 5
   (``no_consumer_for_kind``); unknown kind ⇒ exit 6
   (``unknown_kind`` per the binding doctrine in
   :mod:`ai.swarm.agents.maint._ack_routing`).
3. ``Bus.publish`` the envelope. On any exception the envelope is
   spooled to disk (Phase 8 §8.1.spool) and the call returns exit 4
   (``bus_down_spooled``).
4. Drain ``maint.ack.v1`` for up to ``cfg.opsctl_ack_timeout_ms``
   wall-clock (operator-stopwatch contract per the docblock at
   :class:`ai.common.config.Config`), matching ack ``accepted_by``
   values against ``expected_ack_set``. Exit codes:
       * all acks received → :attr:`ExitCode.OK`
       * partial → :attr:`ExitCode.PARTIAL_ACK_TIMEOUT`
       * none → :attr:`ExitCode.HARD_TIMEOUT`

The ack drain uses a dedicated consumer-group/consumer name pair
so concurrent operators do not steal each other's acks.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ai.common.config import Config
from ai.swarm.agents.maint._ack_routing import (
    KINDS_PENDING_CONSUMER_LANDING,
    KNOWN_MAINT_EVENT_KINDS,
    expected_ack_set,
)
from ai.swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from ai.swarm.sdk.bus import Bus
from ai.swarm.sdk.schemas import validate_kind
from ai.swarm.sdk.types import Envelope, Message

from ._exit_codes import ExitCode

MAINT_EVENT_TOPIC = MAINT_EVENT
MAINT_ACK_TOPIC = MAINT_ACK
OPS_CONSOLE_PRODUCER = "ops_console"


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a single publish + ack-wait cycle."""

    exit_code: ExitCode
    request_id: str
    expected_acks: frozenset[str]
    received_acks: frozenset[str]
    note: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_request_id() -> str:
    return uuid.uuid4().hex


def build_envelope(
    *,
    kind: str,
    target: str,
    client_id: str,
    request_id: Optional[str] = None,
    extra_payload: Optional[dict[str, Any]] = None,
) -> Message:
    """Build a ``maint.event.v1`` :class:`Message` ready for publish."""
    rid = request_id or _new_request_id()
    payload: dict[str, Any] = {
        "kind": kind,
        "target": target,
        "request_id": rid,
        "client_id": client_id,
        "produced_at": _utc_now_iso(),
    }
    if extra_payload:
        payload.update(extra_payload)
    return Message(
        envelope=Envelope(topic=MAINT_EVENT_TOPIC, producer=OPS_CONSOLE_PRODUCER),
        payload=payload,
    )


def _spool_envelope(spool_dir: str, message: Message, max_entries: int) -> Optional[str]:
    """Persist the envelope to ``spool_dir`` for later replay.

    Returns the spool file path on success; ``None`` if the spool
    refused the entry (cap exceeded). The caller maps a None return
    to a separate operator-facing message.
    """
    sp = Path(spool_dir)
    sp.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Cap check: refuse a write past the configured size to keep the
    # spool drainable in finite time. Caller surfaces this distinctly
    # from a generic bus-down.
    existing = list(sp.glob("*.envelope.json"))
    if len(existing) >= max_entries:
        return None
    name = f"{int(time.time() * 1000)}-{message.payload.get('request_id', _new_request_id())}.envelope.json"
    target = sp / name
    body = json.dumps(
        {
            "envelope": message.envelope.as_dict(),
            "payload": message.payload,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    return str(target)


def _validate_payload(kind: str, message: Message) -> Optional[str]:
    """Return error string if the payload fails the per-kind schema."""
    errs = validate_kind(str(MAINT_EVENT_TOPIC), message.payload)
    if errs:
        return "; ".join(errs)
    return None


def publish_event(
    bus: Optional[Bus],
    message: Message,
    *,
    consumer_name: Optional[str] = None,
) -> PublishResult:
    """Publish ``message`` and wait for the expected ack set.

    ``bus`` may be ``None`` to simulate bus-down — the caller will
    then see :attr:`ExitCode.BUS_DOWN_SPOOLED` and a non-empty
    ``note`` pointing at the spool file (or
    ``MAINT_STORAGE_FULL`` if the spool refused).
    """
    cfg = Config()
    kind = message.payload.get("kind")
    request_id = str(message.payload.get("request_id", ""))
    if not isinstance(kind, str) or not kind:
        return PublishResult(
            exit_code=ExitCode.BAD_USAGE,
            request_id=request_id,
            expected_acks=frozenset(),
            received_acks=frozenset(),
            note="payload missing 'kind'",
        )
    if kind not in KNOWN_MAINT_EVENT_KINDS:
        return PublishResult(
            exit_code=ExitCode.UNKNOWN_KIND,
            request_id=request_id,
            expected_acks=frozenset(),
            received_acks=frozenset(),
            note=f"kind {kind!r} not in _ACK_ROUTING_TABLE",
        )

    schema_err = _validate_payload(kind, message)
    if schema_err:
        return PublishResult(
            exit_code=ExitCode.BAD_USAGE,
            request_id=request_id,
            expected_acks=frozenset(),
            received_acks=frozenset(),
            note=f"schema validation failed: {schema_err}",
        )

    expected = expected_ack_set(kind)
    if not expected:
        pending_note = KINDS_PENDING_CONSUMER_LANDING.get(kind, "(no consumer registered)")
        return PublishResult(
            exit_code=ExitCode.NO_CONSUMER_FOR_KIND,
            request_id=request_id,
            expected_acks=frozenset(),
            received_acks=frozenset(),
            note=f"no_consumer_for_kind: {pending_note}",
        )

    if bus is None:
        spool_path = _spool_envelope(
            cfg.opsctl_spool_dir_resolved, message, cfg.opsctl_spool_max_entries
        )
        if spool_path is None:
            return PublishResult(
                exit_code=ExitCode.MAINT_STORAGE_FULL,
                request_id=request_id,
                expected_acks=expected,
                received_acks=frozenset(),
                note=f"spool refused: {cfg.opsctl_spool_max_entries} entries cap reached",
            )
        return PublishResult(
            exit_code=ExitCode.BUS_DOWN_SPOOLED,
            request_id=request_id,
            expected_acks=expected,
            received_acks=frozenset(),
            note=f"spooled to {spool_path}",
        )

    try:
        bus.publish(message)
    except Exception as exc:  # noqa: BLE001 — bus failures are operational, classify uniformly
        spool_path = _spool_envelope(
            cfg.opsctl_spool_dir_resolved, message, cfg.opsctl_spool_max_entries
        )
        if spool_path is None:
            return PublishResult(
                exit_code=ExitCode.MAINT_STORAGE_FULL,
                request_id=request_id,
                expected_acks=expected,
                received_acks=frozenset(),
                note=f"bus.publish failed and spool refused: {exc!r}",
            )
        return PublishResult(
            exit_code=ExitCode.BUS_DOWN_SPOOLED,
            request_id=request_id,
            expected_acks=expected,
            received_acks=frozenset(),
            note=f"bus.publish failed ({exc!r}); spooled to {spool_path}",
        )

    received: set[str] = set()
    consumer = consumer_name or f"opsctl.{os.getpid()}"
    group = f"opsctl.ack.{request_id}"
    bus.ensure_group(MAINT_ACK_TOPIC, group)
    deadline = time.monotonic() + (cfg.opsctl_ack_timeout_ms / 1000.0)

    while time.monotonic() < deadline and received != expected:
        # Read in small batches so a noisy ack stream does not starve
        # the deadline check. block_ms=0 → InMemoryBus returns
        # immediately; RedisStreamsBus would honour the value.
        deliveries = bus.read(MAINT_ACK_TOPIC, group, consumer, count=16, block_ms=50)
        if not deliveries:
            # Tiny sleep so a busy-loop does not pin a core when the
            # bus has no new acks.
            time.sleep(0.01)
            continue
        for d in deliveries:
            payload = d.message.payload
            if str(payload.get("request_id")) != request_id:
                # Not ours — ack to release the slot but ignore the body.
                bus.ack(MAINT_ACK_TOPIC, group, d.handle)
                continue
            accepted_by = payload.get("accepted_by")
            if isinstance(accepted_by, str) and accepted_by in expected:
                received.add(accepted_by)
            bus.ack(MAINT_ACK_TOPIC, group, d.handle)

    if received == expected:
        return PublishResult(
            exit_code=ExitCode.OK,
            request_id=request_id,
            expected_acks=expected,
            received_acks=frozenset(received),
            note="all acks received",
        )
    if received:
        missing = sorted(expected - received)
        return PublishResult(
            exit_code=ExitCode.PARTIAL_ACK_TIMEOUT,
            request_id=request_id,
            expected_acks=expected,
            received_acks=frozenset(received),
            note=f"missing acks from: {','.join(missing)}",
        )
    return PublishResult(
        exit_code=ExitCode.HARD_TIMEOUT,
        request_id=request_id,
        expected_acks=expected,
        received_acks=frozenset(),
        note=f"no acks within {cfg.opsctl_ack_timeout_ms}ms",
    )


__all__ = [
    "MAINT_ACK_TOPIC",
    "MAINT_EVENT_TOPIC",
    "OPS_CONSOLE_PRODUCER",
    "PublishResult",
    "build_envelope",
    "publish_event",
]
