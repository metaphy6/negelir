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
from typing import Callable, Iterable, Protocol
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.clock import window_anchor_ns
from ...sdk.leader import Leader, SingleProcessLeader
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck
from ..topics import MAINT_ACK, MAINT_EVENT

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


# ── Runtime controller protocol ─────────────────────────────────────────
class RuntimeController(Protocol):
    """Pluggable shim that turns a (target, replicas) decision into
    real platform action. v1 ships :class:`NoopController`; the
    docker-compose driver lands in §8.16."""

    name: str

    def apply(self, target: str, replicas: int) -> bool:
        """Return True iff the controller accepted the action."""
        ...


class NoopController:
    """Default — records actions, never touches the platform.
    Useful for tests and for a leader that has no driver wired."""

    name = "noop"

    def __init__(self) -> None:
        self.applied: list[tuple[str, int]] = []

    def apply(self, target: str, replicas: int) -> bool:
        self.applied.append((target, replicas))
        return True


# ── Decision dataclass ──────────────────────────────────────────────────
@dataclass
class _TargetState:
    """Per-target rolling window: last decisions + manual pin."""

    last_window_ns: int = 0
    last_replicas: int = 1
    history: deque[int] = field(default_factory=lambda: deque(maxlen=8))
    pin_replicas: int | None = None
    pin_expires_at_ns: int | None = None


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
        self._paused: bool = False
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
        yield self._notify("scale_decision",
                           target=target,
                           extra={"replicas": replicas,
                                  "source": "manual_pin",
                                  "controller": self._controller.name,
                                  "controller_accepted": accepted,
                                  "decision_window_id": self._window_id()})
        st.last_replicas = replicas
        yield self._ack(msg, request_id, accepted=True, reason="pin_set",
                        details={"ttl_s": ttl_s})

    # ── maint_pause / maint_resume ────────────────────────────────
    def _handle_pause(self, msg: Message, payload: dict, *, paused: bool) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target = str(payload.get("target") or "")
        if not request_id:
            return
        # Only react if target is 'all' or our own name.
        if target not in ("all", self.name):
            return
        self._paused = paused
        yield self._ack(msg, request_id, accepted=True,
                        reason="paused" if paused else "resumed")

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
        st.last_replicas = warmup_replicas
        st.history.append(warmup_replicas)
        st.last_window_ns = self._window_anchor()
        yield self._notify(
            "scale_decision",
            target=warmup_target,
            extra={
                "replicas": warmup_replicas,
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
        if self._paused or not self._leader.is_leader():
            return []
        out: list[Message] = []
        # Expire stale pins first.
        out.extend(self._expire_pins())
        max_changes = max(1, int(_cfg.maint_scaler_max_changes_per_window))
        emitted = 0
        window_anchor = self._window_anchor()
        window_id = self._window_id()
        for target, sig in signals.items():
            st = self._evict_and_get(target)
            if st.last_window_ns >= window_anchor:
                continue  # already decided in this window
            if st.pin_replicas is not None:
                # Pinned targets do not get automatic decisions but ARE
                # observable as a throttled event so dashboards can see
                # the suppression instead of a silent no-op.
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
                    out.append(self._notify(
                        "scale_throttled",
                        target=target,
                        extra=extra,
                    ))
                continue
            if emitted >= max_changes:
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
            out.append(self._notify("scale_decision",
                                    target=target,
                                    extra={"replicas": decision,
                                           "source": "auto",
                                           "controller": self._controller.name,
                                           "controller_accepted": accepted,
                                           "decision_window_id": window_id,
                                           "signals": dict(sig)}))
            st.last_replicas = decision
            st.history.append(decision)
            st.last_window_ns = window_anchor
            emitted += 1
        return out

    # ── Decision logic ───────────────────────────────────────────
    def _decide(self, target: str, st: _TargetState,
                sig: dict[str, float]) -> tuple[int | None, str | None]:
        """Return (new replica count, throttle_reason) where exactly
        one is non-None (or both None for a quiet no-op)."""
        depth = float(sig.get("queue_depth", 0))
        in_flight = float(sig.get("in_flight", 0))
        head_age_s = float(sig.get("head_age_s", 0))
        scale_up_depth = float(_cfg.maint_scaler_scale_up_queue_depth)
        scale_down_depth = float(_cfg.maint_scaler_scale_down_queue_depth)
        max_replicas = self._max_replicas_for(target)
        min_replicas = max(0, int(_cfg.maint_scaler_min_replicas))
        current = st.last_replicas
        # Scale up if depth high or head too old.
        if depth >= scale_up_depth or head_age_s >= float(_cfg.maint_scaler_scale_up_head_age_s):
            if current >= max_replicas:
                return (None, "max_replicas_cap")
            new = min(max_replicas, current + 1)
        elif depth <= scale_down_depth and in_flight <= scale_down_depth:
            if current <= min_replicas:
                return (None, "min_replicas_floor")
            new = max(min_replicas, current - 1)
        else:
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
