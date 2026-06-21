"""Phase 8 §8.9 deep-review — DLQ poison-pattern alert proof tests.

Bullet: Feed 5 distinct payloads on one topic that all escalate within
``consumer_broken_window_s``; assert ``consumer_likely_broken`` fires
exactly once (debounced) AND replays for that topic freeze;
``ops.dlq-resume --topic <t>`` clears the freeze.

Uses the same escalation-drive pattern as the existing §8.5 C2 smoke
tests: send each request twice (visit_max=1, 2nd visit triggers
dlq_escalated → _record_escalation → freeze edge-trigger on the Nth
distinct request).
"""
from __future__ import annotations

from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.agents.topics import MAINT_EVENT, SEC_ALERT
from swarm.sdk.types import Envelope, Message


def _make_replay_msg(target: str, request_id: str) -> Message:
    payload = {
        "kind": "dlq_replay",
        "target": target,
        "request_id": request_id,
        "client_id": "ops",
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


def _make_agent(monkeypatch, threshold: int = 5, window_s: int = 600):
    """Return a configured MaintDlqSupervisor with visit_max=1 and
    backoff/rate caps disabled so each escalation path is exercised
    cleanly."""
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(
        cfg, "maint_dlq_per_topic_max_per_min", 10_000, raising=False
    )
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 10_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 1, raising=False)
    monkeypatch.setattr(
        cfg, "maint_dlq_consumer_broken_threshold", threshold, raising=False
    )
    monkeypatch.setattr(
        cfg, "maint_dlq_consumer_broken_window_s", window_s, raising=False
    )
    return MaintDlqSupervisor()


def _escalate_n(agent: MaintDlqSupervisor, topic: str, n: int) -> list[Message]:
    """Send n distinct request-ids twice each, collecting all outputs.
    The first send replays (visit 1); the second escalates (visit 2 >
    visit_max=1) and triggers _record_escalation.
    """
    out: list[Message] = []
    for i in range(n):
        list(agent.handle(_make_replay_msg(topic, f"poison-req-{i}")))
        out.extend(agent.handle(_make_replay_msg(topic, f"poison-req-{i}")))
    return out


def test_consumer_likely_broken_fires_on_5_distinct_escalations(
    monkeypatch,
) -> None:
    """sec.alert.v1{kind=consumer_likely_broken, severity=error} MUST fire
    exactly once when 5 distinct request_ids escalate within the window."""
    agent = _make_agent(monkeypatch, threshold=5)
    all_out = _escalate_n(agent, "predict.vote.dlq", 5)

    # Exactly one sec.alert.v1 message with kind=consumer_likely_broken.
    broken_alerts = [
        m
        for m in all_out
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "consumer_likely_broken"
    ]
    assert len(broken_alerts) == 1, (
        f"expected exactly one consumer_likely_broken sec.alert, "
        f"got {len(broken_alerts)}"
    )
    alert = broken_alerts[0].payload
    assert alert["severity"] == "error"
    assert alert["subject"] == "predict.vote.dlq"


def test_consumer_likely_broken_fires_exactly_once_debounced(
    monkeypatch,
) -> None:
    """After the threshold is crossed, further escalations MUST NOT
    produce additional consumer_likely_broken alerts (edge-triggered,
    not level-triggered — the 'debounced' contract)."""
    agent = _make_agent(monkeypatch, threshold=5)
    # Trip the threshold.
    _escalate_n(agent, "predict.vote.dlq", 5)
    # Drive 5 more distinct escalations while topic is frozen.
    more_out = _escalate_n(agent, "predict.vote.dlq", 5)

    # Zero additional consumer_likely_broken alerts.
    second_alerts = [
        m
        for m in more_out
        if m.envelope.topic == SEC_ALERT
        and m.payload.get("kind") == "consumer_likely_broken"
    ]
    assert len(second_alerts) == 0, (
        "consumer_likely_broken must not re-fire after freeze (debounced)"
    )


def test_replays_freeze_after_consumer_likely_broken(monkeypatch) -> None:
    """After the poison-pattern fires, every subsequent dlq_replay
    request MUST be rejected with reason='topic_frozen'."""
    agent = _make_agent(monkeypatch, threshold=5)
    _escalate_n(agent, "predict.vote.dlq", 5)

    # Confirm topic is in the frozen set.
    assert "predict.vote.dlq" in agent._frozen_topics, (
        "topic must be in _frozen_topics after threshold crossed"
    )

    # A new replay attempt must be refused.
    out = list(agent.handle(_make_replay_msg("predict.vote.dlq", "new-req")))
    drops = [m for m in out if m.payload.get("kind") == "dlq_dropped"]
    assert len(drops) == 1
    assert drops[0].payload["reason"] == "topic_frozen"


def test_dlq_resume_clears_freeze(monkeypatch) -> None:
    """ops.dlq-resume --topic <t> (kind=dlq_unfreeze) MUST lift the
    freeze so that subsequent replays are accepted again."""
    agent = _make_agent(monkeypatch, threshold=5)
    _escalate_n(agent, "predict.vote.dlq", 5)
    assert "predict.vote.dlq" in agent._frozen_topics

    # Send dlq_unfreeze (the envelope that ops.dlq-resume publishes).
    env = Envelope(
        message_id="unfreeze-1",
        trace_id="unfreeze-1",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at="2025-01-01T00:00:00Z",
        schema_version=1,
        attempt=1,
    )
    unfreeze_payload = {
        "kind": "dlq_unfreeze",
        "target": "predict.vote.dlq",
        "request_id": "unfreeze-1",
        "client_id": "opsctl",
        "produced_at": "2025-01-01T00:00:00Z",
    }
    out = list(agent.handle(Message(envelope=env, payload=unfreeze_payload)))

    # Ack accepted, topic unfrozen notification present.
    acks = [m for m in out if m.envelope.topic == MAINT_EVENT
            and m.payload.get("kind") is None  # ack has no 'kind'
            or (m.envelope.topic is not None
                and m.payload.get("accepted") is True)]
    unfrozen_notifs = [
        m for m in out if m.payload.get("kind") == "dlq_topic_unfrozen"
    ]
    assert len(unfrozen_notifs) == 1
    assert unfrozen_notifs[0].payload["was_frozen"] is True

    # Topic removed from frozen set.
    assert "predict.vote.dlq" not in agent._frozen_topics

    # A fresh replay is now accepted.
    replay_out = list(
        agent.handle(_make_replay_msg("predict.vote.dlq", "post-resume-req"))
    )
    replayed = [m for m in replay_out if m.payload.get("kind") == "dlq_replayed"]
    assert len(replayed) == 1, (
        "after ops.dlq-resume, a new replay must succeed (not be topic_frozen)"
    )
