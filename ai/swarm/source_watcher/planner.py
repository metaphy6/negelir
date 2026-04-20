"""Update planner — turn classified diffs into an actionable plan.

Pure logic, no side-effects. Phase 8 will swap in an LLM narrator that
*augments* the human-readable summary, but the action set is decided
deterministically here so behaviour is reproducible and testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .classifier import (
    COSMETIC,
    SCHEMA_BREAKING,
    SEMANTIC,
    ClassifiedDiff,
    worst_severity,
)

# Action codes the orchestrator understands.
ACTION_SKIP = "skip"
ACTION_REFRESH_FIXTURES = "refresh_fixtures"
ACTION_RUN_PARITY_TESTS = "run_parity_tests"
ACTION_OPEN_TICKET = "open_ticket"
ACTION_PAGE_HUMAN = "page_human"


@dataclass(frozen=True)
class UpdatePlan:
    source: str
    severity: str
    actions: List[str]
    summary: str
    diffs: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _summary_for(severity: str, source: str, n: int) -> str:
    if severity == COSMETIC:
        return f"{source}: {n} cosmetic change(s); no action needed"
    if severity == SEMANTIC:
        return f"{source}: {n} semantic change(s); rerun parity + refresh fixtures"
    return f"{source}: {n} schema-breaking change(s); HUMAN ATTENTION REQUIRED"


def _actions_for(severity: str) -> List[str]:
    if severity == COSMETIC:
        return [ACTION_SKIP]
    if severity == SEMANTIC:
        return [ACTION_RUN_PARITY_TESTS, ACTION_REFRESH_FIXTURES]
    # SCHEMA_BREAKING
    return [ACTION_RUN_PARITY_TESTS, ACTION_OPEN_TICKET, ACTION_PAGE_HUMAN]


def plan(source: str, classified: List[ClassifiedDiff]) -> UpdatePlan:
    severity = worst_severity(classified)
    diffs_payload = [
        {
            "path": c.diff.path,
            "kind": c.diff.kind,
            "severity": c.severity,
            "reason": c.reason,
        }
        for c in classified
    ]
    return UpdatePlan(
        source=source,
        severity=severity,
        actions=_actions_for(severity) if classified else [ACTION_SKIP],
        summary=_summary_for(severity, source, len(classified)),
        diffs=diffs_payload,
    )
