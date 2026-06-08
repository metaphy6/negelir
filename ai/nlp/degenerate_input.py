"""Phase 10 §10.34.2 — Degenerate input detection (before normalize chain).

Hard-rejects input that is provably malformed or would waste CPU/memory in 
downstream components (Symspell, CRF, Zemberek). All five cases bypass the
entire normalization pipeline and route to closed Turkish refusal templates.

Edge cases handled:
- Empty strings (zero-length)
- Whitespace-only strings
- Single-character control characters (U+0000–U+001F, U+007F–U+009F, etc.)
- Lone UTF-16 surrogates (U+D800–U+DFFF) — shouldn't occur in UTF-8, but graceful handling
- NUL byte injection (U+0000)

Per §10.34.2, these are detected and rejected BEFORE any normalization pass runs.
"""
from __future__ import annotations

import unicodedata
from typing import Tuple


def _is_lone_surrogate(ch: str) -> bool:
    """Return True if ch is a lone UTF-16 surrogate (U+D800–U+DFFF).
    
    These should not appear in valid UTF-8, but Python's str can contain them
    from certain malformed inputs or external sources. Graceful handling.
    """
    code = ord(ch)
    return 0xD800 <= code <= 0xDFFF


def _is_control_character(ch: str) -> bool:
    """Return True if ch is in the Unicode control character category (Cc, Cf only).
    
    Includes:
    - Cc: Control characters (U+0000–U+001F, U+007F–U+009F)
    - Cf: Format characters (e.g., zero-width joiner, bidi override)
    
    Excludes:
    - Cs: Surrogate characters (should be caught by _is_lone_surrogate separately)
    - Co: Private use (allowed for now)
    - Cn: Not assigned (allowed for now)
    
    In practice, NLP never needs these single-char inputs, so we reject them.
    """
    category = unicodedata.category(ch)
    return category in ('Cc', 'Cf')


def detect_degenerate_input(text: str) -> Tuple[bool, str | None]:
    """Detect degenerate input that should bypass the normalize chain entirely.
    
    Returns (is_degenerate, meta_template_kind) where meta_template_kind is one of:
    - "meta.empty_input" for empty or whitespace-only input
    - "meta.control_only_input" for single control characters
    - "meta.malformed_input" for lone surrogates or NUL bytes
    - None if input is not degenerate
    
    Per §10.34.2 binding spec, this check must run BEFORE any normalization pass.
    
    Priority order:
    1. Empty / whitespace-only (easiest check)
    2. NUL bytes anywhere (security concern, must be caught early)
    3. Lone surrogates anywhere (malformed UTF-8/16)
    4. Single control character (edge case for very short input)
    
    Parameters
    ----------
    text : str
        Raw user input from qa.request.v1.sanitized_text.
    
    Returns
    -------
    Tuple[bool, str | None]
        (is_degenerate, meta_template_kind)
        - is_degenerate=False, kind=None: input is valid, proceed to normalize
        - is_degenerate=True, kind="meta.empty_input": empty or whitespace-only
        - is_degenerate=True, kind="meta.control_only_input": single control char
        - is_degenerate=True, kind="meta.malformed_input": surrogate or NUL
    """
    if not text:
        # Case 1a: len(s) == 0 (empty string)
        return True, "meta.empty_input"
    
    if not text.strip():
        # Case 1b: len(s.strip()) == 0 (whitespace-only)
        return True, "meta.empty_input"
    
    # Check for NUL and surrogates anywhere in text (higher priority than control chars)
    for ch in text:
        if ch == '\x00':
            # Case 2a: NUL byte (security concern, catch early)
            return True, "meta.malformed_input"
        if _is_lone_surrogate(ch):
            # Case 2b: Lone surrogate (UTF-8/16 malformation)
            return True, "meta.malformed_input"
    
    # Now check for single control character (only if len==1)
    if len(text) == 1:
        # Case 3: Single codepoint that is a control character
        if _is_control_character(text):
            return True, "meta.control_only_input"
    
    # Not degenerate; proceed to normalize chain
    return False, None


def assert_not_degenerate_input(text: str, cfg=None) -> Tuple[str, str | None]:
    """Wrapper for assert_minimum_signal-style floor detection.
    
    Returns (floor_kind, meta_kind) where floor_kind is:
    - "ok": input is valid (not degenerate)
    - "empty_input_floor_response": mapped from meta.empty_input
    - "control_input_floor_response": mapped from meta.control_only_input
    - "malformed_input_floor_response": mapped from meta.malformed_input
    
    This is used in the dispatcher's floor gate (§10.24) for compatibility
    with the existing assert_minimum_signal contract.
    """
    is_degenerate, meta_kind = detect_degenerate_input(text)
    if not is_degenerate:
        return "ok", None
    
    if meta_kind == "meta.empty_input":
        return "empty_input_floor_response", meta_kind
    elif meta_kind == "meta.control_only_input":
        return "control_input_floor_response", meta_kind
    elif meta_kind == "meta.malformed_input":
        return "malformed_input_floor_response", meta_kind
    else:
        # Fallback (should never happen)
        return "empty_input_floor_response", "meta.empty_input"
