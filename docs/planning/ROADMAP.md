# Negelir — Project Roadmap

**Date:** 2026-04-18  
**Status:** Planning  
**Supersedes:** [MULTI_LEAGUE_ROADMAP.md](MULTI_LEAGUE_ROADMAP.md) (deprecated), [ROADMAP.md](ROADMAP.md) (deprecated)  

---

## Guiding Principles

These four principles apply to **every phase** and **every code change** in this roadmap:

1. **Zero Hardcoded Values** — Every configurable value (threshold, timeout, path, port, URL, schedule, weight, hyperparameter) must be driven by config files, environment variables, or `LeagueConfig`. Magic numbers in code are forbidden.
2. **Zero Synthetic Training Data** — The AI model must never train on generated/fake data in production. All training data must be scraped from real sources. Synthetic data is permitted only in files under `tests/` and only when explicitly marked as debug/test fixtures.
3. **Full-System Training & Testing** — "Training the AI" means the full pipeline: scrape → validate → train → P2P simulation → job distribution → proofreading → ensemble prediction → outcome verification. Isolated model training is insufficient.
4. **Phase-Gated Execution** — Each phase has explicit completion criteria. A phase is not complete until every subphase meets its requirements. No skipping ahead.

---

## Phase Overview

| Phase | Name | Focus | Depends On |
|---|---|---|---|
| **1** | Hardcode Elimination | Remove all hardcoded values project-wide | — |
| **2** | Synthetic Data Purge | Remove all fake data paths from production code | Phase 1 |
| **3** | Full-System Training Pipeline | Wire AI training through P2P + orchestrator + proofreader | Phase 2 |
| **4** | Multi-League Foundation | League-aware data layer & config | Phase 1 |
| **5** | Multi-League Data Import | Bulk historical data for top 5 European leagues | Phase 4 |
| **6** | Live Multi-League Scraping | Real-time Mackolik scraping for multiple leagues | Phase 5 |
| **7** | Multi-Locale NLP Stack | Foreign team/league name handling in Turkish UI | Phase 4 |
| **8** | Model Strategy & Experimentation | Global vs per-league model architecture | Phase 5 |
| **9** | Cup & Knockout Competitions | Champions League, domestic cups | Phase 6 |
| **10** | Lower Divisions & Full İddaa | TFF 1. Lig, remaining İddaa-listed leagues | Phases 5-8 |

```
Phase 1 ──→ Phase 2 ──→ Phase 3
  │
  └──→ Phase 4 ──→ Phase 5 ──→ Phase 6 ──→ Phase 9
         │              │            │
         │              └──→ Phase 8 ┘
         │
         └──→ Phase 7 ──────────────────→ Phase 10
```

---

## Phase 1: Hardcode Elimination

**Goal:** Every configurable value in the project is driven by config, env vars, or `LeagueConfig`. Zero magic numbers in business logic.  
**Depends on:** Nothing  

### Subphase 1.1: Centralize AI Configuration Constants

**Files:** `ai/common/config.py`, new `ai/common/defaults.yaml`

All constants currently scattered across source files must move into a single config layer that reads from env vars with documented defaults.

| Current Location | Hardcoded Value | Target Location |
|---|---|---|
| `ai/model/inference.py:47` | `XGB_WEIGHT = 0.35` | `LeagueConfig.xgb_ensemble_weight` |
| `ai/model/inference.py:50` | `DIXON_COLES_RHO = -0.13` | `LeagueConfig.dixon_coles_rho` (already exists, remove duplicate) |
| `ai/model/inference.py:154` | `max(0.3, ...)` min xG floor | `LeagueConfig.min_xg_floor` |
| `ai/model/inference.py:163-178` | `range(8)`, `range(6)` Poisson caps | `LeagueConfig.poisson_max_home_goals`, `poisson_max_away_goals` |
| `ai/model/drift.py:25` | `WINDOW = 30` | `config.drift_accuracy_window` |
| `ai/model/drift.py:26` | `ACCURACY_FLOOR = 0.35` | `config.drift_accuracy_floor` |
| `ai/model/trainer.py:44` | `noise_pct=0.005` | `config.training_noise_pct` |
| `ai/model/trainer.py:47` | `{0: 1.0, 1: 2.0, 2: 1.0}` sample weights | `config.training_sample_weights` |
| `ai/model/trainer.py:50` | `test_size=0.2` | `config.training_test_split` |
| `ai/model/trainer.py:82` | `size_mb > 8.0` model size limit | `config.model_max_size_mb` |
| `ai/common/telemetry.py:37` | `_MAX_STREAM_LEN = 50_000` | `config.telemetry_max_stream_len` |
| `ai/common/telemetry.py:42` | `socket_connect_timeout=2` | `config.redis_socket_timeout` |

**Requirements to complete 1.1:**
- [ ] Every value above reads from `config.py` or `LeagueConfig`
- [ ] Each has a documented env var override (e.g., `NEGELIR_XGB_WEIGHT`)
- [ ] `defaults.yaml` exists with all default values and inline comments
- [ ] No value in `ai/model/` is a bare literal that controls behavior

### Subphase 1.2: Centralize XGBoost Hyperparameters

**Files:** `ai/model/device.py`, `ai/common/league_config.py`

Currently `device.py` defines its own hyperparams that **conflict** with `LeagueConfig`:

| Parameter | `device.py` value | `LeagueConfig` value | Resolution |
|---|---|---|---|
| `n_estimators` | 350 | 300 | Use `LeagueConfig` as single source of truth |
| `max_depth` | 4 | 4 | Same — source from `LeagueConfig` |
| `learning_rate` | 0.06 | 0.08 | Use `LeagueConfig` |
| `seed` | 42 | — | Add to config |

**Change:** `device.py:get_xgb_params()` must accept `LeagueConfig` and use its hyperparams. Delete all hardcoded param dicts from `device.py`.

**Requirements to complete 1.2:**
- [ ] `get_xgb_params(league_config)` signature implemented
- [ ] Zero hardcoded hyperparameter dicts in `device.py`
- [ ] `LeagueConfig` is the single source for all XGBoost hyperparams
- [ ] Training with default config produces identical results to current hardcoded values (regression test)

### Subphase 1.3: Centralize Scraper Configuration

**Files:** `ai/scraper/engine.py`, `ai/scraper/mackolik.py`, `ai/scraper/real_data.py`, `ai/scraper/self_healing.py`

| Current Location | Hardcoded Value | Target Location |
|---|---|---|
| `engine.py:45` | `league_id="super_lig"`, `season="2025-2026"` | `config.default_league_id`, `config.default_season` |
| `engine.py:56,79,94,110` | `timeout=10,10,30,5` | `config.server_fetch_timeout`, `config.scrape_trigger_timeout`, `config.health_check_timeout` |
| `mackolik.py:112` | `GROUP_TURKEY = 1` | `LeagueConfig.mackolik_group_id` |
| `mackolik.py:228` | `timeout=15` | `config.mackolik_http_timeout` |
| `real_data.py:131` | `rate_limit=1.0` | `config.scrape_rate_limit` |
| `real_data.py:138,209` | `timeout=15,10` | `config.scrape_http_timeout` |
| `real_data.py:56-78` | `_HISTORICAL_ALIASES` dict | Move to `locale_tr.yaml` under `team_aliases:` |
| `self_healing.py:114` | `SOURCE_PRIORITY` list | `config.source_priority` (already partially env-driven, complete it) |
| `self_healing.py:121` | `STALE_THRESHOLD_SEC = 604800` | `config.stale_threshold_seconds` |
| `self_healing.py:124` | `STALE_CONFIDENCE_PENALTY = 0.5` | `config.stale_confidence_penalty` |
| `self_healing.py:127` | `FAILURE_THRESHOLD = 3` | `config.source_failure_threshold` |

**Requirements to complete 1.3:**
- [ ] Every scraper reads timeouts, thresholds, and IDs from config
- [ ] `_HISTORICAL_ALIASES` moved to locale YAML
- [ ] Mackolik group ID comes from `LeagueConfig`, not a class constant
- [ ] All `timeout=` calls reference config properties
- [ ] Scrapers work identically with default config values (no behavior change)

### Subphase 1.4: Centralize Scheduler Configuration

**Files:** `ai/scheduler.py`

| Current Location | Hardcoded Value | Target Location |
|---|---|---|
| Line ~95 | `hour=6, minute=0` (daily scrape) | `config.schedule_daily_scrape_hour/minute` |
| Line ~96 | `hour=22, minute=0` (outcome check) | `config.schedule_outcome_check_hour/minute` |
| Line ~97 | `day_of_week="sun", hour=3` (retrain) | `config.schedule_retrain_day/hour` |
| Line ~98 | `minutes=5` (heartbeat) | `config.schedule_heartbeat_minutes` |

**Requirements to complete 1.4:**
- [ ] `build_default_schedule()` reads all timing from config
- [ ] Each schedule parameter has an env var override
- [ ] Scheduler still works with zero env vars (uses sane defaults)

### Subphase 1.5: Centralize P2P Network Constants

**Files:** `p2p/node/discovery.py`, `p2p/protocol/tcp_transport.py`, `p2p/protocol/transport.py`, `p2p/protocol/messages.py`, `p2p/coordination/schema_gossip.py`, `p2p/node/peer.py`

| Current Location | Hardcoded Value | Target |
|---|---|---|
| `discovery.py:18-21` | `MULTICAST_GROUP/PORT/INTERVAL/TTL` | `p2p_config.multicast_group`, `.port`, `.interval`, `.ttl` |
| `tcp_transport.py:17` | `MAX_MESSAGE_SIZE = 1MB` | `p2p_config.max_message_size` |
| `tcp_transport.py:23` | `port=9742` | `p2p_config.tcp_port` |
| `transport.py:58-61` | `latency_ms_range`, `drop_rate`, `k_neighbors`, `gossip_fanout` | `p2p_config.sim_latency_range`, `.sim_drop_rate`, etc. |
| `messages.py:19` | `ttl_hours=168` | `p2p_config.message_ttl_hours` |
| `schema_gossip.py:47-49` | `QUORUM=3`, `VOTE_TIMEOUT=600`, `CONFIDENCE_FLOOR=0.6` | `p2p_config.schema_quorum`, etc. |
| `peer.py:77` | `ttl_hours=168` | `p2p_config.data_ttl_hours` |
| `simulation/runner.py:307-310` | `P2P_NODE_COUNT`, `P2P_SIMULATION_MATCHES`, `P2P_BASE_PORT` | Already env vars — document them |

**Approach:** Create `p2p/config.py` with a `P2PConfig` dataclass mirroring the pattern in `ai/common/config.py`.

**Requirements to complete 1.5:**
- [ ] `p2p/config.py` with `P2PConfig` dataclass exists
- [ ] All P2P modules read from `P2PConfig`, not module-level constants
- [ ] Each constant has an env var override documented
- [ ] P2P simulation runs identically with default config

### Subphase 1.6: Centralize Go Server Constants

**Files:** `server/cmd/main.go`

| Current Location | Hardcoded Value | Target |
|---|---|---|
| Line 31 | DB connection string with password | `DATABASE_URL` env var (already partially done — verify no fallback to hardcoded creds) |
| Line 36 | `MaxConns = 10` | `DB_MAX_CONNS` env var |
| Line 37 | `ConnectTimeout = 5s` | `DB_CONNECT_TIMEOUT` env var |
| Line 62 | `redis:6379` | `REDIS_URL` env var (already partially done — verify) |
| Line 93 | `8080` | `PORT` env var (already partially done — verify) |
| Lines 96-97 | `ReadTimeout: 10s`, `WriteTimeout: 30s` | `HTTP_READ_TIMEOUT`, `HTTP_WRITE_TIMEOUT` env vars |

**Requirements to complete 1.6:**
- [ ] Go server reads every operational parameter from env vars
- [ ] No hardcoded credentials in source code (the `negelir_dev_2026` password must go)
- [ ] `docker-compose.yml` sets all env vars for server container
- [ ] Fallback defaults are documented in server README or env template

### Subphase 1.7: Centralize Pipeline & Data Paths

**Files:** `ai/pipeline/runner.py`, `ai/model/real_features.py`, `ai/model/features.py`

| Current Location | Hardcoded Value | Target |
|---|---|---|
| `runner.py` | `"/data/tr_super_lig_real.json"` | `config.data_dir / f"{league_id}_real.json"` |
| `runner.py` | `"league_id": "super_lig"` | `self.league_config.league_id` |
| `runner.py` | `"Turkish Q&A Demo"` | `f"{league_config.league_name} Analysis"` |
| `real_features.py` | `data/tr_super_lig_real.json` | `config.data_dir / f"{league_id}_real.json"` |
| `real_features.py` | `DERBIES_SET` from Turkish constants | `league_config.derbies` |
| `real_features.py` | `MACKOLIK_ID_MAP` from Turkish constants | League-specific locale lookup |
| `features.py:25-44` | `FEATURE_RANGES` dict | Move to `defaults.yaml` under `feature_validation:` |

**Requirements to complete 1.7:**
- [ ] No file path in `ai/` contains a league name as a hardcoded string
- [ ] All data paths are constructed from `config.data_dir` + `league_id`
- [ ] Demo/label strings reference `league_config.league_name`
- [ ] `FEATURE_RANGES` loaded from config, not hardcoded in source

### Subphase 1.8: Environment Template & Documentation

**Files:** New `.env.example`, update `docs/guides/SETUP.md`

Create a comprehensive `.env.example` that documents every configurable value introduced in subphases 1.1-1.7, grouped by subsystem:

```env
# === AI Model ===
NEGELIR_XGB_WEIGHT=0.35
NEGELIR_TRAINING_NOISE_PCT=0.005
NEGELIR_TRAINING_TEST_SPLIT=0.2
NEGELIR_MODEL_MAX_SIZE_MB=8.0
...

# === Scraping ===
NEGELIR_MACKOLIK_TIMEOUT=15
NEGELIR_SCRAPE_RATE_LIMIT=1.0
...

# === P2P Network ===
P2P_MULTICAST_GROUP=239.42.42.1
P2P_TCP_PORT=9742
...

# === Go Server ===
DATABASE_URL=postgres://...
REDIS_URL=redis:6379
...

# === Scheduler ===
NEGELIR_SCRAPE_HOUR=6
NEGELIR_RETRAIN_DAY=sun
...
```

**Requirements to complete 1.8:**
- [ ] `.env.example` exists with every env var and its default
- [ ] `docs/guides/SETUP.md` references `.env.example` as the canonical config reference
- [ ] `docker-compose.yml` uses `env_file: .env` pattern
- [ ] Running the project with zero custom env vars works identically to current behavior

### Phase 1 Completion Gate

| Requirement | How to Verify |
|---|---|
| Zero bare literals in business logic | `grep` audit: no numeric/string literals in `ai/model/`, `ai/scraper/`, `ai/pipeline/`, `p2p/` outside of imports, log messages, and type hints |
| All config has env var overrides | Every key in `.env.example` maps to a property in `config.py` or `P2PConfig` |
| No behavior change | Full test suite passes, backtest produces identical results, P2P simulation runs |
| No hardcoded credentials | `grep -r "password\|negelir_dev" server/ ai/ p2p/` returns zero hits outside `.env.example` |

---

## Phase 2: Synthetic Data Purge

**Goal:** Remove all synthetic/fake data generation from production code paths. Real scraping is the only data source for training. Synthetic data may only exist in `tests/` directories.  
**Depends on:** Phase 1 (config must be centralized first so scraping works reliably)

### Subphase 2.1: Remove Synthetic Fallback from Trainer

**File:** `ai/model/trainer.py`

Current behavior (lines 33-40):
```python
if use_real_data:
    try:
        X, y = extract_real_dataset(min_history=5)
    except Exception as exc:
        log.warning("falling back to synthetic")
        X, y = generate_synthetic_dataset(n_matches=1000, seed=42)
```

**Change:** Remove the `except` fallback. If real data extraction fails, training **must fail loudly** with a clear error message telling the operator what's missing and how to fix it.

```python
def train_model(save_path=None):
    X, y = extract_real_dataset(min_history=5)
    # No fallback. If this fails, training stops.
```

Also remove the `use_real_data` parameter entirely — there's no "synthetic mode" anymore.

**Requirements to complete 2.1:**
- [ ] `trainer.py` has no import of `generate_synthetic_dataset`
- [ ] `use_real_data` parameter removed from `train_model()` signature
- [ ] Training failure produces actionable error: which league, how many matches found vs required
- [ ] `train_model()` requires minimum match count (configurable, default 100)

### Subphase 2.2: Remove Synthetic Fallback from Pipeline Runner

**File:** `ai/pipeline/runner.py`

Current behavior: Multiple fallback paths that generate synthetic matches when real data isn't available.

**Change:** `_load_cached_matches()` returns real data or raises. `_generate_synthetic_matches()` method is deleted entirely.

**Requirements to complete 2.2:**
- [ ] `_generate_synthetic_matches()` deleted
- [ ] No import of `generate_synthetic_dataset` in `runner.py`
- [ ] Pipeline fails with descriptive error if cached data doesn't exist
- [ ] Error message includes: "Run `make scrape --league {league_id}` first"

### Subphase 2.3: Remove Synthetic Fallback from P2P Simulation

**File:** `p2p/simulation/runner.py`

Current behavior (lines 100-145): If `tr_super_lig_real.json` doesn't exist, falls back to a hardcoded dict with two fake matches.

**Change:** P2P simulation requires real data. If data doesn't exist, fail with instructions to scrape first.

**Requirements to complete 2.3:**
- [ ] Hardcoded fallback match dicts deleted from `simulation/runner.py`
- [ ] Simulation startup validates data file exists and has minimum match count
- [ ] Error message includes scrape command to run

### Subphase 2.4: Quarantine Synthetic Data Generator

**Files:** `ai/model/features.py` (the `generate_synthetic_dataset` function), `data/generate_match_data.py`, `data/tr_super_lig_2024_25.json`

These files contain synthetic data generation that was useful for PoC but is now technical debt.

**Change:**
- Move `generate_synthetic_dataset()` from `ai/model/features.py` to `ai/tests/fixtures.py` (only used by unit tests)
- Move `data/generate_match_data.py` to `ai/tests/generate_test_data.py`
- Delete `data/tr_super_lig_2024_25.json` (the synthetic season file with `"generated": true`)
- Add a guard in `model/features.py`: remove the function, keep `inject_noise()` (it operates on real data)

**Requirements to complete 2.4:**
- [ ] `ai/model/features.py` has no `generate_synthetic_dataset` function
- [ ] `data/tr_super_lig_2024_25.json` deleted
- [ ] `data/generate_match_data.py` moved to `ai/tests/`
- [ ] All test files that need synthetic data import from `tests/fixtures.py`
- [ ] `grep -r "generate_synthetic" ai/` returns zero hits outside `tests/`

### Subphase 2.5: Enforce Real Data Scraping on First Run

**Files:** `Makefile`, `ai/pipeline/runner.py`

When the system starts fresh (no cached data), it must scrape real data before training — not generate synthetic.

**Change:** Add a `make bootstrap` target that runs the full scrape → validate → cache pipeline:

```makefile
bootstrap:
	@echo "Bootstrapping real data for $(LEAGUE)..."
	$(PYTHON) -m scraper.real_data --league $(LEAGUE) --seasons last-5
	$(PYTHON) -m proofreader.validator --input data/$(LEAGUE)_real.json
	@echo "Bootstrap complete. $(LEAGUE) data ready for training."
```

**Requirements to complete 2.5:**
- [ ] `make bootstrap` scrapes, validates, and caches real data for the default league
- [ ] `make bootstrap --league=en_premier_league` works for any configured league
- [ ] `make train` fails with "Run `make bootstrap` first" if no cached data exists
- [ ] CI/CD pipeline includes bootstrap step before training

### Phase 2 Completion Gate

| Requirement | How to Verify |
|---|---|
| Zero synthetic data in production paths | `grep -r "synthetic\|generate_synthetic\|fake\|generated.*true" ai/ p2p/ --include="*.py"` returns hits only in `tests/` |
| Training fails without real data | Delete `data/tr_super_lig_real.json`, run `make train`, confirm it fails with actionable error |
| P2P sim fails without real data | Delete cached data, run P2P sim, confirm it fails with scrape instructions |
| Bootstrap works end-to-end | `make bootstrap` on clean checkout produces valid `data/tr_super_lig_real.json` |
| All tests still pass | Unit tests use `tests/fixtures.py` for synthetic data, all green |

---

## Phase 3: Full-System Training Pipeline

**Goal:** "Training the AI" becomes a full-system integration test that exercises every subsystem end-to-end on **real data**: scrape → proofread → train → run a P2P simulation against a held-out window → ensemble peer predictions → verify against actual outcomes → emit a structured report with a pass/fail verdict. This is the **primary** training and regression-testing surface for the system.  
**Depends on:** Phase 2 (synthetic data removed, real data pipeline works)

**Design principles** (added in revision):

1. **Stage artifacts are first-class.** Each stage produces a typed `StageArtifact` (dataclass) consumed by the next stage. No globals, no implicit state.
2. **Coordinator separation.** A new `TrainingPipeline` class in `ai/pipeline/training_pipeline.py` owns stage execution, while `OrchestratorState` is extended only to surface state-machine telemetry. The pipeline can be invoked directly (Python API) or via CLI.
3. **Holdout-first.** Verification uses a *time-based* walk-forward holdout (last `verification_window` matchweeks) reserved **before** training. Training never sees the holdout.
4. **Threshold-driven verdict.** Pass/fail is computed from configurable thresholds in `Config.training_thresholds`. No magic numbers in code.
5. **Graceful degradation.** P2P simulation failure does not abort the run; it produces a partial report flagged `p2p_status: degraded`. Only data/training failures are fatal.
6. **Resumable / idempotent.** Each stage caches its artifact under `data/reports/runs/<run_id>/`. Re-running a stage with an existing artifact short-circuits unless `--force`.
7. **Trend persistence.** Every run appends a one-line summary to `data/reports/history.jsonl` for longitudinal tracking (regression detection across versions).

### Subphase 3.1: Define the Full Training Lifecycle

The training pipeline must execute these stages in order, with each stage's output feeding the next:

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│  1. SCRAPE   │───→│  2. VALIDATE  │───→│  3. TRAIN    │───→│  4. P2P SIM   │
│  Real data   │    │  Proofread    │    │  GBDT model  │    │  Multi-node   │
└─────────────┘    └──────────────┘    └─────────────┘    └──────────────┘
                                                                  │
┌─────────────┐    ┌──────────────┐    ┌─────────────┐           │
│  7. REPORT   │←──│  6. VERIFY    │←──│  5. ENSEMBLE  │←─────────┘
│  Full report │    │  vs outcomes  │    │  Reputation-  │
│              │    │              │    │  weighted      │
└─────────────┘    └──────────────┘    └─────────────┘
```

**Stage descriptions:**

| Stage | Artifact (typed) | What Happens | Hard Failure? | Default Threshold |
|---|---|---|---|---|
| 1. SCRAPE | `ScrapeArtifact{matches, source_breakdown, errors}` | Real data scraped/loaded for the target league via cached `*_real.json` (Phase 2 path) | Yes | `≥ bootstrap_min_matches` |
| 2. VALIDATE | `ValidationArtifact{kept, quarantined, quarantine_rate, cross_source_agreement}` | `proofreader/validator.py` range/consistency/plausibility + `cross_validator.py` agreement | Yes | `quarantine_rate ≤ 0.10` |
| 3. SPLIT | `SplitArtifact{train_matches, holdout_matches, holdout_window_weeks}` | Time-based walk-forward split: holdout = last `verification_window` matchweeks | Yes | `len(holdout) ≥ 5` |
| 4. TRAIN | `TrainingArtifact{model_path, model_size_mb, test_acc, log_loss, top_features, n_features}` | GBDT trained on `train_matches` only — never touches holdout | Yes | `test_acc ≥ thresholds.model_acc` |
| 5. P2P_SIM | `P2PArtifact{nodes_alive, role_election, schema_consensus, per_node_predictions}` | N simulated peers booted with the trained model, gossip + reputation tracker exercised | **No** (degrades) | `nodes_alive ≥ thresholds.min_nodes_alive` |
| 6. ENSEMBLE | `EnsembleArtifact{ensemble_predictions, per_node_acc, ensemble_acc, reputation_scores}` | Reputation-weighted ensemble across nodes for each holdout match | No (degrades) | `ensemble_acc ≥ best_node_acc - 0.02` |
| 7. VERIFY | `VerifyArtifact{overall_acc, per_market_acc, calibration, brier_score}` | Compare model + ensemble predictions against actual `holdout_matches` outcomes | Yes | `overall_acc ≥ thresholds.ensemble_acc` |
| 8. REPORT | `ReportArtifact{txt_path, json_path, verdict}` | Generate human-readable + machine-readable report; append to `history.jsonl` | Yes | All hard-stage thresholds met |

> **Note on stage count:** The original 7 stages collapsed split/train and ensemble/verify. The revised pipeline separates them so each artifact has a single owner, which makes resumability (`--force-stage train`) and partial reports (`p2p_status: degraded`) tractable.

### Subphase 3.2: Stage Artifacts & Pipeline Coordinator

**New files:**
- `ai/pipeline/training_pipeline.py` — `TrainingPipeline` coordinator + `StageArtifact` base + per-stage subclasses.
- `ai/pipeline/training_artifacts.py` — typed dataclasses (one per stage) with `to_dict()` / `from_dict()` for caching.

**Behavior:**
- `TrainingPipeline.run(run_id: str | None = None, *, force_from: str | None = None, skip_p2p: bool = False) -> ReportArtifact`
- Each stage method: `def _stage_X(self, prev: PrevArtifact) -> XArtifact`
- Stage results are pickled to `data/reports/runs/<run_id>/<stage>.pkl` and a thin JSON sidecar at `<stage>.json` (for human inspection).
- A `manifest.json` at run root records: `run_id`, `started_at`, `finished_at`, `stage_durations_ms`, `verdict`, `model_path`, `report_paths`.
- Run id defaults to `{league}_{utc_isoformat}`.
- Resumability: if `<stage>.pkl` exists and `force_from` is not set or is later in the order, skip recompute and load from disk.

**Requirements to complete 3.2:**
- [x] `TrainingPipeline` class exists with one method per stage and explicit artifact handoff.
- [x] All artifact dataclasses live in `training_artifacts.py` and round-trip through JSON sidecars.
- [x] `--force-from <stage>` invalidates that stage and everything downstream.
- [x] `--skip-p2p` short-circuits stages 5–6 with `p2p_status: skipped`; verify stage runs against the trained model alone.
- [x] Manifest written even on hard failure (with `verdict: FAIL` and `failed_stage`).

### Subphase 3.3: Configurable Thresholds & Validation Window

**File:** `ai/common/config.py`

Add a single `training_thresholds` config block plus `verification_window` and `report_dir` fields. All driven by env vars with sensible defaults; the canonical reference lives in `ai/common/defaults.yaml`.

```python
# Numeric thresholds for full-pipeline pass/fail
training_thresholds_model_acc: float           # NEGELIR_THRESHOLD_MODEL_ACC=0.50
training_thresholds_ensemble_acc: float        # NEGELIR_THRESHOLD_ENSEMBLE_ACC=0.50
training_thresholds_quarantine_max: float      # NEGELIR_THRESHOLD_QUARANTINE_MAX=0.10
training_thresholds_min_nodes_alive: int       # NEGELIR_THRESHOLD_MIN_NODES_ALIVE=3
training_thresholds_min_holdout_matches: int   # NEGELIR_THRESHOLD_MIN_HOLDOUT_MATCHES=5
verification_window_weeks: int                 # NEGELIR_VERIFICATION_WINDOW_WEEKS=4
report_dir: str                                # NEGELIR_REPORT_DIR=/data/reports
```

A `Config.training_thresholds` property returns these as a single dict for ergonomic access from the report module. `Config.validate(strict=True)` rejects nonsensical values (e.g. accuracy outside [0, 1]).

**Requirements to complete 3.3:**
- [x] All thresholds are env-overridable and documented in `.env.example` and `defaults.yaml`.
- [x] `Config.validate()` covers the new fields.
- [x] No magic numbers remain in `training_pipeline.py` or `training_report.py` — every threshold reads from config.

### Subphase 3.4: P2P Simulation as a Pure Validator

**File:** `p2p/simulation/runner.py`

Refactor `P2PSimulation` so it can be invoked as a validator for an external model:

- `P2PSimulation.__init__(model_path: str | None = None, league_id: str | None = None, node_count: int | None = None, holdout_matches: list[dict] | None = None)`
- When `model_path` is supplied, every node loads the same pickled model instead of producing analyses from heuristics. Per-node bias is added by perturbing inference inputs (small ε on form/elo) so peers are non-identical.
- When `holdout_matches` is supplied, each node only predicts those matches (no random sampling), which makes ensemble and verification deterministic.
- New CLI: `python -m simulation.runner --model PATH --league super_lig --holdout JSON_PATH --output OUTPUT_JSON`.
- The simulator emits a structured JSON report at `--output` containing per-node predictions, reputation scores, role election summary, and consensus state — exactly the shape consumed by the ensemble/verify stages.
- All previous behavior (no-args sim, `--scale-test`, `--churn-test`) remains intact.

**Requirements to complete 3.4:**
- [x] `P2PSimulation` accepts the new constructor parameters and the CLI flags.
- [x] When `model_path` is set, no node retrains — they only load and predict.
- [x] Sim produces deterministic per-node + ensemble JSON for a given holdout + seed.
- [x] Existing `make p2p-simulate` runs unchanged.

### Subphase 3.5: Verification & Reporting

**New files:**
- `ai/reports/__init__.py`
- `ai/reports/training_report.py`

**Verification (stage 7):** Walk-forward over `holdout_matches` using the trained model directly *and* the P2P ensemble (when available). Computes:
- `overall_acc` (1X2)
- `per_market_acc` (uses existing `backtest/bet_types.py` evaluators if available)
- `calibration` (Brier score, reliability bins)
- `coverage` (fraction of holdout actually predicted)

**Report (stage 8):** Renders the artifact set into:
- `data/reports/runs/<run_id>/report.txt` — human-readable, matching the layout in §3.1.
- `data/reports/runs/<run_id>/report.json` — machine-readable, schema-versioned (`schema_version: 1`).
- `data/reports/latest_<league>.txt` and `latest_<league>.json` symlinks/copies for easy access.
- One JSONL line appended to `data/reports/history.jsonl` with `{run_id, league, finished_at, verdict, model_acc, ensemble_acc, quarantine_rate, p2p_status}`.

**Verdict logic:**
- `PASS` — every hard-stage threshold met.
- `PASS_DEGRADED` — hard stages pass but `p2p_status ∈ {degraded, skipped}`.
- `FAIL` — any hard stage misses its threshold; report still generated with `failed_stage` populated.

**Requirements to complete 3.5:**
- [x] Both report formats generated for every run (pass or fail).
- [x] Report references the model file path and reproducible `run_id`.
- [x] `history.jsonl` is append-only and survives across runs.
- [x] JSON schema is documented inline (`schema_version`) and unit-tested for shape stability.

### Subphase 3.6: Orchestrator Integration & Telemetry

**File:** `ai/orchestrator/state_machine.py`

The orchestrator no longer drives the pipeline directly; instead it **observes** it. Add states for telemetry only:

```
IDLE → SCRAPING → VALIDATING → TRAINING → P2P_SIMULATION → VERIFYING → REPORTING → IDLE
```

`TaskOrchestrator` gains `run_full_training(force_from=None, skip_p2p=False)` which:
1. Instantiates `TrainingPipeline`.
2. Subscribes to a stage-callback (`pipeline.on_stage_start`, `on_stage_end`) that flips `OrchestratorState` accordingly.
3. Returns the final `ReportArtifact`.

This keeps state-machine semantics for monitoring/telemetry while the actual work lives in `TrainingPipeline`.

**Requirements to complete 3.6:**
- [x] `OrchestratorState` enum has `VALIDATING`, `TRAINING`, `P2P_SIMULATION`, `VERIFYING`, `REPORTING`.
- [x] `TaskOrchestrator.run_full_training()` exists and is exercised by `make train-full`.
- [x] State transitions log with elapsed-ms per stage.

### Subphase 3.7: CLI & Makefile Integration

**Files:** `ai/orchestrator/state_machine.py` (new `__main__`), `Makefile`.

```makefile
train-full:        # Full 8-stage pipeline (default for `make train`)
train-model:       # Stages 1–4 only (data + training, no P2P)
sim-p2p:           # Stage 5–6 only against an existing model
test-integration:  # Run tests/test_full_pipeline.py
```

CLI:
```
python -m orchestrator.state_machine --mode full-training --league super_lig [--force-from train] [--skip-p2p]
python -m orchestrator.state_machine --mode model-only    --league super_lig
python -m orchestrator.state_machine --mode sim-only      --league super_lig --model PATH
```

**Requirements to complete 3.7:**
- [x] `make train-full LEAGUE=...` runs end-to-end and writes a report.
- [x] `make train-model` skips P2P/ensemble/verify-vs-ensemble (model-only verify still runs).
- [x] `make sim-p2p MODEL=...` reuses an existing model.
- [x] `make train` aliases `make train-full` (back-compat: `ai-train` keeps the old behavior).

### Subphase 3.8: Integration Test Suite

**File:** `ai/tests/test_full_pipeline.py`

A `pytest` module that:
- Skips with a clear reason if `data/{league}_real.json` is absent (so unit-test CI without real data still passes).
- Calls `TrainingPipeline(node_count=3, verification_window_weeks=2).run(skip_p2p=False)`.
- Asserts the returned `ReportArtifact` has `schema_version == 1`, every stage artifact exists on disk, the `manifest.json` is well-formed, and `verdict ∈ {PASS, PASS_DEGRADED}` (FAIL surfaces meaningful diagnostics in the assertion message).
- Reads `history.jsonl`, asserts the new run is the last line.

**Requirements to complete 3.8:**
- [x] Test exists and either passes or skips (never errors) on a fresh checkout.
- [x] Test runtime < 5 minutes with `node_count=3, verification_window_weeks=2`.
- [x] `make test-integration` invokes only this test.

### Phase 3 Completion Gate

| Requirement | How to Verify |
|---|---|
| Coordinator owns the pipeline | `TrainingPipeline` exists; `state_machine.py` only observes |
| All artifacts typed and persisted | `data/reports/runs/<run_id>/*.json` present after a run |
| Pass/fail driven by config | Lowering `NEGELIR_THRESHOLD_MODEL_ACC` flips `FAIL → PASS` without code change |
| Holdout never seen by trainer | `SplitArtifact.holdout_matches` ids ∩ training set ids == ∅ (asserted in `_stage_split`) |
| P2P degradation is non-fatal | Killing P2P sim mid-run still produces a `PASS_DEGRADED` report |
| Trend history persists | `data/reports/history.jsonl` grows by exactly one line per run |
| Integration test green | `make test-integration` passes (or skips cleanly without real data) |
| All previous tests still pass | `pytest ai/tests/test_unit.py` green |

---

## Phase 4: Multi-League Foundation

**Goal:** Make the data pipeline accept `league_id` as a first-class parameter everywhere.  
**Depends on:** Phase 1 (hardcoded values already centralized in config)

### Subphase 4.1: Per-League Data Source Registry

**File:** `ai/common/config.py`

Add a `league_data_sources` property returning source configs keyed by `league_id`. This config is loaded from a YAML file (`league_sources.yaml`) rather than hardcoded:

```yaml
# league_sources.yaml
tr_super_lig:
  mackolik_group_id: 1
  mackolik_seasons:
    "2025/2026": 70381
  openfootball_path: "tr.1.json"
  footballdata_country: "T1"
en_premier_league:
  mackolik_group_id: 2
  openfootball_path: "en.1.json"
  footballdata_country: "E0"
...
```

**Requirements to complete 4.1:**
- [ ] `league_sources.yaml` exists with at least 6 leagues configured
- [ ] `config.league_data_sources` loads from YAML
- [ ] Adding a new league requires only a YAML edit, no code changes
- [ ] Env var `NEGELIR_ACTIVE_LEAGUES` controls which leagues are active

### Subphase 4.2: Mackolik Client League Parameterization

**File:** `ai/scraper/mackolik.py`

| Change | Current | Target |
|---|---|---|
| Constructor | `GROUP_TURKEY = 1` class constant | `__init__(self, group_id: int, league_name_filter: str)` |
| `discover_seasons()` | Filters `"Süper Lig"` | Uses `self.league_name_filter` |
| All `params={"group": ...}` | `self.GROUP_TURKEY` | `self.group_id` |

**Requirements to complete 4.2:**
- [ ] `MackolikClient(group_id=1, league_name_filter="Süper Lig")` works
- [ ] `MackolikClient(group_id=2, league_name_filter="Premier Lig")` works
- [ ] Zero class-level constants referencing a specific league

### Subphase 4.3: Real Data Scraper League Parameterization

**File:** `ai/scraper/real_data.py`

| Change | Current | Target |
|---|---|---|
| OpenFootball URL | `f"{base}/{season}/tr.1.json"` | `f"{base}/{season}/{league_config.openfootball_path}"` |
| football-data.co.uk | `T1` hardcoded | `league_config.footballdata_country` |
| Cache file | `data/tr_super_lig_real.json` | `data/{league_id}_real.json` |

**Requirements to complete 4.3:**
- [ ] `RealDataScraper.__init__()` accepts `league_config: LeagueConfig`
- [ ] All URL construction uses league config properties
- [ ] Cache paths are league-specific
- [ ] `make scrape --league=en_premier_league` fetches EPL data

### Subphase 4.4: Data Contracts League Awareness

**File:** `ai/scraper/data_contracts.py`

Team count validation currently hardcodes 18-21 for Turkish Süper Lig. Must use `league_config.teams_count`.

**Requirements to complete 4.4:**
- [ ] All data contract validations reference `league_config` for league-specific bounds
- [ ] EPL data (20 teams) passes validation
- [ ] Bundesliga data (18 teams) passes validation

### Subphase 4.5: DB Multi-League Seed Migration

**File:** New `migrations/004_multi_league_seeds.sql`

Add seed data for target leagues. Schema already has `league_id` columns.

**Requirements to complete 4.5:**
- [ ] Teams for 6 leagues inserted
- [ ] `league_id` correctly tagged
- [ ] Migration runs idempotently (skip existing)

### Phase 4 Completion Gate

| Requirement | How to Verify |
|---|---|
| League ID is first-class | `make scrape --league en_premier_league` loads EPL data end-to-end |
| Config-driven | Adding a new league requires only YAML edits |
| Turkish still works | Existing `make scrape` (defaulting to `tr_super_lig`) produces identical results |
| Validation is league-aware | EPL data (20 teams) and Bundesliga (18 teams) both pass data contracts |

---

## Phase 5: Multi-League Data Import

**Goal:** Import 40,000+ historical matches from football-data.co.uk for EPL, Bundesliga, La Liga, Serie A, Ligue 1. Train a global model and compare accuracy.  
**Depends on:** Phase 4

### Subphase 5.1: Multi-League CSV Downloader

**File:** `ai/scraper/real_data.py`

Add `download_league(league_id, country_code, seasons)` for football-data.co.uk multi-league CSV.

| League | Code | Seasons Available |
|---|---|---|
| English Premier League | `E0` | 1993-2026 (30+) |
| German Bundesliga | `D1` | 1993-2026 (30+) |
| Spanish La Liga | `SP1` | 1993-2026 (30+) |
| Italian Serie A | `I1` | 1993-2026 (30+) |
| French Ligue 1 | `F1` | 1993-2026 (30+) |
| TFF 1. Lig | `T2` | 2018-2026 |

**Requirements to complete 5.1:**
- [ ] `download_league()` downloads, parses, and caches to `data/{league_id}_real.json`
- [ ] Rate limiting respected (1 req/sec to football-data.co.uk)
- [ ] CSV column mapping handles football-data.co.uk format variations by season
- [ ] All 6 leagues successfully imported

### Subphase 5.2: LeagueConfig Tuning with Real Data

**File:** `ai/common/league_config.py`

Fill in empirical parameters for each league by computing from imported data:

| Parameter | TR | EPL | BUN | LIG | SER | L1 |
|---|---|---|---|---|---|---|
| `teams_count` | 19 | 20 | 18 | 20 | 20 | 18 |
| `rounds_per_season` | 38 | 38 | 34 | 38 | 38 | 34 |
| `league_avg_goals` | 2.65 | 2.70 | 2.90 | 2.55 | 2.60 | 2.55 |

Add `it_serie_a()` and `fr_ligue_1()` factory functions.

**Requirements to complete 5.2:**
- [ ] All 6 league factories exist with empirically validated parameters
- [ ] Parameters computed from actual imported data, not estimated
- [ ] `LEAGUE_REGISTRY` contains all 6 leagues

### Subphase 5.3: Per-League Elo Pools

**File:** `ai/model/real_features.py`

Separate Elo pools per league. 800+ teams across 6 leagues cannot share one pool.

**Requirements to complete 5.3:**
- [ ] `EloTracker` maintains `pools: dict[str, dict[str, float]]`
- [ ] Elo ratings are isolated per league
- [ ] Cross-league calibration deferred to Phase 9

### Subphase 5.4: Global Model Experiment

Train XGBoost on all ~45,000 matches. Add `league_id` as categorical feature. Compare:

| Experiment | Training Data | Test Set |
|---|---|---|
| Baseline | TR only (~1,500) | TR last 10 weeks |
| Global | All leagues (~45,000) | TR last 10 weeks |
| Global | All leagues (~45,000) | EPL last 10 weeks |
| Per-league | EPL only (~8,000) | EPL last 10 weeks |

**Requirements to complete 5.4:**
- [ ] Global model trained successfully on all leagues
- [ ] Accuracy comparison table generated
- [ ] Results saved to `data/reports/multi_league_experiment.json`

### Subphase 5.5: Backtest Multi-League Support

**File:** `ai/backtest/evaluator.py`

```bash
python -m backtest.evaluator --weeks 10 --league en_premier_league
python -m backtest.evaluator --weeks 10 --league all
```

**Requirements to complete 5.5:**
- [ ] `--league` flag works for all 6 leagues
- [ ] `--league all` produces cross-league comparison report
- [ ] Report headers include league name

### Phase 5 Completion Gate

| Requirement | How to Verify |
|---|---|
| ≥40,000 matches imported | Data file sizes and match counts across 6 leagues |
| Global model accuracy on TR ≥52% | Within 2pp of current 54% baseline |
| Global model accuracy on EPL ≥48% | Backtest report |
| All 6 leagues load without error | `make scrape --league {id}` for each |
| Accuracy comparison report exists | `data/reports/multi_league_experiment.json` |

---

## Phase 6: Live Multi-League Scraping

**Goal:** Real-time match data from Mackolik for all target leagues.  
**Depends on:** Phase 5

### Subphase 6.1: Mackolik League Discovery

Build `discover_all_leagues()` to find all available group IDs on Mackolik.

**Requirements to complete 6.1:**
- [ ] Discovery returns group IDs for all target leagues
- [ ] Stable group IDs stored in `league_sources.yaml`

### Subphase 6.2: Rate-Limited Multi-League Scraping

Queue-based scraper with per-domain rate buckets. Target: <500 requests/day across all leagues.

**Requirements to complete 6.2:**
- [ ] `MultiLeagueScraper` class handles N leagues
- [ ] Per-domain rate limiting (configurable via `config.scrape_rate_limit`)
- [ ] Total daily request count stays under configurable limit

### Subphase 6.3: Per-League Season Auto-Discovery

Extend `detect_season()` to loop over active leagues.

**Requirements to complete 6.3:**
- [ ] Each active league's seasons are auto-detected
- [ ] Season detection respects league-specific schedules (e.g., Bundesliga winter break)

### Subphase 6.4: Team Name Normalization Per League

Create per-league locale YAML files with team name aliases.

**Requirements to complete 6.4:**
- [ ] `locale_en.yaml`, `locale_de.yaml`, `locale_es.yaml`, `locale_it.yaml`, `locale_fr.yaml` exist
- [ ] Each contains team names, aliases, and Mackolik-to-canonical mappings
- [ ] `locale_loader.py` loads the correct locale per league

### Phase 6 Completion Gate

| Requirement | How to Verify |
|---|---|
| Live Mackolik data for 6 leagues | `make scrape --league {id} --live` for each |
| Rate limits respected | Request log shows <500/day |
| Team names normalized | No "Unknown team" warnings in scrape logs |

---

## Phase 7: Multi-Locale NLP Stack

**Goal:** Enable Turkish users to ask about foreign league matches in Turkish.  
**Depends on:** Phase 4

### Subphase 7.1: Foreign Team Name Recognition

**Files:** `ai/tqu/entities.py`, `ai/tqu/normalizer.py`

Extend `ALL_TEAM_NAMES` to include all tracked league teams.

**Requirements to complete 7.1:**
- [ ] "Arsenal Liverpool maçı" recognized as EPL match
- [ ] "Bayern Münih" recognized as Bundesliga team
- [ ] Turkish suffix stripping works on foreign names

### Subphase 7.2: League Context Detection

**File:** `ai/tqu/patterns.py`

Add league mention patterns: `"premier lig"`, `"la liga"`, `"bundesliga"`, etc. If no league mentioned, infer from team names.

**Requirements to complete 7.2:**
- [ ] Explicit league mentions detected
- [ ] Team-to-league inference works when no league mentioned
- [ ] Ambiguous teams (e.g., "Sporting" appears in multiple leagues) prompt clarification

### Subphase 7.3: League-Aware Response Templates

**File:** `ai/trc/templates.py`, `ai/trc/composer.py`

Add league name in responses: *"Premier Lig'de Arsenal..."*

**Requirements to complete 7.3:**
- [ ] Responses include league context
- [ ] Turkish grammar works with foreign league names

### Phase 7 Completion Gate

| Requirement | How to Verify |
|---|---|
| Foreign team questions work | "Arsenal Liverpool maçını kim kazanır?" produces EPL analysis |
| League detection works | Both explicit ("premier lig") and implicit (from team names) |
| Responses are grammatically correct | Turkish proofreading of template outputs |

---

## Phase 8: Model Strategy & Experimentation

**Goal:** Determine optimal model architecture for multi-league predictions.  
**Depends on:** Phase 5 (needs accuracy data from multi-league experiment)

### Subphase 8.1: Strategy Comparison

| Strategy | Description |
|---|---|
| Single global model | One XGBoost on all leagues, `league_id` as feature |
| Per-league models | Separate XGBoost per league |
| Hierarchical | Global base + per-league fine-tuning |

### Subphase 8.2: Decision Criteria

- **Global if:** accuracy on TR ≥ TR-only baseline - 2pp, EPL ≥50%
- **Per-league if:** per-league models beat global by >5pp
- **Hierarchical if:** both above underperform

### Subphase 8.3: League-Specific Feature Engineering

Add features: `league_id_encoded`, `league_avg_goals`, `league_home_win_pct`, `league_draw_pct`, `league_strength_tier`.

### Subphase 8.4: Model Versioning

```
data/models/negelir_gbdt_v0.3.0.pkl      # Current: TR-only
data/models/negelir_gbdt_v0.4.0.pkl      # Global model
data/models/negelir_gbdt_v0.4.0_epl.pkl  # Per-league (if needed)
```

**Requirements to complete 8.4:**
- [ ] Model naming convention includes league scope
- [ ] Model metadata includes training leagues and feature count
- [ ] Old models preserved for rollback

### Phase 8 Completion Gate

| Requirement | How to Verify |
|---|---|
| Best strategy identified | Experiment results in `data/reports/` |
| Chosen strategy beats TR-only baseline | Accuracy comparison documented |
| All target leagues ≥50% accuracy | Backtest per-league |

---

## Phase 9: Cup & Knockout Competitions

**Goal:** Handle Champions League, Europa League, domestic cups.  
**Depends on:** Phase 6

### Subphase 9.1: Competition Type Classification

```python
class CompetitionType(Enum):
    LEAGUE = "league"
    CUP = "cup"
    GROUP_STAGE = "group"
    FRIENDLY = "friendly"
    QUALIFIER = "qualifier"
```

### Subphase 9.2: Feature Fallbacks for Non-League Matches

Standings-dependent features (league position, points gap, relegation pressure) need fallbacks for cup matches.

### Subphase 9.3: Cross-League Elo Calibration

Use Champions League group stage results to compute league strength offsets for cross-league predictions.

### Phase 9 Completion Gate

| Requirement | How to Verify |
|---|---|
| CL group stage matches predicted | Backtest on recent CL data |
| Feature fallbacks work | Cup match predictions don't crash on missing standings |
| Cross-league Elo calibration | League offsets computed from CL results |

---

## Phase 10: Lower Divisions & Full İddaa Coverage

**Goal:** TFF 1. Lig, remaining İddaa-listed leagues. Confidence gating for sparse data.  
**Depends on:** Phases 5-8

### Subphase 10.1: TFF 1. Lig Import

football-data.co.uk `T2`, Mackolik coverage.

### Subphase 10.2: Confidence-Gated Predictions

Refuse prediction rather than give bad ones when data is insufficient:
```python
if team_history < config.min_matches_for_prediction:
    return False, "Yetersiz veri"
```

### Subphase 10.3: Dynamic Market Availability

Not all betting markets make sense for all leagues. Gate markets per league based on available data.

### Phase 10 Completion Gate

| Requirement | How to Verify |
|---|---|
| TFF 1. Lig predictions work | Backtest report |
| Confidence gating works | Low-data teams get refusal, not bad predictions |
| Market availability is per-league | Unavailable markets not offered |

---

## Risk Register

| # | Risk | Likelihood | Impact | Phase | Mitigation |
|---|---|---|---|---|---|
| R1 | Mackolik rate-limits at 6× scrape volume | High | Critical | 6 | Configurable rate limits, per-domain buckets, aggressive caching |
| R2 | Global model accuracy drops on Turkish data | Medium | High | 5 | Keep TR-only model as fallback, A/B test |
| R3 | Real data scraping fails on first run | Medium | High | 2 | Clear error messages, `make bootstrap` documented prominently |
| R4 | Config explosion — too many env vars | Medium | Medium | 1 | YAML config files, env vars only for secrets and overrides |
| R5 | P2P simulation masks real networking issues | Medium | Medium | 3 | SimulatedTransport faithfully models latency/drops/partitions |
| R6 | football-data.co.uk format changes | Low | Medium | 5 | Self-healing CSV parser, column name pinning |
| R7 | Team name mismatch across sources | High | Medium | 4-6 | Per-league alias maps in locale YAML, fuzzy matching |
| R8 | Lower-division data too sparse | High | Low | 10 | Confidence gating — refuse prediction below threshold |
| R9 | Nesine scraping legal risk | High | Critical | Never | Do NOT scrape Nesine |
| R10 | Full pipeline too slow for CI | Medium | Medium | 3 | Reduced node count + data window for CI test mode |

---

## Quick Reference: Data Source Codes

| League | football-data.co.uk | OpenFootball | Mackolik Group (est.) |
|---|---|---|---|
| Turkish Süper Lig | `T1` | `tr.1.json` | 1 |
| English Premier League | `E0` | `en.1.json` | 2 |
| German Bundesliga | `D1` | `de.1.json` | 7 |
| Spanish La Liga | `SP1` | `es.1.json` | 6 |
| Italian Serie A | `I1` | `it.1.json` | 4 |
| French Ligue 1 | `F1` | `fr.1.json` | 3 |
| TFF 1. Lig | `T2` | — | TBD |
