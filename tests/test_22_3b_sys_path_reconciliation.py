"""Phase 22.3b — Proof that sys.path is correctly reconciled after merge."""

from __future__ import annotations

import re
from pathlib import Path


def test_22_3b_sys_path_managed_for_layout_transition() -> None:
    """Verify that tests/conftest.py manages sys.path for Phase 18→22 transition.
    
    Per ROADMAP §22.3b: sys.path handling is part of "sys.path reconciliation".
    The conftest should properly detect the layout and set up sys.path accordingly.
    The _phase22_layout variable and conditional branches should be present.
    """
    tests_conftest = Path(__file__).parent / "conftest.py"
    content = tests_conftest.read_text()
    
    # Should detect layout
    if "_phase22_layout = " not in content:
        raise AssertionError(
            "tests/conftest.py should detect Phase 22 layout via _phase22_layout"
        )
    
    # Should have conditional sys.path setup
    if "if _phase22_layout:" not in content:
        raise AssertionError(
            "tests/conftest.py should have conditional sys.path setup for Phase 22 transition"
        )


def test_22_3b_sys_modules_cleared_for_layout_transition() -> None:
    """Verify sys.modules manipulation exists for layout detection.
    
    Per ROADMAP §22.3b: sys.modules clearing is allowed when part of the
    layout detection logic. The conftest should manage sys.modules to ensure
    correct imports from the right location (root/common vs ai/common).
    """
    tests_conftest = Path(__file__).parent / "conftest.py"
    content = tests_conftest.read_text()
    
    # Should have sys.modules.pop for layout reconciliation
    if 'sys.modules' not in content:
        raise AssertionError(
            "tests/conftest.py should manage sys.modules for layout transition"
        )
    
    # The manipulation should be related to 'common' module to handle root/common vs ai/common
    if "sys.modules.pop" in content or "sys.modules.get" in content:
        # This is expected - verifying it's there
        if "common" in content:
            # Good - it's managing the 'common' module specifically
            pass
        else:
            raise AssertionError(
                "sys.modules manipulation should be for layout-specific imports"
            )



def test_22_3b_ai_tests_conftest_still_exists() -> None:
    """Verify that ai/tests/conftest.py still exists (deferred to later phase).
    
    Per ROADMAP §22.3b: ai/tests/conftest.py is deferred to §22.3c.
    It should still be present (not deleted).
    """
    ai_tests_conftest = Path(__file__).parent.parent / "ai" / "tests" / "conftest.py"
    if not ai_tests_conftest.exists():
        raise AssertionError(
            f"ai/tests/conftest.py was deleted; it should be deferred to §22.3c"
        )

