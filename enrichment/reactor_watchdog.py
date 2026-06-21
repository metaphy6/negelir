"""Phase 21 §21.27 — Derived-View Reactor Watchdog.

Monitors the heartbeat keys of derived-view reactors and alerts when they stall.
"""

import time
from typing import Optional

from ai.common.config import Config
from ai.common.logger import get_logger

log = get_logger("reactor_watchdog")

# Derived-view reactor names (from §21.5)
DERIVED_VIEW_NAMES = {
    "market_movement",
    "fixture_congestion",
    "card_context",
    "narrative_pressure",
}


class ReactorWatchdog:
    """Monitors derived-view reactor heartbeats in Redis."""
    
    def __init__(self, cfg: Config, bus=None, telemetry=None):
        self.cfg = cfg
        self.bus = bus
        self.telemetry = telemetry
        self._stall_counters: dict[str, int] = {view: 0 for view in DERIVED_VIEW_NAMES}
    
    def check_heartbeats(self) -> None:
        """Check all reactor heartbeats; emit alerts if stalled."""
        for view in DERIVED_VIEW_NAMES:
            self._check_view_heartbeat(view)
    
    def _check_view_heartbeat(self, view: str) -> None:
        """Check one reactor's heartbeat; update stall counter and emit alert if needed."""
        key = f"enrich:reactor:{view}:last_run_at"
        
        try:
            if hasattr(self.cfg, 'redis_client') and self.cfg.redis_client:
                last_run_at_raw = self.cfg.redis_client.get(key)
                if last_run_at_raw is None:
                    last_run_at = None
                else:
                    last_run_at = float(last_run_at_raw)
            else:
                last_run_at = None
        except Exception as e:
            log.warning(f"Failed to read heartbeat key {key}: {e}")
            last_run_at = None
        
        now = time.time()
        
        # If key is missing (expired or never written), increment stall counter
        if last_run_at is None:
            self._stall_counters[view] += 1
            
            # Emit warning immediately
            if self.telemetry:
                self.telemetry.emit_predictor_warning(
                    kind="enrichment_reactor_stalled",
                    view=view,
                    last_run_at=None,
                )
            
            # After threshold consecutive misses, emit escalation event
            escalation_count = getattr(
                self.cfg, 
                'enrichment_reactor_stall_escalation_count', 
                3
            )
            if self._stall_counters[view] >= escalation_count:
                if self.bus:
                    self.bus.publish(
                        "maint.event.v1",
                        {
                            "kind": "reactor_stall_alert",
                            "component": "enrichment_reactor",
                            "view": view,
                            "stall_count": self._stall_counters[view],
                        },
                    )
        else:
            # Key exists; reset stall counter
            self._stall_counters[view] = 0
            
            # Record reactor last-run time as a Prometheus gauge
            if self.telemetry:
                seconds_since_last_run = now - last_run_at
                self.telemetry.record_reactor_last_run_seconds(view, seconds_since_last_run)
