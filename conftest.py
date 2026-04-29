"""Top-level pytest config.

Adds the workspace root to ``sys.path`` so ``ai.*`` and ``xops.*``
imports resolve from any test file location, and registers custom
markers used across the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):  # noqa: D401
    config.addinivalue_line(
        "markers",
        "live: opt-in tests that hit real upstreams (RUN_LIVE_TESTS=1)",
    )
    config.addinivalue_line(
        "markers",
        "cpu_only: Phase 11 parity tests — predictor / model output must be "
        "identical (or within ε) on CPU vs the chosen device.",
    )
    config.addinivalue_line(
        "markers",
        "slow: tests that take noticeable wall time (CPU/GPU parity sweeps, "
        "full-pipeline runs). Excluded by `make test.fast`; included by "
        "`make test.ai` and CI.",
    )
