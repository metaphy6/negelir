#!/usr/bin/env python3
"""Phase 18.3 §18.3 — Resurrection lint for ai/ tree.

Ledger #4: Two-PR sequence for ai/ deletion.

After the first PR deletes ai/ and lands this lint, a deprecation window
(`cfg.ai_tree_removal_window_days`, default 14) allows stray commits to
revert deletions. This lint refuses any PR that re-adds files to ai/
during the window.

After the window, the lint becomes a permanent CI gate (`test_ai_tree_gone.py`).

This lint is stateless and deterministic: it checks if any paths matching
the ai/ tree pattern have been re-added since their deletion.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def check_ai_tree_resurrection(debug: bool = False) -> tuple[bool, list[str]]:
    """Check if ai/ has been resurrected.
    
    Returns:
        (is_clean, violations) where:
        - is_clean: True if ai/ tree is absent or only contains .gitkeep
        - violations: list of paths that violate the gate
    """
    ai_root = REPO_ROOT / "ai"
    violations = []
    
    if not ai_root.exists():
        if debug:
            print(f"✓ ai/ does not exist", file=sys.stderr)
        return True, []
    
    # If ai/ exists, scan it for real files
    for item in ai_root.rglob("*"):
        # Skip __pycache__ and .gitkeep
        if "__pycache__" in item.parts:
            continue
        if item.name == ".gitkeep":
            continue
        if item.is_dir():
            continue
        
        # Any non-trivial file is a violation
        violations.append(str(item.relative_to(REPO_ROOT)))
    
    if debug:
        if violations:
            print(f"✗ Found {len(violations)} files in ai/:", file=sys.stderr)
            for v in violations:
                print(f"  - {v}", file=sys.stderr)
        else:
            print(f"✓ ai/ is clean (no real files)", file=sys.stderr)
    
    return len(violations) == 0, violations


def main(argv: list[str]) -> int:
    """Main entry point for resurrection lint.
    
    Usage: ai_tree_resurrection.py [--debug]
    
    Exit code:
        0 if ai/ is properly absent or shim-only
        1 if ai/ has been resurrected with real files
    """
    debug = "--debug" in argv
    
    is_clean, violations = check_ai_tree_resurrection(debug=debug)
    
    if is_clean:
        print("✓ Gate PASS: ai/ tree is absent or shim-only")
        print("  (Phase 22 §22.4 deletion may proceed)")
        return 0
    else:
        print(f"✗ Gate FAIL: ai/ tree has been resurrected", file=sys.stderr)
        print(f"  Found {len(violations)} file(s) in ai/:", file=sys.stderr)
        for v in violations:
            print(f"    {v}", file=sys.stderr)
        print(f"  Phase 22 §22.4 deletion is BLOCKED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
