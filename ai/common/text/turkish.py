"""Turkish-specific text helpers (codepoint-explicit; NEVER str.lower()).

Key doctrines:
- ``lowercase_tr`` uses an explicit codepoint translation table for I->i_dot_less
  and dotted-I->i, covering the two cases where str.lower() produces the WRONG
  result for Turkish text (English str.lower("I") -> "i", but Turkish needs
  "I" -> "\u0131" (dotless-i) and "\u0130" -> "i").
- No LLM usage anywhere in this module (AGENTS.md Rule 4).
- No external dependencies -- stdlib only.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

# Explicit codepoint translation table for Turkish case mapping.
#
# The two critical Turkish-specific pairs that str.lower() gets wrong:
#   U+0049 LATIN CAPITAL LETTER I         -> U+0131 LATIN SMALL LETTER DOTLESS I
#   U+0130 LATIN CAPITAL LETTER I WITH DOT -> U+0069 LATIN SMALL LETTER I
#
# All other uppercase -> lowercase pairs (A->a, B->b, ...) are handled by the
# subsequent str.lower() call.  After translate(), the string contains no U+0049
# or U+0130 characters, so str.lower() cannot clobber them.
_TR_LOWER_TABLE: dict[int, int] = {
    ord("I"): ord("\u0131"),   # U+0049 -> U+0131 (dotless-i, the critical TR mapping)
    ord("\u0130"): ord("i"),   # U+0130 -> U+0069 (dotted-I -> dotted-i)
}


def lowercase_tr(text: str) -> str:
    """Lowercase a Turkish string using the codepoint-explicit Turkish rules.

    Applies the Turkish-specific I->dotless-i and dotted-I->i mappings first,
    then calls str.lower() on the result.  Because the Turkish-specific
    characters have already been remapped, str.lower() can no longer clobber
    them (there are no remaining U+0049 or U+0130 in the string).

    Safe to call on mixed Turkish/ASCII strings -- pure ASCII strings are
    handled identically to str.lower() EXCEPT for any "I" chars which become
    "\u0131" (correct for Turkish context).
    """
    return text.translate(_TR_LOWER_TABLE).lower()


_REPEAT_COLLAPSE_RE = re.compile(r"(.)\1{2,}")

_REPEAT_ALLOWLIST_PATH: Path = (
    Path(__file__).resolve().parents[2]
    / "nlp"
    / "lang_tr"
    / "repeat_allowlist.tr.yaml"
)

_REPEAT_ALLOWLIST_CACHE: set[str] | None = None


def load_repeat_allowlist(path: Path | None = None) -> set[str]:
    """Load the closed triple-char allowlist used by repeat-collapse."""
    global _REPEAT_ALLOWLIST_CACHE
    if path is None and _REPEAT_ALLOWLIST_CACHE is not None:
        return _REPEAT_ALLOWLIST_CACHE

    effective = path or _REPEAT_ALLOWLIST_PATH
    if not _YAML_AVAILABLE or not effective.exists():
        return set()

    with open(effective, "r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh) or {}

    allowlist = {
        str(item)
        for item in data.get("allowlist", [])
        if isinstance(item, str)
    }
    if path is None:
        _REPEAT_ALLOWLIST_CACHE = allowlist
    return allowlist


def collapse_repeated_chars(token: str, allowlist: set[str] | None = None) -> str:
    """Collapse excessive repeated chars in a Turkish token to at most two.

    This preserves intentional Turkish doubles like "saat" and "dikkat",
    while reducing emphatic runs like "evettttt" -> "evett".
    """
    if allowlist is None:
        allowlist = load_repeat_allowlist()
    if token in allowlist:
        return token
    return _REPEAT_COLLAPSE_RE.sub(r"\1\1", token)


# Turkish vowel harmony tables for suffix checking (§10.9 gate 6).
# Simplified rule check: we verify that common suffixes respect vowel harmony.
# This is NOT a full morphological analyzer — just a probabilistic probe that
# samples 5 random constructions and rejects if any violates basic harmony.
#
# Two harmony rules:
#   - **Back/front**: e,i,ö,ü are front; a,ı,o,u are back.
#   - **Rounded/unrounded**: o,ö,u,ü are rounded; a,e,ı,i are unrounded.
#
# Common suffixes + their harmony requirements (simplified):
#   -'ın/-'in/-'un/-'ün (genitive): picks variant based on last vowel in stem.
#   -'a/-'e (dative)
#   -'dan/-'den (ablative)
#   -'ı/-'i/-'u/-'ü (accusative)
#
# We match pattern `<word>'<suffix>` and verify the suffix's first vowel
# matches the stem's last vowel along the back/front axis.

_FRONT_VOWELS = frozenset("eiöü")
_BACK_VOWELS = frozenset("aıou")


def suffix_harmony_ok(construction: str) -> bool:
    """Check if a noun+suffix construction respects Turkish vowel harmony.

    Args:
        construction: A string like "Galatasaray'ın" or "takım'a" (apostrophe
            separates stem from suffix).

    Returns:
        True if the suffix's first vowel harmonizes with the stem's last vowel
        (back/front agreement), or if the construction doesn't contain an
        apostrophe, or if the stem has no vowels (fallback: assume OK).
        False if there's a clear harmony violation.

    Examples:
        >>> suffix_harmony_ok("Galatasaray'ın")  # back stem 'a', back suffix 'ı'
        True
        >>> suffix_harmony_ok("Fenerbahçe'nin")  # front stem 'e', front suffix 'i'
        True
        >>> suffix_harmony_ok("takım'a")         # back stem 'ı', back suffix 'a'
        True
        >>> suffix_harmony_ok("takım'e")         # back stem 'ı', front suffix 'e' — BAD
        False

    Notes:
        This is a **simplified** check for the proofreader probe (§10.9 gate 6).
        It does NOT handle all Turkish morphology edge cases (consonant assimilation,
        compound words, loanwords with exceptional harmony). It's a heuristic to
        catch gross LLM-generated suffix errors, not a replacement for a full parser.
    """
    if "'" not in construction:
        # No apostrophe → no suffix boundary → assume OK (might be a bare noun).
        return True

    stem, suffix = construction.rsplit("'", 1)
    stem_lower = stem.lower()
    suffix_lower = suffix.lower()

    # Find last vowel in stem.
    stem_last_vowel = None
    for char in reversed(stem_lower):
        if char in _FRONT_VOWELS or char in _BACK_VOWELS:
            stem_last_vowel = char
            break

    if stem_last_vowel is None:
        # Stem has no vowels (e.g., initialism like "TFF'ye"). Fallback: assume OK.
        return True

    # Find first vowel in suffix.
    suffix_first_vowel = None
    for char in suffix_lower:
        if char in _FRONT_VOWELS or char in _BACK_VOWELS:
            suffix_first_vowel = char
            break

    if suffix_first_vowel is None:
        # Suffix has no vowels (rare but possible for consonant-only suffixes). Assume OK.
        return True

    # Check back/front agreement.
    stem_is_front = stem_last_vowel in _FRONT_VOWELS
    suffix_is_front = suffix_first_vowel in _FRONT_VOWELS

    return stem_is_front == suffix_is_front


@dataclass(frozen=True)
class MorphCandidate:
    root: str
    suffix_class: str
    pos: str
    confidence: float
    ambiguity_class: str = "unique"


def normalize_morph_candidates(
    candidates: list[MorphCandidate],
    topk: int = 3,
    min_confidence: float = 0.55,
) -> list[MorphCandidate]:
    """Retain deterministic top-K morphology candidates with ambiguity flags.

    This helper supports §10.26.1 by making candidate selection stable and by
    marking low-confidence parses as high ambiguity without silently dropping
    them from the morphology stage.
    """
    if topk < 1:
        raise ValueError("topk must be >= 1")

    sorted_candidates = sorted(
        candidates,
        key=lambda c: (-c.confidence, c.root, c.suffix_class, c.pos),
    )
    retained = sorted_candidates[:topk]
    if not retained:
        return []

    result: list[MorphCandidate] = []
    for candidate in retained:
        if candidate.confidence < min_confidence:
            ambiguity_class = "high"
        elif len(retained) == 1:
            ambiguity_class = "unique"
        else:
            ambiguity_class = "low"
        result.append(
            MorphCandidate(
                root=candidate.root,
                suffix_class=candidate.suffix_class,
                pos=candidate.pos,
                confidence=candidate.confidence,
                ambiguity_class=ambiguity_class,
            )
        )
    return result


_MORPH_POS_PREFERENCES_PATH: Path = (
    Path(__file__).resolve().parents[2]
    / "nlp"
    / "lang_tr"
    / "morph_pos_preferences.tr.yaml"
)
_MORPH_POS_PREFERENCES_CACHE: dict[str, list[str]] | None = None


def load_morph_pos_preferences(path: Path | None = None) -> dict[str, list[str]]:
    """Load the closed POS-preference table used by morphology arbitration."""
    global _MORPH_POS_PREFERENCES_CACHE
    if path is None and _MORPH_POS_PREFERENCES_CACHE is not None:
        return _MORPH_POS_PREFERENCES_CACHE

    effective = path or _MORPH_POS_PREFERENCES_PATH
    if not _YAML_AVAILABLE:
        return {}

    with open(effective, "r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh) or {}

    table: dict[str, list[str]] = {}
    for entry in data.get("intent_pos_preferences", []):
        if not isinstance(entry, dict):
            continue
        intent_class = entry.get("intent_class")
        pos_order = entry.get("pos_order")
        if isinstance(intent_class, str) and isinstance(pos_order, list):
            table[intent_class] = [str(item) for item in pos_order if isinstance(item, str)]

    if path is None:
        _MORPH_POS_PREFERENCES_CACHE = table
    return table


def resolve_morph_candidates(
    candidates: list[MorphCandidate],
    gazetteer_roots: set[str] | None = None,
    intent_class: str | None = None,
    context_preferred_pos: str | None = None,
    pos_preferences: dict[str, list[str]] | None = None,
) -> list[MorphCandidate]:
    """Rank candidate parses deterministically for §10.26.1 arbitration.

    The ordering is:
      1. Gazetteer cross-check wins.
      2. Co-token context preference wins.
      3. Intent-class POS preference wins.
      4. Confidence rank wins.
      5. Deterministic lexical tie-break by root/suffix/pos.
    """
    if not candidates:
        return []

    if pos_preferences is None:
        pos_preferences = load_morph_pos_preferences()

    def gazetteer_score(candidate: MorphCandidate) -> int:
        if gazetteer_roots is None:
            return 0
        return 1 if candidate.root in gazetteer_roots else 0

    def context_score(candidate: MorphCandidate) -> int:
        return 1 if context_preferred_pos and candidate.pos == context_preferred_pos else 0

    def intent_pos_score(candidate: MorphCandidate) -> int:
        if intent_class is None:
            return 0
        order = pos_preferences.get(intent_class)
        if not order:
            return 0
        if candidate.pos not in order:
            return 0
        return len(order) - order.index(candidate.pos)

    return sorted(
        candidates,
        key=lambda candidate: (
            -gazetteer_score(candidate),
            -context_score(candidate),
            -intent_pos_score(candidate),
            -candidate.confidence,
            candidate.root,
            candidate.suffix_class,
            candidate.pos,
        ),
    )


# ---------------------------------------------------------------------------
# §10.22.2 — Proper-noun suffix stripper
# ---------------------------------------------------------------------------
# These imports are at the bottom of the file to avoid circular-import issues
# at module load time; yaml and pathlib are stdlib / lightweight deps.
import pathlib as _pathlib  # noqa: E402  (module-level import after code is fine)

try:
    import yaml as _yaml  # type: ignore[import]
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False

# Default path: ai/nlp/lang_tr/suffix_families.tr.yaml, resolved relative to
# this file's location so the module works regardless of cwd.
_SUFFIX_FAMILIES_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent  # ai/common/text/
    .parent                          # ai/common/
    .parent                          # ai/
    / "nlp"
    / "lang_tr"
    / "suffix_families.tr.yaml"
)

# Module-level cache; populated on first call.
_SUFFIX_FAMILIES_CACHE: "list[dict] | None" = None

_NO_STRIP_CANONICALS_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent  # ai/common/text/
    .parent                          # ai/common/
    .parent                          # ai/
    / "nlp"
    / "lang_tr"
    / "_no_strip_canonicals.tr.yaml"
)

_NO_STRIP_CANONICALS_CACHE: "set[str] | None" = None

# Characters valid as suffix candidates per spec regex [a-zçğıiöşü].
# Using a broad set covering all Turkish lowercase letters + ASCII lowercase.
_SUFFIX_CHARS: frozenset = frozenset("abcçdefgğhıijklmnoöprsştuüvyz")

# Turkish + Latin uppercase letters that signal a proper-noun token start.
_TR_UPPER: frozenset = frozenset("ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ")


def _load_suffix_families(
    path: "_pathlib.Path | None" = None,
) -> "list[dict]":
    """Load and module-cache the suffix family table from YAML.

    The YAML at ``ai/nlp/lang_tr/suffix_families.tr.yaml`` is the single
    source of truth.  When *path* is ``None`` the module-level cache is used
    after the first load; pass an explicit path to override (e.g. in tests).
    """
    global _SUFFIX_FAMILIES_CACHE
    if path is None and _SUFFIX_FAMILIES_CACHE is not None:
        return _SUFFIX_FAMILIES_CACHE
    effective = path or _SUFFIX_FAMILIES_PATH
    if not _YAML_AVAILABLE:  # pragma: no cover
        return []
    with open(effective, "r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh)
    families: "list[dict]" = data.get("suffix_families", [])
    if path is None:
        _SUFFIX_FAMILIES_CACHE = families
    return families


def _load_no_strip_canonicals(
    path: "_pathlib.Path | None" = None,
) -> "set[str]":
    """Load the canonical-prefix guard list for harmony-tolerant suffix stripping."""
    global _NO_STRIP_CANONICALS_CACHE
    if path is None and _NO_STRIP_CANONICALS_CACHE is not None:
        return _NO_STRIP_CANONICALS_CACHE
    effective = path or _NO_STRIP_CANONICALS_PATH
    if not _YAML_AVAILABLE or not effective.exists():  # pragma: no cover
        canonicals: set[str] = set()
    else:
        with open(effective, "r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        raw = data.get("no_strip_canonicals", [])
        canonicals = {
            lowercase_tr(str(item).strip())
            for item in raw
            if isinstance(item, str) and item.strip()
        }
    if path is None:
        _NO_STRIP_CANONICALS_CACHE = canonicals
    return canonicals


_DIGIT_LETTER_CONFUSABLES_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent
    .parent
    .parent
    / "nlp"
    / "lang_tr"
    / "digit_letter_confusables.tr.yaml"
)
_DIGIT_LETTER_CONFUSABLES_CACHE: "dict[str, str] | None" = None

_YEAR_SUFFIX_ALLOWLIST_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent
    .parent
    .parent
    / "nlp"
    / "lang_tr"
    / "year_suffix_allowlist.tr.yaml"
)
_YEAR_SUFFIX_ALLOWLIST_CACHE: "set[str] | None" = None

_DIGIT_LETTER_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def load_digit_letter_confusables(path: _pathlib.Path | None = None) -> "dict[str, str]":
    """Load the digit-letter confusables table for Phase 10 §10.24.3."""
    global _DIGIT_LETTER_CONFUSABLES_CACHE
    if path is None and _DIGIT_LETTER_CONFUSABLES_CACHE is not None:
        return _DIGIT_LETTER_CONFUSABLES_CACHE

    effective = path or _DIGIT_LETTER_CONFUSABLES_PATH
    if not _YAML_AVAILABLE or not effective.exists():  # pragma: no cover
        mapping: dict[str, str] = {}
    else:
        with open(effective, "r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        raw_map = data.get("mapping", {})
        mapping = {
            str(k): str(v)
            for k, v in raw_map.items()
            if isinstance(k, str) and isinstance(v, str)
        }
    if path is None:
        _DIGIT_LETTER_CONFUSABLES_CACHE = mapping
    return mapping


def load_year_suffix_allowlist(path: _pathlib.Path | None = None) -> "dict[str, str]":
    """Load the allowed year-suffix tokens that must survive digit folding."""
    global _YEAR_SUFFIX_ALLOWLIST_CACHE
    if path is None and _YEAR_SUFFIX_ALLOWLIST_CACHE is not None:
        return _YEAR_SUFFIX_ALLOWLIST_CACHE

    effective = path or _YEAR_SUFFIX_ALLOWLIST_PATH
    if not _YAML_AVAILABLE or not effective.exists():  # pragma: no cover
        allowlist: dict[str, str] = {}
    else:
        with open(effective, "r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        raw = data.get("year_suffix_allowlist", [])
        allowlist = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            abbr = entry.get("abbreviation")
            year = entry.get("year")
            canonical_id = entry.get("canonical_id")
            if isinstance(abbr, str) and isinstance(year, str) and isinstance(canonical_id, str):
                allowlist[f"{abbr}{year}".lower()] = canonical_id
    if path is None:
        _YEAR_SUFFIX_ALLOWLIST_CACHE = allowlist
    return allowlist


def digit_letter_confusable_fold(
    text: str,
    fold_map: "dict[str, str] | None" = None,
    year_suffix_allowlist: "dict[str, str] | None" = None,
) -> str:
    """Fold digit-letter confusables in Turkish input while preserving year suffixes."""
    if fold_map is None:
        fold_map = load_digit_letter_confusables()
    if year_suffix_allowlist is None:
        year_suffix_allowlist = load_year_suffix_allowlist()

    def _replace(match: "re.Match[str]") -> str:
        token = match.group(0)
        if token.lower() in year_suffix_allowlist:
            return token
        if not any(ch.isdigit() for ch in token):
            return token
        if not any(ch.isalpha() for ch in token):
            return token
        return "".join(fold_map.get(ch, ch) for ch in token)

    return _DIGIT_LETTER_TOKEN_RE.sub(_replace, text)


_NUMBER_WORDS_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent
    .parent
    .parent
    / "nlp"
    / "lang_tr"
    / "number_words.tr.yaml"
)

_NUMBER_WORDS_CACHE: "dict[str, int] | None" = None

_DEFAULT_NUMBER_WORDS: dict[str, int] = {
    "sıfır": 0,
    "bir": 1,
    "iki": 2,
    "üç": 3,
    "dört": 4,
    "beş": 5,
    "altı": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "yirmi": 20,
    "otuz": 30,
    "kırk": 40,
    "elli": 50,
    "altmış": 60,
    "yetmiş": 70,
    "seksen": 80,
    "doksan": 90,
    "yüz": 100,
    "bin": 1000,
    "milyon": 1000000,
}


def _load_number_words(path: "_pathlib.Path | None" = None) -> "dict[str, int]":
    """Load and cache the Turkish number-word mapping from YAML.

    If PyYAML is unavailable or the YAML data cannot be read, fall back to a
    built-in default mapping so parser behavior remains deterministic in
    minimal environments.
    """
    global _NUMBER_WORDS_CACHE
    if path is None and _NUMBER_WORDS_CACHE is not None:
        return _NUMBER_WORDS_CACHE
    effective = path or _NUMBER_WORDS_PATH
    if not _YAML_AVAILABLE or not effective.exists():
        mapping = dict(_DEFAULT_NUMBER_WORDS)
    else:
        with open(effective, "r", encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        mapping = {}
        raw = data.get("number_words", {})
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, int):
                    mapping[key] = value
    if path is None:
        _NUMBER_WORDS_CACHE = mapping
    return mapping


def parse_number_word(text: str) -> int | None:
    """Parse a Turkish number phrase into an integer.

    Supports both single-word numbers like ``"bir"`` and composite
    forms like ``"yirmi bir"`` or ``"iki yüz otuz dört"``.

    Returns ``None`` when the phrase cannot be parsed from the
    configured ``ai/nlp/lang_tr/number_words.tr.yaml`` table.
    """
    text = lowercase_tr(text.strip())
    if not text:
        return None

    words = [tok for tok in text.replace("-", " ").split() if tok]
    if not words:
        return None

    number_words = _load_number_words()
    total = 0
    current = 0
    for word in words:
        value = number_words.get(word)
        if value is None:
            return None
        if value >= 1000:
            if current == 0:
                current = 1
            current *= value
            total += current
            current = 0
        elif value == 100:
            if current == 0:
                current = 1
            current *= value
        else:
            current += value

    total += current
    return total


_CARDINAL_NUMBER_WORDS: dict[int, str] = {
    0: "sıfır",
    1: "bir",
    2: "iki",
    3: "üç",
    4: "dört",
    5: "beş",
    6: "altı",
    7: "yedi",
    8: "sekiz",
    9: "dokuz",
    10: "on",
    20: "yirmi",
    30: "otuz",
    40: "kırk",
    50: "elli",
    60: "altmış",
    70: "yetmiş",
    80: "seksen",
    90: "doksan",
    100: "yüz",
    1000: "bin",
    1000000: "milyon",
}

_FRONT_VOWELS = {"e", "i", "ö", "ü"}
_BACK_VOWELS = {"a", "ı", "o", "u"}


def _ordinal_suffix_for_word(word: str) -> str:
    last_vowel: str | None = None
    for ch in reversed(lowercase_tr(word)):
        if ch in _FRONT_VOWELS or ch in _BACK_VOWELS:
            last_vowel = ch
            break

    if last_vowel is None:
        return "inci"
    if last_vowel in {"e", "i"}:
        return "inci"
    if last_vowel in {"ö", "ü"}:
        return "üncü"
    if last_vowel in {"a", "ı"}:
        return "ıncı"
    return "inci"


def int_to_number_word(value: int, register: str = "cardinal") -> str:
    """Convert an integer to a Turkish number-word phrase.

    Supports ``register='cardinal'`` and ``register='ordinal'``.
    """
    if register not in {"cardinal", "ordinal"}:
        raise ValueError("register must be 'cardinal' or 'ordinal'")
    if value < 0 or value > 999999999:
        raise ValueError("value must be between 0 and 999_999_999")

    def _cardinal(n: int) -> str:
        if n == 0:
            return _CARDINAL_NUMBER_WORDS[0]
        parts: list[str] = []
        millions = n // 1000000
        if millions:
            if millions > 1:
                parts.append(_cardinal(millions))
            parts.append(_CARDINAL_NUMBER_WORDS[1000000])
            n %= 1000000
        thousands = n // 1000
        if thousands:
            if thousands > 1:
                parts.append(_cardinal(thousands))
            parts.append(_CARDINAL_NUMBER_WORDS[1000])
            n %= 1000
        hundreds = n // 100
        if hundreds:
            if hundreds > 1:
                parts.append(_CARDINAL_NUMBER_WORDS[hundreds])
            parts.append(_CARDINAL_NUMBER_WORDS[100])
            n %= 100
        tens = n // 10 * 10
        if tens:
            parts.append(_CARDINAL_NUMBER_WORDS[tens])
            n %= 10
        if n:
            parts.append(_CARDINAL_NUMBER_WORDS[n])
        return " ".join(parts)

    cardinal_phrase = _cardinal(value)
    if register == "cardinal":
        return cardinal_phrase

    if value == 0:
        return "sıfırıncı"

    words = cardinal_phrase.split()
    last_word = words[-1]
    if last_word == "iki":
        words[-1] = "ikinci"
    else:
        words[-1] = last_word + _ordinal_suffix_for_word(last_word)
    return " ".join(words)


def _suffix_harmonizes(suffix: str, stem_last_vowel: "str | None") -> bool:
    """Return True if the suffix's first vowel agrees front/back with *stem_last_vowel*.

    When either the stem or suffix has no vowel (initialism / consonant-only
    suffix) harmony cannot be checked and True is returned so the candidate
    remains in play for gazetteer validation.
    """
    suffix_vowel: "str | None" = None
    for ch in suffix:
        if ch in _FRONT_VOWELS or ch in _BACK_VOWELS:
            suffix_vowel = ch
            break
    if stem_last_vowel is None or suffix_vowel is None:
        return True
    return (stem_last_vowel in _FRONT_VOWELS) == (suffix_vowel in _FRONT_VOWELS)


def _match_suffix_family(
    suffix_candidate: str,
    stem: str,
    families: "list[dict]",
    *,
    ignore_harmony: bool = False,
) -> "str | None":
    """Return the family name if *suffix_candidate* is a valid suffix for *stem*.

    The generalising rule is vowel-harmony: the suffix's first vowel must
    agree front/back with the stem's last vowel.  The YAML table provides all
    known surface forms; no literal suffix strings appear here.

    When ``ignore_harmony=True``, a second-pass harmony-tolerant strip is
    allowed for malformed suffix spellings that still belong to a known
    grammatical family.
    """
    # Compute last vowel of stem (using lowercase_tr for correct TR mapping).
    stem_lower = lowercase_tr(stem)
    last_vowel: "str | None" = None
    for ch in reversed(stem_lower):
        if ch in _FRONT_VOWELS or ch in _BACK_VOWELS:
            last_vowel = ch
            break

    if not ignore_harmony and not _suffix_harmonizes(suffix_candidate, last_vowel):
        return None

    # Check suffix against all known forms in each family (both stem-final
    # categories combined) — we don't know the original stem-final char type
    # when the apostrophe is absent, so we check both.
    for family in families:
        all_forms: "set[str]" = set(
            list(family.get("vowel_final_forms", []))
            + list(family.get("consonant_final_forms", []))
        )
        if suffix_candidate in all_forms:
            return family["name"]
    return None


def is_harmony_tolerant_suffix_candidate(
    candidate: str,
    *,
    _families: "list[dict] | None" = None,
) -> "str | None":
    """Return the suffix family when *candidate* is valid only in ignore-harmony mode.

    This is used to detect harmony-tolerant repairs such as ``Fenerbahçe'ya``.
    Returns ``None`` when the candidate is either not a valid suffix or it is
    harmonically valid already.
    """
    if "'" not in candidate:
        return None

    stem, suffix = candidate.rsplit("'", 1)
    families = _families if _families is not None else _load_suffix_families()

    if _match_suffix_family(suffix, stem, families, ignore_harmony=False) is not None:
        return None

    return _match_suffix_family(suffix, stem, families, ignore_harmony=True)


def strip_proper_noun_suffix(
    token: str,
    assume_proper: bool = False,
    *,
    no_strip_canonicals: "set[str] | None" = None,
    _families: "list[dict] | None" = None,
    allow_harmony_tolerance: bool = False,
) -> "tuple[str, str | None]":
    """Strip a Turkish grammatical suffix from a proper-noun token.

    Pre-gazetteer step (§10.22.2): recovers the canonical stem so the
    gazetteer can perform an exact-match lookup.  The suffix families and
    their harmonically valid surface forms are loaded from
    ``ai/nlp/lang_tr/suffix_families.tr.yaml`` — no literal suffix strings
    live in this function.

    The function is intentionally permissive: it may return a "false-positive"
    stem (e.g. ``"Ankar"`` from ``"Ankara"``).  The gazetteer validates
    whether the stem resolves to a real entity and falls back to the original
    token when the stripped stem is not found.

    Parameters
    ----------
    token:
        A single token, either with original casing (e.g. ``"Galatasaray'ın"``)
        or lowercased (e.g. ``"galatasarayın"`` — requires ``assume_proper=True``).
    assume_proper:
        When ``True``, the proper-noun check (uppercase-start) is bypassed and
        suffix stripping is attempted regardless of casing.  Use when the caller
        knows the token is a proper noun after normalization lowercasing.
    _families:
        Pre-loaded suffix family list (for testing / hot-reload).  When
        ``None``, the module-level cached table is used.

    Returns
    -------
    (stem, suffix_class)
        *stem* is the token with the grammatical suffix stripped; suitable for
        gazetteer lookup.  *suffix_class* is the family name (``"genitive"``,
        ``"dative"``, …).  When no suffix is detected returns ``(token, None)``.

    Notes
    -----
    * Only ASCII apostrophe ``'`` (U+0027) must reach this function.  The
      normalization pipeline (§10.1 step 5, §10.22.2 apostrophe-noise bullet)
      converts all typographic apostrophes before tokenisation.
    """
    if not token:
        return token, None

    # Proper-noun check: token must start with Turkish/Latin uppercase OR
    # assume_proper=True.
    if not assume_proper and token[0] not in _TR_UPPER:
        return token, None

    families = _families if _families is not None else _load_suffix_families()
    no_strip_canonicals = (
        no_strip_canonicals
        if no_strip_canonicals is not None
        else _load_no_strip_canonicals()
    )

    # ── Case 1: token contains an apostrophe ─────────────────────────────────
    # Expected form: <STEM>'<suffix> — only the LAST apostrophe is authoritative.
    if "'" in token:
        apos_idx = token.rindex("'")
        stem_part = token[:apos_idx]
        suffix_part = token[apos_idx + 1:]
        # Suffix must be 1–4 lowercase Turkish chars (per spec regex group).
        if (
            1 <= len(suffix_part) <= 4
            and all(c in _SUFFIX_CHARS for c in suffix_part)
            and stem_part  # stem must not be empty
        ):
            family = _match_suffix_family(suffix_part, stem_part, families)
            if family is not None:
                candidate_canonical = lowercase_tr(stem_part + suffix_part)
                if candidate_canonical in no_strip_canonicals:
                    return token, None
                return stem_part, family
            if allow_harmony_tolerance:
                family = _match_suffix_family(
                    suffix_part,
                    stem_part,
                    families,
                    ignore_harmony=True,
                )
                if family is not None:
                    candidate_canonical = lowercase_tr(stem_part + suffix_part)
                    if candidate_canonical in no_strip_canonicals:
                        return token, None
                    return stem_part, family
        # Apostrophe present but split did not yield a valid suffix
        # (e.g. misplaced apostrophe like "Galata'sarayın").  Return as-is.
        return token, None

    # ── Case 2: no apostrophe — scan suffix lengths longest-first ───────────
    # Greedy: try 4 → 1 chars.  Longest valid suffix wins to avoid partial
    # stems.  The gazetteer validates the returned stem independently.
    for suffix_len in range(4, 0, -1):
        if len(token) <= suffix_len:
            continue
        stem_part = token[:-suffix_len]
        suffix_part = token[-suffix_len:]
        if not all(c in _SUFFIX_CHARS for c in suffix_part):
            continue  # Non-Turkish char in candidate suffix → skip
        family = _match_suffix_family(suffix_part, stem_part, families)
        if family is not None:
            candidate_canonical = lowercase_tr(stem_part + suffix_part)
            if candidate_canonical in no_strip_canonicals:
                continue
            return stem_part, family

    # Second-pass harmony-tolerant strip (§10.24.1): if a trailing 1–4 char
    # candidate belongs to a known suffix family but violates vowel harmony,
    # accept it as malformed suffix spelling for proper-noun recovery.
    for suffix_len in range(4, 0, -1):
        if len(token) <= suffix_len:
            continue
        stem_part = token[:-suffix_len]
        suffix_part = token[-suffix_len:]
        if not all(c in _SUFFIX_CHARS for c in suffix_part):
            continue
        family = _match_suffix_family(
            suffix_part,
            stem_part,
            families,
            ignore_harmony=True,
        )
        if family is not None:
            candidate_canonical = lowercase_tr(stem_part + suffix_part)
            if candidate_canonical in no_strip_canonicals:
                continue
            return stem_part, family

    return token, None


# ---------------------------------------------------------------------------
# §10.22.3 — Buffer-consonant renderer
# ---------------------------------------------------------------------------
# Paths resolved relative to this file so the module is cwd-independent.
_BUFFER_TABLE_PATH: "_pathlib.Path" = (
    _pathlib.Path(__file__).parent  # ai/common/text/
    .parent                          # ai/common/
    .parent                          # ai/
    / "nlp"
    / "lang_tr"
    / "buffer_consonant.tr.yaml"
)
_FOREIGN_OVERRIDES_PATH: "_pathlib.Path" = (
    _pathlib.Path(__file__).parent
    .parent
    .parent
    / "nlp"
    / "lang_tr"
    / "foreign_stem_overrides.tr.yaml"
)

_BUFFER_TABLE_CACHE: "dict[str, str] | None" = None
_PRONUNCIATION_CLASS_CACHE: "dict[str, str] | None" = None


def _load_buffer_table(
    path: "_pathlib.Path | None" = None,
) -> "dict[str, str]":
    """Load and cache the buffer-consonant decision table from YAML.

    The table at ``buffer_consonant.tr.yaml`` is the single source of truth;
    no literal suffix-class → consonant mappings appear in code.
    """
    global _BUFFER_TABLE_CACHE
    if path is None and _BUFFER_TABLE_CACHE is not None:
        return _BUFFER_TABLE_CACHE
    effective = path or _BUFFER_TABLE_PATH
    if not _YAML_AVAILABLE:  # pragma: no cover
        return {}
    with open(effective, "r", encoding="utf-8") as fh:
        data = _yaml.safe_load(fh)
    table: "dict[str, str]" = data.get("buffer_rules", {})
    if path is None:
        _BUFFER_TABLE_CACHE = table
    return table


def _load_pronunciation_classes(
    path: "_pathlib.Path | None" = None,
) -> "dict[str, str]":
    """Load and cache pronunciation_class overrides from foreign_stem_overrides.tr.yaml.

    Returns {lowercase_stem: pronunciation_class}.
    """
    global _PRONUNCIATION_CLASS_CACHE
    if path is None and _PRONUNCIATION_CLASS_CACHE is not None:
        return _PRONUNCIATION_CLASS_CACHE
    effective = path or _FOREIGN_OVERRIDES_PATH
    if not _YAML_AVAILABLE or not effective.is_file():  # pragma: no cover
        return {}
    with open(effective, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh)
    result: "dict[str, str]" = {}
    for entry in raw.get("overrides", []):
        stem = entry.get("stem", "")
        pc = entry.get("pronunciation_class", "")
        if stem and pc:
            result[stem.lower()] = pc
    if path is None:
        _PRONUNCIATION_CLASS_CACHE = result
    return result


def buffer_consonant(
    stem: str,
    suffix_class: str,
    *,
    _table: "dict[str, str] | None" = None,
    _pronunciations: "dict[str, str] | None" = None,
) -> str:
    """Return the buffer consonant to insert between *stem* and a vowel-initial suffix.

    Generalising rule (§10.22.3):
      - Vowel-initial suffix on a vowel-final stem → insert a buffer consonant
        whose identity is determined by suffix_class via YAML table lookup.
      - Consonant-final stem → return ``''`` (no buffer needed).
      - Foreign-stem ``pronunciation_class`` override takes precedence over
        written last-char detection.

    Returns the single buffer consonant (``'y'``, ``'s'``, ``'n'``, ``'ş'``)
    or ``''`` when no buffer is needed or the class is not in the table
    (e.g. locative, ablative, plural are consonant-initial).
    """
    if not stem:
        return ""

    table = _table if _table is not None else _load_buffer_table()
    prons = _pronunciations if _pronunciations is not None else _load_pronunciation_classes()

    # 1. Foreign-stem pronunciation_class override has highest priority.
    last_token = stem.rsplit(None, 1)[-1] if " " in stem else stem
    pc = prons.get(last_token.lower(), "")
    if pc == "consonant_final":
        return ""
    if pc == "vowel_final":
        return table.get(suffix_class, "")

    # 2. Default: check the last written character (Turkish-lowercased).
    last_char = lowercase_tr(stem[-1])
    if last_char not in (_FRONT_VOWELS | _BACK_VOWELS):
        return ""

    return table.get(suffix_class, "")

