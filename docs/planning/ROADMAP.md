# 🗺️ Negelir — Master Roadmap (Production Pivot v3)

> **Version:** 3.0.0 — *Production Pivot*
> **Date:** 2026-04-20
> **Status:** Active. Single source of truth.
> **Supersedes:** v2.0.0 Swarm Pivot (all prior prior roadmaps already superseded by v2).
> The **phase numbering from v2.0.0 is preserved intact** — Phases 0–15 still carry the same meaning and the same completion status. v3 **adds** a cross-cutting restructuring track (Phases **R1–R6**) and three new feature phases (**16 Emitter**, **17 Patcher + GitOps**, **18 Datasource Cohesion**) that re-shape ownership boundaries for everything from Phase 3 onward.

---

## 📜 Production Pivot v3 — Why

Through Phase 2.8 the project ran as two top-level components: `ai/` and `server/`. That was fine for dev, but three structural debts showed up as we approached Phase 3+:

1. **Concern mixing.** The AI swarm had to know how scraping worked. Predictors and scrapers lived in the same module tree.
2. **Dev vs. prod asymmetry.** The mock stack looked like "scaffolding," not a production capability we can point the real operators at.
3. **Growing feature surface inside `ai/`.** A content-refresher, an auto-patcher, and a GitOps worker were already on the board; putting them in `ai/` would make it a junk drawer.

v3 introduces a **four-component layout** (`server/`, `datasource/`, `swarm/`, `common/`) defined in [`docs/design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) and plumbs the in-between via a new **emitter** + **feed** contract defined in [`docs/design/EMITTER.md`](../design/EMITTER.md). It also promotes the two most-requested future agents to real phases:

- **Emitter** (Phase 16) — the component that converts DB+Redis state into the NDJSON/Parquet feeds the swarm consumes. Ends the swarm's dependency on Postgres.
- **Patcher + GitOps** (Phase 17) — the auto-patching scraper loop, including the 7-day auto-merge policy behind a 5-gate safety net. See [`docs/design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md).

The v2 Swarm Pivot remains correct. v3 is about **who owns what** and **what they trade in**, not about replacing the bus, the predictors, or the DoD.

---

## 📜 v2 Pivot Summary (retained for archaeology)

The previous design used a **P2P gossip / multicast network** to spread schema changes
and run distributed validation. After review, this approach is **discarded**:

- ❌ P2P adds operational and security overhead disproportionate to the project's needs.
- ❌ It does not improve prediction quality vs. a single-host ensemble.
- ❌ The "validator network" simulation only ever ran inside one Docker host anyway.

The replacement is a **Swarm-AI Agents architecture**:

- ✅ Many small, single-purpose agents (mostly *not* LLMs).
- ✅ Coordinated through a **message bus** (Redis Streams locally, NATS-compatible at scale).
- ✅ Consensus, proofreading, drift detection, malicious-input detection are all **agent roles**, not network primitives.
- ✅ Same architecture runs on a laptop *and* on a 100-pod K8s cluster.

---

## 📚 Table of Contents

- [Guiding Principles](#-guiding-principles)
- [System at a Glance](#-system-at-a-glance)
- [Phase Overview](#-phase-overview)
- [Phase 0 — Repo Reset & Cleanup](#-phase-0--repo-reset--cleanup)
- [Phase 1 — Centralized Configuration & Hardcode Audit](#-phase-1--centralized-configuration--hardcode-audit)
- [Phase 2 — Mock-Data Dev Stack ("Fake Internet")](#-phase-2--mock-data-dev-stack-fake-internet)
- [Phase 3 — Swarm Foundation (Bus, Registry, Supervisor)](#-phase-3--swarm-foundation-bus-registry-supervisor)
- [Phase 4 — Core Worker Agents (Scrape → Categorize → Process → Store)](#-phase-4--core-worker-agents-scrape--categorize--process--store)
- [Phase 5 — Predictor Swarm & Consensus](#-phase-5--predictor-swarm--consensus)
- [Phase 6 — Proofreader & Drift Agents](#-phase-6--proofreader--drift-agents)
- [Phase 7 — Defense Agents (Malicious-Input, Anomaly, Rate Limit)](#-phase-7--defense-agents-malicious-input-anomaly-rate-limit)
- [Phase 8 — Self-Maintenance Agents (Schema Healer, Auto-Scaler, Coder)](#-phase-8--self-maintenance-agents-schema-healer-auto-scaler-coder)
- [Phase 9 — Go REST API & Identity (Public Surface)](#-phase-9--go-rest-api--identity-public-surface)
- [Phase 10 — Turkish-First NLP Layer](#-phase-10--turkish-first-nlp-layer)
- [Phase 11 — GPU/CPU/NPU Compute Strategy](#-phase-11--gpucpunpu-compute-strategy)
- [Phase 12 — Adversarial & Chaos Test Suite](#-phase-12--adversarial--chaos-test-suite)
- [Phase 13 — Multi-League Expansion](#-phase-13--multi-league-expansion)
- [Phase 14 — Cloud-Ready Packaging (Docker → K8s → CSP-Agnostic)](#-phase-14--cloud-ready-packaging-docker--k8s--csp-agnostic)
- [Phase 15 — Frontend Handoff (Flutter, Future)](#-phase-15--frontend-handoff-flutter-future)
- [Phase 16 — Emitter & Feed Contract (Production Pivot v3)](#-phase-16--emitter--feed-contract-production-pivot-v3)
- [Phase 17 — Scraper-Patcher + GitOps (Production Pivot v3)](#-phase-17--scraper-patcher--gitops-production-pivot-v3)
- [Phase 18 — Datasource Cohesion & Swarm Isolation (Production Pivot v3)](#-phase-18--datasource-cohesion--swarm-isolation-production-pivot-v3)
- [Phase R — Restructure Track (Production Pivot v3)](#-phase-r--restructure-track-production-pivot-v3)
- [Appendix A — Decision Log](#-appendix-a--decision-log)
- [Appendix B — Definition of Done (Per Phase)](#-appendix-b--definition-of-done-per-phase)

---

## 🧭 Guiding Principles

These apply to **every** phase, **every** PR, **every** agent. They are non-negotiable.

| # | Principle | What It Means in Practice |
|---|---|---|
| 1 | **🔧 Single-Source Configuration** | Every tunable value comes from one of: `ai/common/config.py` (Python) or `internal/config` (Go). Both read env vars with documented defaults from `.env.example`. **No magic numbers in code, ever.** |
| 2 | **📦 Containerized-Only** | Local dev = `docker compose`. Prod = Docker or K8s. There is no "host install" path. CI runs the same images. |
| 3 | **🚫 Real Data Only in Prod Paths** | Synthetic data is a *test fixture*, not a *fallback*. Production code that silently falls back to fake data is a bug. |
| 4 | **⚡ Smallest-Model-That-Works** | Default to deterministic code. If ML is needed, prefer scikit-learn / XGBoost. Use small transformers (≤ 100 MB) before mid-size LLMs. Use ≥ 1 B-param LLMs only when explicitly justified in the agent's `README`. |
| 5 | **📈 Scale Symmetry** | The same agent process runs whether there is 1 of it or 1000. State lives in Redis / Postgres, never in agent memory. |
| 6 | **🇹🇷 Turkish UX / English Infra** | All AI prompts, model outputs, user-facing error messages → **Turkish (TR-tr)**. All code, comments, log messages, metric names, config keys → **English**. |
| 7 | **🧪 Adversarial Tests Are First-Class** | Every public surface (HTTP, message bus topic, scraping callback) has at least one fuzzing / injection / chaos test. |
| 8 | **🔁 Phase Gates** | A phase ships only when its [Definition of Done](#-appendix-b--definition-of-done-per-phase) checklist is fully green in CI. |

---

## 🏗️ System at a Glance

```
                    ┌──────────────────────────────────────────┐
                    │           Flutter Clients (future)       │
                    │   (web, iOS, Android — Phase 15)         │
                    └────────────────────┬─────────────────────┘
                                         │ HTTPS + JWT
                                         ▼
                ┌────────────────────────────────────────────┐
                │     🟦  Go REST API Gateway  (Phase 9)     │
                │  identity • rate-limit • request shaping   │
                └─────────────────┬──────────────────────────┘
                                  │ Redis Streams (XADD)
                                  ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │                      🟪  Swarm Bus  (Redis / NATS)                 │
   │                topics: scrape.*, predict.*, proof.*, sec.*         │
   └───────┬───────┬──────┬──────┬──────┬──────┬──────┬──────┬──────────┘
           │       │      │      │      │      │      │      │
       ┌───▼─┐ ┌───▼─┐ ┌──▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼────┐ ┌▼────┐ ┌▼─────┐
       │Scrp │ │Cat  │ │Proc │ │Pred │ │Proof│ │Drift│ │Sec  │ │Maint │
       │N×   │ │ger  │ │essr │ │×N   │ │×N   │ │     │ │     │ │      │
       └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └─┬───┘ └──┬──┘ └──┬──┘ └──┬───┘
          │       │       │       │      │        │       │       │
          ▼       ▼       ▼       ▼      ▼        ▼       ▼       ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │   🟨  Storage Layer:  PostgreSQL (truth)  •  Redis (cache/bus)   │
   └──────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ HTTPS scrape (only in dev: → mock)
                                  │
                ┌─────────────────┴──────────────────┐
                │  🟫  Mock-Data Dev Stack (Phase 2) │
                │  nginx + self-signed certs +       │
                │  fake mackolik / nesine / tff      │
                └────────────────────────────────────┘
```

Legend: `Scrp`=Scraper, `Catger`=Categorizer, `Procr`=Processor,
`Pred`=Predictor, `Proof`=Proofreader, `Drift`=Drift Monitor,
`Sec`=Security/Malicious-Input, `Maint`=Self-Maintenance.

---

## 📋 Phase Overview

> **Cross-cutting data scope.** Every phase from 2 onward operates on the
> data planes, sources, and Record envelope defined in
> [`design/DATA_PIPELINE.md`](../design/DATA_PIPELINE.md). Read it before
> implementing any phase that touches scrapes, features, or training.

| # | Phase | Outcome | Depends On |
|---|---|---|---|
| **0** | Repo Reset & Cleanup | P2P removed, docs fresh, tests still green | — |
| **1** | Centralized Config & Hardcode Audit | One config layer, no magic numbers | 0 |
| **2** | Mock-Data Dev Stack | Local nginx mirrors all data sources via fake TLS | 0 |
| **3** | Swarm Foundation | Bus, agent registry, supervisor, base SDK | 1 |
| **4** | Core Worker Agents | Scrape → Categorize → Process → Store works end-to-end | 2, 3 |
| **5** | Predictor Swarm & Consensus | N predictors vote → calibrated probability | 4 |
| **6** | Proofreader & Drift Agents | Multiple proofreaders + drift watchdog gate publication | 5 |
| **7** | Defense Agents | Prompt-injection, payload anomaly, abuse detection live | 3 |
| **8** | Self-Maintenance Agents | Schema healer, autoscaler, optional code-patcher | 4, 6 |
| **9** | Go REST API & Identity | Flutter-ready public surface with JWT/mTLS | 5, 6, 7 |
| **10** | Turkish-First NLP Layer | TR input understood, TR output generated, dialect/typo tolerant | 5 |
| **11** | GPU/CPU/NPU Compute Strategy | RTX 4080m first, CPU + Intel/AMD NPU fallback | 5 |
| **12** | Adversarial & Chaos Test Suite | Fuzz / inject / chaos in CI | 7, 9 |
| **13a** | League + Competition Expansion — Top-5 EU + UEFA + WC/EURO | T1 leagues (top-5 EU + TR), domestic cups + super cups, UEFA UCL/UEL/UECL, FIFA WC, UEFA EURO + qualifiers, Nations League. Per [`design/COMPETITIONS.md`](../design/COMPETITIONS.md) + [`design/LEAGUE_CATALOG.md`](../design/LEAGUE_CATALOG.md). | 4 |
| **13b** | League Expansion — +10 popular leagues + their cups | Primeira Liga, Eredivisie, Pro League, TR Lig 1, Brasileirão, Liga Profesional Argentina, Liga MX, MLS, J1, K League 1 (each starts T2; promotes to T1 per readiness gate). | 13a |
| **13c** | Continental + Completeness | CONMEBOL Libertadores/Sudamericana/Recopa, AFC + CAF Champions Leagues, FIFA Club WC + Intercontinental, Copa América/AFCON/Asian Cup/Gold Cup, all WC qualifier confederations. | 13b |
| **14** | Cloud-Ready Packaging | Docker → K8s manifests, CSP-agnostic | 9 |
| **15** | Frontend Handoff (Flutter) | API contract frozen, sample client | 9 |
| **16** | **Emitter & Feed Contract** *(Pivot v3)* | DB/Redis state → NDJSON/Parquet feeds; swarm stops reading DB | R2 |
| **17** | **Scraper-Patcher + GitOps** *(Pivot v3)* | Auto-patching scraper with 5-gate 7-day auto-merge | 16, R3 |
| **18** | **Datasource Cohesion & Swarm Isolation** *(Pivot v3)* | Three-way isolation tests green; `ai/` tree deleted | 16, 17, R4 |
| **19** | **Global Catalog (deferred long-tail)** | Pluggable catalog architecture for every league listed on mackolik/nesine + every WC qualifier confederation. T3 (research) rows added now; promotion to T2/T1 deferred per business demand. | 13c |
| **20** | **Monetization (built-but-dormant)** | Tier-based entitlement engine + per-token quotas at the Go API. `MONETIZATION_ENABLED=false` default; flips on via single config change. Per [`design/MONETIZATION.md`](../design/MONETIZATION.md). | 9, 13a |
| **21** | **Enrichment Data Planes** | Add planes 6-9 (transfers, injuries/availability, referees, weather/pitch) + four derived views (market-movement, fixture-congestion, card-context, narrative-pressure). Per [`design/ENRICHMENT_DATA.md`](../design/ENRICHMENT_DATA.md). | 4, 6 |
| **R1–R6** | **Restructure Track** *(Pivot v3)* | Rename chart keys; move modules; absorb mock into `server`; delete shims; collapse config triangle | 2, stop-the-world (no parallel feature work) |

```
0 ─→ 1 ─→ 2 ─→ 3 ─→ 4 ─→ 5 ─→ 6 ─→ 9 ─→ 14 ─→ 15
                          ├─→ 7 ─┤
                          ├─→ 8 ─┤
                          ├─→ 10 ┤
                          ├─→ 11 ┤
                          └─→ 12 ┘
                          │
                          └─→ 13a ─→ 13b ─→ 13c ─→ 19 (parallel)
                          │
                          └─→ 21 (parallel; needs 4)
                          │
                                  9 ─→ 20
```

---

## 🧹 Phase 0 — Repo Reset & Cleanup

**Goal:** Remove all P2P code, prune stale docs, leave a green test suite.
**Owner:** infra
**Estimated effort:** 1 working day

### 0.1 Delete the P2P stack

- [x] Remove the entire `p2p/` directory (`config.py`, `node/`, `protocol/`, `coordination/`, `simulation/`, `tests/`).
- [x] Remove the `p2p` service from `docker-compose.yml`.
- [x] Remove `Makefile` targets: `p2p`, `p2p-simulate`, `p2p-continuous`, `p2p-scale-test`, `p2p-churn-test`, `p2p-shell`, `test-p2p`, `sim-p2p`, `logs-p2p`.
- [x] Strip `p2p` from `make test`, `make train-full` and any `PYTHONPATH` it injected.
- [x] Delete the `P2P_*` block from `.env.example`.

### 0.2 Drop P2P references from Python code

- [x] In `ai/tests/test_config_sync.py`: remove `_PYTHON_UNUSED_ENV_KEYS` P2P entries, the P2P pickle round-trip test, the `P2P_CONFIG` import path, and the `p2p/simulation/runner.py` entry of `_EXTRA_PYTHON_SCAN`.
- [x] In `ai/orchestrator/state_machine.py`: remove `--mode sim-only` / `--skip-p2p` paths and the P2P stage from the full pipeline.
- [x] `grep -RIn "p2p\|P2P\|peer\|gossip\|multicast" ai/ server/ --include='*.py' --include='*.go'` must return **0 lines** outside test fixtures.
      *(Verified 2026-04-19. Only matches: `ai/qid/collector.py` reuses `peer` for swarm peers; `test_config_sync.py::test_p2p_module_removed` is the regression guard; `training_pipeline.py` has a docstring noting the removal.)*
- [x] **2026-04-19 follow-up audit:** the `p2p/` working tree had been recreated by stray `__pycache__/` and `.pytest_cache/` artifacts (untracked). Re-deleted; `pytest tests/test_config_sync.py::test_p2p_module_removed` is green again. Added to the standing precaution list in §0.4.

### 0.3 Reset documentation

- [x] Delete every file under `docs/` (no archive).
- [x] Recreate `docs/README.md` (this commit).
- [x] Recreate `docs/planning/ROADMAP.md` (this file).
- [x] Land the `design/` and `guides/` skeleton files referenced from `docs/README.md`.

### 0.4 Verify green CI

- [x] `make test-ai` passes — `TestIncrementalRetrain` fixed by patching `model.trainer.get_xgb_params` to cap `n_estimators=20` inside the test (verified 2026-04-19: 355/355 ai tests pass in ~3 min).
- [x] `make test` passes (no `make test-p2p` to run anymore — that target is gone). Go side: `go test ./...` clean (no test files yet; compiles).
- [x] No `make` target prints `❌` on a fresh clone after `make env`. Verified P2P-free Makefile via `grep -n "p2p\|P2P" Makefile` → 0 matches.
- [x] **Stale-tree precaution:** `p2p/` must not reappear even as an empty directory holding `__pycache__/` or `.pytest_cache/`. The regression test `test_p2p_module_removed` checks `(REPO_ROOT / "p2p").exists()` (not `git ls-files`), so any process that recreates the directory will turn CI red. If it happens, run `rm -rf p2p` (no tracked files to lose) and re-run the suite.

### 0.5 Stale single-league artifacts (post-reframing cleanup)

Follow-up to the multi-league reframing tracked under `phase 0 → adapted` (2026-04-19). These are static reference assets that survived Phase 0 with TR-Süper-Lig-only framing or with internal data errors.

- [x] `README.md` — killed the 354-line stale P2P duplicate; reframed header + pitch as multi-league football with TR Süper Lig as the seeded default.
- [x] `ai/docs/README.md` — overview reframed; doctrine §6 ("Turkish UX, English infra") cited explicitly.
- [x] Docstrings corrected in `ai/common/config.py`, `ai/scraper/real_data.py`, `ai/model/real_features.py`, `ai/scraper/mackolik.py` (the last is now correctly labelled "TR-source adapter for the seeded default league").
- [x] `ai/common/betting_markets.json` — catalogue audit (2026-04-19):
  - Reframed `_meta.source` from "Turkish Süper Lig" to "any league offered on the Spor Toto Teşkilatı bulletin".
  - Fixed duplicate `short_code` collisions: `IYKG` (combined HT-result-and-BTTS vs first-half BTTS) → `IYSKG`/`IYSAU15`; `KCK` (cards vs corners) → `KCKART`.
  - Normalised draw label `"0"` → `"X"` in combined markets.
  - Standardised `iy_2y_kg` outcome labels to the `Var/Yok` convention used elsewhere.
  - Demoted "wins both halves" markets to `available_all_matches: false` (top-tier only on TR bulletins).
  - Added 26 genuinely-offered markets that were missing: `hangi_takim_kazanir` (which-team-wins-each-half), `hangi_takim_gol_atar` (4-way which-teams-score), `gol_olmaz` (no-goal), HT/FT-BTTS combined, total-goals-BTTS combined, full player-markets set (cards/assists/2+goals/first-scorer/last-scorer), new **Asian** category (Asian Handicap with full quarter-line ladder + Asian Total Goals), new **Specials** category (penalty / red card / which-team-red / VAR / 5-way score group).
  - `total_market_types` corrected: 72 → 98 (was wrong even before the additions).
  - Added `_meta.notes` documenting label conventions, card-points formula, and Asian quarter-line settlement.
  - Added `summary.changelog` row stamping the revision.

> 💡 **Example commit:** `chore(p2p): remove P2P stack — superseded by swarm pivot`
> Single squash commit; no half-removed files.

### 0.6 Centralized version chart (cross-cutting)

**Goal:** Every main component (`ai`, `server`, `xops`, `docs`, `infra_mock`, `source_watcher`, …) and the umbrella Negelir application carry an explicit SemVer, controlled from one place, mutated only through a stdlib-only Python CLI.

- [x] `xops/versioning/chart.json` — single source of truth. Schema: `{schema, project:{name,version,build,released}, components:{<key>:{version,description,last_changed}}, changelog[]}`. Every component starts at `1.0.0`; `project.build` increments on each component bump and resets when `project.version` itself bumps.
- [x] `xops/versioning/version.py` — CLI: `show [--changelog N]`, `bump --component <key> --level <major|minor|patch> [--note "..."]`, `validate`, `components`. Stdlib only. Importable as a library.
- [x] `xops/versioning/tests/test_version.py` — 19 tests covering: SemVer parse/bump, schema validation, component bump (build increments + `last_changed` stamps), `bump --component project` resets build to 0, save/load round-trip, **canonical-form guard** that fails on hand edits.
- [x] Makefile dispatcher: `make version.show`, `make version.bump COMPONENT=<key> LEVEL=<major|minor|patch> [NOTE="..."]`, `make version.validate`, `make version.components`.
- [x] AGENTS.md §6.1 documents the discipline: *every* PR that meaningfully changes a component must include a `version.bump` in the same commit. The canonical-form test guards against silent edits.
- [x] CI gate: `pytest xops/versioning/tests/` runs as part of `make test` (wired in `xops/makefile/tests.py::cmd_test`; verified 2026-04-24, 19/19 green).

> 💡 **Example bump:**
> `make version.bump COMPONENT=infra_mock LEVEL=minor NOTE="Phase 2 scaffolding landed"`
> → `infra_mock 1.0.0 → 1.1.0`, `negelir build 0 → 1`, changelog entry appended.

---

## ⚙️ Phase 1 — Centralized Configuration & Hardcode Audit

**Goal:** A single config layer per language; every tunable value documented in `.env.example`; CI fails on drift.
**Depends on:** Phase 0

### 1.1 Python config (`ai/common/config.py`)

- [x] Every value reads from `os.getenv(...)` with a documented default.
- [x] `defaults.yaml` mirrors the dataclass for human reference. _Drift between `defaults.yaml` and `.env.example` is enforced by `test_defaults_yaml_mentions_every_documented_tunable` (token-mention check) and `test_defaults_yaml_is_valid_yaml` (real `yaml.safe_load` parse + spot-checks for `paths.report_dir` and `operational.strict`, added in the second audit pass after a regex-only check failed to catch a key glued into another comment line). A full dataclass-driven generator is still on the backlog but no longer required to keep the two files honest._
- [x] `Config.validate(strict=False)` checks: types, ranges, weekday names, `lo < hi` on tuple ranges, URL schemes for HTTP endpoints.
- [x] Strict mode (`NEGELIR_STRICT=1`) refuses unknown env keys with the `NEGELIR_` / `SCRAPE_` prefixes. *(The legacy `P2P_` tripwire was removed 2026-04-24 along with the rest of the P2P deprecation; reintroduction is now blocked by the broader doctrine, not the prefix list.)*

### 1.2 Go config (`server/internal/config`)

- [x] Mirror the Python pattern: one `Config struct`, one `Load() (*Config, error)`, env-driven, validated.
- [x] Tag every field: `env:"NEGELIR_FOO" default:"42"`. Use `caarlos0/env/v10` or equivalent. _Implemented stdlib-only (small surface, easier to audit, no transitive deps)._
- [x] `go test ./internal/config -run TestEnvSync` enforces parity with `.env.example`.

### 1.3 Bidirectional sync test (already partially landed)

- [x] `ai/tests/test_config_sync.py` covers Python ↔ `.env.example`.
- [x] **New:** `server/internal/config/sync_test.go` covers Go ↔ `.env.example`.
- [x] **New:** a meta-test asserts no env key is owned by *both* Python and Go without a `# shared` marker comment in `.env.example` (`test_shared_env_keys_are_marked` + Go-side `TestSharedKeysAreMarked`).

### 1.4 Hardcode audit (one-shot scan)

Forbidden patterns enforced by an `xops/lint/no_magic.py` lint step (per AGENTS.md §5, all repo automation lives under `xops/`; the legacy `scripts/` folder was retired):

| Pattern | Allowed where |
|---|---|
| Numeric literal in business logic | Only inside test files or config defaults |
| `localhost:<port>` strings | Only in test fixtures |
| `time.sleep(<int>)` | Forbidden in production code; use config-driven timeouts |
| `requests.get("https://...")` | Forbidden; HTTP base URL must be config-driven |
| Float thresholds (`> 0.5`, `< 0.7`, …) | Must be named, sourced from config |

> 💡 **Example violation → fix:**
> `if accuracy < 0.55: alert()` → `if accuracy < cfg.drift_accuracy_floor: alert()`

- [x] `xops/lint/no_magic.py` enforces `time.sleep(<literal>)`, `localhost:<port>`, and `requests.<method>("http(s)://…")` over `ai/`. Wired as `make lint`. Use `# no_magic: allow` to acknowledge a deliberate exception.
- [~] Numeric literal / fuzzy float-threshold rules: deferred — a regex-only check produces too much noise; tracked for a follow-up sub-phase that pairs an AST-based scanner with a per-call allow-list.

---

## 🌐 Phase 2 — Mock-Data Dev Stack ("Fake Internet")

**Goal:** Spin up a local stack that *is* mackolik / nesine / tff / openfootball — same DOM, same JSON, same headers, same TLS — so scraping never hits the real internet during dev or CI.
**Depends on:** Phase 0
**Data scope reference:** [`design/DATA_PIPELINE.md`](../design/DATA_PIPELINE.md) defines the five planes (reference, schedule, live, editorial, market), the four sources, and the Record envelope every later phase consumes. Phase 2 stands the mock vhosts that serve those bytes.

### 2.1 Topology

```
       /etc/hosts (managed by `make hosts.install`)
            │
            ▼
   ┌───────────────────────┐        ┌───────────────────────┐
   │  nginx-mock           │ ──────▶│  postgres (read-only  │
   │  (TLS, self-signed CA)│        │   snapshot of seeds)  │
   │  vhosts:              │        └───────────────────────┘
   │   • mackolik.com      │
   │   • nesine.com        │
   │   • tff.org           │
   │   • api.openfootball  │
   └───────────────────────┘
```

### 2.2 Self-signed CA & per-domain certs

- [x] `infra/mock/ca/`: one root CA, generated on first `make mock.ca-init` (idempotent — re-runs are no-ops unless `--force`). Implemented in `xops/mock/ca.py` via openssl shell-out; 11 unit tests incl. real chain-verify + tamper detection.
- [x] `infra/mock/certs/`: leaf certs for each fake domain, regenerated when the domain list changes. `ca.issue_leaf(host)` drops `<host>/{key.pem, crt.pem, chain.pem}` and refreshes the serial file.
- [x] CA is mounted into `nginx-mock` and every agent container at `/etc/ssl/negelir-ca.crt` via `docker-compose.mock.yml`. `SSL_CERT_FILE` + `REQUESTS_CA_BUNDLE` are set on agent services so Python/requests/urllib pick it up without an image rebuild.
- [x] **No host-side cert install** — `/etc/hosts` is the only host-level edit; the root cert lives inside container mounts only.

### 2.3 Hosts-file integration

`make hosts.install` adds:

```
127.0.0.1   mackolik.local nesine.local tff.local openfootball.local
```

> ⚠️ Uses `.local` TLDs to avoid colliding with real DNS. The scraper config flips between
> real and mock by an env switch (`NEGELIR_SCRAPE_PROFILE=real|mock`); no code changes.

`make hosts.uninstall` cleanly removes them. Both targets are **idempotent** and bail out with a clear message if `/etc/hosts` is not writable, suggesting `sudo`.

### 2.4 Seed corpus

- [x] `infra/mock/seeds/` holds **frozen** captures: `*.html`, `*.json`, response headers (sibling `<file>.headers.json`), status codes. Seeded for all 4 sources on 2026-04-20.
- [x] `xops/mock/capture_engine.py` + `xops/makefile/mock.py::capture` perform rate-limited captures (1.5s inter-request delay; only declared paths, no crawling). Agent-runnable per AGENTS.md §2 #9; only git ops remain AI-restricted.
- [x] nginx serves seeds via `mocksrv` upstream (manifest-keyed `(host, path)` routing; `try_files`-style exact-match — no lua needed since mocksrv handles path logic in Go).
- [x] `infra/mock/seeds/manifest.json` records per entry: source URL, capture date, sha256, byte size, status, content_type. Re-generated atomically by `capture_all()`.

### 2.5 Integrity guarantees

- [x] `xops/mock/verify.py` re-hashes every seed and compares to `manifest.json`. Now wired into `make test` via `xops/makefile/tests.py` (runs alongside AI + swarm + versioning suites).
- [x] **Property test:** `xops/mock/tests/test_manifest_contract.py` parametrizes over every manifest entry and asserts (a) payload file exists, (b) sha256 matches, (c) byte count matches, (d) extension matches `content_type`, (e) every registered source in `xops/mock/sources.py` has at least one seed.

### 2.6 Makefile UX

```
make mock.up           # bring up nginx-mock + seeded postgres
make mock.down         # tear down
make hosts.install     # write /etc/hosts entries (sudo)
make hosts.uninstall   # remove them
make mock.trust        # install dev CA into the host trust store (sudo, opt-in)
make mock.untrust      # remove it (sudo)
make mock.capture      # ⚠️ hits the real internet, refreshes seeds
make mock.verify       # offline integrity check
make mock.smoke        # E2E: reset → capture → up → curl every vhost
```

### 2.7 Server-as-mock redesign

The current `server/` (Go) is **repurposed** as the mock-source backend:

- [x] Move existing API code to `server/cmd/api/` (will become Phase 9 surface). Done 2026-04-20; Dockerfile now builds both `/bin/server` and `/bin/mocksrv`.
- [x] New binary: `server/cmd/mocksrv/` — stdlib-only Go HTTP server; manifest-keyed `(host, path) → entry` routing; `/__mocksrv/health` + `/__mocksrv/reload` endpoints; 6 tests.
- [x] nginx-mock proxies `/` of each fake vhost to `mocksrv:8090` via deterministic vhost configs generated by `xops/mock/nginx.py`. `X-Negelir-Mock-Source` header carries the vhost so mocksrv can route.
- [x] Two run modes wired in `server/internal/config` (`MODE=api`, `MODE=mocksrv`) and the compose overlay (`docker-compose.mock.yml`) starts both services on a dedicated `mocknet` bridge.

> 💡 **Example flow:** scraper container resolves `mackolik.local` → 127.0.0.1 → nginx-mock → mocksrv → postgres seed table. The scraper code is **identical** to production scraping; only the URL changes via config.

### 2.8 Source-Watcher Agent (cross-cutting; powers the dev stack)

**Goal:** A long-running agent that periodically diffs the live upstream sources against the seed corpus + the scraper's expected schema, classifies each delta (cosmetic / semantic / schema-breaking), records it as audit history, and proposes scoped updates to the mock stack and the scrapers' selectors. The mock stack is only as good as its freshness watchdog — this is that watchdog.

**Why it lives here, not in Phase 8:** the Phase 2 dev stack must be trustworthy from day one. A stale mock is worse than no mock. The agent ships with Phase 2 (skeleton + deterministic differ + classifier today; full scheduling, AI summarization, and PR-opening land in Phase 8 once the swarm bus from Phase 3 is available).

**Doctrine constraint:** per Guiding Principle #4 (smallest model that works), the **classification rules are deterministic** — they never depend on an LLM. The optional LLM summarizer added in Phase 8 only ever *narrates* what the rules already decided; it never overrides them. This is what makes the agent testable and auditable.

#### 2.8.1 Module skeleton (this phase)

- [x] `ai/swarm/__init__.py` + `ai/swarm/source_watcher/__init__.py` — package home.
- [x] `differ.py` — pure recursive structural diff over JSON-compatible payloads. Returns `FieldDiff(path, kind, old, new)` records where `kind ∈ {added, removed, changed, type_changed}`.
- [x] `classifier.py` — rule-based mapping from `FieldDiff` → `{cosmetic, semantic, schema_breaking}`. `worst_severity()` for quick gating.
- [x] `tests/test_differ.py` — 9 tests covering diff (identical / add / remove / change / type-change / nested-list / summary-counts) and classifier (removed → breaking, added → semantic, whitespace → cosmetic, worst-of).

#### 2.8.2 Snapshot store + scheduler (next)

- [x] `snapshot_store.py` — append-only on-disk store under `infra/mock/seeds/history/<source>/<iso-date>.json`. Each entry records: URL, headers, status, sha256, timestamp.
- [x] `planner.py` — turns a classified diff into an actionable update plan: which seed files to refresh, which scraper selectors to flag, which `LeagueConfig` fields to revisit.
- [x] `scheduler.py` — periodic runner (cron-style cadence from `cfg.source_watcher_interval_min`). Skips network when `NEGELIR_SCRAPE_PROFILE=mock`.
- [x] CLI: `make watch.run` (one-shot), `make watch.history SOURCE=mackolik.local`, `make watch.sources`. Dispatchers in `xops/makefile/watch.py`; exercised end-to-end against the real seed corpus.

#### 2.8.3 LLM summarizer (Phase 8 graduation)

- [x] `summarizer.py` — stub landed behind an explicit `enabled=False` default. Produces TR-language narration from a `UpdatePlan`; falls back to a deterministic plan-derived string when the LLM is disabled, unreachable, or returns empty text. Phase 8 will swap in a real client without changing the caller.
- [x] Hard-fail tests (`test_summarizer_negative.py`, 6 tests): disabled→fallback, enabled-without-llm→fallback, `ConnectionError`/`TimeoutError`/empty-response all degrade to fallback rather than raise; the plan's `severity`/`actions` cannot be mutated by the summarizer.

#### 2.8.4 Tests (first-class — Guiding Principle #7)

- [x] Unit tests on differ + classifier (this phase).
- [x] Property test: for any pair of payloads, `classify(diff_json(a, a))` is empty; `classify(diff_json(a, b))` is non-empty iff `a != b`.
- [x] Adversarial fuzzing: random-tree generator (stdlib `random`, no `hypothesis` dep) to assert the differ is symmetric and produces unique paths across 200+ randomized cases.
- [x] Integration test: snapshot store + planner against a frozen pair of seed files (`ai/swarm/source_watcher/tests/fixtures/openfootball_v{1,2_breaking}.json` + `test_fixture_integration.py`).
- [x] **Negative test:** if the LLM summarizer is enabled and the LLM endpoint is unreachable, the agent must still complete its run and persist the deterministic plan (`test_summarizer_negative.py`).

#### 2.8.5 Definition of Done for §2.8

- [x] Skeleton landed; all unit tests green.
- [x] Scheduler implemented + tested with fake clock; exercised on the dev stack via `make watch.run` (4/4 sources snapshotted + re-run shows `unchanged` on identical seeds).
- [x] Drift events recorded under `infra/mock/seeds/history/` (first `watch.run` produced 4 `first_snapshot` entries on 2026-04-20).
- [x] End-to-end test where a deliberately tampered seed triggers a `schema_breaking` classification and the planner emits a non-empty update plan (`test_e2e_tampered_seed.py::test_tampered_seed_triggers_schema_breaking_plan` + `test_fixture_integration.py::test_openfootball_v1_vs_v2_schema_breaking`).
- [x] `source_watcher` component bumped to `1.2.0` in `xops/versioning/chart.json` (will move to ≥ `2.0.0` once Phase 8 LLM integration is live).

---

## 🐝 Phase 3 — Swarm Foundation (Bus, Registry, Supervisor)

**Goal:** A minimal but complete agent platform: every agent is a process that registers, subscribes to topics, publishes results, heartbeats, and dies safely.
**Depends on:** Phase 1
**Pivot v3 placement:** the agent SDK is shared infrastructure consumed by both `swarm/` (AI agents) and `datasource/` (scraper/watcher/refresher/patcher). After Phase R2 it lives at **`common/bus/`**. Until R2 lands, this phase ships under the transitional path **`ai/swarm/sdk/`** with the namespace structured so R2 is a directory move, not a rewrite.
**Scope discipline:** Phase 3 ships the SDK + bus implementations + registry + observation-only supervisor + an example echo agent. **It does not ship**: real worker agents (Phase 4), a compose service per agent (Phase 4 onward), a Go SDK (Phase 9 prerequisite), CBOR/CDDL framing (Phase 9 hardening), Prometheus scraping (Phase 11/12), OpenTelemetry tracing (Phase 12), or write-side orchestration like `restart`/`scale` (Phase 8 `maint.scaler.v1`).

### 3.1 Message bus

- [x] **Local / small prod:** Redis Streams (already in stack at `redis:7-alpine`). Topics are stream keys; consumer groups give per-agent at-least-once durability.
- [ ] **Large prod (future):** drop-in NATS JetStream — the SDK exposes a `Bus` interface; Redis and NATS are two implementations.
- [x] **In-memory bus** (`InMemoryBus`) for unit tests — same `Bus` interface, no Redis required. **Required deliverable** of this phase.
- [x] Encoding: **JSON for v1** (human-debuggable, zero new deps; the existing `redis-py` client carries strings natively). The `Bus` interface is encoding-agnostic via a `Codec` seam, so a CBOR+CDDL upgrade in Phase 9 is purely additive — no agent code changes.

### 3.2 Agent SDK

`ai/swarm/sdk/` (Python). The package layout is the post-R2 shape, importable as `swarm.sdk.*`-style internally so the R2 move is `git mv ai/swarm/sdk common/bus`:

```
ai/swarm/sdk/
├── __init__.py       # public re-exports: Agent, Bus, Message, run
├── types.py          # Message, Envelope, AgentSpec, Topic newtype
├── codec.py          # JsonCodec (default); pluggable for CBOR later
├── bus.py            # Bus protocol; InMemoryBus; RedisStreamsBus
├── registry.py       # Redis-backed agent_registry hash + heartbeat
├── agent.py          # Agent base class / Protocol
├── runner.py         # SIGTERM-safe event loop; consumer-group claim
├── metrics.py        # in-process counters; /metrics text exposition
└── tests/            # 40+ unit tests, in-memory bus only
```

```python
class Agent(Protocol):
    name: str                      # e.g. "scraper.mackolik.v1"
    subscribes: list[Topic]        # topics this agent consumes
    publishes:  list[Topic]        # topics it produces (declared up-front)
    async def handle(msg: Message) -> Iterable[Message]: ...
```

- [x] Auto-registers in `agent_registry` Redis hash on start (`HSET agent_registry <instance_id> <json>`); deregisters on `SIGTERM` / `SIGINT`.
- [x] Heartbeat every `cfg.swarm_heartbeat_sec` (default 5s) via `HSET agent_heartbeats <instance_id> <iso8601_utc>`; supervisor marks an instance **stale** after `3×` missed beats.
- [x] Built-in metrics: `msg_consumed`, `msg_published`, `msg_failed`, `msg_retried`, `msg_dlq`, `latency_ms_p50/p95/p99`. Exposed at `/metrics` in Prometheus text format on `cfg.swarm_metrics_port` (default `9100`).
- [x] Built-in correlation: every `Message` carries a `trace_id` (UUID4 string in the envelope). Stdlib only — no OpenTelemetry yet (deferred to Phase 12).

### 3.3 Bus semantics & guarantees (new)

This sub-phase nails down the contract every agent must obey. Consumers and tests both depend on it.

- [x] **At-least-once delivery.** Redis Streams + consumer groups guarantee the message is re-delivered on crash. **Handlers must be idempotent** — re-processing the same `(trace_id, topic)` must produce the same effect.
- [x] **Pending-claim policy.** A message claimed by a dead consumer is reclaimed by another after `cfg.swarm_pending_claim_sec` (default 60s) via `XAUTOCLAIM`.
- [x] **Retry budget.** Failed handler → re-queued up to `cfg.swarm_retry_budget` times (default 3); exhausted retries → DLQ stream `<topic>.dlq`.
- [x] **Dead-letter queue.** `<topic>.dlq` is a Redis stream capped at `cfg.swarm_dlq_max_len` (default 10 000) entries with `MAXLEN ~`. Phase 8 supervisor surfaces DLQ depth; Phase 3 only writes to it.
- [x] **Max in-flight.** Each agent claims at most `cfg.swarm_max_in_flight` (default 32) messages at a time → backpressure without blocking the event loop.
- [x] **Schema versioning.** Every `Message` envelope carries `{"schema_version": int}`. Producers send the highest they know; consumers refuse anything `> max_supported`. Migrations are explicit, not silent.
- [ ] **Bus auth.** Local dev: in-network Redis, no auth. Prod hardening (mTLS, ACLs) tracked under Phase 7.

### 3.4 Supervisor (read-only in Phase 3)

A small Go binary `server/cmd/swarmctl/` (lives next to `cmd/api` and `cmd/mocksrv`):

- [x] `swarmctl ps` — list registered agents, last heartbeat (with stale ✗ marker), per-topic message lag (XLEN minus consumer-group pending).
- [x] `swarmctl topics` — dump topic catalog with stream length + consumer-group pending count.
- [x] `swarmctl tail <topic> [-n N]` — stream the last N messages (JSON-formatted) for debugging.

> **Scope:** `swarmctl` is **read-only** in Phase 3. Mutating commands (`restart`, `scale`, `drain`) are write authority that belongs to Phase 8 `maint.scaler.v1`. Pre-shipping mutators here would create a blast-radius surface with no safety net.

### 3.5 Topic catalog (control plane)

> **Boundary clarification (Pivot v3).** This catalog covers **bus** topics (control + low-volume coordination). Per [`design/EMITTER.md`](../design/EMITTER.md), high-volume data records (per-Record schedules, fixtures, results) flow through **NDJSON/Parquet feeds**, not the bus, starting Phase 16. The legacy `scrape.raw` / `match.normalized` bus topics from earlier drafts are **not** part of v3.

| Topic | Producer | Consumer(s) | Payload |
|---|---|---|---|
| `scrape.request` | API gateway, scheduler | scrapers | `{league, source, target_date}` |
| `predict.request` | API gateway | predictor swarm | `{match_id, market}` |
| `predict.vote` | individual predictors | consensus agent | `{match_id, market, dist, model_id}` |
| `predict.final` | consensus | proofreader, storage, API cache | calibrated `Prediction` |
| `proof.flag` | proofreader | drift, security | `{prediction_id, reason}` |
| `sec.alert` | security agents | supervisor, telemetry | `{kind, source, severity}` |
| `maint.event` | self-maint | supervisor | `{kind, target, action}` |

Topic naming is `<area>.<verb>` (lower-snake). `<topic>.dlq` is reserved for dead-letter streams. Creating a new topic requires (a) a row in this table, (b) a JSON Schema in `ai/swarm/sdk/schemas/<topic>.json`, (c) a config-driven consumer-group prefix.

### 3.6 Existing-agent migration (clarification)

The `ai/swarm/source_watcher/` agent shipped in Phase 2.8 is **cron-driven** (its `scheduler.py` ticks on `cfg.source_watcher_interval_min`). It does **not** use the new SDK. It stays standalone through Phase 7 and migrates to the SDK in Phase 8 alongside its LLM-summarizer graduation. Phase 3 only adds *new* SDK-based agents; it does not retrofit existing ones.

### 3.7 Definition-of-Done for Phase 3

- [x] Echo agent (`ai/swarm/sdk/examples/echo.py`) consumes `echo.in`, publishes `echo.out` with payload echoed back, runs against `InMemoryBus` and `RedisStreamsBus` (latter requires `redis` service up).
- [x] **Throughput / leak test:** agent processes **10 000** echo messages with `InMemoryBus` (in-process); after drain, RSS delta < 5 MB, pending count == 0, registry hash empty, all 10 000 messages observed at the publisher.
- [x] **Crash-recovery test:** start an agent against `RedisStreamsBus`, kill the process mid-stream, restart it; all in-flight messages re-delivered exactly to the surviving consumer (at-least-once verified, no message lost).
- [x] **DLQ test:** an agent that always raises sees `cfg.swarm_retry_budget` re-deliveries followed by exactly one entry in `<topic>.dlq`.
- [x] **InMemoryBus parity:** the unit-test suite runs identically against `InMemoryBus` and (when `REDIS_HOST` resolves) `RedisStreamsBus`. CI uses `InMemoryBus` only — Redis-backed tests are opt-in via `NEGELIR_BUS_INTEGRATION=1`.
- [x] `swarmctl ps` and `swarmctl topics` show the echo agent and `echo.in` / `echo.out` correctly.
- [x] All seven config knobs from §3.3 surface in `xops/env/.env.example`, `ai/common/defaults.yaml`, and `ai/common/config.py`. Triangle test stays green.
- [x] Component bumps: `ai` minor (SDK landed) and a **new** chart key `swarm_sdk` seeded at `0.1.0` *(or, post-R, the existing `swarm` key bumped accordingly)*.

---

## 🛠️ Phase 4 — Core Worker Agents (Scrape → Categorize → Process → Store)

**Goal:** A clean linear pipeline of small, replaceable agents that turn a scrape request into a normalized `Match` row in Postgres.
**Depends on:** Phase 2, Phase 3
**Data scope reference:** [`design/DATA_PIPELINE.md`](../design/DATA_PIPELINE.md) is the contract this phase implements end-to-end. Records produced here become the input to Phase 5 predictors and Phase 10 NLP. The per-record change-detection rules used by the trainer-gating events are owned by [`design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md).

### 4.1 Scraper agents

One agent **per source** (`scraper.mackolik.v1`, `scraper.nesine.v1`, `scraper.tff.v1`).

- [ ] Pulls `scrape.request`, hits the source (mock or real per `NEGELIR_SCRAPE_PROFILE`).
- [ ] Respects per-source rate limit from config; uses token-bucket from Redis to coordinate with replicas.
- [ ] Emits `scrape.raw` carrying the raw bytes + content hash.
- [ ] No parsing here — *raw bytes only*. (Robust to upstream HTML changes.)
- [ ] Failure modes: `404` → `proof.flag`; `5xx` → exponential backoff + `sec.alert` if it persists.

> 💡 **Why split scrape from parse?** When mackolik changes its DOM, only the categorizer/processor needs updating. Raw captures stay valid for replay.

### 4.2 Categorizer agent (`categorizer.v1`)

- [ ] Consumes `scrape.raw`, classifies *what* it is (fixture list, match detail, lineup, odds page, irrelevant).
- [ ] **No LLM.** A small scikit-learn `LinearSVC` over TF-IDF features, ≤ 5 MB on disk. Trained from labelled seed corpus (Phase 2).
- [ ] Confidence threshold from config (`NEGELIR_CATEGORIZER_MIN_CONF`). Below threshold → routes to `proof.flag` for human/agent review.

### 4.3 Processor agents (`processor.<kind>.v1`)

One per content kind (fixture, match-detail, lineup, odds).

- [ ] Stateless parsers; each takes raw + categorizer label, emits `match.normalized`.
- [ ] Use `selectolax` (Python) for HTML — 10× faster than BeautifulSoup, no JS engine needed.
- [ ] **Schema-first:** output is validated against a Pydantic v2 model before publishing. Bad records go to `proof.flag` with the violation list.

### 4.4 Storage agent (`storage.v1`)

- [ ] Single writer for `matches`, `lineups`, `odds`, `outcomes` tables.
- [ ] Idempotent upserts keyed by `(source, source_match_id)`.
- [ ] Emits `match.stored` so caches/predictors can warm.

### 4.5 Cache agent (`cache.v1`)

- [ ] Watches `match.stored` and `predict.final`; populates Redis with TTLs from config.
- [ ] Exposes a tiny gRPC contract to the API gateway for explicit invalidation.

### 4.6 Telemetry agent (`telemetry.v1`)

- [ ] Subscribes to **everything** with a wildcard consumer group.
- [ ] Aggregates per-topic counters, error rates, latency histograms.
- [ ] Pushes to Prometheus (pull) and to a `telemetry.events` Postgres table for forensic queries.

### 4.7 Freshness-event reactors (`reactor.<name>.v1`)

**Why a dedicated sub-phase.** Phase 4 produces `Record`s and emits
the `freshness.events.v1` stream defined by
[`design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md). The
*reactions* — re-running the live predictor on a score change,
re-computing lineup features when an XI moves, debouncing retrains,
flagging value odds — are owned by **named reactors**, not by the
freshness module itself. CONTENT_FRESHNESS §15 is the spec; this
sub-phase is the implementation hook in the roadmap.

- [ ] Reactor base class in `ai/swarm/reactors/_base.py` enforcing
      §15.2 invariants: idempotent on `event_id` (per-reactor
      `processed_events` table), plane-bounded blast radius, no
      back-emission to `freshness.events.v1`, bounded replay window.
- [ ] First-cut reactors: `feature-store-reactor` and `cache-reactor`
      (smallest blast radius, exercise the SDK).
- [ ] Trainer reactor with debounce window, qualifying-event filter,
      accuracy-floor check, and cooldown (CONTENT_FRESHNESS §15.3).
      Publishes `model.trained` on `models.events.v1`.
- [ ] Live-predictor / NLP / market reactors per §15.1.
- [ ] Reactor failure isolation: each runs in its own consumer group;
      `reactor.degraded` emitted after `N` consecutive failures.
- [ ] Replay command: `make reactor.replay REACTOR=<name> SINCE=<ts>`
      for operator-driven recovery (no automatic replay on restart).
- [ ] Tests: per-reactor idempotency probe (replay same event twice
      → one side-effect); chaos test (kill -9 mid-side-effect → no
      half-state).

### 4.8 Definition of Done

- [ ] `make swarm-demo LEAGUE=tr_super_lig` triggers one scrape → one row in Postgres in < 10 s on the mock stack.
- [ ] Killing any single agent for 30 s and restarting it does not lose messages (consumer-group durability).

---

## 🎲 Phase 5 — Predictor Swarm & Consensus

**Goal:** Many small predictors vote on each match × market. A consensus agent fuses votes into a calibrated probability distribution.
**Depends on:** Phase 4

### 5.1 Predictor diversity (intentional, not coincidental)

The point of a swarm is to *disagree well*. Initial roster:

| ID | Backend | Size | Speciality |
|---|---|---|---|
| `pred.elo.v1` | Pure Python | 0 MB | Baseline Elo + home-advantage |
| `pred.dixon_coles.v1` | NumPy | 0 MB | Bivariate Poisson, classic |
| `pred.xgb_form.v1` | XGBoost | ~3 MB | Recent-form features |
| `pred.xgb_xg.v1` | XGBoost | ~3 MB | xG / shot-quality features |
| `pred.lgbm_market.v1` | LightGBM | ~4 MB | Odds-derived features (when permitted) |
| `pred.tabnet.v1` | PyTorch CPU/GPU | ~6 MB | Attention over tabular features |

> ⚠️ **No LLM predictors.** They are slow, overconfident on tabular data, and unjustified for this domain. If we ever add one, it goes here with a documented win in backtest.

### 5.2 Consensus agent (`consensus.v1`)

- [ ] Collects all `predict.vote` for a `(match_id, market)` until `cfg.consensus_window_ms` or all known predictors voted.
- [ ] Per-predictor weight learned from a rolling Brier-score window (`cfg.consensus_brier_window`); refreshed nightly.
- [ ] Output is **calibrated** with isotonic regression per market; calibration tables stored in Postgres and versioned.
- [ ] Publishes `predict.final` with: distribution, weights used, contributing model IDs, calibration version, confidence.

### 5.3 Backtesting harness

- [ ] `make backtest WEEKS=N` replays history through the live swarm against frozen mock seeds.
- [ ] Reports per-predictor accuracy, swarm accuracy, calibration ECE, log-loss, ROI under sample bookmaker odds.
- [ ] CI gate: swarm beats best individual predictor by ≥ 1 % log-loss on the last 6 months.

---

## ✅ Phase 6 — Proofreader & Drift Agents

**Goal:** Catch bad predictions, bad data, and slow model decay before they reach users.
**Depends on:** Phase 5

### 6.1 Multi-proofreader voting

- [ ] N proofreader agents (default 3, scalable). Each runs an independent set of rule-based + statistical checks.
- [ ] A `predict.final` is **published to API cache** only if `≥ ⌈N/2⌉ + 1` proofreaders pass it (configurable quorum).
- [ ] Failed checks emit `proof.flag` with structured reasons.

### 6.2 Built-in proofreader checks

- [ ] **Sanity:** probabilities sum to 1 ± ε; no negative; no NaN.
- [ ] **Plausibility:** away win > 0.85 in a derby — flag for review.
- [ ] **Consistency:** 1X2 distribution matches 0-0 / 2-1 / … score grid.
- [ ] **Cross-source:** agreement with implied probability from at least one external odds source (when available).
- [ ] **Historical:** prediction not wildly out vs. last-3-meetings prior.

### 6.3 Drift agent (`drift.v1`)

- [ ] Maintains rolling Brier / log-loss windows per league × market × predictor.
- [ ] Trips when (a) any window crosses `cfg.drift_accuracy_floor`, or (b) KS-test on input feature distribution rejects stationarity at `cfg.drift_pvalue`.
- [ ] On trip → `maint.event{kind:retrain_request, target:<predictor>}`.

---

## 🛡️ Phase 7 — Defense Agents (Malicious-Input, Anomaly, Rate Limit)

**Goal:** The system stays correct under adversarial input, both from users (API) and from upstream data sources.
**Depends on:** Phase 3

### 7.1 Prompt-injection / payload-anomaly agent (`sec.input.v1`)

- [ ] Sits **in front of** the NLP layer (Phase 10).
- [ ] Detects: prompt injection ("ignore previous instructions"), tool-call smuggling, base64-encoded payloads, zero-width chars, RTL overrides, oversized inputs, language-spoofing (claims TR but is a JS exfil).
- [ ] Detection strategy: fast **deterministic** rules first (regex / charset / length / NFC normalization); only escalate ambiguous cases to a small classifier (`distilbert-base-multilingual-cased`-style, ≤ 60 MB) running on GPU when available.
- [ ] Verdicts: `pass`, `sanitize`, `quarantine`. Quarantined → stored for human review; never reaches predictors.

### 7.2 Upstream-data anomaly agent (`sec.scrape.v1`)

- [ ] Watches `scrape.raw` for: sudden DOM size delta, suspicious JS, encoded redirects, mismatched content-type.
- [ ] Cross-checks content hash against the seed manifest in dev; in prod, compares to the rolling-30-day distribution per source.

### 7.3 Abuse / rate-limit agent (`sec.rate.v1`)

- [ ] Token-bucket per `client_id` (from JWT) and per `ip` (fallback). Limits live in config.
- [ ] Sliding-window anomaly detection (`cfg.sec_burst_threshold`).
- [ ] Issues `sec.alert` and updates a Redis denylist consulted by the API gateway.

### 7.4 Definition of Done

- [ ] All checks have a corresponding entry in [Phase 12](#-phase-12--adversarial--chaos-test-suite) test catalogue.
- [ ] No defense agent ever blocks the **happy path** in CI's golden-input suite.

---

## 🔧 Phase 8 — Self-Maintenance Agents (Schema Healer, Auto-Scaler, Coder)

**Goal:** Keep the system running without human intervention for the boring stuff.
**Depends on:** Phase 4, Phase 6

### 8.1 Schema-healer agent (`maint.schema.v1`)

- [ ] Listens to `proof.flag` reasons of kind `parse_failed` / `selector_missing`.
- [ ] Re-derives selectors from the seed corpus (or a rolling cache of recent raw scrapes) using **structural similarity**, not LLMs.
- [ ] Proposes a patch to `scraper/selectors.json`; opens a PR via the local git server in dev, or auto-applies if the change touches only declared "self-healable" fields (configured allow-list).

### 8.2 Auto-scaler agent (`maint.scaler.v1`)

- [ ] Reads telemetry: stream lag per topic, agent CPU, predictor latency.
- [ ] Decides desired replica counts; writes them to `agent_desired_state`.
- [ ] In compose: invokes `docker compose up -d --scale <svc>=N`. In K8s: patches Deployment replicas via the in-cluster API.
- [ ] **Hard caps** from config to prevent runaway in cloud (`cfg.max_replicas_per_agent`).

### 8.3 Auto-coder agent — *moved to Phase 17*

> **Pivot v3 (2026-04-20).** Auto-coding is owned by `datasource/patcher/` and
> scoped to scraper failures only. Spec: [`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md).
> Roadmap milestone: **Phase 17 — Auto-Patching Scraper**. The
> standalone `maint.coder.v1` agent is dropped.

### 8.4 Backup / retention agent (`maint.backup.v1`)

- [ ] Postgres logical dumps to local volume; pruned by config TTL.
- [ ] Verifies dumps by restoring into a throwaway DB nightly.

---

## 🟦 Phase 9 — Go REST API & Identity (Public Surface)

**Goal:** A clean, versioned, secured REST API in Go that Flutter and external clients can call.
**Depends on:** Phase 5, Phase 6, Phase 7

### 9.1 Surface (v1)

```
GET  /v1/healthz
GET  /v1/leagues
GET  /v1/leagues/{id}/fixtures?from=&to=
GET  /v1/matches/{id}
GET  /v1/matches/{id}/predictions?market=ms,au_2.5,...
POST /v1/qa                   # natural-language Turkish Q&A → answer + citations
POST /v1/auth/login           # exchange credentials → JWT
POST /v1/auth/refresh
GET  /v1/me
```

- [ ] All responses JSON, `application/json; charset=utf-8`.
- [ ] All times ISO-8601 UTC.
- [ ] Pagination: `?cursor=...&limit=...`, never offset.

### 9.2 Identity & auth

- [ ] Local users in Postgres, bcrypt-hashed passwords.
- [ ] **JWT** (RS256) for clients; key pair generated at first run, lives in a Docker volume.
- [ ] **mTLS** between Go API and the swarm bus / Postgres / Redis (using the Phase 2 internal CA).
- [ ] Optional OIDC plug-point for future social login — interface defined, no provider bundled.
- [ ] No external secret-manager dependency. Local-experimental scope per project doctrine.

### 9.3 Request flow

```
client → API gateway → JWT verify → rate-limit (sec.rate.v1)
       → publish predict.request → wait on predict.final (with timeout)
       → return JSON
```

- [ ] Uses Redis as a per-request RPC pattern: API publishes with a `reply_to` topic and waits ≤ `cfg.api_request_timeout_ms`.
- [ ] If timeout: return cached prediction if any; otherwise `503` with a `Retry-After` hint.

### 9.4 OpenAPI

- [ ] `server/api/openapi.yaml` is the source of truth. Go handlers are generated with `oapi-codegen`. CI fails if handler signature drifts from spec.
- [ ] `make api-docs` renders Swagger UI at `localhost:8081`.

---

## 🇹🇷 Phase 10 — Turkish-First NLP Layer

**Goal:** Users type messy Turkish; the system understands and answers in fluent Turkish, even with typos, missing diacritics, or local dialect.
**Depends on:** Phase 5

### 10.1 Input normalization

- [ ] Pipeline: NFC normalize → lowercasing with Turkish dotted-i rules → diacritic restoration (`zemberek-python`-style) → tokenization.
- [ ] **Typo tolerance:** edit-distance candidate generation against the team / player / league lexicon (Phase 13). Edit budget from config.
- [ ] **No diacritics → diacritics:** "fenerbahce" → "Fenerbahçe" via a learned mapping table (no LLM).
- [ ] **Slang & dialect:** lookup table maintained in `ai/nlp/lexicon/dialects.tr.yaml`, easy to extend.

### 10.2 Intent + entity extraction

- [ ] Small fastText classifier for intent (≤ 20 MB), trained on labelled queries.
- [ ] Entity extraction: hybrid — gazetteer for teams/players/leagues + a small CRF for dates and markets.
- [ ] Confidence below `cfg.tqu_min_intent_conf` → "Did you mean?" reformulation, not a guess.

### 10.3 Answer generation

- [ ] Template-driven Turkish responses (jinja2 + Turkish-aware suffix handling).
- [ ] One small Turkish LLM (≤ 1 B params, e.g. `Trendyol-LLM-1B-base`) used **only** for free-form rephrasing of the templated answer when `cfg.tqu_humanize=true`. **Never used for the actual prediction.**
- [ ] Output goes through a "Turkish quality" proofreader agent that flags grammar / register issues before sending.

### 10.4 Test corpus

- [ ] `ai/tests/fixtures/turkish_queries.yaml`: 200+ real-shaped queries with typos, missing diacritics, slang, mixed-case, code-switching ("bugün Galatasaray maçı kaçta?").
- [ ] A subset is **adversarial**: prompt injections, jailbreaks, off-topic.

---

## 🎮 Phase 11 — GPU/CPU/NPU Compute Strategy

**Goal:** Train and infer on whatever the host has, in this priority: **CUDA GPU → ROCm GPU → NPU (Intel/AMD) → CPU**.
**Depends on:** Phase 5

### 11.1 Device probe (`ai/model/device.py`)

- [ ] On startup: enumerate `torch.cuda`, ROCm, OpenVINO (Intel NPU), DirectML (AMD NPU on Windows hosts), MPS (Mac, low priority).
- [ ] Pick by config: `NEGELIR_DEVICE=auto|cuda|rocm|npu|cpu`. `auto` follows the priority above.
- [ ] Log the choice with capabilities (VRAM, compute capability, NPU TOPS) at INFO.

### 11.2 RTX 4080 mobile (12 GB) targets

- [ ] All XGBoost / LightGBM training: GPU enabled by default, falls back to CPU on OOM.
- [ ] Predictor model bundles fit ≤ 1 GB VRAM each so multiple replicas co-exist on the GPU.
- [ ] LLM-based agents (Phase 7 fallback classifier, Phase 10 humanizer, Phase 8 coder) share the GPU via a tiny in-process round-robin scheduler; never load two LLMs simultaneously by default.

### 11.3 CPU fallback

- [ ] All models must pass the `cpu_only` test marker — same accuracy, slower throughput.
- [ ] Container images install both `xgboost-cpu` wheel and (separately) the `xgboost` GPU wheel; the device probe selects.

### 11.4 NPU support

- [ ] Intel NPU via OpenVINO for the categorizer + sec.input classifier (both small enough).
- [ ] AMD XDNA NPU support: stretch goal, behind `NEGELIR_NPU_VENDOR=amd` flag.
- [ ] No NPU? No problem — they are accelerators, not requirements.

### 11.5 Cloud parity

- [ ] Same image runs on Azure NC-series (NVIDIA), AKS with no GPU (CPU-only), or AWS Inf2 (Inferentia) with a vendor-specific extras image.

---

## 🧪 Phase 12 — Adversarial & Chaos Test Suite

**Goal:** Make sure the system survives bad weather, bad neighbours, and bad actors.
**Depends on:** Phase 7, Phase 9

### 12.1 Test taxonomy

| Layer | Kind | Examples |
|---|---|---|
| **Unit** | Pure logic | `test_dixon_coles_grid_sums_to_one` |
| **Integration** | Agent ↔ bus ↔ agent | `test_scraper_to_storage_happy_path` |
| **Contract** | OpenAPI / message schemas | `test_predict_final_matches_cddl` |
| **Property** | Invariants under random input | `hypothesis` strategies for `Match` |
| **Adversarial** | Prompt injection, payload abuse | `test_qa_resists_ignore_previous_instructions` |
| **Fuzz** | Random bytes at every boundary | `boofuzz` against the API gateway |
| **Chaos** | Kill agents, slow Redis, partition | `pumba` / `toxiproxy` in CI |
| **Soak** | Long-run stability | overnight job in nightly CI |

### 12.2 Adversarial corpus (`ai/tests/fixtures/adversarial/`)

- [ ] Prompt-injection set (Turkish + English).
- [ ] Malformed HTML injections served by a chaos variant of the mock server.
- [ ] Oversized / zero-width / RTL-flip Turkish queries.
- [ ] Replayed real attacker traffic patterns (synthetic, generated for tests only).
- [ ] **Each entry maps to the agent that must catch it.** A miss = a failing test.

### 12.3 Chaos lab

- [ ] `make chaos-redis-flap` — drops Redis for 5 s, asserts no message loss, no double-processing.
- [ ] `make chaos-kill-predictor PCT=50` — kills half the predictors; consensus must still publish (with degraded confidence flag).
- [ ] `make chaos-network-slow` — 500 ms added between agent ↔ bus; latency budgets must hold.

### 12.4 Coverage gates

- [ ] Per-package line coverage ≥ 85 %.
- [ ] Adversarial suite must have zero `xfail` — a known weakness is a release blocker, not a known issue.

---

## 🌍 Phase 13 — League + Competition Expansion (split into 13a / 13b / 13c)

**Goal:** Grow from one league (TR Süper Lig) to a globally-meaningful roster. The architecture is **already league-agnostic** — every agent reads `LeagueConfig` + the new `CompetitionConfig` rather than hardcoding. This phase only adds *data* (presets, calibration profiles, lexicons, source seeds), not code branches.

**Anchor docs (binding):** [`design/LEAGUE_CATALOG.md`](../design/LEAGUE_CATALOG.md) (T1/T2/T3 tiers + readiness gates), [`design/COMPETITIONS.md`](../design/COMPETITIONS.md) (cup/tournament shapes + calibration profiles), [`design/ENRICHMENT_DATA.md`](../design/ENRICHMENT_DATA.md) (planes 6-9 needed for cards/player markets).

> ℹ️ The seeded default since v2.0.0 is the **Turkish Süper Lig** (`tr_super_lig`). All other leagues land via the catalog file `ai/common/league_catalog.yaml` + per-league preset modules under `ai/common/leagues/<league_id>.py` (LEAGUE_CATALOG.md §6).

### 13a — Top-5 EU + TR + UEFA + WC/EURO (foundation expansion)

**Domestic leagues (T1):**

- [x] 🇹🇷 Süper Lig — *seeded default since v2.0.0*
- [ ] 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League
- [ ] 🇪🇸 La Liga
- [ ] 🇩🇪 Bundesliga
- [ ] 🇮🇹 Serie A
- [ ] 🇫🇷 Ligue 1

**Domestic cups + super cups (T2 → T1 after beta):**

- [ ] 🇹🇷 Türkiye Kupası, TFF Süper Kupa
- [ ] 🏴󠁧󠁢󠁥󠁮󠁧󠁿 FA Cup, EFL Cup, Community Shield
- [ ] 🇪🇸 Copa del Rey, Supercopa de España
- [ ] 🇩🇪 DFB-Pokal, DFL-Supercup
- [ ] 🇮🇹 Coppa Italia, Supercoppa Italiana
- [ ] 🇫🇷 Coupe de France, Trophée des Champions

**Continental club (T2):**

- [ ] 🇪🇺 UEFA Champions League (qualifying + league phase + knockout)
- [ ] 🇪🇺 UEFA Europa League (qualifying + league phase + knockout)
- [ ] 🇪🇺 UEFA Conference League
- [ ] 🇪🇺 UEFA Super Cup (one-off)

**International (T2):**

- [ ] 🌍 FIFA World Cup (group + knockout)
- [ ] 🇪🇺 UEFA EURO Championship (group + knockout)
- [ ] 🌍 WC qualifiers (UEFA confederation)
- [ ] 🇪🇺 EURO qualifiers
- [ ] 🇪🇺 UEFA Nations League

**Cross-cutting (one-time platform work to enable 13a/b/c):**

- [ ] `ai/common/league_catalog.yaml` schema + loader committed.
- [ ] `CompetitionConfig` + `CompetitionStage` types per `COMPETITIONS.md` §2.
- [ ] `FixturePayloadV2` lands with `competition_id`/`format`/`stage_id`/`leg_index`/`venue_policy` per `COMPETITIONS.md` §3.
- [ ] CalibrationProfile resolution per `COMPETITIONS.md` §4.5.
- [ ] Per-league `LeagueConfig` modules under `ai/common/leagues/<league_id>.py` (LEAGUE_CATALOG.md §6).
- [ ] Tier promotion gate `xops/leagues/readiness.py` (LEAGUE_CATALOG.md §2).
- [ ] `make test.leagues` target (LEAGUE_CATALOG.md §8).

### 13b — +10 most popular non-Top-5 leagues (T2)

Each starts at T2 (publicly available with widened CI) and promotes to T1 once the readiness gate passes (LEAGUE_CATALOG.md §2.2). Headline domestic cups land alongside their league.

- [ ] 🇵🇹 Primeira Liga
- [ ] 🇳🇱 Eredivisie
- [ ] 🇧🇪 Pro League
- [ ] 🇹🇷 TR Lig 1 (2nd tier — required for Türkiye Kupası identity resolution)
- [ ] 🇧🇷 Brasileirão Série A
- [ ] 🇦🇷 Liga Profesional Argentina
- [ ] 🇲🇽 Liga MX
- [ ] 🇺🇸 MLS
- [ ] 🇯🇵 J1 League
- [ ] 🇰🇷 K League 1

### 13c — Continental + Completeness pass

- [ ] 🌎 CONMEBOL Libertadores, Sudamericana, Recopa
- [ ] 🌏 AFC Champions League Elite + Two
- [ ] 🌍 CAF Champions League
- [ ] ⚽ FIFA Club World Cup
- [ ] ⚽ FIFA Intercontinental Cup
- [ ] 🌎 Copa América, AFCON, Asian Cup, Gold Cup
- [ ] 🌍 WC qualifiers (all confederations not in 13a)

### 13.x NLP per league (cross-cutting; applies to a/b/c)

- [ ] Foreign team names get TR transliteration ("Bayern" → "Bayern Münih" with both forms accepted).
- [ ] Entity-extraction lexicons per league, merged at runtime.
- [ ] Phase 10 `transfer_lookup`/`injury_lookup`/`referee_lookup`/`weather_lookup`/`suspension_lookup` intents land alongside `13a` (see Phase 21).

---

## ☁️ Phase 14 — Cloud-Ready Packaging (Docker → K8s → CSP-Agnostic)

**Goal:** Same code, three deployment shapes: laptop compose, single-VM compose, K8s on any CSP.
**Depends on:** Phase 9

### 14.1 Compose profiles

- [ ] `docker-compose.yml` = base.
- [ ] `compose.dev.yml` (mock stack overlay).
- [ ] `compose.prod.yml` (no mock, real CA, restart policies).
- [ ] `make up`, `make up-dev`, `make up-prod` — each composes the right files.

### 14.2 Helm chart (`infra/helm/negelir/`)

- [ ] One chart, all components as sub-charts.
- [ ] Values for: image registry, replica counts, resource requests/limits, GPU node selector, ingress class, TLS issuer.
- [ ] **No CSP-specific resources** in the base chart. Optional sub-charts per CSP under `infra/helm/csp/<azure|aws|gcp>/`.

### 14.3 Image strategy

- [ ] Multi-arch (`linux/amd64`, `linux/arm64`).
- [ ] Per-component image, never a "monolith" image.
- [ ] Reproducible builds: pinned base digests, no `latest` tags.
- [ ] Two flavors per ML image: `-cpu`, `-gpu` (CUDA), with shared base.

### 14.4 Secrets & config in cloud

- [ ] Prod uses K8s Secrets for credentials (still no external secret manager required).
- [ ] Same env-var names as local; the `Config` layer doesn't care where the value came from.

### 14.5 Observability

- [ ] Prometheus scrape configs as a `ServiceMonitor` (when Prometheus Operator present) or a sidecar config.
- [ ] OpenTelemetry traces shipped to any OTLP-compatible backend (Tempo, Jaeger, vendor SaaS).

---

## 📱 Phase 15 — Frontend Handoff (Flutter, Future)

**Goal:** Provide a stable contract and a thin reference client.
**Depends on:** Phase 9

- [ ] Freeze `/v1/*` REST surface; major-bump only via `/v2/...`.
- [ ] Generate Dart client from OpenAPI in `clients/flutter/lib/api_client.dart`.
- [ ] Provide one example screen (fixture list → tap → predictions) for both web and mobile.
- [ ] Localization: ship `tr_TR` first; English later.

> *No further Flutter work is planned in this roadmap version. Phase 15 exists to keep the API surface honest.*

---

## 📤 Phase 16 — Emitter & Feed Contract (Production Pivot v3)

**Goal:** A dedicated `datasource/emitter` component projects Postgres + Redis state into NDJSON live feeds and Parquet training snapshots. After this phase, the swarm **only** reads feeds — no swarm code opens a DB connection, ever.
**Depends on:** Phase R2 (modules moved to `datasource/`).
**Anchor docs:** [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md), [`design/EMITTER.md`](../design/EMITTER.md), [`design/DATA_PIPELINE.md`](../design/DATA_PIPELINE.md).

### 16.1 Feed contract (frozen before code lands)

- [ ] `common/schemas/feeds/registry.json` ships with `v1` for all six record types (reference, schedule, score, lineup, editorial, market).
- [ ] JSONSchema 2020-12 files land under `common/schemas/feeds/` and are loaded by both emitter (writer) and `FeedReader` (reader).
- [ ] Contract test `common/schemas/tests/test_registry_consistent.py` passes.

### 16.2 `FeedWriter` + NDJSON (R3.1–R3.2)

- [ ] `datasource/emitter/writer.py` — per-`(plane, source)` append-only writer with atomic daily rotation at 00:00 UTC.
- [ ] `manifest.json` updated atomically per tick (EMITTER §5).
- [ ] Proof tests: `test_atomic_manifest.py`, `test_at_least_once_duplicates.py`, `test_monotonic_captured_at.py`, `test_utc_only.py` (all specified in EMITTER §6.1).
- [ ] One live NDJSON feed running end-to-end for the `reference` plane against mock seeds; property-based fuzzer covers the writer.

### 16.3 Parquet training snapshots (R3.3)

- [ ] `datasource/emitter/snapshot.py` — hourly hive-partitioned snapshots (`asof=YYYY-MM-DDThh/source=<s>/part-0000.parquet`).
- [ ] Schema generator converts `common/schemas/records.py` TypedDicts into pyarrow schemas; drift CI test fails if they diverge.
- [ ] Proof test: `test_parquet_snapshot_identical_to_ndjson_union` — the union of a day's NDJSON ≡ that day's Parquet snapshots (modulo compression).

### 16.4 `FeedReader` (R3.4)

- [ ] `common/feeds/__init__.py` exposes `FeedReader.stream(plane, sources, since)` and `FeedReader.snapshot(plane, as_of, sources)`.
- [ ] Reader rejects any path not referenced in `manifest.json`.
- [ ] Proof tests: `test_reader_roundtrip.py`, `test_reader_handles_version_skew.py`, `test_reader_rejects_guessed_paths.py` (all specified in EMITTER §8.1).

### 16.5 Swarm migration to feeds (R3.4)

- [ ] One predictor (`pred.elo.v1`) migrated to read from `FeedReader` only; parity test against the DB-reading version on 4 weeks of mock history shows identical outputs.
- [ ] `swarm/tests/test_no_db_imports.py` — no file under `swarm/` imports `psycopg` or `redis`. **This is the cornerstone swarm-isolation test.**
- [ ] All other predictors migrated over the phase; each migration gates on an individual parity check.

### 16.6 Versioned-schemas evolution (R3.5)

- [ ] Land a second active version of `score.v2` (additive) and confirm emitter writes both while a `score.v1`-pinned predictor stays green.
- [ ] Proof test: `test_emitter_writes_all_active_versions.py`, `test_reads_versioned.py`.

### 16.7 Storage backends (R3.6)

- [ ] Local-disk driver (default) and S3-compatible driver (MinIO in dev, Azure Blob / AWS S3 in prod) behind one `FeedsStore` protocol.
- [ ] Proof test: `test_s3_roundtrip.py` against MinIO in a compose-side container.

### 16.8 Retention & cold rollup (R3.7; Phase 14 prerequisite)

- [ ] `make feeds.prune` with configurable retention (default 30 days NDJSON, 365 days snapshots).
- [ ] Monthly cold rollup (`cold/<plane>/<YYYY-MM>/<source>.parquet`).
- [ ] Proof test: `test_retention.py`, `test_cold_rollup_coverage.py`.

### 16.9 Definition of Done

- [ ] All six planes emit NDJSON live feeds and hourly Parquet snapshots against the mock stack.
- [ ] `FeedReader` is the only supported way for `swarm/*` to read ingested data.
- [ ] `test_swarm_isolation.py` (no `datasource.*` imports outside `FeedReader`) and `test_no_db_imports.py` (no `psycopg`/`redis` under `swarm/`) both green in CI — they are complementary, not duplicates.
- [ ] All EMITTER §6.1 writer-guarantee tests green: `test_atomic_manifest`, `test_at_least_once_duplicates`, `test_monotonic_captured_at`, `test_utc_only`, `test_append_only`, `test_midnight_rotation`.
- [ ] All EMITTER §7.3 storage tests green: `test_s3_roundtrip`, `test_retention` (object-lock test may stay `xfail` until Phase 14).
- [ ] All EMITTER §8.1 reader-contract tests green: `test_reader_roundtrip`, `test_reader_handles_version_skew`, `test_reader_rejects_guessed_paths`.
- [ ] Versioned-schema coexistence verified: `test_emitter_writes_all_active_versions` and `test_reads_versioned` green with `score@v1` and `score@v2` active simultaneously.
- [ ] At least one live predictor and one trainer run migrated to feeds with parity maintained.
- [ ] `datasource_emitter` component bumped to ≥ `1.0.0`; `swarm` component bumped to reflect the read-surface change.

---

## 🛠️ Phase 17 — Scraper-Patcher + GitOps (Production Pivot v3)

**Goal:** Close the loop between "a scraper broke" and "a PR fixed it." Ship the `datasource/patcher` + `datasource/gitops` components with the guardrails specified in [`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md).
**Depends on:** Phase 16 (feeds in place — shadow regression gate needs them), Phase R3 (skeletons landed).
**Anchor docs:** [`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md), [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md).

> ⚠️ **Safety rail.** Phase 17 is the riskiest phase in the roadmap. It grants an AI component the ability to edit the repository. Every sub-phase is gated by a config flag and every change is reversible by a single env-var flip. See SCRAPER_PATCHER.md §8 Kill Switches.

### 17.1 Failure artifact schema + detectors (R3.a)

- [ ] `common/schemas/patcher/artifacts.json` (JSONSchema) defines the artifact shape (SCRAPER_PATCHER §2).
- [ ] Every detector writes to `postgres.patcher_artifacts` (append-only) and publishes on the `patcher.artifact.v1` stream.
- [ ] Proof tests: one per artifact kind (`test_parse_failure_emits_artifact.py`, `test_structural_drift_emits_artifact.py`, `test_content_stall_emits_artifact.py`, `test_extractor_empty_emits_artifact.py`, `test_parity_failure_emits_artifact.py`).

### 17.2 Patcher in dry-run mode (R3.b)

- [ ] `datasource/patcher/` scaffolded: artifact consumer, **diagnostic bundle builder** (SCRAPER_PATCHER §12.3), **classifier router** (§12.2), **Anthropic Agent SDK client**, diff parser, scope enforcer, size enforcer, forbidden-pattern scanner, sandbox runner, gauntlet runner, **cost ledger**.
- [ ] **Model provider locked.** Anthropic Agent SDK with three pinned model IDs (Haiku → Sonnet → Opus); env vars `NEGELIR_PATCHER_TIER{1,2,3}_MODEL` populated. Local-model alternative (qwen2.5-coder / deepseek-coder) retained as a documented contingency only.
- [ ] **CLAUDE.md** + per-scope context files under `xops/patcher/context/` shipped (SCRAPER_PATCHER §12.5).
- [ ] **Tool allow-list enforced** via Agent SDK `can_use_tool` callback (§12.4).
- [ ] **Pre-LLM reproduction check** wired (§12.9) — non-reproducing artifacts skip the API.
- [ ] Dry-run mode: patcher stores bundles under `feeds/ops/bundles/` but never hands off to `gitops`. **No real-money API calls in this sub-phase** (mocked SDK responses for development).
- [ ] Proof tests: all seventeen in SCRAPER_PATCHER §12.14, plus the seven scope-enforcement tests in §3.5.

### 17.2a Budget guard + classifier routing live before any real PR opens (R3.b')

- [ ] Cost ledger writes verified against Anthropic usage API to ±1 % (`test_cost_ledger_accuracy.py`).
- [ ] Hard caps from §12.6 all enforced and tested:
  `NEGELIR_PATCHER_MONTHLY_USD_CAP` (default $20), `_PER_DAY_USD_CAP` (default $5), `_PER_ARTIFACT_USD_CAP` (default $0.50).
- [ ] Deduplication + per-source cooldown + global rate limit live (§12.7) and tested.
- [ ] Past-success seeding wired into bundle builder (§12.8) and verified by `test_past_success_seeded.py`.
- [ ] **First $5 of real Anthropic spend** against mock-stack artifacts in this sub-phase. Tier-1 only (Haiku).

### 17.3 GitOps with auto-merge disabled (R3.c)

- [ ] `datasource/gitops/` scaffolded: GitHub App token exchange, branch + PR open, polling loop, label handling.
- [ ] `NEGELIR_GITOPS_AUTOMERGE=0` is the default. First merges go through human review.
- [ ] Proof tests: all four in SCRAPER_PATCHER §5.4.

### 17.4 Auto-merge with 30-day cool-down (R3.d)

- [ ] Enable auto-merge with `cfg.gitops_cooldown_days=30`.
- [ ] Mandatory human review on the first 10 PRs per source; after 10 consecutive clean merges per source, `gitops` may rely on the 5-gate policy alone.
- [ ] Proof tests: the seven listed in SCRAPER_PATCHER §6.7.

### 17.5 Cool-down relaxed to 7 days (R3.e)

- [ ] Flip `cfg.gitops_cooldown_days` from 30 to 7 only after 50 consecutive patcher merges ship with no post-merge regression (verified by §17.6 watchdog).
- [ ] The 7-day value from SCRAPER_PATCHER §6 is locked in once this sub-phase completes.

### 17.6 Post-merge regression watchdog (R3.f)

- [ ] `gitops` watchdog subscribes to `freshness.events.v1` and `swarm.drift`; opens revert PR on parity-pass-rate regression > `cfg.gitops_regression_threshold` (default 5 %) within a 1 h window.
- [ ] Proof tests: `test_regression_triggers_revert.py`, `test_revert_has_same_scope.py`.

### 17.7 Security hardening

- [ ] GitHub App token lifetime ≤ 60 min; scope allow-listed to this repo only.
- [ ] Sandbox egress restricted to `mocksrv` by network policy; verified by `test_sandbox_isolation.py`.
- [ ] Secrets-shaped-string regex veto in patcher; verified by `test_forbidden_patterns.py`.
- [ ] Kill-switch test: `test_kill_switches.py` covers all three levels in SCRAPER_PATCHER §8.

### 17.8 Definition of Done

- [ ] A deliberately tampered seed triggers an artifact → a patcher bundle → a PR → a passing CI → (if cool-down elapses in fake-clock test) an auto-merge. End-to-end integration test: `datasource/patcher/tests/test_closed_loop.py`.
- [ ] **§1 guarantee #9 (no AI without artifact)** verified: `test_no_ai_without_artifact.py` green; the patcher refuses to call any LLM endpoint unless invoked with a serialized detector artifact.
- [ ] All kill switches verified in CI (`test_kill_switches.py` covers all three SCRAPER_PATCHER §8 levels).
- [ ] All five gates independently verified green + red (9 tests).
- [ ] Shadow regression test injects a 3 % log-loss delta and confirms Gate 4 blocks.
- [ ] **GitOps §1 guarantees #4, #7, #8** verified: `test_squash_trailer_format.py`, `test_only_gitops_holds_token.py`, `test_no_direct_push_to_main.py` all green.
- [ ] **Cost & safety floor verified**: `test_budget_caps.py`, `test_cost_ledger_accuracy.py`, `test_tool_allow_list.py`, `test_model_pin_enforced.py`, `test_past_success_seeded.py`, `test_pre_llm_reproduction_skips_api.py`, and `test_prompt_injection_separated.py` all green.
- [ ] `datasource_patcher` and `datasource_gitops` components bumped to ≥ `1.0.0`.

---

## 🧱 Phase 18 — Datasource Cohesion & Swarm Isolation (Production Pivot v3)

**Goal:** Enforce the three-way isolation between `datasource/`, `swarm/`, and `server/`. Delete `ai/` after the migration period.
**Depends on:** Phase 16 (feeds), Phase 17 (patcher/gitops), Phase R4 (shims deleted).
**Anchor docs:** [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) §6.

### 18.1 Isolation tests (R4)

- [ ] `common/tests/test_swarm_isolation.py` — no file under `swarm/` imports `psycopg`, `requests`, or `datasource.*`.
- [ ] `common/tests/test_datasource_isolation.py` — no file under `datasource/` imports `fastapi`, `flask`, or `swarm.*`.
- [ ] `common/tests/test_server_isolation.py` — no Go file under `server/` calls an ML library (`xgboost`, `torch`, etc.).
- [ ] All three run in `make test` and block CI on violation.

### 18.2 Shim deletion (R4)

- [ ] Zero CI warnings of the form `"DeprecationWarning: ai.* import is a Pivot v3 shim"`.
- [ ] `ai/` directory removed (along with its empty `__init__.py`). Single commit with a reassuring message.
- [ ] `test_ai_tree_gone.py` — asserts the path does not exist; prevents accidental recreation.

### 18.3 Compose cohesion (R4)

- [ ] Single `docker-compose.yml` with the profiles listed in COMPONENT_LAYOUT §4.
- [ ] `docker-compose.mock.yml` overlay removed; `mock` is a profile.
- [ ] `make up PROFILES=...` default updated; legacy `make up-dev` / `make up-mock` aliases removed.

### 18.4 Versioning finalization (R4)

- [ ] `ai` chart key marked `eol`; `source_watcher` renamed to `datasource_watcher` via the chart `rename` subcommand (recorded in the changelog).
- [ ] New chart keys all at `≥ 1.0.0` by end of Phase 18: `datasource_scraper`, `datasource_watcher`, `datasource_refresher`, `datasource_patcher`, `datasource_gitops`, `datasource_emitter`, `swarm`, `common`.

### 18.5 Definition of Done

- [ ] All three isolation tests green.
- [ ] `ai/` tree removed; regression test in place.
- [ ] Single compose file, single `make up` entry point, no overlays.
- [ ] Version chart canonical.
- [ ] A fresh clone runs `make up PROFILES=core,mock,datasource,swarm` and the smoke test passes.

---

## � Phase 19 — Global Catalog (deferred long-tail)

**Goal:** Per user directive #6 — *"add all the football leagues like Korean or Brazilian that're listed on mackolik.com and nesine.com alongside world cups (eliminations and championships) … not implementing it yet but revise and set the system ready for such change."* Phase 19 makes the long-tail addition a **single YAML edit per league** with zero platform changes.

**Anchor doc:** [`design/LEAGUE_CATALOG.md`](../design/LEAGUE_CATALOG.md) §5.

### 19.1 Catalog-pluggable architecture (delivered with 13a; verified here)

- [ ] Unit test: AST scan of `ai/` and `server/` rejects any `if league_id == "..."` literal — every league branch reads `league_catalog.yaml`.
- [ ] T3 has zero maintenance cost when empty: no predictor retraining, no NLP gazetteer hit, no monetization SKU.
- [ ] Identity strategy stays generic — `stable_id` minting in `CONTENT_FRESHNESS.md` §2 does not bake in any country list.
- [ ] Source-registry pluggable — adding a new long-tail-league source is a `xops/mock/sources.py` row + extractor + differ; no pipeline changes.

### 19.2 Long-tail ingest (deferred batches; pulled when business demand justifies)

- [ ] Per-batch process: capture seeds → add a T3 row to `league_catalog.yaml` → backtest → promote per LEAGUE_CATALOG.md §2. **No platform changes per league.**
- [ ] Initial deferred targets: every league listed on mackolik.com bulletin pages + every league on nesine.com that has odds coverage + every WC qualifier confederation not in 13a/c.
- [ ] Catalog roster grows in the YAML only — Phase 19 does not require new code.

### 19.3 Definition of Done

- [ ] AST-scan test green.
- [ ] At least 5 T3 rows committed (sample from CONCACAF / AFC / OFC tier-2 leagues) to prove the pluggability — rows stay T3 (admin-only) until business signs off.
- [ ] Catalog round-trip test (load → serialize → diff = empty) passes.

---

## 💰 Phase 20 — Monetization (built-but-dormant)

**Goal:** Per user directives #4 + #5 — ship a **tier-based commercial layer** (Free / Pro / Premium / Admin) with **edge-only enforcement** at the Go API. The system shipped to production with `MONETIZATION_ENABLED=false` (allow-all); it flips on the day the business is ready to charge — **single config change, no migration, no schema work**.

**Anchor doc:** [`design/MONETIZATION.md`](../design/MONETIZATION.md).

**Depends on:** Phase 9 (auth/identity), Phase 13a (so T1 leagues exist for the Free tier to be functional).

### 20.1 Entitlement engine + policy file

- [ ] `MONETIZATION_ENABLED` env var registered in both `ai/common/config.py` and `server/internal/config`; default `false`.
- [ ] `xops/monetization/entitlements.yaml` committed with `league_tier_access`, `market_family_access`, `competition_overrides`, `quotas` (MONETIZATION.md §3.2).
- [ ] `server/internal/auth/entitlements/engine.go` returns `EntitlementDecision`; allow-all when flag is false; lookup-only otherwise (MONETIZATION.md §3.1, §3.3).
- [ ] Coverage test: every public handler either calls `entitlements.Decide()` or is on the discovery allowlist.

### 20.2 Quotas + rate limiting per token

- [ ] Redis sliding-window counter per `(token_id, window_id)` (MONETIZATION.md §5).
- [ ] Counter increments even when flag is false (so capacity-planning data exists before flipping).
- [ ] Burst allowance = `0.5 × calls_per_minute` per tier.
- [ ] Daily quota report `xops/monetization/quota_report.py` shows what *would* have been denied.

### 20.3 Market families

- [ ] `ai/common/betting_markets.json` v2 schema: every market has a `family` field.
- [ ] Test: every family in `betting_markets.json` has a row in `market_family_access`.
- [ ] Test: every `(subscriber_tier, league_tier, market_family)` triple has an explicit decision (MONETIZATION.md §7 exhaustiveness).

### 20.4 Discovery vs. paywall split

- [ ] `server/internal/auth/entitlements/discovery_allowlist.go` — every endpoint that returns publicly-available facts is on it; every endpoint that returns predictions is off it (MONETIZATION.md §9).

### 20.5 Billing-readiness hooks (no payment processor in v1)

- [ ] Token claims carry `Tier`, `SubscriptionID`, `CustomerID`, `ExpiresAt`, `BillingState`.
- [ ] `BillingState=past_due` triggers soft-downgrade to Free (MONETIZATION.md §10).
- [ ] No Stripe/Iyzico/Paddle integration in this phase — that is a Phase 20.x add-on.

### 20.6 Audit + observability

- [ ] `entitlement_decisions_total` Prometheus counter labelled by tier × league_tier × market_family × decision × reason.
- [ ] Sampled audit log at `cfg.entitlement_audit_sample_rate` (default 0.01).
- [ ] Monetization dashboard panel hidden until flag flips on.

### 20.7 End-to-end smoke

- [ ] Staging: flip `MONETIZATION_ENABLED=true`, confirm the deny matrix matches MONETIZATION.md §7 for sample tokens of every tier, flip back to `false`, confirm allow-all behavior restored.

### 20.8 Definition of Done

- [ ] All §11 tests in MONETIZATION.md green.
- [ ] Production runs with `MONETIZATION_ENABLED=false`; Free tier is functional discovery surface.
- [ ] Day-1 readiness: flipping the flag in production is a `kill -HUP` away.

---

## 📡 Phase 21 — Enrichment Data Planes

**Goal:** Per user directive #3 — add the off-pitch signals that materially improve prediction quality but don't fit the original five planes: **transfers, injuries/availability, referees, weather/pitch**, plus four derived views (market-movement, fixture-congestion, card-context, narrative-pressure).

**Anchor doc:** [`design/ENRICHMENT_DATA.md`](../design/ENRICHMENT_DATA.md).

**Depends on:** Phase 4 (storage agent), Phase 6 (proofreader to widen CIs on enrichment-uncertainty), Phase 13a (so the planes have leagues to enrich).

### 21.1 Plane 6 — Roster-state (transfers, contracts, suspensions)

- [ ] Records: `transfer`, `contract`, `suspension` (ENRICHMENT_DATA.md §2.1).
- [ ] Daily refresh during transfer windows; weekly outside.
- [ ] Squad-strength delta + cohesion-penalty curve + departure-shock features.
- [ ] `confidence` field gates whether record mutates roster-state vs only sentiment.

### 21.2 Plane 7 — Health (injuries, availability)

- [ ] Records: `injury`, `availability` (ENRICHMENT_DATA.md §3.1).
- [ ] Spike-aware capture 24-48h pre-KO.
- [ ] Per-fixture squad availability vector → reduces `team_strength` by sum of unavailable players' ratings × starter-likelihood.
- [ ] Availability uncertainty widens proofreader CI bounds.
- [ ] Post-match retroactive `fit` correction (lineup truth-from-history).

### 21.3 Plane 8 — Officials (referees)

- [ ] Records: `referee_assignment`, `referee_profile` (ENRICHMENT_DATA.md §4.1).
- [ ] Reactor recomputes referee rolling stats on every officiated-fixture event.
- [ ] Cards-market + penalty-market features.
- [ ] Home-bias correction clamped at `cfg.referee_home_bias_clamp`.
- [ ] `last_minute_change=true` invalidates per-fixture cards/penalty derived features.

### 21.4 Plane 9 — Environment (weather, pitch)

- [ ] Records: `weather_forecast`, `weather_actual`, `pitch_condition` (ENRICHMENT_DATA.md §5.1).
- [ ] Hourly forecast → actual at KO ±15 min.
- [ ] Wind/rain/frozen impact on goals + cards markets.
- [ ] Style-mismatch feature (passing team on worn pitch).

### 21.5 Derived views

- [ ] Market-movement (drift from opening to closing odds → `high_drift_flag`).
- [ ] Fixture-congestion (days-since-last, matches-in-last-N, travel km).
- [ ] Card-context overlay (referee × team rolling cards/match).
- [ ] Public-narrative pressure (article volume × sentiment polarity 72h pre-KO).

### 21.6 Storage + migrations

- [ ] `migrations/004_enrichment_planes.sql` lands all nine new tables (ENRICHMENT_DATA.md §8).
- [ ] Storage-agent writers + unique-key collision tests.

### 21.7 Feature-flag gating

- [ ] Per-plane `cfg.enrichment_<plane>_enabled` flags.
- [ ] Disabling a plane → predictor falls back to last-known features + emits `predictor.warning` event.

### 21.8 Tier alignment (cross-cutting with Phase 20)

- [ ] Cards / corners / fouls markets gated to **Pro+** (require Officials + congestion).
- [ ] Player-prop markets gated to **Premium** (require Roster + Health).
- [ ] Weather-special markets gated to **Premium** (require Environment).

### 21.9 NLP impact (cross-cutting with Phase 10)

- [ ] Intents added: `transfer_lookup`, `injury_lookup`, `availability_lookup`, `referee_lookup`, `weather_lookup`, `suspension_lookup`. **All template-driven; no LLM.**
- [ ] TR sample queries in `ai/tests/fixtures/turkish_queries.yaml`.

### 21.10 Definition of Done

- [ ] All four planes have extractor + differ + storage + ≥ 5 unit tests.
- [ ] At least one freshness rule per plane in `CONTENT_FRESHNESS.md` §7.
- [ ] Calibration impact measured: predictor log-loss improves by ≥ `cfg.enrichment_promotion_logloss_delta` (default ≥ 0.5%) on the held-out window before any enrichment plane is declared production.
- [ ] Component bumps: `enrichment_roster`, `enrichment_health`, `enrichment_officials`, `enrichment_environment` chart keys.

---

## �🏗️ Phase R — Restructure Track (Production Pivot v3)

**Goal:** Move the code without breaking anything.

> **Sequencing — stop-the-world (2026-04-20).** Earlier drafts of this
> roadmap suggested R1–R5 could "run in parallel with Phases 3–8". That
> turns out to be unrealistic: every Phase 3+ feature ships into one of
> the four target components (`server/`, `datasource/`, `swarm/`,
> `common/`) and would have to be rewritten mid-flight if the layout
> shifts under it. **R1–R6 must run as a single stop-the-world sprint
> (no concurrent feature work) inserted between Phase 2 and Phase 3, or
> — if explicitly deferred — between Phase 5 and Phase 6.** Estimated
> 1–2 weeks of focused work. Each sub-phase is individually reversible
> within the sprint.
**Anchor doc:** [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) §§3, 7.

### R1 — Rename + path aliases

- [ ] New chart keys added to `xops/versioning/chart.json`: `datasource_scraper`, `datasource_watcher`, `datasource_refresher`, `datasource_patcher`, `datasource_gitops`, `datasource_emitter`, `swarm`, `common`.
- [ ] `version.py rename` subcommand lands; used to rename `source_watcher → datasource_watcher` in a single changelog row.
- [ ] No files move yet; chart is the only change.

### R2 — Scraper + watcher move

- [ ] `ai/scraper/` → `datasource/scraper/`.
- [ ] `ai/swarm/source_watcher/` → `datasource/watcher/`.
- [ ] `ai/pipeline/`, `ai/qid/`, `ai/proofreader/` (scrape-time) → `datasource/pipeline/`, `datasource/qid/`, `datasource/proofreader/`.
- [ ] Shim packages (`ai/scraper/__init__.py`, `ai/swarm/source_watcher/__init__.py`) re-export the new paths; a `DeprecationWarning` fires on import. CI records the warning count per build.
- [ ] Proof test: `test_shim_import_works.py`, `test_warning_count_non_increasing.py`.

### R3 — New components scaffold

- [ ] `datasource/refresher/`, `datasource/patcher/`, `datasource/gitops/`, `datasource/emitter/` all land as skeletons with their contract tests in place (phases 16 and 17 fill in the logic).
- [ ] `server/cmd/mock/` (renamed from `mocksrv`) lands; `mocksrv` alias retained for one release.
- [ ] `common/` tree created: `common/config/`, `common/schemas/`, `common/feeds/`, `common/bus/`.

### R4 — Shim deletion + tree removal

- [ ] Zero shim warnings in CI for two consecutive weeks → delete shims.
- [ ] `ai/` tree removed.
- [ ] Isolation tests turned on (§18.1).

### R5 — Mock absorption

- [ ] `docker-compose.mock.yml` removed; `mock` becomes a profile of the base compose.
- [ ] `server` binary gains `MODE=mock`; `mocksrv` dropped entirely.
- [ ] `make up PROFILES=core,mock` brings up only the mock stack; scraper validation works identically to today.

### R6 — Config single-source consolidation

**Goal:** end the three-way hand-sync between `defaults.yaml`, `.env.example`,
and `Config`. Make `defaults.yaml` the single hand-edited source for default
*values*; promote `Config` (Python) and `server/internal/config` (Go) to the
single source for *schema*; reduce `.env.example` and `CONFIGURATION.md` to
generated artifacts.

Motivation: today the triangle test catches drift but does not prevent it —
contributors must remember to touch all three files. After R6 the triangle
becomes a build step.

- [ ] `defaults.yaml` becomes the single hand-edited home for default values
      (today it is partly redundant with `.env.example`).
- [ ] `make config.export-env` generates `xops/env/.env.example` from
      `defaults.yaml` + `Config` field metadata (descriptions, types,
      `# shared` markers). Header line warns the file is generated.
- [ ] `make config.export-doc` generates the registry section of
      `docs/design/CONFIGURATION.md` between `<!-- BEGIN GENERATED -->` /
      `<!-- END GENERATED -->` fences. Narrative prose stays hand-edited
      above/below the fence.
- [ ] CI runs both generators and `git diff --exit-code` on the outputs.
      Drift = red build, not a runtime bug.
- [ ] The existing triangle tests in `ai/tests/test_config_sync.py` stay
      green during the transition; they are deleted only after one full
      release cycle of green generator-diff CI.
- [ ] Go reads the same `defaults.yaml` (or a generated `.env.defaults`
      shim that Compose `env_file:`-loads) so server and Python share one
      source of truth.

**Out of scope for R6:** switching to a different config library
(Pydantic / viper). The dataclass + struct-tag shape stays.

### R — Definition of Done

- [ ] All six sub-phases green.
- [ ] `ai/` path does not exist; `test_ai_tree_gone.py` green.
- [ ] Every component listed in COMPONENT_LAYOUT §5 has an entry in the chart and a non-empty directory.
- [ ] `make up PROFILES=all` brings every service up and the smoke test passes end-to-end.

---

## 📒 Appendix A — Decision Log

| # | Decision | Rationale |
|---|---|---|
| **A1** | **Drop P2P** | Operational cost ≫ benefit; consensus is better solved as agent voting on one host (or many) than as a network protocol. |
| **A2** | **Stay on Python for ML, Go for the API surface, optional Rust for hot paths** | Python's ML ecosystem (PyTorch, XGBoost, LightGBM, scikit-learn, transformers, OpenVINO bindings) is unmatched. Go gives a fast, statically-typed REST + bus client. **Switching the ML stack would lose more in maintenance and library access than it gains in raw speed.** Hot-path agents (e.g. `sec.input.v1` regex pre-filter, `processor.*`) **may** be rewritten in Rust later — exposed via `pyo3` or as standalone agents on the bus. See [`design/LANGUAGE_CHOICES.md`](../design/LANGUAGE_CHOICES.md). |
| **A3** | **Redis Streams now, NATS-ready later** | Already in stack; durable; consumer groups solve at-least-once. NATS JetStream wins at very high scale and is a clean swap behind the SDK interface. |
| **A4** | **Self-signed CA inside containers** | Per project doctrine, no host-side cert install. The CA is a dev/test artifact only. |
| **A5** | **No external secret manager** | Local-experimental scope; per-cloud Secret stores can plug in later via the existing `Config` layer. |
| **A6** | **GPU-first, NPU-aware, CPU-always-works** | The 4080m is the dev rig; CPU is the cloud floor; NPU is a free win when present. |
| **A7** | **Turkish UX, English infra** | Audience is Turkey; engineers and tools speak English. Mixed logs are an operational tax we won't pay. |
| **A8** | **No fabricated data outside `tests/`** | A model trained on fake data is worse than no model — it lies confidently. |
| **A9** | *(Pivot v3)* **Four-component layout: `server` / `datasource` / `swarm` / `common`** | Ends concern mixing between scrapers and predictors; gives us clean isolation tests; lets the patcher live in one place without polluting `ai/`. See [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md). |
| **A10** | *(Pivot v3)* **Swarm consumes feeds, not Postgres** | Forces the data contract to be explicit (JSONSchema), makes the swarm portable across environments, and makes training reproducibility trivial (Parquet snapshots are immutable). See [`design/EMITTER.md`](../design/EMITTER.md). |
| **A11** | *(Pivot v3)* **NDJSON live + Parquet snapshots, not YAML** | YAML is slow to parse, verbose on the wire, and offers nothing for ML pipelines. NDJSON streams cleanly per-record; Parquet is the universal ML columnar format. |
| **A12** | *(Pivot v3)* **`gitops` is the only component with a GitHub token** | One blast radius, one audit log, one kill switch. Granted via a dedicated GitHub App with repo-scoped permissions and 60-minute tokens. |
| **A13** | *(Pivot v3)* **5-gate + 7-day auto-merge** | The patcher produces a lot of PRs; blocking every one on a human bottlenecks the fix loop without adding safety. The 5-gate policy plus a calendar-visible cool-down is safer than best-effort reviews on a deluge. See [`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md). |
| **A14** | *(Pivot v3)* **Mock server absorbed into `server` binary** | Same build, same config layer, same deployment story; mock becomes a first-class production capability (for scraper validation in prod-like envs) rather than "dev scaffolding." |
| **A15** | *(Pivot v3)* **Anthropic Agent SDK (Haiku → Sonnet → Opus, harness-routed) for the patcher** | Frontier coder quality matters most for the diffs the patcher produces; the Agent SDK provides Copilot-grade harness without us re-implementing it; tiered routing keeps cost manageable; budget caps + diagnostic bundle + prompt caching prevent runaway spend; CLAUDE.md plus per-scope context files give the model what it needs without per-call discovery. The five gates do not change — the API model is the *author* of diffs, the gates are the *reviewers*. **AGENTS.md §2 rule 4 ("smallest model that works") gets a narrow carve-out:** components operating inside the patcher's safety perimeter (scope-bounded, gated, sandboxed, budgeted) may use frontier API models. The carve-out is bounded and reversible by a single env var (`NEGELIR_PATCHER=0`). See [`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md) §12 and [`CLAUDE.md`](../../CLAUDE.md). |

---

## 📒 Appendix B — Definition of Done (Per Phase)

Every phase ships only when **all** of the following are true:

1. ✅ All checkbox items in the phase are checked.
2. ✅ A new section in `docs/design/` (or update of one) exists for any architectural choice.
3. ✅ `make test` is green on a fresh clone, including any new adversarial / chaos tests.
4. ✅ `make lint` is green (`no_magic.py`, `ruff`, `mypy --strict` for new modules, `golangci-lint`).
5. ✅ `make up` brings the system up and a smoke script (`make smoke`, lands with the Go API in Phase 9; until then the canonical green-bar is `make test`) passes.
6. ✅ The phase has a one-paragraph entry added to `CHANGELOG.md` (under "Unreleased") describing the user-visible delta.
7. ✅ No new env var exists that is undocumented in `.env.example`.
8. ✅ No new agent exists without a `README.md` describing topics, schema, model size, device requirements.

> 🎯 **Mantra:** *Small agents. Real data. Centralized config. Containerized always. Turkish out, English in.*
