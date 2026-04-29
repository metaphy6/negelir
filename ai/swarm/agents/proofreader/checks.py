"""Pure-function check rules for the Phase 6 proofreader swarm.

These functions are the **single source of truth** for the
range / consistency / plausibility rules. They take primitive inputs
and return a list of violation strings (empty = pass) so they can be:

- wrapped by individual proofreader agents in §6.1 (each agent picks
  the subset it cares about and emits a verdict);
- re-exported from `ai.proofreader.validator` for the legacy pipeline
  callers (data_showcase, runner, training_pipeline) until those
  callers migrate to the swarm path post-Phase-6;
- exercised directly by adversarial unit tests in §6.2 without
  touching any agent / bus machinery.

The rule bodies are deliberately faithful copies of the legacy
`DataProofreader` logic, not a reinterpretation — the legacy unit
tests (`ai/tests/test_unit.py::TestProofreader`) must continue to
pass after the legacy validator switches to importing from here.

Why pure functions and not classes? Because the `predict.final` /
`match.normalized` payloads on the swarm bus arrive as plain dicts,
and the proofreader agents in §6.1 are themselves stateless dispatch
shells. Wrapping the rules in objects would just add a layer the
agents have to unwrap.

Per the §6 build doctrine in `docs/reports/pre-phase6-roadmap.md`,
this module **must not** import from `ai/proofreader/`,
`ai/swarm/agents/`, or any bus / topic / payload module — it stays at
the bottom of the dependency graph so both callers can depend on it
without cycles.
"""
from __future__ import annotations

from typing import Any, Mapping


# ── Range constraints (canonical copy; legacy validator re-exports) ────
#
# Per ROADMAP §5.1 — bounds chosen from the empirical distribution of
# real Süper Lig data plus a small safety margin (e.g. the all-time
# high single-team yellow-card count is 8, so we cap at 10).
RANGES: dict[str, tuple[int, int]] = {
    "home_score":   (0, 15),
    "away_score":   (0, 15),
    "possession":   (0, 100),
    "shots_on":     (0, 40),
    "shots_off":    (0, 40),
    "corners":      (0, 25),
    "fouls":        (0, 40),
    "yellow_cards": (0, 10),
    "red_cards":    (0, 5),
    # Per-team card & foul ranges (v0.2)
    "home_yellows": (0, 10),
    "away_yellows": (0, 10),
    "home_reds":    (0, 5),
    "away_reds":    (0, 5),
    "home_fouls":   (0, 40),
    "away_fouls":   (0, 40),
    # Half-time scores
    "ht_home_score": (0, 10),
    "ht_away_score": (0, 10),
}


def _coerce_int(label: str, raw: Any, warnings: list[str]) -> int | None:
    """Defensive int coercion. Bad values produce a warning, not a
    hard exception — the batch contract requires that one bad record
    never aborts the whole batch (legacy behaviour preserved)."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        warnings.append(f"Invalid value type: {label}={raw}")
        return None


def range_check(match: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Verify every numeric field falls inside its declared `RANGES`
    bound. Returns ``(errors, warnings)``.

    Out-of-range values are **errors** (data is wrong); non-numeric
    values are **warnings** (data is malformed but the rule cannot
    judge it). This mirrors the legacy contract.
    """
    errors: list[str] = []
    warnings: list[str] = []
    stats = match.get("stats", {}) if isinstance(match, Mapping) else {}
    if not isinstance(stats, Mapping):
        stats = {}
    all_fields = {**dict(match), **dict(stats)}

    for field_name, (lo, hi) in RANGES.items():
        val = all_fields.get(field_name)
        if val is None:
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            warnings.append(f"Invalid value type: {field_name}={val}")
            continue
        if num < lo or num > hi:
            errors.append(
                f"Out of range: {field_name}={num} (expected: {lo}-{hi})"
            )
    return errors, warnings


def consistency_check(match: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Cross-field consistency rules (possession≈100, HT≤FT,
    yellows≤fouls). Returns ``(errors, warnings)``.

    Note: possession imbalance is a *warning* because a small drift
    can come from the upstream's rounding; HT>FT is an *error*
    because no real game can shed goals between halves."""
    errors: list[str] = []
    warnings: list[str] = []
    stats = match.get("stats", {}) if isinstance(match, Mapping) else {}
    if not isinstance(stats, Mapping):
        stats = {}

    # Possession sums to ~100
    home_poss = stats.get("home_possession")
    away_poss = stats.get("away_possession")
    if home_poss is not None and away_poss is not None:
        try:
            total = float(home_poss) + float(away_poss)
            if abs(total - 100) > 5:
                warnings.append(
                    f"Possession inconsistent: "
                    f"{home_poss}+{away_poss}={total} (≈100 expected)"
                )
        except (TypeError, ValueError):
            warnings.append(
                f"Invalid possession types: home={home_poss}, away={away_poss}"
            )

    # HT score never exceeds FT score
    ht_home = match.get("ht_home_score")
    ft_home = match.get("home_score")
    if ht_home is not None and ft_home is not None:
        ht_h = _coerce_int("ht_home_score", ht_home, warnings)
        ft_h = _coerce_int("home_score", ft_home, warnings)
        if ht_h is not None and ft_h is not None and ht_h > ft_h:
            errors.append(
                f"HT score cannot exceed FT: HT={ht_home} > FT={ft_home}"
            )

    ht_away = match.get("ht_away_score")
    ft_away = match.get("away_score")
    if ht_away is not None and ft_away is not None:
        ht_a = _coerce_int("ht_away_score", ht_away, warnings)
        ft_a = _coerce_int("away_score", ft_away, warnings)
        if ht_a is not None and ft_a is not None and ht_a > ft_a:
            errors.append(
                f"HT score cannot exceed FT: HT={ht_away} > FT={ft_away}"
            )

    # Yellows should not exceed fouls (a yellow always carries a foul)
    home_yellows = stats.get("home_yellows")
    home_fouls = stats.get("home_fouls")
    if home_yellows is not None and home_fouls is not None:
        hy = _coerce_int("home_yellows", home_yellows, warnings)
        hf = _coerce_int("home_fouls", home_fouls, warnings)
        if hy is not None and hf is not None and hy > hf:
            warnings.append(
                f"More yellow cards ({home_yellows}) than fouls "
                f"({home_fouls}) for home team"
            )

    return errors, warnings


def plausibility_check(match: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Historical-plausibility rules (>3σ from typical distributions).
    Returns ``(errors, warnings)``.

    Total goals ≥10 is statistically rare → warning.
    Single team scoring ≥8 is implausible → error (treat as data
    corruption; the all-time top-flight outlier is 9-1 which still
    keeps each team under 10).
    """
    errors: list[str] = []
    warnings: list[str] = []
    home_score = match.get("home_score")
    away_score = match.get("away_score")
    if home_score is None or away_score is None:
        return errors, warnings

    try:
        hs = int(home_score)
        as_ = int(away_score)
    except (TypeError, ValueError):
        warnings.append(
            f"Invalid value type: score={home_score}-{away_score}"
        )
        return errors, warnings

    total = hs + as_
    if total >= 10:
        warnings.append(
            f"Unusually high total goals: {total} (statistically rare)"
        )
    if hs >= 8 or as_ >= 8:
        errors.append(f"Implausible score: {home_score}-{away_score}")
    return errors, warnings


__all__ = [
    "RANGES",
    "range_check",
    "consistency_check",
    "plausibility_check",
]
