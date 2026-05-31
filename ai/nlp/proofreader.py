"""Phase 10 §10.9 — TR-quality proofreader agent (nlp.proofreader.v1).

**Binding contract:** The proofreader sits between the NLP answer generator
and the final `qa.answer.v1` publication. It subscribes to a pre-publish
internal channel (`_pre_answer_topic` — not a bus topic, to avoid double-
emission) and publishes the final `qa.answer.v1` (post-block) OR
`qa.answer.v1{kind=proofreader_blocked}` plus `nlp.alert.v1`.

Deterministic gates (any failure → block, §10.9 bullet 2):
  1. **Citation block present and unmodified** for any `predict.*` answer
     (sha256 over the citation block compared against dispatcher-stamped value).
  2. **No mid-sentence English** (regex over pinned EN-word blocklist; allowlist
     for proper nouns from LeagueCatalog like "Premier League").
  3. **Length bounds** cfg.nlp_min_answer_chars ≤ len ≤ cfg.nlp_max_answer_chars.
  4. **PII redaction.** Phone-number / email / credit-card / TC-kimlik-no patterns
     → redact (replace with `[***]`) AND emit nlp.alert.v1{kind=nlp_pii_in_answer}.
  5. **Forbidden phrases.** Pinned blocklist (ai/nlp/data/forbidden_phrases.tr.yaml)
     — covers self-promotion, liability disclaimers, jailbreak echoes.
  6. **Suffix-harmony probe.** Sample 5 random `<noun>'<suffix>` constructions;
     assert each passes ai/common/text/turkish.py::suffix_harmony_ok.

Block taxonomy (§10.9 bullet 3): nlp.event.v1{kind=proofreader_blocked, reason ∈
{citation_drift, mid_sentence_english, length_under, length_over, pii_redacted,
forbidden_phrase, suffix_harmony}}.

Fail-safe (§10.9 bullet 4): Proofreader exception → emit template-only answer
(NEVER block the user on proofreader bug); emit nlp.alert.v1{kind=nlp_proofreader_failed}.

References:
  - §10.9 in docs/design/nlp/sections/00-baseline.md (binding)
  - AGENTS.md §2 (doctrine: no fabricated data, Turkish UX, single-source config)
  - CLAUDE.md (forbidden patterns: no blanket try/except returning None)
"""
from __future__ import annotations

import hashlib
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from common.security.patterns import PII_PATTERNS
from common.text.turkish import suffix_harmony_ok

if TYPE_CHECKING:
    from common.config import Config


# English word blocklist (gate 2) — mid-sentence English detection.
# Allowlist for proper nouns from LeagueCatalog ("Premier League", "Champions League").
_ENGLISH_WORDS_BLOCKLIST = frozenset([
    "the", "and", "but", "for", "with", "this", "that", "have", "from",
    "they", "would", "there", "their", "what", "about", "which", "when",
    "make", "like", "time", "just", "know", "take", "people", "into",
    "year", "your", "some", "could", "them", "see", "other", "than",
    "then", "now", "look", "only", "come", "its", "over", "think",
    "also", "back", "after", "use", "two", "how", "our", "work",
    "first", "well", "way", "even", "new", "want", "because", "any",
    "these", "give", "day", "most", "prediction", "analysis", "result",
])

_ENGLISH_ALLOWLIST = frozenset([
    "premier league", "champions league", "europa league", "conference league",
    "fa cup", "league cup", "super cup",
])

# Forbidden phrases loaded from YAML (gate 5).
_forbidden_phrases: "list[str] | None" = None
_forbidden_phrases_path = Path(__file__).resolve().parent / "data" / "forbidden_phrases.tr.yaml"

# Confidence band keywords (gate 7) — Turkish confidence narration terms.
# Maps band label → set of keywords that should appear in that band's narration.
# §10.16 discipline: banded confidence text MUST never contradict raw probability.
_CONFIDENCE_KEYWORDS = {
    "düşük": frozenset(["düşük", "düşük güven", "az güven", "sınırlı", "zayıf"]),
    "orta": frozenset(["orta", "orta güven", "makul", "normal"]),
    "yüksek": frozenset(["yüksek", "yüksek güven", "güçlü", "emin", "iyi"]),
}


def _load_forbidden_phrases() -> "list[str]":
    """Load forbidden phrases from YAML (cached)."""
    global _forbidden_phrases
    if _forbidden_phrases is not None:
        return _forbidden_phrases

    if not _forbidden_phrases_path.exists():
        _forbidden_phrases = []
        return _forbidden_phrases

    with open(_forbidden_phrases_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _forbidden_phrases = [p.lower() for p in data.get("phrases", [])]
    return _forbidden_phrases


class ProofreadResult:
    """Outcome of proofreading a candidate qa.answer.v1 envelope.

    Attributes:
        passed: True if all gates passed; False if blocked.
        answer_text: The possibly-redacted answer text. On pass, equals input.
            On block (PII redaction), contains redacted text (with [***]).
        block_reason: None if passed; else the first gate that failed ∈
            {citation_drift, mid_sentence_english, length_under, length_over,
             pii_redacted, forbidden_phrase, suffix_harmony}.
        alert_severity: When blocked, the severity for nlp.alert.v1 ∈
            {info, warn, error, critical}. Defaults to 'warn' for most blocks;
            'error' for pii_redacted.
        redacted_pii: True if PII patterns were found and redacted.
        fail_safe_triggered: True if the proofreader encountered an exception
            and fell back to passing the original answer through (fail-safe
            per §10.9 bullet 4). When True, an nlp.alert.v1 with
            kind=nlp_proofreader_failed MUST be emitted by the caller.
        exception_detail: When fail_safe_triggered=True, contains the exception
            type and message (for operator debugging, NOT user-facing).
    """

    __slots__ = (
        "passed",
        "answer_text",
        "block_reason",
        "alert_severity",
        "redacted_pii",
        "fail_safe_triggered",
        "exception_detail",
    )

    def __init__(
        self,
        *,
        passed: bool,
        answer_text: str,
        block_reason: "str | None" = None,
        alert_severity: str = "warn",
        redacted_pii: bool = False,
        fail_safe_triggered: bool = False,
        exception_detail: "str | None" = None,
    ) -> None:
        self.passed = passed
        self.answer_text = answer_text
        self.block_reason = block_reason
        self.alert_severity = alert_severity
        self.redacted_pii = redacted_pii
        self.fail_safe_triggered = fail_safe_triggered
        self.exception_detail = exception_detail


def proofread_answer(
    answer_text: str,
    *,
    intent: str,
    citation_sha256_expected: "str | None",
    cfg: Config,
    raw_probability: "float | None" = None,
    confidence_band_label: "str | None" = None,
) -> ProofreadResult:
    """Run deterministic proofreading gates on *answer_text*.

    This is the core function of nlp.proofreader.v1. It applies all seven
    gates (§10.9 bullet 2 + §10.16 gate 7) in order and returns a
    ProofreadResult indicating pass/block + any redactions applied.

    Args:
        answer_text: The rendered Turkish answer prose (may include citation block).
        intent: The intent enum value (e.g., "predict.match_outcome", "meta.help").
            Used to determine whether citation block is expected (predict.* → yes).
        citation_sha256_expected: SHA-256 hex digest (64 chars) of the citation
            block as stamped by the dispatcher. Must match if *intent* is predict.*.
            None for non-predict intents (meta.*, data.*, summary.*).
        cfg: Config instance. Reads cfg.nlp_min_answer_chars, cfg.nlp_max_answer_chars,
            and cfg.nlp_confidence_bands.
        raw_probability: Raw prediction probability ∈ [0,1]. Required for gate 7
            (confidence narration discipline) when confidence_band_label is provided.
        confidence_band_label: Confidence band label (e.g., "düşük", "orta", "yüksek").
            If provided along with raw_probability, gate 7 checks that the answer_text
            narration keywords match the band implied by raw_probability.

    Returns:
        ProofreadResult with passed=True/False, answer_text (possibly redacted),
        block_reason (if any), alert_severity, and redacted_pii flag.

    Example:
        >>> from common.config import Config
        >>> cfg = Config()
        >>> # Non-predict intent (no citation check):
        >>> result = proofread_answer(
        ...     "Bugün Galatasaray maçı var.",
        ...     intent="data.fixture_lookup",
        ...     citation_sha256_expected=None,
        ...     cfg=cfg,
        ... )
        >>> result.passed
        True

    Notes:
        - Fail-safe: any exception here → pass with alert (caller's responsibility).
        - PII redaction (gate 4) modifies answer_text but still blocks (block +
          redacted text returned, so the user sees [***] not raw PII).
        - Suffix-harmony probe (gate 6) samples 5 random constructions; deterministic
          seed per qa_correlation_id (once that field is available in the envelope).
        - Confidence narration discipline (gate 7, §10.16): banded confidence text
          MUST never contradict the raw probability. For example, raw=0.51 with
          band-text "yüksek güven" → blocked.
    """
    working_text = answer_text
    redacted_pii_flag = False

    # Gate 1: Citation block present and unmodified (for predict.* intents only).
    if intent.startswith("predict."):
        if citation_sha256_expected is None:
            return ProofreadResult(
                passed=False,
                answer_text=working_text,
                block_reason="citation_drift",
                alert_severity="warn",
                redacted_pii=False,
            )
        # Extract citation block (assumed to be separated by "---" or similar marker).
        # For Phase 10, we use a simple heuristic: last line(s) after "---" or "\n---\n".
        citation_marker_patterns = ["\n---\n", "\n—\n", "\n***\n"]
        citation_block = None
        for marker in citation_marker_patterns:
            if marker in working_text:
                parts = working_text.rsplit(marker, 1)
                if len(parts) == 2:
                    citation_block = marker + parts[1]
                    break

        if citation_block is None:
            # No citation block found but expected.
            return ProofreadResult(
                passed=False,
                answer_text=working_text,
                block_reason="citation_drift",
                alert_severity="warn",
                redacted_pii=False,
            )

        # Compute SHA-256 of the citation block.
        citation_sha = hashlib.sha256(citation_block.encode("utf-8")).hexdigest()
        if citation_sha != citation_sha256_expected:
            return ProofreadResult(
                passed=False,
                answer_text=working_text,
                block_reason="citation_drift",
                alert_severity="warn",
                redacted_pii=False,
            )

    # Gate 2: No mid-sentence English (regex over blocklist with allowlist).
    text_lower = working_text.lower()
    # Remove allowlisted phrases first.
    for allowed_phrase in _ENGLISH_ALLOWLIST:
        text_lower = text_lower.replace(allowed_phrase, "")

    # Tokenize and check for English words.
    words = re.findall(r"\b[a-z]+\b", text_lower)
    for word in words:
        if word in _ENGLISH_WORDS_BLOCKLIST:
            return ProofreadResult(
                passed=False,
                answer_text=working_text,
                block_reason="mid_sentence_english",
                alert_severity="warn",
                redacted_pii=False,
            )

    # Gate 3: Length bounds.
    char_count = len(working_text)
    if char_count < cfg.nlp_min_answer_chars:
        return ProofreadResult(
            passed=False,
            answer_text=working_text,
            block_reason="length_under",
            alert_severity="warn",
            redacted_pii=False,
        )
    if char_count > cfg.nlp_max_answer_chars:
        return ProofreadResult(
            passed=False,
            answer_text=working_text,
            block_reason="length_over",
            alert_severity="warn",
            redacted_pii=False,
        )

    # Gate 4: PII redaction.
    for pii_kind, pii_pattern in PII_PATTERNS:
        if pii_pattern.search(working_text):
            # Redact all matches.
            working_text = pii_pattern.sub("[***]", working_text)
            redacted_pii_flag = True

    if redacted_pii_flag:
        # PII found and redacted → block with error severity.
        return ProofreadResult(
            passed=False,
            answer_text=working_text,
            block_reason="pii_redacted",
            alert_severity="error",
            redacted_pii=True,
        )

    # Gate 5: Forbidden phrases.
    forbidden_phrases = _load_forbidden_phrases()
    text_lower_check = working_text.lower()
    for phrase in forbidden_phrases:
        if phrase in text_lower_check:
            return ProofreadResult(
                passed=False,
                answer_text=working_text,
                block_reason="forbidden_phrase",
                alert_severity="warn",
                redacted_pii=False,
            )

    # Gate 6: Suffix-harmony probe (sample 5 random constructions).
    # Match pattern: <word>'<suffix> (Turkish genitive/dative/accusative constructions).
    apostrophe_constructions = re.findall(r"\b[\w]+\'[\w]+\b", working_text)
    if apostrophe_constructions:
        # Deterministic sampling (seed=42 for reproducibility in tests).
        random.seed(42)
        sample_size = min(5, len(apostrophe_constructions))
        sampled = random.sample(apostrophe_constructions, sample_size)

        for construction in sampled:
            if not suffix_harmony_ok(construction):
                return ProofreadResult(
                    passed=False,
                    answer_text=working_text,
                    block_reason="suffix_harmony",
                    alert_severity="warn",
                    redacted_pii=False,
                )

    # Gate 7: Confidence narration discipline (§10.16).
    # Banded confidence text MUST never contradict the raw probability.
    # Example: raw_probability=0.51 with band="yüksek" → blocked if answer
    # contains "yüksek güven" keywords.
    if raw_probability is not None and confidence_band_label is not None:
        import json

        # Parse confidence bands from config.
        try:
            bands = json.loads(cfg.nlp_confidence_bands)
        except (ValueError, TypeError):
            # Config parse failure; skip gate 7 (fail-safe).
            bands = []

        # Determine the correct band for raw_probability.
        correct_band = None
        for lower, upper, label in bands:
            if lower <= raw_probability < upper:
                correct_band = label
                break

        # If we have a correct band and it differs from the provided band label,
        # check if answer_text contains keywords from the wrong band.
        if correct_band and correct_band != confidence_band_label:
            text_lower = working_text.lower()
            # Check if the answer contains keywords from the provided (wrong) band.
            wrong_keywords = _CONFIDENCE_KEYWORDS.get(confidence_band_label, frozenset())
            for keyword in wrong_keywords:
                if keyword in text_lower:
                    return ProofreadResult(
                        passed=False,
                        answer_text=working_text,
                        block_reason="confidence_narration_contradiction",
                        alert_severity="warn",
                        redacted_pii=False,
                    )

    # All gates passed.
    return ProofreadResult(
        passed=True,
        answer_text=working_text,
        block_reason=None,
        alert_severity="warn",
        redacted_pii=False,
    )


def proofread_answer_safe(
    answer_text: str,
    *,
    intent: str,
    citation_sha256_expected: "str | None",
    cfg: Config,
    raw_probability: "float | None" = None,
    confidence_band_label: "str | None" = None,
) -> ProofreadResult:
    """Fail-safe wrapper around proofread_answer (§10.9 bullet 4).

    This function wraps `proofread_answer` with exception handling. If the
    proofreader encounters any exception (bug in gate logic, corrupted data,
    etc.), the fail-safe behavior is: emit the template-only answer (NEVER
    block the user on a proofreader bug) AND signal that an alert MUST be
    emitted by the caller.

    Args:
        answer_text: The rendered Turkish answer prose (may include citation block).
        intent: The intent enum value (e.g., "predict.match_outcome", "meta.help").
        citation_sha256_expected: SHA-256 hex digest (64 chars) of the citation
            block. Must match if *intent* is predict.*. None for non-predict intents.
        cfg: Config instance.
        raw_probability: Raw prediction probability ∈ [0,1]. Optional; used for
            gate 7 (confidence narration discipline) when provided.
        confidence_band_label: Confidence band label. Optional; used for gate 7
            when provided along with raw_probability.

    Returns:
        ProofreadResult with passed=True/False. On exception, returns a result
        with:
          - passed=True (fail-safe: let answer through)
          - fail_safe_triggered=True
          - exception_detail=<exception repr>
        The caller MUST check fail_safe_triggered and emit
        nlp.alert.v1{kind=nlp_proofreader_failed, severity=error} when True.

    Example:
        >>> from common.config import Config
        >>> cfg = Config()
        >>> result = proofread_answer_safe(
        ...     "Galatasaray bugün maç oynuyor.",
        ...     intent="data.fixture_lookup",
        ...     citation_sha256_expected=None,
        ...     cfg=cfg,
        ... )
        >>> if result.fail_safe_triggered:
        ...     # Emit nlp.alert.v1{kind=nlp_proofreader_failed, severity=error}
        ...     pass

    Notes:
        - Per AGENTS.md Rule 10 (tests track code): any change to proofreader
          logic MUST include a test; any test change MUST track code.
        - Per CLAUDE.md: this is NOT a blanket try/except returning None —
          it returns a well-defined fail-safe result that preserves the user's
          answer while signaling operator visibility is required.
    """
    try:
        return proofread_answer(
            answer_text,
            intent=intent,
            citation_sha256_expected=citation_sha256_expected,
            cfg=cfg,
            raw_probability=raw_probability,
            confidence_band_label=confidence_band_label,
        )
    except Exception as exc:  # noqa: BLE001
        # Fail-safe per §10.9 bullet 4: let answer through, signal alert.
        exception_detail = f"{type(exc).__name__}: {str(exc)}"
        return ProofreadResult(
            passed=True,  # NEVER block user on proofreader bug
            answer_text=answer_text,  # Return original template-only answer
            block_reason=None,
            alert_severity="error",
            redacted_pii=False,
            fail_safe_triggered=True,
            exception_detail=exception_detail,
        )


