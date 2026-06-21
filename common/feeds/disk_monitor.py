"""Disk usage monitoring and backpressure for feed writer (Phase 16.2 bullet 7).

Monitors feed volume usage and blocks/warns based on thresholds:
  - >= cfg.emitter_disk_usage_warn_pct (default 80) → sec.alert.v1{kind=feeds_disk_warn}
  - >= cfg.emitter_disk_usage_block_pct (default 95) → blocks writes, proof.flag{kind=feeds_disk_blocked}
  - Never silently drops records

Provides deterministic disk checks with caching to avoid repeated syscalls.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import time


@dataclass
class DiskUsage:
    """Snapshot of disk usage statistics."""
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_pct: float
    captured_at_sec: float = field(default_factory=time.time)
    
    def is_stale(self, cache_ttl_sec: float = 1.0) -> bool:
        """Check if snapshot is older than cache TTL."""
        return time.time() - self.captured_at_sec > cache_ttl_sec


class DiskMonitor:
    """Monitor disk usage and enforce backpressure."""
    
    def __init__(
        self,
        feed_root: Path,
        warn_pct: float = 80.0,
        block_pct: float = 95.0,
        cache_ttl_sec: float = 1.0,
    ):
        """Initialize disk monitor.
        
        Args:
            feed_root: Root path for feed files
            warn_pct: Warning threshold (0-100)
            block_pct: Block threshold (0-100)
            cache_ttl_sec: How long to cache disk checks
        """
        self.feed_root = Path(feed_root)
        self.warn_pct = warn_pct
        self.block_pct = block_pct
        self.cache_ttl_sec = cache_ttl_sec
        
        self._cache: Optional[DiskUsage] = None
        self.total_warns = 0
        self.total_blocks = 0
    
    def get_usage(self, force_refresh: bool = False) -> DiskUsage:
        """Get current disk usage.
        
        Args:
            force_refresh: Ignore cache and fetch fresh stats
            
        Returns:
            DiskUsage snapshot
        """
        # Return cached value if valid
        if not force_refresh and self._cache and not self._cache.is_stale(self.cache_ttl_sec):
            return self._cache
        
        # Query statfs
        stat = os.statvfs(str(self.feed_root))
        total_bytes = stat.f_blocks * stat.f_frsize
        free_bytes = stat.f_bavail * stat.f_frsize  # Available to non-root
        used_bytes = total_bytes - free_bytes
        usage_pct = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0.0
        
        usage = DiskUsage(
            total_bytes=total_bytes,
            used_bytes=used_bytes,
            free_bytes=free_bytes,
            usage_pct=usage_pct,
        )
        
        self._cache = usage
        return usage
    
    def check_disk_health(self) -> dict:
        """Check disk health and return status.
        
        Returns:
            Dict with keys:
              - usage_pct: Current usage percentage
              - is_warning: True if >= warn_pct
              - is_blocked: True if >= block_pct
              - status: "ok" | "warning" | "blocked"
        """
        usage = self.get_usage()
        
        is_blocked = usage.usage_pct >= self.block_pct
        is_warning = usage.usage_pct >= self.warn_pct
        
        if is_blocked:
            self.total_blocks += 1
            status = "blocked"
        elif is_warning:
            self.total_warns += 1
            status = "warning"
        else:
            status = "ok"
        
        return {
            "usage_pct": usage.usage_pct,
            "is_warning": is_warning,
            "is_blocked": is_blocked,
            "status": status,
        }
    
    def can_write(self) -> bool:
        """Check if disk usage permits writes.
        
        Returns:
            True if usage < block_pct, False if blocked
        """
        health = self.check_disk_health()
        return not health["is_blocked"]
    
    def should_alert(self) -> Optional[str]:
        """Check if an alert should be emitted.
        
        Returns:
            Alert kind ("feeds_disk_warn" | "feeds_disk_blocked") or None
        """
        health = self.check_disk_health()
        
        if health["is_blocked"]:
            return "feeds_disk_blocked"
        elif health["is_warning"]:
            return "feeds_disk_warn"
        
        return None
    
    def get_stats(self) -> dict:
        """Get monitoring statistics."""
        usage = self.get_usage()
        
        return {
            "total_bytes": usage.total_bytes,
            "used_bytes": usage.used_bytes,
            "free_bytes": usage.free_bytes,
            "usage_pct": usage.usage_pct,
            "warn_threshold_pct": self.warn_pct,
            "block_threshold_pct": self.block_pct,
            "total_warnings": self.total_warns,
            "total_blocks": self.total_blocks,
        }
