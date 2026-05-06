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


# ── Phase 8 §8.5 C1 — Round-robin topic fairness + per-tick budget ──

def test_tick_round_robin_emits_one_per_eligible_topic(monkeypatch) -> None:
    """``tick(active_topics)`` must emit one ``dlq_replayed`` per
    eligible topic with budget = max(1, total // n_topics)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 30, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    agent = MaintDlqSupervisor()
    out = agent.tick(["predict.final.dlq", "predict.vote.dlq", "qa.feedback.dlq"])
    replayed = [m for m in out if m.payload.get("kind") == "dlq_replayed"]
    assert len(replayed) == 3
    for m in replayed:
        assert m.payload["scheduler"] == "round_robin"
        assert m.payload["budget_per_topic"] == 10  # 30 // 3
        assert m.payload["active_topic_count"] == 3


def test_tick_skips_recursion_deny_topics() -> None:
    """Topics in RECURSION_DENY_SET must be filtered out and surfaced
    via ``dlq_topic_disabled_drained`` notifications."""
    agent = MaintDlqSupervisor()
    out = agent.tick(list(RECURSION_DENY_SET)[:2] + ["predict.final.dlq"])
    drained = [m for m in out if m.payload.get("kind") == "dlq_topic_disabled_drained"]
    replayed = [m for m in out if m.payload.get("kind") == "dlq_replayed"]
    assert len(drained) == 2
    assert len(replayed) == 1
    assert replayed[0].payload["target"] == "predict.final.dlq"


def test_tick_empty_active_topics_returns_empty() -> None:
    agent = MaintDlqSupervisor()
    assert agent.tick([]) == []


def test_tick_non_leader_returns_empty() -> None:
    leader = SingleProcessLeader(name="maint.dlq.v1")
    leader.shed()
    agent = MaintDlqSupervisor(leader=leader)
    assert agent.tick(["predict.final.dlq"]) == []


def test_tick_per_topic_budget_floor_one(monkeypatch) -> None:
    """When more topics than total budget, every eligible topic still
    gets a budget of at least 1 (the max(1, …) floor)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    agent = MaintDlqSupervisor()
    out = agent.tick([f"t{i}.dlq" for i in range(5)])
    replayed = [m for m in out if m.payload.get("kind") == "dlq_replayed"]
    assert len(replayed) == 5
    for m in replayed:
        assert m.payload["budget_per_topic"] >= 1


# ── Phase 8 §8.5 C2 — Poison-pattern detection + freeze ─────────────

def _make_replay_msg(target: str, request_id: str, client_id: str = "ops") -> Message:
    """Build a dlq_replay Message with a unique client_id so backoff
    dedup does not fire across requests in a single test."""
    payload = {
        "kind": "dlq_replay",
        "target": target,
        "request_id": request_id,
        "client_id": client_id,
        "produced_at": "2025-01-01T00:00:00Z",
    }
    env = Envelope(
        message_id=request_id,
        trace_id=request_id,
        topic=MAINT_EVENT,
        producer="ops",
        created_at="2025-01-01T00:00:00Z",
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def test_poison_pattern_freezes_topic_after_threshold(monkeypatch) -> None:
    """≥ N distinct request_ids escalating on the same topic within the
    window must freeze the topic and emit dlq_consumer_broken once.
    Drives the escalation path by sending each request twice (visit
    count exceeds visit_max=1 floor on the 2nd visit)."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 1000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_poison_distinct_threshold", 3, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_poison_window_s", 600, raising=False)
    agent = MaintDlqSupervisor()
    broken = []
    for i in range(3):
        # 1st visit replays, 2nd visit escalates → poison log entry
        list(agent.handle(_make_replay_msg("predict.vote.dlq", f"req-{i}")))
        out = list(agent.handle(_make_replay_msg("predict.vote.dlq", f"req-{i}")))
        broken.extend([m for m in out if m.payload.get("kind") == "dlq_consumer_broken"])
    assert len(broken) == 1, f"expected exactly one freeze event, got {len(broken)}"
    assert broken[0].payload["distinct_request_ids"] == 3
    assert "predict.vote.dlq" in agent._frozen_topics


def test_frozen_topic_refuses_further_replays(monkeypatch) -> None:
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 1000, raising=False)
    agent = MaintDlqSupervisor()
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    out = list(agent.handle(_make_replay_msg("predict.vote.dlq", "req-X")))
    drops = [m for m in out if m.payload.get("kind") == "dlq_dropped"]
    assert len(drops) == 1
    assert drops[0].payload["reason"] == "topic_frozen"


def test_dlq_unfreeze_lifts_freeze_and_is_idempotent() -> None:
    agent = MaintDlqSupervisor()
    agent._frozen_topics["predict.vote.dlq"] = "poison_pattern"
    payload1 = {"kind": "dlq_unfreeze", "target": "predict.vote.dlq",
                "request_id": "u1", "client_id": "ops",
                "produced_at": "2025-01-01T00:00:00Z"}
    env = Envelope(message_id="u1", trace_id="u1", topic=MAINT_EVENT,
                   producer="ops", created_at="2025-01-01T00:00:00Z",
                   schema_version=1, attempt=1)
    out1 = list(agent.handle(Message(envelope=env, payload=payload1)))
    notif1 = [m for m in out1 if m.payload.get("kind") == "dlq_topic_unfrozen"]
    assert notif1 and notif1[0].payload["was_frozen"] is True
    assert "predict.vote.dlq" not in agent._frozen_topics
    # Idempotent second call.
    payload2 = dict(payload1, request_id="u2")
    env2 = Envelope(message_id="u2", trace_id="u2", topic=MAINT_EVENT,
                    producer="ops", created_at="2025-01-01T00:00:00Z",
                    schema_version=1, attempt=1)
    out2 = list(agent.handle(Message(envelope=env2, payload=payload2)))
    notif2 = [m for m in out2 if m.payload.get("kind") == "dlq_topic_unfrozen"]
    assert notif2 and notif2[0].payload["was_frozen"] is False


def test_poison_window_expiry_resets_count(monkeypatch) -> None:
    """Escalations older than the window must be pruned so a slow
    burst below threshold does not eventually freeze the topic."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_poison_distinct_threshold", 3, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_poison_window_s", 10, raising=False)
    now = [1000.0]
    agent = MaintDlqSupervisor(clock_s=lambda: now[0])
    # First 2 escalations at t=0..1
    assert agent._record_escalation("t.dlq", "r1") is False
    now[0] += 1
    assert agent._record_escalation("t.dlq", "r2") is False
    # Advance past window before 3rd
    now[0] += 100
    assert agent._record_escalation("t.dlq", "r3") is False
    # Only r3 remains in window; threshold not crossed.
    assert "t.dlq" not in agent._frozen_topics
