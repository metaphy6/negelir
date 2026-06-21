"""Phase 10 §10.1 -- Input normalization pipeline (9-step, ordered, idempotent).

Steps (order is BINDING; any reordering breaks downstream tests):

  1. Length cap: reject inputs that exceed ``cfg.nlp_input_max_codepoints``.
  2. NFC normalize.
  3. Control-char + zero-width + RTL-override strip.
     (Steps 2+3 are fused into ``canonical_normalize`` for Python/Go parity.)
  3.5. Unicode confusables fold (§10.21.5): Cyrillic/Greek lookalikes -> ASCII-Turkish.
  4. Turkish-aware lowercase (I->dotless-i, dotted-I->i; NEVER ``str.lower()``).
  5. Punctuation normalization (curly quotes, em/en-dash, multiple spaces).
  6. Diacritic restoration (table-driven).  [\u00a7 10.3 stub -- pass-through]
  7. Tokenization (whitespace + punctuation split).
  8. Token-level typo correction.             [\u00a7 10.3 stub -- pass-through]

Usage::

    from nlp.normalize import normalize_input, InputTooLongError
    from common.config import cfg

    try:
        result = normalize_input("Galatasaray mac tahmini", cfg=cfg)
    except InputTooLongError:
        ...

"""
from __future__ import annotations

import html
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from common.config import cfg
from common.locale_loader import build_team_names, load_locale
import json
import yaml

from common.text.normalize import canonical_normalize, confusables_fold
from common.text._turkish_compose import compose_turkish_dotted_i
from common.text.turkish import (
    MorphCandidate,
    collapse_repeated_chars,
    digit_letter_confusable_fold,
    load_repeat_allowlist,
    lowercase_tr,
    normalize_morph_candidates,
)
import hashlib
from nlp._particle_normalize import (
    _is_valid_stem as _is_valid_particle_stem,
    _last_vowel as _particle_last_vowel,
    load_rules as _load_particle_rules,
    normalize_particles as _normalize_particles,
)
from nlp.numeric_disambiguation import choose_numeric_parse
from nlp.runtime.budget import BudgetExceeded, RequestBudget
from nlp.degenerate_input import detect_degenerate_input
from nlp.dialect_normalize import (    apply_dialect_normalize as _apply_dialect_normalize,
    _DialectNormalizer,
    load_abbreviations,
)
from nlp.diacritics import make_diacritic_restorer
from nlp.offensive import replace_obfuscated_slurs
from nlp.postposition_stack import (
    detect_postposition_stacks,
    PostpositionStackMatch,
    UnknownPostpositionStack,
)
from common.telemetry import get_sink
from nlp.runtime.budget import RequestBudget
from nlp.phase10_30 import (
    apply_asr_punctuation_words,
    classify_conversational_meta,
    detect_coordinating_particles,
    detect_conditional_modifier,
    detect_focus_particle_disambiguation,
    detect_ki_contexts,
    detect_question_tag_pragmatic_class,
    detect_search_operator_syntax_in_text,
    detect_sarcastic_modifier,
    expand_idioms,
    find_sarcasm_cue_ids,
    find_sarcasm_cues_without_context,
    resolve_voice_number_context,
    strip_politeness_markers,
)
from nlp.apostrophe_proper_noun import (
    ApostropheRepair,
    _load_lexicon_stems,
    repair_apostrophe_proper_noun,
)
from nlp.assimilation import (
    AssimilationRules,
    fold_assimilated_suffixes,
    load_assimilation_pairs,
)
from nlp.compound_splitter import split_compound_tokens
from nlp.football_vocab import load_football_vocab
from nlp.consonant_alternation import (
    ConsonantAlternationRule,
    load_consonant_alternations,
    tolerate_consonant_alternation,
)
from nlp.vowel_drop_before_suffix import (
    VowelDropBeforeSuffixRule,
    load_vowel_drop_before_suffix_rules,
    tolerate_vowel_drop_before_suffix,
)
from nlp.loanword_singularisation import (
    LoanwordSingularisationRule,
    load_loanword_singularisation_rules,
    singularise_loanword_plural,
)
from nlp.geminate_restoration import (
    GeminateRestorationRule,
    load_geminate_restorations,
    restore_geminate,
)
from nlp.reduplication import (
    ReduplicationRule,
    collapse_reduplication,
    load_reduplication_pairs,
)
_inline_self_correction_markers: dict[str, tuple[tuple[str, ...], ...]] | None = None
from nlp.inline_self_correction import (
    apply_inline_self_correction,
    load_inline_self_correction_markers,
)
from nlp.regional_dialect_normalize import (
    apply_regional_dialect_normalize,
    load_dialect_no_rewrite_canonicals,
    RegionalDialectRewrite,
)

# ---------------------------------------------------------------------------
# Step 5 -- punctuation normalization
# ---------------------------------------------------------------------------
# Codepoint -> replacement-string table for str.translate().
# Values are strings (Python str.translate supports str values).
_PUNCT_TABLE: dict[int, str] = {
    ord("\u201C"): '"',    # LEFT DOUBLE QUOTATION MARK  -> straight "
    ord("\u201D"): '"',    # RIGHT DOUBLE QUOTATION MARK -> straight "
    ord("\u201E"): '"',    # DOUBLE LOW-9 QUOTATION MARK -> straight "
    ord("\u2018"): "'",    # LEFT SINGLE QUOTATION MARK  -> straight apostrophe
    ord("\u2019"): "'",    # RIGHT SINGLE QUOTATION MARK -> straight apostrophe
    ord("\u02BC"): "'",    # MODIFIER LETTER APOSTROPHE  -> straight apostrophe (§10.22.2)
    ord("\u0060"): "'",    # GRAVE ACCENT                -> straight apostrophe (§10.22.2)
    ord("\u00B4"): "'",    # ACUTE ACCENT                -> straight apostrophe (§10.22.2)
    ord("\u201A"): ",",    # SINGLE LOW-9 QUOTATION MARK -> comma
    ord("\u2014"): " - ",  # EM DASH  -> hyphen-space-hyphen
    ord("\u2013"): " - ",  # EN DASH  -> hyphen-space-hyphen
    ord("\u2026"): "...",  # HORIZONTAL ELLIPSIS -> three dots
    ord("\u00AD"): "",     # SOFT HYPHEN -> drop entirely
    ord("\u00B7"): ".",    # MIDDLE DOT -> period
}

# Collapse multiple consecutive spaces produced after em/en-dash expansion.
_MULTI_SPACE_RE = re.compile(r" {2,}")

# ---------------------------------------------------------------------------
# Zero-copy guarantee helpers (Phase 10 §10.34.2)
# ---------------------------------------------------------------------------
def _has_punct_to_normalize(text: str) -> bool:
    """Return True if text contains characters that _PUNCT_TABLE would change.
    
    Per §10.34.2, normalize passes must return the same string object
    when no transformation is needed (zero-copy guarantee).
    This predicate checks if punctuation normalization would make changes.
    """
    for ch in text:
        if ord(ch) in _PUNCT_TABLE:
            return True
    return False


def _has_unicode_spaces(text: str) -> bool:
    """Return True if text contains Unicode space characters OTHER than ASCII space.
    
    Per §10.34.2, used to optimize _collapse_unicode_spaces to avoid
    unnecessary allocation on clean input. ASCII space (U+0020) doesn't need
    conversion, only other Unicode Zs/Zl/Zp categories.
    """
    for ch in text:
        # Skip ASCII space (U+0020) - it's already normalized
        if ch == ' ':
            continue
        # Check for other Unicode space separators
        if unicodedata.category(ch) in ('Zs', 'Zl', 'Zp'):
            return True
    return False


def _has_multi_spaces(text: str) -> bool:
    """Return True if text contains multiple consecutive spaces.
    
    Per §10.34.2, used to optimize regex.sub() to avoid unnecessary
    allocation on clean input.
    """
    return "  " in text


# ---------------------------------------------------------------------------
# Step 5a -- Unicode space collapse (Phase 10 §10.33.3)
# ---------------------------------------------------------------------------
# Collapse every Unicode Zs category to ASCII space before tokenization.
# This prevents invisible whitespace from silently joining tokens.
def _collapse_unicode_spaces(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    # Zero-copy guarantee (§10.34.2): if no change needed, return same object
    if not _has_unicode_spaces(text):
        return text
    return "".join(
        " " if unicodedata.category(ch) == "Zs" else ch for ch in text
    )


def detect_all_caps(text: str, cfg=None) -> bool:
    """Return True when uppercase letters dominate a valid Turkish query."""
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 4:
        return False

    tokens = text.split()
    long_token_letters = [
        ch
        for token in tokens
        if sum(1 for ch in token if ch.isalpha()) >= 4
        for ch in token
        if ch.isalpha()
    ]
    relevant_letters = long_token_letters if long_token_letters else letters
    uppercase_letters = sum(1 for ch in relevant_letters if ch.isupper())
    return uppercase_letters / float(len(relevant_letters)) >= float(
        getattr(cfg, "nlp_all_caps_threshold", 0.85)
    )


def _load_single_emoji_intent_lookup() -> dict[str, str]:
    global _SINGLE_EMOJI_INTENT_LOOKUP
    if _SINGLE_EMOJI_INTENT_LOOKUP is None:
        try:
            raw = yaml.safe_load(_SINGLE_EMOJI_INTENT_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            _SINGLE_EMOJI_INTENT_LOOKUP = {}
            return _SINGLE_EMOJI_INTENT_LOOKUP
        if not isinstance(raw, dict):
            raise ValueError("single_emoji_intent.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for emoji, prompt in raw.items():
            if not isinstance(emoji, str) or not isinstance(prompt, str):
                raise ValueError("single_emoji_intent.tr.yaml entries must map strings to strings")
            lookup[emoji.strip()] = prompt.strip()
        _SINGLE_EMOJI_INTENT_LOOKUP = lookup
    assert _SINGLE_EMOJI_INTENT_LOOKUP is not None
    return _SINGLE_EMOJI_INTENT_LOOKUP


def _build_partial_input_completions(text: str, cfg) -> list[str]:
    if not getattr(cfg, "nlp_partial_input_min_token_len", 3):
        return []
    token = str(text or "").strip()
    if not token or " " in token:
        return []
    if len(token) < int(cfg.nlp_partial_input_min_token_len):
        return []

    normalized_token = lowercase_tr(token)
    locale_data = load_locale("tr-TR")
    candidates = [name for name in build_team_names(locale_data) if lowercase_tr(name).startswith(normalized_token)]
    if not candidates:
        return []

    if any(lowercase_tr(candidate) == normalized_token for candidate in candidates):
        return []

    max_completions = int(getattr(cfg, "nlp_partial_input_max_completions", 3))
    return candidates[:max_completions]


def assert_minimum_signal(text: str, cfg=None) -> tuple[str, str | None, list[str] | None]:
    """Inspect sanitized text and return a floor kind or OK signal.

    This helper is a minimal runtime gate for the NLP intent floor path.
    """
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg

    normalized = str(text or "").strip()
    if not normalized:
        return "empty_input_floor_response", None, None

    if _URL_RE.fullmatch(normalized):
        return "meta.url_only_input", None, None

    if _looks_like_fragment(normalized, cfg=cfg):
        return "meta.unsupported_fragment", None, None

    emoji_lookup = _load_single_emoji_intent_lookup()
    if getattr(cfg, "nlp_single_emoji_intent_enabled", True) and normalized in emoji_lookup:
        return "meta.single_emoji_intent", None, [emoji_lookup[normalized]]

    partial_completions = _build_partial_input_completions(normalized, cfg)
    if partial_completions:
        return "meta.likely_partial_input", None, partial_completions

    letter_count = sum(1 for ch in normalized if ch.isalpha())
    if letter_count < 2:
        return "meta.unsupported_too_short", None, None

    return "ok", None, None


_FRAGMENT_FRAGMENT_RE = re.compile(r"(?:\b(?:ya da|veya|ve|ile|kadar|gibi|ama|fakat|için)\s*|[:;])$", re.IGNORECASE)


def _looks_like_fragment(text: str, cfg=None) -> bool:
    """Return True when the text looks like an incomplete Turkish query.

    This is a lightweight floor detector for trailing fragment markers and
    common connective terms that indicate the user may have sent an incomplete
    query. It is intentionally conservative to avoid false positives.
    """
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg

    if not getattr(cfg, "nlp_fragment_detection_enabled", True):
        return False

    normalized = str(text or "").strip()
    if not normalized:
        return False

    return bool(_FRAGMENT_FRAGMENT_RE.search(normalized))

_SOCIAL_HANDLES_PATH = Path(__file__).resolve().parent / "lang_tr" / "social_handles.tr.yaml"
_COPY_PASTE_CITATION_TAILS_PATH = Path(__file__).resolve().parent / "lang_tr" / "copy_paste" / "citation_tails.tr.yaml"
_CITATION_TAIL_REGEXES: list[re.Pattern[str]] | None = None
_SOCIAL_HANDLES: dict[str, str] | None = None
_ABBREVIATION_KEYS: set[str] | None = None
_URL_RE = re.compile(
    r"((?:https?://|ftp://|www\.)[^\s,;!?\)\]]+)", re.IGNORECASE | re.UNICODE
)
_HASHTAG_RE = re.compile(r"#([^\s]+)")
_MENTION_RE = re.compile(r"@([^\s]+)")
_ALL_PUNCT_RE = re.compile(r"[^\w\d]+", re.UNICODE)

_GREETINGS_PATH = Path(__file__).resolve().parent / "lang_tr" / "greetings.tr.yaml"
_GREETINGS: set[str] | None = None

_FRAGMENT_NEGATIVE_CORPUS_PATH = Path(__file__).resolve().parent / "lang_tr" / "fragments" / "fragment_negative_corpus.tr.json"
_TRAILING_CONJUNCTIONS_PATH = Path(__file__).resolve().parent / "lang_tr" / "fragments" / "trailing_conjunctions.tr.yaml"
_TRAILING_POSTPOSITIONS_PATH = Path(__file__).resolve().parent / "lang_tr" / "fragments" / "trailing_postpositions.tr.yaml"
_PREAMBLE_STRIPPERS_PATH = Path(__file__).resolve().parent / "lang_tr" / "preamble_strippers.tr.yaml"
_FRAGMENT_NEGATIVE_CORPUS: set[str] | None = None
_TRAILING_CONJUNCTIONS: set[str] | None = None
_TRAILING_POSTPOSITIONS: set[str] | None = None
_PREAMBLE_STRIPPERS: tuple[tuple[str, ...], ...] | None = None

_EMOJI_HINTS_PATH = Path(__file__).resolve().parent / "lang_tr" / "emoji_hints.tr.yaml"
_EMOJI_HINTS_TABLE: dict[str, dict[str, object]] | None = None
_EMOJI_HINTS_RE: re.Pattern[str] | None = None


def _load_emoji_hints_table() -> dict[str, dict[str, object]]:
    global _EMOJI_HINTS_TABLE
    if _EMOJI_HINTS_TABLE is None:
        raw = yaml.safe_load(_EMOJI_HINTS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("emoji_hints.tr.yaml must contain a mapping")
        lookup: dict[str, dict[str, object]] = {}
        for emoji, hint_payload in raw.items():
            if not isinstance(emoji, str) or not isinstance(hint_payload, dict):
                raise ValueError("emoji_hints.tr.yaml entries must map emoji to mappings")
            lookup[emoji] = {k: v for k, v in hint_payload.items()}
        _EMOJI_HINTS_TABLE = lookup
    assert _EMOJI_HINTS_TABLE is not None
    return _EMOJI_HINTS_TABLE


def _build_emoji_hints_re(lookup: dict[str, dict[str, object]]) -> re.Pattern[str]:
    global _EMOJI_HINTS_RE
    if _EMOJI_HINTS_RE is not None:
        return _EMOJI_HINTS_RE

    if not lookup:
        raise ValueError("emoji_hints lookup must not be empty")

    sorted_keys = sorted(lookup.keys(), key=len, reverse=True)
    alternatives = "|".join(re.escape(key) for key in sorted_keys)
    _EMOJI_HINTS_RE = re.compile(rf"(?P<emoji>{alternatives})")
    return _EMOJI_HINTS_RE


def _load_copy_paste_citation_tail_patterns() -> list[str]:
    raw = yaml.safe_load(_COPY_PASTE_CITATION_TAILS_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return []
    patterns = raw.get("patterns", [])
    if not isinstance(patterns, list):
        return []
    normalized_patterns: list[str] = []
    for pattern in patterns:
        if isinstance(pattern, str) and pattern.strip():
            normalized_patterns.append(pattern.strip().lower())
    return normalized_patterns


def _compile_citation_tail_regexes() -> list[re.Pattern[str]]:
    global _CITATION_TAIL_REGEXES
    if _CITATION_TAIL_REGEXES is None:
        regexes: list[re.Pattern[str]] = []
        for pattern in _load_copy_paste_citation_tail_patterns():
            if pattern.endswith(" x]"):
                prefix = re.escape(pattern[:-3])
                regexes.append(re.compile(prefix + r'[^\\]]+\]\s*$', re.IGNORECASE))
            elif pattern.endswith(" x)"):
                prefix = re.escape(pattern[:-3])
                regexes.append(re.compile(prefix + r'[^\)]+\)\s*$', re.IGNORECASE))
            elif pattern.endswith(": x"):
                prefix = re.escape(pattern[:-3])
                regexes.append(re.compile(prefix + r"\s*.+\s*$", re.IGNORECASE))
            else:
                regexes.append(re.compile(re.escape(pattern) + r"\s*$", re.IGNORECASE))
        _CITATION_TAIL_REGEXES = regexes
    return _CITATION_TAIL_REGEXES


def _strip_copy_paste_citation_tail(text: str) -> tuple[str, str | None]:
    for regex in _compile_citation_tail_regexes():
        m = regex.search(text)
        if m:
            stripped_tail = text[m.start():].rstrip()
            stripped_text = text[: m.start()].rstrip()
            return stripped_text, stripped_tail
    return text, None


def _load_social_handles() -> dict[str, str]:
    global _SOCIAL_HANDLES
    if _SOCIAL_HANDLES is None:
        raw = yaml.safe_load(_SOCIAL_HANDLES_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("social_handles.tr.yaml must be a mapping")
        handles: dict[str, str] = {}
        for handle, canonical in raw.items():
            if isinstance(handle, str) and handle.startswith("_"):
                continue
            if not isinstance(handle, str) or not isinstance(canonical, str):
                raise ValueError("social_handles.tr.yaml entries must be string -> string")
            handles[handle.strip().lower()] = canonical.strip().lower()
        _SOCIAL_HANDLES = handles
    assert _SOCIAL_HANDLES is not None
    return _SOCIAL_HANDLES


def _load_abbreviation_keys() -> set[str]:
    global _ABBREVIATION_KEYS
    if _ABBREVIATION_KEYS is None:
        raw = load_abbreviations()
        if not isinstance(raw, dict):
            raise ValueError("abbreviations.tr.yaml must be a mapping")
        entries = raw.get("abbreviations", [])
        if not isinstance(entries, list):
            raise ValueError("abbreviations.tr.yaml missing abbreviations list")
        keys: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            abbreviation = entry.get("abbreviation")
            if isinstance(abbreviation, str):
                keys.add(abbreviation.lower())
            for alias in entry.get("aliases", []):
                if isinstance(alias, str):
                    keys.add(alias.replace(".", "").replace(" ", "").lower())
        _ABBREVIATION_KEYS = keys
    assert _ABBREVIATION_KEYS is not None
    return _ABBREVIATION_KEYS


def _load_fragment_strings(path: Path, description: str) -> set[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError(f"{description} must contain a list")
    entries: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise ValueError(f"{description} entries must be strings")
        normalized = _MULTI_SPACE_RE.sub(" ", canonical_normalize(entry).strip().lower())
        if normalized:
            entries.add(normalized)
    return entries


def _load_fragment_negative_corpus() -> set[str]:
    global _FRAGMENT_NEGATIVE_CORPUS
    if _FRAGMENT_NEGATIVE_CORPUS is None:
        raw = json.loads(_FRAGMENT_NEGATIVE_CORPUS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("fragment_negative_corpus.tr.json must contain a JSON list")
        entries: set[str] = set()
        for entry in raw:
            if not isinstance(entry, str):
                raise ValueError("fragment_negative_corpus.tr.json entries must be strings")
            normalized = _MULTI_SPACE_RE.sub(" ", canonical_normalize(entry).strip().lower())
            if normalized:
                entries.add(normalized)
        _FRAGMENT_NEGATIVE_CORPUS = entries
    assert _FRAGMENT_NEGATIVE_CORPUS is not None
    return _FRAGMENT_NEGATIVE_CORPUS


def _load_trailing_conjunctions() -> set[str]:
    global _TRAILING_CONJUNCTIONS
    if _TRAILING_CONJUNCTIONS is None:
        _TRAILING_CONJUNCTIONS = _load_fragment_strings(
            _TRAILING_CONJUNCTIONS_PATH,
            "trailing_conjunctions.tr.yaml",
        )
    assert _TRAILING_CONJUNCTIONS is not None
    return _TRAILING_CONJUNCTIONS


def _load_trailing_postpositions() -> set[str]:
    global _TRAILING_POSTPOSITIONS
    if _TRAILING_POSTPOSITIONS is None:
        _TRAILING_POSTPOSITIONS = _load_fragment_strings(
            _TRAILING_POSTPOSITIONS_PATH,
            "trailing_postpositions.tr.yaml",
        )
    assert _TRAILING_POSTPOSITIONS is not None
    return _TRAILING_POSTPOSITIONS


def _load_preamble_strippers() -> tuple[tuple[str, ...], ...]:
    global _PREAMBLE_STRIPPERS
    if _PREAMBLE_STRIPPERS is None:
        raw = yaml.safe_load(_PREAMBLE_STRIPPERS_PATH.read_text(encoding="utf-8")) or []
        if not isinstance(raw, list):
            raise ValueError("preamble_strippers.tr.yaml must contain a list")
        entries: list[tuple[str, ...]] = []
        for entry in raw:
            if not isinstance(entry, str):
                raise ValueError("preamble_strippers.tr.yaml entries must be strings")
            normalized = _MULTI_SPACE_RE.sub(" ", canonical_normalize(entry).strip().lower())
            tokens = tuple(_tokenize(normalized))
            if not tokens:
                continue
            if len(tokens) > 3:
                raise ValueError("preamble_strippers.tr.yaml entries must be at most 3 tokens")
            entries.append(tokens)

            ascii_variant = unicodedata.normalize("NFD", entry)
            ascii_variant = "".join(
                ch for ch in ascii_variant if unicodedata.category(ch) != "Mn"
            )
            ascii_variant = _MULTI_SPACE_RE.sub(" ", ascii_variant.strip().lower())
            if ascii_variant and ascii_variant != normalized:
                ascii_tokens = tuple(_tokenize(ascii_variant))
                if ascii_tokens and ascii_tokens not in entries:
                    entries.append(ascii_tokens)
        entries.sort(key=len, reverse=True)
        _PREAMBLE_STRIPPERS = tuple(entries)
    assert _PREAMBLE_STRIPPERS is not None
    return _PREAMBLE_STRIPPERS


def _strip_preamble(
    text: str,
    cfg,
    event_sink: Callable[[dict[str, object]], None],
    *,
    original_text: str,
) -> str:
    tokens = list(_tokenize(text))
    if not tokens:
        return text

    for pattern in _load_preamble_strippers():
        if tokens[: len(pattern)] != list(pattern):
            continue

        if len(pattern) > getattr(cfg, "nlp_preamble_max_strip_tokens", 2):
            event_sink({
                "kind": "preamble_strip_capped",
                "strip_tokens": len(pattern),
                "max_tokens": getattr(cfg, "nlp_preamble_max_strip_tokens", 2),
                "original_text": original_text,
            })
            return text

        remaining = tokens[len(pattern) :]
        if not remaining:
            return text

        event_sink({
            "kind": "preamble_stripped",
            "stripped_tokens": len(pattern),
            "original_text": original_text,
        })
        return " ".join(remaining)

    return text


_PREDICTIVE_OVERSHOOT_PATH = Path(__file__).resolve().parent / "lang_tr" / "predictive_text_known_overshoot.tr.yaml"
_PREDICTIVE_OVERSHOOT_LOOKUP: dict[str, str] | None = None
_OCR_CONFUSABLES_PATH = Path(__file__).resolve().parent / "lang_tr" / "ocr_confusables.tr.yaml"
_OCR_CONFUSABLES_LOOKUP: dict[str, str] | None = None
_OCR_LIGATURES: frozenset[str] = frozenset({"ﬀ", "ﬁ", "ﬂ", "ﬃ", "ﬄ", "ﬅ", "ﬆ"})
_SINGLE_EMOJI_INTENT_PATH = Path(__file__).resolve().parent / "lang_tr" / "single_emoji_intent.tr.yaml"
_SINGLE_EMOJI_INTENT_LOOKUP: dict[str, str] | None = None
_EMOJI_TO_CONCEPT_PATH = Path(__file__).resolve().parent / "lang_tr" / "emoji_to_concept.tr.yaml"
_EMOJI_TO_CONCEPT_LOOKUP: dict[str, str] | None = None
_EMOJI_TO_CONCEPT_RE: re.Pattern[str] | None = None
_TIME_OF_DAY_SHORTHAND_PATH = Path(__file__).resolve().parent / "lang_tr" / "time_of_day_shorthand.tr.yaml"
_TIME_OF_DAY_SHORTHAND_LOOKUP: dict[str, str] | None = None
_NUMERIC_REDUNDANT_RESTATEMENT_PATH = Path(__file__).resolve().parent / "lang_tr" / "numeric_redundant_restatement.tr.yaml"
_NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP: dict[str, str] | None = None
_PASTE_LAYOUT_LINE_BREAK_RE = re.compile(r"[\u2028\u2029\u000C]")
_PASTE_HYPHEN_BREAK_RE = re.compile(r"([^\s\-\n\r]+)-\r?\n\s*([^\s\-\n\r]+)")
_FOOTBALL_SURFACE_FORMS: set[str] | None = None


def _normalize_paste_layout(
    text: str,
    cfg,
    event_sink: Callable[[dict[str, object]], None],
    *,
    pre_canonical: str,
) -> tuple[str, str | None]:
    """Normalize messy pasted text and detect column-tear failures."""
    floor_kind: str | None = None
    normalized = text

    if _PASTE_HYPHEN_BREAK_RE.search(normalized):
        normalized = _PASTE_HYPHEN_BREAK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}", normalized)
        event_sink({"kind": "paste_layout_normalized"})

    if _PASTE_LAYOUT_LINE_BREAK_RE.search(normalized):
        normalized = _PASTE_LAYOUT_LINE_BREAK_RE.sub(" ", normalized)
        event_sink({"kind": "paste_layout_normalized"})

    lines = [line for line in normalized.split("\n") if line.strip()]
    if len(lines) >= 3 and all(len(_tokenize(line)) <= 3 for line in lines):
        floor_kind = "meta.multi_input_clarification_required"
        event_sink({"kind": "column_tear_detected", "line_count": len(lines)})

    return normalized, floor_kind


def _normalize_ocr_confusions(
    text: str,
    pre_canonical: str,
    cfg,
    event_sink: Callable[[dict[str, object]], None],
) -> str:
    """Stub for OCR-confusion repair when the full feature is not yet implemented."""
    return text


def _is_title_case_token(token: str) -> bool:
    letters = [ch for ch in token if ch.isalpha()]
    if len(letters) < 2:
        return False
    if not letters[0].isupper():
        return False
    return all(ch.islower() for ch in letters[1:])


def _token_random_case_flip_ratio(token: str) -> float:
    letters = [ch for ch in token if ch.isalpha()]
    if len(letters) < 4:
        return 0.0
    flips = sum(
        1
        for previous, current in zip(letters, letters[1:])
        if previous.isupper() != current.isupper()
    )
    return float(flips) / float(len(letters))


def _normalize_random_case_noise(
    text: str,
    cfg,
    event_sink: Callable[[dict[str, object]], None],
) -> str:
    """Detect and fold random-case token noise before lowercase conversion."""
    threshold = float(getattr(cfg, "nlp_random_case_threshold", 0.30))
    if threshold <= 0.0:
        return text

    parts = re.split(r"(\s+)", text)
    normalized_parts: list[str] = []
    for part in parts:
        if part and not part.isspace():
            if _token_random_case_flip_ratio(part) > threshold and not _is_title_case_token(part):
                folded = lowercase_tr(part)
                if folded != part:
                    event_sink({
                        "kind": "random_case_normalized",
                        "original_token": part,
                        "normalized_token": folded,
                    })
                    part = folded
        normalized_parts.append(part)

    return "".join(normalized_parts)


def _normalize_social_tokens(
    text: str,
    event_sink: list[dict[str, object]],
    cfg,
) -> str:
    """Stub for social token normalization when the full feature is not yet implemented."""
    return text


def _normalize_numeric_redundant_restatement(
    tokens: list[str],
    cfg,
    event_sink: Callable[[dict[str, object]], None],
) -> list[str]:
    """Collapse digit + number-word redundant restatements into digit-only tokens."""
    if not getattr(cfg, "nlp_numeric_redundant_restatement_enabled", False):
        return tokens

    word_to_digit = _load_numeric_redundant_restatement_lookup()
    if not word_to_digit:
        return tokens

    normalized_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if re.fullmatch(r"\d+(?:-\d+)*", token):
            digit_parts = token.split("-")
            candidate_slice = tokens[index + 1 : index + 1 + len(digit_parts)]
            if len(candidate_slice) == len(digit_parts):
                if all(word_to_digit.get(word) == digit for word, digit in zip(candidate_slice, digit_parts)):
                    event_sink({
                        "kind": "numeric_redundant_collapsed",
                        "token": token,
                        "restatement": " ".join(candidate_slice),
                        "collapsed_count": len(candidate_slice),
                    })
                    normalized_tokens.append(token)
                    index += 1 + len(digit_parts)
                    continue
        normalized_tokens.append(token)
        index += 1

    return normalized_tokens


def _load_predictive_overshoot_lookup() -> dict[str, str]:
    global _PREDICTIVE_OVERSHOOT_LOOKUP
    if _PREDICTIVE_OVERSHOOT_LOOKUP is None:
        raw = yaml.safe_load(_PREDICTIVE_OVERSHOOT_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("predictive_text_known_overshoot.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for source, target in raw.items():
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValueError("predictive_text_known_overshoot.tr.yaml entries must map strings to strings")
            normalized_source = _MULTI_SPACE_RE.sub(" ", canonical_normalize(source).strip().lower())
            normalized_target = _MULTI_SPACE_RE.sub(" ", canonical_normalize(target).strip().lower())
            if normalized_source == normalized_target:
                raise ValueError("predictive_text_known_overshoot.tr.yaml source and target must differ")
            if normalized_source in lookup and lookup[normalized_source] != normalized_target:
                raise ValueError(f"predictive_text_known_overshoot.tr.yaml contains duplicate source {normalized_source!r}")
            lookup[normalized_source] = normalized_target
        _PREDICTIVE_OVERSHOOT_LOOKUP = lookup
    assert _PREDICTIVE_OVERSHOOT_LOOKUP is not None
    return _PREDICTIVE_OVERSHOOT_LOOKUP


def _load_ocr_confusables_lookup() -> dict[str, str]:
    global _OCR_CONFUSABLES_LOOKUP
    if _OCR_CONFUSABLES_LOOKUP is None:
        raw = yaml.safe_load(_OCR_CONFUSABLES_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("ocr_confusables.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for source, target in raw.items():
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValueError("ocr_confusables.tr.yaml entries must map strings to strings")
            source = source.strip()
            target = target.strip()
            if not source:
                raise ValueError("ocr_confusables.tr.yaml entries must not be empty")
            if source in lookup and lookup[source] != target:
                raise ValueError(f"ocr_confusables.tr.yaml contains duplicate source {source!r}")
            lookup[source] = target
        _OCR_CONFUSABLES_LOOKUP = lookup
    assert _OCR_CONFUSABLES_LOOKUP is not None
    return _OCR_CONFUSABLES_LOOKUP


def _load_single_emoji_intent_lookup() -> dict[str, str]:
    global _SINGLE_EMOJI_INTENT_LOOKUP
    if _SINGLE_EMOJI_INTENT_LOOKUP is None:
        try:
            raw = yaml.safe_load(_SINGLE_EMOJI_INTENT_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            _SINGLE_EMOJI_INTENT_LOOKUP = {}
            return _SINGLE_EMOJI_INTENT_LOOKUP
        if not isinstance(raw, dict):
            raise ValueError("single_emoji_intent.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for emoji, prompt in raw.items():
            if not isinstance(emoji, str) or not isinstance(prompt, str):
                raise ValueError("single_emoji_intent.tr.yaml entries must map strings to strings")
            lookup[emoji] = prompt.strip()
        _SINGLE_EMOJI_INTENT_LOOKUP = lookup
    assert _SINGLE_EMOJI_INTENT_LOOKUP is not None
    return _SINGLE_EMOJI_INTENT_LOOKUP


def _load_emoji_to_concept_lookup() -> dict[str, str]:
    global _EMOJI_TO_CONCEPT_LOOKUP
    if _EMOJI_TO_CONCEPT_LOOKUP is None:
        try:
            raw = yaml.safe_load(_EMOJI_TO_CONCEPT_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            _EMOJI_TO_CONCEPT_LOOKUP = {}
            return _EMOJI_TO_CONCEPT_LOOKUP
        if not isinstance(raw, dict):
            raise ValueError("emoji_to_concept.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for emoji, concept in raw.items():
            if not isinstance(emoji, str) or not isinstance(concept, str):
                raise ValueError("emoji_to_concept.tr.yaml entries must map strings to strings")
            lookup[emoji] = concept.strip().lower()
        _EMOJI_TO_CONCEPT_LOOKUP = lookup
    assert _EMOJI_TO_CONCEPT_LOOKUP is not None
    return _EMOJI_TO_CONCEPT_LOOKUP


def _load_time_of_day_shorthand_lookup() -> dict[str, str]:
    global _TIME_OF_DAY_SHORTHAND_LOOKUP
    if _TIME_OF_DAY_SHORTHAND_LOOKUP is None:
        raw = yaml.safe_load(_TIME_OF_DAY_SHORTHAND_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("time_of_day_shorthand.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for shorthand, expanded in raw.items():
            if not isinstance(shorthand, str) or not isinstance(expanded, str):
                raise ValueError("time_of_day_shorthand.tr.yaml entries must map strings to strings")
            lookup[shorthand.strip().lower()] = expanded.strip().lower()
        _TIME_OF_DAY_SHORTHAND_LOOKUP = lookup
    assert _TIME_OF_DAY_SHORTHAND_LOOKUP is not None
    return _TIME_OF_DAY_SHORTHAND_LOOKUP


def _load_numeric_redundant_restatement_lookup() -> dict[str, str]:
    global _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP
    if _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP is None:
        try:
            raw = yaml.safe_load(_NUMERIC_REDUNDANT_RESTATEMENT_PATH.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP = {}
            return _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP
        if not isinstance(raw, dict):
            raise ValueError("numeric_redundant_restatement.tr.yaml must contain a mapping")
        lookup: dict[str, str] = {}
        for word, digit in raw.items():
            if not isinstance(word, str) or not isinstance(digit, str):
                raise ValueError("numeric_redundant_restatement.tr.yaml entries must map strings to strings")
            word_key = word.strip().lower()
            digit_value = digit.strip()
            if word_key in lookup and lookup[word_key] != digit_value:
                raise ValueError(f"numeric_redundant_restatement.tr.yaml contains duplicate word {word_key!r}")
            lookup[word_key] = digit_value
        _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP = lookup
    assert _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP is not None
    return _NUMERIC_REDUNDANT_RESTATEMENT_LOOKUP


def _extract_last_paragraph(text: str) -> tuple[str, str] | None:
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if len(lines) < 3:
        return None
    last_paragraph = lines[-1].strip()
    if not last_paragraph:
        return None
    preceding_text = text[: text.rfind(last_paragraph)]
    preceding_text = preceding_text.rstrip("\r\n")
    return last_paragraph, preceding_text


def _build_emoji_to_concept_re(lookup: dict[str, str]) -> re.Pattern[str]:
    global _EMOJI_TO_CONCEPT_RE
    if _EMOJI_TO_CONCEPT_RE is not None:
        return _EMOJI_TO_CONCEPT_RE

    if not lookup:
        raise ValueError("emoji_to_concept lookup must not be empty")

    sorted_keys = sorted(lookup.keys(), key=len, reverse=True)
    alternatives = "|".join(re.escape(key) for key in sorted_keys)
    _EMOJI_TO_CONCEPT_RE = re.compile(
        rf"(?P<emoji>{alternatives})(?P<apostrophe>['’]?)(?P<suffix>[A-Za-zÇĞİÖŞÜçğıöşü]+)"
    )
    return _EMOJI_TO_CONCEPT_RE


def _promote_suffixed_emoji_to_concept(
    text: str,
    cfg,
    event_sink: Callable[[dict[str, object]], None],
) -> str:
    if not getattr(cfg, "nlp_emoji_to_concept_enabled", True):
        return text

    lookup = _load_emoji_to_concept_lookup()
    if not lookup:
        return text

    pattern = _build_emoji_to_concept_re(lookup)
    events: list[dict[str, object]] = []

    def replace(match: re.Match[str]) -> str:
        emoji = match.group("emoji")
        apostrophe = match.group("apostrophe") or ""
        suffix = match.group("suffix")
        canonical = lookup.get(emoji)
        if canonical is None:
            return match.group(0)

        events.append(
            {
                "kind": "concept_via_emoji",
                "original_emoji": emoji,
                "canonical": canonical,
                "suffix": suffix,
            }
        )
        return f"{canonical}{apostrophe}{suffix}"

    normalized = pattern.sub(replace, text)
    for event in events:
        event_sink(event)
    return normalized


def _extract_emoji_hints(text: str, event_sink: list[dict[str, object]]) -> tuple[tuple[dict[str, object], ...], str]:
    lookup = _load_emoji_hints_table()
    if not lookup:
        return (), text

    pattern = _build_emoji_hints_re(lookup)
    extracted: list[dict[str, object]] = []

    def replace(match: re.Match[str]) -> str:
        emoji = match.group("emoji")
        payload = lookup.get(emoji)
        if payload is None:
            return ""
        if payload.get("hint") == "generic_decoration":
            return ""
        hint = {"emoji": emoji, **payload}
        extracted.append(hint)
        return ""

    normalized = pattern.sub(replace, text)
    if extracted:
        event_sink.append({"kind": "emoji_hints_extracted", "count": len(extracted), "emojis": [hint["emoji"] for hint in extracted]})
    return tuple(extracted), normalized


def _strip_generic_emoji_symbols(text: str, event_sink: list[dict[str, object]]) -> str:
    stripped_chars: list[str] = []
    stripped_count = 0
    for ch in text:
        if unicodedata.category(ch) in {"So", "Sk"}:
            stripped_count += 1
            continue
        stripped_chars.append(ch)
    normalized = "".join(stripped_chars)
    if stripped_count:
        event_sink.append({"kind": "emoji_stripped", "count": stripped_count})
    return normalized

# ---------------------------------------------------------------------------
# Step 3.4a -- lingering combining-mark strip (Phase 10 §10.24.4)
# ---------------------------------------------------------------------------
_COMBINING_MARK_START = 0x0300
_COMBINING_MARK_END = 0x036F
_MAX_COMBINING_MARKS_PER_TOKEN = 4

def _strip_turkish_combining_marks(token: str) -> tuple[str, int]:
    if not any(_COMBINING_MARK_START <= ord(ch) <= _COMBINING_MARK_END for ch in token):
        return token, 0

    stripped_chars: list[str] = []
    removed = 0
    for ch in token:
        if _COMBINING_MARK_START <= ord(ch) <= _COMBINING_MARK_END:
            removed += 1
            continue
        stripped_chars.append(ch)

    return "".join(stripped_chars), removed


def _annotate_numeric_context(tokens: list[str], event_sink: list[dict[str, object]]) -> None:
    for idx, token in enumerate(tokens):
        left = tokens[max(0, idx - 2) : idx]
        right = tokens[idx + 1 : idx + 3]
        choice, parse = choose_numeric_parse(token, left, right)
        if choice == "market_decimal":
            event_sink.append({
                "kind": "numeric_context_preferred",
                "choice": "market_decimal",
                "token": token,
                "left_context": left,
                "right_context": right,
            })
        elif choice == "score_line":
            event_sink.append({
                "kind": "numeric_context_preferred",
                "choice": "score_line",
                "token": token,
                "left_context": left,
                "right_context": right,
            })
        elif choice == "thousands_decimal":
            event_sink.append({
                "kind": "numeric_context_preferred",
                "choice": "thousands_decimal",
                "token": token,
                "left_context": left,
                "right_context": right,
            })
        elif choice == "apostrophe_numeric":
            event_sink.append({
                "kind": "numeric_apostrophe_suffix",
                "token": token,
                "parse": parse,
                "left_context": left,
                "right_context": right,
            })
        elif choice == "ambiguous_decimal":
            event_sink.append({
                "kind": "numeric_disambiguation_offer",
                "token": token,
                "reason": "bare_decimal_no_context",
            })

# ---------------------------------------------------------------------------
# Step 7 -- tokenization
# ---------------------------------------------------------------------------
# Split on sequences of whitespace + common punctuation boundaries.
# Apostrophes inside tokens are preserved (e.g. Turkish suffix "yarin'ki").
# Preserve apostrophes inside tokens (e.g. Turkish suffix "yarin'ki").
# Preserve comma/dot/colon/hyphen only when they are embedded between digits,
# so numeric tokens like "1,5", "2.5", "1-0", and "21:30" remain intact.
_TOKEN_DELIMITERS = set(" \t\n\r\f\v.?!:;()[]/|, -")
_VOICE_QUESTION_PARTICLES = frozenset(("mi", "mı", "mu", "mü"))
_VOICE_SUBQUERY_LOOKAHEAD = 5


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for idx, ch in enumerate(text):
        if ch in _TOKEN_DELIMITERS:
            prev_digit = idx > 0 and text[idx - 1].isdigit()
            next_digit = idx + 1 < len(text) and text[idx + 1].isdigit()
            if ch in ",.:-" and prev_digit:
                # Preserve numeric ordinals and decimal separators.
                if next_digit or idx + 1 == len(text) or text[idx + 1] in _TOKEN_DELIMITERS:
                    current.append(ch)
                    continue
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def split_questions(tokens: list[str], *, input_source: str = "keyboard") -> list[list[str]]:
    """Split voice queries into subqueries using relaxed Turkish rules.

    When ``input_source == "voice"``, a detached question-particle token
    followed by at least five remaining tokens triggers a boundary split.
    The keyboard path is intentionally a no-op to preserve existing typed
    input behavior.
    """
    if input_source != "voice":
        return [tokens]
    if not tokens:
        return []

    subqueries: list[list[str]] = []
    current: list[str] = []
    for idx, token in enumerate(tokens):
        current.append(token)
        if token in _VOICE_QUESTION_PARTICLES and len(tokens) - idx - 1 >= 5:
            subqueries.append(current)
            current = []
            continue

        if token == "ve":
            lookahead = tokens[idx + 1 : idx + 1 + _VOICE_SUBQUERY_LOOKAHEAD]
            if any(t in _VOICE_QUESTION_PARTICLES for t in lookahead):
                subqueries.append(current)
                current = []
                continue

    if current:
        subqueries.append(current)
    return subqueries

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class InputTooLongError(ValueError):
    """Raised by step 1 when input exceeds ``cfg.nlp_input_max_codepoints``."""


@dataclass(frozen=True)
class NormalizedInput:
    """Result of the 8-step normalization pipeline.

    Attributes
    ----------
    tokens:
        Ordered tuple of normalized tokens (post all 8 steps).
    steps_run:
        Ordered tuple of step names that were executed.  Consumers use
        this for forensic tracing and to assert ordering in tests.
    original_codepoint_count:
        ``len(raw_text)`` before any transforms.
    typo_budget_exhausted:
        ``True`` when the per-query fuzzy-lookup budget was hit during
        step 8 (§10.3 Per-query budget).  Callers should emit
        ``nlp.event.v1{kind=did_you_mean_offered}`` and return a
        "Did you mean?" response rather than treating the partial
        correction as authoritative.
    budget_exhausted_reason:
        ``cpu_budget_exceeded`` or ``rss_budget_exceeded`` when the
        per-request CPU/RSS guard was breached.
    """

    tokens: tuple[str, ...]
    steps_run: tuple[str, ...]
    original_codepoint_count: int
    subqueries: tuple[tuple[str, ...], ...] = tuple()
    typo_budget_exhausted: bool = False
    morph_ambiguity_budget_exhausted: bool = False
    """True when morphology sees more than ``cfg.nlp_morph_ambiguous_max_per_query``
    high-ambiguity tokens.  The caller may emit ``nlp.event.v1{kind=did_you_mean_offered}``
    and route the request to a fallback path instead of guessing the ambiguous parse.
    """
    stage_timed_out: bool = False
    """True when the normalize+diacritic+typo stage exceeded
    ``cfg.nlp_normalize_stage_timeout_ms``.  The caller is responsible
    for emitting ``nlp.event.v1{kind=normalize_timeout}``.
    """
    budget_exhausted_reason: str | None = None
    """If budget was exceeded, the canonical reason string.

    Values: ``cpu_budget_exceeded`` or ``rss_budget_exceeded``.
    """
    budget_exhausted_stage: str | None = None
    """The last normalization stage completed before budget exhaustion."""
    floor_kind: str | None = None
    """Optional post-normalization floor kind for cases like column-tear
    paste-layout input that should be routed to a meta clarification response."""
    context_dump_sha256: str | None = None
    """SHA256 of the preserved pre-question context for mega-input extractions."""
    particle_repairs: frozenset = frozenset()
    """Set of original token strings split by step 8a (§10.22.4 particle
    disambiguation).  Consumers can use this to detect which tokens were
    reconstructed from attached particles.
    """
    dialect_repairs: frozenset = frozenset()
    """Set of (original_token, rule_id) pairs where a token was rewritten
    by a dialect rule in step 8b (§10.22.5 colloquial normalization).
    """
    regional_dialect_rewrites: tuple[RegionalDialectRewrite, ...] = tuple()
    """Regional dialect rewrites applied before tokenization (§10.32.4)."""
    dialect_alternatives: tuple[tuple[str, str], ...] = tuple()
    """Canonicalized alternatives preserved for audit_only=false rewrites."""
    apostrophe_repairs: tuple[ApostropheRepair, ...] = tuple()
    """Set of normalized apostrophe repairs applied in step 6.7."""
    emoji_hints: tuple[dict[str, object], ...] = tuple()
    """Advisory emoji hints extracted before the classifier sees the text."""
    apostrophe_repair_events: tuple[dict[str, str], ...] = tuple()
    """Audit-friendly event payloads for inferred apostrophe repairs."""
    suffix_harmony_repair_events: tuple[dict[str, str], ...] = tuple()
    """Telemetry-friendly events emitted for harmony-tolerant suffix repairs."""
    consonant_alternation_repairs: tuple[tuple[str, str], ...] = tuple()
    """Set of (original_token, repaired_token) repairs applied in step 8a.1."""
    consonant_alternation_events: tuple[dict[str, str], ...] = tuple()
    """Telemetry-friendly events emitted by consonant alternation repairs."""
    geminate_restoration_events: tuple[dict[str, str], ...] = tuple()
    """Telemetry-friendly events emitted by geminate restoration detection."""
    predictive_overshoot_repairs: tuple[tuple[str, str], ...] = tuple()
    """Set of (original_token, corrected_token) pairs repaired by predictive overshoot."""
    vowel_drop_before_suffix_events: tuple[dict[str, str], ...] = tuple()
    """Telemetry-friendly events emitted by vowel-drop-before-suffix repairs."""
    loanword_singularisation_events: tuple[dict[str, str], ...] = tuple()
    """Telemetry-friendly events emitted by loanword singularisation repairs."""
    inline_self_correction_events: tuple[dict[str, Any], ...] = tuple()
    """Telemetry-friendly events emitted by inline self-correction detection."""
    politeness_class: str = "neutral"
    """Detected politeness marker class after normalizing polite/casual tokens."""
    query_style: str = "natural"
    """Detected query style for the input, e.g. natural, search, quoted_exact_search."""
    intent_modifier: str | tuple[str, ...] = "none"
    """Detected intent modifier such as conditional or comparative."""
    focus_particle_disambiguated: bool = False
    """True when embedded focus particles coexist with a WH token and should bypass question-tag classification."""
    pragmatic_class: str | None = None
    """Optional question-tag pragmatic class: confirmation_seeking or information_seeking."""
    idiom_events: tuple[dict[str, Any], ...] = tuple()
    """Logged idiom expansion/ambiguity events discovered during normalization."""
    normalization_events: tuple[dict[str, Any], ...] = tuple()
    """Special normalization events emitted by early voice/ASR features."""
    stripped_tail: str | None = None
    """Copy/paste citation or source tail stripped during normalization."""
    vocatives_stripped: tuple = ()
    """Tokens removed by the vocative/filler-strip sub-step of step 8b
    (§10.22.5).  The classifier never sees these tokens.
    """
    abbreviations_expanded: frozenset = frozenset()
    """Set of (abbrev_token, expansion_id) pairs where a hard abbreviation
    was expanded in step 8b (§10.22.5).
    """
    soft_abbreviations_tagged: frozenset = frozenset()
    """Set of (abbrev_token, expansion_id, frozenset(co_tokens)) for soft
    abbreviations that need downstream resolution (§10.5 conflict resolver).
    """
    slurs_stripped: tuple[str, ...] = tuple()
    """Tokens stripped from the query as offensive slurs before classifier.
    """
    compound_split_events: tuple[dict[str, object], ...] = tuple()
    """Telemetry-friendly events emitted by the compound splitter in step 7.5."""
    postposition_stack_matches: tuple[PostpositionStackMatch, ...] = tuple()
    """Detected closed postposition stacks in the token stream."""
    postposition_stack_unknowns: tuple[UnknownPostpositionStack, ...] = tuple()
    """Unknown marker stacks that should fall through and emit an event."""
    morphology_candidates: tuple[tuple[MorphCandidate, ...], ...] = tuple()
    """Per-token morphology candidate lists after §10.26.1 top-K normalization."""
    morphology_events: tuple[dict[str, object], ...] = tuple()
    """Emitted morphology ambiguity events for low-confidence parse candidates."""


def _classify_particle_repairs(repaired_originals: frozenset[str]) -> dict[str, int]:
    """Classify repaired particle tokens into the Phase 10 repair buckets."""
    if not repaired_originals:
        return {}

    rules = _load_particle_rules()
    mi_cfg = rules["mi_variants"]
    mi_all: list[str] = list(mi_cfg["all_variants"])
    mi_harmony: dict[str, str] = mi_cfg["four_way_harmony"]
    all_vowels = frozenset(rules["vowel_sets"]["all_vowels"])
    front_vowels = frozenset(rules["vowel_sets"]["front"])
    mi_min_stem = int(mi_cfg["min_stem_length"])

    de_da_cfg = rules["de_da"]
    front_p = de_da_cfg["front_variant"]
    back_p = de_da_cfg["back_variant"]
    de_da_particles = (front_p, back_p)
    de_da_min_stem = int(de_da_cfg["min_stem_length"])

    ki_cfg = rules["ki"]
    ki_particle = ki_cfg["particle"]
    ki_min_stem = int(ki_cfg["min_stem_length"])

    counts = {
        "particle_detached_mi": 0,
        "particle_repaired_de_da": 0,
        "particle_repaired_ki": 0,
    }

    for tok in repaired_originals:
        classified = False
        for variant in mi_all:
            if len(tok) <= len(variant) or not tok.endswith(variant):
                continue
            stem = tok[: -len(variant)]
            if not _is_valid_particle_stem(stem, mi_min_stem, all_vowels):
                continue
            last_v = _particle_last_vowel(stem, all_vowels)
            if last_v is None:
                continue
            harmony_base = variant[:2]
            if mi_harmony.get(last_v) == harmony_base:
                counts["particle_detached_mi"] += 1
                classified = True
                break
        if classified:
            continue

        if len(tok) > 2 and tok[-2:] in de_da_particles:
            stem = tok[:-2]
            if _is_valid_particle_stem(stem, de_da_min_stem, all_vowels):
                last_v = _particle_last_vowel(stem, all_vowels)
                if last_v is not None:
                    expected_p = front_p if last_v in front_vowels else back_p
                    if expected_p == tok[-2:]:
                        counts["particle_repaired_de_da"] += 1
                        classified = True
        if classified:
            continue

        if len(tok) > len(ki_particle) and tok.endswith(ki_particle):
            stem = tok[: -len(ki_particle)]
            if _is_valid_particle_stem(stem, ki_min_stem, all_vowels):
                counts["particle_repaired_ki"] += 1
                continue

    return counts


def _record_nlp_input_repair_metrics(
    result: "NormalizedInput",
    token_count: int,
    confusables_folded: bool,
    ascii_restored: bool,
) -> None:
    from common.telemetry import get_sink

    sink = get_sink()
    if confusables_folded:
        sink.record_nlp_input_repair("confusables_folded")

    if ascii_restored:
        sink.record_nlp_input_repair("ascii_restored")

    if result.particle_repairs:
        counts = _classify_particle_repairs(result.particle_repairs)
        for repair_class, count in counts.items():
            if count:
                sink.record_nlp_input_repair(repair_class, count)

    if result.apostrophe_repairs:
        sink.record_nlp_input_repair("apostrophe_inserted", len(result.apostrophe_repairs))

    if result.suffix_harmony_repair_events:
        sink.record_nlp_input_repair("suffix_harmony_repaired", len(result.suffix_harmony_repair_events))

    if result.vowel_drop_before_suffix_events:
        sink.record_nlp_input_repair("vowel_drop_repaired", len(result.vowel_drop_before_suffix_events))

    if result.loanword_singularisation_events:
        sink.record_nlp_input_repair("loanword_singularised", len(result.loanword_singularisation_events))

    if result.dialect_repairs:
        sink.record_nlp_input_repair("dialect_expanded", len(result.dialect_repairs))

    if result.regional_dialect_rewrites:
        for rewrite in result.regional_dialect_rewrites:
            sink.record_nlp_dialect_normalization(rewrite.dialect_class)

    if result.abbreviations_expanded:
        sink.record_nlp_input_repair("abbreviation_expanded", len(result.abbreviations_expanded))

    if result.vocatives_stripped:
        sink.record_nlp_input_repair("vocative_dropped", len(result.vocatives_stripped))

    if result.slurs_stripped:
        sink.record_nlp_input_repair("slur_stripped", len(result.slurs_stripped))

    total_repairs = sum(
        [
            int(confusables_folded),
            len(result.particle_repairs),
            len(result.apostrophe_repairs),
            len(result.suffix_harmony_repair_events),
            len(result.dialect_repairs),
            len(result.abbreviations_expanded),
            len(result.vocatives_stripped),
            len(result.slurs_stripped),
        ]
    )
    sink.record_nlp_input_repair_density(total_repairs, token_count)
    sink.record_nlp_politeness_class(result.politeness_class)


# ---------------------------------------------------------------------------
# Helper routines
# ---------------------------------------------------------------------------

def _html_entity_unescape(text: str, normalization_events: list[dict[str, object]]) -> str:
    unescaped = html.unescape(text)
    if unescaped != text:
        normalization_events.append({
            "kind": "html_entity_unescaped",
            "original": text,
            "normalized": unescaped,
        })
    return unescaped


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def normalize_input(
    text: str,
    cfg=None,
    *,
    _diacritic_restore: Optional[Callable[[str], str]] = None,
    _typo_correct: "Optional[Callable[[list[str]], tuple[list[str], bool]]]" = None,
    _compound_splitter_lookup: Optional[Callable[[str], Any]] = None,
    _compound_splitter_top_words: Optional[set[str]] = None,
    _compound_splitter_skip_if_pii: Optional[Callable[[str], bool]] = None,
    _morph_candidates: Optional[list[list[MorphCandidate]]] = None,
    _morph_token_is_proper: Optional[list[bool]] = None,
    _repeat_allowlist: Optional[set[str]] = None,
    _reduplication_rules: Optional[tuple[ReduplicationRule, ...]] = None,
    _assimilation_lookup: Optional[Callable[[str], Any]] = None,
    input_source: str = "keyboard",
    _assimilation_pairs: Optional[AssimilationRules] = None,
    _consonant_alternation_lookup: Optional[Callable[[str], Any]] = None,
    _consonant_alternation_alternations: Optional[tuple[ConsonantAlternationRule, ...]] = None,
    _vowel_drop_before_suffix_lookup: Optional[Callable[[str], Any]] = None,
    _vowel_drop_before_suffix_rules: Optional[tuple[VowelDropBeforeSuffixRule, ...]] = None,
    _loanword_singularisation_lookup: Optional[Callable[[str], Any]] = None,
    _loanword_singularisation_rules: Optional[tuple[LoanwordSingularisationRule, ...]] = None,
    _geminate_restoration_lookup: Optional[Callable[[str], Any]] = None,
    _geminate_restoration_rules: Optional[tuple[GeminateRestorationRule, ...]] = None,
    _clock: Optional[Callable[[], float]] = None,
    _dialect_normalizer: Optional[_DialectNormalizer] = None,
) -> NormalizedInput:
    """Run the 8-step normalization pipeline on *text*.

    Parameters
    ----------
    text:
        Raw user input from ``qa.request.v1.raw_text``.
    cfg:
        Config instance.  Defaults to the module-level singleton.
    _diacritic_restore:
        Optional step-6 hook (str -> str).  When ``None``, step 6 is a
        pass-through.  Will be wired to the §10.3 implementation
        once that bullet lands.
    _typo_correct:
        Optional step-8 hook ``(list[str]) -> (list[str], bool)``.
        Returns ``(corrected_tokens, budget_exhausted)``.  When ``None``,
        step 8 is a pass-through with ``typo_budget_exhausted=False``.
    _morph_candidates:
        Optional list of morphology candidate lists, one per token.
        When supplied the morphology stage runs normalization on each token.
    _morph_token_is_proper:
        Optional list of booleans matching ``_morph_candidates``.  When a
        token is marked ``True`` the morphology parser is bypassed and the
        surface form is left for gazetteer matching, emitting a
        ``morph_proper_noun_bypassed`` event.
    _consonant_alternation_lookup:
        Optional per-token lexicon lookup hook for consonant alternation
        repair.  When ``None``, step 8a.1 is a no-op.
    _consonant_alternation_alternations:
        Optional cached closed alternation table.  When ``None``, the
        default YAML loader is used.
    _clock:
        Injectable monotonic-time source (``() -> float``, seconds).
        Defaults to ``time.monotonic``.  Override in tests to control
        the deadline without sleeping.
    _dialect_normalizer:
        Injectable :class:`~nlp.dialect_normalize._DialectNormalizer` for
        testing.  Defaults to the module-level singleton.
    input_source:
        Optional input source marker. When ``voice``, the dialect
        normalizer loads the voice-specific ASR filler table so tokens
        like ``yani`` are preserved on typed input.

    Returns
    -------
    NormalizedInput

    Raises
    ------
    InputTooLongError
        When ``len(text)`` (in codepoints) exceeds
        ``cfg.nlp_input_max_codepoints``.
    """
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg

    raw_tokens: list[str] = []
    steps: list[str] = []
    normalization_events: list[dict[str, object]] = []
    subqueries: tuple[tuple[str, ...], ...] = tuple()
    normalized_emoji_hints: tuple[str, ...] = tuple()
    particle_repairs: tuple[dict[str, object], ...] = tuple()
    floor_kind: str | None = None
    dialect_repairs: tuple[dict[str, object], ...] = tuple()
    regional_dialect_rewrites: tuple[dict[str, object], ...] = tuple()
    dialect_alternatives: tuple[dict[str, object], ...] = tuple()
    apostrophe_repairs: tuple[dict[str, object], ...] = tuple()
    apostrophe_repair_events: list[dict[str, object]] = []
    suffix_harmony_repair_events: tuple[dict[str, object], ...] = tuple()
    vocatives_stripped: tuple[str, ...] = tuple()
    abbreviations_expanded: tuple[str, ...] = tuple()
    soft_abbreviations_tagged: tuple[str, ...] = tuple()
    slurs_stripped: tuple[str, ...] = tuple()
    postposition_stack_matches: tuple[dict[str, object], ...] = tuple()
    postposition_stack_unknowns: tuple[dict[str, object], ...] = tuple()
    morphology_candidates: tuple[tuple[MorphCandidate, ...], ...] = tuple()
    morphology_events: list[dict[str, object]] = []
    emoji_hints: tuple[str, ...] = tuple()
    consonant_alternation_repairs: tuple[dict[str, object], ...] = tuple()
    consonant_alternation_events: tuple[dict[str, object], ...] = tuple()
    geminate_restoration_events: tuple[dict[str, object], ...] = tuple()
    predictive_overshoot_repairs: tuple[tuple[str, str], ...] = tuple()
    query_style: str = "natural"
    intent_modifier: str = "none"
    focus_particle_disambiguated: bool = False
    politeness_class: str = "neutral"

    budget = RequestBudget(cfg=cfg, humanizer=False)
    budget_exhausted_reason: str | None = None
    budget_exhausted_stage: str | None = None
    current_stage = "degenerate_check"
    try:
        budget.__enter__()
        try:
            # -- Degenerate input check (§10.34.2) ---------------------------------
            # BEFORE any normalization pass: hard-reject inputs that are provably
            # malformed (empty, whitespace-only, single control char, lone surrogates,
            # NUL bytes). These bypass Symspell/CRF/Zemberek and route to closed
            # Turkish refusal templates.
            is_degenerate, degenerate_meta_kind = detect_degenerate_input(text)
            if is_degenerate:
                # Map degenerate input to floor response
                floor_kind = degenerate_meta_kind or "meta.empty_input"
                steps = ("degenerate_check",)
                current_stage = "length_cap"
                return NormalizedInput(
                    tokens=tuple(),
                    steps_run=steps,
                    original_codepoint_count=len(text),
                    floor_kind=floor_kind,
                    normalization_events=tuple(),
                )
            steps.append("degenerate_check")
            
            _get_time = _clock if _clock is not None else time.monotonic
            _deadline_s = cfg.nlp_normalize_stage_timeout_ms / 1000.0

            raw_cp = len(text)
            context_dump_sha256: str | None = None

            # -- Step 0a: Mega-input last-paragraph extraction ---------------------
            if raw_cp > int(cfg.nlp_megainput_min_chars) or text.count("\n") >= 3:
                last_paragraph = _extract_last_paragraph(text)
                if last_paragraph is not None:
                    tail, preceding = last_paragraph
                    if len(tail) <= cfg.nlp_input_max_codepoints:
                        text = tail
                        raw_cp = len(text)
                        context_dump_sha256 = hashlib.sha256(preceding.encode("utf-8")).hexdigest()
                        normalization_events.append({
                            "kind": "megainput_tail_extracted",
                            "context_dump_chars": len(preceding),
                            "context_dump_sha256": context_dump_sha256,
                            "line_count": text.count("\n") + 1,
                        })
                    else:
                        normalization_events.append({
                            "kind": "megainput_tail_extracted",
                            "context_dump_chars": raw_cp,
                        })

            current_stage = "length_cap"
            # -- Step 1: Length cap --------------------------------------------------
            if raw_cp > cfg.nlp_input_max_codepoints:
                raise InputTooLongError(
                    f"Input length {raw_cp} codepoints exceeds "
                    f"nlp_input_max_codepoints={cfg.nlp_input_max_codepoints}"
                )
            steps.append("length_cap")

            current_stage = "html_entity_unescape"
            # -- Step 1.5: HTML entity unescape (Phase 10 §10.24.10) ------------------
            if cfg.nlp_html_unescape_enabled:
                normalized = _html_entity_unescape(text, normalization_events)
            else:
                normalized = text
            steps.append("html_entity_unescape")

            current_stage = "canonical_normalize"
            # -- Steps 2+3: NFC + control-char / zero-width / RTL strip -------------
            # canonical_normalize is the Python/Go parity surface; NEVER inline here.
            pre_canonical = normalized
            normalized = canonical_normalize(normalized)
            steps.append("canonical_normalize")

            current_stage = "compose_turkish_dotted_i"
            # -- Step 3.4: Turkish dotted-i composition pass ------------------------
            # Rejoin Turkish-specific decomposed dotted i sequences before lowercase.
            normalized = compose_turkish_dotted_i(normalized)
            steps.append("compose_turkish_dotted_i")

            current_stage = "paste_layout_normalize"
            normalized, floor_kind = _normalize_paste_layout(
                normalized,
                cfg,
                normalization_events.append,
                pre_canonical=pre_canonical,
            )
            steps.append("paste_layout_normalize")

            current_stage = "confusables_fold"
            # -- Step 3.5: Unicode confusables fold (Phase 10 §10.21.5) ------------
            # Defense-in-depth against homoglyph attacks (Cyrillic/Greek lookalikes).
            # Folds to ASCII-Turkish-extended before lowercase so "Galаtasaray" (Cyrillic а)
            # -> "Galatasaray" -> gazetteer exact-match succeeds.
            pre_confusables = normalized
            normalized = confusables_fold(normalized)
            confusables_folded = normalized != pre_confusables
            steps.append("confusables_fold")

            normalized = _normalize_random_case_noise(normalized, cfg, normalization_events.append)

            # -- Step 3.6: Digit-letter confusable fold (§10.24.3) -------------------
            current_stage = "digit_letter_fold"
            if cfg.nlp_digit_letter_fold_enabled:
                normalized = digit_letter_confusable_fold(normalized)
            steps.append("digit_letter_fold")

            caseful_normalized = normalized
            shout = detect_all_caps(caseful_normalized, cfg=cfg)
            current_stage = "lowercase_tr"
            # -- Step 4: Turkish-aware lowercase ------------------------------------
            normalized = lowercase_tr(normalized)
            steps.append("lowercase_tr")

            current_stage = "obfuscated_slur_normalize"
            # -- Step 5a: Obfuscated slur defense (§10.30.10) ------------------------
            normalized = replace_obfuscated_slurs(
                normalized,
                event_sink=normalization_events.append,
            )
            steps.append("obfuscated_slur_normalize")

            current_stage = "punct_normalize"
            # -- Step 5: Punctuation normalization ----------------------------------
            # Zero-copy guarantee (§10.34.2): return same object if no change needed
            if _has_punct_to_normalize(normalized):
                normalized = normalized.translate(_PUNCT_TABLE)
            collapse_unicode_spaces = getattr(cfg, "nlp_collapse_unicode_spaces", True)
            normalized = _collapse_unicode_spaces(normalized, collapse_unicode_spaces)
            # Zero-copy on multi-space collapse (§10.34.2)
            if _has_multi_spaces(normalized):
                normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
            else:
                normalized = normalized.strip()
            steps.append("punct_normalize")

            stripped_tail: str | None = None
            current_stage = "citation_tail_strip"
            if input_source == "paste" or raw_cp >= 200:
                normalized, stripped_tail = _strip_copy_paste_citation_tail(normalized)
            steps.append("citation_tail_strip")

            current_stage = "social_hygiene"
            normalized = _normalize_social_tokens(normalized, normalization_events, cfg)
            steps.append("social_hygiene")

            normalized = _promote_suffixed_emoji_to_concept(normalized, cfg, normalization_events.append)

            current_stage = "emoji_hint_extract"
            if cfg.nlp_emoji_hint_enabled:
                normalized_emoji_hints, normalized = _extract_emoji_hints(normalized, normalization_events)
            else:
                normalized_emoji_hints = ()

            if getattr(cfg, "nlp_strip_emoji", True):
                normalized = _strip_generic_emoji_symbols(normalized, normalization_events)
            steps.append("emoji_hint_extract")

            # Zero-copy guarantee on caseful_punct_normalized (§10.34.2)
            if _has_punct_to_normalize(caseful_normalized):
                caseful_punct_normalized = caseful_normalized.translate(_PUNCT_TABLE)
            else:
                caseful_punct_normalized = caseful_normalized
            caseful_punct_normalized = _collapse_unicode_spaces(
                caseful_punct_normalized,
                collapse_unicode_spaces,
            )
            if _has_multi_spaces(caseful_punct_normalized):
                caseful_punct_normalized = _MULTI_SPACE_RE.sub(" ", caseful_punct_normalized).strip()
            else:
                caseful_punct_normalized = caseful_punct_normalized.strip()
            query_style = detect_search_operator_syntax_in_text(caseful_punct_normalized)

            # -- Steps 6-8 are the bounded "normalize+typo+diacritic" stage. --------
            # Start the stage clock here; deadline is cfg.nlp_normalize_stage_timeout_ms.
            _stage_start = _get_time()

            # -- Step 6: Diacritic restoration (§10.3 hook) -------------------------
            current_stage = "diacritic_restore"
            ascii_restored = False
            if _diacritic_restore is None:
                _diacritic_restore = make_diacritic_restorer(cfg, input_source=input_source)
            pre_diacritic = normalized
            normalized = _diacritic_restore(normalized)
            ascii_restored = normalized != pre_diacritic
            steps.append("diacritic_restore")

            if cfg.nlp_preamble_strip_enabled:
                normalized = _strip_preamble(
                    normalized,
                    cfg,
                    normalization_events.append,
                    original_text=normalized,
                )
            steps.append("strip_preamble")

            current_stage = "ocr_confusion_repair"
            normalized = _normalize_ocr_confusions(
                normalized,
                pre_canonical,
                cfg,
                normalization_events.append,
            )
            steps.append("ocr_confusion_repair")

            # -- Step 6.5: Regional / diaspora dialect normalization (§10.32.4) -----
            normalized, regional_dialect_rewrites, dialect_alternatives = apply_regional_dialect_normalize(
                normalized,
                event_sink=normalization_events.append,
            )
            steps.append("regional_dialect_normalize")

            # -- Step 6.7: Apostrophe repair for proper nouns (§10.32.5) ------------
            suffix_harmony_repair_events: list[dict[str, str]] = []
            if cfg.nlp_harmony_tolerant_strip_enabled:
                normalized, apostrophe_repairs = repair_apostrophe_proper_noun(
                    normalized,
                    original_text=caseful_normalized,
                    event_sink=suffix_harmony_repair_events.append,
                    input_source=input_source,
                    shout=shout,
                )
            else:
                apostrophe_repairs = []
            steps.append("apostrophe_proper_noun_repair")

            # -- Step 7: Tokenization -----------------------------------------------
            # Full zemberek suffix-aware rules will be layered in via §10.2 (vendored
            # snapshot in ai/nlp/vendor/zemberek_rules.json).  This basic split is
            # the binding baseline for step ordering.
            raw_tokens: list[str] = _tokenize(normalized)
            steps.append("tokenize")
            raw_tokens, asr_events = apply_asr_punctuation_words(
                raw_tokens,
                input_source=input_source,
            )
            normalization_events.extend(asr_events)
            raw_tokens = resolve_voice_number_context(raw_tokens, input_source=input_source)

            # -- Step 7b: Turkish run-on / multi-question split (§10.24.5) -----------
            compound_split_events: list[dict[str, object]] = []
            current_stage = "split_questions"
            if cfg.nlp_compound_query_enabled:
                subqueries = tuple(
                    tuple(sq) for sq in split_questions(raw_tokens, input_source=input_source)
                )
                if len(subqueries) > int(cfg.nlp_max_subqueries):
                    original_count = len(subqueries)
                    subqueries = subqueries[: int(cfg.nlp_max_subqueries)]
                    compound_split_events.append({
                        "kind": "subquery_cap_applied",
                        "reason": "nlp_max_subqueries",
                        "original_subquery_count": original_count,
                        "capped_subquery_count": len(subqueries),
                        "nlp_max_subqueries": int(cfg.nlp_max_subqueries),
                    })
            else:
                subqueries = (tuple(raw_tokens),)
            steps.append("split_questions")

            # -- Step 7b: Turkish combining mark hygiene (§10.24.4) ------------------
            # Strip leftover combining marks after the dotted-i composition pass.
            # Tokens with more than 4 removed marks are treated as abusive and dropped.
            current_stage = "strip_combining_marks"
            cleaned_tokens: list[str] = []
            for tok in raw_tokens:
                stripped_tok, removed_marks = _strip_turkish_combining_marks(tok)
                if removed_marks > _MAX_COMBINING_MARKS_PER_TOKEN:
                    normalization_events.append({
                        "kind": "excessive_combining_marks",
                        "severity": "warn",
                        "surface_form_sha8": hashlib.sha256(tok.encode("utf-8")).hexdigest()[:8],
                        "removed_combining_mark_count": removed_marks,
                        "token_dropped": True,
                    })
                    continue

                if removed_marks > 0:
                    normalization_events.append({
                        "kind": "excessive_combining_marks",
                        "severity": "warn",
                        "surface_form_sha8": hashlib.sha256(tok.encode("utf-8")).hexdigest()[:8],
                        "removed_combining_mark_count": removed_marks,
                        "token_dropped": False,
                    })

                if stripped_tok:
                    cleaned_tokens.append(stripped_tok)
            raw_tokens = cleaned_tokens
            steps.append("strip_combining_marks")

            # -- Step 7a: repeated-character collapse (§10.24.2) ---------------------
            repeat_allowlist = _repeat_allowlist if _repeat_allowlist is not None else load_repeat_allowlist()
            repeat_collapse_max_len = getattr(cfg, "nlp_repeat_collapse_max_len", 64)
            collapsed_tokens: list[str] = []
            current_stage = "repeat_collapse"
            for tok in raw_tokens:
                if len(tok) > repeat_collapse_max_len:
                    continue
                collapsed_tokens.append(collapse_repeated_chars(tok, allowlist=repeat_allowlist))
            raw_tokens = collapsed_tokens
            steps.append("repeat_collapse")

            raw_tokens = _normalize_numeric_redundant_restatement(raw_tokens, cfg, normalization_events.append)

            # -- Step 7c: Reduplicated-emphasis collapse (§10.29.7) -----------------
            if cfg.nlp_reduplication_collapse_enabled:
                rules = _reduplication_rules or load_reduplication_pairs()
                raw_tokens = collapse_reduplication(
                    raw_tokens,
                    rules,
                    event_sink=normalization_events.append,
                )
            steps.append("reduplication_collapse")

            # -- Step 7d: Predictive-text overshoot correction (§10.34.1) -----------
            predictive_overshoot_repairs: list[tuple[str, str]] = []
            if cfg.nlp_predictive_overshoot_enabled:
                lookup = _load_predictive_overshoot_lookup()
                max_repairs = int(cfg.nlp_predictive_overshoot_max_per_query)
                for index, tok in enumerate(raw_tokens):
                    if len(predictive_overshoot_repairs) >= max_repairs:
                        break
                    corrected = lookup.get(tok)
                    if corrected is None or corrected == tok:
                        continue
                    raw_tokens[index] = corrected
                    predictive_overshoot_repairs.append((tok, corrected))
                    normalization_events.append({
                        "kind": "predictive_overshoot_offered",
                        "original_token": tok,
                        "corrected_token": corrected,
                    })
            steps.append("predictive_overshoot")

            # -- Step 7c.5: Inline self-correction (§10.32.10) ------------------------
            inline_self_correction_events: list[dict[str, object]] = []

            def _append_inline_self_correction_event(event: dict[str, object]) -> None:
                inline_self_correction_events.append(event)
                normalization_events.append(event)

            if cfg.nlp_inline_self_correction_enabled:
                markers = _inline_self_correction_markers or load_inline_self_correction_markers()
                raw_tokens = apply_inline_self_correction(
                    raw_tokens,
                    markers,
                    event_sink=_append_inline_self_correction_event,
                )
            steps.append("inline_self_correction")

            # -- Step 7.2: Turkish numeric context disambiguation (§10.24.11) ---------
            _annotate_numeric_context(raw_tokens, normalization_events)

            # -- Step 7.5: No-space compound splitting (§10.28.3) ----------------------
            if cfg.nlp_compound_split_enabled and _compound_splitter_lookup is not None:
                current_stage = "compound_split"
                raw_tokens = split_compound_tokens(
                    raw_tokens,
                    _compound_splitter_lookup,
                    top_words=_compound_splitter_top_words or set(),
                    max_splits=cfg.nlp_compound_split_max_splits,
                    max_lookups=cfg.nlp_compound_split_max_lookups_per_query,
                    skip_if_pii=_compound_splitter_skip_if_pii,
                    event_sink=compound_split_events.append,
                )
            steps.append("compound_split")

            morphology_candidates: tuple[tuple[MorphCandidate, ...], ...] = tuple()
            morphology_events: list[dict[str, object]] = []
            morph_ambiguity_budget_exhausted: bool = False
            loanword_singularisation_events: list[dict[str, str]] = []
            current_stage = "morphology_candidate_normalize"
            if _morph_candidates is not None:
                if len(_morph_candidates) != len(raw_tokens):
                    raise ValueError("_morph_candidates must match the normalized token count")
                if _morph_token_is_proper is not None and len(_morph_token_is_proper) != len(_morph_candidates):
                    raise ValueError("_morph_token_is_proper must match the length of _morph_candidates")

                normalized_per_token: list[tuple[MorphCandidate, ...]] = []
                morph_high_ambiguity_count = 0
                for idx, candidates in enumerate(_morph_candidates):
                    token_is_proper = (_morph_token_is_proper or [False] * len(_morph_candidates))[idx]
                    token = raw_tokens[idx] if idx < len(raw_tokens) else ""
                    if token_is_proper:
                        normalized_per_token.append(())
                        morphology_events.append({
                            "kind": "morph_proper_noun_bypassed",
                            "surface_form_sha8": hashlib.sha256(token.encode("utf-8")).hexdigest()[:8],
                        })
                        continue

                    if not candidates:
                        normalized_per_token.append(())
                        morphology_events.append({
                            "kind": "morph_parse_unparseable",
                            "surface_form_sha8": hashlib.sha256(token.encode("utf-8")).hexdigest()[:8],
                            "candidate_count": 0,
                        })
                        continue

                    retained = tuple(
                        normalize_morph_candidates(
                            candidates,
                            topk=cfg.nlp_morph_topk,
                            min_confidence=cfg.nlp_morph_min_confidence,
                        )
                    )
                    normalized_per_token.append(retained)
                    if any(candidate.ambiguity_class == "high" for candidate in retained):
                        morph_high_ambiguity_count += 1
                        morphology_events.append({
                            "kind": "morph_parse_ambiguous",
                            "surface_form_sha8": hashlib.sha256(token.encode("utf-8")).hexdigest()[:8],
                            "candidate_count": len(retained),
                        })
                morphology_candidates = tuple(normalized_per_token)
                morph_ambiguity_budget_exhausted = (
                    morph_high_ambiguity_count > cfg.nlp_morph_ambiguous_max_per_query
                )
                if morph_ambiguity_budget_exhausted:
                    morphology_events.append({
                        "kind": "morph_ambiguity_budget_exhausted",
                        "high_ambiguity_token_count": morph_high_ambiguity_count,
                    })
                steps.append("morphology_candidate_normalize")

            # Deadline check after step 6+7: if we are already over budget, skip the
            # expensive steps 8a+8 and return the raw token sequence.  The caller emits
            # nlp.event.v1{kind=normalize_timeout} upon seeing stage_timed_out=True.
            if (_get_time() - _stage_start) * 1000.0 >= _deadline_s * 1000.0:
                steps.append("particle_normalize")
                steps.append("assimilation_fold")
                steps.append("postposition_stack")
                steps.append("consonant_alternation")
                steps.append("vowel_drop_before_suffix")
                steps.append("loanword_singularisation")
                steps.append("geminate_restoration")
                steps.append("dialect_normalize")
                steps.append("typo_correct")
                focus_particle_disambiguated = detect_focus_particle_disambiguation(raw_tokens)
                if focus_particle_disambiguated:
                    normalization_events.append({
                        "kind": "focus_particle_disambiguated",
                    })
                pragmatic_class = detect_question_tag_pragmatic_class(
                    raw_tokens,
                    focus_particle_disambiguated=focus_particle_disambiguated,
                )
                return NormalizedInput(
                    tokens=tuple(raw_tokens),
                    subqueries=subqueries,
                    steps_run=tuple(steps),
                    original_codepoint_count=raw_cp,
                    typo_budget_exhausted=False,
                    stage_timed_out=True,
                    compound_split_events=tuple(compound_split_events),
                    regional_dialect_rewrites=(),
                    dialect_alternatives=(),
                    apostrophe_repairs=tuple(apostrophe_repairs),
                    apostrophe_repair_events=tuple(),
                    politeness_class="neutral",
                    query_style=query_style,
                    intent_modifier="none",
                    focus_particle_disambiguated=focus_particle_disambiguated,
                    pragmatic_class=pragmatic_class,
                    idiom_events=tuple(),
                    vocatives_stripped=tuple(),
                    abbreviations_expanded=frozenset(),
                    soft_abbreviations_tagged=frozenset(),
                    slurs_stripped=tuple(),
                    postposition_stack_matches=tuple(),
                    postposition_stack_unknowns=tuple(),
                    morphology_candidates=morphology_candidates,
                    morphology_events=tuple(morphology_events),
                    loanword_singularisation_events=tuple(loanword_singularisation_events),
                    normalization_events=tuple(normalization_events),
                    floor_kind=floor_kind,
                    context_dump_sha256=context_dump_sha256,
                )

            # -- Step 8a: Particle normalization (§10.22.4) -------------------------
            # Detaches mi/mı/mu/mü question particles and annotates de/da/ki.
            # Runs before typo correction so the classifier (§10.4) sees the canonical
            # (always-detached) particle form.  Fixpoint: idempotent on its own output.
            particle_tokens, _particle_repairs = _normalize_particles(raw_tokens)
            if cfg.nlp_ki_context_disambiguation:
                ki_contexts = detect_ki_contexts(normalized, particle_tokens)
                if ki_contexts:
                    filtered_particle_tokens: list[str] = []
                    ki_index = 0
                    for tok in particle_tokens:
                        if tok.lower() == "ki":
                            context = ki_contexts[ki_index] if ki_index < len(ki_contexts) else "ambiguous"
                            ki_index += 1
                            if context in {"relative", "emphatic"}:
                                normalization_events.append({
                                    "kind": "ki_context_disambiguated",
                                    "reading": context,
                                    "severity": "info",
                                })
                            else:
                                normalization_events.append({
                                    "kind": "ki_disambiguation_low_confidence",
                                    "severity": "warn",
                                })
                            filtered_particle_tokens.append(tok)
                            continue
                        filtered_particle_tokens.append(tok)
                    particle_tokens = filtered_particle_tokens
            steps.append("particle_normalize")

            # -- Step 8a.1: Assimilation normalization (§10.28.2) ----------------------
            current_stage = "assimilation_fold"
            if cfg.nlp_assimilation_fold_enabled and _assimilation_lookup is not None:
                particle_tokens = fold_assimilated_suffixes(
                    particle_tokens,
                    _assimilation_lookup,
                    _assimilation_pairs or load_assimilation_pairs(),
                )
            steps.append("assimilation_fold")

            # -- Step 8a.5: Postposition stack detection (§10.32.3) -------------------
            # Recognises closed 2-postposition stacks and preserves the token stream.
            postposition_stack_matches, postposition_stack_unknowns = detect_postposition_stacks(
                particle_tokens
            )
            steps.append("postposition_stack")

            # -- Step 8a.1: Consonant-alternation tolerance (§10.28.1) ------------
            # Accept a token with softened/unsoftened Turkish consonants if a
            # lexicon lookup proves the alternated form exists and the token is not
            # a canonical exception in the no-rewrite allowlist.
            consonant_alternation_repairs: list[tuple[str, str]] = []
            consonant_alternation_events: list[dict[str, str]] = []
            current_stage = "consonant_alternation"
            if cfg.nlp_consonant_alternation_enabled and _consonant_alternation_lookup is not None:
                alternations = _consonant_alternation_alternations or load_consonant_alternations()
                no_strip_canonicals = load_dialect_no_rewrite_canonicals()
                corrected_tokens: list[str] = []
                for tok in particle_tokens:
                    repaired_token, event = tolerate_consonant_alternation(
                        tok,
                        _consonant_alternation_lookup,
                        no_strip_canonicals=no_strip_canonicals,
                        alternations=alternations,
                    )
                    corrected_tokens.append(repaired_token)
                    if event is not None:
                        consonant_alternation_repairs.append((tok, repaired_token))
                        consonant_alternation_events.append(event)
                particle_tokens = corrected_tokens
            steps.append("consonant_alternation")

            # -- Step 8b.5: Vowel-drop-before-suffix tolerance (§10.29.2) ------------
            vowel_drop_before_suffix_events: list[dict[str, str]] = []
            current_stage = "vowel_drop_before_suffix"
            if _vowel_drop_before_suffix_lookup is None:
                _vowel_drop_before_suffix_lookup = _consonant_alternation_lookup
            if cfg.nlp_vowel_drop_before_suffix_enabled and _vowel_drop_before_suffix_lookup is not None:
                rules = _vowel_drop_before_suffix_rules or load_vowel_drop_before_suffix_rules()
                corrected_tokens = []
                for tok in particle_tokens:
                    repaired_token, event = tolerate_vowel_drop_before_suffix(
                        tok,
                        _vowel_drop_before_suffix_lookup,
                        rules=rules,
                    )
                    corrected_tokens.append(repaired_token)
                    if event is not None:
                        vowel_drop_before_suffix_events.append(event)
                particle_tokens = corrected_tokens
            steps.append("vowel_drop_before_suffix")

            # -- Step 8d: Loanword plural-as-singular repair (§10.29.5) ------------
            loanword_singularisation_events: list[dict[str, str]] = []
            current_stage = "loanword_singularisation"
            if cfg.nlp_loanword_singularisation_enabled and _loanword_singularisation_lookup is not None:
                rules = _loanword_singularisation_rules or load_loanword_singularisation_rules()
                corrected_tokens = []
                for tok in particle_tokens:
                    repaired_token, event = singularise_loanword_plural(
                        tok,
                        _loanword_singularisation_lookup,
                        rules=rules,
                    )
                    corrected_tokens.append(repaired_token)
                    if event is not None:
                        loanword_singularisation_events.append(event)
                particle_tokens = corrected_tokens
            steps.append("loanword_singularisation")

            # -- Step 8c: Geminate restoration (§10.29.1) -----------------------------
            geminate_restoration_events: list[dict[str, str]] = []
            current_stage = "geminate_restoration"
            if _geminate_restoration_lookup is not None:
                restorations = _geminate_restoration_rules or load_geminate_restorations()
                corrected_tokens = []
                for tok in particle_tokens:
                    repaired_token, event = restore_geminate(
                        tok,
                        _geminate_restoration_lookup,
                        restorations=restorations,
                    )
                    corrected_tokens.append(repaired_token)
                    if event is not None:
                        geminate_restoration_events.append(event)
                particle_tokens = corrected_tokens
            steps.append("geminate_restoration")

            # -- Step 8b: Dialect / abbreviation / vocative normalization (§10.22.5) --
            # Applied after particle normalization and before typo correction so the
            # classifier sees canonical spoken-Turkish forms and team entity IDs.
            # Sub-steps (in order):
            #   i.  Multi-token compound rules (negation_q_compound, etc.)
            #   i.  Single-token phonological rules (gerund_r_drop, future_contracted)
            #   i.  Seed-lookup fallback for non-rule forms
            #   ii. Vocative/filler stripping (abi, reis, hocam, …)
            #   iii.Hard abbreviation expansion (GS → galatasaray, etc.)
            current_stage = "dialect_normalize"
            if _dialect_normalizer is not None:
                _dialect_result = _apply_dialect_normalize(
                    particle_tokens, _normalizer=_dialect_normalizer
                )
            else:
                _dialect_result = _apply_dialect_normalize(
                    particle_tokens,
                    use_asr_fillers=(input_source == "voice"),
                    asr_filler_strip_max=(
                        cfg.nlp_asr_filler_strip_max if input_source == "voice" else None
                    ),
                )
            dialect_tokens: list[str] = list(_dialect_result.tokens)
            steps.append("dialect_normalize")

            dialect_normalized_text = " ".join(dialect_tokens)
            dialect_normalized_text = _MULTI_SPACE_RE.sub(" ", dialect_normalized_text).strip()
            dialect_tokens = _tokenize(dialect_normalized_text)

            politeness_tokens, politeness_class = strip_politeness_markers(dialect_tokens)
            idiom_tokens, idiom_events = expand_idioms(politeness_tokens, normalized)
            intent_modifier, _modifier_tense = detect_conditional_modifier(idiom_tokens)
            if detect_coordinating_particles(dialect_normalized_text):
                if isinstance(intent_modifier, tuple):
                    if "comparative" not in intent_modifier:
                        intent_modifier = (*intent_modifier, "comparative")
                elif intent_modifier == "none":
                    intent_modifier = "comparative"
                elif intent_modifier != "comparative":
                    intent_modifier = (intent_modifier, "comparative")
            sarcasm_modifier = detect_sarcastic_modifier(idiom_tokens)
            for cue_id in find_sarcasm_cue_ids(idiom_tokens):
                get_sink().record_nlp_sarcasm_cue(cue_id)

            if sarcasm_modifier != "none":
                if isinstance(intent_modifier, tuple):
                    if sarcasm_modifier not in intent_modifier:
                        intent_modifier = (*intent_modifier, sarcasm_modifier)
                elif intent_modifier == "none":
                    intent_modifier = sarcasm_modifier
                elif intent_modifier != sarcasm_modifier:
                    intent_modifier = (intent_modifier, sarcasm_modifier)
            else:
                for cue_event in find_sarcasm_cues_without_context(idiom_tokens):
                    normalization_events.append(cue_event)

            # -- Step 8: Token-level typo correction (§10.3 hook) -------------------
            current_stage = "typo_correct"
            budget_exhausted = False
            if _typo_correct is not None:
                tokens, budget_exhausted = _typo_correct(idiom_tokens)
            else:
                tokens = idiom_tokens
            steps.append("typo_correct")

            # Final deadline check: step 8 itself may have consumed the remaining
            # budget.  Flag the result so the caller can act accordingly.
            stage_timed_out = (_get_time() - _stage_start) * 1000.0 >= _deadline_s * 1000.0

            apostrophe_repair_events = tuple(
                {
                    "kind": "apostrophe_inferred",
                    "evidence": repair.evidence,
                    "original": repair.original,
                    "canonical": repair.repaired,
                }
                for repair in apostrophe_repairs
                if repair.evidence is not None
            )

            focus_particle_disambiguated = detect_focus_particle_disambiguation(tokens)
            if focus_particle_disambiguated:
                normalization_events.append({
                    "kind": "focus_particle_disambiguated",
                })

            pragmatic_class = detect_question_tag_pragmatic_class(
                tokens,
                focus_particle_disambiguated=focus_particle_disambiguated,
            )

            result = NormalizedInput(
                tokens=tuple(tokens),
                subqueries=subqueries,
                steps_run=tuple(steps),
                original_codepoint_count=raw_cp,
                typo_budget_exhausted=budget_exhausted,
                morph_ambiguity_budget_exhausted=morph_ambiguity_budget_exhausted,
                stage_timed_out=stage_timed_out,
                compound_split_events=tuple(compound_split_events),
                particle_repairs=_particle_repairs,
                dialect_repairs=tuple(_dialect_result.dialect_repairs),
                regional_dialect_rewrites=regional_dialect_rewrites,
                dialect_alternatives=dialect_alternatives,
                apostrophe_repairs=tuple(apostrophe_repairs),
                apostrophe_repair_events=apostrophe_repair_events,
                suffix_harmony_repair_events=tuple(suffix_harmony_repair_events),
                stripped_tail=stripped_tail,
                politeness_class=politeness_class,
                query_style=query_style,
                intent_modifier=intent_modifier,
                focus_particle_disambiguated=focus_particle_disambiguated,
                pragmatic_class=pragmatic_class,
                idiom_events=tuple(idiom_events),
                normalization_events=tuple(normalization_events),
                vocatives_stripped=_dialect_result.vocatives_stripped,
                abbreviations_expanded=_dialect_result.abbreviations_expanded,
                soft_abbreviations_tagged=_dialect_result.soft_abbreviations_tagged,
                slurs_stripped=_dialect_result.slurs_stripped,
                postposition_stack_matches=tuple(postposition_stack_matches),
                postposition_stack_unknowns=tuple(postposition_stack_unknowns),
                emoji_hints=tuple(normalized_emoji_hints),
                consonant_alternation_repairs=tuple(consonant_alternation_repairs),
                consonant_alternation_events=tuple(consonant_alternation_events),
                geminate_restoration_events=tuple(geminate_restoration_events),
                predictive_overshoot_repairs=tuple(
                    (
                        event["original_token"],
                        event["corrected_token"],
                    )
                    for event in normalization_events
                    if event.get("kind") == "predictive_overshoot_offered"
                ),
                vowel_drop_before_suffix_events=tuple(vowel_drop_before_suffix_events),
                inline_self_correction_events=tuple(inline_self_correction_events),
                morphology_candidates=morphology_candidates,
                morphology_events=tuple(morphology_events),
                loanword_singularisation_events=tuple(loanword_singularisation_events),
                floor_kind=floor_kind,
                context_dump_sha256=context_dump_sha256,
            )
            _record_nlp_input_repair_metrics(result, len(tokens), confusables_folded, ascii_restored)
            return result
        finally:
            exc_info = sys.exc_info()
            budget.__exit__(*exc_info)
    except BudgetExceeded as exc:
        budget_exhausted_stage = current_stage
        budget_exhausted_reason = (
            "rss_budget_exceeded"
            if "RSS budget exceeded" in str(exc)
            else "cpu_budget_exceeded"
        )
        normalization_events.append({
            "kind": "request_budget_exhausted",
            "severity": "warn",
            "reason": budget_exhausted_reason,
            "stage": budget_exhausted_stage,
        })
        try:
            return NormalizedInput(
                tokens=tuple(raw_tokens),
                subqueries=subqueries,
                steps_run=tuple(steps),
                original_codepoint_count=len(text),
                typo_budget_exhausted=False,
                morph_ambiguity_budget_exhausted=False,
                stage_timed_out=False,
                compound_split_events=tuple(),
                particle_repairs=tuple(),
                dialect_repairs=tuple(),
                regional_dialect_rewrites=tuple(),
                dialect_alternatives=tuple(),
                apostrophe_repairs=tuple(),
                apostrophe_repair_events=tuple(),
                suffix_harmony_repair_events=tuple(),
                stripped_tail=None,
                politeness_class="neutral",
                query_style="natural",
                intent_modifier="none",
                focus_particle_disambiguated=False,
                idiom_events=tuple(),
                normalization_events=tuple(normalization_events),
                vocatives_stripped=tuple(),
                abbreviations_expanded=tuple(),
                soft_abbreviations_tagged=tuple(),
                slurs_stripped=tuple(),
                postposition_stack_matches=tuple(),
                postposition_stack_unknowns=tuple(),
                emoji_hints=tuple(),
                consonant_alternation_repairs=tuple(),
                consonant_alternation_events=tuple(),
                geminate_restoration_events=tuple(),
                predictive_overshoot_repairs=tuple(),
                morphology_candidates=tuple(),
                morphology_events=tuple(),
                budget_exhausted_reason=budget_exhausted_reason,
                budget_exhausted_stage=budget_exhausted_stage,
                floor_kind=floor_kind,
            )
        except BudgetExceeded:
            return NormalizedInput(
                tokens=tuple(raw_tokens),
                subqueries=subqueries,
                steps_run=tuple(steps),
                original_codepoint_count=len(text),
                typo_budget_exhausted=False,
                morph_ambiguity_budget_exhausted=False,
                stage_timed_out=False,
                compound_split_events=tuple(),
                particle_repairs=tuple(),
                dialect_repairs=tuple(),
                regional_dialect_rewrites=tuple(),
                dialect_alternatives=tuple(),
                apostrophe_repairs=tuple(),
                apostrophe_repair_events=tuple(),
                suffix_harmony_repair_events=tuple(),
                stripped_tail=None,
                politeness_class="neutral",
                query_style="natural",
                intent_modifier="none",
                focus_particle_disambiguated=False,
                idiom_events=tuple(),
                normalization_events=tuple(normalization_events),
                vocatives_stripped=tuple(),
                abbreviations_expanded=tuple(),
                soft_abbreviations_tagged=tuple(),
                slurs_stripped=tuple(),
                postposition_stack_matches=tuple(),
                postposition_stack_unknowns=tuple(),
                emoji_hints=tuple(),
                consonant_alternation_repairs=tuple(),
                consonant_alternation_events=tuple(),
                geminate_restoration_events=tuple(),
                predictive_overshoot_repairs=tuple(),
                morphology_candidates=tuple(),
                morphology_events=tuple(),
                budget_exhausted_reason=budget_exhausted_reason,
                budget_exhausted_stage=budget_exhausted_stage,
                floor_kind=floor_kind,
                context_dump_sha256=context_dump_sha256,
            )
