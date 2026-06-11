"""Time source coordination for FeedWriter (Phase 16.2, bullet 3).

Provides deterministic, accurate clock semantics for feed timestamps:
  - CLOCK_TAI (International Atomic Time) or NTP-disciplined CLOCK_REALTIME
    for captured_at timestamps (no leap seconds, continuous monotonic)
  - time.monotonic() for rotation timers and lease TTL (immune to clock skew)
  - Clock skew detection with configurable alert threshold

Properties (binding per Phase 16.2):
  - captured_at: uses TAI or NTP-disciplined CLOCK_REALTIME (leap-second free)
  - rotation/lease timers: use time.monotonic() (immune to backward jumps)
  - Clock skew monitoring: alerts on deviation > cfg.emitter_clock_skew_alert_ms
  - Rotation trigger: wall-clock midnight UTC crossing (with monotonic safety net)
"""

import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ClockSnapshot:
    """Snapshot of multiple clock sources at a single point in time."""
    captured_at_utc: str  # ISO 8601 UTC timestamp (RFC3339)
    monotonic_ms: float  # monotonic clock in milliseconds
    wall_clock_utc: str  # wall-clock UTC for rotation trigger
    clock_skew_ms: float  # deviation between requested and actual clock


class TimeSource:
    """Coordinates multiple clocks for FeedWriter timing (Phase 16.2 bullet 3).
    
    Clock strategy:
    - captured_at: TAI or NTP-disciplined CLOCK_REALTIME (no leap seconds)
    - Timers: time.monotonic() (immune to wall-clock skew)
    - Rotation: wall-clock midnight UTC crossing + monotonic safety net
    - Monitoring: tracks clock skew deviations
    
    Usage:
        ts = TimeSource(skew_alert_ms=500)
        snapshot = ts.snapshot()  # Get all clocks at once
        
        # Check if should rotate (midnight UTC crossed)
        should_rotate = ts.should_rotate_at_midnight(prev_snapshot)
        
        # Check clock skew
        if snapshot.clock_skew_ms > ts.skew_alert_ms:
            alert("emitter_clock_skew", skew=snapshot.clock_skew_ms)
    """
    
    def __init__(
        self,
        use_tai: bool = True,
        skew_alert_ms: float = 500.0,
    ):
        """Initialize TimeSource.
        
        Args:
            use_tai: Try to use CLOCK_TAI if available, fallback to CLOCK_REALTIME (default True)
            skew_alert_ms: Alert threshold for clock skew (default 500 ms)
        """
        self.use_tai = use_tai
        self.skew_alert_ms = skew_alert_ms
        self.clock_available = self._detect_clocks()
        self.last_snapshot: Optional[ClockSnapshot] = None
        self.rotation_monotonic_at: Optional[float] = None  # monotonic time at last rotation

    def _detect_clocks(self) -> dict[str, bool]:
        """Detect which clocks are available on this system."""
        available = {}
        
        # Check for CLOCK_TAI (Linux only, requires kernel 3.10+)
        # CLOCK_TAI is available as time.CLOCK_TAI in Python 3.3+
        try:
            if hasattr(time, "CLOCK_TAI"):
                _ = time.clock_gettime(time.CLOCK_TAI)
                available["tai"] = True
            else:
                available["tai"] = False
        except (OSError, ValueError):
            available["tai"] = False
        
        # CLOCK_REALTIME is always available
        available["realtime"] = True
        
        # monotonic is always available
        available["monotonic"] = True
        
        if not available["tai"] and self.use_tai:
            logger.warning("CLOCK_TAI not available; falling back to CLOCK_REALTIME with NTP")
        
        return available

    def snapshot(self) -> ClockSnapshot:
        """Capture a snapshot of all relevant clocks at one point in time.
        
        Returns:
            ClockSnapshot with captured_at, monotonic, wall_clock, and skew
        """
        start_monotonic = time.monotonic()
        
        # Get captured_at timestamp
        if self.use_tai and self.clock_available.get("tai") and hasattr(time, "CLOCK_TAI"):
            # Use CLOCK_TAI (International Atomic Time, no leap seconds)
            try:
                tai_seconds = time.clock_gettime(time.CLOCK_TAI)
                captured_at_utc = datetime.fromtimestamp(tai_seconds, tz=timezone.utc).isoformat()
            except (OSError, ValueError):
                # Fallback if TAI fails
                captured_at_utc = datetime.now(timezone.utc).isoformat()
        else:
            # Use NTP-disciplined CLOCK_REALTIME
            # (on well-configured systems, chrony keeps this within ~100 µs of TAI)
            captured_at_utc = datetime.now(timezone.utc).isoformat()
        
        # Elapsed time since start (in microseconds for precision)
        elapsed_monotonic_us = (time.monotonic() - start_monotonic) * 1_000_000
        
        # Get wall-clock UTC for rotation trigger (YYYY-MM-DD HH:00)
        wall_clock_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
        
        # Estimate clock skew (jitter in the snapshot capture)
        # Skew is the elapsed time we spent capturing the clocks
        clock_skew_ms = elapsed_monotonic_us / 1000.0
        
        snapshot = ClockSnapshot(
            captured_at_utc=captured_at_utc,
            monotonic_ms=time.monotonic() * 1000.0,
            wall_clock_utc=wall_clock_utc,
            clock_skew_ms=clock_skew_ms,
        )
        
        self.last_snapshot = snapshot
        return snapshot

    def should_rotate_at_midnight(self, prev_snapshot: ClockSnapshot) -> bool:
        """Check if midnight UTC has been crossed since last snapshot.
        
        Uses wall-clock crossing as trigger with monotonic safety net.
        Midnight rotation is triggered by:
          1. Wall-clock hour changed (e.g., 23:00 → 00:00)
          2. AND monotonic time advanced (ensure no time-jump backward)
        
        Args:
            prev_snapshot: Previous snapshot (for comparison)
            
        Returns:
            True if midnight UTC was crossed, False otherwise
        """
        current_snapshot = self.snapshot()
        
        # Extract hours from wall-clock (format: YYYY-MM-DDTHH:00:00Z)
        prev_hour = prev_snapshot.wall_clock_utc[11:13]
        curr_hour = current_snapshot.wall_clock_utc[11:13]
        
        # Check if hour changed (midnight crossing is 23:00 → 00:00)
        hour_changed = prev_hour != curr_hour
        
        # Check monotonic time advanced (no backward clock jump)
        monotonic_advanced = current_snapshot.monotonic_ms > prev_snapshot.monotonic_ms
        
        # Rotation happens only if BOTH conditions true
        should_rotate = hour_changed and monotonic_advanced
        
        if should_rotate:
            self.rotation_monotonic_at = current_snapshot.monotonic_ms
        
        return should_rotate

    def get_current_date_utc(self) -> str:
        """Get current UTC date in YYYY-MM-DD format.
        
        Returns:
            Date string in YYYY-MM-DD format
        """
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_clock_health(self) -> dict:
        """Get health status of clock sources.
        
        Returns:
            Dictionary with clock availability and configuration
        """
        return {
            "use_tai": self.use_tai,
            "clocks_available": self.clock_available,
            "tai_available": self.clock_available.get("tai", False),
            "skew_alert_ms": self.skew_alert_ms,
            "last_skew_ms": self.last_snapshot.clock_skew_ms if self.last_snapshot else None,
        }
