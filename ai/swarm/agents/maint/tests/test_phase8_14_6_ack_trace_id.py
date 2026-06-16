"""Phase 8 §8.14.6 proof tests — maint.ack.v1 carries trace_id.

Five bullets in the §8.14.6 DoD, exercised here:

1. **Real gap** — maint.ack.v1 payload lacked trace_id; Jaeger traces
   stopped at publish edge. Verified by checking the JSON schema and
   MaintAck dataclass now have the field.
2. **Schema addition** — maint.ack.v1.json + MaintAck gain trace_id
   and schema_version=2. All _ack() methods copy msg.envelope.trace_id.
3. **Spool replay trace-context preservation** — spool round-trip
   preserves the original trace_id in the ack payload.
4. **Versioning** — schema_version 1→2; legacy producers trigger
   sec.alert.v1{kind=maint_ack_legacy_schema} once per accepted_by.
5. **Proof tests** — (a) round-trip, (b) spool replay, (c) boundary.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from swarm.agents.maint.backup import MaintBackupAgent
from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.maint.schema import MaintSchemaSentinel
from swarm.agents.maint.scaler import MaintScaler
from swarm.agents.maint.sec import MaintSecAgent
from swarm.agents.payloads import KNOWN_SEC_ALERT_KINDS, MaintAck
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.types import Envelope, Message


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _make_event(trace_id: str | None, kind: str = "maint_pause") -> Message:
    """Build a minimal maint.event.v1 Message with the given trace_id."""
    env = Envelope(
        message_id=str(uuid.uuid4()),
        trace_id=trace_id,
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=_utc_iso(),
        schema_version=1,
        attempt=1,
    )
    return Message(
        envelope=env,
        payload={
            "kind": kind,
            "target": "maint.schema.v1",
            "request_id": str(uuid.uuid4()),
            "client_id": "op1",
            "produced_at": _utc_iso(),
        },
    )


def _assert_ack_trace_matches_event(event: Message, ack: Message) -> None:
    """Boundary check helper: ack.payload['trace_id'] must equal
    event.envelope.trace_id. Used in boundary test (c) to verify
    that a mismatched trace_id fails this assertion.
    """
    expected_trace = event.envelope.trace_id
    actual_trace = ack.payload.get("trace_id")
    assert actual_trace == expected_trace, (
        f"Boundary violation: ack trace_id={actual_trace!r} does not match "
        f"source event trace_id={expected_trace!r} for "
        f"request_id={event.payload.get('request_id')!r}"
    )


# ─── Bullet 1: Real gap documented ───────────────────────────────────────────


def test_maint_ack_v1_json_schema_has_trace_id_and_schema_version() -> None:
    """§8.14.6 bullet 1: the JSON schema now declares trace_id + schema_version."""
    schema_path = (
        Path(__file__).parents[4] / "swarm" / "sdk" / "schemas" / "maint.ack.v1.json"
    )
    schema = json.loads(schema_path.read_text())
    assert "trace_id" in schema["properties"], (
        "maint.ack.v1.json missing trace_id property"
    )
    assert "schema_version" in schema["properties"], (
        "maint.ack.v1.json missing schema_version property"
    )
    # trace_id must NOT be in required (null is valid for synthetic acks).
    assert "trace_id" not in schema.get("required", []), (
        "trace_id must be optional in maint.ack.v1.json (null for test/synthetic acks)"
    )


def test_maint_ack_dataclass_has_trace_id_and_schema_version() -> None:
    """§8.14.6 bullet 1: MaintAck dataclass carries trace_id and schema_version."""
    ack = MaintAck(
        request_id="r1",
        accepted=True,
        accepted_by="maint.schema.v1",
        processed_at=_utc_iso(),
        trace_id="trace-abc",
    )
    assert ack.trace_id == "trace-abc"
    assert ack.schema_version == 2


def test_maint_ack_legacy_schema_kind_in_known_sec_alert_kinds() -> None:
    """§8.14.6 bullet 4: maint_ack_legacy_schema is in KNOWN_SEC_ALERT_KINDS."""
    assert "maint_ack_legacy_schema" in KNOWN_SEC_ALERT_KINDS, (
        "maint_ack_legacy_schema missing from KNOWN_SEC_ALERT_KINDS"
    )


# ─── Bullet 2 + 5a: Round-trip — trace_id copied from envelope to payload ─────


@pytest.mark.parametrize("agent_cls,ack_kind", [
    (MaintSchemaSentinel, "maint_pause"),
    (MaintScaler, "maint_pause"),
    (MaintDlqSupervisor, "maint_pause"),
    (MaintSecAgent, "maint_pause"),
    (MaintBackupAgent, "maint_pause"),
])
def test_round_trip_trace_id_copied_to_payload(agent_cls, ack_kind) -> None:
    """§8.14.6 bullet 5a: every maint agent's _ack() copies envelope trace_id
    to the MaintAck payload. trace_id in payload == trace_id in envelope.
    """
    trace_id = f"trace-{uuid.uuid4().hex}"
    event = _make_event(trace_id=trace_id, kind=ack_kind)
    agent = agent_cls()

    ack_msg = agent._ack(
        event,
        event.payload["request_id"],
        accepted=True,
        reason="ok",
    )

    assert ack_msg.payload.get("trace_id") == trace_id, (
        f"{agent_cls.__name__}._ack() did not copy trace_id to payload; "
        f"expected {trace_id!r}, got {ack_msg.payload.get('trace_id')!r}"
    )
    assert ack_msg.payload.get("schema_version") == 2, (
        f"{agent_cls.__name__}._ack() must emit schema_version=2"
    )
    # Envelope also carries trace_id (unchanged from before §8.14.6).
    assert ack_msg.envelope.trace_id == trace_id


def test_round_trip_null_trace_id_omitted_from_payload() -> None:
    """§8.14.6: when the source envelope had no trace_id, the payload
    should not include trace_id (omit rather than emit null).
    """
    event = _make_event(trace_id=None)
    agent = MaintSchemaSentinel()
    ack_msg = agent._ack(
        event,
        event.payload["request_id"],
        accepted=True,
        reason="ok",
    )
    # trace_id absent from payload (not emitted for null).
    assert "trace_id" not in ack_msg.payload, (
        "trace_id=None should be omitted from payload (wire-payload minimalism)"
    )
    # schema_version always present.
    assert ack_msg.payload.get("schema_version") == 2


# ─── Bullet 3 + 5b: Spool replay — original trace_id preserved ───────────────


def test_spool_replay_preserves_trace_id_in_ack_payload(tmp_path) -> None:
    """§8.14.6 bullet 5b: an envelope loaded from spool carries the original
    trace_id on its envelope; the agent's _ack() copies it to the payload.

    Simulates the spool round-trip used by the bus circuit-breaker and
    opsctl spool-flush (§8.11 / §8.1.spool):
      1. Serialize a Message to the spool JSON format (envelope + payload).
      2. Deserialize it back using the same pattern as _load_message().
      3. Call _ack() on the deserialized message.
      4. Assert trace_id in the ack payload == original trace_id.
    """
    original_trace_id = f"spool-trace-{uuid.uuid4().hex}"
    original_event = _make_event(trace_id=original_trace_id)

    # Step 1: write to spool file (same format as _spool_write in bus_circuit_breaker).
    spool_file = tmp_path / "0000000001-test.envelope.json"
    spool_body = json.dumps(
        {"envelope": original_event.envelope.as_dict(), "payload": original_event.payload},
        ensure_ascii=False,
        sort_keys=True,
    )
    spool_file.write_text(spool_body, encoding="utf-8")

    # Step 2: deserialize (same pattern as _load_message in _bus_circuit_breaker.py).
    data = json.loads(spool_file.read_text(encoding="utf-8"))
    restored_env = Envelope(**data["envelope"])
    restored_msg = Message(envelope=restored_env, payload=data.get("payload") or {})

    # Invariant: spool must preserve the original trace_id on the envelope.
    assert restored_msg.envelope.trace_id == original_trace_id, (
        "Spool round-trip must preserve trace_id on the envelope"
    )

    # Step 3: process as if flushed from spool.
    agent = MaintSchemaSentinel()
    ack_msg = agent._ack(
        restored_msg,
        restored_msg.payload["request_id"],
        accepted=True,
        reason="replayed from spool",
    )

    # Step 4: ack payload must carry the original trace_id, NOT a fresh one.
    assert ack_msg.payload.get("trace_id") == original_trace_id, (
        "Spool-replayed ack must carry the original trace_id, not a fresh id"
    )


# ─── Bullet 5c: Boundary — mismatched trace_id fails the check ───────────────


def test_boundary_mismatched_trace_id_fails_check() -> None:
    """§8.14.6 bullet 5c: a synthesized ack with a trace_id that does not
    match the source event's trace_id fails the boundary assertion.
    """
    event_trace = f"event-trace-{uuid.uuid4().hex}"
    wrong_trace = f"wrong-trace-{uuid.uuid4().hex}"

    event = _make_event(trace_id=event_trace)

    # Synthesize a BAD ack: attacker or bug sets a different trace_id.
    bad_ack_env = Envelope(
        message_id=str(uuid.uuid4()),
        trace_id=wrong_trace,  # WRONG — should be event_trace
        topic=MAINT_ACK,
        producer="maint.schema.v1",
        created_at=_utc_iso(),
        schema_version=1,
        attempt=1,
    )
    bad_ack = Message(
        envelope=bad_ack_env,
        payload={
            "request_id": event.payload["request_id"],
            "accepted": True,
            "accepted_by": "maint.schema.v1",
            "processed_at": _utc_iso(),
            "attempt": 1,
            "schema_version": 2,
            "trace_id": wrong_trace,  # WRONG — injected wrong trace
        },
    )

    # The boundary check MUST fail for the wrong trace_id.
    with pytest.raises(AssertionError, match="Boundary violation"):
        _assert_ack_trace_matches_event(event, bad_ack)


def test_boundary_correct_trace_id_passes_check() -> None:
    """§8.14.6 bullet 5c (complementary): correct trace_id passes the check."""
    trace_id = f"trace-{uuid.uuid4().hex}"
    event = _make_event(trace_id=trace_id)
    agent = MaintSchemaSentinel()
    ack_msg = agent._ack(
        event,
        event.payload["request_id"],
        accepted=True,
        reason="ok",
    )
    # Must not raise — trace_id matches.
    _assert_ack_trace_matches_event(event, ack_msg)


# ─── Bullet 4: Versioning — legacy-schema alert ───────────────────────────────


def test_legacy_schema_alert_emitted_for_schema_version_1(monkeypatch) -> None:
    """§8.14.6 bullet 4: when the ack-wait loop receives schema_version=1,
    it emits sec.alert.v1{kind=maint_ack_legacy_schema} and registers the
    accepted_by so subsequent acks from the same producer do not re-fire.
    """
    import xops.opsctl._publish as pub_mod
    from xops.opsctl._publish import _LEGACY_SCHEMA_NOTIFIED, publish_event

    # Reset process-lifetime tracker for test isolation.
    _LEGACY_SCHEMA_NOTIFIED.clear()

    bus = InMemoryBus()
    bus.ensure_group(str(MAINT_ACK), "opsctl.ack.test-rid")
    bus.ensure_group(str(SEC_ALERT), "test.sec.reader")

    # Pre-seed a legacy (schema_version=1) ack on the bus so the wait
    # loop finds one immediately.
    legacy_ack_env = Envelope(
        message_id=str(uuid.uuid4()),
        trace_id=None,
        topic=MAINT_ACK,
        producer="maint.schema.v1",
        created_at=_utc_iso(),
        schema_version=1,
        attempt=1,
    )
    legacy_ack_payload = {
        "request_id": "test-rid",
        "accepted": True,
        "accepted_by": "maint.schema.v1",
        "processed_at": _utc_iso(),
        "attempt": 1,
        "schema_version": 1,  # legacy — no trace_id field
    }
    bus.publish(Message(envelope=legacy_ack_env, payload=legacy_ack_payload))

    # Build and publish the event.
    from swarm.agents.maint._ack_routing import expected_ack_set
    from xops.opsctl._publish import MAINT_ACK_TOPIC, MAINT_EVENT_TOPIC, OPS_CONSOLE_PRODUCER

    event_env = Envelope(
        topic=MAINT_EVENT_TOPIC,
        producer=OPS_CONSOLE_PRODUCER,
        created_at=_utc_iso(),
        schema_version=1,
        attempt=1,
    )
    event_payload = {
        "kind": "maint_pause",
        "kind_schema_version": 1,
        "target": "maint.schema.v1",
        "request_id": "test-rid",
        "client_id": "op1",
        "produced_at": _utc_iso(),
    }
    event_msg = Message(envelope=event_env, payload=event_payload)

    from common.config import Config
    cfg = Config()
    monkeypatch.setattr(cfg, "opsctl_ack_timeout_ms", 100, raising=False)

    # publish_event will read from MAINT_ACK and find the legacy ack.
    result = publish_event(bus, event_msg)

    # The alert must have been published on SEC_ALERT.
    alerts = bus.read(str(SEC_ALERT), "test.sec.reader", "test-reader", count=10, block_ms=0)
    alert_payloads = [d.message.payload for d in alerts]
    legacy_alerts = [
        p for p in alert_payloads
        if p.get("kind") == "maint_ack_legacy_schema"
        and p.get("subject") == "maint.schema.v1"
    ]
    assert len(legacy_alerts) >= 1, (
        f"Expected at least one maint_ack_legacy_schema alert; "
        f"got alerts: {alert_payloads}"
    )
    assert legacy_alerts[0]["severity"] == "info"
    assert legacy_alerts[0]["source"] == "ops_console"

    # Second call with the same accepted_by must NOT emit another alert.
    _LEGACY_SCHEMA_NOTIFIED.discard("maint.schema.v1")
    _LEGACY_SCHEMA_NOTIFIED.add("maint.schema.v1")  # simulate already-fired

    bus2 = InMemoryBus()
    bus2.ensure_group(str(MAINT_ACK), "opsctl.ack.test-rid2")
    bus2.ensure_group(str(SEC_ALERT), "test.sec.reader2")
    bus2.publish(Message(envelope=legacy_ack_env, payload={
        **legacy_ack_payload, "request_id": "test-rid2",
    }))
    event_msg2 = Message(
        envelope=event_env,
        payload={**event_payload, "request_id": "test-rid2"},
    )
    publish_event(bus2, event_msg2)

    alerts2 = bus2.read(str(SEC_ALERT), "test.sec.reader2", "test-reader2", count=10, block_ms=0)
    new_legacy_alerts = [
        d.message.payload for d in alerts2
        if d.message.payload.get("kind") == "maint_ack_legacy_schema"
        and d.message.payload.get("subject") == "maint.schema.v1"
    ]
    assert len(new_legacy_alerts) == 0, (
        "Legacy-schema alert must NOT re-fire for already-notified accepted_by"
    )


# ─── MaintAck round-trip via from_dict ───────────────────────────────────────


def test_maint_ack_from_dict_backward_compat_schema_version_1() -> None:
    """§8.14.6: MaintAck.from_dict() defaults schema_version=1 for legacy dicts
    that lack the field (backward compatibility for older producers on the wire).
    """
    legacy_dict = {
        "request_id": "r1",
        "accepted": True,
        "accepted_by": "maint.schema.v1",
        "processed_at": _utc_iso(),
        "attempt": 1,
    }
    ack = MaintAck.from_dict(legacy_dict)
    assert ack.schema_version == 1
    assert ack.trace_id is None


def test_maint_ack_from_dict_v2_round_trip() -> None:
    """§8.14.6: MaintAck.from_dict() correctly reads trace_id and schema_version=2."""
    trace = "trace-xyz"
    d = {
        "request_id": "r2",
        "accepted": True,
        "accepted_by": "maint.schema.v1",
        "processed_at": _utc_iso(),
        "attempt": 1,
        "trace_id": trace,
        "schema_version": 2,
    }
    ack = MaintAck.from_dict(d)
    assert ack.trace_id == trace
    assert ack.schema_version == 2
    # Round-trip via as_dict().
    d2 = ack.as_dict()
    assert d2["trace_id"] == trace
    assert d2["schema_version"] == 2
