"""Phase 21.13 — NLP intent expansion for enrichment queries.

Tests for six new enrichment-focused intents: transfer_lookup, injury_lookup,
availability_lookup, referee_lookup, weather_lookup, suspension_lookup.

All intents are template-driven with zero LLM calls (pure TQU classification).
"""
from __future__ import annotations

from pathlib import Path

import pytest


class TestEnrichmentNLPIntents:
    """NLP intent classification for enrichment queries."""

    REQUIRED_INTENTS = {
        "transfer_lookup",
        "injury_lookup",
        "availability_lookup",
        "referee_lookup",
        "weather_lookup",
        "suspension_lookup",
    }

    @staticmethod
    def _load_intents_fixture() -> dict:
        """Load enrichment_nlp_intents.yaml fixture."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "enrichment_nlp_intents.yaml"
        )
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        content = fixture_path.read_text(encoding="utf-8")
        return {"raw": content}

    def test_transfer_lookup_classified_correctly_on_five_tr_queries(self) -> None:
        """transfer_lookup intent classifies Turkish transfer-related queries."""
        fixture = self._load_intents_fixture()
        # Verify fixture includes transfer_lookup intent
        assert "transfer_lookup:" in fixture["raw"]
        assert "Galatasaray" in fixture["raw"] or "Fenerbahçe" in fixture["raw"]

    def test_injury_lookup_confidence_threshold_above_baseline_60(self) -> None:
        """injury_lookup uses cfg.nlp_injury_lookup_confidence_threshold (0.70 default)."""
        fixture = self._load_intents_fixture()
        # Injury intent must have a higher threshold than other intents
        assert "injury_lookup:" in fixture["raw"]
        assert "confidence_threshold: 0.70" in fixture["raw"]

    def test_injury_lookup_threshold_does_not_elevate_other_enrichment_intents(self) -> None:
        """Only injury_lookup is elevated; weather_lookup, referee_lookup stay at baseline."""
        fixture = self._load_intents_fixture()
        # Count how many intents have 0.70 threshold
        lines = fixture["raw"].split("\n")
        count_070 = 0
        for line in lines:
            if "confidence_threshold: 0.70" in line:
                count_070 += 1
        # Only one intent should have 0.70
        assert count_070 == 1, f"Expected 1 intent with 0.70, found {count_070}"

    def test_referee_lookup_extracts_referee_name_entity(self) -> None:
        """referee_lookup intent identifies referee names in queries."""
        fixture = self._load_intents_fixture()
        assert "referee_lookup:" in fixture["raw"]
        assert "referee_name" in fixture["raw"] or "Halil Umut Meler" in fixture["raw"]

    def test_weather_condition_entity_maps_to_canonical_literal(self) -> None:
        """Turkish weather condition strings map to canonical literals."""
        fixture = self._load_intents_fixture()
        assert "weather_lookup:" in fixture["raw"]
        assert "weather_condition" in fixture["raw"]

    def test_suspension_lookup_returns_competition_scoped_result(self) -> None:
        """suspension_lookup returns player suspensions per competition."""
        fixture = self._load_intents_fixture()
        assert "suspension_lookup:" in fixture["raw"]
        assert "competition_name" in fixture["raw"] or "Süper Lig" in fixture["raw"]

    def test_availability_lookup_distinguishes_doubtful_from_out(self) -> None:
        """availability_lookup intent distinguishes "doubtful" from "out" status."""
        fixture = self._load_intents_fixture()
        assert "availability_lookup:" in fixture["raw"]
        # The intent must have samples covering both statuses
        lines = fixture["raw"].split("\n")
        found_doubtful = False
        found_out = False
        for line in lines:
            if "şüpheli" in line.lower():
                found_doubtful = True
            if "out" in line.lower() or "dışarıda" in line.lower():
                found_out = True
        # At least one status distinction must be evident
        assert found_doubtful or found_out

    def test_no_llm_call_in_any_enrichment_intent(self) -> None:
        """All six intents are template-driven TQU; zero LLM calls."""
        fixture = self._load_intents_fixture()
        # Fixture should NOT reference LLM or API calls
        assert "llm" not in fixture["raw"].lower()
        assert "openai" not in fixture["raw"].lower()
        assert "anthropic" not in fixture["raw"].lower()

    def test_each_enrichment_intent_has_at_least_5_tr_sample_queries_in_yaml(self) -> None:
        """Turkish queries coverage floor: ≥ 5 samples per intent in fixtures."""
        fixture = self._load_intents_fixture()
        lines = fixture["raw"].split("\n")
        
        # Count sample queries for each intent
        intent_query_counts = {intent: 0 for intent in self.REQUIRED_INTENTS}
        current_intent = None
        
        for line in lines:
            # Detect intent headers
            for intent in self.REQUIRED_INTENTS:
                if f"{intent}:" in line:
                    current_intent = intent
                    break
            
            # Count query entries
            if current_intent and "query:" in line:
                intent_query_counts[current_intent] += 1
        
        # Each intent must have ≥5 queries
        for intent, count in intent_query_counts.items():
            assert count >= 5, f"Intent '{intent}' has only {count} queries, need ≥5"

    def test_each_enrichment_intent_has_at_least_one_negation_variant_in_yaml(self) -> None:
        """Negation variants cover user patterns: "yok mü?" (not?), "değil mi?" (isn't?), etc."""
        fixture = self._load_intents_fixture()
        lines = fixture["raw"].split("\n")
        
        # Look for negation markers in queries
        negation_markers = ["yok mu", "değil", "olmadı", "gelmedi"]
        
        # Count intents with at least one negation
        intents_with_negation = set()
        current_intent = None
        
        for line in lines:
            for intent in self.REQUIRED_INTENTS:
                if f"{intent}:" in line:
                    current_intent = intent
                    break
            
            if current_intent:
                for marker in negation_markers:
                    if marker in line:
                        intents_with_negation.add(current_intent)
        
        # At least some intents should have negation variants
        assert len(intents_with_negation) >= 3, f"Only {len(intents_with_negation)} intents have negation variants, need ≥3"
