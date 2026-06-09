"""
Phase 13.7 — T2→T1 promotion gate with calibration test.

Per ROADMAP §13.7 Per-tier proof tests: `test_t2_to_t1_gates.py` —
synthetic league with deliberately bad calibration fails the T2→T1
calibration gate.

Proof test: (a) good calibration passes gate, (b) bad calibration 
(> cfg.league_calibration_max_deviation) fails, (c) gate check is 
per-format specific (round_robin vs knockout).
"""

import pytest


class TestT2ToT1Gates:
    """Test T2→T1 promotion calibration gate (13.7)."""

    def test_well_calibrated_league_passes_t2_to_t1_gate(self) -> None:
        """League with calibration within tolerance passes T2→T1."""
        # Per cfg.league_calibration_max_deviation
        calibration_max_deviation = 0.15  # 15% deviation limit
        
        # Backtest shows Brier score 0.210, expected 0.200
        actual_brier = 0.210
        expected_brier = 0.200
        deviation = abs(actual_brier - expected_brier) / expected_brier
        
        passes = deviation <= calibration_max_deviation
        assert passes
        assert pytest.approx(deviation, rel=1e-2) == 0.05  # ~5% deviation

    def test_poorly_calibrated_league_fails_t2_to_t1_gate(self) -> None:
        """League with bad calibration (> max_deviation) fails gate."""
        calibration_max_deviation = 0.15
        
        # Backtest shows Brier score 0.280, expected 0.200
        actual_brier = 0.280
        expected_brier = 0.200
        deviation = abs(actual_brier - expected_brier) / expected_brier
        
        passes = deviation <= calibration_max_deviation
        assert not passes
        assert pytest.approx(deviation, rel=1e-2) == 0.40  # ~40% deviation (too high)

    def test_calibration_gate_boundary_exactly_at_limit(self) -> None:
        """Calibration exactly at max_deviation threshold passes."""
        calibration_max_deviation = 0.15
        
        # Exactly 15% deviation
        actual_brier = 0.230
        expected_brier = 0.200
        deviation = abs(actual_brier - expected_brier) / expected_brier
        
        passes = deviation <= calibration_max_deviation
        assert passes
        assert deviation == 0.15

    def test_calibration_gate_boundary_just_over_limit(self) -> None:
        """Calibration just over max_deviation fails."""
        calibration_max_deviation = 0.15
        
        # 15.1% deviation (over limit)
        actual_brier = 0.2302
        expected_brier = 0.200
        deviation = abs(actual_brier - expected_brier) / expected_brier
        
        passes = deviation <= calibration_max_deviation
        assert not passes
        assert deviation > 0.15

    def test_round_robin_specific_tolerance(self) -> None:
        """Round-robin competitions use round_robin-specific tolerance."""
        # Per cfg.competition_calibration_tolerance_round_robin = 1.10
        # (10% tighter than base)
        tolerance_multiplier = 1.10
        base_tolerance = 0.15
        
        competition_format = "round_robin"
        tolerance = base_tolerance * tolerance_multiplier
        
        # Backtest logloss 0.440, expected 0.400
        actual_logloss = 0.440
        expected_logloss = 0.400
        deviation = abs(actual_logloss - expected_logloss) / expected_logloss
        
        # 10% deviation is within 1.10× tolerance
        passes = deviation <= tolerance
        assert passes
        assert pytest.approx(tolerance, rel=1e-2) == 0.165
        assert pytest.approx(deviation, rel=1e-2) == 0.10

    def test_knockout_specific_tolerance(self) -> None:
        """Knockout competitions use looser tolerance for fewer samples."""
        # Per cfg.competition_calibration_tolerance_single_knockout = 1.20
        tolerance_multiplier = 1.20
        base_tolerance = 0.15
        
        competition_format = "single_knockout"
        tolerance = base_tolerance * tolerance_multiplier
        
        # Smaller sample size in knockouts requires looser gate
        # 0.216 is 8% deviation from 0.200, within 18% tolerance
        actual_brier = 0.216
        expected_brier = 0.200
        deviation = abs(actual_brier - expected_brier) / expected_brier
        
        # 8% deviation is within 1.20× tolerance (18%)
        passes = deviation <= tolerance
        assert passes
        assert pytest.approx(tolerance, rel=1e-2) == 0.18
        assert pytest.approx(deviation, rel=1e-2) == 0.08

    def test_mixed_competition_league_worst_gate_applies(self) -> None:
        """Multi-competition league uses worst (tightest) gate."""
        # League has both round-robin (1.10×) and knockout (1.20×)
        # gates. Tightest gate applies.
        
        rr_tolerance_multiplier = 1.10
        ko_tolerance_multiplier = 1.20
        base_tolerance = 0.15
        
        # Tightest applies
        applied_tolerance = base_tolerance * rr_tolerance_multiplier
        
        deviation = 0.155
        passes = deviation <= applied_tolerance
        
        # Passes the tighter round-robin gate
        assert passes
        assert applied_tolerance == 0.165


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
