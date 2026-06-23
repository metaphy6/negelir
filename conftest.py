"""Top-level pytest config.

Adds the workspace root to ``sys.path`` so all root packages and ``xops.*``
imports resolve from any test file location, and registers custom
markers used across the suite.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_root_str = str(ROOT)

# Phase 22+: Root layout is definitive; ai/ tree is deleted.
# Ensure repo root is at the front of sys.path so all root packages are found.
if _root_str in sys.path:
    sys.path.remove(_root_str)
sys.path.insert(0, _root_str)


def pytest_configure(config):  # noqa: D401
    """Configure pytest for repo root level.
    
    Phase 22.3b: Marker registrations moved to tests/conftest.py to avoid
    duplication when both root and tests/conftest.py are loaded.
    This conftest handles sys.path setup for the whole project.
    """
    # Double-check that repo root is still first in sys.path
    if _root_str in sys.path:
        sys.path.remove(_root_str)
    sys.path.insert(0, _root_str)
    
    # Phase 22.3b: All pytest markers consolidated in tests/conftest.py
    # Marker registrations removed here to prevent duplication warnings


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
