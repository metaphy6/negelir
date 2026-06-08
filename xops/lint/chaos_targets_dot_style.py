#!/usr/bin/env python3
"""Phase 12 §12.15.1 — Dot-style target naming for chaos/fuzz/soak.

All Phase 12 targets (chaos.*, fuzz.*, soak.*, coverage.*, ci.*)
MUST use dot-style naming (chaos.redis-flap, not chaos-redis-flap).
This lint rejects hyphen-style target names re-introduced by future PRs.
"""

import sys
from pathlib import Path
import re

if __name__ == "__main__":
    repo_root = Path(__file__).parents[2]
    makefile = repo_root / "Makefile"
    
    violations = []
    for line_num, line in enumerate(makefile.read_text().split('\n'), 1):
        # Find .PHONY: targets that should be dot-style
        if '.PHONY:' in line:
            match = re.search(r'\.PHONY: (chaos-|fuzz-|soak-|coverage-|ci-)', line)
            if match:
                target = match.group(1)[:-1]  # Remove trailing '-'
                violations.append(f"{makefile.name}:{line_num} — {target}-* target (use {target}.*)")
    
    if violations:
        print("❌ Hyphen-style chaos/fuzz/soak targets (use dot-style per §12.15.1):")
        for v in violations:
            print(f"  {v}")
        sys.exit(1)
    else:
        print("✓ All Phase 12 targets use dot-style naming")
        sys.exit(0)
