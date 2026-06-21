"""Phase 19 §19.9 — Input sanitiser is idempotent."""
import pytest


def test_catalog_field_sanitiser_idempotent():
    """Sanitiser: f(f(x)) == f(x)."""
    from common.security.input_sanitiser import sanitise_catalog_field
    
    test_strings = [
        "Normal League Name",
        "Lig\u00fc",  # Turkish ğ
        "Team 123",
    ]
    for s in test_strings:
        once = sanitise_catalog_field(s)
        twice = sanitise_catalog_field(once)
        assert once == twice, f"Not idempotent: {s!r} -> {once!r} -> {twice!r}"
