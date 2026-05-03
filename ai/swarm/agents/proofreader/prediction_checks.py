"""Phase 6.2 — Prediction-level check rules.

Pure functions that operate on a `predict.final` distribution dict
(NOT on raw match data — that's `checks.py`). Each returns
``(verdict, score, details)`` where:

* ``verdict ∈ {"accept", "warn", "reject"}`` — the recommendation
* ``score ∈ [0.0, 1.0]`` — confidence in the verdict (1.0 = certain)
* ``details: list[str]`` — human-readable reason strings (empty if
  accept). The agent shell joins these into the verdict's
  ``rationale`` field; the structured ``flags`` list of rule IDs is
  built by the shell from `checks_run` so it stays a subset (an
  invariant the payload enforces).

Rationale for keeping these pure (not classes):

* The `ProofreaderAgent` shells in `_base.py` are stateless dispatch.
* Adversarial unit tests can exercise the rules directly without
  bus / topic / message machinery.
* The legacy `ai.proofreader.cross_validator` callers can import
  these once Phase 9 odds plumbing arrives.

Scope (ROADMAP §6.2):

* `sanity_check`        — probs sum to 1±ε, no NaN, no negatives,
                          no missing market keys.
* `plausibility_check`  — no single market outcome > configured cap
                          (e.g. 0.85 for an away win in a tied
                          derby is suspicious).
* `grid_consistency_check` — if a `score_grid` is present, its
                          marginals match the `market_outcomes`
                          within tolerance.

Cross-source and historical checks are deferred:

* Cross-source needs odds (Phase 9).
* Historical needs realized outcomes loop (`drift.v1`, §6.3, lives
  in a separate agent because its state is per-model).
"""
from __future__ import annotations

import math
from typing import Any, Mapping

# Public verdict tuple type — used across replicas + aggregator tests.
CheckResult = tuple[str, float, list[str]]


# ── Sanity ─────────────────────────────────────────────────────


def sanity_check(
    distribution: Mapping[str, Any],
    *,
    eps: float,
) -> CheckResult:
    """Probabilistic sanity: every market_outcome value is finite, in
    [0,1], and the sum is within ``eps`` of 1.0.

    A failure is fatal (`reject`) — the distribution is malformed and
    must not be cached. There is no `warn` path for sanity: either the
    numbers add up or they don't.
    """
    flags: list[str] = []
    market = distribution.get("market_outcomes")
    if not isinstance(market, Mapping) or not market:
        return "reject", 1.0, ["sanity: market_outcomes missing or empty"]

    total = 0.0
    for key, val in market.items():
        try:
            num = float(val)
        except (TypeError, ValueError):
            flags.append(f"sanity: non-numeric probability for {key!r}={val!r}")
            continue
        if math.isnan(num) or math.isinf(num):
            flags.append(f"sanity: non-finite probability for {key!r}={num}")
            continue
        if num < 0.0 or num > 1.0:
            flags.append(
                f"sanity: probability for {key!r}={num} outside [0,1]"
            )
            continue
        total += num

    if flags:
        return "reject", 1.0, flags
    if abs(total - 1.0) > eps:
        return "reject", 1.0, [
            f"sanity: market_outcomes sum {total:.6f} differs from 1.0 by > eps={eps}"
        ]
    return "accept", 1.0, []


# ── Plausibility ──────────────────────────────────────────────


def plausibility_check(
    distribution: Mapping[str, Any],
    *,
    max_outcome_prob: float,
) -> CheckResult:
    """No single market outcome may exceed ``max_outcome_prob``.

    A predictor that is `> 0.85` confident in any single outcome for a
    competitive sport is statistically suspect — not necessarily wrong,
    but the human should see it. Verdict is `warn`, not `reject`: the
    aggregator counts warnings toward quorum (they are operator-visible
    yes-votes).
    """
    market = distribution.get("market_outcomes")
    if not isinstance(market, Mapping) or not market:
        # Sanity will catch this; here we abstain.
        return "accept", 1.0, []
    flags: list[str] = []
    for key, val in market.items():
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue  # sanity owns this branch
        if num > max_outcome_prob:
            flags.append(
                f"plausibility: outcome {key!r}={num:.3f} exceeds cap "
                f"{max_outcome_prob}"
            )
    if flags:
        return "warn", 0.7, flags
    return "accept", 1.0, []


# ── Consistency ───────────────────────────────────────────────


def grid_consistency_check(
    distribution: Mapping[str, Any],
    *,
    tol: float,
) -> CheckResult:
    """If a `score_grid` is present, its marginals must agree with
    the `market_outcomes` within ``tol`` per outcome.

    `score_grid` is a 2D matrix ``grid[home][away] = prob`` (Phase 5
    contract — see ``ai/swarm/agents/predictors/_grid.score_grid``).
    The 1X2 marginals are:

        H = Σ grid[h][a] where h > a
        D = Σ grid[h][a] where h == a
        A = Σ grid[h][a] where h < a

    Disagreement is a `reject` — the predictor produced two
    inconsistent views of the same prediction, which is a contract
    violation, not a confidence issue.
    """
    grid = distribution.get("score_grid")
    if grid is None:
        return "accept", 1.0, []
    if not isinstance(grid, list):
        return "reject", 1.0, ["consistency: score_grid is not a list"]

    market = distribution.get("market_outcomes")
    if not isinstance(market, Mapping):
        return "accept", 1.0, []

    # Currently only 1X2 marginals are checked; extend per market as
    # new market types arrive (over/under, BTTS).
    h = d = a = 0.0
    for home_idx, row in enumerate(grid):
        if not isinstance(row, list):
            return "reject", 1.0, [
                "consistency: score_grid row is not a list"
            ]
        for away_idx, cell in enumerate(row):
            try:
                prob = float(cell)
            except (TypeError, ValueError):
                return "reject", 1.0, [
                    f"consistency: malformed score_grid cell at "
                    f"[{home_idx}][{away_idx}]={cell!r}"
                ]
            if math.isnan(prob) or math.isinf(prob):
                return "reject", 1.0, [
                    f"consistency: non-finite score_grid cell at "
                    f"[{home_idx}][{away_idx}]={prob}"
                ]
            if home_idx > away_idx:
                h += prob
            elif home_idx < away_idx:
                a += prob
            else:
                d += prob

    flags: list[str] = []
    expected = {"H": h, "D": d, "A": a}
    # Phase-6 audit (F-7): normalise market keys to uppercase before
    # lookup so a stray lowercase `"h"` / `"d"` / `"a"` from a future
    # predictor does not silently skip the consistency check.
    market_upper = {str(k).upper(): v for k, v in market.items()}
    for key, marginal in expected.items():
        declared = market_upper.get(key)
        if declared is None:
            continue
        try:
            num = float(declared)
        except (TypeError, ValueError):
            continue
        if abs(num - marginal) > tol:
            flags.append(
                f"consistency: market[{key!r}]={num:.3f} differs from "
                f"score_grid marginal={marginal:.3f} by > tol={tol}"
            )
    if flags:
        return "reject", 1.0, flags
    return "accept", 1.0, []


__all__ = [
    "CheckResult",
    "sanity_check",
    "plausibility_check",
    "grid_consistency_check",
]
