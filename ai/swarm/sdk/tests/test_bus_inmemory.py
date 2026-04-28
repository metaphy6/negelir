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


def test_read_is_linear_in_batch_not_in_backlog() -> None:
    """Perf guard: `read()` should walk only `count` items past the
    consumer's offset, not materialize the whole stream every call.

    With 5_000 published messages and a steady drain at batch=64 the
    cumulative work must stay near `N + N/count * count = 2N`, well
    under the prior `O(N**2/count)` quadratic.
    """
    bus = InMemoryBus()
    n = 5_000
    for i in range(n):
        bus.publish(Message.new("t", {"i": i}))
    consumed = 0
    t0 = time.perf_counter()
    while True:
        out = bus.read("t", "g", "c", count=64)
        if not out:
            break
        for d in out:
            bus.ack("t", "g", d.handle)
        consumed += len(out)
    elapsed = time.perf_counter() - t0
    assert consumed == n
    # Generous ceiling — the prior quadratic implementation took ~5s
    # on the same machine for n=5_000; the linear version finishes in
    # well under 0.5s. We assert under 2s to keep the guard stable on
    # slower CI runners while still catching a regression to quadratic.
    assert elapsed < 2.0, f"read() too slow ({elapsed:.2f}s for {n} msgs)"


def test_ack_is_constant_time_per_handle() -> None:
    """Perf guard: `ack()` is dict-keyed (was list-scan, O(N_pending))."""
    bus = InMemoryBus()
    for i in range(2_000):
        bus.publish(Message.new("t", {"i": i}))
    out = bus.read("t", "g", "c", count=2_000)
    t0 = time.perf_counter()
    for d in out:
        bus.ack("t", "g", d.handle)
    elapsed = time.perf_counter() - t0
    assert bus.pending_count("t", "g") == 0
    # Old O(N) scan: ~2s for 2_000 acks; new O(1): well under 0.1s.
    assert elapsed < 1.0, f"ack() too slow ({elapsed:.2f}s for 2_000 acks)"
