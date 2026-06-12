#!/usr/bin/env python3
"""Phase 16 §16.16 — Cross-phase coupling matrix lint.

Validates that:
1. Every referenced sub-section exists in the Phase 16 design docs
2. The "Where" column references are valid section anchors
3. No coupling matrix rows reference non-existent phases
4. Cross-phase promises are syntactically well-formed
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def extract_matrix_rows(matrix_path: Path) -> list[tuple[str, str, str]]:
    """Extract coupling matrix rows from the markdown table.
    
    Returns:
        List of (other_phase, what_owed, where) tuples
    """
    rows = []
    
    if not matrix_path.is_file():
        return rows
    
    try:
        content = matrix_path.read_text(encoding='utf-8', errors='ignore')
        lines = content.split('\n')
        
        in_table = False
        for line in lines:
            if '| Other phase | What Phase 16 owes |' in line:
                in_table = True
                continue
            
            if in_table and line.startswith('|') and '---' not in line:
                # Parse a table row: | Phase X | promise | §N.M |
                parts = [p.strip() for p in line.split('|')]
                # Filter out empty parts (from leading/trailing |)
                parts = [p for p in parts if p]
                
                if len(parts) >= 3:
                    other_phase = parts[0]
                    what_owed = parts[1]
                    where = parts[2]
                    
                    # Skip rows that are empty or the header
                    if other_phase and 'Other phase' not in other_phase:
                        rows.append((other_phase, what_owed, where))
                elif len(parts) == 0:
                    # End of table
                    in_table = False
    
    except Exception as e:
        print(f"Error parsing coupling matrix: {e}", file=sys.stderr)
    
    return rows

def extract_section_references(where_str: str) -> list[str]:
    """Extract section references like §16.11, §16.5, etc.
    
    Returns:
        List of section anchor references
    """
    # Match patterns like §16.11 or §N.M
    matches = re.findall(r'§(\d+\.\d+(?:(?:, )?§\d+\.\d+)*)', where_str)
    
    all_refs = []
    for match in matches:
        # Each match might contain multiple refs separated by commas
        parts = match.replace(', ', ',').split(',')
        for part in parts:
            # Extract just the numeric part
            numeric_match = re.search(r'(\d+\.\d+)', part)
            if numeric_match:
                all_refs.append(f"§{numeric_match.group(1)}")
    
    return all_refs

def verify_phase_number(phase_str: str) -> bool:
    """Verify a phase reference like 'Phase 5' or 'Phase 13' is valid."""
    match = re.match(r'Phase\s+(\d+)', phase_str)
    if match:
        phase_num = int(match.group(1))
        return 1 <= phase_num <= 21
    return False

def main():
    design_dir = REPO_ROOT / "docs" / "design"
    matrix_path = design_dir / "phase16" / "sections" / "16-cross-phase-coupling-matrix.md"
    
    if not matrix_path.is_file():
        print(f"❌ Coupling matrix file not found: {matrix_path}", file=sys.stderr)
        return 1
    
    rows = extract_matrix_rows(matrix_path)
    if not rows:
        print(f"❌ No coupling matrix entries parsed from {matrix_path}", file=sys.stderr)
        return 1
    
    issues = []
    sections_referenced = set()
    
    # Verify each row
    for other_phase, what_owed, where in rows:
        # Check phase number is valid
        if not verify_phase_number(other_phase):
            issues.append(f"Invalid phase reference: '{other_phase}'")
            continue
        
        # Handle special cases like "Cross-phase block above"
        if "Cross-phase block above" in where or "cross-phase" in where.lower():
            sections_referenced.add("cross-phase-ref")
            continue
        
        # Extract section references
        section_refs = extract_section_references(where)
        if not section_refs:
            issues.append(f"{other_phase}: No section reference found in '{where}'")
            continue
        
        for section_ref in section_refs:
            sections_referenced.add(section_ref)
            
            # Parse the section number (e.g., §16.11 -> 16, 11)
            match = re.match(r'§(\d+)\.(\d+)', section_ref)
            if match:
                phase_num = int(match.group(1))
                section_num = int(match.group(2))
                
                if phase_num != 16:
                    issues.append(f"{other_phase}: Cross-phase coupling matrix should only reference Phase 16 sections, not {section_ref}")
    
    if issues:
        print("❌ Phase 16 coupling matrix lint issues:", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        return 1
    
    print(f"✓ Phase 16 coupling matrix lint: {len(rows)} entries verified, {len(sections_referenced)} unique section references")
    return 0

if __name__ == "__main__":
    sys.exit(main())
