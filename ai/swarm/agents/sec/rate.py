"""Phase 7 §7.3 — `sec.rate.v1` aggregator + sole denylist writer.

Two responsibilities:

1. **Burst detection** — listens to ``sec.alert.v1`` events emitted
   by the Go gateway (``kind=rate_throttled``) and other defense
   agents, maintains a sliding monotonic-clock window per subject,
   and trips at ``cfg.sec_burst_threshold`` events within
   ``cfg.sec_burst_window_ms`` (§7.3 binding).
2. **Denylist mutation** — sole producer of ``sec.denylist.v1``.
   Any other component that wants to list / unlist a subject
   either (a) fires a ``sec.alert.v1`` rate event so the rate
   agent decides, or (b) goes through the operator path
   (``maint.event.v1{kind=denylist_clear}``).

Why **single-instance** (`SINGLE_INSTANCE_AGENTS`):

The denylist is a Redis hash with a TTL per entry. Two replicas
of ``sec.rate.v1`` would race on the burst counter — both could
trip at threshold and emit duplicate ``denylist_added``. The Lua
script (``infra/redis/lua/sec_denylist_mutate.lua``) is atomic, so
the *Redis* state stays consistent, but the bus would carry two
``sec.denylist.v1`` events per real decision and the dashboards
would double-count. Cheaper to keep one writer.

Subject identity (§7.3 binding):

Subjects are **opaque strings** by design — ``client_id`` for
post-auth, IPv4 ``a.b.c.d`` (``/32``) or IPv6 ``/64`` prefix for
pre-auth. We do not parse the subject; the Go gateway already
emitted it in canonical form. The IPv6 ``/64`` decision is the
defense against an attacker who controls a single ``/48``
allocation: without prefix collapsing they would spray
``2^64`` unique subject buckets and exhaust the LRU.

Bounded state (§7.3 binding):

* ``self._windows`` — per-subject deque[float] (monotonic
  timestamps), bounded by ``cfg.sec_rate_max_subjects`` (LRU
  eviction). Eviction rate watched against
  ``cfg.sec_rate_eviction_rate_alert_per_s`` — sustained eviction
  fires ``sec.alert.v1{kind=subject_map_churn}``.
* ``self._dedup`` — OrderedDict keyed on ``(subject, alert_id)``
  bounded by ``cfg.sec_burst_dedup_window``. Defense against
  at-least-once redelivery — duplicate alerts must not double-count
  the burst window.
* Denylist **inventory** — we do NOT mirror Redis state in process
  beyond an LRU cap counter; cardinality is enforced server-side
  by the Lua script + ``cfg.sec_denylist_max_entries``.

Operator overrides (§7.3):

``maint.event.v1{kind=denylist_clear}`` with
``target=<subject>`` removes the subject from the denylist
(emits ``sec.denylist.v1{action=remove}``) and resets its burst
window. ``target="*"`` is **not** supported in v1 — global wipe
is a console action that goes through the same per-subject loop
to keep the audit trail one-row-per-decision.

Fail-open doctrine (§7.7):

The agent does NOT block traffic itself — that is the gateway's
job. If the bus drops ``sec.alert.v1`` events, the worst case is
the gateway's deterministic per-process token buckets do the
work alone (§7.3 defense-in-depth) and the human-readable
``sec.denylist.v1`` audit stream goes silent. The gateway never
asks the rate agent for permission on the hot path.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from common.config import cfg as _cfg

from ..payloads import DenylistEvent, MaintEvent, SecAlert
from ..topics import MAINT_EVENT, SEC_ALERT, SEC_DENYLIST
from ...sdk.types import Message, Topic
from ._alert import SecAlertDebouncer

_log = logging.getLogger("swarm.agents.sec.rate")


# Kinds of incoming sec.alert.v1 the rate agent counts toward the
# burst window. Anything else is observed (telemetry) but not
# counted — e.g. classifier_degraded is operational, not abusive.
_BURST_TRIGGER_KINDS: frozenset[str] = frozenset({
    "rate_throttled",
    "prompt_injection",
    "homoglyph_attack",
    "language_spoof",
})


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


@dataclass
class _SubjectWindow:
    """Per-subject sliding-window state. ``hits`` is a deque of
    monotonic timestamps; ``denylisted_at`` is set after a trip so
    we don't re-trip while already listed (the Redis TTL does the
    eventual unlist; we just stop adding events to the bus)."""

    hits: deque[float] = field(default_factory=deque)
    denylisted_at: float | None = None
    last_seen: float = 0.0


class SecRateAgent:
    """Subscribes ``sec.alert.v1`` + ``maint.event.v1``; emits
    ``sec.alert.v1`` (burst notifications) + ``sec.denylist.v1``.

    Joins ``SINGLE_INSTANCE_AGENTS`` (see module docstring).
    """

    name = "sec.rate.v1"
    subscribes: tuple[Topic, ...] = (SEC_ALERT, MAINT_EVENT)
    publishes: tuple[Topic, ...] = (SEC_ALERT, SEC_DENYLIST)

    def __init__(
        self,
        *,
        debouncer: SecAlertDebouncer | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_mono: Callable[[], float] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        # NOTE: explicit ``is None`` check rather than ``debouncer or ...``
        # because ``SecAlertDebouncer.__len__`` returns the bucket count
        # — a freshly-injected debouncer is len()==0 and therefore
        # falsy, which would silently drop the test/operator override.
        self._debouncer = debouncer if debouncer is not None else SecAlertDebouncer(
            ttl_s=int(_cfg.sec_alert_debounce_ttl_s),
            critical_bypass=not bool(_cfg.sec_alert_critical_debounce_enabled),
            max_buckets=int(_cfg.sec_alert_debouncer_max_buckets),
        )
        self._clock_iso = clock_iso or _utc_iso
        self._clock_mono = clock_mono or time.monotonic
        self._new_id = new_id or _new_id
        self._lock = threading.Lock()
        # Subject map (LRU), bounded.
        self._windows: "OrderedDict[str, _SubjectWindow]" = OrderedDict()
        self._max_subjects = max(1, int(_cfg.sec_rate_max_subjects))
        # Idempotency dedup on (subject, alert_id).
        self._dedup: "OrderedDict[tuple[str, str], None]" = OrderedDict()
        self._dedup_max = max(1, int(_cfg.sec_burst_dedup_window))
        # Eviction-rate watch.
        self._evictions: deque[float] = deque()
        self._eviction_window_s = max(1, int(_cfg.sec_rate_eviction_rate_window_s))

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == SEC_ALERT:
            return list(self._handle_alert(msg))
        if topic == MAINT_EVENT:
            return list(self._handle_maint(msg))
        _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
        return ()

    # ── sec.alert.v1 → burst window ───────────────────────────────
    def _handle_alert(self, msg: Message) -> Iterable[Message]:
        try:
            alert = SecAlert.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed sec.alert.v1: %s", self.name, exc)
            return
        # Don't react to our OWN alerts (we'd loop on rate_burst).
        if alert.source == self.name:
            return
        # Only count abusive kinds toward the burst window.
        if alert.kind not in _BURST_TRIGGER_KINDS:
            return
        subject = alert.subject or alert.client_id or alert.ip
        if not subject:
            return  # nothing to attribute the hit to

        now = self._clock_mono()
        window_s = max(1, int(_cfg.sec_burst_window_ms)) / 1000.0
        threshold = max(1, int(_cfg.sec_burst_threshold))
        # In-process listing flag must expire alongside the Redis
        # entry it represents; otherwise once a subject trips the
        # burst threshold the agent never re-adds them on a future
        # burst (the in-process `denylisted_at` outlives the Redis
        # TTL and silently weakens defense-in-depth — the gateway
        # would happily allow the resumed user, then fail to
        # denylist them again on a fresh burst). Mirror the Redis
        # TTL so a re-burst after `sec_denylist_ttl_s` re-trips.
        denylist_ttl_s = max(1, int(_cfg.sec_denylist_ttl_s))

        with self._lock:
            # Idempotency.
            dedup_key = (subject, alert.alert_id)
            if dedup_key in self._dedup:
                return
            self._dedup[dedup_key] = None
            while len(self._dedup) > self._dedup_max:
                self._dedup.popitem(last=False)

            window = self._windows.get(subject)
            if window is None:
                window = _SubjectWindow()
                self._windows[subject] = window
            else:
                # Touch for LRU.
                self._windows.move_to_end(subject)
            # Expire the in-process listing flag once the matching
            # Redis TTL would have lapsed. The gateway is the
            # authoritative enforcer (Redis is the source of truth);
            # this just lets the agent re-trip on the next burst.
            if (
                window.denylisted_at is not None
                and now - window.denylisted_at >= denylist_ttl_s
            ):
                window.denylisted_at = None
                window.hits.clear()
            window.last_seen = now
            window.hits.append(now)
            # Evict stale hits outside the window.
            cutoff = now - window_s
            while window.hits and window.hits[0] < cutoff:
                window.hits.popleft()

            # LRU cap.
            evicted_subjects: list[str] = []
            while len(self._windows) > self._max_subjects:
                k, _ = self._windows.popitem(last=False)
                evicted_subjects.append(k)
                self._evictions.append(now)
            # Trim eviction-rate buffer.
            ev_cutoff = now - self._eviction_window_s
            while self._evictions and self._evictions[0] < ev_cutoff:
                self._evictions.popleft()
            eviction_rate = len(self._evictions) / self._eviction_window_s

            tripped = (
                window.denylisted_at is None
                and len(window.hits) >= threshold
            )
            if tripped:
                window.denylisted_at = now
            churn = eviction_rate >= float(_cfg.sec_rate_eviction_rate_alert_per_s)

        # Off-lock side effects.
        if churn:
            yield from self._maybe_alert(
                kind="subject_map_churn",
                severity="warn",
                subject="*",
                reason=(
                    f"eviction rate {eviction_rate:.1f}/s ≥ "
                    f"{float(_cfg.sec_rate_eviction_rate_alert_per_s):.1f}/s"
                ),
            )
        if tripped:
            yield from self._trip(subject=subject, source_alert=alert)

    def _trip(self, *, subject: str, source_alert: SecAlert) -> Iterable[Message]:
        # 1. Loud alert (rate_burst).
        yield from self._maybe_alert(
            kind="rate_burst",
            severity="error",
            subject=subject,
            reason=(
                f"burst threshold {int(_cfg.sec_burst_threshold)} hits in "
                f"{int(_cfg.sec_burst_window_ms)}ms "
                f"(trigger={source_alert.kind})"
            ),
        )
        # 2. Denylist mutation. The Redis Lua script enforces TTL +
        # cardinality cap server-side; we simply announce the
        # decision on the bus. ttl_s carries the operator-visible
        # default; escalation (subnet mode etc.) is the gateway's
        # call on the next request.
        ttl_s = max(1, int(_cfg.sec_denylist_ttl_s))
        event = DenylistEvent(
            event_id=self._new_id(),
            action="add",
            subject=subject,
            reason="rate_burst",
            decided_at=self._clock_iso(),
            ttl_s=ttl_s,
        )
        yield Message.new(SEC_DENYLIST, event.as_dict(), producer=self.name)
        # 3. Surface the add as a debounced informational alert so
        # operators see the listing without subscribing to the
        # mutation stream directly.
        yield from self._maybe_alert(
            kind="denylist_added",
            severity="warn",
            subject=subject,
            reason=f"ttl_s={ttl_s}",
        )

    # ── maint.event.v1{kind=denylist_clear} ───────────────────────
    def _handle_maint(self, msg: Message) -> Iterable[Message]:
        try:
            event = MaintEvent.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed maint.event.v1: %s", self.name, exc)
            return
        if event.kind != "denylist_clear":
            return
        subject = event.target
        if not subject or subject == "*":
            _log.warning(
                "%s: denylist_clear with empty/wildcard target rejected; "
                "operator must enumerate subjects (audit trail policy §7.3)",
                self.name,
            )
            return
        with self._lock:
            window = self._windows.pop(subject, None)
        # Always announce the remove — the Redis script is idempotent
        # and the audit trail benefits from one-event-per-decision.
        remove_event = DenylistEvent(
            event_id=self._new_id(),
            action="remove",
            subject=subject,
            reason="manual_override",
            decided_at=self._clock_iso(),
            ttl_s=0,
        )
        yield Message.new(SEC_DENYLIST, remove_event.as_dict(), producer=self.name)
        yield from self._maybe_alert(
            kind="denylist_removed",
            severity="info",
            subject=subject,
            reason=(
                "manual_override; window_reset"
                if window is not None
                else "manual_override; subject not active"
            ),
        )

    # ── Alert helper ──────────────────────────────────────────────
    def _maybe_alert(
        self,
        *,
        kind: str,
        severity: str,
        subject: str,
        reason: str,
    ) -> Iterable[Message]:
        decision = self._debouncer.decide(
            kind=kind, subject=subject, severity=severity, reason=reason
        )
        if not decision.emit:
            return
        alert = SecAlert(
            alert_id=self._new_id(),
            kind=kind,
            severity=severity,
            source=self.name,
            reason=decision.reason,
            produced_at=self._clock_iso(),
            subject=subject,
        )
        yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)

    # ── Inspection helpers ────────────────────────────────────────
    def subject_count(self) -> int:
        with self._lock:
            return len(self._windows)

    def is_denylisted(self, subject: str) -> bool:
        """In-process view (NOT authoritative — Redis is the source
        of truth). Used by tests + telemetry only."""
        with self._lock:
            window = self._windows.get(subject)
            return bool(window and window.denylisted_at is not None)

    # ── Cardinality-cap escalation (ROADMAP §7.3) ─────────────────
    def note_denylist_capped(
        self,
        *,
        subject: str,
        current_count: int,
    ) -> Iterable[Message]:
        """Public hook for the Go gateway / write-path to invoke when
        the server-side ``sec_denylist_mutate.lua`` script returns
        ``rejected_capped`` because the denylist hash is at
        ``cfg.sec_denylist_max_entries``.

        Emits a single ``sec.alert.v1{kind=denylist_growth_anomaly,
        severity=critical}`` message — this is a runaway-growth
        signal (likely sustained credential-stuffing / DDoS, or a
        widened attacker subnet) and pages on-call immediately.
        Critical alerts bypass debounce by default
        (``cfg.sec_alert_critical_debounce_enabled=False`` per
        §7.4); when an operator opts in, the standard debouncer
        TTL applies — useful when the cap has been reached for a
        sustained outage and the on-call team wants the noise
        damped.

        ``subject`` identifies the candidate-but-rejected entry
        (``client_id`` for post-auth, ``ip`` / CIDR for pre-auth /
        cap-mode subnets); ``current_count`` is the post-script
        cardinality so the alert reason carries the operator-
        actionable metric.

        Idempotent: the debouncer keys on ``(kind, subject)`` so
        repeated reports for the same subject within the TTL
        window collapse to one alert.
        """
        kind = "denylist_growth_anomaly"
        severity = "critical"
        reason = (
            f"denylist cardinality cap hit "
            f"({current_count}>={int(_cfg.sec_denylist_max_entries)}); "
            f"runaway growth or attacker subnet expansion suspected"
        )
        if bool(_cfg.sec_alert_critical_debounce_enabled):
            decision = self._debouncer.decide(
                kind=kind, subject=subject, severity=severity, reason=reason
            )
            if not decision.emit:
                return
            reason = decision.reason
        alert = SecAlert(
            alert_id=self._new_id(),
            kind=kind,
            severity=severity,
            source=self.name,
            reason=reason,
            produced_at=self._clock_iso(),
            subject=subject,
        )
        yield Message.new(SEC_ALERT, alert.as_dict(), producer=self.name)


__all__ = ["SecRateAgent"]
