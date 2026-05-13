"""Optional LLM narrator for source_watcher update plans (Phase 8 preview).

**Contract (must stay true for the life of the project):**

* The summarizer NEVER changes classification or action decisions.
* If the LLM endpoint is unreachable the summarizer returns a
  deterministic, plan-derived Turkish-language string — it does not
  raise and does not drop the plan.
* ``enabled=False`` short-circuits to the deterministic fallback so
  CI and offline tests never touch a network.

Phase 8 will swap in a real adapter; for now the implementation is
a tiny stub that lets us freeze the contract with tests today.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .planner import UpdatePlan

# A Callable that returns a Turkish narrative for a given plan, or raises
# on network failure. The stub uses this signature so real Phase 8 code
# can plug in `openai.Chat…`/`azure.ai.chat…` without changing the caller.
LLMCallable = Callable[[UpdatePlan], str]
ReachabilityProbe = Callable[[str], bool]


@dataclass(frozen=True)
class SummaryResult:
    text: str
    source: str                 # "llm" | "fallback" | "disabled"


def model_id_is_pinned(model_id: str) -> bool:
    pinned = str(model_id or "").strip()
    if not pinned:
        return False
    return not (pinned.endswith("-latest") or pinned.endswith(":latest"))


def probe_endpoint_reachable(url: str, *, timeout_sec: float = 2.0) -> bool:
    probe_url = str(url or "").strip()
    if not probe_url:
        return False
    request = Request(probe_url, method="HEAD")
    try:
        with urlopen(request, timeout=float(timeout_sec)) as response:
            return int(getattr(response, "status", 200)) < 500
    except HTTPError as exc:
        return int(exc.code) < 500
    except (OSError, URLError, ValueError):
        return False


def _deterministic_fallback(up: UpdatePlan) -> str:
    """TR-language summary derived entirely from the plan — no LLM needed."""
    sev_tr = {
        "cosmetic": "kozmetik",
        "semantic": "anlamsal",
        "schema_breaking": "şema kırıcı",
    }.get(up.severity, up.severity)
    n = len(up.diffs)
    return (
        f"{up.source} kaynağında {n} adet '{sev_tr}' değişiklik saptandı. "
        f"Öngörülen eylemler: {', '.join(up.actions)}."
    )


def _call_llm_with_optional_max_tokens(
    llm: LLMCallable,
    up: UpdatePlan,
    max_tokens: Optional[int],
) -> str:
    if max_tokens is None:
        return llm(up)
    try:
        signature = inspect.signature(llm)
    except (TypeError, ValueError):
        return llm(up)
    params = signature.parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if "max_tokens" in params or accepts_kwargs:
        return llm(up, max_tokens=max_tokens)
    return llm(up)


def summarize(
    up: UpdatePlan,
    *,
    enabled: bool = False,
    llm: Optional[LLMCallable] = None,
    max_tokens: Optional[int] = None,
) -> SummaryResult:
    """Return a TR summary for ``up``. Contract guarantees no raise."""
    if not enabled:
        return SummaryResult(text=_deterministic_fallback(up), source="disabled")
    if llm is None:
        return SummaryResult(text=_deterministic_fallback(up), source="fallback")
    try:
        text = _call_llm_with_optional_max_tokens(llm, up, max_tokens)
        if not text:
            return SummaryResult(text=_deterministic_fallback(up), source="fallback")
        return SummaryResult(text=text, source="llm")
    except Exception:
        # Network / timeout / auth / anything: fall back, never propagate.
        return SummaryResult(text=_deterministic_fallback(up), source="fallback")


__all__ = [
    "LLMCallable",
    "ReachabilityProbe",
    "SummaryResult",
    "model_id_is_pinned",
    "probe_endpoint_reachable",
    "summarize",
]
