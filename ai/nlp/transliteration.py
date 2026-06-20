"""§13.11 TR transliteration support for foreign team names.

Maps foreign team names (e.g., "Bayern") to Turkish equivalents (e.g., "Bayern Münih")
so that both variants resolve to the same canonical_id in the gazetteer.

This module provides the mapping dictionary used by the entity extractor
to handle multi-variant team name resolution.
"""

# Comprehensive foreign-to-Turkish team name transliterations.
# Each entry maps from a foreign variant to the Turkish name used in the gazetteer.
# The gazetteer then maps both forms to the same canonical_id.
#
# Format: (foreign_name, turkish_name) tuples
# All names are lowercase_tr after normalization for gazetteer lookup.

FOREIGN_TEAM_TRANSLITERATIONS: dict[str, str] = {
    # ===== German Bundesliga (de_bundesliga) =====
    "bayern": "bayern münih",
    "bayern munich": "bayern münih",
    "munich": "bayern münih",  # fallback for context-dependent usage
    
    "dortmund": "borussia dortmund",
    "borussia": "borussia dortmund",
    "bvb": "borussia dortmund",
    
    "hamburg": "hamburger sv",
    "hsv": "hamburger sv",
    
    "schalke": "fc schalke 04",
    "schalke 04": "fc schalke 04",
    "schalke04": "fc schalke 04",
    
    "cologne": "fc koln",
    "koln": "fc koln",
    "cologne": "fc koln",
    
    "cologne": "colonia",  # alt form
    "fc koln": "colonia",
    
    # ===== English Premier League (en_premier_league) =====
    "manchester": "manchester",  # fallback, needs team context
    "united": "manchester united",
    "man u": "manchester united",
    "manu": "manchester united",
    "manchester united": "manchester united",
    
    "city": "manchester city",
    "man city": "manchester city",
    "manchester city": "manchester city",
    
    "liverpool": "liverpool fc",
    "lfc": "liverpool fc",
    "liverpool fc": "liverpool fc",
    
    "arsenal": "arsenal fc",
    "gunners": "arsenal fc",
    "arsenal fc": "arsenal fc",
    
    "chelsea": "chelsea fc",
    "chelsea fc": "chelsea fc",
    
    "tottenham": "tottenham hotspur",
    "spurs": "tottenham hotspur",
    "thfc": "tottenham hotspur",
    
    # ===== Spanish La Liga (es_la_liga) =====
    "real madrid": "real madrid",
    "madrid": "real madrid",
    "real": "real madrid",
    
    "barcelona": "barcelona",
    "barca": "barcelona",
    "fc barcelona": "barcelona",
    
    "atletico": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "atletico madryt": "atletico madrid",  # typo/transliteration variant
    
    # ===== Italian Serie A (it_serie_a) =====
    "juventus": "juventus",
    "juve": "juventus",
    "juventus fc": "juventus",
    
    "ac milan": "ac milan",
    "milan": "ac milan",
    "ac": "ac milan",  # needs context
    
    "inter": "inter milan",
    "inter milan": "inter milan",
    "internazionale": "inter milan",
    
    "roma": "as roma",
    "as roma": "as roma",
    "roma fc": "as roma",
    
    # ===== French Ligue 1 (fr_ligue_1) =====
    "psg": "psg",
    "paris": "psg",
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    
    "lyon": "olympique lyonnais",
    "lyonnais": "olympique lyonnais",
    "ol": "olympique lyonnais",
    
    "marseille": "olympique marseille",
    "om": "olympique marseille",
    
    # ===== Dutch Eredivisie (nl_eredivisie) =====
    "ajax": "ajax",
    "ajax amsterdam": "ajax",
    "afc ajax": "ajax",
    
    "psv": "psv eindhoven",
    "psv eindhoven": "psv eindhoven",
    "eindhoven": "psv eindhoven",
    
    "feyenoord": "feyenoord",
    "rotterdam": "feyenoord",
}


def transliterate_team_name(foreign_name: str) -> str | None:
    """Map a foreign team name to its Turkish equivalent.
    
    Parameters
    ----------
    foreign_name : str
        Foreign (non-Turkish) team name, typically in English.
        Will be normalized via lowercase before lookup.
    
    Returns
    -------
    str | None
        Turkish equivalent name if found in the transliteration table,
        or None if no mapping exists.
        
    Examples
    --------
    >>> transliterate_team_name("Bayern")
    'bayern münih'
    >>> transliterate_team_name("Manchester United")
    'manchester united'
    >>> transliterate_team_name("unknown team")
    None
    """
    from ai.common.text.turkish import lowercase_tr
    
    normalized = lowercase_tr(foreign_name.strip())
    return FOREIGN_TEAM_TRANSLITERATIONS.get(normalized)


def get_all_transliterations() -> list[tuple[str, str]]:
    """Get all foreign-to-Turkish team name mappings.
    
    Used by the gazetteer builder to auto-populate aliases for
    multilingual team resolution.
    
    Returns
    -------
    list[tuple[str, str]]
        List of (foreign_name, turkish_name) pairs.
    """
    return list(FOREIGN_TEAM_TRANSLITERATIONS.items())
