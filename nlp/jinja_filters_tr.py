"""Phase 10 §10.7 — Turkish morphology Jinja2 filters.

Vendored at ``ai/nlp/jinja_filters_tr.py``.  All filters are:

- Deterministic (no LLM, no RNG).
- Suffix-harmony aware via vowel-class tables (vowel harmony only; no full
  morphophonological cascade beyond the final-consonant voicing and apostrophe
  rules required for proper nouns in the closed intent set).
- Registered on the shared Jinja2 Environment in ``ai/nlp/render.py``.

No external dependencies; stdlib only.

Turkish vowel harmony summary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
2-way (e/a)
  Front vowels (e, i, ö, ü) → suffix uses *e*.
  Back  vowels (a, ı, o, u) → suffix uses *a*.

4-way (i/ı/ü/u)
  Front unrounded (e, i) → *i*.
  Back  unrounded (a, ı) → *ı*.
  Front rounded   (ö, ü) → *ü*.
  Back  rounded   (o, u) → *u*.

Voiceless final consonant (çfhkpşt) → locative/ablative use *t*;
voiced or vowel-final → *d*.

Proper nouns (initial uppercase) take an apostrophe before the suffix.

§10.22.2 additions
~~~~~~~~~~~~~~~~~~
- Every morphology filter now accepts ``proper: bool = False``.  When
  ``proper=True`` the apostrophe is injected unconditionally (even for
  lowercased team names after normalization).
- The module loads ``ai/nlp/lang_tr/foreign_stem_overrides.tr.yaml`` to
  resolve ambiguous vowel-class / pronunciation-class for non-Turkish proper
  nouns (initialisms, English words ending in 'y', etc.) when ``proper=True``.
"""
from __future__ import annotations

import datetime as _dt
import pathlib as _pathlib
from typing import Optional
from zoneinfo import ZoneInfo

from common.config import cfg

try:
    import yaml as _yaml  # type: ignore[import]
    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False

# Path to the foreign-stem overrides table (§10.22.2).
_FOREIGN_OVERRIDES_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent / "lang_tr" / "foreign_stem_overrides.tr.yaml"
)

# §10.22.3 — buffer-consonant helper (loaded here, avoids circular imports).
from common.text.turkish import buffer_consonant as _buffer_consonant  # noqa: E402
from common.text.tr_format import (
    tr_format_number,
    tr_format_money,
    tr_format_clock,
    tr_format_date,
    tr_format_date_short,
    tr_format_score,
)

# §10.22.3 — vowel-harmony tables live in YAML, not inline code.
_VOWEL_HARMONY_PATH: _pathlib.Path = (
    _pathlib.Path(__file__).parent / "lang_tr" / "vowel_harmony_4way.tr.yaml"
)


def _load_vowel_sets() -> "tuple[frozenset, frozenset, frozenset, frozenset, frozenset, frozenset, dict, dict]":
    """Load vowel classes, harmony maps, and voiceless set from YAML.

    Returns (FRONT, BACK, ALL_VOWELS, FRONT_ROUNDED, BACK_ROUNDED,
             VOICELESS, FOUR_WAY_MAP, TWO_WAY_MAP).
    Raises ``ImportError`` if the YAML cannot be read (missing installation).
    """
    if not _YAML_AVAILABLE or not _VOWEL_HARMONY_PATH.is_file():  # pragma: no cover
        raise ImportError(
            f"Cannot load vowel harmony table: {_VOWEL_HARMONY_PATH}. "
            "Ensure ai/nlp/lang_tr/ is present."
        )
    with open(_VOWEL_HARMONY_PATH, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh)
    vc = raw["vowel_classes"]
    front_unrounded = frozenset(vc["front_unrounded"])
    front_rounded   = frozenset(vc["front_rounded"])
    back_unrounded  = frozenset(vc["back_unrounded"])
    back_rounded    = frozenset(vc["back_rounded"])
    front = front_unrounded | front_rounded
    back  = back_unrounded  | back_rounded
    all_vowels = front | back
    voiceless = frozenset(raw.get("voiceless_consonants", []))
    four_way  = dict(raw.get("four_way_map", {}))
    two_way   = dict(raw.get("two_way_map", {}))
    return front, back, all_vowels, front_rounded, back_rounded, voiceless, four_way, two_way


(
    _FRONT, _BACK, _ALL_VOWELS,
    _FRONT_ROUNDED, _BACK_ROUNDED,
    _VOICELESS,
    _FOUR_WAY_MAP, _TWO_WAY_MAP,
) = _load_vowel_sets()

# Module-level cache: {lowercase_stem: {"vowel_class": str, "pronunciation_class": str}}
_FOREIGN_OVERRIDES_CACHE: "Optional[dict[str, dict]]" = None


def _load_foreign_overrides() -> "dict[str, dict]":
    """Load and cache the foreign-stem override table (lazy, thread-safe for CPython).

    Returns a dict keyed by *lowercase* stem for O(1) lookup.
    """
    global _FOREIGN_OVERRIDES_CACHE
    if _FOREIGN_OVERRIDES_CACHE is not None:
        return _FOREIGN_OVERRIDES_CACHE
    if not _YAML_AVAILABLE or not _FOREIGN_OVERRIDES_PATH.is_file():  # pragma: no cover
        _FOREIGN_OVERRIDES_CACHE = {}
        return _FOREIGN_OVERRIDES_CACHE
    with open(_FOREIGN_OVERRIDES_PATH, "r", encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh)
    result: "dict[str, dict]" = {}
    for entry in raw.get("overrides", []):
        stem = entry.get("stem", "")
        if stem:
            result[stem.lower()] = {
                "vowel_class": entry.get("vowel_class", ""),
                "pronunciation_class": entry.get("pronunciation_class", ""),
            }
    _FOREIGN_OVERRIDES_CACHE = result
    return result


def _get_stem_override(word: str) -> "Optional[dict]":
    """Look up the last whitespace-separated token of *word* in the overrides table.

    For "Manchester City" the lookup key is "city" (last token, lowercase).
    Returns None when no override is found.
    """
    # Use the last token (handles multi-word proper nouns like "Manchester City").
    last_token = word.rsplit(None, 1)[-1] if word else ""
    if not last_token:
        return None
    return _load_foreign_overrides().get(last_token.lower())

# Vowel sets loaded from YAML — see _load_vowel_sets() above.

# Turkish weekday names (Monday=0 \u2026 Sunday=6, matching datetime.weekday())
_WEEKDAYS_TR: tuple[str, ...] = (
    "Pazartesi",    # 0
    "Sal\u0131",   # 1
    "\u00c7ar\u015famba",  # 2
    "Per\u015fembe",        # 3
    "Cuma",         # 4
    "Cumartesi",    # 5
    "Pazar",        # 6
)

# Default confidence bands: [[lower_inclusive, upper_exclusive, label], ...]
_DEFAULT_BANDS: list[list] = [
    [0.0,  0.55, "d\u00fc\u015fük"],
    [0.55, 0.75, "orta"],
    [0.75, 1.01, "yüksek"],
]

_DEFAULT_BAND_LOWER: float = 0.55
_DEFAULT_BAND_UPPER: float = 0.75


# ── Internal helpers ────────────────────────────────────────────────────────

def _last_vowel(word: str) -> str | None:
    """Return the last vowel codepoint in *word* (lowercased), or ``None``."""
    for ch in reversed(word.lower()):
        if ch in _ALL_VOWELS:
            return ch
    return None


def _is_proper_noun(word: str) -> bool:
    """``True`` if the word starts with an uppercase letter (proper-noun heuristic)."""
    return bool(word) and word[0].isupper()


def _sep(word: str) -> str:
    """Return apostrophe if *word* is a proper noun, else empty string."""
    return "'" if _is_proper_noun(word) else ""


def _sep_ex(word: str, proper: bool) -> str:
    """Return apostrophe when *word* is a proper noun OR *proper* is ``True``.

    §10.22.2 output-side filter discipline: ``proper=True`` forces the
    apostrophe regardless of capitalisation (needed after normalization
    lowercases canonical entity names).
    """
    return "'" if (proper or _is_proper_noun(word)) else ""


def _vowel_info_ex(word: str, proper: bool) -> "tuple[str | None, bool]":
    """Return ``(last_vowel, is_vowel_final)`` with foreign-stem override applied.

    When *proper* is ``True``, the last token of *word* is looked up in
    ``foreign_stem_overrides.tr.yaml``.  If an override is found its
    ``vowel_class`` and ``pronunciation_class`` take precedence over the
    written-form heuristics.

    The override specifies front/back class but not rounding.  We preserve
    the word's *actual* last vowel character whenever it already agrees with
    the override's class, so that rounding (e.g. 'o'/'u' vs 'a'/'ı') is
    retained for 4-way harmony.  When the actual vowel disagrees (or there
    is none), a canonical representative is used: 'e' for front, 'a' for back.

    Returns
    -------
    (last_vowel_char_or_none, is_vowel_final_bool)
    """
    override = _get_stem_override(word) if proper else None

    if override:
        vc = override.get("vowel_class", "")
        pc = override.get("pronunciation_class", "")
        is_vowel_final: bool = (pc == "vowel_final")
        # Start from the word's actual last vowel to preserve rounding.
        actual_lv = _last_vowel(word)
        if vc == "front":
            # If the actual last vowel is already front, keep it (preserves ö/ü).
            lv: "str | None" = actual_lv if actual_lv in _FRONT else "e"
        elif vc == "back":
            # If the actual last vowel is already back, keep it (preserves o/u).
            lv = actual_lv if actual_lv in _BACK else "a"
        else:
            lv = actual_lv
        return lv, is_vowel_final

    # Default: derive from written form.
    lv = _last_vowel(word)
    last_char = word[-1].lower() if word else ""
    vf: bool = last_char in _ALL_VOWELS
    return lv, vf


def _two_way(word: str) -> str:
    """2-way suffix vowel: *a* for back, *e* for front (default *e*)."""
    v = _last_vowel(word)
    return _TWO_WAY_MAP.get(v, "e") if v else "e"


def _two_way_ex(word: str, proper: bool) -> str:
    """2-way suffix vowel with foreign-override support."""
    lv, _ = _vowel_info_ex(word, proper)
    return _TWO_WAY_MAP.get(lv, "e") if lv else "e"


def _four_way(word: str) -> str:
    """4-way suffix vowel: i/ı/ü/u based on last vowel (default *i*)."""
    v = _last_vowel(word)
    return _FOUR_WAY_MAP.get(v, "i") if v else "i"


def _four_way_ex(word: str, proper: bool) -> str:
    """4-way suffix vowel with foreign-override support."""
    lv, _ = _vowel_info_ex(word, proper)
    return _FOUR_WAY_MAP.get(lv, "i") if lv else "i"


def _td_consonant(word: str) -> str:
    """Return *t* for voiceless-final words, *d* otherwise (locative/ablative)."""
    last = word[-1].lower() if word else ""
    return "t" if last in _VOICELESS else "d"


# ── Public filters ────────────────────────────────────────────────────────────

def locative(word: str, proper: bool = False) -> str:
    """Locative case (-da/-de/-ta/-te): Galatasaray'da, Beşiktaş'ta.

    §10.22.2: *proper=True* forces the apostrophe regardless of capitalisation.
    """
    if not word:
        return word
    return f"{word}{_sep_ex(word, proper)}{_td_consonant(word)}{_two_way_ex(word, proper)}"


def dative(word: str, proper: bool = False) -> str:
    """Dative case (-a/-e/-ya/-ye): Galatasaray'a, Fenerbahçe'ye.

    §10.22.2: *proper=True* forces the apostrophe; consults foreign-stem
    overrides for correct vowel-class and pronunciation-class.
    """
    if not word:
        return word
    lv, _ = _vowel_info_ex(word, proper)
    vowel = _TWO_WAY_MAP.get(lv, "e") if lv else "e"
    sep = _sep_ex(word, proper)
    buf = _buffer_consonant(word, "dative")
    return f"{word}{sep}{buf}{vowel}"


def ablative(word: str, proper: bool = False) -> str:
    """Ablative case (-dan/-den/-tan/-ten): Galatasaray'dan, Beşiktaş'tan.

    §10.22.2: *proper=True* forces the apostrophe.
    """
    if not word:
        return word
    return f"{word}{_sep_ex(word, proper)}{_td_consonant(word)}{_two_way_ex(word, proper)}n"


def accusative(word: str, proper: bool = False) -> str:
    """Accusative case (-ı/-i/-u/-ü/-yı/-yi/-yu/-yü).

    §10.22.2: *proper=True* forces the apostrophe; consults foreign-stem
    overrides for correct vowel-class and pronunciation-class.
    """
    if not word:
        return word
    lv, _ = _vowel_info_ex(word, proper)
    v4 = _FOUR_WAY_MAP.get(lv, "i") if lv else "i"
    sep = _sep_ex(word, proper)
    buf = _buffer_consonant(word, "accusative")
    return f"{word}{sep}{buf}{v4}"


def genitive(word: str, proper: bool = False) -> str:
    """Genitive case (-ın/-in/-un/-ün/-nın/-nin/-nun/-nün).

    §10.22.2: *proper=True* forces the apostrophe; consults foreign-stem
    overrides for correct vowel-class and pronunciation-class.
    """
    if not word:
        return word
    lv, is_vowel_final = _vowel_info_ex(word, proper)
    v4 = _FOUR_WAY_MAP.get(lv, "i") if lv else "i"
    sep = _sep_ex(word, proper)
    if is_vowel_final:
        return f"{word}{sep}n{v4}n"
    return f"{word}{sep}{v4}n"


def plural(word: str, proper: bool = False) -> str:
    """Plural suffix (-lar/-ler): Galatasaray'lar, Fenerbahçe'ler.

    §10.22.2: *proper=True* forces the apostrophe.
    """
    if not word:
        return word
    vowel = _two_way_ex(word, proper)
    return f"{word}{_sep_ex(word, proper)}l{vowel}r"


def possessive_3sg(word: str, proper: bool = False) -> str:
    """3rd-person singular possessive (-ı/-i/-u/-ü after consonant; -sı/-si/-su/-sü after vowel).

    §10.22.3: uses buffer_consonant(word, 'possessive_3sg') to determine
    whether to insert 's' (vowel-final) or '' (consonant-final).
    The suffix vowel follows 4-way harmony.

    Examples
    --------
    Bursa  → Bursa'sı   (vowel-final, back-unrounded)
    Monaco → Monaco'su  (vowel-final, back-rounded)
    Trabzonspor → Trabzonspor'u  (consonant-final, back-rounded)
    Fenerbahçe  → Fenerbahçe'si (vowel-final, front-unrounded)
    """
    if not word:
        return word
    v4 = _four_way_ex(word, proper)
    sep = _sep_ex(word, proper)
    buf = _buffer_consonant(word, "possessive_3sg")
    return f"{word}{sep}{buf}{v4}"


def kickoff_time(dt: "str | _dt.datetime | None", locale: str = "tr-TR") -> str:
    """Format a kickoff datetime as 'Cumartesi 21:30' (locale-aware Turkish).

    Parameters
    ----------
    dt:
        An ISO-8601 string, a ``datetime.datetime`` instance, or ``None``.
        ``None`` \u2192 "Bilinmiyor".  Unparseable strings are returned as-is.
    locale:
        Reserved for future multi-locale support; currently only ``tr-TR`` is
        supported.
    """
    if dt is None:
        return "Bilinmiyor"
    if isinstance(dt, str):
        try:
            dt = _dt.datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return dt  # pass-through unparseable strings unchanged
    if not isinstance(dt, _dt.datetime):
        return str(dt)
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; datetime must include timezone information")
    target = dt.astimezone(ZoneInfo(cfg.nlp_render_timezone))
    weekday_name = _WEEKDAYS_TR[target.weekday()]
    return f"{weekday_name} {target.hour:02d}:{target.minute:02d}"


def match_label(home: str, away: str) -> str:
    """Format a match label as 'Galatasaray\u2013Fenerbah\u00e7e' (en-dash separator)."""
    return f"{home}\u2013{away}"


def confidence_band(prob: float, bands: "list | None" = None) -> str:
    """Map a probability to a Turkish confidence label.

    Parameters
    ----------
    prob:
        Probability in [0, 1].
    bands:
        List of ``[lower_inclusive, upper_exclusive, label]`` triples.
        When ``None`` the default \u00a710.7 three-band table is used.
        The first matching band wins.
    """
    if bands is None:
        # Keep default-band boundary behavior stable at exact cut points.
        if prob < _DEFAULT_BAND_LOWER:
            return "d\u00fc\u015fük"
        if prob < _DEFAULT_BAND_UPPER:
            return "orta"
        return "yüksek"
    for lower, upper, label in bands:
        if lower <= prob < upper:
            return label
    # Edge case: prob == 1.0 falls through the last band\u2019s exclusive upper bound.
    return bands[-1][2] if bands else "orta"


# \u2500\u2500 Filter registry \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

#: Mapping from Jinja2 filter name \u2192 callable.
#: ``render.py`` calls ``jinja2.Environment.filters.update(FILTERS)``
#: and then overrides ``confidence_band`` with a closure that captures the
#: configured band thresholds from ``cfg.nlp_confidence_bands``.
FILTERS: dict[str, object] = {
    "dative": dative,
    "accusative": accusative,
    "locative": locative,
    "ablative": ablative,
    "genitive": genitive,
    "plural": plural,
    "possessive_3sg": possessive_3sg,
    "kickoff_time": kickoff_time,
    "match_label": match_label,
    "number_tr": tr_format_number,
    "money_tr": tr_format_money,
    "clock_tr": tr_format_clock,
    "date_tr": tr_format_date,
    "date_tr_short": tr_format_date_short,
    "score_tr": tr_format_score,
    "confidence_band": confidence_band,
}
