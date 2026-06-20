"""Phase 21.4 — Environment plane differs (weather & pitch).

Differs compare old vs. new weather/pitch records and emit DiffEvent objects.
Idempotent: identical re-fetches produce no diff.

Per ROADMAP §21.4:
  - Weather key: (venue_id, weather_source)
  - Dedup window: 1h (cfg.enrichment_weather_dedup_window_s = 3600s)
  - Forecast vs actual: kept separate; actual always overrides post-KO
  - Pitch key: (venue_id, inspection_at)

DiffEvent contract:
  - source: str ("weather_prov")
  - entity_type: str ("weather_forecast" | "weather_actual" | "pitch_condition")
  - key_tuple: tuple (diff key)
  - old_record: dict | None
  - new_record: dict | None
  - timestamp: str (ISO-8601 UTC)
  - change_type: str ("created" | "updated" | "deleted")
"""

from ai.scraper.differs.weather_prov.differ import (
    WeatherDiffer,
    DiffEvent,
)

__all__ = [
    "WeatherDiffer",
    "DiffEvent",
]
