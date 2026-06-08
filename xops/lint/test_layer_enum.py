#!/usr/bin/env python3
"""
test_layer_enum.py — Phase 12.1 layer enum enforcement.

Validates that all references to test layer names in the codebase
(CI jobs, chaos configuration, test metadata) use only the 11 canonical
layer names defined in Phase 12 §12.1:
  {unit, property, contract, integration, adversarial, fuzz, load, chaos,
   soak, regression, mutation}

An unknown layer label in any CI job, chaos config, or pytest marker
results in a lint failure.

Exit code 0 = all references valid, 1 = unknown layer found, 2 = bad invocation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The canonical layer enum from Phase 12 §12.1 (lowercase for matching)
CANONICAL_LAYERS_ENUM = {
    "unit",
    "property",
    "contract",
    "integration",
    "adversarial",
    "fuzz",
    "load",
    "chaos",
    "soak",
    "regression",
    "mutation",
}


def _read_file_safe(path: Path) -> str:
    """Read a file with graceful error handling."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _find_invalid_layer_references() -> list[tuple[str, int, str]]:
    """
    Scan for invalid layer references.
    
    Returns list of (file_path, line_num, violation_msg) tuples.
    """
    violations: list[tuple[str, int, str]] = []
    
    # Pattern to find potential layer references:
    # - YAML: layer: <value>
    # - Python: layer='<value>' or layer="<value>" or layer=<value>
    # - Comments: # layer: <value>
    layer_pattern = re.compile(
        r'(?:layer\s*[:=]\s*["\']?([a-z_]+)["\']?|@pytest\.mark\.layer_([a-z_]+))',
        re.IGNORECASE,
    )
    
    # Scan Python files in xops/ and .github/
    scan_dirs = [
        REPO_ROOT / "xops",
        REPO_ROOT / ".github",
        REPO_ROOT / "ai" / "tests",
    ]
    
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        
        # Scan YAML and Python files
        for pattern in ["**/*.yml", "**/*.yaml", "**/*.py"]:
            for file_path in scan_dir.glob(pattern):
                # Skip common non-config files
                if "__pycache__" in str(file_path):
                    continue
                
                content = _read_file_safe(file_path)
                if not content:
                    continue
                
                for line_num, line in enumerate(content.splitlines(), 1):
                    for match in layer_pattern.finditer(line):
                        # Extract the layer value from group 1 or 2
                        layer_value = match.group(1) or match.group(2)
                        if not layer_value:
                            continue
                        
                        # Normalize to lowercase for comparison
                        layer_lower = layer_value.lower()
                        
                        # Check if it's a valid layer
                        if layer_lower not in CANONICAL_LAYERS_ENUM:
                            violations.append((
                                str(file_path.relative_to(REPO_ROOT)),
                                line_num,
                                f"Unknown layer '{layer_value}'; must be one of {sorted(CANONICAL_LAYERS_ENUM)}",
                            ))
    
    return violations


def scan() -> list[str]:
    """Return a list of human-readable violation strings."""
    violations_list = _find_invalid_layer_references()
    
    if not violations_list:
        return []
    
    result: list[str] = []
    for file_path, line_num, msg in violations_list:
        result.append(f"{file_path}:{line_num}: {msg}")
    
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress 'clean' message on success",
    )
    args = parser.parse_args(argv)

    violations = scan()
    if violations:
        print("❌ test_layer_enum: invalid layer references found:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            f"\nValid test layers (Phase 12 §12.1): {', '.join(sorted(CANONICAL_LAYERS_ENUM))}",
            file=sys.stderr,
        )
        return 1
    
    if not args.quiet:
        print("✅ test_layer_enum: all layer references are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
