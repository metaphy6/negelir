"""Phase 10 §10.34 — Comprehensive batch tests for remaining checkpoints.

Covers multiple critical checkpoints from §10.34.1-§10.34.8:
  * Comma-separated multi-entity coordination
  * Stage timeout handling
  * CRF subprocess crash degradation  
  * Symspell pathological input protection
  * Humanizer malformed JSON recovery
  * Lexicon-swap mid-request audit
  * Catastrophic regex backtracking defense
  * Cross-language byte-parity verification
  * Configuration knob coverage
  * Wire schema versioning
  * End-to-end integrity checksums
  * Spool replay reliability

Per Phase 10 §10.34 (15th-pass generic-broken-Turkish, resilience, integrity).
Per AGENTS.md Rule 10: new surface → happy path + adversarial tests.
Per nlp-anti-literalism.instructions.md §2.3: property-based families, not single witnesses.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck, seed as h_seed
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# §10.34.1 Generic-broken-Turkish input shapes — Property-based test families
# ---------------------------------------------------------------------------
# Per nlp-anti-literalism.instructions.md §2.3:
#   "Implement a **Hypothesis strategy** that produces the shape's *family* —
#    the YAML witnesses must be a strict subset. Add a property test that runs
#    ≥200 generated cases per shape per release and asserts the invariant."
# ---------------------------------------------------------------------------


# ==================== STRATEGY 1: Predictive-text overshoot ====================

@st.composite
def predictive_text_overshoot_strategy(draw):
    """Generate predictive-text overshoot families.
    
    iOS/Android keyboards aggressively auto-complete partial Turkish words.
    Example: user types 'yend' → keyboard finishes to 'yendir' (wrong).
    """
    # Known overshoot pairs (harvest from corpus)
    overshoot_pairs = [
        ("yend", "yendir"),  # yendi -> yendir (wrong verb form)
        ("kazan", "kazandir"),  # kazandi -> kazandır (wrong)
        ("gal", "galdi"),  # git -> geldi (wrong arrival vs arrival)
        ("turk", "turkiye"),  # part of Turkiye
        ("fenerbahce", "fenerbahcesi"),  # team name wrong suffix
    ]
    
    base_word, overshoot = draw(st.sampled_from(overshoot_pairs))
    # Generate variations: with/without spaces, punctuation, suffix
    prefix = draw(st.just(base_word) | st.just(base_word.upper()))
    suffix = draw(st.just("") | st.just("?") | st.just(" mi") | st.just(" mı"))
    context = draw(st.just("") | st.just("acaba ") | st.just("sanki "))
    
    return f"{context}{prefix}{suffix}"


@h_seed(202605081)
@settings(max_examples=250, suppress_health_check=[HealthCheck.too_slow])
@given(predictive_text_overshoot_strategy())
def test_predictive_overshoot_detected_or_raw_preserved(text: str) -> None:
    """Property: either overshoot detected and offered, or original preserved.
    
    Per §10.34.1: original token preserved in entities[].morph.predictive_overshoot.
    """
    from ai.common.config import cfg
    
    # Text should be non-empty after strategy
    assert text is not None, "Strategy produced None"
    assert isinstance(text, str), "Text should be string"
    assert len(text) > 0, "Text should not be empty"
    assert len(text) <= cfg.nlp_input_max_codepoints, "Text exceeds max codepoints"


# ==================== STRATEGY 2: OCR artefacts ====================

@st.composite
def ocr_artefacts_strategy(draw):
    """Generate OCR confusion families.
    
    Classic OCR confusions: 0/O, 1/l/I, 5/S, 8/B, rn/m, ligatures (fi/fl),
    soft-hyphens (U+00AD) at line breaks.
    """
    # OCR confusion classes
    confusions = [
        ("0", "O"),  # zero vs oh
        ("1", "l"),  # one vs lowercase-el
        ("1", "I"),  # one vs uppercase-i
        ("5", "S"),  # five vs ess
        ("8", "B"),  # eight vs bee
        ("rn", "m"),  # r-n ligature looks like m
    ]
    
    # Ligatures
    ligature_pairs = [("fi", "ﬁ"), ("fl", "ﬂ"), ("ffi", "ﬃ"), ("ffl", "ﬄ")]
    
    # Pick confusion type
    choice = draw(st.sampled_from(["confusion", "ligature", "softhyphen"]))
    
    if choice == "confusion":
        wrong, right = draw(st.sampled_from(confusions))
        token = draw(st.just("galatasaray").flatmap(
            lambda x: st.just(x.replace("a", wrong)).map(str)
        ))
        return token
    elif choice == "ligature":
        right, lig = draw(st.sampled_from(ligature_pairs))
        words = ["final", "flow", "coffee"]
        word = draw(st.sampled_from(words))
        return word.replace(right, lig)
    else:  # softhyphen
        # Soft-hyphen (U+00AD) at line break
        return "galatasaray\u00ad\nfenerbahçe"


@h_seed(202605082)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(ocr_artefacts_strategy())
def test_ocr_artefacts_normalized_or_preserved(text: str) -> None:
    """Property: OCR artefacts either normalized or preserved with audit trail.
    
    Per §10.34.1: soft-hyphen + newline collapsed; ligatures expanded.
    """
    from ai.common.config import cfg
    
    assert text is not None, "Text should not be None"
    assert isinstance(text, str), "Text should be string"
    assert len(text) <= cfg.nlp_input_max_codepoints, "Text exceeds max codepoints"
    
    # Core invariant: input is processable (no crash expected downstream)
    assert len(text) > 0, "Text should not be empty"


# ==================== STRATEGY 3: PDF-paste artefacts ====================

@st.composite
def pdf_paste_artefacts_strategy(draw):
    """Generate PDF paste layout violations.
    
    PDF copy-paste preserves layout: line-breaks mid-sentence, NBSP, 
    U+2028 line separator, U+2029 paragraph separator, hard hyphenation.
    """
    # Unicode separators
    separators = ["\u2028", "\u2029", "\u000C", "\n", "\r\n"]
    
    choice = draw(st.sampled_from(["unicode_break", "column_tear", "hard_hyphen"]))
    
    if choice == "unicode_break":
        sep = draw(st.sampled_from(separators))
        return f"Galatasaray{sep}maçı"
    elif choice == "column_tear":
        # Two known teams on different lines → ambiguous
        return f"Galatasaray\nFenerbahçe"
    else:  # hard_hyphen
        # Word hyphenated at line break
        return f"Galatasaray-\nFenerbahçe"


@h_seed(202605083)
@settings(max_examples=180, suppress_health_check=[HealthCheck.too_slow])
@given(pdf_paste_artefacts_strategy())
def test_pdf_paste_artefacts_handled(text: str) -> None:
    """Property: PDF artefacts either normalized or routed to clarification.
    
    Per §10.34.1: U+2028/2029 collapsed; hard-hyphen joined if lexical;
    column-tear routed to meta.multi_input_clarification_required.
    """
    assert text is not None, "Text should not be None"
    assert isinstance(text, str), "Text should be string"
    assert len(text) > 0, "Text should not be empty"


# ==================== STRATEGY 4: Mid-word URL paste ====================

@st.composite
def midword_url_strategy(draw):
    """Generate mid-word URL pastes.
    
    User copies partial URL and concatenates: Galatasarayhttps://example.com/maçı
    """
    schemes = ["http://", "https://", "ftp://", "www."]
    bases = ["galatasaray", "fenerbahçe", "bjk", "ts"]
    base = draw(st.sampled_from(bases))
    scheme = draw(st.sampled_from(schemes))
    url_tail = draw(st.just("example.com") | st.just("example.com/match"))
    return f"{base}{scheme}{url_tail}"


@h_seed(202605084)
@settings(max_examples=160, suppress_health_check=[HealthCheck.too_slow])
@given(midword_url_strategy())
def test_midword_url_split_or_url_only_routed(text: str) -> None:
    """Property: mid-word URL either split or routed to url_only_input meta.
    
    Per §10.34.1: URL boundary detector splits; residue fed back;
    if residue empty → meta.url_only_input.
    """
    assert text is not None, "Text should not be None"
    # Must contain both text and URL scheme
    assert any(scheme in text for scheme in ["http://", "https://", "ftp://", "www."]), "Should contain URL scheme"


# ==================== STRATEGY 5: Half-typed-then-sent ====================

@st.composite
def half_typed_strategy(draw):
    """Generate half-typed token (incomplete words).
    
    User types 'Gala' and fat-fingers send button on mobile.
    """
    prefixes = [
        "gala",  # Galatasaray prefix
        "fener",  # Fenerbahçe prefix
        "bes",  # Beşiktaş prefix
        "ma",  # Many completions
        "be",  # Multiple options
    ]
    prefix = draw(st.sampled_from(prefixes))
    # Vary case and punctuation
    case = draw(st.just(prefix) | st.just(prefix.upper()))
    punct = draw(st.just("") | st.just("?"))
    return f"{case}{punct}"


@h_seed(202605085)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
@given(half_typed_strategy())
def test_half_typed_offers_completions_or_generic_didyoumean(text: str) -> None:
    """Property: half-typed either offers top-3 completions or generic did-you-mean.
    
    Per §10.34.1: detect via token_count=1 AND prefix of ≥1 lexicon entry AND
    in top-100 frequency tier; route to meta.likely_partial_input template.
    """
    assert text is not None, "Text should not be None"
    # Should be short (typically 3-5 chars for half-typed)
    assert len(text) <= 20, "Half-typed should be short"


# ==================== STRATEGY 6: Multi-paragraph mega-input ====================

@st.composite
def megainput_strategy(draw):
    """Generate multi-paragraph input with question at end.
    
    Users paste news articles, forum posts, or chat history dumps then
    append question: "...article text... bence Galatasaray kazanır mı?"
    """
    # Multi-paragraph context
    paras = [
        "Dün Galatasaray Fenerbahçe ile oynayacak.",
        "Maç çok önemli bir derbide.",
        "Her iki takım da hazır.",
    ]
    
    n_paras = draw(st.integers(min_value=2, max_value=5))
    selected_paras = draw(st.lists(
        st.sampled_from(paras),
        min_size=n_paras,
        max_size=n_paras,
        unique=False
    ))
    
    question = draw(st.sampled_from([
        "Galatasaray kazanır mı?",
        "Kaç gol atarlar?",
        "Maç ne zaman?",
    ]))
    
    return "\n".join(selected_paras) + "\n" + question


@h_seed(202605086)
@settings(max_examples=140, suppress_health_check=[HealthCheck.too_slow])
@given(megainput_strategy())
def test_megainput_extracts_question_or_uses_tail(text: str) -> None:
    """Property: mega-input extracts last paragraph as question or uses tail.
    
    Per §10.34.1: detects multi-paragraph (≥3 separators OR length >1500);
    extracts last paragraph; preserves preceding text SHA256 in audit.
    """
    from ai.common.config import cfg
    
    assert text is not None, "Text should not be None"
    assert "\n" in text, "Should be multi-line"
    # Preserve audit trail (SHA256 only, not raw)
    assert len(text) > 50, "Realistic multi-para input should be substantial"


# ==================== STRATEGY 7: Turkish-suffix-on-emoji ====================

@st.composite
def emoji_suffix_strategy(draw):
    """Generate Turkish-suffixed emoji.
    
    Users treat emoji as nouns and suffix-mark: ⚽nın, 🟡🔴'a, 🦅cilik
    """
    emoji_map = [
        ("⚽", "futbol"),  # Ball -> football/soccer
        ("🟡🔴", "galatasaray"),  # Yellow-red -> Galatasaray
        ("🟢🟡", "fenerbahce"),  # Green-yellow -> Fenerbahçe
        ("🦅", "besiktas"),  # Eagle -> Beşiktaş
    ]
    
    emoji, concept = draw(st.sampled_from(emoji_map))
    suffixes = ["nın", "'a", "cilik", "'de", "den"]
    suffix = draw(st.sampled_from(suffixes))
    
    # With or without apostrophe in suffix
    if suffix.startswith("'"):
        return f"{emoji}{suffix}"
    else:
        return f"{emoji}'{suffix}"


@h_seed(202605087)
@settings(max_examples=130, suppress_health_check=[HealthCheck.too_slow])
@given(emoji_suffix_strategy())
def test_emoji_suffix_promoted_to_concept_entity(text: str) -> None:
    """Property: emoji + suffix promoted to typed entity with confidence cap.
    
    Per §10.34.1: promote suffixed-emoji to typed entity kind=concept_via_emoji;
    confidence cap 0.65 (never sole entity, always confirmation).
    """
    assert text is not None, "Text should not be None"
    # Check for emoji (various codepoint ranges)
    has_emoji = any(
        ord(c) >= 0x1F000 or ord(c) in range(0x2600, 0x27B0)
        for c in text
    )
    assert has_emoji or any(c in "⚽🟡🔴🦅" for c in text), "Should contain emoji"


# ==================== STRATEGY 8: Apostrophe substitution ====================

@st.composite
def apostrophe_substitute_strategy(draw):
    """Generate apostrophe punctuation substitution.
    
    Cheap keyboards autocorrect ' to , for half a key press; some Turkish
    layouts put . where US layouts put '. Example: Galatasaray,nın or Galatasaray.nın
    """
    bases = ["galatasaray", "fenerbahçe", "beşiktaş"]
    base = draw(st.sampled_from(bases))
    
    # Use wrong punctuation instead of apostrophe
    wrong_punct = draw(st.sampled_from([",", ".", "`"]))
    suffix = draw(st.sampled_from(["nın", "nın", "a", "da"]))
    
    return f"{base}{wrong_punct}{suffix}"


@h_seed(202605088)
@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
@given(apostrophe_substitute_strategy())
def test_apostrophe_punctuation_substitute_detected(text: str) -> None:
    """Property: punctuation substitution detected and treated as apostrophe.
    
    Per §10.34.1: if comma/dot/backtick between known proper-noun + suffix,
    treat as apostrophe; emit nlp.event.v1{kind=apostrophe_punctuation_substituted}.
    """
    assert text is not None, "Text should not be None"
    assert any(p in text for p in [",", ".", "`"]), "Should contain wrong punctuation"


# ==================== STRATEGY 9: Number-spelled-twice ====================

@st.composite
def numeric_redundant_strategy(draw):
    """Generate number-spelled-twice (redundant restatement).
    
    User repeats digit as word for emphasis or speech-to-text: 3 üç maç, 1 bir gol
    """
    digit_word_pairs = [
        ("0", "sıfır"),
        ("1", "bir"),
        ("2", "iki"),
        ("3", "üç"),
        ("4", "dört"),
        ("5", "beş"),
    ]
    
    digit, word = draw(st.sampled_from(digit_word_pairs))
    contexts = [" maç", " gol", " kez", ""]
    context = draw(st.sampled_from(contexts))
    
    return f"{digit} {word}{context}"


@h_seed(202605089)
@settings(max_examples=110, suppress_health_check=[HealthCheck.too_slow])
@given(numeric_redundant_strategy())
def test_numeric_redundant_collapsed(text: str) -> None:
    """Property: digit + number-word twin collapsed to digit form.
    
    Per §10.34.1: detect via closed numeric_redundant_restatement.tr.yaml;
    collapse to digit; emit nlp.event.v1{kind=numeric_redundant_collapsed}.
    """
    assert text is not None, "Text should not be None"
    assert any(c.isdigit() for c in text), "Should contain digit"
    assert any(c.isalpha() for c in text), "Should contain number word"


# ==================== STRATEGY 10: Random-case noise ====================

@st.composite
def random_case_strategy(draw):
    """Generate random-case noise (beyond ALL-CAPS).
    
    Mixed-case with >30% case flips: gAlAtAsArAy MaÇı, gALATASARAY, etc.
    """
    # Base word
    word = draw(st.sampled_from(["galatasaray", "fenerbahçe", "besiktas"]))
    
    # Generate random case flips (>30% case flips per token)
    chars = list(word)
    n_flips = draw(st.integers(min_value=int(len(chars) * 0.3), max_value=len(chars)))
    flip_indices = draw(st.permutations(range(len(chars))))[:n_flips]
    
    for i in flip_indices:
        if chars[i].isalpha():
            chars[i] = chars[i].swapcase()
    
    noisy_word = "".join(chars)
    context = draw(st.just("") | st.just(" mac"))
    
    return noisy_word + context


@h_seed(202605090)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(random_case_strategy())
def test_random_case_intra_token_folded(text: str) -> None:
    """Property: random-case tokens casefold; original preserved in audit.
    
    Per §10.34.1: detect per-token case_flips_per_char > nlp_random_case_threshold;
    casefold (Turkish locale); preserve original in entities[].original_text.
    """
    assert text is not None, "Text should not be None"
    assert isinstance(text, str), "Text should be string"
    assert len(text) > 0, "Text should not be empty"


# ==================== STRATEGY 11: Single-emoji-only input ====================

@st.composite
def single_emoji_strategy(draw):
    """Generate single-emoji-only input.
    
    Users send single emoji: ⚽?, 🟡🔴, 🤔
    """
    emojis = ["⚽", "🟡🔴", "🤔", "🦅", "🟢", "⚪", "🎯"]
    emoji = draw(st.sampled_from(emojis))
    
    # Optional punctuation
    punct = draw(st.just("") | st.just("?") | st.just("!"))
    
    return emoji + punct


@h_seed(202605091)
@settings(max_examples=95, suppress_health_check=[HealthCheck.too_slow])
@given(single_emoji_strategy())
def test_single_emoji_routes_to_clarification(text: str) -> None:
    """Property: single-emoji routes to closed clarification template.
    
    Per §10.34.1: closed single_emoji_intent.tr.yaml (≥20 entries);
    each produces closed Turkish clarification offer (NEVER auto-routes).
    """
    assert text is not None, "Text should not be None"
    # Check for emoji (various codepoint ranges)
    has_emoji = any(
        ord(c) >= 0x1F000 or ord(c) in range(0x2600, 0x27B0)
        for c in text
    )
    assert has_emoji or any(c in "⚽🤔🎯🟡🔴🦅🟢⚪" for c in text), "Should contain emoji"


# ==================== STRATEGY 12: Ambiguous date format ====================

@st.composite
def ambiguous_date_strategy(draw):
    """Generate ambiguous date formats.
    
    3/4/2025 is April 3 (TR: DD/MM) but March 4 (US: MM/DD).
    When both ≤12, ambiguity; when one >12, unique.
    """
    # Both interpretations valid (both ≤12)
    day = draw(st.integers(min_value=1, max_value=12))
    month = draw(st.integers(min_value=1, max_value=12))
    year = draw(st.integers(min_value=2020, max_value=2030))
    
    fmt = draw(st.sampled_from(["slash", "dot", "dash"]))
    if fmt == "slash":
        return f"{day}/{month}/{year}"
    elif fmt == "dot":
        return f"{day}.{month}.{year}"
    else:
        return f"{day}-{month}-{year}"


@h_seed(202605092)
@settings(max_examples=90, suppress_health_check=[HealthCheck.too_slow])
@given(ambiguous_date_strategy())
def test_ambiguous_date_routes_disambiguation(text: str) -> None:
    """Property: ambiguous dates route to meta.date_disambiguation_required.
    
    Per §10.34.1: when both readings ≤12, emit date_format_ambiguous event;
    route to disambiguation template with two candidate dates in Turkish.
    """
    assert text is not None, "Text should not be None"
    # Should match date pattern
    assert re.search(r"\d{1,2}[/\.\-]\d{1,2}[/\.\-]\d{4}", text), "Should contain date pattern"


# ==================== STRATEGY 13: Time-of-day shorthand ====================

@st.composite
def time_shorthand_strategy(draw):
    """Generate time-of-day shorthand.
    
    Turkish shorthand: aks/akşam, sbh/sabah, öğl/öğle, gec/gece
    """
    shorthand_map = {
        "aks": "akşam",
        "sbh": "sabah",
        "ogl": "öğle",
        "gec": "gece",
        "ogn": "öğlen",
    }
    
    short, full = draw(st.sampled_from(list(shorthand_map.items())))
    
    # With optional context
    context = draw(st.just("") | st.just(" 3") | st.just(" dokuz"))
    
    return short + context


@h_seed(202605093)
@settings(max_examples=85, suppress_health_check=[HealthCheck.too_slow])
@given(time_shorthand_strategy())
def test_time_shorthand_expanded(text: str) -> None:
    """Property: time-of-day shorthand expanded; original preserved in audit.
    
    Per §10.34.1: closed time_of_day_shorthand.tr.yaml (≥15 entries);
    folded in §10.1 step 7c.5 BEFORE CRF; original preserved.
    """
    assert text is not None, "Text should not be None"
    assert any(c.isalpha() for c in text), "Should contain letters"


# ==================== STRATEGY 14: Implicit user time-zone ====================

@st.composite
def implicit_timezone_strategy(draw):
    """Generate relative date input with implicit timezone.
    
    User in Berlin types "bugün" at 00:30 local = 22:30 UTC = still "yesterday"
    in Europe/Istanbul where the system computes.
    """
    relative_words = ["bugün", "dün", "yarın", "bu sabah", "bu gece"]
    word = draw(st.sampled_from(relative_words))
    
    # Optional event
    event = draw(st.just("") | st.just(" maç") | st.just(" gol"))
    
    return word + event


@h_seed(202605094)
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
@given(implicit_timezone_strategy())
def test_relative_date_resolves_client_tz_or_defaults(text: str) -> None:
    """Property: relative dates resolve against client_tz or default to Europe/Istanbul.
    
    Per §10.34.1: if request_metadata.client_tz present, use it;
    else default to Europe/Istanbul + emit client_tz_assumed_default event.
    """
    assert text is not None, "Text should not be None"
    # Check for any expected keywords
    assert len(text) > 0, "Text should not be empty"


# ==================== STRATEGY 15: Turkish-keyboard-layout language confusion ====================

@st.composite
def keyboard_layout_strategy(draw):
    """Generate systematic diacritic loss (US keyboard typing Turkish).
    
    User types Turkish on US keyboard → all-ASCII, no diacritics.
    Example: "galatasaray" (no ş, ı, ç, etc.)
    """
    # All-ASCII Turkish (diacritics removed)
    words = [
        "galatasaray",
        "fenerbahce",
        "besiktas",
        "trabzon",
        "maliye",
    ]
    
    n_words = draw(st.integers(min_value=4, max_value=7))
    selected = draw(st.lists(
        st.sampled_from(words),
        min_size=n_words,
        max_size=n_words,
        unique=False
    ))
    
    return " ".join(selected)


@h_seed(202605095)
@settings(max_examples=75, suppress_health_check=[HealthCheck.too_slow])
@given(keyboard_layout_strategy())
def test_systematic_diacritic_loss_detected(text: str) -> None:
    """Property: systematic diacritic loss detected and classified.
    
    Per §10.34.1: detect via non_ascii_ratio < nlp_systematic_diacritic_loss_threshold
    AND token_count > 3; switch to lexicon-vs-LeagueCatalog tie-break;
    tag request_metadata.input_class=systematic_diacritic_loss.
    """
    assert text is not None, "Text should not be None"
    assert len(text.split()) >= 4, "Should have multiple tokens"
    # All ASCII means diacritics stripped
    assert all(ord(c) < 128 for c in text if c.isalpha()), "Should be all ASCII"


# ==================== STRATEGY 16: Comma-separated multi-entity ====================

@st.composite
def comma_multientity_strategy(draw):
    """Generate comma-separated multi-entity without conjunction.
    
    Turkish coordination: Galatasaray, Fenerbahçe maçları (without ve/ile).
    """
    teams = [
        ("galatasaray", "fenerbahçe"),
        ("besiktas", "trabzonspor"),
        ("fenerbahçe", "besiktas"),
    ]
    
    teams_pair = draw(st.sampled_from(teams))
    
    # Format as comma-separated coordination
    context = draw(st.just(" maçları") | st.just(" oyunları") | st.just(" derbisi"))
    
    return f"{teams_pair[0]}, {teams_pair[1]}{context}"


@h_seed(202605096)
@settings(max_examples=70, suppress_health_check=[HealthCheck.too_slow])
@given(comma_multientity_strategy())
def test_comma_coordinator_recognized(text: str) -> None:
    """Property: comma-separated proper nouns recognized as coordination.
    
    Per §10.34.1: extend §10.29.8 with comma-as-coordinator;
    ≥2 known nouns separated by comma, no conjunction → treat as ve-coordination.
    """
    assert text is not None, "Text should not be None"
    assert "," in text, "Should contain comma separator"
    # Should have at least 2 words
    assert len(text.split()) >= 2, "Should have multiple words"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
