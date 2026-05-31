"""Phase 10 §10.23.1 — humanizer per-tenant budget tests."""
from __future__ import annotations

from common.config import Config
from nlp.humanizer import (
    HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON,
    TenantHumanizerBudget,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_nlp_humanizer_tenant_budget_degrades_to_template() -> None:
    cfg = Config()
    clock = _FakeClock()
    budget = TenantHumanizerBudget(
        cfg=cfg,
        burst=1,
        refill_per_s=2.0,
        now_fn=clock,
    )

    first = budget.try_acquire({"account_id": "acct-a"})
    second = budget.try_acquire({"account_id": "acct-a"})
    other_tenant = budget.try_acquire({"account_id": "acct-b"})

    assert first.allowed is True
    assert first.degraded_reason is None
    assert second.allowed is False
    assert second.degraded_reason == HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON
    assert other_tenant.allowed is True


def test_nlp_humanizer_tenant_budget_refills_after_window() -> None:
    cfg = Config()
    clock = _FakeClock()
    budget = TenantHumanizerBudget(
        cfg=cfg,
        burst=1,
        refill_per_s=2.0,
        now_fn=clock,
    )

    assert budget.try_acquire({"account_id": "acct-a"}).allowed is True
    blocked = budget.try_acquire({"account_id": "acct-a"})
    assert blocked.allowed is False
    assert blocked.degraded_reason == HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON

    clock.now += 0.5
    allowed_again = budget.try_acquire({"account_id": "acct-a"})
    assert allowed_again.allowed is True
    assert allowed_again.degraded_reason is None
