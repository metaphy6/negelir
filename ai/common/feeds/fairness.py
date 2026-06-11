"""Per-source fairness floor token bucket for FeedWriter (Phase 16.2, ledger #8).

Enforces a minimum write capacity floor per source while allowing burst
accumulation up to a configured factor. When multiple sources compete for
write capacity, slower sources are protected by a fairness floor.

Properties (binding per Phase 16.2):
  - Token bucket per source with fairness floor and burst capacity
  - Fairness floor: floor_pct of total write capacity reserved per source
  - Burst capacity: burst_factor * floor_pct per source
  - Window: measurement window over which tokens are consumed
  - Throttling: when global capacity is exhausted, slower sources can proceed
    up to their floor, while faster sources are throttled
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TokenBucket:
    """Token bucket for a single source with fairness floor and burst."""
    source_id: str
    floor_capacity: float  # tokens per window at floor_pct
    burst_capacity: float  # max tokens allowed per window
    window_duration_s: float
    tokens: float = field(default=0.0)
    last_refill_at: float = field(default_factory=time.time)
    total_violations: int = field(default=0)  # count of fairness floor violations

    def refill(self, current_time: Optional[float] = None) -> float:
        """Refill tokens based on elapsed time. Returns current token count."""
        if current_time is None:
            current_time = time.time()
        
        elapsed = current_time - self.last_refill_at
        if elapsed <= 0:
            return self.tokens
        
        # Refill at burst_capacity rate per window
        refill_rate = self.burst_capacity / self.window_duration_s
        new_tokens = min(self.burst_capacity, self.tokens + (elapsed * refill_rate))
        
        self.tokens = new_tokens
        self.last_refill_at = current_time
        return self.tokens

    def try_consume(self, amount: float) -> bool:
        """Try to consume tokens. Returns True if successful."""
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False

    def can_consume_at_floor(self, amount: float) -> bool:
        """Check if amount is within floor capacity (fairness protection)."""
        return amount <= self.floor_capacity

    def record_violation(self) -> None:
        """Record that this source's fairness floor was violated (throttled)."""
        self.total_violations += 1


class PerSourceFairnessFloor:
    """Enforces per-source fairness floor for bursty write patterns (ledger #8).
    
    Coordination model:
      - Each source maintains a token bucket with a fairness floor
      - Floor: minimum % of capacity reserved per source
      - Burst: sources can accumulate up to (burst_factor * floor) tokens
      - When capacity is exhausted, slower sources are allowed to proceed
        up to their floor while faster sources are throttled
    
    Usage:
        ff = PerSourceFairnessFloor(floor_pct=5.0, burst_factor=4.0, window_s=1.0)
        can_write = ff.allow_write(source_id="mackolik", num_records=100)
        if can_write:
            writer.write(records)
        else:
            time.sleep(0.01)  # backoff
    """

    def __init__(
        self,
        floor_pct: float = 5.0,
        burst_factor: float = 4.0,
        window_s: float = 1.0,
        num_sources: int = 12,  # approximate number of sources expected
    ):
        """Initialize per-source fairness floor.
        
        Args:
            floor_pct: Minimum % of capacity reserved per source (default 5%)
            burst_factor: Multiplicative burst cap (default 4x floor)
            window_s: Measurement window in seconds (default 1s)
            num_sources: Expected number of sources (for capacity calculation)
        """
        self.floor_pct = floor_pct / 100.0  # convert to decimal
        self.burst_factor = burst_factor
        self.window_s = window_s
        self.num_sources = num_sources
        
        # Total normalized capacity is 1.0 per window
        self.total_capacity = 1.0
        
        # Per-source floor and burst
        self.floor_capacity = self.total_capacity * self.floor_pct  # e.g., 0.05 for 5%
        self.burst_capacity = self.floor_capacity * burst_factor  # e.g., 0.20 for 5% floor * 4x
        
        self.buckets: Dict[str, TokenBucket] = {}
        self.violations_window: Dict[str, int] = {}  # for monitoring

    def allow_write(self, source_id: str, num_records: int = 1) -> bool:
        """Check if a source can write num_records under fairness floor rules.
        
        Args:
            source_id: Source identifier (e.g., "mackolik")
            num_records: Number of records about to be written
            
        Returns:
            True if write is allowed, False if source should be throttled.
        """
        # Normalize write size to capacity fraction (simple heuristic)
        # In real use, this would be bytes-based or records-per-second based
        capacity_consumed = (num_records / 1000.0) * self.burst_capacity  # rough normalization
        capacity_consumed = min(capacity_consumed, self.burst_capacity)
        
        # Get or create bucket for this source
        if source_id not in self.buckets:
            self.buckets[source_id] = TokenBucket(
                source_id=source_id,
                floor_capacity=self.floor_capacity,
                burst_capacity=self.burst_capacity,
                window_duration_s=self.window_s,
            )
        
        bucket = self.buckets[source_id]
        current_time = time.time()
        bucket.refill(current_time)
        
        # Try to consume at full capacity first
        if bucket.try_consume(capacity_consumed):
            return True
        
        # If not enough tokens, check if we can consume at floor
        # (this allows slower sources to proceed even if bursting sources haven't refilled)
        if bucket.can_consume_at_floor(capacity_consumed):
            bucket.tokens -= capacity_consumed
            bucket.record_violation()  # Track that we throttled a burst
            return True
        
        return False

    def get_bucket_state(self, source_id: str) -> Optional[Dict]:
        """Get current token bucket state for diagnostics."""
        if source_id not in self.buckets:
            return None
        
        bucket = self.buckets[source_id]
        bucket.refill()
        
        return {
            "source_id": source_id,
            "tokens": bucket.tokens,
            "floor_capacity": bucket.floor_capacity,
            "burst_capacity": bucket.burst_capacity,
            "violations_count": bucket.total_violations,
        }

    def get_all_bucket_states(self) -> Dict[str, Dict]:
        """Get state for all sources (for monitoring)."""
        states = {}
        for source_id in self.buckets:
            state = self.get_bucket_state(source_id)
            if state:
                states[source_id] = state
        return states

    def reset_buckets(self) -> None:
        """Reset all buckets (typically for testing)."""
        self.buckets.clear()
        self.violations_window.clear()
