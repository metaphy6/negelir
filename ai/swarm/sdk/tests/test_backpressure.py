"""Phase 8 §8.11 — three-tier backpressure unit tests."""
from __future__ import annotations

from swarm.sdk.backpressure import (
    Signals,
    Tier,
    cadence_factor,
    classify,
    should_run,
)


def test_classify_green_when_no_signals() -> None:
    assert classify(Signals()) == Tier.GREEN


def test_classify_yellow_on_queue_depth() -> None:
    sig = Signals(queue_depth=500)
    assert classify(sig) == Tier.YELLOW


def test_classify_red_on_queue_depth_ceiling() -> None:
    sig = Signals(queue_depth=10_000)
    assert classify(sig) == Tier.RED


def test_classify_red_on_storage_pct() -> None:
    sig = Signals(storage_used_pct=95.0)
    assert classify(sig) == Tier.RED


def test_cadence_factor_green_is_one() -> None:
    assert cadence_factor(Tier.GREEN) == 1.0


def test_cadence_factor_yellow_is_slowdown() -> None:
    assert cadence_factor(Tier.YELLOW) >= 1.0


def test_cadence_factor_red_is_inf() -> None:
    assert cadence_factor(Tier.RED) == float("inf")


def test_should_run_only_blocks_red() -> None:
    assert should_run(Tier.GREEN) is True
    assert should_run(Tier.YELLOW) is True
    assert should_run(Tier.RED) is False


def test_yellow_must_be_strictly_below_red_thresholds() -> None:
    """Doctrine smoke: classify is monotonic across tiers."""
    yellow = Signals(queue_depth=500)
    red = Signals(queue_depth=10_000)
    assert classify(yellow) == Tier.YELLOW
    assert classify(red) == Tier.RED
