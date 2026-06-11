"""Per-plane semantic invariants for feed Records.

Invariants are pure functions that validate the semantic constraints of a
payload that JSONSchema alone cannot express. Examples:
- score.score_h >= 0
- lineup.starting_eleven_count == 11
- market.odds_decimal >= 1.01
- schedule.kickoff_at > captured_at - 7d

Invariants run at enqueue()-time in the writer, **before** the canonical
encoder. Violations quarantine the record with reason=invariant_violation
and the invariant_id=<name>.

Each plane defines a `check_<plane>(payload: dict, record_envelope: dict) -> list[tuple[str, str]]`
function that returns a list of (invariant_id, reason) tuples. Empty list = pass.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "check_score",
    "check_lineup",
    "check_market",
    "check_schedule",
    "check_reference",
    "check_editorial",
    "check_feature_vectors",
    "check_sec_quarantine",
    "check_match_outcomes",
    "check_calibration",
    "check_competition",
    "check_predict_invalidated",
]


def check_score(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate score plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: home and away scores must be non-negative
    home_score = payload.get("home", {}).get("score")
    if home_score is not None and home_score < 0:
        violations.append(
            (
                "score_home_non_negative",
                f"home.score={home_score} is negative",
            )
        )

    away_score = payload.get("away", {}).get("score")
    if away_score is not None and away_score < 0:
        violations.append(
            (
                "score_away_non_negative",
                f"away.score={away_score} is negative",
            )
        )

    # Invariant: status must be in allowed values
    status = payload.get("status")
    allowed_statuses = {"not_started", "live", "halftime", "finished", "abandoned"}
    if status not in allowed_statuses:
        violations.append(
            (
                "status_enum",
                f"status={status!r} not in {sorted(allowed_statuses)}",
            )
        )

    # Invariant: minute must be non-negative
    minute = payload.get("minute")
    if minute is not None and minute < 0:
        violations.append(
            (
                "minute_non_negative",
                f"minute={minute} is negative",
            )
        )

    return violations


def check_lineup(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate lineup plane invariants."""
    violations: list[tuple[str, str]] = []

    starters = payload.get("starters", [])

    # Invariant: must have exactly 11 starters
    if len(starters) != 11:
        violations.append(
            (
                "starting_eleven_count",
                f"starters count={len(starters)}, expected 11",
            )
        )

    # Invariant: all starters must have unique player_ids
    player_ids = [s.get("player_id") for s in starters if s.get("player_id")]
    if len(player_ids) != len(set(player_ids)):
        violations.append(
            (
                "starter_duplicate_player_ids",
                f"duplicate player_ids in starters",
            )
        )

    # Invariant: jersey numbers must be in valid range (1-99)
    for starter in starters:
        number = starter.get("number")
        if number is not None and (number < 1 or number > 99):
            violations.append(
                (
                    "jersey_number_range",
                    f"starter jersey number={number} not in 1-99",
                )
            )

    # Invariant: bench is optional but if present, must be an array
    bench = payload.get("bench", [])
    for sub in bench:
        number = sub.get("number")
        if number is not None and (number < 1 or number > 99):
            violations.append(
                (
                    "bench_jersey_number_range",
                    f"bench jersey number={number} not in 1-99",
                )
            )

    return violations


def check_market(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate market plane invariants."""
    violations: list[tuple[str, str]] = []

    selections = payload.get("selections", [])

    # Invariant: all odds must be >= 1.01
    for i, selection in enumerate(selections):
        odds = selection.get("odds_decimal")
        if odds is not None and odds < 1.01:
            violations.append(
                (
                    "odds_decimal_min",
                    f"selections[{i}].odds_decimal={odds} < 1.01",
                )
            )

    # Invariant: available_amount, if present, must be non-negative
    for i, selection in enumerate(selections):
        available = selection.get("available_amount")
        if available is not None and available < 0:
            violations.append(
                (
                    "available_amount_non_negative",
                    f"selections[{i}].available_amount={available} is negative",
                )
            )

    return violations


def check_schedule(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate schedule plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: status must be in allowed values
    status = payload.get("status")
    allowed_statuses = {"scheduled", "postponed", "cancelled", "finished"}
    if status not in allowed_statuses:
        violations.append(
            (
                "schedule_status_enum",
                f"status={status!r} not in {sorted(allowed_statuses)}",
            )
        )

    # Invariant: kickoff_utc must be a valid ISO-8601 date-time
    # (basic format check — full validation done by JSONSchema)
    kickoff = payload.get("kickoff_utc")
    if kickoff and not _is_valid_iso8601(kickoff):
        violations.append(
            (
                "kickoff_utc_format",
                f"kickoff_utc={kickoff!r} is not valid ISO-8601",
            )
        )

    return violations


def check_reference(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate reference plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: kind must be in allowed values
    kind = payload.get("kind")
    allowed_kinds = {"team", "player", "venue", "competition", "season"}
    if kind not in allowed_kinds:
        violations.append(
            (
                "reference_kind_enum",
                f"kind={kind!r} not in {sorted(allowed_kinds)}",
            )
        )

    # Invariant: name must be non-empty
    name = payload.get("name")
    if not name:
        violations.append(
            (
                "reference_name_required",
                f"name is required and non-empty",
            )
        )

    return violations


def check_editorial(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate editorial plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: body_text must be non-empty
    body_text = payload.get("body_text")
    if not body_text:
        violations.append(
            (
                "body_text_required",
                f"body_text is required and non-empty",
            )
        )

    # Invariant: published_at must be a valid ISO-8601 date-time
    published_at = payload.get("published_at")
    if published_at and not _is_valid_iso8601(published_at):
        violations.append(
            (
                "published_at_format",
                f"published_at={published_at!r} is not valid ISO-8601",
            )
        )

    return violations


def check_feature_vectors(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate feature_vectors plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: vector must be an array of numbers
    vector = payload.get("vector", [])
    if not isinstance(vector, list):
        violations.append(
            (
                "vector_is_array",
                f"vector must be an array, got {type(vector).__name__}",
            )
        )
    else:
        for i, v in enumerate(vector):
            if not isinstance(v, (int, float)):
                violations.append(
                    (
                        "vector_element_numeric",
                        f"vector[{i}]={v!r} is not numeric",
                    )
                )

    return violations


def check_sec_quarantine(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate sec_quarantine plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: verdict must be in allowed values
    verdict = payload.get("verdict")
    allowed_verdicts = {"quarantine"}
    if verdict not in allowed_verdicts:
        violations.append(
            (
                "quarantine_verdict_enum",
                f"verdict={verdict!r} not in {sorted(allowed_verdicts)}",
            )
        )

    # Invariant: reasons must be non-empty
    reasons = payload.get("reasons", [])
    if not reasons:
        violations.append(
            (
                "quarantine_reasons_required",
                f"reasons must be non-empty",
            )
        )

    return violations


def check_match_outcomes(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate match_outcomes plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: outcome must be in allowed values
    outcome = payload.get("outcome")
    allowed_outcomes = {"home_win", "draw", "away_win"}
    if outcome not in allowed_outcomes:
        violations.append(
            (
                "outcome_enum",
                f"outcome={outcome!r} not in {sorted(allowed_outcomes)}",
            )
        )

    return violations


def check_calibration(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate calibration plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: calibration_score must be in range [0, 1]
    score = payload.get("calibration_score")
    if score is not None and (score < 0 or score > 1):
        violations.append(
            (
                "calibration_score_range",
                f"calibration_score={score} not in [0, 1]",
            )
        )

    return violations


def check_competition(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate competition plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: format must be in allowed values
    fmt = payload.get("format")
    allowed_formats = {"league", "knockout", "group_stage"}
    if fmt not in allowed_formats:
        violations.append(
            (
                "competition_format_enum",
                f"format={fmt!r} not in {sorted(allowed_formats)}",
            )
        )

    return violations


def check_predict_invalidated(
    payload: dict[str, Any], record_envelope: dict[str, Any]
) -> list[tuple[str, str]]:
    """Validate predict_invalidated plane invariants."""
    violations: list[tuple[str, str]] = []

    # Invariant: reason must be non-empty
    reason = payload.get("reason")
    if not reason:
        violations.append(
            (
                "invalidation_reason_required",
                f"reason is required and non-empty",
            )
        )

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _is_valid_iso8601(s: str) -> bool:
    """Quick ISO-8601 format check.
    
    Full parsing / validation is deferred to JSONSchema; this is just
    a sanity check to catch obvious junk.
    """
    if not isinstance(s, str):
        return False
    # Very basic: should have T and end with Z or offset
    return "T" in s and (s.endswith("Z") or "+" in s or (s.count("-") > 2))
