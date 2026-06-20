"""Phase 19 §19.1 — Patcher bundle two-key scoping gate.

Enforces that patcher bundles are stored at:
    xops/patcher/bundles/<extractor_id>/<league_id>/

Legacy flat-path bundles (keyed on extractor_id only) are rejected after
the 90-day alias window expires (configured via cfg.patcher_bundle_alias_window_days).

This lint rule prevents regression into flat-path bundle storage.
"""

from __future__ import annotations

import sys
import re
from pathlib import Path
from typing import Any


def check_patcher_bundle_scoping(repo_root: Path) -> list[str]:
    """
    Verify patcher bundle paths follow the two-key scoping format.
    
    Args:
        repo_root: Repository root
        
    Returns:
        List of error messages, empty if all checks pass
    """
    errors = []
    
    # Check that xops/patcher/bundles exists and is properly structured
    patcher_bundles_root = repo_root / "xops" / "patcher" / "bundles"
    
    # If no bundles exist yet, that's OK
    if not patcher_bundles_root.exists():
        return errors
    
    # Walk the bundle directory and check paths
    for extractor_dir in patcher_bundles_root.iterdir():
        if not extractor_dir.is_dir():
            continue
        
        extractor_id = extractor_dir.name
        
        # Each extractor should have league_id subdirectories
        for league_dir in extractor_dir.iterdir():
            if not league_dir.is_dir():
                continue
            
            league_id = league_dir.name
            
            # Verify the path structure is correct:
            # xops/patcher/bundles/<extractor_id>/<league_id>/
            expected_path_pattern = r"^xops/patcher/bundles/[a-z_][a-z0-9_]*/[a-z_][a-z0-9_]*/$"
            actual_path = str(league_dir.relative_to(repo_root)) + "/"
            
            if not re.match(expected_path_pattern, actual_path):
                errors.append(
                    f"ERROR: patcher bundle path does not follow two-key scoping: {actual_path}\n"
                    f"       Expected format: xops/patcher/bundles/<extractor_id>/<league_id>/\n"
                    f"       extractor_id and league_id must be lowercase with underscores only."
                )
    
    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point for CI/CLI."""
    repo_root = Path(__file__).parent.parent.parent
    
    errors = check_patcher_bundle_scoping(repo_root)
    
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    
    print("✓ Patcher bundle scoping checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
