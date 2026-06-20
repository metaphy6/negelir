"""Phase 10 §10.15 — Defense-in-depth injection probe.

Even though ``sec.input.v1`` already classifies ``qa.request`` and produces
``qa.request.v1``, NLP runs a **second-pass deterministic injection probe**
on the normalized text against the same ``injection_patterns.yaml``
(single-source) — defends against an injection that survived sanitize because
rules drifted.

Hit → route intent to ``meta.adversarial``, emit
``nlp.alert.v1{kind=nlp_secondary_injection_hit, severity=warn}``.

This module is a thin wrapper over :mod:`common.security.patterns` that
exposes an NLP-oriented check function and abstracts the ruleset loading.
"""
from __future__ import annotations

from typing import Optional

from ai.common.security.patterns import (
    CompiledRule,
    RuleSet,
    current_ruleset,
)


class InjectionProbeResult:
    """Result of the second-pass injection probe.

    Attributes:
        detected: True if any injection pattern matched the normalized text.
        matched_rule_id: The ``rule_id`` of the first matching pattern, or None.
        matched_reason: The ``reason`` field of the first matching pattern, or None.
        matched_severity: The ``severity`` field of the first matching pattern, or None.
    """

    __slots__ = ("detected", "matched_rule_id", "matched_reason", "matched_severity")

    def __init__(
        self,
        detected: bool,
        matched_rule_id: Optional[str] = None,
        matched_reason: Optional[str] = None,
        matched_severity: Optional[str] = None,
    ):
        self.detected = detected
        self.matched_rule_id = matched_rule_id
        self.matched_reason = matched_reason
        self.matched_severity = matched_severity


def probe_normalized_text(text: str) -> InjectionProbeResult:
    """Run the second-pass injection probe against normalized text.

    This is the NLP defense-in-depth check per §10.15. The patterns are
    loaded from the same ``injection_patterns.yaml`` that ``sec.input.v1``
    uses (single-source, hot-reloadable).

    Args:
        text: The normalized text to check (post §10.1 normalization).

    Returns:
        An :class:`InjectionProbeResult` with ``detected=True`` if any
        pattern matched, ``detected=False`` otherwise.

    The caller is responsible for:

    * routing to ``meta.adversarial`` intent when ``detected=True``;
    * emitting ``nlp.alert.v1{kind=nlp_secondary_injection_hit, severity=warn}``
      (debounced via ``swarm.sdk.AlertDebouncer``).

    Thread-safety:
        This function is safe to call from multiple threads concurrently.
        It takes a snapshot reference to the current ruleset and works
        with that immutable snapshot.
    """
    if not text:
        return InjectionProbeResult(detected=False)

    ruleset: Optional[RuleSet] = current_ruleset()
    if ruleset is None:
        # Patterns not loaded yet (unlikely but possible at startup).
        # Fail open: no patterns → no detection.
        return InjectionProbeResult(detected=False)

    matched: Optional[CompiledRule] = ruleset.match(text)
    if matched is None:
        return InjectionProbeResult(detected=False)

    return InjectionProbeResult(
        detected=True,
        matched_rule_id=matched.rule_id,
        matched_reason=matched.reason,
        matched_severity=matched.severity,
    )


__all__ = [
    "InjectionProbeResult",
    "probe_normalized_text",
]
