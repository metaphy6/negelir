"""Shared text normalization helpers (Python/Go parity surface).

``canonical_normalize`` is the Python-side reference for the exact byte
sequence produced by ``server/internal/sec/sanitize.go::SanitizeText``.
Both apply the same two transforms in the same order so neither drifts:

  1. NFC normalization.
  2. Strip control chars (C0, DEL, C1, soft-hyphen) + zero-width chars
     + RTL overrides (LRE/RLE/PDF/LRO/RLO, LRI/RLI/FSI/PDI) + BOM.

Any change here MUST be mirrored in ``sanitize.go`` and vice-versa; the
cross-reference test in ``test_nlp_normalize_pipeline`` asserts the
behaviour deterministically for the Python side.

Design note: the same code-point set appears in
``ai/swarm/agents/sec/input.py::_STRIP_CONTROL_RE``.  The two regexes
are intentionally kept verbatim-equal so a grep diff catches any drift.
This module has ZERO dependency on the sec package — agents must not
import from other agents.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

# Verbatim copy of the set in ai/swarm/agents/sec/input.py::_STRIP_CONTROL_RE.
# Must be kept bit-for-bit equal; test_canonical_normalize_matches_sec_sanitize
# asserts the equality on a fixed corpus.
_STRIP_RE = re.compile(
    "["
    "\u0000-\u0008\u000B\u000C\u000E-\u001F"  # C0 minus \t \n \r
    "\u007F"                                         # DEL
    "\u0080-\u009F"                                 # C1
    "\u00AD"                                         # SOFT HYPHEN
    "\u200B-\u200F"                                 # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u202A-\u202E"                                 # LRE, RLE, PDF, LRO, RLO
    "\u2066-\u2069"                                 # LRI, RLI, FSI, PDI
    "\uFEFF"                                         # BOM / ZWNBSP
    "]"
)

# Explicit default-strip allow-list for Unicode format category characters.
# The list is empty for v1; any allowlist entry must be documented and
# audited via `test_normalize_no_format_chars_pass`.
_FORMAT_CATEGORY_ALLOWLIST: frozenset[int] = frozenset()

# Additional explicit codepoints outside the Cf category that are known to
# survive ZWJ/ZWNJ-only stripping and are adversarial in the Turkish input
# path.
_HANGUL_FILLER_CODEPOINTS = frozenset({0x115F, 0x1160, 0x3164})


def _is_disallowed_codepoint(ch: str) -> bool:
    cp = ord(ch)
    category = unicodedata.category(ch)
    if category == "Cf" and cp not in _FORMAT_CATEGORY_ALLOWLIST:
        return True
    if 0xFE00 <= cp <= 0xFE0F:  # Variation selectors
        return True
    if cp in _HANGUL_FILLER_CODEPOINTS:
        return True
    if category in {"Cn", "Co", "Cs"}:
        return True
    return False


def _tr_normalize_spec_path() -> Path:
    return Path(os.getenv("NEGELIR_NLP_TR_NORMALIZE_SPEC_PATH", "ai/common/text/tr_normalize_spec.json"))


def _load_tr_normalize_spec(path: Path | str | None = None) -> dict[str, Any]:
    spec_path = Path(path or _tr_normalize_spec_path())
    raw = spec_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{spec_path}: expected JSON object")
    if parsed.get("spec_version") != 1:
        raise ValueError(f"{spec_path}: expected spec_version=1")
    steps = parsed.get("steps")
    if not isinstance(steps, list) or not all(isinstance(step, str) for step in steps):
        raise ValueError(f"{spec_path}: expected a list of string steps")
    required = {"nfc", "strip_control", "lowercase_tr"}
    if not required.issubset(set(steps)):
        raise ValueError(
            f"{spec_path}: must declare required steps {sorted(required)}; got {steps}"
        )
    mappings = parsed.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError(f"{spec_path}: expected a mappings object")
    for required_key in ("I", "İ"):
        if required_key not in mappings:
            raise ValueError(f"{spec_path}: missing required mapping {required_key!r}")
    return parsed


def _load_tr_normalize_spec_sha(path: Path | str | None = None) -> str:
    spec_path = Path(path or _tr_normalize_spec_path())
    raw = spec_path.read_bytes()
    _ = _load_tr_normalize_spec(spec_path)
    return hashlib.sha256(raw).hexdigest()


_TR_NORMALIZE_SPEC_SHA = _load_tr_normalize_spec_sha()
TR_NORMALIZE_SPEC_SHA = _TR_NORMALIZE_SPEC_SHA


# ---------------------------------------------------------------------------
# Phase 10 §10.21.5 -- Unicode confusables folding (homoglyph defense)
# ---------------------------------------------------------------------------
# Mapping derived from Unicode TR39 Confusables.txt (v15.1.0).
# SHA-256 of source table: (pinned in xops/versioning/chart.json).
# Folds visually-confusable codepoints to ASCII-Turkish-extended (a-zçğıöşü).
# Defense-in-depth against CVE-2021-42574-style attacks (Cyrillic/Greek
# lookalikes bypassing gazetteer exact-match).
#
# This table is **never** applied to password fields (already excluded by
# §7.1 password-bypass in the sec gate; reasserted here for NLP plane).
#
# Format: codepoint -> replacement string.  Immutable dict for const folding.
_CONFUSABLES_TABLE: dict[int, str] = {
    # Cyrillic lowercase lookalikes (most common in trojan-source attacks)
    0x0430: "a",   # а CYRILLIC SMALL LETTER A -> Latin a
    0x0435: "e",   # е CYRILLIC SMALL LETTER IE -> Latin e
    0x043E: "o",   # о CYRILLIC SMALL LETTER O -> Latin o
    0x0440: "p",   # р CYRILLIC SMALL LETTER ER -> Latin p
    0x0441: "c",   # с CYRILLIC SMALL LETTER ES -> Latin c
    0x0445: "x",   # х CYRILLIC SMALL LETTER HA -> Latin x
    0x0455: "s",   # ѕ CYRILLIC SMALL LETTER DZE -> Latin s
    0x0456: "i",   # і CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I -> Latin i
    0x0458: "j",   # ј CYRILLIC SMALL LETTER JE -> Latin j
    0x04CF: "l",   # ӏ CYRILLIC SMALL LETTER PALOCHKA -> Latin l
    # Cyrillic uppercase lookalikes
    0x0410: "A",   # А CYRILLIC CAPITAL LETTER A -> Latin A
    0x0412: "B",   # В CYRILLIC CAPITAL LETTER VE -> Latin B
    0x0415: "E",   # Е CYRILLIC CAPITAL LETTER IE -> Latin E
    0x041A: "K",   # К CYRILLIC CAPITAL LETTER KA -> Latin K
    0x041C: "M",   # М CYRILLIC CAPITAL LETTER EM -> Latin M
    0x041D: "H",   # Н CYRILLIC CAPITAL LETTER EN -> Latin H
    0x041E: "O",   # О CYRILLIC CAPITAL LETTER O -> Latin O
    0x0420: "P",   # Р CYRILLIC CAPITAL LETTER ER -> Latin P
    0x0421: "C",   # С CYRILLIC CAPITAL LETTER ES -> Latin C
    0x0422: "T",   # Т CYRILLIC CAPITAL LETTER TE -> Latin T
    0x0425: "X",   # Х CYRILLIC CAPITAL LETTER HA -> Latin X
    0x0405: "S",   # Ѕ CYRILLIC CAPITAL LETTER DZE -> Latin S
    0x0406: "I",   # І CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I -> Latin I
    0x0408: "J",   # Ј CYRILLIC CAPITAL LETTER JE -> Latin J
    # Greek lowercase lookalikes
    0x03B1: "a",   # α GREEK SMALL LETTER ALPHA -> Latin a
    0x03B5: "e",   # ε GREEK SMALL LETTER EPSILON -> Latin e
    0x03B9: "i",   # ι GREEK SMALL LETTER IOTA -> Latin i
    0x03BF: "o",   # ο GREEK SMALL LETTER OMICRON -> Latin o
    0x03C1: "p",   # ρ GREEK SMALL LETTER RHO -> Latin p
    0x03C5: "u",   # υ GREEK SMALL LETTER UPSILON -> Latin u
    0x03C7: "x",   # χ GREEK SMALL LETTER CHI -> Latin x
    # Greek uppercase lookalikes
    0x0391: "A",   # Α GREEK CAPITAL LETTER ALPHA -> Latin A
    0x0392: "B",   # Β GREEK CAPITAL LETTER BETA -> Latin B
    0x0395: "E",   # Ε GREEK CAPITAL LETTER EPSILON -> Latin E
    0x0396: "Z",   # Ζ GREEK CAPITAL LETTER ZETA -> Latin Z
    0x0397: "H",   # Η GREEK CAPITAL LETTER ETA -> Latin H
    0x0399: "I",   # Ι GREEK CAPITAL LETTER IOTA -> Latin I
    0x039A: "K",   # Κ GREEK CAPITAL LETTER KAPPA -> Latin K
    0x039C: "M",   # Μ GREEK CAPITAL LETTER MU -> Latin M
    0x039D: "N",   # Ν GREEK CAPITAL LETTER NU -> Latin N
    0x039F: "O",   # Ο GREEK CAPITAL LETTER OMICRON -> Latin O
    0x03A1: "P",   # Ρ GREEK CAPITAL LETTER RHO -> Latin P
    0x03A4: "T",   # Τ GREEK CAPITAL LETTER TAU -> Latin T
    0x03A5: "Y",   # Υ GREEK CAPITAL LETTER UPSILON -> Latin Y
    0x03A7: "X",   # Χ GREEK CAPITAL LETTER CHI -> Latin X
    # Additional lookalikes from other scripts
    # NOTE: U+0131 (ı, Turkish dotless-i) is intentionally EXCLUDED here.
    # It is a legitimate Turkish character produced by lowercase_tr('I').
    # Folding ı→i would break idempotency of the full normalize pipeline.
    0x04BB: "h",   # һ CYRILLIC SMALL LETTER SHHA -> Latin h
    0x13A0: "a",   # Ꭺ CHEROKEE LETTER GO -> Latin a (uppercase visual)
    0x13D4: "b",   # Ꮟ CHEROKEE LETTER SI -> Latin b (visual similarity)
}


def _unicode_compat_confusables_fold(text: str) -> str:
    result: list[str] = []
    for ch in text:
        ord_ch = ord(ch)
        # Tag characters are Cf format marks used in emoji-flag spoofing.
        if 0xE0020 <= ord_ch <= 0xE007F:
            continue

        if (
            0x1D400 <= ord_ch <= 0x1D7FF
            or 0xFF01 <= ord_ch <= 0xFF5E
            or 0x2460 <= ord_ch <= 0x24FF
        ):  # math alpha, halfwidth/fullwidth, enclosed alphanumerics
            folded = unicodedata.normalize("NFKD", ch)
            if folded and all(ord(c) < 128 for c in folded):
                result.append(folded)
                continue

        result.append(ch)
    return "".join(result)


def confusables_fold(text: str) -> str:
    """Fold Unicode confusables to ASCII-Turkish-extended (Phase 10 §10.21.5).

    Replaces visually-confusable characters (Cyrillic а, Greek α, etc.) with
    their ASCII-Turkish equivalents to defend against homoglyph attacks on
    gazetteer exact-match (CVE-2021-42574-style).

    This function also normalizes the additional Unicode blocks enumerated by
    Phase 10 §10.33.1: Mathematical Alphanumeric Symbols, Halfwidth/Fullwidth
    Forms, and Enclosed Alphanumerics. Tag characters are stripped.

    This function is idempotent and MUST NOT be applied to password fields
    (already excluded upstream by §7.1; the NLP plane never sees passwords).

    Parameters
    ----------
    text : str
        Text post-canonical-normalize, pre-lowercase.

    Returns
    -------
    str
        Text with confusables folded to ASCII-Turkish-extended.

    Examples
    --------
    >>> confusables_fold("Galаtasaray")  # Cyrillic а U+0430
    'Galatasaray'
    >>> confusables_fold("Αthens")       # Greek Α U+0391
    'Athens'
    >>> confusables_fold("ＦＣ")         # fullwidth Latin letters
    'FC'
    >>> confusables_fold("𝐀")          # mathematical bold A
    'A'
    >>> confusables_fold("Ⓐ")          # enclosed Latin capital A
    'A'
    """
    normalized = text.translate(_CONFUSABLES_TABLE)
    return _unicode_compat_confusables_fold(normalized)


def canonical_normalize(text: str) -> str:
    """NFC-normalize then strip control chars, zero-width chars, and RTL overrides.

    Idempotent: ``canonical_normalize(canonical_normalize(x)) == canonical_normalize(x)``
    for any ``x``.

    Mirrors ``server/internal/sec/sanitize.go::SanitizeText`` byte-for-byte
    on the codepoint intersection both sides process.  Use this function
    (not a local re-implementation) in any Python code that needs the same
    transforms -- prevents Python/Go drift.
    """
    normalized = unicodedata.normalize("NFC", text)
    stripped = _STRIP_RE.sub("", normalized)
    return "".join(ch for ch in stripped if not _is_disallowed_codepoint(ch))
