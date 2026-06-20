"""Turkish Süper Lig preset configuration for Negelir Phase 13.

This module exposes a single CONFIG constant containing all league-specific
parameters, following Phase 13.3 discipline:
- Structural data only (no computed values, no os.environ, no function calls)
- No side effects at import time
- Supports auditability via config checksum (Phase 13.21)
"""

from ai.common.league_config import LeagueConfig

# Turkish Süper Lig with empirically tuned parameters
# Derbies defined per competition rules
CONFIG = LeagueConfig(
    # Identity
    league_id="tr_super_lig",
    league_name="Turkish Süper Lig",
    country="Turkey",
    language="tr",
    
    # External source mapping
    openfootball_path="tr.1.json",
    footballdata_country="T1",
    
    # Structure (19 teams, double round-robin = 38 matches)
    teams_count=19,
    rounds_per_season=38,
    promotion_slots=3,
    relegation_slots=4,
    
    # Elo parameters (calibrated on 15+ years TR Süper Lig history)
    elo_initial=1500.0,
    elo_k=32.0,
    elo_home_advantage=65.0,
    
    # Goal distribution (empirical from 2015-2025 seasons)
    first_half_goal_pct=0.47,
    league_avg_goals=2.65,
    
    # Poisson limits
    poisson_max_goals=7,
    poisson_ht_max_goals=5,
    poisson_home_goal_cap=7,
    poisson_away_goal_cap=7,
    poisson_draw_goal_cap=5,
    poisson_market_goal_cap=6,
    min_xg_floor=0.3,
    
    # Dixon-Coles low-scoring adjustment (rho parameter)
    dixon_coles_rho=-0.13,
    
    # Elo → xG adjustment curve
    elo_xg_divisor=600.0,
    xg_elo_factor_min=0.7,
    xg_elo_factor_range=0.6,
    
    # Venue-specific xG ratio bounds
    venue_ratio_floor=0.7,
    venue_ratio_ceiling=1.4,
    
    # Derby pairs (classic rivalries)
    derbies={
        frozenset(("Galatasaray", "Fenerbahçe")),  # Intercontinental Derby
        frozenset(("Galatasaray", "Beşiktaş")),   # Marmara Derby
        frozenset(("Fenerbahçe", "Beşiktaş")),    # Bosphorus Derby
        frozenset(("Istanbul Basaksehir", "Galatasaray")),
        frozenset(("Istanbul Basaksehir", "Fenerbahçe")),
        frozenset(("Istanbul Basaksehir", "Beşiktaş")),
    },
    
    # Ensemble weights
    xgb_weight=0.35,
    
    # Draw detection thresholds
    draw_ha_gap_threshold=0.15,
    draw_prob_threshold=0.26,
    draw_bayesian_threshold=0.20,
    
    # XGBoost hyperparameters
    xgb_n_estimators=300,
    xgb_max_depth=4,
    xgb_learning_rate=0.08,
    xgb_min_child_weight=3,
    xgb_reg_alpha=0.5,
    xgb_reg_lambda=1.5,
    xgb_subsample=0.8,
    xgb_colsample_bytree=0.8,
    xgb_gamma=0.1,
    
    # Training
    draw_sample_weight=2.0,
    val_split=0.15,
    train_pct=0.75,
    
    # Confidence calibration
    calibrate_probabilities=True,
    
    # Demo / showcase strings
    demo_label="Turkish Q&A Demo",
    demo_sentiment_samples=[
        "Galatasaray son maçta muhteşem bir galibiyet aldı, takım morali çok yüksek",
        "Fenerbahçe'de sakatlık krizi devam ediyor, taraftar moral bozuk",
        "Beşiktaş istikrarlı oynuyor, savunma sağlam gidiyor",
    ],
)

# Checksum for audit trail & drift detection (Phase 13.21)
# Precomputed via compute_config_sha256(CONFIG) over canonical dataclasses.asdict()
# Computed in the canonical import context (PYTHONPATH=ai, with ROOT in sys.path)
CONFIG_SHA256 = "2724121b5ebabe470aaeb37e418fc8d0a21107154353c0ea447c81f95db71529"

__all__ = ["CONFIG", "CONFIG_SHA256"]
