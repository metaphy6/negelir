"""
Negelir — League configuration for generic multi-league support.
Extracts all league-specific parameters into pluggable configs.
"""

from dataclasses import dataclass, field


@dataclass
class LeagueConfig:
    """All league-specific parameters in one place."""

    # Identity
    league_id: str = "tr_super_lig"
    league_name: str = "Turkish Süper Lig"
    country: str = "Turkey"
    language: str = "tr"

    # External source mapping
    openfootball_path: str = "tr.1.json"
    footballdata_country: str = "T1"

    # Structure
    teams_count: int = 19
    rounds_per_season: int = 38
    promotion_slots: int = 3
    relegation_slots: int = 4

    # Elo parameters
    elo_initial: float = 1500.0
    elo_k: float = 32.0
    elo_home_advantage: float = 65.0

    # Goal distribution (empirical)
    first_half_goal_pct: float = 0.47
    league_avg_goals: float = 2.65

    # Poisson limits
    poisson_max_goals: int = 7
    poisson_ht_max_goals: int = 5
    poisson_home_goal_cap: int = 7
    poisson_away_goal_cap: int = 7
    poisson_draw_goal_cap: int = 5
    poisson_market_goal_cap: int = 6
    min_xg_floor: float = 0.3

    # Dixon-Coles low-scoring adjustment (rho parameter)
    dixon_coles_rho: float = -0.13

    # Elo → xG adjustment curve
    # factor = 1 / (1 + 10 ** (-elo_diff / elo_xg_divisor))
    # adjusted_xg_multiplier = xg_elo_factor_min + factor * xg_elo_factor_range
    elo_xg_divisor: float = 600.0
    xg_elo_factor_min: float = 0.7
    xg_elo_factor_range: float = 0.6

    # Venue-specific xG ratio bounds (home/away scoring vs all-venues)
    venue_ratio_floor: float = 0.7
    venue_ratio_ceiling: float = 1.4

    # Derby pairs (frozenset of team name tuples)
    derbies: set = field(default_factory=set)

    # Ensemble weights
    xgb_weight: float = 0.35

    # Draw detection thresholds
    draw_ha_gap_threshold: float = 0.15
    draw_prob_threshold: float = 0.26
    draw_bayesian_threshold: float = 0.20

    # XGBoost hyperparameters
    xgb_n_estimators: int = 300
    xgb_max_depth: int = 4
    xgb_learning_rate: float = 0.08
    xgb_min_child_weight: int = 3
    xgb_reg_alpha: float = 0.5
    xgb_reg_lambda: float = 1.5
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_gamma: float = 0.1

    # Training
    draw_sample_weight: float = 2.0
    val_split: float = 0.15
    train_pct: float = 0.75

    # Confidence calibration
    calibrate_probabilities: bool = True

    # Team name map (display name → canonical)
    team_name_map: dict = field(default_factory=dict)

    # Demo / showcase strings (localized; surfaced by pipeline runner banners
    # and the NLP sentiment showcase). Override per-league for non-Turkish
    # demos or custom narratives.
    demo_label: str = "Turkish Q&A Demo"
    demo_sentiment_samples: list = field(default_factory=lambda: [
        "Galatasaray son maçta muhteşem bir galibiyet aldı, takım morali çok yüksek",
        "Fenerbahçe'de sakatlık krizi devam ediyor, taraftar moral bozuk",
        "Beşiktaş istikrarlı oynuyor, savunma sağlam gidiyor",
    ])

    def is_derby(self, home: str, away: str) -> bool:
        """True if (home, away) — by display name OR canonical UUID — is a derby pair."""
        if frozenset((home, away)) in self.derbies:
            return True
        # Also try canonical UUIDs (display names may differ between sources)
        try:
            from .constants import TEAM_MAP
        except Exception:
            return False
        h_uuid = TEAM_MAP.get(home.lower())
        a_uuid = TEAM_MAP.get(away.lower())
        if h_uuid and a_uuid:
            return frozenset((h_uuid, a_uuid)) in self.derbies
        return False


# ── Pre-built league configs ────────────────────────────

def turkish_super_lig() -> LeagueConfig:
    """Turkish Süper Lig with empirically tuned parameters."""
    from .constants import DERBIES_SET
    return LeagueConfig(derbies=DERBIES_SET)


def english_premier_league() -> LeagueConfig:
    return LeagueConfig(
        league_id="en_premier_league",
        league_name="English Premier League",
        country="England",
        language="en",
        openfootball_path="en.1.json",
        footballdata_country="E0",
        teams_count=20,
        rounds_per_season=38,
        promotion_slots=3,
        relegation_slots=3,
        elo_home_advantage=55.0,
        first_half_goal_pct=0.46,
        league_avg_goals=2.70,
        dixon_coles_rho=-0.11,
        derbies={
            frozenset(("Arsenal", "Tottenham")),
            frozenset(("Liverpool", "Manchester United")),
            frozenset(("Liverpool", "Everton")),
            frozenset(("Manchester United", "Manchester City")),
            frozenset(("Chelsea", "Arsenal")),
            frozenset(("Chelsea", "Tottenham")),
        },
        xgb_weight=0.35,
    )


def german_bundesliga() -> LeagueConfig:
    return LeagueConfig(
        league_id="de_bundesliga",
        league_name="German Bundesliga",
        country="Germany",
        language="de",
        openfootball_path="de.1.json",
        footballdata_country="D1",
        teams_count=18,
        rounds_per_season=34,
        promotion_slots=3,
        relegation_slots=3,
        elo_home_advantage=60.0,
        first_half_goal_pct=0.46,
        league_avg_goals=2.90,
        dixon_coles_rho=-0.12,
        derbies={
            frozenset(("Borussia Dortmund", "Schalke 04")),
            frozenset(("Bayern München", "Borussia Dortmund")),
            frozenset(("Hamburger SV", "Werder Bremen")),
        },
        xgb_weight=0.35,
    )


def spanish_la_liga() -> LeagueConfig:
    return LeagueConfig(
        league_id="es_la_liga",
        league_name="Spanish La Liga",
        country="Spain",
        language="es",
        openfootball_path="es.1.json",
        footballdata_country="SP1",
        teams_count=20,
        rounds_per_season=38,
        promotion_slots=3,
        relegation_slots=3,
        elo_home_advantage=58.0,
        first_half_goal_pct=0.47,
        league_avg_goals=2.55,
        dixon_coles_rho=-0.14,
        derbies={
            frozenset(("Real Madrid", "Barcelona")),
            frozenset(("Real Madrid", "Atlético Madrid")),
            frozenset(("Barcelona", "Atlético Madrid")),
            frozenset(("Real Madrid", "Sevilla")),
        },
        xgb_weight=0.35,
    )


LEAGUE_REGISTRY: dict[str, callable] = {
    "tr_super_lig": turkish_super_lig,
    "en_premier_league": english_premier_league,
    "de_bundesliga": german_bundesliga,
    "es_la_liga": spanish_la_liga,
}


LEAGUE_ALIASES: dict[str, str] = {
    "super_lig": "tr_super_lig",
    "turkish_super_lig": "tr_super_lig",
}


def normalize_league_id(league_id: str) -> str:
    """Map legacy IDs to canonical registry IDs."""
    if not league_id:
        return "tr_super_lig"
    return LEAGUE_ALIASES.get(league_id, league_id)


def get_available_league_ids() -> list[str]:
    """List canonical league IDs currently supported by the registry."""
    return sorted(LEAGUE_REGISTRY.keys())


def get_league_config(league_id: str = "tr_super_lig") -> LeagueConfig:
    """Get league config by ID. Falls back to Turkish Süper Lig."""
    resolved = normalize_league_id(league_id)
    factory = LEAGUE_REGISTRY.get(resolved, turkish_super_lig)
    return factory()


def compute_config_sha256(config: LeagueConfig) -> str:
    """Compute SHA256 checksum of a LeagueConfig object.
    
    Uses canonical serialization via dataclasses.asdict() to ensure
    deterministic hash across Python versions and imports (Phase 13.3.7).
    
    Args:
        config: LeagueConfig instance
        
    Returns:
        Hex-encoded SHA256 hash (64 chars)
    """
    import hashlib
    import json
    from dataclasses import asdict
    
    def _serialize_special(obj):
        """Custom serializer for non-JSON types, with deterministic ordering."""
        if isinstance(obj, frozenset):
            # For frozenset (e.g., a single derby pair like frozenset({'Team A', 'Team B'}))
            # Convert to sorted list of strings for JSON serialization
            return sorted([str(i) for i in obj])
        elif isinstance(obj, set):
            # For regular sets (e.g., the derbies field is a set of frozensets)
            # Need to recursively handle frozensets inside the set
            items = []
            for item in obj:
                if isinstance(item, frozenset):
                    # Recursively serialize each frozenset to a sorted list
                    items.append(sorted([str(i) for i in item]))
                else:
                    # Handle other types in the set
                    items.append(str(item))
            # Sort the list of items for determinism
            return sorted(items)
        # For other types, use str()
        return str(obj)
    
    # Convert to dict with deterministic serialization
    config_dict = asdict(config)
    
    # Serialize to JSON with sorted keys for determinism.
    # Use ensure_ascii=False to avoid Unicode escaping changes,
    # then encode UTF-8 for consistent byte representation.
    canonical_json = json.dumps(
        config_dict,
        sort_keys=True,
        separators=(',', ':'),
        default=_serialize_special,
        ensure_ascii=False,
    )
    
    # Compute SHA256 over UTF-8 bytes
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
