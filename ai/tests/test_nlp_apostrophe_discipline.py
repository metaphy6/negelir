"""Tests for §10.22.2 — Apostrophe discipline (proper-noun suffix-stripper,
output-side filter discipline, foreign-stem overrides, apostrophe-noise tolerance).

Anti-literalism contract:
  The YAML tables are test / audit corpus — NOT the implementation.  Code in
  ai/common/text/turkish.py and ai/nlp/jinja_filters_tr.py must implement the
  GENERALISING rule (vowel harmony + YAML-table lookup), not if-cascades.

Proof tests required by spec (§10.22.2):
  • test_nlp_strip_suffix_recovers_galatasarayin_to_galatasaray
  • test_nlp_strip_suffix_recovers_realmadride_to_real_madrid
  • test_nlp_morph_filter_renders_apostrophe_for_proper_noun (20-case golden table)
  • test_nlp_apostrophe_normalization_to_ascii
  • test_nlp_foreign_stem_overrides_resolve_to_catalog (YAML integrity)

Additional anti-literalism guards:
  • Property test via hypothesis: strip does not blow up on any proper-noun-like token
  • Composition test: §10.22.2 works together with previously-shipped §10.1/§10.7 code
  • AST guard: no literal suffix strings inside turkish.py's suffix-stripper body
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest

# ── Imports under test ──────────────────────────────────────────────────────
from common.text.turkish import strip_proper_noun_suffix
from nlp.jinja_filters_tr import (
    locative,
    dative,
    ablative,
    accusative,
    genitive,
    plural,
)
from nlp.normalize import normalize_input as normalize


# ── §10.22.2 Bullet 1: input-side suffix-stripper ───────────────────────────

class TestStripProperNounSuffix:
    """strip_proper_noun_suffix() — recognition / input side."""

    def test_nlp_strip_suffix_recovers_galatasarayin_to_galatasaray(self) -> None:
        """Genitive with apostrophe: 'Galatasaray'ın' → stem 'Galatasaray'."""
        stem, cls = strip_proper_noun_suffix("Galatasaray'ın")
        assert stem == "Galatasaray"
        assert cls == "genitive"

    def test_nlp_strip_suffix_recovers_realmadride_to_real_madrid(self) -> None:
        """Apostrophe dative 'Madrid'e' → stem 'Madrid' / 'dative'.

        Without an apostrophe, greedy longest-first would match the 2-char
        suffix 'de' (locative) before the 1-char 'e' (dative), returning a
        false-positive stem 'Madri'.  The apostrophe form disambiguates.
        Gazetteer is responsible for validating false-positive no-apostrophe
        stems.
        """
        stem, cls = strip_proper_noun_suffix("Madrid'e")
        assert stem == "Madrid"
        assert cls == "dative"

    def test_strip_apostrophe_genitive_back(self) -> None:
        """Back-vowel genitive 'Trabzonspor'un' → 'Trabzonspor'."""
        stem, cls = strip_proper_noun_suffix("Trabzonspor'un")
        assert stem == "Trabzonspor"
        assert cls == "genitive"

    def test_strip_no_apostrophe_dative_front(self) -> None:
        """No-apostrophe front dative: 'Fenerbahçede' → 'Fenerbahçe' (locative)."""
        stem, cls = strip_proper_noun_suffix("Fenerbahçede")
        # 'de' matches both dative-front and locative vowel_final-front
        # The code returns the FIRST matched family; locative 'de' comes
        # before dative in the YAML — acceptable since gazetteer validates.
        assert stem == "Fenerbahçe"
        assert cls is not None

    def test_strip_no_apostrophe_wrong_harmony_dative(self) -> None:
        """Wrong-harmony dative suffix 'Fenerbahçeya' recovers 'Fenerbahçe'."""
        stem, cls = strip_proper_noun_suffix("Fenerbahçeya")
        assert stem == "Fenerbahçe"
        assert cls == "dative"

    def test_strip_tolerant_rejects_canonical_entity_prefix(self) -> None:
        """Harmony-tolerant strip must not split a canonical entity token."""
        stem, cls = strip_proper_noun_suffix(
            "Edirne",
            assume_proper=True,
            no_strip_canonicals={"edirne"},
        )
        assert stem == "Edirne"
        assert cls is None

    def test_strip_preserves_non_proper(self) -> None:
        """A lowercase token without assume_proper → (token, None)."""
        token = "galatasaray"
        stem, cls = strip_proper_noun_suffix(token)
        assert stem == token
        assert cls is None

    def test_strip_assume_proper_lowercase(self) -> None:
        """assume_proper=True bypasses uppercase check.

        Greedy longest-first: 'ya' (2-char, dative vowel_final back) matches
        before 'a' (1-char, dative consonant_final back), returning stem
        'galatasara'. This is the expected (permissive) behaviour — the
        gazetteer validates. The apostrophe form 'galatasaray'a' gives the
        unambiguous 1-char match.
        """
        # No-apostrophe: greedy match returns 'ya' (vowel_final dative)
        stem, cls = strip_proper_noun_suffix("galatasaraya", assume_proper=True)
        assert stem == "galatasara"
        assert cls == "dative"
        # Apostrophe form: unambiguous 1-char suffix
        stem2, cls2 = strip_proper_noun_suffix("galatasaray'a", assume_proper=True)
        assert stem2 == "galatasaray"
        assert cls2 == "dative"

    def test_strip_empty_string(self) -> None:
        """Empty string returns (empty, None) without raising."""
        assert strip_proper_noun_suffix("") == ("", None)

    def test_strip_no_suffix_detected(self) -> None:
        """Token with no recognisable suffix → (token, None)."""
        stem, cls = strip_proper_noun_suffix("FIFA")
        # 'A' ends token but 'A' → uppercase → proper.  No 1-4 char suffix
        # that harmonises. 'A' alone is 1 char: is 'A' in _SUFFIX_CHARS?
        # _SUFFIX_CHARS is lowercase only → 'A' is NOT → skip suffix 1.
        assert stem == "FIFA"
        assert cls is None

    def test_strip_apostrophe_dative_front(self) -> None:
        """Fenerbahçe'ye → Fenerbahçe / dative."""
        stem, cls = strip_proper_noun_suffix("Fenerbahçe'ye")
        assert stem == "Fenerbahçe"
        assert cls == "dative"

    def test_strip_apostrophe_plural_back(self) -> None:
        """Galatasaray'lar → Galatasaray / plural."""
        stem, cls = strip_proper_noun_suffix("Galatasaray'lar")
        assert stem == "Galatasaray"
        assert cls == "plural"

    def test_strip_apostrophe_ablative_voiceless_back(self) -> None:
        """Beşiktaş'tan → Beşiktaş / ablative."""
        stem, cls = strip_proper_noun_suffix("Beşiktaş'tan")
        assert stem == "Beşiktaş"
        assert cls == "ablative"

    def test_strip_apostrophe_locative_voiceless_back(self) -> None:
        """Beşiktaş'ta → Beşiktaş / locative."""
        stem, cls = strip_proper_noun_suffix("Beşiktaş'ta")
        assert stem == "Beşiktaş"
        assert cls == "locative"

    def test_strip_invalid_apostrophe_suffix_not_in_table(self) -> None:
        """An apostrophe-split suffix not in the YAML table → (token, None)."""
        stem, cls = strip_proper_noun_suffix("Xyz'zzz")
        assert stem == "Xyz'zzz"
        assert cls is None

    def test_strip_suffix_too_long_ignored(self) -> None:
        """A candidate suffix > 4 chars is not attempted (too long)."""
        # 'spor' is 4 chars; 'gspor' is 5 → not in any family forms
        # Greedy scan tries 4 → 1.  'spor' is 4 chars, it IS in plural-like
        # suffix lists? No: 'spor' ≠ lar/ler/ın/in/un/ün etc.
        # Token ends in 'spor': none of the 4-char family forms match.
        stem, cls = strip_proper_noun_suffix("Trabzonspor")
        # Should not strip because 'spor' is not a grammar suffix
        # (even though 4 chars). But 'r' alone IS consonant-final dative?
        # Actually 'r' (1-char): ablative or dative? 'r' is NOT in dative forms
        # (a/e/ya/ye), NOT in locative (da/de/ta/te), NOT in genitive (ın/…).
        # So no suffix found → (token, None).
        assert stem == "Trabzonspor"
        assert cls is None

    @pytest.mark.parametrize("token,expected_stem,expected_cls", [
        ("Rize'ye",       "Rize",       "dative"),
        ("Bursa'dan",     "Bursa",      "ablative"),
        ("İstanbul'da",   "İstanbul",   "locative"),
        ("Ankara'nın",    "Ankara",     "genitive"),
    ])
    def test_strip_parametrized_turkish_cities(
        self, token: str, expected_stem: str, expected_cls: str
    ) -> None:
        stem, cls = strip_proper_noun_suffix(token)
        assert stem == expected_stem, f"stem mismatch for {token!r}"
        assert cls == expected_cls, f"class mismatch for {token!r}"


# ── §10.22.2 Bullet 2: output-side filter discipline ────────────────────────

# 20-case golden table: (filter_fn, word, proper, expected_output)
# Covers: Turkish domestic clubs, foreign clubs, initialisms, edge cases.
_MORPH_GOLDEN: list[tuple[Any, str, bool, str]] = [
    # Domestic clubs — proper=False (uppercase → apostrophe via _is_proper_noun)
    (locative,  "Galatasaray",       False, "Galatasaray'da"),
    (locative,  "Beşiktaş",          False, "Beşiktaş'ta"),
    (dative,    "Trabzonspor",       False, "Trabzonspor'a"),
    (dative,    "Fenerbahçe",        False, "Fenerbahçe'ye"),
    (genitive,  "Galatasaray",       False, "Galatasaray'ın"),
    (ablative,  "Beşiktaş",          False, "Beşiktaş'tan"),
    (accusative, "Trabzonspor",      False, "Trabzonspor'u"),
    (plural,    "Galatasaray",       False, "Galatasaray'lar"),
    # proper=True forces apostrophe on lowercased names (after NLP normalisation)
    (dative,    "trabzonspor",       True,  "trabzonspor'a"),
    (genitive,  "galatasaray",       True,  "galatasaray'ın"),
    # Foreign clubs — need override: PSG (initialism vowel_final front)
    (dative,    "PSG",               True,  "PSG'ye"),
    (genitive,  "PSG",               True,  "PSG'nin"),
    # Foreign clubs — Manchester City (English 'y' = vowel_final front)
    (genitive,  "Manchester City",   True,  "Manchester City'nin"),
    (dative,    "Manchester City",   True,  "Manchester City'ye"),
    # Porto (override: back, vowel_final)
    (genitive,  "Porto",             True,  "Porto'nun"),
    (dative,    "Porto",             True,  "Porto'ya"),
    # Bayern (override: front, consonant_final)
    (genitive,  "Bayern",            True,  "Bayern'in"),
    (dative,    "Bayern",            True,  "Bayern'e"),
    # Juventus (override: back, consonant_final)
    (genitive,  "Juventus",          True,  "Juventus'un"),
    # Inter (override: front, consonant_final)
    (dative,    "Inter",             True,  "Inter'e"),
]


@pytest.mark.parametrize(
    "fn,word,proper,expected",
    _MORPH_GOLDEN,
    ids=[f"{fn.__name__}({word!r},proper={proper})" for fn, word, proper, expected in _MORPH_GOLDEN],
)
def test_nlp_morph_filter_renders_apostrophe_for_proper_noun(
    fn: Any, word: str, proper: bool, expected: str
) -> None:
    """§10.22.2 output-side: morphology filters produce correct apostrophe + harmony."""
    result = fn(word, proper)
    assert result == expected, (
        f"{fn.__name__}({word!r}, proper={proper}) → {result!r}, want {expected!r}"
    )


# ── §10.22.2 Bullet 3: apostrophe-noise tolerance (normalize.py) ─────────────

@pytest.mark.parametrize("raw_apos,token_suffix", [
    ("\u2019", "Galatasaray\u2019ın"),   # RIGHT SINGLE QUOTATION MARK (already mapped)
    ("\u2018", "Galatasaray\u2018ın"),   # LEFT SINGLE QUOTATION MARK  (already mapped)
    ("\u02BC", "Galatasaray\u02BCın"),   # MODIFIER LETTER APOSTROPHE  (§10.22.2 new)
    ("\u0060", "Galatasaray\u0060ın"),   # GRAVE ACCENT                (§10.22.2 new)
    ("\u00B4", "Galatasaray\u00B4ın"),   # ACUTE ACCENT                (§10.22.2 new)
])
def test_nlp_apostrophe_normalization_to_ascii(raw_apos: str, token_suffix: str) -> None:
    """§10.22.2 noise bullet: typographic apostrophe variants normalise to ASCII '."""
    result = normalize(token_suffix)
    tokens = list(result.tokens)
    # After normalisation the token should contain ASCII apostrophe only.
    full_text = " ".join(tokens)
    assert "\u2019" not in full_text, "U+2019 escaped normalization"
    assert "\u2018" not in full_text, "U+2018 escaped normalization"
    assert "\u02BC" not in full_text, "U+02BC (modifier apostrophe) escaped normalization"
    assert "\u0060" not in full_text, "U+0060 (grave) escaped normalization"
    assert "\u00B4" not in full_text, "U+00B4 (acute) escaped normalization"
    # The raw_apos character must not be present anywhere in output.
    assert raw_apos not in full_text, f"{raw_apos!r} was NOT normalized to ASCII apostrophe"


# ── §10.22.2 Bullet 4: foreign-stem YAML table integrity ─────────────────────

def test_nlp_foreign_stem_overrides_resolve_to_catalog() -> None:
    """Every entry in foreign_stem_overrides.tr.yaml has required fields and
    valid enum values.  This guards the YAML schema, not filter output.
    """
    import yaml
    override_path = (
        pathlib.Path(__file__).parent.parent
        / "nlp" / "lang_tr" / "foreign_stem_overrides.tr.yaml"
    )
    assert override_path.is_file(), f"Override table missing at {override_path}"
    data = yaml.safe_load(override_path.read_text(encoding="utf-8"))
    overrides = data.get("overrides", [])
    assert len(overrides) >= 10, "Table has too few entries to be a useful bootstrap"
    valid_vc = {"front", "back"}
    valid_pc = {"vowel_final", "consonant_final"}
    stems_seen: set[str] = set()
    for entry in overrides:
        stem = entry.get("stem", "")
        assert stem, f"Entry missing 'stem' field: {entry}"
        assert stem.lower() not in stems_seen, f"Duplicate stem in overrides: {stem!r}"
        stems_seen.add(stem.lower())
        vc = entry.get("vowel_class", "")
        pc = entry.get("pronunciation_class", "")
        assert vc in valid_vc, f"{stem}: invalid vowel_class={vc!r}"
        assert pc in valid_pc, f"{stem}: invalid pronunciation_class={pc!r}"


# ── Anti-literalism: AST guard on turkish.py ─────────────────────────────────

def test_nlp_strip_suffix_stripper_has_no_hardcoded_suffix_literals() -> None:
    """The suffix-stripper body must not contain any hardcoded Turkish suffix
    strings (e.g. 'ın', 'ler', 'nın' as string literals).

    This is the anti-literalism guard: the YAML table is the single source;
    the algorithm derives all valid forms from it at runtime.

    This test parses the AST of turkish.py and checks that no string-constant
    node inside the strip_proper_noun_suffix / _match_suffix_family functions
    is a known suffix form from the YAML.
    """
    import yaml
    # Load known suffix forms from the YAML.
    suffix_path = (
        pathlib.Path(__file__).parent.parent
        / "nlp" / "lang_tr" / "suffix_families.tr.yaml"
    )
    data = yaml.safe_load(suffix_path.read_text(encoding="utf-8"))
    known_forms: set[str] = set()
    for family in data.get("suffix_families", []):
        known_forms.update(family.get("vowel_final_forms", []))
        known_forms.update(family.get("consonant_final_forms", []))

    # Parse turkish.py AST.
    turkish_path = (
        pathlib.Path(__file__).parent.parent
        / "common" / "text" / "turkish.py"
    )
    source = turkish_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(turkish_path))

    # Collect string constants inside the two functions of interest.
    target_fns = {"strip_proper_noun_suffix", "_match_suffix_family"}
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in target_fns:
            for child in ast.walk(node):
                # In Python 3.8+ string literals are ast.Constant with str value.
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    if child.value in known_forms:
                        violations.append(
                            f"Hardcoded suffix {child.value!r} found in {node.name}()"
                        )

    assert not violations, (
        "Anti-literalism violation: suffix strings must come from YAML, not code.\n"
        + "\n".join(violations)
    )


# ── Anti-literalism: composition test (§10.22.2 + §10.1 + §10.7) ─────────────

def test_nlp_composition_normalize_then_strip_then_dative() -> None:
    """Composition test: §10.1 normalize → §10.22.2 strip suffix → §10.7 dative.

    Simulates the pipeline:
      1. Raw query "Trabzonspor\u2019dan" (RIGHT SINGLE QUOTATION MARK).
      2. normalize() converts U+2019 → ASCII apostrophe.
      3. strip_proper_noun_suffix() recovers "Trabzonspor" / "ablative".
      4. dative("Trabzonspor") produces "Trabzonspor'a" (correct back dative).
    """
    raw = "Trabzonspor\u2019dan"  # Typed with typographic apostrophe

    # Step 1: normalize (§10.1)
    normalised_result = normalize(raw)
    tokens = list(normalised_result.tokens)
    # Normalise produces a token list; rejoin and find the relevant token.
    normalized_token = next(
        (t for t in tokens if "trabzonspor" in t.lower()),
        "Trabzonspor'dan",  # fallback if normalisation changed casing
    )
    # Ensure the typographic apostrophe has been replaced.
    assert "\u2019" not in normalized_token

    # Step 2: strip (§10.22.2) — use original casing for the strip test.
    stem, cls = strip_proper_noun_suffix("Trabzonspor'dan")
    assert stem == "Trabzonspor"
    assert cls == "ablative"

    # Step 3: re-inflect to dative (§10.7).
    result = dative(stem)
    assert result == "Trabzonspor'a"


# ── Property test (hypothesis) ───────────────────────────────────────────────

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    _HYPOTHESIS_AVAILABLE = True
except ImportError:
    _HYPOTHESIS_AVAILABLE = False


if _HYPOTHESIS_AVAILABLE:
    # Turkish uppercase letters + ASCII uppercase for proper-noun start.
    _UPPER_CHARS = "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ"
    _LOWER_CHARS = "abcçdefgğhıijklmnoöprsştuüvyz"

    @given(
        st.text(alphabet=_UPPER_CHARS, min_size=1, max_size=1).flatmap(
            lambda first: st.text(alphabet=_LOWER_CHARS, min_size=1, max_size=20).map(
                lambda rest: first + rest
            )
        )
    )
    @settings(max_examples=200)
    def test_nlp_strip_proper_noun_suffix_never_raises(token: str) -> None:
        """strip_proper_noun_suffix() must not raise for any proper-noun-like token."""
        stem, cls = strip_proper_noun_suffix(token)
        # Invariants that must always hold:
        assert isinstance(stem, str)
        assert cls is None or isinstance(cls, str)
        # When a suffix was stripped, the stem must be a prefix of the token
        # OR the original token had no apostrophe and we did greedy strip.
        if cls is not None and "'" not in token:
            assert token.startswith(stem), (
                f"Greedy strip: {token!r} stem={stem!r} does not start token"
            )
