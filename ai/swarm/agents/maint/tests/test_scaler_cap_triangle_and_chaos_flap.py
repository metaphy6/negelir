"""Phase 8 §8.9 — scaler replica-cap triangle test + chaos-flap hysteresis.

Triangle test (3 corners):
  A) Per-agent global cap (``maint_scaler_max_replicas``) enforced when no
     per-agent CSV override is configured.
  B) Per-agent CSV override (``maint_scaler_max_replicas_overrides_csv``)
     takes precedence over the global default and is enforced independently.
  C) Roster-wide global cap (``maint_scaler_global_max_replicas``) is enforced
     even when the per-agent cap has not been reached.

All three corners reference their cfg keys by name so the test fails
immediately if a key rename silently breaks enforcement.

Chaos-flap hysteresis test (``test_chaos_flap_replicas``):
  Simulates ``make chaos-flap-replicas AGENT=consensus.v1`` — alternating
  high/low signals at sub-``min_decision_interval_s`` cadence.  Proves the
  scaler does NOT issue back-to-back ``scale_decision`` events within the
  interval; all subsequent attempts emit ``scale_throttled`` with
  ``reason=min_decision_interval``.

ROADMAP §8.9 Safety/hard-caps bullet:
  "Scaler refuses to exceed cfg.maint_scaler_max_replicas[<agent>] (per-agent)
  and cfg.maint_scaler_global_max_replicas (global). Triangle test covers the
  cfg keys; chaos test make chaos-flap-replicas AGENT=consensus.v1 proves
  hysteresis (no back-to-back decisions inside min_decision_interval_s)."
"""
from __future__ import annotations

import pytest

from common.config import cfg
from swarm.agents.maint.scaler import MaintScaler


# ── helpers ─────────────────────────────────────────────────────────────────

def _high_signal() -> dict[str, float]:
    return {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}


def _low_signal() -> dict[str, float]:
    return {"queue_depth": 0.0, "in_flight": 0.0, "head_age_s": 0.0}


def _fresh_window(agent: MaintScaler, target: str) -> None:
    """Reset per-target window anchor so the next tick is eligible."""
    if target in agent._targets:
        agent._targets[target].last_window_ns = 0


def _kinds(msgs) -> list[str]:
    return [m.payload.get("kind") for m in msgs]


def _throttle_reasons(msgs) -> list[str]:
    return [
        m.payload.get("reason")
        for m in msgs
        if m.payload.get("kind") == "scale_throttled"
    ]


# ── Triangle corner A: per-agent global cap (maint_scaler_max_replicas) ──────

class TestTriangleCornerA:
    """Corner A — the global default ``maint_scaler_max_replicas`` is respected
    when no per-agent CSV override is present.  The scaler must refuse to scale
    above the cap and emit ``scale_throttled{reason=max_replicas_cap}``."""

    def test_refuses_scale_above_global_default_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 2, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()
        target = "predictor.elo"

        # Tick until the cap is reached; track how many decisions land.
        decisions: list = []
        for _ in range(5):
            _fresh_window(agent, target)
            out = agent.tick({target: _high_signal()})
            decisions.extend(m for m in out if m.payload.get("kind") == "scale_decision")

        # At most ``max_replicas=2`` worth of scale_decisions should have fired.
        final_replicas = agent._targets[target].last_replicas
        assert final_replicas <= 2, (
            f"last_replicas={final_replicas} exceeds maint_scaler_max_replicas=2"
        )

        # Explicitly test that hitting the cap produces scale_throttled.
        _fresh_window(agent, target)
        cap_tick = agent.tick({target: _high_signal()})
        reasons = _throttle_reasons(cap_tick)
        assert "max_replicas_cap" in reasons, (
            f"expected max_replicas_cap throttle at cap=2, got reasons={reasons}"
        )

    def test_global_default_cap_key_name_is_maint_scaler_max_replicas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """White-box: the cfg key used by the scaler must be exactly
        ``maint_scaler_max_replicas`` — changing the name silently breaks
        enforcement and this test surfaces that."""
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 999, raising=False)
        # Phase 8 §8.14.8: trainer.v1 is now the default self_scaling_target;
        # disable that guard so the cap test can exercise trainer.v1 as a
        # normal auto-scaled target for max_replicas_cap enforcement.
        monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)

        agent = MaintScaler()
        target = "trainer.v1"
        # First tick may scale to 1 (at the cap), subsequent ticks must throttle.
        _fresh_window(agent, target)
        agent.tick({target: _high_signal()})
        _fresh_window(agent, target)
        out = agent.tick({target: _high_signal()})
        assert "max_replicas_cap" in _throttle_reasons(out), (
            "maint_scaler_max_replicas=1 must trigger max_replicas_cap throttle"
        )


# ── Triangle corner B: per-agent CSV override ────────────────────────────────

class TestTriangleCornerB:
    """Corner B — a CSV entry in ``maint_scaler_max_replicas_overrides_csv``
    sets the per-agent ceiling independently of the global default.  The scaler
    must honour the lower of the two where applicable."""

    def test_csv_override_lower_than_global_is_enforced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Global default allows 10; CSV override for the target allows only 3.
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 10, raising=False)
        monkeypatch.setattr(
            cfg, "maint_scaler_max_replicas_overrides_csv", "consensus.v1=3", raising=False
        )
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()
        target = "consensus.v1"

        for _ in range(6):
            _fresh_window(agent, target)
            agent.tick({target: _high_signal()})

        assert agent._targets[target].last_replicas <= 3, (
            "CSV override maint_scaler_max_replicas_overrides_csv=consensus.v1=3 must cap at 3"
        )

        _fresh_window(agent, target)
        out = agent.tick({target: _high_signal()})
        assert "max_replicas_cap" in _throttle_reasons(out)

    def test_csv_override_does_not_affect_other_targets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The CSV override for consensus.v1 must not bleed into other agents.
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 5, raising=False)
        monkeypatch.setattr(
            cfg, "maint_scaler_max_replicas_overrides_csv", "consensus.v1=1", raising=False
        )
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()
        other = "predictor.elo"

        for _ in range(3):
            _fresh_window(agent, other)
            agent.tick({other: _high_signal()})

        # predictor.elo should be able to scale to 5 (the global default), not 1.
        assert agent._targets[other].last_replicas >= 2, (
            "CSV override for consensus.v1 must not cap unrelated target predictor.elo"
        )


# ── Triangle corner C: global roster cap (maint_scaler_global_max_replicas) ──

class TestTriangleCornerC:
    """Corner C — the global roster ceiling ``maint_scaler_global_max_replicas``
    fires even when the per-agent cap has not been reached, defending against
    multi-agent surge."""

    def test_global_cap_blocks_scale_up_at_roster_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 100, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 4, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()
        # Pre-populate the roster so it already equals the global cap.
        agent._evict_and_get("trainer.v1").last_replicas = 4

        out = agent.tick({"predictor.elo": _high_signal()})
        assert "global_max_replicas" in _throttle_reasons(out), (
            "maint_scaler_global_max_replicas=4 with roster at 4 must emit global_max_replicas throttle"
        )

    def test_global_cap_key_name_is_maint_scaler_global_max_replicas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """White-box: cfg key must be ``maint_scaler_global_max_replicas`` exactly."""
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 100, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 2, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()
        agent._evict_and_get("trainer.v1").last_replicas = 2

        out = agent.tick({"consensus.v1": _high_signal()})
        # The throttle envelope must carry the global cap value so dashboards
        # can surface the correct limit.
        payloads = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]
        assert any(
            p.get("reason") == "global_max_replicas" and p.get("global_max_replicas") == 2
            for p in payloads
        ), f"expected global_max_replicas=2 in throttle payload, got {payloads}"


# ── Chaos-flap hysteresis: simulates make chaos-flap-replicas AGENT=consensus.v1

class TestChaosFlap:
    """Simulates ``make chaos-flap-replicas AGENT=consensus.v1``.

    Alternates high/low signals at sub-``min_decision_interval_s`` cadence
    and asserts the scaler does NOT issue back-to-back ``scale_decision``
    events — all subsequent attempts within the interval emit
    ``scale_throttled{reason=min_decision_interval}``.

    ROADMAP §8.9 reference:
        "chaos test make chaos-flap-replicas AGENT=consensus.v1 proves
        hysteresis (no back-to-back decisions inside min_decision_interval_s)"
    """

    TARGET = "consensus.v1"

    def test_chaos_flap_replicas_no_back_to_back_decisions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No two consecutive scale_decision events for consensus.v1 within
        min_decision_interval_s; all intermediate attempts are throttled.

        Uses real monotonic clock (same approach as existing
        test_min_decision_interval_throttles_back_to_back).  The interval
        is set large enough that the test body completes within it.
        """
        interval_s = 3600.0  # 1 hour — test body takes < 1 s
        monkeypatch.setattr(
            cfg, "maint_scaler_min_decision_interval_s", interval_s, raising=False
        )
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_down_queue_depth", 0.5, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 20, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 0, raising=False)

        agent = MaintScaler()

        # First decision must fire (initial state; last_decision_at_ns==0 initially).
        tick1 = agent.tick({self.TARGET: _high_signal()})
        first_decisions = [m for m in tick1 if m.payload.get("kind") == "scale_decision"]
        assert first_decisions, "expected first scale_decision for consensus.v1"

        # Flap: 10 rapid alternating high/low ticks — all within the interval
        # because the interval is 1 hour and the test runs in milliseconds.
        flap_throttles: list[str] = []
        flap_decisions: list = []
        signals = [_high_signal, _low_signal] * 5
        for sig_fn in signals:
            # Force a fresh window (window-anchor check) but keep the
            # real last_decision_at_ns so the interval check triggers.
            _fresh_window(agent, self.TARGET)
            out = agent.tick({self.TARGET: sig_fn()})
            flap_throttles.extend(
                m.payload.get("reason")
                for m in out
                if m.payload.get("kind") == "scale_throttled"
            )
            flap_decisions.extend(
                m for m in out if m.payload.get("kind") == "scale_decision"
            )

        # All flap attempts within the interval must be throttled.
        assert not flap_decisions, (
            f"no scale_decision should fire during flap within interval_s={interval_s}; "
            f"got {[m.payload for m in flap_decisions]}"
        )
        assert "min_decision_interval" in flap_throttles, (
            f"expected min_decision_interval throttle during flap; got {flap_throttles}"
        )

    def test_chaos_flap_replicas_resumes_after_interval_clears(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once ``min_decision_interval_s`` elapses the scaler is free to
        emit a new decision — the hysteresis is time-bounded, not permanent.

        Simulates the passage of time by backdating ``last_decision_at_ns``
        to a timestamp far in the past.
        """
        import time as _t
        interval_s = 3600.0
        monkeypatch.setattr(
            cfg, "maint_scaler_min_decision_interval_s", interval_s, raising=False
        )
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 20, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()

        # First decision.
        tick1 = agent.tick({self.TARGET: _high_signal()})
        assert any(m.payload.get("kind") == "scale_decision" for m in tick1)

        # Simulate clock advance: backdate the per-target timestamp.
        now_ns = _t.monotonic_ns()
        agent._targets[self.TARGET].last_decision_at_ns = (
            now_ns - int(interval_s * 1_000_000_000) - 1
        )

        _fresh_window(agent, self.TARGET)
        out = agent.tick({self.TARGET: _high_signal()})
        decisions = [m for m in out if m.payload.get("kind") == "scale_decision"]
        assert decisions, (
            "expected scale_decision to fire after min_decision_interval_s has elapsed"
        )

    def test_chaos_flap_replicas_throttle_payload_carries_interval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ``scale_throttled`` payload for ``min_decision_interval`` must
        carry ``min_decision_interval_s`` so operators can tune the knob
        without guessing the current value."""
        interval_s = 3600.0  # large enough that second tick is always within it
        monkeypatch.setattr(
            cfg, "maint_scaler_min_decision_interval_s", interval_s, raising=False
        )
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 20, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)

        agent = MaintScaler()

        tick1 = agent.tick({self.TARGET: _high_signal()})
        assert any(m.payload.get("kind") == "scale_decision" for m in tick1)
        _fresh_window(agent, self.TARGET)
        out = agent.tick({self.TARGET: _high_signal()})

        throttled_payloads = [
            m.payload for m in out
            if m.payload.get("kind") == "scale_throttled"
            and m.payload.get("reason") == "min_decision_interval"
        ]
        assert throttled_payloads, "expected min_decision_interval throttle"
        assert throttled_payloads[0].get("min_decision_interval_s") == pytest.approx(interval_s), (
            "scale_throttled payload must carry min_decision_interval_s for operator visibility"
        )
