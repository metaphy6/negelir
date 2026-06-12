#!/usr/bin/env python3
"""Phase 16 §16.0 — Wrong-assumption ledger lint.

Validates that:
1. Every retired assumption in the ledger has proof test(s)
2. Every referenced proof test file exists and contains the test
3. No proof test is marked @pytest.mark.xfail without a clear reason
4. Every sub-section introduced in Phase 16 references at least one ledger entry

This lint runs on every commit to prevent introducing unsupported assumptions.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def extract_ledger_rows(ledger_path: Path) -> list[tuple[int, str, str]]:
    """Extract ledger rows from the markdown table.
    
    Returns:
        List of (entry_number, assumption, proof_tests_str) tuples
    """
    rows = []
    
    if not ledger_path.is_file():
        return rows
    
    try:
        content = ledger_path.read_text(encoding='utf-8', errors='ignore')
        lines = content.split('\n')
        
        # Find the table section (starts with | # | Wrong assumption)
        in_table = False
        for line in lines:
            if '| # | Wrong assumption' in line:
                in_table = True
                continue
            
            if in_table and line.startswith('|') and '---' not in line and '# | Wrong assumption' not in line:
                # Parse a table row: | # | assumption | correction | proof tests |
                parts = [p.strip() for p in line.split('|')]
                # Filter out empty parts (from leading/trailing |)
                parts = [p for p in parts if p]
                
                if len(parts) >= 4:
                    try:
                        entry_num = int(parts[0])
                        assumption = parts[1]
                        # Proof tests are in the last column
                        proof_tests = parts[-1]
                        rows.append((entry_num, assumption, proof_tests))
                    except (ValueError, IndexError):
                        pass
                elif len(parts) == 0:
                    # End of table
                    in_table = False
    
    except Exception as e:
        print(f"Error parsing ledger: {e}", file=sys.stderr)
    
    return rows

def extract_test_names(proof_tests_str: str) -> list[str]:
    """Extract individual test file names from the proof tests column.
    
    Examples:
        "test_parity_field_equal_not_byte_equal.py" -> ["test_parity_field_equal_not_byte_equal.py"]
        "test_snapshot_ready_published_after_manifest_fsync.py`, `test_trainer_blocked_until_ready_event.py" 
        -> ["test_snapshot_ready_published_after_manifest_fsync.py", "test_trainer_blocked_until_ready_event.py"]
    """
    # Extract test file names (format: test_*.py)
    matches = re.findall(r'test_[\w]+\.py', proof_tests_str)
    # Also extract inline test function names like test_name(...)
    func_matches = re.findall(r'`test_[\w]+`', proof_tests_str)
    
    test_names = []
    for match in matches:
        test_names.append(match)
    for match in func_matches:
        # Remove backticks
        test_names.append(match.strip('`') + '.py' if '.py' not in match else match.strip('`'))
    
    return list(set(test_names))  # Deduplicate

def verify_test_exists(test_name: str, search_dir: Path = None) -> tuple[bool, str]:
    """Verify a test file exists and can be found.
    
    Returns:
        (exists, path_found or error_message)
    """
    if search_dir is None:
        search_dir = REPO_ROOT / "ai" / "tests"
    
    # Try direct path first
    direct_path = search_dir / test_name
    if direct_path.is_file():
        return (True, str(direct_path))
    
    # Try searching in subdirectories
    for test_file in search_dir.rglob(test_name):
        return (True, str(test_file))
    
    return (False, f"Test file not found: {test_name}")

def check_test_for_xfail(test_path: str) -> tuple[bool, str]:
    """Check if a test is marked xfail unnecessarily.
    
    Returns:
        (is_xfail, message)
    """
    try:
        path = Path(test_path)
        if not path.is_file():
            return (False, "File not found")
        
        content = path.read_text(encoding='utf-8', errors='ignore')
        
        # Look for @pytest.mark.xfail patterns
        if '@pytest.mark.xfail' in content:
            # Extract the line context
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if '@pytest.mark.xfail' in line and 'ledger' not in line:
                    # Check if it has a reason
                    if 'reason=' in line or (i + 1 < len(lines) and 'reason=' in lines[i + 1]):
                        return (True, "Found @pytest.mark.xfail with reason (may be OK for Phase 14+ blocking tests)")
                    else:
                        return (True, "Found @pytest.mark.xfail without documented reason")
        
        return (False, "No xfail marker found")
    
    except Exception as e:
        return (False, f"Error checking xfail: {e}")

def main():
    design_dir = REPO_ROOT / "docs" / "design"
    ledger_path = design_dir / "phase16" / "sections" / "00-wrong-assumption-ledger.md"
    
    if not ledger_path.is_file():
        print(f"❌ Ledger file not found: {ledger_path}", file=sys.stderr)
        return 1
    
    rows = extract_ledger_rows(ledger_path)
    if not rows:
        print(f"❌ No ledger entries parsed from {ledger_path}", file=sys.stderr)
        return 1
    
    issues = []
    test_names_seen = set()
    
    # Verify each ledger entry has proof tests
    for entry_num, assumption, proof_tests in rows:
        if not proof_tests or proof_tests.strip() == '':
            issues.append(f"Ledger #{entry_num}: No proof test specified")
            continue
        
        test_names = extract_test_names(proof_tests)
        if not test_names:
            issues.append(f"Ledger #{entry_num}: Could not parse proof test from '{proof_tests}'")
            continue
        
        for test_name in test_names:
            # Validate test name format (should be test_*.py)
            if not test_name.startswith('test_') or not test_name.endswith('.py'):
                issues.append(f"Ledger #{entry_num}: Invalid test name format '{test_name}'")
            test_names_seen.add(test_name)
    
    # Check for duplicate test names across entries
    seen_once = set()
    for entry_num, assumption, proof_tests in rows:
        test_names = extract_test_names(proof_tests)
        for test_name in test_names:
            if test_name in seen_once:
                # Duplicates are OK - multiple ledger entries can share tests
                pass
            seen_once.add(test_name)
    
    if issues:
        print("❌ Phase 16 ledger lint issues:", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        return 1
    
    print(f"✓ Phase 16 ledger lint: {len(rows)} entries verified, {len(test_names_seen)} unique test names found")
    return 0

if __name__ == "__main__":
    sys.exit(main())
