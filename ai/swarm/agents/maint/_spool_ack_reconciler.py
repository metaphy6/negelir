"""Phase 8 §8.16.2 — spool-flush ack reconciler.

Runs inside ``maint.dlq.v1`` as an ack-only consumer of
``maint.ack.v1``.  For each ``(flush_invocation_id, request_id)``
pair it tracks which per-consumer acks have arrived and fires two
side-effects once the window closes:

* ``maint.event.v1{kind=spool_flush_acks_reconciled}`` --- always; the
  ``complete`` field distinguishes full vs. partial reconciliation.
* ``sec.alert.v1{kind=spool_flush_acks_incomplete, severity=warn}`` ---
  only when ``complete=False`` (some consumers missed the deadline),
  debounced per ``flush_invocation_id`` so a single process lifetime
  emits at most one alert per invocation.

The class is intentionally state-only (no bus reference).  Callers
(``MaintDlqSupervisor._handle_spool_ack``) drive it and collect the
returned ``Message`` list to publish.

Clock is injectable for deterministic tests.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, FrozenSet, List, Optional, Set, Tuple
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.types import Envelope, Message
from ..payloads import SecAlert
from ..topics import MAINT_EVENT, SEC_ALERT

_log = logging.getLogger("swarm.agents.maint.spool_ack_reconciler")

_AckKey = Tuple[str, str]  # (flush_invocation_id, request_id)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


@dataclass
class _AckState:
    flush_invocation_id: str
    request_id: str
    deadline_s: float
    expected: Optional[FrozenSet[str]] = None
    received: Set[str] = field(default_factory=set)
    seen_tuples: Set[Tuple[str, str, str]] = field(default_factory=set)
    emitted: bool = False


class SpoolAckReconciler:
    """Back-fills per-consumer ack receipts for spool-flush invocations.

    Instantiate once inside MaintDlqSupervisor; drive via reconcile()
    on every maint.ack.v1 arrival that carries a flush_invocation_id.
    Call sweep() periodically to close deadline-elapsed windows.
    """

    PRODUCER = "maint.dlq.v1"

    def __init__(
        self,
        *,
        clock_s: Optional[Callable[[], float]] = None,
        clock_iso: Optional[Callable[[], str]] = None,
        new_id: Optional[Callable[[], str]] = None,
    ) -> None:
        import time as _t
        self._clock_s: Callable[[], float] = clock_s or _t.time
        self._clock_iso: Callable[[], str] = clock_iso or _utc_iso
        self._new_id: Callable[[], str] = new_id or _new_id
        self._state: Dict[_AckKey, _AckState] = {}
        self._incomplete_alerted: Set[str] = set()

    def _deadline_s(self) -> float:
        max_wait_h = max(1, int(_cfg.opsctl_spool_ack_max_wait_h))
        return self._clock_s() + max_wait_h * 3600

    def _get_or_create(
        self,
        flush_invocation_id: str,
        request_id: str,
        expected: Optional[FrozenSet[str]] = None,
    ) -> _AckState:
        key: _AckKey = (flush_invocation_id, request_id)
        if key not in self._state:
            self._state[key] = _AckState(
                flush_invocation_id=flush_invocation_id,
                request_id=request_id,
                deadline_s=self._deadline_s(),
                expected=expected,
            )
        return self._state[key]

    def reconcile(
        self,
        *,
        flush_invocation_id: str,
        request_id: str,
        accepted_by: str,
        expected: Optional[FrozenSet[str]] = None,
    ) -> List[Message]:
        """Process one per-consumer ack for a spool-flush envelope.

        Returns messages to publish.  Empty when ack is a duplicate
        or the window is not yet complete.
        """
        state = self._get_or_create(flush_invocation_id, request_id, expected)
        if state.emitted:
            return []
        triple: Tuple[str, str, str] = (flush_invocation_id, request_id, accepted_by)
        if triple in state.seen_tuples:
            return []
        state.seen_tuples.add(triple)
        state.received.add(accepted_by)
        if state.expected is not None and state.received >= state.expected:
            return self._emit_reconciled(state, complete=True)
        return []

    def sweep(self) -> List[Message]:
        """Close any open windows whose deadline has elapsed."""
        now = self._clock_s()
        out: List[Message] = []
        for state in list(self._state.values()):
            if state.emitted:
                continue
            if now >= state.deadline_s:
                complete = (
                    state.expected is not None
                    and state.received >= state.expected
                )
                out.extend(self._emit_reconciled(state, complete=complete))
        return out

    def _emit_reconciled(
        self, state: _AckState, *, complete: bool
    ) -> List[Message]:
        state.emitted = True
        now_iso = self._clock_iso()
        msgs: List[Message] = []

        expected_count = len(state.expected) if state.expected is not None else 0
        missing: List[str] = []
        if not complete and state.expected is not None:
            missing = sorted(state.expected - state.received)

        payload: dict = {
            "kind": "spool_flush_acks_reconciled",
            "kind_schema_version": 1,
            "target": "opsctl",
            "produced_at": now_iso,
            "flush_invocation_id": state.flush_invocation_id,
            "request_id": state.request_id,
            "expected_ack_count": expected_count,
            "received_ack_count": len(state.received),
            "complete": complete,
        }
        if missing:
            payload["missing_ack_consumers"] = missing

        env = Envelope(
            message_id=self._new_id(),
            trace_id=state.request_id,
            topic=MAINT_EVENT,
            producer=self.PRODUCER,
            created_at=now_iso,
            schema_version=1,
            attempt=1,
        )
        msgs.append(Message(envelope=env, payload=payload))

        if not complete and state.flush_invocation_id not in self._incomplete_alerted:
            self._incomplete_alerted.add(state.flush_invocation_id)
            max_wait_h = _cfg.opsctl_spool_ack_max_wait_h
            alert = SecAlert(
                alert_id=self._new_id(),
                kind="spool_flush_acks_incomplete",
                severity="warn",
                source=self.PRODUCER,
                reason=(
                    f"spool-flush {state.flush_invocation_id!r}: "
                    f"{len(missing)} of {expected_count} expected acks "
                    f"not received within "
                    f"cfg.opsctl_spool_ack_max_wait_h={max_wait_h}h. "
                    f"Missing: {', '.join(missing) or 'unknown'}"
                )[:1024],
                produced_at=now_iso,
                subject=state.flush_invocation_id,
            )
            alert_env = Envelope(
                message_id=self._new_id(),
                trace_id=state.request_id,
                topic=SEC_ALERT,
                producer=self.PRODUCER,
                created_at=now_iso,
                schema_version=1,
                attempt=1,
            )
            msgs.append(Message(envelope=alert_env, payload=alert.as_dict()))

        return msgs
