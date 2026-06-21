"""
Negelir TRC — Response composer.
Combines verdict + explanation template + model output into a Turkish response.
Per roadmap §5.1: deterministic template composition, no generative text.
"""

from ai.common.constants import UUID_TO_NAME, BANNED_WORDS
from ai.common.logger import get_logger
from trc.templates import (
    VERDICTS, EXPLANATION_TEMPLATES, MOMENTUM_SENTENCES,
    DEFENSE_SENTENCES, H2H_SENTENCES, FORM_LABELS,
)
from trc.verdict import select_verdict

log = get_logger("trc.composer")

MAX_RESPONSE_LENGTH = 500


def compose_response(
    intent_id: str,
    analysis: dict,
    entities: dict | None = None,
) -> str:
    """
    Compose a Turkish response from model analysis output.

    Args:
        intent_id: The classified question intent
        analysis: Model output dict with keys like confidence, probability, features, etc.
        entities: Extracted entities (team names, goal ranges, etc.)

    Returns:
        Human-readable Turkish response string.
    """
    confidence = analysis.get("confidence", 0.5)
    probability = analysis.get("probability", 0.5)
    features = analysis.get("features", {})
    entities = entities or {}

    # Determine positivity based on intent
    is_positive = _is_positive_intent(intent_id, analysis)

    # Select verdict
    verdict_key = select_verdict(confidence, probability, is_positive)

    # Special case: form_query and head_to_head use "report" format
    if intent_id in ("form_query", "head_to_head"):
        verdict_key = "report"

    # Get verdict text
    verdict_text = VERDICTS.get(verdict_key, VERDICTS["uncertain"])
    if intent_id in ("form_query", "head_to_head"):
        verdict_text = ""  # no verdict for informational queries

    # Build template context
    ctx = _build_template_context(intent_id, analysis, features, entities)

    # Get explanation template
    intent_templates = EXPLANATION_TEMPLATES.get(intent_id, {})
    template = intent_templates.get(verdict_key)

    # Fallback: use 'uncertain' or first available template
    if not template:
        template = intent_templates.get("uncertain") or next(iter(intent_templates.values()), "")

    # Fill template
    try:
        explanation = template.format(**ctx)
    except KeyError as e:
        log.warning(f"Template fill error: missing key {e}")
        explanation = f"Analiz tamamlandı. Güven: %{int(confidence * 100)}."

    # Combine verdict + explanation
    if verdict_text:
        response = f"{verdict_text} {explanation}"
    else:
        response = explanation

    # Compliance: check for banned words (roadmap §3.1)
    response = _compliance_check(response)

    # Length enforcement (roadmap §5.6.3)
    if len(response) > MAX_RESPONSE_LENGTH:
        response = response[:MAX_RESPONSE_LENGTH - 3] + "..."

    return response


def _is_positive_intent(intent_id: str, analysis: dict) -> bool:
    """Determine if the question expects a 'yes' answer based on probability."""
    prob = analysis.get("probability", 0.5)
    return prob >= 0.5


def _build_template_context(
    intent_id: str,
    analysis: dict,
    features: dict,
    entities: dict,
) -> dict:
    """Build the template placeholder context from model output."""
    confidence_pct = int(analysis.get("confidence", 0.5) * 100)

    # Team names
    team_refs = entities.get("team_refs", [])
    team = UUID_TO_NAME.get(team_refs[0], "Ev sahibi") if team_refs else "Ev sahibi"
    team2 = UUID_TO_NAME.get(team_refs[1], "Deplasman") if len(team_refs) > 1 else "Deplasman"

    # Common features
    window = features.get("window", 5)
    avg_goals = features.get("avg_total_goals", 2.3)
    avg_scored = features.get("avg_goals_scored", 1.4)
    avg_conceded = features.get("avg_goals_conceded", 1.1)
    h2h_over_pct = features.get("h2h_over_pct", 55)
    draw_pct = features.get("draw_pct", 25)
    bts_pct = features.get("bts_pct", 45)
    elo = features.get("elo_rating", 1500)

    # Momentum
    home_momentum = features.get("home_momentum", "stable")
    away_momentum = features.get("away_momentum", "stable")
    if home_momentum == "rising" and away_momentum == "rising":
        momentum_text = MOMENTUM_SENTENCES["both_rising"]
    elif home_momentum == "rising":
        momentum_text = MOMENTUM_SENTENCES["home_rising"]
    elif away_momentum == "rising":
        momentum_text = MOMENTUM_SENTENCES["away_rising"]
    elif home_momentum == "falling" and away_momentum == "falling":
        momentum_text = MOMENTUM_SENTENCES["both_falling"]
    elif home_momentum == "falling":
        momentum_text = MOMENTUM_SENTENCES["home_falling"]
    elif away_momentum == "falling":
        momentum_text = MOMENTUM_SENTENCES["away_falling"]
    else:
        momentum_text = MOMENTUM_SENTENCES["stable"]

    # Defense quality
    defense_key = features.get("defense_quality", "mixed")
    defense_text = DEFENSE_SENTENCES.get(defense_key, DEFENSE_SENTENCES["mixed"])

    # H2H
    h2h_key = features.get("h2h_advantage", "balanced")
    h2h_text = H2H_SENTENCES.get(h2h_key, H2H_SENTENCES["balanced"])

    # Form label
    form_val = features.get("form_index", 0.5)
    if form_val > 0.8:
        form_label = FORM_LABELS["excellent"]
    elif form_val > 0.6:
        form_label = FORM_LABELS["good"]
    elif form_val > 0.4:
        form_label = FORM_LABELS["average"]
    elif form_val > 0.2:
        form_label = FORM_LABELS["poor"]
    else:
        form_label = FORM_LABELS["very_poor"]

    return {
        "team": team,
        "team1": team,
        "team2": team2,
        "window": window,
        "win_count": features.get("win_count", 3),
        "opp_wins": features.get("opp_wins", 1),
        "venue_type": features.get("venue_type", "deplasman"),
        "venue_type_tr": features.get("venue_type_tr", "deplasman"),
        "advantage_text": features.get("advantage_text", "ev sahibi lehine"),
        "avg_goals": f"{avg_goals:.1f}",
        "avg_scored": f"{avg_scored:.1f}",
        "avg_conceded": f"{avg_conceded:.1f}",
        "h2h_over_pct": int(h2h_over_pct),
        "h2h_text": h2h_text,
        "draw_pct": int(draw_pct),
        "bts_pct": int(bts_pct),
        "defense_text": defense_text,
        "momentum_text": momentum_text,
        "confidence": confidence_pct,
        "threshold_text": entities.get("threshold_text", "yüksek gol sayısı (4+)"),
        "min_goals": entities.get("min_goals", 0),
        "max_goals": entities.get("max_goals", 6),
        "direction": entities.get("direction", "dışında"),
        "clean_sheets": features.get("clean_sheets", 2),
        "half_text": "İlk yarı" if entities.get("half") == 1 else "İkinci yarı",
        "half_text_lower": "ilk yarı" if entities.get("half") == 1 else "ikinci yarı",
        "half_stat": features.get("half_stat", "karışık sonuçlar alınmış"),
        "wins": features.get("wins", 2),
        "draws": features.get("draws", 1),
        "losses": features.get("losses", 2),
        "t1_wins": features.get("t1_wins", 3),
        "t2_wins": features.get("t2_wins", 2),
        "trend_text": features.get("trend_text", "dengeli"),
        "form_label": form_label,
        "elo": int(elo),
    }


def _compliance_check(text: str) -> str:
    """
    Per roadmap §3.1 & §5.6.3: ensure no banned words appear in output.
    This is a final safety net — templates should already be clean.
    """
    text_lower = text.lower()
    for word in BANNED_WORDS:
        if word in text_lower:
            log.error(f"⛔ COMPLIANCE VIOLATION: banned word '{word}' detected in response!")
            text = text.replace(word, "***")
    return text
