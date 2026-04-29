"""Pre-Phase-6 audit A1: bounded `InMemoryLedger`.

The default reactor ledger must not grow unbounded. We assert:

  * Newest entries evict the oldest once the cap is hit.
  * Re-marking a known event refreshes its LRU position rather
    than triggering eviction.
  * `len(ledger._seen) <= max_size` always holds.
"""
from __future__ import annotations

import pytest

from swarm.agents.reactor import InMemoryLedger


def test_in_memory_ledger_bounds_growth() -> None:
    ledger = InMemoryLedger(max_size=10)
    for i in range(25):
        ledger.mark_processed("rx", f"evt-{i}")
    assert len(ledger._seen) == 10
    # The first 15 should have been evicted.
    for i in range(0, 15):
        assert not ledger.already_processed("rx", f"evt-{i}")
    for i in range(15, 25):
        assert ledger.already_processed("rx", f"evt-{i}")


def test_in_memory_ledger_refresh_preserves_recent_hit() -> None:
    ledger = InMemoryLedger(max_size=3)
    ledger.mark_processed("rx", "a")
    ledger.mark_processed("rx", "b")
    ledger.mark_processed("rx", "c")
    # Re-touching "a" must move it to the freshest end.
    ledger.mark_processed("rx", "a")
    ledger.mark_processed("rx", "d")
    # "b" was the oldest at insertion of "d" → evicted.
    assert not ledger.already_processed("rx", "b")
    assert ledger.already_processed("rx", "a")
    assert ledger.already_processed("rx", "c")
    assert ledger.already_processed("rx", "d")


def test_in_memory_ledger_rejects_zero_max_size() -> None:
    with pytest.raises(ValueError, match="max_size"):
        InMemoryLedger(max_size=0)


def test_in_memory_ledger_default_uses_config(monkeypatch) -> None:
    """Default constructor must read `cfg.reactor_ledger_max_size`."""
    import swarm.agents.reactor as rx_mod

    monkeypatch.setattr(rx_mod._cfg, "reactor_ledger_max_size", 5)
    ledger = InMemoryLedger()
    assert ledger._max_size == 5
