"""
Negelir — Constants, team mappings, and domain knowledge.
Per roadmap §6.2: team names → UUIDs; no source-identifying data.
Per Gemini §4 Phase 2: locale data loaded from external YAML config.
"""

import logging

MODEL_VERSION = "0.3.0"
MAX_INPUT_LENGTH = 200
N_FEATURES = 130

# ── Locale-driven data (loaded from YAML) ───────────────
# Falls back to empty structures if YAML unavailable.
_log = logging.getLogger(__name__)

try:
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
    _log.info(
        "Locale loaded: %d team aliases, %d keywords, %d banned words",
        len(TEAM_MAP), len(FOOTBALL_KEYWORDS), len(BANNED_WORDS),
    )
except Exception as exc:  # noqa: BLE001
    _log.warning("Failed to load locale YAML (%s), using empty defaults", exc)
    TEAM_MAP = {}
    UUID_TO_NAME = {}
    FOOTBALL_KEYWORDS = []
    LEAGUES = {}
    BANNED_WORDS = []
    DERBIES_SET = set()
    DERBY_PAIRS = []
    TEAM_STRENGTH = {}
    SOURCE_ALIAS_MAP = {}
    ALL_TEAM_NAMES = []
    MACKOLIK_ID_MAP = {}
