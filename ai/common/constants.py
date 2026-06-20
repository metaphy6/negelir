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
    # DEPRECATED: superseded by enrichment derived view fixture-congestion (Schedule + Live planes)
    "home_fixture_congestion_7d", "away_fixture_congestion_7d",
    # DEPRECATED: superseded by enrichment derived view fixture-congestion (Schedule + Live planes)
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
    # DEPRECATED: superseded by enrichment plane 9 (Environment) — values now computed by weather reactor
    "temperature_bucket", "precipitation_flag", "wind_category",
    # DEPRECATED: superseded by enrichment plane 9 (Environment) — surface penalty computed by environment reactor
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
    
    # ── Enrichment Plane 6: Roster-state (transfers, contracts, suspensions) ──
    "squad_strength_delta",          # Phase 21.1: recomputed on official transfer
    "cohesion_penalty",              # Phase 21.1: decaying penalty for new arrivals (first 4 league appearances)
    "departure_shock",               # Phase 21.1: top-quartile player left within 14d
    
    # ── Enrichment Plane 7: Health (injuries, availability) ──
    "squad_availability_score",      # Phase 21.2: scaled reduction from unavailable players
    "doubtful_ratio",                # Phase 21.2: fraction of starting XI with doubtful status
    "key_player_out_flag",           # Phase 21.2: binary flag: key player (top 3 rated) is out
    
    # ── Enrichment Plane 8: Officials (referees, VAR) ──
    "referee_yellows_per_match",     # Phase 21.3: rolling stat from referee profile
    "referee_reds_per_match",        # Phase 21.3: rolling stat from referee profile
    "referee_penalties_per_match",   # Phase 21.3: rolling stat from referee profile
    "referee_home_win_pct_adj",      # Phase 21.3: home-win % clamped by cfg.referee_home_bias_clamp
    
    # ── Enrichment Plane 9: Environment (weather, pitch) ──
    "wind_xg_factor",                # Phase 21.4: multiplicative xG reduction for wind > threshold
    "rain_xg_factor",                # Phase 21.4: multiplicative xG reduction for rain > threshold
    "surface_style_penalty",         # Phase 21.4: additional xG reduction for style-mismatch on worn pitch
    "pitch_condition_score",         # Phase 21.4: numeric score from pitch condition (pristine=1.0, frozen=0.0)
    
    # ── Enrichment Derived View: Market-movement ──
    "drift_1x2_home_pct",            # Phase 21.5: opening home odds % change to closing
    "drift_1x2_draw_pct",            # Phase 21.5: opening draw odds % change to closing
    "drift_1x2_away_pct",            # Phase 21.5: opening away odds % change to closing
    "drift_total_pct",               # Phase 21.5: max absolute % change across all legs
    "implied_prob_shift_max",        # Phase 21.5: maximum implied probability shift
    "high_drift_flag",               # Phase 21.5: binary flag: drift exceeds cfg.drift_high_threshold
    
    # ── Enrichment Derived View: Fixture-congestion (refined from v0.2) ──
    "home_travel_km_7d",             # Phase 21.5: cumulative travel distance for home team in last 7d
    "away_travel_km_7d",             # Phase 21.5: cumulative travel distance for away team in last 7d
    "congestion_diff_7d",            # Phase 21.5: home matches in 7d minus away matches in 7d (positive = home more congested)
    "is_post_international_break",   # Phase 21.5: float 0.0/0.5/1.0 indicating how many teams return from intl break
    
    # ── Enrichment Derived View: Card-context ──
    "combined_card_score",           # Phase 21.5: referee card rate × team card rate interaction
    "referee_cards_per_match_smoothed",  # Phase 21.5: smoothed rolling stat for the assigned referee
    
    # ── Enrichment Derived View: Narrative-pressure ──
    "narrative_score",               # Phase 21.5: sentiment polarity aggregated from editorial plane (Phase 10)
]

N_FEATURES: int = len(FEATURE_COLUMNS)  # Auto-resolves to 147 after Phase 21.16 lands

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
