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
import time as _time_mod
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
from ..topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
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


# Phase 8 §8.2 — bounded reason allow-list shared by the
# observability counter. The decisions counter normalises every
# reason not in this set to ``"unknown"`` so a malformed code path
# (or a future reason added by accident) cannot blow up label
# cardinality on Prometheus.
_KNOWN_REASONS: frozenset[str] = DECISION_REASONS | THROTTLE_REASONS

# Phase 8 §8.2 — outcome label values for ``maint_scaler_decisions_total``.
# Closed enum: extending requires a minor bump on the ``ai`` component.
_OUTCOME_APPLIED = "applied"
_OUTCOME_THROTTLED = "throttled"
_OUTCOME_ERROR = "error"
_DECISION_OUTCOMES: frozenset[str] = frozenset(
    {_OUTCOME_APPLIED, _OUTCOME_THROTTLED, _OUTCOME_ERROR}
)


def _parse_runtime_histogram_buckets(raw: str) -> tuple[float, ...]:
    """Parse the ``maint_scaler_runtime_histogram_buckets`` CSV.

    The cfg layer already rejects malformed entries at boot; this
    helper is the runtime fallback that drops bad tokens silently
    so a field-overridden value can never crash the agent. Returns
    a sorted, de-duplicated tuple of strictly positive floats.
    """
    out: list[float] = []
    seen: set[float] = set()
    for raw_tok in raw.split(","):
        tok = raw_tok.strip()
        if not tok:
            continue
        try:
            v = float(tok)
        except ValueError:
            continue
        if v <= 0.0 or v in seen:
            continue
        seen.add(v)
        out.append(v)
    out.sort()
    return tuple(out)


# Fallback bucket ladder used when cfg parses to zero usable
# entries. Matches the cfg default so a runtime-only override
# accident still produces a sane histogram.
_FALLBACK_RUNTIME_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)


class _LabelCounter:
    """Tiny labelled counter — Prometheus-style.

    Series live in a dict keyed on the label-value tuple. ``inc``
    silently drops calls whose label arity does not match the
    declared ``label_names`` (cardinality safety).
    """

    __slots__ = ("name", "label_names", "_values")

    def __init__(self, name: str, label_names: tuple[str, ...]) -> None:
        self.name = name
        self.label_names = label_names
        self._values: dict[tuple[str, ...], int] = {}

    def inc(self, labels: tuple[str, ...], n: int = 1) -> None:
        if len(labels) != len(self.label_names):
            return
        self._values[labels] = self._values.get(labels, 0) + int(n)

    def value(self, labels: tuple[str, ...]) -> int:
        return self._values.get(labels, 0)

    def series(self) -> Iterable[tuple[tuple[str, ...], int]]:
        return self._values.items()


class _LabelGauge:
    """Tiny labelled gauge — last-write-wins per label tuple."""

    __slots__ = ("name", "label_names", "_values")

    def __init__(self, name: str, label_names: tuple[str, ...]) -> None:
        self.name = name
        self.label_names = label_names
        self._values: dict[tuple[str, ...], float] = {}

    def set(self, labels: tuple[str, ...], value: float) -> None:
        if len(labels) != len(self.label_names):
            return
        self._values[labels] = float(value)

    def value(self, labels: tuple[str, ...]) -> float | None:
        return self._values.get(labels)

    def series(self) -> Iterable[tuple[tuple[str, ...], float]]:
        return self._values.items()


class _LabelHistogram:
    """Tiny labelled histogram — Prometheus-style cumulative buckets."""

    __slots__ = ("name", "label_names", "buckets", "_counts", "_sums",
                 "_totals")

    def __init__(self, name: str, label_names: tuple[str, ...],
                 buckets: tuple[float, ...]) -> None:
        self.name = name
        self.label_names = label_names
        self.buckets = buckets
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = {}
        self._totals: dict[tuple[str, ...], int] = {}

    def observe(self, labels: tuple[str, ...], value: float) -> None:
        if len(labels) != len(self.label_names):
            return
        v = float(value)
        counts = self._counts.get(labels)
        if counts is None:
            counts = [0] * len(self.buckets)
            self._counts[labels] = counts
        for i, bound in enumerate(self.buckets):
            if v <= bound:
                counts[i] += 1
        self._sums[labels] = self._sums.get(labels, 0.0) + v
        self._totals[labels] = self._totals.get(labels, 0) + 1

    def total(self, labels: tuple[str, ...]) -> int:
        return self._totals.get(labels, 0)

    def sum(self, labels: tuple[str, ...]) -> float:
        return self._sums.get(labels, 0.0)

    def bucket_counts(self, labels: tuple[str, ...]) -> tuple[int, ...]:
        return tuple(self._counts.get(labels, [0] * len(self.buckets)))

    def series(
        self,
    ) -> Iterable[tuple[tuple[str, ...], list[int], float, int]]:
        for labels, counts in self._counts.items():
            yield (labels, counts, self._sums[labels], self._totals[labels])


def _format_label_block(label_names: tuple[str, ...],
                        label_values: tuple[str, ...]) -> str:
    """Render ``{k=v,k=v}`` for use in a flat metric key. Caller
    guarantees arity matches; values are cast to str (the agent
    only ever passes already-bounded labels)."""
    parts = [f"{n}={v}" for n, v in zip(label_names, label_values)]
    return "{" + ",".join(parts) + "}"


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
        # Phase 8 §8.2 — observability surface (binding):
        #   * Counter ``maint_scaler_decisions_total{agent,reason,outcome}``
        #     where ``outcome ∈ {applied, throttled, error}``.
        #   * Gauge ``maint_scaler_desired_replicas{agent}`` — set on
        #     every emitted ``scale_decision`` to the new replica count.
        #   * Gauge ``maint_scaler_vram_budget_mb{host}`` — set inside
        #     :meth:`_check_vram_budget` whenever a fresh probe is
        #     observed.
        #   * Histogram ``maint_scaler_runtime_call_seconds{controller,outcome}``
        #     — wraps every :meth:`RuntimeController.apply` call.
        # Bucket boundaries are sourced from cfg so operators can
        # tune the SLO ladder without a code change. Empty / malformed
        # cfg falls back to the prometheus default ladder.
        buckets = _parse_runtime_histogram_buckets(
            str(_cfg.maint_scaler_runtime_histogram_buckets)
        ) or _FALLBACK_RUNTIME_BUCKETS
        self._m_decisions = _LabelCounter(
            "maint_scaler_decisions_total",
            ("agent", "reason", "outcome"),
        )
        self._m_desired = _LabelGauge(
            "maint_scaler_desired_replicas", ("agent",)
        )
        self._m_vram_budget = _LabelGauge(
            "maint_scaler_vram_budget_mb", ("host",)
        )
        self._m_runtime = _LabelHistogram(
            "maint_scaler_runtime_call_seconds",
            ("controller", "outcome"),
            buckets,
        )
        # Phase 8 §8.16.1 — one-shot tracking for unconfigured-agent
        # alerts. Once a target's name lands here, no further
        # ``maint_scaler_unconfigured_agent`` alert / ``maint_scaler_default_applied``
        # event is emitted for that target during this process'
        # lifetime. Survives leader flips within a process; a pod
        # restart re-emits (intentional — the operator should re-
        # observe the warning if the pod has been re-rolled).
        self._unconfigured_alerted: set[str] = set()
        # Phase 8 §8.16.1 — symmetric one-shot tracking for orphan-cfg
        # alerts (cfg override pointing at an agent name that is not
        # in the live registry). Same lifetime semantics as above:
        # one alert per orphan per process. Populated by
        # :meth:`report_registered_agents`.
        self._orphan_cfg_alerted: set[str] = set()

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
        accepted = self._invoke_runtime(target, replicas)
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
        self._record_decision_metric(
            "manual_pin", _OUTCOME_APPLIED if accepted else _OUTCOME_ERROR
        )
        self._set_desired_replicas(target, replicas)
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
        # Only react if target is 'all' or our own name. Other agents
        # ack 'not_targeted' (still accepted=True) so the ops console
        # receives a complete ack set on single-target pauses.
        if target not in ("all", self.name):
            yield self._ack(msg, request_id, accepted=True, reason="not_targeted")
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
        accepted = self._invoke_runtime(warmup_target, warmup_replicas)
        prev = st.last_replicas
        st.last_replicas = warmup_replicas
        st.history.append(warmup_replicas)
        st.last_window_ns = self._window_anchor()
        st.last_decision_at_ns = self._now_ns()
        self._bump_counter("scale_decision", "retrain_request_warmup")
        self._record_decision_metric(
            "retrain_request_warmup",
            _OUTCOME_APPLIED if accepted else _OUTCOME_ERROR,
        )
        self._set_desired_replicas(warmup_target, warmup_replicas)
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
            # Phase 8 §8.16.1 — first sighting of an unconfigured
            # agent emits a one-shot warn alert + audit event before
            # any decision is computed. No-op when default-policy is
            # disabled OR when this target was already alerted.
            out.extend(self._emit_unconfigured_alerts(target))
            st = self._evict_and_get(target)
            if st.last_window_ns >= window_anchor:
                continue  # already decided in this window
            if st.pin_replicas is not None:
                self._bump_counter("scale_throttled", "manual_pin_active")
                self._record_decision_metric(
                    "manual_pin_active", _OUTCOME_THROTTLED
                )
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
                    self._record_decision_metric(
                        throttle_reason, _OUTCOME_THROTTLED
                    )
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
                self._record_decision_metric(
                    "min_decision_interval", _OUTCOME_THROTTLED
                )
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
                self._record_decision_metric(
                    "global_max_replicas", _OUTCOME_THROTTLED
                )
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
                    self._record_decision_metric(
                        vram_throttle, _OUTCOME_THROTTLED
                    )
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
                self._record_decision_metric(
                    "max_changes_per_window", _OUTCOME_THROTTLED
                )
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
            accepted = self._invoke_runtime(target, decision)
            decision_reason = self._classify_decision_reason(
                st.last_replicas, decision, sig
            )
            self._bump_counter("scale_decision", decision_reason)
            self._record_decision_metric(
                decision_reason,
                _OUTCOME_APPLIED if accepted else _OUTCOME_ERROR,
            )
            self._set_desired_replicas(target, decision)
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
        from cfg trump the global ``maint_scaler_max_replicas`` cap.

        Phase 8 §8.16.1 default-policy fallback: when no override
        is set AND ``cfg.maint_scaler_default_max_replicas > 0``,
        the per-target ceiling is the conservative default (still
        capped by the global ceiling). When the cfg key is 0 the
        legacy fallback (``maint_scaler_max_replicas``) applies —
        operators opt in by raising the cfg value.
        """
        override = self._max_replicas_overrides.get(target)
        if override is not None:
            return max(1, int(override))
        default_policy = int(_cfg.maint_scaler_default_max_replicas)
        if default_policy > 0:
            return min(
                max(2, default_policy),
                max(1, int(_cfg.maint_scaler_max_replicas)),
            )
        return max(1, int(_cfg.maint_scaler_max_replicas))

    def _emit_unconfigured_alerts(self, target: str) -> list[Message]:
        """Phase 8 §8.16.1 — emit one-shot alert + audit on first
        sighting of a registered agent that has no explicit
        max_replicas override. No-op when the cfg key is disabled
        (=0), when the target HAS an override, or when this target
        has already been alerted in this process' lifetime.
        """
        if int(_cfg.maint_scaler_default_max_replicas) <= 0:
            return []
        if target in self._max_replicas_overrides:
            return []
        if target in self._unconfigured_alerted:
            return []
        self._unconfigured_alerted.add(target)
        applied = self._max_replicas_for(target)
        return [
            self._sec_alert(
                kind="maint_scaler_unconfigured_agent",
                severity="warn",
                subject=target,
                reason=(
                    f"agent {target!r} has no entry in "
                    f"maint_scaler_max_replicas_overrides_csv; "
                    f"applied default ceiling={applied}"
                ),
            ),
            self._notify(
                "maint_scaler_default_applied",
                target=target,
                extra={
                    "applied": applied,
                    "default_max_replicas": int(
                        _cfg.maint_scaler_default_max_replicas
                    ),
                },
            ),
        ]

    def report_registered_agents(self, names: Iterable[str]) -> list[Message]:
        """Phase 8 §8.16.1 forward-compat — emit one-shot info alert
        per cfg override key that does NOT match a registered agent
        name (operator forgot to clean cfg after agent removal).

        Symmetric to :meth:`_emit_unconfigured_alerts`: one alert per
        orphan per process lifetime, never a hard failure. The
        orphan entry is otherwise ignored — :meth:`_max_replicas_for`
        only looks up by target name (which is dynamically observed
        from signals), so an unmatched override key is simply dead
        data in the cfg map.

        Intended call site: orchestrator boot, once the agent
        registry has reached steady state (e.g. immediately after
        the §3.2 initial registration sweep). Safe to call
        repeatedly — second invocations are no-ops for orphans
        already alerted in this process.
        """
        registered = {str(n) for n in names if n}
        out: list[Message] = []
        for cfg_key in sorted(self._max_replicas_overrides.keys()):
            if cfg_key in registered:
                continue
            if cfg_key in self._orphan_cfg_alerted:
                continue
            self._orphan_cfg_alerted.add(cfg_key)
            out.append(self._sec_alert(
                kind="maint_scaler_orphan_cfg",
                severity="info",
                subject=cfg_key,
                reason=(
                    f"cfg.maint_scaler_max_replicas_overrides_csv has "
                    f"entry for {cfg_key!r} but no live agent of that "
                    f"name is registered; entry is ignored. Remove the "
                    f"cfg entry after the agent has been retired."
                ),
            ))
        return out

    def _sec_alert(self, *, kind: str, severity: str, subject: str,
                   reason: str) -> Message:
        """Build a ``sec.alert.v1`` message. Kept tiny so the only
        coupling with the sec-plane payload shape lives in one
        place — mirrors the shape used by ``maint.deadmans.v1``.
        """
        payload = {
            "alert_id": secrets.token_hex(8),
            "kind": kind,
            "severity": severity,
            "source": self.name,
            "reason": reason[:1024],
            "subject": subject,
            "request_id": None,
            "client_id": None,
            "ip": None,
            "evidence_ref": None,
            "produced_at": self._clock_iso(),
        }
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=SEC_ALERT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)

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
        """Legacy counter bump: increments the per-(agent, kind, reason)
        ledger consumed by ``metrics_snapshot()`` for the legacy
        Prometheus key shape ``maint_scaler_<kind>_total{...}``.

        The Phase 8.2 observability counter
        ``maint_scaler_decisions_total{agent,reason,outcome}`` is
        bumped via :meth:`_record_decision_metric` at the call site
        (the ``kind`` → ``outcome`` mapping is decided there because
        only the call site knows whether the runtime call accepted).
        """
        key = (self.name, kind, reason)
        self._counters[key] = self._counters.get(key, 0) + 1

    def _record_decision_metric(self, reason: str, outcome: str) -> None:
        """Bump ``maint_scaler_decisions_total{agent,reason,outcome}``.

        Cardinality safety: a ``reason`` that is not in
        :data:`_KNOWN_REASONS` is normalised to ``"unknown"`` before
        the increment so a malformed code path cannot spawn a new
        Prometheus series. An ``outcome`` outside the closed enum is
        dropped silently (defence-in-depth — the call sites only
        ever pass one of the three valid values).
        """
        if outcome not in _DECISION_OUTCOMES:
            return
        norm_reason = reason if reason in _KNOWN_REASONS else "unknown"
        self._m_decisions.inc((self.name, norm_reason, outcome))

    def _set_desired_replicas(self, target: str, replicas: int) -> None:
        """Update ``maint_scaler_desired_replicas{agent}`` to reflect
        the latest emitted decision for ``target``."""
        self._m_desired.set((target,), float(replicas))

    def _invoke_runtime(self, target: str, replicas: int) -> bool:
        """Wrap :meth:`RuntimeController.apply` with timing + the
        ``maint_scaler_runtime_call_seconds{controller,outcome}``
        histogram. Outcome is ``"success"`` when the controller
        returned truthy, ``"error"`` otherwise (or when the
        controller raised — exception is re-raised after the
        histogram is observed so callers can react)."""
        controller_name = getattr(self._controller, "name", "unknown")
        t0 = _time_mod.perf_counter()
        outcome = "error"
        try:
            accepted = bool(self._controller.apply(target, replicas))
            outcome = "success" if accepted else "error"
            return accepted
        finally:
            elapsed = _time_mod.perf_counter() - t0
            self._m_runtime.observe((str(controller_name), outcome), elapsed)

    def metrics_snapshot(self) -> dict[str, float]:
        """Return a flat dict for Prometheus-style export.

        Two key shapes are present:

        * Legacy (kept for back-compat with the Phase 8.2 surface
          coverage test): ``maint_scaler_<kind>_total{agent=..,reason=..}``.
        * Observability (Phase 8.2 binding):
          ``maint_scaler_decisions_total{agent=..,reason=..,outcome=..}``,
          ``maint_scaler_desired_replicas{agent=..}``,
          ``maint_scaler_vram_budget_mb{host=..}``,
          ``maint_scaler_runtime_call_seconds_count{controller=..,outcome=..}``,
          ``maint_scaler_runtime_call_seconds_sum{controller=..,outcome=..}``,
          and one ``..._bucket{..,le=X}`` per histogram bucket.
        """
        out: dict[str, float] = {}
        # Legacy counters.
        for (agent, kind, reason), count in self._counters.items():
            out[
                f"maint_scaler_{kind}_total"
                f"{{agent={agent},reason={reason}}}"
            ] = count
        # Observability counter.
        for labels, count in self._m_decisions.series():
            out[
                self._m_decisions.name
                + _format_label_block(self._m_decisions.label_names, labels)
            ] = count
        # Observability gauges.
        for gauge in (self._m_desired, self._m_vram_budget):
            for labels, value in gauge.series():
                out[
                    gauge.name
                    + _format_label_block(gauge.label_names, labels)
                ] = value
        # Observability histogram (count + sum + per-bucket).
        for labels, counts, total_sum, total_n in self._m_runtime.series():
            block = _format_label_block(
                self._m_runtime.label_names, labels
            )
            out[f"{self._m_runtime.name}_count{block}"] = total_n
            out[f"{self._m_runtime.name}_sum{block}"] = total_sum
            for bound, c in zip(self._m_runtime.buckets, counts):
                # ``le`` formatted with ``g`` keeps integer bucket
                # bounds clean (``1`` not ``1.0``) without losing
                # precision on fractional bounds (``0.005``).
                bucket_block = block[:-1] + f",le={bound:g}}}"
                out[f"{self._m_runtime.name}_bucket{bucket_block}"] = c
        return out

    def update_device_probe(self, target: str, *,
                            vram_total_mb: float,
                            vram_used_mb: float,
                            vram_per_replica_mb: float,
                            observed_at_ns: int | None = None,
                            host: str | None = None) -> None:
        """Push a fresh device probe for ``target``. Called by the
        Phase 6.x device telemetry collector (or by tests directly).

        The probe is treated as stale (and the scaler refuses to
        scale up) once it is older than 5 decision windows.

        Phase 8.2 observability: the per-host VRAM budget gauge
        ``maint_scaler_vram_budget_mb{host}`` is updated immediately
        from this probe (``budget = vram_total_mb - vram_headroom_mb``).
        ``host`` defaults to ``target`` because the v1 probe shape
        carries no separate host field (Phase 11 contract); callers
        that already split host from agent pass ``host=`` explicitly.
        """
        host_label = host if host is not None else target
        self._device_probes[target] = {
            "vram_total_mb": float(vram_total_mb),
            "vram_used_mb": float(vram_used_mb),
            "vram_per_replica_mb": float(vram_per_replica_mb),
            "observed_at_ns": int(
                observed_at_ns if observed_at_ns is not None else self._now_ns()
            ),
            "host": str(host_label),
        }
        headroom = float(_cfg.maint_scaler_vram_headroom_mb)
        budget = max(0.0, float(vram_total_mb) - headroom)
        self._m_vram_budget.set((str(host_label),), budget)

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
        # Phase 8.2 observability — keep the gauge fresh on every
        # decision (in case headroom cfg changed since the last
        # probe). ``host`` defaults to target when probes pre-date
        # the host-aware ``update_device_probe`` field.
        host_label = str(probe.get("host", target))
        self._m_vram_budget.set((host_label,), budget)
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
