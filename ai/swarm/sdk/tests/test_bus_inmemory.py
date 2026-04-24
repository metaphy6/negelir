"""InMemoryBus semantics: pub/sub, consumer groups, ack, reclaim, DLQ name."""
from __future__ import annotations

import time

from swarm.sdk.bus import InMemoryBus, dlq_for
from swarm.sdk.types import Message, Topic


def test_publish_then_read_returns_message() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("t", {"k": 1}))
    out = bus.read("t", group="g1", consumer="c1", count=10)
    assert len(out) == 1
    assert out[0].message.payload == {"k": 1}


def test_consumer_group_does_not_redeliver_within_one_consumer() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("t", {"k": 1}))
    first = bus.read("t", "g1", "c1", count=10)
    second = bus.read("t", "g1", "c1", count=10)
    assert len(first) == 1
    assert len(second) == 0


def test_two_groups_each_receive_independently() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("t", {"k": 1}))
    g1 = bus.read("t", "g1", "c1", count=10)
    g2 = bus.read("t", "g2", "c1", count=10)
    assert len(g1) == 1
    assert len(g2) == 1


def test_pending_count_reflects_unacked() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("t", {"k": 1}))
    bus.publish(Message.new("t", {"k": 2}))
    out = bus.read("t", "g1", "c1", count=10)
    assert bus.pending_count("t", "g1") == 2
    bus.ack("t", "g1", out[0].handle)
    assert bus.pending_count("t", "g1") == 1


def test_reclaim_returns_only_idle_messages() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("t", {"k": 1}))
    bus.read("t", "g1", "c1", count=10)
    # Brand-new message: not idle yet.
    assert bus.reclaim("t", "g1", "c2", idle_ms=10_000, count=10) == []
    # Force idle by waiting briefly.
    time.sleep(0.05)
    out = bus.reclaim("t", "g1", "c2", idle_ms=10, count=10)
    assert len(out) == 1


def test_length_counts_published() -> None:
    bus = InMemoryBus()
    for i in range(5):
        bus.publish(Message.new("t", {"i": i}))
    assert bus.length("t") == 5


def test_dlq_for_returns_topic_dlq() -> None:
    assert dlq_for("foo") == "foo.dlq"
    # Idempotent: doesn't double-suffix.
    assert dlq_for("foo.dlq") == "foo.dlq"


def test_drain_topic_helper_pops_all() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("t", {"k": 1}))
    bus.publish(Message.new("t", {"k": 2}))
    msgs = bus.drain_topic("t")
    assert [m.payload for m in msgs] == [{"k": 1}, {"k": 2}]
    assert bus.length("t") == 0


def test_topic_isolation() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new("a", {"x": 1}))
    bus.publish(Message.new("b", {"x": 2}))
    a_msgs = bus.read("a", "g", "c", count=10)
    b_msgs = bus.read("b", "g", "c", count=10)
    assert len(a_msgs) == 1
    assert a_msgs[0].message.payload == {"x": 1}
    assert b_msgs[0].message.payload == {"x": 2}


def test_read_count_caps_returned_messages() -> None:
    bus = InMemoryBus()
    for i in range(10):
        bus.publish(Message.new("t", {"i": i}))
    out = bus.read("t", "g", "c", count=3)
    assert len(out) == 3


def test_ensure_group_is_idempotent() -> None:
    bus = InMemoryBus()
    bus.ensure_group("t", "g")
    bus.ensure_group("t", "g")
    bus.publish(Message.new("t", {"k": 1}))
    assert len(bus.read("t", "g", "c", count=10)) == 1


def test_topic_must_be_string_or_topic_newtype() -> None:
    bus = InMemoryBus()
    bus.publish(Message.new(Topic("typed"), {"k": 1}))
    out = bus.read("typed", "g", "c", count=10)
    assert len(out) == 1
