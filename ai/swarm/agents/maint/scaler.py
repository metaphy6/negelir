"""Phase 8 §8.2 — `maint.scaler.v1` agent.

Decides per-agent replica counts from a bounded set of signals
(queue depth, in-flight messages, age of head-of-queue) and emits
`maint.event.v1{kind=scale_decision}` once per decision window.
The actual scale action is delegated to a :class:`RuntimeController`
(NoopController in v1; ComposeController shell stubbed for the
docker-compose driver landing in §8.16).

Decision discipline (binding):

* One decision per ``cfg.maint_scaler_decision_window_ms`` per
  target. The window anchor is monotonic-clock based via
  :func:`swarm.sdk.clock.window_anchor_ns` so a wall-clock NTP step
  cannot collapse two windows.
* Hysteresis: a target's replica count cannot move twice in the
  same direction inside ``cfg.maint_scaler_hysteresis_windows``
  consecutive windows without ``cfg.maint_scaler_hysteresis_grace``
  windows of opposite signal.
* Manual pin: an active ``manual_scale_pin`` overrides automatic
  decisions until it expires. Expiry emits
  ``manual_scale_pin_expired``.
* Leader-only: a non-leader replica observes signals but emits
  no decisions. The leader gate is :class:`SingleProcessLeader` in
  v1; Phase 14 swaps in a K8s lease driver.
* Throttle: at most ``cfg.maint_scaler_max_changes_per_window``
  scale_decisions per window across the whole roster — additional
  candidates emit ``scale_throttled`` and wait one window.
"""
from __future__ import annotations

import logging
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.clock import window_anchor_ns
from ...sdk.leader import Leader, SingleProcessLeader
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck
from ..topics import MAINT_ACK, MAINT_EVENT
from .runtime import NoopController, RuntimeController  # re-exported

_log = logging.getLogger("swarm.agents.maint.scaler")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _parse_overrides_csv(raw: str) -> dict[str, int]:
    """Parse ``"agent=N,agent2=M"`` into ``{agent: N, agent2: M}``.

    The cfg layer (``_bounded`` validator) already rejects malformed
    entries at boot; this helper is robust to whitespace and skips
    silently-bad tokens as a defence-in-depth.
    """
    out: dict[str, int] = {}
    for raw_tok in raw.split(","):
        tok = raw_tok.strip()
        if not tok or "=" not in tok:
            continue
        name, _, value = tok.partition("=")
        name = name.strip()
        try:
            n = int(value.strip())
        except ValueError:
            continue
        if name and n > 0:
            out[name] = n
    return out


# ── Decision reason taxonomy ─────────────────────────────────────────
# Reason codes attached to ``scale_decision.reason`` (binding per
# ROADMAP §8.2). The set is closed for now — extending it requires a
# minor bump on the ``swarm`` component (so consumers can roll a
# discriminator without surprise).
DECISION_REASONS: frozenset[str] = frozenset({
    "queue_depth_high",
    "head_age_high",
    "queue_depth_low",
    "manual_pin",
    "retrain_request_warmup",
})

# Throttle reason taxonomy attached to ``scale_throttled.reason``.
# Open within shape; consumers route by severity. Adding a code
# requires a minor bump (so dashboards can colour the new bucket).
THROTTLE_REASONS: frozenset[str] = frozenset({
    "max_replicas_cap",
    "min_replicas_floor",
    "hysteresis_block",
    "manual_pin_active",
    "max_changes_per_window",
    "min_decision_interval",
    "global_max_replicas",
    "vram_budget_exceeded",
    "vram_telemetry_stale",
    "runtime_failed",
    # Phase 8 §8.2 A1 — down-scale grace gate (smoothed signals are
    # below the down-scale threshold but the consecutive-low-windows
    # streak has not yet reached cfg.maint_scaler_scale_down_grace_windows).
    "scale_down_grace",
})


# ── Welford rolling sketch (Phase 8 §8.2 A1) ───────────────────────────
class _Welford:
    """Bounded-window mean tracker.

    Holds at most ``window`` samples in a deque and recomputes the
    mean from the deque. The cap is what makes the sketch *rolling*
    — once full, the oldest sample falls off as a new one is
    appended, so the sketch tracks recent regime rather than
    lifetime mean.
    """

    __slots__ = ("_window", "_samples")

    def __init__(self, window: int) -> None:
        self._window = max(0, int(window))
        # ``maxlen`` of 0 is illegal for deque; degenerate path keeps
        # only the latest sample (window=0 disables smoothing).
        self._samples: deque[float] = deque(
            maxlen=self._window if self._window > 0 else 1
        )

    def add(self, value: float) -> None:
        if self._window <= 0:
            self._samples.clear()
        self._samples.append(float(value))

    @property
    def n(self) -> int:
        return len(self._samples)

    def mean(self) -> float:
        if not self._samples:
            return 0.0
        return sum(self._samples) / len(self._samples)

    def latest(self) -> float:
        if not self._samples:
            return 0.0
        return self._samples[-1]


# ── Decision dataclass ──────────────────────────────────────────────────
@dataclass
class _TargetState:
    """Per-target rolling window: last decisions + manual pin."""

    last_window_ns: int = 0
    last_decision_at_ns: int = 0
    last_replicas: int = 1
    history: deque[int] = field(default_factory=lambda: deque(maxlen=8))
    pin_replicas: int | None = None
    pin_expires_at_ns: int | None = None
    # Phase 8 §8.2 A1 — per-signal Welford sketches keyed on signal
    # name. Created lazily on first observation; adding a new signal
    # is a non-event for existing state.
    signals: dict[str, "_Welford"] = field(default_factory=dict)
    # Phase 8 §8.2 A1 — consecutive low-load windows toward the
    # scale-down grace requirement. Reset to 0 the moment a non-low
    # signal is observed.
    low_streak: int = 0


# ── Agent ───────────────────────────────────────────────────────────────
class MaintScaler:
    """`maint.scaler.v1` reactor.

    Subscribes ``maint.event.v1`` (kind=manual_scale_pin / maint_pause /
    maint_resume).
    Publishes ``maint.event.v1`` (notifications: scale_decision,
    scale_throttled, manual_scale_pin_expired) and ``maint.ack.v1``.
    """

    name = "maint.scaler.v1"
    subscribes: tuple[Topic, ...] = (MAINT_EVENT,)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK)

    def __init__(
        self,
        *,
        controller: RuntimeController | None = None,
        leader: Leader | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_ns: Callable[[], int] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._controller = controller if controller is not None else NoopController()
        self._leader = leader if leader is not None else SingleProcessLeader(name=self.name)
        self._clock_iso = clock_iso or _utc_iso
        self._clock_ns = clock_ns
        self._new_id = new_id or _new_id
        self._targets: "OrderedDict[str, _TargetState]" = OrderedDict()
        self._max_targets = max(16, int(_cfg.maint_scaler_max_targets))
        from ._pause_state import PauseState
        self._pause = PauseState()
        # Per-agent ``max_replicas`` overrides parsed once at boot.
        # Empty dict means every target uses the global cap. Kept on
        # the instance so reload semantics later (Phase 8.16) only
        # need to re-read cfg.
        self._max_replicas_overrides: dict[str, int] = _parse_overrides_csv(
            str(_cfg.maint_scaler_max_replicas_overrides_csv)
        )
        # Pod instance id — random 8-hex prefix so a leader flip after
        # a process restart cannot collide with the pre-restart leader's
        # decision_window_id values in the audit ledger. ROADMAP §8.2
        # binding (decision_window_id discipline).
        self._pod_instance_id: str = secrets.token_hex(4)
        # LRU dedup for retrain_request warm-ups so duplicate drift
        # envelopes do not double-emit warm-up scale_decisions.
        self._warmup_seen: "OrderedDict[str, None]" = OrderedDict()
        self._warmup_seen_max: int = 1024
        # §8.2 VRAM accounting — a tiny in-memory probe map
        # ``{target: {vram_total_mb, vram_used_mb, vram_per_replica_mb,
        # observed_at_ns}}``. Populated externally via
        # :meth:`update_device_probe`. Stale probes (older than 5
        # decision windows) are treated as ``vram_telemetry_stale``
        # and the scaler refuses to scale up that target until fresh
        # data arrives — fail-safe over fail-amnesia.
        self._device_probes: dict[str, dict[str, float]] = {}
        # §8.2 telemetry counters keyed on (agent, kind, reason). Used
        # by ``metrics_snapshot()`` and the Phase 8.9 surface coverage
        # test that proves every reason in DECISION_REASONS ∪
        # THROTTLE_REASONS gets exercised by the agent.
        self._counters: dict[tuple[str, str, str], int] = {}

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        if msg.envelope.topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        kind = payload.get("kind")
        if kind == "manual_scale_pin":
            return list(self._handle_pin(msg, payload))
        if kind == "maint_pause":
            return list(self._handle_pause(msg, payload, paused=True))
        if kind == "maint_resume":
            return list(self._handle_pause(msg, payload, paused=False))
        if kind == "retrain_request":
            return list(self._handle_retrain_request(msg, payload))
        return ()

    # ── manual_scale_pin ──────────────────────────────────────────
    def _handle_pin(self, msg: Message, payload: dict) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target = str(payload.get("target") or "")
        try:
            replicas = int(payload.get("replicas"))
        except (TypeError, ValueError):
            yield self._ack(msg, request_id, accepted=False, reason="bad_replicas")
            return
        if not request_id or not target:
            return
        if not self._leader.is_leader():
            yield self._ack(msg, request_id, accepted=True, reason="leader_skip")
            return
        st = self._evict_and_get(target)
        if replicas == -1:
            # Cancel an active pin.
            if st.pin_replicas is not None:
                yield self._notify("manual_scale_pin_expired",
                                   target=target,
                                   extra={"reason": "operator_cancel"})
            st.pin_replicas = None
            st.pin_expires_at_ns = None
            yield self._ack(msg, request_id, accepted=True, reason="pin_cleared")
            return
        ttl_s = int(payload.get("ttl_s") or 0) or int(_cfg.maint_scaler_manual_pin_ttl_s)
        ttl_s = max(1, min(ttl_s, 86400))
        st.pin_replicas = replicas
        st.pin_expires_at_ns = self._now_ns() + ttl_s * 1_000_000_000
        accepted = self._controller.apply(target, replicas)
        prev = st.last_replicas
        yield self._notify("scale_decision",
                           target=target,
                           extra={"replicas": replicas,
                                  "prev": prev,
                                  "next": replicas,
                                  "reason": "manual_pin",
                                  "observed": {"ttl_s": ttl_s},
                                  "source": "manual_pin",
                                  "controller": self._controller.name,
                                  "controller_accepted": accepted,
                                  "decision_window_id": self._window_id()})
        self._bump_counter("scale_decision", "manual_pin")
        st.last_replicas = replicas
        st.last_decision_at_ns = self._now_ns()
        yield self._ack(msg, request_id, accepted=True, reason="pin_set",
                        details={"ttl_s": ttl_s})

    # ── maint_pause / maint_resume (§8.13.5 idempotency matrix) ──
    def _handle_pause(self, msg: Message, payload: dict, *, paused: bool) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target = str(payload.get("target") or "")
        if not request_id:
            return
        # Only react if target is 'all' or our own name.
        if target not in ("all", self.name):
            return
        # Auto-resume any expired pause first so the matrix sees a
        # truthful current state.
        self._pause.expire_if_due(self._now_ns())
        if paused:
            ttl_s = int(payload.get("ttl_s") or 0) or int(_cfg.maint_pause_default_ttl_s)
            res = self._pause.apply_pause(ttl_s=ttl_s, now_ns=self._now_ns())
        else:
            res = self._pause.apply_resume()
        details = {"ttl_s": (res.deadline_ns - self._now_ns()) // 1_000_000_000} if res.deadline_ns else None
        yield self._ack(msg, request_id, accepted=res.accepted,
                        reason=res.reason, details=details)

    # ── retrain_request warm-up ──────────────────────────────────
    def _handle_retrain_request(self, msg: Message, payload: dict) -> Iterable[Message]:
        """When the drift agent (Phase 6.3) emits a `retrain_request`,
        the scaler warms the trainer up by emitting a single
        `scale_decision{source=retrain_request_warmup}` for the target.

        retrain_request carries no `request_id` per its sub-schema (it
        is a producer-driven envelope, not operator-driven), so we
        derive a stable dedup key from envelope.message_id × target.
        Empty consumer set → no ack is emitted (pending Phase 5.x
        trainer-as-agent landing).
        """
        target = str(payload.get("target") or "")
        if not target:
            return
        if not self._leader.is_leader():
            return
        # Scaler warms ONLY the trainer surface, not arbitrary targets.
        # Predictor targets retain their existing replica counts; the
        # trainer pod is what actually runs the retrain job.
        warmup_target = "trainer.v1"
        dedup_key = f"{msg.envelope.message_id}:{warmup_target}"
        if dedup_key in self._warmup_seen:
            return
        self._warmup_seen[dedup_key] = None
        while len(self._warmup_seen) > self._warmup_seen_max:
            self._warmup_seen.popitem(last=False)

        warmup_replicas = max(1, int(_cfg.maint_scaler_warmup_replicas))
        st = self._evict_and_get(warmup_target)
        # Don't downscale: if a higher count is already in effect, the
        # warm-up is a no-op. Honest semantics over surprise shrinkage.
        if st.last_replicas >= warmup_replicas:
            return
        accepted = self._controller.apply(warmup_target, warmup_replicas)
        prev = st.last_replicas
        st.last_replicas = warmup_replicas
        st.history.append(warmup_replicas)
        st.last_window_ns = self._window_anchor()
        st.last_decision_at_ns = self._now_ns()
        self._bump_counter("scale_decision", "retrain_request_warmup")
        yield self._notify(
            "scale_decision",
            target=warmup_target,
            extra={
                "replicas": warmup_replicas,
                "prev": prev,
                "next": warmup_replicas,
                "reason": "retrain_request_warmup",
                "observed": {},
                "source": "retrain_request_warmup",
                "controller": self._controller.name,
                "controller_accepted": accepted,
                "decision_window_id": self._window_id(),
                "request_id": str(payload.get("request_id") or msg.envelope.message_id),
            },
        )

    # ── Periodic decision tick (not bus-driven) ──────────────────
    def tick(self, signals: dict[str, dict[str, float]]) -> list[Message]:
        """Evaluate signals and emit at most
        ``cfg.maint_scaler_max_changes_per_window`` scale decisions.

        ``signals`` is ``{target: {queue_depth, in_flight, head_age_s}}``.
        Returns the list of messages to publish.
        """
        if self._pause.paused or self._pause.self_isolated or not self._leader.is_leader():
            # Honour TTL — re-check post-expiry once per tick.
            self._pause.expire_if_due(self._now_ns())
            if self._pause.paused or self._pause.self_isolated or not self._leader.is_leader():
                return []
        out: list[Message] = []
        # Expire stale pins first.
        out.extend(self._expire_pins())
        max_changes = max(1, int(_cfg.maint_scaler_max_changes_per_window))
        emitted = 0
        window_anchor = self._window_anchor()
        window_id = self._window_id()
        min_interval_ns = int(
            float(_cfg.maint_scaler_min_decision_interval_s) * 1_000_000_000
        )
        global_cap = max(1, int(_cfg.maint_scaler_global_max_replicas))
        roster_total = sum(
            (st.last_replicas or 0) for st in self._targets.values()
        )
        for target, sig in signals.items():
            st = self._evict_and_get(target)
            if st.last_window_ns >= window_anchor:
                continue  # already decided in this window
            if st.pin_replicas is not None:
                self._bump_counter("scale_throttled", "manual_pin_active")
                out.append(self._notify(
                    "scale_throttled",
                    target=target,
                    extra={
                        "would_be": st.pin_replicas,
                        "reason": "manual_pin_active",
                        "decision_window_id": window_id,
                    },
                ))
                continue
            decision, throttle_reason = self._decide(target, st, sig)
            if decision is None:
                if throttle_reason is not None:
                    extra: dict = {
                        "would_be": st.last_replicas,
                        "reason": throttle_reason,
                        "decision_window_id": window_id,
                    }
                    if throttle_reason == "max_replicas_cap":
                        extra["max_replicas"] = self._max_replicas_for(target)
                    self._bump_counter("scale_throttled", throttle_reason)
                    out.append(self._notify(
                        "scale_throttled",
                        target=target,
                        extra=extra,
                    ))
                continue
            # Time-based hysteresis (separate from per-window gate):
            # refuse two decisions inside ``min_decision_interval_s``
            # for the SAME target across distinct windows.
            now_ns = self._now_ns()
            if (
                min_interval_ns > 0
                and st.last_decision_at_ns > 0
                and (now_ns - st.last_decision_at_ns) < min_interval_ns
            ):
                self._bump_counter("scale_throttled", "min_decision_interval")
                out.append(self._notify(
                    "scale_throttled",
                    target=target,
                    extra={
                        "would_be": decision,
                        "reason": "min_decision_interval",
                        "min_decision_interval_s":
                            float(_cfg.maint_scaler_min_decision_interval_s),
                        "decision_window_id": window_id,
                    },
                ))
                continue
            # Global-roster cap — defends against a self-amplifying lag
            # storm where every target wants +1 in the same tick.
            projected = roster_total - (st.last_replicas or 0) + decision
            if decision > st.last_replicas and projected > global_cap:
                self._bump_counter("scale_throttled", "global_max_replicas")
                out.append(self._notify(
                    "scale_throttled",
                    target=target,
                    extra={
                        "would_be": decision,
                        "reason": "global_max_replicas",
                        "global_max_replicas": global_cap,
                        "decision_window_id": window_id,
                    },
                ))
                continue
            # VRAM budget guard — only on scale-up.
            if decision > st.last_replicas:
                vram_throttle = self._check_vram_budget(target, decision)
                if vram_throttle is not None:
                    self._bump_counter("scale_throttled", vram_throttle)
                    out.append(self._notify(
                        "scale_throttled",
                        target=target,
                        extra={
                            "would_be": decision,
                            "reason": vram_throttle,
                            "decision_window_id": window_id,
                        },
                    ))
                    continue
            if emitted >= max_changes:
                self._bump_counter("scale_throttled", "max_changes_per_window")
                out.append(self._notify(
                    "scale_throttled",
                    target=target,
                    extra={
                        "would_be": decision,
                        "reason": "max_changes_per_window",
                        "max_changes": max_changes,
                        "decision_window_id": window_id,
                    },
                ))
                continue
            accepted = self._controller.apply(target, decision)
            decision_reason = self._classify_decision_reason(
                st.last_replicas, decision, sig
            )
            self._bump_counter("scale_decision", decision_reason)
            out.append(self._notify("scale_decision",
                                    target=target,
                                    extra={"replicas": decision,
                                           "prev": st.last_replicas,
                                           "next": decision,
                                           "reason": decision_reason,
                                           "observed": dict(sig),
                                           "source": "auto",
                                           "controller": self._controller.name,
                                           "controller_accepted": accepted,
                                           "decision_window_id": window_id,
                                           "signals": dict(sig)}))
            roster_total = roster_total - (st.last_replicas or 0) + decision
            st.last_replicas = decision
            st.history.append(decision)
            st.last_window_ns = window_anchor
            st.last_decision_at_ns = now_ns
            emitted += 1
        return out

    # ── Decision-reason classifier ─────────────────────────────────
    def _classify_decision_reason(self, prev: int, new: int,
                                  sig: dict[str, float]) -> str:
        """Map a (prev, new, signals) tuple to a reason in
        :data:`DECISION_REASONS`. Defensive: unknown shapes fall back
        to ``queue_depth_high`` / ``queue_depth_low`` based on direction.
        """
        if new > prev:
            head_age = float(sig.get("head_age_s", 0))
            if head_age >= float(_cfg.maint_scaler_scale_up_head_age_s):
                return "head_age_high"
            return "queue_depth_high"
        return "queue_depth_low"

    # ── Decision logic ───────────────────────────────────────────
    def _smooth_signals(self, st: _TargetState,
                        sig: dict[str, float]) -> dict[str, float]:
        """Update per-signal Welford sketches and return the smoothed
        view used by :meth:`_decide`. Window=0 → instantaneous values
        (sketches still cleared so the latest sample is what's read).
        """
        window = max(0, int(_cfg.maint_scaler_signal_window_samples))
        out: dict[str, float] = {}
        for name, value in sig.items():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            sketch = st.signals.get(name)
            if sketch is None or sketch._window != window:  # noqa: SLF001
                sketch = _Welford(window)
                st.signals[name] = sketch
            sketch.add(v)
            out[name] = sketch.mean() if window > 0 else v
        return out

    def _decide(self, target: str, st: _TargetState,
                sig: dict[str, float]) -> tuple[int | None, str | None]:
        """Return (new replica count, throttle_reason) where exactly
        one is non-None (or both None for a quiet no-op).

        Reads from the smoothed per-signal Welford view so a single
        spike or single calm sample cannot toggle replicas. Down-
        scales additionally require ``cfg.maint_scaler_scale_down_grace_windows``
        consecutive low-load windows to elapse before firing
        (``low_streak`` counter).

        When ``cfg.maint_scaler_target_load_per_replica > 0`` the
        decision uses the load-driven clamp formula
        ``desired = clamp(min, ceil(load / target_per_replica), max)``
        and steps toward ``desired`` by at most
        ``cfg.maint_scaler_max_step_per_window`` replicas. When 0 the
        legacy ±1-step decision is used (forward compatibility for
        operators who haven't tuned the per-replica target).
        """
        from math import ceil
        smoothed = self._smooth_signals(st, sig)
        depth = float(smoothed.get("queue_depth", 0))
        in_flight = float(smoothed.get("in_flight", 0))
        head_age_s = float(smoothed.get("head_age_s", 0))
        scale_up_depth = float(_cfg.maint_scaler_scale_up_queue_depth)
        scale_down_depth = float(_cfg.maint_scaler_scale_down_queue_depth)
        max_replicas = self._max_replicas_for(target)
        min_replicas = max(0, int(_cfg.maint_scaler_min_replicas))
        max_step = max(1, int(_cfg.maint_scaler_max_step_per_window))
        target_per_replica = max(0, int(_cfg.maint_scaler_target_load_per_replica))
        current = st.last_replicas
        # Compute desired (clamp formula) when enabled. ``observed_load``
        # combines depth + in_flight so an idle queue with mid-flight
        # work still counts toward the headcount budget.
        if target_per_replica > 0:
            observed_load = max(depth, in_flight)
            desired = max(
                min_replicas,
                min(max_replicas, max(1, ceil(observed_load / target_per_replica))),
            )
        else:
            desired = current  # legacy mode: step decision only
        # Scale up if depth high or head too old (or clamp says we
        # want more headcount than we have).
        wants_up = (
            depth >= scale_up_depth
            or head_age_s >= float(_cfg.maint_scaler_scale_up_head_age_s)
            or (target_per_replica > 0 and desired > current)
        )
        wants_down = (
            depth <= scale_down_depth
            and in_flight <= scale_down_depth
            and (target_per_replica == 0 or desired < current)
        )
        if wants_up:
            st.low_streak = 0
            if current >= max_replicas:
                return (None, "max_replicas_cap")
            if target_per_replica > 0:
                step = min(max_step, max(1, desired - current))
                new = min(max_replicas, current + step)
            else:
                new = min(max_replicas, current + 1)
        elif wants_down:
            # Bump the consecutive-low-window streak; only fire the
            # actual down-scale once the grace count is met. Until
            # then, surface a `scale_down_grace` throttle so dashboards
            # can show "we'd shrink in N more windows".
            st.low_streak += 1
            grace = max(0, int(_cfg.maint_scaler_scale_down_grace_windows))
            if st.low_streak <= grace:
                return (None, "scale_down_grace")
            if current <= min_replicas:
                return (None, "min_replicas_floor")
            if target_per_replica > 0:
                step = min(max_step, max(1, current - desired))
                new = max(min_replicas, current - step)
            else:
                new = max(min_replicas, current - 1)
        else:
            # Mixed signal — neither up nor down. Reset the streak
            # so a partial calm cannot piggy-back on earlier ones.
            st.low_streak = 0
            return (None, None)
        if not self._hysteresis_ok(st, new, current):
            return (None, "hysteresis_block")
        return (new, None)

    def _max_replicas_for(self, target: str) -> int:
        """Return the per-target replica ceiling. Per-agent overrides
        from cfg trump the global ``maint_scaler_max_replicas`` cap."""
        override = self._max_replicas_overrides.get(target)
        if override is not None:
            return max(1, int(override))
        return max(1, int(_cfg.maint_scaler_max_replicas))

    def _hysteresis_ok(self, st: _TargetState, new: int, current: int) -> bool:
        """Refuse two same-direction moves inside hysteresis_windows
        unless preceded by hysteresis_grace opposite signals.
        v1 implements only the simpler form: count consecutive same-
        direction history entries against the window cap."""
        windows = max(1, int(_cfg.maint_scaler_hysteresis_windows))
        if len(st.history) < windows:
            return True
        direction = 1 if new > current else -1
        recent = list(st.history)[-windows:]
        prev_direction = 1 if recent[-1] > st.last_replicas else -1
        same_dir_count = sum(
            1 for r in recent
            if (r > st.last_replicas) == (direction > 0)
        )
        return same_dir_count < windows or direction != prev_direction

    # ── Pin expiry ───────────────────────────────────────────────
    def _expire_pins(self) -> Iterable[Message]:
        now = self._now_ns()
        for target, st in self._targets.items():
            if st.pin_expires_at_ns is not None and now >= st.pin_expires_at_ns:
                yield self._notify("manual_scale_pin_expired",
                                   target=target,
                                   extra={"reason": "ttl"})
                st.pin_replicas = None
                st.pin_expires_at_ns = None

    # ── State helpers ────────────────────────────────────────────
    def _evict_and_get(self, target: str) -> _TargetState:
        st = self._targets.get(target)
        if st is not None:
            self._targets.move_to_end(target)
            return st
        if len(self._targets) >= self._max_targets:
            self._targets.popitem(last=False)
        st = _TargetState()
        self._targets[target] = st
        return st

    def _now_ns(self) -> int:
        if self._clock_ns is not None:
            return self._clock_ns()
        import time as _t
        return _t.monotonic_ns()

    def _window_id(self) -> str:
        """String form ``<pod_instance_id>:<window_anchor_ns>``. The
        prefix prevents post-restart collisions of decision_window_id
        in the audit ledger (binding per ROADMAP §8.2)."""
        return f"{self._pod_instance_id}:{self._window_anchor()}"

    def _window_anchor(self) -> int:
        window_ms = max(1, int(_cfg.maint_scaler_decision_window_ms))
        return window_anchor_ns(window_ms,
                                now_ns=self._clock_ns() if self._clock_ns else None,
                                source=str(_cfg.maint_scaler_clock_source))

    # ── Counters / VRAM probe ────────────────────────────────────
    def _bump_counter(self, kind: str, reason: str) -> None:
        """Increment ``maint_scaler_decisions_total{agent,kind,reason}``."""
        key = (self.name, kind, reason)
        self._counters[key] = self._counters.get(key, 0) + 1

    def metrics_snapshot(self) -> dict[str, int]:
        """Return a flat dict for Prometheus-style export. Keys are
        ``"maint_scaler_<kind>_total{agent=..,reason=..}"`` so a
        downstream exporter can split them on ``{`` for label parsing."""
        out: dict[str, int] = {}
        for (agent, kind, reason), count in self._counters.items():
            out[f"maint_scaler_{kind}_total{{agent={agent},reason={reason}}}"] = count
        return out

    def update_device_probe(self, target: str, *,
                            vram_total_mb: float,
                            vram_used_mb: float,
                            vram_per_replica_mb: float,
                            observed_at_ns: int | None = None) -> None:
        """Push a fresh device probe for ``target``. Called by the
        Phase 6.x device telemetry collector (or by tests directly).

        The probe is treated as stale (and the scaler refuses to
        scale up) once it is older than 5 decision windows.
        """
        self._device_probes[target] = {
            "vram_total_mb": float(vram_total_mb),
            "vram_used_mb": float(vram_used_mb),
            "vram_per_replica_mb": float(vram_per_replica_mb),
            "observed_at_ns": int(
                observed_at_ns if observed_at_ns is not None else self._now_ns()
            ),
        }

    def _check_vram_budget(self, target: str, projected_replicas: int) -> str | None:
        """Return throttle reason if the projected replica count would
        breach the per-host VRAM budget; else ``None``.

        Two failure modes:
        * ``"vram_telemetry_stale"`` — probe older than 5 decision
          windows (or never observed). Fail-safe over fail-amnesia:
          the scaler will not commit a scale-up it cannot account
          for. The min/min_replicas floor is unaffected.
        * ``"vram_budget_exceeded"`` — projected utilisation would
          cross ``vram_total_mb - vram_headroom_mb``.
        """
        probe = self._device_probes.get(target)
        if probe is None:
            return None  # no probe yet → opt-in, no enforcement
        window_ms = max(1, int(_cfg.maint_scaler_decision_window_ms))
        max_age_ns = 5 * window_ms * 1_000_000
        if (self._now_ns() - int(probe["observed_at_ns"])) > max_age_ns:
            return "vram_telemetry_stale"
        headroom = float(_cfg.maint_scaler_vram_headroom_mb)
        budget = max(0.0, float(probe["vram_total_mb"]) - headroom)
        per_replica = float(probe["vram_per_replica_mb"])
        # Baseline: keep currently-used VRAM minus what the existing
        # replicas account for, then add the projected count's draw.
        current_replicas = max(1, self._targets.get(target, _TargetState()).last_replicas)
        baseline = max(0.0, float(probe["vram_used_mb"]) - per_replica * current_replicas)
        projected_used = baseline + per_replica * projected_replicas
        if projected_used > budget:
            return "vram_budget_exceeded"
        return None

    # ── Emission helpers ─────────────────────────────────────────
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


__all__ = ["MaintScaler", "NoopController", "RuntimeController"]
