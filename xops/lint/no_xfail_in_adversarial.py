#!/usr/bin/env python3
"""Phase 12 §12.13.1 — No xfail in adversarial/chaos tests lint.

Adversarial + chaos test suites MUST NOT use xfail marker.
A known weakness is a release blocker, not a documented skip (§12.0 A9).
Lint scans ai/tests/test_chaos_*.py and ai/tests/test_adversarial_*.py
"""

import sys
from pathlib import Path
import re

if __name__ == "__main__":
    repo_root = Path(__file__).parents[2]
    test_dir = repo_root / "ai" / "tests"
    
    violations = []
    for pattern in ["test_chaos_*.py", "test_adversarial_*.py"]:
        for f in test_dir.glob(pattern):
            content = f.read_text()
            # Find @pytest.mark.xfail or @pytest.xfail
            if re.search(r'@pytest\.mark\.xfail|pytest\.xfail\(', content):
                violations.append(f.name)
    
    if violations:
        print("❌ xfail found in adversarial/chaos tests (§12.13.1 violation):")
        for v in violations:
            print(f"  {v}")
        sys.exit(1)
    else:
        print("✓ No xfail in adversarial/chaos tests")
        sys.exit(0)
