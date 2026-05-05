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
    api_consensus_overhead_ms: int = field(default_factory=lambda: int(os.getenv("NEGELIR_API_CONSENSUS_OVERHEAD_MS", "250")))

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
