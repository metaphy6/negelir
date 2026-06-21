"""Writer pool coordinator enforcing per-source fairness floor (Phase 16.2, ledger #8).

A WriterPool manages multiple FeedWriter instances across different sources
and enforces a fairness floor to prevent bursty sources from monopolizing
write capacity. Quieter sources are protected by a minimum % of write capacity.

Properties (binding per Phase 16.2):
  - Per-source token bucket with fairness floor and burst capacity
  - Fairness floor: floor_pct (default 5%) of write capacity reserved per source
  - Burst capacity: burst_factor * floor_pct per source
  - Throttling: when global capacity is exhausted, slower sources can still proceed
    up to their floor while faster sources are throttled
  - Monitoring: tracks fairness violations per source and window
"""

import logging
import time
from typing import Dict, Optional, Any

from common.feeds.fairness import PerSourceFairnessFloor
from common.feeds.writer import FeedWriter

logger = logging.getLogger(__name__)


class WriterPool:
    """Coordinates multiple FeedWriter instances with per-source fairness enforcement.
    
    Usage:
        pool = WriterPool(
            plane="score",
            feeds_dir="/data/feeds",
            redis_client=redis_conn,
            floor_pct=5.0,
            burst_factor=4.0,
        )
        
        writer = pool.get_writer(source="mackolik")  # May block waiting for fairness
        writer.enqueue(record)
        pool.close_writer(source="mackolik")
    """

    def __init__(
        self,
        plane: str,
        feeds_dir: str = "/data/feeds",
        redis_client: Optional[Any] = None,
        floor_pct: float = 5.0,
        burst_factor: float = 4.0,
        burst_window_s: float = 1.0,
        max_sources: int = 20,
    ):
        """Initialize WriterPool with fairness floor enforcement.
        
        Args:
            plane: Feed plane (e.g., "score", "schedule")
            feeds_dir: Root directory for feed files
            redis_client: Redis connection for lease coordination
            floor_pct: Minimum % of capacity per source (default 5%)
            burst_factor: Burst multiplier (default 4x floor)
            burst_window_s: Window for fairness measurement (default 1s)
            max_sources: Expected maximum number of sources
        """
        self.plane = plane
        self.feeds_dir = feeds_dir
        self.redis_client = redis_client
        self.floor_pct = floor_pct
        self.burst_factor = burst_factor
        self.burst_window_s = burst_window_s
        self.max_sources = max_sources
        
        self.writers: Dict[str, FeedWriter] = {}
        self.fairness = PerSourceFairnessFloor(
            floor_pct=floor_pct,
            burst_factor=burst_factor,
            window_s=burst_window_s,
            num_sources=max_sources,
        )
        
        self.fairness_violations_total: Dict[str, int] = {}
        self.fairness_throttles_total: Dict[str, int] = {}

    def get_writer(self, source: str) -> FeedWriter:
        """Get or create a writer for the given source.
        
        Note: This does NOT enforce fairness. Fairness is enforced in
        enqueue_with_fairness(). This method is for low-level access.
        
        Args:
            source: Source identifier (e.g., "mackolik")
            
        Returns:
            FeedWriter for the source
            
        Raises:
            RuntimeError: If lease cannot be acquired
        """
        if source not in self.writers:
            writer = FeedWriter(
                plane=self.plane,
                source=source,
                feeds_dir=self.feeds_dir,
                redis_client=self.redis_client,
            )
            writer.open()
            self.writers[source] = writer
            logger.info(f"Created writer for {self.plane}/{source}")
        
        return self.writers[source]

    def enqueue_with_fairness(
        self,
        source: str,
        record: dict,
        max_wait_s: float = 0.1,
        retry_interval_ms: int = 10,
    ) -> bool:
        """Enqueue a record respecting per-source fairness floor.
        
        Args:
            source: Source identifier
            record: Record dictionary to append
            max_wait_s: Max time to wait for fairness to allow write (default 100ms)
            retry_interval_ms: Sleep between fairness checks (default 10ms)
            
        Returns:
            True if enqueued, False if fairness floor blocked after timeout
        """
        writer = self.get_writer(source)
        
        start_time = time.time()
        while True:
            # Check fairness floor (1 record normalized to capacity)
            if self.fairness.allow_write(source, num_records=1):
                writer.enqueue(record)
                if source not in self.fairness_violations_total:
                    self.fairness_violations_total[source] = 0
                return True
            
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > max_wait_s:
                if source not in self.fairness_throttles_total:
                    self.fairness_throttles_total[source] = 0
                self.fairness_throttles_total[source] += 1
                logger.warning(
                    f"Fairness floor throttled {source} after {elapsed:.3f}s; "
                    f"record dropped (fairness violations: "
                    f"{self.fairness_violations_total.get(source, 0)})"
                )
                return False
            
            # Backoff and retry
            time.sleep(retry_interval_ms / 1000.0)

    def close_writer(self, source: str) -> None:
        """Close and release a writer.
        
        Args:
            source: Source identifier
        """
        if source in self.writers:
            writer = self.writers[source]
            writer.close()
            del self.writers[source]
            logger.info(f"Closed writer for {self.plane}/{source}")

    def close_all(self) -> None:
        """Close all open writers."""
        sources = list(self.writers.keys())
        for source in sources:
            self.close_writer(source)
        logger.info(f"Closed all writers for {self.plane}")

    def get_fairness_stats(self) -> Dict[str, Any]:
        """Get fairness enforcement statistics.
        
        Returns:
            Dictionary with per-source and global fairness metrics
        """
        return {
            "plane": self.plane,
            "floor_pct": self.floor_pct,
            "burst_factor": self.burst_factor,
            "burst_window_s": self.burst_window_s,
            "active_sources": len(self.writers),
            "fairness_violations_total": self.fairness_violations_total.copy(),
            "fairness_throttles_total": self.fairness_throttles_total.copy(),
            "bucket_states": self.fairness.get_all_bucket_states(),
        }
