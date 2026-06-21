"""Phase 19 §19.6 — T3 resource governance & scrape-lane isolation.

Manages T3 pipeline resource constraints:
- Separate scrape lane (workers, rate limits, budgets)
- Per-league compute caps
- Automatic shelving on resource exhaustion
- Redis key namespacing
- Budget exhaustion metrics
"""

from dataclasses import dataclass
from typing import Optional, Dict
import time


@dataclass
class T3BudgetState:
    """Per-league daily scrape budget tracking."""
    league_id: str
    budget_seconds_per_day: float
    used_seconds_today: float = 0.0
    last_reset_utc_timestamp: float = 0.0
    budget_exhausted_count: int = 0
    shelved_since_utc_timestamp: Optional[float] = None
    
    def is_shelved(self) -> bool:
        """Returns True if league is currently shelved."""
        return self.shelved_since_utc_timestamp is not None
    
    def reset_if_new_day(self, current_utc_timestamp: float) -> None:
        """Reset budget if day boundary crossed."""
        # Simple daily reset (could be more sophisticated with timezone)
        if current_utc_timestamp - self.last_reset_utc_timestamp >= 86400:
            self.used_seconds_today = 0.0
            self.last_reset_utc_timestamp = current_utc_timestamp
    
    def can_allocate(self, seconds_needed: float, current_utc_timestamp: float) -> bool:
        """Check if allocation fits within daily budget."""
        self.reset_if_new_day(current_utc_timestamp)
        if self.is_shelved():
            return False
        remaining = self.budget_seconds_per_day - self.used_seconds_today
        return remaining >= seconds_needed
    
    def allocate(self, seconds: float) -> None:
        """Record scrape time usage."""
        self.used_seconds_today += seconds
        if self.used_seconds_today >= self.budget_seconds_per_day:
            self.budget_exhausted_count += 1


class T3ResourceManager:
    """Manages scrape lane isolation and per-league resource caps."""
    
    def __init__(self, cfg):
        self.cfg = cfg
        self.budgets: Dict[str, T3BudgetState] = {}
        self.shelved_leagues: Dict[str, float] = {}  # league_id -> shelved_timestamp
    
    def get_redis_key_prefix(self, league_id: str) -> str:
        """Return T3-namespaced Redis key prefix for a league."""
        # Per §19.6 bullet 4: T3 leagues use `datasource:t3:<league_id>:` prefix
        return f"datasource:t3:{league_id}:"
    
    def shelve_league(self, league_id: str, reason: str) -> None:
        """Shelve a T3 league (pipeline paused, queue drained)."""
        if league_id not in self.budgets:
            self.budgets[league_id] = T3BudgetState(
                league_id=league_id,
                budget_seconds_per_day=self.cfg.t3_scrape_budget_per_league_s
            )
        now = time.time()
        self.budgets[league_id].shelved_since_utc_timestamp = now
        self.shelved_leagues[league_id] = now
        # In production: emit datasource.alert.v1{kind=t3_shelved, league_id, reason}
    
    def unshelve_league(self, league_id: str) -> None:
        """Unshelve a T3 league (requires operator command)."""
        if league_id in self.budgets:
            self.budgets[league_id].shelved_since_utc_timestamp = None
        if league_id in self.shelved_leagues:
            del self.shelved_leagues[league_id]


class T3LazyLoader:
    """Lazy loading of T3 LeagueConfig/CalibrationProfile to avoid memory bloat."""
    
    def __init__(self, cfg):
        self.cfg = cfg
        self.loaded_configs: Dict[str, object] = {}
        self.pending_loads: Dict[str, float] = {}
    
    def preload_async(self, league_id: str) -> None:
        """Mark league for async preload; actual load deferred to access time."""
        now = time.time()
        if league_id not in self.pending_loads:
            self.pending_loads[league_id] = now
    
    def get_or_load(self, league_id: str, loader_fn) -> object:
        """Lazy-load config if not already in memory."""
        if league_id in self.loaded_configs:
            return self.loaded_configs[league_id]
        # In production: load from disk/Redis via loader_fn()
        config = loader_fn()  
        self.loaded_configs[league_id] = config
        return config
    
    def evict_lru(self, max_leagues: int) -> None:
        """Evict oldest accessed configs if memory exceeds max_leagues."""
        if len(self.loaded_configs) > max_leagues:
            # Simple eviction: drop older entries
            excess = len(self.loaded_configs) - max_leagues
            for key in list(self.loaded_configs.keys())[:excess]:
                del self.loaded_configs[key]
