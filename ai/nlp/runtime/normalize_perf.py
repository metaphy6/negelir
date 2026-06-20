"""Phase 10 §10.34.2 — Normalize-chain per-pass performance measurement.

Tracks timing for each normalize pass and emits telemetry on budget violations.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Optional
import yaml

from ai.common.telemetry import get_sink


@dataclass
class PerPassTiming:
    """Timing measurement for a single normalize pass."""

    name: str
    elapsed_ms: float
    budget_p99_ms: Optional[float] = None
    gated: bool = False
    gate_flag: Optional[str] = None

    def exceeds_budget(self, tolerance: float = 1.10) -> bool:
        """Return True if elapsed time exceeds budget (with tolerance)."""
        if self.budget_p99_ms is None:
            return False
        return self.elapsed_ms > (self.budget_p99_ms * tolerance)


@dataclass
class NormalizePerfMeasurement:
    """Complete performance measurement for a normalize run."""

    total_elapsed_ms: float
    per_pass_timings: list[PerPassTiming] = field(default_factory=list)
    total_budget_p99_ms: Optional[float] = None
    budget_tolerance: float = 1.10
    violations: list[PerPassTiming] = field(default_factory=list)

    def check_budget(self) -> None:
        """Check budget violations and emit telemetry."""
        self.violations = [
            timing for timing in self.per_pass_timings
            if timing.exceeds_budget(self.budget_tolerance)
        ]

        for timing in self.violations:
            # Emit telemetry event (non-blocking; telemetry is best-effort)
            try:
                sink = get_sink()
                if sink and sink.enabled:
                    # Log as structured event (mirrors §10.14 pattern)
                    import logging
                    log = logging.getLogger(__name__)
                    log.warning(
                        "Normalize pass exceeded perf budget",
                        extra={
                            "structured": True,
                            "pass_name": timing.name,
                            "elapsed_ms": f"{timing.elapsed_ms:.2f}",
                            "budget_p99_ms": f"{timing.budget_p99_ms:.2f}",
                            "severity": "warn",
                        },
                    )
            except Exception:  # noqa: BLE001
                pass  # non-blocking telemetry failure


class NormalizePerfLoader:
    """Load and cache normalize per-pass budget YAML."""

    _BUDGETS_PATH: Path = Path(__file__).parent.parent / "normalize_perf_budgets.yaml"
    _CACHED_BUDGETS: Optional[dict[str, Any]] = None

    @classmethod
    def load_budgets(cls) -> dict[str, Any]:
        """Load per-pass budget table from YAML."""
        if cls._CACHED_BUDGETS is not None:
            return cls._CACHED_BUDGETS

        try:
            raw = yaml.safe_load(cls._BUDGETS_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return {}

        cls._CACHED_BUDGETS = raw
        return raw

    @classmethod
    def get_pass_budget(cls, pass_name: str) -> Optional[float]:
        """Get the p99 budget (ms) for a named pass."""
        budgets = cls.load_budgets()
        passes = budgets.get("passes", [])
        for pass_spec in passes:
            if pass_spec.get("name") == pass_name:
                return pass_spec.get("p99_ms")
        return None

    @classmethod
    def get_total_budget(cls) -> Optional[float]:
        """Get the total p99 budget (ms)."""
        budgets = cls.load_budgets()
        return budgets.get("total_budget_p99_ms")


@contextmanager
def measure_normalize_pass(
    pass_name: str,
    *,
    clock: Optional[Any] = None,
) -> Generator[NormalizePerfMeasurement | None, None, None]:
    """Context manager to measure a single normalize pass.

    Usage:
        with measure_normalize_pass("lowercase_tr") as perf:
            # ... pass implementation ...
            pass

    Emits telemetry on budget violations (if enabled).
    """
    _clock = clock or time.monotonic

    start_time = _clock()
    measurement = NormalizePerfMeasurement(total_elapsed_ms=0.0)

    try:
        yield measurement
    finally:
        elapsed = (_clock() - start_time) * 1000.0  # Convert to ms
        measurement.total_elapsed_ms = elapsed

        budget = NormalizePerfLoader.get_pass_budget(pass_name)
        timing = PerPassTiming(
            name=pass_name,
            elapsed_ms=elapsed,
            budget_p99_ms=budget,
        )
        measurement.per_pass_timings.append(timing)
        measurement.check_budget()
