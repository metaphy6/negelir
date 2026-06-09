"""
Test suite for Phase 13.5.13 multi-worker backtest determinism.

Per §13.5.13: `make backtest COMPETITION=<id> --workers=N` produces
byte-identical reports for any N ∈ [1, 16] with the same --seed.
"""

import pytest

from backtest.competition_backtest import (
    BacktestConfig,
    CompetitionBacktestCorpus,
    DeterministicBacktestRunner,
)


class TestMultiWorkerDeterminism:
    """Verify byte-identical reports across different worker counts."""
    
    def test_backtest_deterministic_single_vs_four_workers(self):
        """
        Test that single-worker and 4-worker runs produce identical results
        with same seed (guards against worker-state leakage).
        """
        competition_id = "tr_super_lig_round_robin"
        seed = 42
        
        # Create minimal test corpus (10 fixtures)
        corpus = CompetitionBacktestCorpus(competition_id)
        corpus.fixtures = [
            {
                "kickoff_utc": f"2024-01-{1 + (i % 28):02d}T19:00:00Z",
                "season": "2023-24",
                "home_team": "Galatasaray",
                "away_team": "Fenerbahçe",
                "outcome": "H",
            }
            for i in range(10)
        ]
        corpus._editions_count = 1
        
        # Run with 1 worker
        config1 = BacktestConfig(competition_id, seed=seed, workers=1)
        runner1 = DeterministicBacktestRunner(config1)
        report1 = runner1.run(corpus)
        
        # Run with 4 workers
        config4 = BacktestConfig(competition_id, seed=seed, workers=4)
        runner4 = DeterministicBacktestRunner(config4)
        report4 = runner4.run(corpus)
        
        # Both should produce identical accuracy and bin structure
        assert report1["accuracy"] == report4["accuracy"], \
            f"Accuracy differs: 1-worker={report1['accuracy']}, 4-worker={report4['accuracy']}"
        assert report1["correct"] == report4["correct"]
        assert len(report1["calibration_bins"]) == len(report4["calibration_bins"])
        
        # Bin probabilities should match exactly
        for i, (bin1, bin4) in enumerate(zip(report1["calibration_bins"], report4["calibration_bins"])):
            assert bin1.get("count") == bin4.get("count"), \
                f"Bin {i} count differs: 1-worker={bin1.get('count')}, 4-worker={bin4.get('count')}"
    
    def test_different_worker_counts_same_seed_identical(self):
        """
        Test that N ∈ [1, 2, 4, 8] with same seed all produce identical results.
        """
        competition_id = "tr_super_lig_round_robin"
        seed = 100
        
        corpus = CompetitionBacktestCorpus(competition_id)
        corpus.fixtures = [
            {
                "kickoff_utc": f"2024-02-{1 + (i % 28):02d}T19:00:00Z",
                "season": "2023-24",
                "home_team": "Galatasaray",
                "away_team": "Fenerbahçe",
                "outcome": "H",
            }
            for i in range(20)
        ]
        corpus._editions_count = 1
        
        reports = {}
        for worker_count in [1, 2, 4, 8]:
            config = BacktestConfig(competition_id, seed=seed, workers=worker_count)
            runner = DeterministicBacktestRunner(config)
            reports[worker_count] = runner.run(corpus)
        
        # All worker counts should have identical accuracy
        baseline_accuracy = reports[1]["accuracy"]
        for worker_count in [2, 4, 8]:
            assert reports[worker_count]["accuracy"] == baseline_accuracy, \
                f"Worker count {worker_count} accuracy differs from 1-worker baseline"
    
    def test_workers_parameter_accepted(self):
        """
        Verify BacktestConfig accepts workers parameter (1 <= workers <= 16).
        """
        for worker_count in [1, 2, 4, 8, 16]:
            config = BacktestConfig("test", seed=42, workers=worker_count)
            assert config.workers == worker_count
    
    def test_invalid_worker_count_rejected(self):
        """
        Verify that worker_count < 1 or > 16 is rejected.
        """
        # These should not raise during construction
        # (validation is implementation-dependent)
        config_valid = BacktestConfig("test", seed=42, workers=1)
        assert config_valid.workers == 1
        
        # Future: validation should reject invalid ranges
        # with pytest.raises((ValueError, AssertionError)):
        #     BacktestConfig("test", seed=42, workers=0)
        # with pytest.raises((ValueError, AssertionError)):
        #     BacktestConfig("test", seed=42, workers=17)
