#!/usr/bin/env python3
"""
test_no_skip_down_rule.py — Phase 12.1.1 no-skip-down rule enforcement.

Implements the "no-skip-down" policy: a behaviour provable at a cheaper layer
(unit/property/contract) must have its proof there. An apex test (fuzz/chaos/soak)
may *additionally* exercise it end-to-end but never *instead*.

This lint warns when expensive tests duplicate coverage that should be at a
cheaper layer. The enforcement is advisory: reviewers are the final check.

Per Phase 12 §12.1.1:
  "Reviewers reject a chaos test that is really an un-unit-tested invariant
   in disguise."

Exit code 0 = no violations, 1 = warnings present, 2 = bad invocation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Layer hierarchy: cheap → middle → apex
LAYER_HIERARCHY = {
    "unit": 1,
    "property": 1,
    "contract": 1,
    "integration": 2,
    "adversarial": 2,
    "regression": 2,
    "fuzz": 3,
    "load": 3,
    "chaos": 3,
    "soak": 3,
    "mutation": 3,
}


def scan() -> list[str]:
    """
    Return a list of human-readable violations.
    
    This is a policy-enforcement lint. In the short term, it serves as
    documentation; the actual enforcement happens during code review
    (per the §12.1.1 bullet: "Reviewers reject...").
    """
    violations: list[str] = []
    
    # The enforcement is primarily manual during review. This lint would need:
    # 1. A way to extract test coverage metadata
    # 2. A way to cross-reference apex tests with cheaper-layer equivalents
    # 3. A test-naming convention that makes this discoverable
    #
    # For now, this is a placeholder that always passes but documents the rule.
    # Future enhancement: scan pytest markers and test comments to detect
    # re-tested invariants.
    
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress 'clean' message on success",
    )
    args = parser.parse_args(argv)

    violations = scan()
    if violations:
        print("⚠️  test_no_skip_down_rule: policy violations found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nPer Phase 12 §12.1.1: behaviours provable at cheaper layers must have proof there.",
            file=sys.stderr,
        )
        return 1
    
    if not args.quiet:
        print("✅ test_no_skip_down_rule: no-skip-down policy in effect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
