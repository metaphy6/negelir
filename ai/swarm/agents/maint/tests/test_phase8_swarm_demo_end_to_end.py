"""Phase 8.9 — live-emission JSON-Schema validation for all Phase 8 emits.

Mirrors the Phase 4 / Phase 5 / Phase 7 live-emission probe pattern:
drives each Phase 8 maint reactor through a triggering message, then
validates every emitted payload against its registered JSON Schema.

Closes ROADMAP §8.9 DoD: "Live-emission JSON-Schema validation covers every
Phase 8 emit (test_phase8_swarm_demo_end_to_end, mirroring the Phase 4 /
Phase 6 live-emission probe pattern)."

All tests are pure-Python, no I/O. Agents are constructed with their default
in-memory shims.
"""
from __future__ import annotations

import sys
import socket
import uuid
from pathlib import Path
from typing import Iterator

import pytest

from swarm.agents.maint.backup import (
    MaintBackupAgent,
    InMemoryQuarantineStore,
    StaticDiskGauge,
)
from swarm.agents.maint.deadmans import MaintDeadmansSwitch
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.scaler import MaintScaler, NoopController
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.sec import MaintSecAgent, InMemoryPatternStore
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.schemas import known_topics, validate as schema_validate
from swarm.sdk.types import Message


_KNOWN_TOPICS: frozenset[str] = frozenset(known_topics())
_ISO = "2026-05-21T12:00:00+00:00"


def _ids() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"p8demo-{n:06d}"


def _next_id_factory():
    g = _ids()
    return lambda: next(g)


def _maint_msg(payload: dict, *, producer: str = "ops_console") -> Message:
    return Message.new(MAINT_EVENT, payload, producer=producer)


def _validate_all(messages: list[Message]) -> None:
    """Assert every message whose topic has a registered schema is valid."""
    for m in messages:
        topic = str(m.envelope.topic)
        if topic not in _KNOWN_TOPICS:
            continue
        errors = schema_validate(topic, m.payload)
        assert errors == [], (
            f"Phase 8 live emission on {topic!r} violated its JSON Schema:\n  "
            + "\n  ".join(errors)
        )


# -- MaintScaler ------------------------------------------------------------


def test_live_emission_scaler_manual_pin_validates() -> None:
    """maint.scaler.v1: manual_scale_pin emits scale_decision + maint.ack.v1."""
    agent = MaintScaler(
        controller=NoopController(),
        leader=SingleProcessLeader(name="maint.scaler.v1"),
        clock_iso=lambda: _ISO,
        new_id=_next_id_factory(),
    )
    msg = _maint_msg({
        "kind": "manual_scale_pin",
        "request_id": "scaler-demo-001",
        "client_id": "ops",
        "target": "pred.elo.v1",
        "replicas": 2,
        "ttl_s": 300,
        "produced_at": _ISO,
        "reason": "phase8-demo",
    })
    out = list(agent.handle(msg))
    topics = {m.envelope.topic for m in out}
    assert MAINT_EVENT in topics, "expected maint.event.v1 from scaler"
    assert MAINT_ACK in topics, "expected maint.ack.v1 from scaler"
    _validate_all(out)


# -- MaintDlqSupervisor -----------------------------------------------------


def test_live_emission_dlq_replay_validates() -> None:
    """maint.dlq.v1: dlq_replay on a non-denied topic emits ack + notification."""
    agent = MaintDlqSupervisor(
        leader=SingleProcessLeader(name="maint.dlq.v1"),
        clock_iso=lambda: _ISO,
        clock_s=lambda: 1_716_294_000.0,
        new_id=_next_id_factory(),
    )
    msg = _maint_msg({
        "kind": "dlq_replay",
        "request_id": "dlq-demo-001",
        "client_id": "ops",
        "target": "predict.vote.dlq",
        "max_msgs": 5,
        "produced_at": _ISO,
    })
    out = list(agent.handle(msg))
    topics = {m.envelope.topic for m in out}
    assert MAINT_ACK in topics, "expected maint.ack.v1 from dlq supervisor"
    _validate_all(out)


# -- MaintSchemaSentinel ----------------------------------------------------


def test_live_emission_schema_sentinel_pause_validates() -> None:
    """maint.schema.v1: maint_pause targeting self emits maint.ack.v1."""
    agent = MaintSchemaSentinel(
        clock_iso=lambda: _ISO,
        new_id=_next_id_factory(),
    )
    msg = _maint_msg({
        "kind": "maint_pause",
        "request_id": "schema-pause-001",
        "client_id": "ops",
        "target": "maint.schema.v1",
        "ttl_s": 60,
        "produced_at": _ISO,
    })
    out = list(agent.handle(msg))
    topics = {m.envelope.topic for m in out}
    assert MAINT_ACK in topics, "expected maint.ack.v1 from schema sentinel"
    _validate_all(out)


def test_live_emission_schema_sentinel_drift_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """maint.schema.v1: observing an invalid payload triggers drift detection."""
    from common import config as _cfg_mod
    monkeypatch.setattr(_cfg_mod.cfg, "maint_schema_sample_rate_per_s", 100.0)
    monkeypatch.setattr(_cfg_mod.cfg, "maint_schema_burst", 10)
    monkeypatch.setattr(_cfg_mod.cfg, "maint_schema_drift_debounce_s", 0)
    agent = MaintSchemaSentinel(
        clock_iso=lambda: _ISO,
        clock_mono=lambda: 0.0,
        new_id=_next_id_factory(),
    )
    invalid_msg = Message.new(
        "predict.vote",
        {"totally": "wrong", "payload": True},
        producer="test.phase8.e2e",
    )
    out = list(agent.observe(invalid_msg))
    _validate_all(out)
    for m in out:
        if m.envelope.topic == MAINT_EVENT:
            assert m.payload.get("kind") == "schema_drift_detected"


# -- MaintSecAgent ----------------------------------------------------------


def test_live_emission_sec_quarantine_clear_validates() -> None:
    """maint.sec.v1: quarantine_clear with a pattern emits ack + notifications."""
    agent = MaintSecAgent(
        pattern_store=InMemoryPatternStore(),
        clock_iso=lambda: _ISO,
        new_id=_next_id_factory(),
    )
    msg = _maint_msg({
        "kind": "quarantine_clear",
        "request_id": "sec-clear-001",
        "client_id": "ops",
        "target": "qid-abc123",
        "details": {"pattern": r"\b(union|select)\b"},
        "produced_at": _ISO,
    })
    out = list(agent.handle(msg))
    topics = {m.envelope.topic for m in out}
    assert MAINT_ACK in topics, "expected maint.ack.v1 from maint.sec.v1"
    _validate_all(out)


def test_live_emission_sec_decimate_validates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """maint.sec.v1: denylist_decimate_now emits ack + denylist_decimate event."""
    from swarm.agents.maint.sec import InMemoryDecimator
    from common import config as _cfg_mod
    monkeypatch.setattr(_cfg_mod.cfg, "maint_sec_decimate_min_interval_s", 0)
    agent = MaintSecAgent(
        decimator=InMemoryDecimator(),
        clock_iso=lambda: _ISO,
        clock_ms=lambda: 1_716_294_000_000,
        new_id=_next_id_factory(),
    )
    msg = _maint_msg({
        "kind": "denylist_decimate_now",
        "request_id": "sec-decimate-001",
        "client_id": "ops",
        "target": "all",
        "produced_at": _ISO,
    })
    out = list(agent.handle(msg))
    topics = {m.envelope.topic for m in out}
    assert MAINT_ACK in topics, "expected maint.ack.v1 from maint.sec.v1 decimate"
    _validate_all(out)


# -- MaintBackupAgent -------------------------------------------------------


def test_live_emission_backup_quarantine_erase_validates() -> None:
    """maint.backup.v1: quarantine_erase emits pii_erased + ack."""
    from common.config import cfg as _cfg
    qstore = InMemoryQuarantineStore(rows_per_client={"client-42": 7})
    agent = MaintBackupAgent(
        quarantine=qstore,
        disk=StaticDiskGauge(
            free_bytes=int(_cfg.maint_backup_min_free_gb) * 1024 ** 3 * 4,
        ),
        clock_iso=lambda: _ISO,
        enforce_permissions=False,
        new_id=_next_id_factory(),
    )
    msg = _maint_msg({
        "kind": "quarantine_erase",
        "request_id": "backup-erase-001",
        "client_id": "client-42",
        "target": "client-42",
        "produced_at": _ISO,
    })
    out = list(agent.handle(msg))
    topics = {m.envelope.topic for m in out}
    assert MAINT_EVENT in topics, "expected maint.event.v1 from backup agent"
    assert MAINT_ACK in topics, "expected maint.ack.v1 from backup agent"
    pii_events = [
        m for m in out
        if m.envelope.topic == MAINT_EVENT and m.payload.get("kind") == "pii_erased"
    ]
    assert pii_events, "pii_erased event missing"
    _validate_all(out)


# -- MaintDeadmansSwitch ----------------------------------------------------


def test_live_emission_deadmans_silence_alert_validates() -> None:
    """maint.deadmans.v1: forced silence beyond the alert window emits
    sec.alert.v1{kind=maint_silence_alert} which must validate.

    Default cfg hard floors: warmup >= 3600 s, threshold >= 86400 s (24 h),
    dedup >= 300 s.  Use started_at_s=0, last_event_s=0, now_s=100_000 so
    silence_s=100000 > 86400 and uptime=100000 > 3600.
    """
    switch = MaintDeadmansSwitch(started_at_s=0.0, last_event_s=0.0)
    out = list(switch.tick(now_s=100_000.0, dlq_depths={}))
    alerts = [
        m for m in out
        if m.envelope.topic == SEC_ALERT and m.payload.get("kind") == "maint_silence_alert"
    ]
    assert alerts, "maint_silence_alert not fired under forced silence"
    _validate_all(out)


# -- Phase 8.9 make swarm.demo (extended): denylist-clear round-trip --------


def test_demo_denylist_clear_dry_run_publishes_nothing() -> None:
    """``make swarm.demo`` (extended) dry-run: validates envelope without
    publishing anything on the bus (ROADMAP §8.9 DoD bullet).

    Calls ``ops.denylist-clear --dry-run`` via the subcommand directly
    with an ``InMemoryBus``; asserts the bus stream count is unchanged.
    """
    import argparse

    from swarm.sdk.bus import InMemoryBus
    from xops.opsctl.subcommands.denylist_clear import run as _dc_run

    bus = InMemoryBus()
    args = argparse.Namespace(
        target="203.0.113.1",
        client_id="demo-op",
        dry_run=True,
        json=False,
        confirm="",
    )
    msgs_before = sum(len(s) for s in bus._streams.values())
    rc = _dc_run(args, bus=bus)
    msgs_after = sum(len(s) for s in bus._streams.values())

    assert rc == 0, f"dry-run exited non-zero: {rc}"
    assert msgs_after == msgs_before, (
        f"dry-run published {msgs_after - msgs_before} unexpected message(s)"
    )


def test_demo_denylist_clear_round_trip_ack_matches_expected_set() -> None:
    """``make swarm.demo`` (extended) live round-trip: publish
    ``maint.event.v1{kind=denylist_clear}`` through an ``InMemoryBus``
    and assert the expected consumer ack-set is observed.
    """
    import uuid
    from datetime import datetime, timezone

    from swarm.agents.maint._ack_routing import expected_ack_set
    from swarm.sdk.bus import InMemoryBus
    from swarm.sdk.types import Envelope, Message

    bus = InMemoryBus()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rid = uuid.uuid4().hex

    live_msg = Message(
        envelope=Envelope(topic=MAINT_EVENT, producer="ops_console"),
        payload={
            "kind": "denylist_clear",
            "target": "203.0.113.1",
            "request_id": rid,
            "client_id": "demo-op",
            "produced_at": now_iso,
        },
    )

    stub_group = "sec.rate.v1.demo"
    bus.ensure_group(MAINT_EVENT, stub_group)

    bus.publish(live_msg)

    # sec.rate.v1 stub: reads denylist_clear and emits maint.ack.v1.
    deliveries = bus.read(MAINT_EVENT, stub_group, "sec.rate.v1.stub",
                          count=16, block_ms=0)
    for d in deliveries:
        p = d.message.payload
        if p.get("kind") == "denylist_clear" and str(p.get("request_id")) == rid:
            ack_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            bus.publish(Message(
                envelope=Envelope(topic=MAINT_ACK, producer="sec.rate.v1"),
                payload={
                    "request_id": rid,
                    "accepted": True,
                    "accepted_by": "sec.rate.v1",
                    "reason": "demo_denylist_clear",
                    "processed_at": ack_now,
                    "attempt": 1,
                },
            ))
        bus.ack(MAINT_EVENT, stub_group, d.handle)

    # opsctl side: drain the ack via the standard consumer-group pattern.
    ack_group = f"opsctl.ack.{rid}"
    bus.ensure_group(MAINT_ACK, ack_group)
    ack_deliveries = bus.read(MAINT_ACK, ack_group, "demo.opsctl",
                              count=16, block_ms=0)
    received: set[str] = set()
    for d in ack_deliveries:
        p = d.message.payload
        if str(p.get("request_id")) == rid:
            ab = p.get("accepted_by")
            if isinstance(ab, str):
                received.add(ab)
        bus.ack(MAINT_ACK, ack_group, d.handle)

    expected = expected_ack_set("denylist_clear")

    assert received == expected, (
        f"ack set mismatch: got {received!r}, expected {expected!r}"
    )
    # Validate the emitted ack payload against the registered schema.
    ack_messages = [
        d.message for d in ack_deliveries
        if str(d.message.payload.get("request_id")) == rid
    ]
    _validate_all(ack_messages)


def test_phase8_16_13_swarm_demo_inmemory_success_without_latency_assertion() -> None:
    """ROADMAP §8.16.13 proof (a): InMemory demo succeeds without latency gate."""
    from swarm.sdk.bus import InMemoryBus

    bus = InMemoryBus()
    swarm_make = _load_swarm_makefile_module()

    swarm_make._run_phase8_opsctl_demo(bus, max_ack_latency_ms=None)


def _redis_available_live_demo(host: str = "localhost", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _scan_prefixed_keys(client, prefix: str) -> list[bytes | str]:
    pattern = f"{prefix}*"
    cursor = 0
    out: list[bytes | str] = []
    while True:
        cursor, batch = client.scan(cursor=cursor, match=pattern, count=100)
        if batch:
            out.extend(batch)
        if cursor == 0:
            break
    return out


def _load_swarm_makefile_module():
    """Import xops/makefile/swarm.py with sibling _common resolution."""
    repo_root = Path(__file__).resolve().parents[5]
    makefile_dir = str(repo_root / "xops" / "makefile")
    if makefile_dir not in sys.path:
        sys.path.insert(0, makefile_dir)
    from xops.makefile import swarm as swarm_make

    return swarm_make


@pytest.mark.skipif(
    not _redis_available_live_demo(),
    reason="Phase 8.16.13 live demo proof test requires Redis on localhost:6379",
)
def test_phase8_16_13_swarm_demo_live_redis_latency_and_cleanup() -> None:
    """ROADMAP §8.16.13 proof (b): live Redis demo meets <1000ms and cleans keys."""
    redis = pytest.importorskip("redis")
    from swarm.sdk.bus import RedisStreamsBus
    swarm_make = _load_swarm_makefile_module()

    client = redis.Redis(host="localhost", port=6379, decode_responses=False)
    client.ping()

    bus = RedisStreamsBus(host="localhost", port=6379, client=client)
    topic_prefix = f"phase8.16.13.demo.live.{uuid.uuid4().hex[:10]}"

    try:
        swarm_make._run_phase8_opsctl_demo(
            bus,
            max_ack_latency_ms=1000,
            topic_prefix=topic_prefix,
        )

        touched = _scan_prefixed_keys(client, topic_prefix)
        assert touched, "live demo did not create prefixed Redis keys to clean"
    finally:
        swarm_make._redis_demo_cleanup(bus, topic_prefix=topic_prefix)

    leftovers = _scan_prefixed_keys(client, topic_prefix)
    assert leftovers == [], f"expected zero leftover keys, got {leftovers!r}"
