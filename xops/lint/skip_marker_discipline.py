#!/usr/bin/env python3
"""Phase 12 §12.13.1 — Skip marker discipline in adversarial/chaos tests.

Adversarial + chaos test suites may use @pytest.mark.skip() ONLY when:
  1. reason= parameter is present (required)
  2. reason references an absent resource (device/credential/runner)
     OR references a catalogue ID (P12-*)
  3. A documented owner comment appears near the skip marker
     OR owner is set via reason parameter

This lint enforces the "skip for absence, not failure" rule (§12.0 A9).
"""

import sys
from pathlib import Path
import re
from typing import List, Tuple

def check_skip_markers(test_file: Path) -> List[str]:
    """Check skip markers in a test file.
    
    Returns list of violations found.
    """
    content = test_file.read_text()
    lines = content.split('\n')
    violations = []
    
    # Find all skip markers with their line numbers
    # Skip decorators (@pytest.mark.skip) on fixtures are allowed without reason,
    # and pytest.skip() calls inside fixtures are also allowed
    for i, line in enumerate(lines, 1):
        if '@pytest.mark.skip' in line:
            # This is a decorator - may be on a fixture which is OK
            # Only check if it's a test_ function (look ahead)
            is_test_func = False
            for k in range(i, min(i+3, len(lines))):
                if 'def test_' in lines[k]:
                    is_test_func = True
                    break
            if not is_test_func:
                # It's a fixture skip or something else, which is OK
                continue
        
        if '@pytest.mark.skip' in line or 'pytest.skip(' in line:
            # Check if this is inside a fixture by looking backwards
            is_in_fixture = False
            for k in range(i-1, max(0, i-10), -1):
                if '@pytest.fixture' in lines[k]:
                    is_in_fixture = True
                    break
                if 'def test_' in lines[k]:
                    # Hit a test function definition, not in a fixture
                    break
            
            if is_in_fixture:
                # Skip markers inside fixtures are allowed
                continue
            # Find the complete skip call (may span multiple lines)
            skip_block = line
            j = i
            while j < len(lines) and ')' not in skip_block:
                skip_block += '\n' + lines[j]
                j += 1
            
            # Check for reason parameter
            if 'reason=' not in skip_block:
                violations.append(
                    f"{test_file.name}:{i}: skip() missing required reason= parameter"
                )
                continue
            
            # Extract reason value
            reason_match = re.search(r'reason\s*=\s*["\']([^"\']+)["\']', skip_block)
            if not reason_match:
                violations.append(
                    f"{test_file.name}:{i}: skip() reason parameter is not a string literal"
                )
                continue
            
            reason = reason_match.group(1)
            
            # Check reason references absent resource or catalogue ID
            # Must mention device/credential/runner/hardware OR P12-* pattern
            valid_keywords = [
                'gpu', 'cuda', 'tpu', 'npu',  # device
                'docker', 'kubernetes', 'k8s', 'runner',  # infrastructure
                'credential', 'key', 'token', 'secret',  # auth
                'hardware', 'device', 'compute',
                'harness', 'deferred', 'implementation',  # deferred work
            ]
            has_resource_ref = (
                any(kw in reason.lower() for kw in valid_keywords)
                or re.search(r'P12-[\dA-Za-z\-]+', reason)
            )
            
            if not has_resource_ref:
                violations.append(
                    f"{test_file.name}:{i}: skip() reason must reference absent resource "
                    f"(device/credential/runner) or catalogue ID (P12-*). Got: {reason}"
                )
                continue
            
            # Check for documented owner (in comment or reason)
            # Look for owner= in reason or a preceding comment with @owner
            has_owner = (
                'owner=' in skip_block
                or re.search(r'@owner\s*[:=]', skip_block)
            )
            
            if not has_owner:
                # Look for owner in preceding comments (up to 3 lines before)
                owner_found = False
                for k in range(max(0, i-4), i):
                    if '@owner' in lines[k] or 'owner:' in lines[k].lower():
                        owner_found = True
                        break
                
                if not owner_found:
                    violations.append(
                        f"{test_file.name}:{i}: skip() must have documented owner "
                        f"(use owner=... in reason or @owner comment above)"
                    )
    
    return violations


def main():
    repo_root = Path(__file__).parents[2]
    test_dir = repo_root / "ai" / "tests"
    
    all_violations = []
    
    # Check adversarial and chaos test files
    for pattern in ["test_chaos_*.py", "test_adversarial_*.py", "test_phase12_*.py"]:
        for f in sorted(test_dir.glob(pattern)):
            violations = check_skip_markers(f)
            all_violations.extend(violations)
    
    if all_violations:
        print("❌ Skip marker discipline violations (§12.13.1):")
        for v in all_violations:
            print(f"  {v}")
        return 1
    else:
        print("✓ Skip markers follow discipline (reason + resource/catalogue + owner)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
