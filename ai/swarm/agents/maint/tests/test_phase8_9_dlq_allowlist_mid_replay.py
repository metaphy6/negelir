"""Phase 8 §8.9 DoD — DLQ allow-list mid-replay proof tests.

Bullet:
  Operator removes predict.vote from maint_dlq_replay_topics_allow
  while 50 entries are in flight from the current tick; assert in-flight
  50 complete normally, no new entries pulled in subsequent ticks,
  kind=dlq_topic_disabled_drained fires once with in_flight_count=50.

Three proofs:
1. test_in_flight_complete_normally -- tick 1 (allow-list includes the
   topic) emits dlq_replayed with max_msgs=50 for predict.vote.dlq.
2. test_disabled_notification_fires_once -- removing the topic from the
   allow-list and running a second tick emits exactly one
   dlq_topic_disabled_drained carrying in_flight_count=50.
3. test_no_new_entries_on_subsequent_ticks -- ticks 2 and 3 (both with
   the topic still presented as active but excluded) emit zero
   dlq_replayed for predict.vote.dlq.
"""
from __future__ import annotations

from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.sdk.types import Message

PREDICT_DLQ = "predict.vote.dlq"
OTHER_DLQ = "freshness.v1.dlq"
BUDGET = 50


def _setup_cfg(monkeypatch, *, allow_csv: str) -> None:
    from common.config import cfg
    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", BUDGET, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 10_000_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 10_000_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_backlog_alert", 999_999_999, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_state_max", 10_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", allow_csv, raising=False)


def _replayed_topics(msgs: list) -> list:
    return [
        str(m.payload["target"])
        for m in msgs
        if m.payload.get("kind") == "dlq_replayed"
    ]


def _disabled_drained_with_inflight(msgs: list) -> list:
    return [
        m.payload
        for m in msgs
        if m.payload.get("kind") == "dlq_topic_disabled_drained"
        and "in_flight_count" in (m.payload or {})
    ]


def test_in_flight_complete_normally(monkeypatch) -> None:
    _setup_cfg(monkeypatch, allow_csv=f"{PREDICT_DLQ},{OTHER_DLQ}")
    sup = MaintDlqSupervisor()
    msgs = sup.tick([PREDICT_DLQ])
    replayed = [m.payload for m in msgs if m.payload.get("kind") == "dlq_replayed"]
    assert any(
        p.get("target") == PREDICT_DLQ and int(p.get("max_msgs", 0)) == BUDGET
        for p in replayed
    ), f"Expected dlq_replayed max_msgs={BUDGET} for {PREDICT_DLQ}; got {replayed}"


def test_disabled_notification_fires_once(monkeypatch) -> None:
    from common.config import cfg
    _setup_cfg(monkeypatch, allow_csv=f"{PREDICT_DLQ},{OTHER_DLQ}")
    sup = MaintDlqSupervisor()
    sup.tick([PREDICT_DLQ])
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", OTHER_DLQ, raising=False)
    msgs2 = sup.tick([PREDICT_DLQ])
    drained2 = _disabled_drained_with_inflight(msgs2)
    assert len(drained2) == 1, f"Expected 1 disabled notification; got {drained2}"
    assert drained2[0]["target"] == PREDICT_DLQ
    assert drained2[0]["in_flight_count"] == BUDGET
    msgs3 = sup.tick([PREDICT_DLQ])
    drained3 = _disabled_drained_with_inflight(msgs3)
    assert drained3 == [], f"Expected no repeat; got {drained3}"


def test_no_new_entries_on_subsequent_ticks(monkeypatch) -> None:
    from common.config import cfg
    _setup_cfg(monkeypatch, allow_csv=f"{PREDICT_DLQ},{OTHER_DLQ}")
    sup = MaintDlqSupervisor()
    sup.tick([PREDICT_DLQ])
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", OTHER_DLQ, raising=False)
    for tick_n in (2, 3):
        msgs = sup.tick([PREDICT_DLQ])
        assert PREDICT_DLQ not in _replayed_topics(msgs), (
            f"Tick {tick_n}: unexpected dlq_replayed for {PREDICT_DLQ}"
        )
