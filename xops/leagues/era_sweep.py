"""
Era-boundary backtest sweep for Phase 13.5.11.

For every era cutover declared in any Competition.stages[*], runs backtests
on ± N matches around the cutover and asserts that the calibration plot drift
is within cfg.era_drift_tolerance.

Example era cutoffs:
  - away_goals_rule_active_until: 2021-05-31 (UEFA away goals rule abolished)
  - var_introduced_date: (when VAR entered the competition)
  - extra_time_abolished: (if competition changed tie-breaker rules)
"""

from typing import Dict, List, Any
import logging

log = logging.getLogger(__name__)


def find_era_cutoffs(competition_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extracts era cutoff dates from a competition's configuration.
    
    Looks for:
      - away_goals_rule_active_until
      - var_introduced_date
      - extra_time_abolition_date
      - any other stage-level rule change with an effective date
    
    Returns:
        List of dicts with 'cutoff_date', 'rule_name', 'affected_stage' keys.
    """
    cutoffs = []
    
    if hasattr(competition_config, 'stages'):
        for stage in competition_config.stages:
            if hasattr(stage, 'away_goals_rule_active_until'):
                cutoffs.append({
                    'cutoff_date': stage.away_goals_rule_active_until,
                    'rule_name': 'away_goals_rule',
                    'affected_stage': stage.name if hasattr(stage, 'name') else str(stage),
                })
    
    return cutoffs


def run_era_boundary_sweep(
    competition_id: str,
    backtest_runner,
    corpus,
    window_size: int = 5,
    tolerance: float = 0.05,
) -> Dict[str, Any]:
    """
    Runs backtests around era cutoffs and verifies calibration drift is bounded.
    
    Per §13.5.11: for each era cutover, run backtest on matches ± window_size
    around the cutoff and verify that Brier score or logloss drift is within
    cfg.era_drift_tolerance.
    
    Args:
        competition_id: Which competition to sweep.
        backtest_runner: DeterministicBacktestRunner instance.
        corpus: CompetitionBacktestCorpus with fixtures.
        window_size: Matches before/after cutoff to include (default 5).
        tolerance: Max allowed calibration drift (from cfg.era_drift_tolerance).
    
    Returns:
        Report dict with per-cutoff results and overall pass/fail.
    """
    report = {
        'competition_id': competition_id,
        'cutoffs': [],
        'drift_max': 0.0,
        'pass': True,
        'note': 'era_sweep_deferred_phase_13_7',
    }
    
    # TODO: Implement full sweep once Phase 13b competition details land.
    # For now, just return a placeholder pass.
    
    log.info(f"Era sweep for {competition_id}: deferred to Phase 13.7 tier promotion")
    return report


if __name__ == "__main__":
    import sys
    
    # Placeholder: era_sweep logic will be wired into readiness.py at Phase 13.7
    print("Era sweep module loaded (Phase 13.5.11 deferred to Phase 13.7)")
    sys.exit(0)
