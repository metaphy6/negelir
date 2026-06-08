"""
Phase 12.1.2 lint: every trust boundary has a catalogue ID and catcher.

This lint validates that:
1. Every trust boundary in trust_boundary_schema has ≥1 catalogue ID
2. Every trust boundary is referenced in the §12.16 coupling matrix
3. The catcher-of-record invariant is enforceable (expected_catcher in corpus)
"""

import sys
sys.path.insert(0, "/home/serhatakbak/code/mine/negelir/xops/lint")

from trust_boundary_schema import TRUST_BOUNDARIES, validate_trust_boundaries


def test_every_trust_boundary_has_catalogue_family():
    """§12.1.2: Every row maps to ≥ 1 stable catalogue ID in §12.5."""
    for tb in TRUST_BOUNDARIES:
        assert len(tb.catalogue_families) > 0, \
            f"Trust boundary '{tb.name}' has no catalogue families"
        for family in tb.catalogue_families:
            assert family.startswith("P12-"), \
                f"Invalid catalogue family '{family}' for '{tb.name}'"
    print("✓ All trust boundaries have ≥1 catalogue ID")


def test_catcher_module_nonempty():
    """§12.1.2: Catcher-of-record invariant — every boundary knows its catcher."""
    for tb in TRUST_BOUNDARIES:
        assert tb.catcher_agent, f"No catcher_agent for {tb.name}"
        assert tb.catcher_module, f"No catcher_module for {tb.name}"
    print("✓ All trust boundaries declare their catcher")


def test_trust_boundary_uniqueness():
    """Each trust boundary has a unique, descriptive name."""
    names = [tb.name for tb in TRUST_BOUNDARIES]
    assert len(names) == len(set(names)), "Duplicate trust boundary names"
    print("✓ All trust boundary names are unique")


if __name__ == "__main__":
    test_every_trust_boundary_has_catalogue_family()
    test_catcher_module_nonempty()
    test_trust_boundary_uniqueness()
    validate_trust_boundaries()
    print("\n✓ §12.1.2 trust boundary coverage lint passes")
