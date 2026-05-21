"""Phase 8 §8.9 DoD — DLQ topic fairness proof tests.

Covers the bullet:
  "1000 entries on predict.vote.dlq + 5 on freshness.v1.dlq; small DLQ
  drains within ⌈ 5 / per_tick_share ⌉ ticks; ratio of replays per tick
  across topics is ≤ 1 + remainder."

Three proofs:
1. small_dlq_drains_within_expected_ticks — with total_budget=6 and
   2 eligible topics, per_tick_share=3, so freshness.v1.dlq (depth=5)
   accumulates enough scheduled budget in ceil(5/3)=2 ticks.
2. fairness_ratio_per_tick — with total_budget=7 and 2 topics, the
   difference between the per-topic budgets (max - min) is ≤ remainder
   (= total_budget % n_eligible = 1). In the current integer-division
   scheduler both topics receive the same budget so ratio excess = 0.
3. large_dlq_does_not_starve_small — over 10 ticks with depths
   {predict.vote.dlq: 1000, freshness.v1.dlq: 5}, both topics receive
   a non-zero per-tick budget every tick (round-robin guarantee).

All tests set maint_dlq_backlog_alert high enough to suppress backlog-
pressure damping, keeping the focus on the pure fairness scheduler.
"""
from __future__ import annotations

import math

from swarm.agents.maint.dlq import MaintDlqSupervisor
from swarm.sdk.types import Message

PREDICT_DLQ = "predict.vote.dlq"
FRESHNESS_DLQ = "freshness.v1.dlq"


def _agent(monkeypatch, *, total_budget: int) -> MaintDlqSupervisor:
    """Construct a MaintDlqSupervisor with all rate limiters relaxed so
    the fairness scheduler is the only variable under test."""
    from common.config import cfg

    monkeypatch.setattr(cfg, "maint_dlq_max_replays_per_tick", total_budget, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_per_topic_max_per_min", 10_000_000, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_rps", 10_000_000, raising=False)
    # Raise alert threshold above any depth used in these tests so
    # backlog-pressure damping never fires and alters the budget.
    monkeypatch.setattr(cfg, "maint_dlq_backlog_alert", 999_999_999, raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_replay_topics_allow_csv", "", raising=False)
    monkeypatch.setattr(cfg, "maint_dlq_state_max", 10_000, raising=False)
    return MaintDlqSupervisor()


def _scheduled_budget(msgs: list[Message]) -> dict[str, int]:
    """Extract {topic: budget_per_topic} from dlq_replayed notifications."""
    budgets: dict[str, int] = {}
    for m in msgs:
        p = m.payload or {}
        if p.get("kind") == "dlq_replayed":
            budgets[str(p.get("target", ""))] = int(
                p.get("budget_per_topic", p.get("max_msgs", 0))
            )
    return budgets


# ── 1. Small DLQ drains within the expected tick count ───────────────

def test_small_dlq_drains_within_expected_ticks(monkeypatch) -> None:
    """freshness.v1.dlq (depth=5) fully scheduled within
    ceil(5 / per_tick_share) ticks.

    Setup: total_budget=6, 2 topics ⟹ per_tick_share = max(1, 6//2) = 3.
    Expected drain = ceil(5 / 3) = 2 ticks.
    After those 2 ticks the cumulative scheduled budget (6) ≥ depth (5).
    """
    TOTAL_BUDGET = 6
    SMALL_DEPTH = 5
    LARGE_DEPTH = 1000

    agent = _agent(monkeypatch, total_budget=TOTAL_BUDGET)
    topics = [PREDICT_DLQ, FRESHNESS_DLQ]
    depths = {PREDICT_DLQ: LARGE_DEPTH, FRESHNESS_DLQ: SMALL_DEPTH}

    n_eligible = 2
    per_tick_share = max(1, TOTAL_BUDGET // n_eligible)
    expected_drain_ticks = math.ceil(SMALL_DEPTH / per_tick_share)

    cumulative = 0
    for _ in range(expected_drain_ticks):
        msgs = agent.tick(topics, depths=depths)
        budgets = _scheduled_budget(msgs)
        cumulative += budgets.get(FRESHNESS_DLQ, 0)

    assert cumulative >= SMALL_DEPTH, (
        f"After {expected_drain_ticks} tick(s) (ceil({SMALL_DEPTH}/{per_tick_share})) "
        f"cumulative scheduled budget {cumulative} < depth {SMALL_DEPTH}; "
        f"fair scheduler must allocate at least {per_tick_share} per tick"
    )


# ── 2. Fairness ratio per tick ≤ 1 + remainder ───────────────────────

def test_fairness_ratio_per_tick(monkeypatch) -> None:
    """Budget spread across topics in one tick is ≤ 1 + remainder.

    With total_budget=7 and 2 topics:
      per_topic = 7 // 2 = 3, remainder = 7 % 2 = 1.
    Both topics receive budget=3 (integer division is perfectly even),
    so max_budget - min_budget = 0 ≤ remainder = 1.
    """
    TOTAL_BUDGET = 7
    N_ELIGIBLE = 2

    agent = _agent(monkeypatch, total_budget=TOTAL_BUDGET)
    msgs = agent.tick([PREDICT_DLQ, FRESHNESS_DLQ])
    budgets = _scheduled_budget(msgs)

    assert len(budgets) == N_ELIGIBLE, (
        f"Expected budgets for both topics, got: {budgets}"
    )

    min_b = min(budgets.values())
    max_b = max(budgets.values())
    remainder = TOTAL_BUDGET % N_ELIGIBLE

    assert max_b - min_b <= remainder, (
        f"Fairness violated: max_budget={max_b}, min_budget={min_b}, "
        f"spread={max_b - min_b} > remainder={remainder}"
    )


# ── 3. Large DLQ does not starve the small one across multiple ticks ─

def test_large_dlq_does_not_starve_small(monkeypatch) -> None:
    """Round-robin guarantee: both topics receive a non-zero per-tick
    budget every tick regardless of depth imbalance (1000 vs 5).

    Validates over 10 consecutive ticks with the same depth snapshot.
    """
    agent = _agent(monkeypatch, total_budget=10)
    topics = [PREDICT_DLQ, FRESHNESS_DLQ]
    depths = {PREDICT_DLQ: 1000, FRESHNESS_DLQ: 5}

    for tick_i in range(1, 11):
        msgs = agent.tick(topics, depths=depths)
        budgets = _scheduled_budget(msgs)
        assert budgets.get(PREDICT_DLQ, 0) > 0, (
            f"tick {tick_i}: large DLQ received 0 budget — scheduler broken"
        )
        assert budgets.get(FRESHNESS_DLQ, 0) > 0, (
            f"tick {tick_i}: small DLQ starved — received 0 budget; "
            f"large DLQ monopolised the scheduler"
        )
