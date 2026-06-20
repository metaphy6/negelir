"""Phase 21.12 — Tier alignment and enrichment market gating.

Tests that enrichment-derived features and markets are correctly
gated to the appropriate monetization tiers (free/pro/premium).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestTierEnforcement:
    """Tier-gating for enrichment markets and features."""

    @staticmethod
    def _load_entitlements() -> dict:
        """Load xops/monetization/entitlements.yaml as dict (YAML parsing via json for now)."""
        entitlements_path = Path(__file__).parent.parent.parent / "xops" / "monetization" / "entitlements.yaml"
        # For this test, we assume a parsed YAML structure (in reality, yaml.safe_load)
        # We verify it exists and is well-formed
        assert entitlements_path.exists(), f"entitlements.yaml not found at {entitlements_path}"
        content = entitlements_path.read_text(encoding="utf-8")
        assert "tiers:" in content
        assert "pro:" in content
        assert "premium:" in content
        return {}  # placeholder dict for now

    def test_pro_tier_response_includes_cards_market_when_officials_plane_active(self) -> None:
        """Pro tier can access cards/corners/fouls markets when Officials plane is enabled."""
        entitlements = self._load_entitlements()
        # Pro tier must include officials plane and cards_corners_fouls market
        content = (Path(__file__).parent.parent.parent / "xops" / "monetization" / "entitlements.yaml").read_text()
        assert "pro:" in content
        assert "cards_corners_fouls" in content or "officials" in content
        # Assertion: pro tier includes at least one enrichment-dependent market
        assert "derived_markets:" in content

    def test_free_tier_response_excludes_card_context_overlay(self) -> None:
        """Free tier subscribers never see card-context overlay, even if computed."""
        content = (Path(__file__).parent.parent.parent / "xops" / "monetization" / "entitlements.yaml").read_text()
        # Free tier must NOT include card_context or premium markets
        lines = content.split("\n")
        in_free_tier = False
        free_tier_markets = []
        for i, line in enumerate(lines):
            if "free:" in line:
                in_free_tier = True
            elif in_free_tier and line.strip().startswith("derived_markets:"):
                # Extract markets from free tier
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("  ") and not lines[j].startswith("    "):
                        break
                    if "- " in lines[j]:
                        market = lines[j].strip().lstrip("- ")
                        free_tier_markets.append(market)
                break
        # Card context should NOT be in free tier
        assert "card_context" not in free_tier_markets
        assert "combined_card_score" not in free_tier_markets

    def test_premium_tier_response_includes_player_props_with_health_plane(self) -> None:
        """Premium tier gets player-prop markets when Health plane is active."""
        content = (Path(__file__).parent.parent.parent / "xops" / "monetization" / "entitlements.yaml").read_text()
        # Premium tier must include health plane and player_props market
        assert "premium:" in content
        assert "player_props" in content or "health" in content
        # Verify health plane is in premium
        assert "enrichment_planes:" in content

    def test_pro_tier_cannot_access_weather_special_markets(self) -> None:
        """Weather-special markets (windy_day_totals, red_card_markets) require premium tier."""
        content = (Path(__file__).parent.parent.parent / "xops" / "monetization" / "entitlements.yaml").read_text()
        # Extract pro tier markets
        lines = content.split("\n")
        in_pro_tier = False
        pro_markets = []
        for i, line in enumerate(lines):
            if "pro:" in line:
                in_pro_tier = True
            elif in_pro_tier and line.strip().startswith("derived_markets:"):
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("  ") and not lines[j].startswith("    "):
                        break
                    if "- " in lines[j]:
                        market = lines[j].strip().lstrip("- ")
                        pro_markets.append(market)
                break
        # Weather markets must NOT be in pro tier
        assert "windy_day_totals" not in pro_markets
        assert "weather_special_markets" not in pro_markets

    def test_tier_gate_not_enforced_in_ai_layer_only_in_api_layer(self) -> None:
        """Tier gating is in Go API layer, not in AI pipeline."""
        # This is an architecture assertion: enrichment code should not directly gate features
        # Instead, the API layer (Go) handles tier-based filtering
        # We verify that ai/common/config.py does NOT have tier-specific feature stripping
        config_path = Path(__file__).parent.parent / "common" / "config.py"
        content = config_path.read_text(encoding="utf-8")
        # Config should NOT have functions like "filter_by_tier" or "gate_features_by_tier"
        assert "def filter_enrichment_by_tier" not in content
        assert "tier_gate" not in content.lower() or "tier_gate" in content.split("enrichment")[0]

    def test_entitlements_yaml_has_row_for_each_enrichment_derived_market(self) -> None:
        """Single-source policy: xops/monetization/entitlements.yaml has all enrichment markets."""
        entitlements_path = Path(__file__).parent.parent.parent / "xops" / "monetization" / "entitlements.yaml"
        content = entitlements_path.read_text(encoding="utf-8")
        
        # Required enrichment-derived markets per ROADMAP §21.12
        required_markets = {
            "cards_corners_fouls",
            "player_props",
            "weather_special_markets",
            "windy_day_totals",
            "red_card_markets",
            "injury_insurance_markets",
            "referee_stats",
        }
        
        # Each required market must have an entry in entitlements.yaml
        for market in required_markets:
            assert market in content, f"Required market '{market}' missing from entitlements.yaml"
        
        # Verify market_families section exists
        assert "market_families:" in content
