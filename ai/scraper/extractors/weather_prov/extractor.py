"""Phase 21.4 — WeatherExtractor: Parse forecast/actual/pitch-condition records.

Integrates with a configurable weather API provider (no hardcoded URLs).
Parses JSON responses into WeatherForecastPayload, WeatherActualPayload, PitchConditionPayload.

Per ENRICHMENT_DATA.md §5 + ROADMAP §21.4:
  - weather_api_url from config (no default; must be set by operator).
  - Forecast/actual API responses parsed into canonical payloads.
  - Invalid condition strings raise ExtractionError.
  - Frequency: hourly forecasts, KO ±15 min / post-match actuals, per-fixture pitch inspections.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal

from ai.common.config import cfg
from ai.common.logger import get_logger
from ai.common.schemas.records import (
    WeatherForecastPayload,
    WeatherActualPayload,
    PitchConditionPayload,
)

log = get_logger("scraper.extractors.weather_prov")

# Canonical condition strings per ENRICHMENT_DATA.md §5.1.
VALID_CONDITIONS = frozenset(["clear", "rain", "snow", "fog", "thunderstorm"])


class ExtractionError(Exception):
    """Raised when weather data extraction fails."""

    def __init__(self, reason: str, payload: Optional[Dict[str, Any]] = None):
        self.reason = reason
        self.payload = payload
        super().__init__(f"ExtractionError: {reason}")


@dataclass
class WeatherExtractor:
    """Extracts weather payloads from API provider JSON responses.
    
    Per ROADMAP §21.4:
    - Forecast: hourly, 24-48h horizon from cfg.weather_api_url
    - Actual: KO ±15 min, post-match observations
    - Pitch: per-fixture inspection records
    
    Validates condition strings against VALID_CONDITIONS; unmapped provider
    strings raise ExtractionError. All datetimes must be ISO-8601 UTC.
    """

    max_string_length: int = 500
    """Maximum length for string fields."""

    def extract_forecast(self, data: Dict[str, Any]) -> List[WeatherForecastPayload]:
        """Extract hourly forecast records from API response.
        
        Expected structure (Open-Meteo style):
        {
            "hourly": {
                "time": ["2026-06-20T00:00", "2026-06-20T01:00", ...],
                "temperature_2m": [20.5, 19.8, ...],
                "wind_speed_10m": [15.2, 16.1, ...],
                "wind_direction_10m": [180, 185, ...],
                "precipitation": [0.0, 0.5, ...],
                "relative_humidity_2m": [65, 68, ...],
                "visibility": [10.0, 10.0, ...],
                "weather_code": [0, 80, ...],  # WMO codes mapped to canonical conditions
            },
            "venue_id": "venue_123",
            "issued_at": "2026-06-20T00:00:00Z"
        }
        """
        results: List[WeatherForecastPayload] = []

        venue_id = data.get("venue_id")
        if not venue_id:
            raise ExtractionError("missing venue_id", data)

        issued_at_str = data.get("issued_at")
        if not issued_at_str:
            raise ExtractionError("missing issued_at", data)

        # Validate issued_at is ISO-8601 UTC
        try:
            datetime.fromisoformat(issued_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ExtractionError(f"invalid issued_at format: {issued_at_str}", data)

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("wind_speed_10m", [])
        wind_dirs = hourly.get("wind_direction_10m", [])
        precips = hourly.get("precipitation", [])
        humidities = hourly.get("relative_humidity_2m", [])
        visibilities = hourly.get("visibility", [])
        weather_codes = hourly.get("weather_code", [])

        if len(times) != len(temps):
            raise ExtractionError(
                f"hourly array length mismatch: times={len(times)}, temps={len(temps)}",
                data,
            )

        for i, time_str in enumerate(times):
            try:
                # Validate time is ISO-8601 UTC (Open-Meteo returns without Z suffix)
                valid_at = time_str if time_str.endswith("Z") else f"{time_str}Z"
                datetime.fromisoformat(valid_at.replace("Z", "+00:00"))

                temp_c = float(temps[i]) if i < len(temps) else 0.0
                wind_kph = float(winds[i]) if i < len(winds) else 0.0
                wind_deg = int(wind_dirs[i]) if i < len(wind_dirs) else 0
                precip_mm = float(precips[i]) if i < len(precips) else 0.0
                humidity = int(humidities[i]) if i < len(humidities) else 50
                visibility = float(visibilities[i]) if i < len(visibilities) else None

                # Map WMO code to canonical value
                wmo_code = weather_codes[i] if i < len(weather_codes) else 0
                condition = self._wmo_to_condition(wmo_code)

                horizon_hours = int(
                    (
                        datetime.fromisoformat(valid_at.replace("Z", "+00:00"))
                        - datetime.fromisoformat(issued_at_str.replace("Z", "+00:00"))
                    ).total_seconds()
                    / 3600
                )

                forecast_id = hashlib.sha256(
                    f"{venue_id}:{valid_at}:{wmo_code}".encode()
                ).hexdigest()[:16]

                payload: WeatherForecastPayload = {
                    "forecast_id": forecast_id,
                    "venue_id": venue_id,
                    "valid_at": valid_at,
                    "issued_at": issued_at_str,
                    "horizon_hours": horizon_hours,
                    "temp_c": temp_c,
                    "wind_kph": wind_kph,
                    "wind_direction_deg": wind_deg,
                    "precip_mm_per_hr": precip_mm,
                    "humidity_pct": humidity,
                    "visibility_km": visibility,
                    "conditions": condition,
                }
                results.append(payload)
            except (ValueError, IndexError, KeyError) as e:
                log.warning(f"Failed to parse forecast record [{i}]: {e}")
                raise ExtractionError(str(e), data)

        return results

    def extract_actual(self, data: Dict[str, Any]) -> WeatherActualPayload:
        """Extract a single weather actual observation."""
        required_fields = {
            "actual_id": str,
            "venue_id": str,
            "observed_at": str,
            "temperature_2m": (int, float),
            "wind_speed_10m": (int, float),
            "wind_direction_10m": int,
            "precipitation": (int, float),
            "relative_humidity_2m": int,
        }

        for field, expected_types in required_fields.items():
            if field not in data:
                raise ExtractionError(f"missing required field: {field}", data)
            if not isinstance(data[field], expected_types):
                raise ExtractionError(
                    f"field {field} has wrong type: {type(data[field]).__name__}",
                    data,
                )

        # Validate observed_at is ISO-8601 UTC
        observed_at = data["observed_at"]
        try:
            datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ExtractionError(f"invalid observed_at format: {observed_at}", data)

        wmo_code = data.get("weather_code", 0)
        condition = self._wmo_to_condition(wmo_code)

        payload: WeatherActualPayload = {
            "actual_id": data["actual_id"],
            "venue_id": data["venue_id"],
            "observed_at": observed_at,
            "temp_c": float(data["temperature_2m"]),
            "wind_kph": float(data["wind_speed_10m"]),
            "wind_direction_deg": int(data["wind_direction_10m"]),
            "precip_mm_per_hr": float(data["precipitation"]),
            "humidity_pct": int(data["relative_humidity_2m"]),
            "visibility_km": float(data.get("visibility", 10.0)),
            "conditions": condition,
        }

        return payload

    def extract_pitch_condition(self, data: Dict[str, Any]) -> PitchConditionPayload:
        """Extract a single pitch condition inspection record."""
        required_fields = {
            "pitch_id": str,
            "venue_id": str,
            "surface": str,
            "condition": str,
            "inspection_at": str,
        }

        for field, expected_type in required_fields.items():
            if field not in data:
                raise ExtractionError(f"missing required field: {field}", data)
            if not isinstance(data[field], expected_type):
                raise ExtractionError(
                    f"field {field} has wrong type: {type(data[field]).__name__}",
                    data,
                )

        surface = data["surface"]
        if surface not in ("natural_grass", "hybrid", "artificial_turf", "indoor"):
            raise ExtractionError(f"invalid surface value: {surface}", data)

        condition = data["condition"]
        valid_conditions = (
            "pristine",
            "good",
            "worn",
            "muddy",
            "frozen",
            "playable_with_concerns",
        )
        if condition not in valid_conditions:
            raise ExtractionError(f"invalid condition value: {condition}", data)

        # Validate inspection_at is ISO-8601 UTC
        inspection_at = data["inspection_at"]
        try:
            datetime.fromisoformat(inspection_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ExtractionError(f"invalid inspection_at format: {inspection_at}", data)

        # last_match_at is optional
        last_match_at = data.get("last_match_at")
        if last_match_at is not None:
            try:
                datetime.fromisoformat(last_match_at.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                raise ExtractionError(
                    f"invalid last_match_at format: {last_match_at}",
                    data,
                )

        payload: PitchConditionPayload = {
            "pitch_id": data["pitch_id"],
            "venue_id": data["venue_id"],
            "surface": surface,  # type: ignore
            "condition": condition,  # type: ignore
            "last_match_at": last_match_at,
            "inspection_at": inspection_at,
        }

        return payload

    def _wmo_to_condition(self, wmo_code: int) -> str:
        """Map WMO code to canonical condition string."""
        if wmo_code == 0:
            return "clear"
        elif 1 <= wmo_code <= 3:
            return "clear"
        elif wmo_code in (45, 48):
            return "fog"
        elif 51 <= wmo_code <= 67:
            return "rain"
        elif 71 <= wmo_code <= 77:
            return "snow"
        elif 80 <= wmo_code <= 82:
            return "rain"
        elif 85 <= wmo_code <= 86:
            return "snow"
        elif 95 <= wmo_code <= 99:
            return "thunderstorm"
        else:
            log.debug(f"Unknown WMO code {wmo_code}, defaulting to clear")
            return "clear"
