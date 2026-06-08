#!/usr/bin/env python3
"""Phase 12 §12.7.2 — Noise-aware load test comparison.

Implements mean ± stdev baseline comparison with hard-floor fallback,
so load-test regressions are caught while noisy runners don't produce
false failures.

Config knobs (xops/env/.env.example):
  NEGELIR_LOAD_BASELINE_STDEV_MULTIPLIER (default 2.0)
  NEGELIR_LOAD_BASELINE_HARD_FLOOR_MS (default 500)
  NEGELIR_LOAD_BASELINE_DIR (default docs/reports/load-baselines)

Baseline storage:
  Baselines are stored as JSON in NEGELIR_LOAD_BASELINE_DIR/
  Each baseline file is named: <surface>_<percentile>.json
  E.g.: api_p99.json, nlp_p95.json, predictor_p50.json

Baseline format:
  {
    "surface": "api",
    "percentile": "p99",
    "samples": [...],
    "mean_ms": 123.45,
    "stdev_ms": 12.34,
    "min_ms": 100.0,
    "max_ms": 150.0,
    "updated_at": "2026-06-08T10:30:00Z"
  }
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from _common import err, warn, info, ok, step


@dataclass
class LoadBaseline:
    """A load test baseline with statistics."""
    surface: str  # "api", "nlp", "predictor"
    percentile: str  # "p50", "p95", "p99"
    samples: list[float]  # raw measurements in ms
    mean_ms: float
    stdev_ms: float
    min_ms: float
    max_ms: float
    updated_at: str  # ISO 8601 timestamp


def load_baseline(surface: str, percentile: str, baseline_dir: Path) -> Optional[LoadBaseline]:
    """Load a baseline from disk.
    
    Args:
        surface: "api", "nlp", or "predictor"
        percentile: "p50", "p95", or "p99"
        baseline_dir: Directory containing baseline JSON files
        
    Returns:
        LoadBaseline if found, None otherwise
    """
    baseline_file = baseline_dir / f"{surface}_{percentile}.json"
    
    if not baseline_file.is_file():
        warn(f"Baseline not found: {baseline_file}")
        return None
    
    try:
        with open(baseline_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return LoadBaseline(**data)
    except (OSError, json.JSONDecodeError, TypeError) as e:
        err(f"Failed to load baseline {baseline_file}: {e}")
        return None


def save_baseline(baseline: LoadBaseline, baseline_dir: Path) -> bool:
    """Save a baseline to disk.
    
    Args:
        baseline: LoadBaseline to save
        baseline_dir: Directory where baseline will be stored
        
    Returns:
        True if successful, False otherwise
    """
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_file = baseline_dir / f"{baseline.surface}_{baseline.percentile}.json"
    
    try:
        with open(baseline_file, "w", encoding="utf-8") as fh:
            json.dump(asdict(baseline), fh, indent=2)
        ok(f"Saved baseline: {baseline_file}")
        return True
    except OSError as e:
        err(f"Failed to save baseline {baseline_file}: {e}")
        return False


def compute_baseline(surface: str, percentile: str, samples: list[float]) -> LoadBaseline:
    """Compute statistics from raw samples and return a baseline."""
    if not samples:
        raise ValueError("Cannot compute baseline with zero samples")
    
    mean = statistics.mean(samples)
    stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    
    return LoadBaseline(
        surface=surface,
        percentile=percentile,
        samples=samples,
        mean_ms=round(mean, 2),
        stdev_ms=round(stdev, 2),
        min_ms=round(min(samples), 2),
        max_ms=round(max(samples), 2),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def compare_with_baseline(
    current_value_ms: float,
    baseline: LoadBaseline,
    stdev_multiplier: float = 2.0,
    hard_floor_ms: float = 500.0,
) -> tuple[bool, str]:
    """Compare a current measurement against a baseline using noise-aware thresholding.
    
    Logic:
      1. Compute acceptable threshold = baseline.mean + (stdev_multiplier * baseline.stdev)
      2. Apply hard floor: threshold = max(threshold, hard_floor_ms)
      3. Pass if current_value <= threshold, else fail
      
    Args:
        current_value_ms: Current measured latency in milliseconds
        baseline: LoadBaseline to compare against
        stdev_multiplier: Number of standard deviations to allow (default 2.0)
        hard_floor_ms: Absolute minimum threshold regardless of stdev (default 500.0)
        
    Returns:
        (pass: bool, reason: str)
    """
    threshold_no_floor = baseline.mean_ms + (stdev_multiplier * baseline.stdev_ms)
    threshold = max(threshold_no_floor, hard_floor_ms)
    
    passed = current_value_ms <= threshold
    reason = (
        f"Current {current_value_ms:.1f}ms vs threshold {threshold:.1f}ms "
        f"(baseline {baseline.mean_ms:.1f}ms ± {baseline.stdev_ms:.1f}ms × {stdev_multiplier})"
    )
    
    return passed, reason


def report_load_test(
    surface: str,
    percentile: str,
    current_samples: list[float],
    baseline: Optional[LoadBaseline] = None,
    stdev_multiplier: float = 2.0,
    hard_floor_ms: float = 500.0,
    baseline_dir: Optional[Path] = None,
    should_update_baseline: bool = False,
) -> bool:
    """Run a complete load test report with baseline comparison.
    
    Args:
        surface: "api", "nlp", or "predictor"
        percentile: "p50", "p95", or "p99"
        current_samples: List of latency measurements in ms
        baseline: LoadBaseline to compare against (will load if None and baseline_dir provided)
        stdev_multiplier: Number of stdevs to allow
        hard_floor_ms: Hard minimum threshold in ms
        baseline_dir: Directory for baseline storage
        should_update_baseline: If True, save the current run as the new baseline
        
    Returns:
        True if test passed (or baseline didn't exist), False if regression detected
    """
    if not current_samples:
        err("No samples provided for load test")
        return False
    
    current_baseline = compute_baseline(surface, percentile, current_samples)
    
    # If no baseline provided and we have a directory, try to load it
    if baseline is None and baseline_dir:
        baseline = load_baseline(surface, percentile, baseline_dir)
    
    # If we should update, save first and always pass
    if should_update_baseline:
        if baseline_dir:
            save_baseline(current_baseline, baseline_dir)
        info(f"Updated baseline: {surface} {percentile}")
        return True
    
    # If no baseline exists, this is the first run — save it and pass
    if baseline is None:
        if baseline_dir:
            save_baseline(current_baseline, baseline_dir)
            info(f"Established new baseline: {surface} {percentile}")
        else:
            warn(f"No baseline and no baseline_dir provided; skipping comparison")
        return True
    
    # Compare current against baseline
    passed, reason = compare_with_baseline(
        current_baseline.mean_ms,
        baseline,
        stdev_multiplier,
        hard_floor_ms,
    )
    
    step(f"Load test {surface} {percentile}: {reason}")
    
    if passed:
        ok(f"✓ {surface} {percentile} PASSED")
    else:
        err(f"✗ {surface} {percentile} REGRESSED")
    
    return passed


# Dispatch table for xops.makefile.chaos
COMMANDS = {
    "compare": lambda argv: compare_with_baseline,  # Exported for use in other modules
}
