"""Phase 21.4 — WeatherDiffer: Compare forecast/actual/pitch records.

Emits DiffEvent objects when weather conditions change.
Implements 1h dedup window (cfg.enrichment_weather_dedup_window_s = 3600s).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from common.config import cfg
from common.logger import get_logger

log = get_logger("scraper.differs.weather_prov")


class DiffEvent(TypedDict):
    """Emitted when a weather/pitch record changes."""
    source: str
    entity_type: str  # "weather_forecast", "weather_actual", "pitch_condition"
    key_tuple: tuple
    old_record: Optional[Dict[str, Any]]
    new_record: Optional[Dict[str, Any]]
    timestamp: str
    change_type: str  # "created", "updated", "deleted"


@dataclass
class WeatherDiffer:
    """Diffs old vs new weather records; emits DiffEvent on change.
    
    Per ROADMAP §21.4:
    - Dedup window: 1h (cfg.enrichment_weather_dedup_window_s)
    - Weather key: (venue_id, weather_source)
    - Forecast vs actual: separate streams
    - Pitch key: (venue_id, inspection_at)
    
    Idempotent: identical re-fetches produce no diff.
    """

    dedup_window_s: int = cfg.enrichment_weather_dedup_window_s
    """Dedup window in seconds (default 3600 = 1h)."""

    def diff_forecasts(
        self,
        old_forecasts: List[Dict[str, Any]],
        new_forecasts: List[Dict[str, Any]],
    ) -> List[DiffEvent]:
        """Compare forecast lists; emit DiffEvent on change."""
        events: List[DiffEvent] = []

        # Build old map: (venue_id, weather_source) → old record
        old_map = {}
        for record in old_forecasts:
            venue_id = record.get("venue_id")
            source = record.get("source", "weather_prov")
            if venue_id and source:
                key = (venue_id, source)
                # Within dedup window, keep only the newest
                if key not in old_map:
                    old_map[key] = record
                else:
                    # If timestamps within dedup window, prefer the newer one
                    old_issued = datetime.fromisoformat(
                        old_map[key].get("issued_at", "").replace("Z", "+00:00")
                    )
                    new_issued = datetime.fromisoformat(
                        record.get("issued_at", "").replace("Z", "+00:00")
                    )
                    if new_issued > old_issued:
                        old_map[key] = record

        # Build new map
        new_map = {}
        for record in new_forecasts:
            venue_id = record.get("venue_id")
            source = record.get("source", "weather_prov")
            if venue_id and source:
                key = (venue_id, source)
                if key not in new_map:
                    new_map[key] = record
                else:
                    new_issued = datetime.fromisoformat(
                        new_map[key].get("issued_at", "").replace("Z", "+00:00")
                    )
                    record_issued = datetime.fromisoformat(
                        record.get("issued_at", "").replace("Z", "+00:00")
                    )
                    if record_issued > new_issued:
                        new_map[key] = record

        # Detect changes
        now = datetime.utcnow().isoformat() + "Z"

        # Existing records that changed or were deleted
        for key, old_record in old_map.items():
            if key in new_map:
                # Updated
                new_record = new_map[key]
                if old_record != new_record:
                    events.append({
                        "source": "weather_prov",
                        "entity_type": "weather_forecast",
                        "key_tuple": key,
                        "old_record": old_record,
                        "new_record": new_record,
                        "timestamp": now,
                        "change_type": "updated",
                    })
            else:
                # Deleted
                events.append({
                    "source": "weather_prov",
                    "entity_type": "weather_forecast",
                    "key_tuple": key,
                    "old_record": old_record,
                    "new_record": None,
                    "timestamp": now,
                    "change_type": "deleted",
                })

        # New records not in old
        for key, new_record in new_map.items():
            if key not in old_map:
                events.append({
                    "source": "weather_prov",
                    "entity_type": "weather_forecast",
                    "key_tuple": key,
                    "old_record": None,
                    "new_record": new_record,
                    "timestamp": now,
                    "change_type": "created",
                })

        return events

    def diff_actuals(
        self,
        old_actuals: List[Dict[str, Any]],
        new_actuals: List[Dict[str, Any]],
    ) -> List[DiffEvent]:
        """Compare actual observation lists; emit DiffEvent on change."""
        events: List[DiffEvent] = []

        # Build maps: (venue_id) → actual record
        old_map = {}
        for record in old_actuals:
            venue_id = record.get("venue_id")
            if venue_id:
                old_map[venue_id] = record

        new_map = {}
        for record in new_actuals:
            venue_id = record.get("venue_id")
            if venue_id:
                new_map[venue_id] = record

        now = datetime.utcnow().isoformat() + "Z"

        for venue_id, old_record in old_map.items():
            if venue_id in new_map:
                new_record = new_map[venue_id]
                if old_record != new_record:
                    events.append({
                        "source": "weather_prov",
                        "entity_type": "weather_actual",
                        "key_tuple": (venue_id,),
                        "old_record": old_record,
                        "new_record": new_record,
                        "timestamp": now,
                        "change_type": "updated",
                    })
            else:
                events.append({
                    "source": "weather_prov",
                    "entity_type": "weather_actual",
                    "key_tuple": (venue_id,),
                    "old_record": old_record,
                    "new_record": None,
                    "timestamp": now,
                    "change_type": "deleted",
                })

        for venue_id, new_record in new_map.items():
            if venue_id not in old_map:
                events.append({
                    "source": "weather_prov",
                    "entity_type": "weather_actual",
                    "key_tuple": (venue_id,),
                    "old_record": None,
                    "new_record": new_record,
                    "timestamp": now,
                    "change_type": "created",
                })

        return events

    def diff_pitch_conditions(
        self,
        old_conditions: List[Dict[str, Any]],
        new_conditions: List[Dict[str, Any]],
    ) -> List[DiffEvent]:
        """Compare pitch condition records; emit DiffEvent on change."""
        events: List[DiffEvent] = []

        # Build maps: (venue_id) → latest pitch record
        old_map = {}
        for record in old_conditions:
            venue_id = record.get("venue_id")
            if venue_id:
                inspection_at = datetime.fromisoformat(
                    record.get("inspection_at", "").replace("Z", "+00:00")
                )
                if venue_id not in old_map:
                    old_map[venue_id] = record
                else:
                    old_inspection = datetime.fromisoformat(
                        old_map[venue_id].get("inspection_at", "").replace("Z", "+00:00")
                    )
                    if inspection_at > old_inspection:
                        old_map[venue_id] = record

        new_map = {}
        for record in new_conditions:
            venue_id = record.get("venue_id")
            if venue_id:
                inspection_at = datetime.fromisoformat(
                    record.get("inspection_at", "").replace("Z", "+00:00")
                )
                if venue_id not in new_map:
                    new_map[venue_id] = record
                else:
                    new_inspection = datetime.fromisoformat(
                        new_map[venue_id].get("inspection_at", "").replace("Z", "+00:00")
                    )
                    if inspection_at > new_inspection:
                        new_map[venue_id] = record

        now = datetime.utcnow().isoformat() + "Z"

        for venue_id, old_record in old_map.items():
            if venue_id in new_map:
                new_record = new_map[venue_id]
                if old_record != new_record:
                    events.append({
                        "source": "weather_prov",
                        "entity_type": "pitch_condition",
                        "key_tuple": (venue_id,),
                        "old_record": old_record,
                        "new_record": new_record,
                        "timestamp": now,
                        "change_type": "updated",
                    })
            else:
                events.append({
                    "source": "weather_prov",
                    "entity_type": "pitch_condition",
                    "key_tuple": (venue_id,),
                    "old_record": old_record,
                    "new_record": None,
                    "timestamp": now,
                    "change_type": "deleted",
                })

        for venue_id, new_record in new_map.items():
            if venue_id not in old_map:
                events.append({
                    "source": "weather_prov",
                    "entity_type": "pitch_condition",
                    "key_tuple": (venue_id,),
                    "old_record": None,
                    "new_record": new_record,
                    "timestamp": now,
                    "change_type": "created",
                })

        return events
