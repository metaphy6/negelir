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
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from common.config import cfg
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
from nlp.dialect_normalize import (    apply_dialect_normalize as _apply_dialect_normalize,
    _DialectNormalizer,
    load_abbreviations,
)
from nlp.diacritics import make_diacritic_restorer
from nlp.postposition_stack import (
    detect_postposition_stacks,
    PostpositionStackMatch,
    UnknownPostpositionStack,
)
from nlp.phase10_30 import (
    apply_asr_punctuation_words,
    detect_conditional_modifier,
    detect_search_operator_syntax_in_text,
    detect_sarcastic_modifier,
    expand_idioms,
    resolve_voice_number_context,
    strip_politeness_markers,
)
from nlp.apostrophe_proper_noun import (
    ApostropheRepair,
    repair_apostrophe_proper_noun,
)
from nlp.assimilation import (
    AssimilationRules,
    fold_assimilated_suffixes,
    load_assimilation_pairs,
)
from nlp.compound_splitter import split_compound_tokens
from nlp.consonant_alternation import (
    ConsonantAlternationRule,
    load_consonant_alternations,
    tolerate_consonant_alternation,
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
    ord("\u00B7"): ".",    # MIDDLE DOT -> period
}

# Collapse multiple consecutive spaces produced after em/en-dash expansion.
_MULTI_SPACE_RE = re.compile(r" {2,}")

# ---------------------------------------------------------------------------
# Step 5a -- Unicode space collapse (Phase 10 §10.33.3)
# ---------------------------------------------------------------------------
# Collapse every Unicode Zs category to ASCII space before tokenization.
# This prevents invisible whitespace from silently joining tokens.
def _collapse_unicode_spaces(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return "".join(
        " " if unicodedata.category(ch) == "Zs" else ch for ch in text
    )

_SOCIAL_HANDLES_PATH = Path(__file__).resolve().parent / "lang_tr" / "social_handles.tr.yaml"
_SOCIAL_HANDLES: dict[str, str] | None = None
_ABBREVIATION_KEYS: set[str] | None = None
_URL_RE = re.compile(r"(https?://[^\s,;!?\)\]]+|www\.[^\s,;!?\)\]]+)", re.UNICODE)
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]+)")
_MENTION_RE = re.compile(r"@([A-Za-z0-9_]+)")
_ALL_PUNCT_RE = re.compile(r"[^\w\d]+", re.UNICODE)

_GREETINGS_PATH = Path(__file__).resolve().parent / "lang_tr" / "greetings.tr.yaml"
_GREETINGS: set[str] | None = None

_EMOJI_HINTS_PATH = Path(__file__).resolve().parent / "lang_tr" / "emoji_hints.tr.yaml"
_EMOJI_HINTS_TABLE: dict[str, dict[str, object]] | None = None
_EMOJI_HINTS_RE: re.Pattern[str] | None = None


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


def _load_greetings() -> set[str]:
    global _GREETINGS
    if _GREETINGS is None:
        raw = yaml.safe_load(_GREETINGS_PATH.read_text(encoding="utf-8")) or []
        if not isinstance(raw, list):
            raise ValueError("greetings.tr.yaml must contain a list of greetings")
        greetings: set[str] = set()
        for entry in raw:
            if not isinstance(entry, str):
                raise ValueError("greetings.tr.yaml entries must be strings")
            normalized = canonical_normalize(entry).strip().lower()
            if normalized:
                greetings.add(normalized)
        _GREETINGS = greetings
    assert _GREETINGS is not None
    return _GREETINGS


def assert_minimum_signal(text: str, *, cfg=None) -> tuple[str, str | None]:
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg

    normalized = canonical_normalize(str(text or ""))
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    if not normalized:
        return "empty_input_floor_response", None

    lower_text = normalized.lower()
    if lower_text in _load_greetings():
        return "greeting_input_floor_response", lower_text

    if len(normalized) == 1 and normalized != "?" and not normalized.isdigit():
        return "meta.unsupported_too_short", None

    if _ALL_PUNCT_RE.sub("", normalized) == "":
        return "meta.unsupported_too_short", None

    raw_tokens = _tokenize(normalized)
    if len(raw_tokens) < int(cfg.nlp_min_tokens) and not re.search(r"\d", normalized):
        return "meta.unsupported_too_short", None

    return "ok", None


def _segment_hashtag(token: str) -> list[str]:
    known = _load_abbreviation_keys()
    token = token.lower()
    if token in known:
        return [token]

    segments: list[str] = []
    idx = 0
    while idx < len(token):
        match: str | None = None
        for end in range(len(token), idx, -1):
            candidate = token[idx:end]
            if candidate in known:
                match = candidate
                break
        if match is None:
            return []
        segments.append(match)
        idx += len(match)
    return segments


def _extract_domain(url: str) -> str:
    parsed = urlparse(url if url.startswith("http") else f"http://{url}")
    return parsed.netloc.lower()


def _html_entity_unescape(text: str, event_sink: list[dict[str, object]]) -> str:
    normalized = html.unescape(text)
    if normalized != text:
        event_sink.append({"kind": "html_entity_unescaped", "original": text, "normalized": normalized})
    return normalized


def _normalize_social_tokens(text: str, event_sink: list[dict[str, object]], cfg) -> str:
    normalized = text

    def _url_replacer(match: re.Match[str]) -> str:
        url = match.group(0)
        event_sink.append({"kind": "url_stripped", "url": url, "domain": _extract_domain(url)})
        return " "

    normalized = _URL_RE.sub(_url_replacer, normalized)

    handles = _load_social_handles()

    def _hashtag_replacer(match: re.Match[str]) -> str:
        token = match.group(1)
        segments = _segment_hashtag(token)
        if not segments:
            event_sink.append({"kind": "hashtag_dropped", "original": match.group(0)})
            return " "
        event_sink.append({"kind": "hashtag_expanded", "original": match.group(0), "segments": segments})
        return " " + " ".join(segments) + " "

    if cfg.nlp_hashtag_handling_enabled:
        normalized = _HASHTAG_RE.sub(_hashtag_replacer, normalized)

    def _mention_replacer(match: re.Match[str]) -> str:
        handle = match.group(1).strip().lower()
        canonical = handles.get(handle)
        if canonical is None:
            event_sink.append({"kind": "mention_dropped", "original": match.group(0)})
            return " "
        event_sink.append({"kind": "mention_resolved", "original": match.group(0), "canonical": canonical})
        return " " + canonical + " "

    if cfg.nlp_at_mention_handling_enabled:
        normalized = _MENTION_RE.sub(_mention_replacer, normalized)
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    return normalized


def _load_emoji_hints() -> tuple[dict[str, dict[str, object]], re.Pattern[str]]:
    global _EMOJI_HINTS_TABLE, _EMOJI_HINTS_RE
    if _EMOJI_HINTS_TABLE is None:
        raw = yaml.safe_load(_EMOJI_HINTS_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("emoji_hints.tr.yaml must be a mapping")

        hints: dict[str, dict[str, object]] = {}
        for emoji, meta in raw.items():
            if not isinstance(emoji, str):
                raise ValueError("emoji_hints keys must be strings")
            if not isinstance(meta, dict):
                raise ValueError("emoji_hints values must be mappings")
            hint = str(meta.get("hint", "")).strip()
            if not hint:
                raise ValueError(f"emoji_hints entry for {emoji!r} missing hint")
            team_color = meta.get("team_color")
            if team_color is not None:
                if not isinstance(team_color, list) or not all(isinstance(item, str) for item in team_color):
                    raise ValueError(f"team_color for {emoji!r} must be a list of strings")
                team_color = tuple(item.strip() for item in team_color if item.strip())
            else:
                team_color = tuple()
            hints[emoji] = {"hint": hint, "team_color": team_color}

        _EMOJI_HINTS_TABLE = hints
        _EMOJI_HINTS_RE = re.compile(
            "|".join(re.escape(emoji) for emoji in sorted(hints.keys(), key=len, reverse=True))
        )
    assert _EMOJI_HINTS_TABLE is not None and _EMOJI_HINTS_RE is not None
    return _EMOJI_HINTS_TABLE, _EMOJI_HINTS_RE


def _extract_emoji_hints(text: str, event_sink: list[dict[str, object]]) -> tuple[tuple[dict[str, object], ...], str]:
    hints_table, hint_re = _load_emoji_hints()
    emoji_hints: list[dict[str, object]] = []

    def _replace(match: re.Match[str]) -> str:
        emoji = match.group(0)
        meta = hints_table[emoji]
        if meta["hint"] != "generic_decoration":
            hint_payload: dict[str, object] = {
                "emoji": emoji,
                "hint": meta["hint"],
            }
            if meta["team_color"]:
                hint_payload["team_color"] = list(meta["team_color"])
            emoji_hints.append(hint_payload)
            event_sink.append({
                "kind": "emoji_hint_extracted",
                "emoji": emoji,
                "hint": meta["hint"],
                "team_color": list(meta["team_color"]),
            })
        else:
            event_sink.append({
                "kind": "emoji_stripped_generic_decoration",
                "emoji": emoji,
            })
        return ""

    normalized = hint_re.sub(_replace, text)
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    return tuple(emoji_hints), normalized

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
            if ch in ",.:-" and prev_digit and next_digit:
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
    politeness_class: str = "neutral"
    """Detected politeness marker class after normalizing polite/casual tokens."""
    query_style: str = "natural"
    """Detected query style for the input, e.g. natural, search, quoted_exact_search."""
    intent_modifier: str | tuple[str, ...] = "none"
    """Detected intent modifier such as conditional or comparative."""
    idiom_events: tuple[dict[str, Any], ...] = tuple()
    """Logged idiom expansion/ambiguity events discovered during normalization."""
    normalization_events: tuple[dict[str, Any], ...] = tuple()
    """Special normalization events emitted by early voice/ASR features."""
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

    if result.dialect_repairs:
        sink.record_nlp_input_repair("dialect_expanded", len(result.dialect_repairs))

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
    _assimilation_lookup: Optional[Callable[[str], Any]] = None,
    input_source: str = "keyboard",
    _assimilation_pairs: Optional[AssimilationRules] = None,
    _consonant_alternation_lookup: Optional[Callable[[str], Any]] = None,
    _consonant_alternation_alternations: Optional[tuple[ConsonantAlternationRule, ...]] = None,
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

    _get_time = _clock if _clock is not None else time.monotonic
    _deadline_s = cfg.nlp_normalize_stage_timeout_ms / 1000.0

    steps: list[str] = []
    raw_cp = len(text)
    normalization_events: list[dict[str, object]] = []

    # -- Step 1: Length cap --------------------------------------------------
    if raw_cp > cfg.nlp_input_max_codepoints:
        raise InputTooLongError(
            f"Input length {raw_cp} codepoints exceeds "
            f"nlp_input_max_codepoints={cfg.nlp_input_max_codepoints}"
        )
    steps.append("length_cap")

    # -- Step 1.5: HTML entity unescape (Phase 10 §10.24.10) ------------------
    if cfg.nlp_html_unescape_enabled:
        normalized = _html_entity_unescape(text, normalization_events)
    else:
        normalized = text
    steps.append("html_entity_unescape")

    # -- Steps 2+3: NFC + control-char / zero-width / RTL strip -------------
    # canonical_normalize is the Python/Go parity surface; NEVER inline here.
    normalized = canonical_normalize(normalized)
    steps.append("canonical_normalize")

    # -- Step 3.4: Turkish dotted-i composition pass ------------------------
    # Rejoin Turkish-specific decomposed dotted i sequences before lowercase.
    normalized = compose_turkish_dotted_i(normalized)
    steps.append("compose_turkish_dotted_i")

    # -- Step 3.5: Unicode confusables fold (Phase 10 §10.21.5) ------------
    # Defense-in-depth against homoglyph attacks (Cyrillic/Greek lookalikes).
    # Folds to ASCII-Turkish-extended before lowercase so "Galаtasaray" (Cyrillic а)
    # -> "Galatasaray" -> gazetteer exact-match succeeds.
    pre_confusables = normalized
    normalized = confusables_fold(normalized)
    confusables_folded = normalized != pre_confusables
    steps.append("confusables_fold")

    # -- Step 3.6: Digit-letter confusable fold (§10.24.3) -------------------
    if cfg.nlp_digit_letter_fold_enabled:
        normalized = digit_letter_confusable_fold(normalized)
    steps.append("digit_letter_fold")

    caseful_normalized = normalized
    # -- Step 4: Turkish-aware lowercase ------------------------------------
    normalized = lowercase_tr(normalized)
    steps.append("lowercase_tr")

    # -- Step 5: Punctuation normalization ----------------------------------
    normalized = normalized.translate(_PUNCT_TABLE)
    collapse_unicode_spaces = getattr(cfg, "nlp_collapse_unicode_spaces", True)
    normalized = _collapse_unicode_spaces(normalized, collapse_unicode_spaces)
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    steps.append("punct_normalize")

    normalized = _normalize_social_tokens(normalized, normalization_events, cfg)
    steps.append("social_hygiene")

    if cfg.nlp_emoji_hint_enabled:
        normalized_emoji_hints, normalized = _extract_emoji_hints(normalized, normalization_events)
    else:
        normalized_emoji_hints = ()
    steps.append("emoji_hint_extract")

    caseful_punct_normalized = caseful_normalized.translate(_PUNCT_TABLE)
    caseful_punct_normalized = _collapse_unicode_spaces(
        caseful_punct_normalized,
        collapse_unicode_spaces,
    )
    caseful_punct_normalized = _MULTI_SPACE_RE.sub(" ", caseful_punct_normalized).strip()
    query_style = detect_search_operator_syntax_in_text(caseful_punct_normalized)

    # -- Steps 6-8 are the bounded "normalize+typo+diacritic" stage. --------
    # Start the stage clock here; deadline is cfg.nlp_normalize_stage_timeout_ms.
    _stage_start = _get_time()

    # -- Step 6: Diacritic restoration (§10.3 hook) -------------------------
    ascii_restored = False
    if _diacritic_restore is None:
        _diacritic_restore = make_diacritic_restorer(cfg, input_source=input_source)
    pre_diacritic = normalized
    normalized = _diacritic_restore(normalized)
    ascii_restored = normalized != pre_diacritic
    steps.append("diacritic_restore")

    # -- Step 6.5: Regional / diaspora dialect normalization (§10.32.4) -----
    normalized, regional_dialect_rewrites, dialect_alternatives = apply_regional_dialect_normalize(normalized)
    steps.append("regional_dialect_normalize")

    # -- Step 6.7: Apostrophe repair for proper nouns (§10.32.5) ------------
    suffix_harmony_repair_events: list[dict[str, str]] = []
    if cfg.nlp_harmony_tolerant_strip_enabled:
        normalized, apostrophe_repairs = repair_apostrophe_proper_noun(
            normalized,
            original_text=caseful_normalized,
            event_sink=suffix_harmony_repair_events.append,
            input_source=input_source,
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
    for tok in raw_tokens:
        if len(tok) > repeat_collapse_max_len:
            continue
        collapsed_tokens.append(collapse_repeated_chars(tok, allowlist=repeat_allowlist))
    raw_tokens = collapsed_tokens
    steps.append("repeat_collapse")

    # -- Step 7.2: Turkish numeric context disambiguation (§10.24.11) ---------
    _annotate_numeric_context(raw_tokens, normalization_events)

    # -- Step 7.5: No-space compound splitting (§10.28.3) ----------------------
    if _compound_splitter_lookup is not None:
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
        steps.append("postposition_stack")
        steps.append("dialect_normalize")
        steps.append("typo_correct")
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
            idiom_events=tuple(),
            vocatives_stripped=tuple(),
            abbreviations_expanded=frozenset(),
            soft_abbreviations_tagged=frozenset(),
            slurs_stripped=tuple(),
            postposition_stack_matches=tuple(),
            postposition_stack_unknowns=tuple(),
            morphology_candidates=morphology_candidates,
            morphology_events=tuple(morphology_events),
            normalization_events=tuple(normalization_events),
        )

    # -- Step 8a: Particle normalization (§10.22.4) -------------------------
    # Detaches mi/mı/mu/mü question particles and annotates de/da/ki.
    # Runs before typo correction so the classifier (§10.4) sees the canonical
    # (always-detached) particle form.  Fixpoint: idempotent on its own output.
    particle_tokens, _particle_repairs = _normalize_particles(raw_tokens)
    steps.append("particle_normalize")

    # -- Step 8a.1: Assimilation normalization (§10.28.2) ----------------------
    if _assimilation_lookup is not None:
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
    if _consonant_alternation_lookup is not None:
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

    # -- Step 8b: Dialect / abbreviation / vocative normalization (§10.22.5) --
    # Applied after particle normalization and before typo correction so the
    # classifier sees canonical spoken-Turkish forms and team entity IDs.
    # Sub-steps (in order):
    #   i.  Multi-token compound rules (negation_q_compound, etc.)
    #   i.  Single-token phonological rules (gerund_r_drop, future_contracted)
    #   i.  Seed-lookup fallback for non-rule forms
    #   ii. Vocative/filler stripping (abi, reis, hocam, …)
    #   iii.Hard abbreviation expansion (GS → galatasaray, etc.)
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

    politeness_tokens, politeness_class = strip_politeness_markers(dialect_tokens)
    idiom_tokens, idiom_events = expand_idioms(politeness_tokens, normalized)
    intent_modifier, _modifier_tense = detect_conditional_modifier(idiom_tokens)
    sarcasm_modifier = detect_sarcastic_modifier(idiom_tokens)
    if sarcasm_modifier != "none":
        if isinstance(intent_modifier, tuple):
            if sarcasm_modifier not in intent_modifier:
                intent_modifier = (*intent_modifier, sarcasm_modifier)
        elif intent_modifier == "none":
            intent_modifier = sarcasm_modifier
        elif intent_modifier != sarcasm_modifier:
            intent_modifier = (intent_modifier, sarcasm_modifier)

    # -- Step 8: Token-level typo correction (§10.3 hook) -------------------
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
        politeness_class=politeness_class,
        query_style=query_style,
        intent_modifier=intent_modifier,
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
        morphology_candidates=morphology_candidates,
        morphology_events=tuple(morphology_events),
    )
    _record_nlp_input_repair_metrics(result, len(tokens), confusables_folded, ascii_restored)
    return result
