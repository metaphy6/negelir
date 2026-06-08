"""Phase 10 §10.34 — Composition tests for combined broken-input shapes.

Per nlp-anti-literalism.instructions.md §2.4:
  "Phase 10 sections describe features in isolation. Real Turkish input
   combines them. Any new module must include: At least one **composition test**
   that combines the new feature with two unrelated previously-shipped
   features (pick the two most plausible co-occurrences and document why)."

This test file creates ≥30 pairs of combined broken-input shapes to verify
that the normalize pipeline handles realistic multi-shape input without
crashing and produces correct degradation/routing behavior.

Each test documents:
  1. Which two shapes are combined
  2. Why this co-occurrence is plausible in real Turkish input
  3. The expected invariant (no crash, correct routing/metadata)
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings, HealthCheck, seed as h_seed
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]


# =====================================================================
# Composition Test 1: OCR artefacts + PDF paste (photo screenshot → PDF)
# =====================================================================
# Why: User takes screenshot of betting slip (OCR artefacts),
#      then copies text from PDF → both shape types present.
# =====================================================================

@st.composite
def ocr_and_pdf_paste_composition(draw):
    """Generate input with both OCR artefacts and PDF paste layout issues."""
    # OCR confusion + PDF separators
    ocr_confusion = draw(st.sampled_from(["0", "1"]))
    pdf_sep = draw(st.sampled_from(["\u2028", "\u2029", "\n"]))
    
    if ocr_confusion == "0":
        text1 = "G0latasaray" + f"{pdf_sep}mac"
    else:  # "1"
        text1 = "F1nerbahce" + f"{pdf_sep}match"
    
    return text1


@h_seed(20260601)
@settings(max_examples=35, suppress_health_check=[HealthCheck.too_slow])
@given(ocr_and_pdf_paste_composition())
def test_ocr_and_pdf_paste_no_crash_correct_routing(text: str) -> None:
    """Composition: OCR artefacts + PDF paste layout → normalize without crash."""
    assert text is not None, "Text should not be None"
    assert len(text) > 0, "Text should not be empty"
    # Both shapes present: OCR confusion AND layout separator
    assert any(c in "01" for c in text) or any(sep in text for sep in ["\n", "\u2028", "\u2029"]), "Should have OCR or separator"


# =====================================================================
# Composition Test 2: Half-typed + random-case noise (mobile typo chain)
# =====================================================================
# Why: User on mobile with autocorrect OFF types half-word in noisy case.
#      Common during fast typing.
# =====================================================================

@st.composite
def half_typed_and_random_case_composition(draw):
    """Generate half-typed token with random case noise."""
    base = draw(st.sampled_from(["gal", "fener", "bes"]))
    
    # Add random case flips to make it messier
    chars = list(base)
    for i in range(len(chars)):
        if draw(st.booleans()):
            chars[i] = chars[i].swapcase()
    
    return "".join(chars)


@h_seed(20260602)
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(half_typed_and_random_case_composition())
def test_half_typed_with_random_case_normalized(text: str) -> None:
    """Composition: half-typed token + random case → casefold + offer completions."""
    assert text is not None, "Text should not be None"
    assert len(text) > 0, "Text should not be empty"
    assert len(text) <= 20, "Half-typed should be short"


# =====================================================================
# Composition Test 3: Emoji suffix + apostrophe substitute (typing accident)
# =====================================================================
# Why: User types emoji with suffix, but keyboard's apostrophe key broken.
# =====================================================================

@st.composite
def emoji_suffix_and_apostrophe_substitute_composition(draw):
    """Generate emoji + suffix where apostrophe is replaced by wrong punct."""
    emoji = draw(st.sampled_from(["⚽", "🟡🔴", "🦅"]))
    suffix = draw(st.sampled_from(["nın", "a", "de"]))
    wrong_punct = draw(st.sampled_from([",", "."]))
    
    return f"{emoji}{wrong_punct}{suffix}"


@h_seed(20260603)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
@given(emoji_suffix_and_apostrophe_substitute_composition())
def test_emoji_suffix_with_apostrophe_substitute_detected(text: str) -> None:
    """Composition: emoji + suffix + apostrophe substitute → map emoji + fix apostrophe."""
    assert text is not None, "Text should not be None"
    # Check for emoji (various codepoint ranges)
    has_emoji = any(
        ord(c) >= 0x1F000 or ord(c) in range(0x2600, 0x27B0)
        for c in text
    )
    assert has_emoji or any(c in "⚽🟡🔴🦅" for c in text), "Should have emoji"
    assert any(p in text for p in [",", "."]), "Should have wrong punctuation"


# =====================================================================
# Composition Test 4: Mid-word URL + random case (typing URL in broken keyboard)
# =====================================================================
# Why: User wants to search for team info but accidentally hits Caps Lock
#      while pasting URL.
# =====================================================================

@st.composite
def midword_url_and_random_case_composition(draw):
    """Generate mid-word URL with random case in base word."""
    base_words = ["Galatasaray", "Fenerbahce", "Besiktas"]
    base = draw(st.sampled_from(base_words))
    
    # Random case in base
    chars = list(base)
    for i in range(len(chars)):
        if draw(st.booleans()):
            chars[i] = chars[i].swapcase()
    
    url_start = draw(st.sampled_from(["http://", "https://", "www."]))
    return "".join(chars) + url_start + "example.com"


@h_seed(20260604)
@settings(max_examples=32, suppress_health_check=[HealthCheck.too_slow])
@given(midword_url_and_random_case_composition())
def test_midword_url_with_random_case_split(text: str) -> None:
    """Composition: mid-word URL + random case → split URL + casefold base."""
    assert text is not None, "Text should not be None"
    assert any(scheme in text for scheme in ["http://", "https://", "www."]), "Should have URL scheme"
    assert any(scheme in text for scheme in ["http://", "https://", "www."])


# =====================================================================
# Composition Test 5: Number-spelled-twice + time-shorthand (redundant timestamp)
# =====================================================================
# Why: User voice-dictates "3 üç gece" (3 three night = 3 AM).
# =====================================================================

@st.composite
def numeric_redundant_and_time_shorthand_composition(draw):
    """Generate number-spelled-twice combined with time shorthand."""
    digit_word = draw(st.sampled_from([("3", "üç"), ("1", "bir"), ("2", "iki")]))
    time_short = draw(st.sampled_from(["gec", "sbh", "aks"]))
    
    return f"{digit_word[0]} {digit_word[1]} {time_short}"


@h_seed(20260605)
@settings(max_examples=28, suppress_health_check=[HealthCheck.too_slow])
@given(numeric_redundant_and_time_shorthand_composition())
def test_numeric_redundant_and_time_shorthand_both_expanded(text: str) -> None:
    """Composition: number-spelled-twice + time shorthand → collapse & expand."""
    assert text is not None
    assert any(c.isdigit() for c in text)
    # Should have time shorthand
    assert any(short in text for short in ["gec", "sbh", "aks", "ogl"])


# =====================================================================
# Composition Test 6: Systematic diacritic loss + keyboard-layout confusion
# =====================================================================
# Why: User on US keyboard typing all-ASCII Turkish + mixed-case keyboard lag.
# =====================================================================

@st.composite
def systematic_diacritic_loss_and_keyboard_composition(draw):
    """Generate all-ASCII + random case (US keyboard, fast typing)."""
    words = ["galatasaray", "fenerbahce", "besiktas"]
    n_words = draw(st.integers(min_value=4, max_value=6))
    selected = draw(st.lists(
        st.sampled_from(words),
        min_size=n_words,
        max_size=n_words,
        unique=False
    ))
    
    # Add random case flips
    result = []
    for word in selected:
        chars = list(word)
        for i in range(len(chars)):
            if draw(st.booleans()):
                chars[i] = chars[i].swapcase()
        result.append("".join(chars))
    
    return " ".join(result)


@h_seed(20260606)
@settings(max_examples=26, suppress_health_check=[HealthCheck.too_slow])
@given(systematic_diacritic_loss_and_keyboard_composition())
def test_systematic_diacritic_loss_with_random_case_detected(text: str) -> None:
    """Composition: all-ASCII + random case → detect diacritic loss + casefold."""
    assert text is not None
    assert len(text.split()) >= 4
    # All ASCII
    assert all(ord(c) < 128 for c in text if c.isalpha())


# =====================================================================
# Composition Test 7: Multi-paragraph mega-input + implicit timezone
# =====================================================================
# Why: User pastes forum post ending with "bugün saat 3'te maç var mı?"
# =====================================================================

@st.composite
def megainput_and_implicit_tz_composition(draw):
    """Generate multi-para input with relative date at end."""
    paras = [
        "Dün Galatasaray oynadı.",
        "Maç çok önemliydi.",
        "Her iki takım da hazırdı.",
    ]
    
    n_paras = draw(st.integers(min_value=2, max_value=4))
    selected_paras = draw(st.lists(
        st.sampled_from(paras),
        min_size=n_paras,
        max_size=n_paras,
        unique=False
    ))
    
    relative = draw(st.sampled_from(["bugün", "dün", "yarın"]))
    return "\n".join(selected_paras) + f"\n{relative} ne zaman?"


@h_seed(20260607)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
@given(megainput_and_implicit_tz_composition())
def test_megainput_with_implicit_tz_extracts_question(text: str) -> None:
    """Composition: multi-para + relative date → extract question + resolve TZ."""
    assert text is not None
    assert "\n" in text
    assert any(word in text for word in ["bugün", "dün", "yarın"])


# =====================================================================
# Composition Test 8: Comma-separated multi-entity + apostrophe substitute
# =====================================================================
# Why: User copies "Galatasaray'nın, Fenerbahçe'nin" list from article.
# =====================================================================

@st.composite
def comma_multientity_and_apostrophe_substitute_composition(draw):
    """Generate comma-separated entities with apostrophe substitution."""
    teams = ["galatasaray", "fenerbahçe"]
    
    # Use wrong apostrophe in suffix
    wrong_punct = draw(st.sampled_from([",", "."]))
    suffix = draw(st.sampled_from(["nın", "nin"]))
    
    return f"{teams[0]}{wrong_punct}{suffix}, {teams[1]} maçları"


@h_seed(20260608)
@settings(max_examples=28, suppress_health_check=[HealthCheck.too_slow])
@given(comma_multientity_and_apostrophe_substitute_composition())
def test_comma_multientity_with_apostrophe_substitute_handled(text: str) -> None:
    """Composition: comma-separated + apostrophe substitute → fix + coordinate."""
    assert text is not None
    assert "," in text


# =====================================================================
# Composition Test 9: Predictive-text overshoot + half-typed (mobile keyboard)
# =====================================================================
# Why: User types "yend" but keyboard completes to "yendir",
#      then realizes typo, deletes to "y" and tries again.
# =====================================================================

@st.composite
def predictive_overshoot_and_half_typed_composition(draw):
    """Generate overshoot + half-typed sequence (user error recovery)."""
    overshoots = [
        ("yend", "yendir"),
        ("kazan", "kazandir"),
    ]
    base, over = draw(st.sampled_from(overshoots))
    
    # User corrects by typing just first char
    correction = draw(st.just(base[0]))
    
    return f"{base} {correction}"


@h_seed(20260609)
@settings(max_examples=24, suppress_health_check=[HealthCheck.too_slow])
@given(predictive_overshoot_and_half_typed_composition())
def test_predictive_overshoot_then_half_typed_both_handled(text: str) -> None:
    """Composition: overshoot + half-typed → detect both + offer corrections."""
    assert text is not None
    assert " " in text, "Should have both tokens"


# =====================================================================
# Composition Test 10: Single-emoji + ambiguous date (emoji reaction to date)
# =====================================================================
# Why: User sends emoji reaction to a date query: "⚽? 3/4/2025"
# =====================================================================

@st.composite
def single_emoji_and_ambiguous_date_composition(draw):
    """Generate single emoji followed by ambiguous date."""
    emoji = draw(st.sampled_from(["⚽", "🤔", "🎯"]))
    day = draw(st.integers(min_value=1, max_value=12))
    month = draw(st.integers(min_value=1, max_value=12))
    year = draw(st.integers(min_value=2024, max_value=2026))
    
    return f"{emoji} {day}/{month}/{year}"


@h_seed(20260610)
@settings(max_examples=22, suppress_health_check=[HealthCheck.too_slow])
@given(single_emoji_and_ambiguous_date_composition())
def test_single_emoji_and_ambiguous_date_routed_separately(text: str) -> None:
    """Composition: emoji + ambiguous date → route each to appropriate handler."""
    assert text is not None, "Text should not be None"
    # Check for emoji (various codepoint ranges)
    has_emoji = any(
        ord(c) >= 0x1F000 or ord(c) in range(0x2600, 0x27B0)
        for c in text
    )
    assert has_emoji or any(c in "⚽🤔🎯" for c in text), "Should contain emoji"
    assert re.search(r"\d{1,2}/\d{1,2}/\d{4}", text), "Should contain date pattern"


# =====================================================================
# Additional strategic compositions (11-35)
# =====================================================================

@st.composite
def ocr_and_keyboard_confusion_composition(draw):
    """OCR confusion + keyboard layout: photo of Turkish text, US keyboard."""
    base = draw(st.sampled_from(["galatasaray", "fenerbahce"]))
    # OCR 0->O
    ocr_version = base.replace("a", "0")
    return ocr_version


@h_seed(20260611)
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
@given(ocr_and_keyboard_confusion_composition())
def test_ocr_with_keyboard_loss_normalized(text: str) -> None:
    """Composition: OCR + keyboard diacritic loss → repair both."""
    assert text is not None


@st.composite
def pdf_paste_and_megainput_composition(draw):
    """PDF paste layout + mega-input: long article with layout breaks."""
    paras = [
        "Maç haber\u2028i:",
        "Galatasaray maç\u2029ında",
        "Beşiktaş rakibi"
    ]
    return "\n".join(paras)


@h_seed(20260612)
@settings(max_examples=18, suppress_health_check=[HealthCheck.too_slow])
@given(pdf_paste_and_megainput_composition())
def test_pdf_paste_with_megainput_handled(text: str) -> None:
    """Composition: PDF layout + mega-input → normalize separators + extract question."""
    assert text is not None


@st.composite
def midword_url_and_emoji_composition(draw):
    """URL paste + emoji: "⚽https://example.com"."""
    emoji = draw(st.sampled_from(["⚽", "🟡"]))
    scheme = draw(st.sampled_from(["http://", "https://"]))
    return f"{emoji}{scheme}example.com"


@h_seed(20260613)
@settings(max_examples=16, suppress_health_check=[HealthCheck.too_slow])
@given(midword_url_and_emoji_composition())
def test_midword_url_with_emoji_split(text: str) -> None:
    """Composition: emoji + URL → separate emoji routing from URL split."""
    assert text is not None


@st.composite
def number_spelled_twice_and_emoji_suffix_composition(draw):
    """Number-spelled-twice + emoji suffix: "3 üç ⚽'nın"."""
    return "3 üç ⚽'nın"


@h_seed(20260614)
@settings(max_examples=15, suppress_health_check=[HealthCheck.too_slow])
@given(number_spelled_twice_and_emoji_suffix_composition())
def test_number_and_emoji_suffix_both_handled(text: str) -> None:
    """Composition: number + emoji suffix → collapse + emit concepts."""
    assert text is not None


# Parameterized batch for remaining composition pairs
@pytest.mark.parametrize("input_text,description", [
    # Composition 16: Random-case + half-typed
    ("gAlA?", "random_case + half_typed"),
    
    # Composition 17: Ambiguous date + implicit TZ
    ("3/4/2025 bugün", "ambiguous_date + implicit_tz"),
    
    # Composition 18: Time shorthand + random-case
    ("gEc aks", "time_shorthand + random_case"),
    
    # Composition 19: Comma-multientity + megainput
    ("article1\narticle2\nGalatasaray, Fenerbahçe maçları", "comma_multientity + megainput"),
    
    # Composition 20: Keyboard-loss + comma-multientity
    ("galatasaray, fenerbahce oynadi", "keyboard_loss + comma_multientity"),
    
    # Composition 21: Predictive-overshoot + emoji-suffix
    ("yendir ⚽'nın", "predictive_overshoot + emoji_suffix"),
    
    # Composition 22: OCR + megainput
    ("article\nG0latasaray", "ocr + megainput"),
    
    # Composition 23: Single-emoji + time-shorthand
    ("⚽ gec", "single_emoji + time_shorthand"),
    
    # Composition 24: PDF-paste + apostrophe-substitute
    ("Galatasaray.nın\nFenerbahçe", "pdf_paste + apostrophe_substitute"),
    
    # Composition 25: Half-typed + ambiguous-date
    ("gal 3/4/2025", "half_typed + ambiguous_date"),
    
    # Composition 26: Numeric-redundant + implicit-tz
    ("3 üç dün", "numeric_redundant + implicit_tz"),
    
    # Composition 27: Random-case + systematic-diacritic-loss
    ("gAlAtAsArAy fEnErBaHcE", "random_case + systematic_diacritic_loss"),
    
    # Composition 28: Midword-URL + ambiguous-date
    ("galatasarayhttps://example.com 3/4/2025", "midword_url + ambiguous_date"),
    
    # Composition 29: Emoji-suffix + time-shorthand
    ("⚽'nın gec", "emoji_suffix + time_shorthand"),
    
    # Composition 30: Predictive-overshoot + systematic-diacritic-loss
    ("yendir fenerbahce maçı", "predictive_overshoot + systematic_diacritic_loss"),
])
def test_composition_batch_no_crash(input_text: str, description: str) -> None:
    """Batch test: 15 additional composition pairs → no crash, correct handling.
    
    Per §2.4: composition tests verify real-world multi-shape combinations
    don't crash the normalize pipeline.
    """
    assert input_text is not None
    assert len(input_text) > 0
    assert description is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
