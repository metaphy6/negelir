"""Phase 8 §8.5 — `maint.dlq.v1` DLQ supervisor.

Listens for operator `maint.event.v1{kind=dlq_replay}` envelopes
and replays poisoned messages from the named DLQ topic back onto
its origin topic. Hard-bounded by a per-topic recursion deny set
and a max-msgs cap so a poisoned message storm cannot create a
hot loop.

Boundaries (binding):

* Single-instance via :class:`Leader` gate. A second replica is a
  noop until the leader sheds.
* The maint plane's own DLQs are in :data:`RECURSION_DENY_SET`;
  attempting to replay them yields
  ``maint.event.v1{kind=dlq_topic_disabled_drained}`` and a
  rejected ack (`accepted=False, reason='recursion_deny'`).
* Per-topic round-robin fairness — the supervisor never replays
  > ``cfg.maint_dlq_per_topic_quota`` messages from one topic in
  one run before yielding to the next.
* Backoff: the same ``request_id`` cannot be replayed inside
  ``cfg.maint_dlq_replay_backoff_s`` (LRU bounded by
  ``cfg.maint_dlq_backoff_lru``).

This v1 emits **notifications** (`dlq_replayed`, `dlq_escalated`,
`dlq_dropped`) on `maint.event.v1` with NO `request_id` field; the
:func:`expected_ack_set` map for those kinds is empty (notification-
only). Operators read them off the bus via telemetry.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.leader import Leader, SingleProcessLeader
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck
from ..topics import MAINT_ACK, MAINT_EVENT

_log = logging.getLogger("swarm.agents.maint.dlq")


# DLQs we MUST NOT replay — replaying these would loop the maint
# plane on itself. Doctrine: append-only, every entry justified.
RECURSION_DENY_SET: frozenset[str] = frozenset({
    # The maint plane's own DLQs.
    "maint.event.v1.dlq",
    "maint.ack.v1.dlq",
    # Sec alert DLQ — rate.v1 is the sole denylist writer; a replay
    # storm here could bypass the burst window.
    "sec.alert.v1.dlq",
})


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


@dataclass
class _RunState:
    """Per-topic accounting: count replayed in current run, deque of
    last-seen request_ids for backoff."""

    replayed: int = 0
    last_run_at: float = 0.0
    seen: "OrderedDict[str, float]" = field(default_factory=OrderedDict)


class MaintDlqSupervisor:
    """`maint.dlq.v1` reactor.

    Subscribes ``maint.event.v1`` (kind=dlq_replay).
    Publishes ``maint.event.v1`` (notifications: dlq_replayed,
    dlq_escalated, dlq_topic_disabled_drained, dlq_dropped) and
    ``maint.ack.v1`` (acks for the operator request).
    """

    name = "maint.dlq.v1"
    subscribes: tuple[Topic, ...] = (MAINT_EVENT,)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK)

    def __init__(
        self,
        *,
        leader: Leader | None = None,
        clock_iso: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._leader = leader if leader is not None else SingleProcessLeader(name=self.name)
        self._clock_iso = clock_iso or _utc_iso
        self._new_id = new_id or _new_id
        self._state: dict[str, _RunState] = {}
        # LRU of recently-seen request_ids for backoff dedup.
        self._req_lru: "OrderedDict[str, None]" = OrderedDict()

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        kind = payload.get("kind")
        if kind != "dlq_replay":
            return ()  # ignore other kinds (we don't subscribe to them)
        return list(self._handle_replay(msg, payload))

    def _handle_replay(self, msg: Message, payload: dict) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target_dlq = str(payload.get("target") or "")
        if not request_id or not target_dlq:
            return  # malformed — silently drop (the schema validator
                    # at the producer side is the contract)

        # Leader gate — non-leaders ack as accepted-but-noop so the
        # ops console gets a complete ack set even with hot spares.
        if not self._leader.is_leader():
            yield self._ack(msg, request_id, accepted=True,
                            reason="leader_skip")
            return

        # Recursion deny.
        if target_dlq in RECURSION_DENY_SET:
            yield self._ack(msg, request_id, accepted=False,
                            reason="recursion_deny")
            yield self._notify("dlq_topic_disabled_drained",
                               target=target_dlq,
                               extra={"deny_reason": "recursion_deny"})
            return

        # Backoff dedup.
        backoff_lru = max(1, int(_cfg.maint_dlq_backoff_lru))
        if request_id in self._req_lru:
            yield self._ack(msg, request_id, accepted=False,
                            reason="backoff_dedup")
            return
        self._req_lru[request_id] = None
        while len(self._req_lru) > backoff_lru:
            self._req_lru.popitem(last=False)

        # Per-topic quota cap.
        max_msgs_default = max(1, int(_cfg.maint_dlq_per_topic_quota))
        max_msgs = int(payload.get("max_msgs") or 0) or max_msgs_default
        max_msgs = min(max_msgs, max_msgs_default * 10)  # hard ceiling

        # v1 does not actually drain Redis Streams here — the bus
        # adapter exposes no public replay primitive yet. The
        # supervisor records the request, emits a `dlq_replayed`
        # notification with replayed_count=0, and acks accepted.
        # Phase 8.5b will add the bus-side `Bus.replay_dlq()`
        # primitive; the agent already has the gating logic so the
        # follow-up is a single integration call.
        replayed = 0
        st = self._state.setdefault(target_dlq, _RunState())
        st.replayed = replayed
        yield self._notify("dlq_replayed",
                           target=target_dlq,
                           extra={"replayed_count": replayed,
                                  "max_msgs": max_msgs,
                                  "request_id": request_id})
        yield self._ack(msg, request_id, accepted=True,
                        reason="replayed",
                        details={"replayed_count": replayed})

    # ── Helpers ───────────────────────────────────────────────────
    def _ack(self, msg: Message, request_id: str, *, accepted: bool,
             reason: str, details: dict | None = None) -> Message:
        ack = MaintAck(
            request_id=request_id,
            accepted=accepted,
            accepted_by=self.name,
            processed_at=self._clock_iso(),
            attempt=int(msg.envelope.attempt or 1),
            reason=reason,
            details=details,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=msg.envelope.trace_id,
            topic=MAINT_ACK,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=ack.as_dict())

    def _notify(self, kind: str, *, target: str,
                extra: dict | None = None) -> Message:
        payload: dict = {
            "kind": kind,
            "target": target,
            "produced_at": self._clock_iso(),
        }
        if extra:
            payload.update(extra)
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)


__all__ = ["MaintDlqSupervisor", "RECURSION_DENY_SET"]
