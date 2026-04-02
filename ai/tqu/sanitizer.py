"""
Negelir TQU — Input sanitization layer.
Per roadmap §5.6.2: strip URLs, code, injection markers;
normalize Turkish chars; enforce 200-char limit.
"""

import re
from common.constants import MAX_INPUT_LENGTH
from common.logger import get_logger

log = get_logger("tqu.sanitizer")

# Patterns to strip (injection markers, code, URLs)
_INJECTION_PATTERNS = [
    r"\[INST\]", r"\[/INST\]",
    r"###\s*System:", r"###\s*User:", r"###\s*Assistant:",
    r"<\|im_start\|>", r"<\|im_end\|>",
    r"<\|system\|>", r"<\|user\|>",
    r"ignore\s+previous", r"forget\s+instructions",
    r"system\s+prompt", r"you\s+are\s+now",
    r"<script", r"</script>",
    r"javascript:", r"eval\(", r"exec\(",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_HTML_RE = re.compile(r"<[^>]+>")
# Allow only Turkish alphabet, digits, and basic punctuation
_ALLOWED_CHARS_RE = re.compile(r"[^a-zA-ZçÇğĞıİöÖşŞüÜ0-9\s?.!,'\-]")

# Turkish char normalization (uppercase İ → lowercase i, etc.)
_TR_UPPER_TO_LOWER = str.maketrans("İIÇĞÖŞÜ", "iıçğöşü")


def sanitize(text: str) -> tuple[str, bool]:
    """
    Sanitize Turkish user input.

    Returns:
        (sanitized_text, is_valid) — is_valid is False if the input
        was rejected (too long, empty after sanitization, or contained
        only injection patterns).
    """
    if not text or not text.strip():
        log.debug("Empty input rejected")
        return "", False

    original_len = len(text)

    # Length gate
    if original_len > MAX_INPUT_LENGTH:
        log.warning(f"Input too long ({original_len} > {MAX_INPUT_LENGTH}), rejected")
        return "", False

    cleaned = text

    # Strip injection markers
    injection_found = bool(_INJECTION_RE.search(cleaned))
    if injection_found:
        log.warning("⛔ Injection pattern detected, cleaning")
        cleaned = _INJECTION_RE.sub("", cleaned)

    # Strip URLs
    cleaned = _URL_RE.sub("", cleaned)

    # Strip HTML
    cleaned = _HTML_RE.sub("", cleaned)

    # Remove disallowed characters
    cleaned = _ALLOWED_CHARS_RE.sub("", cleaned)

    # Normalize Turkish characters (lowercase)
    cleaned = cleaned.lower().translate(_TR_UPPER_TO_LOWER)

    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        log.warning("Input empty after sanitization, rejected")
        return "", False

    if injection_found:
        log.info(f"Input sanitized: '{cleaned}'")

    return cleaned, True
