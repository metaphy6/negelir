"""Phase 8 §8.16.8 — CPU-class agent CPU-budget gate.

Proves three properties:

(a) A cpu-class agent registered via ``register_model_vram_hint`` is
    admitted on scale-up when the total cpu-class replica count stays
    within ``cfg.maint_scaler_cpu_budget_pct × detected_cores``.
    VRAM probe is intentionally absent so we prove the cpu path runs
    WITHOUT a device probe.
(b) A cpu-class agent scale-up is refused with
    ``scale_throttled{reason=cpu_budget_exceeded}`` once the projected
    aggregate cpu-class replicas exceed the budget.
(c) A gpu-class agent with a stale probe still hits
    ``vram_telemetry_stale`` (regression: cpu path must not swallow
    gpu agents).
"""
from __future__ import annotations

import os
import pytest

from common.config import cfg
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.runtime import NoopController
from swarm.sdk.leader import SingleProcessLeader

_T0_NS: int = 1_000_000_000_000  # stable monotonic baseline

# High-load signal — always triggers a scale-up attempt.
_SCALE_UP_SIG = {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}

_CPU_TARGET = "tokenizer.v1"
_GPU_TARGET = "inference.v1"


def _make_scaler(ns_fn) -> MaintScaler:
    return MaintScaler(
        controller=NoopController(),
        leader=SingleProcessLeader(name="maint.scaler.v1"),
        clock_ns=ns_fn,
    )


def _patch_scale_cfg(mp: pytest.MonkeyPatch) -> None:
    """Disable all throttle gates except the budget gates under test."""
    mp.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    mp.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
    mp.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
    mp.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
    mp.setattr(cfg, "maint_scaler_max_replicas", 9999, raising=False)
    mp.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    mp.setattr(cfg, "maint_scaler_decision_window_ms", 1000, raising=False)
    mp.setattr(cfg, "maint_scaler_scale_down_grace_windows", 0, raising=False)


class TestCpuClassAgents:
    # ------------------------------------------------------------------ #
    # (a) cpu-class agent admitted within budget — VRAM check bypassed    #
    # ------------------------------------------------------------------ #

    def test_cpu_class_admitted_within_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cpu-class agent is admitted on scale-up when aggregate replica
        count stays within the cpu budget.  No device probe is registered
        so this also proves the cpu path runs without a probe.
        """
        _patch_scale_cfg(monkeypatch)
        # Force a generous cpu budget so the single-replica scale-up is
        # always under budget regardless of os.cpu_count() on CI runners.
        detected = float(os.cpu_count() or 1)
        monkeypatch.setattr(cfg, "maint_scaler_cpu_budget_pct", 1.0, raising=False)

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])
        agent.register_model_vram_hint(
            _CPU_TARGET, vram_footprint_mb=0.0, device_class="cpu"
        )
        # No device probe registered.

        msgs = agent.tick({_CPU_TARGET: _SCALE_UP_SIG})
        kinds = [m.payload.get("kind") for m in msgs]

        assert "scale_decision" in kinds, (
            f"cpu-class agent within budget must be admitted; got kinds={kinds}"
        )
        vram_reasons = [
            m.payload.get("reason")
            for m in msgs
            if m.payload.get("reason") in ("vram_telemetry_stale", "vram_budget_exceeded")
        ]
        assert not vram_reasons, (
            f"VRAM throttle reasons must be absent for cpu-class; got {vram_reasons}"
        )

    # ------------------------------------------------------------------ #
    # (b) cpu-class agent refused when aggregate replicas exceed budget    #
    # ------------------------------------------------------------------ #

    def test_cpu_class_refused_when_budget_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cpu-class scale-up is refused with cpu_budget_exceeded when
        projected aggregate cpu-class replicas × 1 core > budget.

        Setup:
          cpu_budget_pct = 0.0 → budget = 0 replicas (always exceeded
          for any scale-up).  This gives a clean, cpu_count-independent
          refusal on the first scale-up attempt.
        """
        _patch_scale_cfg(monkeypatch)
        # budget = 0.0 * cores = 0; any projected count > 0 is refused.
        monkeypatch.setattr(cfg, "maint_scaler_cpu_budget_pct", 0.0, raising=False)

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])
        agent.register_model_vram_hint(
            _CPU_TARGET, vram_footprint_mb=0.0, device_class="cpu"
        )

        msgs = agent.tick({_CPU_TARGET: _SCALE_UP_SIG})
        kinds = [m.payload.get("kind") for m in msgs]
        reasons = [m.payload.get("reason") for m in msgs]

        assert "scale_decision" not in kinds, (
            "scale_decision must NOT be emitted when cpu budget is exceeded"
        )
        assert "scale_throttled" in kinds, (
            "scale_throttled must be emitted when cpu budget is exceeded"
        )
        assert "cpu_budget_exceeded" in reasons, (
            f"expected reason=cpu_budget_exceeded, got reasons={reasons}"
        )

    # ------------------------------------------------------------------ #
    # (c) gpu-class agent still hits vram_telemetry_stale (regression)    #
    # ------------------------------------------------------------------ #

    def test_gpu_class_agent_still_hits_vram_telemetry_stale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registering a cpu hint for ONE agent must not swallow gpu-class
        agents.  A gpu agent with a stale probe must still emit
        scale_throttled{reason=vram_telemetry_stale}.
        """
        _patch_scale_cfg(monkeypatch)
        window_ms = 1000
        max_age_ns = 5 * window_ms * 1_000_000

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        # CPU-class agent registered — must not affect gpu path.
        agent.register_model_vram_hint(
            _CPU_TARGET, vram_footprint_mb=0.0, device_class="cpu"
        )
        # GPU-class agent with a stale probe.
        agent.update_device_probe(
            _GPU_TARGET,
            vram_total_mb=8000.0,
            vram_used_mb=1024.0,
            vram_per_replica_mb=1024.0,
            observed_at_ns=_T0_NS - max_age_ns - 1,
        )
        # Register gpu footprint hint so it won't fall back to unknown-footprint path.
        agent.register_model_vram_hint(
            _GPU_TARGET, vram_footprint_mb=1024.0, device_class="gpu_inference"
        )

        msgs = agent.tick({_GPU_TARGET: _SCALE_UP_SIG})
        kinds = [m.payload.get("kind") for m in msgs]
        reasons = [m.payload.get("reason") for m in msgs]

        assert "vram_telemetry_stale" in reasons, (
            f"gpu-class agent with stale probe must still get vram_telemetry_stale; "
            f"got reasons={reasons}"
        )
        assert "scale_decision" not in kinds, (
            "scale_decision must NOT be emitted for gpu agent with stale probe"
        )
