"""Phase 10 §10.23.1 — per-tenant intake fair-queue tests."""
from __future__ import annotations

from nlp.intake_fair_queue import NlpIntakeFairQueue


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def test_round_robin_dispatch_over_non_empty_keys() -> None:
    queue = NlpIntakeFairQueue[str](
        fairness_key="account_id",
        per_tenant_inflight_max=8,
        max_tracked_keys=100,
    )

    queue.enqueue("a-1", {"account_id": "acct-a"})
    queue.enqueue("a-2", {"account_id": "acct-a"})
    queue.enqueue("b-1", {"account_id": "acct-b"})

    d1 = queue.dequeue()
    d2 = queue.dequeue()
    d3 = queue.dequeue()

    assert d1 is not None and (d1.key, d1.item) == ("acct-a", "a-1")
    assert d2 is not None and (d2.key, d2.item) == ("acct-b", "b-1")
    assert d3 is not None and (d3.key, d3.item) == ("acct-a", "a-2")


def test_per_tenant_inflight_cap_isolates_noisy_tenant() -> None:
    queue = NlpIntakeFairQueue[str](
        fairness_key="account_id",
        per_tenant_inflight_max=1,
        max_tracked_keys=100,
    )

    queue.enqueue("a-1", {"account_id": "acct-a"})
    queue.enqueue("a-2", {"account_id": "acct-a"})
    queue.enqueue("b-1", {"account_id": "acct-b"})

    d1 = queue.dequeue()
    d2 = queue.dequeue()
    d3 = queue.dequeue()

    assert d1 is not None and (d1.key, d1.item) == ("acct-a", "a-1")
    assert d2 is not None and (d2.key, d2.item) == ("acct-b", "b-1")
    assert d3 is None

    queue.complete("acct-a")
    d4 = queue.dequeue()
    assert d4 is not None and (d4.key, d4.item) == ("acct-a", "a-2")


def test_account_key_falls_back_to_ip_bucket_for_unauthenticated() -> None:
    queue = NlpIntakeFairQueue[str](
        fairness_key="account_id",
        per_tenant_inflight_max=8,
        max_tracked_keys=100,
    )

    key = queue.enqueue("anon", {"ip_bucket": "198.51.100.0/24"})

    assert key == "198.51.100.0/24"


def test_tracked_key_lru_eviction_is_bounded() -> None:
    evicted: list[str] = []
    queue = NlpIntakeFairQueue[str](
        fairness_key="account_id",
        per_tenant_inflight_max=8,
        max_tracked_keys=2,
        on_key_evicted=evicted.append,
    )

    queue.enqueue("a", {"account_id": "acct-a"})
    queue.enqueue("b", {"account_id": "acct-b"})
    queue.enqueue("a-2", {"account_id": "acct-a"})
    queue.enqueue("c", {"account_id": "acct-c"})

    assert queue.tracked_key_count() == 2
    assert evicted == ["acct-b"]


def test_tenant_abuse_signal_emits_and_debounces_per_key_class() -> None:
    clock = _FakeClock()
    abuse_alerts: list[tuple[str, float]] = []
    rate_samples: list[tuple[str, float]] = []

    queue = NlpIntakeFairQueue[str](
        fairness_key="account_id",
        per_tenant_inflight_max=8,
        max_tracked_keys=100,
        tenant_abuse_qps_threshold=1.0,
        tenant_abuse_window_s=2,
        on_tenant_intake_rate=lambda key_class, qps: rate_samples.append((key_class, qps)),
        on_tenant_abuse_detected=lambda key_class, qps: abuse_alerts.append((key_class, qps)),
        clock=clock,
    )

    # Sustained account_free overload: alert emits once, then debounces.
    queue.enqueue("x0", {"account_id": "acct-free"})
    clock.advance(1.0)
    queue.enqueue("x1", {"account_id": "acct-free"})
    clock.advance(1.0)
    queue.enqueue("x2", {"account_id": "acct-free"})
    clock.advance(1.0)
    queue.enqueue("x3", {"account_id": "acct-free"})

    assert abuse_alerts == [("account_free", 1.5)]
    assert rate_samples[-1][0] == "account_free"

    # Debounce window is 5 minutes per class.
    clock.advance(301.0)
    queue.enqueue("x4", {"account_id": "acct-free"})
    clock.advance(1.0)
    queue.enqueue("x5", {"account_id": "acct-free"})
    clock.advance(1.0)
    queue.enqueue("x6", {"account_id": "acct-free"})

    assert len(abuse_alerts) == 2
    assert abuse_alerts[-1][0] == "account_free"


def test_tenant_abuse_detection_uses_ip_known_proxy_class() -> None:
    clock = _FakeClock()
    abuse_alerts: list[tuple[str, float]] = []

    queue = NlpIntakeFairQueue[str](
        fairness_key="ip_bucket",
        per_tenant_inflight_max=8,
        max_tracked_keys=100,
        tenant_abuse_qps_threshold=1.0,
        tenant_abuse_window_s=2,
        on_tenant_abuse_detected=lambda key_class, qps: abuse_alerts.append((key_class, qps)),
        clock=clock,
    )

    queue.enqueue("p0", {"ip_bucket": "203.0.113.0/24", "ip_known_proxy": True})
    clock.advance(1.0)
    queue.enqueue("p1", {"ip_bucket": "203.0.113.0/24", "ip_known_proxy": True})
    clock.advance(1.0)
    queue.enqueue("p2", {"ip_bucket": "203.0.113.0/24", "ip_known_proxy": True})

    assert abuse_alerts == [("ip_known_proxy", 1.5)]
