from __future__ import annotations

_COMBINING_DOT_ABOVE = "\u0307"

# Explicit map for the Turkish dotted-i composition step.
# - I + COMBINING DOT ABOVE -> İ
# - i + COMBINING DOT ABOVE -> i
# - J + COMBINING DOT ABOVE -> J
# Other bases with a stray combining dot above drop the combining mark.
_TURKISH_DOTTED_I_MAP: dict[str, str] = {
    "I": "İ",
    "i": "i",
    "J": "J",
}


def compose_turkish_dotted_i(text: str) -> str:
    """Recompose Turkish dotted-i sequences before lowercase.

    This step handles the canonical-equivalence corner cases that NFC
    normalization does not fully close for Turkish input:

    - U+0049 U+0307 -> U+0130 (capital dotted I)
    - U+0069 U+0307 -> U+0069 (lowercase i, drop stray dot)
    - U+004A U+0307 -> U+004A (J with stray dot removed)
    """
    if _COMBINING_DOT_ABOVE not in text:
        return text

    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if i + 1 < len(text) and text[i + 1] == _COMBINING_DOT_ABOVE:
            out.append(_TURKISH_DOTTED_I_MAP.get(ch, ch))
            i += 2
            continue
        out.append(ch)
        i += 1

    return "".join(out)
