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
    nlp_predictive_overshoot_max_per_query: int = field(default_factory=lambda: int(os.getenv(
        "NEGELIR_NLP_PREDICTIVE_OVERSHOOT_MAX_PER_QUERY", "2"
    )))

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
    # Pre-Phase-6 audit (gpt5-Codex #6): approximated cross-source
    # agreement when the scrape has more than one upstream feed. The
    # real per-(date, teams)-key scorer lands with Phase 6.3 drift wiring;
    # this knob lets ops tune the placeholder until then.
    training_cross_source_agreement_multi: float = field(default_factory=lambda: float(
        os.getenv("NEGELIR_TRAINING_CROSS_SOURCE_AGREEMENT_MULTI", "0.95")
    ))
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
    # Deployment profile (cross-cutting). ``mock`` is the local-dev /
    # CI default; ``prod`` flips fail-safe gates that refuse insecure
    # configurations outright (e.g. unencrypted nightly backups —
    # ROADMAP §8.3 ``fail_safe_no_encryption_in_prod``). Validated
    # below; only the closed enum {mock, prod} is admitted.
    profile: str = field(default_factory=lambda: os.getenv("NEGELIR_PROFILE", "mock"))
    scrape_http_max_retries: int = field(default_factory=lambda: int(os.getenv("SCRAPE_HTTP_MAX_RETRIES", "3")))
    categorizer_min_conf: float = field(default_factory=lambda: float(os.getenv("NEGELIR_CATEGORIZER_MIN_CONF", "0.55")))
    categorizer_model_path: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_CATEGORIZER_MODEL_PATH", "data/models/categorizer_v1.joblib"
    ))
    cache_record_ttl_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CACHE_RECORD_TTL_SEC", "600")))
    cache_prediction_ttl_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CACHE_PREDICTION_TTL_SEC", "300")))
    telemetry_metrics_port: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TELEMETRY_METRICS_PORT", "9101")))
    telemetry_metrics_bind: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_TELEMETRY_METRICS_BIND", "127.0.0.1"
    ))
    # Phase 8.16.4 — cardinality-safe ack metrics debug gate.
    # When False (default, prod), only the low-cardinality metric family
    # maint_ack_total{accepted_by, accepted} is emitted.  When True (dev /
    # incident triage), the per-kind debug family
    # maint_ack_total_debug{kind, accepted_by, accepted} is also enabled via
    # the /metrics-debug endpoint (Phase 9).
    telemetry_debug_enabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_TELEMETRY_DEBUG_ENABLED", "false").lower() == "true")
    # Hard ceiling for debug-mode series count projected at boot.  Raising
    # telemetry_debug_enabled=true is refused if
    # len(kinds) × len(consumers) × 2 > telemetry_debug_max_series.
    telemetry_debug_max_series: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TELEMETRY_DEBUG_MAX_SERIES", "5000")))
    reactor_max_event_age_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_REACTOR_MAX_EVENT_AGE_SEC", "86400")))
    # Cap on the per-reactor in-memory idempotency ledger. The ledger
    # keys events by `(reactor_name, event_id)`; with no bound a long-
    # running swarm or backtest replay accumulates one tuple per
    # event forever (Pre-Phase-6 audit A1). The LRU evicts oldest
    # entries when the cap is hit; collisions on evicted ids are
    # impossible in practice because event_id is content-derived
    # (CONTENT_FRESHNESS §15.2).
    reactor_ledger_max_size: int = field(default_factory=lambda: int(os.getenv("NEGELIR_REACTOR_LEDGER_MAX_SIZE", "100000")))

    # Phase 5 — Predictor swarm + consensus
    consensus_window_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CONSENSUS_WINDOW_MS", "750")))
    consensus_min_confidence: float = field(default_factory=lambda: float(os.getenv("NEGELIR_CONSENSUS_MIN_CONFIDENCE", "0.0")))
    consensus_min_voters: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CONSENSUS_MIN_VOTERS", "3")))
    consensus_brier_window: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CONSENSUS_BRIER_WINDOW", "200")))
    consensus_max_pending: int = field(default_factory=lambda: int(os.getenv("NEGELIR_CONSENSUS_MAX_PENDING", "4096")))
    # Pre-Phase-6 audit A3: suppression window for repeat
    # `consensus.overflow` proof.flag emissions. When the pending set
    # is saturated, every new vote evicts an older one and would
    # otherwise emit a fresh flag — flooding proof.flag with the same
    # signal. We rate-limit the flag to one emission per N seconds.
    consensus_overflow_flag_min_interval_sec: float = field(default_factory=lambda: float(os.getenv("NEGELIR_CONSENSUS_OVERFLOW_FLAG_MIN_INTERVAL_SEC", "10")))
    predictor_market_features_enabled: bool = field(default_factory=lambda: os.getenv(
        "NEGELIR_PREDICTOR_MARKET_FEATURES_ENABLED", "false"
    ).lower() in ("true", "1", "yes"))
    predictor_max_vram_mb: int = field(default_factory=lambda: int(os.getenv("NEGELIR_PREDICTOR_MAX_VRAM_MB", "1024")))
    trainer_debounce_sec: int = field(default_factory=lambda: int(os.getenv("NEGELIR_TRAINER_DEBOUNCE_SEC", "300")))
    backtest_swarm_floor_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_BACKTEST_SWARM_FLOOR_PCT", "0.01")))
    backtest_window_weeks: int = field(default_factory=lambda: int(os.getenv("NEGELIR_BACKTEST_WINDOW_WEEKS", "12")))
    backtest_min_n: int = field(default_factory=lambda: int(os.getenv("NEGELIR_BACKTEST_MIN_N", "20")))
    api_consensus_overhead_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_CONSENSUS_OVERHEAD_MS", "200")))

    # ── Phase 6 — Proofreader & drift swarm ─────────────────
    # The proofreader replica roster is *not* a config knob — it lives
    # in `swarm.agents.proofreader.replicas.PROOFREADER_POLICY_CLASSES`
    # (one entry per distinct check policy: sanity, plausibility,
    # consistency). The aggregator quorum (`cfg.proofreader_quorum`)
    # derives from that roster so the two cannot drift. Phase-6 audit
    # F3-1 retired the standalone `NEGELIR_PROOFREADER_REPLICAS` env
    # knob because it was disconnected from the roster — setting it
    # to anything other than 3 silently broke quorum without changing
    # the actual voter count. Horizontal fan-out moves to consumer-
    # group sharding (Phase 14).
    # How long the aggregator waits, after seeing the first verdict
    # for a (request_id, prediction_id), before declaring "no quorum"
    # and dropping the candidate. Late verdicts (arriving after the
    # window) are recorded as `proofreader_late_verdict_dropped`
    # proof.flag events but do not retroactively approve a prediction.
    # 200 ms balances "give all 3 replicas a fair shot" against the
    # API SLA budget (api_consensus_overhead_ms accounts for it).
    proofreader_quorum_window_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_PROOFREADER_QUORUM_WINDOW_MS", "200")))
    # Phase 6.1 (Phase-6 audit F-9): bound for the aggregator's
    # `_pending` map. Without this the aggregator leaks memory when
    # verdicts trickle in but never reach quorum (the window flush
    # cleans them, but only if `flush_expired` actually ticks). Default
    # mirrors `consensus_max_pending` since the per-prediction shape is
    # comparable; LRU-eviction behaviour mirrors the consensus agent.
    proofreader_aggregator_max_pending: int = field(default_factory=lambda: int(os.getenv("NEGELIR_PROOFREADER_AGGREGATOR_MAX_PENDING", "4096")))
    # Phase 6 (Phase-6 audit F-2): how often the AgentRunner ticks
    # `flush_expired` on aggregator-style agents (consensus,
    # proofreader_aggregator) when no new message arrived to drive
    # `handle()`. Without this, windows never expire and `no_quorum`
    # candidates leak. 100 ms is short enough to keep window-jitter
    # below `proofreader_quorum_window_ms / 2` and long enough that the
    # tick is amortised across normal traffic.
    swarm_flush_interval_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SWARM_FLUSH_INTERVAL_MS", "100")))

    # ── Phase 6.2 — per-replica check thresholds ───────────────
    #
    # `sanity` rejects a prediction whose market_outcomes do not sum
    # to 1.0 within ±eps. 0.01 (1%) absorbs float-rounding from
    # consensus + calibration without masking real bugs (the legacy
    # tolerance was 0.01 too — kept for parity).
    proofreader_sanity_eps: float = field(default_factory=lambda: float(os.getenv("NEGELIR_PROOFREADER_SANITY_EPS", "0.01")))
    # `plausibility` warns (does NOT reject — operator-visible yes-vote
    # toward quorum) when any single market outcome exceeds this cap.
    # 0.85 picks up "lopsided derby pick" without flagging legit blowout
    # leaders against bottom-table opponents (those land ≤ 0.80 in our
    # historical Brier traces).
    proofreader_plausibility_max_prob: float = field(default_factory=lambda: float(os.getenv("NEGELIR_PROOFREADER_PLAUSIBILITY_MAX_PROB", "0.85")))
    # `consistency` rejects when score_grid marginals disagree with
    # market_outcomes by more than this per-outcome tolerance. 0.05
    # (5 percentage points) catches contract violations without
    # tripping on grid truncation rounding (we cap the grid at 9-9 so
    # the tail cuts off ~0.5%).
    proofreader_grid_consistency_tol: float = field(default_factory=lambda: float(os.getenv("NEGELIR_PROOFREADER_GRID_CONSISTENCY_TOL", "0.05")))

    # ── Phase 6.3 — drift agent ────────────────────────────────
    #
    # Rolling Brier / log-loss windows are kept per
    # (predictor, league, market). When a window's mean metric
    # crosses the floor we emit `maint.event.v1{kind=retrain_request}`.
    # 50 samples is the legacy `drift.py` default; balances "react
    # fast to a regression" with "don't fire on a 5-game variance
    # blip". Floor 0.30 is the project's documented Brier ceiling
    # (`docs/design/TESTING_STRATEGY.md` — anything worse than 0.30
    # is "dart-throwing chimp" territory).
    drift_window_size: int = field(default_factory=lambda: int(os.getenv("NEGELIR_DRIFT_WINDOW_SIZE", "50")))
    # Phase 6.3 (Phase-6 audit F-3/F-5): the swarm `drift.v1` agent
    # trips when the rolling **mean Brier** for a (league, market)
    # bucket *exceeds* this value (lower Brier = better prediction,
    # so this is semantically a *ceiling*, not a floor). Earlier
    # drafts called this `drift_accuracy_floor`, which collided
    # with the Phase-5 accuracy-floor field of the same name and
    # silently shadowed it; the Phase-5 field (`drift_accuracy_floor`,
    # default 0.35, env `NEGELIR_DRIFT_FLOOR`) governs the legacy
    # accuracy-based detector in `ai/model/drift.py` and the
    # `TrainerReactor` debounce gate, both of which compare
    # *accuracy < floor*. Keep the two knobs distinct.
    drift_brier_ceiling: float = field(default_factory=lambda: float(os.getenv("NEGELIR_DRIFT_BRIER_CEILING", "0.30")))
    # Phase 6.3 — bound for the drift agent's per-(match, market)
    # `_pending` and `_settled` maps. Without this, predictions for
    # unsupported markets (anything other than 1X2 in v1) accumulate
    # forever because they never get scored, and the settled-set never
    # forgets a match. Default 100k allows ~5 seasons of weekly fixtures
    # for a typical league before LRU eviction kicks in; eviction is
    # silent (no proof.flag) because it is a memory bound, not a
    # correctness signal.
    drift_max_pending: int = field(default_factory=lambda: int(os.getenv("NEGELIR_DRIFT_MAX_PENDING", "100000")))
    drift_max_settled: int = field(default_factory=lambda: int(os.getenv("NEGELIR_DRIFT_MAX_SETTLED", "100000")))
    # KS-test p-value below which the input feature distribution is
    # declared non-stationary. 0.01 is conservative (only ~1% false
    # positives at steady state); raise to 0.05 to react faster.
    drift_pvalue: float = field(default_factory=lambda: float(os.getenv("NEGELIR_DRIFT_PVALUE", "0.01")))

    # ── Phase 7 — Defense agents (sec.input.v1 / sec.scrape.v1 / sec.rate.v1) ──
    #
    # Foundation knobs landed here in lockstep with the topic catalog +
    # JSON schemas; agent logic follows in Phase 7.1 / 7.2 / 7.3.
    # The §7.7 test_config_sync gate is the contract: every knob below
    # also appears in `xops/env/.env.example` and `ai/common/defaults.yaml`.
    #
    # Doctrine: `sec_input_max_len` is **bytes after UTF-8 encoding**
    # (NOT codepoints) — the byte count stresses Redis + the
    # classifier tokenizer (§7.1 length-cap binding). `sec_burst_window_ms`
    # uses `time.monotonic()`-based math in-process; only the on-the-wire
    # `produced_at` and Redis denylist TTL stamps stay wall-clock
    # (§7 monotonic-clock convention from the M2/M4 audit fix).
    #
    # The retired knob `sec_scrape_baseline_max_per_source` is INTENTIONALLY
    # ABSENT — the streaming-statistic baseline (Welford / P² / count-min
    # sketches) replaces the capped-LRU; `test_no_retired_phase7_knobs`
    # below asserts the name cannot creep back.

    # sec.input.v1 (§7.1)
    sec_input_max_len: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_MAX_LEN", "8192")))
    sec_input_gateway_max_latency_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_GATEWAY_MAX_LATENCY_MS", "10")))
    sec_input_classifier_max_latency_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_MAX_LATENCY_MS", "100")))
    sec_input_classifier_device: str = field(default_factory=lambda: os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_DEVICE", "auto"))
    sec_input_classifier_path: str = field(default_factory=lambda: os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_PATH", ""))
    sec_input_classifier_batch_enabled: str = field(default_factory=lambda: os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_BATCH_ENABLED", "auto"))
    sec_input_classifier_batch_size: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_BATCH_SIZE", "8")))
    sec_input_classifier_batch_window_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_BATCH_WINDOW_MS", "20")))
    sec_input_classifier_max_pending: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_CLASSIFIER_MAX_PENDING", "256")))
    sec_input_breaker_open_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_BREAKER_OPEN_S", "30")))
    sec_input_pattern_reload_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_PATTERN_RELOAD_S", "30")))
    # Phase 8 §8.7 — pattern_allowlist read-side cache poll interval.
    # Mirrors the §7.4 sec.config fan-out cadence (mtime-style polling
    # against `pattern_allowlist_meta.version` under REPEATABLE READ).
    sec_input_allowlist_reload_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_ALLOWLIST_RELOAD_S", "60")))
    # Phase 8 §8.16.10 — dedicated key file for allowlist fingerprint
    # HMAC (separate from the audit-log chain key). In mock profile,
    # the allowlist codec uses an in-memory fallback key when this path
    # is missing; prod requires a readable key file.
    sec_input_allowlist_hmac_key_path: str = field(default_factory=lambda: os.getenv("NEGELIR_SEC_INPUT_ALLOWLIST_HMAC_KEY_PATH", "/var/lib/negelir/secrets/allowlist_hmac.key"))
    # Max key age (days) used by rotation-policy checks in the sec
    # maintenance surface.
    sec_input_allowlist_hmac_key_max_age_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_INPUT_ALLOWLIST_HMAC_KEY_MAX_AGE_DAYS", "365")))

    # sec.quarantine.v1 envelope + storage backpressure (§7.1 + §7.5)
    sec_quarantine_ttl_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_QUARANTINE_TTL_DAYS", "30")))
    sec_quarantine_payload_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_QUARANTINE_PAYLOAD_MAX_BYTES", "65536")))
    sec_quarantine_producer_queue_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_QUARANTINE_PRODUCER_QUEUE_MAX", "1000")))
    sec_quarantine_storage_lag_alert_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_QUARANTINE_STORAGE_LAG_ALERT_MS", "5000")))

    # sec.scrape.v1 (§7.2). Streaming-statistic baseline → no per-source
    # raw-sample cap. SimHash distance threshold is bits-out-of-64.
    sec_scrape_size_delta_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_SCRAPE_SIZE_DELTA_PCT", "200.0")))
    sec_scrape_inflate_ratio_max: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_SCRAPE_INFLATE_RATIO_MAX", "50.0")))
    sec_scrape_warmup_samples: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_WARMUP_SAMPLES", "50")))
    sec_scrape_baseline_flush_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_BASELINE_FLUSH_S", "300")))
    sec_scrape_max_pending: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_MAX_PENDING", "4096")))
    # F7.3: dedicated cap for the per-source content-addressed dedup map
    # ((source, bytes_sha256) → None LRU). Distinct from _max_pending
    # which (today reserved, future async-scoring) controls memory under
    # classifier backpressure. Default matches _max_pending so behaviour
    # is unchanged at default settings; operators can now scale them
    # independently.
    sec_scrape_dedup_window: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_DEDUP_WINDOW", "4096")))
    sec_scrape_simhash_max_distance: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_SIMHASH_MAX_DISTANCE", "12")))
    sec_scrape_dom_fingerprint_max_nodes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_DOM_FINGERPRINT_MAX_NODES", "5000")))
    # F7.4: bounded ring of recent SimHash fingerprints per source.
    # Drift trips when the MIN Hamming distance to any ring member
    # exceeds sec_scrape_simhash_max_distance — not the adjacent-pair
    # distance. Tolerates legitimate A/B-test layout oscillation
    # (post-warmup) at the cost of one transient false trip when a
    # genuinely-new layout first lands.
    sec_scrape_simhash_ring_size: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_SCRAPE_SIMHASH_RING_SIZE", "8")))

    # sec.rate.v1 (§7.3). Pre-auth caps protect /v1/auth/* against
    # credential stuffing; post-auth caps are looser. IPv6 prefix
    # default is `/64` (typical end-site allocation boundary) so a
    # single IPv6 allocation cannot spray 2^64 unique buckets.
    sec_rate_pre_auth_capacity: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_PRE_AUTH_CAPACITY", "30")))
    sec_rate_pre_auth_refill_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_RATE_PRE_AUTH_REFILL_PER_S", "0.5")))
    sec_rate_post_auth_capacity: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_POST_AUTH_CAPACITY", "600")))
    sec_rate_post_auth_refill_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_RATE_POST_AUTH_REFILL_PER_S", "5.0")))
    sec_rate_bucket_idle_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_BUCKET_IDLE_TTL_S", "3600")))
    sec_rate_max_subjects: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_MAX_SUBJECTS", "100000")))
    sec_rate_ipv4_prefix: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_IPV4_PREFIX", "32")))
    sec_rate_ipv6_prefix: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_IPV6_PREFIX", "64")))
    sec_rate_trusted_proxies: str = field(default_factory=lambda: os.getenv("NEGELIR_SEC_RATE_TRUSTED_PROXIES", ""))
    sec_rate_redis_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_REDIS_TIMEOUT_MS", "50")))
    sec_rate_secondary_capacity: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_SECONDARY_CAPACITY", "300")))
    sec_rate_secondary_refill_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_RATE_SECONDARY_REFILL_PER_S", "5.0")))
    sec_rate_default_cost: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_DEFAULT_COST", "1")))
    sec_rate_eviction_rate_alert_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_RATE_EVICTION_RATE_ALERT_PER_S", "50.0")))
    sec_rate_eviction_rate_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_RATE_EVICTION_RATE_WINDOW_S", "60")))

    # Sliding-window burst detector (§7.3) — `sec.rate.v1`'s anomaly
    # path. `sec_burst_window_ms` is monotonic-clock-based.
    sec_burst_threshold: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_BURST_THRESHOLD", "100")))
    sec_burst_window_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_BURST_WINDOW_MS", "60000")))
    sec_burst_dedup_window: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_BURST_DEDUP_WINDOW", "10000")))

    # Denylist (Redis hash, sole writer = sec.rate.v1) — §7.3.
    sec_denylist_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_DENYLIST_TTL_S", "3600")))
    sec_denylist_escalation_factor: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SEC_DENYLIST_ESCALATION_FACTOR", "2.0")))
    sec_denylist_max_entries: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_DENYLIST_MAX_ENTRIES", "250000")))

    # sec.alert.v1 envelope (§7.4) — generalized debounce.
    sec_alert_debounce_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_ALERT_DEBOUNCE_TTL_S", "60")))
    sec_alert_critical_debounce_enabled: bool = field(default_factory=lambda: os.getenv(
        "NEGELIR_SEC_ALERT_CRITICAL_DEBOUNCE_ENABLED", "false"
    ).lower() in ("true", "1", "yes"))
    # F7.2: dedicated LRU cap for SecAlertDebouncer per-agent buckets.
    # Distinct from sec_rate_max_subjects (which sizes the rate agent's
    # per-subject burst-window LRU). Default 4096 — kinds × subjects in
    # the debouncer is much smaller than the rate-agent's subject space.
    sec_alert_debouncer_max_buckets: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_ALERT_DEBOUNCER_MAX_BUCKETS", "4096")))

    # qa.request.v1 — NLP-side dedup window (§7.5 binding).
    qa_request_v1_dedup_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_QA_REQUEST_V1_DEDUP_WINDOW_S", "300")))

    # ── Phase 9 §9.7 — Burst budget (shared with Go API gateway) ───────────
    # Per-subject token-bucket capacity: maximum tokens a subject can
    # accumulate while idle. Default 60. The in-process SecondaryBucket
    # (GCRA fallback tier) is constructed with these values at boot.
    api_burst_capacity: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_BURST_CAPACITY", "60")))
    # Tokens added to the bucket per second of idle time. Default 2.0.
    api_burst_refill_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_BURST_REFILL_PER_S", "2.0")))

    # ── Phase 9 §9.12 — Full API knob inventory (shared with Go API gateway) ──
    # Every key below is also in server/internal/config/config.go, ai/common/defaults.yaml,
    # and xops/env/.env.example with `# shared`. test_config_sync covers all three sides.
    api_request_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REQUEST_TIMEOUT_MS", "2500")))
    api_transit_jitter_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_TRANSIT_JITTER_MS", "100")))
    api_request_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REQUEST_MAX_BYTES", "65536")))
    qa_input_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_QA_INPUT_MAX_BYTES", "4096")))
    api_fixture_window_max_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_FIXTURE_WINDOW_MAX_DAYS", "14")))
    api_allowed_markets: str = field(default_factory=lambda: os.getenv("NEGELIR_API_ALLOWED_MARKETS", "ms,au_2.5,btts,ah_home,modal_score"))
    api_cursor_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_CURSOR_TTL_S", "1800")))
    api_idempotency_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_IDEMPOTENCY_TTL_S", "86400")))
    api_idempotency_inflight_wait_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_IDEMPOTENCY_INFLIGHT_WAIT_MS", "1500")))
    api_swr_inflight_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_SWR_INFLIGHT_MAX", "64")))
    api_cache_stale_after_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_CACHE_STALE_AFTER_S", "30")))
    api_cache_max_age_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_CACHE_MAX_AGE_S", "300")))
    api_reply_reaper_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REPLY_REAPER_S", "60")))
    api_predict_request_backlog_high: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_PREDICT_REQUEST_BACKLOG_HIGH", "5000")))
    api_max_concurrent_requests: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_MAX_CONCURRENT_REQUESTS", "5000")))
    api_response_write_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_RESPONSE_WRITE_TIMEOUT_MS", "5000")))
    api_bcrypt_cost: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_BCRYPT_COST", "12")))
    api_access_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_ACCESS_TTL_S", "900")))
    api_refresh_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REFRESH_TTL_S", "2592000")))
    api_refresh_replay_grace_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REFRESH_REPLAY_GRACE_S", "30")))
    api_revocation_set_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REVOCATION_SET_MAX", "10000")))
    api_jwt_key_poll_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_JWT_KEY_POLL_S", "10")))
    api_jwt_retired_grace_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_JWT_RETIRED_GRACE_S", "960")))
    api_jwt_clock_skew_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_JWT_CLOCK_SKEW_S", "30")))
    api_self_registration_enabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_API_SELF_REGISTRATION_ENABLED", "false").lower() in ("true", "1", "yes"))
    api_register_cap_per_subnet_per_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REGISTER_CAP_PER_SUBNET_PER_H", "20")))
    api_trusted_proxies: str = field(default_factory=lambda: os.getenv("NEGELIR_API_TRUSTED_PROXIES", ""))
    api_log_sample_pct: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_LOG_SAMPLE_PCT", "10")))
    api_tier_enforcement_enabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_API_TIER_ENFORCEMENT_ENABLED", "false").lower() in ("true", "1", "yes"))
    api_deprecation_window_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_DEPRECATION_WINDOW_DAYS", "90")))
    api_schema_version: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_SCHEMA_VERSION", "1")))
    api_slo_burn_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_SLO_BURN_WINDOW_S", "3600")))
    api_slo_burn_threshold: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_SLO_BURN_THRESHOLD", "2.0")))
    api_time_format: str = field(default_factory=lambda: os.getenv("NEGELIR_API_TIME_FORMAT", "iso8601_utc"))

    # ── Phase 9 §9.17.1 — Go runtime tuning knobs (documented mirrors) ──
    # These env vars drive the Go API server's runtime tuning (GOMEMLIMIT,
    # GOGC, HTTP timeouts, H2C listener). The Python AI layer does not use
    # them at runtime; they are mirrored here so the single-source config
    # doctrine is intact and the triangle test (test_config_sync) covers them.
    api_go_mem_limit_mib: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_GO_MEM_LIMIT_MIB", "0")))
    api_go_gc_percent: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_GO_GC_PERCENT", "50")))
    api_read_header_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_READ_HEADER_TIMEOUT_MS", "5000")))
    api_read_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_READ_TIMEOUT_MS", "10000")))
    api_write_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_WRITE_TIMEOUT_MS", "15000")))
    api_idle_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_IDLE_TIMEOUT_MS", "60000")))
    api_shutdown_grace_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_SHUTDOWN_GRACE_S", "30")))
    api_in_mesh_port: str = field(default_factory=lambda: os.getenv("NEGELIR_API_IN_MESH_PORT", "8082"))

    # ── Phase 9 §9.17.3 — Connection pool sizing (documented mirrors) ──
    # These mirror the Go-server pgxpool and go-redis/v9 knobs.  The Python
    # pipeline does not use these pools directly; the fields exist so that
    # the single-source-config doctrine (AGENTS.md Rule 1) is satisfied and
    # ``sync_test.go`` can verify every env key has a Python counterpart.
    api_pg_pool_max_conns: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_PG_POOL_MAX_CONNS", "25")))
    api_pg_replica_url: str = field(default_factory=lambda: os.getenv("NEGELIR_API_PG_REPLICA_URL", ""))
    api_pg_replica_lag_check_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_PG_REPLICA_LAG_CHECK_S", "10")))
    api_pg_replica_lag_max_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_PG_REPLICA_LAG_MAX_MS", "500")))
    api_redis_cache_pool_size: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REDIS_CACHE_POOL_SIZE", "50")))
    api_redis_bus_pool_size: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_REDIS_BUS_POOL_SIZE", "20")))

    # ── Phase 9 §9.17.4 — Resilience: circuit breakers, bulkheads, hedging, retry budgets ──
    # Documented mirrors of the Go-side knobs; code paths are Go-only.
    api_breaker_fail_ratio: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_BREAKER_FAIL_RATIO", "0.5")))
    api_breaker_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_BREAKER_WINDOW_S", "10")))
    api_breaker_min_requests: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_BREAKER_MIN_REQUESTS", "20")))
    api_breaker_open_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_BREAKER_OPEN_S", "15")))
    api_hedge_after_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_HEDGE_AFTER_MS", "200")))
    api_hedging_enabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_API_HEDGING_ENABLED", "true").lower() in ("1", "true", "yes"))
    api_hedge_budget_pct: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_HEDGE_BUDGET_PCT", "10")))
    api_retry_budget_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_RETRY_BUDGET_PER_S", "10")))
    api_retry_budget_capacity: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_RETRY_BUDGET_CAPACITY", "50")))

    # ── Phase 9 §9.17.5 — k6 bench target (documented mirror) ──
    # The k6 script reads this env var directly. The Python field mirrors
    # it here so the triangle test (test_config_sync) covers it.
    api_bench_target_rps: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_BENCH_TARGET_RPS", "200")))

    # ── Phase 9 §9.17.6 — In-process L0 LRU cache (documented mirrors;
    #    implementation is Go-only; Python mirrors exist so test_config_sync
    #    and the .env.example parity check cover these env vars end-to-end).
    api_l0_cache_max_entries: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_L0_CACHE_MAX_ENTRIES", "10000")))
    api_l0_cache_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_L0_CACHE_MAX_BYTES", "67108864")))
    api_l0_max_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_L0_MAX_TTL_S", "5")))
    api_negative_cache_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_NEGATIVE_CACHE_S", "10")))
    api_l0_refresh_max_wait_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_L0_REFRESH_MAX_WAIT_MS", "200")))
    api_l0_invalidation_lag_max_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_L0_INVALIDATION_LAG_MAX_MS", "500")))

    # ── Phase 9 §9.17.7/§9.17.8/§9.17.9 — Audit, TCP, Adaptive shedding
    #    (documented mirrors; implementation is Go-only; Python mirrors exist
    #    so test_config_sync covers these env vars end-to-end).
    api_audit_batch_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_AUDIT_BATCH_MAX", "64")))
    api_audit_batch_max_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_AUDIT_BATCH_MAX_MS", "10")))
    api_audit_chan_cap: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_AUDIT_CHAN_CAP", "4096")))
    api_audit_sample_pct_under_pressure: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_AUDIT_SAMPLE_PCT_UNDER_PRESSURE", "10")))
    api_tcp_user_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_TCP_USER_TIMEOUT_MS", "20000")))
    api_adaptive_error_rate_threshold: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_ADAPTIVE_ERROR_RATE_THRESHOLD", "0.02")))
    api_adaptive_shed_factor: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_ADAPTIVE_SHED_FACTOR", "0.5")))
    api_adaptive_shed_duration_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_ADAPTIVE_SHED_DURATION_S", "60")))
    api_priority_tier_floor: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_PRIORITY_TIER_FLOOR", "0")))
    # §9.17.10 — Observability for performance (documented mirrors; code path is Go-only).
    api_pprof_enabled_dev: bool = field(default_factory=lambda: os.getenv("NEGELIR_API_PPROF_ENABLED_DEV", "true").lower() in ("1", "true", "yes"))
    api_pprof_enabled_prod: bool = field(default_factory=lambda: os.getenv("NEGELIR_API_PPROF_ENABLED_PROD", "false").lower() in ("1", "true", "yes"))
    api_alloc_sample_rate: float = field(default_factory=lambda: float(os.getenv("NEGELIR_API_ALLOC_SAMPLE_RATE", "0.001")))
    api_pprof_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_API_PPROF_DIR", "data/api/profiles"))

    # ── Phase 8 — Self-maintenance plane (ops console + maint.event/ack) ──
    #
    # §8.1 ops console baseline knobs. The ops console is a stateless CLI
    # under ``xops/opsctl/``; it publishes ``maint.event.v1`` envelopes
    # and waits for ``maint.ack.v1`` replies up to the per-publish budget.
    # Bus-down replays land in ``opsctl_spool_dir`` and are drained by
    # ``make ops.spool-flush``. Critical-agent destructive operations
    # (scale=0 / restart of consensus / sec.rate / maint.backup) require
    # an explicit typed-token confirmation, sourced from the agent set
    # below (csv-parsed; whitespace-tolerant).
    #
    # Doctrine reminders (binding):
    #   * ``opsctl_ack_timeout_ms`` is wall-clock per the Phase 7
    #     monotonic-clock convention only inside agent code; the CLI
    #     uses wall-clock for operator-facing budgets so it matches the
    #     human's stopwatch on a stuck publish.
    #   * The ack payload caps below cap PRODUCER side (consumers
    #     publishing ``maint.ack.v1``); they do NOT cap the operator's
    #     own envelope payload.
    #   * Empty ``opsctl_audit_path`` / ``opsctl_spool_dir`` resolve to
    #     ``<data_dir>/maint/opsctl_audit.csv`` and
    #     ``<data_dir>/maint/opsctl_spool/`` respectively (see the
    #     properties of the same name).
    opsctl_ack_timeout_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_ACK_TIMEOUT_MS", "5000")))
    # Phase 8 §8.16.13 — realistic local Redis Streams latency budget used
    # by `make swarm.demo.live`. This must stay strictly below the hard
    # operator-facing ack timeout above.
    opsctl_ack_timeout_ms_live_demo: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_ACK_TIMEOUT_MS_LIVE_DEMO", "1000")))
    # Phase 9 §9.13 — base URL for the `make swarm.demo.live` API smoke test
    # (register → login → POST /v1/qa end-to-end check). Override when the
    # API runs on a non-default port or host in the local dev environment.
    api_demo_base_url: str = field(default_factory=lambda: os.getenv("NEGELIR_API_DEMO_BASE_URL", "http://localhost:8080"))
    opsctl_spool_max_entries: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_SPOOL_MAX_ENTRIES", "1024")))
    opsctl_critical_agents: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_OPSCTL_CRITICAL_AGENTS", "consensus.v1,sec.rate.v1,maint.backup.v1"
    ))
    opsctl_audit_path: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_AUDIT_PATH", ""))
    opsctl_spool_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_SPOOL_DIR", ""))
    opsctl_lock_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_LOCK_DIR", ""))
    # Re-entrancy lock: a stale lockfile (no live ``flock`` holder)
    # older than ``opsctl_ack_timeout_ms × opsctl_lock_stale_factor``
    # is reaped on the next acquire. Keeps a crashed CLI from
    # permanently blocking the same ``(kind, target)`` tuple.
    opsctl_lock_stale_factor: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_LOCK_STALE_FACTOR", "2")))
    # Phase 8 §8.16.2 — spool-flush ack reconciler. The reconciler
    # walks the audit CSV and, for every ``op=spool-flush`` row whose
    # ``received_acks < expected_acks``, alerts when the row's age
    # exceeds this threshold. Default: 24h (one operator-day).
    opsctl_spool_ack_max_wait_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_SPOOL_ACK_MAX_WAIT_H", "24")))
    # §8.14.10 spool-flush drain budget: max envelopes per flush invocation.
    # 0 = unlimited (operator override via --max-entries=0). Default 100
    # bounds wall-clock cost against a wedged bus. Partial flushes emit a
    # kind=spool_flush_partial audit row; operator re-runs to drain further.
    opsctl_spool_flush_max_per_run: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_SPOOL_FLUSH_MAX_PER_RUN", "100")))
    maint_ack_payload_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_ACK_PAYLOAD_MAX_BYTES", "4096")))
    maint_ack_reason_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_ACK_REASON_MAX_BYTES", "512")))
    maint_ack_details_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_ACK_DETAILS_MAX_BYTES", "2048")))
    # Phase 8 §8.14.4 — opsctl Redis ACL + signed envelopes.
    # ``opsctl_redis_expected_user`` is the ACL username opsctl must
    # authenticate as; ``negelir_opsctl`` is provisioned by the §2 mock
    # setup and the Phase 14 K8s Secret manifest.
    opsctl_redis_expected_user: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_REDIS_EXPECTED_USER", "negelir_opsctl"))
    # ``opsctl_require_signature`` gates envelope signing and consumer-side
    # verification. Default ``true`` in prod; set ``false`` in mock via env var.
    opsctl_require_signature: bool = field(default_factory=lambda: os.getenv(
        "NEGELIR_OPSCTL_REQUIRE_SIGNATURE", "true"
    ).lower() in ("true", "1", "yes"))
    # ``opsctl_key_path`` — path to the 32-byte operator key file (mode 0600).
    # Empty string resolves to ``~/.negelir/opsctl_key`` at call time.
    opsctl_key_path: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_KEY_PATH", ""))
    # ``opsctl_operators_file`` — path to the operator registry JSON.
    # Empty string resolves to ``infra/maint/opsctl_operators.json``.
    opsctl_operators_file: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_OPERATORS_FILE", ""))
    # ``opsctl_authz_file`` — path to the per-subcommand authz YAML.
    # Empty string resolves to ``infra/maint/opsctl_authz.yaml``.
    opsctl_authz_file: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_AUTHZ_FILE", ""))

    # ── Phase 8 §8.15.4 — HMAC key lifecycle ──────────────────────────
    # Revocation grace window: envelopes published up to this many seconds
    # BEFORE a revocation are still accepted (allows in-flight ops to land).
    # After the grace window, revoked-key envelopes are hard-rejected with
    # reason="key_revoked" + critical sec.alert.v1.
    opsctl_key_revocation_grace_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_KEY_REVOCATION_GRACE_S", "60")))
    # Maximum key age in days before rotation is overdue. A heartbeat alert
    # (sec.alert.v1{kind=opsctl_key_rotation_overdue, severity=warn}) is
    # emitted daily (debounced) per key that has exceeded this threshold.
    opsctl_key_max_age_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_KEY_MAX_AGE_DAYS", "365")))
    # Days past max_age before auto-revocation fires at the consumer side.
    # Consumer rejects with reason="key_age_exceeded" regardless of revoked_at.
    opsctl_key_revocation_grace_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_KEY_REVOCATION_GRACE_DAYS", "30")))
    # operators.json hot-reload poll interval in seconds (cache coherency).
    # Reload failure flips the consumer to fail-safe: all signatures fail.
    opsctl_operators_reload_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_OPERATORS_RELOAD_S", "60")))
    # Emergency kill-switch file path. When the file exists and its mtime is
    # within kill_switch_max_age_h hours, ALL opsctl envelopes are rejected.
    # Empty string resolves to ``infra/maint/opsctl_kill_switch`` under the
    # repo root at call time.
    opsctl_kill_switch_path: str = field(default_factory=lambda: os.getenv("NEGELIR_OPSCTL_KILL_SWITCH_PATH", ""))
    # Kill-switch becomes stale (treated as absent) after this many hours.
    opsctl_kill_switch_max_age_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_KILL_SWITCH_MAX_AGE_H", "24")))
    # Per-key token-bucket rate limit: max envelopes per minute per key_id.
    # Caps stolen-key blast radius even when signature + authz pass.
    opsctl_key_rate_limit_per_min: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_KEY_RATE_LIMIT_PER_MIN", "30")))

    # ── Phase 8 §8.2 — `maint.scaler.v1` agent ────────────────────────
    # Decision window in ms: one scale_decision per target per window.
    # Anchored on a monotonic clock (CLOCK_BOOTTIME on Linux when
    # `maint_scaler_clock_source=auto`); a wall-clock NTP step cannot
    # collapse two windows into one.
    maint_scaler_decision_window_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_DECISION_WINDOW_MS", "30000")))
    maint_scaler_clock_source: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCALER_CLOCK_SOURCE", "auto"))
    # Phase 8 §8.15.1 — suspend-detection alert threshold in seconds.
    # Heartbeat agents compute delta_s = (boottime_ns - monotonic_ns) / 1e9;
    # a step-up larger than this value within one heartbeat interval indicates
    # a container suspend just happened.  Set to 0 to disable the probe.
    maint_clock_suspend_alert_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_CLOCK_SUSPEND_ALERT_S", "30")))
    maint_scaler_max_targets: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_MAX_TARGETS", "256")))
    maint_scaler_max_replicas: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_MAX_REPLICAS", "16")))
    # Phase 8 §8.16.1 — default-policy fallback applied to any
    # registered agent that has NO explicit entry in
    # ``maint_scaler_max_replicas_overrides_csv``. Conservative-by-
    # default ceiling for unconfigured agents. Set to ``0`` (the
    # bootstrap default) to preserve legacy behavior — unconfigured
    # agents fall back to ``maint_scaler_max_replicas`` and no alert
    # is emitted. Set to >=2 to OPT IN: each first-sighting of an
    # unconfigured agent then emits a one-shot
    # ``sec.alert.v1{kind=maint_scaler_unconfigured_agent}`` plus an
    # audit ``maint.event.v1{kind=maint_scaler_default_applied}``
    # AND the per-target ceiling drops to this value (capped by
    # ``maint_scaler_max_replicas`` and ``..._global_max_replicas``).
    # Floor when enabled is 2 (1 is indistinguishable from "do not
    # scale me" and would silently freeze unconfigured agents).
    maint_scaler_default_max_replicas: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_DEFAULT_MAX_REPLICAS", "0")))
    maint_scaler_min_replicas: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_MIN_REPLICAS", "1")))
    maint_scaler_scale_up_queue_depth: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_SCALE_UP_QUEUE_DEPTH", "50")))
    maint_scaler_scale_down_queue_depth: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_SCALE_DOWN_QUEUE_DEPTH", "5")))
    maint_scaler_scale_up_head_age_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_SCALER_SCALE_UP_HEAD_AGE_S", "30")))
    maint_scaler_hysteresis_windows: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_HYSTERESIS_WINDOWS", "3")))
    maint_scaler_hysteresis_grace: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_HYSTERESIS_GRACE", "1")))
    maint_scaler_max_changes_per_window: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_MAX_CHANGES_PER_WINDOW", "4")))
    maint_scaler_manual_pin_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_MANUAL_PIN_TTL_S", "1800")))
    # Per-agent ``max_replicas`` overrides as ``"agent=N,agent2=M"``.
    # An entry trumps :attr:`maint_scaler_max_replicas` for that
    # specific target; closes the spec gap that registered agents may
    # legitimately need different ceilings (a single trainer.v1 vs a
    # fan-out predictor.elo.v1).
    maint_scaler_max_replicas_overrides_csv: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCALER_MAX_REPLICAS_OVERRIDES_CSV", ""))
    # Replica count published when the scaler reacts to a
    # ``retrain_request`` warm-up. Kept tiny by default — the trainer
    # is the action-of-record; the scaler only ensures one warm pod.
    maint_scaler_warmup_replicas: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_WARMUP_REPLICAS", "1")))
    # Phase 8 §8.14.8 — comma-separated set of agent names that manage
    # their own replica counts (self-scaling targets). The auto-scaler
    # refuses to emit ``scale_decision`` for these targets; instead it
    # emits ``scale_throttled{reason=self_scaling_target}`` every tick
    # AND a one-shot ``sec.alert.v1{kind=scaler_target_forbidden,
    # severity=warn}`` (debounced per target per process). On
    # ``retrain_request``, the scaler emits the softer
    # ``trainer_warmup_hint`` advisory instead of ``scale_decision``.
    # Default: ``trainer.v1`` — the trainer pod is the sole writer of
    # its own replica count; the scaler must not race it.
    maint_scaler_self_scaling_targets: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCALER_SELF_SCALING_TARGETS", "trainer.v1"))
    # Phase 8 §8.15.9 — scheduler noise-window suppression.
    # JSON-encoded list of 5-field UTC cron expressions (minute hour dom
    # month dow) that mark known high-load periods where the §8.3 backup
    # agent inflates PG / IO / network signals. During an active window the
    # scaler suppresses load-driven scale decisions (lag_high, cpu_high,
    # p95_high, dlq_depth_high) and emits scale_throttled{reason=
    # noise_window_active}. Emergency decisions (vram_budget_exceeded,
    # manual_pin, retrain_request_warmup) always fire. Empty list disables
    # suppression entirely. Uses the §8.3 stdlib cron evaluator; the active
    # check tests whether the current UTC hour matches the cron's hour set
    # (the minute field is ignored — the full hour block is suppressed).
    # Default covers the §8.3 nightly backup window (03:00-05:59) and
    # Sunday cold-verify (05:00 on DOW=0).
    maint_scaler_noise_windows: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCALER_NOISE_WINDOWS", '["0 3-5 * * *","0 5 * * 0"]'))
    # Runtime selector for the scaler's ``RuntimeController``. ``none``
    # makes the scaler a pure observer (decisions emit; runtime calls
    # are skipped). ``compose`` invokes ``docker compose --scale`` via
    # subprocess. ``k8s`` is reserved for Phase 14 — boot raises until
    # the K8s controller lands.
    maint_runtime: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_RUNTIME", "none"))
    # Compose file used by ``ComposeController`` when
    # ``maint_runtime=compose``. Boot validation refuses to start if
    # the file does not exist on disk.
    maint_scaler_compose_file: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCALER_COMPOSE_FILE", "docker-compose.yml"))
    # Subprocess timeout for any runtime call (compose / k8s patch).
    maint_scaler_runtime_timeout_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_SCALER_RUNTIME_TIMEOUT_S", "30")))
    # Hard global cap across every target — defends against runaway
    # auto-scale during a self-amplifying lag storm. The per-target
    # cap (``maint_scaler_max_replicas`` + overrides) is applied
    # first; this cap is enforced on the *sum* of desired replicas
    # before issuing the runtime call.
    maint_scaler_global_max_replicas: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_GLOBAL_MAX_REPLICAS", "64")))
    # Minimum interval between two scale_decision events for the SAME
    # target across distinct decision windows. Lower than this and
    # the candidate decision is coalesced (latest-wins, no runtime
    # call) and emits ``scale_throttled{reason=min_decision_interval}``.
    # Wall-clock-of-monotonic, set in seconds — defaults to 90s per
    # ROADMAP §8.2 binding.
    maint_scaler_min_decision_interval_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_SCALER_MIN_DECISION_INTERVAL_S", "90")))
    # Headroom (MB) subtracted from total per-host VRAM before the
    # scaler computes its budget. Stops the scaler from packing pods
    # so densely that any one pod's transient spike OOMs the host.
    maint_scaler_vram_headroom_mb: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_VRAM_HEADROOM_MB", "1024")))
    # Phase 8 §8.16.8 — VRAM-budget pessimism factor for unknown-footprint
    # agents. When GPU is the active device and the fraction of VRAM already
    # committed exceeds this value, scale-up for an agent that has never
    # emitted model_registered is refused with reason=vram_footprint_unknown.
    # Below the threshold the unknown agent is admitted on the legacy
    # predictor_max_vram_mb default.
    maint_scaler_vram_pessimistic_threshold_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_SCALER_VRAM_PESSIMISTIC_THRESHOLD_PCT", "0.6")))
    # Phase 8 §8.16.8 — CPU-class scale-up budget: fraction of total detected
    # cores per host that CPU-class (device_class=cpu) replicas may collectively
    # consume. Each CPU-class replica counts as 1 core. Scale-up that would push
    # aggregate CPU-class replicas past budget×cores is refused.
    # No-op pre-Phase 14 (single-host compose mode); active under K8s.
    maint_scaler_cpu_budget_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_SCALER_CPU_BUDGET_PCT", "0.8")))
    # Phase 8 §8.2 A1 — scale-down grace: number of consecutive
    # decision windows whose smoothed signals must remain below the
    # scale-down threshold before the supervisor emits a scale-down.
    # Stops a single quiet window from yanking replicas away while a
    # bursty workload is mid-spike. Set to 0 to disable the grace
    # gate (legacy behaviour).
    maint_scaler_scale_down_grace_windows: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_SCALE_DOWN_GRACE_WINDOWS", "2")))
    # Phase 8 §8.2 A1 — Welford rolling-sketch retention: number of
    # most-recent samples per signal whose mean+variance is used in
    # the decision function. ``maint_scaler_signal_window_samples=0``
    # falls back to instantaneous (last sample) values.
    maint_scaler_signal_window_samples: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_SIGNAL_WINDOW_SAMPLES", "5")))
    # Phase 8 §8.2 A2 — load-driven clamp formula: desired_replicas =
    # clamp(min, ceil(observed_load / target_load_per_replica), max).
    # ``observed_load`` is the smoothed queue_depth (see Welford).
    # 0 disables the clamp formula and reverts to the legacy ±1-step
    # decision (kept for forward compatibility with operators who
    # haven't tuned the per-replica target yet).
    maint_scaler_target_load_per_replica: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_TARGET_LOAD_PER_REPLICA", "50")))
    # Phase 8 §8.2 A2 — cap on how many replicas the clamp formula
    # may add or remove in a single decision window. Defends against
    # a Welford-window cold-start where ``observed_load`` jumps from
    # 0 to a large value and would otherwise scale from 1 → N in one
    # tick. Default 1 preserves the legacy step magnitude.
    maint_scaler_max_step_per_window: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_MAX_STEP_PER_WINDOW", "1")))
    # Phase 8 §8.2 — observability: histogram bucket boundaries for
    # ``maint_scaler_runtime_call_seconds`` (the wall-clock duration
    # of every ``RuntimeController.apply`` call). CSV of strictly
    # positive floats in seconds; the parser sorts ascending and
    # de-duplicates. The default mirrors the prometheus default
    # latency ladder (5ms..10s) which covers both the noop path
    # (~µs) and a slow ``docker compose --scale`` (~seconds).
    maint_scaler_runtime_histogram_buckets: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCALER_RUNTIME_HISTOGRAM_BUCKETS", "0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0"))
    # Phase 8 §8.9 DoD — bounded global decision history. The scaler
    # keeps an insertion-ordered map of the most recent N
    # ``scale_decision`` events (keyed by ``decision_window_id``).
    # Oldest entries are evicted when the cap is hit (LRU by
    # insertion order). Default 1024 holds ~14h of decisions at the
    # default 30-second window cadence across a 256-target roster.
    maint_scaler_history_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCALER_HISTORY_MAX", "1024")))
    # Phase 8 §8.9 DoD — leader-lease duration for maint-plane agents.
    # When the K8s coordination API is unreachable, the in-memory
    # :class:`~swarm.sdk.leader.ControllableK8sLeader` / Phase 14 real
    # driver expire the lease after this many seconds.  A losing pod
    # transitions to observer mode (``is_leader()`` returns False) no
    # later than ``maint_leader_lease_duration_s`` after the last
    # successful renewal.  Mirrors the ``leaseDurationSeconds`` field
    # on the ``coordination.k8s.io/v1.Lease`` object (Phase 14).
    maint_leader_lease_duration_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_LEADER_LEASE_DURATION_S", "15")))

    # ── Phase 8 §8.5 — `maint.dlq.v1` supervisor ─────────────────────
    maint_dlq_per_topic_quota: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_PER_TOPIC_QUOTA", "100")))
    maint_dlq_replay_backoff_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_REPLAY_BACKOFF_S", "60")))
    maint_dlq_backoff_lru: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_BACKOFF_LRU", "1024")))
    # CSV allow-list of replayable DLQ topics (e.g.
    # ``"predict.vote.dlq,predict.final.dlq"``). Empty = allow every
    # topic *not* in :data:`RECURSION_DENY_SET`. Sec/PII DLQs are
    # never automatically replayable; this is the operator surface
    # for the rest.
    maint_dlq_replay_topics_allow_csv: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_DLQ_REPLAY_TOPICS_ALLOW_CSV", ""))
    # Phase 8.16.7 — operator-attested exceptions to replay-policy
    # sensitive-prefix denial. CSV of full DLQ topic names.
    _maint_dlq_replay_allow_overrides_raw: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_DLQ_REPLAY_ALLOW_OVERRIDES", ""))

    @property
    def maint_dlq_replay_allow_overrides(self) -> list[str]:
        """Attested replay exceptions as an ordered list."""
        return [
            tok.strip()
            for tok in self._maint_dlq_replay_allow_overrides_raw.split(",")
            if tok.strip()
        ]

    # Operator-driven replays a single ``(topic, request_id)`` may
    # incur before escalation. Default 2 → 1st + 2nd visit replay,
    # 3rd visit emits ``dlq_escalated`` and refuses further replays
    # for that request.
    maint_dlq_visit_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_VISIT_MAX", "2")))
    # Per-topic token-bucket cap on replay attempts per minute. Caps
    # a poisoned-message storm from being thrashed against a still-
    # broken consumer (§8.5 binding).
    maint_dlq_per_topic_max_per_min: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_PER_TOPIC_MAX_PER_MIN", "60")))
    # LRU cap on the ``(topic, request_id) → visit_count`` map.
    # Bounded state per the §8.9 DoD.
    maint_dlq_visit_lru: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_VISIT_LRU", "4096")))
    # Phase 8 §8.5 C1 — periodic-tick budget across all active DLQ
    # topics (round-robin fairness). Per-tick total replays is
    # ``max(1, maint_dlq_max_replays_per_tick // len(active_topics))``
    # per topic, so a single hot topic cannot starve the others.
    maint_dlq_max_replays_per_tick: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_MAX_REPLAYS_PER_TICK", "50")))
    # Phase 8 §8.5 C2 — poison-pattern detection. If ≥
    # ``maint_dlq_consumer_broken_threshold`` distinct request_ids
    # escalate on the same DLQ topic within
    # ``maint_dlq_consumer_broken_window_s`` seconds, the supervisor
    # freezes that topic (refusing further dlq_replay requests) and
    # emits ``sec.alert.v1{kind=consumer_likely_broken, severity=error}``.
    # Operator lifts the freeze via ``ops.dlq-resume --topic <t>``.
    maint_dlq_consumer_broken_threshold: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_CONSUMER_BROKEN_THRESHOLD", "5")))
    maint_dlq_consumer_broken_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_CONSUMER_BROKEN_WINDOW_S", "600")))
    # Phase 8 §8.5 backlog-pressure damping: per-topic DLQ depth
    # threshold above which the supervisor emits a debounced
    # ``sec.alert.v1{kind=dlq_backlog_high}`` and quarters that
    # topic's per-tick replay budget until depth falls below half
    # the original observed depth.
    maint_dlq_backlog_alert: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_BACKLOG_ALERT", "1000")))
    # Phase 8 §8.9 DoD — bounded in-memory topic-state map.
    # ``_state`` is capped at this value with insertion-order LRU
    # eviction. Default 100 000 covers large-scale deployments with
    # thousands of DLQ topic variants. Cap-pressure alert fires when
    # the evicted entry is younger than
    # ``maint_dlq_replay_backoff_s × maint_dlq_backoff_factor × 3``.
    maint_dlq_state_max: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_STATE_MAX", "100000")))
    # Exponential-backoff multiplier used by the DLQ supervisor for
    # cap-pressure evaluation (also referenced by the escalation
    # window calculation). Default 2 matches the §8.5 "double the
    # backoff window" pattern.
    maint_dlq_backoff_factor: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_BACKOFF_FACTOR", "2")))
    # Phase 8 §8.9 DoD — per-topic per-second replay rate cap.
    # Enforced on both the operator-driven handle() path and the
    # periodic tick() scheduler. Default 10 rps per topic; values ≥ 1.
    maint_dlq_replay_rps: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_DLQ_REPLAY_RPS", "10")))

    # ── Phase 8 §8.6 — `maint.schema.v1` sentinel ────────────────────
    maint_schema_sample_rate_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_SCHEMA_SAMPLE_RATE_PER_S", "5")))
    maint_schema_burst: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCHEMA_BURST", "10")))
    maint_schema_drift_debounce_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCHEMA_DRIFT_DEBOUNCE_S", "60")))
    maint_schema_drift_lru: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCHEMA_DRIFT_LRU", "512")))
    # Phase 8 §8.6 Detector B — cadence for the PG-column-vs-migration
    # comparison. Default 1h; lower bound 60s (ROADMAP §8.6 binding
    # — the crawl runs information_schema.columns once per tick and
    # is cheap, but cadence below 60s adds noise without recall gain).
    maint_schema_pg_check_interval_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCHEMA_PG_CHECK_INTERVAL_S", "3600")))
    # Phase 8 §8.6 binding boundary — auto-apply migrations is
    # OUT OF SCOPE for v1. The sentinel is detect-only; humans (or
    # the Phase 17 patcher under `migration` scope) drive the fix.
    # This knob exists for forward compatibility only: when set to
    # ``true`` the schema sentinel logs a warning at boot AND emits
    # a one-shot ``sec.alert.v1{kind=schema_auto_apply_misconfigured,
    # severity=warn}``. No `psql -f migrations/NNN_*.sql` code path
    # exists in v1; the AST boundary test in
    # ``ai/swarm/agents/maint/tests/test_schema_auto_apply_boundary.py``
    # locks this so a future patch wiring auto-apply gets caught.
    maint_schema_auto_apply_enabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_SCHEMA_AUTO_APPLY_ENABLED", "false").lower() in ("1", "true", "yes"))
    # Phase 8 §8.14.7 — hard per-process cross-topic cap on the total
    # validation rate.  Prevents a sample_rate=1.0 misconfig from
    # burning CPU and starving the agent heartbeat (self-DoS guard).
    # Over-budget validates are silently dropped and counted in the
    # per-topic drop tracker; a debounced sec.alert is emitted when
    # the drop rate exceeds 10 % of attempted over a 60 s window.
    # Boundary cap: value MUST be ≤ 500 (boot-validated;
    # fail_safe_validate_rps_cap_exceeded on larger values).
    maint_schema_validate_max_rps: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCHEMA_VALIDATE_MAX_RPS", "50")))

    # ── Phase 8 §8.7 + §8.8 — `maint.sec.v1` agent ───────────────────
    maint_sec_pattern_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SEC_PATTERN_TTL_S", "604800")))
    maint_sec_pattern_promote_threshold: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SEC_PATTERN_PROMOTE_THRESHOLD", "1")))
    # Days before an un-promoted `pending` row is pruned from the
    # pattern_allowlist table. Bounds growth when operators never
    # confirm a FP (e.g. noise generated by a transient rule hit).
    maint_sec_pattern_pending_ttl_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SEC_PATTERN_PENDING_TTL_DAYS", "30")))
    # Formal Phase 8 DoD name for the pattern_allowlist pending-row TTL
    # (same semantic as maint_sec_pattern_pending_ttl_days; canonical name
    # required by the triangle-test bullet).  Default 30 days.
    maint_sec_allowlist_pending_ttl_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SEC_ALLOWLIST_PENDING_TTL_DAYS", "30")))
    maint_sec_request_lru: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SEC_REQUEST_LRU", "2048")))
    # Phase 8 §8.8 hysteresis: minimum seconds between two
    # ``denylist_decimate_now`` runs (global; the denylist zset is
    # one shared resource). A second decimate inside the window is
    # acked ``accepted=true, reason="hysteresis_throttled"`` and
    # emits ``denylist_decimate_throttled``.
    maint_sec_decimate_min_interval_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SEC_DECIMATE_MIN_INTERVAL_S", "300")))

    # ── Phase 8 §8.10 — broadcast pause ──────────────────────────────
    maint_pause_default_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_PAUSE_DEFAULT_TTL_S", "600")))
    # Hard upper-bound on any operator-specified pause TTL. Operators
    # cannot request a pause longer than this; the agent caps the TTL
    # and emits ``kind=maint_pause_ttl_capped`` if the request exceeds it.
    # Default 86400s (24h) — prevents accidentally indefinite pauses.
    maint_pause_max_ttl_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_PAUSE_MAX_TTL_S", "86400")))
    maint_silence_dedup_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SILENCE_DEDUP_S", "300")))
    # Phase 8 §8.16 D2 — dead-mans-switch.
    # If no maint.event.v1 message has been observed for this many
    # hours AND swarm uptime exceeds ``maint_silence_warmup_s``,
    # emit ``sec.alert.v1{kind=maint_silence_alert, severity=critical}``.
    maint_silence_alert_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SILENCE_ALERT_H", "24")))
    maint_silence_warmup_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SILENCE_WARMUP_S", "3600")))
    # Self-DLQ depth threshold per maint.* agent. When an agent's
    # own ``<id>.dlq`` depth exceeds this, the dead-mans-switch
    # flips that agent's PauseState.self_isolated to True (§8.13.5
    # idempotency matrix; agent then refuses pause until an
    # operator explicitly resumes it).
    maint_self_dlq_alert: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SELF_DLQ_ALERT", "100")))
    # Growth-rate self-throttle (§8.11): if the agent's own DLQ depth
    # grows by more than this many entries per minute, the agent halves
    # its emit rate (token-bucket on its own producer side) until growth
    # is non-positive for ``maint_self_dlq_throttle_recovery_s`` seconds.
    # Distinct from the absolute-depth ``maint_self_dlq_alert`` above.
    maint_self_dlq_growth_alert: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SELF_DLQ_GROWTH_ALERT", "50")))
    # How long (seconds) growth must remain non-positive before the
    # per-agent DLQ self-throttle lifts (default 120 s = 2 minutes).
    maint_self_dlq_throttle_recovery_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SELF_DLQ_THROTTLE_RECOVERY_S", "120")))

    # ── Phase 8 §8.11 — consumer-lag watchdog ────────────────────────
    # Lag threshold (ms) that triggers tier-1 shedding after the alert
    # window has elapsed.  Tier 2 = 15 000ms, Tier 3 = 60 000ms.
    maint_plane_lag_alert_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_PLANE_LAG_ALERT_MS", "5000")))
    # Lag must exceed the threshold for this many seconds before tier-1 fires.
    maint_plane_lag_alert_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_PLANE_LAG_ALERT_WINDOW_S", "60")))
    # Symmetric sec-plane lag watchdog (§8.16.11) for sec.alert.v1 consumers.
    sec_plane_lag_alert_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_PLANE_LAG_ALERT_MS", "5000")))
    sec_plane_lag_alert_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SEC_PLANE_LAG_ALERT_WINDOW_S", "60")))
    # Lag must be below 1s for this many seconds before recovery fires.
    maint_plane_recovery_window_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_PLANE_RECOVERY_WINDOW_S", "120")))

    # ── Phase 8 §8.9 — per-agent bus circuit-breaker ─────────────────
    # Consecutive publish failures before the breaker opens (bus_degraded).
    maint_bus_fail_threshold: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BUS_FAIL_THRESHOLD", "3")))
    # Time window (seconds) within which consecutive failures must occur
    # for the breaker to open.  A failure outside this window resets the
    # streak counter.  Default 30s per §8.11 spec.
    maint_bus_fail_window_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BUS_FAIL_WINDOW_S", "30.0")))
    # Per-agent spool cap (entries).  Oldest entries are NOT evicted —
    # new writes are refused when the cap is reached.
    maint_bus_spool_max_entries: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BUS_SPOOL_MAX_ENTRIES", "1024")))
    # Root directory for per-agent spools (one sub-dir per agent name).
    maint_agent_spool_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_AGENT_SPOOL_DIR", "data/maint/agent_spool"))
    # Cap on entries stored per agent in its per-agent sub-spool under
    # ``maint_agent_spool_dir``. Distinct from ``maint_bus_spool_max_entries``
    # (the bus circuit-breaker spool cap). New writes are refused when
    # the cap is reached; oldest entries are NOT evicted.
    maint_agent_spool_max_entries: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_AGENT_SPOOL_MAX_ENTRIES", "512")))

    # ── Phase 8 §8.11 — three-tier backpressure ──────────────────────
    maint_backpressure_yellow_factor: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_YELLOW_FACTOR", "4.0")))
    maint_backpressure_yellow_queue_depth: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKPRESSURE_YELLOW_QUEUE_DEPTH", "200")))
    maint_backpressure_yellow_head_age_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_YELLOW_HEAD_AGE_S", "60")))
    maint_backpressure_yellow_storage_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_YELLOW_STORAGE_PCT", "75")))
    maint_backpressure_yellow_error_rate_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_YELLOW_ERROR_RATE_PER_S", "1")))
    maint_backpressure_red_queue_depth: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKPRESSURE_RED_QUEUE_DEPTH", "1000")))
    maint_backpressure_red_head_age_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_RED_HEAD_AGE_S", "300")))
    maint_backpressure_red_storage_pct: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_RED_STORAGE_PCT", "92")))
    maint_backpressure_red_error_rate_per_s: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKPRESSURE_RED_ERROR_RATE_PER_S", "10")))

    # ── Phase 8 §8.13.2 — cumulative `data/maint/` storage cap ────────
    # Total budget across every per-subdir spool / audit / ledger
    # under ``data/maint/``. The per-subdir caps that already exist
    # (e.g. ``opsctl_spool_max_entries``) are individual; this is the
    # single rollup that prevents one runaway producer from
    # filling the disk regardless of which subdir it touches.
    # 80% → warn alert (debounced 1h); 100% → error alert + spool
    # writes refuse; usage must drop below 70% before writes resume
    # (single hysteresis band, prevents thrash). 0 = disabled.
    maint_storage_total_max_mb: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_STORAGE_TOTAL_MAX_MB", "512")))

    # ── Phase 8 §8.13.3 — spool entry max age ───────────────────────
    # Spool entries (both opsctl_spool and agent_spool) older than
    # this many hours are pruned on every flush attempt. Pruned entries
    # emit maint.event.v1{kind=spool_entry_aged_out} (audit) and
    # sec.alert.v1{kind=spool_entry_aged_out, severity=warn} (debounced
    # per agent). Default 168h = 7d. 0 = disabled (no pruning).
    maint_spool_entry_max_age_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SPOOL_ENTRY_MAX_AGE_H", "168")))

    # ── Phase 8 §8.13.3 — spool retired-kind floor ───────────────────
    # Spool entries whose envelope schema_version is below this value
    # are quarantined to spool_dir/.retired/ on flush (same path as
    # entries with a kind no longer in KNOWN_MAINT_EVENT_KINDS). 1 =
    # accept all current schema versions; bump only when a breaking
    # schema change is deployed.
    swarm_min_supported_schema_version: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SWARM_MIN_SUPPORTED_SCHEMA_VERSION", "1")))

    # ── Phase 8 §8.15.3 — advisory-lock hold-time guard ──────────────
    # Wall-clock cap on how long a Postgres advisory lock taken via
    # ``xops.maint.advisory_lock.BoundLock`` may stay acquired before
    # the context manager fires a debounced
    # ``sec.alert.v1{kind=maint_advisory_lock_held_long, severity=warn}``
    # on release. Detects accidental long transactions inside the
    # critical section. Generous default (5s); 0 disables.
    maint_advisory_lock_max_hold_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_ADVISORY_LOCK_MAX_HOLD_MS", "5000")))

    # ── Phase 8 §8.14 — audit log ────────────────────────────────────
    maint_audit_hmac_key_b64: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_AUDIT_HMAC_KEY_B64", ""))
    maint_audit_partition_retention_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_AUDIT_PARTITION_RETENTION_DAYS", "365")))

    # ── Phase 8 §8.15.7 — opsctl_audit.csv hash-chain HMAC ─────────────
    # Path to the 32-byte HMAC-SHA256 key file used by the opsctl_audit.csv
    # integrity chain.  Mode 0400, owned by the agent process user.
    # Empty → no HMAC chain (test/dev only — set in prod).
    audit_chain_hmac_key_path: str = field(default_factory=lambda: os.getenv("NEGELIR_AUDIT_CHAIN_HMAC_KEY_PATH", "/var/lib/negelir/secrets/audit_chain.key"))
    # Maximum size of opsctl_audit.csv before rotation (bytes).
    # When the active file grows past this, it is renamed to
    # opsctl_audit.csv.1 (et seq.) and a fresh file is started.
    # The chain continues across rotation: the new file's genesis
    # prev_hmac = last rotated file's row_hmac.  Default 10 MB.
    opsctl_audit_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_OPSCTL_AUDIT_MAX_BYTES", str(10 * 1024 * 1024))))

    # ── Phase 8 §8.15.5 — per-row size cap + per-kind details budget ─
    # Hard per-row cap for the maint_audit_log ``payload`` JSONB column
    # (UTF-8 JSON bytes).  Enforced by the §8.14.1 BEFORE INSERT trigger
    # backstop AND by the producer-side helper in swarm.sdk.maint_audit.
    # Default 16384 (16 KB) keeps rows toast-friendly and autovacuum-safe.
    maint_audit_row_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_AUDIT_ROW_MAX_BYTES", "16384")))
    # Per-kind soft fence (JSON dict, kind → int bytes).  Producer-side
    # cap applied BEFORE emit by MaintEvent._make().  Keys are
    # maint.event.v1 kind strings; "default" key is the fallback for
    # unlisted kinds.  Values must be ≤ maint_audit_row_max_bytes.
    # Example override: '{"dlq_escalated": 4096}'.
    maint_audit_per_kind_details_max_bytes: str = field(
        default_factory=lambda: os.getenv(
            "NEGELIR_MAINT_AUDIT_PER_KIND_DETAILS_MAX_BYTES",
            '{"dlq_escalated": 8192, "schema_drift_detected": 4096,'
            ' "backup_dump_file_corrupted": 8192, "default": 2048}',
        )
    )

    # ── Phase 8 §8.3 — backup agent ──────────────────────────────────
    # Cron expression (5-field, UTC) that fires the nightly backup
    # state machine. Operator typos are caught by parse_cron at boot.
    maint_backup_cron: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_CRON", "0 3 * * *"))
    # Where dump artefacts + audit.csv live. Created on demand.
    maint_backup_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_DIR", "./data/backups"))
    # Daily-grain retention. Older daily dumps are pruned; weekly
    # dumps (Sunday) are kept for `retention_weeks` instead.
    maint_backup_retention_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_RETENTION_DAYS", "14")))
    maint_backup_retention_weeks: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_RETENTION_WEEKS", "4")))
    # Safety floor — when true, every emit carries dry_run=true and
    # NO destructive prune is executed (would_delete_count instead).
    # Defaults to true when NEGELIR_PROFILE is unset or "mock"
    # (dev/CI safety net); false for production.
    # Note: uses (os.getenv("NEGELIR_PROFILE") or "mock") so the
    # _GETENV_DEFAULT_RE duplicate-key test ignores this nested read.
    maint_backup_dry_run: bool = field(default_factory=lambda: os.getenv(
        "NEGELIR_MAINT_BACKUP_DRY_RUN",
        "true" if (os.getenv("NEGELIR_PROFILE") or "mock") == "mock" else "false",
    ).lower() in ("1", "true", "yes"))
    # Disk-pressure guard — refuse to start a dump if free space <
    # max(2*last_dump_size, min_free_gb*1GB).
    maint_backup_min_free_gb: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MIN_FREE_GB", "5")))
    # Catch-up: at most one make-up run if monotonic delta vs last fire
    # exceeds this many hours; otherwise we wait for the next cron tick.
    maint_backup_max_skew_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MAX_SKEW_H", "36")))
    # `pii_erased` / `quarantine_pruned` are DML, no Postgres dump
    # required — but we still gate on having a recent successful dump
    # (within this many hours) before the destructive prune phase.
    maint_backup_age_alert_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_AGE_ALERT_H", "30")))
    # Backwards wall-clock step bigger than this (seconds) → emit
    # sec.alert.v1{kind=backup_clock_skew, severity=error} and skip
    # this fire (refuse-to-start safety floor).
    maint_backup_clock_step_back_alert_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_CLOCK_STEP_BACK_ALERT_S", "300")))
    # Forward wall-clock leap (last_fire → now) bigger than this (hours)
    # → log a warn-level operator-visibility marker AND tag the next
    # `backup_started` event with `forward_leap_h: float`. The catch-up
    # policy still handles the missed window itself; this is purely the
    # early-warning surface (`scope=forward` per ROADMAP §8.3 prose).
    # The corresponding `sec.alert.v1{kind=backup_clock_skew, severity=warn,
    # scope=forward}` emission is deferred until the closed sec.alert.v1
    # source enum is extended to admit `maint.backup.v1`.
    maint_backup_clock_step_forward_alert_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_CLOCK_STEP_FORWARD_ALERT_H", "24")))
    # pg_dump parallelism (-j flag); 1 disables parallel mode.
    maint_backup_pg_jobs: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PG_JOBS", "2")))
    # ROADMAP §8.9 binding (fail_safe_pg_conn_limit_too_low): minimum
    # Postgres role connection limit accepted at agent startup.  0 means
    # "auto-derive": the agent requires at least pg_jobs + 1 (N parallel
    # workers + 1 coordinator connection).  Set an explicit positive value
    # to enforce a higher floor (e.g. pg_jobs + application pool headroom).
    maint_backup_pg_conn_limit: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PG_CONN_LIMIT", "0")))
    # ROADMAP §8.16.3 binding (``fail_safe_prune_order_invalid``): boot
    # validation in :class:`xops.maint.prune_order.PruneOrderValidator`
    # asserts that the declared :data:`PRUNE_ORDER` is a valid topological
    # sort of the live PG FK graph. Drift → refuse-to-start + critical alert.
    # No runtime knob; presence here documents the doctrine name so the
    # §7.7-style triangle test can assert it is referenced in config comments.

    # DELETE batch size for the destructive prune phase. Bounded so a
    # single cron run cannot hold a long-lived row-lock cascade.
    maint_backup_prune_batch: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PRUNE_BATCH", "10000")))
    # Maximum milliseconds a single prune batch may hold a table lock.
    # Each DELETE batch is constrained so that
    # (rows_in_batch × cost_per_row_ms) <= this budget.
    # Default 500ms matches the §8.9 DoD lock-hold-time requirement.
    maint_backup_prune_max_lock_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PRUNE_MAX_LOCK_MS", "500")))
    # ROADMAP §8.3 TTL prune retention windows. Each is a calendar-day
    # cap; rows whose `created_at` (or `expires_at` for the allowlist)
    # falls outside the window are pruned by the nightly maint.backup.v1
    # tick. The audit-log retention is intentionally the longest — the
    # operator trail is the highest-value record on disk.
    maint_schema_snapshot_retention_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_SCHEMA_SNAPSHOT_RETENTION_DAYS", "90")))
    swarm_dlq_pg_retention_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SWARM_DLQ_PG_RETENTION_DAYS", "14")))
    maint_audit_retention_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_AUDIT_RETENTION_DAYS", "365")))
    # Per-kind retention overrides (JSON dict, str → int days). Keys are
    # ``maint.event.v1`` kind strings; values override the global
    # ``maint_audit_retention_days`` for that kind. Default ships the
    # ROADMAP §8.9 right-to-erasure requirement: ``pii_erased`` rows
    # are kept for 7 years (2555 days) as breach-evidence records.
    # Example: '{"pii_erased": 2555, "backup_age_alert": 90}'.
    maint_audit_retention_days_overrides: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_AUDIT_RETENTION_DAYS_OVERRIDES", '{"pii_erased": 2555}'))
    # Live `pg_dump` DSN — empty string means "no live driver wired"
    # (the in-memory shim is used; refused at agent boot in production
    # profile by the swarm bootstrap).
    maint_backup_pg_dsn: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_PG_DSN", ""))
    # Path to the `age` recipients file (one DR-class public key per
    # line). Required when the live `LocalPgDumpExecutor` is wired.
    maint_backup_age_recipients_file: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_AGE_RECIPIENTS_FILE", ""))
    # Directory of versioned recipient public keys (``keys.vN.age.pub``
    # + optional ``keys.vN.recipients.txt``). Empty string disables
    # encryption-at-rest. ROADMAP §8.3 binding: when ``profile=prod``
    # AND ``maint_runtime != none``, an unset key dir AND unset
    # recipients file refuses-to-start (``fail_safe_no_encryption_in_prod``).
    # The dir-format full implementation lands in a follow-up bullet;
    # this knob exists today so the prod-profile refusal can gate on
    # both surfaces uniformly.
    maint_backup_encryption_key_dir: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_ENCRYPTION_KEY_DIR", ""))
    # Minimum DR-class recipients required in each `keys.vN.recipients.txt`
    # under `maint_backup_encryption_key_dir`. Default `2` matches the
    # ROADMAP §8.3 prod binding ("at least 2 in prod") — a single DR
    # recipient is a single point of disaster-recovery failure. Mock
    # / dev stacks override down to `1` via env when running the
    # encryption surface end-to-end without an off-cluster custodian.
    maint_backup_min_dr_recipients: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MIN_DR_RECIPIENTS", "2")))
    # Path to the `age` identity file used by the restore-verifier to
    # decrypt dumps in the ephemeral scratch container.
    maint_backup_age_identity_file: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_AGE_IDENTITY_FILE", ""))
    # Pinned Postgres image for the restore-verifier scratch container.
    # Must NOT be `*-latest` (CLAUDE.md doctrine: pin specific tags).
    maint_backup_verify_pg_image: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_VERIFY_PG_IMAGE", "postgres:16-alpine"))
    # §8.14.9 nice level for pg_dump subprocess. Default 10 (lower CPU
    # priority than interactive queries). Set 0 to disable nice wrapping
    # (mock profile; dedicated-PG deployments). Bounded 0–19 (UNIX nice).
    maint_backup_pg_dump_nice_level: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PG_DUMP_NICE_LEVEL", "10")))
    # §8.14.9 ionice wrapping for pg_dump on Linux: best-effort I/O class
    # (-c 2) at lowest priority (-n 7). Default true. Ignored on non-Linux.
    maint_backup_pg_dump_ionice: bool = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_PG_DUMP_IONICE", "true").lower() not in ("false", "0", "no"))
    # Restore-verify mode (ROADMAP §8.3 escape hatch). `full` (default)
    # runs the complete `pg_restore` + verify.sql suite; `toc_only` runs
    # only `pg_restore --list` to validate the dump's table-of-contents
    # without restoring rows — forward escape hatch for very-large-DB ops
    # where a nightly full restore exceeds the maintenance window. The
    # weekly cold-verify still runs the full suite regardless. Boot
    # validation in `MaintBackupAgent` refuses any other value.
    maint_backup_verify_mode: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_VERIFY_MODE", "full"))
    # ROADMAP §8.13.4 restore version-invariant: maximum schema-version gap
    # (in_tree_max_version - manifest.max_version) before restore-verify
    # refuses with backup_dump_too_old + sec.alert.v1{severity=error}.
    # Default 5 covers ~quarterly migration cadence (≤5 migrations per
    # quarter). Operator must escalate to a manual restore using the
    # historical commit when the gap exceeds this.
    maint_backup_max_version_gap: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MAX_VERSION_GAP", "5")))
    # ROADMAP §8.3 binding (weekly cold-verify — silent storage rot).
    # 5-field UTC cron expression that fires the cold-verify pass on
    # the oldest still-retained Sunday dump. Default `0 5 * * 0`
    # (Sunday 05:00 UTC, after the nightly window). Catches bit-rot /
    # S3 lifecycle bugs / silent encryption-key loss long before the
    # dump is needed for real DR. Boot validation in
    # `MaintBackupAgent` refuses cron syntax errors loudly.
    maint_backup_cold_verify_cron: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_COLD_VERIFY_CRON", "0 5 * * 0"))
    # ROADMAP §8.15.10 Fix A — restore-verify concurrency cap.
    # Maximum seconds the second restore-verify caller waits to acquire
    # the PG advisory lock `LOCK_MAINT_BACKUP_RESTORE_VERIFY` before
    # yielding with kind=verify_concurrency_blocked.  Default 1800 s
    # (30 min — generous; both cold-verify and nightly fire in the same
    # early-Sunday window).  0 disables the wait (try-once, yield immediately).
    maint_backup_verify_lock_timeout_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_VERIFY_LOCK_TIMEOUT_S", "1800")))
    # ROADMAP §8.3 crash-cleanup invariant: on agent restart, orphaned
    # `negelir-maint-verify/restore-verify-*` K8s Jobs + ephemeral PVCs older
    # than this many hours are swept at boot and emit
    # `maint.event.v1{kind=backup_verify_orphan_swept}`. Default 6h.
    maint_backup_verify_orphan_ttl_h: float = field(default_factory=lambda: float(os.getenv("NEGELIR_MAINT_BACKUP_VERIFY_ORPHAN_TTL_H", "6.0")))
    # Size (Gi) of the ephemeral PVC provisioned for the K8s
    # restore-verify job. Must be at least 2× the expected
    # pg_restore output size; boot validation warns when this
    # is below ``maint_backup_min_free_gb``. Default 10 Gi.
    maint_backup_pvc_size_gb: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PVC_SIZE_GB", "10")))
    # PII-aware dump: comma-separated list of ``table.column`` entries excluded
    # from the logical dump by default. The production ``LocalPgDumpExecutor``
    # maps these to ``pg_dump --exclude-table-data`` / ``--exclude-column``.
    # The in-memory ``NoopDumpExecutor`` records them in ``dump_toc`` so tests
    # can assert the contract. ROADMAP §8.9 DoD: quarantine_samples.raw_bytes_b64
    # excluded by default (right-to-erasure invariant).
    maint_backup_pii_excluded_columns: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_MAINT_BACKUP_PII_EXCLUDED_COLUMNS",
        "quarantine_samples.raw_bytes_b64",
    ))
    # ROADMAP §8.9 binding (`fail_safe_wrong_pg_role`): the expected
    # Postgres role name the backup agent must run as. Defaults to the
    # least-privilege backup role `negelir_backup` (migration 011).
    # Changing this in prod requires an explicit env override and a
    # matching Postgres GRANT; the default is the safe hardened value.
    maint_backup_pg_role: str = field(default_factory=lambda: os.getenv(
        "NEGELIR_MAINT_BACKUP_PG_ROLE",
        "negelir_backup",
    ))
    # ROADMAP §8.13.6 binding (fail_safe_pg_secret_expired): hard cap on the
    # backup-role PG password age in days.  The agent refuses to start when
    # the age reported by PgSecretAgeChecker exceeds this value, forcing the
    # operator to rotate.  Default 120d = alert threshold (100d) + 20d grace.
    maint_backup_pg_secret_max_age_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_PG_SECRET_MAX_AGE_DAYS", "120")))
    # ROADMAP §8.14.3 supply-chain pin: the `age` encryption binary version
    # that the `maint.backup.v1` agent and the `ops.restore` CLI require.
    # Default "1.2.0" matches the upstream release pinned in the Dockerfile
    # and recorded in infra/maint/age_binary_provenance.txt. Operators can
    # override to roll forward without an image rebuild; the boot assertion
    # still fires loud on mismatch (fail_safe_age_version_mismatch).
    maint_backup_age_binary_version: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_AGE_BINARY_VERSION", "1.2.0"))
    # ROADMAP §8.9 two-class encryption: when True (default) each nightly
    # dump gets a freshly-generated ephemeral verify-class recipient keypair.
    # The verify key is included as a second recipient alongside the DR keys
    # so the SidecarVerifier (Phase 14) can decrypt for restore-verify without
    # holding a DR key. Set to False only for disaster-recovery drills where
    # the verify sidecar is intentionally bypassed.
    maint_backup_verify_key_rotate_per_dump: bool = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_VERIFY_KEY_ROTATE_PER_DUMP", "true").lower() in ("true", "1", "yes"))
    # ── ROADMAP §8.12 off-host replication ────────────────────────────────────────────────
    # Target type: "none" (disabled, default) or "s3" (S3-compatible).
    maint_backup_offsite_target: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_TARGET", "none"))
    # S3-compatible endpoint URL (leave empty for AWS-default region routing).
    maint_backup_offsite_endpoint: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_ENDPOINT", ""))
    # Destination bucket name.
    maint_backup_offsite_bucket: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_BUCKET", ""))
    # Minimum file size (MB) to trigger multipart upload. 0 = single-part.
    maint_backup_offsite_multipart_threshold_mb: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_MULTIPART_THRESHOLD_MB", "64")))
    # Bandwidth cap for offsite uploads (KB/s). 0 = unlimited.
    maint_backup_offsite_bw_kbps: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_BW_KBPS", "0")))
    # Upload timeout per fire window (hours). Exceeded → offsite_failed.
    maint_backup_offsite_upload_timeout_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_UPLOAD_TIMEOUT_H", "6")))
    # Object-lock (WORM) retention period in days. 0 = no WORM enforcement.
    maint_backup_offsite_object_lock_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_OBJECT_LOCK_DAYS", "0")))
    # Alert threshold: emit ``backup_offsite_age_alert`` when last successful
    # offsite upload is older than this many hours. 0 = watchdog disabled.
    maint_backup_offsite_age_alert_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_AGE_ALERT_H", "48")))
    # On-object retention in days for objects in the remote bucket.
    # Default 90 d in prod (compliance-grade window), 7 d in mock/dev.
    # Note: uses (os.getenv("NEGELIR_PROFILE") or "mock") so the
    # _GETENV_DEFAULT_RE duplicate-key test ignores this nested read.
    maint_backup_offsite_retention_days: int = field(default_factory=lambda: int(os.getenv(
        "NEGELIR_MAINT_BACKUP_OFFSITE_RETENTION_DAYS",
        "90" if (os.getenv("NEGELIR_PROFILE") or "mock") == "prod" else "7",
    )))
    # S3 access key ID (public, non-secret; the matching secret is referenced by
    # maint_backup_offsite_secret_access_key_secret_ref below).
    maint_backup_offsite_access_key_id: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_ACCESS_KEY_ID", ""))
    # File-path reference to the S3 secret access key. In K8s this is a
    # secretKeyRef volume-mount path (0400); in Compose/dev it is a plain file.
    # NEVER the literal secret value — the agent reads the file at boot.
    maint_backup_offsite_secret_access_key_secret_ref: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_SECRET_ACCESS_KEY_SECRET_REF", ""))
    # AWS / S3-compatible region used for SigV4 signing (e.g. "us-east-1",
    # "auto" for non-AWS services like R2 / B2 that don't enforce a region).
    maint_backup_offsite_s3_region: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_S3_REGION", "us-east-1"))
    # ROADMAP §8.15.10 Fix B — offsite credential hot-reload.
    # How often FileSecretProvider polls the secret file for mtime changes.
    # 0 disables polling (credentials read once at agent boot — compose dev shortcut).
    maint_backup_offsite_cred_reload_s: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_CRED_RELOAD_S", "60")))
    # Age threshold (days) beyond which the S3 access key is considered overdue
    # for rotation.  Matches the §8.15.10 90-day cadence best practice.
    # 0 disables the age check.
    maint_backup_offsite_credential_max_age_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_CREDENTIAL_MAX_AGE_DAYS", "90")))
    # Grace period (days) on top of maint_backup_offsite_credential_max_age_days.
    # Past max_age the agent emits severity=warn daily.  Past max_age+grace the
    # agent escalates to severity=critical AND refuses new uploads (keeps running
    # to not affect the rest of the maint plane).
    maint_backup_offsite_credential_grace_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_CREDENTIAL_GRACE_DAYS", "30")))
    # Phase 8 §8.16.5 — multipart upload-id TTL + lifecycle assertion.
    # Max age (hours) of .offsite_state.json before treating the persisted
    # upload_id as expired without even probing AWS.  Headroom under AWS's
    # 24 h default abort policy; default 18 h.  0 = always probe (no
    # time-based short-circuit).
    maint_backup_offsite_state_max_age_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_STATE_MAX_AGE_H", "18")))
    # Minimum acceptable AbortIncompleteMultipartUpload.DaysAfterInitiation.
    # If the bucket's lifecycle rule is more aggressive, a sec.alert is emitted.
    # Default 2 — gives the agent a one-day recovery window even on aggressive
    # cost-optimised bucket policies.
    maint_backup_offsite_lifecycle_min_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_LIFECYCLE_MIN_DAYS", "2")))
    # Phase 8 §8.16.6 — Object-Lock / WORM boot-time preflight probe.
    # How often (hours) the preflight probe repeats after the initial boot run.
    # 0 = run at boot only (disables recurring probe).
    maint_backup_offsite_preflight_interval_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_PREFLIGHT_INTERVAL_H", "24")))
    # When True (default) the agent refuses to start if the bucket's
    # Object-Lock is disabled while maint_backup_offsite_object_lock_days > 0.
    # Mock profile sets this to False via env to skip the hardware check.
    maint_backup_offsite_object_lock_required: bool = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_OBJECT_LOCK_REQUIRED", "true").lower() in ("true", "1", "yes"))
    # ROADMAP §8.16.6 binding fail-safe flags (all default True — refuse-to-start
    # / spool-mode on any preflight failure; operators may relax in non-prod).
    # Bucket Object-Lock is not enabled and object_lock_days > 0.
    fail_safe_offsite_object_lock_disabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_FAIL_SAFE_OFFSITE_OBJECT_LOCK_DISABLED", "true").lower() in ("true", "1", "yes"))
    # Sentinel retention metadata did not round-trip (IAM policy gap).
    fail_safe_offsite_retention_not_applied: bool = field(default_factory=lambda: os.getenv("NEGELIR_FAIL_SAFE_OFFSITE_RETENTION_NOT_APPLIED", "true").lower() in ("true", "1", "yes"))
    # Sentinel was deleted during retention window (WORM not enforced).
    fail_safe_offsite_lock_not_enforced: bool = field(default_factory=lambda: os.getenv("NEGELIR_FAIL_SAFE_OFFSITE_LOCK_NOT_ENFORCED", "true").lower() in ("true", "1", "yes"))
    # RsyncSshTarget: SSH host (or user@host) for the DR replica.
    maint_backup_offsite_rsync_host: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_RSYNC_HOST", ""))
    # RsyncSshTarget: absolute destination path on the remote SSH host.
    maint_backup_offsite_rsync_dest_path: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_RSYNC_DEST_PATH", ""))
    # RsyncSshTarget: path to a known_hosts file for strict host-key checking.
    # Empty = fall back to agent's ~/.ssh/known_hosts (acceptable in K8s pods).
    maint_backup_offsite_rsync_ssh_known_hosts: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_OFFSITE_RSYNC_SSH_KNOWN_HOSTS", ""))
    # Phase 8 §8.12 — DR-drill cadence gauge.
    # Path to the append-only CSV recording quarterly DR-drill outcomes.
    maint_backup_dr_drill_csv: str = field(default_factory=lambda: os.getenv("NEGELIR_MAINT_BACKUP_DR_DRILL_CSV", "data/backups/dr_drills.csv"))
    # Days threshold for the cadence-overdue alert (default 100 — one quarter
    # is ~91 d; the extra 9 d absorbs scheduling slippage before paging).
    maint_backup_dr_drill_alert_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_DR_DRILL_ALERT_DAYS", "100")))
    # ROADMAP §8.15.10 Fix C — restore-verify forensic capture.
    # Maximum total bytes written to <date>.failed/verify_forensic.json.
    # Default 256 KiB (262144).  When the computed JSON exceeds this budget,
    # the largest field is truncated first (pg_restore_stderr → pg_restore_stdout
    # → verify_sql_results) until the serialised size fits.
    # 0 disables the cap (unbounded; use only in dev/test).
    maint_backup_forensic_max_bytes: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_FORENSIC_MAX_BYTES", "262144")))
    # Phase 8 §8.13.1 — model-artifact backup discipline.
    # After a worst-case restore, the trainer can re-derive a byte-equivalent
    # artifact from the calibration/outcome rows referenced in the lineage
    # sidecar within this many hours of latency.  Used by the ops runbook
    # to set the SLA expectation; not enforced in-process today.
    maint_backup_model_reproducibility_window_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MODEL_REPRODUCIBILITY_WINDOW_H", "24")))
    # Retention days for model tarballs in the offsite bucket (shorter than
    # the PG retention because models are reproducible from Postgres rows).
    maint_backup_model_offsite_retention_days: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MODEL_OFFSITE_RETENTION_DAYS", "30")))
    # Debounce window (hours) for sec.alert.v1{kind=backup_model_lineage_missing}
    # per predictor_id.  A predictor whose artifacts are persistently sidecar-free
    # re-alerts at most once per window so a misconfigured trainer does not flood
    # the bus.  Set to 0 to disable debounce (useful in tests).
    maint_backup_model_lineage_missing_debounce_h: int = field(default_factory=lambda: int(os.getenv("NEGELIR_MAINT_BACKUP_MODEL_LINEAGE_MISSING_DEBOUNCE_H", "24")))
    # Phase 8 §8.4 — source-watcher summarizer graduation gate.
    # The summarizer may only enable when a pinned model id is
    # configured AND a startup reachability probe can contact the
    # summarizer endpoint from the agent's network namespace.
    source_watcher_summarizer_enabled: bool = field(default_factory=lambda: os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_ENABLED", "false").lower() in ("true", "1", "yes"))
    source_watcher_summarizer_model_id: str = field(default_factory=lambda: os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_MODEL_ID", ""))
    source_watcher_summarizer_probe_url: str = field(default_factory=lambda: os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_PROBE_URL", ""))
    source_watcher_summarizer_probe_timeout_sec: float = field(default_factory=lambda: float(os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_PROBE_TIMEOUT_SEC", "2.0")))
    source_watcher_summarizer_max_tokens_per_call: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_MAX_TOKENS_PER_CALL", "4096")))
    source_watcher_summarizer_max_tokens_per_day: int = field(default_factory=lambda: int(os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_MAX_TOKENS_PER_DAY", "50000")))
    source_watcher_summarizer_ledger_path: str = field(default_factory=lambda: os.getenv("NEGELIR_SOURCE_WATCHER_SUMMARIZER_LEDGER_PATH", "data/maint/summarizer_ledger.json"))

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

    @property
    def proofreader_quorum(self) -> int:
        """Phase 6.1: minimum distinct accept/warn verdicts required
        for the aggregator to publish `predict.approved.v1`. Computed
        as ⌊N/2⌋+1 from the length of
        ``swarm.agents.proofreader.replicas.PROOFREADER_POLICY_CLASSES``
        (the single source of truth for replica count; see Phase-6
        audit F3-1). Imported lazily to avoid a config↔swarm import
        cycle. Always ≥1.
        """
        # Local import: ai/common must not depend on ai/swarm at
        # module load time. The roster is a module-level constant so
        # the import is effectively free after the first call.
        from swarm.agents.proofreader.replicas import (
            PROOFREADER_POLICY_CLASSES,
        )

        n = max(len(PROOFREADER_POLICY_CLASSES), 1)
        return (n // 2) + 1

    # ── Phase 8 §8.1 resolved paths + parsed critical-agent set ────────
    @property
    def opsctl_critical_agents_set(self) -> frozenset[str]:
        """Comma-separated agent ids (whitespace-tolerant) that require
        typed-token confirmation for destructive ops console commands."""
        return frozenset(
            tok.strip()
            for tok in self.opsctl_critical_agents.split(",")
            if tok.strip()
        )

    @property
    def opsctl_audit_path_resolved(self) -> str:
        """Empty ``opsctl_audit_path`` → ``<data_dir>/maint/opsctl_audit.csv``."""
        if self.opsctl_audit_path:
            return self.opsctl_audit_path
        return os.path.join(self.data_dir, "maint", "opsctl_audit.csv")

    @property
    def opsctl_spool_dir_resolved(self) -> str:
        """Empty ``opsctl_spool_dir`` → ``<data_dir>/maint/opsctl_spool``."""
        if self.opsctl_spool_dir:
            return self.opsctl_spool_dir
        return os.path.join(self.data_dir, "maint", "opsctl_spool")

    @property
    def opsctl_lock_dir_resolved(self) -> str:
        """Empty ``opsctl_lock_dir`` → ``<data_dir>/maint/opsctl_locks``.

        Per ROADMAP §8.1 binding, the ops console takes a per-(host,
        kind, target) advisory lockfile here via :func:`fcntl.flock`
        non-blocking. Stale locks (no live holder, mtime older than
        ``opsctl_ack_timeout_ms × opsctl_lock_stale_factor``) are
        reaped on the next acquire.
        """
        if self.opsctl_lock_dir:
            return self.opsctl_lock_dir
        return os.path.join(self.data_dir, "maint", "opsctl_locks")

    @property
    def maint_audit_per_kind_details_max_bytes_parsed(self) -> "dict[str, int]":
        """Parse ``maint_audit_per_kind_details_max_bytes`` (JSON str) → dict.

        Keys are ``maint.event.v1`` kind strings; values are byte caps.
        The ``"default"`` key provides the fallback for unlisted kinds.
        Falls back to the ROADMAP §8.15.5 defaults on parse failure (malformed
        values are caught by ``validate()`` at boot).
        """
        import json as _json
        _defaults = {
            "dlq_escalated": 8192,
            "schema_drift_detected": 4096,
            "backup_dump_file_corrupted": 8192,
            "default": 2048,
        }
        try:
            parsed = {k: int(v) for k, v in _json.loads(
                self.maint_audit_per_kind_details_max_bytes
            ).items()}
            return parsed
        except (ValueError, TypeError, AttributeError):
            return _defaults

    @property
    def maint_audit_retention_overrides_parsed(self) -> "dict[str, int]":
        """Parse ``maint_audit_retention_days_overrides`` (JSON str) → dict.

        Used by the partition prune / pre-creation jobs to apply per-kind
        retention cutoffs.  Falls back to the §8.9 default (``pii_erased:
        2555``) when the env var is absent or malformed — validated at boot
        by ``validate()`` so malformed values only reach this path in tests.
        """
        import json as _json
        try:
            return {k: int(v) for k, v in _json.loads(
                self.maint_audit_retention_days_overrides
            ).items()}
        except (ValueError, TypeError, AttributeError):
            return {"pii_erased": 2555}

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
        _bounded("reactor_ledger_max_size", self.reactor_ledger_max_size, 1, 10_000_000)
        if self.scrape_profile not in ("mock", "real"):
            issues.append(
                f"scrape_profile={self.scrape_profile!r} not in ('mock', 'real')"
            )
        if self.profile not in ("mock", "prod"):
            issues.append(
                f"profile={self.profile!r} not in ('mock', 'prod')"
            )

        # Telemetry metrics bind: minimal sanity. Reject empty / whitespace
        # strings so we never silently bind to "" (= 0.0.0.0). A full
        # IP/hostname grammar isn't worth re-implementing — `socket.bind`
        # will reject anything truly malformed at startup.
        if not self.telemetry_metrics_bind or not self.telemetry_metrics_bind.strip():
            issues.append("telemetry_metrics_bind must be a non-empty host/IP")

        # Swarm bus kind enum
        _swarm_bus_kinds = {"redis", "memory"}
        if self.swarm_bus_kind not in _swarm_bus_kinds:
            issues.append(
                f"swarm_bus_kind={self.swarm_bus_kind!r} must be one of "
                f"{sorted(_swarm_bus_kinds)}"
            )

        # Probability / fraction fields
        _bounded("drift_accuracy_floor", self.drift_accuracy_floor, 0.0, 1.0)
        _bounded("drift_brier_ceiling", self.drift_brier_ceiling, 0.0, 1.0)
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
            # Phase 5
            ("consensus_window_ms", self.consensus_window_ms),
            ("consensus_min_voters", self.consensus_min_voters),
            ("consensus_brier_window", self.consensus_brier_window),
            ("predictor_max_vram_mb", self.predictor_max_vram_mb),
            ("trainer_debounce_sec", self.trainer_debounce_sec),
            ("backtest_window_weeks", self.backtest_window_weeks),
            ("backtest_min_n", self.backtest_min_n),
            ("api_consensus_overhead_ms", self.api_consensus_overhead_ms),
            # Phase 6
            ("proofreader_quorum_window_ms", self.proofreader_quorum_window_ms),
            ("proofreader_aggregator_max_pending", self.proofreader_aggregator_max_pending),
            ("swarm_flush_interval_ms", self.swarm_flush_interval_ms),
            ("drift_window_size", self.drift_window_size),
            ("drift_max_pending", self.drift_max_pending),
            ("drift_max_settled", self.drift_max_settled),
        ):
            if not isinstance(value, int) or value <= 0:
                issues.append(f"{name}={value} must be a positive integer")

        # Phase 5 fractions
        _bounded("consensus_min_confidence", self.consensus_min_confidence, 0.0, 1.0)
        _bounded("backtest_swarm_floor_pct", self.backtest_swarm_floor_pct, 0.0, 1.0)
        _bounded(
            "consensus_overflow_flag_min_interval_sec",
            self.consensus_overflow_flag_min_interval_sec,
            0.0,
            3600.0,
        )

        # Phase 6.2 — proofreader check thresholds
        _bounded("proofreader_sanity_eps", self.proofreader_sanity_eps, 0.0, 1.0)
        _bounded("proofreader_plausibility_max_prob", self.proofreader_plausibility_max_prob, 0.0, 1.0)
        _bounded("proofreader_grid_consistency_tol", self.proofreader_grid_consistency_tol, 0.0, 1.0)

        # Phase 6.3 — drift agent (Brier *ceiling* — see field docstring)
        _bounded("drift_brier_ceiling", self.drift_brier_ceiling, 0.0, 1.0)
        _bounded("drift_pvalue", self.drift_pvalue, 0.0, 1.0)

        # ── Phase 7 — Defense-agent knob validation ───────────────
        # Bytes (not codepoints) — see `sec_input_max_len` docstring.
        _bounded("sec_input_max_len", self.sec_input_max_len, 1, 1_048_576)
        _bounded("sec_input_gateway_max_latency_ms", self.sec_input_gateway_max_latency_ms, 1, 60_000)
        _bounded("sec_input_classifier_max_latency_ms", self.sec_input_classifier_max_latency_ms, 1, 60_000)
        _bounded("sec_input_classifier_batch_size", self.sec_input_classifier_batch_size, 1, 1024)
        _bounded("sec_input_classifier_batch_window_ms", self.sec_input_classifier_batch_window_ms, 1, 60_000)
        _bounded("sec_input_classifier_max_pending", self.sec_input_classifier_max_pending, 1, 1_000_000)
        _bounded("sec_input_breaker_open_s", self.sec_input_breaker_open_s, 1, 86_400)
        _bounded("sec_input_pattern_reload_s", self.sec_input_pattern_reload_s, 1, 86_400)
        _bounded("sec_input_allowlist_reload_s", self.sec_input_allowlist_reload_s, 1, 86_400)
        _bounded(
            "sec_input_allowlist_hmac_key_max_age_days",
            self.sec_input_allowlist_hmac_key_max_age_days,
            1,
            3650,
        )
        _SEC_DEVICES = {"auto", "cpu", "cuda", "rocm", "npu"}
        if self.sec_input_classifier_device not in _SEC_DEVICES:
            issues.append(
                f"sec_input_classifier_device={self.sec_input_classifier_device!r} "
                f"must be one of {sorted(_SEC_DEVICES)}"
            )
        _SEC_BATCH = {"auto", "true", "false"}
        if self.sec_input_classifier_batch_enabled not in _SEC_BATCH:
            issues.append(
                f"sec_input_classifier_batch_enabled="
                f"{self.sec_input_classifier_batch_enabled!r} must be one of "
                f"{sorted(_SEC_BATCH)}"
            )
        _bounded("sec_quarantine_ttl_days", self.sec_quarantine_ttl_days, 1, 3650)
        _bounded("sec_quarantine_payload_max_bytes", self.sec_quarantine_payload_max_bytes, 1, 16 * 1024 * 1024)
        _bounded("sec_quarantine_producer_queue_max", self.sec_quarantine_producer_queue_max, 1, 1_000_000)
        _bounded("sec_quarantine_storage_lag_alert_ms", self.sec_quarantine_storage_lag_alert_ms, 1, 86_400_000)

        _bounded("sec_scrape_size_delta_pct", self.sec_scrape_size_delta_pct, 0.0, 100_000.0)
        _bounded("sec_scrape_inflate_ratio_max", self.sec_scrape_inflate_ratio_max, 1.0, 10_000.0)
        _bounded("sec_scrape_warmup_samples", self.sec_scrape_warmup_samples, 0, 100_000)
        _bounded("sec_scrape_baseline_flush_s", self.sec_scrape_baseline_flush_s, 1, 86_400)
        _bounded("sec_scrape_max_pending", self.sec_scrape_max_pending, 1, 10_000_000)
        _bounded("sec_scrape_dedup_window", self.sec_scrape_dedup_window, 1, 10_000_000)
        # SimHash distance is bits-out-of-64; >= 32 is essentially "always trip".
        _bounded("sec_scrape_simhash_max_distance", self.sec_scrape_simhash_max_distance, 0, 64)
        _bounded("sec_scrape_dom_fingerprint_max_nodes", self.sec_scrape_dom_fingerprint_max_nodes, 1, 1_000_000)
        _bounded("sec_scrape_simhash_ring_size", self.sec_scrape_simhash_ring_size, 1, 1024)

        _bounded("sec_rate_pre_auth_capacity", self.sec_rate_pre_auth_capacity, 1, 1_000_000)
        _bounded("sec_rate_pre_auth_refill_per_s", self.sec_rate_pre_auth_refill_per_s, 0.0, 1e6)
        _bounded("sec_rate_post_auth_capacity", self.sec_rate_post_auth_capacity, 1, 10_000_000)
        _bounded("sec_rate_post_auth_refill_per_s", self.sec_rate_post_auth_refill_per_s, 0.0, 1e6)
        _bounded("sec_rate_bucket_idle_ttl_s", self.sec_rate_bucket_idle_ttl_s, 1, 86_400 * 30)
        _bounded("sec_rate_max_subjects", self.sec_rate_max_subjects, 1, 100_000_000)
        _bounded("sec_rate_ipv4_prefix", self.sec_rate_ipv4_prefix, 0, 32)
        _bounded("sec_rate_ipv6_prefix", self.sec_rate_ipv6_prefix, 0, 128)
        _bounded("sec_rate_redis_timeout_ms", self.sec_rate_redis_timeout_ms, 1, 60_000)
        _bounded("sec_rate_secondary_capacity", self.sec_rate_secondary_capacity, 1, 10_000_000)
        _bounded("sec_rate_secondary_refill_per_s", self.sec_rate_secondary_refill_per_s, 0.0, 1e6)
        _bounded("sec_rate_default_cost", self.sec_rate_default_cost, 0, 1_000_000)
        _bounded("sec_rate_eviction_rate_alert_per_s", self.sec_rate_eviction_rate_alert_per_s, 0.0, 1e9)
        _bounded("sec_rate_eviction_rate_window_s", self.sec_rate_eviction_rate_window_s, 1, 86_400)

        _bounded("sec_burst_threshold", self.sec_burst_threshold, 1, 100_000_000)
        _bounded("sec_burst_window_ms", self.sec_burst_window_ms, 1, 86_400_000)
        _bounded("sec_burst_dedup_window", self.sec_burst_dedup_window, 1, 10_000_000)

        _bounded("sec_denylist_ttl_s", self.sec_denylist_ttl_s, 1, 86_400 * 30)
        _bounded("sec_denylist_escalation_factor", self.sec_denylist_escalation_factor, 1.0, 1e6)
        _bounded("sec_denylist_max_entries", self.sec_denylist_max_entries, 1, 100_000_000)

        _bounded("sec_alert_debounce_ttl_s", self.sec_alert_debounce_ttl_s, 0, 86_400)
        _bounded("sec_alert_debouncer_max_buckets", self.sec_alert_debouncer_max_buckets, 1, 10_000_000)
        _bounded("qa_request_v1_dedup_window_s", self.qa_request_v1_dedup_window_s, 1, 86_400)

        # Phase 9 §9.7 — burst budget.
        _bounded("api_burst_capacity", self.api_burst_capacity, 1, 10_000_000)
        _bounded("api_burst_refill_per_s", self.api_burst_refill_per_s, 0.001, 1e6)

        # Phase 9 §9.13 — demo API base URL must be http:// or https://.
        if not (
            self.api_demo_base_url.startswith("http://")
            or self.api_demo_base_url.startswith("https://")
        ):
            issues.append(
                "api_demo_base_url must start with http:// or https://"
            )

        # Phase 8 §8.1 — ops console budgets + ack payload caps.
        _bounded("opsctl_ack_timeout_ms", self.opsctl_ack_timeout_ms, 1, 600_000)
        _bounded("opsctl_ack_timeout_ms_live_demo", self.opsctl_ack_timeout_ms_live_demo, 1, 60_000)
        if self.opsctl_ack_timeout_ms_live_demo >= self.opsctl_ack_timeout_ms:
            issues.append(
                "opsctl_ack_timeout_ms_live_demo must be lower than "
                "opsctl_ack_timeout_ms"
            )
        _bounded("opsctl_spool_max_entries", self.opsctl_spool_max_entries, 1, 1_000_000)
        _bounded("opsctl_spool_flush_max_per_run", self.opsctl_spool_flush_max_per_run, 0, 1_000_000)
        _bounded("maint_ack_payload_max_bytes", self.maint_ack_payload_max_bytes, 64, 1_048_576)
        _bounded("maint_ack_reason_max_bytes", self.maint_ack_reason_max_bytes, 16, 65_536)
        _bounded("maint_ack_details_max_bytes", self.maint_ack_details_max_bytes, 64, 1_048_576)
        # Reason + details together must fit inside the total payload cap
        # with room for the fixed-shape JSON wrapper (~256 bytes for the
        # request_id/accepted/accepted_by/processed_at/attempt fields).
        _ACK_FIXED_OVERHEAD = 256
        if (
            self.maint_ack_reason_max_bytes
            + self.maint_ack_details_max_bytes
            + _ACK_FIXED_OVERHEAD
            > self.maint_ack_payload_max_bytes
        ):
            issues.append(
                "maint_ack_payload_max_bytes is too small for "
                "maint_ack_reason_max_bytes + maint_ack_details_max_bytes "
                f"(+ {_ACK_FIXED_OVERHEAD}B fixed overhead)"
            )

        # Phase 8 §8.2 — scaler.
        _bounded("maint_scaler_decision_window_ms", self.maint_scaler_decision_window_ms, 100, 86_400_000)
        _bounded("maint_scaler_max_targets", self.maint_scaler_max_targets, 1, 1_000_000)
        _bounded("maint_scaler_max_replicas", self.maint_scaler_max_replicas, 1, 10_000)
        # Phase 8 §8.16.1 — default-policy fallback. 0 = disabled
        # (legacy behavior: unconfigured agents inherit
        # maint_scaler_max_replicas with no alert). When enabled,
        # floor is 2 (1 would be indistinguishable from "do not
        # scale me" and would silently freeze unconfigured agents).
        if self.maint_scaler_default_max_replicas != 0:
            _bounded("maint_scaler_default_max_replicas", self.maint_scaler_default_max_replicas, 2, 10_000)
        _bounded("maint_scaler_min_replicas", self.maint_scaler_min_replicas, 0, 10_000)
        _bounded("maint_scaler_scale_up_queue_depth", self.maint_scaler_scale_up_queue_depth, 1, 10_000_000)
        _bounded("maint_scaler_scale_down_queue_depth", self.maint_scaler_scale_down_queue_depth, 0, 10_000_000)
        _bounded("maint_scaler_scale_up_head_age_s", self.maint_scaler_scale_up_head_age_s, 0.0, 86_400.0)
        _bounded("maint_scaler_hysteresis_windows", self.maint_scaler_hysteresis_windows, 1, 1_000)
        _bounded("maint_scaler_hysteresis_grace", self.maint_scaler_hysteresis_grace, 0, 1_000)
        _bounded("maint_scaler_max_changes_per_window", self.maint_scaler_max_changes_per_window, 1, 1_000)
        _bounded("maint_scaler_manual_pin_ttl_s", self.maint_scaler_manual_pin_ttl_s, 1, 604_800)
        _bounded("maint_scaler_warmup_replicas", self.maint_scaler_warmup_replicas, 1, 10_000)
        _bounded("maint_scaler_global_max_replicas", self.maint_scaler_global_max_replicas, 1, 100_000)
        _bounded("maint_scaler_min_decision_interval_s", self.maint_scaler_min_decision_interval_s, 0.0, 86_400.0)
        _bounded("maint_scaler_runtime_timeout_s", self.maint_scaler_runtime_timeout_s, 1.0, 3_600.0)
        _bounded("maint_scaler_vram_headroom_mb", self.maint_scaler_vram_headroom_mb, 0, 1_048_576)
        _bounded("maint_scaler_vram_pessimistic_threshold_pct", self.maint_scaler_vram_pessimistic_threshold_pct, 0.0, 1.0)
        _bounded("maint_scaler_cpu_budget_pct", self.maint_scaler_cpu_budget_pct, 0.0, 1.0)
        _bounded("maint_scaler_scale_down_grace_windows", self.maint_scaler_scale_down_grace_windows, 0, 1_000)
        _bounded("maint_scaler_signal_window_samples", self.maint_scaler_signal_window_samples, 0, 10_000)
        _bounded("maint_scaler_target_load_per_replica", self.maint_scaler_target_load_per_replica, 0, 10_000_000)
        _bounded("maint_scaler_max_step_per_window", self.maint_scaler_max_step_per_window, 1, 10_000)
        # Phase 8 §8.2 observability — histogram bucket CSV must
        # parse to at least one strictly-positive float; values
        # outside (0, 86_400] are rejected to keep the bucket count
        # small and the bound monotonic.
        if self.maint_scaler_runtime_histogram_buckets.strip():
            seen: set[float] = set()
            for raw in self.maint_scaler_runtime_histogram_buckets.split(","):
                tok = raw.strip()
                if not tok:
                    continue
                try:
                    v = float(tok)
                except ValueError:
                    issues.append(
                        f"maint_scaler_runtime_histogram_buckets entry "
                        f"{tok!r} is not a float"
                    )
                    continue
                if not (0.0 < v <= 86_400.0):
                    issues.append(
                        f"maint_scaler_runtime_histogram_buckets entry "
                        f"{v!r} out of (0, 86400]"
                    )
                    continue
                seen.add(v)
            if not seen:
                issues.append(
                    "maint_scaler_runtime_histogram_buckets parsed "
                    "to no usable buckets"
                )
        if self.maint_runtime not in ("none", "compose", "k8s"):
            issues.append(
                f"maint_runtime={self.maint_runtime!r} must be one of: "
                "none, compose, k8s"
            )
        if self.maint_scaler_clock_source not in ("auto", "boottime", "monotonic"):
            issues.append(
                f"maint_scaler_clock_source={self.maint_scaler_clock_source!r} "
                "must be one of: auto, boottime, monotonic"
            )
        if self.maint_clock_suspend_alert_s < 0:
            issues.append(
                f"maint_clock_suspend_alert_s={self.maint_clock_suspend_alert_s!r} "
                "must be >= 0 (0 = disabled)"
            )
        # Per-agent overrides parse-validation: each non-empty entry
        # MUST be ``name=int`` with int in [min, max-replicas-cap].
        if self.maint_scaler_max_replicas_overrides_csv.strip():
            for raw in self.maint_scaler_max_replicas_overrides_csv.split(","):
                tok = raw.strip()
                if not tok:
                    continue
                if "=" not in tok:
                    issues.append(
                        f"maint_scaler_max_replicas_overrides_csv entry "
                        f"{tok!r} is not 'agent=N'"
                    )
                    continue
                name, _, value = tok.partition("=")
                name = name.strip()
                if not name:
                    issues.append(
                        f"maint_scaler_max_replicas_overrides_csv entry "
                        f"{tok!r} has empty agent name"
                    )
                    continue
                try:
                    n = int(value.strip())
                except ValueError:
                    issues.append(
                        f"maint_scaler_max_replicas_overrides_csv[{name}]"
                        f"={value!r} is not an integer"
                    )
                    continue
                if not (1 <= n <= 10_000):
                    issues.append(
                        f"maint_scaler_max_replicas_overrides_csv[{name}]"
                        f"={n} out of [1, 10000]"
                    )

        # Phase 8 §8.5 — DLQ supervisor.
        _bounded("maint_dlq_per_topic_quota", self.maint_dlq_per_topic_quota, 1, 10_000_000)
        _bounded("maint_dlq_replay_backoff_s", self.maint_dlq_replay_backoff_s, 1, 86_400)
        _bounded("maint_dlq_backoff_lru", self.maint_dlq_backoff_lru, 1, 1_000_000)
        _bounded("maint_dlq_visit_max", self.maint_dlq_visit_max, 1, 1_000)
        _bounded("maint_dlq_per_topic_max_per_min", self.maint_dlq_per_topic_max_per_min, 1, 1_000_000)
        _bounded("maint_dlq_visit_lru", self.maint_dlq_visit_lru, 1, 1_000_000)
        _bounded("maint_dlq_max_replays_per_tick", self.maint_dlq_max_replays_per_tick, 1, 1_000_000)
        _bounded("maint_dlq_consumer_broken_threshold", self.maint_dlq_consumer_broken_threshold, 2, 1000)
        _bounded("maint_dlq_consumer_broken_window_s", self.maint_dlq_consumer_broken_window_s, 1, 86_400)
        # Allow-list parse: every non-empty entry MUST end in ``.dlq``.
        if self.maint_dlq_replay_topics_allow_csv.strip():
            for raw in self.maint_dlq_replay_topics_allow_csv.split(","):
                tok = raw.strip()
                if tok and not tok.endswith(".dlq"):
                    issues.append(
                        f"maint_dlq_replay_topics_allow_csv entry "
                        f"{tok!r} must end in '.dlq'"
                    )
        for tok in self.maint_dlq_replay_allow_overrides:
            if not tok.endswith(".dlq"):
                issues.append(
                    f"maint_dlq_replay_allow_overrides entry "
                    f"{tok!r} must end in '.dlq'"
                )

        # Phase 8 §8.6 — schema sentinel.
        _bounded("maint_schema_sample_rate_per_s", self.maint_schema_sample_rate_per_s, 0.0, 10_000.0)
        _bounded("maint_schema_burst", self.maint_schema_burst, 1, 10_000)
        _bounded("maint_schema_drift_debounce_s", self.maint_schema_drift_debounce_s, 1, 86_400)
        _bounded("maint_schema_drift_lru", self.maint_schema_drift_lru, 1, 1_000_000)
        _bounded("maint_schema_pg_check_interval_s", self.maint_schema_pg_check_interval_s, 60, 86_400)
        # Phase 8 §8.14.7 — hard per-process validation-rate cap.
        # Positive lower bound (≥ 1); hard ceiling 500 is the safety knob
        # itself — exceeding it means a finger-fumble in the safety config.
        _bounded("maint_schema_validate_max_rps", self.maint_schema_validate_max_rps, 1, 500)
        if self.maint_schema_validate_max_rps > 500:
            issues.append(
                f"fail_safe_validate_rps_cap_exceeded: "
                f"maint_schema_validate_max_rps={self.maint_schema_validate_max_rps} "
                f"exceeds the safety ceiling of 500 — reduce to ≤ 500"
            )

        # Phase 8 §8.7 + §8.8 — sec maint.
        _bounded("maint_sec_pattern_ttl_s", self.maint_sec_pattern_ttl_s, 1, 31_536_000)
        _bounded("maint_sec_pattern_promote_threshold", self.maint_sec_pattern_promote_threshold, 1, 1_000_000)
        _bounded("maint_sec_pattern_pending_ttl_days", self.maint_sec_pattern_pending_ttl_days, 1, 3_650)
        _bounded("maint_sec_allowlist_pending_ttl_days", self.maint_sec_allowlist_pending_ttl_days, 1, 3_650)
        _bounded("maint_sec_request_lru", self.maint_sec_request_lru, 1, 1_000_000)
        _bounded("maint_sec_decimate_min_interval_s", self.maint_sec_decimate_min_interval_s, 1, 86_400)
        _bounded("maint_dlq_backlog_alert", self.maint_dlq_backlog_alert, 1, 100_000_000)
        _bounded("maint_dlq_replay_rps", self.maint_dlq_replay_rps, 1, 100_000)

        # Phase 8 §8.10 — pause/resume.
        _bounded("maint_pause_default_ttl_s", self.maint_pause_default_ttl_s, 1, 604_800)
        _bounded("maint_pause_max_ttl_s", self.maint_pause_max_ttl_s, self.maint_pause_default_ttl_s, 604_800)
        _bounded("maint_silence_dedup_s", self.maint_silence_dedup_s, 1, 86_400)
        _bounded("maint_silence_alert_h", self.maint_silence_alert_h, 1, 720)
        _bounded("maint_silence_warmup_s", self.maint_silence_warmup_s, 60, 86_400)
        _bounded("maint_self_dlq_alert", self.maint_self_dlq_alert, 1, 1_000_000)
        _bounded("maint_self_dlq_growth_alert", self.maint_self_dlq_growth_alert, 1, 100_000)
        _bounded("maint_self_dlq_throttle_recovery_s", self.maint_self_dlq_throttle_recovery_s, 1, 3_600)
        _bounded("maint_plane_lag_alert_ms", self.maint_plane_lag_alert_ms, 100, 300_000)
        _bounded("maint_plane_lag_alert_window_s", self.maint_plane_lag_alert_window_s, 1, 3_600)
        _bounded("sec_plane_lag_alert_ms", self.sec_plane_lag_alert_ms, 100, 300_000)
        _bounded("sec_plane_lag_alert_window_s", self.sec_plane_lag_alert_window_s, 1, 3_600)
        _bounded("maint_plane_recovery_window_s", self.maint_plane_recovery_window_s, 1, 3_600)
        # Phase 8 §8.9 — bus circuit-breaker.
        _bounded("maint_bus_fail_threshold", self.maint_bus_fail_threshold, 1, 100)
        _bounded("maint_bus_fail_window_s", self.maint_bus_fail_window_s, 1.0, 3_600.0)
        _bounded("maint_bus_spool_max_entries", self.maint_bus_spool_max_entries, 1, 100_000)
        _bounded("maint_agent_spool_max_entries", self.maint_agent_spool_max_entries, 1, 100_000)

        # Phase 8 §8.11 — backpressure.
        _bounded("maint_backpressure_yellow_factor", self.maint_backpressure_yellow_factor, 1.0, 1_000.0)
        _bounded("maint_backpressure_yellow_queue_depth", self.maint_backpressure_yellow_queue_depth, 1, 100_000_000)
        _bounded("maint_backpressure_yellow_head_age_s", self.maint_backpressure_yellow_head_age_s, 0.0, 86_400.0)
        _bounded("maint_backpressure_yellow_storage_pct", self.maint_backpressure_yellow_storage_pct, 0.0, 100.0)
        _bounded("maint_backpressure_yellow_error_rate_per_s", self.maint_backpressure_yellow_error_rate_per_s, 0.0, 1_000_000.0)
        _bounded("maint_backpressure_red_queue_depth", self.maint_backpressure_red_queue_depth, 1, 100_000_000)
        _bounded("maint_backpressure_red_head_age_s", self.maint_backpressure_red_head_age_s, 0.0, 86_400.0)
        _bounded("maint_backpressure_red_storage_pct", self.maint_backpressure_red_storage_pct, 0.0, 100.0)
        _bounded("maint_backpressure_red_error_rate_per_s", self.maint_backpressure_red_error_rate_per_s, 0.0, 1_000_000.0)
        # Phase 8 §8.13.2 — cumulative storage cap (0 = disabled).
        if self.maint_storage_total_max_mb != 0:
            _bounded("maint_storage_total_max_mb", self.maint_storage_total_max_mb, 1, 1_048_576)
        # Phase 8 §8.15.3 advisory-lock hold-time guard. 0 disables.
        if self.maint_advisory_lock_max_hold_ms != 0:
            _bounded("maint_advisory_lock_max_hold_ms", self.maint_advisory_lock_max_hold_ms, 1, 3_600_000)
        if self.maint_backpressure_yellow_queue_depth >= self.maint_backpressure_red_queue_depth:
            issues.append("maint_backpressure_yellow_queue_depth must be < maint_backpressure_red_queue_depth")
        if self.maint_backpressure_yellow_head_age_s >= self.maint_backpressure_red_head_age_s:
            issues.append("maint_backpressure_yellow_head_age_s must be < maint_backpressure_red_head_age_s")
        if self.maint_backpressure_yellow_storage_pct >= self.maint_backpressure_red_storage_pct:
            issues.append("maint_backpressure_yellow_storage_pct must be < maint_backpressure_red_storage_pct")

        # Phase 8 §8.14 — audit retention.
        _bounded("maint_audit_partition_retention_days", self.maint_audit_partition_retention_days, 1, 36_500)

        # Phase 8 §8.3 — backup agent.
        try:
            from xops.backup.cron import CronSyntaxError, parse_cron
            _parsed = parse_cron(str(self.maint_backup_cron))
            if _parsed.fires_every_minute:
                issues.append(
                    "maint_backup_cron resolves to every-minute firing "
                    f"({self.maint_backup_cron!r}); refusing — set a"
                    " specific hour/minute"
                )
        except CronSyntaxError as exc:
            issues.append(f"maint_backup_cron: {exc}")
        except ImportError:
            # xops package not on sys.path during very-early bootstrap
            # (e.g. some pickled-cfg unit tests). Defer to the agent's
            # own parse at construction time.
            pass
        # Phase 8 §8.3 — weekly cold-verify cron.
        try:
            from xops.backup.cron import CronSyntaxError, parse_cron
            _parsed_cv = parse_cron(str(self.maint_backup_cold_verify_cron))
            if _parsed_cv.fires_every_minute:
                issues.append(
                    "maint_backup_cold_verify_cron resolves to every-minute "
                    f"firing ({self.maint_backup_cold_verify_cron!r}); "
                    "refusing — set a specific hour/minute"
                )
        except CronSyntaxError as exc:
            issues.append(f"maint_backup_cold_verify_cron: {exc}")
        except ImportError:
            pass
        _bounded("maint_backup_retention_days", self.maint_backup_retention_days, 1, 3650)
        _bounded("maint_backup_retention_weeks", self.maint_backup_retention_weeks, 1, 520)
        _bounded("maint_backup_min_free_gb", self.maint_backup_min_free_gb, 1, 100_000)
        _bounded("maint_backup_max_skew_h", self.maint_backup_max_skew_h, 1, 8760)
        _bounded("maint_backup_age_alert_h", self.maint_backup_age_alert_h, 1, 8760)
        _bounded("maint_backup_clock_step_back_alert_s", self.maint_backup_clock_step_back_alert_s, 1, 86_400)
        _bounded("maint_backup_pg_jobs", self.maint_backup_pg_jobs, 1, 64)
        _bounded("maint_backup_pg_conn_limit", self.maint_backup_pg_conn_limit, 0, 10_000)
        _bounded("maint_backup_pg_secret_max_age_days", self.maint_backup_pg_secret_max_age_days, 1, 3650)
        _bounded("maint_backup_prune_batch", self.maint_backup_prune_batch, 1, 1_000_000)
        _bounded("maint_backup_prune_max_lock_ms", self.maint_backup_prune_max_lock_ms, 1, 300_000)
        _bounded("maint_schema_snapshot_retention_days", self.maint_schema_snapshot_retention_days, 1, 3650)
        _bounded("swarm_dlq_pg_retention_days", self.swarm_dlq_pg_retention_days, 1, 3650)
        _bounded("maint_audit_retention_days", self.maint_audit_retention_days, 1, 3650)
        _bounded("opsctl_audit_max_bytes", self.opsctl_audit_max_bytes, 65536, 1_073_741_824)
        _bounded("maint_audit_row_max_bytes", self.maint_audit_row_max_bytes, 1024, 1_048_576)
        try:
            import json as _json
            kind_budgets = _json.loads(self.maint_audit_per_kind_details_max_bytes)
            if not isinstance(kind_budgets, dict):
                issues.append(
                    "maint_audit_per_kind_details_max_bytes must be a JSON object "
                    f"(got {self.maint_audit_per_kind_details_max_bytes!r})"
                )
            else:
                for k, v in kind_budgets.items():
                    if not isinstance(v, int) or v < 1:
                        issues.append(
                            f"maint_audit_per_kind_details_max_bytes[{k!r}]={v!r} "
                            "must be a positive integer"
                        )
                    elif v > self.maint_audit_row_max_bytes:
                        issues.append(
                            f"maint_audit_per_kind_details_max_bytes[{k!r}]={v} "
                            f"exceeds maint_audit_row_max_bytes={self.maint_audit_row_max_bytes}"
                        )
        except (ValueError, TypeError) as _perr:
            issues.append(
                "maint_audit_per_kind_details_max_bytes must be a valid JSON object "
                f"(got {self.maint_audit_per_kind_details_max_bytes!r}): {_perr}"
            )
        try:
            import json as _json
            _json.loads(self.maint_audit_retention_days_overrides)
        except (ValueError, TypeError):
            issues.append(
                "maint_audit_retention_days_overrides must be a valid JSON object "
                f"(got {self.maint_audit_retention_days_overrides!r})"
            )
        _bounded("maint_backup_min_dr_recipients", self.maint_backup_min_dr_recipients, 1, 64)
        _bounded("maint_backup_pvc_size_gb", self.maint_backup_pvc_size_gb, 1, 65_536)
        _bounded("maint_backup_max_version_gap", self.maint_backup_max_version_gap, 1, 1000)
        # Refuse `*-latest` style verify-image tags — CLAUDE.md doctrine.
        if str(self.maint_backup_verify_pg_image).endswith(":latest") or self.maint_backup_verify_pg_image.endswith("-latest"):
            issues.append(
                f"maint_backup_verify_pg_image={self.maint_backup_verify_pg_image!r} "
                f"must pin a specific tag (no *-latest)"
            )
        _bounded("maint_backup_pg_dump_nice_level", self.maint_backup_pg_dump_nice_level, 0, 19)
        # §8.15.10 new knobs — allow 0 (disabled) for all three.
        if self.maint_backup_verify_lock_timeout_s != 0:
            _bounded("maint_backup_verify_lock_timeout_s", self.maint_backup_verify_lock_timeout_s, 1, 86_400)
        if self.maint_backup_offsite_cred_reload_s != 0:
            _bounded("maint_backup_offsite_cred_reload_s", self.maint_backup_offsite_cred_reload_s, 1, 86_400)
        if self.maint_backup_offsite_credential_max_age_days != 0:
            _bounded("maint_backup_offsite_credential_max_age_days", self.maint_backup_offsite_credential_max_age_days, 1, 3650)
        if self.maint_backup_offsite_credential_grace_days != 0:
            _bounded("maint_backup_offsite_credential_grace_days", self.maint_backup_offsite_credential_grace_days, 1, 365)
        if self.maint_backup_offsite_state_max_age_h != 0:
            _bounded("maint_backup_offsite_state_max_age_h", self.maint_backup_offsite_state_max_age_h, 1, 168)
        if self.maint_backup_offsite_lifecycle_min_days != 0:
            _bounded("maint_backup_offsite_lifecycle_min_days", self.maint_backup_offsite_lifecycle_min_days, 1, 365)
        if self.maint_backup_forensic_max_bytes != 0:
            _bounded("maint_backup_forensic_max_bytes", self.maint_backup_forensic_max_bytes, 1024, 10_485_760)
        _bounded(
            "source_watcher_summarizer_probe_timeout_sec",
            self.source_watcher_summarizer_probe_timeout_sec,
            0.1,
            60.0,
        )
        _bounded(
            "source_watcher_summarizer_max_tokens_per_call",
            self.source_watcher_summarizer_max_tokens_per_call,
            1,
            131_072,
        )
        _bounded(
            "source_watcher_summarizer_max_tokens_per_day",
            self.source_watcher_summarizer_max_tokens_per_day,
            1,
            10_000_000,
        )
        if (
            self.source_watcher_summarizer_max_tokens_per_day
            < self.source_watcher_summarizer_max_tokens_per_call
        ):
            issues.append(
                "source_watcher_summarizer_max_tokens_per_day must be >= "
                "source_watcher_summarizer_max_tokens_per_call"
            )
        if not self.source_watcher_summarizer_ledger_path.strip():
            issues.append(
                "source_watcher_summarizer_ledger_path must be non-empty"
            )
        if (
            self.source_watcher_summarizer_model_id.strip()
            and (
                self.source_watcher_summarizer_model_id.endswith(":latest")
                or self.source_watcher_summarizer_model_id.endswith("-latest")
            )
        ):
            issues.append(
                "source_watcher_summarizer_model_id="
                f"{self.source_watcher_summarizer_model_id!r} must pin a "
                "specific model id (no *-latest)"
            )
        if self.source_watcher_summarizer_enabled:
            if not self.source_watcher_summarizer_model_id.strip():
                issues.append(
                    "source_watcher_summarizer_enabled=true requires a non-empty "
                    "source_watcher_summarizer_model_id"
                )
            if not self.source_watcher_summarizer_probe_url.strip():
                issues.append(
                    "source_watcher_summarizer_enabled=true requires a non-empty "
                    "source_watcher_summarizer_probe_url"
                )

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
        _check_url(
            "source_watcher_summarizer_probe_url",
            self.source_watcher_summarizer_probe_url,
        )
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
