"""Phase 8 §8.11 — per-agent DLQ growth-rate self-throttle.

Independent of the plane-wide consumer-lag watchdog (also §8.11):
if an agent's own ``<id>.dlq`` depth grows by more than
``cfg.maint_self_dlq_growth_alert`` (default 50) entries **per minute**,
the agent halves its own emit rate via the ``rate_factor`` multiplier
until growth has been non-positive for
``cfg.maint_self_dlq_throttle_recovery_s`` (default 120 s = 2 minutes).

Less drastic than §8.10 self-isolation; catches early-warning DLQ
pressure before the absolute threshold trips ``PauseState.self_isolated``.

Usage::

    throttle = DlqSelfThrottle()
    # On every DLQ depth observation (e.g. each heartbeat tick):
    throttle.note_depth(depth=current_depth, now_s=time.monotonic())
    # Scale the agent's own producer token-bucket rate:
    effective_rate = normal_rate * throttle.rate_factor   # 0.5 or 1.0
"""

from __future__ import annotations

import time as _time
from collections import deque
from dataclasses import dataclass, field

from ai.common.config import cfg as _cfg

# Growth is measured over a rolling 60-second window (1 minute).
_GROWTH_WINDOW_S: float = 60.0


@dataclass
class DlqSelfThrottle:
    """DLQ growth-rate self-throttle for §8.x maint agents (Phase 8 §8.11).

    Call :meth:`note_depth` on each DLQ depth observation.
    Read :attr:`rate_factor` to get the current emit-rate multiplier
    (``1.0`` = full rate, ``0.5`` = halved when DLQ is growing fast).

    The throttle lifts once growth has been non-positive for
    ``cfg.maint_self_dlq_throttle_recovery_s`` (default 120 s) continuously.
    """

    # Ring buffer of (monotonic_s, depth) observations.
    _samples: deque = field(default_factory=deque)
    # True when the agent's emit rate should be halved.
    _throttled: bool = False
    # Timestamp (same clock as _samples) when growth first became ≤ 0
    # after being throttled. Reset to None whenever growth goes positive.
    _non_positive_since: float | None = None

    # ── Public interface ────────────────────────────────────────────

    def note_depth(
        self,
        depth: int,
        now_s: float | None = None,
    ) -> None:
        """Record the agent's own DLQ depth.

        Updates throttle state based on the growth rate computed over the
        last :data:`_GROWTH_WINDOW_S` seconds.  Call on every heartbeat.
        """
        t = _time.monotonic() if now_s is None else now_s
        self._samples.append((t, int(depth)))

        # Keep only samples within 2× the growth window to bound memory.
        prune_before = t - _GROWTH_WINDOW_S * 2.0
        while self._samples and self._samples[0][0] < prune_before:
            self._samples.popleft()

        growth = self._growth_per_min(t)
        threshold = float(_cfg.maint_self_dlq_growth_alert)
        recovery_s = float(_cfg.maint_self_dlq_throttle_recovery_s)

        if growth > threshold:
            # Growth exceeds the per-minute threshold → engage throttle.
            self._throttled = True
            self._non_positive_since = None
        elif growth <= 0.0:
            if self._throttled:
                if self._non_positive_since is None:
                    # First observation of non-positive growth; start the
                    # recovery countdown.
                    self._non_positive_since = t
                elif t - self._non_positive_since >= recovery_s:
                    # Non-positive for the full recovery window → lift.
                    self._throttled = False
                    self._non_positive_since = None
        else:
            # 0 < growth ≤ threshold: not triggering, but not recovering.
            # Reset the recovery countdown if one was in progress.
            self._non_positive_since = None

    @property
    def throttled(self) -> bool:
        """``True`` while the agent's DLQ is growing faster than the limit."""
        return self._throttled

    @property
    def rate_factor(self) -> float:
        """Emit-rate multiplier: ``0.5`` when throttled, ``1.0`` otherwise.

        Apply to the agent's own normal emit rate before passing to the
        producer-side token bucket::

            effective_rate = normal_rate * throttle.rate_factor
        """
        return 0.5 if self._throttled else 1.0

    # ── Internals ───────────────────────────────────────────────────

    def _growth_per_min(self, now_s: float) -> float:
        """Return DLQ depth growth (entries/minute) over the last 60 seconds.

        Returns ``0.0`` when fewer than two samples fall inside the window.
        """
        cutoff = now_s - _GROWTH_WINDOW_S
        window = [(t, d) for t, d in self._samples if t >= cutoff]
        if len(window) < 2:
            return 0.0
        earliest_t, earliest_d = window[0]
        latest_t, latest_d = window[-1]
        elapsed = latest_t - earliest_t
        if elapsed < 0.1:
            return 0.0
        # Scale elapsed from seconds to minutes for a per-minute rate.
        return (latest_d - earliest_d) / (elapsed / 60.0)


__all__ = ["DlqSelfThrottle"]
