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
    monkeypatch.setattr(cfg, "maint_dlq_consumer_broken_threshold", 3, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_consumer_broken_window_s", 600, raising=False)
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
    monkeypatch.setattr(cfg, "maint_dlq_consumer_broken_threshold", 3, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_consumer_broken_window_s", 10, raising=False)
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


# ── Phase 8 §8.5 — Backlog-pressure damping ─────────────────────────

def test_backlog_damping_emits_alert_and_quarters_budget(monkeypatch) -> None:
    """Per ROADMAP §8.5: depth > cfg.maint_dlq_backlog_alert ⇒
    debounced sec.alert.v1{kind=dlq_backlog_high, severity=warn} +
    per-topic replay budget quartered until depth halves."""
    from common.config import cfg
    from swarm.agents.topics import SEC_ALERT
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 40, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backlog_alert", 100, raising=False)
    agent = MaintDlqSupervisor()
    out = agent.tick(
        ["predict.final.dlq", "predict.vote.dlq"],
        depths={"predict.final.dlq": 500, "predict.vote.dlq": 50},
    )
    # One sec.alert.v1 for the over-threshold topic.
    alerts = [m for m in out if m.envelope.topic == SEC_ALERT]
    assert len(alerts) == 1
    assert alerts[0].payload["kind"] == "dlq_backlog_high"
    assert alerts[0].payload["severity"] == "warn"
    assert alerts[0].payload["subject"] == "predict.final.dlq"
    # Mirror notification on maint.event.v1.
    backlog_notifs = [m for m in out
                      if m.envelope.topic == MAINT_EVENT
                      and m.payload.get("kind") == "dlq_backlog_high"]
    assert len(backlog_notifs) == 1
    # Budgets: damped topic gets per_topic // 4, healthy gets per_topic.
    replayed = {m.payload["target"]: m.payload
                for m in out if m.payload.get("kind") == "dlq_replayed"}
    # per_topic = 40 // 2 = 20
    assert replayed["predict.vote.dlq"]["budget_per_topic"] == 20
    assert replayed["predict.vote.dlq"].get("backlog_damped") is not True
    assert replayed["predict.final.dlq"]["budget_per_topic"] == 5  # 20 // 4
    assert replayed["predict.final.dlq"]["backlog_damped"] is True


def test_backlog_damping_debounces_repeat_alerts(monkeypatch) -> None:
    """Sustained backlog must not re-page on every tick — repeat
    alerts respect cfg.maint_dlq_replay_backoff_s."""
    from common.config import cfg
    from swarm.agents.topics import SEC_ALERT
    monkeypatch.setattr(cfg, "maint_dlq_backlog_alert", 100, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_backoff_s", 60, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    clock = {"s": 1_700_000_000.0}
    agent = MaintDlqSupervisor(clock_s=lambda: clock["s"])
    # First tick: alert fires.
    out1 = agent.tick(["t.dlq"], depths={"t.dlq": 500})
    assert sum(1 for m in out1 if m.envelope.topic == SEC_ALERT) == 1
    # Second tick 10s later: still over threshold, no re-alert.
    clock["s"] += 10
    out2 = agent.tick(["t.dlq"], depths={"t.dlq": 600})
    assert sum(1 for m in out2 if m.envelope.topic == SEC_ALERT) == 0
    # Third tick after debounce window: re-alert fires.
    clock["s"] += 60
    out3 = agent.tick(["t.dlq"], depths={"t.dlq": 700})
    assert sum(1 for m in out3 if m.envelope.topic == SEC_ALERT) == 1


def test_backlog_damping_clears_when_depth_halves(monkeypatch) -> None:
    """Once depth ≤ trip_depth // 2 AND back below the alert
    threshold, damping clears and the topic resumes its normal
    per-tick budget. ROADMAP §8.5: 'until depth halves' is the
    recovery floor; if depth is still above the alert threshold
    after halving, the topic re-trips with a fresh trip_depth."""
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 40, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backlog_alert", 100, raising=False)
    agent = MaintDlqSupervisor()
    # Trip damping at depth=500.
    agent.tick(["t.dlq"], depths={"t.dlq": 500})
    assert "t.dlq" in agent._backlog_damped  # noqa: SLF001
    # Depth above half (500//2 = 250) AND above threshold: stays damped.
    agent.tick(["t.dlq"], depths={"t.dlq": 300})
    assert "t.dlq" in agent._backlog_damped
    # Depth drops below the alert threshold AND below half-trip:
    # damping clears, no fresh alert.
    out = agent.tick(["t.dlq"], depths={"t.dlq": 50})
    assert "t.dlq" not in agent._backlog_damped
    replayed = [m for m in out if m.payload.get("kind") == "dlq_replayed"]
    assert replayed[0].payload["budget_per_topic"] == 40
    assert replayed[0].payload.get("backlog_damped") is not True


def test_backlog_damping_skips_recursion_deny() -> None:
    """Topics in RECURSION_DENY_SET must never be considered for
    backlog damping (they are never replayed at all)."""
    agent = MaintDlqSupervisor()
    out = agent.tick(
        ["predict.final.dlq"],
        depths={"maint.event.v1.dlq": 99999, "predict.final.dlq": 5},
    )
    assert "maint.event.v1.dlq" not in agent._backlog_damped  # noqa: SLF001


def test_tick_omitting_depths_preserves_v1_behaviour(monkeypatch) -> None:
    """Backwards-compat: callers that do not pass ``depths=`` keep
    the v1 fairness scheduler unchanged (no alerts, no damping)."""
    from common.config import cfg
    from swarm.agents.topics import SEC_ALERT
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 30, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    agent = MaintDlqSupervisor()
    out = agent.tick(["a.dlq", "b.dlq"])
    assert all(m.envelope.topic != SEC_ALERT for m in out)
    assert agent._backlog_damped == {}  # noqa: SLF001


# ── §8.9 DoD — idempotency / single-publication ──────────────────


def test_dlq_replay_redelivery_no_second_downstream_emission() -> None:
    """Negative test (§8.9 DoD idempotency bullet for maint.dlq.v1):

    Replaying an already-accepted DLQ entry a second time (simulating
    at-least-once bus redelivery) must NOT produce a second
    ``dlq_replayed`` notification on the ``predict.vote → predict.final``
    path.

    Concretely:
    - First delivery (attempt=1): accepted, one ``dlq_replayed`` emitted.
    - Second delivery (attempt=2, same ``request_id``): backoff-dedup
      gate fires, ack returned with ``accepted=False, reason=backoff_dedup``,
      zero ``dlq_replayed`` emitted — the downstream path is NOT triggered
      a second time.
    """
    agent = MaintDlqSupervisor()

    def _make_msg(attempt: int) -> Message:
        env = Envelope(
            message_id="m-idempotency-dlq",
            trace_id="t-idempotency",
            topic=MAINT_EVENT,
            producer="ops_console",
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            schema_version=1,
            attempt=attempt,
        )
        return Message(
            envelope=env,
            payload={
                "kind": "dlq_replay",
                # Same request_id on both deliveries — identical logical op.
                "request_id": "req-idempotency-001",
                "client_id": "ops",
                # The predict.vote → predict.final downstream path.
                "target": "predict.vote.dlq",
                "max_msgs": 5,
                "produced_at": "2024-01-01T00:00:00+00:00",
                "reason": "manual_replay",
            },
        )

    # First delivery — must be accepted with one dlq_replayed.
    out1 = list(agent.handle(_make_msg(attempt=1)))
    replayed1 = [m for m in out1 if m.payload.get("kind") == "dlq_replayed"]
    acks1 = [m.payload for m in out1 if m.envelope.topic == MAINT_ACK]
    assert len(replayed1) == 1, "first delivery must emit exactly one dlq_replayed"
    assert acks1 and acks1[0]["accepted"] is True

    # Second delivery (bus redelivery, same request_id, attempt=2).
    # Must NOT emit a second dlq_replayed — the downstream path must
    # not be triggered again.
    out2 = list(agent.handle(_make_msg(attempt=2)))
    replayed2 = [m for m in out2 if m.payload.get("kind") == "dlq_replayed"]
    acks2 = [m.payload for m in out2 if m.envelope.topic == MAINT_ACK]
    assert replayed2 == [], (
        "second delivery (redelivery) must not produce a second dlq_replayed "
        "— downstream predict.vote path must not be triggered twice"
    )
    assert acks2 and acks2[0]["accepted"] is False
    assert acks2[0]["reason"] == "backoff_dedup"


# ── Phase 8 §8.9 DoD — _state LRU cap + cap-pressure alert ───────


def test_state_map_lru_evicts_oldest_topic(monkeypatch) -> None:
    """``_state`` must not grow beyond ``maint_dlq_state_max``.

    With cap=3, inserting a 4th distinct topic evicts the oldest one
    (insertion-order LRU). The 4th topic becomes the most-recent
    entry; the first topic is gone.
    """
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_dlq_state_max", 3, raising=False)
    # Disable backoff LRU so each distinct request_id is accepted.
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)

    agent = MaintDlqSupervisor()
    topics = [f"t{i}.dlq" for i in range(4)]
    for i, t in enumerate(topics):
        list(agent.handle(_wrap({
            "kind": "dlq_replay",
            "request_id": f"req-cap-{i}",
            "client_id": "ops",
            "target": t,
            "produced_at": "2024-01-01T00:00:00+00:00",
            "reason": "x",
        })))

    assert len(agent._state) == 3, "_state must be capped at 3"
    assert "t0.dlq" not in agent._state, "oldest topic must have been evicted"
    assert "t3.dlq" in agent._state, "newest topic must still be present"


def test_state_map_cap_pressure_alert_fires_when_fill_rate_high(monkeypatch) -> None:
    """Cap-pressure ``sec.alert.v1{kind=dlq_state_pressure}`` fires
    when the evicted entry is younger than
    ``backoff_s × backoff_factor × 3``.

    Proof: cap=2, backoff_s=300, backoff_factor=2 → pressure window=1800s.
    All inserts happen at the same simulated timestamp (all entries are
    0 seconds old), so the eviction guard must fire on the 3rd insert.
    """
    from common.config import cfg
    from swarm.agents.topics import SEC_ALERT

    monkeypatch.setattr(cfg, "maint_dlq_state_max", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_backoff_s", 300, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_factor", 2, raising=False)

    fixed_time = 5000.0
    agent = MaintDlqSupervisor(clock_s=lambda: fixed_time)

    pressure_alerts: list = []
    for i in range(3):
        out = list(agent.handle(_wrap({
            "kind": "dlq_replay",
            "request_id": f"req-pressure-{i}",
            "client_id": "ops",
            "target": f"p{i}.dlq",
            "produced_at": "2024-01-01T00:00:00+00:00",
            "reason": "x",
        })))
        pressure_alerts.extend(
            m for m in out
            if m.envelope.topic == SEC_ALERT
            and m.payload.get("kind") == "dlq_state_pressure"
        )

    assert pressure_alerts, (
        "at least one dlq_state_pressure alert must fire when the map "
        "fills faster than the backoff window clears entries"
    )
    assert pressure_alerts[0].payload["severity"] == "warn"


def test_state_map_no_pressure_alert_when_entries_are_old(monkeypatch) -> None:
    """No cap-pressure alert when the evicted entry is OLDER than the
    pressure window (fill rate is within normal backoff cadence).

    Proof: cap=2, backoff_s=10, factor=2 → window=60s.
    Insert t0 at time=0, then insert t1 at time=0 (at cap). Then insert t2
    at time=1000 (well past the 60s window). The eviction of t0 at
    time=1000 sees t0.last_run_at=0 → age=1000s > 60s → no alert.
    """
    from common.config import cfg
    from swarm.agents.topics import SEC_ALERT

    monkeypatch.setattr(cfg, "maint_dlq_state_max", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_backoff_s", 10, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_factor", 2, raising=False)

    clock = [0.0]
    agent = MaintDlqSupervisor(clock_s=lambda: clock[0])

    # Insert t0 and t1 at time 0 (fills cap exactly).
    for i in range(2):
        list(agent.handle(_wrap({
            "kind": "dlq_replay",
            "request_id": f"req-old-{i}",
            "client_id": "ops",
            "target": f"old{i}.dlq",
            "produced_at": "2024-01-01T00:00:00+00:00",
            "reason": "x",
        })))

    # Advance clock well past the pressure window (60s).
    clock[0] = 1000.0

    # Insert t2 — evicts t0 (oldest). t0.last_run_at=0 → age=1000s > 60s.
    out = list(agent.handle(_wrap({
        "kind": "dlq_replay",
        "request_id": "req-old-2",
        "client_id": "ops",
        "target": "old2.dlq",
        "produced_at": "2024-01-01T00:00:00+00:00",
        "reason": "x",
    })))

    pressure = [
        m for m in out
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "dlq_state_pressure"
    ]
    assert pressure == [], (
        "no dlq_state_pressure alert must fire when evicted entry is older "
        "than the backoff pressure window"
    )


# ── Phase 8 §8.9 DoD — loop-budget / heartbeat timing ───────────────


def test_tick_loop_budget_10k_backlog_yields_within_heartbeat(
    monkeypatch,
) -> None:
    """DLQ read loop yields back to heartbeat within ``swarm_heartbeat_sec``
    even with 10k backlog entries (§8.9 DoD loop-budget test).

    The ``tick()`` method must complete in < ``cfg.swarm_heartbeat_sec``
    so the bootstrap loop can fire a heartbeat between ticks. This proves
    the round-robin fair-share scheduler does not hold the event loop
    hostage on a large backlog.

    Asserts:
    * elapsed wall-clock < swarm_heartbeat_sec (no missed heartbeat).
    * Exactly 10k ``dlq_replayed`` notifications emitted (every topic
      gets a fair-share slice — none silently dropped by the scheduler).
    """
    import time

    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    # Set max_replays_per_tick high enough to cover all 10k topics so
    # per-topic budget is at least 1 (per_topic = max(1, 10000 // 10000) = 1).
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", 10_000, raising=False)

    # 10k distinct DLQ topic names — none in RECURSION_DENY_SET, no
    # prior rate-bucket state, so all are eligible.
    active_topics = [f"predict.event.{i}.dlq" for i in range(10_000)]

    agent = MaintDlqSupervisor()

    start = time.monotonic()
    out = agent.tick(active_topics)
    elapsed = time.monotonic() - start

    heartbeat_budget_s = max(1, int(cfg.swarm_heartbeat_sec))
    assert elapsed < heartbeat_budget_s, (
        f"tick() with 10k topics took {elapsed:.3f}s "
        f"(budget: {heartbeat_budget_s}s = swarm_heartbeat_sec); "
        "DLQ loop must yield within one heartbeat period"
    )

    replayed = [m for m in out if m.payload.get("kind") == "dlq_replayed"]
    assert len(replayed) == 10_000, (
        f"expected 10k dlq_replayed notifications, got {len(replayed)}"
    )
