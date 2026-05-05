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
