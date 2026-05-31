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

