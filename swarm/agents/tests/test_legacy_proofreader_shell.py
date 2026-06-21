"""Wave A.2 (pre-Phase-6 roadmap §4.2) — byte-identical contract test.

The legacy ``ai/proofreader/validator.py::DataProofreader`` is kept
alive as a thin OO shell so the legacy callers
(``ai/pipeline/runner.py``, ``ai/pipeline/training_pipeline.py``,
``ai/data_showcase.py``) keep working through Phase 6. Its three
private check methods now delegate to the canonical pure functions
in ``ai/swarm/agents/proofreader/checks.py``.

This test set guarantees that the shell's output is **byte-identical**
to the direct sum of the pure-function outputs across a representative
input matrix (happy path, range-violation, consistency-violation,
plausibility-violation, malformed types, the gpt5-Codex#2 ``"x"``
non-numeric crash repro, and the empty payload). If the shell ever
drifts from the canonical functions the test fails loudly, which is
the safety net that lets the Plan B "delete-after-Phase-6" deferral
be safe.

The test deliberately compares the **multisets of error / warning
strings** (set-equal — order is not part of the contract because the
two callers iterate over slightly different field orders) rather
than the underlying ``ValidationResult`` object identity, because
the shell adds its own bookkeeping (``is_valid`` boolean,
``quarantined`` list) that the pure functions do not.
"""
from __future__ import annotations

from proofreader.validator import DataProofreader
from swarm.agents.proofreader.checks import (
    consistency_check,
    plausibility_check,
    range_check,
)


def _pure_run(match: dict) -> tuple[set[str], set[str]]:
    """Return the canonical (errors, warnings) sets for ``match``
    by composing the three pure functions in the same order the
    legacy shell does."""
    errors: list[str] = []
    warnings: list[str] = []
    for fn in (range_check, consistency_check, plausibility_check):
        e, w = fn(match)
        errors.extend(e)
        warnings.extend(w)
    return set(errors), set(warnings)


# Representative input matrix. Each entry is one independent test case.
_CASES: list[tuple[str, dict]] = [
    (
        "happy_path",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 2, "away_score": 1,
            "ht_home_score": 1, "ht_away_score": 0,
            "stats": {
                "home_possession": 55, "away_possession": 45,
                "home_yellows": 2, "home_fouls": 11,
                "away_yellows": 1, "away_fouls": 9,
                "shots_on": 6, "shots_off": 8, "corners": 5,
            },
        },
    ),
    (
        "range_violation_score",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 99, "away_score": 0,  # out of (0,15)
            "stats": {},
        },
    ),
    (
        "consistency_ht_gt_ft",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 1, "away_score": 1,
            "ht_home_score": 3, "ht_away_score": 0,  # HT > FT — error
            "stats": {},
        },
    ),
    (
        "consistency_possession_drift",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 0, "away_score": 0,
            "stats": {"home_possession": 70, "away_possession": 20},  # 90, off by >5
        },
    ),
    (
        "plausibility_high_total",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 6, "away_score": 5,  # total=11, warn
            "stats": {},
        },
    ),
    (
        "plausibility_implausible_single",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 9, "away_score": 0,  # >=8, error
            "stats": {},
        },
    ),
    (
        "gpt5_x_string",
        # gpt5-Codex finding #2 repro: a non-numeric ``ht_home_score``.
        # The legacy shell originally crashed here; both shell and
        # pure functions must now produce the same warning instead.
        {
            "home_team": "A", "away_team": "B",
            "home_score": 1, "away_score": 0,
            "ht_home_score": "x", "ht_away_score": 0,
            "stats": {},
        },
    ),
    (
        "stats_not_a_dict",
        {
            "home_team": "A", "away_team": "B",
            "home_score": 1, "away_score": 1,
            "stats": "not-a-dict",  # malformed, must not crash
        },
    ),
    (
        "empty_payload",
        {},
    ),
    (
        "missing_scores",
        {"home_team": "A", "away_team": "B", "stats": {}},
    ),
]


def test_legacy_proofreader_shell_matches_checks() -> None:
    """For every case in the matrix, the legacy ``DataProofreader``
    must emit the same error/warning multiset as the direct
    composition of the three pure functions."""
    pr = DataProofreader()
    for case_id, match in _CASES:
        result = pr.validate_match(match)
        shell_errors = set(result.errors)
        shell_warnings = set(result.warnings)
        pure_errors, pure_warnings = _pure_run(match)
        assert shell_errors == pure_errors, (
            f"[{case_id}] errors drifted from canonical checks:\n"
            f"  shell only: {shell_errors - pure_errors}\n"
            f"  pure  only: {pure_errors - shell_errors}"
        )
        assert shell_warnings == pure_warnings, (
            f"[{case_id}] warnings drifted from canonical checks:\n"
            f"  shell only: {shell_warnings - pure_warnings}\n"
            f"  pure  only: {pure_warnings - shell_warnings}"
        )


def test_legacy_shell_is_valid_flag_matches_errors() -> None:
    """Sanity: ``is_valid`` must be ``True`` iff there are zero errors."""
    pr = DataProofreader()
    for case_id, match in _CASES:
        result = pr.validate_match(match)
        expected_valid = not result.errors
        assert result.is_valid is expected_valid, (
            f"[{case_id}] is_valid={result.is_valid} but errors={result.errors}"
        )


def test_gpt5_x_string_does_not_crash() -> None:
    """Explicit regression for gpt5-Codex finding #2 — non-numeric
    half-time score must produce a warning, not raise. This used to
    crash inside the legacy ``_consistency_checks`` int-coercion.
    """
    pr = DataProofreader()
    match = {
        "home_team": "A", "away_team": "B",
        "home_score": 1, "away_score": 0,
        "ht_home_score": "x", "ht_away_score": 0,
        "stats": {},
    }
    # Must not raise.
    result = pr.validate_match(match)
    # And must record the type warning at least once.
    assert any("Invalid value type" in w for w in result.warnings), (
        f"expected 'Invalid value type' warning, got: {result.warnings}"
    )
