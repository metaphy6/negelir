"""
Negelir TRC — Verdict selection logic.
Per roadmap §5.1: confidence × probability → verdict key.
Phase 2: Added data-quality verdicts for unresolved/stale matches.
"""

# Verdict keys that indicate data-quality issues (not prediction outcomes)
DATA_VERDICTS = frozenset({
    "fixture_unknown",
    "data_stale",
    "insufficient_data",
})


def select_verdict(confidence: float, probability: float, is_positive: bool,
                   *, data_issue: str | None = None) -> str:
    """
    Select verdict template key based on model confidence and probability.

    Args:
        confidence: Model confidence (0.0 - 1.0)
        probability: Outcome probability (0.0 - 1.0)
        is_positive: Whether the question asks about a positive outcome
        data_issue: If set, returns this verdict directly (fixture_unknown, data_stale, etc.)

    Returns:
        Verdict key: strong_yes, strong_no, likely_yes, likely_no, uncertain, low_data,
                     fixture_unknown, data_stale, insufficient_data
    """
    if data_issue and data_issue in DATA_VERDICTS:
        return data_issue

    if confidence < 0.5:
        return "low_data"

    if confidence > 0.7:
        if probability > 0.65:
            return "strong_yes" if is_positive else "strong_no"
        elif probability > 0.45:
            return "likely_yes" if is_positive else "likely_no"
        else:
            return "strong_no" if is_positive else "strong_yes"
    else:
        if probability > 0.55:
            return "likely_yes" if is_positive else "likely_no"
        return "uncertain"
