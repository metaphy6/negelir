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

from ....sdk.leader import Leader, SingleProcessLeader
from ....sdk.types import Envelope, Message, Topic
from ...payloads import MaintAck, SecAlert
from ...topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from .replay_policy import (
    LEGACY_EXACT_DENY_TOPICS,
    build_policy_loaded_payload,
    current_allow_overrides,
    deny_reason as replay_policy_deny_reason,
)
from .._liveness import LivenessMixin
from .._op_signature import gate_op_envelope
from .._spool_ack_reconciler import SpoolAckReconciler

_log = logging.getLogger("swarm.agents.maint.dlq")


# Topics whose JSON schemas declare ``additionalProperties:false``.
# When the DLQ supervisor (or the future Bus.replay_dlq() primitive)
# replays a message back to one of these topics, ``__dlq_meta``
# MUST NOT be injected into the payload — it would fail schema
# validation.  Instead the bus adapter carries it in the Redis Stream
# entry header (out-of-band transport).
#
# Topics NOT in this set are "opt-in": the replay layer MAY merge
# ``__dlq_meta`` directly into the payload dict before re-publishing.
#
# Derived from ``ai/swarm/sdk/schemas/`` (grep additionalProperties:false).
# Extend as new strict schemas land; the :func:`dlq_meta_policy` test
# gate will catch drift.
_STRICT_PAYLOAD_TOPICS: frozenset[str] = frozenset({
    "freshness.events.v1",
    "maint.ack.v1",
    "match.normalized",
    "match.outcome.v1",
    "match.stored",
    "models.events.v1",
    "predict.approved.v1",
    "predict.final",
    "predict.proofreader_verdict.v1",
    "predict.request",
    "predict.vote",
    "qa.request",
    "qa.request.v1",
    "scrape.classified",
    "scrape.raw",
    "scrape.request",
    "sec.alert.v1",
    "sec.config.v1",
    "sec.denylist.v1",
    "sec.quarantine.v1",
    "source.watch.report.v1",
})


def dlq_meta_policy(origin_topic: str) -> str:
    """Return the ``__dlq_meta`` placement policy for *origin_topic*.

    ``"out_of_band"``
        The schema has ``additionalProperties:false``.  The bus adapter
        must carry ``__dlq_meta`` in the Redis Stream entry header and
        must NOT merge it into the message payload.

    ``"inject"``
        The schema is permissive; the replay layer may merge
        ``__dlq_meta`` directly into the payload dict before
        re-publication.  Payload schema validation still passes.
    """
    return "out_of_band" if origin_topic in _STRICT_PAYLOAD_TOPICS else "inject"


# DLQs we MUST NOT replay — replaying these would loop the maint
# plane on itself. Doctrine: append-only, every entry justified.
# §8.14.5 (binding): RECURSION_DENY_SET = {maint.dlq.v1.dlq,
# maint.event.v1.dlq, maint.ack.v1.dlq, sec.alert.v1.dlq} is the
# core four. Additional entries below extend the set conservatively.
# NOT operator-overridable (cfg.maint_dlq_replay_topics_deny exists
# only to make the deny set visible in config audit; values are
# always sourced from this constant, never from cfg).
RECURSION_DENY_SET: frozenset[str] = LEGACY_EXACT_DENY_TOPICS


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _parse_csv_set(raw: str) -> set[str]:
    """Parse ``"a,b,c"`` → ``{a, b, c}`` (whitespace-trimmed, empties
    dropped). Used by the dlq allow-list parser."""
    out: set[str] = set()
    for tok in raw.split(","):
        s = tok.strip()
        if s:
            out.add(s)
    return out


@dataclass
class _RunState:
    """Per-topic accounting: count replayed in current run, deque of
    last-seen request_ids for backoff."""

    replayed: int = 0
    last_run_at: float = 0.0
    seen: "OrderedDict[str, float]" = field(default_factory=OrderedDict)


@dataclass
class _RateBucket:
    """Per-topic token bucket over a rolling 60-second window. The
    actual token math is plain count + epoch-second floor — accurate
    enough for a 1-minute granularity rate cap and dependency-free."""

    minute_epoch: int = 0
    count: int = 0


@dataclass
class _RpsSecBucket:
    """Per-topic token bucket over a rolling 1-second window.
    Used by the Phase 8 §8.9 DoD ``maint_dlq_replay_rps`` cap."""

    sec_epoch: int = 0
    count: int = 0


class MaintDlqSupervisor(LivenessMixin):
    """`maint.dlq.v1` reactor.

    Subscribes ``maint.event.v1`` (kind=dlq_replay).
    Publishes ``maint.event.v1`` (notifications: dlq_replayed,
    dlq_escalated, dlq_topic_disabled_drained, dlq_dropped) and
    ``maint.ack.v1`` (acks for the operator request).
    """

    name = "maint.dlq.v1"
    subscribes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK, SEC_ALERT)

    def __init__(
        self,
        *,
        leader: Leader | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_s: Callable[[], float] | None = None,
        new_id: Callable[[], str] | None = None,
        liveness_clock: Callable[[], float] | None = None,
    ) -> None:
        self._leader = leader if leader is not None else SingleProcessLeader(name=self.name)
        self._clock_iso = clock_iso or _utc_iso
        self._clock_s = clock_s
        self._new_id = new_id or _new_id
        # Phase 8 §8.9 DoD — insertion-order LRU bounded at
        # ``cfg.maint_dlq_state_max``. Oldest entry evicted on cap
        # hit; cap-pressure alert fires when the evicted entry is
        # younger than backoff_s × backoff_factor × 3 (fill rate
        # outpaces the natural backoff window).
        self._state_max: int = max(1, int(_cfg.maint_dlq_state_max))
        self._state: "OrderedDict[str, _RunState]" = OrderedDict()
        # LRU of recently-seen request_ids for backoff dedup.
        self._req_lru: "OrderedDict[str, None]" = OrderedDict()
        # Per-topic budget from the last completed tick. Used to compute
        # ``in_flight_count`` when the allow-list removes a topic mid-replay
        # (§8.9 DoD: "DLQ allow-list mid-replay" bullet).
        self._last_tick_budgets: dict[str, int] = {}
        # Topics for which we already emitted ``dlq_topic_disabled_drained``
        # with ``in_flight_count`` (fires exactly once per removal event).
        # Cleared when the topic re-appears in the eligible set.
        self._disabled_notified: set[str] = set()
        # Per-(topic, request_id) visit-count map for escalation.
        # Bounded by ``cfg.maint_dlq_visit_lru`` per §8.9 DoD bullet
        # ("bounded state in every reactor").
        self._visit_lru: "OrderedDict[tuple[str, str], int]" = OrderedDict()
        # Per-topic rate bucket for ops.dlq-replay attempts/min.
        self._rate_buckets: dict[str, _RateBucket] = {}
        # Phase 8 §8.9 DoD — per-topic per-second rate bucket.
        self._rps_buckets: dict[str, _RpsSecBucket] = {}
        # Phase 8 §8.5 C2 — poison-pattern detection.
        # Per-topic deque of (escalation_ts_s, request_id). Trimmed
        # on insert by ``cfg.maint_dlq_consumer_broken_window_s``. When the
        # number of *distinct* request_ids in the window crosses
        # ``cfg.maint_dlq_consumer_broken_threshold`` the topic is
        # added to ``self._frozen_topics`` and refuses further
        # dlq_replay until an operator sends ``dlq_unfreeze``.
        from collections import deque as _deque
        self._poison_log: dict[str, "_deque[tuple[float, str]]"] = {}
        self._frozen_topics: dict[str, str] = {}  # topic → reason
        # Phase 8 §8.13.5 — pause/resume idempotency state.
        from .._pause_state import PauseState
        self._pause = PauseState()
        # Phase 8 §8.5 backlog-pressure damping. Per-topic state:
        #   ``trip_depth``: depth observed when the alert first fired
        #   ``alerted_at_s``: epoch s of last sec.alert.v1 emission
        # Topic stays in damped mode until depth ≤ trip_depth // 2;
        # once cleared, the entry is dropped from the dict and the
        # topic resumes its normal per-tick replay budget.
        self._backlog_damped: dict[str, dict[str, float]] = {}
        self._liveness_init(liveness_clock=liveness_clock)
        # Per-topic replay counter — incremented when a replay is
        # accepted (not blocked by deny/rate/freeze). Used by proof
        # tests (§8.14.5) to assert zero auto-replay for deny-set
        # topics. Also surfaced via telemetry as
        # ``maint_dlq_replays_total{topic}``.
        self._replays_total: dict[str, int] = {}
        # Tracks which deny-set orphans we have already alerted at
        # boot, so the alert fires exactly once per process lifetime.
        self._boot_recursion_alerted: set[str] = set()
        # §8.16.2 — spool-flush ack reconciler; runs inside this agent
        # as the ack-only consumer of maint.ack.v1 spool-flush envelopes.
        self._spool_ack_reconciler = SpoolAckReconciler(
            clock_s=clock_s,
            clock_iso=clock_iso,
            new_id=new_id,
        )

    def _now_s(self) -> float:
        if self._clock_s is not None:
            return self._clock_s()
        import time as _t
        return _t.time()

    def _current_allow_list(self) -> frozenset[str]:
        """Return the live allow-list from cfg. Re-parsed on every call
        to honour runtime config changes — operators can remove a topic
        at runtime and the supervisor honours the change on the next
        tick boundary."""
        return frozenset(_parse_csv_set(str(_cfg.maint_dlq_replay_topics_allow_csv)))

    def _current_allow_overrides(self) -> tuple[str, ...]:
        """Return the live operator-attested replay exceptions."""
        return current_allow_overrides()

    def _policy_deny_reason(self, target_dlq: str) -> str | None:
        """Return deny reason from the layered replay policy for a topic."""
        return replay_policy_deny_reason(
            target_dlq,
            allow_overrides=self._current_allow_overrides(),
        )

    def _is_allowed_topic(self, target_dlq: str) -> bool:
        """Return True iff topic passes policy and operator allow-list.

        Layered deny/override policy is always enforced first.
        """
        if self._policy_deny_reason(target_dlq) is not None:
            return False
        allow = self._current_allow_list()
        if not allow:
            return True
        return target_dlq in allow

    def boot_replay_policy_messages(self) -> list["Message"]:
        """Emit policy-loaded audit event + orphan allow-list warnings."""
        env = Envelope(
            message_id=self._new_id(),
            trace_id="boot-check",
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        payload = build_policy_loaded_payload(
            produced_at=self._clock_iso(),
            target=self.name,
            allow_overrides=self._current_allow_overrides(),
        )
        return [Message(envelope=env, payload=payload), *self.boot_check_allow_list()]

    def boot_check_allow_list(self) -> list["Message"]:
        """Scan the operator-supplied allow-list for topics that also
        appear in :data:`RECURSION_DENY_SET` (orphan entries).

        For each orphan found, emits a single
        ``sec.alert.v1{kind=dlq_recursion_blocked, severity=warn,
        source=maint.dlq.v1, subject=<topic>}`` alert **once per
        process lifetime** (idempotent via
        ``_boot_recursion_alerted``). The orphan does NOT become
        eligible for replay — :data:`RECURSION_DENY_SET` is
        unconditional and NOT operator-overridable.

        Returns the list of alert :class:`Message` objects so callers
        can inject them into the bus without holding a direct bus
        reference during boot.
        """
        allow = self._current_allow_list()
        alerts: list[Message] = []
        for topic in sorted(allow):  # sorted for determinism in tests
            if topic in RECURSION_DENY_SET and topic not in self._boot_recursion_alerted:
                self._boot_recursion_alerted.add(topic)
                alert = SecAlert(
                    alert_id=self._new_id(),
                    kind="dlq_recursion_blocked",
                    severity="warn",
                    source=self.name,
                    reason=(
                        f"allow-list entry {topic!r} is in "
                        "RECURSION_DENY_SET and will never be replayed; "
                        "remove it from cfg.maint_dlq_replay_topics_allow_csv"
                    )[:1024],
                    produced_at=self._clock_iso(),
                    subject=topic,
                )
                env = Envelope(
                    message_id=self._new_id(),
                    trace_id="boot-check",
                    topic=SEC_ALERT,
                    producer=self.name,
                    created_at=self._clock_iso(),
                    schema_version=1,
                    attempt=1,
                )
                alerts.append(Message(envelope=env, payload=alert.as_dict()))
        return alerts

    def _dlq_meta_policy(self, target_dlq: str) -> str:
        """Return the ``__dlq_meta`` placement policy for *target_dlq*.

        Strips the ``.dlq`` suffix to recover the origin topic name,
        then delegates to the module-level :func:`dlq_meta_policy`
        function.  The bus adapter uses this to decide whether to
        inject ``__dlq_meta`` into the payload or carry it out-of-band
        in the Redis Stream entry header (see :data:`_STRICT_PAYLOAD_TOPICS`).
        """
        origin = target_dlq[:-4] if target_dlq.endswith(".dlq") else target_dlq
        return dlq_meta_policy(origin)

    def _bump_visit(self, target_dlq: str, request_id: str) -> int:
        """Increment and return the visit-count for ``(topic, req)``.
        Bounded LRU eviction at cfg.maint_dlq_visit_lru."""
        key = (target_dlq, request_id)
        if key in self._visit_lru:
            self._visit_lru[key] += 1
            self._visit_lru.move_to_end(key)
        else:
            self._visit_lru[key] = 1
            cap = max(1, int(_cfg.maint_dlq_visit_lru))
            while len(self._visit_lru) > cap:
                self._visit_lru.popitem(last=False)
        return self._visit_lru[key]

    def _rps_rate_limited(self, target_dlq: str) -> bool:
        """Return True if ``target_dlq`` has exceeded
        ``cfg.maint_dlq_replay_rps`` replay attempts in the current
        1-second epoch window (Phase 8 §8.9 DoD)."""
        cap = max(1, int(_cfg.maint_dlq_replay_rps))
        now_s = self._now_s()
        sec_epoch = int(now_s)
        bucket = self._rps_buckets.get(target_dlq)
        if bucket is None or bucket.sec_epoch != sec_epoch:
            bucket = _RpsSecBucket(sec_epoch=sec_epoch, count=0)
            self._rps_buckets[target_dlq] = bucket
        if bucket.count >= cap:
            return True
        bucket.count += 1
        return False

    def _rate_limited(self, target_dlq: str) -> bool:
        """Return True if ``target_dlq`` has exceeded
        ``cfg.maint_dlq_per_topic_max_per_min`` replay attempts in
        the current 60-second epoch window."""
        cap = max(1, int(_cfg.maint_dlq_per_topic_max_per_min))
        now_s = self._now_s()
        minute_epoch = int(now_s) // 60
        bucket = self._rate_buckets.get(target_dlq)
        if bucket is None or bucket.minute_epoch != minute_epoch:
            bucket = _RateBucket(minute_epoch=minute_epoch, count=0)
            self._rate_buckets[target_dlq] = bucket
        if bucket.count >= cap:
            return True
        bucket.count += 1
        return False

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        # §8.16.2 — ack-only consumer of maint.ack.v1 spool-flush envelopes.
        # Sweep is called on every tick regardless of topic so deadline-
        # elapsed windows are closed even without incoming acks.
        if topic == MAINT_ACK:
            return list(self._handle_spool_ack(msg))
        if topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        # ── §8.14.4 signature / authz gate (binding) ─────────────────────
        _sig_ok, _sig_reason, _alert_kind = gate_op_envelope(payload, _cfg)
        if not _sig_ok:
            _req_id = str(payload.get("request_id") or msg.envelope.message_id)
            _ack = self._ack(msg, _req_id, accepted=False, reason=_sig_reason)
            _alert = SecAlert(
                alert_id=self._new_id(),
                kind=_alert_kind,
                severity="critical",
                source=self.name,
                reason=_sig_reason,
                produced_at=self._clock_iso(),
                subject=str(payload.get("op_key_id") or "unknown"),
            )
            _alert_env = Envelope(
                message_id=self._new_id(),
                trace_id=msg.envelope.trace_id,
                topic=SEC_ALERT,
                producer=self.name,
                created_at=self._clock_iso(),
                schema_version=1,
                attempt=1,
            )
            return [_ack, Message(envelope=_alert_env, payload=_alert.as_dict())]
        # ─────────────────────────────────────────────────────────────────
        kind = payload.get("kind")
        if kind == "dlq_replay":
            return list(self._handle_replay(msg, payload))
        if kind == "dlq_unfreeze":
            return list(self._handle_unfreeze(msg, payload))
        if kind == "dlq_drop_request":
            return list(self._handle_drop_request(msg, payload))
        if kind == "maint_pause":
            return list(self._handle_pause(msg, payload, paused=True))
        if kind == "maint_resume":
            return list(self._handle_pause(msg, payload, paused=False))
        return ()  # ignore other kinds

    # §8.16.2 — spool-flush ack reconciliation ────────────────────
    def _handle_spool_ack(self, msg: Message) -> Iterable[Message]:
        """Consume a ``maint.ack.v1`` emitted by a spool-flush consumer.

        Delegates to :class:`SpoolAckReconciler` to back-fill the
        per-consumer ack receipt.  Also calls ``sweep()`` to close any
        deadline-elapsed windows so the reconciler does not stall if no
        further acks arrive.

        Only acks that carry a ``flush_invocation_id`` in their
        ``details`` dict are forwarded to the reconciler; all others are
        silently ignored (they belong to normal operator-command acks
        and are consumed by ops_console, not by us).
        """
        payload = msg.payload or {}
        details = payload.get("details") or {}
        flush_invocation_id = str(details.get("flush_invocation_id") or "").strip()
        if not flush_invocation_id:
            # Not a spool-flush ack — ignore (normal acks go to ops_console).
            yield from self._spool_ack_reconciler.sweep()
            return

        request_id = str(payload.get("request_id") or "").strip()
        accepted_by = str(payload.get("accepted_by") or "").strip()
        if not request_id or not accepted_by:
            yield from self._spool_ack_reconciler.sweep()
            return

        # Extract expected consumer set from details when present.
        raw_expected = details.get("expected_ack_consumers")
        expected = frozenset(raw_expected) if isinstance(raw_expected, list) else None

        yield from self._spool_ack_reconciler.reconcile(
            flush_invocation_id=flush_invocation_id,
            request_id=request_id,
            accepted_by=accepted_by,
            expected=expected,
        )
        yield from self._spool_ack_reconciler.sweep()

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

        # Layered replay-policy deny.
        policy_reason = self._policy_deny_reason(target_dlq)
        if policy_reason is not None:
            yield self._ack(msg, request_id, accepted=False,
                            reason=policy_reason)
            yield self._notify("dlq_topic_disabled_drained",
                               target=target_dlq,
                               extra={"deny_reason": policy_reason,
                                      "request_id": request_id})
            return

        # Allow-list gate (when configured). Sec/PII DLQs default to
        # the recursion deny set above; this gate is for everything
        # else where the operator opts in explicitly.
        if not self._is_allowed_topic(target_dlq):
            yield self._ack(msg, request_id, accepted=False,
                            reason="allow_list_excluded")
            yield self._notify("dlq_topic_disabled_drained",
                               target=target_dlq,
                               extra={"deny_reason": "allow_list_excluded",
                                      "request_id": request_id})
            return

        # Backoff dedup — same request_id within the LRU window.
        # cfg.maint_dlq_backoff_lru = 0 disables backoff dedup (used
        # by tests that want to exercise the visit-count escalator).
        backoff_lru = int(_cfg.maint_dlq_backoff_lru)
        if backoff_lru > 0:
            if request_id in self._req_lru:
                yield self._ack(msg, request_id, accepted=False,
                                reason="backoff_dedup")
                yield self._notify("dlq_dropped",
                                   target=target_dlq,
                                   extra={"reason": "backoff_dedup",
                                          "request_id": request_id})
                return
            self._req_lru[request_id] = None
            while len(self._req_lru) > backoff_lru:
                self._req_lru.popitem(last=False)

        # Per-topic per-second rate limit (cfg.maint_dlq_replay_rps).
        if self._rps_rate_limited(target_dlq):
            yield self._ack(msg, request_id, accepted=False,
                            reason="rate_limited")
            yield self._notify("dlq_dropped",
                               target=target_dlq,
                               extra={"reason": "rate_limited",
                                      "request_id": request_id})
            return

        # Per-topic rate limit (cfg.maint_dlq_per_topic_max_per_min).
        if self._rate_limited(target_dlq):
            yield self._ack(msg, request_id, accepted=False,
                            reason="rate_limited")
            yield self._notify("dlq_dropped",
                               target=target_dlq,
                               extra={"reason": "rate_limited",
                                      "request_id": request_id})
            return

        # Phase 8 §8.5 C2 — refuse if topic is currently frozen by
        # the poison-pattern detector. Operator must send
        # ``dlq_unfreeze`` to lift.
        if target_dlq in self._frozen_topics:
            yield self._ack(msg, request_id, accepted=False,
                            reason="topic_frozen")
            yield self._notify("dlq_dropped",
                               target=target_dlq,
                               extra={"reason": "topic_frozen",
                                      "request_id": request_id})
            return

        # Visit count + escalation. The first ``cfg.maint_dlq_visit_max``
        # visits replay; the visit AFTER that triggers escalation and
        # refuses further replays for this (topic, request_id).
        visit_count = self._bump_visit(target_dlq, request_id)
        visit_max = max(1, int(_cfg.maint_dlq_visit_max))
        if visit_count > visit_max:
            yield self._ack(msg, request_id, accepted=False,
                            reason="dlq_escalated")
            yield self._notify("dlq_escalated",
                               target=target_dlq,
                               extra={"request_id": request_id,
                                      "visit_count": visit_count,
                                      "reason": "visit_max_exceeded"})
            # Phase 8 §8.5 C2 — record this escalation in the
            # poison-pattern window. If we just crossed the distinct-
            # request_id threshold, freeze the topic, emit
            # ``sec.alert.v1{kind=consumer_likely_broken}`` (the
            # canonical operational alert per ROADMAP §8.5), and emit
            # ``dlq_consumer_broken`` on maint.event.v1 for the audit
            # trail (both per the _emit_backlog_alert pattern).
            if self._record_escalation(target_dlq, request_id):
                self._frozen_topics[target_dlq] = "poison_pattern"
                distinct = len({r for _, r in self._poison_log[target_dlq]})
                yield from self._emit_consumer_broken_alert(
                    target_dlq, distinct
                )
            return

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
        pressure_alerts = self._bump_state(target_dlq)
        st = self._state[target_dlq]
        st.replayed = replayed
        # §8.14.5: telemetry counter — incremented on every accepted
        # operator-commanded replay (deny-set and rate-limited paths
        # return early above, so this line is only reached for actual
        # accepted replays).
        self._replays_total[target_dlq] = (
            self._replays_total.get(target_dlq, 0) + 1
        )
        yield from iter(pressure_alerts)
        yield self._notify("dlq_replayed",
                           target=target_dlq,
                           extra={"replayed_count": replayed,
                                  "max_msgs": max_msgs,
                                  "request_id": request_id,
                                  "visit_count": visit_count})
        yield self._ack(msg, request_id, accepted=True,
                        reason="replayed",
                        details={"replayed_count": replayed,
                                 "visit_count": visit_count})

    # ── Periodic round-robin tick (Phase 8 §8.5 C1) ──────────────
    def tick(self, active_topics: list[str],
             *, depths: dict[str, int] | None = None,
             lag_tier: int = 0) -> list[Message]:
        """Run a fair-share periodic replay across ``active_topics``.

        Per-topic budget = ``max(1, cfg.maint_dlq_max_replays_per_tick
        // len(eligible))`` where ``eligible`` is ``active_topics``
        minus :data:`RECURSION_DENY_SET` minus topics currently rate-
        limited by the per-minute token bucket. The supervisor then
        emits one ``dlq_replayed`` notification per eligible topic
        with ``replayed_count=0`` (the actual bus-side replay
        primitive lands in §8.5b — the fairness scheduler is
        independent of that).

        ``depths`` (optional) maps each DLQ topic to its current
        observed depth (e.g. ``XLEN``). When provided, Phase 8 §8.5
        backlog-pressure damping fires: any topic whose depth
        exceeds ``cfg.maint_dlq_backlog_alert`` enters damped mode
        (per-tick budget quartered, debounced ``dlq_backlog_high``
        ``sec.alert.v1`` emitted) until its depth falls below half
        the trip depth. Caller may omit ``depths`` to retain v1
        behaviour (no damping).

        ``lag_tier`` is the current maint-plane lag tier (§8.11):
        0 = healthy; 1 = budget halved; 2 = drain-only (no periodic
        replays, only operator-driven escalations); 3 = observer-only.

        Returns the emitted messages so the caller (the bootstrap
        loop) can publish them. Honours leader gate + pause flag.
        """
        # Phase 8 §8.11 — tier-3: observer-only, emit nothing.
        if lag_tier >= 3:
            return []
        if not active_topics:
            return []
        if not self._leader.is_leader():
            return []
        # Honour pause/self-isolation (§8.13.5 idempotency matrix).
        self._pause.expire_if_due(int(self._now_s() * 1_000_000_000))
        if self._pause.paused or self._pause.self_isolated:
            return []
        active_set = set(active_topics)
        eligible: list[str] = []
        skipped_recursion: list[tuple[str, str]] = []
        skipped_rate: list[str] = []
        for t in active_topics:
            policy_reason = self._policy_deny_reason(t)
            if policy_reason is not None:
                skipped_recursion.append((t, policy_reason))
                continue
            if not self._is_allowed_topic(t):
                skipped_recursion.append((t, "allow_list_excluded"))
                continue
            # Probe the rate bucket WITHOUT consuming a token; the
            # actual replay loop in §8.5b consumes from the bus side.
            cap = max(1, int(_cfg.maint_dlq_per_topic_max_per_min))
            now_s = self._now_s()
            minute_epoch = int(now_s) // 60
            bucket = self._rate_buckets.get(t)
            if bucket is not None and bucket.minute_epoch == minute_epoch and bucket.count >= cap:
                skipped_rate.append(t)
                continue
            # Probe per-second RPS cap WITHOUT consuming a token.
            rps_cap = max(1, int(_cfg.maint_dlq_replay_rps))
            sec_epoch = int(now_s)
            rps_bucket = self._rps_buckets.get(t)
            if rps_bucket is not None and rps_bucket.sec_epoch == sec_epoch and rps_bucket.count >= rps_cap:
                skipped_rate.append(t)
                continue
            eligible.append(t)
        out: list[Message] = []
        # §8.9 DoD — mid-tick allow-list removal detection.
        # If a topic was in our per-topic budget map from the last tick
        # but is now excluded, emit ``dlq_topic_disabled_drained`` with
        # ``in_flight_count`` exactly once (fires on the first tick after
        # the operator removes the topic from the allow-list).
        current_allow = self._current_allow_list()
        for t, prev_budget in list(self._last_tick_budgets.items()):
            if t not in active_set or t in self._disabled_notified:
                continue
            # Topic still presented as active but now excluded.
            policy_reason = self._policy_deny_reason(t)
            if policy_reason is not None or (current_allow and t not in current_allow):
                out.append(self._notify(
                    "dlq_topic_disabled_drained",
                    target=t,
                    extra={
                        "deny_reason": policy_reason or "allow_list_excluded",
                        "in_flight_count": prev_budget,
                    },
                ))
                self._disabled_notified.add(t)
        for t, reason in skipped_recursion:
            out.append(self._notify("dlq_topic_disabled_drained",
                                    target=t,
                                    extra={"deny_reason": reason}))
        for t in skipped_rate:
            out.append(self._notify("dlq_dropped",
                                    target=t,
                                    extra={"reason": "rate_limited",
                                           "scheduler": "round_robin"}))
        if not eligible:
            return out
        # Phase 8 §8.11 — tier-2: drain-only (no periodic replays;
        # operator-commanded replays via _handle_replay() still run).
        if lag_tier >= 2:
            return out
        # Phase 8 §8.5 — backlog-pressure damping per topic.
        damped_topics: set[str] = set()
        if depths:
            damped_topics = self._update_backlog_damping(depths, out)
        total_budget = max(1, int(_cfg.maint_dlq_max_replays_per_tick))
        # Phase 8 §8.11 — tier-1: halve the replay budget.
        if lag_tier >= 1:
            total_budget = max(1, total_budget // 2)
        per_topic = max(1, total_budget // len(eligible))
        # Damped topics receive 1/4 of the per-topic budget (floor 1)
        # so a broken consumer is not flooded harder. ROADMAP §8.5:
        # "drops the per-topic replay rate to replay_rps / 4 until
        # depth halves".
        new_last_tick_budgets: dict[str, int] = {}
        for t in eligible:
            out.extend(self._bump_state(t))
            st = self._state[t]
            st.replayed = 0  # v1 stub: §8.5b plumbs Bus.replay_dlq()
            topic_budget = max(1, per_topic // 4) if t in damped_topics else per_topic
            # Track budget for mid-tick allow-list removal detection on
            # the next tick (§8.9 DoD "DLQ allow-list mid-replay").
            new_last_tick_budgets[t] = topic_budget
            # Re-enabled: clear the one-shot disabled-notification flag.
            self._disabled_notified.discard(t)
            extra = {
                "replayed_count": 0,
                "max_msgs": topic_budget,
                "request_id": f"tick:{t}",
                "budget_per_topic": topic_budget,
                "active_topic_count": len(eligible),
                "scheduler": "round_robin",
            }
            if t in damped_topics:
                extra["backlog_damped"] = True
            out.append(self._notify("dlq_replayed",
                                    target=t,
                                    extra=extra))
        # Persist this tick's budgets for the next tick's mid-replay detection.
        self._last_tick_budgets = new_last_tick_budgets
        return out

    # ── §8.5 backlog-pressure damping ────────────────────────────
    def _update_backlog_damping(
        self,
        depths: dict[str, int],
        out: list[Message],
    ) -> set[str]:
        """Update damped-topic state from a fresh ``{topic: depth}``
        snapshot. Appends ``dlq_backlog_high`` ``sec.alert.v1`` and a
        ``dlq_backlog_high`` ``maint.event.v1`` notification to
        ``out`` per ROADMAP §8.5 binding (debounced re-emission on
        the alert path; the maint.event.v1 mirror is always emitted
        for the audit trail). Returns the set of topics currently
        in damped mode (so the caller can quarter their per-tick
        budget).
        """
        threshold = max(1, int(_cfg.maint_dlq_backlog_alert))
        # Re-alert at most once per ``cfg.maint_dlq_replay_backoff_s``
        # so a sustained backlog does not page the on-call team
        # repeatedly. Mirrors the §7.3 debouncer cadence.
        debounce_s = max(1, int(_cfg.maint_dlq_replay_backoff_s))
        now_s = self._now_s()
        damped: set[str] = set()
        for topic, depth in depths.items():
            if topic in RECURSION_DENY_SET:
                continue
            depth_int = int(depth)
            state = self._backlog_damped.get(topic)
            # Recovery check first: damping clears as soon as depth
            # falls to half of the trip depth, even if depth is
            # still above the alert threshold (ROADMAP §8.5: "until
            # depth halves" — recovery is half of trip, not half
            # of threshold).
            if state is not None:
                half_trip = float(state.get("trip_depth", 0.0)) / 2.0
                if depth_int <= half_trip:
                    del self._backlog_damped[topic]
                    state = None
            if depth_int > threshold:
                if state is None:
                    # First trip (or re-trip after recovery): record
                    # trip depth and emit the alert.
                    state = {
                        "trip_depth": float(depth_int),
                        "alerted_at_s": float(now_s),
                    }
                    self._backlog_damped[topic] = state
                    out.extend(self._emit_backlog_alert(topic, depth_int))
                else:
                    # Sustained: re-alert if outside debounce window.
                    if now_s - float(state.get("alerted_at_s", 0.0)) >= debounce_s:
                        state["alerted_at_s"] = float(now_s)
                        out.extend(self._emit_backlog_alert(topic, depth_int))
                damped.add(topic)
            elif state is not None:
                # depth ≤ threshold but still above trip_depth // 2
                # ⇒ stay damped, no new alert.
                damped.add(topic)
        return damped

    def _emit_backlog_alert(self, topic: str, depth: int) -> list[Message]:
        """Emit the paired ``sec.alert.v1{kind=dlq_backlog_high}`` and
        ``maint.event.v1{kind=dlq_backlog_high}`` envelopes for a
        single observed trip. Severity is ``warn`` per ROADMAP §8.5
        (an ``error`` severity here would re-page on every tick a
        broken consumer is down — defeats the damping purpose)."""
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="dlq_backlog_high",
            severity="warn",
            source=self.name,
            reason=(
                f"depth={depth} > cfg.maint_dlq_backlog_alert="
                f"{int(_cfg.maint_dlq_backlog_alert)}"
            ),
            produced_at=self._clock_iso(),
            subject=topic,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=SEC_ALERT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        notif = self._notify(
            "dlq_backlog_high",
            target=topic,
            extra={
                "depth": int(depth),
                "threshold": int(_cfg.maint_dlq_backlog_alert),
                "damped_budget_factor": 4,
            },
        )
        return [Message(envelope=env, payload=alert.as_dict()), notif]

    def _emit_consumer_broken_alert(
        self, topic: str, distinct: int
    ) -> list[Message]:
        """Emit the paired ``sec.alert.v1{kind=consumer_likely_broken,
        severity=error}`` and ``maint.event.v1{kind=dlq_consumer_broken}``
        messages when the poison-pattern threshold is crossed.

        The ``sec.alert.v1`` is the canonical operational pager per
        ROADMAP §8.5. The ``maint.event.v1`` mirror is retained for
        the audit trail (mirrors the ``_emit_backlog_alert`` pattern).
        Edge-triggered: the caller only invokes this once per crossing.
        """
        window_s = max(1, int(_cfg.maint_dlq_consumer_broken_window_s))
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="consumer_likely_broken",
            severity="error",
            source=self.name,
            reason=(
                f"distinct_escalations={distinct} >= "
                f"cfg.maint_dlq_consumer_broken_threshold="
                f"{int(_cfg.maint_dlq_consumer_broken_threshold)} "
                f"within {window_s}s window"
            ),
            produced_at=self._clock_iso(),
            subject=topic,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=SEC_ALERT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        notif = self._notify(
            "dlq_consumer_broken",
            target=topic,
            extra={
                "reason": "poison_pattern",
                "distinct_request_ids": distinct,
                "window_s": window_s,
            },
        )
        return [Message(envelope=env, payload=alert.as_dict()), notif]

    # ── Helpers ───────────────────────────────────────────────────
    # ── State-cap LRU + pressure alert ──────────────────────────
    def _bump_state(self, topic: str) -> list[Message]:
        """Upsert ``topic`` in ``_state``, update ``last_run_at``, and
        enforce the ``_state_max`` LRU cap.

        Returns a list with a single ``sec.alert.v1{kind=
        dlq_state_pressure}`` message if an eviction occurred AND the
        evicted entry was younger than the cap-pressure window
        (``maint_dlq_replay_backoff_s × maint_dlq_backoff_factor × 3``);
        otherwise returns an empty list.
        """
        now_s = self._now_s()
        if topic in self._state:
            self._state.move_to_end(topic)
            self._state[topic].last_run_at = now_s
            return []
        # New entry — insert, then evict if over cap.
        self._state[topic] = _RunState(last_run_at=now_s)
        out: list[Message] = []
        while len(self._state) > self._state_max:
            _evicted_topic, evicted_st = self._state.popitem(last=False)
            backoff_s = max(1, int(_cfg.maint_dlq_replay_backoff_s))
            factor = max(1, int(_cfg.maint_dlq_backoff_factor))
            pressure_window_s = float(backoff_s * factor * 3)
            if (now_s - evicted_st.last_run_at) < pressure_window_s:
                out.append(self._make_state_pressure_alert())
        return out

    def _make_state_pressure_alert(self) -> Message:
        """Build ``sec.alert.v1{kind=dlq_state_pressure, severity=warn}``."""
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="dlq_state_pressure",
            severity="warn",
            source=self.name,
            reason=(
                f"state cap {self._state_max} hit; "
                "fill rate outpaces backoff window"
            ),
            produced_at=self._clock_iso(),
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=SEC_ALERT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=alert.as_dict())

    def _record_escalation(self, topic: str, request_id: str) -> bool:
        """Append an escalation event to the topic's poison window
        and return True iff the freeze threshold was just crossed.

        Trims expired entries on insert (window =
        ``cfg.maint_dlq_consumer_broken_window_s`` seconds). The detector
        is edge-triggered: it returns True only on the transition,
        never re-fires while the topic stays above threshold.
        """
        from collections import deque
        now_s = self._now_s()
        window_s = max(1, int(_cfg.maint_dlq_consumer_broken_window_s))
        threshold = max(2, int(_cfg.maint_dlq_consumer_broken_threshold))
        log = self._poison_log.setdefault(topic, deque())
        # Prune expired
        cutoff = now_s - window_s
        while log and log[0][0] < cutoff:
            log.popleft()
        # Track distinct count BEFORE insert to detect the edge.
        distinct_before = len({r for _, r in log})
        log.append((now_s, request_id))
        distinct_after = len({r for _, r in log})
        already_frozen = topic in self._frozen_topics
        crossed = (distinct_before < threshold <= distinct_after) and not already_frozen
        return crossed

    def _handle_unfreeze(self, msg: Message, payload: dict) -> Iterable[Message]:
        """Operator command: lift a poison-pattern freeze on a topic.

        Phase 8 §8.5 C2 / §8.13.5 idempotency matrix.

        When the topic is already unfrozen, the ack reason is
        context-sensitive per the §8.13.5 matrix:

        * agent running  → ``already_running``
        * agent paused   → ``paused_not_blocked``  (topic not blocked, agent is)
        * agent self-isolated → ``already_unfrozen`` (no-op/partial per spec)

        When the topic IS frozen, always ``unfrozen`` (regardless of
        agent pause/isolation state — the operator clears the per-topic
        freeze even while the agent is paused or self-isolated, giving
        a partial outcome: topic unfrozen, but replays remain blocked
        by the agent's own pause/isolation until that is lifted).
        """
        request_id = str(payload.get("request_id") or "")
        target_dlq = str(payload.get("target") or "")
        if not request_id or not target_dlq:
            return
        if not self._leader.is_leader():
            yield self._ack(msg, request_id, accepted=True, reason="non_leader_noop")
            return
        # Honour TTL expiry before reading pause state.
        now_ns = int(self._now_s() * 1_000_000_000)
        self._pause.expire_if_due(now_ns)
        was_frozen = self._frozen_topics.pop(target_dlq, None) is not None
        # Drop the poison log so the next burst starts fresh.
        self._poison_log.pop(target_dlq, None)
        if was_frozen:
            reason = "unfrozen"
        elif self._pause.paused:
            # §8.13.5: paused + dlq-resume (not blocked) → paused_not_blocked
            reason = "paused_not_blocked"
        elif self._pause.self_isolated:
            # §8.13.5: self-isolated + dlq-resume (not blocked) → no-op
            reason = "already_unfrozen"
        else:
            # §8.13.5: running + dlq-resume (not blocked) → already_running
            reason = "already_running"
        yield self._ack(msg, request_id, accepted=True, reason=reason)
        yield self._notify("dlq_topic_unfrozen",
                           target=target_dlq,
                           extra={"request_id": request_id,
                                  "was_frozen": was_frozen})

    # ── dlq_drop_request (§8.15.9 operator explicit drop) ────────
    def _handle_drop_request(
        self, msg: Message, payload: dict
    ) -> "Iterable[Message]":
        """Operator command: explicitly drop a DLQ entry without replaying it.

        Phase 8 §8.15.9 — the ops console sends ``kind=dlq_drop_request`` to
        purge a poisoned or no-longer-relevant entry from the DLQ. The
        supervisor acks the request AND emits ``kind=dlq_dropped{reason=
        operator_drop}`` with full forensic fields so the audit channel
        can reconstruct who dropped what and why.

        The opsctl §8.14.4 signature gate has already run (in ``handle()``).
        """
        request_id = str(payload.get("request_id") or "")
        target_dlq = str(payload.get("target") or "")

        # Non-leader hot-spares ack so the ops console gets a full set.
        if not self._leader.is_leader():
            yield self._ack(msg, request_id, accepted=True, reason="leader_skip")
            return

        # Recursion deny check — cannot drop from protected DLQs.
        if target_dlq in RECURSION_DENY_SET:
            yield self._ack(msg, request_id, accepted=False,
                            reason="recursion_deny")
            return

        # Extract forensic fields forwarded from the operator's payload.
        dlq_entry_id = str(payload.get("dlq_entry_id") or "")
        original_request_id = str(payload.get("original_request_id") or "")
        original_envelope_summary: dict = (
            payload.get("original_envelope_summary") or {}
        )
        drop_reason = str(
            payload.get("drop_reason") or "operator_explicit_drop"
        )
        dropped_by = str(
            payload.get("dropped_by") or payload.get("op_key_id") or "unknown"
        )

        # Ack the operator first, then emit the audit notification so the
        # ops console always sees the ack regardless of the notify path.
        yield self._ack(msg, request_id, accepted=True, reason="dropped")

        # Derive origin topic from the DLQ topic name (strip .dlq suffix
        # if present; otherwise use the target as-is).
        origin_topic = (
            target_dlq[: -len(".dlq")]
            if target_dlq.endswith(".dlq")
            else target_dlq
        )
        yield self._notify(
            "dlq_dropped",
            target=target_dlq,
            extra={
                "reason": "operator_drop",
                "topic": origin_topic,
                "dlq_entry_id": dlq_entry_id,
                "original_request_id": original_request_id,
                "original_envelope_summary": original_envelope_summary,
                "dropped_by": dropped_by,
                "drop_reason": drop_reason,
            },
        )

    # ── maint_pause / maint_resume (§8.13.5 idempotency matrix) ──
    def _handle_pause(self, msg: Message, payload: dict, *, paused: bool) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target = str(payload.get("target") or "")
        if not request_id:
            return
        if target not in ("all", self.name):
            yield self._ack(msg, request_id, accepted=True, reason="not_targeted")
            return
        now_ns = int(self._now_s() * 1_000_000_000)
        # §8.13.5 bullet 4: emit maint_resumed when TTL auto-expires so the
        # operator sees the expiry event regardless of what command arrives next.
        if self._pause.expire_if_due(now_ns):
            yield self._notify_lifecycle("maint_resumed",
                                         extra={"reason": "ttl_expired"})
        if paused:
            ttl_s = int(payload.get("ttl_s") or 0) or int(_cfg.maint_pause_default_ttl_s)
            res = self._pause.apply_pause(ttl_s=ttl_s, now_ns=now_ns)
        else:
            res = self._pause.apply_resume()
        details: dict | None = None
        if res.deadline_ns is not None:
            # §8.13.5 bullet 3: audit row carries both requested and effective TTL.
            details = {
                "ttl_s": (res.deadline_ns - now_ns) // 1_000_000_000,
                "requested_ttl_s": res.requested_ttl_s,
                "effective_ttl_s": res.effective_ttl_s,
            }
        yield self._ack(msg, request_id, accepted=res.accepted,
                        reason=res.reason, details=details)
        # §8.13.5 self-isolation precedence: when a maint-pause is rejected
        # because the agent is self-isolated, emit a sec.alert.v1 so the
        # operator has a pager-level signal to investigate before resuming.
        if not res.accepted and paused:
            yield self._emit_pause_rejected_alert(msg, request_id)
        # §8.13.5 bullet 4: emit maint_paused lifecycle notification.
        # Re-pause cases carry explicit action=ttl_refresh or action=no_op.
        if paused and res.accepted:
            evt_extra: dict | None = None
            if res.reason == "ttl_refreshed":
                evt_extra = {"action": "ttl_refresh"}
            elif res.reason == "already_paused":
                evt_extra = {"action": "no_op"}
            yield self._notify_lifecycle("maint_paused", extra=evt_extra)

    def _emit_pause_rejected_alert(
        self, msg: Message, request_id: str
    ) -> Message:
        """Emit ``sec.alert.v1{kind=maint_pause_rejected, severity=warn}``
        when a ``maint_pause`` is refused because the agent is self-isolated
        (§8.13.5 self-isolation precedence). Operator must issue
        ``maint_resume`` to clear the involuntary isolation before any
        pause command will be accepted.
        """
        alert = SecAlert(
            alert_id=self._new_id(),
            kind="maint_pause_rejected",
            severity="warn",
            source=self.name,
            reason="self_isolated",
            produced_at=self._clock_iso(),
            subject=request_id,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=msg.envelope.trace_id,
            topic=SEC_ALERT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=alert.as_dict())

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
            trace_id=msg.envelope.trace_id,
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

    def _notify_lifecycle(self, kind: str, *,
                          extra: dict | None = None) -> Message:
        """Emit a self-scoped lifecycle notification (maint_paused / maint_resumed).

        Uses ``agent_id`` (not ``target``) per the §8.9 sub-schema for these
        kinds — they are self-announcements, not target-scoped decisions.
        """
        payload: dict = {
            "kind": kind,
            "kind_schema_version": 1,
            "agent_id": self.name,
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


__all__ = [
    "MaintDlqSupervisor",
    "RECURSION_DENY_SET",
    "_STRICT_PAYLOAD_TOPICS",
    "dlq_meta_policy",
]
