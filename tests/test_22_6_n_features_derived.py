"""Phase 22.6 — N_FEATURES verification tests.

These tests verify that:
1. N_FEATURES is derived from len(FEATURE_COLUMNS), never a hardcoded literal
2. The value matches the Phase 21 canonical value (157)
3. The comment accurately reflects the current composition
"""

import re
from pathlib import Path


def test_22_6_n_features_is_len_feature_columns_not_literal():
    """Verify N_FEATURES is derived from len(FEATURE_COLUMNS), never hardcoded."""
    constants_path = Path(__file__).resolve().parents[1] / "common" / "constants.py"
    content = constants_path.read_text(encoding="utf-8")
    
    # Find the N_FEATURES assignment line
    match = re.search(
        r'N_FEATURES:\s*int\s*=\s*(.+?)(?=\n|$)',
        content
    )
    assert match, "Could not find N_FEATURES in constants.py"
    
    assignment = match.group(1).strip()
    
    # Should be exactly len(FEATURE_COLUMNS), not a literal
    assert assignment.startswith("len(FEATURE_COLUMNS)"), (
        f"N_FEATURES should be assigned via len(FEATURE_COLUMNS), "
        f"found: {assignment}"
    )
    # Should not end with a numeric literal
    assert not re.match(r'^\d+', assignment), (
        f"N_FEATURES should be derived from len(), not a literal; found: {assignment}"
    )


def test_22_6_n_features_matches_phase21_canonical_value():
    """Verify N_FEATURES == 157 (120 base + 10 QID + 27 enrichment per Phase 21)."""
    # Count features by parsing the file to avoid import issues
    constants_path = Path(__file__).resolve().parents[1] / "common" / "constants.py"
    content = constants_path.read_text(encoding="utf-8")
    
    # Extract FEATURE_COLUMNS list
    match = re.search(
        r'FEATURE_COLUMNS: list\[str\] = \[(.*?)\]',
        content,
        re.DOTALL
    )
    assert match, "Could not find FEATURE_COLUMNS in constants.py"
    
    # Count string literals in the list
    list_content = match.group(1)
    features = re.findall(r'"([^"]+)"', list_content)
    
    actual_count = len(features)
    phase21_canonical = 157
    
    assert actual_count == phase21_canonical, (
        f"N_FEATURES count mismatch: expected {phase21_canonical} per Phase 21 DoD "
        f"(120 base + 10 QID + 27 enrichment), found {actual_count}"
    )


def test_22_6_n_features_stale_comment_reconciled():
    """Verify the N_FEATURES comment reflects the current Phase 21 composition."""
    constants_path = Path(__file__).resolve().parents[1] / "common" / "constants.py"
    content = constants_path.read_text(encoding="utf-8")
    
    # Find the N_FEATURES line
    match = re.search(
        r'N_FEATURES: int = len\(FEATURE_COLUMNS\)\s*#\s*(.+?)$',
        content,
        re.MULTILINE
    )
    assert match, "Could not find N_FEATURES with comment"
    
    comment = match.group(1)
    
    # The comment should NOT reference the old "147" value
    assert "147" not in comment, (
        f"N_FEATURES comment contains stale '147' value; "
        f"found: {comment}"
    )
    
    # The comment should reference the derived nature and current value
    assert "derived" in comment.lower() or "len" in comment.lower() or "157" in comment, (
        f"N_FEATURES comment should reflect derived nature or current value; "
        f"found: {comment}"
    )
    
    # Extract the composition from comment (e.g. "120 + 10 + 27")
    composition_match = re.search(r'(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)', comment)
    if composition_match:
        base, qid, enrichment = [int(x) for x in composition_match.groups()]
        total = base + qid + enrichment
        assert total == 157, (
            f"Phase 21 composition in comment should sum to 157; "
            f"found {base} + {qid} + {enrichment} = {total}"
        )


if __name__ == "__main__":
    test_22_6_n_features_is_len_feature_columns_not_literal()
    test_22_6_n_features_matches_phase21_canonical_value()
    test_22_6_n_features_stale_comment_reconciled()
    print("✅ All N_FEATURES tests passed")
