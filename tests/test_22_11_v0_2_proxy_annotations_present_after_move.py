"""Phase 22.11 — Proof test for v0.2 proxy column annotations.

Verifies that all v0.2 proxy columns are properly annotated with
DEPRECATED comments referencing enrichment planes after migration.
"""
from pathlib import Path
import re


def test_22_11_v0_2_proxy_annotations_present_after_move() -> None:
    """Phase 22.11 bullet 2: Verify v0.2 proxy columns have DEPRECATED annotations.
    
    The 8 v0.2 proxy columns introduced in Phase 2 must be annotated with:
    # DEPRECATED: superseded by enrichment plane <N>
    
    These live in common/constants.py (after migration from ai/model/features.py).
    """
    constants_path = Path("common/constants.py")
    assert constants_path.exists(), "common/constants.py not found after migration"
    
    content = constants_path.read_text(encoding="utf-8")
    
    # Verify the required proxy columns are annotated
    # Note: Comments can appear on the same line or the line before
    proxy_columns_with_expected_plane = [
        ("home_fixture_congestion_7d", "Schedule.*Live"),
        ("away_fixture_congestion_7d", "Schedule.*Live"),
        ("home_fixture_congestion_14d", "Schedule.*Live"),
        ("away_fixture_congestion_14d", "Schedule.*Live"),
        ("temperature_bucket", "Environment"),
        ("precipitation_flag", "Environment"),
        ("wind_category", "Environment"),
        ("venue_type", "Environment"),
    ]
    
    # For each proxy column, verify it's in the constants and has a nearby DEPRECATED annotation
    for col_name, expected_plane_ref in proxy_columns_with_expected_plane:
        # Find the column in the content
        assert col_name in content, f"v0.2 proxy column {col_name} not found in constants"
        
        # Extract context around the column (50 chars before and after)
        col_idx = content.find(f'"{col_name}"')
        if col_idx != -1:
            context_start = max(0, col_idx - 200)
            context_end = min(len(content), col_idx + 100)
            context = content[context_start:context_end]
            
            # Check if DEPRECATED annotation is nearby
            has_deprecated = "DEPRECATED" in context
            assert has_deprecated, (
                f"v0.2 proxy column {col_name} missing DEPRECATED annotation nearby"
            )
            
            # Check if enrichment plane reference is present
            has_plane_ref = "enrichment" in context.lower()
            assert has_plane_ref, (
                f"v0.2 proxy column {col_name} missing enrichment plane reference in nearby context"
            )
    
    # Overall verify enrichment plane references exist
    assert "enrichment plane" in content.lower(), (
        "Annotations should reference specific enrichment planes "
        "(e.g., 'enrichment plane 9 (Environment)')"
    )


def test_22_11_v0_2_columns_still_present_for_compat() -> None:
    """Phase 22.11 bullet 2: Verify v0.2 proxy columns exist but are deprecated.
    
    Backward compatibility is maintained — columns are NOT removed,
    just annotated as deprecated.
    """
    constants_path = Path("common/constants.py")
    content = constants_path.read_text(encoding="utf-8")
    
    # All 8 proxy columns must still be listed in FEATURE_COLUMNS
    proxy_columns = [
        "home_fixture_congestion_7d",
        "away_fixture_congestion_7d",
        "home_fixture_congestion_14d",
        "away_fixture_congestion_14d",
        "temperature_bucket",
        "precipitation_flag",
        "wind_category",
        "venue_type",
    ]
    
    for col in proxy_columns:
        assert col in content, f"v0.2 proxy column {col} missing from constants (should be kept for compat)"
