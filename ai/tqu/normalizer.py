"""
Negelir TQU — Turkish text normalizer.

Handles the messy reality of user-written Turkish:
- ASCII-folded matching (ç→c, ş→s, ğ→g so 'kazanir' matches 'kazanır')
- Repeated character collapse ('gooool' → 'gol')
- Basic agglutinative suffix stripping ('kazanabilir' → 'kazan')
- Fuzzy team name resolution ('galatasary' → 'galatasaray')

Sits between sanitization and classification so existing regex/keyword
patterns work on noisy real-world input without hardcoding every variant.
"""

import re

# ── Turkish ↔ ASCII folding ─────────────────────────────

_TR_TO_ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
_ASCII_TO_TR = {
    "c": "ç", "g": "ğ", "i": "ı", "o": "ö", "s": "ş", "u": "ü",
}

def asciify(text: str) -> str:
    """Fold Turkish special characters to ASCII equivalents."""
    return text.translate(_TR_TO_ASCII)


# ── Repeated character collapse ─────────────────────────

# Any letter repeated 3+ times → collapse to 1  (gooool → gol, yeneeeer → yener)
_REPEAT_RE = re.compile(r"(.)\1{2,}")


def dedup_chars(text: str) -> str:
    """Collapse excessively repeated characters: 'gooool' → 'gol'."""
    return _REPEAT_RE.sub(r"\1", text)


# ── Basic Turkish suffix stripping ──────────────────────
# Not a full morphological analyzer — just removes the most common
# agglutinative suffixes so keyword matching works on varied forms.
# Order matters: strip longer suffixes first.

_SUFFIX_LIST = [
    # Compound verbal suffixes (longest first)
    "abilecek", "ebilecek", "acaktır", "ecektir",
    "abilir", "ebilir", "ıyormu", "iyormu",
    "ıyor", "iyor", "uyor", "üyor",
    "acak", "ecek", "arak", "erek",
    "abil", "ebil",
    "dığı", "diği", "duğu", "düğü",
    "lığı", "liği", "luğu", "lüğü",
    # Noun case / possessive
    "ları", "leri", "ında", "inde", "unda", "ünde",
    "ının", "inin", "unun", "ünün",
    "ıyla", "iyle", "uyla", "üyle",
    "ımız", "imiz", "umuz", "ümüz",
    "ları", "leri",
    # Simple verb / adjective suffixes
    "mış", "miş", "muş", "müş",
    "dır", "dir", "dur", "dür",
    "tır", "tir", "tur", "tür",
    "lar", "ler",
    "dan", "den", "tan", "ten",
    "nın", "nin", "nun", "nün",
    "ın", "in", "un", "ün",
    "da", "de", "ta", "te",
    "la", "le",
    "mı", "mi", "mu", "mü",
    "ız", "iz", "uz", "üz",
    "lı", "li", "lu", "lü",
    "sı", "si", "su", "sü",
    "ya", "ye",
    "ı", "i",
]

# Minimum stem length after stripping — prevents over-stemming short words
_MIN_STEM = 3


def strip_suffixes(word: str) -> str:
    """Strip common Turkish agglutinative suffixes from a single word."""
    for suffix in _SUFFIX_LIST:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            return word[: -len(suffix)]
    return word


def stem_text(text: str) -> str:
    """Apply suffix stripping to every word in a text."""
    return " ".join(strip_suffixes(w) for w in text.split())


# ── Fuzzy team name matching ────────────────────────────

def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (Wagner-Fischer, no external deps)."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def fuzzy_match_team(token: str, team_names: list[str], max_dist: int = 2) -> str | None:
    """
    Return the best-matching team name if within edit distance threshold.
    Operates on ASCII-folded forms to handle ç/c, ş/s confusion.
    """
    token_ascii = asciify(token.lower())
    if len(token_ascii) < 4:
        return None

    best_name = None
    best_dist = max_dist + 1

    for name in team_names:
        name_ascii = asciify(name.lower())
        # Quick length filter — can't be within max_dist if lengths differ too much
        if abs(len(token_ascii) - len(name_ascii)) > max_dist:
            continue
        dist = _edit_distance(token_ascii, name_ascii)
        if dist < best_dist:
            best_dist = dist
            best_name = name

    return best_name if best_dist <= max_dist else None


def resolve_team_typos(text: str, team_names: list[str]) -> str:
    """Replace misspelled team names in text with their canonical forms."""
    words = text.split()
    result = []
    i = 0
    while i < len(words):
        matched = False
        # Try 2-word team names first (e.g. "adana demirspor")
        if i + 1 < len(words):
            bigram = f"{words[i]} {words[i+1]}"
            match = fuzzy_match_team(bigram, team_names, max_dist=2)
            if match:
                result.append(match)
                i += 2
                matched = True
        if not matched:
            match = fuzzy_match_team(words[i], team_names, max_dist=2)
            if match:
                result.append(match)
            else:
                result.append(words[i])
            i += 1
    return " ".join(result)


# ── Main normalizer ─────────────────────────────────────

def normalize(text: str, team_names: list[str] | None = None) -> str:
    """
    Full normalization pipeline for Turkish football text.

    Returns a cleaned version where:
    - Repeated chars are collapsed
    - Team typos are resolved (if team_names provided)

    The classifier should match patterns against BOTH the original
    sanitized text and an asciified version for maximum coverage.
    """
    # Step 1: Collapse repeated characters
    text = dedup_chars(text)

    # Step 2: Resolve team name typos
    if team_names:
        text = resolve_team_typos(text, team_names)

    return text


def asciify_keywords(keywords: list[str]) -> list[str]:
    """Generate ASCII-folded versions of keyword list (for dual matching)."""
    folded = set()
    for kw in keywords:
        folded.add(kw)
        ascii_ver = asciify(kw)
        if ascii_ver != kw:
            folded.add(ascii_ver)
    return list(folded)
