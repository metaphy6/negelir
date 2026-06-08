#!/usr/bin/env python3
"""
test_pyramid_shape.py — Phase 12.1 test pyramid shape enforcement.

Validates that the test suite maintains a proper pyramid shape:
  - Base (cheap, per-push): unit, property, contract
  - Middle (moderate, per-PR): integration, adversarial, regression
  - Apex (expensive, nightly+): fuzz, load, chaos, soak, mutation

A lint warns when the apex-to-base ratio inverts (a sign the cheap layers
are being skipped in favour of slow end-to-end ones).

This implements the "Shape contract" bullet in Phase 12 §12.1.1.

Exit code 0 = pyramid shape is correct, 1 = inverted ratio detected, 
2 = bad invocation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Counter

REPO_ROOT = Path(__file__).resolve().parents[2]

# Test layer categories
BASE_LAYERS = {"unit", "property", "contract"}
MIDDLE_LAYERS = {"integration", "adversarial", "regression"}
APEX_LAYERS = {"fuzz", "load", "chaos", "soak", "mutation"}

# Default threshold: apex should be at most 20% of base for a healthy pyramid
DEFAULT_APEX_TO_BASE_RATIO_THRESHOLD = 0.2


def _extract_test_counts_from_ci() -> dict[str, int]:
    """
    Extract test counts by layer from CI configuration and test files.
    
    Returns a dict mapping layer name to estimated test count.
    """
    counts = {
        "unit": 0,
        "property": 0,
        "contract": 0,
        "integration": 0,
        "adversarial": 0,
        "fuzz": 0,
        "load": 0,
        "chaos": 0,
        "soak": 0,
        "regression": 0,
        "mutation": 0,
    }
    
    # Count test files by prefix/pattern
    ai_tests_dir = REPO_ROOT / "ai" / "tests"
    if ai_tests_dir.exists():
        test_files = list(ai_tests_dir.glob("test_*.py"))
        
        for test_file in test_files:
            # Heuristic categorization based on test file name/content
            name = test_file.name.lower()
            
            # Check for property tests
            if "property" in name:
                counts["property"] += 1
            # Check for adversarial tests
            elif "adversarial" in name or "abuse" in name or "attack" in name or "injection" in name:
                counts["adversarial"] += 1
            # Check for regression tests
            elif "regression" in name or "golden" in name or "byte_identical" in name:
                counts["regression"] += 1
            # Check for contract/schema tests
            elif "schema" in name or "contract" in name or "envelope" in name:
                counts["contract"] += 1
            # Check for integration tests
            elif "integration" in name or "full_pipeline" in name or "demo" in name:
                counts["integration"] += 1
            # Check for fuzz tests
            elif "fuzz" in name:
                counts["fuzz"] += 1
            # Check for load tests
            elif "load" in name or "latency" in name or "throughput" in name:
                counts["load"] += 1
            # Check for chaos tests
            elif "chaos" in name or "fault" in name or "partition" in name:
                counts["chaos"] += 1
            # Check for soak tests
            elif "soak" in name or "leak" in name or "endurance" in name:
                counts["soak"] += 1
            # Default to unit (most tests are unit)
            else:
                counts["unit"] += 1
    
    return counts


def _read_file_safe(path: Path) -> str:
    """Read a file with graceful error handling."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def scan(threshold: float = DEFAULT_APEX_TO_BASE_RATIO_THRESHOLD) -> list[str]:
    """
    Return a list of human-readable violation strings.
    
    Checks that apex-to-base ratio is healthy (apex <= threshold * base).
    """
    violations: list[str] = []
    
    # Extract test counts
    counts = _extract_test_counts_from_ci()
    
    # Calculate totals per category
    base_total = sum(counts[layer] for layer in BASE_LAYERS)
    middle_total = sum(counts[layer] for layer in MIDDLE_LAYERS)
    apex_total = sum(counts[layer] for layer in APEX_LAYERS)
    
    # Check the pyramid shape
    if base_total == 0:
        # No tests at all (might be a fresh repo), not a violation
        return []
    
    ratio = apex_total / base_total if base_total > 0 else 0
    
    if ratio > threshold:
        violations.append(
            f"Test pyramid inverted: apex-to-base ratio is {ratio:.2f} (limit: {threshold:.2f}). "
            f"Base: {base_total}, Middle: {middle_total}, Apex: {apex_total}. "
            f"The suite is skipping cheap tests in favour of slow end-to-end ones."
        )
    
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_APEX_TO_BASE_RATIO_THRESHOLD,
        help=f"Apex-to-base ratio threshold (default: {DEFAULT_APEX_TO_BASE_RATIO_THRESHOLD})",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress 'clean' message on success",
    )
    args = parser.parse_args(argv)

    violations = scan(args.threshold)
    if violations:
        print("⚠️  test_pyramid_shape: pyramid shape warning:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nTo fix: add more cheap tests (unit/property/contract) relative to expensive ones.",
            file=sys.stderr,
        )
        return 1
    
    if not args.quiet:
        print("✅ test_pyramid_shape: pyramid is properly shaped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
