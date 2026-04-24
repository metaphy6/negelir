"""AgentRegistry: register, heartbeat, dead-after-3-misses."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from swarm.sdk.agent import AgentSpec
from swarm.sdk.registry import HEARTBEAT_KEY, AgentRegistry


@pytest.fixture()
def spec() -> AgentSpec:
    return AgentSpec(
        name="echo.v1",
        instance_id="echo.v1.abc123",
        subscribes=("echo.in",),
        publishes=("echo.out",),
        pid=4242,
    )


def test_register_then_list_returns_spec(spec: AgentSpec) -> None:
    reg = AgentRegistry()
    reg.register(spec)
    specs = reg.all_specs()
    assert spec.instance_id in specs
    assert specs[spec.instance_id].name == "echo.v1"


def test_deregister_removes_spec(spec: AgentSpec) -> None:
    reg = AgentRegistry()
    reg.register(spec)
    reg.deregister(spec.instance_id)
    assert spec.instance_id not in reg.all_specs()
    assert spec.instance_id not in reg.heartbeats()


def test_fresh_agent_is_not_stale(spec: AgentSpec) -> None:
    reg = AgentRegistry()
    reg.register(spec)
    assert not reg.is_stale(spec.instance_id, heartbeat_sec=5)


def test_unknown_agent_is_stale() -> None:
    reg = AgentRegistry()
    assert reg.is_stale("nonexistent", heartbeat_sec=5)


def test_stale_after_three_missed_heartbeats(spec: AgentSpec) -> None:
    reg = AgentRegistry()
    reg.register(spec)
    # Force the heartbeat into the past (>3×heartbeat_sec ago).
    past = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(timespec="seconds")
    reg._mem_heartbeats[spec.instance_id] = past  # type: ignore[attr-defined]
    assert reg.is_stale(spec.instance_id, heartbeat_sec=5)


def test_heartbeat_refreshes_timestamp(spec: AgentSpec) -> None:
    reg = AgentRegistry()
    reg.register(spec)
    first = reg.heartbeats()[spec.instance_id]
    time.sleep(1.1)  # ISO-8601 timespec=seconds requires ≥1s gap
    reg.heartbeat(spec.instance_id)
    second = reg.heartbeats()[spec.instance_id]
    assert second >= first


def test_heartbeat_for_unregistered_is_noop() -> None:
    reg = AgentRegistry()
    reg.heartbeat("ghost")
    assert "ghost" not in reg.heartbeats()


def test_redis_backend_uses_hset(spec: AgentSpec) -> None:
    """When given a redis-like backend, registry routes through it."""

    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, dict[str, str]] = {}
            self.expirations: dict[str, int] = {}

        def hset(self, key: str, field: str, value: str) -> None:
            self.store.setdefault(key, {})[field] = value

        def hdel(self, key: str, field: str) -> None:
            self.store.get(key, {}).pop(field, None)

        def hgetall(self, key: str) -> dict[str, str]:
            return dict(self.store.get(key, {}))

        def expire(self, key: str, ttl: int) -> None:
            self.expirations[key] = ttl

    fake = FakeRedis()
    reg = AgentRegistry(backend=fake, ttl_sec=10)
    reg.register(spec)
    assert spec.instance_id in fake.store["agent_registry"]
    assert spec.instance_id in fake.store[HEARTBEAT_KEY]
    assert fake.expirations["agent_registry"] == 40
    specs = reg.all_specs()
    assert specs[spec.instance_id].name == "echo.v1"
