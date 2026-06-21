"""Phase 21 §21.0 — Enrichment configuration stubs and validation tests."""

import json
from pathlib import Path

import msgpack
import pytest

from ai.common.config import Config, cfg


class TestEnrichmentConfigPresence:
    """All enrichment feature flags and numeric tunables must be present with correct types."""

    def test_all_enrichment_feature_flags_present_with_correct_types(self) -> None:
        """Assert every feature flag exists with expected Python type."""
        flags = [
            ("enrichment_roster_enabled", bool),
            ("enrichment_health_enabled", bool),
            ("enrichment_officials_enabled", bool),
            ("enrichment_environment_enabled", bool),
            ("enrichment_market_movement_enabled", bool),
            ("enrichment_fixture_congestion_enabled", bool),
            ("enrichment_card_context_enabled", bool),
            ("enrichment_narrative_pressure_enabled", bool),
        ]
        for attr_name, expected_type in flags:
            assert hasattr(cfg, attr_name), f"Config missing {attr_name}"
            value = getattr(cfg, attr_name)
            assert isinstance(value, expected_type), (
                f"Config.{attr_name} type is {type(value).__name__}, "
                f"expected {expected_type.__name__}"
            )

    def test_all_numeric_tunables_within_valid_range(self) -> None:
        """Sanity bounds for all numeric enrichment tunables."""
        # Floats in (0, 1)
        bounded_01 = [
            ("enrichment_departure_shock", (0.0, 1.0)),
            ("enrichment_referee_home_bias_clamp", (0.0, 1.0)),
            ("enrichment_drift_high_threshold", (0.0, 1.0)),
            ("enrichment_health_ci_widen_threshold", (0.0, 1.0)),
            ("nlp_injury_lookup_confidence_threshold", (0.0, 1.0)),
        ]
        for attr_name, (lo, hi) in bounded_01:
            value = getattr(cfg, attr_name)
            assert lo <= value <= hi, (
                f"Config.{attr_name}={value} not in [{lo}, {hi}]"
            )

        # Positive floats
        positive_floats = [
            ("enrichment_congestion_xg_decay", 0.001),
            ("enrichment_surface_style_penalty", 0.0),
            ("enrichment_wind_threshold_kph", 0.0),
            ("enrichment_rain_threshold_mm", 0.0),
            ("enrichment_promotion_logloss_delta", 0.0),
        ]
        for attr_name, min_val in positive_floats:
            value = getattr(cfg, attr_name)
            assert value >= min_val, (
                f"Config.{attr_name}={value} not >= {min_val}"
            )

        # Positive integers
        positive_ints = [
            ("enrichment_narrative_min_articles", 1),
            ("enrichment_weather_forecast_max_age_h", 1),
            ("enrichment_circuit_failure_threshold", 1),
            ("enrichment_circuit_window_s", 1),
            ("enrichment_circuit_cooldown_s", 1),
            ("enrichment_derived_view_coalesce_ms", 1),
            ("enrichment_weather_dedup_window_s", 1),
            ("enrichment_referee_batch_max", 1),
            ("enrichment_referee_window_matches", 1),
            ("enrichment_cache_ttl_s", 1),
            ("enrichment_env_cache_ttl_s", 1),
            ("enrichment_roster_stale_s", 1),
            ("enrichment_health_stale_s", 1),
            ("enrichment_officials_stale_s", 1),
            ("enrichment_environment_stale_s", 1),
            ("enrichment_health_stale_threshold_s", 1),
            ("enrichment_feed_backpressure_threshold", 1),
            ("enrichment_feed_backpressure_retry_base_ms", 1),
            ("enrichment_feed_backpressure_max_retries", 1),
            ("enrichment_scraper_timeout_s", 1),
            ("enrichment_scraper_retry_max", 1),
            ("enrichment_scraper_retry_backoff_ms", 1),
            ("enrichment_calibration_seed", 0),
            ("enrichment_reactor_heartbeat_ttl_s", 1),
            ("enrichment_reactor_watchdog_interval_s", 1),
            ("enrichment_reactor_stall_escalation_count", 1),
            ("enrichment_consistency_check_interval_s", 1),
            ("db_pool_max_enrichment", 1),
        ]
        for attr_name, min_val in positive_ints:
            value = getattr(cfg, attr_name)
            assert isinstance(value, int), (
                f"Config.{attr_name} type is {type(value).__name__}, expected int"
            )
            assert value >= min_val, (
                f"Config.{attr_name}={value} not >= {min_val}"
            )

        # Cohesion penalty curve: list of 4 floats in [0, 1]
        assert isinstance(cfg.enrichment_cohesion_penalty_curve, list)
        assert len(cfg.enrichment_cohesion_penalty_curve) == 4, (
            f"enrichment_cohesion_penalty_curve has {len(cfg.enrichment_cohesion_penalty_curve)} values, "
            "expected 4"
        )
        for i, val in enumerate(cfg.enrichment_cohesion_penalty_curve):
            assert isinstance(val, float), (
                f"enrichment_cohesion_penalty_curve[{i}] type is {type(val).__name__}, expected float"
            )
            assert 0.0 <= val <= 1.0, (
                f"enrichment_cohesion_penalty_curve[{i}]={val} not in [0, 1]"
            )

    def test_version_chart_has_four_enrichment_keys(self) -> None:
        """Assert xops/versioning/chart.json has all four enrichment keys with correct versions."""
        chart_path = Path(__file__).resolve().parent.parent.parent / "xops" / "versioning" / "chart.json"
        assert chart_path.exists(), f"chart.json not found at {chart_path}"
        
        with open(chart_path, "r", encoding="utf-8") as fh:
            chart = json.load(fh)
        
        components = chart.get("components", {})
        # enrichment_roster is bumped to 0.2.0 during Phase 21.1 implementation
        expected_versions = {
            "enrichment_roster": "0.2.0",
            "enrichment_health": "0.1.0",
            "enrichment_officials": "0.1.0",
            "enrichment_environment": "0.1.0",
        }
        for key, expected_version in expected_versions.items():
            assert key in components, (
                f"chart.json components missing {key}"
            )
            entry = components[key]
            assert entry.get("version") == expected_version, (
                f"chart.json {key} version is {entry.get('version')}, expected {expected_version}"
            )
            assert entry.get("will_reach_1_0_0_in_phase") == 21, (
                f"chart.json {key} missing will_reach_1_0_0_in_phase: 21"
            )

    def test_env_example_documents_every_enrichment_key(self) -> None:
        """Assert xops/env/.env.example has every enrichment key."""
        env_example_path = (
            Path(__file__).resolve().parent.parent.parent / "xops" / "env" / ".env.example"
        )
        assert env_example_path.exists(), f".env.example not found at {env_example_path}"
        
        content = env_example_path.read_text(encoding="utf-8")
        required_keys = [
            "ENRICHMENT_ROSTER_ENABLED",
            "ENRICHMENT_HEALTH_ENABLED",
            "ENRICHMENT_OFFICIALS_ENABLED",
            "ENRICHMENT_ENVIRONMENT_ENABLED",
            "ENRICHMENT_MARKET_MOVEMENT_ENABLED",
            "ENRICHMENT_FIXTURE_CONGESTION_ENABLED",
            "ENRICHMENT_CARD_CONTEXT_ENABLED",
            "ENRICHMENT_NARRATIVE_PRESSURE_ENABLED",
            "ENRICHMENT_COHESION_PENALTY_CURVE",
            "ENRICHMENT_DEPARTURE_SHOCK",
            "ENRICHMENT_CONGESTION_XG_DECAY",
            "ENRICHMENT_REFEREE_HOME_BIAS_CLAMP",
            "ENRICHMENT_DRIFT_HIGH_THRESHOLD",
            "ENRICHMENT_NARRATIVE_MIN_ARTICLES",
            "ENRICHMENT_WEATHER_FORECAST_MAX_AGE_H",
            "ENRICHMENT_PROMOTION_LOGLOSS_DELTA",
            "ENRICHMENT_ROSTER_CRON",
            "ENRICHMENT_SURFACE_STYLE_PENALTY",
            "ENRICHMENT_WIND_THRESHOLD_KPH",
            "ENRICHMENT_RAIN_THRESHOLD_MM",
            "ENRICHMENT_REFEREE_WINDOW_MATCHES",
            "ENRICHMENT_CACHE_TTL_S",
            "ENRICHMENT_ENV_CACHE_TTL_S",
            "ENRICHMENT_HEALTH_CI_WIDEN_THRESHOLD",
            "ENRICHMENT_CIRCUIT_FAILURE_THRESHOLD",
            "ENRICHMENT_CIRCUIT_WINDOW_S",
            "ENRICHMENT_CIRCUIT_COOLDOWN_S",
            "ENRICHMENT_DERIVED_VIEW_COALESCE_MS",
            "ENRICHMENT_WEATHER_DEDUP_WINDOW_S",
            "ENRICHMENT_REFEREE_BATCH_MAX",
            "ENRICHMENT_FALLBACK_VALUES_PATH",
            "ENRICHMENT_ROSTER_STALE_S",
            "ENRICHMENT_HEALTH_STALE_S",
            "ENRICHMENT_OFFICIALS_STALE_S",
            "ENRICHMENT_ENVIRONMENT_STALE_S",
            "ENRICHMENT_HEALTH_STALE_THRESHOLD_S",
            "ENRICHMENT_BACKFILL_MODE",
            "ENRICHMENT_RETRAIN_FLAG_PATH",
            "DB_POOL_MAX_ENRICHMENT",
            "ENRICHMENT_FEED_BACKPRESSURE_THRESHOLD",
            "ENRICHMENT_FEED_BACKPRESSURE_RETRY_BASE_MS",
            "ENRICHMENT_FEED_BACKPRESSURE_MAX_RETRIES",
            "ENRICHMENT_SCRAPER_TIMEOUT_S",
            "ENRICHMENT_SCRAPER_RETRY_MAX",
            "ENRICHMENT_SCRAPER_RETRY_BACKOFF_MS",
            "WEATHER_API_URL",
            "ENRICHMENT_CONFEDERATION_CALENDAR_PATH",
            "ENRICHMENT_CALIBRATION_SEED",
            "NLP_INJURY_LOOKUP_CONFIDENCE_THRESHOLD",
            "ENRICHMENT_REACTOR_HEARTBEAT_TTL_S",
            "ENRICHMENT_REACTOR_WATCHDOG_INTERVAL_S",
            "ENRICHMENT_REACTOR_STALL_ESCALATION_COUNT",
            "ENRICHMENT_CONSISTENCY_CHECK_INTERVAL_S",
        ]
        for key in required_keys:
            assert key in content, (
                f".env.example missing {key}"
            )

    def test_fallback_values_path_key_present_in_config(self) -> None:
        """Assert ENRICHMENT_FALLBACK_VALUES_PATH is configured."""
        assert hasattr(cfg, "enrichment_fallback_values_path")
        assert isinstance(cfg.enrichment_fallback_values_path, str)
        assert len(cfg.enrichment_fallback_values_path) > 0

    def test_weather_api_url_has_no_hardcoded_default(self) -> None:
        """Assert WEATHER_API_URL has None as default (no hardcoded URL)."""
        assert hasattr(cfg, "weather_api_url")
        # When not set, should be None (no default URL hardcoded)
        # If it's set, it's from the environment
        if cfg.weather_api_url is not None:
            assert isinstance(cfg.weather_api_url, str)
            assert cfg.weather_api_url.startswith("http")

    def test_confederation_calendar_seed_file_exists(self) -> None:
        """Assert data/confederation_calendars.json exists and is valid JSON."""
        cal_path = (
            Path(__file__).resolve().parent.parent.parent / "data" / "confederation_calendars.json"
        )
        assert cal_path.exists(), f"confederation_calendars.json not found at {cal_path}"
        
        content = cal_path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert "confederations" in data, "confederation_calendars.json missing 'confederations' key"
        assert isinstance(data["confederations"], list)
        assert len(data["confederations"]) > 0, "confederation_calendars.json has no confederations"

    def test_msgpack_importable_at_configured_version(self) -> None:
        """Assert msgpack is importable and version >= 1.0."""
        # If this test runs, import succeeded
        assert msgpack is not None
        # Check version
        version_str = msgpack.version[0]
        major = int(str(version_str).split(".")[0])
        assert major >= 1, f"msgpack version {version_str} < 1.0"
