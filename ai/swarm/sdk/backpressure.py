"""Phase 8 §8.11 — three-tier backpressure helpers.

The maintenance plane (§8.2 scaler, §8.5 DLQ supervisor, §8.6
schema sentinel, §8.7+§8.8 sec maint) coexists with the data
plane and MUST shed first when the platform is constrained. This
module owns the shared tier vocabulary so every agent applies the
same shedding rules.

Tiers (binding):

* **Tier 1 — green.**     No constraint detected. All maint loops
  run at their default cadence.
* **Tier 2 — yellow.**    One signal degraded (e.g. queue depth
  trending up, head-age above warn). Maint loops slow to
  ``cfg.maint_backpressure_yellow_factor`` × their default cadence;
  notifications keep firing.
* **Tier 3 — red.**       Hard ceiling reached (queue depth above
  the cap, or storage near full). Maint loops halt entirely until
  the next green tick; only critical sec.* paths keep running. The
  agent that flips to red emits ``maint.event.v1{kind=
  maint_silence_alert}`` at most once per
  ``cfg.maint_silence_dedup_s``.

The tier is computed deterministically from a snapshot of inputs
(no hidden state) so two replicas seeing the same signals reach
the same verdict. Hysteresis to prevent flapping is applied at the
caller (replicas track their own previous tier).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ai.common.config import cfg as _cfg


class Tier(str, Enum):
    """Three-tier backpressure ladder."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass(frozen=True)
class Signals:
    """Snapshot of the five signals that drive tier selection."""

    queue_depth: int = 0
    in_flight: int = 0
    head_age_s: float = 0.0
    storage_used_pct: float = 0.0
    error_rate_per_s: float = 0.0


def classify(sig: Signals) -> Tier:
    """Pure deterministic mapping of signals → tier."""
    # Red: hard ceiling on any one input.
    if sig.queue_depth >= int(_cfg.maint_backpressure_red_queue_depth):
        return Tier.RED
    if sig.head_age_s >= float(_cfg.maint_backpressure_red_head_age_s):
        return Tier.RED
    if sig.storage_used_pct >= float(_cfg.maint_backpressure_red_storage_pct):
        return Tier.RED
    if sig.error_rate_per_s >= float(_cfg.maint_backpressure_red_error_rate_per_s):
        return Tier.RED
    # Yellow: any one warn signal.
    if sig.queue_depth >= int(_cfg.maint_backpressure_yellow_queue_depth):
        return Tier.YELLOW
    if sig.head_age_s >= float(_cfg.maint_backpressure_yellow_head_age_s):
        return Tier.YELLOW
    if sig.storage_used_pct >= float(_cfg.maint_backpressure_yellow_storage_pct):
        return Tier.YELLOW
    if sig.error_rate_per_s >= float(_cfg.maint_backpressure_yellow_error_rate_per_s):
        return Tier.YELLOW
    return Tier.GREEN


def cadence_factor(tier: Tier) -> float:
    """Multiplier applied to the agent's default sleep / tick interval.

    GREEN  → 1.0 (no slowdown)
    YELLOW → cfg.maint_backpressure_yellow_factor (e.g. 4.0 = 4× slower)
    RED    → +inf (caller halts the loop)
    """
    if tier == Tier.GREEN:
        return 1.0
    if tier == Tier.YELLOW:
        return max(1.0, float(_cfg.maint_backpressure_yellow_factor))
    return float("inf")


def should_run(tier: Tier) -> bool:
    """Convenience: True iff the maint loop should execute on this tick."""
    return tier != Tier.RED


__all__ = ["Tier", "Signals", "classify", "cadence_factor", "should_run"]
