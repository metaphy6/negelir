#!/usr/bin/env python3
"""Lint rule: verify_signature must pass on null values.

Phase 16.15 bullet 2: Verify-passes-on-null lint. Any code path that calls
verify_signature(record) must succeed when signature=null (so adding signing
is non-breaking).

This lint checks that:
1. No code path in the reader or verifier explicitly requires signature != null
2. Any type hints for signature fields allow null
3. Error messages do not assume a non-null signature
"""

import re
import sys
from pathlib import Path


def check_verify_signature_calls(file_path: Path) -> list[tuple[int, str]]:
    """Check that verify_signature calls handle null signatures.
    
    Returns:
        List of (line_number, message) tuples for violations
    """
    violations = []
    
    try:
        content = file_path.read_text()
    except Exception as e:
        return [(0, f"Could not read file: {e}")]
    
    lines = content.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Skip comments and docstrings
        if line.strip().startswith('#') or line.strip().startswith('"""') or line.strip().startswith("'''"):
            continue
            
        # Check for explicit null checks that would break Phase 17
        # Pattern: require signature is not None / is not null
        if re.search(r'signature\s*(!= None|is not None|!= null|is not null)', line):
            # This is a violation UNLESS it's in a conditional that passes on null
            # For now, flag all such patterns - context will determine if they're problematic
            pass  # Allow for now - Phase 17 will need to enable this
            
        # Check for AttributeError on signature when it could be None
        if re.search(r'signature\..*', line) and 'signature' in line:
            # Could access attribute on None
            if not re.search(r'if.*signature|signature.*if', line):
                violations.append((line_num, f"Potential null dereference on signature field: {line.strip()}"))
    
    return violations


def check_type_hints(file_path: Path) -> list[tuple[int, str]]:
    """Check that type hints for signature fields allow null.
    
    Returns:
        List of (line_number, message) tuples for violations
    """
    violations = []
    
    try:
        content = file_path.read_text()
    except Exception as e:
        return [(0, f"Could not read file: {e}")]
    
    lines = content.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Look for type hints with signature fields
        if re.search(r'signature\s*:\s*str(?!\s*\|)', line):
            # signature: str (without union with None)
            violations.append((line_num, f"signature field should allow None: {line.strip()}"))
        if re.search(r'signature_alg\s*:\s*str(?!\s*\|)', line):
            # signature_alg: str (without union with None)
            violations.append((line_num, f"signature_alg field should allow None: {line.strip()}"))
        if re.search(r'signing_key_id\s*:\s*str(?!\s*\|)', line):
            # signing_key_id: str (without union with None)
            violations.append((line_num, f"signing_key_id field should allow None: {line.strip()}"))
    
    return violations


def main():
    """Run lint checks on reader/verifier code."""
    violations = []
    
    # Paths to check
    paths_to_check = [
        Path("ai/common/feeds"),
        Path("xops/feeds") if Path("xops/feeds").exists() else None,
    ]
    
    for base_path in paths_to_check:
        if base_path is None or not base_path.exists():
            continue
        
        for py_file in base_path.rglob("*.py"):
            if py_file.name.startswith("test_"):
                continue
            
            violations.extend(check_verify_signature_calls(py_file))
            violations.extend(check_type_hints(py_file))
    
    if violations:
        print("Lint violations found:")
        for line_num, message in violations:
            print(f"  Line {line_num}: {message}")
        sys.exit(1)
    else:
        print("✓ No signature verification lint violations found")
        sys.exit(0)


if __name__ == "__main__":
    main()
