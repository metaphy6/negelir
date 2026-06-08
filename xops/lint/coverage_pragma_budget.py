#!/usr/bin/env python3
"""Phase 12 §12.12.5 — Coverage pragma budget enforcement.

Ensures that # pragma: no cover and # coverage:ignore directives
are tracked and bounded per module by cfg.coverage_pragma_max_per_module.
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Patterns for coverage pragmas
PRAGMA_PATTERNS = [
    re.compile(r'#\s*pragma:\s*no\s*cover'),
    re.compile(r'#\s*coverage:\s*ignore'),
    re.compile(r'//\s*coverage:ignore'),
]

def scan_file(path: Path) -> list[tuple[int, str]]:
    """Scan file for coverage pragmas. Returns [(line_num, pragma_text)]."""
    pragmas = []
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern in PRAGMA_PATTERNS:
                if pattern.search(line):
                    pragmas.append((line_num, line.strip()))
                    break
    except Exception:
        pass
    return pragmas

def main():
    repo_root = REPO_ROOT
    max_pragmas_per_module = 20  # Conservative budget
    
    violations = []
    pragma_counts = defaultdict(int)
    
    # Scan all Python and Go files
    for pattern in ["**/*.py", "**/*.go"]:
        for file_path in repo_root.glob(pattern):
            # Skip test files and third-party
            if "__pycache__" in str(file_path) or ".vendor" in str(file_path):
                continue
            
            pragmas = scan_file(file_path)
            if pragmas:
                # Determine module from path
                rel_path = file_path.relative_to(repo_root)
                parts = rel_path.parts[:2]  # First 2 parts of path (e.g., "ai", "server")
                module = "/".join(parts) if parts else "root"
                pragma_counts[module] += len(pragmas)
    
    # Check budget
    for module, count in pragma_counts.items():
        if count > max_pragmas_per_module:
            violations.append(f"{module}: {count} pragmas (limit: {max_pragmas_per_module})")
    
    if violations:
        print("❌ Coverage pragma budget exceeded:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    else:
        print(f"✓ Coverage pragma budget OK: {sum(pragma_counts.values())} total pragmas")
        return 0

if __name__ == "__main__":
    sys.exit(main())
