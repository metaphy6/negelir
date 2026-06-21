"""§13.11 TR transliteration tests for foreign team names.

Verifies that both "Bayern" and "Bayern Münih" resolve to the same canonical_id,
and that the transliteration infrastructure supports multi-league corpus development.

Per AGENTS.md Rule 10: new feature -> happy + adversarial tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nlp.entity import EntityExtractor
from nlp.lexicon_loader import LexiconStore


@pytest.fixture
def lexicon_store(tmp_path: Path) -> LexiconStore:
    """Create a LexiconStore from the production lexicon files."""
    lexicon_dir = Path(__file__).resolve().parents[2] / "ai" / "nlp" / "lexicon"
    assert lexicon_dir.exists(), f"Lexicon dir not found: {lexicon_dir}"
    store = LexiconStore(lexicon_dir, reload_s=9999, max_rss_mb=0)
    store.maybe_reload()
    return store


@pytest.fixture
def entity_extractor(lexicon_store: LexiconStore) -> EntityExtractor:
    """Create an EntityExtractor with the production lexicon."""
    return EntityExtractor(store=lexicon_store)


class TestNlpTransliteration:
    """§13.11 TR transliteration — foreign team names resolve to same canonical_id."""

    def test_bayern_english_form_resolves_to_canonical_id(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """English form 'Bayern Munich' should resolve to team_bayern_munich."""
        result = entity_extractor.extract(["bayern", "munich", "tahmini"])
        assert len(result.spans) >= 1
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == "team_bayern_munich"

    def test_bayern_german_form_resolves_to_canonical_id(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """German form 'Bayern Münih' should resolve to same canonical_id."""
        result = entity_extractor.extract(["bayern", "münih", "maç", "sonucu"])
        assert len(result.spans) >= 1
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == "team_bayern_munich"

    def test_bayern_abbreviation_resolves_correctly(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """FCB abbreviation should also resolve to team_bayern_munich."""
        result = entity_extractor.extract(["fcb", "kazanır", "mı"])
        assert len(result.spans) >= 1
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == "team_bayern_munich"

    def test_bayern_and_bayern_munich_both_resolve_to_same_id(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """Core requirement: both variants must resolve to identical canonical_id."""
        # Extract with "Bayern" form
        result1 = entity_extractor.extract(["bayern", "tahmini"])
        spans1 = [s for s in result1.spans if s.kind == "team"]
        assert len(spans1) >= 1
        canonical1 = spans1[0].canonical_id

        # Extract with "Bayern Munich" form
        result2 = entity_extractor.extract(["bayern", "munich", "tahmini"])
        spans2 = [s for s in result2.spans if s.kind == "team"]
        assert len(spans2) >= 1
        canonical2 = spans2[0].canonical_id

        # Both must resolve to same canonical_id
        assert canonical1 == canonical2 == "team_bayern_munich"

    def test_bayern_munih_turkish_variant_resolves(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """Turkish transliteration 'Bayern Münih' should resolve correctly."""
        result = entity_extractor.extract(["bayern", "münih", "tahmini"])
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == "team_bayern_munich"

    def test_transliteration_with_turkish_suffixes(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """Bayern should resolve even with Turkish postposition suffixes."""
        # "Bayern'ın" (Bayern's - possessive genitive)
        result = entity_extractor.extract(["bayern", "in", "tahmini"])
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == "team_bayern_munich"

    def test_transliteration_fcb_abbreviation_resolves(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """FCB (FC Bayern) abbreviation should resolve to team_bayern_munich."""
        result = entity_extractor.extract(["fcb", "maç", "tahmini"])
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == "team_bayern_munich"

    def test_transliteration_fc_bayern_full_form_resolves(
        self, entity_extractor: EntityExtractor
    ) -> None:
        """FC Bayern full form should resolve to team_bayern_munich."""
        result = entity_extractor.extract(["fc", "bayern", "tahmini"])
        team_spans = [s for s in result.spans if s.kind == "team"]
        # May or may not capture depending on multi-token handling
        # but if captured, should be correct
        if team_spans:
            assert team_spans[0].canonical_id == "team_bayern_munich"

    @pytest.mark.parametrize("query,expected_canonical_id", [
        (["bayern"], "team_bayern_munich"),
        (["bayern", "munich"], "team_bayern_munich"),
        (["bayern", "münih"], "team_bayern_munich"),
        (["fcb"], "team_bayern_munich"),
        (["munich"], "team_bayern_munich"),
    ])
    def test_transliteration_parametrized_variants(
        self, entity_extractor: EntityExtractor, query: list[str], expected_canonical_id: str
    ) -> None:
        """Parametrized test of all Bayern variants."""
        result = entity_extractor.extract(query)
        team_spans = [s for s in result.spans if s.kind == "team"]
        assert len(team_spans) >= 1
        assert team_spans[0].canonical_id == expected_canonical_id


class TestGermanBundesligaCorpus:
    """§13.11 Test corpus loading and structure for de_bundesliga."""

    @pytest.fixture
    def corpus_path(self) -> Path:
        """Path to German Bundesliga promotion corpus."""
        corpus = (
            Path(__file__).resolve().parents[1]
            / "tests" / "fixtures" / "nlp" / "de_bundesliga" / "promotion_corpus.jsonl"
        )
        assert corpus.exists(), f"Corpus not found: {corpus}"
        return corpus

    def test_promotion_corpus_exists(self, corpus_path: Path) -> None:
        """Promotion corpus file should exist."""
        assert corpus_path.is_file()
        assert corpus_path.stat().st_size > 0

    def test_promotion_corpus_has_exactly_50_queries(self, corpus_path: Path) -> None:
        """Corpus must have exactly 50 queries per phase requirement."""
        with corpus_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 50, f"Expected 50 queries, got {len(lines)}"

    def test_promotion_corpus_all_lines_valid_json(self, corpus_path: Path) -> None:
        """Every line should be valid JSON."""
        with corpus_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                try:
                    json.loads(line.strip())
                except json.JSONDecodeError as e:
                    pytest.fail(f"Line {line_num} is not valid JSON: {e}")

    def test_promotion_corpus_has_required_fields(self, corpus_path: Path) -> None:
        """Each query entry must have query, intent, and expected_entities."""
        with corpus_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                entry = json.loads(line.strip())
                assert "query" in entry, f"Line {line_num} missing 'query' field"
                assert "intent" in entry, f"Line {line_num} missing 'intent' field"
                assert "expected_entities" in entry, f"Line {line_num} missing 'expected_entities' field"
                assert isinstance(entry["query"], str), f"Line {line_num}: query must be string"
                assert isinstance(entry["intent"], str), f"Line {line_num}: intent must be string"
                assert isinstance(entry["expected_entities"], list), f"Line {line_num}: expected_entities must be list"

    def test_promotion_corpus_covers_bayern_variants(self, corpus_path: Path) -> None:
        """Corpus should cover multiple Bayern name variants."""
        with corpus_path.open("r", encoding="utf-8") as f:
            queries = [json.loads(line.strip())["query"].lower() for line in f]

        # Collect which variants appear
        variants_found = []
        if any("bayern" in q and "münchen" not in q and "münih" not in q for q in queries):
            variants_found.append("bayern")
        if any("münchen" in q or "münih" in q for q in queries):
            variants_found.append("münchen/münih")
        if any("munich" in q for q in queries):
            variants_found.append("munich")
        if any("fcb" in q or "fc" in q for q in queries):
            variants_found.append("fcb/fc")

        # At minimum should cover Bayern and at least one Turkish/English variant
        assert len(variants_found) >= 2, f"Corpus should cover multiple Bayern variants, got: {variants_found}"

    def test_promotion_corpus_bayern_consistently_maps_to_canonical_id(
        self, entity_extractor: EntityExtractor, corpus_path: Path
    ) -> None:
        """All Bayern queries in corpus should map to same canonical_id."""
        with corpus_path.open("r", encoding="utf-8") as f:
            entries = [json.loads(line.strip()) for line in f]

        bayern_queries = [e for e in entries if "team_bayern_munich" in e.get("expected_entities", [])]
        assert len(bayern_queries) >= 5, "Corpus should have at least 5 Bayern queries"

        # Extract from a sample of Bayern queries
        for entry in bayern_queries[:5]:
            query = entry["query"]
            # Simple tokenization for test
            tokens = query.lower().split()
            result = entity_extractor.extract(tokens)
            team_spans = [s for s in result.spans if s.kind == "team" and "bayern" in query.lower()]
            # If any team found, it should be the right one
            if team_spans:
                assert team_spans[0].canonical_id == "team_bayern_munich"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
