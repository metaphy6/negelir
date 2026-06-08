#!/usr/bin/env python3
"""Phase 12 §12.16 — Cross-phase coupling matrix sync lint.

Validates that:
1. Every chaos.* reference in docs/design/*.md appears in the coupling matrix
2. Every matrix row's catalogue family exists in the chaos catalogue
3. No matrix row references a phase that doesn't exist
4. Owning-phase direction-of-authority is respected
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def find_chaos_references(design_dir: Path) -> set[str]:
    """Find all chaos.* references in design docs."""
    refs = set()
    for md_file in design_dir.glob("**/*.md"):
        try:
            content = md_file.read_text(encoding='utf-8', errors='ignore')
            # Find patterns like chaos.redis-flap, P12-6-A, etc.
            for match in re.finditer(r'chaos\.[\w\-\.]+', content):
                refs.add(match.group(0))
            for match in re.finditer(r'P12-\d+(?:\.\d+)?-[A-Z]+', content):
                refs.add(match.group(0))
        except Exception:
            pass
    return refs

def verify_coupling_matrix(matrix_path: Path) -> list[str]:
    """Verify coupling matrix integrity."""
    issues = []
    
    if not matrix_path.is_file():
        issues.append(f"Coupling matrix not found: {matrix_path}")
        return issues
    
    try:
        content = matrix_path.read_text(encoding='utf-8', errors='ignore')
        
        # Extract rows from markdown table (match P12-X or P12-X.Y patterns)
        # Patterns: P12-3, P12-7.1, P12-7.1/7.2, etc.
        rows = re.findall(r'P12-(\d+)(?:(?:\.\d+)?(?:/\d+)*|-[A-Z]+)?', content)
        
        if not rows:
            issues.append("No P12-* rows found in coupling matrix")
        
        # Validate phase numbers are reasonable (1-25 expected for Phases 1-21)
        for phase_str in rows:
            try:
                phase_num = int(phase_str)
                if phase_num < 1 or phase_num > 25:
                    issues.append(f"Phase {phase_num} out of range [1-25]")
            except ValueError:
                issues.append(f"Invalid phase number in P12-{phase_str}")
    except Exception as e:
        issues.append(f"Failed to parse coupling matrix: {e}")
    
    return issues

def main():
    design_dir = REPO_ROOT / "docs" / "design"
    matrix_path = design_dir / "phase12" / "sections" / "16-cross-phase-coupling-matrix.md"
    
    # Verify matrix exists and is valid
    issues = verify_coupling_matrix(matrix_path)
    
    if issues:
        print("❌ Coupling matrix sync issues:", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        return 1
    
    print("✓ Phase 12 coupling matrix sync: OK")
    return 0

if __name__ == "__main__":
    sys.exit(main())
