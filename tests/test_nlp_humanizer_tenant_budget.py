"""Phase 10 §10.23.1 — humanizer per-tenant budget tests."""
from __future__ import annotations

from common.config import Config
from nlp.humanizer import (
    HUMANIZER_POD_BUDGET_EXCEEDED_REASON,
    HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON,
    PodHumanizerBudget,
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


def test_nlp_humanizer_tenant_token_budget_charges_token_counts() -> None:
    cfg = Config()
    clock = _FakeClock()
    budget = TenantHumanizerBudget(
        cfg=cfg,
        burst=3,
        refill_per_s=1.0,
        now_fn=clock,
    )

    first = budget.try_acquire({"account_id": "acct-a"}, token_count=2)
    second = budget.try_acquire({"account_id": "acct-a"}, token_count=2)

    assert first.allowed is True
    assert second.allowed is False
    assert second.degraded_reason == HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON


def test_nlp_humanizer_pod_budget_triggers_cooldown() -> None:
    cfg = Config()
    clock = _FakeClock()
    cfg.nlp_max_humanizer_tokens_per_pod_per_hour = 10
    cfg.nlp_humanizer_pod_cooldown_s = 60
    budget = PodHumanizerBudget(cfg=cfg, now_fn=clock)

    assert budget.try_acquire(token_count=5).allowed is True
    assert budget.try_acquire(token_count=5).allowed is True
    blocked = budget.try_acquire(token_count=1)
    assert blocked.allowed is False
    assert blocked.degraded_reason == HUMANIZER_POD_BUDGET_EXCEEDED_REASON
    assert budget.try_acquire(token_count=1).allowed is False

    clock.now += 60.0
    assert budget.try_acquire(token_count=1).allowed is False

    clock.now += 3540.0
    assert budget.try_acquire(token_count=1).allowed is True


def test_nlp_humanizer_tenant_budget_overrides_to_tier_budget_when_monetization_enabled() -> None:
    cfg = Config()
    clock = _FakeClock()
    cfg.api_tier_enforcement_enabled = True
    cfg._nlp_tier_humanizer_tokens_per_min_raw = '{"pro": 1}'
    budget = TenantHumanizerBudget(cfg=cfg, burst=4, now_fn=clock)

    first = budget.try_acquire({"account_id": "acct-a", "tier_id_required": "pro"})
    second = budget.try_acquire({"account_id": "acct-a", "tier_id_required": "pro"})

    assert first.allowed is True
    assert first.degraded_reason is None
    assert second.allowed is False
    assert second.degraded_reason == HUMANIZER_TENANT_BUDGET_EXCEEDED_REASON
