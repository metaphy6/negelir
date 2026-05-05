"""Phase 8 §8.5 — `maint.dlq.v1` smoke tests."""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.dlq import RECURSION_DENY_SET, MaintDlqSupervisor
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.leader import SingleProcessLeader
from swarm.sdk.types import Envelope, Message


def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id="m1",
        trace_id="t1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_subscribes_publishes() -> None:
    a = MaintDlqSupervisor()
    assert a.name == "maint.dlq.v1"
    assert MAINT_EVENT in a.subscribes


def test_replay_emits_notification_and_ack() -> None:
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-001",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "max_msgs": 10,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


def test_recursion_deny_for_maint_event_dlq() -> None:
    """The supervisor must not loop on its own DLQ."""
    agent = MaintDlqSupervisor()
    target = next(iter(RECURSION_DENY_SET))
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-002",
        "client_id": "ops",
        "target": target,
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" not in kinds
    # Must produce ack rejecting and a topic_disabled notification.
    acks = [m for m in out if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload["accepted"] is False


def test_dedup_blocks_repeat_request() -> None:
    agent = MaintDlqSupervisor()
    msg = _wrap({
        "kind": "dlq_replay",
        "request_id": "req-003",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })
    list(agent.handle(msg))  # first call accepted
    out2 = list(agent.handle(msg))  # second call dedup-rejected
    acks = [m for m in out2 if m.envelope.topic == MAINT_ACK]
    assert acks and acks[0].payload["accepted"] is False


def test_non_leader_acks_skip() -> None:
    leader = SingleProcessLeader(name="maint.dlq.v1")
    leader.shed()
    agent = MaintDlqSupervisor(leader=leader)
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-004",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" not in kinds
    assert any(m.envelope.topic == MAINT_ACK for m in out)


# ── Phase 8.5 gap-fill: allow-list, visit escalation, rate-limit ──

def test_extended_recursion_deny_includes_sec_quarantine_and_qa_request() -> None:
    """Per Phase 8.5 the recursion-deny set must include the quarantine
    and qa.request DLQs as well as the maint plane's own DLQs."""
    assert "sec.quarantine.v1.dlq" in RECURSION_DENY_SET
    assert "qa.request.v1.dlq" in RECURSION_DENY_SET
    assert "maint.event.v1.dlq" in RECURSION_DENY_SET


def test_allow_list_excludes_unlisted_topic(monkeypatch) -> None:
    """When the allow-list is non-empty, topics not listed are denied
    even if they are not in the recursion-deny set."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv",
                        "predict.final.dlq", raising=False)
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-allow-1",
        "client_id": "ops",
        "target": "scrape.raw.v1.dlq",  # not in allow-list
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    acks = [m.payload for m in out if m.envelope.topic == MAINT_ACK]
    notifs = [m.payload for m in out if m.payload.get("kind") == "dlq_topic_disabled_drained"]
    assert acks and acks[0]["accepted"] is False
    assert acks[0]["reason"] == "allow_list_excluded"
    assert notifs and notifs[0]["deny_reason"] == "allow_list_excluded"


def test_allow_list_admits_listed_topic(monkeypatch) -> None:
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv",
                        "predict.final.dlq", raising=False)
    agent = MaintDlqSupervisor()
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-allow-2",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))
    kinds = [m.payload.get("kind") for m in out]
    assert "dlq_replayed" in kinds


def test_visit_count_third_visit_escalates(monkeypatch) -> None:
    """After ``maint_dlq_visit_max`` successful replays for the same
    (topic, request_id), the next attempt must escalate."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    agent = MaintDlqSupervisor()
    payload = {
        "kind": "dlq_replay",
        "request_id": "req-visit-1",
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    }
    list(agent.handle(_wrap(payload)))  # visit 1
    list(agent.handle(_wrap(payload)))  # visit 2
    out3 = list(agent.handle(_wrap(payload)))  # visit 3 — escalate
    kinds = [m.payload.get("kind") for m in out3]
    acks = [m.payload for m in out3 if m.envelope.topic == MAINT_ACK]
    assert "dlq_escalated" in kinds
    assert acks and acks[0]["accepted"] is False
    assert acks[0]["reason"] == "dlq_escalated"


def test_per_topic_rate_limit_emits_dlq_dropped(monkeypatch) -> None:
    """Once ``maint_dlq_per_topic_max_per_min`` attempts in the same
    minute window are exceeded, further attempts must be dropped with
    a ``dlq_dropped{reason=rate_limited}`` notification."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 100, raising=False)
    agent = MaintDlqSupervisor(clock_s=lambda: 1700000000.0)
    p = lambda rid: {
        "kind": "dlq_replay",
        "request_id": rid,
        "client_id": "ops",
        "target": "predict.final.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    }
    out1 = list(agent.handle(_wrap(p("rl-1"))))  # admitted
    out2 = list(agent.handle(_wrap(p("rl-2"))))  # rate-limited
    assert any(m.payload.get("kind") == "dlq_replayed" for m in out1)
    dropped = [m.payload for m in out2 if m.payload.get("kind") == "dlq_dropped"]
    acks = [m.payload for m in out2 if m.envelope.topic == MAINT_ACK]
    assert dropped and dropped[0]["reason"] == "rate_limited"
    assert acks and acks[0]["accepted"] is False and acks[0]["reason"] == "rate_limited"
