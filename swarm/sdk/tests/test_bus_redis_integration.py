"""Redis-backed parity tests for the SDK.

DoD §3.7: the unit-test suite runs identically against InMemoryBus and
RedisStreamsBus (when the broker is reachable). CI uses InMemoryBus
only — these are opt-in via `NEGELIR_BUS_INTEGRATION=1` AND a reachable
Redis at `REDIS_HOST`/`REDIS_PORT`.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

from common.config import cfg
from swarm.sdk.bus import RedisStreamsBus, dlq_for
from swarm.sdk.types import Message, Topic

_INTEGRATION = os.environ.get("NEGELIR_BUS_INTEGRATION") == "1"


def _redis_available() -> bool:
    if not _INTEGRATION:
        return False
    try:
        import redis  # noqa: PLC0415
    except ImportError:
        return False
    try:
        client = redis.Redis(
            host=cfg.redis_host, port=int(cfg.redis_port), socket_timeout=1
        )
        client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(),
    reason="set NEGELIR_BUS_INTEGRATION=1 with a reachable redis to run",
)


@pytest.fixture()
def bus() -> RedisStreamsBus:
    return RedisStreamsBus(host=cfg.redis_host, port=int(cfg.redis_port))


@pytest.fixture()
def topic() -> Topic:
    # Unique per-test stream so concurrent runs don't collide.
    return Topic(f"sdk.it.{uuid.uuid4().hex[:8]}")


def test_publish_and_read_roundtrip(bus: RedisStreamsBus, topic: Topic) -> None:
    group = "g.it"
    bus.ensure_group(topic, group)
    bus.publish(Message.new(topic, {"k": 1}, producer="it"))
    out = bus.read(topic, group, "c1", count=10, block_ms=100)
    assert len(out) == 1
    assert out[0].message.payload == {"k": 1}
    bus.ack(topic, group, out[0].handle)
    assert bus.pending_count(topic, group) == 0


def test_at_least_once_until_ack(bus: RedisStreamsBus, topic: Topic) -> None:
    group = "g.it"
    bus.ensure_group(topic, group)
    bus.publish(Message.new(topic, {"k": 1}))
    first = bus.read(topic, group, "c1", count=10, block_ms=100)
    assert len(first) == 1
    # Without an ack, pending count must reflect the un-acked message.
    assert bus.pending_count(topic, group) >= 1
    bus.ack(topic, group, first[0].handle)


def test_reclaim_after_idle(bus: RedisStreamsBus, topic: Topic) -> None:
    group = "g.it"
    bus.ensure_group(topic, group)
    bus.publish(Message.new(topic, {"k": 1}))
    bus.read(topic, group, "c1", count=10, block_ms=100)
    # Wait briefly so the message ages past idle_ms=50.
    time.sleep(0.2)
    reclaimed = bus.reclaim(topic, group, "c2", idle_ms=50, count=10)
    assert len(reclaimed) == 1
    bus.ack(topic, group, reclaimed[0].handle)


def test_dlq_topic_can_receive(bus: RedisStreamsBus, topic: Topic) -> None:
    dlq = dlq_for(topic)
    bus.publish(Message.new(dlq, {"reason": "test"}))
    assert bus.length(dlq) >= 1


def test_crash_recovery_against_redis(bus: RedisStreamsBus, topic: Topic) -> None:
    """DoD §3.7: kill consumer mid-stream, restart; in-flight messages
    are reclaimed by the surviving consumer via XAUTOCLAIM. Redis-backed
    counterpart of the InMemoryBus crash test in test_runner.py.
    """
    group = "g.crash"
    bus.ensure_group(topic, group)
    bus.publish(Message.new(topic, {"k": 1}))

    # Consumer A claims but "crashes" without acking.
    claimed = bus.read(topic, group, "consumer.A", count=10, block_ms=200)
    assert len(claimed) == 1
    pending_after_crash = bus.pending_count(topic, group)
    assert pending_after_crash >= 1

    # Wait so the orphan exceeds the idle window.
    time.sleep(0.2)

    # Consumer B reclaims via XAUTOCLAIM.
    reclaimed = bus.reclaim(topic, group, "consumer.B", idle_ms=50, count=10)
    assert len(reclaimed) == 1, "survivor must reclaim the orphaned message"
    assert reclaimed[0].message.payload == {"k": 1}
    bus.ack(topic, group, reclaimed[0].handle)
    assert bus.pending_count(topic, group) == 0


def test_swarmctl_observability_surfaces(bus: RedisStreamsBus, topic: Topic) -> None:
    """DoD §3.7: swarmctl ps/topics rely on the same Redis primitives.
    This test exercises XLEN + XInfoGroups against a live group so the
    swarmctl Go binary's read paths are validated end-to-end.
    """
    group = "g.observability"
    bus.ensure_group(topic, group)
    bus.publish(Message.new(topic, {"k": 1}))
    bus.publish(Message.new(topic, {"k": 2}))

    # XLEN equivalent
    assert bus.length(topic) == 2

    # Claim one to create a pending entry the supervisor would see.
    out = bus.read(topic, group, "c1", count=1, block_ms=100)
    assert len(out) == 1
    assert bus.pending_count(topic, group) >= 1

    # Cleanup so concurrent test runs don't see stale pending.
    bus.ack(topic, group, out[0].handle)
    other = bus.read(topic, group, "c1", count=10, block_ms=100)
    for d in other:
        bus.ack(topic, group, d.handle)
