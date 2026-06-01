"""§10.22.3 buffer-consonant golden table test.

Loads ai/nlp/lang_tr/golden/buffer_golden.yaml (300 rows).
Each row: {stem, suffix_class, expected_output}.
Calls the corresponding jinja filter with proper=True.
100% pass is required by §10.20 / §10.22 DoD.
"""
from __future__ import annotations

import pathlib
import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_GOLDEN = _REPO_ROOT / "ai" / "nlp" / "lang_tr" / "golden" / "buffer_golden.yaml"


def _load_golden():
    with open(_GOLDEN, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["rows"]


def _build_filter_map():
    from nlp.jinja_filters_tr import (
        dative, accusative, locative, ablative, genitive, plural, possessive_3sg,
    )
    return {
        "dative":         lambda s: dative(s, proper=True),
        "accusative":     lambda s: accusative(s, proper=True),
        "locative":       lambda s: locative(s, proper=True),
        "ablative":       lambda s: ablative(s, proper=True),
        "genitive":       lambda s: genitive(s, proper=True),
        "plural":         lambda s: plural(s, proper=True),
        "possessive_3sg": lambda s: possessive_3sg(s, proper=True),
    }


class TestBufferGoldenTable100Percent:
    """All 300 rows in buffer_golden.yaml must pass."""

    @pytest.mark.parametrize(
        "stem,suffix_class,expected_output",
        [
            (r["stem"], r["suffix_class"], r["expected_output"])
            for r in _load_golden()
        ],
        ids=[
            f'{r["stem"]}+{r["suffix_class"]}'
            for r in _load_golden()
        ],
    )
    def test_row(self, stem: str, suffix_class: str, expected_output: str):
        filters = _build_filter_map()
        assert suffix_class in filters, (
            f"No filter registered for suffix_class={suffix_class!r}. "
            "Add it to _build_filter_map() when the filter is implemented."
        )
        got = filters[suffix_class](stem)
        assert got == expected_output, (
            f"Golden row failed: {stem!r} + {suffix_class!r}\n"
            f"  expected: {expected_output!r}\n"
            f"  got:      {got!r}"
        )


class TestGoldenTableCoverage:
    """Structural sanity on the golden table itself."""

    def test_row_count_at_least_300(self):
        rows = _load_golden()
        assert len(rows) >= 300, f"Expected >=300 rows, got {len(rows)}"

    def test_all_suffix_classes_covered(self):
        rows = _load_golden()
        covered = {r["suffix_class"] for r in rows}
        required = {
            "dative", "accusative", "locative", "ablative",
            "genitive", "plural", "possessive_3sg",
        }
        missing = required - covered
        assert not missing, f"suffix_classes not covered: {missing}"

    def test_both_vowel_and_consonant_final_stems_present(self):
        from common.text.turkish import buffer_consonant
        rows = _load_golden()
        stems_with_y_buffer = {
            r["stem"] for r in rows
            if buffer_consonant(r["stem"], "dative") == "y"
        }
        stems_no_buffer = {
            r["stem"] for r in rows
            if buffer_consonant(r["stem"], "dative") == ""
        }
        assert stems_with_y_buffer, "No vowel-final stems found in golden table"
        assert stems_no_buffer, "No consonant-final stems found in golden table"
