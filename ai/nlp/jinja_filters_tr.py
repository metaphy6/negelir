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
  Front vowels (e, i, \u00f6, \u00fc) \u2192 suffix uses *e*.
  Back  vowels (a, \u0131, o, u) \u2192 suffix uses *a*.

4-way (i/\u0131/\u00fc/u)
  Front unrounded (e, i) \u2192 *i*.
  Back  unrounded (a, \u0131) \u2192 *\u0131*.
  Front rounded   (\u00f6, \u00fc) \u2192 *\u00fc*.
  Back  rounded   (o, u) \u2192 *u*.

Voiceless final consonant (\u00e7fhkps\u015ft) \u2192 locative/ablative use *t*;
voiced or vowel-final \u2192 *d*.

Proper nouns (initial uppercase) take an apostrophe before the suffix.
"""
from __future__ import annotations

import datetime as _dt

# \u2500\u2500 Vowel sets \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_FRONT: frozenset[str] = frozenset("ei\u00f6\u00fc")
_BACK: frozenset[str] = frozenset("a\u0131ou")
_ALL_VOWELS: frozenset[str] = _FRONT | _BACK

_FRONT_ROUNDED: frozenset[str] = frozenset("\u00f6\u00fc")
_BACK_ROUNDED: frozenset[str] = frozenset("ou")

# Voiceless consonants: locative/ablative use -t- (not -d-)
_VOICELESS: frozenset[str] = frozenset("\u00e7fhkps\u015ft")

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


# \u2500\u2500 Internal helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

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
    return "\'" if _is_proper_noun(word) else ""


def _two_way(word: str) -> str:
    """2-way suffix vowel: *a* for back, *e* for front (default *e*)."""
    v = _last_vowel(word)
    return "a" if v in _BACK else "e"


def _four_way(word: str) -> str:
    """4-way suffix vowel: i/\u0131/\u00fc/u based on last vowel (default *i*)."""
    v = _last_vowel(word)
    if v is None:
        return "i"
    if v in _FRONT_ROUNDED:
        return "\u00fc"
    if v in _BACK_ROUNDED:
        return "u"
    if v in _BACK:
        return "\u0131"
    return "i"


def _td_consonant(word: str) -> str:
    """Return *t* for voiceless-final words, *d* otherwise (locative/ablative)."""
    last = word[-1].lower() if word else ""
    return "t" if last in _VOICELESS else "d"


# \u2500\u2500 Public filters \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def locative(word: str) -> str:
    """Locative case (-da/-de/-ta/-te): Galatasaray'da, Be\u015fkta\u015f'ta."""
    if not word:
        return word
    return f"{word}{_sep(word)}{_td_consonant(word)}{_two_way(word)}"


def dative(word: str) -> str:
    """Dative case (-a/-e/-ya/-ye): Galatasaray'a, Fenerbah\u00e7e'ye."""
    if not word:
        return word
    vowel = _two_way(word)
    last = word[-1].lower()
    buffer = f"{word}{_sep(word)}"
    if last in _ALL_VOWELS:
        return f"{buffer}y{vowel}"
    return f"{buffer}{vowel}"


def ablative(word: str) -> str:
    """Ablative case (-dan/-den/-tan/-ten): Galatasaray'dan, Be\u015fkta\u015f'tan."""
    if not word:
        return word
    return f"{word}{_sep(word)}{_td_consonant(word)}{_two_way(word)}n"


def accusative(word: str) -> str:
    """Accusative case (-\u0131/-i/-u/-\u00fc/-y\u0131/-yi/-yu/-y\u00fc)."""
    if not word:
        return word
    v4 = _four_way(word)
    last = word[-1].lower()
    buffer = f"{word}{_sep(word)}"
    if last in _ALL_VOWELS:
        return f"{buffer}y{v4}"
    return f"{buffer}{v4}"


def genitive(word: str) -> str:
    """Genitive case (-\u0131n/-in/-un/-\u00fcn/-n\u0131n/-nin/-nun/-n\u00fcn)."""
    if not word:
        return word
    v4 = _four_way(word)
    last = word[-1].lower()
    buffer = f"{word}{_sep(word)}"
    if last in _ALL_VOWELS:
        return f"{buffer}n{v4}n"
    return f"{buffer}{v4}n"


def plural(word: str) -> str:
    """Plural suffix (-lar/-ler): Galatasaray'lar, Fenerbah\u00e7e'ler."""
    if not word:
        return word
    vowel = _two_way(word)
    return f"{word}{_sep(word)}l{vowel}r"


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
    weekday_name = _WEEKDAYS_TR[dt.weekday()]
    return f"{weekday_name} {dt.hour:02d}:{dt.minute:02d}"


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
        bands = _DEFAULT_BANDS
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
    "kickoff_time": kickoff_time,
    "match_label": match_label,
    "confidence_band": confidence_band,
}
