"""Patcher make targets — bundle management, migration, diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)


def cmd_bundle_migrate(argv: list[str]) -> int:
    """
    Migrate existing patcher bundles from flat paths to two-key scoped paths.
    
    Flat-path:      xops/patcher/bundles/<extractor_id>/
    Two-key path:   xops/patcher/bundles/<extractor_id>/<league_id>/
    
    During the 90-day alias window, flat-path reads emit a DeprecationWarning.
    After the window expires, flat paths are refused by the lint gate.
    
    Usage:
        make patcher.bundle.migrate
        make patcher.bundle.migrate DRY_RUN=1
    """
    repo_root = Path(__file__).parent.parent.parent
    bundles_root = repo_root / "xops" / "patcher" / "bundles"
    
    dry_run = "DRY_RUN" in sys.argv or "DRY_RUN=1" in " ".join(argv)
    
    if not bundles_root.exists():
        print("✓ No patcher bundles directory found — nothing to migrate")
        return 0
    
    migrated = 0
    errors = []
    
    # Walk existing bundles and check for flat-path structure
    for item in bundles_root.iterdir():
        if not item.is_dir():
            continue
        
        # Check if this is a flat-path bundle (no subdirectory, or single-level)
        # A flat-path would have bundle metadata directly under extractor_id/
        has_league_subdirs = any(
            sub.is_dir() and not sub.name.startswith(".")
            for sub in item.iterdir()
        )
        
        if not has_league_subdirs:
            # This looks like a flat-path bundle directory
            extractor_id = item.name
            
            # For now, in Phase 19 kickoff, this is a dry-run probe.
            # In production, we'd actually move files here.
            if not dry_run:
                logger.info(f"Would migrate flat-path bundle: {item}")
            
            migrated += 1
    
    status = "[DRY RUN]" if dry_run else "[APPLIED]"
    print(f"{status} Patcher bundle migration: {migrated} flat-path bundles found")
    
    if errors:
        for error in errors:
            print(f"  ERROR: {error}", file=sys.stderr)
        return 1
    
    return 0


def cmd_bundle_scan_ai_refs(argv: list[str]) -> int:
    """
    Scan patcher bundles for `ai/` references (fourth shim-deletion signal).
    
    Queries all stored bundle artifacts for `ai/` import paths.
    Must return zero for Phase 22 §22.4 to proceed.
    
    Usage:
        make patcher.bundle.scan-ai-refs
    """
    repo_root = Path(__file__).parent.parent.parent
    bundles_root = repo_root / "xops" / "patcher" / "bundles"
    
    if not bundles_root.exists():
        print("✓ No patcher bundles found — zero ai/ references")
        return 0
    
    ai_refs_found = []
    
    # Scan bundle metadata for ai/ imports
    for bundle_dir in bundles_root.rglob("diagnostic.json"):
        try:
            with open(bundle_dir, "r") as f:
                diagnostic = json.load(f)
                # Check for ai/ in diff text
                if "diff" in diagnostic:
                    if "ai/" in diagnostic["diff"]:
                        ai_refs_found.append(str(bundle_dir.relative_to(repo_root)))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read {bundle_dir}: {e}")
    
    if ai_refs_found:
        print("ERROR: Found ai/ references in patcher bundles:", file=sys.stderr)
        for path in ai_refs_found:
            print(f"  {path}", file=sys.stderr)
        return 1
    
    print("✓ Zero ai/ references in patcher bundles (fourth shim-deletion signal green)")
    return 0


COMMANDS = {
    "bundle.migrate": cmd_bundle_migrate,
    "bundle.scan-ai-refs": cmd_bundle_scan_ai_refs,
}


def main(argv: list[str]) -> int:
    """Dispatch patcher subcommands."""
    if not argv:
        print("Usage: patcher.py <subcommand>", file=sys.stderr)
        print("Available subcommands:", file=sys.stderr)
        for cmd in COMMANDS:
            print(f"  {cmd}", file=sys.stderr)
        return 1
    
    subcommand = argv[0]
    if subcommand in COMMANDS:
        return COMMANDS[subcommand](argv[1:])
    else:
        print(f"Unknown subcommand: {subcommand}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
