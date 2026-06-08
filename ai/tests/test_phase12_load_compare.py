"""Phase 12 §12.7.2 — Noise-aware load test comparison tests.

Verifies that the load-comparison gate correctly:
1. Accepts measurements within mean ± stdev * multiplier
2. Rejects measurements exceeding threshold
3. Applies hard-floor correctly
4. Handles missing baselines (establish baseline on first run)
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import json
import statistics

# Mock the sys.path insertion for xops.makefile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "xops" / "makefile"))

from load_compare import (
    LoadBaseline,
    compute_baseline,
    compare_with_baseline,
    load_baseline,
    save_baseline,
    report_load_test,
)


def test_compute_baseline():
    """Test basic baseline statistics computation."""
    samples = [100.0, 110.0, 120.0, 130.0, 140.0]
    baseline = compute_baseline("api", "p99", samples)
    
    assert baseline.surface == "api"
    assert baseline.percentile == "p99"
    assert baseline.mean_ms == pytest.approx(120.0, abs=0.01)
    # stdev for sample [100, 110, 120, 130, 140] is ~15.81 (sample stdev)
    assert baseline.stdev_ms == pytest.approx(15.81, abs=0.1)
    assert baseline.min_ms == 100.0
    assert baseline.max_ms == 140.0
    assert len(baseline.samples) == 5


def test_compare_with_baseline_pass():
    """Test that measurements within threshold pass."""
    baseline = LoadBaseline(
        surface="api",
        percentile="p99",
        samples=[100.0, 110.0, 120.0, 130.0, 140.0],
        mean_ms=120.0,
        stdev_ms=14.14,
        min_ms=100.0,
        max_ms=140.0,
        updated_at="2026-06-08T00:00:00Z",
    )
    
    # With stdev_multiplier=2.0:
    # threshold = 120 + (2.0 * 14.14) = ~148.28
    # Measurement of 145 should pass
    passed, reason = compare_with_baseline(145.0, baseline, stdev_multiplier=2.0)
    assert passed, f"Should pass: {reason}"


def test_compare_with_baseline_fail():
    """Test that measurements exceeding threshold fail."""
    baseline = LoadBaseline(
        surface="api",
        percentile="p99",
        samples=[100.0, 110.0, 120.0, 130.0, 140.0],
        mean_ms=120.0,
        stdev_ms=15.81,  # actual stdev from sample
        min_ms=100.0,
        max_ms=140.0,
        updated_at="2026-06-08T00:00:00Z",
    )
    
    # With stdev_multiplier=2.0:
    # threshold = 120 + (2.0 * 15.81) = ~151.62
    # But hard_floor_ms=500, so threshold = 500
    # Use a very large hard floor so it doesn't mask the stdev calculation
    passed, reason = compare_with_baseline(160.0, baseline, stdev_multiplier=2.0, hard_floor_ms=100.0)
    assert not passed, f"Should fail: {reason}"


def test_compare_with_baseline_hard_floor():
    """Test that hard floor is enforced."""
    baseline = LoadBaseline(
        surface="api",
        percentile="p99",
        samples=[10.0, 11.0, 12.0, 13.0, 14.0],
        mean_ms=12.0,
        stdev_ms=1.41,  # small stdev
        min_ms=10.0,
        max_ms=14.0,
        updated_at="2026-06-08T00:00:00Z",
    )
    
    # Without hard floor:
    # threshold = 12 + (2.0 * 1.41) = ~14.82
    # But with hard_floor_ms=500, threshold becomes 500
    passed, reason = compare_with_baseline(
        600.0, baseline, stdev_multiplier=2.0, hard_floor_ms=500.0
    )
    assert not passed, "Should fail: 600 > 500 (hard floor)"
    
    passed, reason = compare_with_baseline(
        400.0, baseline, stdev_multiplier=2.0, hard_floor_ms=500.0
    )
    assert passed, "Should pass: 400 <= 500 (hard floor)"


def test_save_and_load_baseline():
    """Test baseline persistence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        baseline_dir = Path(tmpdir)
        
        original = LoadBaseline(
            surface="nlp",
            percentile="p95",
            samples=[200.0, 210.0, 220.0],
            mean_ms=210.0,
            stdev_ms=8.16,
            min_ms=200.0,
            max_ms=220.0,
            updated_at="2026-06-08T12:00:00Z",
        )
        
        # Save
        assert save_baseline(original, baseline_dir)
        
        # Load
        loaded = load_baseline("nlp", "p95", baseline_dir)
        assert loaded is not None
        assert loaded.surface == original.surface
        assert loaded.percentile == original.percentile
        assert loaded.mean_ms == original.mean_ms


def test_report_load_test_new_baseline():
    """Test that report_load_test establishes baseline on first run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        baseline_dir = Path(tmpdir)
        samples = [100.0, 105.0, 110.0, 115.0, 120.0]
        
        # First run — no baseline exists
        passed = report_load_test(
            surface="predictor",
            percentile="p99",
            current_samples=samples,
            baseline_dir=baseline_dir,
        )
        
        # Should pass (establishing new baseline)
        assert passed
        
        # Baseline file should now exist
        baseline_file = baseline_dir / "predictor_p99.json"
        assert baseline_file.exists()


def test_report_load_test_regression_detection():
    """Test that report_load_test detects regressions against baseline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        baseline_dir = Path(tmpdir)
        
        # Establish baseline with first run
        baseline_samples = [100.0, 105.0, 110.0, 115.0, 120.0]
        report_load_test(
            surface="api",
            percentile="p99",
            current_samples=baseline_samples,
            baseline_dir=baseline_dir,
        )
        
        # Second run: good measurement (within tolerance)
        good_samples = [102.0, 107.0, 112.0, 117.0, 122.0]
        passed = report_load_test(
            surface="api",
            percentile="p99",
            current_samples=good_samples,
            baseline_dir=baseline_dir,
            stdev_multiplier=2.0,
            hard_floor_ms=500.0,
        )
        assert passed, "Should pass: measurement within tolerance"
        
        # Third run: regressed measurement (exceeding threshold)
        regressed_samples = [500.0, 505.0, 510.0, 515.0, 520.0]
        passed = report_load_test(
            surface="api",
            percentile="p99",
            current_samples=regressed_samples,
            baseline_dir=baseline_dir,
            stdev_multiplier=2.0,
            hard_floor_ms=500.0,
        )
        assert not passed, "Should fail: measurement exceeds threshold"


def test_zero_samples_handled():
    """Test that zero samples are rejected."""
    with pytest.raises(ValueError, match="zero samples"):
        compute_baseline("api", "p99", [])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
