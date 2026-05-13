"""Phase 8 §8.2 — `maint.scaler.v1` smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.scaler import MaintScaler, NoopController
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_subscribes_publishes_set() -> None:
    a = MaintScaler()
    assert a.name == "maint.scaler.v1"
    assert MAINT_EVENT in a.subscribes
    assert MAINT_EVENT in a.publishes
    assert MAINT_ACK in a.publishes


def test_manual_scale_pin_emits_decision_and_ack() -> None:
    controller = NoopController()
    agent = MaintScaler(controller=controller, leader=SingleProcessLeader(name="maint.scaler.v1"))
    msg = _wrap({
        "kind": "manual_scale_pin",
        "request_id": "req-001",
        "client_id": "ops",
        "target": "predictor.elo",
        "replicas": 5,
        "ttl_s": 60,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "test",
    })
    out = list(agent.handle(msg))
    kinds = [m.payload.get("kind") for m in out]
    assert "scale_decision" in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)
    assert ("predictor.elo", 5) in controller.applied


def test_non_leader_no_decision_but_acks() -> None:
    leader = SingleProcessLeader(name="maint.scaler.v1")
    leader.shed()
    agent = MaintScaler(leader=leader)
    out = list(agent.handle(_wrap({
        "kind": "manual_scale_pin",
        "request_id": "req-002",
        "client_id": "ops",
        "target": "predictor.elo",
        "replicas": 3,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "scale_decision" not in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


def test_unrelated_kind_ignored() -> None:
    agent = MaintScaler()
    assert list(agent.handle(_wrap({"kind": "bogus"}))) == []


def test_maint_pause_acks_when_target_matches() -> None:
    agent = MaintScaler()
    msgs = list(agent.handle(_wrap({
        "kind": "maint_pause",
        "request_id": "req-003",
        "client_id": "ops",
        "target": "all",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "rolling",
    })))
    assert any(m.envelope.topic == MAINT_ACK for m in msgs)


# ── Phase 8.2 gap-fill: per-agent caps, throttle taxonomy, retrain warmup ──

def test_per_agent_max_replicas_override(monkeypatch) -> None:
    """``maint_scaler_max_replicas_overrides_csv`` lets an operator
    pin a higher (or lower) ceiling on a single agent."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv",
                        "predictor.elo=2,trainer.v1=8", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 5, raising=False)
    agent = MaintScaler()
    assert agent._max_replicas_for("predictor.elo") == 2
    assert agent._max_replicas_for("trainer.v1") == 8
    assert agent._max_replicas_for("unmapped.v1") == 5


def test_scale_throttled_carries_reason(monkeypatch) -> None:
    """When the per-target cap is hit, ``tick`` must emit
    ``scale_throttled`` with a structured ``reason`` field."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv",
                        "predictor.elo=1", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    # First tick — climbs to the cap (1) since depth >= threshold.
    out1 = agent.tick({"predictor.elo": {"queue_depth": 100, "in_flight": 0, "head_age_s": 0}})
    # Force a fresh window so the second tick emits.
    agent._targets["predictor.elo"].last_window_ns = 0
    out2 = agent.tick({"predictor.elo": {"queue_depth": 100, "in_flight": 0, "head_age_s": 0}})
    msgs = [m.payload for m in out1 + out2 if m.payload.get("kind") == "scale_throttled"]
    assert msgs, "expected at least one scale_throttled when capped"
    assert any(p.get("reason") == "max_replicas_cap" for p in msgs)


def test_pinned_target_emits_throttled_with_manual_pin_active() -> None:
    """A pinned target must emit a `scale_throttled{manual_pin_active}`
    on tick rather than silently no-op."""
    agent = MaintScaler()
    list(agent.handle(_wrap({
        "kind": "manual_scale_pin",
        "request_id": "req-pin",
        "client_id": "ops",
        "target": "predictor.elo",
        "replicas": 3,
        "ttl_s": 600,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "test",
    })))
    out = agent.tick({"predictor.elo": {"queue_depth": 999, "in_flight": 0, "head_age_s": 0}})
    throttled = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]
    assert throttled and throttled[0]["reason"] == "manual_pin_active"


def test_decision_window_id_has_pod_instance_id_prefix() -> None:
    """Decision-window-id must be ``<pod_instance_id>:<anchor_ns>`` so
    that decisions from different pods never collide in audit logs."""
    agent = MaintScaler()
    out = list(agent.handle(_wrap({
        "kind": "manual_scale_pin",
        "request_id": "req-w",
        "client_id": "ops",
        "target": "predictor.elo",
        "replicas": 2,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "test",
    })))
    decisions = [m.payload for m in out if m.payload.get("kind") == "scale_decision"]
    assert decisions
    wid = decisions[0]["decision_window_id"]
    assert ":" in wid and len(wid.split(":")[0]) == 8


def test_retrain_request_warms_trainer_once(monkeypatch) -> None:
    """A `retrain_request` envelope must produce a single
    `scale_decision{source=retrain_request_warmup, target=trainer.v1}`."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_warmup_replicas", 2, raising=False)
    agent = MaintScaler()
    out = list(agent.handle(_wrap({
        "kind": "retrain_request",
        "target": "predictor.elo",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "drift",
    })))
    decisions = [m.payload for m in out if m.payload.get("kind") == "scale_decision"]
    assert len(decisions) == 1
    assert decisions[0]["target"] == "trainer.v1"
    assert decisions[0]["source"] == "retrain_request_warmup"


def test_retrain_request_dedup_skips_duplicate(monkeypatch) -> None:
    """Re-handling the SAME envelope (same message_id) must not
    re-warm — the dedup LRU keys on envelope.message_id × target."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_warmup_replicas", 2, raising=False)
    agent = MaintScaler()
    msg = _wrap({
        "kind": "retrain_request",
        "target": "predictor.elo",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "drift",
    })
    first = list(agent.handle(msg))
    second = list(agent.handle(msg))
    assert any(m.payload.get("kind") == "scale_decision" for m in first)
    assert not any(m.payload.get("kind") == "scale_decision" for m in second)


# ── §8.2 final gap-fill: payload shape, runtime, hysteresis, VRAM, counters ──

def test_scale_decision_payload_includes_prev_next_reason_observed(monkeypatch) -> None:
    """ROADMAP §8.2 binding contract: every ``scale_decision`` carries
    ``prev``, ``next``, ``reason``, ``observed`` alongside the legacy
    ``replicas/source/signals`` keys (additive — back-compat preserved)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    out = agent.tick({"predictor.elo": {"queue_depth": 100, "in_flight": 0, "head_age_s": 0}})
    decisions = [m.payload for m in out if m.payload.get("kind") == "scale_decision"]
    assert decisions
    p = decisions[0]
    for k in ("prev", "next", "reason", "observed", "decision_window_id"):
        assert k in p, f"missing {k!r} in {p!r}"
    assert p["next"] == p["replicas"]  # additive, not replacement
    assert p["reason"] in {"queue_depth_high", "head_age_high", "queue_depth_low",
                           "manual_pin", "retrain_request_warmup"}


def test_min_decision_interval_throttles_back_to_back(monkeypatch) -> None:
    """A second decision for the same target inside
    ``min_decision_interval_s`` must emit ``scale_throttled``."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 60, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    out1 = agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    assert any(m.payload.get("kind") == "scale_decision" for m in out1)
    # Force a fresh decision-window — but min_decision_interval_s
    # must still gate the second emission.
    agent._targets["predictor.elo"].last_window_ns = 0
    out2 = agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    throttled = [m.payload for m in out2 if m.payload.get("kind") == "scale_throttled"]
    assert any(p.get("reason") == "min_decision_interval" for p in throttled)


def test_global_max_replicas_throttles_aggregate(monkeypatch) -> None:
    """Sum of desired replicas across the roster cannot exceed the
    global cap. The over-cap target emits ``scale_throttled``."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_changes_per_window", 10, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_global_max_replicas", 2, raising=False)
    agent = MaintScaler()
    # Pre-populate one target at replicas=2 so the next scale-up
    # would push the projected roster total to 3 > 2.
    agent._evict_and_get("trainer.v1").last_replicas = 2
    out = agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    throttled = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]
    assert any(p.get("reason") == "global_max_replicas" for p in throttled)


def test_vram_budget_exceeded_blocks_scale_up(monkeypatch) -> None:
    """A device probe that reports near-full VRAM must throttle the
    scale-up with ``vram_budget_exceeded``."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_vram_headroom_mb", 512, raising=False)
    agent = MaintScaler()
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=8192,
        vram_used_mb=7000,
        vram_per_replica_mb=2000,
    )
    out = agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    throttled = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]
    assert any(p.get("reason") == "vram_budget_exceeded" for p in throttled)


def test_vram_telemetry_stale_fail_safe(monkeypatch) -> None:
    """A probe older than 5 decision windows must throttle as
    ``vram_telemetry_stale`` rather than silently allowing the
    scale-up."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_decision_window_ms", 1000, raising=False)
    agent = MaintScaler()
    # Inject a probe with observed_at_ns far in the past.
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=16384,
        vram_used_mb=1000,
        vram_per_replica_mb=1000,
        observed_at_ns=1,  # ancient
    )
    out = agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    throttled = [m.payload for m in out if m.payload.get("kind") == "scale_throttled"]
    assert any(p.get("reason") == "vram_telemetry_stale" for p in throttled)


def test_metrics_snapshot_increments_on_decision(monkeypatch) -> None:
    """Every emitted scale_decision must increment a labelled counter."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    assert agent.metrics_snapshot() == {}
    agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    snap = agent.metrics_snapshot()
    assert snap, "expected at least one counter after a decision"
    assert any(k.startswith("maint_scaler_scale_decision_total") for k in snap)


def test_observability_metrics_cover_phase8_2_contract(monkeypatch) -> None:
    """Phase 8.2 observability contract: decisions counter + desired
    replicas gauge + VRAM budget gauge + runtime histogram."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    agent.update_device_probe(
        "predictor.elo",
        vram_total_mb=8192,
        vram_used_mb=2048,
        vram_per_replica_mb=512,
        host="host-a",
    )
    agent.tick({"predictor.elo": {"queue_depth": 99, "in_flight": 0, "head_age_s": 0}})
    snap = agent.metrics_snapshot()
    assert (
        "maint_scaler_decisions_total"
        "{agent=maint.scaler.v1,reason=queue_depth_high,outcome=applied}"
    ) in snap
    assert "maint_scaler_desired_replicas{agent=predictor.elo}" in snap
    assert "maint_scaler_vram_budget_mb{host=host-a}" in snap
    assert (
        "maint_scaler_runtime_call_seconds_count"
        "{controller=noop,outcome=success}"
    ) in snap


def test_compose_controller_invokes_subprocess(tmp_path) -> None:
    """ComposeController must shell out to ``docker compose --scale``
    and surface the exit code."""
    from swarm.agents.maint.runtime import ComposeController
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stderr = ""

    def fake_runner(cmd, **kw):  # noqa: ANN001
        calls.append(list(cmd))
        return _Result()

    ctl = ComposeController(compose_file=str(compose), timeout_s=5.0)
    ctl._runner = fake_runner  # type: ignore[assignment]
    assert ctl.apply("predictor.elo", 3) is True
    assert calls and calls[0][0] == "docker"
    assert "--scale" in calls[0]
    assert "predictor.elo=3" in calls[0]


def test_compose_controller_refuses_missing_file() -> None:
    """Boot validation: the controller must refuse to construct when
    the compose file does not exist on disk."""
    import pytest
    from swarm.agents.maint.runtime import ComposeController
    with pytest.raises(FileNotFoundError):
        ComposeController(compose_file="/nonexistent/docker-compose.yml")


def test_runtime_factory_selects_noop_by_default(monkeypatch) -> None:
    """``cfg.maint_runtime=none`` (default) must yield NoopController."""
    from common.config import cfg
    from swarm.agents.maint.runtime import NoopController, make_runtime_controller
    monkeypatch.setattr(cfg, "maint_runtime", "none", raising=False)
    assert isinstance(make_runtime_controller(), NoopController)


def test_runtime_factory_refuses_k8s_until_phase_14(monkeypatch) -> None:
    """``cfg.maint_runtime=k8s`` must refuse loud (no silent fall-back)."""
    import pytest
    from common.config import cfg
    from swarm.agents.maint.runtime import make_runtime_controller
    monkeypatch.setattr(cfg, "maint_runtime", "k8s", raising=False)
    with pytest.raises(NotImplementedError):
        make_runtime_controller()


def test_cfg_rejects_unknown_maint_runtime() -> None:
    """Boot validation: unknown ``maint_runtime`` value must raise.

    We construct a fresh AppConfig on the side and exercise its
    validator directly so we do NOT mutate the process-wide ``cfg``
    singleton (which would leak into every later test in the suite).
    """
    from common.config import Config
    side = Config()
    side.maint_runtime = "kubernetes_v2"  # type: ignore[assignment]
    issues = side.validate()
    assert any("maint_runtime" in x for x in issues), \
        f"expected validator to flag maint_runtime, got: {issues!r}"


# ── Phase 8 §8.2 A1 — Welford rolling sketches + scale_down_grace_windows ──

def test_welford_smooths_single_spike(monkeypatch) -> None:
    """A single spike in queue_depth must NOT trigger scale-up when
    smoothed by the Welford sketch (window > 1)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 5, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_queue_depth", 5, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 0, raising=False)
    agent = MaintScaler()
    # Four calm windows → mean stays low.
    for _ in range(4):
        agent.tick({"a": {"queue_depth": 5, "in_flight": 1, "head_age_s": 0}})
    # One spike — mean = (5*4 + 200)/5 = 44 < 50 → still no scale-up.
    out = agent.tick({"a": {"queue_depth": 200, "in_flight": 1, "head_age_s": 0}})
    kinds = [m.payload.get("kind") for m in out]
    assert "scale_decision" not in kinds


def test_welford_window_zero_falls_back_to_instantaneous(monkeypatch) -> None:
    """``maint_scaler_signal_window_samples=0`` disables smoothing — a
    single sample above the threshold MUST trigger scale-up immediately."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 0, raising=False)
    agent = MaintScaler()
    out = agent.tick({"a": {"queue_depth": 200, "in_flight": 1, "head_age_s": 0}})
    kinds = [m.payload.get("kind") for m in out]
    assert "scale_decision" in kinds


def test_scale_down_grace_holds_replicas_for_n_windows(monkeypatch) -> None:
    """A target sitting at >1 replicas must observe grace windows of
    low load BEFORE the scaler emits the down-scale. Throttle reason
    on the held windows is `scale_down_grace`."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_queue_depth", 5, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_decision_window_ms", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_min_replicas", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_hysteresis_windows", 1, raising=False)
    agent = MaintScaler()
    # Pre-load: target sitting at 3 replicas so a down-scale is even possible.
    agent._targets["a"] = agent._evict_and_get("a")
    agent._targets["a"].last_replicas = 3
    sig = {"a": {"queue_depth": 1, "in_flight": 0, "head_age_s": 0}}
    import time
    out1 = agent.tick(sig); time.sleep(0.005)
    out2 = agent.tick(sig); time.sleep(0.005)
    out3 = agent.tick(sig)
    reasons1 = [m.payload.get("reason") for m in out1 if m.payload.get("kind") == "scale_throttled"]
    reasons2 = [m.payload.get("reason") for m in out2 if m.payload.get("kind") == "scale_throttled"]
    kinds3 = [m.payload.get("kind") for m in out3]
    assert "scale_down_grace" in reasons1
    assert "scale_down_grace" in reasons2
    # On the third low window the grace counter is satisfied → real down-scale fires.
    assert "scale_decision" in kinds3
    # Streak resets after the down-scale fires.
    assert agent._targets["a"].low_streak == 3 or agent._targets["a"].last_replicas == 2


def test_scale_up_resets_low_streak(monkeypatch) -> None:
    """A scale-up signal mid-streak resets the consecutive-low-window
    counter so a subsequent calm window starts the grace clock fresh."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_queue_depth", 5, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_down_grace_windows", 5, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_min_decision_interval_s", 0.0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_decision_window_ms", 1, raising=False)
    agent = MaintScaler()
    st = agent._evict_and_get("a")
    st.last_replicas = 4
    import time
    agent.tick({"a": {"queue_depth": 1, "in_flight": 0, "head_age_s": 0}}); time.sleep(0.005)
    agent.tick({"a": {"queue_depth": 1, "in_flight": 0, "head_age_s": 0}}); time.sleep(0.005)
    assert st.low_streak == 2
    # Spike triggers scale-up consideration → resets streak.
    agent.tick({"a": {"queue_depth": 999, "in_flight": 0, "head_age_s": 0}})
    assert st.low_streak == 0


# ── Phase 8 §8.2 A2 — Load-driven clamp formula ──

def test_clamp_formula_steps_toward_desired(monkeypatch) -> None:
    """When the smoothed load supports many replicas the clamp formula
    raises the desired count, but the per-window step cap throttles
    the actual movement (default max_step_per_window=1)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_target_load_per_replica", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_step_per_window", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    agent = MaintScaler()
    # Load = 200 → desired = ceil(200/50) = 4, but step cap → +1.
    out = agent.tick({"a": {"queue_depth": 200, "in_flight": 0, "head_age_s": 0}})
    decisions = [m for m in out if m.payload.get("kind") == "scale_decision"]
    assert decisions, f"expected a scale_decision, got {[m.payload for m in out]}"
    assert decisions[0].payload["next"] == 2  # 1 → 2 (step cap)


def test_clamp_formula_step_cap_two(monkeypatch) -> None:
    """Raising ``maint_scaler_max_step_per_window`` lets the scaler
    cover more ground per tick."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_target_load_per_replica", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_step_per_window", 3, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    agent = MaintScaler()
    out = agent.tick({"a": {"queue_depth": 500, "in_flight": 0, "head_age_s": 0}})
    decisions = [m for m in out if m.payload.get("kind") == "scale_decision"]
    assert decisions
    # Load 500 → desired = 10. Current 1 + step 3 = 4.
    assert decisions[0].payload["next"] == 4


def test_clamp_formula_disabled_falls_back_to_step(monkeypatch) -> None:
    """``maint_scaler_target_load_per_replica=0`` reverts to the legacy
    ±1-step decision (no clamp formula)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_scaler_signal_window_samples", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_target_load_per_replica", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 50, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    agent = MaintScaler()
    out = agent.tick({"a": {"queue_depth": 500, "in_flight": 0, "head_age_s": 0}})
    decisions = [m for m in out if m.payload.get("kind") == "scale_decision"]
    assert decisions
    assert decisions[0].payload["next"] == 2  # +1 step from default 1
