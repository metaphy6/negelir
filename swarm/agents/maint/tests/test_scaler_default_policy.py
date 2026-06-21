"""Phase 8 §8.16.1 — default-policy fallback proof tests.

These tests prove the binding doctrine: when an agent has NO
explicit entry in ``cfg.maint_scaler_max_replicas_overrides_csv``
AND ``cfg.maint_scaler_default_max_replicas > 0``:

* the per-target ceiling drops to the conservative default
  (capped by the global ceiling);
* exactly one ``sec.alert.v1{kind=maint_scaler_unconfigured_agent}``
  per process lifetime is emitted for that target;
* exactly one ``maint.event.v1{kind=maint_scaler_default_applied}``
  audit row per process lifetime is emitted for that target.

When the cfg key is 0 (default) the behavior is the legacy
fallback to ``maint_scaler_max_replicas`` with NO alert (preserves
backward compat for deployments that have not opted in).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.config import cfg
from swarm.agents.maint._ack_routing import (
    KINDS_NOTIFICATION_ONLY,
    KNOWN_MAINT_EVENT_KINDS,
)
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.topics import MAINT_EVENT, SEC_ALERT


def _signals(depth: int = 100) -> dict[str, dict[str, float]]:
    return {"agent.unconfigured.v1": {
        "queue_depth": depth, "in_flight": 0, "head_age_s": 0,
    }}


# ── Routing-table integration ─────────────────────────────────────────


def test_kind_registered_as_notification_only() -> None:
    assert "maint_scaler_default_applied" in KNOWN_MAINT_EVENT_KINDS
    assert "maint_scaler_default_applied" in KINDS_NOTIFICATION_ONLY


def test_kind_schema_file_exists() -> None:
    """Boundary: every kind in the routing table must have a schema."""
    from pathlib import Path
    p = (
        Path(__file__).resolve().parents[3]
        / "sdk" / "schemas" / "maint.event.v1"
        / "maint_scaler_default_applied.json"
    )
    assert p.is_file(), f"missing schema: {p}"


# ── Disabled (legacy) behavior ────────────────────────────────────────


def test_default_disabled_no_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    out = agent.tick(_signals())
    kinds = [m.payload.get("kind") for m in out]
    assert "maint_scaler_default_applied" not in kinds
    topics = {m.envelope.topic for m in out}
    assert SEC_ALERT not in topics
    # Legacy ceiling still applies.
    assert agent._max_replicas_for("agent.unconfigured.v1") == 16


def test_default_disabled_max_replicas_for_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 7, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    agent = MaintScaler()
    assert agent._max_replicas_for("anything.v1") == 7


# ── Enabled behavior ──────────────────────────────────────────────────


def test_enabled_lowers_ceiling_for_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    agent = MaintScaler()
    assert agent._max_replicas_for("agent.unconfigured.v1") == 2


def test_enabled_override_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv",
                        "trainer.v1=8", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    agent = MaintScaler()
    assert agent._max_replicas_for("trainer.v1") == 8
    assert agent._max_replicas_for("unmapped.v1") == 2


def test_enabled_capped_by_global_max_replicas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default cannot escape the per-target hard ceiling."""
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 100, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 4, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    agent = MaintScaler()
    # default(100) clamped down to maint_scaler_max_replicas(4)
    assert agent._max_replicas_for("anything.v1") == 4


def test_enabled_emits_one_shot_alert_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()

    out = agent.tick(_signals())
    audit = [
        m.payload for m in out
        if m.payload.get("kind") == "maint_scaler_default_applied"
    ]
    alerts = [
        m.payload for m in out
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "maint_scaler_unconfigured_agent"
    ]
    assert len(audit) == 1, f"expected one audit row, got {audit}"
    assert audit[0]["target"] == "agent.unconfigured.v1"
    assert audit[0]["applied"] == 2
    assert audit[0]["default_max_replicas"] == 2
    assert len(alerts) == 1, f"expected one sec.alert, got {alerts}"
    assert alerts[0]["severity"] == "warn"
    assert alerts[0]["subject"] == "agent.unconfigured.v1"
    assert alerts[0]["source"] == "maint.scaler.v1"


def test_enabled_one_shot_per_process_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()

    out1 = agent.tick(_signals())
    # Force fresh window so tick re-evaluates.
    agent._targets["agent.unconfigured.v1"].last_window_ns = 0
    out2 = agent.tick(_signals())
    agent._targets["agent.unconfigured.v1"].last_window_ns = 0
    out3 = agent.tick(_signals())

    all_msgs = out1 + out2 + out3
    audit = [m for m in all_msgs if m.payload.get("kind") == "maint_scaler_default_applied"]
    alerts = [m for m in all_msgs if m.envelope.topic == SEC_ALERT]
    assert len(audit) == 1, "audit row must be one-shot per process lifetime"
    assert len(alerts) == 1, "sec.alert must be one-shot per process lifetime"


def test_enabled_overridden_target_no_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    """An agent WITH an explicit override never triggers the warn."""
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv",
                        "trainer.v1=8", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    # Phase 8 §8.14.8: trainer.v1 is the default self_scaling_target;
    # disable that guard so the default-policy test can exercise trainer.v1
    # as a normal auto-scaled target to verify no spurious unconfigured alert.
    monkeypatch.setattr(cfg, "maint_scaler_self_scaling_targets", "", raising=False)
    agent = MaintScaler()
    out = agent.tick({"trainer.v1": {
        "queue_depth": 100, "in_flight": 0, "head_age_s": 0,
    }})
    audit = [m for m in out if m.payload.get("kind") == "maint_scaler_default_applied"]
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    assert audit == []
    assert alerts == []


def test_enabled_distinct_targets_each_get_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two unconfigured targets each emit exactly one alert + one audit."""
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    sigs = {
        "agent.a.v1": {"queue_depth": 100, "in_flight": 0, "head_age_s": 0},
        "agent.b.v1": {"queue_depth": 100, "in_flight": 0, "head_age_s": 0},
    }
    out = agent.tick(sigs)
    audit = [m for m in out if m.payload.get("kind") == "maint_scaler_default_applied"]
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    assert {m.payload["target"] for m in audit} == {"agent.a.v1", "agent.b.v1"}
    assert {m.payload["subject"] for m in alerts} == {"agent.a.v1", "agent.b.v1"}


def test_audit_payload_matches_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit row carries exactly the required fields per schema."""
    monkeypatch.setattr(cfg, "maint_scaler_default_max_replicas", 3, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas", 16, raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_max_replicas_overrides_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_scaler_scale_up_queue_depth", 1, raising=False)
    agent = MaintScaler()
    out = agent.tick(_signals())
    [audit] = [m for m in out if m.payload.get("kind") == "maint_scaler_default_applied"]
    p = audit.payload
    assert p.keys() >= {
        "kind", "target", "produced_at", "applied", "default_max_replicas",
    }
    assert p["applied"] == 3
    assert p["default_max_replicas"] == 3


def test_config_validator_rejects_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Floor when enabled is 2 — 1 is indistinguishable from \"never scale me\"."""
    from common.config import Config
    issues = Config().__class__(maint_scaler_default_max_replicas=1).validate()
    assert any(
        "maint_scaler_default_max_replicas" in s and "outside" in s
        for s in issues
    ), f"validator must flag value=1, got: {issues}"


def test_config_validator_accepts_zero() -> None:
    """0 is the disabled sentinel — must be valid."""
    from common.config import Config
    issues = Config(maint_scaler_default_max_replicas=0).validate()
    assert not any(
        "maint_scaler_default_max_replicas" in s for s in issues
    )
