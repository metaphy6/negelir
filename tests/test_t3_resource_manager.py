"""Tests for Phase 19 §19.6 — T3 resource governance."""

import pytest
import time
from dataclasses import dataclass
from enrichment.t3_resource_manager import T3BudgetState, T3ResourceManager, T3LazyLoader


class MockConfig:
    """Mock config for testing."""
    t3_scrape_budget_per_league_s = 10.0


class TestT3BudgetState:
    """§19.6 bullet 3: Per-league budget tracking."""
    
    def test_budget_initially_available(self):
        """Fresh budget state has full allocation available."""
        state = T3BudgetState(
            league_id="test_league",
            budget_seconds_per_day=10.0
        )
        now = time.time()
        assert state.can_allocate(5.0, now)
        assert state.can_allocate(10.0, now)
        assert not state.can_allocate(10.1, now)
    
    def test_budget_exhaustion_prevents_allocation(self):
        """Budget exhaustion blocks further allocation."""
        state = T3BudgetState(
            league_id="test_league",
            budget_seconds_per_day=10.0
        )
        now = time.time()
        assert state.can_allocate(10.0, now)
        state.allocate(10.0)
        assert not state.can_allocate(0.1, now)
    
    def test_budget_resets_after_24_hours(self):
        """Budget resets when day boundary crosses."""
        state = T3BudgetState(
            league_id="test_league",
            budget_seconds_per_day=10.0,
            last_reset_utc_timestamp=0.0,
            used_seconds_today=10.0  # Consumed all
        )
        now = 86400 + 1  # 24h + 1 second later
        # can_allocate() automatically resets on boundary
        assert state.can_allocate(10.0, now)  # Full budget available after reset


class TestT3ResourceManager:
    """§19.6 resource manager functionality."""
    
    def test_redis_key_prefix_namespaced(self):
        """§19.6 bullet 4: T3 Redis keys use proper prefix."""
        cfg = MockConfig()
        manager = T3ResourceManager(cfg)
        prefix = manager.get_redis_key_prefix("tr_super_lig")
        assert prefix == "datasource:t3:tr_super_lig:"
    
    def test_league_shelving(self):
        """§19.6 bullet 3: Shelving blocks allocation."""
        cfg = MockConfig()
        manager = T3ResourceManager(cfg)
        
        # Initially can allocate
        assert "my_league" not in manager.budgets
        
        # Shelve the league
        manager.shelve_league("my_league", "source unavailable")
        assert "my_league" in manager.shelved_leagues
        
        # Check shelving prevents allocation
        league_budget = manager.budgets["my_league"]
        assert league_budget.is_shelved()
        assert not league_budget.can_allocate(1.0, time.time())
    
    def test_league_unshelving(self):
        """§19.6 bullet 3: Unshelving restores allocation."""
        cfg = MockConfig()
        manager = T3ResourceManager(cfg)
        manager.shelve_league("my_league", "test")
        
        # Shelved state blocks
        assert manager.budgets["my_league"].is_shelved()
        
        # Unshelve
        manager.unshelve_league("my_league")
        assert not manager.budgets["my_league"].is_shelved()
        assert manager.budgets["my_league"].can_allocate(1.0, time.time())


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


class TestT3LazyLoader:
    """§19.6 bullet 5: Lazy loading to avoid memory bloat."""
    
    def test_lazy_load_defers_to_first_access(self):
        """Configs are loaded only on first access."""
        cfg = MockConfig()
        loader = T3LazyLoader(cfg)
        
        # Mark for preload but don't load yet
        loader.preload_async("league_1")
        assert "league_1" not in loader.loaded_configs
        
        # Access triggers load
        loaded = loader.get_or_load("league_1", lambda: {"name": "league_1"})
        assert loaded["name"] == "league_1"
        assert "league_1" in loader.loaded_configs
    
    def test_lru_eviction_on_max_leagues(self):
        """Excess configs are evicted when memory limit exceeded."""
        cfg = MockConfig()
        loader = T3LazyLoader(cfg)
        
        # Load 5 configs
        for i in range(5):
            loader.get_or_load(f"league_{i}", lambda i=i: {"id": i})
        
        # Evict when exceeding max of 3
        loader.evict_lru(3)
        assert len(loader.loaded_configs) == 3
