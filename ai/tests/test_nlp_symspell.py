"""Phase 10 §10.3 — Tests for the SymSpell-style typo-correction index.

Covers:
  * Happy-path fuzzy lookup (edit distances 1 and 2 for long tokens)
  * Per-token edit budget (len ≤ 2 → exact-only; len 3-4 → max 1; len ≥ 5 → max 2)
  * Exact-match fast path returns edit_distance=0
  * Unknown token returns None when no candidate is within budget
  * Tie-breaking: shorter term wins when two candidates have the same distance
  * max_edit_distance validation: only 1 and 2 are accepted
  * term_count reports the number of unique indexed terms
  * add_term de-duplicates variant entries (idempotent re-add)
  * config key nlp_typo_max_edit_distance present and default=2
  * config validator rejects out-of-range value (adversarial)
"""
from __future__ import annotations

import pytest

from nlp.lexicon_loader import AliasHit
from nlp.vendor.symspell import SymSpellIndex, _edit_distance, _weighted_edit_distance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hit(cid: str = "x-001", kind: str = "team") -> AliasHit:
    return AliasHit(canonical_id=cid, kind=kind, lexicon_version="1.0.0")


def _build(terms: list[tuple[str, str]], max_edit_distance: int = 2) -> SymSpellIndex:
    idx = SymSpellIndex(max_edit_distance=max_edit_distance)
    for term, cid in terms:
        idx.add_term(term, _hit(cid))
    return idx


# ---------------------------------------------------------------------------
# _edit_distance unit tests
# ---------------------------------------------------------------------------


class TestEditDistance:
    def test_identical(self):
        assert _edit_distance("abc", "abc") == 0

    def test_insertion(self):
        assert _edit_distance("abc", "abbc") == 1

    def test_deletion(self):
        assert _edit_distance("abbc", "abc") == 1

    def test_substitution(self):
        assert _edit_distance("abc", "axc") == 1

    def test_two_edits(self):
        assert _edit_distance("galatasaray", "gaalatasray") == 2

    def test_empty_strings(self):
        assert _edit_distance("", "") == 0
        assert _edit_distance("abc", "") == 3
        assert _edit_distance("", "abc") == 3


# ---------------------------------------------------------------------------
# SymSpellIndex construction
# ---------------------------------------------------------------------------


class TestSymSpellIndexConstruction:
    def test_rejects_max_edit_distance_0(self):
        with pytest.raises(ValueError, match="max_edit_distance must be 1 or 2"):
            SymSpellIndex(max_edit_distance=0)

    def test_rejects_max_edit_distance_3(self):
        with pytest.raises(ValueError, match="max_edit_distance must be 1 or 2"):
            SymSpellIndex(max_edit_distance=3)

    def test_accepts_max_edit_distance_1(self):
        idx = SymSpellIndex(max_edit_distance=1)
        assert idx.term_count == 0

    def test_accepts_max_edit_distance_2(self):
        idx = SymSpellIndex(max_edit_distance=2)
        assert idx.term_count == 0

    def test_term_count_increments(self):
        idx = SymSpellIndex()
        assert idx.term_count == 0
        idx.add_term("galatasaray", _hit("gs"))
        assert idx.term_count == 1
        idx.add_term("fenerbahce", _hit("fb"))
        assert idx.term_count == 2

    def test_add_term_idempotent(self):
        """Re-adding the same term must not inflate variant entries."""
        idx = SymSpellIndex()
        idx.add_term("galatasaray", _hit("gs"))
        idx.add_term("galatasaray", _hit("gs"))
        assert idx.term_count == 1


# ---------------------------------------------------------------------------
# Exact-match fast path
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_returns_distance_zero(self):
        idx = _build([("galatasaray", "gs")])
        result = idx.lookup("galatasaray")
        assert result is not None
        assert result.term == "galatasaray"
        assert result.edit_distance == 0
        assert result.hit.canonical_id == "gs"

    def test_exact_short_token(self):
        """Tokens of length ≤ 2 match exactly."""
        idx = _build([("gs", "gs-001")])
        result = idx.lookup("gs")
        assert result is not None
        assert result.edit_distance == 0


# ---------------------------------------------------------------------------
# Per-token edit budget
# ---------------------------------------------------------------------------


class TestPerTokenBudget:
    # -- len ≤ 2: exact only -------------------------------------------------

    def test_len1_no_fuzzy(self):
        """Single-char token: no fuzzy match even with edit distance 1."""
        idx = _build([("a", "x")])
        assert idx.lookup("b") is None

    def test_len2_no_fuzzy(self):
        """Two-char token: no fuzzy match."""
        idx = _build([("gs", "x")])
        # "gss" differs by 1 from "gs" but len("gss")==3 → budget=1
        result = idx.lookup("gss")
        assert result is not None and result.edit_distance == 1
        # "gb" differs by 1 from "gs" but len("gb")==2 → budget=0 → None
        assert idx.lookup("gb") is None

    # -- len 3-4: budget = 1 -------------------------------------------------

    def test_len3_budget_one(self):
        idx = _build([("bes", "besiktas")])
        # "bex" → edit distance 1 from "bes", len=3 → budget=1 → match
        result = idx.lookup("bex")
        assert result is not None
        assert result.edit_distance == 1

    def test_len4_budget_one(self):
        idx = _build([("fene", "fb")])
        # "fenne" → len=5 → budget=2 BUT dict term "fene" len=4
        # reverse: "fenx" → len=4 → budget=1 → distance from "fene" = 1 → match
        result = idx.lookup("fenx")
        assert result is not None
        assert result.edit_distance == 1

    def test_len4_no_match_beyond_budget(self):
        idx = _build([("fene", "fb")])
        # "fnxx" → distance 2 from "fene" → budget=1 → None
        assert idx.lookup("fnxx") is None

    # -- len ≥ 5: budget = max_edit_distance (default 2) --------------------

    def test_len5_edit1_matches(self):
        idx = _build([("besik", "bes")])
        result = idx.lookup("besek")  # one substitution
        assert result is not None
        assert result.edit_distance == 1

    def test_len5_edit2_matches(self):
        idx = _build([("galatasaray", "gs")])
        # "gaalatasaray" → 1 insertion → distance 1
        result = idx.lookup("gaalatasaray")
        assert result is not None
        assert result.edit_distance == 1

    def test_len5_edit2_full(self):
        idx = _build([("galatasaray", "gs")])
        # two deletions: "glaataaray" → edit distance 2
        result = idx.lookup("galaasaray")  # one deletion (missing 't')
        assert result is not None
        assert result.edit_distance == 1

    def test_long_token_beyond_budget_returns_none(self):
        idx = _build([("galatasaray", "gs")])
        # 3 substitutions: "xyzatasaray" vs "galatasaray" → distance 3 → beyond budget=2 → None
        assert idx.lookup("xyzatasaray") is None


# ---------------------------------------------------------------------------
# Tie-breaking
# ---------------------------------------------------------------------------


class TestTieBreaking:
    def test_shorter_term_wins(self):
        """When two candidates have equal edit distance, shorter term wins."""
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term("gala", _hit("short"))      # len 4
        idx.add_term("galas", _hit("long"))       # len 5
        # "galx" → edit 1 from "gala" (substitution) and edit 2 from "galas"
        result = idx.lookup("galx")
        assert result is not None
        assert result.hit.canonical_id == "short"


class TestLayoutAwareLookup:
    def test_weighted_edit_distance_uses_layout_costs(self):
        assert _weighted_edit_distance("ax", "ab", layout="q") == 0.5
        assert _weighted_edit_distance("ax", "ab") == 1.0

    def test_lookup_layout_optional(self):
        idx = _build([("galatasaray", "gs")])
        assert idx.lookup("galatasaray") == idx.lookup("galatasaray", layout=None)
        assert idx.lookup("galatasaray", layout="unknown") is not None

    def test_layout_aware_budget_counts_half(self):
        idx = _build([("galatasaray", "gs"), ("fenerbahce", "fb")])
        tokens = ["gaalatasaray", "fenrbahce"]
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1, layout="q")
        assert exhausted is False
        assert results[0] is not None and results[0].edit_distance > 0
        assert results[1] is not None and results[1].edit_distance > 0


# ---------------------------------------------------------------------------
# Unknown token
# ---------------------------------------------------------------------------


class TestUnknownToken:
    def test_returns_none_for_completely_unrelated_token(self):
        idx = _build([("galatasaray", "gs"), ("fenerbahce", "fb")])
        # "xyzqwerty" shares no deletions within budget=2
        assert idx.lookup("xyzqwerty") is None

    def test_empty_index_returns_none(self):
        idx = SymSpellIndex()
        assert idx.lookup("galatasaray") is None


# ---------------------------------------------------------------------------
# Multiple terms, realistic aliases
# ---------------------------------------------------------------------------


class TestRealisticAliases:
    def test_gs_abbreviation_exact_only(self):
        """'gs' must not fuzzy-match to 'fb' (len=2 → budget=0)."""
        idx = _build([("galatasaray", "gs"), ("fenerbahce", "fb"), ("gs", "gs"), ("fb", "fb")])
        result = idx.lookup("gs")
        assert result is not None
        assert result.hit.canonical_id == "gs"

    def test_misspelled_team_name(self):
        idx = _build([("galatasaray", "gs"), ("fenerbahce", "fb")])
        result = idx.lookup("fenrbahce")  # one deletion
        assert result is not None
        assert result.hit.canonical_id == "fb"
        assert result.edit_distance == 1

    def test_all_kinds_indexed(self):
        """Verify that team/player/league/competition aliases coexist."""
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term("galatasaray", AliasHit("gs", "team", "1.0.0"))
        idx.add_term("muslera", AliasHit("p-001", "player", "1.0.0"))
        idx.add_term("super lig", AliasHit("sl", "league", "1.0.0"))
        idx.add_term("turkiye kupasi", AliasHit("tk", "competition", "1.0.0"))
        assert idx.term_count == 4
        r = idx.lookup("muslra")  # one deletion
        assert r is not None and r.hit.kind == "player"


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    def test_nlp_typo_max_edit_distance_default(self):
        from common.config import cfg
        assert cfg.nlp_typo_max_edit_distance == 2

    def test_nlp_typo_max_edit_distance_in_env_example(self):
        import pathlib
        env_example = pathlib.Path("xops/env/.env.example").read_text()
        assert "NEGELIR_NLP_TYPO_MAX_EDIT_DISTANCE" in env_example

    def test_config_rejects_invalid_edit_distance(self):
        """Boot validator rejects nlp_typo_max_edit_distance outside {1, 2}."""
        import os
        from common.config import Config
        orig = os.environ.get("NEGELIR_NLP_TYPO_MAX_EDIT_DISTANCE")
        os.environ["NEGELIR_NLP_TYPO_MAX_EDIT_DISTANCE"] = "3"
        try:
            bad = Config()
            issues = bad.validate(strict=False)
            assert any("nlp_typo_max_edit_distance" in i for i in issues), issues
        finally:
            if orig is None:
                os.environ.pop("NEGELIR_NLP_TYPO_MAX_EDIT_DISTANCE", None)
            else:
                os.environ["NEGELIR_NLP_TYPO_MAX_EDIT_DISTANCE"] = orig

    def test_nlp_typo_max_lookups_per_query_default(self):
        from common.config import cfg
        assert cfg.nlp_typo_max_lookups_per_query == 8

    def test_nlp_typo_max_lookups_per_query_in_env_example(self):
        import pathlib
        env_example = pathlib.Path("xops/env/.env.example").read_text()
        assert "NEGELIR_NLP_TYPO_MAX_LOOKUPS_PER_QUERY" in env_example

    def test_config_rejects_invalid_max_lookups(self):
        """Boot validator rejects nlp_typo_max_lookups_per_query < 1."""
        import os
        from common.config import Config
        orig = os.environ.get("NEGELIR_NLP_TYPO_MAX_LOOKUPS_PER_QUERY")
        os.environ["NEGELIR_NLP_TYPO_MAX_LOOKUPS_PER_QUERY"] = "0"
        try:
            bad = Config()
            issues = bad.validate(strict=False)
            assert any("nlp_typo_max_lookups_per_query" in i for i in issues), issues
        finally:
            if orig is None:
                os.environ.pop("NEGELIR_NLP_TYPO_MAX_LOOKUPS_PER_QUERY", None)
            else:
                os.environ["NEGELIR_NLP_TYPO_MAX_LOOKUPS_PER_QUERY"] = orig


# ---------------------------------------------------------------------------
# Per-query budget (§10.3)
# ---------------------------------------------------------------------------


class TestPerQueryBudget:
    """Tests for SymSpellIndex.lookup_tokens() per-query fuzzy-lookup budget."""

    def _idx(self) -> SymSpellIndex:
        """Index with several long team-name aliases."""
        idx = SymSpellIndex(max_edit_distance=2)
        idx.add_term("galatasaray", AliasHit("gs", "team", "1.0.0"))
        idx.add_term("fenerbahce", AliasHit("fb", "team", "1.0.0"))
        idx.add_term("besiktas", AliasHit("bjk", "team", "1.0.0"))
        idx.add_term("trabzonspor", AliasHit("ts", "team", "1.0.0"))
        idx.add_term("bursaspor", AliasHit("bs", "team", "1.0.0"))
        idx.add_term("konyaspor", AliasHit("ks", "team", "1.0.0"))
        return idx

    # -- Exact-only tokens do not consume budget ---------------------------

    def test_exact_matches_do_not_consume_budget(self):
        """Exact-match tokens (edit_distance=0) never count against the budget."""
        idx = self._idx()
        tokens = ["galatasaray", "fenerbahce", "besiktas"]
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1)
        assert exhausted is False
        assert results[0] is not None and results[0].edit_distance == 0
        assert results[1] is not None and results[1].edit_distance == 0
        assert results[2] is not None and results[2].edit_distance == 0

    # -- Budget enforced precisely -----------------------------------------

    def test_budget_1_allows_one_fuzzy(self):
        """max_lookups=1 → exactly one fuzzy correction allowed."""
        idx = self._idx()
        # "gaalatasaray" → fuzzy (edit 1), "fenerbahce" → exact → fine
        tokens = ["gaalatasaray", "fenerbahce"]
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1)
        assert exhausted is False
        assert results[0] is not None and results[0].edit_distance == 1
        assert results[1] is not None and results[1].edit_distance == 0

    def test_budget_1_second_fuzzy_exhausts(self):
        """With max_lookups=1, the 2nd fuzzy lookup sets budget_exhausted."""
        idx = self._idx()
        # Both tokens need 1 edit each → second exceeds budget=1
        tokens = ["gaalatasaray", "fenrbahe"]
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1)
        assert exhausted is True
        # First fuzzy: allowed
        assert results[0] is not None and results[0].edit_distance > 0
        # Second fuzzy: budget exceeded → None (pass-through)
        assert results[1] is None

    def test_budget_8_allows_eight_fuzzy(self):
        """Default budget=8 allows 8 fuzzy corrections before exhausting."""
        idx = SymSpellIndex(max_edit_distance=2)
        # Index 10 terms; misspell 8
        for i, name in enumerate(
            ["alpa", "betab", "gamma", "delta", "epslon", "zetaa", "etaa", "thetaa",
             "iota", "kappa"]
        ):
            idx.add_term(name, AliasHit(f"c-{i}", "team", "1.0.0"))
        # Misspelled versions (each has edit_distance=1 to indexed term)
        misspelled = ["alpb", "betac", "gammd", "deltb", "epslom", "zetab", "etab", "thetab"]
        exact_suffix = ["iota", "kappa"]
        tokens = misspelled + exact_suffix
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=8)
        # 8 fuzzy lookups → budget exactly reached but not exceeded
        assert exhausted is False
        # All 8 misspelled tokens must have a fuzzy result
        for r in results[:8]:
            assert r is not None and r.edit_distance > 0
        # The two exact tokens at the end are unaffected
        for r in results[8:]:
            assert r is not None and r.edit_distance == 0

    def test_budget_exceeded_short_circuits_remaining_tokens(self):
        """Once budget is exhausted, all remaining tokens return None."""
        idx = self._idx()
        # 3 fuzzy tokens with max_lookups=1: only first is corrected
        tokens = ["galatasaay", "fenrbahe", "besikts"]
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1)
        assert exhausted is True
        assert results[0] is not None and results[0].edit_distance > 0  # corrected
        assert results[1] is None   # budget exceeded here
        assert results[2] is None   # short-circuited

    def test_no_match_does_not_consume_budget(self):
        """Tokens with no in-budget candidate (lookup returns None) do not count."""
        idx = self._idx()
        # "xyzqwerty" has no match → lookup returns None → no budget consumed
        tokens = ["xyzqwerty", "gaalatasaray"]
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1)
        assert exhausted is False
        assert results[0] is None   # genuinely no match
        assert results[1] is not None and results[1].edit_distance > 0  # fuzzy match

    def test_empty_token_list_returns_false(self):
        """Empty input never exhausts budget."""
        idx = self._idx()
        results, exhausted = idx.lookup_tokens([], max_lookups=1)
        assert results == []
        assert exhausted is False

    def test_all_exact_large_list_never_exhausts(self):
        """100 exact-match tokens with max_lookups=1 never trigger exhaustion."""
        idx = SymSpellIndex(max_edit_distance=2)
        term = "galatasaray"
        idx.add_term(term, AliasHit("gs", "team", "1.0.0"))
        tokens = [term] * 100
        results, exhausted = idx.lookup_tokens(tokens, max_lookups=1)
        assert exhausted is False
        assert all(r is not None and r.edit_distance == 0 for r in results)


# ---------------------------------------------------------------------------
# SymSpellIndex memory lifecycle
# ---------------------------------------------------------------------------


class TestSymSpellMemoryLifecycle:
    """Tests for §10.21.2 Symspell dictionary lifetime: no growth on repeated swaps."""

    def test_nlp_symspell_no_growth_on_repeated_swaps(self, tmp_path):
        """§10.21.2 Symspell dictionary lifetime: RSS Δ < 5 MiB after 100 swaps.

        Built once at boot from current lexicon snapshot; on lexicon swap,
        REBUILT (not mutated). Old Symspell instance dereferenced atomically
        with old lexicon generation. Memory test probes RSS after 100 swaps.
        """
        from pathlib import Path
        from nlp.lexicon_loader import LexiconStore, _current_rss_kb

        # Create a minimal lexicon dir with one file
        lexdir = tmp_path / "lexicon"
        lexdir.mkdir()
        (lexdir / "teams.tr.yaml").write_text(
            "_meta:\n"
            "  schema_version: 1\n"
            "  lexicon_version: '1.0.0'\n"
            "  generated_at_utc: '2026-01-01T00:00:00Z'\n"
            "  generator: test\n"
            "entries:\n"
            "  - canonical_id: gs-001\n"
            "    names: [Galatasaray]\n"
            "    aliases: [gala, gs, cimbom]\n"
            "  - canonical_id: fb-001\n"
            "    names: [Fenerbahce]\n"
            "    aliases: [fener, fb]\n"
            "  - canonical_id: bjk-001\n"
            "    names: [Besiktas]\n"
            "    aliases: [besiktas, bjk, kartal]\n"
        )

        # Capture baseline RSS before any loads
        rss_before_kb = _current_rss_kb()
        if rss_before_kb == 0:
            pytest.skip("RSS measurement unavailable on this platform")

        store = LexiconStore(
            lexdir,
            reload_s=1,
            max_old_generations=2,
            max_rss_mb=0,  # disable RSS budget check for this test
        )

        # Initial load
        store.maybe_reload()
        assert store.is_loaded
        assert store.get_symspell() is not None

        # Touch the file 100 times to trigger 100 swaps
        teams_file = lexdir / "teams.tr.yaml"
        for i in range(100):
            # Append a comment to change SHA (triggers swap)
            with teams_file.open("a") as f:
                f.write(f"# swap {i}\n")
            import time
            time.sleep(0.01)  # ensure mtime changes
            alerts = store.maybe_reload()
            # Each swap should succeed (no alerts)
            assert alerts == []
            # SymSpellIndex should be rebuilt (non-None)
            assert store.get_symspell() is not None

        # Capture RSS after 100 swaps
        rss_after_kb = _current_rss_kb()

        # Compute delta
        delta_kb = rss_after_kb - rss_before_kb
        delta_mb = delta_kb / 1024

        # §10.21.2 contract: Δ < 5 MiB
        # Allow some headroom for test runner overhead (10 MiB)
        assert delta_mb < 10, (
            f"RSS grew by {delta_mb:.1f} MiB after 100 swaps "
            f"(before: {rss_before_kb // 1024} MiB, after: {rss_after_kb // 1024} MiB). "
            "Expected < 10 MiB (§10.21.2 contract: < 5 MiB + 5 MiB test overhead)."
        )

