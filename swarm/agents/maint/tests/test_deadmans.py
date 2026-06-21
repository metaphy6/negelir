"""Phase 8 §8.16 D2 — dead-mans-switch tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from common import config as _cfg_mod
from swarm.agents.maint._pause_state import PauseState
from swarm.agents.maint.deadmans import MaintDeadmansSwitch


@dataclass
class _StubAgent:
    name: str
    _pause: PauseState


@pytest.fixture
def cfg(monkeypatch):
    """Tighten thresholds so tests stay fast and deterministic."""
    c = _cfg_mod.cfg
    monkeypatch.setattr(c, "maint_silence_warmup_s", 60, raising=True)
    monkeypatch.setattr(c, "maint_silence_alert_h", 1, raising=True)
    monkeypatch.setattr(c, "maint_self_dlq_alert", 5, raising=True)
    monkeypatch.setattr(c, "maint_silence_dedup_s", 1, raising=True)
    return c


# ── silence detector ─────────────────────────────────────────────


def test_silence_within_warmup_emits_nothing(cfg):
    sw = MaintDeadmansSwitch(started_at_s=1000.0)
    assert sw.tick(now_s=1000.0 + 30.0) == []


def test_silence_below_threshold_emits_nothing(cfg):
    sw = MaintDeadmansSwitch(started_at_s=1000.0)
    sw.note_event(now_s=1100.0)
    # 100s after last event, threshold is 1h.
    assert sw.tick(now_s=1200.0) == []


def test_silence_above_threshold_emits_critical_alert(cfg):
    sw = MaintDeadmansSwitch(started_at_s=1000.0)
    sw.note_event(now_s=1100.0)
    out = sw.tick(now_s=1100.0 + 3601.0)
    assert len(out) == 1
    p = out[0].payload
    assert p["kind"] == "maint_silence_alert"
    assert p["severity"] == "critical"
    assert p["source"] == "maint.deadmans.v1"
    assert "no maint.event.v1" in p["reason"]


def test_silence_alert_dedup_within_window(cfg):
    sw = MaintDeadmansSwitch(started_at_s=1000.0)
    out1 = sw.tick(now_s=1000.0 + 3700.0)
    out2 = sw.tick(now_s=1000.0 + 3700.5)  # < 1s dedup window
    assert len(out1) == 1
    assert out2 == []


def test_silence_alert_re_emits_after_dedup(cfg):
    sw = MaintDeadmansSwitch(started_at_s=1000.0)
    out1 = sw.tick(now_s=1000.0 + 3700.0)
    out2 = sw.tick(now_s=1000.0 + 3702.0)  # dedup is 1s
    assert len(out1) == 1
    assert len(out2) == 1


def test_silence_with_no_observed_event_uses_uptime(cfg):
    sw = MaintDeadmansSwitch(started_at_s=1000.0)
    out = sw.tick(now_s=1000.0 + 3700.0)
    assert len(out) == 1
    assert out[0].payload["kind"] == "maint_silence_alert"


# ── self-DLQ detector ────────────────────────────────────────────


def test_self_dlq_below_threshold_no_alert(cfg):
    agent = _StubAgent(name="maint.scaler.v1", _pause=PauseState())
    sw = MaintDeadmansSwitch(agents={agent.name: agent}, started_at_s=1000.0)
    out = sw.tick(now_s=1010.0, dlq_depths={agent.name: 4})
    assert out == []
    assert agent._pause.self_isolated is False


def test_self_dlq_at_threshold_flips_isolation_and_alerts(cfg):
    agent = _StubAgent(name="maint.scaler.v1", _pause=PauseState())
    sw = MaintDeadmansSwitch(agents={agent.name: agent}, started_at_s=1000.0)
    out = sw.tick(now_s=1010.0, dlq_depths={agent.name: 5})
    assert agent._pause.self_isolated is True
    assert len(out) == 1
    p = out[0].payload
    assert p["kind"] == "maint_self_dlq_alert"
    assert p["severity"] == "critical"
    assert p["subject"] == "maint.scaler.v1"
    assert "depth 5" in p["reason"]


def test_self_dlq_alert_dedup_per_agent(cfg):
    agent = _StubAgent(name="maint.scaler.v1", _pause=PauseState())
    sw = MaintDeadmansSwitch(agents={agent.name: agent}, started_at_s=1000.0)
    out1 = sw.tick(now_s=1010.0, dlq_depths={agent.name: 10})
    out2 = sw.tick(now_s=1010.5, dlq_depths={agent.name: 12})
    assert len(out1) == 1
    assert out2 == []  # within dedup window


def test_self_dlq_alert_per_agent_independent_dedup(cfg):
    a = _StubAgent(name="maint.scaler.v1", _pause=PauseState())
    b = _StubAgent(name="maint.dlq.v1", _pause=PauseState())
    sw = MaintDeadmansSwitch(agents={a.name: a, b.name: b}, started_at_s=1000.0)
    out = sw.tick(now_s=1010.0, dlq_depths={a.name: 10, b.name: 10})
    kinds = sorted(m.payload["subject"] for m in out)
    assert kinds == ["maint.dlq.v1", "maint.scaler.v1"]


def test_self_dlq_for_unknown_agent_still_alerts(cfg):
    sw = MaintDeadmansSwitch(agents={}, started_at_s=1000.0)
    out = sw.tick(now_s=1010.0, dlq_depths={"maint.unknown.v1": 99})
    assert len(out) == 1
    assert out[0].payload["subject"] == "maint.unknown.v1"


# ── §8.13.5 integration: isolation persists pause ────────────────


def test_self_isolated_agent_refuses_pause(cfg):
    """After D2 flips self_isolated, D1's matrix refuses pause."""
    agent = _StubAgent(name="maint.scaler.v1", _pause=PauseState())
    sw = MaintDeadmansSwitch(agents={agent.name: agent}, started_at_s=1000.0)
    sw.tick(now_s=1010.0, dlq_depths={agent.name: 99})
    assert agent._pause.self_isolated is True
    res = agent._pause.apply_pause(ttl_s=600, now_ns=2_000_000_000_000)
    assert res.accepted is False
    assert res.reason == "requires_resume_first"
