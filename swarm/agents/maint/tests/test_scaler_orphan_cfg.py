"""Phase 8 §8.16.1 — orphan-cfg forward-compat proof tests.

Doctrine: a cfg override entry pointing at an agent name that is
NOT in the live registry must NOT be a hard failure — it emits one
``sec.alert.v1{kind=maint_scaler_orphan_cfg, severity=info}`` per
orphan per process lifetime and is otherwise ignored.
"""
from __future__ import annotations

import pytest

from common.config import cfg
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS
from swarm.agents.topics import SEC_ALERT


# ── Kind registration ────────────────────────────────────────────────


def test_orphan_cfg_kind_is_registered() -> None:
    assert "maint_scaler_orphan_cfg" in KNOWN_SEC_ALERT_KINDS


def test_unconfigured_agent_kind_is_registered() -> None:
    """Slice 2 also added this kind; assert the registry caught up."""
    assert "maint_scaler_unconfigured_agent" in KNOWN_SEC_ALERT_KINDS


# ── Behavior ────────────────────────────────────────────────────────


def test_orphan_emits_info_alert_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv",
        "agent.live.v1=4,agent.retired.v1=2", raising=False,
    )
    # Phase 8 §8.14.8: disable self_scaling_targets to isolate
    # the max_replicas_overrides_csv orphan check.
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    out = agent.report_registered_agents(["agent.live.v1"])
    assert len(out) == 1
    msg = out[0]
    assert msg.envelope.topic == SEC_ALERT
    p = msg.payload
    assert p["kind"] == "maint_scaler_orphan_cfg"
    assert p["severity"] == "info"
    assert p["subject"] == "agent.retired.v1"
    assert "agent.retired.v1" in p["reason"]


def test_orphan_one_shot_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv",
        "agent.retired.v1=2", raising=False,
    )
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    a = agent.report_registered_agents([])
    b = agent.report_registered_agents([])
    c = agent.report_registered_agents([])
    assert len(a) == 1
    assert b == []
    assert c == []


def test_no_orphans_emits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv",
        "agent.alpha.v1=3,agent.beta.v1=5", raising=False,
    )
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    out = agent.report_registered_agents(
        ["agent.alpha.v1", "agent.beta.v1", "agent.gamma.v1"]
    )
    assert out == []


def test_empty_overrides_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False,
    )
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    assert agent.report_registered_agents([]) == []
    assert agent.report_registered_agents(["whatever.v1"]) == []


def test_orphan_does_not_crash_max_replicas_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctrine: orphan entries are otherwise ignored — they must not
    affect ceiling lookups for live agents."""
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv",
        "agent.live.v1=7,agent.retired.v1=99", raising=False,
    )
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 0, raising=False)
    agent = MaintScaler()
    agent.report_registered_agents(["agent.live.v1"])
    # Live override wins
    assert agent._max_replicas_for("agent.live.v1") == 7
    # An unrelated agent uses the legacy global cap
    assert agent._max_replicas_for("agent.brand_new.v1") == 16


def test_multiple_orphans_each_alerted_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv",
        "agent.gone.a=1,agent.gone.b=2,agent.live=4", raising=False,
    )
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    out = agent.report_registered_agents(["agent.live"])
    subjects = sorted(m.payload["subject"] for m in out)
    assert subjects == ["agent.gone.a", "agent.gone.b"]
    # All info severity
    assert all(m.payload["severity"] == "info" for m in out)
    # Re-running yields nothing
    assert agent.report_registered_agents(["agent.live"]) == []


def test_late_registration_silences_followups(monkeypatch: pytest.MonkeyPatch) -> None:
    """If an agent registers AFTER the first report (unusual but
    possible during rolling upgrades), a second report with the now-
    live agent in the names list emits no alert for it (it never
    landed in the alerted set, and it's no longer an orphan)."""
    monkeypatch.setattr(
        cfg, "maint_scaler_max_replicas_overrides_csv",
        "agent.late.v1=3", raising=False,
    )
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    first = agent.report_registered_agents([])
    assert len(first) == 1  # late-comer flagged on first sweep
    # Operator-side fix: agent now registers; no new alert on re-sweep
    second = agent.report_registered_agents(["agent.late.v1"])
    assert second == []
