"""Phase 8 §8.9 — operator scale-pin proof test (runtime mock).

Proves:
  1. While a pin is active, ``tick()`` does NOT call the runtime
     controller --- ``scale_throttled{reason=manual_pin_active}`` is
     emitted but ``RuntimeController.apply()`` is never invoked.
  2. The pin is honored until its TTL elapses (pin_max_ttl_s).
     One second before expiry: still blocked.  One second after: the
     pin is cleared, ``manual_scale_pin_expired`` is emitted, and the
     auto-scaler next tick IS allowed to call the runtime.
  3. Oversized TTL (> 86400 s) is silently clamped to 86400 s.

ROADMAP §8.9 Safety/hard-caps bullet:
  "Operator scale-pin honored for <= pin_max_ttl_s; auto-scaler
  decisions during pin emit scale_throttled, reason=manual_pin and do
  not call the runtime (proof test on the runtime mock)."
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.config import cfg
from swarm.agents.maint.runtime import NoopController
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.topics import MAINT_EVENT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message


# A large non-zero clock baseline ensures window_anchor_ns() always returns a
# positive value so that _fresh_window (last_window_ns=0) correctly marks the
# target as "needs a decision this window".
_T0_NS: int = 1_000_000_000_000  # 1000 s past monotonic "epoch"


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m-pin-proof",
        trace_id="t-pin-proof",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _high_signal() -> dict[str, float]:
    return {"queue_depth": 999.0, "in_flight": 0.0, "head_age_s": 0.0}


def _fresh_window(agent: MaintScaler, target: str) -> None:
    """Reset per-target window anchor so the next tick is eligible."""
    if target in agent._targets:
        agent._targets[target].last_window_ns = 0


class TestPinHonorsTtlAndNoRuntime:
    """Proof suite for the operator scale-pin gate (runtime mock)."""

    def test_pin_blocks_runtime_call_on_tick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """While a pin is active, tick() must NOT invoke controller.apply().

        The initial pin application (via handle()) calls the runtime once to
        set the desired replica count.  All subsequent auto-scaler ticks during
        the pin must NOT produce additional apply() calls.
        """
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)

        controller = NoopController()
        ns: list[int] = [_T0_NS]
        agent = MaintScaler(
            controller=controller,
            leader=SingleProcessLeader(name="maint.scaler.v1"),
            clock_ns=lambda: ns[0],
        )
        target = "predictor.elo"

        # Apply pin --- _handle_pin calls the runtime once.
        list(agent.handle(_wrap({
            "kind": "manual_scale_pin",
            "request_id": "req-proof-1",
            "client_id": "ops",
            "target": target,
            "replicas": 3,
            "ttl_s": 600,
            "produced_at": "2024-01-01T00:00:00+00:00",
            "reason": "proof-test",
        })))
        calls_after_pin_set = len(controller.applied)
        # Sanity: pin application issued one apply() for the initial count.
        assert calls_after_pin_set >= 1

        # Tick three times with high signals that would normally trigger
        # auto-scale.  Advance clock by one full window width per iteration
        # to avoid the "already decided this window" short-circuit.
        WINDOW_STEP_NS = 10_000_000_000  # 10 s > default decision window
        for i in range(3):
            ns[0] = _T0_NS + (i + 1) * WINDOW_STEP_NS
            _fresh_window(agent, target)
            out = agent.tick({target: _high_signal()})

            # No additional runtime call.
            assert len(controller.applied) == calls_after_pin_set, (
                f"runtime.apply() was called during active pin on iter {i}: "
                f"{controller.applied[calls_after_pin_set:]}"
            )

            # scale_throttled with reason=manual_pin_active emitted.
            throttled = [
                m.payload for m in out
                if m.payload.get("kind") == "scale_throttled"
            ]
            assert throttled, f"expected scale_throttled while pin active (iter {i})"
            assert throttled[0]["reason"] == "manual_pin_active", (
                f"expected reason=manual_pin_active, got {throttled[0]['reason']!r}"
            )

    def test_pin_expires_after_ttl_and_runtime_resumes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin expires at TTL; auto-scaler runtime call resumes post-expiry.

        Timeline (all times relative to T0 when pin was set):
          T0             -> pin set with TTL=60s  (expires at T0+60s)
          T0+59s         -> tick: still blocked, runtime not called
          T0+61s         -> tick: manual_scale_pin_expired emitted,
                            runtime IS called (auto-scaler resumed)
        """
        monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 99, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 9999, raising=False)
        monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 999, raising=False)

        controller = NoopController()
        ns: list[int] = [_T0_NS]
        agent = MaintScaler(
            controller=controller,
            leader=SingleProcessLeader(name="maint.scaler.v1"),
            clock_ns=lambda: ns[0],
        )
        target = "predictor.elo"
        TTL_S = 60

        # T0 --- set pin (pin_expires_at_ns = T0 + TTL_S * 1e9).
        list(agent.handle(_wrap({
            "kind": "manual_scale_pin",
            "request_id": "req-proof-2",
            "client_id": "ops",
            "target": target,
            "replicas": 3,
            "ttl_s": TTL_S,
            "produced_at": "2024-01-01T00:00:00+00:00",
            "reason": "proof-test",
        })))
        calls_after_pin = len(controller.applied)

        # T0 + (TTL-1)s: pin still active.
        ns[0] = _T0_NS + (TTL_S - 1) * 1_000_000_000
        _fresh_window(agent, target)
        before = agent.tick({target: _high_signal()})
        throttled = [m for m in before if m.payload.get("kind") == "scale_throttled"]
        assert throttled, "pin should still block 1s before TTL"
        assert len(controller.applied) == calls_after_pin, (
            "runtime.apply() called before pin expired"
        )

        # T0 + (TTL+1)s: pin expires on this tick.
        ns[0] = _T0_NS + (TTL_S + 1) * 1_000_000_000
        _fresh_window(agent, target)
        after = agent.tick({target: _high_signal()})

        # manual_scale_pin_expired must be present.
        expired_msgs = [m for m in after if m.payload.get("kind") == "manual_scale_pin_expired"]
        assert expired_msgs, "expected manual_scale_pin_expired after TTL elapsed"

        # Runtime must now be called (auto-scaler resumed).
        assert len(controller.applied) > calls_after_pin, (
            "runtime.apply() was not called after pin expired"
        )

    def test_pin_ttl_clamped_to_86400_seconds(self) -> None:
        """A TTL > 86400 s in the pin message is silently clamped to 86400 s.

        This prevents the pin from being made effectively permanent by passing
        an oversized ttl_s value in the message payload.
        """
        controller = NoopController()
        ns: list[int] = [_T0_NS]
        agent = MaintScaler(
            controller=controller,
            leader=SingleProcessLeader(name="maint.scaler.v1"),
            clock_ns=lambda: ns[0],
        )
        target = "predictor.elo"
        OVERSIZED_TTL_S = 999_999  # well beyond the 86400 s hard ceiling

        list(agent.handle(_wrap({
            "kind": "manual_scale_pin",
            "request_id": "req-proof-3",
            "client_id": "ops",
            "target": target,
            "replicas": 2,
            "ttl_s": OVERSIZED_TTL_S,
            "produced_at": "2024-01-01T00:00:00+00:00",
            "reason": "proof-test",
        })))

        st = agent._targets.get(target)
        assert st is not None, "target state must exist after pin"
        assert st.pin_expires_at_ns is not None, "pin_expires_at_ns must be set"

        # Pin was set at T0; with clamped TTL=86400s it must expire at
        # most T0 + 86400 * 1e9 ns.
        MAX_TTL_S = 86_400
        max_expires_ns = _T0_NS + MAX_TTL_S * 1_000_000_000
        actual_ttl_s = (st.pin_expires_at_ns - _T0_NS) // 1_000_000_000
        assert st.pin_expires_at_ns <= max_expires_ns, (
            f"pin_expires_at_ns exceeds T0+{MAX_TTL_S}s ceiling "
            f"(actual TTL ~{actual_ttl_s}s); TTL clamping is not working"
        )
