#!/usr/bin/env python3
"""
test_taxonomy_sync.py — Phase 12.1 taxonomy sync enforcement.

Verifies that the test taxonomy table in
``docs/design/phase12/sections/01-test-taxonomy-and-pyramid.md`` (§12.1)
and the table in ``docs/design/TESTING_STRATEGY.md`` (the public-facing
specification) remain in perfect sync.

The **source of truth** is §12.1 (the binding per-section file in the
detailed phase design). The lint warns if TESTING_STRATEGY.md diverges.

Expected layers in order (Phase 12 §12.1):
    Unit, Property, Contract, Integration, Adversarial, Fuzz, Load, Chaos,
    Soak, Regression/Golden, Mutation

Exit code 0 = tables match, 1 = mismatch found, 2 = bad CLI invocation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The canonical layer order from Phase 12 §12.1.
CANONICAL_LAYERS = [
    "Unit",
    "Property",
    "Contract",
    "Integration",
    "Adversarial",
    "Fuzz",
    "Load",
    "Chaos",
    "Soak",
    "Regression/Golden",
    "Mutation",
]


def _extract_layer_names(content: str) -> list[str]:
    """Extract layer names from a markdown table.
    
    Assumes the table has a Layer column as the first column.
    Looks for lines starting with `|` and extracts the first cell.
    """
    layers = []
    in_table = False
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if in_table and layers:
                # End of table
                break
            continue
        
        # Skip header separator row (e.g., |---|---|...)
        if all(c in "-|" for c in line):
            in_table = True
            continue
        
        if not in_table:
            continue
        
        # Parse the row: | Layer | ... |
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 2:
            continue
        
        layer_cell = cells[1]
        # Remove markdown bold markers (**) and trim
        layer_cell = layer_cell.replace("**", "").strip()
        if layer_cell and layer_cell not in ("Layer", "---"):
            layers.append(layer_cell)
    
    return layers


def _read_file_safe(path: Path) -> str:
    """Read a file with graceful error handling."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def scan() -> list[str]:
    """Return a list of human-readable violation strings."""
    violations: list[str] = []
    
    # Read the source-of-truth: Phase 12 §12.1
    phase12_path = REPO_ROOT / "docs/design/phase12/sections/01-test-taxonomy-and-pyramid.md"
    phase12_content = _read_file_safe(phase12_path)
    phase12_layers = _extract_layer_names(phase12_content)
    
    # Read the public spec: TESTING_STRATEGY.md
    testing_path = REPO_ROOT / "docs/design/TESTING_STRATEGY.md"
    testing_content = _read_file_safe(testing_path)
    testing_layers = _extract_layer_names(testing_content)
    
    # Validate that phase12_path exists
    if not phase12_content:
        violations.append(
            f"Could not read source-of-truth file: {phase12_path.relative_to(REPO_ROOT)}"
        )
    
    # Validate that testing_path exists
    if not testing_content:
        violations.append(
            f"Could not read public-spec file: {testing_path.relative_to(REPO_ROOT)}"
        )
    
    if violations:
        return violations
    
    # Compare layer names
    if phase12_layers != testing_layers:
        violations.append(
            f"Layer mismatch: Phase 12 §12.1 has {phase12_layers}, "
            f"but TESTING_STRATEGY.md has {testing_layers}"
        )
    
    # Verify against canonical order
    if phase12_layers != CANONICAL_LAYERS:
        violations.append(
            f"Phase 12 §12.1 layers {phase12_layers} do not match canonical order {CANONICAL_LAYERS}"
        )
    
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress 'clean' message on success",
    )
    args = parser.parse_args(argv)

    violations = scan()
    if violations:
        print("❌ test_taxonomy_sync: violations found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "\nEnsure docs/design/TESTING_STRATEGY.md §2 'Test taxonomy' table "
            "matches docs/design/phase12/sections/01-test-taxonomy-and-pyramid.md §12.1 exactly.",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print("✅ test_taxonomy_sync: TESTING_STRATEGY.md and Phase 12 §12.1 are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
