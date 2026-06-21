"""Phase 8 §8.15.9 — proof tests (a): dlq_drop_request → dlq_dropped forensic audit.

Tests:
  (a1) dlq_drop_request fires dlq_dropped{reason=operator_drop} with all
       forensic fields forwarded and topic derived from target.
  (a2) Non-leader emits ack{accepted=False, reason=leader_skip}; no dlq_dropped.
  (a3) Recursion-deny target emits ack{accepted=False, reason=recursion_deny};
       no dlq_dropped.
"""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.dlq import RECURSION_DENY_SET, MaintDlqSupervisor
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m-drop-1",
        trace_id="t-drop-1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


_BASE_DROP_REQUEST = {
    "kind": "dlq_drop_request",
    "kind_schema_version": 1,
    "request_id": "drop-req-001",
    "target": "predict.vote.dlq",
    "produced_at": "2025-06-01T00:00:00Z",
    "dlq_entry_id": "entry-abc123",
    "original_request_id": "orig-req-001",
    "original_envelope_summary": {
        "topic": "predict.vote",
        "producer": "pred.elo.v1",
        "attempt": 4,
        "last_error": "schema validation failed: field 'match_id' missing",
    },
    "drop_reason": "poison entry — schema will never satisfy validation",
    "dropped_by": "sha256:cafebabe",
}


def test_drop_request_emits_dlq_dropped_with_forensic_fields() -> None:
    """Happy path: dlq_drop_request → ack(accepted=True) + dlq_dropped
    with operator_drop reason and all forensic fields forwarded."""
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap(_BASE_DROP_REQUEST)))

    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks, "must emit an ack on MAINT_ACK topic"
    ack = acks[0].payload
    assert ack["accepted"] is True, f"expected accepted=True, got {ack}"
    assert ack.get("reason") == "dropped"

    notifications = [m for m in out if m.envelope.topic != MAINT_ACK]
    dropped_msgs = [m for m in notifications if m.payload.get("kind") == "dlq_dropped"]
    assert dropped_msgs, "must emit a dlq_dropped notification"
    dropped = dropped_msgs[0].payload

    # Core forensic fields
    assert dropped["reason"] == "operator_drop", (
        f"expected reason=operator_drop, got {dropped.get('reason')!r}"
    )
    assert dropped["dlq_entry_id"] == "entry-abc123"
    assert dropped["original_request_id"] == "orig-req-001"
    assert dropped["dropped_by"] == "sha256:cafebabe"
    assert dropped["drop_reason"] == "poison entry — schema will never satisfy validation"

    # topic is derived from target.removesuffix(".dlq")
    assert dropped["topic"] == "predict.vote", (
        f"expected topic='predict.vote' derived from target, got {dropped.get('topic')!r}"
    )

    # original_envelope_summary is forwarded verbatim
    oes = dropped.get("original_envelope_summary", {})
    assert oes.get("producer") == "pred.elo.v1"
    assert oes.get("attempt") == 4
    assert oes.get("last_error") == "schema validation failed: field 'match_id' missing"


def test_drop_request_target_field_in_notification() -> None:
    """dlq_dropped notification must carry target=<original dlq topic>."""
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap(_BASE_DROP_REQUEST)))
    dropped_msgs = [m for m in out if m.payload.get("kind") == "dlq_dropped"]
    assert dropped_msgs
    dropped = dropped_msgs[0].payload
    assert dropped.get("target") == "predict.vote.dlq", (
        f"dlq_dropped target should be the DLQ topic, got {dropped.get('target')!r}"
    )


def test_drop_request_non_leader_emits_leader_skip_ack() -> None:
    """Non-leader acks with accepted=True, reason=leader_skip (hot-spares
    pattern: ops console receives a complete ack set from all replicas)
    and must NOT emit a dlq_dropped notification."""
    leader = SingleProcessLeader(name="maint.dlq.v1")
    leader.shed()  # relinquish leadership
    agent = MaintDlqSupervisor(leader=leader)
    out = list(agent.handle(_wrap(_BASE_DROP_REQUEST)))

    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks, "non-leader must still ack"
    ack = acks[0].payload
    # Non-leader acks with accepted=True + reason=leader_skip so the
    # ops console gets a complete ack set even with hot spares.
    assert ack["accepted"] is True
    assert ack.get("reason") == "leader_skip"

    # Must NOT have emitted dlq_dropped
    dropped = [m for m in out if m.payload.get("kind") == "dlq_dropped"]
    assert not dropped, "non-leader must not emit dlq_dropped"


def test_drop_request_recursion_deny_emits_ack_rejected() -> None:
    """A dlq_drop_request targeting a recursion-deny target must ack with
    accepted=False, reason=recursion_deny and must NOT emit dlq_dropped."""
    deny_target = next(iter(RECURSION_DENY_SET))
    payload = {**_BASE_DROP_REQUEST, "target": deny_target, "request_id": "drop-req-deny"}
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap(payload)))

    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks, "must ack even for recursion-deny"
    ack = acks[0].payload
    assert ack["accepted"] is False, f"expected accepted=False, got {ack}"
    assert ack.get("reason") == "recursion_deny"

    dropped = [m for m in out if m.payload.get("kind") == "dlq_dropped"]
    assert not dropped, "recursion-deny target must not emit dlq_dropped"


def test_drop_request_without_dlq_suffix_derives_topic_as_self() -> None:
    """If operator targets a non-suffixed topic (unusual but valid),
    topic in dlq_dropped is the full target string."""
    payload = {**_BASE_DROP_REQUEST,
               "target": "predict.vote",
               "request_id": "drop-req-nosuffix"}
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap(payload)))
    dropped_msgs = [m for m in out if m.payload.get("kind") == "dlq_dropped"]
    assert dropped_msgs
    dropped = dropped_msgs[0].payload
    # removesuffix(".dlq") on "predict.vote" → "predict.vote" unchanged
    assert dropped["topic"] == "predict.vote"
