"""Tests for `ai/swarm/agents/proofreader/prediction_checks.py` (§6.2)."""
from __future__ import annotations

import math

import pytest

from swarm.agents.proofreader.prediction_checks import (
    grid_consistency_check,
    plausibility_check,
    sanity_check,
)


# ── Sanity ────────────────────────────────────────────────────


def test_sanity_accepts_well_formed_distribution() -> None:
    v, _, flags = sanity_check(
        {"market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25}}, eps=0.01,
    )
    assert v == "accept"
    assert flags == []


def test_sanity_rejects_when_market_outcomes_missing() -> None:
    v, _, flags = sanity_check({}, eps=0.01)
    assert v == "reject"
    assert "missing" in flags[0]


def test_sanity_rejects_empty_market_outcomes() -> None:
    v, _, flags = sanity_check({"market_outcomes": {}}, eps=0.01)
    assert v == "reject"


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_sanity_rejects_non_finite_probability(bad_value: float) -> None:
    v, _, flags = sanity_check(
        {"market_outcomes": {"H": bad_value, "D": 0.25, "A": 0.25}},
        eps=0.01,
    )
    assert v == "reject"
    assert any("non-finite" in f for f in flags)


def test_sanity_rejects_negative_probability() -> None:
    v, _, flags = sanity_check(
        {"market_outcomes": {"H": -0.1, "D": 0.5, "A": 0.6}},
        eps=0.01,
    )
    assert v == "reject"
    assert any("outside [0,1]" in f for f in flags)


def test_sanity_rejects_probability_above_one() -> None:
    v, _, _ = sanity_check(
        {"market_outcomes": {"H": 1.5, "D": 0.0, "A": 0.0}}, eps=0.01,
    )
    assert v == "reject"


def test_sanity_rejects_when_sum_drifts_beyond_eps() -> None:
    v, _, flags = sanity_check(
        {"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.3}},  # sum=1.1
        eps=0.01,
    )
    assert v == "reject"
    assert "differs from 1.0" in flags[0]


def test_sanity_accepts_within_tolerance() -> None:
    v, _, _ = sanity_check(
        {"market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.249}},  # sum=0.999
        eps=0.01,
    )
    assert v == "accept"


def test_sanity_rejects_non_numeric_probability() -> None:
    v, _, flags = sanity_check(
        {"market_outcomes": {"H": "high", "D": 0.5, "A": 0.5}}, eps=0.01,
    )
    assert v == "reject"
    assert any("non-numeric" in f for f in flags)


# ── Plausibility ──────────────────────────────────────────────


def test_plausibility_accepts_balanced_distribution() -> None:
    v, _, flags = plausibility_check(
        {"market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25}},
        max_outcome_prob=0.85,
    )
    assert v == "accept"
    assert flags == []


def test_plausibility_warns_on_lopsided_outcome() -> None:
    v, score, flags = plausibility_check(
        {"market_outcomes": {"H": 0.92, "D": 0.05, "A": 0.03}},
        max_outcome_prob=0.85,
    )
    assert v == "warn"
    assert score < 1.0
    assert any("exceeds cap" in f for f in flags)


def test_plausibility_at_cap_does_not_warn() -> None:
    """Boundary: exactly at the cap is acceptable; only `> cap` warns."""
    v, _, _ = plausibility_check(
        {"market_outcomes": {"H": 0.85, "D": 0.075, "A": 0.075}},
        max_outcome_prob=0.85,
    )
    assert v == "accept"


def test_plausibility_abstains_when_no_market_outcomes() -> None:
    """Sanity is the gate for missing data; plausibility abstains."""
    v, _, _ = plausibility_check({}, max_outcome_prob=0.85)
    assert v == "accept"


# ── Grid consistency ──────────────────────────────────────────


def test_grid_consistency_accepts_when_no_grid() -> None:
    v, _, _ = grid_consistency_check(
        {"market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25}}, tol=0.05,
    )
    assert v == "accept"


def test_grid_consistency_accepts_matching_marginals() -> None:
    v, _, flags = grid_consistency_check(
        {
            "market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2},
            "score_grid": [
                {"home": 1, "away": 0, "prob": 0.3},
                {"home": 2, "away": 1, "prob": 0.2},
                {"home": 0, "away": 0, "prob": 0.15},
                {"home": 1, "away": 1, "prob": 0.15},
                {"home": 0, "away": 1, "prob": 0.1},
                {"home": 1, "away": 2, "prob": 0.1},
            ],
        },
        tol=0.05,
    )
    assert v == "accept"
    assert flags == []


def test_grid_consistency_rejects_when_marginals_diverge() -> None:
    v, _, flags = grid_consistency_check(
        {
            "market_outcomes": {"H": 0.7, "D": 0.2, "A": 0.1},  # claims H=0.7
            "score_grid": [
                {"home": 1, "away": 0, "prob": 0.3},   # H marginal = 0.3
                {"home": 0, "away": 0, "prob": 0.5},   # D marginal = 0.5
                {"home": 0, "away": 1, "prob": 0.2},   # A marginal = 0.2
            ],
        },
        tol=0.05,
    )
    assert v == "reject"
    assert any("market['H']" in f for f in flags)


def test_grid_consistency_rejects_malformed_grid() -> None:
    v, _, _ = grid_consistency_check(
        {
            "market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2},
            "score_grid": [{"home": "one", "away": 0, "prob": 0.5}],
        },
        tol=0.05,
    )
    assert v == "reject"


def test_grid_consistency_rejects_non_list_grid() -> None:
    v, _, _ = grid_consistency_check(
        {
            "market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2},
            "score_grid": "not a list",
        },
        tol=0.05,
    )
    assert v == "reject"
