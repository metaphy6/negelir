"""Phase 10 §10.31.8 — output-side Turkish grammar validator.

This validator runs after Jinja render and before the answer envelope is
sealed. It checks apostrophe-form suffixes against the Turkish suffix-family
rules, enforces locative voicing on consonant-final stems, detects wrong
genitive buffer choice, and catches a narrow stem-final vowel-drop failure
pattern from the Phase 10 grammar addendum.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from common.config import Config
from common.text.turkish import lowercase_tr, strip_proper_noun_suffix

if TYPE_CHECKING:
    from common.config import Config

_APOSTROPHE_SUFFIX_RE = re.compile(r"\b([A-Za-zÇĞİÖŞÜçğıöşü]+)'([a-zçğıöşü]+)\b")
_VOICELSS_CONSONANTS = frozenset("çfhkpsşt")
_VOWELS = frozenset("aeıioöuü")
_VOWEL_DROP_EXAMPLES = {
    "oğul": "oğlu",
    "burun": "burnu",
}

GRAMMAR_FALLBACK_TEMPLATE = "Yanıtım hazırlanırken bir hata oluştu. Lütfen tekrar deneyiniz."


def _stem_ends_with_vowel(stem: str) -> bool:
    return bool(stem and lowercase_tr(stem[-1]) in _VOWELS)


def _is_voiceless_consonant(char: str) -> bool:
    return lowercase_tr(char) in _VOICELSS_CONSONANTS


def _locative_expected_suffix(stem: str) -> str | None:
    if not stem:
        return None
    last = lowercase_tr(stem[-1])
    if _stem_ends_with_vowel(stem) or not _is_voiceless_consonant(last):
        return "da" if last in frozenset("aıou") else "de"
    return "ta" if last in frozenset("aıou") else "te"


def _genitive_form_is_invalid(stem: str, suffix: str) -> bool:
    suffix_lower = lowercase_tr(suffix)
    if suffix_lower not in {"ın", "in", "un", "ün", "nın", "nin", "nun", "nün"}:
        return False
    if _stem_ends_with_vowel(stem):
        return suffix_lower in {"ın", "in", "un", "ün"}
    return suffix_lower in {"nın", "nin", "nun", "nün"}


def _detect_vowel_drop_failure(stem: str, suffix: str) -> bool:
    stem_lower = lowercase_tr(stem)
    if stem_lower in _VOWEL_DROP_EXAMPLES and suffix in {"u", "ü", "ı", "i"}:
        return True
    return False


def validate_tr_output_grammar(answer_text: str, cfg: Config) -> list[dict[str, str]]:
    """Validate a rendered Turkish answer for output-side grammar violations.

    Args:
        answer_text: Rendered Turkish answer text after Jinja template pass.
        cfg: Config object (currently unused, present for future policy knobs).

    Returns:
        A list of violation records. Empty means the answer is clean.
    """
    violations: list[dict[str, str]] = []
    for match in _APOSTROPHE_SUFFIX_RE.finditer(answer_text):
        stem, suffix = match.group(1), match.group(2)
        token = match.group(0)
        suffix_lower = lowercase_tr(suffix)
        stem_lower = lowercase_tr(stem)

        _, suffix_class = strip_proper_noun_suffix(token, assume_proper=True)
        if suffix_class is None:
            violations.append(
                {
                    "type": "invalid_suffix_form",
                    "token": token,
                    "expected": "valid TR suffix form",
                    "got": token,
                }
            )
            continue

        if suffix_class == "locative" and suffix_lower in {"da", "de", "ta", "te"}:
            expected = _locative_expected_suffix(stem)
            if expected and suffix_lower != expected:
                violations.append(
                    {
                        "type": "locative_voicing",
                        "token": token,
                        "expected": expected,
                        "got": suffix_lower,
                    }
                )
                continue

        if suffix_class == "genitive" and _genitive_form_is_invalid(stem, suffix_lower):
            expected = "nın/nin/nun/nün" if _stem_ends_with_vowel(stem) else "ın/in/un/ün"
            violations.append(
                {
                    "type": "genitive_buffer",
                    "token": token,
                    "expected": expected,
                    "got": suffix_lower,
                }
            )
            continue

        if _detect_vowel_drop_failure(stem, suffix_lower):
            violations.append(
                {
                    "type": "stem_vowel_deletion",
                    "token": token,
                    "expected": _VOWEL_DROP_EXAMPLES[stem_lower],
                    "got": token,
                }
            )
            continue

    return violations
