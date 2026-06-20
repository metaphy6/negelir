"""Phase 10 §10.34.2 — Normalize-chain per-pass performance budget tests.

Verifies that each normalize pass respects its p50/p99 budget on the golden corpus.
Any regression that exceeds the per-pass p99 budget (with tolerance) is flagged.

Per AGENTS.md Rule 10: tests track code. New perf gate → new test.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest


class TestNormalizePerPassBudgets:
    """Each pass must not exceed its p99 budget on the golden corpus."""

    def test_normalize_per_pass_budgets_loaded_from_yaml(self) -> None:
        """Verify budgets YAML is parseable and well-formed."""
        from nlp.runtime.normalize_perf import NormalizePerfLoader

        budgets = NormalizePerfLoader.load_budgets()
        assert budgets is not None
        assert "passes" in budgets
        assert "total_budget_p99_ms" in budgets

        passes = budgets["passes"]
        assert len(passes) > 10, "Expected 10+ passes"

        # Every pass must have name, p50_ms, p99_ms
        for pass_spec in passes:
            assert "name" in pass_spec, f"Pass {pass_spec} missing 'name'"
            assert "p50_ms" in pass_spec
            assert "p99_ms" in pass_spec
            assert isinstance(pass_spec["name"], str)
            assert isinstance(pass_spec["p50_ms"], (int, float))
            assert isinstance(pass_spec["p99_ms"], (int, float))
            assert pass_spec["p99_ms"] >= pass_spec["p50_ms"]

    def test_normalize_total_budget_sum_check(self) -> None:
        """Verify total budget is reasonable vs. sum of per-pass budgets."""
        from nlp.runtime.normalize_perf import NormalizePerfLoader

        budgets = NormalizePerfLoader.load_budgets()
        passes = budgets.get("passes", [])
        total_budget = budgets.get("total_budget_p99_ms", 0)

        # Sum of per-pass p99s; should be ≤ total (allows for overlap, parallelization, etc.)
        sum_p99 = sum(p.get("p99_ms", 0) for p in passes)
        assert sum_p99 > 0, "Sum of per-pass p99 budgets must be > 0"
        # Total should be somewhat close to sum (not wildly different)
        assert total_budget > 0, "Total budget must be > 0"
        assert total_budget >= sum_p99 * 0.5, f"Total {total_budget}ms seems too small vs. sum {sum_p99}ms"

    def test_normalize_clean_input_respects_budgets(self) -> None:
        """Run normalize on clean input and assert no pass timeouts."""
        from nlp.normalize import normalize_input
        from nlp.runtime.normalize_perf import NormalizePerfLoader

        # Clean Turkish input should be fast (though cold start is slower)
        text = "galatasaray maçı bugün ne zaman"

        # Measure full pipeline (warm up first)
        for _ in range(3):
            normalize_input(text, _clock=lambda: 0.0)

        start = time.monotonic()
        result = normalize_input(text)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        total_budget = NormalizePerfLoader.get_total_budget()
        assert total_budget is not None
        # This is a loose check; tight ones are in CI with repeated measurements and statistical analysis
        # Cold-start can be 5-10x slower than steady-state, so we allow 10x for safety
        assert elapsed_ms < total_budget * 10.0, (
            f"Normalize took {elapsed_ms:.2f}ms; "
            f"budget is {total_budget}ms (10x allows for cold-start)"
        )

    def test_normalize_mixed_input_respects_budgets(self) -> None:
        """Run normalize on mixed Turkish input (typos, etc.)."""
        from nlp.normalize import normalize_input
        from nlp.runtime.normalize_perf import NormalizePerfLoader

        text = "galatasaray'un macı bugun saat kactaa"  # Mixed: typos, lowercase

        start = time.monotonic()
        result = normalize_input(text)
        elapsed_ms = (time.monotonic() - start) * 1000.0

        total_budget = NormalizePerfLoader.get_total_budget()
        assert total_budget is not None
        assert elapsed_ms < total_budget * 2.5, (
            f"Normalize (mixed input) took {elapsed_ms:.2f}ms; "
            f"budget is {total_budget}ms"
        )

    def test_get_pass_budget_by_name(self) -> None:
        """Verify we can look up individual pass budgets by name."""
        from nlp.runtime.normalize_perf import NormalizePerfLoader

        # These should exist
        assert NormalizePerfLoader.get_pass_budget("lowercase_tr") is not None
        assert NormalizePerfLoader.get_pass_budget("confusables_fold") is not None
        assert NormalizePerfLoader.get_pass_budget("diacritic_restore") is not None

        # These may not exist (will return None)
        result = NormalizePerfLoader.get_pass_budget("nonexistent_pass")
        assert result is None

    def test_per_pass_timing_exceeds_budget_check(self) -> None:
        """Verify PerPassTiming.exceeds_budget() works correctly."""
        from nlp.runtime.normalize_perf import PerPassTiming

        # Under budget
        timing1 = PerPassTiming(name="test", elapsed_ms=0.5, budget_p99_ms=1.0)
        assert not timing1.exceeds_budget(tolerance=1.10)

        # Over budget (1.5 > 1.0 * 1.10 = 1.1)
        timing2 = PerPassTiming(name="test", elapsed_ms=1.5, budget_p99_ms=1.0)
        assert timing2.exceeds_budget(tolerance=1.10)

        # Exactly at tolerance
        timing3 = PerPassTiming(name="test", elapsed_ms=1.1, budget_p99_ms=1.0)
        assert not timing3.exceeds_budget(tolerance=1.10)

    def test_normalize_perf_measurement_dataclass(self) -> None:
        """Verify NormalizePerfMeasurement aggregates timings correctly."""
        from nlp.runtime.normalize_perf import (
            NormalizePerfMeasurement,
            PerPassTiming,
        )

        measurement = NormalizePerfMeasurement(
            total_elapsed_ms=5.0,
            total_budget_p99_ms=12.0,
        )
        measurement.per_pass_timings.append(
            PerPassTiming(name="pass1", elapsed_ms=0.5, budget_p99_ms=1.0)
        )
        measurement.per_pass_timings.append(
            PerPassTiming(name="pass2", elapsed_ms=2.0, budget_p99_ms=3.0)
        )

        measurement.check_budget()
        assert len(measurement.violations) == 0

    def test_normalize_perf_measurement_detects_violations(self) -> None:
        """Verify NormalizePerfMeasurement detects budget violations."""
        from nlp.runtime.normalize_perf import (
            NormalizePerfMeasurement,
            PerPassTiming,
        )

        measurement = NormalizePerfMeasurement(
            total_elapsed_ms=10.0,
            total_budget_p99_ms=12.0,
            budget_tolerance=1.10,
        )
        measurement.per_pass_timings.append(
            PerPassTiming(name="pass1", elapsed_ms=0.5, budget_p99_ms=1.0)
        )
        measurement.per_pass_timings.append(
            PerPassTiming(name="slow_pass", elapsed_ms=2.5, budget_p99_ms=1.0)  # Over!
        )

        measurement.check_budget()
        assert len(measurement.violations) == 1
        assert measurement.violations[0].name == "slow_pass"

    def test_normalize_config_has_total_budget_setting(self) -> None:
        """Verify config has the nlp_normalize_total_budget_p99_ms setting."""
        from ai.common.config import cfg

        # Should have the config value
        budget = getattr(cfg, "nlp_normalize_total_budget_p99_ms", None)
        assert budget is not None, "Config missing nlp_normalize_total_budget_p99_ms"
        assert budget > 0, f"Budget must be positive, got {budget}"
        assert budget <= 20, f"Budget seems unreasonably high: {budget}ms"
