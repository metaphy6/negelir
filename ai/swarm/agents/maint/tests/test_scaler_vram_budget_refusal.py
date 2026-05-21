"""Phase 8 §8.9 — VRAM-budget refusal proof test.

Proves three scenarios for the scaler's VRAM-budget gate
(``_check_vram_budget`` called inside ``tick()`` before any
scale-up is committed):

  (a) All probes stale → ``scale_throttled{reason=vram_telemetry_stale}``
      and ``scale_decision`` is NOT emitted.
  (b) Projected replica count would breach VRAM budget →
      ``scale_throttled{reason=vram_budget_exceeded}`` and
      ``scale_decision`` is NOT emitted.
  (c) CPU-only path (no probe registered for the target) → VRAM
      checks are entirely bypassed and ``scale_decision`` IS emitted.

ROADMAP §8.9 Safety/hard-caps bullet:
  "VRAM-budget refusal proven via two scenarios:
   (a) all probes stale → reason=vram_telemetry_stale,
   (b) projected exceedance → reason=vram_budget_exceeded.
   CPU-only path bypasses VRAM checks (third scenario)."
"""
from __future__ import annotations

import pytest

from common.config import cfg
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.runtime import NoopController
from swarm.sdk.leader import SingleProcessLeader

# Stable clock baseline: well above zero so window_anchor_ns() never
# underflows.  All test clocks are expressed as offsets from this.
_T0_NS: int = 1_000_000_000_000  # 1 000 s into monotonic epoch

# High-load signal that reliably triggers a scale-up decision.
_SCALE_UP_SIG = {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}

_TARGET = "inference.v1"


def _make_scaler(ns_fn) -> MaintScaler:
    """Build a scaler wired to a controllable clock and a NoopController."""
    return MaintScaler(
        controller=NoopController(),
        leader=SingleProcessLeader(name="maint.scaler.v1"),
        clock_ns=ns_fn,
    )


def _patch_scale_cfg(mp: pytest.MonkeyPatch) -> None:
    """Set cfg knobs that let tick() reach the VRAM guard without hitting
    any earlier throttle gate (window gate, pin gate, time-interval gate,
    global-roster cap, max-changes cap)."""
    mp.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    mp.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
    mp.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
    mp.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
    mp.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    mp.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    mp.setattr(cfg, "maint_scaler_decision_window_ms", 1000, raising=False)


class TestVramBudgetRefusal:
    """Proof suite for the VRAM-budget gate in MaintScaler.tick()."""

    # ------------------------------------------------------------------
    # (a) Stale probes → vram_telemetry_stale
    # ------------------------------------------------------------------

    def test_stale_probe_emits_vram_telemetry_stale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the device probe for the target is older than
        5 × decision_window_ms, tick() must emit
        scale_throttled{reason=vram_telemetry_stale} and must NOT emit
        a scale_decision."""
        _patch_scale_cfg(monkeypatch)
        # decision_window_ms=1000 → max_age_ns = 5 * 1000 * 1_000_000 = 5_000_000_000
        window_ms = 1000
        max_age_ns = 5 * window_ms * 1_000_000

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        # Register a probe whose observed_at_ns is just beyond the stale limit.
        stale_observed_at = _T0_NS - max_age_ns - 1
        agent.update_device_probe(
            _TARGET,
            vram_total_mb=8000.0,
            vram_used_mb=4000.0,
            vram_per_replica_mb=4000.0,
            observed_at_ns=stale_observed_at,
        )

        msgs = agent.tick({_TARGET: _SCALE_UP_SIG})

        kinds = [m.payload.get("kind") for m in msgs]
        reasons = [m.payload.get("reason") for m in msgs]

        assert "scale_decision" not in kinds, (
            "scale_decision must NOT be emitted when probe is stale"
        )
        assert "scale_throttled" in kinds, (
            "scale_throttled must be emitted when probe is stale"
        )
        assert "vram_telemetry_stale" in reasons, (
            f"expected reason=vram_telemetry_stale, got reasons={reasons}"
        )

    # ------------------------------------------------------------------
    # (b) Projected exceedance → vram_budget_exceeded
    # ------------------------------------------------------------------

    def test_projected_vram_exceedance_emits_vram_budget_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When adding one more replica would push projected VRAM use above
        (vram_total_mb - vram_headroom_mb), tick() must emit
        scale_throttled{reason=vram_budget_exceeded} and must NOT emit
        a scale_decision.

        Numbers chosen so headroom=1024 leaves budget=6976 MB:
          current replicas=1, per_replica=4000 MB, used=4000 MB
          baseline = max(0, 4000 - 4000×1) = 0
          projected (2 replicas) = 0 + 4000×2 = 8000 > 6976  → exceeded
        """
        _patch_scale_cfg(monkeypatch)
        monkeypatch.setattr(cfg, "maint_scaler_vram_headroom_mb", 1024, raising=False)

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        # Fresh probe (observed_at = now).
        agent.update_device_probe(
            _TARGET,
            vram_total_mb=8000.0,
            vram_used_mb=4000.0,     # 1 replica in use
            vram_per_replica_mb=4000.0,
            observed_at_ns=_T0_NS,
        )

        msgs = agent.tick({_TARGET: _SCALE_UP_SIG})

        kinds = [m.payload.get("kind") for m in msgs]
        reasons = [m.payload.get("reason") for m in msgs]

        assert "scale_decision" not in kinds, (
            "scale_decision must NOT be emitted when VRAM budget would be exceeded"
        )
        assert "scale_throttled" in kinds, (
            "scale_throttled must be emitted when projected VRAM exceeds budget"
        )
        assert "vram_budget_exceeded" in reasons, (
            f"expected reason=vram_budget_exceeded, got reasons={reasons}"
        )

    # ------------------------------------------------------------------
    # (c) CPU-only path (no probe) → VRAM checks bypassed
    # ------------------------------------------------------------------

    def test_cpu_only_no_probe_bypasses_vram_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no device probe has been registered for the target,
        the VRAM gate is not enforced (opt-in semantics) and
        scale_decision IS emitted for a scale-up signal."""
        _patch_scale_cfg(monkeypatch)

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        # Deliberately do NOT call update_device_probe — CPU-only path.

        msgs = agent.tick({_TARGET: _SCALE_UP_SIG})

        kinds = [m.payload.get("kind") for m in msgs]

        assert "scale_decision" in kinds, (
            "scale_decision must be emitted on CPU-only path (no probe → no VRAM gate)"
        )
        vram_reasons = [
            m.payload.get("reason")
            for m in msgs
            if m.payload.get("reason") in (
                "vram_telemetry_stale", "vram_budget_exceeded"
            )
        ]
        assert not vram_reasons, (
            f"no VRAM throttle reason expected on CPU-only path, got {vram_reasons}"
        )
