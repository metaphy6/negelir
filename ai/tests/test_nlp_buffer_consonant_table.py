"""§10.22.3 buffer-consonant renderer — unit tests.

Covers:
  1. AST guard: buffer_consonant() in turkish.py must NOT contain hardcoded
     if-elif chains on suffix_class strings.  Only table.get() is allowed.
  2. Lyon foreign-override: pronunciation_class=consonant_final suppresses buffer.
  3. AST guard: jinja_filters_tr.py must NOT contain multi-char all-vowel
     string literals (no inline frozenset("eiöü") style code).
  4. Hypothesis property test: buffer_consonant never raises on any input.
  5. Composition test: §10.22.3 buffer_consonant composes correctly with
     §10.22.2 strip_proper_noun_suffix and §10.7 dative/genitive filters.
"""
from __future__ import annotations

import ast
import pathlib
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
_TURKISH_PY = _REPO_ROOT / "ai" / "common" / "text" / "turkish.py"
_FILTERS_PY = _REPO_ROOT / "ai" / "nlp" / "jinja_filters_tr.py"

ALL_TR_VOWELS = set("aeıioöuü")


def _ast_source(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# ---------------------------------------------------------------------------
# 1. AST guard: buffer_consonant uses table.get(), not if-elif on suffix_class
# ---------------------------------------------------------------------------
class TestBufferConsonantTableDrivesDecision:
    """The buffer_consonant() function must delegate to the YAML table via
    dict.get(), not branch on suffix_class with if/elif literals."""

    def test_no_suffix_class_if_elif_in_buffer_consonant(self):
        """buffer_consonant() must not contain hardcoded if/elif on suffix_class."""
        tree = _ast_source(_TURKISH_PY)
        func_body: list[ast.stmt] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "buffer_consonant":
                func_body = node.body
                break
        assert func_body, "buffer_consonant() not found in turkish.py"

        # Walk the function body for If nodes that compare to suffix_class literals
        suffix_class_comparisons = 0
        for node in ast.walk(ast.Module(body=func_body, type_ignores=[])):
            if isinstance(node, ast.If):
                for child in ast.walk(node.test):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        # Flag if the literal looks like a known suffix class
                        if child.value in {
                            "dative", "accusative", "possessive_3sg",
                            "compound_marker", "verb_passive_3sg",
                            "locative", "ablative", "genitive", "plural",
                        }:
                            suffix_class_comparisons += 1

        assert suffix_class_comparisons == 0, (
            f"buffer_consonant() contains {suffix_class_comparisons} if/elif "
            "branch(es) on suffix_class literals. Use table.get() instead."
        )

    def test_buffer_consonant_uses_table_get(self):
        """buffer_consonant() must contain at least one .get(suffix_class, ...) call."""
        tree = _ast_source(_TURKISH_PY)
        get_calls = 0
        for node in ast.walk(tree):
            # Look for `something.get(suffix_class ...)` in buffer_consonant body
            if isinstance(node, ast.FunctionDef) and node.name == "buffer_consonant":
                for child in ast.walk(node):
                    if (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "get"
                    ):
                        # Check the first arg is the name suffix_class
                        if (
                            child.args
                            and isinstance(child.args[0], ast.Name)
                            and child.args[0].id == "suffix_class"
                        ):
                            get_calls += 1
        assert get_calls >= 1, (
            "buffer_consonant() must call table.get(suffix_class, ...) "
            "but no such call was found."
        )


# ---------------------------------------------------------------------------
# 2. Lyon foreign-override: consonant_final → no buffer
# ---------------------------------------------------------------------------
class TestLyonForeignPronunciationOverride:
    """Lyon has pronunciation_class=consonant_final in the YAML overrides.
    buffer_consonant("Lyon", "dative") must return "" regardless of the
    written last character."""

    def test_lyon_dative_buffer_is_empty(self):
        from common.text.turkish import buffer_consonant
        assert buffer_consonant("Lyon", "dative") == "", (
            "Lyon is consonant_final by override; buffer should be ''"
        )

    def test_lyon_accusative_buffer_is_empty(self):
        from common.text.turkish import buffer_consonant
        assert buffer_consonant("Lyon", "accusative") == ""

    def test_lyon_possessive_buffer_is_empty(self):
        from common.text.turkish import buffer_consonant
        assert buffer_consonant("Lyon", "possessive_3sg") == ""

    def test_psg_dative_buffer_is_y(self):
        """PSG has pronunciation_class=vowel_final; buffer for dative is 'y'."""
        from common.text.turkish import buffer_consonant
        assert buffer_consonant("PSG", "dative") == "y"

    def test_psg_possessive_buffer_is_s(self):
        from common.text.turkish import buffer_consonant
        assert buffer_consonant("PSG", "possessive_3sg") == "s"


# ---------------------------------------------------------------------------
# 3. AST guard: no inline multi-char all-vowel string literals in jinja_filters
# ---------------------------------------------------------------------------
class TestNoInlineVowelLiteralsInMorphFilters:
    """jinja_filters_tr.py must not contain string literals of length >= 2
    where every character is a Turkish vowel (e.g. frozenset("eiöü")).
    Single-char vowel strings ("e", "a") used in return expressions are OK."""

    def test_no_multichar_all_vowel_string_literals(self):
        tree = _ast_source(_FILTERS_PY)
        violations: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if len(val) >= 2 and all(c in ALL_TR_VOWELS for c in val):
                    violations.append((node.lineno, val))

        assert not violations, (
            "jinja_filters_tr.py contains multi-char all-vowel string "
            f"literals (must load from vowel_harmony_4way.tr.yaml):\n"
            + "\n".join(f"  line {ln}: {v!r}" for ln, v in violations)
        )


# ---------------------------------------------------------------------------
# 4. Hypothesis property test: buffer_consonant never raises
# ---------------------------------------------------------------------------
try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    _HAS_HYPOTHESIS = True
except ImportError:
    given = None  # type: ignore[assignment]
    settings = None  # type: ignore[assignment]
    st = None  # type: ignore[assignment]
    _HAS_HYPOTHESIS = False

_SUFFIX_CLASSES = [
    "dative", "accusative", "possessive_3sg",
    "compound_marker", "verb_passive_3sg",
    "locative", "ablative", "genitive", "plural", "",
    "unknown_future_class",
]


def _hypothesis_available() -> bool:
    return _HAS_HYPOTHESIS


if _HAS_HYPOTHESIS:
    @given(
        stem=st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll"),
                whitelist_characters="abcçdefgğhıijklmnoöprsştuüvyz''",
            ),
            min_size=1,
            max_size=40,
        ),
        suffix_class=st.sampled_from(_SUFFIX_CLASSES),
    )
    @settings(max_examples=400)
    def _prop_buffer_never_raises(stem: str, suffix_class: str) -> None:
        from common.text.turkish import buffer_consonant
        result = buffer_consonant(stem, suffix_class)
        assert isinstance(result, str)
        assert len(result) <= 1, f"buffer must be 0 or 1 chars, got {result!r}"

    @given(suffix_class=st.sampled_from(_SUFFIX_CLASSES))
    def _prop_empty_stem_returns_empty(suffix_class: str) -> None:
        from common.text.turkish import buffer_consonant
        assert buffer_consonant("", suffix_class) == ""
else:
    def _prop_buffer_never_raises(*a, **kw) -> None:  # type: ignore[misc]
        pass

    def _prop_empty_stem_returns_empty(*a, **kw) -> None:  # type: ignore[misc]
        pass


@pytest.mark.skipif(not _HAS_HYPOTHESIS, reason="hypothesis not installed")
class TestBufferConsonantPropertyBased:
    def test_buffer_consonant_never_raises(self):
        _prop_buffer_never_raises()

    def test_buffer_consonant_empty_stem_returns_empty(self):
        _prop_empty_stem_returns_empty()


# ---------------------------------------------------------------------------
# 5. Composition: buffer_consonant composes with §10.22.2 and §10.7 filters
# ---------------------------------------------------------------------------
class TestBufferConsonantComposesWithFilters:
    """§10.22.3 buffer_consonant is used inside dative() and accusative() in
    jinja_filters_tr.py.  These integration tests verify the composed output."""

    def test_dative_vowel_final_uses_y_buffer(self):
        from nlp.jinja_filters_tr import dative
        # strip_proper_noun_suffix is §10.22.2; here we test composition
        # at the filter boundary.
        assert dative("Ankara", proper=True) == "Ankara\'ya"

    def test_dative_consonant_final_no_buffer(self):
        from nlp.jinja_filters_tr import dative
        assert dative("Trabzonspor", proper=True) == "Trabzonspor\'a"

    def test_genitive_vowel_final_n_prefix(self):
        from nlp.jinja_filters_tr import genitive
        # genitive vowel-final uses n-prefix, not buffer_consonant; compound_marker uses n.
        assert genitive("Bursa", proper=True) == "Bursa\'n\u0131n"

    def test_genitive_consonant_final_no_n_prefix(self):
        from nlp.jinja_filters_tr import genitive
        assert genitive("Galatasaray", proper=True) == "Galatasaray\'\u0131n"

    def test_possessive_vowel_final_s_buffer(self):
        from nlp.jinja_filters_tr import possessive_3sg
        assert possessive_3sg("Fenerbah\u00e7e", proper=True) == "Fenerbah\u00e7e\'si"

    def test_possessive_consonant_final_no_buffer(self):
        from nlp.jinja_filters_tr import possessive_3sg
        assert possessive_3sg("Trabzonspor", proper=True) == "Trabzonspor\'u"

    def test_strip_then_dative_composes(self):
        """strip_proper_noun_suffix (§10.22.2) + dative (§10.7 + §10.22.3)."""
        from common.text.turkish import strip_proper_noun_suffix
        from nlp.jinja_filters_tr import dative
        stem, _ = strip_proper_noun_suffix("Bursa\'ya")
        # The stem stripped from "Bursa\'ya" should be "Bursa"; re-applying
        # dative must recover the original form.
        assert dative(stem, proper=True) == "Bursa\'ya"
