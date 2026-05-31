"""AgentRunner: happy path, retry budget → DLQ, schema-version refusal."""
from __future__ import annotations

import threading
import time
from typing import Iterable

import pytest

from swarm.sdk.agent import FunctionAgent
from swarm.sdk.bus import InMemoryBus, dlq_for
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.runner import AgentRunner
from swarm.sdk.types import ENVELOPE_SCHEMA_VERSION, Envelope, Message, Topic

ECHO_IN = Topic("echo.in")
ECHO_OUT = Topic("echo.out")


def _echo_fn(msg: Message) -> Iterable[Message]:
    yield Message.new(ECHO_OUT, {**msg.payload, "echoed": True}, producer="echo.v1")


def _echo_agent() -> FunctionAgent:
    return FunctionAgent(
        name="echo.v1", subscribes=[ECHO_IN], publishes=[ECHO_OUT], fn=_echo_fn,
    )


def _make_runner(
    bus: InMemoryBus, agent, *, retry_budget: int = 3,
) -> AgentRunner:
    return AgentRunner(
        agent=agent,
        bus=bus,
        registry=AgentRegistry(),
        max_in_flight=8,
        retry_budget=retry_budget,
        pending_claim_sec=3600,  # disable reclaim for unit tests
    )


def test_happy_path_publishes_output_and_acks() -> None:
    bus = InMemoryBus()
    runner = _make_runner(bus, _echo_agent())
    runner.register()
    bus.publish(Message.new(ECHO_IN, {"k": 1}, producer="prod"))

    runner.step()

    outs = bus.drain_topic(ECHO_OUT)
    assert len(outs) == 1
    assert outs[0].payload == {"k": 1, "echoed": True}
    assert bus.pending_count(ECHO_IN, runner._group_name()) == 0
    assert runner.metrics.snapshot()["counter.msg_consumed"] == 1
    assert runner.metrics.snapshot()["counter.msg_published"] == 1


def test_handler_exception_retries_then_dlq() -> None:
    calls = {"n": 0}

    def boom(_msg: Message) -> Iterable[Message]:
        calls["n"] += 1
        raise RuntimeError("kaboom")

    agent = FunctionAgent(name="boom.v1", subscribes=[ECHO_IN], publishes=[], fn=boom)
    bus = InMemoryBus()
    runner = _make_runner(bus, agent, retry_budget=2)
    runner.register()
    bus.publish(Message.new(ECHO_IN, {"k": 1}))

    # Step 1: attempt 0 fails → re-published with attempt=1.
    runner.step()
    # Step 2: attempt 1 fails → retry budget reached → DLQ.
    runner.step()

    assert calls["n"] == 2
    dlq = bus.drain_topic(dlq_for(ECHO_IN))
    assert len(dlq) == 1
    assert dlq[0].payload["reason"] == "retry_budget_exhausted"
    assert dlq[0].payload["original_topic"] == "echo.in"
    snap = runner.metrics.snapshot()
    assert snap["counter.msg_failed"] == 2
    assert snap["counter.msg_retried"] == 1
    assert snap["counter.msg_dlq"] == 1


def test_unsupported_schema_version_goes_to_dlq_without_calling_handler() -> None:
    calls = {"n": 0}

    def fn(_msg: Message) -> Iterable[Message]:
        calls["n"] += 1
        return []

    agent = FunctionAgent(name="echo.v1", subscribes=[ECHO_IN], publishes=[], fn=fn)
    bus = InMemoryBus()
    runner = _make_runner(bus, agent)
    runner.register()
    env = Envelope(
        topic=ECHO_IN,
        producer="alien",
        schema_version=ENVELOPE_SCHEMA_VERSION + 1,
    )
    bus.publish(Message(envelope=env, payload={"k": 1}))

    runner.step()

    assert calls["n"] == 0
    dlq = bus.drain_topic(dlq_for(ECHO_IN))
    assert len(dlq) == 1
    assert dlq[0].payload["reason"] == "schema_version_unsupported"


def test_runner_processes_all_messages_in_one_step_up_to_max_in_flight() -> None:
    bus = InMemoryBus()
    runner = _make_runner(bus, _echo_agent())
    runner.register()
    for i in range(5):
        bus.publish(Message.new(ECHO_IN, {"i": i}))
    runner.step()
    outs = bus.drain_topic(ECHO_OUT)
    assert len(outs) == 5


def test_step_reports_idle_when_no_messages() -> None:
    bus = InMemoryBus()
    runner = _make_runner(bus, _echo_agent())
    runner.register()
    assert runner.step() is False


def test_handler_returning_none_is_safe() -> None:
    def fn(_msg: Message):
        return None

    agent = FunctionAgent(name="silent.v1", subscribes=[ECHO_IN], publishes=[], fn=fn)
    bus = InMemoryBus()
    runner = _make_runner(bus, agent)
    runner.register()
    bus.publish(Message.new(ECHO_IN, {"k": 1}))
    runner.step()
    assert bus.pending_count(ECHO_IN, runner._group_name()) == 0
    assert runner.metrics.snapshot()["counter.msg_consumed"] == 1


def test_register_creates_consumer_groups_for_subscribed_topics() -> None:
    bus = InMemoryBus()
    runner = _make_runner(bus, _echo_agent())
    runner.register()
    # Group must exist even before any read.
    bus.publish(Message.new(ECHO_IN, {"k": 1}))
    out = bus.read(ECHO_IN, runner._group_name(), runner.instance_id, count=10)
    assert len(out) == 1


@pytest.mark.parametrize("count", [10_000])
def test_no_leak_under_load_in_memory(count: int) -> None:
    """DoD §3.7: 10 000 echo messages, no runtime leaks, pending == 0,
    registry empty after deregister, all messages observed at the publisher.

    "Leak" is measured as residual Python-heap retained AFTER the bus and
    runner are dropped and gc.collect() runs — i.e. anything still alive
    is by definition not freed by ordinary cleanup. The bus itself
    retains the full stream while alive (Redis-Streams parity), which is
    not a leak; the spec's "< 5 MB" budget is residual-only.
    """
    import gc
    import resource  # POSIX-only stdlib; CI is Linux
    import tracemalloc

    bus = InMemoryBus()
    registry = AgentRegistry()
    runner = AgentRunner(
        agent=_echo_agent(),
        bus=bus,
        registry=registry,
        max_in_flight=64,
        retry_budget=3,
        pending_claim_sec=3600,
    )
    runner.register()

    rss_before_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    for i in range(count):
        bus.publish(Message.new(ECHO_IN, {"i": i}))
    while runner.step():
        pass
    outs = bus.drain_topic(ECHO_OUT)

    assert len(outs) == count
    assert bus.pending_count(ECHO_IN, runner._group_name()) == 0
    runner.deregister()
    assert registry.all_specs() == {}

    # Drop every reference to bus/runner/messages, then collect.
    del runner, bus, registry, outs
    gc.collect()

    snap_after = tracemalloc.take_snapshot()
    diff = snap_after.compare_to(snap_before, "filename")
    residual_mb = sum(s.size_diff for s in diff if s.size_diff > 0) / (1024.0 * 1024.0)
    tracemalloc.stop()

    rss_after_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_delta_mb = max(0, (rss_after_kb - rss_before_kb)) / 1024.0

    # Spec: < 5 MB residual (after bus drop). Anything still on the heap
    # is genuinely unreferenced from anywhere we control.
    assert residual_mb < 5.0, (
        f"Residual Python heap after drop+gc: {residual_mb:.2f} MB "
        f"after {count} msgs (true leak)"
    )
    # RSS is interpreter-influenced and may include freed-but-unreturned
    # arenas; keep a generous sanity bound.
    assert rss_delta_mb < 50, f"RSS spike: {rss_delta_mb:.1f} MB after {count} msgs"


def test_crash_recovery_reclaims_pending_to_surviving_consumer() -> None:
    """DoD §3.7: crash-recovery — kill consumer mid-stream, restart;
    in-flight messages are reclaimed exactly once by the survivor.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()
    # Consumer A claims a message but "crashes" before acking.
    runner_a = AgentRunner(
        agent=_echo_agent(),
        bus=bus,
        registry=registry,
        max_in_flight=8,
        retry_budget=3,
        pending_claim_sec=0,  # let reclaim fire immediately for the test
        instance_id="echo.crashy",
    )
    runner_a.register()
    bus.publish(Message.new(ECHO_IN, {"k": 1}))
    # Manually claim without processing (simulate crash mid-handle).
    claimed = bus.read(
        ECHO_IN, runner_a._group_name(), runner_a.instance_id, count=1,
    )
    assert len(claimed) == 1
    assert bus.pending_count(ECHO_IN, runner_a._group_name()) == 1
    # Consumer A "crashes" — deregister without acking.
    runner_a.deregister()

    # Consumer B starts up under the SAME group and runs one step.
    runner_b = AgentRunner(
        agent=_echo_agent(),
        bus=bus,
        registry=registry,
        max_in_flight=8,
        retry_budget=3,
        pending_claim_sec=0,  # idle threshold = 0 → immediate reclaim
        instance_id="echo.survivor",
    )
    runner_b.register()
    runner_b.step()

    outs = bus.drain_topic(ECHO_OUT)
    assert len(outs) == 1, "survivor must reclaim and process the orphaned message"
    assert outs[0].payload == {"k": 1, "echoed": True}
    assert bus.pending_count(ECHO_IN, runner_b._group_name()) == 0


def test_stop_signal_stops_accepting_new_consumes() -> None:
    """SIGTERM path should stop accepting new reads and drain only in-flight work."""

    started = threading.Event()
    calls = {"n": 0}

    def slow(_msg: Message) -> Iterable[Message]:
        calls["n"] += 1
        started.set()
        time.sleep(0.05)
        return []

    agent = FunctionAgent(name="nlp.answer.v1", subscribes=[ECHO_IN], publishes=[], fn=slow)
    bus = InMemoryBus()
    runner = AgentRunner(
        agent=agent,
        bus=bus,
        registry=AgentRegistry(),
        max_in_flight=8,
        retry_budget=3,
        pending_claim_sec=3600,
        shutdown_grace_s=1.0,
    )

    for i in range(20):
        bus.publish(Message.new(ECHO_IN, {"i": i}, producer="prod"))

    t = threading.Thread(target=runner.run, daemon=True)
    t.start()
    assert started.wait(timeout=1.0)
    runner.stop()
    t.join(timeout=2.0)
    assert not t.is_alive(), "runner should exit after graceful drain"
    # Should not keep consuming after shutdown starts.
    assert calls["n"] < 20


def test_shutdown_runs_hooks_and_releases_consumer_group() -> None:
    """Shutdown invokes flush/gpu-release hooks and releases stream consumer."""

    class _BusWithRelease(InMemoryBus):
        def __init__(self) -> None:
            super().__init__()
            self.releases: list[tuple[str, str, str]] = []

        def release_consumer(self, topic: Topic | str, group: str, consumer: str) -> None:
            self.releases.append((str(topic), group, consumer))

    class _AgentWithHooks:
        name = "nlp.intent.v1"
        subscribes = [ECHO_IN]
        publishes = [ECHO_OUT]

        def __init__(self) -> None:
            self.gpu_released = False

        def handle(self, _msg: Message) -> Iterable[Message]:
            return []

        def flush_on_shutdown(self) -> Iterable[Message]:
            return [Message.new(ECHO_OUT, {"kind": "shutdown_flush"}, producer=self.name)]

        def release_gpu_lease(self) -> None:
            self.gpu_released = True

    bus = _BusWithRelease()
    agent = _AgentWithHooks()
    runner = AgentRunner(
        agent=agent,
        bus=bus,
        registry=AgentRegistry(),
        max_in_flight=8,
        retry_budget=3,
        pending_claim_sec=3600,
        shutdown_grace_s=1.0,
    )

    t = threading.Thread(target=runner.run, daemon=True)
    t.start()
    time.sleep(0.05)
    runner.stop()
    t.join(timeout=2.0)

    assert not t.is_alive()
    assert agent.gpu_released is True
    flushed = bus.drain_topic(ECHO_OUT)
    assert len(flushed) == 1
    assert flushed[0].payload == {"kind": "shutdown_flush"}
    assert len(bus.releases) == 1
    topic, group, _consumer = bus.releases[0]
    assert topic == str(ECHO_IN)
    assert group == "swarm:nlp.intent.v1"
