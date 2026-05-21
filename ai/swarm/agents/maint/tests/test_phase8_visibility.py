"""Phase 8 §8.9 DoD — swarmctl visibility: `ps` + `topics`.

Closes the DoD bullet:

  "Every Phase 8 agent appears in `swarmctl ps`;
   `maint.event.v1`, `maint.ack.v1`, and all `<topic>.dlq` streams
   in `swarmctl topics`."

Mirrors `test_phase7_visibility_and_lua_parity.py` — the InMemoryBus
+ AgentRegistry pair drives the same code path as production
Redis-backed wiring. The Go binary reads `agent_registry` for
`swarmctl ps` and scans stream keys for `swarmctl topics`; the in-
memory equivalents prove the same contract holds at the Python level.

Three assertions:

1. Every Phase 8 maint reactor + source watcher registers a spec
   the Go `swarmctl ps` command will read from `agent_registry`.
   Subscribes/publishes columns are validated so a regression that
   strips a topic from the agent surface fails this gate.

2. After one `manual_scale_pin` cycle, both `maint.event.v1` and
   `maint.ack.v1` surface in `bus.topics()` — the stream listing
   `swarmctl topics` enumerates.

3. Dead-letter streams (`<topic>.dlq`) surface in `bus.topics()`
   as first-class streams once a message is published to them —
   proving `swarmctl topics` can enumerate them server-side.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from swarm.agents.maint.backup import MaintBackupAgent
from swarm.agents.maint.dlq import RECURSION_DENY_SET, MaintDlqSupervisor
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.sec import MaintSecAgent
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.runner import AgentRunner
from swarm.sdk.types import Envelope, Message, Topic
from swarm.source_watcher.agent import SourceWatcherAgent

# ── Constants ───────────────────────────────────────────────────────

_PHASE8_AGENT_NAMES: frozenset[str] = frozenset({
    "maint.scaler.v1",
    "maint.backup.v1",
    "maint.dlq.v1",
    "maint.schema.v1",
    "maint.sec.v1",
    "source.watcher.v1",
})

# DLQ streams that must surface in `swarmctl topics`.
# Includes the RECURSION_DENY_SET members (maint-plane + sec plane
# DLQs that the supervisor manages but never auto-replays) plus one
# business-topic DLQ to prove the mechanism is generic.
_DLQ_STREAMS: frozenset[str] = frozenset(RECURSION_DENY_SET) | frozenset({
    "predict.vote.dlq",
})

# ── Helpers ─────────────────────────────────────────────────────────


def _build_phase8_agents() -> list:
    """Instantiate all Phase 8 maint reactors + source watcher with
    minimal stubs — exactly the set `build_agents()` includes."""
    return [
        MaintScaler(),
        MaintBackupAgent(enforce_permissions=False),
        MaintDlqSupervisor(),
        MaintSchemaSentinel(),
        MaintSecAgent(),
        SourceWatcherAgent(sources=("mackolik",), fetcher=lambda s: {}),
    ]


def _make_runner(
    agent,
    bus: InMemoryBus,
    registry: AgentRegistry,
) -> AgentRunner:
    runner = AgentRunner(
        agent=agent,
        bus=bus,
        registry=registry,
        max_in_flight=4,
        retry_budget=2,
        tick_sec=0.001,
    )
    runner.register()
    return runner


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_maint_msg(kind: str, extra: dict | None = None) -> Message:
    """Wrap a maint.event.v1 payload ready to publish."""
    payload: dict = {
        "kind": kind,
        "request_id": f"vis-{kind}",
        "client_id": "test.visibility",
        "produced_at": _now_iso(),
    }
    if extra:
        payload.update(extra)
    env = Envelope(
        message_id=f"vis-msg-{kind}",
        trace_id="vis-trace",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=_now_iso(),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


# ── Test 1: swarmctl ps ──────────────────────────────────────────────


def test_phase8_agents_register_for_swarmctl_ps() -> None:
    """Every Phase 8 maint agent registers a spec that the Go
    ``swarmctl ps`` command will read from ``agent_registry``.

    Mirrors ``test_phase7_agents_register_for_swarmctl_ps`` — the
    AgentRunner.register() call writes to the same AgentRegistry
    the production Redis-backed runner uses; the SDK suite's
    ``test_swarmctl_observability_surfaces`` proves the Redis path
    end-to-end against a live Redis.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()
    runners: list[AgentRunner] = []

    try:
        for agent in _build_phase8_agents():
            runners.append(_make_runner(agent, bus, registry))

        specs = registry.all_specs()
        registered_names = {s.name for s in specs.values()}
        missing = _PHASE8_AGENT_NAMES - registered_names
        assert not missing, (
            f"Phase 8 agents missing from agent_registry: {missing}; "
            f"Go swarmctl ps would not list them"
        )

        # Validate subscribes / publishes per agent so a regression
        # that strips a topic from the contract fails this gate.
        for spec in specs.values():
            name = spec.name
            if name not in _PHASE8_AGENT_NAMES:
                continue  # skip Phase 5/6/7 agents that may be co-registered
            if name in (
                "maint.scaler.v1",
                "maint.backup.v1",
                "maint.dlq.v1",
                "maint.schema.v1",
            ):
                assert MAINT_EVENT in spec.subscribes, (
                    f"{name}: MAINT_EVENT not in subscribes"
                )
                assert MAINT_EVENT in spec.publishes, (
                    f"{name}: MAINT_EVENT not in publishes"
                )
                assert MAINT_ACK in spec.publishes, (
                    f"{name}: MAINT_ACK not in publishes"
                )
            elif name == "maint.sec.v1":
                assert MAINT_EVENT in spec.subscribes
                assert SEC_ALERT in spec.subscribes
                assert MAINT_ACK in spec.publishes
            elif name == "source.watcher.v1":
                # Source watcher publishes MAINT_EVENT (drift alerts) but
                # does not subscribe to it.
                assert MAINT_EVENT in spec.publishes

    finally:
        for r in runners:
            r.deregister()


# ── Test 2: maint.event.v1 + maint.ack.v1 in swarmctl topics ────────


def test_phase8_maint_event_and_ack_in_swarmctl_topics() -> None:
    """After one manual_scale_pin cycle, both ``maint.event.v1`` and
    ``maint.ack.v1`` surface in ``bus.topics()`` — the same stream
    listing ``swarmctl topics`` enumerates."""
    bus = InMemoryBus()
    registry = AgentRegistry()
    scaler = MaintScaler()
    runner = _make_runner(scaler, bus, registry)

    try:
        # Publish a manual_scale_pin event — the scaler will ack it.
        bus.publish(
            _make_maint_msg(
                "manual_scale_pin",
                extra={"target": "some.agent.v1", "replicas": 2},
            )
        )

        # maint.event.v1 must already be visible (we just published to it).
        topic_names = {str(t) for t in bus.topics()}
        assert str(MAINT_EVENT) in topic_names, (
            f"maint.event.v1 missing from bus.topics() immediately after publish: "
            f"{topic_names}"
        )

        # Step the runner so the scaler handles the message and emits ack.
        runner.step()

        topic_names = {str(t) for t in bus.topics()}
        assert str(MAINT_ACK) in topic_names, (
            f"maint.ack.v1 missing from bus.topics() after scaler step: "
            f"{topic_names}"
        )

    finally:
        runner.deregister()


# ── Test 3: DLQ streams in swarmctl topics ───────────────────────────


def test_phase8_dlq_streams_in_swarmctl_topics() -> None:
    """Dead-letter streams surface in ``bus.topics()`` as first-class
    streams once a message is published to them — exactly how
    ``swarmctl topics`` enumerates streams server-side via SCAN.

    Every stream in ``_DLQ_STREAMS`` is seeded with one envelope;
    the full set must then appear in ``bus.topics()``."""
    bus = InMemoryBus()
    ts = _now_iso()

    for dlq_topic in sorted(_DLQ_STREAMS):
        env = Envelope(
            message_id=f"dlq-seed-{dlq_topic}",
            trace_id="dlq-visibility-trace",
            topic=Topic(dlq_topic),
            producer="test.phase8.visibility",
            created_at=ts,
            schema_version=1,
            attempt=1,
        )
        bus.publish(Message(envelope=env, payload={"_dlq_visibility_test": True}))

    topic_names = {str(t) for t in bus.topics()}
    missing = _DLQ_STREAMS - topic_names
    assert not missing, (
        f"DLQ streams missing from bus.topics() after seeding: {missing}; "
        f"swarmctl topics would not list them"
    )
