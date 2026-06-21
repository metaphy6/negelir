"""Phase 21.4 — Environment plane weather extractor.

Integrates with configurable weather API (e.g., Open-Meteo) to extract:
  - WeatherForecastPayload (hourly, 24-48h horizon)
  - WeatherActualPayload (KO ±15 min, post-match)
  - PitchConditionPayload (per-venue inspection)

Per ENRICHMENT_DATA.md §5, config-driven provider URL with no hardcoded endpoints.
Canonical condition strings validated per §5.1; unmapped provider strings raise ExtractionError.
"""

from scraper.extractors.weather_prov.extractor import (
    ExtractionError,
    WeatherExtractor,
)

__all__ = [
    "WeatherExtractor",
    "ExtractionError",
]
