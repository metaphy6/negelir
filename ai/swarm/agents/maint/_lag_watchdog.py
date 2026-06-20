"""Phase 8 §8.11 — maint.event.v1 consumer-lag watchdog.

Observes the median consumer lag on ``maint.event.v1`` and applies
graded shedding in three tiers:

  Tier 0 — lag ≤ ``maint_plane_lag_alert_ms / 1000`` s (healthy): no shedding.
  Tier 1 — lag > threshold: scaler suppresses non-emergency decisions;
            DLQ supervisor halves ``max_replays_per_tick``.
            Emits ``sec.alert.v1{kind=maint_plane_lag_high, severity=warn}``.
  Tier 2 — lag > 15s: scaler scale-down paused; DLQ drain-only;
            schema sentinel 0.1× sample rate.
  Tier 3 — lag > 60s: all agents stop non-critical events;
            emits ``maint.event.v1{kind=maint_plane_throttled, tier=3}``
            then enters observer-only mode.
  Recovery — lag < 1s for ``maint_plane_recovery_window_s`` (default 120s):
             emits ``maint.event.v1{kind=maint_plane_recovered}``.

Only one event is emitted per tier **transition** — never per-tick.

Wiring contract for the bootstrap loop::

    watchdog = MaintLagWatchdog()
    # On every consumer-lag observation:
    watchdog.note_lag(lag_s=measured_lag, now_s=time.time())
    # On every heartbeat:
    messages = watchdog.tick(now_s=time.time())
    # Forward messages to the bus.
    # Check current tier before emitting non-critical events:
    if watchdog.tier < 3:
        ...
"""

from __future__ import annotations

import secrets
import time as _time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from ai.common.config import cfg as _cfg
from ...sdk.shed_state import ShedStateStore
from ...sdk.types import Message
from ..topics import MAINT_EVENT, SEC_ALERT

# ---------------------------------------------------------------------------
# Tier thresholds (seconds) — tier 1 threshold comes from config at runtime.
_TIER2_LAG_S: float = 15.0
_TIER3_LAG_S: float = 60.0
_RECOVERY_FLOOR_S: float = 1.0


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sec_alert(kind: str, severity: str, tier: int, now_s: float) -> Message:
    return Message.new(
        topic=SEC_ALERT,
        payload={
            "kind": kind,
            "severity": severity,
            "source": "maint.lag_watchdog.v1",
            "tier": tier,
            "ts": _utc_iso(),
        },
        producer="maint.lag_watchdog.v1",
    )


def _maint_event(kind: str, tier: int, now_s: float) -> Message:
    return Message.new(
        topic=MAINT_EVENT,
        payload={
            "kind": kind,
            "tier": tier,
            "source": "maint.lag_watchdog.v1",
            "ts": _utc_iso(),
        },
        producer="maint.lag_watchdog.v1",
    )


def _maint_event_inherited(
    tier: int,
    prior_leader_pod_instance_id: Optional[str],
    now_s: float,
) -> Message:
    """§8.15.8 cross-pod coherency: one-per-handover inherited-tier announcement."""
    return Message.new(
        topic=MAINT_EVENT,
        payload={
            "kind": "maint_plane_throttled",
            "tier": tier,
            "action": "inherited_from_lease",
            "prior_leader_pod_instance_id": prior_leader_pod_instance_id or "",
            "source": "maint.lag_watchdog.v1",
            "ts": _utc_iso(),
        },
        producer="maint.lag_watchdog.v1",
    )


@dataclass
class MaintLagWatchdog:
    """Consumer-lag watchdog for ``maint.event.v1`` (Phase 8 §8.11).

    §8.15.8 additions: shed-tier is persisted to a :class:`ShedStateStore`
    on every tier transition so a new leader (or a restarted process)
    can inherit the active tier and hold it for the full
    ``maint_plane_recovery_window_s`` before independently recovering.
    """

    # Ring buffer of (timestamp_s, lag_s) observations.
    _samples: deque = field(default_factory=deque)
    # Active tier (0 = healthy).
    _current_tier: int = 0
    # Tier levels we have already emitted a transition event for.
    # Reset to empty when we recover back to tier 0.
    _emitted_tiers: set[int] = field(default_factory=set)
    # Timestamp when lag first dropped below _RECOVERY_FLOOR_S.
    _recovery_start_s: float | None = None

    # ── §8.15.8 fields ──────────────────────────────────────────
    # Optional shed-state backing store (None disables persistence).
    _shed_store: Optional[ShedStateStore] = field(
        default=None, compare=False, repr=False
    )
    # Per-process identity written into every shed_state record.
    _pod_instance_id: str = field(
        default_factory=lambda: secrets.token_hex(8),
        compare=False,
        repr=False,
    )
    # Monotonic deadline (seconds) before which tier cannot be lowered
    # after inheriting from a prior leader.
    _inherit_lock_until_s: Optional[float] = field(
        default=None, compare=False, repr=False
    )
    # True on the first tick() after inheriting — triggers the
    # "inherited_from_lease" coherency announcement (once only).
    _emit_inherited_pending: bool = field(
        default=False, compare=False, repr=False
    )
    # Instance ID of the prior leader whose state we inherited.
    _prior_leader_pod_id: Optional[str] = field(
        default=None, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        """§8.15.8 — inherit shed tier from a prior leader at boot."""
        if self._shed_store is None:
            return
        record = self._shed_store.read()
        if record is None or record.tier <= 0:
            return
        recovery_window_s = int(_cfg.maint_plane_recovery_window_s)
        self._current_tier = record.tier
        self._inherit_lock_until_s = _time.time() + recovery_window_s
        self._emit_inherited_pending = True
        self._prior_leader_pod_id = record.pod_instance_id

    # ── Public interface ────────────────────────────────────────

    def note_lag(self, lag_s: float, now_s: float | None = None) -> None:
        """Record a consumer-lag observation (seconds)."""
        t = _time.time() if now_s is None else now_s
        self._samples.append((t, lag_s))
        # Prune observations older than 2× the alert window (memory bound).
        window = int(_cfg.maint_plane_lag_alert_window_s)
        while self._samples and t - self._samples[0][0] > window * 2 + 1:
            self._samples.popleft()
        # Start recovery countdown when lag first drops below the floor while
        # the watchdog is in an active shedding tier.
        if lag_s < _RECOVERY_FLOOR_S:
            if self._current_tier > 0 and self._recovery_start_s is None:
                self._recovery_start_s = t
        else:
            # Lag rose above the floor — cancel any in-progress recovery.
            self._recovery_start_s = None

    def tick(self, now_s: float | None = None) -> list[Message]:
        """Evaluate current lag and return any transition events."""
        t = _time.time() if now_s is None else now_s
        if not self._samples:
            return []

        latest_lag: float = self._samples[-1][1]
        out: list[Message] = []

        # --- §8.15.8: Inherited-tier announcement (first tick only) ---
        # Emitted regardless of current lag state so operators see the
        # inheritance + can correlate handover-driven tier continuation.
        if self._emit_inherited_pending and self._current_tier > 0:
            out.append(
                _maint_event_inherited(
                    tier=self._current_tier,
                    prior_leader_pod_instance_id=self._prior_leader_pod_id,
                    now_s=t,
                )
            )
            self._emit_inherited_pending = False

        # --- Recovery path ---
        if latest_lag < _RECOVERY_FLOOR_S:
            # §8.15.8: honour the inheritance lock — new leader must hold
            # the inherited tier for at least maint_plane_recovery_window_s
            # before it can independently decide to lower the tier.
            if self._inherit_lock_until_s is not None:
                if t >= self._inherit_lock_until_s:
                    # Lock expired; fall through to normal recovery logic.
                    self._inherit_lock_until_s = None
                else:
                    # Still in lock window — hold the inherited tier.
                    return out

            recovery_window_s = int(_cfg.maint_plane_recovery_window_s)
            if (
                self._current_tier > 0
                and self._recovery_start_s is not None
                and t - self._recovery_start_s >= recovery_window_s
            ):
                # Full recovery — transition back to tier 0.
                self._current_tier = 0
                self._emitted_tiers = set()
                self._recovery_start_s = None
                # §8.15.8: clear the shed store on full recovery.
                if self._shed_store is not None:
                    self._shed_store.clear()
                out.append(_maint_event(kind="maint_plane_recovered", tier=0, now_s=t))
            return out
        else:
            # Lag is not below the recovery floor; note_lag handles the reset.
            pass

        # --- Only escalate after the sustained alert window has elapsed ---
        threshold_s = int(_cfg.maint_plane_lag_alert_ms) / 1000.0
        window_s = int(_cfg.maint_plane_lag_alert_window_s)
        if not self._lag_sustained_for(threshold_s, window_s, t):
            return out

        # --- Classify the new tier ---
        if latest_lag > _TIER3_LAG_S:
            new_tier = 3
        elif latest_lag > _TIER2_LAG_S:
            new_tier = 2
        elif latest_lag > threshold_s:
            new_tier = 1
        else:
            new_tier = 0

        # --- Emit at most once per tier level entered (no per-tick re-emission) ---
        # §8.11: tier-2/3 shedding events must fire exactly once per tier
        # transition and never again while the tier is sustained — preventing
        # the shedding signal from amplifying the plane it is shedding.
        if new_tier > self._current_tier:
            for tier in range(self._current_tier + 1, new_tier + 1):
                if tier not in self._emitted_tiers:
                    if tier == 1:
                        out.append(
                            _sec_alert(
                                kind="maint_plane_lag_high",
                                severity="warn",
                                tier=1,
                                now_s=t,
                            )
                        )
                    if tier == 2:
                        # Tier-2 shedding announcement — emitted once per
                        # transition; never re-emitted while tier 2 is active.
                        out.append(
                            _maint_event(
                                kind="maint_plane_throttled",
                                tier=2,
                                now_s=t,
                            )
                        )
                    if tier == 3:
                        out.append(
                            _maint_event(
                                kind="maint_plane_throttled",
                                tier=3,
                                now_s=t,
                            )
                        )
                    self._emitted_tiers.add(tier)
            self._current_tier = new_tier
            # §8.15.8: persist new tier so a successor leader can inherit.
            if self._shed_store is not None:
                self._shed_store.write(
                    tier=self._current_tier,
                    reason=f"tier{self._current_tier}_from_lag",
                    pod_instance_id=self._pod_instance_id,
                )

        return out

    @property
    def tier(self) -> int:
        """Current active shedding tier (0 = healthy, 3 = observer mode)."""
        return self._current_tier

    # ── Internals ───────────────────────────────────────────────

    def _lag_sustained_for(
        self, threshold_s: float, window_s: float, now_s: float
    ) -> bool:
        """Return True if ALL samples in the last ``window_s`` exceed ``threshold_s``."""
        if not self._samples:
            return False
        window_start = now_s - window_s
        recent = [lag for ts, lag in self._samples if ts >= window_start]
        if not recent:
            # No samples in window — fall back to the latest sample.
            return self._samples[-1][1] > threshold_s
        return all(lag > threshold_s for lag in recent)
