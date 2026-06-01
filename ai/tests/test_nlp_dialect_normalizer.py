"""Phase 10 §10.22.5 — Proof tests for dialect/abbreviation/vocative normalizer.

Per spec (22-turkish-input-robustness.md §10.22.5):
  test_nlp_dialect_yapicaz_expands_to_yapacagiz
  test_nlp_abbreviation_gs_resolves_to_galatasaray
  test_nlp_abbreviation_rm_requires_co_token
  test_nlp_vocative_filler_dropped_does_not_change_intent
  test_nlp_dialect_and_entity_dialect_tables_are_disjoint  (build guard)

Per AGENTS.md Rule 10: happy + adversarial + regression.
"""
from __future__ import annotations

import pathlib
import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LANG_TR = pathlib.Path("ai/nlp/lang_tr")


def _normalizer():
    from nlp.dialect_normalize import _DialectNormalizer
    return _DialectNormalizer()


# ---------------------------------------------------------------------------
# §10.22.5 named proof: yapıcaz → yapacağız  (future-contraction rule)
# ---------------------------------------------------------------------------
class TestDialectYapicazExpandsToYapacagiz:
    def test_yapicaz_expands(self) -> None:
        n = _normalizer()
        r = n.normalize(["yapıcaz"])
        assert "yapacağız" in r.tokens
        assert any(src == "yapıcaz" for src, _ in r.dialect_repairs)

    def test_gidecez_expands(self) -> None:
        """Front-vowel variant: -ecez → -eceğiz."""
        n = _normalizer()
        r = n.normalize(["gidecez"])
        assert "gideceğiz" in r.tokens
        assert any(src == "gidecez" for src, _ in r.dialect_repairs)

    def test_geliyo_expands(self) -> None:
        """Gerund r-drop rule: -iyo → -iyor."""
        n = _normalizer()
        r = n.normalize(["geliyo"])
        assert "geliyor" in r.tokens

    def test_dimi_expands_to_degil_mi(self) -> None:
        """Negation-question compound: dimi → değil mi (2 tokens)."""
        n = _normalizer()
        r = n.normalize(["dimi"])
        assert "değil" in r.tokens
        assert "mi" in r.tokens

    def test_birsey_splits(self) -> None:
        """birşey → bir şey (two tokens, handled by birsey_compound rule)."""
        n = _normalizer()
        r = n.normalize(["birşey"])
        assert "bir" in r.tokens, "birşey did not produce 'bir'"
        assert "şey" in r.tokens, "birşey did not produce 'şey'"

    def test_clean_token_unchanged(self) -> None:
        """Tokens that need no repair must pass through unchanged."""
        n = _normalizer()
        r = n.normalize(["galatasaray", "maç", "tahmini"])
        assert r.tokens == ("galatasaray", "maç", "tahmini")
        assert len(r.dialect_repairs) == 0


# ---------------------------------------------------------------------------
# §10.22.5 named proof: GS → Galatasaray  (hard abbreviation)
# ---------------------------------------------------------------------------
class TestAbbreviationGsResolvesToGalatasaray:
    def test_gs_hard_expand(self) -> None:
        n = _normalizer()
        r = n.normalize(["gs"])
        assert "galatasaray" in r.tokens
        assert any(src == "gs" for src, _ in r.abbreviations_expanded)

    def test_fb_hard_expand(self) -> None:
        # expansion_canonical_id is the ASCII entity-ID used by the gazetteer
        n = _normalizer()
        r = n.normalize(["fb"])
        assert "fenerbahce" in r.tokens

    def test_bjk_hard_expand(self) -> None:
        n = _normalizer()
        r = n.normalize(["bjk"])
        assert "besiktas" in r.tokens

    def test_ts_hard_expand(self) -> None:
        n = _normalizer()
        r = n.normalize(["ts"])
        assert "trabzonspor" in r.tokens

    def test_gs_in_context(self) -> None:
        """GS still expands when surrounded by other tokens."""
        n = _normalizer()
        r = n.normalize(["gs", "maç", "tahmini"])
        assert "galatasaray" in r.tokens
        assert "maç" in r.tokens

    def test_unknown_abbrev_not_expanded(self) -> None:
        """Tokens not in the table must not be modified."""
        n = _normalizer()
        r = n.normalize(["xyz"])
        assert r.tokens == ("xyz",)
        assert len(r.abbreviations_expanded) == 0


# ---------------------------------------------------------------------------
# §10.22.5 named proof: RM requires co-token  (soft abbreviation)
# ---------------------------------------------------------------------------
class TestAbbreviationRmRequiresCoToken:
    def test_rm_without_co_token_not_expanded(self) -> None:
        n = _normalizer()
        r = n.normalize(["rm"])
        assert r.tokens == ("rm",), (
            "soft abbreviation 'rm' must NOT expand without a required co-token"
        )
        assert len(r.abbreviations_expanded) == 0

    def test_rm_with_madrid_co_token_expands(self) -> None:
        n = _normalizer()
        r = n.normalize(["rm", "madrid"])
        assert "real_madrid" in r.tokens

    def test_rm_adversarial_partial_context(self) -> None:
        """RM should not expand with an irrelevant neighbour."""
        n = _normalizer()
        r = n.normalize(["rm", "tahmini"])
        # tahmini is not a required co-token for rm
        assert "real_madrid" not in r.tokens


# ---------------------------------------------------------------------------
# §10.22.5 named proof: vocative/filler stripped
# ---------------------------------------------------------------------------
class TestVocativeFillerDroppedDoesNotChangeIntent:
    def test_abi_stripped(self) -> None:
        n = _normalizer()
        r = n.normalize(["abi", "galatasaray", "maç"])
        assert "abi" not in r.tokens
        assert "galatasaray" in r.tokens
        assert "abi" in r.vocatives_stripped

    def test_reis_stripped(self) -> None:
        n = _normalizer()
        r = n.normalize(["reis", "skor", "ne"])
        assert "reis" not in r.tokens
        assert "skor" in r.tokens

    def test_vocative_only_input_yields_empty(self) -> None:
        n = _normalizer()
        r = n.normalize(["abi"])
        assert r.tokens == ()
        assert "abi" in r.vocatives_stripped

    def test_non_vocative_not_stripped(self) -> None:
        n = _normalizer()
        r = n.normalize(["galatasaray"])
        assert r.tokens == ("galatasaray",)
        assert len(r.vocatives_stripped) == 0

    def test_vocative_mid_sentence(self) -> None:
        n = _normalizer()
        r = n.normalize(["bu", "abi", "gs", "maç"])
        assert "abi" not in r.tokens
        assert "bu" in r.tokens
        assert "galatasaray" in r.tokens


# ---------------------------------------------------------------------------
# §10.22.5 build guard: dialect and abbreviation tables must be disjoint
# ---------------------------------------------------------------------------
class TestDialectAndEntityDialectTablesAreDisjoint:
    def test_no_token_in_both_tables(self) -> None:
        """No token must appear in both dialect seed_entries AND abbreviations."""
        abbrev_data = yaml.safe_load(
            (LANG_TR / "abbreviations.tr.yaml").read_text(encoding="utf-8")
        )
        dialect_data = yaml.safe_load(
            (LANG_TR / "dialect.tr.yaml").read_text(encoding="utf-8")
        )
        abbrev_tokens = {e["abbreviation"] for e in abbrev_data.get("abbreviations", [])}
        seed_tokens = {
            e["spoken"] for e in dialect_data.get("seed_entries", [])
        }
        overlap = abbrev_tokens & seed_tokens
        assert not overlap, (
            f"Tokens appear in BOTH abbreviations.tr.yaml AND dialect.tr.yaml: {overlap}. "
            "These tables must be disjoint (§10.22.5 spec)."
        )

    def test_abbreviations_schema_has_required_fields(self) -> None:
        """Every abbreviation entry must have all required fields."""
        abbrev_data = yaml.safe_load(
            (LANG_TR / "abbreviations.tr.yaml").read_text(encoding="utf-8")
        )
        required = {"abbreviation", "expansion_canonical_id", "ambiguity_class"}
        for entry in abbrev_data.get("abbreviations", []):
            missing = required - entry.keys()
            assert not missing, (
                f"abbreviation entry {entry.get('abbreviation')!r} missing fields: {missing}"
            )

    def test_vocative_table_has_token_field(self) -> None:
        """Every vocative entry must have a 'token' key."""
        voc_data = yaml.safe_load(
            (LANG_TR / "vocative_filler.tr.yaml").read_text(encoding="utf-8")
        )
        for entry in voc_data.get("vocative", []) + voc_data.get("fillers", []):
            assert "token" in entry, f"vocative entry missing 'token': {entry}"


# ---------------------------------------------------------------------------
# Regression: normalize_input pipeline includes dialect_normalize step
# ---------------------------------------------------------------------------
class TestDialectNormalizeIntegration:
    def test_step_in_pipeline(self) -> None:
        from nlp.normalize import normalize_input
        r = normalize_input("yapıcaz maç tahmini abi")
        assert "dialect_normalize" in r.steps_run

    def test_yapicaz_expands_through_pipeline(self) -> None:
        from nlp.normalize import normalize_input
        r = normalize_input("yapıcaz maç tahmini")
        assert "yapacağız" in r.tokens

    def test_gs_expands_through_pipeline(self) -> None:
        from nlp.normalize import normalize_input
        r = normalize_input("gs maç")
        assert "galatasaray" in r.tokens

    def test_vocative_stripped_through_pipeline(self) -> None:
        from nlp.normalize import normalize_input
        r = normalize_input("abi gs maç")
        assert "abi" not in r.tokens
        assert "galatasaray" in r.tokens
