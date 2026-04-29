"""Tests for `ai/swarm/agents/proofreader/checks.py`.

These cover the pure-function check rules that Phase 6.2 will wrap
in agent shells. They duplicate the legacy `TestProofreader` cases
intentionally — once Phase 6.3 lands and the legacy validator is
retired, *these* become the regression suite.

The legacy `ai/tests/test_unit.py::TestProofreader` is left in place
for the duration of Wave A.2 to guarantee the OO `DataProofreader`
shell (which now delegates here) keeps passing — that double cover
is the proof of the parity contract.
"""
from __future__ import annotations

from swarm.agents.proofreader.checks import (
    RANGES,
    consistency_check,
    plausibility_check,
    range_check,
)


def _valid_match() -> dict:
    return {
        "home_score": 2,
        "away_score": 1,
        "ht_home_score": 1,
        "ht_away_score": 0,
        "stats": {
            "home_possession": 55,
            "away_possession": 45,
            "home_yellows": 2,
            "home_fouls": 11,
            "shots_on": 6,
        },
    }


# ── range_check ─────────────────────────────────────────────────


def test_range_check_clean_match() -> None:
    errors, warnings = range_check(_valid_match())
    assert errors == []
    # The valid match also reports zero range warnings.
    assert warnings == []


def test_range_check_negative_score_is_error() -> None:
    m = _valid_match()
    m["home_score"] = -1
    errors, _ = range_check(m)
    assert any("home_score" in e for e in errors)


def test_range_check_excessive_goals_is_error() -> None:
    m = _valid_match()
    m["home_score"] = 30
    errors, _ = range_check(m)
    assert any("home_score" in e for e in errors)


def test_range_check_non_numeric_is_warning_not_error() -> None:
    m = _valid_match()
    m["home_score"] = "not-a-number"
    errors, warnings = range_check(m)
    assert errors == []
    assert any("home_score" in w for w in warnings)


def test_range_check_handles_missing_stats() -> None:
    """`stats` may be missing or non-dict — must not crash."""
    errors, warnings = range_check({"home_score": 1, "away_score": 0})
    assert errors == []
    errors, _ = range_check({"home_score": 1, "stats": "garbage"})
    assert errors == []  # garbage stats simply skipped


def test_ranges_dict_is_canonical_export() -> None:
    """The legacy `ai/proofreader/validator.RANGES` re-exports this
    dict; dropping a key here would silently break the legacy callers
    in `data_showcase.py` (which iterates `RANGES.items()`).
    """
    assert "home_score" in RANGES
    assert "ht_home_score" in RANGES
    assert RANGES["red_cards"] == (0, 5)


# ── consistency_check ───────────────────────────────────────────


def test_consistency_check_clean_match() -> None:
    errors, warnings = consistency_check(_valid_match())
    assert errors == []
    assert warnings == []


def test_consistency_ht_exceeds_ft_is_error() -> None:
    m = _valid_match()
    m["ht_home_score"] = 3  # > ft 2
    errors, _ = consistency_check(m)
    assert any("HT" in e and "FT" in e for e in errors)


def test_consistency_possession_imbalance_is_warning() -> None:
    m = _valid_match()
    m["stats"]["home_possession"] = 80
    m["stats"]["away_possession"] = 50  # sums to 130
    errors, warnings = consistency_check(m)
    assert errors == []
    assert any("Possession" in w for w in warnings)


def test_consistency_yellows_exceed_fouls_is_warning() -> None:
    m = _valid_match()
    m["stats"]["home_yellows"] = 5
    m["stats"]["home_fouls"] = 2
    _, warnings = consistency_check(m)
    assert any("yellow" in w.lower() for w in warnings)


def test_consistency_handles_non_numeric_ht_gracefully() -> None:
    """Bad upstream values become warnings, never exceptions."""
    m = _valid_match()
    m["ht_home_score"] = "n/a"
    errors, warnings = consistency_check(m)
    # No HT comparison happens (coercion failed) → no error.
    assert errors == []
    assert any("ht_home_score" in w for w in warnings)


# ── plausibility_check ─────────────────────────────────────────


def test_plausibility_clean_match() -> None:
    errors, warnings = plausibility_check(_valid_match())
    assert errors == []
    assert warnings == []


def test_plausibility_high_total_goals_is_warning() -> None:
    m = _valid_match()
    m["home_score"] = 6
    m["away_score"] = 4  # total 10
    _, warnings = plausibility_check(m)
    assert any("Unusually high" in w for w in warnings)


def test_plausibility_implausible_single_team_score_is_error() -> None:
    m = _valid_match()
    m["home_score"] = 9
    m["away_score"] = 0
    errors, _ = plausibility_check(m)
    assert any("Implausible" in e for e in errors)


def test_plausibility_missing_scores_is_noop() -> None:
    errors, warnings = plausibility_check({"stats": {}})
    assert errors == []
    assert warnings == []


def test_plausibility_non_numeric_score_is_warning() -> None:
    errors, warnings = plausibility_check(
        {"home_score": "n/a", "away_score": "n/a"}
    )
    assert errors == []
    assert any("score=" in w for w in warnings)
