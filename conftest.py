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
_root_str = str(ROOT)

# Phase 18 transitional layout: ai/common exists, root/common doesn't
# Phase 22+ layout: root/common exists, ai/ tree is deleted
# Check if root/common/config/__init__.py exists to determine which phase we're in
_phase22_layout = (ROOT / "common" / "config" / "__init__.py").exists()

if _phase22_layout:
    # Phase 22+: Ensure repo root is at the front of sys.path
    # This allows top-level 'common' to be found before 'ai/common'
    if _root_str in sys.path:
        sys.path.remove(_root_str)
    sys.path.insert(0, _root_str)
else:
    # Phase 18: Keep ai/ in sys.path so ai.common imports work
    # Don't manipulate sys.path to prefer root/common since it doesn't exist
    pass


def pytest_configure(config):  # noqa: D401
    """Configure pytest for repo root level.
    
    Phase 22.3b: Marker registrations moved to tests/conftest.py to avoid
    duplication when both root and tests/conftest.py are loaded.
    This conftest handles sys.path setup for the whole project.
    """
    if _phase22_layout:
        # Double-check that repo root is still first (it should be, but just in case)
        if _root_str in sys.path:
            sys.path.remove(_root_str)
        sys.path.insert(0, _root_str)
        
        # If 'common' was imported as 'ai/common' (due to PYTHONPATH=ai being set first),
        # clear it from sys.modules so that subsequent imports resolve to the top-level common
        if 'common' in sys.modules:
            common_module = sys.modules['common']
            if hasattr(common_module, '__file__') and common_module.__file__:
                if '/ai/common' in common_module.__file__:
                    # This is ai/common; remove it so the top-level common is imported next time
                    sys.modules.pop('common', None)
                    # Also remove any submodules of ai/common
                    modules_to_remove = [k for k in sys.modules.keys() if k.startswith('common.')]
                    for k in modules_to_remove:
                        sys.modules.pop(k, None)
    
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
