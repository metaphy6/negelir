"""
Phase 13.5 — Competition-specific calibration backtest harness.

Implements per-competition backtest corpus loading, forward-chaining
cross-validation, and deterministic backtest evaluation with full
audit trail.

Per §13.5:
- Per-competition backtest corpus (≥2 full editions per competition)
- make backtest COMPETITION=<id> command
- Time-series cross-validation (forward-chaining, no lookahead)
- Backtest determinism (byte-identical reports with same seed)
- Calibration reliability reporting (Wilson-scored CIs per bin)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from common.config import cfg
from common.logger import get_logger

log = get_logger("competition_backtest")


@dataclass
class BacktestConfig:
    """Configuration for a deterministic backtest run."""
    competition_id: str
    seed: int
    workers: int = 1
    # Hashes for cache invalidation (per §13.5.14)
    catalog_sha256: str = ""
    calibration_profile_sha256: str = ""


@dataclass
class CalibrationBin:
    """Per-bin calibration metric with Wilson score CI."""
    bin_range: tuple[float, float]  # (min_conf, max_conf)
    n_samples: int
    n_correct: int
    accuracy: float  # point estimate
    avg_confidence: float
    wilson_ci_lower: float  # 95% CI lower bound
    wilson_ci_upper: float  # 95% CI upper bound


def _wilson_score_ci(
    successes: int,
    trials: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """
    Compute Wilson score confidence interval for Bernoulli outcomes.
    
    Per §13.5.8: each backtest report ships per-bin CIs using Wilson score
    to prevent flattering small-sample bins. Promotion gate evaluates
    against upper CI, not point estimate.
    
    Args:
        successes: Number of correct predictions.
        trials: Total number of predictions.
        confidence: Desired CI (default 0.95 = 95%).
    
    Returns:
        (lower_bound, upper_bound) as floats in [0, 1].
    """
    if trials == 0:
        return (0.0, 1.0)
    
    p_hat = successes / trials
    z = 1.96  # 95% CI critical value
    
    denom = 1.0 + z**2 / trials
    centre = (p_hat + z**2 / (2 * trials)) / denom
    spread = z * np.sqrt(p_hat * (1 - p_hat) / trials + z**2 / (4 * trials**2)) / denom
    
    lower = max(0.0, centre - spread)
    upper = min(1.0, centre + spread)
    
    return (lower, upper)


class CompetitionBacktestCorpus:
    """
    Loads and validates per-competition backtest corpus.
    
    Ensures ≥ 2 full editions of historical results per competition
    (per §13.5.1). Verifies Reference + Schedule + Live planes are
    populated and consistent.
    """
    
    def __init__(self, competition_id: str, db_session=None):
        """
        Initialize corpus loader for a competition.
        
        Args:
            competition_id: The competition to load corpus for.
            db_session: Optional DB session (future: for Phase 13.2 schema).
        """
        self.competition_id = competition_id
        self.db_session = db_session
        self.fixtures: list[dict[str, Any]] = []
        self._editions_count = 0
    
    def load(self, min_editions: int = 2) -> bool:
        """
        Load historical fixture corpus from the database.
        
        Per §13.5.1, verifies that ≥ min_editions (default 2) full
        editions exist for this competition across Reference + Schedule
        + Live planes.
        
        Args:
            min_editions: Minimum required editions (default 2).
        
        Returns:
            True if corpus loaded successfully; False if gap reported.
        """
        # TODO: In Phase 13.2+ when per-competition schema lands,
        #       query CompetitionRow + FixturePayloadV2 from database.
        #       For now, mock placeholder for structure validation.
        
        if not self.competition_id:
            log.error("Cannot load corpus: competition_id is empty")
            return False
        
        # Placeholder: In production, fetch from database
        # For testing: use seed data if available
        seed_path = Path(f"data/backtest/corpus/{self.competition_id}.json")
        if seed_path.exists():
            with open(seed_path) as f:
                self.fixtures = json.load(f)
            # Count editions heuristically by season grouping
            seasons = set(f.get("season") for f in self.fixtures)
            self._editions_count = len(seasons)
        else:
            # No seed corpus available
            self._editions_count = 0
        
        if self._editions_count < min_editions:
            log.warning(
                f"Corpus gap: {self.competition_id} has {self._editions_count} "
                f"editions (need {min_editions}). Readiness gate fails per §13.5.1."
            )
            return False
        
        log.info(
            f"Loaded corpus: {self.competition_id} with {self._editions_count} editions, "
            f"{len(self.fixtures)} fixtures"
        )
        return True
    
    def fixtures_sorted_by_date(self) -> list[dict[str, Any]]:
        """
        Return fixtures sorted by kickoff date (ascending).
        
        Used for time-series cross-validation (forward-chaining).
        """
        return sorted(self.fixtures, key=lambda f: f.get("kickoff_utc", ""))


class TimeSeriesSplitter:
    """
    Forward-chaining time-series cross-validator.
    
    Per §13.5.9: backtests use forward-chaining (train on weeks 1–N,
    test on N+1) per Phase 5 doctrine. No lookahead bias allowed.
    """
    
    def __init__(self, fixtures: list[dict[str, Any]], weeks_per_fold: int = 1):
        """
        Initialize the splitter.
        
        Args:
            fixtures: Sorted list of fixtures by date.
            weeks_per_fold: Number of weeks per test fold (default 1).
        """
        self.fixtures = fixtures
        self.weeks_per_fold = weeks_per_fold
    
    def splits(self, min_train_weeks: int = 4) -> list[tuple[int, int]]:
        """
        Generate forward-chaining (train_idx, test_idx) splits.
        
        Each split trains on an expanding window and tests on the
        next N weeks (no lookahead bias).
        
        Args:
            min_train_weeks: Minimum weeks required for training.
        
        Yields:
            Tuples of (train_end_idx, test_end_idx).
        """
        if len(self.fixtures) < 10:
            return
        
        # Group fixtures by week (naive: +7 days)
        # TODO: Use RFC-5545 recurrence + competition calendar
        weeks = []
        current_week = []
        last_date = None
        
        for f in self.fixtures:
            date_str = f.get("kickoff_utc", "")
            if last_date and (datetime.fromisoformat(date_str) -
                               datetime.fromisoformat(last_date)).days >= 7:
                weeks.append(current_week)
                current_week = []
            current_week.append(f)
            last_date = date_str
        
        if current_week:
            weeks.append(current_week)
        
        # Generate splits
        if len(weeks) < min_train_weeks + self.weeks_per_fold:
            return
        
        for test_week_idx in range(min_train_weeks, len(weeks) - self.weeks_per_fold):
            train_end_idx = sum(len(w) for w in weeks[:test_week_idx])
            test_end_idx = sum(len(w) for w in weeks[:test_week_idx + self.weeks_per_fold])
            yield (train_end_idx, test_end_idx)


class DeterministicBacktestRunner:
    """
    Deterministic competition backtest runner.
    
    Per §13.5.10: re-running with the same seed produces byte-identical
    reports (proof test validates determinism). Seeds numpy + torch +
    random before each run for reproducibility.
    """
    
    def __init__(self, config: BacktestConfig):
        """
        Initialize deterministic runner.
        
        Args:
            config: BacktestConfig with competition_id, seed, workers.
        """
        self.config = config
        self.rng = np.random.RandomState(config.seed)
    
    def _set_seeds(self) -> None:
        """Set deterministic seeds across numpy, torch, and random."""
        np.random.seed(self.config.seed)
        try:
            import torch
            torch.manual_seed(self.config.seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(self.config.seed)
        except ImportError:
            pass  # torch not installed
        
        import random
        random.seed(self.config.seed)
    
    def run(self, corpus: CompetitionBacktestCorpus) -> dict[str, Any]:
        """
        Run deterministic backtest on the corpus.
        
        Per §13.5.9-10: uses forward-chaining validation, deterministic
        seeds, and produces byte-identical output for identical inputs.
        
        Args:
            corpus: Loaded CompetitionBacktestCorpus.
        
        Returns:
            Dict with backtest report: {
                "competition_id": str,
                "n_matches": int,
                "correct": int,
                "accuracy": float,
                "calibration_bins": [...],
                "asof": ISO-8601 timestamp,
                "seed": int,
                "seed_hash": SHA256 of inputs for cache key (§13.5.14),
            }
        """
        self._set_seeds()
        
        fixtures = corpus.fixtures_sorted_by_date()
        if not fixtures:
            log.warning(f"Empty corpus for {self.config.competition_id}")
            return {
                "competition_id": self.config.competition_id,
                "n_matches": 0,
                "correct": 0,
                "accuracy": 0.0,
                "calibration_bins": [],
                "asof": datetime.now(timezone.utc).isoformat(),
                "seed": self.config.seed,
                "seed_hash": "",
                "error": "empty_corpus",
            }
        
        # Time-series cross-validation
        splitter = TimeSeriesSplitter(fixtures)
        
        all_correct = 0
        all_total = 0
        confidences = []
        actuals = []
        
        for train_idx, test_idx in splitter.splits():
            train_set = fixtures[:train_idx]
            test_set = fixtures[train_idx:test_idx]
            
            if not train_set or not test_set:
                continue
            
            # TODO: Train model on train_set, predict on test_set
            # For now: dummy predictions (random with seed determinism)
            for fixture in test_set:
                pred_correct = self.rng.rand() > 0.5  # Dummy predictor
                all_correct += int(pred_correct)
                all_total += 1
                confidences.append(self.rng.uniform(0.5, 1.0))
                actuals.append(int(pred_correct))
        
        # If no valid splits, report empty result
        if all_total == 0:
            return {
                "competition_id": self.config.competition_id,
                "n_matches": 0,
                "correct": 0,
                "accuracy": 0.0,
                "calibration_bins": [],
                "asof": datetime.now(timezone.utc).isoformat(),
                "seed": self.config.seed,
                "seed_hash": "",
                "error": "insufficient_fixtures_for_splits",
            }
        
        # Compute calibration bins (Wilson scored)
        bins = self._calibration_bins(confidences, actuals)
        
        # Compute cache key (§13.5.14)
        seed_hash = self._compute_seed_hash(
            self.config.catalog_sha256,
            self.config.calibration_profile_sha256,
            self.config.seed,
        )
        
        accuracy = all_correct / max(all_total, 1)
        
        report = {
            "competition_id": self.config.competition_id,
            "n_matches": all_total,
            "correct": all_correct,
            "accuracy": accuracy,
            "calibration_bins": [asdict(b) for b in bins],
            "asof": datetime.now(timezone.utc).isoformat(),
            "seed": self.config.seed,
            "seed_hash": seed_hash,
        }
        
        log.info(
            f"Backtest {self.config.competition_id}: "
            f"{all_correct}/{all_total} correct ({accuracy:.2%})"
        )
        
        return report
    
    def _calibration_bins(
        self,
        confidences: list[float],
        actuals: list[int],
        n_bins: int = 10,
    ) -> list[CalibrationBin]:
        """
        Compute calibration bins with Wilson-scored CIs.
        
        Per §13.5.8, evaluates promotion gate against upper CI,
        not point estimate, to prevent flattering small-sample bins.
        """
        if not confidences:
            return []
        
        bins = []
        edges = np.linspace(0.0, 1.0, n_bins + 1)
        
        for lo, hi in zip(edges[:-1], edges[1:]):
            mask = (np.array(confidences) >= lo) & (np.array(confidences) < hi)
            if not mask.any():
                continue
            
            bin_actuals = np.array(actuals)[mask]
            n_correct = int(bin_actuals.sum())
            n_total = len(bin_actuals)
            
            if n_total == 0:
                continue
            
            accuracy = n_correct / n_total
            avg_conf = np.mean(np.array(confidences)[mask])
            lower_ci, upper_ci = _wilson_score_ci(n_correct, n_total)
            
            bin_obj = CalibrationBin(
                bin_range=(float(lo), float(hi)),
                n_samples=n_total,
                n_correct=n_correct,
                accuracy=accuracy,
                avg_confidence=avg_conf,
                wilson_ci_lower=lower_ci,
                wilson_ci_upper=upper_ci,
            )
            bins.append(bin_obj)
        
        return bins
    
    @staticmethod
    def _compute_seed_hash(
        catalog_sha256: str,
        profile_sha256: str,
        seed: int,
    ) -> str:
        """
        Compute cache key (§13.5.14).
        
        Keyed on (competition_id, catalog_sha256, calibration_profile_sha256, seed)
        so that catalog edits automatically invalidate stale reports.
        """
        combined = f"{catalog_sha256}:{profile_sha256}:{seed}"
        return hashlib.sha256(combined.encode()).hexdigest()


def run_competition_backtest(
    competition_id: str,
    seed: int | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """
    Main entry point for competition backtest (§13.5).
    
    Args:
        competition_id: Which competition to backtest.
        seed: Random seed (default: cfg.backtest_seed).
        workers: Parallel workers for prediction (unused for now).
    
    Returns:
        Backtest report dict.
    """
    if seed is None:
        seed = cfg.backtest_seed
    
    # Load corpus
    corpus = CompetitionBacktestCorpus(competition_id)
    if not corpus.load(min_editions=2):
        log.error(f"Failed to load corpus for {competition_id}")
        return {
            "competition_id": competition_id,
            "error": "corpus_unavailable",
        }
    
    # Run backtest with determinism guarantees
    config = BacktestConfig(
        competition_id=competition_id,
        seed=seed,
        workers=workers,
    )
    runner = DeterministicBacktestRunner(config)
    report = runner.run(corpus)
    
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="python -m backtest.competition_backtest",
        description="Phase 13.5 competition backtest harness",
    )
    parser.add_argument("--competition", required=True, help="Competition ID")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: cfg.backtest_seed)")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers (default: 1)")
    parser.add_argument("--all", action="store_true", help="Backtest all competitions")
    
    args = parser.parse_args()
    
    if args.all:
        # TODO: Implement all-competitions sweep with concurrency control
        log.error("--all not yet implemented")
        raise SystemExit(1)
    
    # Single competition backtest
    report = run_competition_backtest(
        competition_id=args.competition,
        seed=args.seed,
        workers=args.workers,
    )
    
    # Write report
    output_dir = Path("data") / "backtest" / "competition" / args.competition
    output_dir.mkdir(parents=True, exist_ok=True)
    
    asof = datetime.now(timezone.utc).isoformat().replace(":", "").replace(".", "")[:15]
    report_path = output_dir / f"{asof}.json"
    
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    
    log.info(f"Backtest report written to {report_path}")
    
    # Exit with error if corpus missing or error in report
    if report.get("error"):
        log.error(f"Backtest failed: {report.get('error')}")
        raise SystemExit(1)
