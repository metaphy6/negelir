"""Top-level pytest config.

Adds the workspace root to ``sys.path`` so ``ai.*`` and ``xops.*``
imports resolve from any test file location, and registers custom
markers used across the suite.
"""

from __future__ import annotations

import os
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


import pytest  # noqa: E402 — must come after sys.path is populated above


@pytest.fixture(autouse=True, scope="session")
def _enforce_backup_dir_permissions():
    """Tighten data/backups/ file permissions to 0o600 once per test session.

    MaintBackupAgent._enforce_startup_permissions() refuses to start when any
    file under data/backups/ has mode > 0o600.  The two tracked files
    (audit.csv, dr_drills.csv) are sometimes checked out at 0o664 on
    developer machines, causing BackupPermissionError in every test that calls
    build_agents().  Git does not track the lower 3 permission bits so a
    chmod here does not produce a working-tree diff.
    """
    backup_dir = ROOT / "data" / "backups"
    if backup_dir.is_dir():
        for path in backup_dir.iterdir():
            if path.is_file():
                current = path.stat().st_mode & 0o777
                if current > 0o600:
                    os.chmod(path, 0o600)
