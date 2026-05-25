"""Phase 8 §8.16.8 — Proof tests for per-model VRAM footprint hints.

Proves three properties:

(a) Known footprints 50 MB and 4000 MB on an effective 7999 MB budget
    (8000 MB total - 1 MB headroom):
    - 100 replicas of the small (50 MB) model are admitted by the
      budget gate (100 x 50 = 5000 <= 7999).
    - 1 replica of the large (4000 MB) model is admitted (1 x 4000 <= 7999).
    - 2 replicas of the large model are refused with
      vram_budget_exceeded (2 x 4000 = 8000 > 7999).

(b) Unregistered agent + tight budget (vram_used_mb > 60 % of budget):
    scale-up is refused with scale_throttled{reason=vram_footprint_unknown}.
    scale_decision is NOT emitted.

(c) Unregistered agent + plentiful budget (vram_used_mb = 0):
    scale-up is admitted using the legacy cfg.predictor_max_vram_mb
    default AND exactly one sec.alert.v1{kind=vram_footprint_unknown,
    severity=info} is emitted (one-shot debounce).
"""
from __future__ import annotations

import pytest

from common.config import cfg
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.runtime import NoopController
from swarm.sdk.leader import SingleProcessLeader

# Stable monotonic baseline - far enough from 0 that window_anchor_ns
# never underflows even with a decision_window_ms=1000 cfg.
_T0_NS: int = 1_000_000_000_000  # 1 000 s

# High-load signal that reliably triggers a scale-up attempt on every tick.
_SCALE_UP_SIG = {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}


def _make_scaler(ns_fn) -> MaintScaler:
    return MaintScaler(
        controller=NoopController(),
        leader=SingleProcessLeader(name="maint.scaler.v1"),
        clock_ns=ns_fn,
    )


def _patch_scale_cfg(mp: pytest.MonkeyPatch) -> None:
    """Disable all throttle gates except the VRAM budget gate under test."""
    mp.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    mp.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
    mp.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
    mp.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
    mp.setattr(cfg, "maint_scaler_max_replicas", 9999, raising=False)
    mp.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    mp.setattr(cfg, "maint_scaler_decision_window_ms", 1000, raising=False)
    mp.setattr(cfg, "maint_scaler_scale_down_grace_windows", 0, raising=False)
    # 1 MB headroom => effective budget = vram_total_mb - 1.
    mp.setattr(cfg, "maint_scaler_vram_headroom_mb", 1.0, raising=False)


class TestVramFootprintHints:
    # ------------------------------------------------------------------ #
    # (a) Known footprints: arithmetic uses per-model hints                #
    # ------------------------------------------------------------------ #

    def test_known_footprints_budget_arithmetic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) Registered footprints 50 MB and 4000 MB on 8000 MB VRAM.

        Effective budget = 8000 - 1 = 7999 MB.
        - 100 x 50 = 5000 <= 7999 => admitted.
        - 1 x 4000 = 4000 <= 7999 => admitted.
        - 2 x 4000 = 8000 > 7999  => refused (vram_budget_exceeded).

        Tests _check_vram_budget directly so the assertion is on the
        precise replica count, independent of the step-decision formula.
        """
        _patch_scale_cfg(monkeypatch)

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        agent.register_model_vram_hint("small_agent", vram_footprint_mb=50.0)
        agent.register_model_vram_hint("large_agent", vram_footprint_mb=4000.0)

        agent.update_device_probe(
            "small_agent",
            vram_total_mb=8000.0,
            vram_used_mb=0.0,
            vram_per_replica_mb=50.0,
            observed_at_ns=_T0_NS,
        )
        agent.update_device_probe(
            "large_agent",
            vram_total_mb=8000.0,
            vram_used_mb=0.0,
            vram_per_replica_mb=4000.0,
            observed_at_ns=_T0_NS,
        )

        # (a-1) 100 replicas of small: 100 x 50 = 5000 <= 7999 => admitted.
        reason_small, unknown_small = agent._check_vram_budget("small_agent", 100)
        assert reason_small is None, (
            "100 small replicas (100x50=5000 MB) must fit in 7999 MB budget; "
            f"got reason={reason_small!r}"
        )
        assert not unknown_small, "small_agent has a registered hint - unknown must be False"

        # (a-2) 1 replica of large: 1 x 4000 = 4000 <= 7999 => admitted.
        reason_large_1, unknown_large_1 = agent._check_vram_budget("large_agent", 1)
        assert reason_large_1 is None, (
            "1 large replica (1x4000=4000 MB) must fit in 7999 MB budget; "
            f"got reason={reason_large_1!r}"
        )
        assert not unknown_large_1, "large_agent has a registered hint - unknown must be False"

        # (a-3) 2 replicas of large: 2 x 4000 = 8000 > 7999 => refused.
        reason_large_2, unknown_large_2 = agent._check_vram_budget("large_agent", 2)
        assert reason_large_2 == "vram_budget_exceeded", (
            "2 large replicas (2x4000=8000 MB) must exceed 7999 MB budget; "
            f"got reason={reason_large_2!r}"
        )
        assert not unknown_large_2, (
            "large_agent has a registered hint - unknown must be False even when refused"
        )

    # ------------------------------------------------------------------ #
    # (b) Unregistered agent + tight budget => vram_footprint_unknown      #
    # ------------------------------------------------------------------ #

    def test_unregistered_tight_budget_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(b) No hint registered; GPU is above the pessimistic threshold.

        vram_used_mb = 4801 > 0.6 x 7999 = 4799.4 => pessimistic refusal.
        tick() must emit scale_throttled{reason=vram_footprint_unknown}
        and must NOT emit scale_decision.
        """
        _patch_scale_cfg(monkeypatch)
        monkeypatch.setattr(
            cfg, "maint_scaler_vram_pessimistic_threshold_pct", 0.6, raising=False
        )

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        # No hint registered for "unknown_agent".
        # budget = 8000 - 1 = 7999; 0.6 x 7999 = 4799.4; used = 4801 > threshold.
        agent.update_device_probe(
            "unknown_agent",
            vram_total_mb=8000.0,
            vram_used_mb=4801.0,
            vram_per_replica_mb=1024.0,
            observed_at_ns=_T0_NS,
        )

        msgs = agent.tick({"unknown_agent": _SCALE_UP_SIG})

        kinds = [m.payload.get("kind") for m in msgs]
        reasons = [m.payload.get("reason") for m in msgs]

        assert "scale_decision" not in kinds, (
            "scale_decision must NOT be emitted when footprint unknown + "
            f"tight budget; got kinds={kinds}"
        )
        assert "vram_footprint_unknown" in reasons, (
            "scale_throttled reason=vram_footprint_unknown must be emitted; "
            f"got reasons={reasons}"
        )

    # ------------------------------------------------------------------ #
    # (c) Unregistered agent + plentiful budget => admitted + info alert   #
    # ------------------------------------------------------------------ #

    def test_unregistered_plentiful_budget_admits_with_info_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c) No hint registered; GPU is below the pessimistic threshold.

        vram_used_mb = 0 < 0.6 x 7999 => scale-up admitted using legacy
        cfg.predictor_max_vram_mb.  A one-shot
        sec.alert.v1{kind=vram_footprint_unknown, severity=info} must be
        emitted on the first admission.  A second tick must NOT re-emit
        the alert (debounce).
        """
        _patch_scale_cfg(monkeypatch)
        monkeypatch.setattr(
            cfg, "maint_scaler_vram_pessimistic_threshold_pct", 0.6, raising=False
        )
        # Use a small legacy footprint so projected 2 replicas fits within budget.
        monkeypatch.setattr(cfg, "predictor_max_vram_mb", 512, raising=False)

        ns: list[int] = [_T0_NS]
        agent = _make_scaler(lambda: ns[0])

        # No hint registered; budget plentiful (0 MB used).
        # Legacy footprint 512 MB; projected = 0 + 512 x 2 = 1024 <= 7999 => admitted.
        agent.update_device_probe(
            "unknown_agent",
            vram_total_mb=8000.0,
            vram_used_mb=0.0,
            vram_per_replica_mb=512.0,
            observed_at_ns=_T0_NS,
        )

        msgs = agent.tick({"unknown_agent": _SCALE_UP_SIG})

        kinds = [m.payload.get("kind") for m in msgs]

        # Scale-up must be admitted.
        assert "scale_decision" in kinds, (
            "unregistered agent on plentiful budget must be admitted; "
            f"got kinds={kinds}"
        )

        # Exactly one sec.alert{kind=vram_footprint_unknown, severity=info}.
        alert_msgs = [
            m
            for m in msgs
            if m.payload.get("kind") == "vram_footprint_unknown"
            and m.payload.get("severity") == "info"
        ]
        assert len(alert_msgs) == 1, (
            "exactly one vram_footprint_unknown info alert must be emitted "
            f"on first admission; got {len(alert_msgs)}"
        )
        assert alert_msgs[0].payload.get("subject") == "unknown_agent", (
            "alert subject must match the unregistered agent name"
        )

        # Debounce: advance clock past current decision window and tick again;
        # the alert must NOT be re-emitted.
        ns[0] += 2_000_000_000  # +2 s => new decision window

        msgs2 = agent.tick({"unknown_agent": _SCALE_UP_SIG})
        re_alerts = [
            m
            for m in msgs2
            if m.payload.get("kind") == "vram_footprint_unknown"
        ]
        assert len(re_alerts) == 0, (
            "vram_footprint_unknown alert must be one-shot (debounced per agent); "
            f"got {len(re_alerts)} alerts on second tick"
        )
