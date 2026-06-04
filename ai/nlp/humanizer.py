"""Phase 10 §10.8 — Humanizer LLM (opt-in, fenced, decoding-constrained).

**Role.** Rephrase the templated answer for tone. The humanizer:
  - **NEVER** decides the prediction (decision already made by consensus).
  - **NEVER** generates the citation block (citation comes from dispatcher).
  - **NEVER** introduces facts not in the templated answer (rephrasing only).

The humanizer is opt-in polish (cfg.nlp_humanize=false by default). When
enabled, it takes the templated prose (without citation block) and rephrases
it for natural Turkish tone while preserving all facts. The output is
recombined with the unmodified citation block.

Per AGENTS.md Rule 4 (smallest model that works): ≤ 1B params, quantized
GGUF for CPU, bf16 for GPU. Per CLAUDE.md: NEVER use *-latest model IDs
(pinned by exact version in xops/versioning/chart.json).

Decoding constraints (binding, §10.8):
  - temperature=0.3, top_p=0.9, repetition_penalty=1.05
  - max_new_tokens=cfg.nlp_humanizer_max_new_tokens=120
  - Stop sequences include citation block delimiter (prevents bleed)
  - Logit bias against fabricated-fact triggers (numerals/teams not in source,
    English words from ai/nlp/data/en_word_blocklist.txt)

Latency budget: Per-call hard cap cfg.nlp_humanizer_max_latency_ms=600.
Breach → fall back to template, emit nlp.event.v1{kind=humanizer_disabled},
open circuit breaker for cfg.nlp_humanizer_breaker_open_s=60.

Drift guard: Output edit distance vs template ≤ cfg.nlp_humanizer_max_edit_ratio=0.6.
Over-cap → discard, fall back to template, emit nlp.alert.v1{kind=nlp_humanizer_drift}.

GPU sharing: Phase 11 §11.2 round-robin scheduler with patcher LLM (lease swap).

CPU parity: Phase 11 §11.3 — greedy decode with seed=1337 must produce byte-identical
output across CUDA / CPU within ε for tokens (deterministic decode required).
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING

from nlp.vendor.symspell import _edit_distance

if TYPE_CHECKING:
    from common.config import Config


HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON = "humanizer_tenant_budget_exceeded"
HUMANIZER_POD_BUDGET_EXCEEDED_REASON = "humanizer_pod_budget_exceeded"


@dataclass(frozen=True)
class HumanizerAdmissionDecision:
    """Admission decision for per-tenant humanizer scheduling."""

    allowed: bool
    degraded_reason: str | None


class TenantHumanizerBudget:
    """Per-tenant token bucket for humanizer admission (§10.23.1)."""

    def __init__(
        self,
        *,
        cfg: Config,
        burst: int | None = None,
        refill_per_s: float | None = None,
        now_fn: callable | None = None,
    ) -> None:
        self._cfg = cfg
        self._burst = int(
            burst
            if burst is not None
            else cfg.nlp_per_tenant_humanizer_burst
        )
        self._refill_per_s = float(
            refill_per_s
            if refill_per_s is not None
            else cfg.nlp_per_tenant_humanizer_refill_per_s
        )
        if self._burst < 1:
            raise ValueError("nlp_per_tenant_humanizer_burst must be >= 1")
        if self._refill_per_s <= 0.0:
            raise ValueError("nlp_per_tenant_humanizer_refill_per_s must be > 0")

        self._now_fn = now_fn if now_fn is not None else monotonic
        self._lock = Lock()
        self._tokens_by_key: dict[str, float] = {}
        self._last_refill_ts_by_key: dict[str, float] = {}

    def try_acquire(
        self,
        attrs: dict[str, object] | None = None,
        token_count: int = 1,
    ) -> HumanizerAdmissionDecision:
        """Try to admit a humanizer request paying *token_count* humanizer tokens."""
        if token_count < 1:
            raise ValueError("token_count must be >= 1")

        key = self._resolve_key(attrs)
        now = float(self._now_fn())
        effective_budget_per_min = self._resolve_tenant_budget_per_min(attrs)
        effective_burst = min(self._burst, max(1, int(effective_budget_per_min)))
        effective_refill_per_s = float(effective_budget_per_min) / 60.0

        with self._lock:
            tokens = self._tokens_by_key.get(key, float(effective_burst))
            last = self._last_refill_ts_by_key.get(key, now)
            elapsed = max(0.0, now - last)
            refilled = min(float(effective_burst), tokens + elapsed * effective_refill_per_s)

            self._last_refill_ts_by_key[key] = now
            if refilled >= float(token_count):
                self._tokens_by_key[key] = min(refilled - float(token_count), float(effective_burst))
                return HumanizerAdmissionDecision(allowed=True, degraded_reason=None)

            self._tokens_by_key[key] = min(refilled, float(effective_burst))
            return HumanizerAdmissionDecision(
                allowed=False,
                degraded_reason=HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON,
            )

    def _resolve_key(self, attrs: dict[str, object] | None) -> str:
        attrs = attrs or {}

        def _as_str(value: object | None) -> str:
            return str(value).strip() if value is not None else ""

        tenant_id = _as_str(attrs.get("tenant_id"))
        account_id = _as_str(attrs.get("account_id"))
        ip_bucket = _as_str(attrs.get("ip_bucket")) or "ip:unknown"

        if self._cfg.nlp_fairness_key == "tenant_id":
            return tenant_id or account_id or ip_bucket
        if self._cfg.nlp_fairness_key == "account_id":
            return account_id or ip_bucket
        return ip_bucket

    def _resolve_tenant_budget_per_min(self, attrs: dict[str, object] | None) -> int:
        if self._cfg.api_tier_enforcement_enabled and attrs is not None:
            tier_id = str(attrs.get("tier_id_required") or "").strip()
            if tier_id:
                tier_budget = self._cfg.nlp_tier_humanizer_tokens_per_min.get(tier_id)
                if tier_budget is not None:
                    return tier_budget
        return self._cfg.nlp_max_humanizer_tokens_per_tenant_per_min


class PodHumanizerBudget:
    """Per-pod hourly humanizer token ceiling (§10.23.8)."""

    def __init__(
        self,
        *,
        cfg: Config,
        now_fn: callable | None = None,
    ) -> None:
        self._cfg = cfg
        self._now_fn = now_fn if now_fn is not None else monotonic
        self._lock = Lock()
        self._window_start = float(self._now_fn())
        self._tokens_used = 0.0
        self._cooldown_until = 0.0

    def try_acquire(
        self,
        token_count: int = 1,
    ) -> HumanizerAdmissionDecision:
        """Try to admit humanizer tokens against the pod hourly ceiling."""
        if token_count < 1:
            raise ValueError("token_count must be >= 1")

        now = float(self._now_fn())
        with self._lock:
            if now < self._cooldown_until:
                return HumanizerAdmissionDecision(
                    allowed=False,
                    degraded_reason=HUMANIZER_POD_BUDGET_EXCEEDED_REASON,
                )

            if now - self._window_start >= 3600.0:
                self._window_start = now
                self._tokens_used = 0.0

            if self._tokens_used + float(token_count) <= self._cfg.nlp_max_humanizer_tokens_per_pod_per_hour:
                self._tokens_used += float(token_count)
                return HumanizerAdmissionDecision(allowed=True, degraded_reason=None)

            self._cooldown_until = now + float(self._cfg.nlp_humanizer_pod_cooldown_s)
            return HumanizerAdmissionDecision(
                allowed=False,
                degraded_reason=HUMANIZER_POD_BUDGET_EXCEEDED_REASON,
            )


def humanize(
    templated_answer: str,
    *,
    cfg: Config,
) -> str:
    """Rephrase *templated_answer* for natural Turkish tone (opt-in).

    **Role constraints (binding):**
      - **NEVER** decides the prediction (consensus already decided).
      - **NEVER** generates citation block (stripped before call, re-added after).
      - **NEVER** introduces facts not in *templated_answer* (rephrasing only).

    When cfg.nlp_humanize=false (default), returns *templated_answer* unchanged.
    When enabled, rephrases the prose using the ≤1B humanizer LLM (Phase 11 §11.2).

    Decoding constraints:
      - temperature=0.3, top_p=0.9, repetition_penalty=1.05
      - max_new_tokens <= humanizer_max_allowed_new_tokens(cfg=cfg)
      - Stop sequences: citation block delimiter (CITATION_DELIMITER)
      - Logit bias: against numerals/teams not in source, EN words from blocklist

    Latency budget: cfg.nlp_humanizer_max_latency_ms (default 600ms).
    Breach → fall back to *templated_answer*, emit nlp.event.v1{kind=humanizer_disabled}.
    Circuit breaker opens for cfg.nlp_humanizer_breaker_open_s=60 after breach.

    Drift guard: edit_distance(output, input) / len(input) <= cfg.nlp_humanizer_max_edit_ratio.
    Over-cap → discard output, fall back to *templated_answer*, emit nlp.alert.v1{kind=nlp_humanizer_drift}.

    Args:
        templated_answer: The Jinja2-rendered Turkish prose (citation block already
            stripped via render.strip_degraded_for_humanizer or similar).
        cfg: Config instance. If cfg.nlp_humanize=false, returns input unchanged.

    Returns:
        Rephrased Turkish prose (same facts, natural tone). Falls back to
        *templated_answer* on latency breach / drift / error.

    Example:
        >>> from common.config import Config
        >>> cfg = Config()
        >>> template = "Galatasaray'ın kazanma olasılığı yüksek (güven: orta)."
        >>> # With nlp_humanize=false (default), returns unchanged:
        >>> humanize(template, cfg=cfg)
        'Galatasaray'ın kazanma olasılığı yüksek (güven: orta).'
        >>> # With nlp_humanize=true, would rephrase (Phase 11 integration):
        >>> # "Galatasaray'ın bu maçı kazanma şansı oldukça yüksek görünüyor."

    Notes:
        - **Phase 10 stub:** Returns *templated_answer* unchanged (humanize always off).
        - **Phase 11 §11.2:** LLM integration (Trendyol-LLM-1B-base or equivalent).
        - **Phase 11 §11.3:** CPU parity test (greedy seed=1337, byte-identical output).
        - The caller is responsible for stripping/re-adding citation block.
        - Degraded-mode disclaimer must bypass humanizer (§10.7 binding).
        - **§10.15 humanizer bypass list:** ``meta.*`` intents (``meta.help``,
          ``meta.unsupported``, ``meta.adversarial``) use fixed phrasing and must
          NOT be rephrased by the humanizer; proofreader still runs PII check.
    """
    # Phase 10 stub: humanizer is documented but not integrated (Phase 11 §11.2).
    # When the LLM is integrated, apply drift guard to the output.
    # For now, always return unchanged (no LLM call, no drift).
    #
    # Phase 11 §11.2 GPU sharing workflow (when LLM is active):
    # lease_token = _acquire_gpu_lease(cfg=cfg)  # Round-robin scheduler
    # try:
    #     output = _call_llm(templated_answer, cfg=cfg)  # Uses leased GPU
    #     if _check_drift_guard(templated_answer, output, cfg=cfg):
    #         return output
    #     else:
    #         # emit nlp.alert.v1{kind=nlp_humanizer_drift, severity=warn}
    #         return templated_answer
    # finally:
    #     _release_gpu_lease(lease_token)  # Lease swap → patcher can acquire
    return templated_answer


def humanizer_max_allowed_new_tokens(*, cfg: Config) -> int:
    """Return the effective per-request humanizer output token cap.

    This is the smaller of the model's decode cap and the explicit per-request
    budget defined by cfg.nlp_max_humanizer_tokens_per_request.
    """
    return min(cfg.nlp_humanizer_max_new_tokens, cfg.nlp_max_humanizer_tokens_per_request)


def _check_drift_guard(
    templated_answer: str,
    humanized_output: str,
    *,
    cfg: Config,
) -> bool:
    """Check if *humanized_output* passes the drift guard.

    Returns True if edit_distance / len(template) <= cfg.nlp_humanizer_max_edit_ratio.
    Returns False if over-cap (caller should discard and fall back to template).

    Args:
        templated_answer: The original templated prose.
        humanized_output: The LLM-generated rephrased output.
        cfg: Config instance.

    Returns:
        True if output passes drift guard, False if over-cap.
    """
    if not templated_answer:
        # Empty template → no drift possible
        return True
    
    distance = _edit_distance(templated_answer, humanized_output)
    ratio = distance / len(templated_answer)
    return ratio <= cfg.nlp_humanizer_max_edit_ratio


# ──────────────────────────────────────────────────────────────────────────────
# GPU Sharing (Phase 11 §11.2)
# ──────────────────────────────────────────────────────────────────────────────

def _acquire_gpu_lease(*, cfg: Config) -> str:
    """Acquire a GPU lease from the Phase 11 §11.2 round-robin scheduler.

    **Lease swap contract (binding):**
      - The humanizer LLM and the Phase 8 patcher LLM coexist by **lease swap**,
        not concurrent load. Only one LLM holds a lease at a time.
      - Lease acquisition blocks until the GPU is available or times out.
      - Lease must be released via `_release_gpu_lease(lease_token)` in a
        finally block to ensure the patcher (or other LLM) can acquire.
      - On timeout or lease unavailable, caller must fall back to template-only
        mode and emit nlp.event.v1{kind=humanizer_disabled, reason=no_gpu_lease}.

    **Phase 11 §11.2 integration:**
      - Scheduler lives at `ai/swarm/sdk/gpu_arbiter.py` (not yet implemented).
      - Arbiter coordinates via Redis locks or a shared lease table.
      - Lease duration is bounded by cfg.nlp_humanizer_max_latency_ms (default 600ms).

    Args:
        cfg: Config instance.

    Returns:
        Opaque lease token (string). Must be passed to `_release_gpu_lease()`.

    Raises:
        TimeoutError: If lease cannot be acquired within cfg.nlp_humanizer_max_latency_ms.

    Notes:
        - **Phase 10 stub:** Always raises NotImplementedError (GPU arbiter is Phase 11).
        - **Phase 11 §11.2:** Real implementation calls `gpu_arbiter.acquire_lease()`.
        - **Phase 14 K8s:** Per-pod GPU lease; refuses to start if lease unattainable
          AND cfg.nlp_humanize=true (cleanly degrades to template-only).
    """
    raise NotImplementedError(
        "GPU lease acquisition is a Phase 11 §11.2 feature (ai/swarm/sdk/gpu_arbiter.py). "
        "Humanizer currently runs in stub mode (always returns template unchanged)."
    )


def _release_gpu_lease(lease_token: str) -> None:
    """Release the GPU lease acquired via `_acquire_gpu_lease()`.

    Must be called in a finally block to ensure lease swap with patcher LLM.

    Args:
        lease_token: The opaque token returned by `_acquire_gpu_lease()`.

    Notes:
        - **Phase 10 stub:** Always raises NotImplementedError.
        - **Phase 11 §11.2:** Real implementation calls `gpu_arbiter.release_lease(token)`.
    """
    raise NotImplementedError(
        "GPU lease release is a Phase 11 §11.2 feature (ai/swarm/sdk/gpu_arbiter.py)."
    )
