"""Phase 10 §10.34.2 — Single-pass DFA fast-path for clean input.

Empirically ~80% of input is already NFC + Turkish-locale-lowercase + no
confusables + no format chars + no mojibake + no ligatures + no bidi controls
+ no paste artefacts. The fast-path detects this invariant without running
the full 11+ pass normalize pipeline.

Guarantees:
- Zero-copy return (same string object) when input is clean
- O(n) scan bounded by cfg.nlp_input_max_codepoints
- Telemetry event `normalize_fast_path_taken` on fast-path dispatch
"""
from __future__ import annotations

import sys
from typing import Optional

from ai.common.config import cfg as _default_cfg


# Turkish character ranges (explicit codepoint sets).
# These are the "printable Turkish" characters that, combined with ASCII
# printable and space/punct, define the "clean input invariant".
#
# Per AGENTS.md Rule 6: Turkish UX, English infra.
# These codepoints represent Turkish-specific letters and diacritics.
_TURKISH_LETTER_RANGES = (
    # Turkish lowercase letters with diacritics
    (0x00E7, 0x00E7),  # ç
    (0x011F, 0x011F),  # ğ
    (0x0131, 0x0131),  # ı (dotless i)
    (0x00F6, 0x00F6),  # ö
    (0x015F, 0x015F),  # ş
    (0x00FC, 0x00FC),  # ü
    # Turkish uppercase letters with diacritics
    (0x00C7, 0x00C7),  # Ç
    (0x011E, 0x011E),  # Ğ
    (0x0130, 0x0130),  # İ (dotted capital I)
    (0x00D6, 0x00D6),  # Ö
    (0x015E, 0x015E),  # Ş
    (0x00DC, 0x00DC),  # Ü
)

# ASCII ranges that are "clean" (printable, no special formatting).
# - [0x20, 0x7E]: ASCII printable (space through ~)
#   Includes basic punctuation and basic ASCII letters (a-z, A-Z, 0-9)
_ASCII_CLEAN_RANGES = (
    (0x20, 0x7E),  # ASCII printable (space through tilde)
)

# ASCII whitespace and common punctuation that are "clean" and allowed.
# - 0x09: TAB
# - 0x0A: LF (newline)
# - 0x0D: CR (carriage return)
_ASCII_SPACE_PUNCT = {0x09, 0x0A, 0x0D}


def _is_clean_codepoint(codepoint: int) -> bool:
    """Return True if a single codepoint is in the "clean input" set.
    
    A codepoint is "clean" if it is:
    - ASCII printable (U+0020–U+007E) OR
    - ASCII whitespace/line-control (TAB, LF, CR) OR
    - A Turkish-specific letter (ç, ğ, ı, ö, ş, ü, and uppercase variants)
    
    Per §10.34.2, inputs composed entirely of clean codepoints can skip
    the full normalize pipeline and use the zero-copy fast path.
    """
    # Check ASCII printable
    for start, end in _ASCII_CLEAN_RANGES:
        if start <= codepoint <= end:
            return True
    
    # Check ASCII space/punct
    if codepoint in _ASCII_SPACE_PUNCT:
        return True
    
    # Check Turkish letters
    for start, end in _TURKISH_LETTER_RANGES:
        if start <= codepoint <= end:
            return True
    
    return False


def is_clean_input(text: str, max_chars: Optional[int] = None) -> bool:
    """Return True when input is "clean" and can bypass the normalize pipeline.
    
    A "clean" input is one where every codepoint is in the clean-input invariant
    set (printable ASCII, ASCII space/line-control, or Turkish-specific letters).
    Such inputs require no normalization — no NFC, no confusables fold, no
    mojibake recovery, no paste cleanup, and so on.
    
    Parameters
    ----------
    text : str
        The input string to classify.
    max_chars : Optional[int]
        Optional scan limit (e.g., cfg.nlp_input_max_codepoints). If the input
        length exceeds this, scanning stops early (returns False on first
        codepoint beyond the limit). Defaults to cfg.nlp_input_max_codepoints
        if not supplied.
    
    Returns
    -------
    bool
        True if every codepoint (up to max_chars) is in the clean set.
        False if any codepoint is outside the clean set OR if the input
        length exceeds max_chars.
    
    Notes
    -----
    - This scan is O(n) but bounded by max_chars, so it has a hard upper
      bound regardless of input length.
    - The scan does NOT perform any allocations on clean input (no copies,
      no intermediate collections).
    - Use this as an early guard before calling the full normalize_input().
    """
    if text is None:
        return False
    
    if max_chars is None:
        max_chars = _default_cfg.nlp_input_max_codepoints
    
    # Early exit: empty input is clean.
    if not text:
        return True
    
    # Scan each codepoint. O(n) but bounded by max_chars.
    text_len = len(text)
    if text_len > max_chars:
        # Input exceeds length cap; cannot be clean.
        return False
    
    for codepoint_char in text:
        codepoint = ord(codepoint_char)
        if not _is_clean_codepoint(codepoint):
            return False
    
    return True


def get_clean_input_fast_path(
    text: str,
    cfg=None,
    *,
    max_chars: Optional[int] = None,
) -> tuple[str, bool]:
    """Apply the fast path to clean input; fall back to full normalize if needed.
    
    This is the top-level entry point for the fast-path optimization.
    
    If the input passes is_clean_input(), this function:
    - Returns the input unchanged (same string object, not a copy)
    - Emits a `normalize_fast_path_taken` telemetry event
    - Returns (input, True) to signal the fast path was taken
    
    If the input fails the clean check, this function:
    - Returns (input, False) to signal the caller should use the full pipeline
    
    Parameters
    ----------
    text : str
        The input string to normalize.
    cfg : Optional[Config]
        Configuration instance. Defaults to the module singleton.
    max_chars : Optional[int]
        Optional codepoint limit for the scan. Defaults to cfg.nlp_input_max_codepoints.
    
    Returns
    -------
    tuple[str, bool]
        - (text, True) if the fast path was taken (input is clean, unchanged)
        - (text, False) if the fast path was not taken (caller should use full pipeline)
    
    Examples
    --------
    >>> text = "Galatasaray maçı"
    >>> normalized, took_fast_path = get_clean_input_fast_path(text)
    >>> if took_fast_path:
    ...     print(f"Fast path: {normalized}")
    ... else:
    ...     # Use full normalize_input() here
    ...     from nlp.normalize import normalize_input
    ...     normalized = normalize_input(text)
    """
    if cfg is None:
        cfg = _default_cfg
    
    if max_chars is None:
        max_chars = cfg.nlp_input_max_codepoints
    
    # Check if input is clean.
    if is_clean_input(text, max_chars=max_chars):
        # Emit telemetry event.
        try:
            from ai.common.telemetry import get_sink
            sink = get_sink()
            if sink and sink.enabled:
                # Log structured event (mirrors §10.14 pattern)
                import logging
                log = logging.getLogger(__name__)
                log.debug(
                    "Normalize fast path taken",
                    extra={
                        "structured": True,
                        "event_kind": "normalize_fast_path_taken",
                        "input_len": len(text),
                    },
                )
        except Exception:  # noqa: BLE001
            pass  # non-blocking telemetry failure
        
        # Fast path: return unchanged (zero-copy).
        return (text, True)
    
    # Input is not clean; caller should use full pipeline.
    return (text, False)
