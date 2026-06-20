"""Phase 19 §19.9 — Valid DPA entry enables restricted planes."""
import pytest


def test_dpa_entry_enables_restricted_planes():
    """Once DPA is documented, restricted planes can be enabled."""
    from ai.common.isolation.dpa_validator import can_enable_restricted_planes
    
    # Mock: with DPA, returns True
    result = can_enable_restricted_planes("gdpr_league", dpa_entered=True)
    assert result is True
