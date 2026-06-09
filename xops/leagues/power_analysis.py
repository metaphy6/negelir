"""
Power analysis for Phase 13.5.7 — statistical adequacy of backtest corpora.

Computes the minimum N matches needed to detect a cfg.league_calibration_max_deviation-
sized effect with power 0.8, α 0.05 (two-tailed Bernoulli test).

Reference: Rosner (2021) "Fundamentals of Biostatistics", or any frequentist
power calculation toolbox (scipy.stats, statsmodels, or simple approximation).
"""

import math
from typing import Dict, Any

# Phase 13.5 doctrine: league corpora must carry sufficient power to reject
# null (coin-flip calibration) when actual deviation is cfg.league_calibration_max_deviation.


def power_analysis_binomial(
    effect_size: float,
    alpha: float = 0.05,
    power: float = 0.8,
    two_tailed: bool = True,
) -> float:
    """
    Computes minimum sample size N for a two-tailed Bernoulli test.
    
    Args:
        effect_size: Standardized deviation (e.g., 0.12 = league_calibration_max_deviation)
        alpha: Type I error (default 0.05)
        power: Statistical power (default 0.8 per Phase 13.5.7)
        two_tailed: Whether test is two-tailed (default True)
    
    Returns:
        Minimum N matches required.
    
    Note:
        Uses normal approximation (Fleiss, Tytun, Ury).
        For exact Bayesian or permutation-based power, use statsmodels or external tools.
    """
    z_alpha = 1.96 if two_tailed else 1.645  # Critical value for alpha
    z_beta = 0.842  # Critical value for power=0.8 (1 - beta)
    
    # Fleiss approximation for Bernoulli power
    # n ≈ (z_alpha + z_beta)^2 * (p0*(1-p0) + p1*(1-p1)) / (p1 - p0)^2
    # Assuming null p0 = 0.5 (coin flip), alternative p1 = 0.5 + effect_size
    p0 = 0.5
    p1 = 0.5 + effect_size
    
    numerator = (z_alpha + z_beta) ** 2 * (p0 * (1 - p0) + p1 * (1 - p1))
    denominator = (p1 - p0) ** 2
    
    if denominator == 0:
        return float('inf')
    
    n = numerator / denominator
    return math.ceil(n)


def compute_minimum_corpus_size(
    league_calibration_max_deviation: float,
) -> Dict[str, Any]:
    """
    Computes minimum corpus size for a league's calibration backtest.
    
    Per §13.5.7, if actual corpus size < minimum N, tier promotion gate
    reports "insufficient_power" rather than "pass".
    
    Args:
        league_calibration_max_deviation: From cfg.league_calibration_max_deviation
    
    Returns:
        Dict with 'min_matches', 'alpha', 'power', 'effect_size' keys.
    """
    min_n = power_analysis_binomial(
        effect_size=league_calibration_max_deviation,
        alpha=0.05,
        power=0.8,
        two_tailed=True,
    )
    
    return {
        "min_matches": min_n,
        "alpha": 0.05,
        "power": 0.8,
        "effect_size": league_calibration_max_deviation,
    }


if __name__ == "__main__":
    import sys
    from ai.common.config import cfg
    
    result = compute_minimum_corpus_size(cfg.league_calibration_max_deviation)
    print(f"Power Analysis (α=0.05, power=0.8, effect={result['effect_size']})")
    print(f"Minimum corpus size: {result['min_matches']} matches")
    sys.exit(0)
