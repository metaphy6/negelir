"""Phase 10 §10.1 -- Input normalization pipeline (9-step, ordered, idempotent).

Steps (order is BINDING; any reordering breaks downstream tests):

  1. Length cap: reject inputs that exceed ``cfg.nlp_input_max_codepoints``.
  2. NFC normalize.
  3. Control-char + zero-width + RTL-override strip.
     (Steps 2+3 are fused into ``canonical_normalize`` for Python/Go parity.)
  3.5. Unicode confusables fold (§10.21.5): Cyrillic/Greek lookalikes -> ASCII-Turkish.
  4. Turkish-aware lowercase (I->dotless-i, dotted-I->i; NEVER ``str.lower()``).
  5. Punctuation normalization (curly quotes, em/en-dash, multiple spaces).
  6. Diacritic restoration (table-driven).  [\u00a7 10.3 stub -- pass-through]
  7. Tokenization (whitespace + punctuation split).
  8. Token-level typo correction.             [\u00a7 10.3 stub -- pass-through]

Usage::

    from nlp.normalize import normalize_input, InputTooLongError
    from common.config import cfg

    try:
        result = normalize_input("Galatasaray mac tahmini", cfg=cfg)
    except InputTooLongError:
        ...

"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from common.text.normalize import canonical_normalize, confusables_fold
from common.text.turkish import lowercase_tr

# ---------------------------------------------------------------------------
# Step 5 -- punctuation normalization
# ---------------------------------------------------------------------------
# Codepoint -> replacement-string table for str.translate().
# Values are strings (Python str.translate supports str values).
_PUNCT_TABLE: dict[int, str] = {
    ord("\u201C"): '"',    # LEFT DOUBLE QUOTATION MARK  -> straight "
    ord("\u201D"): '"',    # RIGHT DOUBLE QUOTATION MARK -> straight "
    ord("\u201E"): '"',    # DOUBLE LOW-9 QUOTATION MARK -> straight "
    ord("\u2018"): "'",    # LEFT SINGLE QUOTATION MARK  -> straight apostrophe
    ord("\u2019"): "'",    # RIGHT SINGLE QUOTATION MARK -> straight apostrophe
    ord("\u201A"): ",",    # SINGLE LOW-9 QUOTATION MARK -> comma
    ord("\u2014"): " - ",  # EM DASH  -> hyphen-space-hyphen
    ord("\u2013"): " - ",  # EN DASH  -> hyphen-space-hyphen
    ord("\u2026"): "...",  # HORIZONTAL ELLIPSIS -> three dots
    ord("\u00B7"): ".",    # MIDDLE DOT -> period
}

# Collapse multiple consecutive spaces produced after em/en-dash expansion.
_MULTI_SPACE_RE = re.compile(r" {2,}")

# ---------------------------------------------------------------------------
# Step 7 -- tokenization
# ---------------------------------------------------------------------------
# Split on sequences of whitespace + common punctuation boundaries.
# Apostrophes inside tokens are preserved (e.g. Turkish suffix "yarin'ki").
_TOKEN_SPLIT_RE = re.compile(r"[\s,\.\?!\:;()\[\]/|]+")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class InputTooLongError(ValueError):
    """Raised by step 1 when input exceeds ``cfg.nlp_input_max_codepoints``."""


@dataclass(frozen=True)
class NormalizedInput:
    """Result of the 8-step normalization pipeline.

    Attributes
    ----------
    tokens:
        Ordered tuple of normalized tokens (post all 8 steps).
    steps_run:
        Ordered tuple of step names that were executed.  Consumers use
        this for forensic tracing and to assert ordering in tests.
    original_codepoint_count:
        ``len(raw_text)`` before any transforms.
    typo_budget_exhausted:
        ``True`` when the per-query fuzzy-lookup budget was hit during
        step 8 (§10.3 Per-query budget).  Callers should emit
        ``nlp.event.v1{kind=did_you_mean_offered}`` and return a
        "Did you mean?" response rather than treating the partial
        correction as authoritative.
    """

    tokens: tuple[str, ...]
    steps_run: tuple[str, ...]
    original_codepoint_count: int
    typo_budget_exhausted: bool = False
    stage_timed_out: bool = False
    """True when the normalize+diacritic+typo stage exceeded
    ``cfg.nlp_normalize_stage_timeout_ms``.  The caller is responsible
    for emitting ``nlp.event.v1{kind=normalize_timeout}``.
    """


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def normalize_input(
    text: str,
    cfg=None,
    *,
    _diacritic_restore: Optional[Callable[[str], str]] = None,
    _typo_correct: "Optional[Callable[[list[str]], tuple[list[str], bool]]]" = None,
    _clock: Optional[Callable[[], float]] = None,
) -> NormalizedInput:
    """Run the 8-step normalization pipeline on *text*.

    Parameters
    ----------
    text:
        Raw user input from ``qa.request.v1.raw_text``.
    cfg:
        Config instance.  Defaults to the module-level singleton.
    _diacritic_restore:
        Optional step-6 hook (str -> str).  When ``None``, step 6 is a
        pass-through.  Will be wired to the §10.3 implementation
        once that bullet lands.
    _typo_correct:
        Optional step-8 hook ``(list[str]) -> (list[str], bool)``.
        Returns ``(corrected_tokens, budget_exhausted)``.  When ``None``,
        step 8 is a pass-through with ``typo_budget_exhausted=False``.
    _clock:
        Injectable monotonic-time source (``() -> float``, seconds).
        Defaults to ``time.monotonic``.  Override in tests to control
        the deadline without sleeping.

    Returns
    -------
    NormalizedInput

    Raises
    ------
    InputTooLongError
        When ``len(text)`` (in codepoints) exceeds
        ``cfg.nlp_input_max_codepoints``.
    """
    if cfg is None:
        from common.config import cfg as _cfg
        cfg = _cfg

    _get_time = _clock if _clock is not None else time.monotonic
    _deadline_s = cfg.nlp_normalize_stage_timeout_ms / 1000.0

    steps: list[str] = []
    raw_cp = len(text)

    # -- Step 1: Length cap --------------------------------------------------
    if raw_cp > cfg.nlp_input_max_codepoints:
        raise InputTooLongError(
            f"Input length {raw_cp} codepoints exceeds "
            f"nlp_input_max_codepoints={cfg.nlp_input_max_codepoints}"
        )
    steps.append("length_cap")

    # -- Steps 2+3: NFC + control-char / zero-width / RTL strip -------------
    # canonical_normalize is the Python/Go parity surface; NEVER inline here.
    normalized = canonical_normalize(text)
    steps.append("canonical_normalize")

    # -- Step 3.5: Unicode confusables fold (Phase 10 §10.21.5) ------------
    # Defense-in-depth against homoglyph attacks (Cyrillic/Greek lookalikes).
    # Folds to ASCII-Turkish-extended before lowercase so "Galаtasaray" (Cyrillic а)
    # -> "Galatasaray" -> gazetteer exact-match succeeds.
    normalized = confusables_fold(normalized)
    steps.append("confusables_fold")

    # -- Step 4: Turkish-aware lowercase ------------------------------------
    normalized = lowercase_tr(normalized)
    steps.append("lowercase_tr")

    # -- Step 5: Punctuation normalization ----------------------------------
    normalized = normalized.translate(_PUNCT_TABLE)
    normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()
    steps.append("punct_normalize")

    # -- Steps 6-8 are the bounded "normalize+typo+diacritic" stage. --------
    # Start the stage clock here; deadline is cfg.nlp_normalize_stage_timeout_ms.
    _stage_start = _get_time()

    # -- Step 6: Diacritic restoration (§10.3 hook) -------------------------
    if _diacritic_restore is not None:
        normalized = _diacritic_restore(normalized)
    steps.append("diacritic_restore")

    # -- Step 7: Tokenization -----------------------------------------------
    # Full zemberek suffix-aware rules will be layered in via §10.2 (vendored
    # snapshot in ai/nlp/vendor/zemberek_rules.json).  This basic split is
    # the binding baseline for step ordering.
    raw_tokens: list[str] = [t for t in _TOKEN_SPLIT_RE.split(normalized) if t]
    steps.append("tokenize")

    # Deadline check after step 6+7: if we are already over budget, skip the
    # expensive step 8 and return the raw token sequence.  The caller emits
    # nlp.event.v1{kind=normalize_timeout} upon seeing stage_timed_out=True.
    if (_get_time() - _stage_start) * 1000.0 >= _deadline_s * 1000.0:
        steps.append("typo_correct")
        return NormalizedInput(
            tokens=tuple(raw_tokens),
            steps_run=tuple(steps),
            original_codepoint_count=raw_cp,
            typo_budget_exhausted=False,
            stage_timed_out=True,
        )

    # -- Step 8: Token-level typo correction (§10.3 hook) -------------------
    budget_exhausted = False
    if _typo_correct is not None:
        tokens, budget_exhausted = _typo_correct(raw_tokens)
    else:
        tokens = raw_tokens
    steps.append("typo_correct")

    # Final deadline check: step 8 itself may have consumed the remaining
    # budget.  Flag the result so the caller can act accordingly.
    stage_timed_out = (_get_time() - _stage_start) * 1000.0 >= _deadline_s * 1000.0

    return NormalizedInput(
        tokens=tuple(tokens),
        steps_run=tuple(steps),
        original_codepoint_count=raw_cp,
        typo_budget_exhausted=budget_exhausted,
        stage_timed_out=stage_timed_out,
    )
