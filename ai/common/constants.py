"""
Negelir — Constants, team mappings, and domain knowledge.
Per roadmap §6.2: team names → UUIDs; no source-identifying data.
Per Gemini §4 Phase 2: locale data loaded from external YAML config.
"""

import logging

MODEL_VERSION = "0.3.0"
MAX_INPUT_LENGTH = 200

# ── Feature column names (canonical schema) ─────────────
# Single source of truth — N_FEATURES is derived from this list.
FEATURE_COLUMNS: list[str] = [
    # Team form (rolling windows)
    "home_avg_scored_3", "home_avg_scored_5", "home_avg_scored_10",
    "home_avg_conceded_3", "home_avg_conceded_5", "home_avg_conceded_10",
    "home_ppg_5", "home_ppg_10", "home_clean_sheet_10",
    "home_win_ratio_5", "home_draw_ratio_5", "home_loss_ratio_5",
    "away_avg_scored_3", "away_avg_scored_5", "away_avg_scored_10",
    "away_avg_conceded_3", "away_avg_conceded_5", "away_avg_conceded_10",
    "away_ppg_5", "away_ppg_10", "away_clean_sheet_10",
    "away_win_ratio_5", "away_draw_ratio_5", "away_loss_ratio_5",
    # Elo & derived
    "home_elo", "away_elo", "elo_diff",
    "home_xg", "away_xg", "xg_diff",
    "home_form_index", "away_form_index", "form_diff",
    # H2H
    "h2h_home_win_pct", "h2h_draw_pct", "h2h_avg_goals",
    "h2h_over25_pct", "h2h_bts_pct", "h2h_count",
    # League position
    "home_league_pos_norm", "away_league_pos_norm", "pos_diff",
    "home_goal_diff", "away_goal_diff",
    "home_pts_gap_leader", "away_pts_gap_leader",
    "home_pts_gap_relegation", "away_pts_gap_relegation",
    # Squad & tactical
    "home_formation_stability", "away_formation_stability",
    "home_squad_rotation_gini", "away_squad_rotation_gini",
    "home_goal_concentration", "away_goal_concentration",
    "home_avg_age", "away_avg_age",
    # Contextual
    "home_fixture_congestion_7d", "away_fixture_congestion_7d",
    "home_fixture_congestion_14d", "away_fixture_congestion_14d",
    "home_manager_tenure", "away_manager_tenure",
    "home_manager_change", "away_manager_change",
    "derby_flag", "season_phase",
    "match_week_norm",
    # Temporal
    "day_sin", "day_cos", "month_sin", "month_cos",
    "home_rest_days", "away_rest_days", "rest_diff",
    # Sentiment
    "home_media_sentiment", "away_media_sentiment",
    "home_fan_optimism", "away_fan_optimism",
    "media_consensus_strength",
    # Derived
    "style_matchup_index", "fatigue_diff",
    "home_momentum", "away_momentum",
    "home_scoring_consistency", "away_scoring_consistency",
    "surprise_index_home", "surprise_index_away",
    # Weather / venue
    "temperature_bucket", "precipitation_flag", "wind_category",
    "venue_type",
    # ── Card & discipline (v0.2) ──
    "home_avg_yellows_5", "away_avg_yellows_5",
    "home_avg_yellows_10", "away_avg_yellows_10",
    "home_avg_fouls_5", "away_avg_fouls_5",
    "h2h_avg_cards",
    "derby_card_factor",
    # ── Half-time / second-half splits (v0.2) ──
    "home_avg_ht_scored_5", "away_avg_ht_scored_5",
    "home_avg_sh_scored_5", "away_avg_sh_scored_5",
    "home_avg_ht_conceded_5", "away_avg_ht_conceded_5",
    # ── Venue-specific performance (v0.2) ──
    "home_venue_win_pct", "away_venue_win_pct",
    "home_venue_ppg_10", "away_venue_ppg_10",
    # ── Draw & low-scoring tendencies (v0.2) ──
    "home_draws_bayesian", "away_draws_bayesian",
    "low_scoring_likelihood",
    # ── Strength of schedule (v0.2) ──
    "home_sos", "away_sos",
    # ── Second-half detail (v0.2) ──
    "home_sh_scoring_rate", "away_sh_scoring_rate",
    "home_sh_conceding_rate", "away_sh_conceding_rate",
    # ── Scoring patterns (v0.2) ──
    "home_goals_per_match_rate", "away_goals_per_match_rate",
    # ── Query Intent Distribution (v0.3) ──
    "qid_match_winner", "qid_draw", "qid_over_under", "qid_goal_range",
    "qid_both_teams_score", "qid_clean_sheet", "qid_half_time",
    "qid_form_query", "qid_head_to_head", "qid_score_predict",
]

N_FEATURES: int = len(FEATURE_COLUMNS)

# ── Locale-driven data (loaded from YAML) ───────────────
# Strict loading: missing/malformed locale is a hard error. Silent empty
# fallbacks were removed during the modernization sweep — every consumer
# (TQU classifier, derby detector, source resolver, …) requires real data.
_log = logging.getLogger(__name__)

from .locale_loader import (
    load_locale, build_team_map, build_uuid_to_name,
    build_derbies, build_derby_pairs, build_team_strength,
    build_source_alias_map, build_team_names, build_mackolik_id_map,
)

_locale_data = load_locale()
TEAM_MAP: dict[str, str] = build_team_map(_locale_data)
UUID_TO_NAME: dict[str, str] = build_uuid_to_name(_locale_data)
FOOTBALL_KEYWORDS: list[str] = _locale_data.get("football_keywords", [])
LEAGUES: dict = _locale_data.get("leagues", {})
BANNED_WORDS: list[str] = _locale_data.get("banned_words", [])
DERBIES_SET: set[frozenset[str]] = build_derbies(_locale_data)
DERBY_PAIRS: list[tuple[str, str]] = build_derby_pairs(_locale_data)
TEAM_STRENGTH: dict[str, tuple[float, float]] = build_team_strength(_locale_data)
SOURCE_ALIAS_MAP: dict[str, str] = build_source_alias_map(_locale_data)
ALL_TEAM_NAMES: list[str] = build_team_names(_locale_data)
MACKOLIK_ID_MAP: dict[int, str] = build_mackolik_id_map(_locale_data)

if not TEAM_MAP or not FOOTBALL_KEYWORDS:
    raise RuntimeError(
        "Locale data is empty or incomplete (TEAM_MAP/FOOTBALL_KEYWORDS missing). "
        "Check ai/common/locale_tr.yaml."
    )

_log.info(
    "Locale loaded: %d team aliases, %d keywords, %d banned words",
    len(TEAM_MAP), len(FOOTBALL_KEYWORDS), len(BANNED_WORDS),
)
