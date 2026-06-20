"""Phase 19 §19.1 — ai/ layout freeze gate.

Refuses any new ai/<module>/ top-level directory that is not a pre-existing stub
from Phase 18 §18.3. This prevents uncoordinated module additions and ensures
orderly Phase 22 migration.

Pre-existing stubs (allowed to remain unchanged):
- ai/common/
- ai/scraper/
- ai/nlp/
- ai/swarm/
- ai/pipeline/
- ai/backtest/
- ai/orchestrator/
- ai/model/
- ai/proofreader/
- ai/qid/
- ai/reports/
- ai/tqu/
- ai/trc/
"""

from __future__ import annotations

import sys
from pathlib import Path


# Phase 18 §18.3 pre-existing stubs that are allowed to remain
ALLOWED_AI_MODULES = {
    "common",
    "scraper",
    "nlp",
    "swarm",
    "pipeline",
    "backtest",
    "orchestrator",
    "model",
    "proofreader",
    "qid",
    "reports",
    "tqu",
    "trc",
    # Allow some special files/dirs
    "scheduler.py",
    "main.py",
    "data_showcase.py",
    "requirements.txt",
    "requirements-dev.txt",
    "Dockerfile",
    "__init__.py",
    "docs",
    "tests",
    "datasource",
}


def check_ai_layout_freeze(repo_root: Path) -> list[str]:
    """
    Verify that no new top-level ai/ modules have been added.
    
    Args:
        repo_root: Repository root
        
    Returns:
        List of error messages, empty if all checks pass
    """
    errors = []
    
    ai_path = repo_root / "ai"
    if not ai_path.exists():
        return errors
    
    # Check all items in ai/
    for item in ai_path.iterdir():
        # Skip special files
        if item.name.startswith(".") or item.name.startswith("_"):
            continue
        
        # Skip allowed modules
        if item.name in ALLOWED_AI_MODULES:
            continue
        
        # Found a new module (not in the pre-existing list)
        if item.is_dir():
            errors.append(
                f"ERROR: New ai/ module not allowed: ai/{item.name}/\n"
                f"       Phase 19 layout freeze prevents new top-level modules.\n"
                f"       Phase 18 pre-existing modules: {', '.join(sorted(ALLOWED_AI_MODULES))}\n"
                f"       If this is a Phase 18 stub that should be allowed, update ALLOWED_AI_MODULES."
            )
    
    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point for CI/CLI."""
    repo_root = Path(__file__).parent.parent.parent
    
    errors = check_ai_layout_freeze(repo_root)
    
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    
    print("✓ ai/ layout freeze checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
