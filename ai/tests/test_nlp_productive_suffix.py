"""Tests for Phase 10 §10.32.8 productive suffix peeling."""
from __future__ import annotations

from common.text.turkish import lowercase_tr
from nlp.apostrophe_proper_noun import repair_apostrophe_proper_noun
from nlp.morph.productive_suffixes import (
    load_productive_peel_no_fire_allowlist,
    load_productive_suffix_families,
    peel_productive_suffixes,
)


def _resolver_for_cs(residue: str) -> bool:
    return lowercase_tr(residue) == "gs"


def _resolver_for_fenerbahce(residue: str) -> bool:
    return lowercase_tr(residue) == "fenerbahçe"


class TestProductiveSuffixPeeler:
    def test_loads_eight_productive_suffix_families(self) -> None:
        families = load_productive_suffix_families()
        assert len(families) == 8
        assert {family["id"] for family in families} == {
            "lI",
            "lIk",
            "cI",
            "CIk",
            "mIş",
            "yorlu",
            "lIlIk",
            "lIlAr",
        }

    def test_peels_gslilik_to_gs(self) -> None:
        result = peel_productive_suffixes(
            "GSlilik",
            can_resolve=_resolver_for_cs,
            max_depth=3,
        )

        assert result.success is True
        assert result.stripped_token == "gs"
        assert result.peeled_suffixes == ("lilik",)

    def test_does_not_peel_no_fire_negative_corpus_token(self) -> None:
        allowlist = load_productive_peel_no_fire_allowlist()
        assert "birlik" in allowlist

        result = peel_productive_suffixes(
            "birlik",
            can_resolve=lambda residue: True,
            _no_fire_allowlist=allowlist,
        )

        assert result.success is False
        assert result.stripped_token == "birlik"
        assert result.peeled_suffixes == ()

    def test_missing_apostrophe_repair_precedes_productive_peel(self) -> None:
        repaired, repairs = repair_apostrophe_proper_noun("Fenerbahçeli", original_text="Fenerbahçeli")
        assert "'" in repaired
        assert repairs

        repaired_peel = peel_productive_suffixes(
            repaired,
            can_resolve=_resolver_for_fenerbahce,
            max_depth=3,
        )
        plain_peel = peel_productive_suffixes(
            "Fenerbahçeli",
            can_resolve=_resolver_for_fenerbahce,
            max_depth=3,
        )

        assert repaired_peel.success is True
        assert plain_peel.success is True
        assert repaired_peel.stripped_token == plain_peel.stripped_token == "fenerbahçe"
