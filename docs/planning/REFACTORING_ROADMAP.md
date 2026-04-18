# Negelir — Code Refactoring Roadmap

**Date:** 2026-04-18  
**Scope:** Centralized config management, performance optimization, code cleanup  
**Companion to:** [ROADMAP.md](ROADMAP.md) (project feature roadmap)  
**Based on:** Full codebase audit — 87 issues across 24 files  
**Status:** Planning  

---

## Executive Summary

The codebase has **three systemic problems** this roadmap addresses:

1. **Config fragmentation** — Three disconnected config systems (`ai/common/config.py`, `ai/common/league_config.py`, `p2p/config.py`) with values duplicated/conflicting across 15+ source files.
2. **Performance blind spots** — No caching layer for hot paths, regex recompilation on every call, redundant Poisson matrix calculations, and blocking I/O at module import time.
3. **Dead code & inconsistency** — Stale methods, unused imports, incomplete refactors, and magic strings/numbers scattered throughout the codebase.

**Issue Breakdown:**

| Severity | Hardcoded | Config Frag | Config Conflict | Performance | Dead Code | Cleanup | Total |
|----------|-----------|-------------|-----------------|-------------|-----------|---------|-------|
| Critical | 8 | 2 | 1 | 1 | 2 | — | **12** |
| High | 12 | 3 | 2 | 3 | 3 | 4 | **28** |
| Medium | 15 | 2 | 2 | 5 | 2 | 8 | **35** |
| Low | 12 | — | — | 1 | 3 | 7 | **12** |
| **Total** | **47** | **7** | **5** | **10** | **10** | **19** | **87** |

---

## Guiding Principles

1. **Single Source of Truth** — Every configurable value exists in exactly one place. No duplication.
2. **No Behavior Change** — Refactoring preserves identical runtime behavior. Default values don't change.
3. **Incremental & Testable** — Each phase has a verification gate. Tests must pass before proceeding.
4. **Config Hierarchy** — `env var > config file > LeagueConfig field > dataclass default`

---

## Phase Overview

| Phase | Name | Focus | Effort | Depends On |
|-------|------|-------|--------|------------|
| **R1** | Unified Config Architecture | Merge 3 config systems into layered hierarchy | Large | — |
| **R2** | Hardcode Extraction (AI Engine) | Move all magic numbers from `ai/model/` and `ai/pipeline/` to config | Medium | R1 |
| **R3** | Hardcode Extraction (Scraper & Scheduler) | Move scraper/scheduler literals to config | Medium | R1 |
| **R4** | Hardcode Extraction (P2P & Server) | Move P2P and Go server hardcodes to config | Medium | R1 |
| **R5** | Performance Optimization | Caching, lazy loading, computation reduction | Medium | — |
| **R6** | Dead Code Removal & Cleanup | Remove stale code, fix inconsistencies | Small | R2-R4 |
| **R7** | Config Documentation & Validation | `.env.example`, runtime validation, startup diagnostics | Small | R1-R4 |

```
R1 (Unified Config) ──→ R2 (AI Hardcodes) ──→ R6 (Cleanup)
       │                 R3 (Scraper)     ──→ R6
       │                 R4 (P2P/Server)  ──→ R6
       │                                      │
       └── R5 (Performance) ──────────────────→ R7 (Docs & Validation)
```

---

## Phase R1: Unified Config Architecture

**Goal:** Replace the three independent config systems with a single layered config hierarchy that all modules consume.  
**Current state:** `ai/common/config.py` (68 fields), `ai/common/league_config.py` (40+ fields), `p2p/config.py` (18 fields) — each with its own `os.getenv()` pattern. Values conflict between them (e.g., XGBoost hyperparams in `device.py` vs `LeagueConfig`).

### R1.1: Create `defaults.yaml` as the single defaults file

**New file:** `ai/common/defaults.yaml`

All default values currently hardcoded as second arguments to `os.getenv()` calls move into a structured YAML file.

```yaml
# ai/common/defaults.yaml — Single source of truth for all default values.
# Override any value via the corresponding env var (documented inline).

ai:
  device: auto                    # AI_DEVICE
  log_level: DEBUG                # AI_LOG_LEVEL
  model_version: "0.3.0"         # NEGELIR_MODEL_VERSION
  max_input_length: 200          # NEGELIR_MAX_INPUT_LENGTH
  n_features: null               # Derived from FEATURE_COLUMNS length; never hardcode

  model:
    xgb_weight: 0.35             # NEGELIR_XGB_WEIGHT — ensemble weight (XGB vs Poisson)
    dixon_coles_rho: -0.13       # NEGELIR_DIXON_COLES_RHO
    min_xg_floor: 0.3            # NEGELIR_MIN_XG_FLOOR
    elo_divisor: 600.0            # NEGELIR_ELO_DIVISOR
    venue_ratio_floor: 0.7       # NEGELIR_VENUE_RATIO_FLOOR
    venue_ratio_ceiling: 1.4     # NEGELIR_VENUE_RATIO_CEILING
    drift_window: 30             # NEGELIR_DRIFT_WINDOW
    drift_accuracy_floor: 0.35   # NEGELIR_DRIFT_ACCURACY_FLOOR

  training:
    noise_pct: 0.005             # NEGELIR_TRAINING_NOISE_PCT
    sample_weights:              # NEGELIR_TRAINING_SAMPLE_WEIGHTS (JSON string)
      home_win: 1.0
      draw: 2.0
      away_win: 1.0
    test_split: 0.2              # NEGELIR_TRAINING_TEST_SPLIT
    val_split: 0.15              # NEGELIR_TRAINING_VAL_SPLIT
    model_max_size_mb: 8.0       # NEGELIR_MODEL_MAX_SIZE_MB
    min_matches_required: 100    # NEGELIR_MIN_MATCHES_REQUIRED

  scraping:
    rate_limit_seconds: 5        # SCRAPE_RATE_LIMIT_SECONDS
    real_data_rate_limit: 1.0    # NEGELIR_REAL_DATA_RATE_LIMIT
    server_fetch_timeout: 10     # NEGELIR_SERVER_FETCH_TIMEOUT
    scrape_trigger_timeout: 30   # NEGELIR_SCRAPE_TRIGGER_TIMEOUT
    health_check_timeout: 5      # NEGELIR_HEALTH_CHECK_TIMEOUT
    mackolik_http_timeout: 15    # NEGELIR_MACKOLIK_HTTP_TIMEOUT
    scrape_http_timeout: 15      # NEGELIR_SCRAPE_HTTP_TIMEOUT
    footballdata_http_timeout: 10 # NEGELIR_FOOTBALLDATA_HTTP_TIMEOUT
    user_agent: "Negelir/0.1 (Football Analysis Research)"

  scheduler:
    daily_scrape_hour: 6         # NEGELIR_SCHEDULE_DAILY_SCRAPE_HOUR
    daily_scrape_minute: 0       # NEGELIR_SCHEDULE_DAILY_SCRAPE_MINUTE
    outcome_check_hour: 22       # NEGELIR_SCHEDULE_OUTCOME_CHECK_HOUR
    outcome_check_minute: 0      # NEGELIR_SCHEDULE_OUTCOME_CHECK_MINUTE
    retrain_day: sun             # NEGELIR_SCHEDULE_RETRAIN_DAY
    retrain_hour: 3              # NEGELIR_SCHEDULE_RETRAIN_HOUR
    heartbeat_minutes: 5         # NEGELIR_SCHEDULE_HEARTBEAT_MINUTES

  self_healing:
    stale_threshold_seconds: 604800  # NEGELIR_STALE_THRESHOLD_SECONDS (7 days)
    stale_confidence_penalty: 0.5    # NEGELIR_STALE_CONFIDENCE_PENALTY
    source_failure_threshold: 3      # NEGELIR_SOURCE_FAILURE_THRESHOLD

  telemetry:
    max_stream_len: 50000        # NEGELIR_TELEMETRY_MAX_STREAM_LEN
    redis_socket_timeout: 2      # NEGELIR_REDIS_SOCKET_TIMEOUT

p2p:
  message_ttl_hours: 168         # P2P_MESSAGE_TTL_HOURS
  data_ttl_hours: 168            # P2P_DATA_TTL_HOURS
  multicast_group: "239.42.42.1" # P2P_MULTICAST_GROUP
  multicast_port: 9743           # P2P_MULTICAST_PORT
  discovery_interval_sec: 30     # P2P_DISCOVERY_INTERVAL_SEC
  multicast_ttl: 2               # P2P_MULTICAST_TTL
  tcp_host: "0.0.0.0"           # P2P_TCP_HOST
  tcp_port: 9742                 # P2P_TCP_PORT
  tcp_connect_timeout_sec: 5.0   # P2P_TCP_CONNECT_TIMEOUT_SEC
  tcp_read_timeout_sec: 10.0     # P2P_TCP_READ_TIMEOUT_SEC
  tcp_max_message_size: 1048576  # P2P_TCP_MAX_MESSAGE_SIZE (1MB)
  sim_latency_min_ms: 20.0       # P2P_SIM_LATENCY_MIN_MS
  sim_latency_max_ms: 150.0      # P2P_SIM_LATENCY_MAX_MS
  sim_drop_rate: 0.02            # P2P_SIM_DROP_RATE
  sim_k_neighbors: 8             # P2P_SIM_K_NEIGHBORS
  sim_gossip_fanout: 3           # P2P_SIM_GOSSIP_FANOUT
  schema_quorum: 3               # P2P_SCHEMA_QUORUM
  schema_vote_timeout_sec: 600   # P2P_SCHEMA_VOTE_TIMEOUT_SEC
  schema_confidence_floor: 0.6   # P2P_SCHEMA_CONFIDENCE_FLOOR

server:
  port: 8080                     # PORT
  db_max_conns: 10               # DB_MAX_CONNS
  db_connect_timeout_sec: 5      # DB_CONNECT_TIMEOUT_SEC
  db_ping_timeout_sec: 5         # DB_PING_TIMEOUT_SEC
  http_read_timeout_sec: 10      # HTTP_READ_TIMEOUT_SEC
  http_write_timeout_sec: 30     # HTTP_WRITE_TIMEOUT_SEC
  http_shutdown_timeout_sec: 5   # HTTP_SHUTDOWN_TIMEOUT_SEC
  cache_matches_ttl_sec: 300     # CACHE_MATCHES_TTL_SEC
  cache_teams_ttl_sec: 600       # CACHE_TEAMS_TTL_SEC
```

**Deliverables:**
- [ ] `ai/common/defaults.yaml` created with every default value and inline env var comments
- [ ] `defaults.yaml` is version-controlled and treated as the canonical reference

### R1.2: Create unified config loader

**File:** `ai/common/config.py` (refactor)

Replace the current 180+ line `Config` dataclass (68 `os.getenv()` calls with inline defaults) with a loader that:

1. Reads `defaults.yaml` for base values
2. Overlays env vars on top (each YAML key has a documented env var name)
3. Exposes a typed `Config` object with the same field names (API stays the same)

```python
# Pseudocode for the loading chain:
# 1. Load defaults.yaml → flat dict
# 2. For each key, check os.getenv(ENV_VAR_NAME)
# 3. If env var set, override the default
# 4. Construct Config dataclass from merged dict
```

**Key design decisions:**
- `Config` and `P2PConfig` remain separate dataclasses (different namespaces), but both read from the same `defaults.yaml`
- `LeagueConfig` fields that are league-independent (like `xgb_weight`, `dixon_coles_rho`) read their defaults from `defaults.yaml`. League-specific overrides (like `elo_home_advantage=55.0` for EPL) remain in `LeagueConfig` factory functions.
- The `defaults.yaml` → env-var overlay → dataclass pattern replaces all 86+ `os.getenv()` calls

**Deliverables:**
- [ ] `Config.__init__()` loads from YAML + env overlay (not 68 individual `os.getenv` calls)
- [ ] `P2PConfig.__init__()` uses the same loader for its section
- [ ] All existing `config.field_name` access patterns continue to work (no API break)
- [ ] `Config()` with no env vars produces identical behavior to current code

### R1.3: Eliminate LeagueConfig / Config conflicts

**Current conflicts:**

| Parameter | `config.py` | `league_config.py` | `device.py` | Resolution |
|-----------|-------------|---------------------|-------------|------------|
| `xgb_weight` | Line 93 (unused) | `0.35` | — | Keep in `LeagueConfig` only; remove from `config.py` |
| `n_estimators` | — | `300` | Was `350` (now reads from `LeagueConfig`) | Already resolved in `device.py`; verify no other copies |
| `learning_rate` | — | `0.08` | Was `0.06` (now reads from `LeagueConfig`) | Already resolved; verify |
| `mackolik_group_id` | Line 29 (`1`) | — | — | Move to `LeagueConfig.mackolik_group_id` field, keep env override |
| `default_season` | Line 28 (`"2025-2026"`) | — | — | Keep in `Config`; `LeagueConfig` references `config.default_season` |
| `dixon_coles_rho` | — | `-0.13` | — | Stay in `LeagueConfig` (is league-specific) |

**Deliverables:**
- [ ] No value exists in both `Config` and `LeagueConfig`
- [ ] `device.py:get_xgb_params()` reads exclusively from `LeagueConfig` (already done — verify)
- [ ] `mackolik_group_id` moved to `LeagueConfig` with `NEGELIR_MACKOLIK_GROUP_ID` env override
- [ ] Document which config owns which namespace in `defaults.yaml` header comments

### R1.4: Wire P2P modules to read from `P2PConfig`

**Current state:** `p2p/config.py` exists with all fields env-driven, but several P2P modules still define their own module-level constants:

| Module | Hardcoded Constant | Should Read From |
|--------|--------------------|------------------|
| `p2p/node/discovery.py:15-17` | `MULTICAST_GROUP`, `MULTICAST_PORT`, `DISCOVERY_INTERVAL_SEC`, `ANNOUNCE_TTL` | `p2p_cfg.multicast_group`, `.multicast_port`, `.discovery_interval_sec`, `.multicast_ttl` |
| `p2p/protocol/tcp_transport.py:20` | `MAX_MESSAGE_SIZE = 1048576` | `p2p_cfg.tcp_max_message_size` |
| `p2p/protocol/transport.py:58-61` | `latency_ms_range=(20,150)`, `drop_rate=0.02`, `k_neighbors=8`, `gossip_fanout=3` | `p2p_cfg.sim_latency_min_ms/max_ms`, `.sim_drop_rate`, `.sim_k_neighbors`, `.sim_gossip_fanout` |
| `p2p/protocol/messages.py:47` | `ttl_hours=168` | `p2p_cfg.message_ttl_hours` |
| `p2p/coordination/schema_gossip.py:47-49` | `QUORUM=3`, `VOTE_TIMEOUT=600`, `CONFIDENCE_FLOOR=0.6` | `p2p_cfg.schema_quorum`, `.schema_vote_timeout_sec`, `.schema_confidence_floor` |
| `p2p/node/peer.py:77` | `ttl_hours=168` | `p2p_cfg.data_ttl_hours` |

**Deliverables:**
- [ ] Every module-level constant in `p2p/` replaced with `p2p_cfg.field` access
- [ ] Module-level `CONSTANT = value` lines deleted (not commented out)
- [ ] All P2P tests pass with default `P2PConfig()`
- [ ] `p2p_cfg` singleton imported from `p2p.config` consistently

### R1.5: Make `N_FEATURES` derived, not hardcoded

**File:** `ai/common/constants.py` line 11

**Current:** `N_FEATURES = 130` — a magic number that must match `FEATURE_COLUMNS` length.

**Change:**
```python
# Before:
N_FEATURES = 130

# After:
N_FEATURES = len(FEATURE_COLUMNS)
```

This means `FEATURE_COLUMNS` must be defined before `N_FEATURES`. Currently it's defined in `ai/model/features.py`. Either:
- Move `FEATURE_COLUMNS` to `constants.py` (preferred — it's a domain constant), or
- Import it and derive `N_FEATURES` dynamically

**Deliverables:**
- [ ] `N_FEATURES` is computed from `len(FEATURE_COLUMNS)`, not a literal
- [ ] Adding/removing a feature column automatically adjusts `N_FEATURES`
- [ ] Shape validation in inference and training uses this derived value

### Phase R1 Completion Gate

| Check | Command |
|-------|---------|
| No `os.getenv` with inline default in `config.py` | `grep -n "os.getenv" ai/common/config.py` — all calls should reference `defaults.yaml` values |
| No duplicate values across config files | Manual review: each configurable value in exactly one config dataclass |
| `defaults.yaml` matches current behavior | `diff` runtime config with and without YAML loader — identical |
| All tests pass | `make test` — 487+ tests green |

---

## Phase R2: Hardcode Extraction — AI Engine

**Goal:** Zero magic numbers in `ai/model/` and `ai/pipeline/`. Every behavioral constant reads from `Config` or `LeagueConfig`.  
**Depends on:** R1 (unified config in place)

### R2.1: `ai/model/inference.py` — Feature ranges and model constants

**Current hardcodes (11 items):**

| Line | Value | Target Config Field |
|------|-------|---------------------|
| 42-77 | `FEATURE_RANGES` dict (12 range tuples) | `defaults.yaml: ai.model.feature_ranges` — loaded as dict at startup |
| 172 | `rho` param in `_dixon_coles_tau()` | Already `LeagueConfig.dixon_coles_rho` — verify caller passes it |
| 227 | `600.0` (Elo divisor) | `LeagueConfig.elo_divisor` (new field, default `600.0`) |
| 230-240 | `min(1.4, max(0.7, ...))` venue ratio bounds | `LeagueConfig.venue_ratio_floor`, `LeagueConfig.venue_ratio_ceiling` |
| 163-178 | `range(8)`, `range(6)` Poisson caps | Already `LeagueConfig.poisson_home_goal_cap`, `poisson_away_goal_cap` — verify usage |

**Deliverables:**
- [ ] `FEATURE_RANGES` loaded from `defaults.yaml` or `LeagueConfig`, not an inline dict
- [ ] Elo divisor (`600.0`) is a `LeagueConfig` field
- [ ] Venue ratio floor/ceiling are `LeagueConfig` fields
- [ ] No bare numeric literal in `inference.py` controls model behavior

### R2.2: `ai/model/trainer.py` — Training parameters

**Current hardcodes (6 items):**

| Line | Value | Target |
|------|-------|--------|
| 44 | `noise_pct=0.005` | `config.training_noise_pct` |
| 47 | `{0: 1.0, 1: 2.0, 2: 1.0}` sample weights | `config.training_sample_weights` |
| 50 | `test_size=0.2` | `config.training_test_split` |
| 82 | `size_mb > 8.0` model size limit | `config.model_max_size_mb` |
| ~30 | `random_seed` (local var, not from config) | `config.random_seed` or `LeagueConfig.xgb_seed` |
| ~68 | `sample_weights` variable with possibly incorrect XGBoost API usage | Fix: use `sample_weight` param in `fit()` correctly |

**Deliverables:**
- [ ] All training params read from config
- [ ] `sample_weight` correctly passed to XGBoost `fit()` call (verify API)
- [ ] Model size limit from config
- [ ] Default values unchanged (backward compatible)

### R2.3: `ai/model/drift.py` — Drift detection thresholds

**Current hardcodes:**

| Line | Value | Target |
|------|-------|--------|
| 25 | `WINDOW = 30` | `config.drift_accuracy_window` |
| 26 | `ACCURACY_FLOOR = 0.35` | `config.drift_accuracy_floor` |

**Deliverables:**
- [ ] Both values read from config
- [ ] Drift detection behavior unchanged with default values

### R2.4: `ai/model/features.py` — Synthetic generation ranges

**Current hardcodes:**

| Line | Value | Issue |
|------|-------|-------|
| 163-165 | `rng.uniform(1500, 200)` Elo generation | Only used for synthetic — will be removed in synthetic data purge |
| 165 | `rng.normal(26, 3)` player age | Same — synthetic only |
| 140-155 | Magic substring matching: `"flag"`, `"ratio"`, `"pct"`, etc. | Fragile; should match feature schema |

**Deliverables:**
- [ ] If synthetic generation stays in `tests/fixtures.py`, generation ranges read from a schema
- [ ] Magic substring matching replaced with explicit feature-type mapping from config
- [ ] `FEATURE_COLUMNS` canonical list moved to `constants.py`

### R2.5: `ai/pipeline/runner.py` — League-specific strings and paths

**Current hardcodes:**

| Location | Value | Target |
|----------|-------|--------|
| Various | `league_id="super_lig"` | `self.config.default_league_id` |
| Various | `"Turkish Q&A Demo"` label | `f"{self.league_config.league_name} Analysis"` |
| Various | File paths with `tr_super_lig_real.json` | `config.data_dir / f"{league_id}_real.json"` |
| ~60-80 | Demo sentiment text samples | Move to `defaults.yaml: ai.demo.sentiment_samples` or locale file |

**Deliverables:**
- [ ] No league name hardcoded as a string literal in `runner.py`
- [ ] All data file paths constructed from `config.data_dir + league_id`
- [ ] Demo content moved to config/locale
- [ ] Pipeline works for any configured league without code changes

### R2.6: `ai/common/telemetry.py` — Stream and timeout constants

**Current hardcodes:**

| Line | Value | Target |
|------|-------|--------|
| 37 | `_MAX_STREAM_LEN = 50_000` | `config.telemetry_max_stream_len` |
| 42 | `socket_connect_timeout=2` | `config.redis_socket_timeout` |

**Deliverables:**
- [ ] Both values read from config
- [ ] Telemetry behavior unchanged with defaults

### Phase R2 Completion Gate

| Check | Command |
|-------|---------|
| No bare literals in `ai/model/` | `grep -nP '(?<![a-zA-Z_])\d+\.?\d*(?![a-zA-Z_])' ai/model/*.py` — only log strings, type hints, indices |
| No league strings in `ai/pipeline/` | `grep -n "super_lig\|Turkish\|Süper Lig" ai/pipeline/` — zero hits |
| All tests pass | `make test` |
| Backtest identical | Run backtest with default config, compare accuracy numbers |

---

## Phase R3: Hardcode Extraction — Scraper & Scheduler

**Goal:** All scraper timeouts, URLs, rates, and scheduler timing are config-driven.  
**Depends on:** R1

### R3.1: `ai/scraper/self_healing.py` — Thresholds and source priority

**Current hardcodes (4 items):**

| Line | Value | Already in Config? | Action |
|------|-------|--------------------|--------|
| 48-52 | `STALE_THRESHOLD_SEC=604800` | Yes: `config.stale_threshold_seconds` | Wire module to read from config instead of module-level constant |
| 48-52 | `STALE_CONFIDENCE_PENALTY=0.5` | Yes: `config.stale_confidence_penalty` | Same — wire to config |
| 48-52 | `FAILURE_THRESHOLD=3` | Yes: `config.source_failure_threshold` | Same |
| 114 | `SOURCE_PRIORITY` list | Partially via `config._source_priority_raw` | Complete the wiring |

**Key issue:** `config.py` already defines these values with env overrides, but `self_healing.py` still has its own module-level constants. The wiring is incomplete.

**Deliverables:**
- [ ] Delete module-level `STALE_THRESHOLD_SEC`, `STALE_CONFIDENCE_PENALTY`, `FAILURE_THRESHOLD` from `self_healing.py`
- [ ] All reads go through `config` instance (injected or imported)
- [ ] `SOURCE_PRIORITY` parsed from `config._source_priority_raw`

### R3.2: `ai/scraper/health.py` — Failure threshold

| Line | Value | Action |
|------|-------|--------|
| 19 | `FAILURE_THRESHOLD = 3` | **Duplicate** of `self_healing.py` and `config.py`. Delete, read from config |

**Deliverables:**
- [ ] `FAILURE_THRESHOLD` deleted from `health.py`
- [ ] Module imports value from config

### R3.3: `ai/scraper/mackolik.py` — Group ID, timeout, user-agent

| Line | Value | Action |
|------|-------|--------|
| 106 | User-Agent string | Read from `config.scrape_user_agent` |
| 112 | `GROUP_TURKEY = 1` | Read from `LeagueConfig.mackolik_group_id` (new field) |
| 228 | `timeout=15` | Read from `config.mackolik_http_timeout` |

**Deliverables:**
- [ ] `GROUP_TURKEY` constant deleted; method accepts `group_id` parameter
- [ ] User-Agent read from config
- [ ] Timeout read from config

### R3.4: `ai/scraper/real_data.py` — URLs, rate limits, aliases

| Line | Value | Action |
|------|-------|--------|
| 24-25 | OpenFootball GitHub URL, football-data.co.uk base URL | Read from `config.scrape_openfootball_base`, `config.scrape_footballdata_base` (already exist as properties) |
| 131 | `rate_limit=1.0` | Read from `config.real_data_rate_limit` |
| 138, 209 | `timeout=15, 10` | Read from `config.scrape_http_timeout`, `config.footballdata_http_timeout` |
| 56-78 | `_HISTORICAL_ALIASES` dict | Move to `locale_tr.yaml` under `team_aliases:` section |

**Deliverables:**
- [ ] All URLs come from config properties
- [ ] `_HISTORICAL_ALIASES` loaded from locale YAML
- [ ] Rate limits and timeouts from config

### R3.5: `ai/scraper/engine.py` — Selector loading and timeouts

| Line | Value | Action |
|------|-------|--------|
| 45 | `league_id="super_lig"` | Read from `config.default_league_id` |
| 45 | `season="2025-2026"` | Read from `config.default_season` |
| 56, 79, 94, 110 | `timeout=10, 10, 30, 5` | Read from respective config timeout fields |

**Deliverables:**
- [ ] Engine constructor accepts `config` parameter
- [ ] All timeouts from config
- [ ] League/season from config, not hardcoded

### R3.6: `ai/scheduler.py` — Cron timing

**Current state:** Scheduler config values already exist in `config.py` (lines 53-58) with env var overrides. Verify `scheduler.py` actually reads from them.

**Deliverables:**
- [ ] `build_default_schedule()` reads all timing from `config` instance
- [ ] No hardcoded `hour=`, `minute=`, `day_of_week=` literals in `scheduler.py`

### Phase R3 Completion Gate

| Check | Command |
|-------|---------|
| No module-level threshold constants | `grep -n "THRESHOLD\|PRIORITY" ai/scraper/*.py` — only imports, no assignments |
| No hardcoded timeouts | `grep -n "timeout=" ai/scraper/*.py` — all reference config fields |
| Scheduler fully config-driven | `grep -n "hour=\|minute=\|day_of_week=" ai/scheduler.py` — only config reads |
| All tests pass | `make test` |

---

## Phase R4: Hardcode Extraction — P2P & Go Server

**Goal:** P2P modules use `P2PConfig` exclusively. Go server uses env vars for everything.  
**Depends on:** R1

### R4.1: P2P module wiring (detailed in R1.4)

Already covered in R1.4. This phase ensures it's complete and verified.

**Additional items:**

| Module | Issue | Action |
|--------|-------|--------|
| `p2p/coordination/election.py:53-57` | Role assignment logic hardcoded (`scraper_mackolik → ranked[0]`) | Parameterize role list via config or make assignment pluggable |
| `p2p/protocol/messages.py:47` | `schema_version = "2.0"` | Move to `P2PConfig.schema_version` with env override |

### R4.2: Go server — eliminate hardcoded credentials

**File:** `server/cmd/main.go`

**Status (2026-04-18):** ✅ RESOLVED by Phase 1.6 of [ROADMAP.md](ROADMAP.md). The Go
source no longer carries any hardcoded credential fallback; it reads the DB
password from `POSTGRES_PASSWORD` and the connection string from `DATABASE_URL`,
defaulting to empty strings. `.env.example` ships a placeholder.

**Historical note (kept for archaeology):** an earlier revision of
`server/cmd/main.go` shipped `negelir_dev_2026` as a fallback default for the
database password. That literal has been removed from source; only deployment
`.env` files (gitignored in production setups) carry an actual value.

**Changes required:**

| Line | Current | Target |
|------|---------|--------|
| ~485-491 | All `getEnvOrDefault("DB_...", "5")` calls | Keep pattern but verify `.env.example` documents every var |
| ~482-483 | `CACHE_MATCHES_TTL_SEC=300`, `CACHE_TEAMS_TTL_SEC=600` | Already env-driven — document in `.env.example` |
| ~195-213 | `LIMIT 50` in SQL query | Make configurable: `MATCHES_QUERY_LIMIT` env var |
| DB password | ~~Hardcoded `negelir_dev_2026` as fallback~~ | ✅ Removed; reads `POSTGRES_PASSWORD` env var, defaults to empty |

**Deliverables:**
- [x] Zero hardcoded credentials in Go source
- [ ] Server refuses to start if `DATABASE_URL` is not set (fail-closed)
- [ ] `LIMIT 50` made configurable
- [ ] All Go env vars documented in `.env.example`

### Phase R4 Completion Gate

| Check | Command |
|-------|---------|
| No hardcoded creds | `grep -r "password\|negelir_dev" server/` — zero hits |
| P2P modules use config | `grep -n "MULTICAST_GROUP\|MAX_MESSAGE_SIZE\|QUORUM" p2p/` — only in `config.py` |
| All tests pass | `make test` |

---

## Phase R5: Performance Optimization

**Goal:** Eliminate unnecessary computation, add caching for hot paths, fix blocking I/O.  
**Depends on:** Nothing (can run in parallel with R2-R4)

### R5.1: TQU regex compilation caching

**File:** `ai/tqu/classifier.py`

**Problem:** `INTENT_PATTERNS` regex patterns are recompiled on every `classify()` call.

**Fix:** Pre-compile patterns at module load time using `re.compile()` and store in a module-level dict.

```python
# Before: patterns recompiled each call
# After: compile once at import time
_COMPILED_PATTERNS = {
    intent: re.compile(pattern, re.IGNORECASE)
    for intent, pattern in INTENT_PATTERNS.items()
}
```

**Impact:** Eliminates regex compilation overhead on every Q&A query.

**Deliverables:**
- [ ] All TQU patterns pre-compiled at module load
- [ ] `classify()` uses `_COMPILED_PATTERNS`
- [ ] No `re.search(raw_string, ...)` in hot paths

### R5.2: Selector JSON singleton loading

**File:** `ai/scraper/engine.py`

**Problem:** `selectors.json` loaded from disk on every `ScrapingEngine.__init__()`.

**Fix:** Load once at module level or use `functools.lru_cache`:

```python
@functools.lru_cache(maxsize=1)
def _load_selectors() -> dict:
    with open(SELECTOR_PATH) as f:
        return json.load(f)
```

**Impact:** Eliminates repeated file I/O for scraping requests.

**Deliverables:**
- [ ] `selectors.json` loaded exactly once per process
- [ ] Subsequent `ScrapingEngine` instances reuse cached selectors

### R5.3: Poisson calculation optimization

**File:** `ai/model/inference.py`

**Problem:** `_compute_score_brackets()` iterates all `home_cap × away_cap` combinations (49+ iterations) per match, computing Poisson PMF pairs for each.

**Fix:** Pre-compute Poisson PMF vectors, then use outer product for the probability matrix:

```python
# Before: nested loop with individual poisson.pmf() calls
# After: vectorized
home_pmf = np.array([poisson.pmf(g, home_xg) for g in range(home_cap)])
away_pmf = np.array([poisson.pmf(g, away_xg) for g in range(away_cap)])
prob_matrix = np.outer(home_pmf, away_pmf)
# Extract brackets from matrix directly
```

**Impact:** Reduces ~49 individual `poisson.pmf()` calls to 2 vectorized operations + 1 outer product.

**Deliverables:**
- [ ] Poisson probability matrix computed via `np.outer()`
- [ ] Score bracket extraction uses matrix slicing
- [ ] Results numerically identical (regression test)

### R5.4: Lazy locale loading

**File:** `ai/common/constants.py`

**Problem:** Locale YAML loaded at module import time. If YAML is unavailable, all locale-dependent constants become empty dicts, silently degrading functionality.

**Fix:** Implement lazy loading with thread-safe initialization:

```python
_locale_data = None
_locale_lock = threading.Lock()

def _ensure_locale():
    global _locale_data
    if _locale_data is not None:
        return
    with _locale_lock:
        if _locale_data is not None:
            return
        _locale_data = load_locale()
        # ... build all maps

def get_team_map() -> dict[str, str]:
    _ensure_locale()
    return _TEAM_MAP
```

**Impact:** Module import no longer blocks on file I/O. Locale loaded on first access.

**Deliverables:**
- [ ] Locale loaded lazily on first access, not at import
- [ ] Thread-safe initialization
- [ ] Clear error message if locale fails to load (not silent empty dicts)
- [ ] All callers use accessor functions instead of bare module-level dicts

### R5.5: Rolling statistics caching in `real_features.py`

**File:** `ai/model/real_features.py`

**Problem:** `_recent(20)` called inside loops, recalculates mean/variance every time for Bayesian draw calculation.

**Fix:** Cache rolling statistics per team using `functools.lru_cache` or an internal memoization dict keyed by `(team, window_size)`.

**Deliverables:**
- [ ] Rolling stats computed once per (team, window) combination
- [ ] Cache invalidated when new match data arrives
- [ ] Measurable reduction in redundant stat calculations

### R5.6: Mackolik response caching

**File:** `ai/scraper/mackolik.py`

**Problem:** HTTP responses from Mackolik API not cached. Same data fetched repeatedly if requested within a short window.

**Fix:** Use Redis (already available) for short-lived response caching:

```python
cache_key = f"mackolik:fixtures:{season_id}"
cached = redis.get(cache_key)
if cached:
    return json.loads(cached)
# ... fetch from API
redis.setex(cache_key, ttl=300, value=json.dumps(data))
```

**Deliverables:**
- [ ] Mackolik fixture responses cached in Redis with configurable TTL (default 5 min)
- [ ] Cache key includes season ID and group ID
- [ ] Cache bypass option for forced refresh

### Phase R5 Completion Gate

| Check | Method |
|-------|--------|
| Regex pre-compiled | `grep -n "re.search\|re.match" ai/tqu/` — all use compiled patterns |
| Selector loaded once | Add debug log on load; verify single log line per process |
| Poisson vectorized | Unit test: compare old vs new bracket results — identical |
| Lazy locale verified | Import `constants` without YAML on disk — no crash, deferred error |
| Benchmark improvement | profile key paths before/after; expect measurable improvement in scrape + inference loops |

---

## Phase R6: Dead Code Removal & Cleanup

**Goal:** Remove stale code, fix inconsistencies, reduce maintenance surface.  
**Depends on:** R2-R4 (hardcode extraction may change the code being cleaned)

### R6.1: Dead methods and unused code

| File | Dead Code | Action |
|------|-----------|--------|
| `ai/pipeline/runner.py:105` | `_load_cached_matches()` — referenced but implementation incomplete | Complete implementation or remove |
| `ai/pipeline/runner.py:250-270` | `_build_real_features()` — only builds stub | Complete or remove |
| `ai/pipeline/runner.py:30` | Import `TEAM_STRENGTH` — never used | Remove unused import |
| `ai/scraper/engine.py:99-105` | `fetch_teams_from_server()` — never called anywhere | Remove dead method |
| `ai/model/inference.py:160-168` | `_venue_adjusted_xg()` — computed values unused in final calc | Integrate into calculation or remove |
| `ai/common/config.py:181-186` | `scrape_sources` property — never called | Remove or integrate into code that needs source list |
| `p2p/protocol/tcp_transport.py:60-80` | `_create_ssl_context()` — TLS never enabled | Keep but add `# TODO: enable for production` comment. Do not remove security infrastructure. |
| `ai/model/trainer.py:68` | `sample_weights` variable — may not correctly map to XGBoost API | Verify XGBoost `sample_weight` API; fix or remove |

**Deliverables:**
- [ ] Each item above resolved (removed, completed, or documented)
- [ ] No unused imports in modified files
- [ ] All tests pass after removals

### R6.2: Inconsistent patterns

| Pattern | Files | Fix |
|---------|-------|-----|
| Derby definitions in multiple places | `league_config.py`, `tqu/questions.py` | Single source: `LeagueConfig.derbies`. TQU queries `LeagueConfig`, not hardcoded sets |
| Team data in 3 locations | `locale_tr.yaml` (UUIDs), `league_config.py` (strengths), `tqu/questions.py` (names) | All team data flows from `locale_tr.yaml` → `constants.py` → rest of codebase |
| Feature columns in `features.py`, ranges in `inference.py` | `ai/model/features.py`, `ai/model/inference.py` | Unify: feature definitions + ranges in one place (`constants.py` or `defaults.yaml`) |
| Mackolik season IDs hardcoded per year | `ai/common/config.py:94-118` | Already env-driven but static. Add `MackolikClient.discover_seasons()` integration as future improvement |

**Deliverables:**
- [ ] Derby data has single source
- [ ] Team data flows from locale YAML only
- [ ] Feature definitions co-located with their validation ranges

### R6.3: CSS selectors versioning

**File:** `ai/scraper/selectors.json`

**Problem:** CSS selectors hardcoded in JSON with no versioning. If Mackolik changes their DOM, requires manual JSON edit + redeploy.

**Fix:** Add schema fingerprinting integration (already implemented in `schema_fingerprint.py` and `schema_trainer.py`):

1. Add `_version` and `_last_verified` metadata to `selectors.json`
2. Self-healing engine (`self_healing.py`) should automatically update selectors when schema change detected
3. Gossip protocol distributes updated selectors across P2P network (already have `schema_gossip.py`)

**Deliverables:**
- [ ] `selectors.json` includes version metadata
- [ ] Self-healing engine updates selectors on schema change
- [ ] Updated selectors propagated via gossip

### R6.4: Makefile variable extraction

**File:** `Makefile`

**Problem:** Hardcoded defaults in make targets (`25` nodes, `3` weeks, etc.).

**Fix:**
```makefile
# At top of Makefile
P2P_NODE_COUNT ?= 25
BACKTEST_WEEKS ?= 3
LEAGUE ?= super_lig
```

**Deliverables:**
- [ ] All magic numbers in Makefile are `?=` variables at top
- [ ] `make help` shows configurable parameters

### Phase R6 Completion Gate

| Check | Command |
|-------|---------|
| No unused imports | `ruff check --select F401 ai/ p2p/` (or manual grep) |
| Derby single source | `grep -rn "derby\|DERBY" ai/ p2p/ --include="*.py"` — only in `league_config.py` and `constants.py` |
| Dead code removed | Manual review of items in R6.1 list |
| All tests pass | `make test` |

---

## Phase R7: Config Documentation & Validation

**Goal:** Complete `.env.example`, add startup validation, make config discoverable.  
**Depends on:** R1-R4 (all config extraction complete)

### R7.1: Comprehensive `.env.example`

Create `.env.example` with every env var introduced in R1-R4, organized by subsystem:

```env
# ═══════════════════════════════════════════
# Negelir — Environment Configuration
# Copy to .env and customize for your environment.
# All values below are defaults — the system runs with
# zero custom variables.
# ═══════════════════════════════════════════

# ── Infrastructure ──────────────────────
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=negelir
POSTGRES_USER=negelir
POSTGRES_PASSWORD=          # REQUIRED — no default
REDIS_HOST=localhost
REDIS_PORT=6379
SERVER_URL=http://localhost:8080

# ── AI Model ────────────────────────────
AI_DEVICE=auto              # auto|cpu|cuda
AI_LOG_LEVEL=DEBUG
NEGELIR_DEFAULT_LEAGUE_ID=super_lig
NEGELIR_DEFAULT_SEASON=2025-2026

# ── XGBoost (via LeagueConfig) ──────────
NEGELIR_XGB_WEIGHT=0.35
NEGELIR_DIXON_COLES_RHO=-0.13

# ── Training ────────────────────────────
NEGELIR_TRAINING_NOISE_PCT=0.005
NEGELIR_TRAINING_TEST_SPLIT=0.2
NEGELIR_MODEL_MAX_SIZE_MB=8.0

# ── Scraping ────────────────────────────
NEGELIR_MACKOLIK_HTTP_TIMEOUT=15
NEGELIR_SERVER_FETCH_TIMEOUT=10
SCRAPE_RATE_LIMIT_SECONDS=5
NEGELIR_REAL_DATA_RATE_LIMIT=1.0

# ── Self-Healing ────────────────────────
NEGELIR_STALE_THRESHOLD_SECONDS=604800
NEGELIR_SOURCE_FAILURE_THRESHOLD=3

# ── Scheduler ───────────────────────────
NEGELIR_SCHEDULE_DAILY_SCRAPE_HOUR=6
NEGELIR_SCHEDULE_OUTCOME_CHECK_HOUR=22
NEGELIR_SCHEDULE_RETRAIN_DAY=sun
NEGELIR_SCHEDULE_RETRAIN_HOUR=3

# ── P2P Network ─────────────────────────
P2P_MULTICAST_GROUP=239.42.42.1
P2P_TCP_PORT=9742
P2P_SCHEMA_QUORUM=3
P2P_MESSAGE_TTL_HOURS=168

# ── Go Server ───────────────────────────
PORT=8080
DB_MAX_CONNS=10
HTTP_READ_TIMEOUT_SEC=10
HTTP_WRITE_TIMEOUT_SEC=30
CACHE_MATCHES_TTL_SEC=300
```

### R7.2: Startup config validation

**File:** `ai/common/config.py` (add `validate()` method)

```python
def validate(self) -> list[str]:
    """Return list of config warnings/errors."""
    issues = []
    if not self.pg_password:
        issues.append("POSTGRES_PASSWORD not set")
    if self.stale_threshold_seconds < 3600:
        issues.append(f"STALE_THRESHOLD_SECONDS={self.stale_threshold_seconds} seems too low (< 1 hour)")
    if self.mackolik_http_timeout < 5:
        issues.append(f"MACKOLIK_HTTP_TIMEOUT={self.mackolik_http_timeout} may cause premature timeouts")
    # ... more sanity checks
    return issues
```

Call at startup in `ai/main.py` and log warnings.

**Deliverables:**
- [ ] `Config.validate()` catches common misconfigurations
- [ ] `P2PConfig.validate()` same
- [ ] Startup logs list all active config overrides (so operators can verify)
- [ ] Missing required values cause immediate startup failure (fail-closed)

### R7.3: Config dump command

Add a `make config-dump` target that prints the resolved config (defaults + env overrides) for debugging:

```
$ make config-dump
Negelir Configuration (resolved)
─────────────────────────────────
ai.device = auto
ai.log_level = DEBUG
ai.model.xgb_weight = 0.35
ai.scraping.mackolik_http_timeout = 15  [override: NEGELIR_MACKOLIK_HTTP_TIMEOUT=15]
...
```

### R7.4: Update `docker-compose.yml`

Ensure `docker-compose.yml` uses `env_file: .env` pattern instead of inline environment blocks for every service.

**Deliverables:**
- [ ] `docker-compose.yml` references `.env` file
- [ ] Each service's env vars documented in `.env.example`
- [ ] Removing `.env` file falls back to documented defaults

### Phase R7 Completion Gate

| Check | Method |
|-------|--------|
| `.env.example` complete | Every env var in codebase has a corresponding line in `.env.example` |
| Startup validation works | Unset `POSTGRES_PASSWORD`, start AI service → clear error message |
| Config dump accurate | `make config-dump` matches actual runtime config |
| Docker Compose env-file | `docker compose config` shows all vars resolved from `.env` |

---

## Appendix A: Full Hardcode Inventory

Complete list of every hardcoded value found during the audit, organized by file.

### `ai/model/inference.py`
- Line 42-77: `FEATURE_RANGES` dict (12 tuples)
- Line 172: `rho` parameter (-0.13)
- Line 227: Elo divisor (600.0)
- Line 230-240: Venue ratio bounds (0.7–1.4)
- Line 163-178: Poisson cap ranges (8, 6)

### `ai/model/trainer.py`
- Line 44: `noise_pct=0.005`
- Line 47: `sample_weights={0:1.0, 1:2.0, 2:1.0}`
- Line 50: `test_size=0.2`
- Line 82: `size_mb > 8.0`
- Line 68: `sample_weights` mapping

### `ai/model/drift.py`
- Line 25: `WINDOW = 30`
- Line 26: `ACCURACY_FLOOR = 0.35`

### `ai/model/features.py`
- Line 163-165: `rng.uniform(1500, 200)` Elo generation
- Line 165: `rng.normal(26, 3)` age distribution
- Line 140-155: Magic substring matching for feature ranges

### `ai/common/config.py`
- Line 27-28: `default_season="2025-2026"`
- Line 94-118: Mackolik season ID mappings (per-year)
- Line 120-124: OpenFootball season directories
- Line 127-130: Football-data.co.uk season codes

### `ai/common/constants.py`
- Line 11: `N_FEATURES = 130`

### `ai/common/telemetry.py`
- Line 37: `_MAX_STREAM_LEN = 50_000`
- Line 42: `socket_connect_timeout=2`

### `ai/common/league_config.py`
- Line 12-22: Elo system constants (1500.0, 32.0, 65.0)
- Line 27-31: Poisson limits (7, 5, 7, 7, 5, 6)
- Line 36: `dixon_coles_rho=-0.13`
- Line 42: `xgb_weight=0.35`
- Line 76-97: Derby frozensets (inline)
- Line 52-68: XGBoost hyperparameters (per-league)

### `ai/scraper/engine.py`
- Line 45: `league_id="super_lig"`, `season="2025-2026"`
- Line 56, 79, 94, 110: `timeout=10, 10, 30, 5`

### `ai/scraper/mackolik.py`
- Line 106: User-Agent string
- Line 112: `GROUP_TURKEY = 1`
- Line 228: `timeout=15`

### `ai/scraper/real_data.py`
- Line 24-25: OpenFootball/football-data URLs
- Line 131: `rate_limit=1.0`
- Line 138, 209: `timeout=15, 10`
- Line 56-78: `_HISTORICAL_ALIASES` dict

### `ai/scraper/self_healing.py`
- Line 48-52: `STALE_THRESHOLD_SEC=604800`, `STALE_CONFIDENCE_PENALTY=0.5`, `FAILURE_THRESHOLD=3`
- Line 114: `SOURCE_PRIORITY` list

### `ai/scraper/health.py`
- Line 19: `FAILURE_THRESHOLD = 3` (duplicate of self_healing)

### `ai/scheduler.py`
- Cron values: `hour=6`, `hour=22`, `day_of_week="sun"`, `hour=3`, `minutes=5`

### `ai/pipeline/runner.py`
- Various: `league_id="super_lig"`
- Various: `"Turkish Q&A Demo"` label
- Various: File paths with league name
- Line 60-80: Demo sentiment samples

### `p2p/node/discovery.py`
- Line 15-17: `MULTICAST_GROUP`, `MULTICAST_PORT`, `DISCOVERY_INTERVAL_SEC`, `ANNOUNCE_TTL`

### `p2p/protocol/tcp_transport.py`
- Line 20: `MAX_MESSAGE_SIZE = 1048576`

### `p2p/protocol/transport.py`
- Line 58-61: `latency_ms_range`, `drop_rate`, `k_neighbors`, `gossip_fanout`

### `p2p/protocol/messages.py`
- Line 47: `schema_version = "2.0"`, `ttl_hours=168`

### `p2p/coordination/schema_gossip.py`
- Line 47-49: `QUORUM=3`, `VOTE_TIMEOUT=600`, `CONFIDENCE_FLOOR=0.6`

### `p2p/node/peer.py`
- Line 77: `ttl_hours=168`

### `p2p/coordination/election.py`
- Line 53-57: Hardcoded role assignment logic

### `server/cmd/main.go`
- Line 485-491: All timeout defaults (5s, 5s, 10s, 30s, 5s)
- Line 482-483: Cache TTLs (300s, 600s)
- Line 483: Default ports (5432, 6379)
- Line 483: Server port (8080)
- Line 485: `DB_MAX_CONNS=10`
- Line 195-213: SQL `LIMIT 50`
- ~~DB password: `negelir_dev_2026` as fallback~~ ✅ Resolved (Phase 1.6)

---

## Appendix B: Config Conflict Resolution Matrix

| Value | `config.py` | `league_config.py` | Other File | Winner | Action |
|-------|-------------|---------------------|------------|--------|--------|
| `xgb_weight` (0.35) | Line 93 (unused) | Field | — | `LeagueConfig` | Remove from `config.py` |
| `n_estimators` (300 vs 350) | — | 300 | `device.py` had 350 | `LeagueConfig` | `device.py` already fixed; delete leftover |
| `learning_rate` (0.08 vs 0.06) | — | 0.08 | `device.py` had 0.06 | `LeagueConfig` | `device.py` already fixed; delete leftover |
| `mackolik_group_id` (1) | Line 29 | — | `mackolik.py:112` | `LeagueConfig` (new) | Add to `LeagueConfig`, remove from both |
| `FAILURE_THRESHOLD` (3) | Line 63-64 | — | `health.py:19`, `self_healing.py:48` | `Config` | Delete from health.py + self_healing.py |
| `dixon_coles_rho` (-0.13) | — | Field | `inference.py:50` | `LeagueConfig` | Remove from inference.py |
| `stale_threshold_seconds` (604800) | Line 61-62 | — | `self_healing.py:48` | `Config` | Delete from self_healing.py |
| `SOURCE_PRIORITY` list | Line 61 (raw) | — | `self_healing.py:114` | `Config` | Wire self_healing to config |
| `timeout=15` (Mackolik) | Line 48 | — | `mackolik.py:228` | `Config` | Wire mackolik to config |
| Data source URLs | Lines 79-89 | — | `real_data.py:24-25` | `Config` | Wire real_data to config properties |

---

## Appendix C: Execution Priority

Recommended implementation order for maximum impact with minimum risk:

### Sprint 1 (Quick Wins)
1. **R1.5** — Make `N_FEATURES` derived (5 min, eliminates crash risk)
2. **R5.1** — Pre-compile TQU regex patterns (30 min, immediate perf win)
3. **R5.2** — Singleton selector loading (15 min, reduces I/O)
4. **R6.1** — Remove dead imports and unused methods (1 hour)

### Sprint 2 (Config Foundation)
5. **R1.1** — Create `defaults.yaml` (2 hours)
6. **R1.2** — Refactor config loader to use YAML (3 hours)
7. **R1.3** — Resolve config conflicts (1 hour)
8. **R7.1** — Create `.env.example` (1 hour)

### Sprint 3 (Hardcode Extraction)
9. **R2.1-R2.6** — AI engine hardcode extraction (4 hours)
10. **R3.1-R3.6** — Scraper/scheduler hardcode extraction (3 hours)
11. **R1.4** — Wire P2P modules to `P2PConfig` (2 hours)
12. **R4.2** — Go server credential removal (1 hour)

### Sprint 4 (Performance & Polish)
13. **R5.3** — Poisson vectorization (2 hours)
14. **R5.4** — Lazy locale loading (1 hour)
15. **R5.5-R5.6** — Rolling stats cache + Mackolik response cache (2 hours)
16. **R6.2-R6.4** — Consistency fixes + Makefile cleanup (2 hours)
17. **R7.2-R7.4** — Config validation + dump + docker-compose (2 hours)
