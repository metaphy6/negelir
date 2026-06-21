"""Phase 8 §8.10 — Liveness probe unit tests.

Contract under test
-------------------
* Every §8.x maint agent inherits :class:`LivenessMixin`.
* :meth:`heartbeat_age_s` returns seconds since the last call to
  :meth:`on_heartbeat` (or agent construction, whichever is more recent).
* :meth:`is_alive` returns ``True`` iff ``heartbeat_age_s() < 3 * hb_sec``.
* :meth:`healthz_dict` returns ``{"alive": bool, "heartbeat_age_s": float}``.
* :meth:`on_heartbeat` resets the age to ≈ 0.
* A freshly-constructed agent is alive (age ≈ 0 < threshold).
"""
from __future__ import annotations

import pytest

from ai.swarm.agents.maint._liveness import LivenessMixin
from ai.swarm.agents.maint.backup import MaintBackupAgent
from ai.swarm.agents.maint.dlq import MaintDlqSupervisor
from ai.swarm.agents.maint.scaler import MaintScaler
from ai.swarm.agents.maint.schema import MaintSchemaSentinel
from ai.swarm.agents.maint.sec import MaintSecAgent

# Heartbeat interval used across all tests.
_HB_SEC = 5


# ── Helpers ──────────────────────────────────────────────────────────────

class _FakeClock:
    """Monotonic clock stub: starts at 0.0, advanced by ``advance()``."""

    def __init__(self) -> None:
        self._t: float = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, delta: float) -> None:
        self._t += delta


def _scaler(clock: _FakeClock) -> MaintScaler:
    return MaintScaler(liveness_clock=clock)


def _backup(clock: _FakeClock) -> MaintBackupAgent:
    return MaintBackupAgent(liveness_clock=clock, enforce_permissions=False)


def _dlq(clock: _FakeClock) -> MaintDlqSupervisor:
    return MaintDlqSupervisor(liveness_clock=clock)


def _schema(clock: _FakeClock) -> MaintSchemaSentinel:
    return MaintSchemaSentinel(liveness_clock=clock)


def _sec(clock: _FakeClock) -> MaintSecAgent:
    return MaintSecAgent(liveness_clock=clock)


_FACTORIES = [_scaler, _backup, _dlq, _schema, _sec]
_IDS = ["scaler", "backup", "dlq", "schema", "sec"]


# ── §8.10 liveness-mixin unit tests ──────────────────────────────────────

@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_fresh_agent_is_alive(factory):
    """A freshly-constructed agent must report age ≈ 0 and be alive."""
    clock = _FakeClock()
    agent = factory(clock)
    assert agent.heartbeat_age_s() == pytest.approx(0.0, abs=0.01)
    assert agent.is_alive(_HB_SEC) is True


@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_age_grows_over_time(factory):
    """heartbeat_age_s grows as the clock advances without on_heartbeat."""
    clock = _FakeClock()
    agent = factory(clock)
    clock.advance(7.0)
    assert agent.heartbeat_age_s() == pytest.approx(7.0, abs=0.01)


@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_is_alive_below_threshold(factory):
    """Agent is alive when age < 3 × heartbeat_sec."""
    clock = _FakeClock()
    agent = factory(clock)
    # 3 × 5 = 15; advance to 14.9 — still alive
    clock.advance(14.9)
    assert agent.is_alive(_HB_SEC) is True


@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_is_alive_at_threshold_boundary(factory):
    """Agent is dead when age >= 3 × heartbeat_sec."""
    clock = _FakeClock()
    agent = factory(clock)
    clock.advance(15.0)
    assert agent.is_alive(_HB_SEC) is False


@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_on_heartbeat_resets_age(factory):
    """on_heartbeat() must reset heartbeat_age_s to ≈ 0."""
    clock = _FakeClock()
    agent = factory(clock)
    clock.advance(20.0)  # age = 20 → stale
    assert agent.is_alive(_HB_SEC) is False
    agent.on_heartbeat()  # reset
    assert agent.heartbeat_age_s() == pytest.approx(0.0, abs=0.01)
    assert agent.is_alive(_HB_SEC) is True


@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_healthz_dict_shape_alive(factory):
    """healthz_dict returns the correct shape when alive."""
    clock = _FakeClock()
    agent = factory(clock)
    clock.advance(3.0)
    result = agent.healthz_dict(_HB_SEC)
    assert result["alive"] is True
    assert result["heartbeat_age_s"] == pytest.approx(3.0, abs=0.01)


@pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
def test_healthz_dict_shape_stale(factory):
    """healthz_dict returns alive=False when stale."""
    clock = _FakeClock()
    agent = factory(clock)
    clock.advance(16.0)
    result = agent.healthz_dict(_HB_SEC)
    assert result["alive"] is False
    assert result["heartbeat_age_s"] >= 15.0


# ── LivenessMixin stand-alone tests ──────────────────────────────────────

class _BareAgent(LivenessMixin):
    """Minimal LivenessMixin consumer used for direct mixin tests."""

    def __init__(self, clock=None):
        self._liveness_init(liveness_clock=clock)


def test_note_heartbeat_directly():
    """_note_heartbeat() is the same as on_heartbeat() for age reset."""
    clock = _FakeClock()
    agent = _BareAgent(clock)
    clock.advance(30.0)
    agent._note_heartbeat()
    assert agent.heartbeat_age_s() == pytest.approx(0.0, abs=0.01)


def test_on_heartbeat_base_class_only():
    """LivenessMixin.on_heartbeat() calls _note_heartbeat internally."""
    clock = _FakeClock()
    agent = _BareAgent(clock)
    clock.advance(10.0)
    LivenessMixin.on_heartbeat(agent)
    assert agent.heartbeat_age_s() == pytest.approx(0.0, abs=0.01)
