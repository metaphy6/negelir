"""Phase 19 §19.8 — Failing preflight blocks promotion tier-flip PR."""
import pytest


def test_failing_preflight_blocks_promotion():
    """A failing preflight report prevents tier field from being flipped."""
    from xops.lint.promotion_preflight_lint import PromotionPreflightLint
    
    linter = PromotionPreflightLint()
    
    # Simulate a tier change without a passing preflight
    result = linter.check_pr_tier_change(
        league_id="br_serie_a",
        new_tier="T2",
        has_passing_preflight=False
    )
    
    assert result["allowed"] is False
    assert "preflight" in result["reason"].lower()


def test_passing_preflight_allows_promotion():
    """A passing preflight report allows tier field flip."""
    from xops.lint.promotion_preflight_lint import PromotionPreflightLint
    
    linter = PromotionPreflightLint()
    result = linter.check_pr_tier_change(
        league_id="br_serie_a",
        new_tier="T2",
        has_passing_preflight=True
    )
    
    assert result["allowed"] is True
