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
from typing import Callable, Optional

from .planner import UpdatePlan

# A Callable that returns a Turkish narrative for a given plan, or raises
# on network failure. The stub uses this signature so real Phase 8 code
# can plug in `openai.Chat…`/`azure.ai.chat…` without changing the caller.
LLMCallable = Callable[[UpdatePlan], str]


@dataclass(frozen=True)
class SummaryResult:
    text: str
    source: str                 # "llm" | "fallback" | "disabled"


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


def summarize(
    up: UpdatePlan,
    *,
    enabled: bool = False,
    llm: Optional[LLMCallable] = None,
) -> SummaryResult:
    """Return a TR summary for ``up``. Contract guarantees no raise."""
    if not enabled:
        return SummaryResult(text=_deterministic_fallback(up), source="disabled")
    if llm is None:
        return SummaryResult(text=_deterministic_fallback(up), source="fallback")
    try:
        text = llm(up)
        if not text:
            return SummaryResult(text=_deterministic_fallback(up), source="fallback")
        return SummaryResult(text=text, source="llm")
    except Exception:
        # Network / timeout / auth / anything: fall back, never propagate.
        return SummaryResult(text=_deterministic_fallback(up), source="fallback")
