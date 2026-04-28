"""
Negelir — Configuration loaded from environment variables.
All settings respect Docker Compose injection.
"""

import os
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


# Env-var prefixes considered "owned" by the Python config layer.
# Strict mode (`NEGELIR_STRICT=1`) refuses unknown keys with these prefixes.
# `SWARM_` was added in Phase 3 (§3.3 DoD: triangle test stays green for
# the 9 SDK knobs); a typo like `SWARM_HEARTBEET_SEC` must surface, not
# silently fall through to the dataclass default.
_OWNED_ENV_PREFIXES: tuple[str, ...] = ("NEGELIR_", "SCRAPE_", "SWARM_")

# Pattern that captures every env-var name read via os.getenv in this module.
_GETENV_RE = re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']""")


def _declared_env_keys() -> frozenset[str]:
    """Set of every env-var name referenced via os.getenv(...) in this file."""
    here = os.path.abspath(__file__)
    try:
        with open(here, "r", encoding="utf-8") as fh:
            return frozenset(_GETENV_RE.findall(fh.read()))
    except OSError:
        return frozenset()


def _derive_default_season() -> str:
    """Date-derived ``"YYYY-YYYY+1"`` fallback for :attr:`Config.default_season`.

    Imported lazily to avoid a circular import with ``common.logger`` at
    module-load time.
    """
    from common.season import current_season
    return current_season()


@dataclass
class Config:
    # PostgreSQL
    pg_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    pg_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    pg_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "negelir"))
    pg_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "negelir"))
    pg_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", ""))

    # Redis
    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))

    # Go server
    server_url: str = field(default_factory=lambda: os.getenv("SERVER_URL", "http://localhost:8080"))

    # AI
    device: str = field(default_factory=lambda: os.getenv("AI_DEVICE", "auto"))
    log_level: str = field(default_factory=lambda: os.getenv("AI_LOG_LEVEL", "DEBUG"))

    # Runtime defaults
    default_league_id: str = field(default_factory=lambda: os.getenv("NEGELIR_DEFAULT_LEAGUE_ID", "super_lig"))
    default_season: str = field(default_factory=lambda: (
        os.getenv("NEGELIR_DEFAULT_SEASON")
        or _derive_default_season()
    ))
    mackolik_group_id: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MACKOLIK_GROUP_ID", "1")))
    mackolik_league_name_filter: str = field(default_factory=lambda: os.getenv("NEGELIR_MACKOLIK_LEAGUE_FILTER", "Süper Lig"))

    # Scraper and server timeouts
    server_fetch_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SERVER_FETCH_TIMEOUT", "10")))
    scrape_trigger_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCRAPE_TRIGGER_TIMEOUT", "30")))
    health_check_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_HEALTH_CHECK_TIMEOUT", "5")))
    mackolik_http_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MACKOLIK_HTTP_TIMEOUT", "15")))
    scrape_http_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCRAPE_HTTP_TIMEOUT", "15")))
    footballdata_http_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_FOOTBALLDATA_HTTP_TIMEOUT", "10")))

    # Scheduler defaults
    schedule_daily_scrape_hour: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCHEDULE_DAILY_SCRAPE_HOUR", "6")))
    schedule_daily_scrape_minute: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCHEDULE_DAILY_SCRAPE_MINUTE", "0")))
    schedule_outcome_check_hour: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCHEDULE_OUTCOME_CHECK_HOUR", "22")))
    schedule_outcome_check_minute: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCHEDULE_OUTCOME_CHECK_MINUTE", "0")))
    schedule_retrain_day: str = field(default_factory=lambda: os.getenv("NEGELIR_SCHEDULE_RETRAIN_DAY", "sun"))
    schedule_retrain_hour: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCHEDULE_RETRAIN_HOUR", "3")))
    schedule_heartbeat_minutes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SCHEDULE_HEARTBEAT_MINUTES", "5")))

    # Self-healing defaults
    _source_priority_raw: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_SOURCE_PRIORITY", "source_a,source_b,source_c,source_d"
    ))
    stale_threshold_seconds: int = field(default_factory=lambda: int(os.getenv(
        "NEGELIR_STALE_THRESHOLD_SECONDS", "604800"
    )))
    stale_confidence_penalty: float = field(default_factory=lambda: float(os.getenv(
        "NEGELIR_STALE_CONFIDENCE_PENALTY", "0.5"
    )))
    source_failure_threshold: int = field(default_factory=lambda: int(os.getenv(
        "NEGELIR_SOURCE_FAILURE_THRESHOLD", "3"
    )))

    # Scraping
    scrape_rate_limit: int = field(default_factory=lambda: int(os.getenv("SCRAPE_RATE_LIMIT_SECONDS", "2")))
    real_data_rate_limit: float = field(default_factory=lambda: float(os.getenv(
        "NEGELIR_REAL_DATA_RATE_LIMIT", "1.0"
    )))
    scrape_user_agent: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_USER_AGENT", "Xops/0.1 (Football Analysis Research)"
    ))
    scrape_respect_robots: bool = field(default_factory=lambda: os.getenv(
        "SCRAPE_RESPECT_ROBOTS_TXT", "true"
    ).lower() in ("true", "1", "yes"))

    # Scraping data sources (in priority order)
    scrape_source_1: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_1", "https://www.mackolik.com"
    ))
    scrape_source_2: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_2", "https://www.nesine.com"
    ))
    scrape_source_3: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_3", "https://www.tff.org"
    ))
    scrape_source_4: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_4", "https://raw.githubusercontent.com/openfootball/football.json/master"
    ))
    scrape_source_5: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_5", "https://www.football-data.co.uk/mmz4281"
    ))
    # Fallback: historical archive (slower, throttled)
    scrape_source_fallback: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_FALLBACK", "https://arsiv.mackolik.com"
    ))
    scrape_source_extra: str = field(default_factory=lambda: os.getenv(
        "SCRAPE_SOURCE_EXTRA", ""
    ))

    # Mackolik archive season IDs (read from individual env vars)
    _mackolik_season_2025_2026: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2025_2026", "70381"
    ))
    _mackolik_season_2024_2025: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2024_2025", "67287"
    ))
    _mackolik_season_2023_2024: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2023_2024", "62682"
    ))
    _mackolik_season_2022_2023: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2022_2023", "59539"
    ))
    _mackolik_season_2021_2022: str = field(default_factory=lambda: os.getenv(
        "MACKOLIK_SEASON_2021_2022", "55775"
    ))

    # openfootball season dirs (comma-separated "dir:label" pairs)
    _openfootball_seasons_raw: str = field(default_factory=lambda: os.getenv(
        "OPENFOOTBALL_SEASONS",
        "2018-19:2018-19,2019-20:2019-20,2020-21:2020-21,2024-25:2024-25,2025-26:2025-26",
    ))

    # football-data.co.uk season codes (comma-separated "code:label" pairs)
    _footballdata_uk_seasons_raw: str = field(default_factory=lambda: os.getenv(
        "FOOTBALLDATA_UK_SEASONS",
        "2526:2025-26,2425:2024-25,2324:2023-24,2223:2022-23,2122:2021-22,2021:2020-21,1920:2019-20,1819:2018-19",
    ))

    @property
    def scrape_mackolik_archive(self) -> str:
        """Base URL for the Mackolik historical archive (fallback source)."""
        return self.scrape_source_fallback

    @property
    def scrape_openfootball_base(self) -> str:
        """Base URL for openfootball GitHub JSON files (source 4)."""
        return self.scrape_source_4

    @property
    def scrape_footballdata_base(self) -> str:
        """Base URL for football-data.co.uk CSV archive (source 5)."""
        return self.scrape_source_5

    @property
    def mackolik_known_seasons(self) -> dict[str, int]:
        """Trendyol Süper Lig season label → Mackolik season ID."""
        return {
            "2025/2026": int(self._mackolik_season_2025_2026),
            "2024/2025": int(self._mackolik_season_2024_2025),
            "2023/2024": int(self._mackolik_season_2023_2024),
            "2022/2023": int(self._mackolik_season_2022_2023),
            "2021/2022": int(self._mackolik_season_2021_2022),
        }

    @property
    def openfootball_seasons(self) -> list[tuple[str, str]]:
        """List of (season_dir, label) pairs for openfootball.

        The repository covers many leagues; the per-league file is selected
        by `LeagueConfig.openfootball_path` (e.g. `tr.1.json` for the seeded
        Turkish Süper Lig default).
        """
        result = []
        for entry in self._openfootball_seasons_raw.split(","):
            entry = entry.strip()
            if ":" in entry:
                dir_, label = entry.split(":", 1)
                result.append((dir_.strip(), label.strip()))
        return result

    @property
    def footballdata_uk_seasons(self) -> dict[str, str]:
        """Dict of season_code → label for football-data.co.uk."""
        result = {}
        for entry in self._footballdata_uk_seasons_raw.split(","):
            entry = entry.strip()
            if ":" in entry:
                code, label = entry.split(":", 1)
                result[code.strip()] = label.strip()
        return result

    @property
    def scrape_sources(self) -> list[dict[str, str]]:
        """All active scraping sources as a list of {name, url} dicts (priority order)."""
        _LABELS = {
            "source_1": "Live Scores & Odds",
            "source_2": "Betting Aggregator",
            "source_3": "Official Turkish FA",
            "source_4": "OpenFootball JSON",
            "source_5": "Football-Data.co.uk CSV",
            "source_fallback": "Historical Archive (Fallback)",
        }
        defined = [
            ("source_1", self.scrape_source_1),
            ("source_2", self.scrape_source_2),
            ("source_3", self.scrape_source_3),
            ("source_4", self.scrape_source_4),
            ("source_5", self.scrape_source_5),
            ("source_fallback", self.scrape_source_fallback),
        ]
        sources = [
            {"name": name, "label": _LABELS[name], "url": url}
            for name, url in defined
            if url
        ]
        for extra in self.scrape_source_extra.split(","):
            extra = extra.strip()
            if extra:
                sources.append({"name": "source_extra", "label": "Extra Source", "url": extra})
        return sources

    @property
    def source_priority(self) -> list[str]:
        """Ordered source preference for self-healing failover logic."""
        values = [item.strip() for item in self._source_priority_raw.split(",") if item.strip()]
        if values:
            return values
        return ["source_a", "source_b", "source_c", "source_d"]

    # Model / Training
    drift_accuracy_window: int = field(default_factory=lambda: int(os.getenv("NEGELIR_DRIFT_WINDOW", "30")))
    drift_accuracy_floor: float = field(default_factory=lambda: float(os.getenv("NEGELIR_DRIFT_FLOOR", "0.35")))
    training_noise_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_TRAINING_NOISE_PCT", "0.005")))
    training_test_split: float = field(default_factory=lambda: float(os.getenv("NEGELIR_TRAINING_TEST_SPLIT", "0.2")))
    training_random_seed: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TRAINING_SEED", "42")))
    model_max_size_mb: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MODEL_MAX_SIZE_MB", "8.0")))
    training_min_matches: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TRAINING_MIN_MATCHES", "100")))

    # Sample weights per class (0=Home, 1=Draw, 2=Away) — comma-separated
    _training_sample_weights_raw: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_TRAINING_SAMPLE_WEIGHTS", "1.0,2.0,1.0"
    ))

    @property
    def training_sample_weights(self) -> dict[int, float]:
        parts = self._training_sample_weights_raw.split(",")
        return {i: float(v.strip()) for i, v in enumerate(parts)}

    # Telemetry
    telemetry_max_stream_len: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TELEMETRY_MAX_STREAM", "50000")))
    redis_socket_timeout: int = field(default_factory=lambda: int(os.getenv("NEGELIR_REDIS_SOCKET_TIMEOUT", "2")))

    # Swarm SDK (Phase 3) — bus, registry, agent runner
    swarm_bus_kind: str = field(default_factory=lambda: os.getenv("SWARM_BUS_KIND", "redis"))
    swarm_consumer_group_prefix: str = field(default_factory=lambda: os.getenv("SWARM_CONSUMER_GROUP_PREFIX", "swarm"))
    swarm_heartbeat_sec: int = field(default_factory=lambda: int(os.getenv("SWARM_HEARTBEAT_SEC", "5")))
    swarm_registry_ttl_sec: int = field(default_factory=lambda: int(os.getenv("SWARM_REGISTRY_TTL_SEC", "30")))
    swarm_max_in_flight: int = field(default_factory=lambda: int(os.getenv("SWARM_MAX_IN_FLIGHT", "32")))
    swarm_retry_budget: int = field(default_factory=lambda: int(os.getenv("SWARM_RETRY_BUDGET", "3")))
    swarm_dlq_max_len: int = field(default_factory=lambda: int(os.getenv("SWARM_DLQ_MAX_LEN", "10000")))
    swarm_pending_claim_sec: int = field(default_factory=lambda: int(os.getenv("SWARM_PENDING_CLAIM_SEC", "60")))
    swarm_metrics_port: int = field(default_factory=lambda: int(os.getenv("SWARM_METRICS_PORT", "9100")))

    # Phase 4 worker agents — scrape → categorize → process → store loop
    scrape_profile: str = field(default_factory=lambda: os.getenv("SCRAPE_PROFILE", "mock"))
    scrape_http_max_retries: int = field(default_factory=lambda: int(os.getenv("SCRAPE_HTTP_MAX_RETRIES", "3")))
    categorizer_min_conf: float = field(default_factory=lambda: float(os.getenv("NEGELIR_CATEGORIZER_MIN_CONF", "0.55")))
    categorizer_model_path: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_CATEGORIZER_MODEL_PATH", "data/models/categorizer_v1.joblib"
    ))
    cache_record_ttl_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CACHE_RECORD_TTL_SEC", "600")))
    cache_prediction_ttl_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CACHE_PREDICTION_TTL_SEC", "300")))
    telemetry_metrics_port: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TELEMETRY_METRICS_PORT", "9101")))
    reactor_max_event_age_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_REACTOR_MAX_EVENT_AGE_SEC", "86400")))

    # Bootstrap / data validation
    bootstrap_min_matches: int = field(default_factory=lambda: int(os.getenv(
        "BOOTSTRAP_MIN_MATCHES", "100"
    )))

    # Feature-vector range validation (roadmap §5.6.2 firewall).
    # Override via NEGELIR_FEATURE_RANGES_JSON='{"elo":[-500,3500], ...}'.
    _feature_ranges_raw: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_FEATURE_RANGES_JSON", ""
    ))

    @property
    def feature_ranges(self) -> dict[str, tuple[float, float]]:
        """
        Mapping of feature-name substring → (lo, hi) clamp range.
        Defaults match roadmap §5.6.2 firewall spec; override via
        NEGELIR_FEATURE_RANGES_JSON for league-specific tuning.
        """
        defaults: dict[str, tuple[float, float]] = {
            "elo":       (-500.0, 3500.0),
            "ratio":     (0.0, 1.0),
            "pct":       (0.0, 100.0),
            "norm":      (0.0, 1.0),
            "sentiment": (-1.0, 1.0),
            "optimism":  (-1.0, 1.0),
            "sin":       (-1.0, 1.0),
            "cos":       (-1.0, 1.0),
            "flag":      (0.0, 1.0),
            "age":       (15.0, 45.0),
            "scored":    (0.0, 10.0),
            "conceded":  (0.0, 10.0),
            "yellows":   (0.0, 10.0),
            "fouls":     (0.0, 40.0),
            "cards":     (0.0, 15.0),
            "bayesian":  (0.0, 1.0),
            "sos":       (800.0, 2200.0),
            "default":   (-100.0, 100.0),
        }
        raw = self._feature_ranges_raw.strip()
        if not raw:
            return defaults
        try:
            parsed = json.loads(raw)
            return {k: (float(v[0]), float(v[1])) for k, v in parsed.items()}
        except (ValueError, TypeError, KeyError, IndexError):
            return defaults

    # Paths
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "/data"))
    model_dir: str = field(default_factory=lambda: os.getenv("MODEL_DIR", "/data/models"))
    report_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_REPORT_DIR", "/data/reports"))

    # Phase 3 — Training pipeline thresholds (env-overridable)
    training_thresholds_model_acc: float = field(default_factory=lambda: float(os.getenv(
        "NEGELIR_THRESHOLD_MODEL_ACC", "0.50"
    )))
    training_thresholds_holdout_acc: float = field(default_factory=lambda: float(os.getenv(
        "NEGELIR_THRESHOLD_HOLDOUT_ACC", "0.50"
    )))
    training_thresholds_quarantine_max: float = field(default_factory=lambda: float(os.getenv(
        "NEGELIR_THRESHOLD_QUARANTINE_MAX", "0.10"
    )))
    training_thresholds_min_holdout_matches: int = field(default_factory=lambda: int(os.getenv(
        "NEGELIR_THRESHOLD_MIN_HOLDOUT_MATCHES", "5"
    )))
    verification_window_weeks: int = field(default_factory=lambda: int(os.getenv(
        "NEGELIR_VERIFICATION_WINDOW_WEEKS", "4"
    )))

    @property
    def training_thresholds(self) -> dict[str, float | int]:
        """Phase 3: numeric thresholds driving pipeline pass/fail verdict."""
        return {
            "model_acc": self.training_thresholds_model_acc,
            "ensemble_acc": self.training_thresholds_holdout_acc,  # legacy key alias
            "holdout_acc": self.training_thresholds_holdout_acc,
            "quarantine_max": self.training_thresholds_quarantine_max,
            "min_holdout_matches": self.training_thresholds_min_holdout_matches,
        }

    @property
    def pg_dsn(self) -> str:
        return f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} user={self.pg_user} password={self.pg_password}"

    @property
    def pg_url(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"

    def validate(self, *, strict: bool = False) -> list[str]:
        """
        Sanity-check configuration values. Returns list of issue strings.
        When strict=True, raises ValueError on any issue.

        Numeric ranges, port bounds, and probability fractions are validated.
        Empty/missing secrets are reported but never echoed back.
        """
        issues: list[str] = []

        def _bounded(name: str, value, lo, hi, *, allow_eq_hi: bool = True):
            try:
                v = float(value)
            except (TypeError, ValueError):
                issues.append(f"{name}: not numeric ({value!r})")
                return
            ok = (lo <= v <= hi) if allow_eq_hi else (lo <= v < hi)
            if not ok:
                issues.append(f"{name}={v} outside [{lo}, {hi}]")

        # Ports
        _bounded("pg_port", self.pg_port, 1, 65535)
        _bounded("redis_port", self.redis_port, 1, 65535)
        _bounded("swarm_metrics_port", self.swarm_metrics_port, 1, 65535)
        _bounded("telemetry_metrics_port", self.telemetry_metrics_port, 1, 65535)
        _bounded("categorizer_min_conf", self.categorizer_min_conf, 0.0, 1.0)
        _bounded("scrape_http_max_retries", self.scrape_http_max_retries, 0, 100)
        _bounded("cache_record_ttl_sec", self.cache_record_ttl_sec, 1, 86400 * 30)
        _bounded("cache_prediction_ttl_sec", self.cache_prediction_ttl_sec, 1, 86400 * 30)
        _bounded("reactor_max_event_age_sec", self.reactor_max_event_age_sec, 1, 86400 * 365)
        if self.scrape_profile not in ("mock", "real"):
            issues.append(
                f"scrape_profile={self.scrape_profile!r} not in ('mock', 'real')"
            )

        # Swarm bus kind enum
        _swarm_bus_kinds = {"redis", "memory"}
        if self.swarm_bus_kind not in _swarm_bus_kinds:
            issues.append(
                f"swarm_bus_kind={self.swarm_bus_kind!r} must be one of "
                f"{sorted(_swarm_bus_kinds)}"
            )

        # Probability / fraction fields
        _bounded("drift_accuracy_floor", self.drift_accuracy_floor, 0.0, 1.0)
        _bounded("training_noise_pct", self.training_noise_pct, 0.0, 1.0)
        _bounded("training_test_split", self.training_test_split, 0.0, 1.0, allow_eq_hi=False)
        _bounded("stale_confidence_penalty", self.stale_confidence_penalty, 0.0, 1.0)
        _bounded("training_thresholds_model_acc", self.training_thresholds_model_acc, 0.0, 1.0)
        _bounded("training_thresholds_holdout_acc", self.training_thresholds_holdout_acc, 0.0, 1.0)
        _bounded("training_thresholds_quarantine_max", self.training_thresholds_quarantine_max, 0.0, 1.0)

        # Positive integers
        for name, value in (
            ("drift_accuracy_window", self.drift_accuracy_window),
            ("training_min_matches", self.training_min_matches),
            ("source_failure_threshold", self.source_failure_threshold),
            ("stale_threshold_seconds", self.stale_threshold_seconds),
            ("telemetry_max_stream_len", self.telemetry_max_stream_len),
            ("server_fetch_timeout", self.server_fetch_timeout),
            ("scrape_trigger_timeout", self.scrape_trigger_timeout),
            ("health_check_timeout", self.health_check_timeout),
            ("mackolik_http_timeout", self.mackolik_http_timeout),
            ("scrape_http_timeout", self.scrape_http_timeout),
            ("footballdata_http_timeout", self.footballdata_http_timeout),
            ("redis_socket_timeout", self.redis_socket_timeout),
            ("training_thresholds_min_holdout_matches", self.training_thresholds_min_holdout_matches),
            ("verification_window_weeks", self.verification_window_weeks),
            ("bootstrap_min_matches", self.bootstrap_min_matches),
            ("swarm_heartbeat_sec", self.swarm_heartbeat_sec),
            ("swarm_registry_ttl_sec", self.swarm_registry_ttl_sec),
            ("swarm_max_in_flight", self.swarm_max_in_flight),
            ("swarm_retry_budget", self.swarm_retry_budget),
            ("swarm_dlq_max_len", self.swarm_dlq_max_len),
            ("swarm_pending_claim_sec", self.swarm_pending_claim_sec),
        ):
            if not isinstance(value, int) or value <= 0:
                issues.append(f"{name}={value} must be a positive integer")

        # Hour/minute ranges
        _bounded("schedule_daily_scrape_hour", self.schedule_daily_scrape_hour, 0, 23)
        _bounded("schedule_outcome_check_hour", self.schedule_outcome_check_hour, 0, 23)
        _bounded("schedule_retrain_hour", self.schedule_retrain_hour, 0, 23)
        _bounded("schedule_daily_scrape_minute", self.schedule_daily_scrape_minute, 0, 59)
        _bounded("schedule_outcome_check_minute", self.schedule_outcome_check_minute, 0, 59)

        # Day-of-week for retrain schedule (APScheduler short-form names)
        _ALLOWED_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if str(self.schedule_retrain_day).lower() not in _ALLOWED_DAYS:
            issues.append(
                f"schedule_retrain_day={self.schedule_retrain_day!r} "
                f"must be one of {sorted(_ALLOWED_DAYS)}"
            )

        # Feature-range JSON override must parse to (lo, hi) tuples with lo < hi
        try:
            for fname, (lo, hi) in self.feature_ranges.items():
                if lo >= hi:
                    issues.append(f"feature_ranges[{fname!r}]: lo={lo} >= hi={hi}")
        except (ValueError, TypeError, KeyError) as e:
            issues.append(f"feature_ranges parse error: {e}")

        # Required strings
        if not self.default_league_id:
            issues.append("default_league_id is empty")
        if not self.data_dir:
            issues.append("data_dir is empty")
        if not self.model_dir:
            issues.append("model_dir is empty")
        if not self.report_dir:
            issues.append("report_dir is empty")

        # Sample weights must parse and have at least 3 entries (Home/Draw/Away)
        try:
            weights = self.training_sample_weights
            if len(weights) < 3:
                issues.append(f"training_sample_weights needs >=3 entries (got {len(weights)})")
            for k, v in weights.items():
                if v < 0:
                    issues.append(f"training_sample_weights[{k}]={v} cannot be negative")
        except (ValueError, TypeError) as e:
            issues.append(f"training_sample_weights parse error: {e}")

        # URL schemes for HTTP endpoints (server + active scrape sources)
        def _check_url(name: str, value: str) -> None:
            if not value:
                return  # empty = optional / disabled
            try:
                parsed = urlparse(value)
            except (ValueError, TypeError):
                issues.append(f"{name}={value!r} is not a parseable URL")
                return
            if parsed.scheme not in ("http", "https"):
                issues.append(
                    f"{name}={value!r} must use http:// or https:// (got scheme={parsed.scheme!r})"
                )
            if not parsed.netloc:
                issues.append(f"{name}={value!r} is missing a host")

        _check_url("server_url", self.server_url)
        _check_url("scrape_source_1", self.scrape_source_1)
        _check_url("scrape_source_2", self.scrape_source_2)
        _check_url("scrape_source_3", self.scrape_source_3)
        _check_url("scrape_source_4", self.scrape_source_4)
        _check_url("scrape_source_5", self.scrape_source_5)
        _check_url("scrape_source_fallback", self.scrape_source_fallback)
        for extra in self.scrape_source_extra.split(","):
            extra = extra.strip()
            if extra:
                _check_url("scrape_source_extra", extra)

        # Strict mode: refuse unknown env keys with prefixes the Python layer owns.
        # Triggered by NEGELIR_STRICT=1 OR explicit strict=True call.
        env_strict = os.getenv("NEGELIR_STRICT", "").lower() in ("1", "true", "yes", "on")
        if strict or env_strict:
            declared = _declared_env_keys()
            stray = sorted(
                k for k in os.environ
                if k.startswith(_OWNED_ENV_PREFIXES) and k not in declared
            )
            for key in stray:
                issues.append(
                    f"unknown env key {key!r} matches reserved prefix "
                    f"({'/'.join(p.rstrip('_') for p in _OWNED_ENV_PREFIXES)}); "
                    "remove it or add a corresponding field in Config"
                )

        if strict and issues:
            raise ValueError("Config validation failed:\n  - " + "\n  - ".join(issues))
        return issues


# Singleton
cfg = Config()
