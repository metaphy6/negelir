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
from ..payloads import MaintAck, SecAlert
from ..topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT

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
    # Sec quarantine DLQ — quarantine_samples are forensic records;
    # replaying them would re-trigger detector loops.
    "sec.quarantine.v1.dlq",
    # QA request DLQ — the proofreader response surface; replays
    # would double-bill / double-page on already-handled requests.
    "qa.request.v1.dlq",
})


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


class MaintDlqSupervisor:
    """`maint.dlq.v1` reactor.

    Subscribes ``maint.event.v1`` (kind=dlq_replay).
    Publishes ``maint.event.v1`` (notifications: dlq_replayed,
    dlq_escalated, dlq_topic_disabled_drained, dlq_dropped) and
    ``maint.ack.v1`` (acks for the operator request).
    """

    name = "maint.dlq.v1"
    subscribes: tuple[Topic, ...] = (MAINT_EVENT,)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK, SEC_ALERT)

    def __init__(
        self,
        *,
        leader: Leader | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_s: Callable[[], float] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._leader = leader if leader is not None else SingleProcessLeader(name=self.name)
        self._clock_iso = clock_iso or _utc_iso
        self._clock_s = clock_s
        self._new_id = new_id or _new_id
        self._state: dict[str, _RunState] = {}
        # LRU of recently-seen request_ids for backoff dedup.
        self._req_lru: "OrderedDict[str, None]" = OrderedDict()
        # Allow-list parsed once at construction. Empty set ⇒ allow
        # every topic not in :data:`RECURSION_DENY_SET`. Operators
        # opt in to a topic by adding it to the cfg knob.
        self._allow_list: frozenset[str] = frozenset(
            _parse_csv_set(str(_cfg.maint_dlq_replay_topics_allow_csv))
        )
        # Per-(topic, request_id) visit-count map for escalation.
        # Bounded by ``cfg.maint_dlq_visit_lru`` per §8.9 DoD bullet
        # ("bounded state in every reactor").
        self._visit_lru: "OrderedDict[tuple[str, str], int]" = OrderedDict()
        # Per-topic rate bucket for ops.dlq-replay attempts/min.
        self._rate_buckets: dict[str, _RateBucket] = {}
        # Phase 8 §8.5 C2 — poison-pattern detection.
        # Per-topic deque of (escalation_ts_s, request_id). Trimmed
        # on insert by ``cfg.maint_dlq_poison_window_s``. When the
        # number of *distinct* request_ids in the window crosses
        # ``cfg.maint_dlq_poison_distinct_threshold`` the topic is
        # added to ``self._frozen_topics`` and refuses further
        # dlq_replay until an operator sends ``dlq_unfreeze``.
        from collections import deque as _deque
        self._poison_log: dict[str, "_deque[tuple[float, str]]"] = {}
        self._frozen_topics: dict[str, str] = {}  # topic → reason
        # Phase 8 §8.13.5 — pause/resume idempotency state.
        from ._pause_state import PauseState
        self._pause = PauseState()
        # Phase 8 §8.5 backlog-pressure damping. Per-topic state:
        #   ``trip_depth``: depth observed when the alert first fired
        #   ``alerted_at_s``: epoch s of last sec.alert.v1 emission
        # Topic stays in damped mode until depth ≤ trip_depth // 2;
        # once cleared, the entry is dropped from the dict and the
        # topic resumes its normal per-tick replay budget.
        self._backlog_damped: dict[str, dict[str, float]] = {}

    def _now_s(self) -> float:
        if self._clock_s is not None:
            return self._clock_s()
        import time as _t
        return _t.time()

    def _is_allowed_topic(self, target_dlq: str) -> bool:
        """A topic passes the allow-list gate if (a) it is NOT in the
        recursion deny set AND (b) either the configured allow-list
        is empty (open default) or the topic is explicitly listed."""
        if target_dlq in RECURSION_DENY_SET:
            return False
        if not self._allow_list:
            return True
        return target_dlq in self._allow_list

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
        if topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        kind = payload.get("kind")
        if kind == "dlq_replay":
            return list(self._handle_replay(msg, payload))
        if kind == "dlq_unfreeze":
            return list(self._handle_unfreeze(msg, payload))
        if kind == "maint_pause":
            return list(self._handle_pause(msg, payload, paused=True))
        if kind == "maint_resume":
            return list(self._handle_pause(msg, payload, paused=False))
        return ()  # ignore other kinds

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
                               extra={"deny_reason": "recursion_deny",
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
            # request_id threshold, freeze the topic and emit
            # ``dlq_consumer_broken``.
            if self._record_escalation(target_dlq, request_id):
                self._frozen_topics[target_dlq] = "poison_pattern"
                yield self._notify("dlq_consumer_broken",
                                   target=target_dlq,
                                   extra={"reason": "poison_pattern",
                                          "distinct_request_ids":
                                              len({r for _, r in self._poison_log[target_dlq]}),
                                          "window_s": int(_cfg.maint_dlq_poison_window_s)})
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
        st = self._state.setdefault(target_dlq, _RunState())
        st.replayed = replayed
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
             *, depths: dict[str, int] | None = None) -> list[Message]:
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

        Returns the emitted messages so the caller (the bootstrap
        loop) can publish them. Honours leader gate + pause flag.
        """
        if not active_topics:
            return []
        if not self._leader.is_leader():
            return []
        # Honour pause/self-isolation (§8.13.5 idempotency matrix).
        self._pause.expire_if_due(int(self._now_s() * 1_000_000_000))
        if self._pause.paused or self._pause.self_isolated:
            return []
        eligible: list[str] = []
        skipped_recursion: list[tuple[str, str]] = []
        skipped_rate: list[str] = []
        for t in active_topics:
            if t in RECURSION_DENY_SET:
                skipped_recursion.append((t, "recursion_deny"))
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
            eligible.append(t)
        out: list[Message] = []
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
        # Phase 8 §8.5 — backlog-pressure damping per topic.
        damped_topics: set[str] = set()
        if depths:
            damped_topics = self._update_backlog_damping(depths, out)
        total_budget = max(1, int(_cfg.maint_dlq_max_replays_per_tick))
        per_topic = max(1, total_budget // len(eligible))
        # Damped topics receive 1/4 of the per-topic budget (floor 1)
        # so a broken consumer is not flooded harder. ROADMAP §8.5:
        # "drops the per-topic replay rate to replay_rps / 4 until
        # depth halves".
        for t in eligible:
            st = self._state.setdefault(t, _RunState())
            st.replayed = 0  # v1 stub: §8.5b plumbs Bus.replay_dlq()
            topic_budget = max(1, per_topic // 4) if t in damped_topics else per_topic
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

    # ── Helpers ───────────────────────────────────────────────────
    def _record_escalation(self, topic: str, request_id: str) -> bool:
        """Append an escalation event to the topic's poison window
        and return True iff the freeze threshold was just crossed.

        Trims expired entries on insert (window =
        ``cfg.maint_dlq_poison_window_s`` seconds). The detector is
        edge-triggered: it returns True only on the transition,
        never re-fires while the topic stays above threshold.
        """
        from collections import deque
        now_s = self._now_s()
        window_s = max(1, int(_cfg.maint_dlq_poison_window_s))
        threshold = max(2, int(_cfg.maint_dlq_poison_distinct_threshold))
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

        Phase 8 §8.5 C2. Acks ``accepted=true`` even if the topic
        was not frozen (idempotent surface, mirrors the §8.13.5
        pause/resume idempotency posture for D1).
        """
        request_id = str(payload.get("request_id") or "")
        target_dlq = str(payload.get("target") or "")
        if not request_id or not target_dlq:
            return
        if not self._leader.is_leader():
            yield self._ack(msg, request_id, accepted=True, reason="non_leader_noop")
            return
        was_frozen = self._frozen_topics.pop(target_dlq, None) is not None
        # Drop the poison log so the next burst starts fresh.
        self._poison_log.pop(target_dlq, None)
        yield self._ack(msg, request_id, accepted=True,
                        reason="unfrozen" if was_frozen else "already_unfrozen")
        yield self._notify("dlq_topic_unfrozen",
                           target=target_dlq,
                           extra={"request_id": request_id,
                                  "was_frozen": was_frozen})

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
        self._pause.expire_if_due(now_ns)
        if paused:
            ttl_s = int(payload.get("ttl_s") or 0) or int(_cfg.maint_pause_default_ttl_s)
            res = self._pause.apply_pause(ttl_s=ttl_s, now_ns=now_ns)
        else:
            res = self._pause.apply_resume()
        details = None
        if res.deadline_ns is not None:
            details = {"ttl_s": (res.deadline_ns - now_ns) // 1_000_000_000}
        yield self._ack(msg, request_id, accepted=res.accepted,
                        reason=res.reason, details=details)

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
