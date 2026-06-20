"""Phase 19 §19.9 — Input sanitiser blocks injection."""
import pytest


def test_catalog_field_sanitiser_blocks_injection():
    """Dangerous patterns are rejected."""
    from ai.common.security.input_sanitiser import sanitise_catalog_field, SanitationError
    
    dangerous = [
        "<script>alert(1)</script>",
        "'; DROP TABLE--",
        "\x00 null byte",
    ]
    for danger in dangerous:
        with pytest.raises(SanitationError):
            sanitise_catalog_field(danger)
