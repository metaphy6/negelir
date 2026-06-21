"""Phase 8 §8.9 DoD — DLQ replay-rate boundary tests.

Covers:
* Per-topic per-second rate cap (cfg.maint_dlq_replay_rps) enforced
  on the operator-driven handle() path.
* auto-replay (tick()) excludes sec.quarantine.v1.dlq,
  sec.alert.v1.dlq, and qa.request.v1.dlq from scheduling.
* opsctl dlq-replay classify: qa.request.v1.dlq (and any qa.* topic)
  without --confirm-pii yields Action.REFUSE.
"""
from __future__ import annotations

from datetime import datetime, timezone

from swarm.agents.maint.dlq import RECURSION_DENY_SET, MaintDlqSupervisor
from swarm.agents.topics import MAINT_ACK, MAINT_EVENT
from swarm.sdk.types import Envelope, Message


# ─────────────────────────── helpers ─────────────────────────────────

def _wrap(payload: dict) -> Message:
    env = Envelope(
        message_id=payload.get("request_id", "m-rps"),
        trace_id="t-rps",
        topic=MAINT_EVENT,
        producer="ops_console",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        schema_version=1,
        attempt=1,
    )
    return Message(envelope=env, payload=payload)


def _replay_payload(target: str, rid: str) -> dict:
    return {
        "kind": "dlq_replay",
        "request_id": rid,
        "client_id": "ops",
        "target": target,
        "produced_at": "2026-01-01T00:00:00+00:00",
        "reason": "rps-test",
    }


# ─────────────────── 1. Per-second RPS cap (handle path) ─────────────

def test_rps_cap_enforced_within_one_second(monkeypatch) -> None:
    """After cfg.maint_dlq_replay_rps handle() calls in the same
    second epoch, the next attempt is rate-limited with reason
    rate_limited and an ack of accepted=False."""
    from common.config import cfg

    fixed_clock = [1_700_000_000.0]
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 2, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 1_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 100, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)

    agent = MaintDlqSupervisor(clock_s=lambda: fixed_clock[0])

    out1 = list(agent.handle(_wrap(_replay_payload("predict.final.dlq", "rps-1"))))
    out2 = list(agent.handle(_wrap(_replay_payload("predict.final.dlq", "rps-2"))))
    assert any(m.payload.get("kind") == "dlq_replayed" for m in out1)
    assert any(m.payload.get("kind") == "dlq_replayed" for m in out2)

    out3 = list(agent.handle(_wrap(_replay_payload("predict.final.dlq", "rps-3"))))
    drops = [m.payload for m in out3 if m.payload.get("kind") == "dlq_dropped"]
    acks = [m.payload for m in out3 if m.envelope.topic == MAINT_ACK]
    assert drops and drops[0]["reason"] == "rate_limited", (
        f"expected rate_limited drop, got: {[m.payload for m in out3]}"
    )
    assert acks and acks[0]["accepted"] is False
    assert acks[0]["reason"] == "rate_limited"


def test_rps_cap_resets_on_new_second(monkeypatch) -> None:
    """Advancing the clock to a new second resets the token bucket."""
    from common.config import cfg

    clock = [1_700_000_000.0]
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 1_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 100, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)

    agent = MaintDlqSupervisor(clock_s=lambda: clock[0])

    list(agent.handle(_wrap(_replay_payload("predict.vote.dlq", "rps-sec1"))))

    clock[0] = 1_700_000_001.0
    out = list(agent.handle(_wrap(_replay_payload("predict.vote.dlq", "rps-sec2"))))
    assert any(m.payload.get("kind") == "dlq_replayed" for m in out), (
        "expected dlq_replayed after second-epoch reset"
    )


def test_rps_cap_is_per_topic_independent(monkeypatch) -> None:
    """RPS cap applies independently per topic."""
    from common.config import cfg

    fixed_clock = [1_700_000_000.0]
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 1, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 1_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backoff_lru", 0, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_visit_max", 100, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)

    agent = MaintDlqSupervisor(clock_s=lambda: fixed_clock[0])

    list(agent.handle(_wrap(_replay_payload("predict.final.dlq", "rps-a1"))))
    out_a2 = list(agent.handle(_wrap(_replay_payload("predict.final.dlq", "rps-a2"))))
    assert any(m.payload.get("kind") == "dlq_dropped" for m in out_a2), "A should be capped"

    out_b = list(agent.handle(_wrap(_replay_payload("predict.vote.dlq", "rps-b1"))))
    assert any(m.payload.get("kind") == "dlq_replayed" for m in out_b), (
        "B should not be affected by A cap"
    )


# ─────── 2. Auto-replay (tick) excludes PII DLQs ─────────────────────

_PII_DLQS = [
    "sec.quarantine.v1.dlq",
    "sec.alert.v1.dlq",
    "qa.request.v1.dlq",
]


def test_pii_dlqs_in_recursion_deny_set() -> None:
    """The three PII-bearing DLQs are in RECURSION_DENY_SET."""
    for topic in _PII_DLQS:
        assert topic in RECURSION_DENY_SET, f"{topic!r} must be in RECURSION_DENY_SET"


def test_tick_excludes_pii_dlqs_emits_disabled_notifications(monkeypatch) -> None:
    """tick() fed only PII DLQs must not emit any dlq_replayed."""
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    agent = MaintDlqSupervisor()

    out = agent.tick(list(_PII_DLQS))
    replayed = [m for m in out if m.payload.get("kind") == "dlq_replayed"]
    disabled = [m for m in out if m.payload.get("kind") == "dlq_topic_disabled_drained"]

    assert replayed == [], "no PII DLQ must ever be auto-replayed via tick()"
    disabled_targets = {m.payload["target"] for m in disabled}
    for topic in _PII_DLQS:
        assert topic in disabled_targets, (
            f"{topic!r} must appear as dlq_topic_disabled_drained"
        )


def test_tick_excludes_pii_dlqs_mixed_with_eligible(monkeypatch) -> None:
    """PII DLQs mixed with eligible topics — only eligible are replayed."""
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    agent = MaintDlqSupervisor()

    eligible = ["predict.final.dlq", "freshness.v1.dlq"]
    out = agent.tick(eligible + list(_PII_DLQS))

    replayed_targets = {
        m.payload["target"]
        for m in out if m.payload.get("kind") == "dlq_replayed"
    }
    assert replayed_targets == set(eligible), (
        f"only eligible topics should be replayed; got {replayed_targets}"
    )
    for topic in _PII_DLQS:
        assert topic not in replayed_targets, f"{topic!r} must not appear in replayed set"


# ─────── 3. opsctl classifier: qa.* requires --confirm-pii ───────────

def test_opsctl_classify_qa_dlq_refuses_without_confirm_pii() -> None:
    """dlq-replay targeting qa.* without --confirm-pii must be REFUSE."""
    from xops.opsctl._classify import Action, ClassifyRequest, classify

    req = ClassifyRequest(
        subcommand="dlq-replay",
        flags=frozenset({"topic_sec"}),
    )
    assert classify(req) == Action.REFUSE


def test_opsctl_classify_qa_dlq_admits_with_confirm_pii() -> None:
    """dlq-replay targeting qa.* WITH --confirm-pii must not be REFUSE."""
    from xops.opsctl._classify import Action, ClassifyRequest, classify

    req = ClassifyRequest(
        subcommand="dlq-replay",
        flags=frozenset({"topic_sec", "confirm_pii"}),
    )
    assert classify(req) != Action.REFUSE


def test_opsctl_dlq_replay_qa_topic_sets_topic_sec_flag() -> None:
    """dlq_replay._topic_is_pii() returns True for qa.request.v1.dlq."""
    from xops.opsctl.subcommands.dlq_replay import _topic_is_pii

    assert _topic_is_pii("qa.request.v1.dlq") is True, (
        "qa.* must be in _DENY_PREFIXES so --confirm-pii is required"
    )
    assert _topic_is_pii("sec.alert.v1.dlq") is True
    assert _topic_is_pii("predict.final.dlq") is False
