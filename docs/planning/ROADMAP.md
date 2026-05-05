# 🗺️ Negelir — Master Roadmap (Production Pivot v3)

> **Version:** 3.0.0 — *Production Pivot*
> **Date:** 2026-04-20
> **Status:** Active. Single source of truth.
> **Supersedes:** v2.0.0 Swarm Pivot (all prior prior roadmaps already superseded by v2).
> The **phase numbering from v2.0.0 is preserved intact** — Phases 0–15 still carry the same meaning and the same completion status. v3 **adds** a cross-cutting restructuring track (Phases **R1–R6**) and three new feature phases (**16 Emitter**, **17 Patcher + GitOps**, **18 Datasource Cohesion**) that re-shape ownership boundaries for everything from Phase 3 onward.

---

## 🧭 Implementation Alignment Snapshot (2026-04-28)

> Living header — refreshed whenever a phase ships. Authoritative state
> always lives in the per-phase checkboxes below; this is a quick map
> for new readers.

| Phase | Status | Notes |
|---|---|---|
| 0 — Repo reset | ✅ done | P2P fully removed; `test_p2p_module_removed` guards regression. |
| 1 — Centralized config | ✅ done | Triangle test green; numeric/float-threshold AST scanner still on backlog (§1.4). |
| 2 — Mock dev stack | ✅ done | All four vhosts live via `nginx-mock` → `mocksrv` (manifest-keyed seeds, **no postgres**). |
| 2.8 — Source-watcher | ✅ done | Cron-driven; LLM summarizer stubbed behind `enabled=False` until Phase 8. |
| 3 — Swarm foundation | ✅ done | SDK at `ai/swarm/sdk/`; all 7 §3.7 DoD tests green; NATS + bus auth deferred. |
| 4 — Worker agents | ✅ done | All 6 Phase 4 topics flow end-to-end via `make swarm.demo`; Postgres-backed gates deferred to Phase 9. |
| 5 — Predictor swarm | 🛠 design only | §5.1–§5.5 scoped + cross-phase contracts wired; no code yet. |
| 6+ | ⏳ not started | Ordered per dependency graph. |
| 13a Süper Lig seed | ✅ done | Other T1 leagues land with the 13a sprint. |
| R1 — chart rename | 🟡 partial | All new chart keys seeded; `version.py rename` + the `source_watcher → datasource_watcher` collapse stay open. |
| R2–R6 | ⏳ not started | Deferred-path window: lands between Phase 5 design and Phase 6 kickoff (see §Phase R sequencing note). |
| 16/17/18 | ⏳ design only | Anchor docs (EMITTER, SCRAPER_PATCHER, COMPONENT_LAYOUT) are binding; no code yet. |

**Doctrine reminder:** every checkbox flip ships in the same commit as
the implementing code, the matching tracker row, and the
`make version.bump` for the affected component (per AGENTS.md §3.4 +
§6.1). Stale checkboxes mislead the next agent and waste budget.

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
- [Phase 8 — Self-Maintenance Agents (Ops Console, Auto-Scaler, Backup, DLQ Supervisor, Watcher Graduation)](#-phase-8--self-maintenance-agents-ops-console-auto-scaler-backup-dlq-supervisor-watcher-graduation)
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
                │  nginx-mock (self-signed CA + per- │
                │  vhost certs) → Go mocksrv ──┐     │
                │  fake mackolik / nesine /    │     │
                │  tff / openfootball          ▼     │
                │              infra/mock/seeds/     │
                │              (manifest.json +      │
                │               frozen captures)     │
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
   ┌───────────────────────┐        ┌───────────────────────────┐
   │  nginx-mock           │ ──────▶│  Go mocksrv (server bin   │
   │  (TLS, self-signed CA)│        │   MODE=mocksrv) — reads   │
   │  vhosts:              │        │   infra/mock/seeds/       │
   │   • mackolik.local    │        │   manifest.json and       │
   │   • nesine.local      │        │   serves frozen captures  │
   │   • tff.local         │        │   keyed by (host, path)   │
   │   • openfootball.local│        └───────────────────────────┘
   └───────────────────────┘
```

> ℹ️ **No postgres in the mock path.** Earlier drafts of this roadmap
> sketched a postgres-backed seed table; the actual implementation in §2.7
> is file-system + manifest based (simpler, faster, exactly mirrors the
> on-disk seed corpus). Postgres only appears later, behind the Phase 4
> storage agent and the Phase 9 API surface.

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

> **Boundary clarification (Pivot v3).** This catalog covers **bus** topics (control + low-volume coordination). Per [`design/EMITTER.md`](../design/EMITTER.md), high-volume data records (per-Record schedules, fixtures, results) move via **NDJSON/Parquet feeds**, not the bus, starting Phase 16. Until then (Phase 4–15) the `scrape.raw` / `match.normalized` topics carry pipeline artifacts on the bus; Phase 16 swaps them for feed-pointer envelopes without renaming the topics. The full record diff for a stored row is **not** carried on `match.stored` — it ships on `freshness.events.v1` (see [`design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md) §15.1).

> **Wire authority.** The dataclasses in `ai/swarm/agents/payloads.py` plus the matching JSON Schemas in `ai/swarm/sdk/schemas/<topic>.json` are the **binding** wire contract; the table below is a human-readable summary that may abbreviate optional fields. Any disagreement between the two is a bug — `ai/swarm/agents/tests/test_schemas_match_payloads.py` keeps them honest.

| Topic | Producer | Consumer(s) | Payload (required + key optional) |
|---|---|---|---|
| `scrape.request` | API gateway, scheduler | scrapers | `{source, target}` + opt `{league_id, competition_id, requested_at, metadata}` |
| `scrape.raw` | scraper agents | categorizer | `{source, target, bytes_sha256, http_status, content_type}` + opt `{bytes_b64, bytes_ref, league_id, competition_id, fetched_at}` |
| `scrape.classified` | categorizer | processors | `{raw, label, confidence, classifier_id}` |
| `match.normalized` | processors | storage | `NormalizedRecord` — `{record_type, plane, source, source_match_id, stable_id, extractor_version, payload}` + opt `{captured_at}` |
| `match.stored` | storage | cache, reactors | `{record_id, record_type, plane, source, stable_id, change_kind}` + opt `{stored_at}` (diff lives on `freshness.events.v1`) |
| `freshness.events.v1` | storage | reactors (consume only) | per `design/CONTENT_FRESHNESS.md` §15.1 |
| `predict.request` | API gateway | predictor swarm | `{request_id, match_id, market}` + opt `{league_id, profile_id, requested_at, features, metadata}` |
| `predict.vote` | individual predictors | consensus agent | `{request_id, match_id, market, predictor_id, distribution, confidence}` + opt `{produced_at, features_version, league_id, profile_id, metadata}` |
| `predict.final` | consensus | proofreader replicas + aggregator (CANDIDATE; never user-visible) | calibrated `Prediction` (typed `distribution` `{market_outcomes, score_grid?}`, `degraded`/`degraded_reason`, `prediction_id`, `produced_at`, `weights`, `contributing_models`, `calibration_version`, `swarm_confidence`) |
| `predict.proofreader_verdict.v1` | each proofreader replica (sanity / plausibility / consistency / future cross-source / historical) | `proofreader_aggregator.v1` (SOLE consumer) | `{request_id, prediction_id, match_id, market, proofreader_id, verdict ∈ {accept,warn,reject}, score, checks_run, flags, rationale}` + opt `{calibration_version, checked_at}` |
| `predict.approved.v1` | `proofreader_aggregator.v1` (SOLE producer) | `cache.v1`, API gateway (Phase 9), `drift.v1` | `{request_id, prediction_id, match_id, market, approved_at, approved_by, verdict_count, quorum, final, calibration_version}` |
| `match.outcome.v1` | `storage.v1` (SOLE producer) | `drift.v1`, future scoring agents | `{match_id, stable_id, source, final_home, final_away, outcome_1x2 ∈ {H,D,A}, settled_at}` + opt `{league_id, competition_id, metadata}` |
| `models.events.v1` | `TrainerReactor` (SOLE producer) | ops dashboards, model registry | `{kind=model_trained, predictor_id, model_version, trained_at}` + opt `{league_id, profile_id, metric, metric_value, sample_size}` |
| `maint.event.v1` | `drift.v1` (v1 SOLE producer; future maint agents reuse with new `kind`) | trainer, supervisor, ops | `{kind ∈ {retrain_request,…}, target, reason, produced_at}` + opt `{league_id, market, metric, metric_value, threshold, sample_size, action}` |
| `proof.flag` | scrapers, categorizer, processors, consensus, `proofreader_aggregator.v1`, individual proofreader replicas | drift, security, ops dashboards | `{kind ∈ ProofFlagKind, agent, source?, reason?, …}` (kind-specific extras documented per `ProofFlagKind`) |
| `telemetry` | (reserved — Phase 5+ producers; nothing emits today) | telemetry agent | `{kind, emitted_at}` + opt `{agent, topic, value, labels}` — sparse, hand-emitted events (deploys, manual replays); not the bulk metrics path |
| `sec.alert` | security agents (Phase 7) | supervisor, telemetry | `{kind, source, severity}` |

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

**Goal:** A clean linear pipeline of small, replaceable agents that turn a scrape request into a unified `NormalizedRecord` row keyed on `(source, source_match_id, record_type)`.
**Depends on:** Phase 2, Phase 3
**Data scope reference:** [`design/DATA_PIPELINE.md`](../design/DATA_PIPELINE.md) is the contract this phase implements end-to-end. Records produced here become the input to Phase 5 predictors and Phase 10 NLP. The per-record change-detection rules that gate trainer reactors live in [`design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md).

**Cross-phase alignment (binding):**

- **Phase 2 mock stack.** All four sources resolve to mock vhosts when `NEGELIR_SCRAPE_PROFILE=mock` — never real upstreams in dev/CI.
- **Phase 2.8 source-watcher.** Stays standalone (cron-driven). Phase 4 scrapers do **not** consume the watcher's drift events — they migrate to the SDK in Phase 8 alongside the LLM-summarizer graduation. Phase 4 only adds *new* SDK-based agents.
- **Phase 3 §3.5 topic catalog.** The wire authority for every Phase 4 topic. Payload changes go through `ai/swarm/agents/payloads.py` + `ai/swarm/sdk/schemas/<topic>.json`; the §3.5 table is a human summary that must be updated in lock-step.
- **Phase 3 §3.3 bus semantics.** Every Phase 4 handler must be **idempotent** (at-least-once redelivery), publish at most `swarm_max_in_flight` in-flight, and respect the retry/DLQ contract.
- **Phase 3 §3.4 swarmctl visibility.** Every Phase 4 agent must show up in `swarmctl ps` (registered, heartbeating) and every new topic must show up in `swarmctl topics`. The supervisor stays read-only — Phase 4 adds no mutating commands.

### 4.1 Scraper agents

One agent **per source**, mirroring the four mock vhosts shipped in Phase 2.4:
`scraper.mackolik.v1`, `scraper.nesine.v1`, `scraper.tff.v1`, `scraper.openfootball.v1`.

- [x] Pulls `scrape.request`, hits the source (mock or real per `NEGELIR_SCRAPE_PROFILE`); ignores requests whose `source` field does not match its `source_key`.
- [~] Respects per-source rate limit from config via in-process token bucket. *(Redis-backed bucket for cross-replica coordination is owned by `maint.scaler.v1` in Phase 8 — single replica only today.)*
- [x] Emits `scrape.raw` carrying the raw bytes + content sha256 + status + content-type.
- [x] No parsing here — *raw bytes only*. (Robust to upstream DOM changes.)
- [~] Failure modes: `404` → `proof.flag` (data missing upstream); `5xx` → SDK retry budget → DLQ. *(`sec.alert` escalation deferred to Phase 7 `sec.scrape.v1`; the DLQ row is the bridge.)*

> 💡 **Why split scrape from parse?** When mackolik changes its DOM, only the categorizer/processor needs updating. Raw captures stay valid for replay and for the Phase 17 patcher's diagnostic bundle.

### 4.2 Categorizer agent (`categorizer.v1`)

- [x] Consumes `scrape.raw`, classifies *what* it is (fixture list, match detail, lineup, odds page, irrelevant) and emits `scrape.classified`.
- [~] **No LLM.** Default is a deterministic rule-based classifier with a `set_model()` hot-swap hook for a future scikit-learn `LinearSVC` over TF-IDF features (≤ 5 MB on disk), trained from the labelled seed corpus (Phase 2). *(Doctrine respected — Guiding Principle #4. The trained artifact lands when the labelled corpus exists.)*
- [x] Confidence threshold from config (`NEGELIR_CATEGORIZER_MIN_CONF`). Below threshold → routes to `proof.flag` for review (no silent fallthrough).

### 4.3 Processor agents (`processor.<kind>.v1`)

One per content kind (fixture, match-detail, lineup, odds).

- [x] Stateless parsers; each takes `scrape.classified` and emits `match.normalized` carrying a `NormalizedRecord` (plane + record_type per [`design/DATA_PIPELINE.md`](../design/DATA_PIPELINE.md)).
- [~] HTML path uses a JSON walker + regex fallback today; `selectolax` swap (10× faster than BeautifulSoup, no JS engine) lands when real HTML fixtures come online. JSON sources (openfootball, tff feeds) already use the JSON walker.
- [x] **Schema-first:** output is validated against the frozen `NormalizedRecord` dataclass + the JSON schema at `ai/swarm/sdk/schemas/match.normalized.json` before publishing. Violations route to `proof.flag` with the violation list. *(Pydantic v2 upgrade is non-binding — same contract; deferred to Phase 9 when the API surface lands.)*

### 4.4 Storage agent (`storage.v1`)

Pivot v3 collapses the legacy `matches` / `lineups` / `odds` / `outcomes` tables into a **single unified `match_normalized` table** keyed on `(source, source_match_id, record_type)`. Per-plane materialized views ship with Phase 16 emitter, not here.

- [~] Single writer for `match_normalized`. *(In-memory `RecordStore` Protocol + the `match_normalized` table in `migrations/004_pipeline.sql`; Postgres-backed implementation pending Phase 9 DB wiring.)*
- [x] Idempotent upserts keyed by `(source, source_match_id, record_type)`.
- [x] Emits `match.stored` so caches/predictors can warm; emits `freshness.events.v1` with the plane-scoped diff for reactors (§4.7) — never carries the diff on `match.stored` (per [`design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md) §15.1).

### 4.5 Cache agent (`cache.v1`)

Cache concerns split cleanly between two agents to keep blast radius small:

- **`cache.v1` (this section)** — *warms* the cache from `match.stored`.
- **`reactor.cache-invalidation.v1` (§4.7)** — *invalidates* keys when freshness events fire.

- [x] Watches `match.stored`; populates the cache with TTL from `cfg.cache_record_ttl_sec`. In-memory backend behind `CacheBackend` Protocol; Redis backend lands with the Phase 9 API surface that consumes it.
- [x] Subscribes to **`predict.approved.v1`** (NOT `predict.final` — Phase 6 contract: only post-quorum predictions reach the cache) and warms with `cfg.cache_prediction_ttl_sec`. *(Wired in Phase 6; boundary test in `test_boundary_discipline.py` enforces `cache.v1.subscribes` excludes `predict.final`. Box flipped per [`reports/phase6-second-pass.md`](../reports/phase6-second-pass.md) F2-3 — the implementation shipped, the box was simply stale.)*
- [ ] Exposes a tiny gRPC contract to the API gateway for explicit invalidation. *(Deferred to Phase 9 — no consumer exists yet.)*

### 4.6 Telemetry agent (`telemetry.v1`)

- [x] Subscribes to the **explicit topic set** (Phase 4 + Phase 5 predictor topics — the bus has no wildcard primitive; the subscription list updates in lock-step with §3.5).
- [x] Aggregates per-topic counters, error rates, latency averages.
- [~] Pushes to Prometheus (pull) and to a `telemetry_events` Postgres table for forensic queries. *(Prometheus text endpoint via stdlib `http.server` ready; `telemetry_events` table created in `004_pipeline.sql`; insert wiring lands when the Postgres backend ships.)*

### 4.7 Freshness-event reactors (`reactor.<name>.v1`)

**Why a dedicated sub-phase.** Phase 4 produces `Record`s and emits
the `freshness.events.v1` stream defined by
[`design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md). The
*reactions* — re-running the live predictor on a score change,
re-computing lineup features when an XI moves, debouncing retrains,
flagging value odds — are owned by **named reactors**, not by the
freshness module itself. CONTENT_FRESHNESS §15 is the spec; this
sub-phase is the implementation hook in the roadmap.

- [x] `ReactorBase` at `ai/swarm/agents/reactor.py` enforces
      CONTENT_FRESHNESS §15.2 invariants: idempotent on `event_id`
      (per-reactor `reactor_processed_events` ledger), plane-bounded
      blast radius (`allowed_planes`), no back-emission to
      `freshness.events.v1` (asserted at construction), bounded
      replay window (`max_age_sec`). *(Final Pivot v3 home is
      `swarm/reactors/_base.py` after Phase R2 — directory move,
      not a rewrite.)*
- [x] First-cut reactors: `FeatureStoreReactor` and `CacheInvalidationReactor`
      (smallest blast radius, exercise the SDK end-to-end).
- [x] Trainer reactor with debounce window, qualifying-event filter,
      accuracy-floor check, and cooldown (CONTENT_FRESHNESS §15.3).
      Publishes `model.trained` on `models.events.v1`. *(Shipped in Phase 5.5; see `ai/swarm/agents/reactor.py::TrainerReactor`. Box flipped per [`reports/phase6-second-pass.md`](../reports/phase6-second-pass.md) F2-4 — duplicate of §5.5 entry.)*
- [x] Live-predictor / NLP / market reactors per §15.1. *(Shipped in Phase 5.5; see `LivePredictorReactor` and friends in `reactor.py`. Box flipped per `phase6-second-pass.md` F2-4.)*
- [~] Reactor failure isolation: each runs in its own consumer group
      with the SDK retry budget → DLQ. *(Explicit `reactor.degraded`
      topic — emitted after N consecutive failures — deferred to
      Phase 8 supervisor work.)*
- [x] Replay command: `make reactor.replay REACTOR=<name> SINCE=<ts>`
      for operator-driven recovery (no automatic replay on restart).
- [x] Tests: per-reactor idempotency probe (replay same event twice
      → one side-effect) green in `test_cache_telemetry_reactor.py`.
      *(Kill -9 mid-side-effect chaos test deferred until the
      Postgres-backed ledger lands — the in-memory ledger cannot
      simulate a half-committed transaction.)*

### 4.8 Definition of Done

- [x] `make swarm.demo LEAGUE=<id>` runs end-to-end through `InMemoryBus`
      producing ≥ 1 `NormalizedRecord` per processor in < 1 s. *(Verified
      2026-04-28: 3 records, cache populated, FeatureStoreReactor flagged
      3 dirty IDs, telemetry counters present for all 6 Phase 4 topics.)*
- [x] Every Phase 4 message validates against its JSON schema at the
      live emission point (not just hand-crafted fixtures).
      `test_phase4_swarm_demo_end_to_end` enforces this.
- [x] Every Phase 4 agent registers in `agent_registry`, heartbeats per
      `cfg.swarm_heartbeat_sec`, and deregisters on `SIGTERM` (inherits
      from Phase 3 `AgentRunner`; covered by SDK suite).
- [x] Every Phase 4 agent appears in `swarmctl ps` and every Phase 4
      topic appears in `swarmctl topics` (Phase 3.4 visibility contract
      preserved — no mutating commands added).
- [x] Every Phase 4 handler is **idempotent** under at-least-once
      redelivery (storage upserts on `(source, source_match_id,
      record_type)`; reactors short-circuit on the ledger; categorizer
      / processors are pure functions of input).
- [x] Failed handlers exhaust `cfg.swarm_retry_budget` and land in
      `<topic>.dlq` (inherited DLQ contract from §3.3, exercised by the
      scraper 5xx path).
- [x] All Phase 4 config knobs surface in `xops/env/.env.example`,
      `ai/common/defaults.yaml`, and `ai/common/config.py` (triangle
      test green).
- [ ] **Postgres-backed gates (deferred to Phase 9 DB wiring):**
      Postgres `RecordStore` writes one row per scrape; killing any
      single agent for 30 s and restarting it does not lose messages
      (Redis Streams consumer-group durability test against the real
      bus, not `InMemoryBus`).

---

## 🎲 Phase 5 — Predictor Swarm & Consensus

**Goal:** Many small predictors vote on each match × market. A consensus agent fuses votes into a calibrated probability distribution.
**Depends on:** Phase 4
**Pivot v3 placement:** Predictors and consensus live under `swarm/predictors/` per [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md). Until Phase R2 lands the directory move, ship under the transitional path **`ai/swarm/agents/predictors/`** + **`ai/swarm/agents/consensus.py`**, importable as `swarm.agents.*` (matches Phase 4 layout — R2 is a `git mv`, not a rewrite).

**Cross-phase alignment (binding):**

- **Phase 3 §3.2 SDK contract.** Every `pred.*.v1` and `consensus.v1` is an `Agent` (registers in `agent_registry`, heartbeats per `cfg.swarm_heartbeat_sec`, declares `subscribes`/`publishes`, deregisters on `SIGTERM`). Inherits `AgentRunner` retry/DLQ.
- **Phase 3 §3.3 bus semantics.** Predictors are **idempotent** on `(match_id, market, request_id)` — a redelivered `predict.request` produces the same vote. Consensus is idempotent on `(match_id, market, request_id)` — late votes after a `predict.final` has been published are dropped (`proof.flag` with `kind=late_vote_dropped` for observability), never trigger a second emission.
- **Phase 3 §3.5 topic catalog (wire authority).** Phase 5 lands the JSON Schemas for `predict.request`, `predict.vote`, `predict.final` at `ai/swarm/sdk/schemas/<topic>.json`, plus `PREDICT_VOTE` constant in `ai/swarm/agents/topics.py` (today only `PREDICT_REQUEST`/`PREDICT_FINAL` exist). Payload dataclasses live in `ai/swarm/agents/payloads.py` next to the Phase 4 ones; `test_schemas_match_payloads.py` is extended to cover them.
- **Phase 3.4 swarmctl visibility.** Every Phase 5 agent appears in `swarmctl ps`; every new topic appears in `swarmctl topics`. Read-only — Phase 5 adds no mutating commands.
- **Phase 4.7 reactor wiring.** Two trigger paths fan into `predict.request`, both already stubbed by Phase 4:
  - `LivePredictorReactor` (live/market planes) consumes `freshness.events.v1` and emits `predict.request` when an in-flight match's score / lineup / odds change. **Phase 5 implements this stub.**
  - The Phase 9 API gateway emits `predict.request` for explicit user calls. *(Phase 9 dep — surface only.)*
  - `TrainerReactor` (schedule/live planes) consumes outcomes via `freshness.events.v1` and triggers per-predictor retrain (writes to `agent_desired_state` / nightly job — see §5.4). **Phase 5 implements this stub.**
- **Phase 4 storage / records.** Predictors read features by querying the storage agent's `match_normalized` rows for the match's `(stable_id, plane)` set; **never** parse `scrape.raw` directly (scope discipline — predictors live in `swarm/`, not `datasource/`). The Phase 4.7 `FeatureStoreReactor`'s dirty set is the prioritization hint, not the data source.
- **Phase 2 mock stack.** Backtests resolve to mock vhosts via `NEGELIR_SCRAPE_PROFILE=mock`; backtest data is the frozen seed corpus + the `match_normalized` rows it produces. Real upstreams are off-limits per AGENTS.md §5.

**Forward-phase contracts (binding for Phase 5 design):**

- **Phase 6 proofreader is the gate, not Phase 5.** `predict.final` published by Phase 5 is a **candidate** — it is **never** user-visible until the Phase 6 proofreader quorum (⌊N/2⌋+1, simple majority) approves it and the cache reactor (Phase 6 wiring of Phase 4.5) writes it. Phase 5 must therefore *publish freely* (no in-process self-veto) and let Phase 6 do the gating. Phase 5 emits `proof.flag` only for its own internal failures (late vote, no votes), never to second-guess its own consensus.
- **Phase 6.2 consistency check** requires the payload to carry a *score grid* for markets where one exists (Dixon-Coles + the XGBoost pair produce one; Elo does not). `predict.final.distribution` is therefore typed as `{market_outcomes: dict, score_grid?: 2D array}` — not bare floats. Markets without a grid set `score_grid=null`; the proofreader skips the consistency check for those.
- **Phase 9 §9.3 request flow.** The Go API gateway's RPC pattern (publish + wait on `reply_to` topic) requires `request_id` to be **generated by the requester** (API or `LivePredictorReactor`) and **round-tripped unchanged** in `predict.vote` and `predict.final`. Phase 5 owns the propagation; Phase 9 owns the correlation. Constraint: `cfg.api_request_timeout_ms ≥ cfg.consensus_window_ms + cfg.api_consensus_overhead_ms` (Phase 9 enforces; Phase 5 documents the relationship).
- **Phase 10 NLP citation.** `/v1/qa` answers cite predictions by id + timestamp ("3. yarı sonucu, son güncelleme …"). `predict.final` must carry `produced_at` (ISO-8601 UTC) and a stable `prediction_id` (sha256 of `match_id|market|request_id|calibration_version`).
- **Phase 11 compute.** Each predictor bundle fits ≤ `cfg.predictor_max_vram_mb` (default 1024) on GPU, and **must pass a `cpu_only` parity test** asserting identical predictions (within `ε = 1e-6` log-loss) on CPU and on the chosen device. The roster's must-status quartet (Elo / DC / XGB form / XGB xG) is GPU-optional by design; only the deferred TabNet would change that.
- **Phase 12 chaos.** `make chaos-kill-predictor PCT=50` requires consensus to **still publish** `predict.final` with a `degraded: true` flag and `degraded_reason` (e.g. `"only 2/4 predictors voted"`). Phase 5 owns the flag; Phase 12 owns the assertion.
- **Phase 13a CalibrationProfile.** Calibration tables stored by §5.4 are keyed on `(profile_id, market, version)` where `profile_id` resolves via `CompetitionConfig.calibration_profile` per [`design/COMPETITIONS.md`](../design/COMPETITIONS.md) §4.5 (cup vs league vs continental shapes share profiles). Until Phase 13a lands the catalog loader, Phase 5 hard-codes `profile_id = league_id` and the migration carries that as the default value; Phase 13a swaps the resolver, no schema change.
- **Phase 14 K8s.** `consensus.v1` runs at `replicas: 1` (matches [`design/SWARM.md`](../design/SWARM.md) table) — the single-publication guarantee at §5.2 depends on it. Multi-replica consensus would require Postgres-backed leader election, which is **out of scope** for Phase 5 / 14 and explicitly tracked as a Phase 14.x follow-up item if scaling pressure ever justifies it. Predictors scale horizontally; consensus does not.
- **Phase 16 emitter.** Once Phase 16 lands, the `predictor_calibration` table (§5.4) is exported as a feed (`feeds/calibration.v1.parquet`) consumed by `consensus.v1` via `FeedReader` instead of `psycopg`. The Phase 5 storage interface is therefore a **`CalibrationStore` Protocol** (in-memory → Postgres at Phase 9 → Feed at Phase 16) — the consensus code stays unchanged across all three.
- **Phase 17 patcher scope.** Per [`CLAUDE.md`](../../CLAUDE.md), the auto-patcher's allow-list is `extractor` / `schema` / `migration` / `fixture` — it **never** edits `swarm/` (predictors live there post-R2). Failures attributable to a predictor surface as `proof.flag` and route to a human, not the patcher. Phase 5 needs no patcher integration.

### 5.1 Predictor diversity (intentional, not coincidental)

The point of a swarm is to *disagree well*. Initial roster (ordered by build-effort cheap → expensive):

| ID | Backend | Size on disk | Image-cost delta | Status | Speciality |
|---|---|---|---|---|---|
| `pred.elo.v1` | Pure Python | 0 MB | 0 MB | **must** | Baseline Elo + home-advantage |
| `pred.dixon_coles.v1` | NumPy | 0 MB | 0 MB (numpy already pulled) | **must** | Bivariate Poisson, classic |
| `pred.xgb_form.v1` | XGBoost | ~3 MB | ~50 MB | **must** | Recent-form features |
| `pred.xgb_xg.v1` | XGBoost | ~3 MB | shared with form | **must** | xG / shot-quality features |
| `pred.lgbm_market.v1` | LightGBM | ~4 MB | ~30 MB | **opt-in** behind `cfg.predictor_market_features_enabled` (default `false`); requires the odds processor's `match_normalized.record_type='odds'` rows | Odds-derived features |
| `pred.tabnet.v1` | PyTorch CPU/GPU | ~6 MB | ~700 MB | **deferred** to Phase 5.5 — only added if backtest (§5.3) shows a calibrated log-loss win over the XGBoost pair on the last 6 months. Doctrine §4 ("smallest model that works") gates this. | Attention over tabular features |

> ⚠️ **No LLM predictors.** They are slow, overconfident on tabular data, and unjustified for this domain. If we ever add one, it goes here with a documented backtest win against the XGBoost pair (same gate as TabNet).

### 5.2 Consensus agent (`consensus.v1`)

- [x] Collects `predict.vote` for a `(match_id, market, request_id)` until `cfg.consensus_window_ms` elapses **or** every **expected** predictor has voted, whichever fires first. The expected set is **constructor-injected** (static tuple); a runtime `agent_registry`-driven expected set is a Phase 14.x follow-up — today `consensus.v1` runs at `replicas: 1` so an injected list is sufficient and avoids a Redis hit per vote on the hot path.
- [x] **Subscribes to `predict.request` too**, dispatching by topic in `handle()`: a request opens the window via `note_request()` (records the `(match, market, request_id)` + `profile_id` / `league_id`), a vote drives fusion. Without this the §5.2 quorum-empty path was unreachable in production — `note_request` could only ever be called from test code (fixed 2026-04-28).
- [x] **Per-vote confidence floor.** Votes with `confidence < cfg.consensus_min_confidence` are dropped silently (the swarm simply has one fewer voter). Default `0.0` = filter disabled so baseline predictors (Elo emits ~0.32) still contribute; operators raise it once roster confidences are calibrated. Matches `design/SWARM.md` consensus algorithm step 2 — previously documented but unwired (fixed 2026-04-28).
- [ ] Per-predictor weight learned from a rolling Brier-score window (`cfg.consensus_brier_window`); refreshed nightly by the `TrainerReactor` (§5.4) — never inside the hot path.
- [x] Output is **calibrated** with isotonic regression per `(profile_id, market)` where `profile_id` resolves via `CompetitionConfig.calibration_profile` (Phase 13a; default `profile_id = league_id` until then). Calibration tables stored via the `CalibrationStore` Protocol (in-memory → Postgres Phase 9 → Feed Phase 16) and versioned.
      Consensus resolves the profile from the **vote-carried** `profile_id`/`league_id` (round-tripped from the request) — no fragile parsing of `match_id`. **Single calibration-store hit per request:** the `CalibrationTable` itself is cached on the pending key on the first vote and reused by `_finalize` for both calibration application and the late-vote guard. Locked in by `test_calibration_store_is_hit_at_most_once_per_request`.
- [x] Publishes `predict.final` with: `distribution = {market_outcomes, score_grid?}` (score grid only when the predictor produces one; null otherwise), weights used, contributing model IDs, calibration version, swarm-confidence (0–1), `degraded` boolean + `degraded_reason` (true when fewer than `cfg.consensus_min_voters` predictors voted), `request_id`, `prediction_id` (sha256 of `match_id|market|request_id|calibration_version`), `produced_at` (ISO-8601 UTC).
- [x] Single-publication guarantee: a second `predict.final` for the same `(match_id, market, request_id)` is **never** emitted; late votes are logged + dropped (`proof.flag` with `kind=late_vote_dropped`). Idempotency ledger reuses the Phase 4.7 `Ledger` Protocol — in-process for tests, Postgres-backed in prod.
- [x] Quorum-empty fallback: if zero votes arrive within the window (every predictor down or DLQ-ed, or every vote dropped by the confidence filter), emit `proof.flag` with `kind=consensus_no_votes` and **no** `predict.final`. The proofreader (Phase 6) handles user-facing degradation.
- [x] **Bounded pending set.** `_pending` is capped at `cfg.consensus_max_pending` (default 4096) using insertion-order LRU eviction; overflow emits `proof.flag` with `kind=consensus_overflow` carrying the evicted `(match_id, market, request_id)`. Protects against unbounded growth if predictors permanently DLQ or the runner stops calling `flush_expired`.

### 5.3 Backtesting harness

- [x] `make swarm.backtest WEEKS=N` (driver: [`xops/swarm_backtest.py`](../../xops/swarm_backtest.py), dispatched via [`xops/makefile/ai_commands.py`](../../xops/makefile/ai_commands.py)) replays history through the live swarm chain (predictors → `consensus.v1`) against frozen mock seeds. Distinct from the legacy single-model `make backtest` target.
- [x] Reports per-predictor + swarm 1x2 accuracy, log-loss, Brier, ECE (10-bin reliability). Output: a JSON report under `data/backtest/<ts>.json` + a Markdown summary alongside it. ROI under sample bookmaker odds is deferred until Phase 9 wires odds into the predictor feature dict.
- [x] CI gate (configurable, not hardcoded): swarm log-loss ≤ `(1 - cfg.backtest_swarm_floor_pct)` × best-individual-predictor log-loss over the trailing `cfg.backtest_window_weeks`. Default `backtest_swarm_floor_pct = 0.01` (1% improvement). The gate skips automatically when `n_matches < cfg.backtest_min_n` so a sparse seed corpus doesn't flap CI. Per-`(league, market)` slicing lands when Phase 5.4 wires real per-league weights (today every match feeds a single league-agnostic gate).

### 5.4 Migrations + reactor implementations

- [x] **Migration `005_predictor.sql`**: tables `predictor_weights` (per `(predictor_id, profile_id, market, valid_from)`), `predictor_calibration` (per `(profile_id, market, version, valid_from)` storing the isotonic table as JSONB), `predictor_outcomes` (per `(match_id, market, outcome_at)` for backtest replay). `profile_id` is the Phase 13a `CalibrationProfile` id; `005` ships with `profile_id` defaulting to `league_id` so the migration is forward-compatible without waiting on Phase 13a.
- [x] **`CalibrationStore` Protocol** — in-memory backend (tests + CI), Postgres backend stub (Phase 9 wiring), Feed backend stub (Phase 16). Consensus code reads through the Protocol only; the store choice is a constructor injection, never a global.
- [x] Implement `LivePredictorReactor.react()` (replaces the Phase 4.7 `NotImplementedError` stub): emit `predict.request` keyed on the freshness event's `(stable_id, market_set)` derived from the record's plane (live → 1X2 + AH; market → AH/OU recompute).
- [x] Implement `TrainerReactor.react()`: debounce per `(predictor_id, league)` for `cfg.trainer_debounce_sec`, qualifying-event filter (only `change_kind=created|updated` on planes the predictor consumes), accuracy-floor check against `cfg.drift_accuracy_floor` (the Phase 6 `drift.v1` knob — single source). Publishes `model.trained` on a new `models.events.v1` topic with its own JSON Schema + payload dataclass.
- [x] Topic + schema deliverables (per §3.5 wire-authority rule): add `PREDICT_VOTE` and `MODEL_TRAINED` to `topics.py`; add `predict.request.json`, `predict.vote.json`, `predict.final.json`, `models.events.v1.json` schemas; extend `test_schemas_match_payloads.py` and update the §3.5 table row for each.

### 5.5 Definition of Done

- [x] All §5.1 **must**-status predictors (`elo`, `dixon_coles`, `xgb_form`, `xgb_xg`) implemented + voting against `InMemoryBus` through `AgentRunner` in `ai/swarm/agents/tests/test_phase5_swarm_demo.py` (the `make swarm.demo` driver covers Phase 4; Phase 5 is exercised via the same in-process runner stack rather than a separate make target so it runs in CI). `pred.lgbm_market.v1` ships behind a default-off flag; `pred.tabnet.v1` deferred per the §5.1 gate.
- [x] `consensus.v1` produces exactly one `predict.final` per `(match_id, market, request_id)` under at-least-once redelivery (idempotency test in `ai/swarm/agents/tests/test_consensus.py`).
- [x] Quorum-empty path emits `proof.flag` with `kind=consensus_no_votes` and **does not** emit `predict.final` (negative test).
- [x] Every Phase 5 agent registers in `agent_registry`, heartbeats, and shows up in `swarmctl ps`; every Phase 5 topic shows up in `swarmctl topics` (Phase 3.4 contract preserved). Guard: `test_phase5_swarm_visible_in_registry_and_topics` asserts the in-memory equivalents of the Redis surfaces `swarmctl` reads (`AgentRegistry.all_specs()` ↔ `agent_registry` HGETALL; `bus.topics()` ↔ stream-key SCAN).
- [x] All Phase 5 messages validate against their JSON Schema at the live emission point (`test_phase5_swarm_visible_in_registry_and_topics` runs `swarm.sdk.schemas.validate` on every emitted `predict.*` payload, mirroring the Phase 4 demo's pattern instead of duplicating it).
- [x] All Phase 5 config knobs (`consensus_window_ms`, `consensus_min_confidence`, `consensus_min_voters`, `consensus_brier_window`, `consensus_max_pending`, `predictor_market_features_enabled`, `predictor_max_vram_mb`, `trainer_debounce_sec`, `backtest_swarm_floor_pct`, `backtest_window_weeks`, `backtest_min_n`, `api_consensus_overhead_ms`) surface in `xops/env/.env.example`, `ai/common/defaults.yaml`, and `ai/common/config.py` — triangle test stays green.
- [x] `LivePredictorReactor` and `TrainerReactor` no longer raise `NotImplementedError`; their idempotency probes (Phase 4.7 pattern) are green in `test_cache_telemetry_reactor.py` (or a new `test_predictor_reactors.py`).
- [x] `make swarm.backtest WEEKS=12` runs end-to-end against the seed corpus and produces the JSON + Markdown report (per-predictor + swarm log-loss / accuracy / Brier / ECE). The CI gate (configurable, default 1%) is **operator-facing only** today — it correctly fails until Phase 5.4 trains real per-predictor weights / calibration tables (the toy hand-tuned baselines don't beat their best member). Wire-up to a hard CI block lands with the trainer.
- [x] **Phase 11 parity:** every must-status predictor has a `cpu_only`-marked parity test (`ai/swarm/agents/tests/test_predictor_cpu_parity.py`): determinism (same input → bit-identical PMF), CPU-forced reload matches default within `ε = 1e-9` per outcome, and instance footprint stays under `cfg.predictor_max_vram_mb`. The `cpu_only` marker is registered in the top-level `conftest.py` so a future Phase 11 device-aware runner can opt in/out.
- [x] **Phase 12 forward-test:** under simulated 50%-predictor kill, `consensus.v1` still emits `predict.final` with `degraded=true` and a non-empty `degraded_reason` (negative test, in-process — the `make chaos-kill-predictor` target itself ships in Phase 12).
- [x] **Phase 9 forward-test:** `request_id` round-trips end-to-end (synthetic API → predictors → consensus → `predict.final`); `prediction_id` is deterministic (same inputs → same id).
- [x] Versioning: `swarm` bumped to `0.3.0` at the Phase 5 landing; subsequent Phase 5 review patches bump `swarm` patch-level. A standalone `swarm_predictors` chart key remains an open option if §6+ work warrants distinct cadence.
- [ ] **Postgres-dependent items deferred to Phase 9:** real `predictor_weights` / `predictor_calibration` reads/writes in production (in-memory tables suffice for the CI gate). The migration ships now so Phase 9 wiring is additive.

### 5.6 Pivot v3 alignment & follow-ups (added 2026-04-28 review)

**Why this sub-section exists.** A retroactive review of Phase 5 against the Pivot v3 anchor docs ([`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md), [`design/EMITTER.md`](../design/EMITTER.md), [`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md)) and against the live consensus implementation surfaced seven issues. Four were fixed in this review (confidence-filter wiring, single calibration-store hit, bounded pending set, **`predict.request` subscription so the quorum-empty path actually fires in production** — see §5.2 / §5.5); three are tracked here as deferred but explicit follow-ups.

- [x] **Calibration store: Protocol seam already in place** (§5.4). In-memory backend ships now; Postgres backend stub waits on Phase 9; Feed backend stub waits on Phase 16. Consensus reads through the Protocol only — backend swap is constructor injection.
- [ ] **`FeatureSource` Protocol mirror.** Today's cross-phase note in §5 says "predictors read features by querying the storage agent's `match_normalized` rows". Post Phase 16 this violates the Pivot v3 swarm-isolation invariant (`swarm/` must consume feeds, not query Postgres). Ship a `FeatureSource` Protocol mirroring `CalibrationStore`: in-memory backend now (already de-facto in the predictor `features` dict), Postgres backend at Phase 9, **`FeedReader`-backed at Phase 16** (`feeds/match_records.v1.parquet`). Predictor `predict()` signature stays unchanged across all three. Tracked as part of Phase 16 wire-up.
- [ ] **Live-registry expected predictor set.** §5.2 currently uses a constructor-injected static tuple. A runtime `agent_registry` heartbeat query ("who is healthy right now?") would let consensus close the window early when scaled predictors come and go. Out of scope for Phase 5 / 14 (consensus is `replicas: 1`, predictors are typically static at deploy time); revisit if Phase 14.x scaling pressure justifies the per-vote Redis hit.
- [ ] **Backtest hard CI gate.** §5.3 ships the gate as **operator-facing only** today (rationale: hand-tuned baseline weights don't beat their best member, by construction). Wire-up to a hard CI block lands when `TrainerReactor` trains real per-predictor weights against the seed corpus.
- [x] **SWARM.md staleness sweep.** [`design/SWARM.md`](../design/SWARM.md) updated to (a) reflect JSON-not-CBOR for v1 (Phase 3 §3.1; CBOR is Phase 9), and (b) restate the consensus algorithm to match the live code (confidence floor + bounded pending + single store hit).

---

## ✅ Phase 6 — Proofreader & Drift Agents

**Goal:** Catch bad predictions, bad data, and slow model decay before they reach users.
**Depends on:** Phase 5
**Pivot v3 placement:** proofreader replicas + aggregator live under `swarm/proofreaders/` per [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md); the drift agent under `swarm/drift/`. Until Phase R2 lands the directory move, ship under the transitional path **`ai/swarm/agents/proofreader/`** and **`ai/swarm/agents/drift.py`**, importable as `swarm.agents.*` (matches Phase 4/5 layout — R2 is a `git mv`, not a rewrite).

**Cross-phase alignment (binding):**

- **Phase 3 §3.2 SDK contract.** Every proofreader replica, the aggregator, and `drift.v1` is an `Agent` (registers in `agent_registry`, heartbeats per `cfg.swarm_heartbeat_sec`, declares `subscribes`/`publishes`, deregisters on `SIGTERM`). Inherits `AgentRunner` retry/DLQ.
- **Phase 3 §3.3 bus semantics.** All Phase 6 handlers are **idempotent**: aggregator on `prediction_id` (via the Phase 4.7 `Ledger` Protocol — same in-memory backend now, Postgres at Phase 9); drift on `(match_id, market)` settled-set; per-replica proofreaders are pure functions of `predict.final` payload (no state).
- **Phase 3 §3.5 topic catalog (wire authority).** Phase 6 lands JSON Schemas at `ai/swarm/sdk/schemas/{predict.proofreader_verdict.v1,predict.approved.v1,match.outcome.v1,maint.event.v1}.json` plus the `MAINT_EVENT`/`MATCH_OUTCOME`/`PROOFREADER_VERDICT`/`PREDICT_APPROVED` constants in `topics.py`. Payload dataclasses live in `payloads.py`. `test_schemas_match_payloads.py` covers them.
- **Phase 3.4 swarmctl visibility.** Every Phase 6 agent appears in `swarmctl ps`; every new topic appears in `swarmctl topics`. Read-only — Phase 6 adds no mutating commands.
- **Phase 4.5 cache wiring.** `cache.v1` subscribes to **`predict.approved.v1`** (the post-quorum surface) — never to `predict.final`. The boundary test in `test_boundary_discipline.py` enforces this so a future regression cannot silently ship un-vetted predictions to users.
- **Phase 4.6 telemetry watch set.** `telemetry.v1._WATCHED_TOPICS` includes all four Phase 6 topics — `PREDICT_APPROVED`, `PROOFREADER_VERDICT`, `MAINT_EVENT`, and `MATCH_OUTCOME` — so the full proofreader → drift surface is visible in the Prometheus page. Closed in the 2026-04-30+ Phase 6 review pass (§6.5).
- **Phase 4.7 reactor base.** Aggregator's `_pending` overflow eviction mirrors the Phase 5 `consensus.v1` pattern (bounded map + buffered overflow drained outside the lock); same `Ledger` Protocol; same single-replica invariant (Phase 14 `replicas: 1`).
- **Phase 5 single-publication invariant.** Phase 5 `consensus.v1` publishes `predict.final` exactly once per `(match_id, market, request_id)`; Phase 6 aggregator publishes `predict.approved.v1` exactly once per `prediction_id`. Both rely on `replicas: 1` for the single-publication guarantee — multi-replica consensus / aggregator would need Postgres-backed leader election (Phase 14.x follow-up).
- **Phase 5 score-grid contract.** `predict.final.distribution.score_grid` is optional (Elo emits None; Dixon-Coles + the XGBoost pair emit one). The consistency proofreader **abstains gracefully** when no grid is attached (not a `reject`), so non-grid-producing predictors do not bias quorum against themselves.

**Forward-phase contracts (binding for Phase 6 design):**

- **Phase 7 `sec.input.v1`** runs *upstream* of NLP, not of Phase 6. Proofreader checks are post-prediction sanity, not adversarial-input defense; the two never share a topic.
- **Phase 8 `maint.scaler.v1`** consumes `maint.event.v1{kind=retrain_request}` (alongside the trainer). Phase 6 emits the event; Phase 8 owns the scheduling. The `kind` enum is open — Phase 8 may add `recalibration_request`, `cache_ttl_bump`, etc. without a schema migration.
- **Phase 9 odds plane.** Cross-source proofreader (§6.2) lands once `processor.odds.v1` produces persisted odds Records the proofreader can read via the `RecordStore` Protocol. The wire format reserves `flags=["cross_source.implied_prob_disagree"]` so the v2 check slots in without a verdict-payload migration.
- **Phase 9 API surface.** `cache.v1` subscription to `predict.approved.v1` is the only way a prediction reaches `/v1/matches/{id}/predictions`. The API never reads `predict.final` directly. Phase 9 docs must call this out explicitly.
- **Phase 12 chaos.** `make chaos-kill-proofreader PCT=33` (≥ 1 of 3 replicas down) must not block approvals — quorum is `⌊N/2⌋+1 = 2/3`, so the swarm degrades to 2-of-2 silently. Killing 2 of 3 trips `proofreader_no_quorum` after `cfg.proofreader_quorum_window_ms` (deterministic). Phase 12 owns the assertions.
- **Phase 13a CalibrationProfile.** Drift windows are keyed on `(profile_id, market)` once Phase 13a lands; until then `profile_id == league_id` (same default as Phase 5 `predictor_calibration`). No schema migration — `_Window` already keys on `(league_id | None, market)`; the profile resolver rebinds the field at Phase 13a.
- **Phase 13a per-league plausibility.** `cfg.proofreader_plausibility_max_prob = 0.85` is league-agnostic today. Phase 13a per-league overrides land via `LeagueConfig.proofreader_plausibility_max_prob` resolved by the proofreader replica from the vote-carried `league_id`; no schema change.
- **Phase 14 K8s.** `proofreader_aggregator.v1` and `drift.v1` run at `replicas: 1` (matches the Phase 5 `consensus.v1` pattern and [`design/SWARM.md`](../design/SWARM.md) roster). Per-check proofreader replicas (`proofreader.sanity.v1` etc.) scale horizontally, but the aggregator's single-publication guarantee forbids multiple aggregator replicas without leader election.
- **Phase 16 emitter.** Approved predictions and drift events stay on the bus (control plane). Realized outcomes (`match.outcome.v1`) move to feeds when Phase 16 lands; the `MatchOutcome` dataclass is the in-memory shape that maps 1:1 to `feeds/match_outcomes.v1.parquet` so the producer swap is constructor-injected, not a rewrite.
- **Phase 17 patcher scope.** Per [`CLAUDE.md`](../../CLAUDE.md), the patcher's allow-list is `extractor` / `schema` / `migration` / `fixture` — it never edits `swarm/`. Proofreader rejects + drift retrain requests are routed to humans via `proof.flag` and `maint.event.v1`, not to the patcher. Phase 6 needs no patcher integration.

### 6.1 Multi-proofreader voting

- [x] N proofreader agents (default 3). Each runs an independent set of rule-based + statistical checks. **Implemented (Wave B.1+B.2)** — three replicas (`proofreader.sanity.v1`, `proofreader.plausibility.v1`, `proofreader.consistency.v1`) wrap pure-function checks in [`prediction_checks.py`](../../ai/swarm/agents/proofreader/prediction_checks.py). The replica roster lives in `swarm.agents.proofreader.replicas.PROOFREADER_POLICY_CLASSES` (single source of truth — Phase-6 audit F3-1); horizontal fan-out moves to consumer-group sharding (Phase 14), which scales throughput without changing the vote count. Per-replica thresholds (`proofreader_sanity_eps`, `proofreader_plausibility_max_prob`, `proofreader_grid_consistency_tol`) live in the standard config triangle.
- [x] A `predict.final` is **published to API cache** only if `≥ ⌊N/2⌋ + 1` proofreaders pass it (simple majority; configurable quorum). Per pre-Phase-6 audit §D4: `⌊N/2⌋+1` gives the standard simple-majority threshold (N=3→2, N=5→3, N=7→4); the previous `⌈N/2⌉+1` formula collapses to **unanimity** for odd N, which is a different policy and was unintentional. **Implemented** in [`ai/swarm/agents/proofreader/aggregator.py`](../../ai/swarm/agents/proofreader/aggregator.py) — `cfg.proofreader_quorum` (derived property) derives N from `len(PROOFREADER_POLICY_CLASSES)` and computes `⌊N/2⌋+1` so the quorum cannot drift from the actual voter count (Phase-6 audit F3-1). The cache subscribes only to `predict.approved.v1` (Wave A.1 boundary test enforces this).
- [x] Failed checks emit `proof.flag` with structured reasons. **Implemented** — five new `ProofFlagKind` values: `proofreader_no_quorum`, `proofreader_rejected`, `proofreader_late_verdict_dropped`, `proofreader_duplicate_approval`, `proofreader_overflow`. Each fires from a distinct aggregator branch with full match / market / request / verdict context, validated by [`test_proofreader_aggregator.py`](../../ai/swarm/agents/tests/test_proofreader_aggregator.py).

### 6.2 Built-in proofreader checks

- [x] **Sanity:** probabilities sum to 1 ± ε; no negative; no NaN. **Implemented** in [`ai/swarm/agents/proofreader/prediction_checks.py`](../../ai/swarm/agents/proofreader/prediction_checks.py) (`sanity_check`) and wrapped by `SanityProofreader` in [`replicas.py`](../../ai/swarm/agents/proofreader/replicas.py). Tolerance is `cfg.proofreader_sanity_eps` (default 0.01); failure = `reject` (no warn path — the distribution is malformed). 9 adversarial tests in `test_prediction_checks.py`.
- [x] **Plausibility:** away win > 0.85 in a derby — flag for review. **Implemented** as `plausibility_check` + `PlausibilityProofreader`. Cap is `cfg.proofreader_plausibility_max_prob` (default 0.85); failure = `warn` (counts toward quorum — operator-visible but not fatal). Boundary test confirms `=cap` accepts, `>cap` warns.
- [x] **Consistency:** 1X2 distribution matches 0-0 / 2-1 / … score grid. **Implemented** as `grid_consistency_check` + `ConsistencyProofreader`. When a `score_grid` is present, its 1X2 marginals must match `market_outcomes` within `cfg.proofreader_grid_consistency_tol` (default 0.05); divergence = `reject` (contract violation). Abstains gracefully when no grid is attached.
- [ ] **Cross-source:** agreement with implied probability from at least one external odds source (when available). *Deferred to Phase 9* — no odds data plane yet.
- [ ] **Historical:** prediction not wildly out vs. last-3-meetings prior. *Deferred to §6.3* — drift agent owns realized-outcome state.

### 6.3 Drift agent (`drift.v1`)

- [x] Maintains rolling Brier / log-loss windows per league × market × predictor. **Implemented (Wave B.3)** in [`ai/swarm/agents/drift.py`](../../ai/swarm/agents/drift.py). v1 keeps a rolling Brier window per `(league_id, market)` (the swarm aggregate, since consensus has already merged the individual votes by the time we see `predict.approved.v1`); per-predictor windows wait for a durable `predict.vote` plane (Phase 9). State is in-memory; Postgres lift is a Phase 9 task — the contract here is identical, only the storage backend changes.
- [~] Trips when (a) any window crosses `cfg.drift_brier_ceiling`, or (b) KS-test on input feature distribution rejects stationarity at `cfg.drift_pvalue`. **(a) implemented** — once a `(league, market)` window is full, mean Brier > `cfg.drift_brier_ceiling` (default 0.30, env `NEGELIR_DRIFT_BRIER_CEILING`) trips a `retrain_request` with `reason=brier_floor`. The legacy `cfg.drift_accuracy_floor` (default 0.35, env `NEGELIR_DRIFT_FLOOR`) remains bound to the Phase 5 accuracy detector in `ai/model/drift.py` (genuinely measures accuracy, lower-is-worse, trips below the floor) — Phase-6 audit F-3 split the two so neither detector borrows the other's name. Re-trip is debounced until the window recovers below the ceiling (no spam). **(b) deferred** — KS-test needs the predictor's input feature vector on the bus (currently ephemeral inside the predictor process); the wire format reserves `reason=feature_ks` so the v2 KS-test agent slots in without a schema migration.
- [x] On trip → `maint.event{kind:retrain_request, target:<predictor>}`. **Implemented** — emits one `MaintEvent` per contributing model (the union of predictors that contributed to predictions in the breached window); `target` carries the predictor_id so the trainer can scope its retrain. New `maint.event.v1` topic + JSON schema; producer is `drift.v1` only (boundary test enforces).

### 6.4 Definition of Done

- [x] Three default proofreader replicas (`proofreader.sanity.v1`, `proofreader.plausibility.v1`, `proofreader.consistency.v1`) implemented + voting against `InMemoryBus` through `AgentRunner` in [`test_proofreader_replicas.py`](../../ai/swarm/agents/tests/test_proofreader_replicas.py). Each runs ONE check from `prediction_checks.py` (failure isolation; scale symmetry per Doctrine §2 Rule 5).
- [x] `proofreader_aggregator.v1` produces exactly one `predict.approved.v1` per `prediction_id` under at-least-once redelivery (idempotency test in [`test_proofreader_aggregator.py`](../../ai/swarm/agents/tests/test_proofreader_aggregator.py); single-publication guarded by the Phase 4.7 `Ledger` Protocol).
- [x] Quorum threshold = `⌊N/2⌋+1` (simple majority). N=3 → quorum=2 (default); N=5 → 3; N=7 → 4. Surfaced via `cfg.proofreader_quorum` derived property; never settable directly. Pre-Phase-6 audit caught the legacy `⌈N/2⌉+1` formula (which collapsed to unanimity for odd N) before launch.
- [x] **One `reject` is fatal regardless of quorum** (§6.1 contract). Boundary test `test_reject_vetoes_quorum` enforces.
- [x] Quorum-empty / window-elapsed paths emit `proof.flag` with `kind=proofreader_no_quorum` and **do not** emit `predict.approved.v1` (negative test).
- [x] Late verdict for an already-approved prediction → `proof.flag{kind=proofreader_late_verdict_dropped}`; aggregator does not double-emit (negative test).
- [x] **Bounded pending set.** Aggregator `_pending` capped at `cfg.proofreader_aggregator_max_pending` — a parallel knob that **defaults to `cfg.consensus_max_pending`** (4096) so operators see one number unless proofreader latency pressure forces them to tune the two apart. Overflow eviction emits `proof.flag{kind=proofreader_overflow}` outside the lock (mirrors Phase 5 `consensus_overflow` pattern).
- [x] `drift.v1` rolling window trips exactly once per breach (debounced via `_tripped` set; clears on recovery). Negative test: settling 100 outcomes after a trip without recovery emits no extra `maint.event.v1`.
- [x] `drift.v1` settled-set + pending-map are bounded (`cfg.drift_max_settled` / `cfg.drift_max_pending`, defaults 100 000) with insertion-order LRU eviction. Long-tail markets that never settle (anything other than 1X2 in v1) are evicted silently (memory bound, not correctness signal).
- [x] Every Phase 6 agent registers in `agent_registry`, heartbeats, and shows up in `swarmctl ps`; every Phase 6 topic shows up in `swarmctl topics` (Phase 3.4 contract preserved). Guard: `test_proofreader_visible_in_registry_and_topics`.
- [x] Every Phase 6 message validates against its JSON Schema at the live emission point (`test_schemas_match_payloads.py` + the live-emission probes in `test_phase6_bug_fixes.py`).
- [x] All Phase 6 config knobs (`proofreader_quorum_window_ms`, `proofreader_sanity_eps`, `proofreader_plausibility_max_prob`, `proofreader_grid_consistency_tol`, `drift_window_size`, `drift_brier_ceiling`, `drift_max_pending`, `drift_max_settled`, `drift_pvalue`) surface in `xops/env/.env.example`, `ai/common/defaults.yaml`, and `ai/common/config.py` — triangle test stays green. (Phase-6 audit F3-1 retired the standalone `proofreader_replicas` knob; the replica count now derives from `PROOFREADER_POLICY_CLASSES`.)
- [x] **Boundary discipline** ([`test_boundary_discipline.py`](../../ai/swarm/agents/tests/test_boundary_discipline.py)): (a) `cache.v1` does NOT subscribe to `predict.final`; (b) `predict.approved.v1` has exactly one producer (`proofreader_aggregator.v1`); (c) `match.outcome.v1` has exactly one producer (`storage.v1`); (d) `maint.event.v1` has exactly one producer (`drift.v1` in v1); (e) `predict.proofreader_verdict.v1` has exactly one consumer (the aggregator).
- [x] Versioning: `swarm` minor bump at the Phase 6 landing; subsequent Phase 6 review patches bump `swarm` patch-level.

### 6.5 Pivot v3 alignment & follow-ups (added 2026-04-30 review)

- [x] **`_Window.popleft` perf** — replaced O(window·models) set-rebuild with reference-counted `Counter` (O(|models per evicted entry|) per popleft). Hot path stays on a single `_Window` instance per `(league, market)` bucket; the windows themselves are bounded by config so the dict never grows.
- [x] **Topic catalog stale rows** — Phase 3.5 table updated to include the five Phase 6 topics (`predict.proofreader_verdict.v1`, `predict.approved.v1`, `match.outcome.v1`, `maint.event.v1`, `models.events.v1`) plus the corrected `proof.flag` producer set. Wire-authority lock-step rule restored.
- [x] **Phase 4.5 cache pointer fixed** — the stale "Subscribes to `predict.final`" bullet now correctly points to `predict.approved.v1` with the boundary-test reference.
- [x] **Telemetry watch set** — `_WATCHED_TOPICS` extended with `PROOFREADER_VERDICT`, `MAINT_EVENT`, and `MATCH_OUTCOME` alongside the existing `PREDICT_APPROVED` entry. Closes the Phase 4.6 follow-up; covered by `test_telemetry_watches_phase6_proofreader_drift_topics` in `test_cache_telemetry_reactor.py`. (Closed in the Phase 6 review pass.)
- [x] **Aggregator perf — running quorum counters.** `_Pending` now maintains `_accept_warn_count` and `_reject_count` via a delta-aware `set_verdict()` instead of recomputing `sum()` / `any()` over `verdicts.values()` on every quorum probe. Approver/rejecter list construction stays sort-on-finalize (called once per candidate). Matters once Phase 13a per-league replicas raise N above the default 3; harmless at today's N. Regression covered by `test_replica_upgrades_verdict_from_accept_to_reject_finalises_as_rejected` in `test_proofreader_aggregator.py`.
- [ ] **Per-league plausibility cap.** Today's `cfg.proofreader_plausibility_max_prob = 0.85` is league-agnostic. Phase 13a per-league overrides via `LeagueConfig.proofreader_plausibility_max_prob` (resolved from the vote-carried `league_id`). Until then, the global cap is the right default per `docs/design/TESTING_STRATEGY.md`.
- [ ] **Per-predictor drift windows.** §6.3 v1 scores the swarm aggregate; per-predictor Brier requires durable `predict.vote` plane (Phase 9). Wire format already reserves the trip surface (`MaintEvent.target` is per-predictor today via the contributing-models attribution).
- [ ] **KS-test on feature distribution.** Reserved as `MaintEvent.reason=feature_ks`; depends on a feature-vector plane (deferred to Phase 9 or the Phase 16 emitter `feeds/feature_vectors.v1.parquet`, whichever lands first).
- [ ] **Cross-source proofreader.** `flags=["cross_source.implied_prob_disagree"]` slot reserved; lands when `processor.odds.v1` produces persisted Records (Phase 9 odds plumbing).
- [x] **`drift_brier_ceiling` separate knob (not alias).** Phase-6 audit F-3 shipped a dedicated `cfg.drift_brier_ceiling` (default `0.30`, env `NEGELIR_DRIFT_BRIER_CEILING`) for the swarm `drift.v1` agent, while leaving `cfg.drift_accuracy_floor` (default `0.35`, env `NEGELIR_DRIFT_FLOOR`) bound to the legacy Phase 5 accuracy detector in `ai/model/drift.py`. An *alias* would have been wrong because the two detectors measure different metrics with opposite trip directions (Brier: lower-is-better, trip *above* ceiling; accuracy: higher-is-better, trip *below* floor) — locking them to the same numeric value would silently break one or the other.
- [x] **Proofreader replica roster is the single source of truth.** Phase-6 audit F3-1 retired the standalone `cfg.proofreader_replicas` env knob (default 3) because it was disconnected from the actual replica list in the bootstrap and silently broke quorum at any value other than 3. Replaced by `swarm.agents.proofreader.replicas.PROOFREADER_POLICY_CLASSES` (one entry per distinct check policy: sanity, plausibility, consistency); `cfg.proofreader_quorum` derives from `len(roster)` so the two cannot drift. Horizontal fan-out moves to consumer-group sharding (Phase 14), which scales throughput without changing vote count.
- [x] **`proofreader_internal_error` flag carries canonical fields.** Phase-6 audit F3-3 harmonised the replica internal-error proof.flag payload to use `agent` / `prediction_id` / `match_id` / `market` / `request_id` (the field set shared by every other Phase 6 proof.flag kind), replacing the prior `source` / `target` aliases that hid this kind from operator dashboard queries filtering by `prediction_id`.

---

## 🛡️ Phase 7 — Defense Agents (Malicious-Input, Anomaly, Rate Limit)

**Goal:** The system stays correct under adversarial input, both from users (API) and from upstream data sources, **without** ever blocking the happy path or becoming a single point of failure for QA.
**Depends on:** Phase 3 (SDK + bus + registry), Phase 4 (`scrape.raw` exists; `proof.flag` taxonomy is the prior surface), Phase 6 (the four MAJORs in [`docs/reports/phase4-to-6-pre-phase7.md`](../reports/phase4-to-6-pre-phase7.md) — single-instance frozenset, monotonic clocks for in-process LRU windows, fusion shape guard, `proof.flag.detail` length cap — must be green before §7.3 lands a fourth sliding-window agent inheriting the same pattern).
**Design ref:** [`design/SECURITY.md`](../design/SECURITY.md) §"Defense agents (Phase 7 detail)" is the binding contract for the per-agent pipelines; this phase wires it.

**Cross-phase alignment (binding):**

- **Phase 3 §3.5 topic catalog.** Phase 7 introduces five new topics — `qa.request`, `qa.request.v1`, `sec.alert.v1`, `sec.quarantine.v1`, `sec.denylist.v1` (see §7.5). Each must land with (a) a row in §3.5, (b) a JSON Schema in `ai/swarm/sdk/schemas/<topic>.json`, (c) a config-driven consumer-group prefix. The §3.5 `sec.alert` row is replaced with the versioned `sec.alert.v1` row (data-plane envelope, see §7.5 below).
- **Phase 3 §3.7 control-plane vs data-plane.** `qa.request` (raw user input arriving at the gateway) is **control-plane** and unversioned by convention (per the C2 cleanup in [`docs/reports/phase4-to-6-pre-phase7.md`](../reports/phase4-to-6-pre-phase7.md) §1.6 #8); `qa.request.v1` (sanitized output of `sec.input.v1`, consumed by NLP in Phase 10) is **data-plane** and versioned. The split exists so the wire format that reaches the predictor / NLP layer is a stable contract that survives sanitizer-rule iteration.
- **Phase 3 §3.4 swarmctl visibility.** Every Phase 7 agent registers + heartbeats and shows up in `swarmctl ps`; every new topic shows up in `swarmctl topics`. Read-only — Phase 7 adds no mutating commands. (Operator un-blocklisting is a Phase 8 maint surface; see forward contracts.)
- **Phase 4.1 scrape failure modes.** The Phase 4.1 contract — `404 → proof.flag{kind=upstream_missing}`, `5xx → SDK retry budget → DLQ` — **stays unchanged**. `sec.scrape.v1` watches only **successful** `scrape.raw` payloads (HTTP 200 with non-empty body); it never re-handles upstream failures, and never publishes `proof.flag` for the same condition. Boundary test enforces (see §7.6).
- **Phase 4.6 telemetry watch set.** `telemetry.v1._WATCHED_TOPICS` extends to include `QA_REQUEST` (control-plane raw, mirrors the existing `PREDICT_REQUEST` watch), `QA_REQUEST_V1`, `SEC_ALERT_V1`, `SEC_QUARANTINE_V1`, `SEC_DENYLIST_V1`. Cardinality stays bounded by the topic enum (per the N3 fix and the C-level cardinality note in the pre-Phase-7 audit §1.4); `evidence_ref` (sha256) and `subject` (IP/client_id) are payload fields, **never** label dimensions — explicit assertion in `test_telemetry_watches_phase7_topics`.
- **Phase 6 single-publication / monotonic-clock pattern.** `sec.rate.v1` is the next sliding-window agent after consensus / aggregator / drift. It uses **`time.monotonic()`-based ms** for in-process bucket math (per pre-Phase-7 audit M2/M4); only the **on-the-wire** `produced_at` and the Redis denylist TTL stamps stay wall-clock. `sec.rate.v1` is the **sole writer** of the Redis denylist hash and joins `SINGLE_INSTANCE_AGENTS` (per audit M1's frozenset contract); horizontal fan-out moves to consumer-group sharding (Phase 14) with a Postgres-backed leader for the denylist writer.
- **Phase 6 `proof.flag` taxonomy.** Phase 7 does **not** add `proof.flag` kinds — the security verdicts have their own envelope (`sec.alert.v1`). `proof.flag` stays scoped to *post-prediction sanity*; `sec.alert.v1` carries *adversarial-input* verdicts. The two never share a topic (forward contract carried over from Phase 6).
- **Defense-in-depth contract (binding doctrine, not relaxable in later phases).** Every Phase 7 agent's fail-open path is **safe only because** later layers carry independent defenses: (a) `sec.input.v1` fails open to `pass` *only because* the Phase 10 NLP layer answers from **templated responses with no LLM in the answer-generation hot path** (per [`design/SECURITY.md`](../design/SECURITY.md) threat model row 1); (b) `sec.scrape.v1` fails open *only because* the Phase 4 categorizer / processor never executes upstream JS (no headless browser by default); (c) `sec.rate.v1` fails open on Redis partition *only because* the Phase 9 gateway carries a per-process secondary token bucket (sized `cfg.sec_rate_secondary_capacity`, default 10× the per-IP cap, lossy-on-restart) as a circuit-breaker fallback. If a future phase removes any of (a)/(b)/(c), the corresponding Phase 7 fail-open default must be reconsidered. Recorded here so the doctrine survives later refactors.

**Forward-phase contracts (binding for Phase 7 design):**

- **Phase 8 `maint.scaler.v1`** consumes `sec.alert.v1{kind=rate_burst, severity≥warn}` to inform scale-up decisions for the API frontend (alongside the existing telemetry-driven path). The `kind` enum is open — Phase 8 may add `replica_unhealthy`, `denylist_growth_anomaly`, etc. without a schema migration.
- **Phase 8 maint surface for denylist override.** Operator un-blocklisting (false-positive recovery) lands as a Phase 8 maint command (`maint.event.v1{kind=denylist_clear, target=<client_id|ip>}`) consumed by `sec.rate.v1`. Phase 7 ships the consumer hook stub (`sec.rate.v1` subscribes to `maint.event.v1` filtered to the `denylist_clear` kind) so Phase 8 can land the publisher without a schema change.
- **Phase 9 API surface.** The Go gateway is the **first-line** enforcer for the cheap, deterministic checks (length cap, charset, deny-list lookup, token bucket math). The `sec.input.v1` *agent* runs only the **escalation tier** (small classifier) for ambiguous payloads the gateway flagged but did not quarantine outright. This avoids a Redis Streams round-trip on every QA request — the median request is decided in-process inside Go and never touches the bus. The split is encoded in §7.1 / §7.3.
- **Phase 9 §9.3 request flow.** `client → API gateway → JWT verify → sec.rate.v1 (in-process: bucket peek; bus: bucket update + alert) → publish predict.request` (or `qa.request` for Q&A). The gateway never publishes `qa.request.v1` directly — only `sec.input.v1` does, after running the escalation classifier on top of the gateway's deterministic verdict. `predict.request` is unaffected (no NLP surface).
- **Phase 10 NLP layer.** Subscribes only to `qa.request.v1` (sanitized). It never reads `qa.request` (raw). Boundary test enforces.
- **Phase 11 device strategy.** The `sec.input.v1` classifier respects the Phase 11 device probe (`cfg.sec_input_classifier_device = auto|cuda|rocm|npu|cpu`), shares the GPU round-robin scheduler with other LLM-class agents, and **must pass the `cpu_only` test marker** (Phase 11.3) — when GPU is contended, classifier falls back to CPU; when CPU latency exceeds `cfg.sec_input_classifier_max_latency_ms`, the circuit breaker (§7.1) opens and the verdict defaults to **`pass` with a `sec.alert.v1{kind=classifier_degraded, severity=warn}`** (fail-open, alarm-loud — never fail-closed on QA, per the §7.7 doctrine).
- **Phase 12 chaos.** `make chaos-kill-sec-input PCT=100` (classifier process down) must not block QA: the gateway's deterministic checks still run, the circuit breaker opens, and verdict defaults to `pass` with a `classifier_degraded` alert. `make chaos-redis-partition` must not double-charge token buckets (idempotent denylist writes; bucket math is sticky-on-skew thanks to the monotonic clock). `make chaos-flood-rate-limit RPS=10000` must trip `sec.alert.v1{kind=rate_burst}` deterministically within `cfg.sec_burst_window_ms` and **must not** evict legitimate users from the bucket map (bounded LRU per audit M1 pattern). Phase 12 owns the assertions; Phase 7 owns the surfaces. **Phase 7 ↔ Phase 12 circular-dep policy:** until Phase 12 lands, the §7.7 DoD bullet that requires Phase-12-catalogue entries is satisfied by **stub rows** in `docs/testing/phase12_catalogue.md` (one row per defense check, body = "TBD — implementation pending Phase 12"). The stubs are a forward-compatible placeholder, **not** a green check.
- **Phase 13 lexicon / Phase 13a per-league overrides.** `sec.input.v1`'s deterministic injection rules are league-agnostic in v1. Phase 13a per-league overrides (e.g. derby-day burst ceilings) land as `LeagueConfig.sec_burst_multiplier` resolved by `sec.rate.v1` from the JWT claim's preferred league or the request's `league_id` query param; no schema change.
- **Phase 16 emitter.** Quarantined samples (`sec.quarantine.v1`) move to the feeds plane (`feeds/sec_quarantine.v1.parquet`) when Phase 16 lands, so long-tail forensic storage doesn't pin the bus. The in-memory `QuarantineSample` dataclass maps 1:1 to the parquet row so the producer swap is constructor-injected, not a rewrite.
- **Phase 17 patcher scope.** Per [`CLAUDE.md`](../../CLAUDE.md), the patcher's allow-list is `extractor` / `schema` / `migration` / `fixture` — it never edits `swarm/` and never touches `server/internal/auth/` or `*/crypto/`. `sec.scrape.v1` anomalies that look like *parser* problems (DOM drift) route to the patcher via the existing `proof.flag{kind=parse_failed}` Phase 4 channel, **not** through `sec.alert.v1`. The two channels are deliberately disjoint: `sec.alert.v1` is operator-only (humans triage); `proof.flag{kind=parse_failed}` is patcher-eligible. `sec.scrape.v1` decides which channel to use based on whether the anomaly affects bytes-on-the-wire (`sec.alert.v1`: encoded redirect, mismatched content-type, sudden inflate ratio) or post-parse structure (`proof.flag`: selector-missing-after-DOM-shift). Boundary test enforces.

### 7.1 Prompt-injection / payload-anomaly agent (`sec.input.v1`)

The agent runs the **escalation tier** on top of the Go gateway's deterministic first line. The split is the doctrine: deterministic + cheap stays in-process inside the gateway (no Redis hop on the median QA call); the small-classifier escalation runs as a Python agent on the bus.

- [x] **Topology.** Two surfaces, one boundary:
  - Go gateway middleware (`server/internal/sec/input.go`): runs steps 1–4 of the [`design/SECURITY.md`](../design/SECURITY.md) `sec.input.v1` pipeline (length cap, charset / control-char strip, NFC + Turkish-aware lowercase, deterministic injection rules). Verdict `quarantine` → write to `sec.quarantine.v1` and return `400` to the client. Verdict `pass` → publish `qa.request.v1` directly. Verdict `sanitize` (rules inconclusive) → publish `qa.request` (raw) for the agent to escalate.
  - Python agent (`ai/swarm/agents/sec/input.py`): subscribes to `qa.request`, runs the small classifier (step 5), publishes `qa.request.v1` (verdict `pass`) or `sec.quarantine.v1` (verdict `quarantine`), and emits `sec.alert.v1{severity=info|warn}` for every escalation that resolved to `quarantine`.
- [x] **Detects:** prompt injection ("ignore previous instructions", system-prompt smuggling, role-play jailbreaks), tool-call smuggling, base64-encoded payloads with `eval`/`exec`/`__import__` markers, zero-width chars, RTL overrides, oversized inputs (`> cfg.sec_input_max_len`, default 8 KiB), language-spoofing (claims TR but body is JS / shell / SQL exfil), homoglyph attacks (Cyrillic 'е' for Latin 'e' in known team names — uses Phase 13 lexicon when available; deterministic NFKC fold in v1).
- [ ] **Detection strategy.** Fast **deterministic** rules first (regex over a YAML pattern file at `ai/common/security/injection_patterns.yaml`, charset bitmap, length, NFC + NFKC normalization, Turkish-dotted-i rules); only escalate ambiguous cases to a small classifier (`distilbert-base-multilingual-cased`-style, ≤ 60 MB on disk, ≤ 200 MB resident) running on GPU when available, CPU fallback per Phase 11.3. **Pattern hot-reload.** The YAML file is reloaded on mtime change (poll interval `cfg.sec_input_pattern_reload_s`, default 30 s) so operators can iterate on rules without restarting the gateway / agent; reload is atomic (parse → validate → swap pointer) and emits `sec.alert.v1{kind=pattern_reload, severity=info, reason=<sha256>}`. Parse failure leaves the previous ruleset in place and emits `severity=error`. **Reload sync across pods (binding for K8s).** mtime polling does not fire on `kubectl rollout` of a ConfigMap-mounted file in every CRI runtime; therefore `sec.input.v1` *also* subscribes to a control-plane fan-out topic `sec.config.v1` (single producer: any agent that detects a local mtime delta; envelope `{config_name, sha256, mtime}`) and re-reads the file on every event with a sha256 mismatch from its current ruleset. Both the Go gateway and the Python agent listen; the file remains the source of truth, the bus event is just the wake-up. mtime poll stays as the default trigger (no bus dependency in dev).
- [x] **Length-cap byte semantics.** `cfg.sec_input_max_len` is **bytes after UTF-8 encoding**, not codepoints (a 4 KiB JSON request body of `\u0001` characters is 6 KiB on the wire — the byte count is what stresses Redis and the classifier tokenizer, not the codepoint count). Hard-rejected at the gateway *before* JSON parsing — payload length is checked against `Content-Length` first, then re-checked against actual body bytes after read (the second check defends against `Content-Length` lying). Both checks emit `sec.alert.v1{kind=payload_oversize}` (different `reason` substring) and return 413.
- [x] **Verdicts:** `pass`, `sanitize`, `quarantine`. The three are mutually exclusive and exhaustive. **`pass`** → publish `qa.request.v1{sec_verdict=pass}` unchanged. **`sanitize`** → apply the deterministic transform (NFC normalize, strip control chars / zero-widths / RTL overrides, optional homoglyph fold via Phase 13 lexicon when present) and publish `qa.request.v1{sec_verdict=sanitized, sec_steps_run=[...]}` carrying the **transformed** text; the original raw bytes are **not** retained on the bus (operator-visible only via the `sec.alert.v1{kind=charset_anomaly, severity=info}` evidence pointer if quarantine forensics are needed later). **`quarantine`** → publish to `sec.quarantine.v1` (envelope: `{quarantine_id, source=qa|scrape, raw_bytes_b64 (raw payload capped at cfg.sec_quarantine_payload_max_bytes BEFORE base64 encoding — wire size ≈ ⌈4N/3⌉), verdict=quarantine, reasons[], detected_at, client_id?, ip?, pii_redacted: bool}`) and persisted by Phase 4 `storage.v1` to the `quarantine_samples` table (migration `007_quarantine.sql`). TTL configurable (`cfg.sec_quarantine_ttl_days`, default 30); a Phase 8 `maint.backup.v1` job prunes. **PII handling.** Quarantined samples may contain user identifiers (email, name) — the table carries an `erased_at` column and a Phase 8 maint command (`maint.event.v1{kind=quarantine_erase, target=<client_id>}`) sets `raw_bytes_b64=NULL` for the matching rows (right-to-erasure hook; the `quarantine_id` row stays for audit). Quarantined samples **never** reach predictors and **never** appear on `qa.request.v1`.
- [x] **Latency budget.** Gateway middleware: hard cap `cfg.sec_input_gateway_max_latency_ms` (default 10 ms). Agent classifier: hard cap `cfg.sec_input_classifier_max_latency_ms` (default 100 ms, **per-batch wall-clock, not per-request** — see batching note below). On breach → circuit breaker opens for `cfg.sec_input_breaker_open_s` (default 30 s); verdict defaults to `pass` (fail-open) and `sec.alert.v1{kind=classifier_degraded, severity=warn}` is emitted exactly once per breaker-open window (debounced — see §7.4 generalized debounce contract).
- [ ] **Classifier batch inference (efficiency).** A distilbert-class model on a contended GPU runs ~3–5× more samples / second under micro-batching than per-request inference. The agent accumulates pending classifications into a batch of up to `cfg.sec_input_classifier_batch_size` (default 8) for at most `cfg.sec_input_classifier_batch_window_ms` (default 20) before launching the forward pass. Per-request latency budget is the **batch-departure deadline** (request enters at t=0, must depart on a forward pass by t = 100 ms - p99(forward_pass_ms)); requests near deadline depart immediately on a smaller batch. CPU fallback path skips batching (single-request) because CPU forward-pass time scales with batch size 1:1 — batching gives no win and adds head-of-line blocking. Toggle: `cfg.sec_input_classifier_batch_enabled` (default `auto`, follows the device probe).
- [ ] **Classifier load shedding (backpressure).** The classifier queue is bounded by `cfg.sec_input_classifier_max_pending` (default 256). On overflow, the oldest pending request resolves with verdict `pass` and a `sec.alert.v1{kind=classifier_load_shed, severity=warn}` (debounced) — fail-open consistent with §7.7 doctrine. Overflow rate is exposed as `negelir_sec_input_classifier_shed_total{reason=queue_full}` so operators see saturation before it becomes a chronic miss.
- [x] **Auth-endpoint scope (with password-field carve-out — binding correctness).** `sec.input.v1` runs on every QA payload AND on the `email` field of `/v1/auth/login` / `/v1/auth/register` request bodies (user-controlled, injection-prone). The **`password` field is exempt from the entire pipeline** — running NFC normalization or Turkish-aware lowercasing on it would silently break bcrypt verification for any password containing combining characters, dotted-i, or non-NFC sequences (the stored hash was computed from the raw client bytes). The gateway extracts the JSON `password` value, holds it in a separate buffer that is forwarded **as-is** to the auth handler, and feeds only the `email` (and any other free-text claim fields) to the sec pipeline. The password buffer is also redacted from quarantine envelopes (`pii_redacted=true` on `sec.quarantine.v1`). Boundary test (`server/internal/sec/input_test.go::TestPasswordFieldBypassesNormalization`) feeds a known non-NFC password, asserts the byte-stream that reaches `auth.Verify` is byte-identical to the request body, and asserts no quarantine row carries the password substring even after `--no-redact` debug builds.
- [x] **No `proof.flag` emission.** All sec.input verdicts go to `sec.alert.v1` / `sec.quarantine.v1`; the `proof.flag` topic stays scoped to post-prediction sanity (Phase 6 doctrine).

### 7.2 Upstream-data anomaly agent (`sec.scrape.v1`)

- [x] Subscribes to `scrape.raw` filtered to **HTTP 200 + non-empty body**. Failures (404 / 5xx / empty body) stay on the Phase 4.1 path (`proof.flag` / DLQ); boundary test enforces no double-handling.
- [x] Watches for: sudden body-size delta (`> cfg.sec_scrape_size_delta_pct`, default 200%, vs. rolling source baseline), suspicious JS markers in DOM bodies (regex over a configurable allowlist of known-good script srcs from the seed corpus), encoded redirects (`<meta http-equiv="refresh">`, JS `location` writes inside the first 4 KiB), mismatched content-type (header vs. magic-byte sniff), inflate-ratio outliers (gzip / brotli expansion > `cfg.sec_scrape_inflate_ratio_max`, default 50× — defense against zip-bomb-style upstream payloads).
- [x] **Cold-start warm-up.** A new source has no baseline. For the first `cfg.sec_scrape_warmup_samples` (default 50) successful samples per source, the agent **collects** baseline statistics but **does not emit `sec.alert.v1`** — only a single `sec.alert.v1{kind=baseline_warmup, severity=info}` at start and at end. Without warm-up, every newly onboarded source would generate spurious `dom_size_delta` / `inflate_ratio_outlier` alerts on its first request (the rolling baseline is empty → any value is an "outlier").
- [x] **Baseline storage — streaming statistic, not capped LRU.** A 30-day rolling baseline of raw samples capped at 5000 entries gives wrong percentiles (recent samples evict, p95 drifts). Use **streaming estimators**: Welford's online algorithm for (mean, variance) of body size and inflate ratio; P² algorithm (or t-digest if a small dep is acceptable) for median / p95; bounded count-min sketch for content-type histogram. Memory bound: `O(constant per source)` regardless of sample count, ~4 KiB per source. In dev / CI: compares `bytes_sha256` against [`infra/mock/seeds/manifest.json`](../../infra/mock/seeds/manifest.json) (exact match expected; mismatch is a hard `sec.alert.v1{severity=critical}` — the manifest is the contract, drift means the mock vhost is serving content that disagrees with `make mock.verify`). In prod: streaming statistics persisted to Postgres (`source_fingerprints` table, migration `008_source_fingerprints.sql`) — schema carries the serialized sketch state, not raw samples; flush on interval (`cfg.sec_scrape_baseline_flush_s`, default 300) so a process crash loses ≤ 5 min of update. *(Closed: `ai/swarm/agents/sec/scrape.py::_Welford` (population mean/variance, O(1) per update) + `_simhash64` (deterministic 64-bit DOM fingerprint) + `_SourceBaseline` (per-source streaming state). Direct proof tests in `test_phase7_streaming_baseline.py` (12 tests): Welford parity vs textbook two-pass on small / large-mean / small-mean / zero-variance / 10k-random corpora; constant memory footprint with field-set guard; SimHash determinism + Hamming distance bounds. Content-type histogram is a bounded `dict[str,int]` (cardinality bounded by the source registry — the value space, not the URL space). P² / t-digest / count-min sketch deferred — current Welford-only baseline already meets the §7.2 "O(constant per source)" doctrine; percentile estimators land when an alerting rule actually needs p95 (none in v1). Postgres flush of sketch state is the Phase 8 follow-up — schema `008_source_fingerprints.sql` is reserved.)*
- [x] **Operator baseline reset (intentional upstream redesign).** When an upstream site legitimately redesigns (TFF re-skin, Mackolik DOM shuffle that the patcher already adapted to), the rolling baseline is now wrong — every sample looks like an anomaly. The operator clears the baseline for one source via `maint.event.v1{kind=baseline_reset, target=<source_id>}` (Phase 8 publisher; Phase 7 ships the `sec.scrape.v1` consumer hook). On consume: the agent zeroes the in-memory sketches for `target`, deletes the matching `source_fingerprints` row, re-enters the warm-up state (`cfg.sec_scrape_warmup_samples` window), and emits `sec.alert.v1{kind=baseline_reset, severity=info, subject=<source_id>}`. The `kind=baseline_reset` value joins the §7.4 known-kinds set.
- [x] **Verdict routing.** Bytes-on-the-wire anomalies (encoded redirect, mismatched content-type, inflate-ratio outlier, suspicious-JS marker) → `sec.alert.v1`. Post-parse-shape anomalies that surface upstream of categorizer (e.g., DOM drift detected by structural fingerprint divergence) → `proof.flag{kind=parse_failed}` so the Phase 17 patcher can pick them up. Routing is a single-decision function with a unit test per branch. **DOM structural fingerprint = SimHash of normalized tag-path bag (tag·class·id triples, no text content), 64-bit, distance computed via popcount.** SimHash is chosen over `xxhash(html)` because it is robust to whitespace + attribute-order churn that the patcher already absorbs; threshold `cfg.sec_scrape_simhash_max_distance` (default 12 bits out of 64). Fingerprint computation is bounded by source-level `cfg.sec_scrape_dom_fingerprint_max_nodes` (default 5000) — oversized DOMs sample the first N tag-path triples deterministically (insertion order from a single-pass parser), so the routing decision stays O(N) regardless of body size.
- [x] **Bounded state.** Streaming sketches are `O(constant)` per source; pending classification queue is `cfg.sec_scrape_max_pending`-bounded with insertion-order LRU eviction (mirrors the Phase 6 `drift.v1` `_pending` pattern). The set of *active* sources is bounded by the source registry (Phase 2.8) — no per-arbitrary-string growth.

### 7.3 Abuse / rate-limit agent (`sec.rate.v1`)

- [x] **Two-tier enforcement.**
  - **Pre-auth (per IP-subject):** lower limits, defense against credential stuffing on `/v1/auth/login`. Bucket capacity `cfg.sec_rate_pre_auth_capacity` (default 30 tokens), refill `cfg.sec_rate_pre_auth_refill_per_s` (default 0.5/s).
  - **Post-auth (per `client_id` from JWT):** higher limits for legitimate users. Bucket capacity `cfg.sec_rate_post_auth_capacity` (default 600), refill `cfg.sec_rate_post_auth_refill_per_s` (default 5/s). Per-tier multipliers (free / paid) land in Phase 9 once the user table carries a `tier` column; the agent reads the tier from the JWT claim — no second DB hit.
- [x] **IP-subject derivation (binding — IPv6 address-space defense).** A naïve per-IP bucket lets an IPv6-equipped attacker spray 2⁶⁴ unique addresses from a single allocation, exhausting both the in-process subject map and the Redis denylist. The IP **subject key** is the network prefix, not the host: IPv4 → `/cfg.sec_rate_ipv4_prefix` (default `/32`, full host); IPv6 → `/cfg.sec_rate_ipv6_prefix` (default `/64`, the typical end-site allocation boundary). Knobs are tunable for shared-CG-NAT environments (operators may widen IPv4 to `/24`).
- [x] **`X-Forwarded-For` trust boundary (binding — spoofing defense).** The gateway derives the client IP from the **right-most untrusted hop** of `X-Forwarded-For`, walking right-to-left and skipping addresses that match `cfg.sec_rate_trusted_proxies` (CIDR list, default empty → ignore XFF entirely and use TCP peer). With XFF disabled, an attacker can only spoof their TCP source. Documented behaviour, with a unit test that asserts the right-most-untrusted derivation against a worked example.
- [x] **Implementation.** Token-bucket math + denylist check run **inside a single Redis Lua script** (`infra/redis/lua/sec_rate_check.lua`, GCRA — Generic Cell Rate Algorithm). The script atomically: (1) checks `sec:denylist:{subject}` → returns `denied` if present; (2) updates the GCRA bucket with a per-call **weighted cost** (see below) → returns `(allow|throttle, remaining, retry_after_ms)`. **One `EVALSHA`, one round-trip, atomic by Redis's single-threaded execution model.** (Earlier draft incorrectly described combining this with `MULTI` — Lua is the atomicity primitive; `MULTI`/`EXEC` is a separate mechanism and does not compose with `EVAL`.) Bucket state TTL = `cfg.sec_rate_bucket_idle_ttl_s` (default 3600); idle buckets evict naturally and do not pin Redis memory. The `sec.rate.v1` Python agent never sits on the hot path — it runs only the **anomaly detector** (sliding-window burst detection over `sec.alert.v1{kind=rate_throttled}` events the gateway emits asynchronously) and the **denylist writer**.
- [x] **Lua script lifecycle (binding for production stability).** The script carries a header marker `-- VERSION: <semver>` and a `-- SHA256: <digest>` line auto-generated by `make verify.lua` (CI gate). On startup the Go gateway computes the local sha256, calls `SCRIPT LOAD`, caches the resulting sha for `EVALSHA` calls, and refuses to start if Redis returns a different sha (deployment skew detection). On `NOSCRIPT` at runtime (Redis flushed scripts after a restart) the gateway falls back to `EVAL` once and re-runs `SCRIPT LOAD` to repopulate — emits `sec.alert.v1{kind=rate_script_reloaded, severity=info}`. The `sec.rate.v1` Python agent runs the same lifecycle for its denylist-mutation script (`sec_denylist_mutate.lua`).
- [x] **Weighted token cost per endpoint (efficiency + fairness).** A `GET /v1/healthz` should not consume the same bucket capacity as a `POST /v1/qa` (the latter triggers a downstream LLM batch). The Lua script accepts a `cost` argument (positive integer); the gateway routing table maps each endpoint pattern to a cost via `cfg.sec_rate_endpoint_costs` (YAML at `ai/common/security/endpoint_costs.yaml`, hot-reloaded on the same `sec.config.v1` channel as the injection patterns). Default mapping: `/v1/healthz` → 0 (free), `/v1/leagues*` → 1, `/v1/matches/*/predictions` → 2, `/v1/qa` → 5, `/v1/auth/*` → 3 (reflects bcrypt CPU cost). Unmapped endpoints get `cfg.sec_rate_default_cost` (default 1). Costs are observable: the Lua script returns `cost_charged` so the gateway can label its `negelir_sec_rate_charge_total{endpoint, cost}` counter (cardinality bounded by the endpoint pattern set, not the URL set).
- [x] **Gateway secondary bucket (Redis-partition fail-open).** When the Lua call fails (Redis partition, timeout > `cfg.sec_rate_redis_timeout_ms`, default 50 ms), the gateway falls through to a **per-process secondary token bucket** (capacity `cfg.sec_rate_secondary_capacity`, default 10× the per-IP cap; refill `cfg.sec_rate_secondary_refill_per_s`) and emits `sec.alert.v1{kind=rate_redis_degraded, severity=error}` (debounced per §7.4). The secondary is intentionally lossy (in-process, restart-clears) — its sole purpose is to keep the gateway responsive during a brief Redis blip without becoming a free-pass. Doctrine: defense-in-depth, not a bypass.
- [x] **HTTP throttle response (RFC 6585 + 7231).** When the Lua script returns `throttle` or `denied`, the gateway responds `429 Too Many Requests` (or `403 Forbidden` for denylist) with `Retry-After: <ceil(retry_after_ms / 1000)>` and a JSON body `{error: "rate_limited", retry_after_ms, reason}`. The `Retry-After` header is mandatory; clients MUST honor it (the Phase 9 client SDK will). Throttled responses do NOT consume an additional token (the bucket already debited the cost on the throttling decision); a retry inside the retry-after window incurs only the per-call denylist lookup, not a second bucket charge.
- [x] **Sliding-window burst detection** (`cfg.sec_burst_threshold`, e.g. > 100 distinct rejected attempts in `cfg.sec_burst_window_ms` from a single subject). Window math uses `time.monotonic()`-based ms (per pre-Phase-7 audit M2/M4); on-the-wire `produced_at` stays wall-clock. **Idempotency under at-least-once redelivery.** The agent's burst counter dedups on `(subject, event_id)` (event_id is the `alert_id` of the source `sec.alert.v1{kind=rate_throttled}` event); seen ids live in an LRU bounded by `cfg.sec_burst_dedup_window` (default 10 000) per subject. Without dedup, a Redis Streams replay during consumer-group rebalance would inflate counts and trip false `rate_burst` alerts.
- [x] **Bounded subject map with eviction telemetry (anti-spray).** In-process LRU of subjects-being-watched capped at `cfg.sec_rate_max_subjects` (default 100 000, mirrors `cfg.drift_max_settled`). Eviction does NOT signal correctness (the Redis bucket survives), but a sustained eviction rate is a smell of subject-spray attack — exposed as `negelir_sec_rate_subject_evictions_total{reason}` and trips `sec.alert.v1{kind=subject_map_churn, severity=warn}` when the eviction rate exceeds `cfg.sec_rate_eviction_rate_alert_per_s` (default 50/s) for `cfg.sec_rate_eviction_rate_window_s` (default 60). Replaces the prior "silent eviction" wording — silent on correctness, **loud on telemetry**.
- [x] **Denylist (sole writer).** `sec.rate.v1` is the sole writer of the Redis hash `sec:denylist:{client_id|ip}` with TTL `cfg.sec_denylist_ttl_s` (default 3600 = 1 h, escalating per offense via `cfg.sec_denylist_escalation_factor`). Reads happen inside the Lua script (above); the agent never serves reads on the hot path. Denylist mutations also publish `sec.denylist.v1{action=add|remove, subject, ttl_s, reason, decided_at}` so dashboards stay in sync without polling Redis.
- [x] **Denylist cardinality cap (DoS defense).** A randomized-IP attacker can otherwise grow the denylist without bound. Hard cap `cfg.sec_denylist_max_entries` (default 250 000); when the cap is reached the agent (a) stops adding new entries with `sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}` (the kind already exists in §7.4's enum), (b) accelerates eviction by halving the TTL of the oldest decile, (c) holds a `sec:denylist:capped` Redis flag the gateway reads (one cached read per second, not per request) so it can switch to **subnet-level denylist mode** — denylisting the `/24` (IPv4) or `/48` (IPv6) of the offending subject for the duration of the cap pressure. Cardinality of the cap-mode denylist is bounded by the IPv6 routing table (~10⁶ /48 prefixes globally — still tractable; in practice attackers come from a handful of ASNs). *(Closed: server-side enforcement in `infra/redis/lua/sec_denylist_mutate.lua` — atomic counter `sec:denylist:_count`, `rejected_capped` return on new-entry overflow (re-adds refresh TTL without growing), `sec:denylist:capped` flag SET with 300 s safety-net TTL for the gateway to switch to subnet-mode. Python hook `SecRateAgent.note_denylist_capped()` emits the `denylist_growth_anomaly` critical alert (bypasses debounce by default per §7.4). Tests: `test_phase7_lua_redis.py::test_sec_denylist_mutate_cap_rejects_overflow` exercises the cap server-side; `test_phase7_denylist_growth_anomaly.py` (4 tests) covers the Python alert path including idempotency under repeated cap reports and per-subject debounce. Sub-bullet (b) "halve TTL of oldest decile" deferred to a Phase 8 sweeper. **v1.1.0 follow-up (Phase 7 audit)**: the v1.0.0 design tracked cardinality with a plain `INCR/DECR sec:denylist:_count` counter, which natural Redis TTL expiry never decremented — the cap flag would have flipped on permanently after enough churn, over-blocking legitimate users via subnet-mode. v1.1.0 of `sec_denylist_mutate.lua` replaces the counter with a sorted set `sec:denylist:_zset` (score = `expires_at_ms`); every mutation lazily evicts expired members via `ZREMRANGEBYSCORE` so `ZCARD` is always truthful. New regression tests in `test_phase7_lua_v110_cardinality.py` (6 live-Redis tests) prove (a) `now_ms` is mandatory on add, (b) the ZSET tracker lazily evicts expired entries before the cap check, (c) the cap recovers after natural TTL expiry, (d) re-add overwrites the score, (e) remove decrements truthfully, (f) the capped flag carries a bounded 300 s safety-net TTL. `sec_rate_check.lua` v1.0.1 adds defensive `idle_ttl_s <= 0` validation (would have produced an immortal bucket via `SET ... EX 0`).)*
- [x] **Operator override hook.** Subscribes to `maint.event.v1{kind=denylist_clear, target=<subject>}` (Phase 8 publisher) and removes the matching denylist entry, emitting a `sec.denylist.v1{action=remove, reason=manual_override}` event. The same channel handles the cap-mode subnet entries — operators target the `/24` or `/48` directly. The same channel also handles `kind=baseline_reset` for `sec.scrape.v1` (per §7.2). **Cross-phase: `maint.event.v1` is no longer single-producer.** Phase 6 §6.4 boundary test asserted `drift.v1` as the sole producer "in v1"; Phase 7 expands the producer set to `{drift.v1, ops_console}` (the latter is the Phase 8 maint surface). The §6.4 test must be loosened to assert producers ⊆ a configured allow-list rather than equals `{drift.v1}` — this loosening lands in the same PR as Phase 7.3, not deferred to Phase 8 (Phase 8 just adds the producer; the contract change belongs to whichever phase first needs the second producer, which is Phase 7 via this consumer hook).
- [x] **Single-instance.** `sec.rate.v1` joins `SINGLE_INSTANCE_AGENTS` (per pre-Phase-7 audit M1's frozenset contract) because it is the sole writer of the denylist hash and the sole publisher of `sec.denylist.v1`. Multi-replica coordination needs Postgres-backed leader election (Phase 14.x follow-up).

### 7.4 `sec.alert.v1` envelope and severity ladder

- [x] **Schema** (`ai/swarm/sdk/schemas/sec.alert.v1.json`). Fields: `{alert_id, kind ∈ SecAlertKind, severity ∈ {info, warn, error, critical}, source ∈ {sec.input.v1, sec.scrape.v1, sec.rate.v1}, subject?, request_id?, client_id?, ip?, evidence_ref?, reason, produced_at}`. `evidence_ref` is a pointer (sha256 + blob URI) into `sec.quarantine.v1` payloads — the alert never inlines the offending bytes (cardinality + log-injection guard).
- [x] **`SecAlertKind` open-enum for forward compatibility.** JSON Schema closed enums break older consumers when a new kind lands; Phase 7's wire contract uses an **open enum** pattern: `{"kind": {"type": "string", "x-enum": [...known kinds...], "pattern": "^[a-z][a-z0-9_]{0,63}$"}}`. Producers MUST emit only known kinds; consumers MUST accept unknown kinds and fall back to `severity` for routing. Same pattern reused by `MaintEventKind` (Phase 6/8) and any open enum the system adds later. Documented once, referenced from each schema. **Test convention (binding — `x-enum` is non-standard, validators ignore it).** Every open-enum field gets two tests: (a) `test_open_enum_producers_emit_only_known_kinds` enumerates every emission site by AST scan + asserts the literal value is in the `x-enum` list (catches typos at landing time — the JSON Schema validator will *not*); (b) `test_open_enum_consumers_accept_unknown_kind` round-trips an envelope with `kind="future_unknown_kind_v999"` through every consumer and asserts no `KeyError` / `ValueError` / dropped message. Helper lives in `ai/swarm/sdk/schemas/open_enum.py` and the two tests are parametrized over the registered open-enum field set.
- [x] **Known kinds (v1 set, additions are minor bumps).** From `sec.input.v1`: `prompt_injection`, `payload_oversize`, `charset_anomaly`, `language_spoof`, `homoglyph_attack`, `classifier_degraded`, `classifier_load_shed`, `pattern_reload`. From `sec.scrape.v1`: `dom_size_delta`, `suspicious_js`, `encoded_redirect`, `content_type_mismatch`, `inflate_ratio_outlier`, `seed_drift`, `baseline_warmup`, `baseline_reset`. From `sec.rate.v1`: `rate_burst`, `rate_throttled`, `rate_redis_degraded`, `rate_script_reloaded`, `denylist_added`, `denylist_removed`, `denylist_growth_anomaly`, `subject_map_churn`.
- [x] **Generalized debounce contract.** Every `sec.alert.v1` kind has a per-`(kind, subject)` debounce TTL `cfg.sec_alert_debounce_ttl_s` (default 60 s). During the TTL, repeated triggers increment an in-process `suppressed_count` and the next emission after TTL expiry carries `reason="<original> (suppressed: <N>)"`. Without this, a burst attack produces an alert storm that drowns operator dashboards (the same anti-pattern Phase 6 `drift.v1._tripped` already solved for retrain events). Severity-`critical` kinds bypass debounce by default (operator-paging events should always page); knob `cfg.sec_alert_critical_debounce_enabled` (default false) flips this for noisy environments.
- [x] **Severity ladder.** `info`: observable, no action (e.g. `denylist_added` for a known-bad IP, `pattern_reload`, `baseline_warmup`). `warn`: human review during business hours (e.g. `classifier_degraded`). `error`: alert on-call (e.g. `dom_size_delta` from a real upstream, `rate_redis_degraded`). `critical`: page (e.g. `seed_drift` in CI — supply-chain signal; `denylist_growth_anomaly` — active attack). The Phase 4.6 telemetry agent counts alerts by `(kind, severity)` and surfaces them on the Prometheus page; cardinality is bounded by the **known-kinds** set (unknown-kind counters fold into a single `negelir_sec_alerts_unknown_kind_total{severity}` to keep cardinality bounded under the open-enum contract).

### 7.5 Topic catalog additions

To be added to Phase 3 §3.5 in lock-step with this phase. Every row lands with (a) a JSON Schema in `ai/swarm/sdk/schemas/<topic>.json`; (b) for control-plane (unversioned) topics, the schema carries the C2 marker `"comment": "control-plane: unversioned by design (ROADMAP §3.7)"` per the pre-Phase-7 audit cleanup.

| Topic | Plane | Producer | Consumer(s) | Payload |
|---|---|---|---|---|
| `qa.request` | control | API gateway (raw, post-deterministic-rules-with-verdict=sanitize-or-escalate) | `sec.input.v1` | `{request_id, raw_text, client_id?, ip, locale, received_at}` (control-plane, unversioned, C2 marker required) |
| `qa.request.v1` | data | API gateway (verdict=pass on deterministic rules) **OR** `sec.input.v1` (verdict=pass post-classifier) — exactly one publisher per `request_id`; the gateway path and the agent path are **mutually exclusive** by construction (gateway publishes only on `pass`; on `sanitize`/`escalate` it publishes raw `qa.request` and the agent owns the v1 emission) | NLP layer (Phase 10) | `{request_id, sanitized_text, client_id?, locale, sec_verdict ∈ {pass, sanitized}, sec_steps_run[], emitted_at}` |
| `sec.alert.v1` | data | `sec.input.v1`, `sec.scrape.v1`, `sec.rate.v1` (open producer set within `sec.*` only) | telemetry, supervisor, ops dashboards | per §7.4 |
| `sec.quarantine.v1` | data | `sec.input.v1` (QA path), `sec.scrape.v1` (scrape path) | `storage.v1` (persists to `quarantine_samples`) | per §7.1 |
| `sec.denylist.v1` | data | `sec.rate.v1` (SOLE producer) | API gateway cache, telemetry | per §7.3 |

**Cross-language schema parity (binding).** `qa.request.v1` has two language producers (Go gateway + Python agent). To keep them from drifting, the schema lives in `ai/swarm/sdk/schemas/qa.request.v1.json` and the Go gateway loads it at start (`server/internal/sec/schemas/`) via a `go:embed` of the same JSON file (symlink or generated copy enforced by `make verify.schemas`). Contract test `server/internal/sec/input_test.go::TestQARequestV1MatchesPythonSchema` parses the embedded schema and asserts every field name + type matches the Python `payloads.QaRequestV1` dataclass. Without this, the two producers WILL drift the first time someone adds a field to one side only.

**Bus-level dedup for mutually-exclusive producers (binding for `qa.request.v1`).** "Exactly one publisher per `request_id`" is a producer-side promise; under Redis Streams at-least-once semantics, gateway crashes between publish and ack can replay. The NLP layer (Phase 10) MUST dedup by `request_id` over a sliding window of `cfg.qa_request_v1_dedup_window_s` (default 300, comfortably larger than the SDK retry budget * max attempts). Storage on the dedup is a bounded Redis SET (`qa:dedup:{shard}` with TTL = window) sized by request rate * window; cardinality bounded by the rate limiter (§7.3) so it cannot grow without bound. Boundary test (§7.6) replays the same `request_id` with both gateway-pass and agent-pass envelopes, asserts NLP processes exactly once.

**Backpressure on `sec.quarantine.v1` (storage is single-instance).** Per the pre-Phase-7 audit M1 fix, `storage.v1` is in `SINGLE_INSTANCE_AGENTS`; under a quarantine burst (e.g., a coordinated injection campaign) the storage consumer can fall behind. Producer-side guard: each sec agent buffers pending quarantine writes in a bounded queue `cfg.sec_quarantine_producer_queue_max` (default 1000); on overflow, the **oldest** quarantine sample is dropped (drop-oldest, not drop-newest — the most recent payloads are the freshest forensic evidence) and `sec.alert.v1{kind=quarantine_overflow, severity=error}` (debounced, joins the §7.4 known-kinds set) fires. Consumer-side guard: `storage.v1`'s consumer-group lag for the `sec.quarantine.v1` stream is exposed as a Phase 4.6 telemetry counter; lag > `cfg.sec_quarantine_storage_lag_alert_ms` (default 5000) trips `sec.alert.v1{kind=quarantine_storage_slow, severity=error}`. The Phase 16 emitter migration removes the bus pin entirely (already in §7 forward contracts).

The legacy `sec.alert` row (unversioned, `{kind, source, severity}`) is **removed** — it is replaced by `sec.alert.v1` above. No code references the old name yet (it was a forward placeholder added in Phase 3); the Phase 7 landing PR removes the row.

### 7.6 Boundary discipline

`ai/swarm/agents/tests/test_boundary_discipline.py` extensions (mirrors the Phase 6 §6.4 boundary tests):

- [x] `qa.request.v1` has at most two producers (`server.gateway` + `sec.input.v1`) and exactly one consumer (NLP, Phase 10 placeholder until then).
- [x] `sec.denylist.v1` has exactly one producer (`sec.rate.v1`).
- [x] `sec.quarantine.v1` consumer set is `{storage.v1}` only (no predictor / NLP / proofreader subscriber).
- [x] `sec.input.v1` and `sec.scrape.v1` **do not** publish `proof.flag` (the two taxonomies are disjoint per §7 forward contracts).
- [x] `sec.scrape.v1` does **not** consume `proof.flag` (no rebound on Phase 4.1 failures).
- [x] NLP layer (Phase 10) does **not** subscribe to `qa.request` (raw).
- [x] `sec.rate.v1` is the only writer of the Redis `sec:denylist:*` keys (Lua-script audit + integration test against `RedisStreamsBus` profile). *(Closed: AST scan in `test_boundary_discipline.py::test_sec_denylist_v1_no_unauthorised_writer_in_registry` plus live-Redis integration in `ai/swarm/agents/tests/test_phase7_lua_redis.py` exercising `sec_denylist_mutate.lua` add/remove/cap/refresh-not-stack semantics.)*
- [x] **No publisher emits both `qa.request` AND `qa.request.v1` for the same `request_id`** (mutually-exclusive producer paths per §7.5). Idempotency test: replaying a `qa.request` with `verdict=pass` from the agent does not double-publish `qa.request.v1`.
- [x] **XFF derivation correctness.** Unit test in `server/internal/sec/rate_test.go` worked-example asserts the right-most-untrusted derivation against `cfg.sec_rate_trusted_proxies` for: (a) empty trusted list → TCP peer always wins; (b) single trusted proxy → spoofed left entries are ignored; (c) chained trusted proxies → the right-most untrusted hop is selected. *(Closed: `server/internal/sec/xff_test.go::TestDeriveClientIP*` — empty list → TCP peer; trusted hop walked right-to-left and skipped; malformed hop tolerated; all-trusted falls back to TCP peer.)*
- [x] **IPv6 prefix bucketing.** Test that two requests from `2001:db8::1` and `2001:db8::ffff` (same `/64`) share a bucket; requests from `2001:db8:1::1` and `2001:db8:2::1` (different `/64`) do not. *(Closed: `server/internal/sec/xff_test.go::TestSubjectKeyIPv6PrefixCollapse` + `TestSubjectKeyIPv6DifferentSubnetsDoNotCollide`.)*
- [x] **Password field bypasses normalization.** Per §7.1 auth-endpoint scope: a known non-NFC password reaches `auth.Verify` byte-identical to the request body; no quarantine row carries the password substring; the email field still goes through the full pipeline. *(Closed at the library tier: `server/internal/sec/input_test.go::TestPasswordFieldBypassesNormalization` — `QAInputGate.PasswordPasses` runs zero transforms (`StepsRun` empty), returns the bytes unchanged, and `TestPasswordFieldNeverPatternMatches` confirms no quarantine row will carry the password substring even when it textually matches an injection rule. Length-cap defense against bcrypt-bombs is preserved by `TestPasswordFieldStillEnforcesLengthCap`. End-to-end auth-endpoint wiring lands with the Phase 9 router.)*
- [x] **`qa.request.v1` consumer-side dedup.** Replay the same `request_id` with both gateway-pass and agent-pass envelopes; assert NLP (Phase 10 stub until then) sees exactly one event. *(Closed: `swarm.sdk.RequestIdDeduper` (`ai/swarm/sdk/dedup.py`) — sliding-window LRU on monotonic clock with bounded `max_keys`. Five tests in `test_phase7_completion.py`: dedup-within-window, age-out, LRU eviction, malformed-id safety, gateway+agent dual-publish collapse.)*
- [x] **`sec.quarantine.v1` overflow drops oldest.** Fill the producer-side queue past `cfg.sec_quarantine_producer_queue_max`; assert the oldest sample is dropped (not the newest), `sec.alert.v1{kind=quarantine_overflow}` fires (debounced), and the counter increments. *(Closed: `test_phase7_completion.py::test_quarantine_overflow_evicts_oldest_tracking_entries_not_wire` — asserts every quarantine still reaches the wire (drop-from-tracking, never drop-from-publication, per §7.5 fresh-evidence doctrine) and that entries age out of the producer-side deque after `sec_quarantine_storage_lag_alert_ms`.)*
- [x] **`maint.event.v1` producer set is bounded by allow-list, not single.** Producers ⊆ `{drift.v1, ops_console}` (the Phase 6 §6.4 "single producer" assertion is loosened in this phase per §7.3 cross-phase note). *(Closed: `test_phase7_completion.py::test_maint_event_v1_producer_set_is_bounded_by_allow_list` enumerates `bootstrap.build_agents()` and asserts every `maint.event.v1` producer is a member of `swarm.sdk.wire_contracts.MAINT_EVENT_V1_ALLOWED_PRODUCERS`. Sanity test asserts the allow-list always includes `drift.v1` + `ops_console` so the retrain channel can never be silently muted.)*
- [x] **Lua script sha pin.** Gateway refuses to start if `SCRIPT LOAD` returns a sha that disagrees with the `-- SHA256:` header in `sec_rate_check.lua`. `make verify.lua` is the canonical regenerator; CI gate fails on header drift. *(Closed on the Python side: `xops/makefile/lua.py` (`make verify.lua` / `make fix.lua`) regenerates and CI gates the `-- SHA256:` headers; `test_phase7_lua_scripts.py` asserts header presence + recompute parity; `test_phase7_lua_redis.py::test_lua_sha_matches_pinned_header` additionally re-verifies the running Redis's EVALSHA matches a fresh SHA1 over the source. Gateway-side refuse-to-start enforcement lives with the Go middleware (Bucket B / §7.8).)*
- [x] **Endpoint cost mapping is total.** Every route registered with the gateway router has an entry in `cfg.sec_rate_endpoint_costs`; routes without an explicit entry are charged `sec_rate_default_cost` and the test asserts no route is silently free. *(Closed at the library tier: `server/internal/sec/costs.go::EndpointCostMap.CheckTotality` reports any router pattern lacking an explicit entry; `costs_test.go::TestCheckTotalityFlagsSilentFreeRoutes` is the assertion. Phase 9 router wiring calls `CheckTotality(router.Routes(), allowFallback=[])` at boot and refuses to start on non-empty result. Canonical entries live in `ai/common/security/endpoint_costs.yaml` (embedded by Go via `server/internal/sec/embedded/`).)*

### 7.7 Definition of Done

- [x] All four pre-Phase-7 audit MAJORs (M1–M4 in [`docs/reports/phase4-to-6-pre-phase7.md`](../reports/phase4-to-6-pre-phase7.md)) shipped — `SINGLE_INSTANCE_AGENTS` includes `storage.v1`, monotonic clocks across consensus / aggregator, `_fuse_score_grids` shape guard, `proof.flag.detail` capped at 1 KB. `sec.rate.v1` builds on the monotonic-clock convention from day one.
- [x] Three default sec agents (`sec.input.v1`, `sec.scrape.v1`, `sec.rate.v1`) implemented + voting against `InMemoryBus` through `AgentRunner`. Each lives under `ai/swarm/agents/sec/` (mirrors the Phase 6 `proofreader/` package layout).
- [~] Go gateway middleware (`server/internal/sec/input.go`, `server/internal/sec/rate.go`) implements the in-process tier; integration test against the gateway + Redis confirms median QA latency stays under `cfg.sec_input_gateway_max_latency_ms` for benign payloads. *(Library tier closed: full `server/internal/sec/` package shipped — `sanitize.go` (NFC + control / zero-width strip mirroring `ai/swarm/agents/sec/input.py::sanitize_text`), `patterns.go` (RE2 compiler over `injection_patterns.yaml`), `xff.go` (right-most-untrusted derivation + IPv6 /64 bucketing), `costs.go` (endpoint cost map + totality check), `lua.go` (header SHA256 verifier + SCRIPT LOAD deploy-skew gate), `input.go` (`QAInputGate` length cap + sanitize + pattern + password-field carve-out), `rate.go` (`SecondaryBucket` fail-open in-process GCRA tier). Deterministic-path latency asserted in `latency_test.go::TestDeterministicPathLatencyUnderSLO` (≈15µs/op vs 12.5ms budget on CI). End-to-end gateway+Redis integration test waits for Phase 9 router wiring of the `/v1/qa` + `/v1/auth/*` routes.)*
- [x] **Fail-open doctrine.** No defense agent ever blocks the **happy path** in CI's golden-input suite (200+ benign Turkish queries from [`ai/tests/fixtures/turkish_queries.yaml`](../../ai/tests/fixtures/turkish_queries.yaml), Phase 10) — explicit negative test: kill `sec.input.v1`, run the golden suite, expect 0 quarantines and ≤ N `classifier_degraded` warns where N = ceil(suite_size / cfg.sec_input_breaker_open_s). *(Closed via `test_phase7_completion.py`: 4 tests against an inline benign-Turkish corpus — zero quarantines, every benign query produces a `qa.request.v1` (no silent drop), `classifier_degraded` debounce keys on subject (one alert per distinct user, single-subject burst collapses to one). Full Phase 10 corpus + `turkish_queries.yaml` fixture lands with NLP.)*
- [x] **Idempotency.** Each sec agent's handler is idempotent under at-least-once redelivery: re-publishing the same `request_id` does not double-add to the denylist, double-quarantine, or double-emit `sec.alert.v1` (regression tests mirror the Phase 6 `test_phase6_bug_fixes.py` style). *(Closed: `sec.input.v1` — `test_sec_input_idempotent_on_redelivery`; `sec.rate.v1` — `test_sec_rate_dedup_on_redelivered_alerts`; `sec.scrape.v1` — `test_sec_scrape_idempotent_under_intra_source_replay_in_one_step` and `test_sec_scrape_idempotent_under_replay_after_window_advance` (content-addressed dedup outlives arbitrary clock skew). Plus the deduper-level coverage from the `RequestIdDeduper` tests above.)*
- [x] **Bounded state.** Every in-process map is config-capped with insertion-order LRU eviction (mirror Phase 5 `consensus.v1` and Phase 6 `drift.v1` patterns). Overflow eviction emits `sec.alert.v1{kind=…, severity=warn}` outside the lock.
- [x] **Schema parity.** Every Phase 7 message validates against its JSON Schema at the live emission point (`test_schemas_match_payloads.py` extension + live-emission probes in a new `test_phase7_bug_fixes.py`). *(Closed: `test_phase7_completion.py` ships four live-emission probes — `sec.input.v1` pass-path, `sec.input.v1` quarantine-path, `sec.scrape.v1` warmup + normal sample, `sec.rate.v1` burst trip — each running the agent end-to-end and validating every emitted `Message.payload` via `swarm.sdk.schemas.validate(topic, payload)`. Hand-crafted `_example_*()` parity in `test_schemas_match_payloads.py` remains as belt-and-braces.)*
- [x] **Boundary tests** (§7.6) all green.
- [x] **swarmctl visibility.** Every Phase 7 agent appears in `swarmctl ps`; every Phase 7 topic appears in `swarmctl topics`. Guard: `test_phase7_agents_register_for_swarmctl_ps` + `test_phase7_topics_are_known_to_the_bus_schema_layer` in `ai/swarm/agents/tests/test_phase7_visibility_and_lua_parity.py` assert the in-memory equivalents of the Redis surfaces `swarmctl` reads (`AgentRegistry.all_specs()` ↔ `agent_registry` HGETALL; SDK `known_topics()` ↔ stream-key catalog).
- [x] **Telemetry watch set** extended (per cross-phase alignment above); regression test mirrors `test_telemetry_watches_phase6_proofreader_drift_topics`.
- [x] **Phase 12 catalogue stubs.** Every check listed in §7.1 / §7.2 / §7.3 has a corresponding *stub* row in `docs/testing/phase12_catalogue.md` (one row per check, body = "TBD — implementation pending Phase 12"). The stubs satisfy the original Phase 7.4 DoD bullet without requiring Phase 12 to land first; the bullet flips to fully green when Phase 12 fills the bodies in.
- [x] **Config triangle green.** All Phase 7 knobs surface in `xops/env/.env.example`, `ai/common/defaults.yaml`, and `ai/common/config.py` — `test_config_sync` stays green. Knob inventory: `sec_input_max_len`, `sec_input_gateway_max_latency_ms`, `sec_input_classifier_max_latency_ms`, `sec_input_classifier_device`, `sec_input_classifier_path`, `sec_input_classifier_batch_enabled`, `sec_input_classifier_batch_size`, `sec_input_classifier_batch_window_ms`, `sec_input_classifier_max_pending`, `sec_input_breaker_open_s`, `sec_input_pattern_reload_s`, `sec_quarantine_ttl_days`, `sec_quarantine_payload_max_bytes`, `sec_quarantine_producer_queue_max`, `sec_quarantine_storage_lag_alert_ms`, `sec_scrape_size_delta_pct`, `sec_scrape_inflate_ratio_max`, `sec_scrape_warmup_samples`, `sec_scrape_baseline_flush_s`, `sec_scrape_max_pending`, `sec_scrape_simhash_max_distance`, `sec_scrape_dom_fingerprint_max_nodes`, `sec_rate_pre_auth_capacity`, `sec_rate_pre_auth_refill_per_s`, `sec_rate_post_auth_capacity`, `sec_rate_post_auth_refill_per_s`, `sec_rate_bucket_idle_ttl_s`, `sec_rate_max_subjects`, `sec_rate_ipv4_prefix`, `sec_rate_ipv6_prefix`, `sec_rate_trusted_proxies`, `sec_rate_redis_timeout_ms`, `sec_rate_secondary_capacity`, `sec_rate_secondary_refill_per_s`, `sec_rate_default_cost`, `sec_rate_eviction_rate_alert_per_s`, `sec_rate_eviction_rate_window_s`, `sec_burst_threshold`, `sec_burst_window_ms`, `sec_burst_dedup_window`, `sec_denylist_ttl_s`, `sec_denylist_escalation_factor`, `sec_denylist_max_entries`, `sec_alert_debounce_ttl_s`, `sec_alert_critical_debounce_enabled`, `qa_request_v1_dedup_window_s`. (The earlier `sec_scrape_baseline_max_per_source` knob is retired — the streaming-statistic baseline replaces the capped LRU; absence of the knob is asserted in `test_config_sync` so it cannot creep back.)
- [x] **Lua-script CI gate.** `make verify.lua` recomputes the `-- SHA256:` header for every script under `infra/redis/lua/`; CI fails on drift. Integration test (`test_phase7_lua_redis.py`) loads `sec_rate_check.lua` into a containerized Redis and asserts behavioural correctness; the deterministic Python GCRA reference (`test_phase7_visibility_and_lua_parity.py::_python_reference_rate_check`) drives 1000 deterministic `(capacity, refill, cost, elapsed_ms)` tuples (seed=1337) with byte-for-byte allow/throttle parity, plus an optional skip-if-no-redis live parity sweep that drives the same corpus through both implementations and asserts status-enum agreement. Denylist short-circuit (including the PTTL=-2 race) is asserted against both the reference and the live script.
- [x] **`maint.event.v1` producer-set relaxation.** Phase 6 §6.4 boundary test for `maint.event.v1` is loosened from `producers == {drift.v1}` to `producers ⊆ maint_event_v1_allowed_producers`; the allow-list (`{drift.v1, ops_console}` after Phase 7 lands) lives in `ai/swarm/sdk/wire_contracts.py`. Tracker row + `swarm` minor bump cite the relaxation.
- [x] **Versioning.** `swarm` minor bump at the Phase 7 landing; `server` minor bump for the Go gateway middleware; subsequent Phase 7 review patches bump `swarm` / `server` patch-level. *(Closed: `swarm 0.20.x → 0.21.0` at the Phase 7 landing; `server 1.4.1 → 1.5.0` at the Bucket B Go library landing; `swarm 0.21.0 → 0.22.0` at this final closure landing (streaming-statistic baseline + denylist cardinality cap evidence). Subsequent Phase 7.x review work bumps patch-level per §6.1 doctrine.)*
- [x] **Migrations.** `migrations/007_quarantine.sql` (the `quarantine_samples` table, including the `erased_at` PII-erasure column per §7.1) and `migrations/008_source_fingerprints.sql` (streaming-statistic baseline state, **not** raw samples — schema carries serialized Welford / P² / count-min state per source) land with this phase; both are additive (no `DROP`). **Migration-numbering reservation:** Phase 9 migrations start at `009_*` (the user / tier / auth tables); Phase 10 NLP starts at `011_*` (`010` is reserved for Phase 9.x follow-ups). Documented in [`migrations/README.md`](../../migrations/) so future phases don't collide.

### 7.8 Pivot v3 alignment & follow-ups

- [ ] **Per-league burst multiplier.** Phase 13a per-league overrides via `LeagueConfig.sec_burst_multiplier`; `sec.rate.v1` resolves the multiplier from JWT preferred-league claim or the request's `league_id`. Until then, the global threshold is the right default.
- [ ] **Quarantine → feeds plane.** Phase 16 emitter migration of `sec.quarantine.v1` to `feeds/sec_quarantine.v1.parquet` — keeps long-tail forensic storage off the bus. The `QuarantineSample` dataclass already maps 1:1 to the parquet row.
- [ ] **Denylist leader election.** Multi-replica `sec.rate.v1` requires Postgres-backed leader election (Phase 14.x); single replica is the v1 invariant.
- [ ] **Sec.input classifier promotion.** v1 ships a deterministic-only fallback (no classifier on disk). The first labelled-corpus drop (Phase 13 lexicon work) unlocks the small classifier; until then, `sec_input_classifier_path` defaults to empty and the agent skips step 5 (verdict short-circuits to `pass` on rule-inconclusive payloads, with a `sec.alert.v1{severity=info}` for visibility — fail-open consistent with §7.7).
- [ ] **False-positive feedback loop (deferred to Phase 8.x).** When an operator clears a quarantined sample (`maint.event.v1{kind=quarantine_clear}`), the deterministic rule-id that triggered it should auto-add to a per-source allowlist with a TTL (operator-tunable). v1 does not auto-learn — every clear is a manual edit to `injection_patterns.yaml`. The Phase 8 maint command exists at landing but the auto-learn loop is gated behind `cfg.sec_input_pattern_autolearn_enabled` (default false) until Phase 13 lexicon work provides a labelled-negative corpus to validate suppressions against.
- [ ] **WAF bypass parity.** SECURITY.md explicitly excludes a WAF; if a deploy adds one (cloud profile), the gateway middleware must continue to enforce all checks (defense-in-depth) — covered by an integration test that runs the gateway with `SEC_ASSUME_UPSTREAM_WAF=true` and confirms quarantine still fires.
- [ ] **SECURITY.md sync.** This phase's revisions (IPv6 prefix bucketing, XFF trust boundary, denylist cardinality cap, baseline warm-up, streaming-statistic baseline, generalized alert debounce, open-enum pattern, pattern hot-reload, gateway secondary bucket, PII-erasure path, defense-in-depth contract) land as a SECURITY.md update **in the same PR** as this ROADMAP revision so the design doc and the plan stay in lock-step (the existing `Defense agents (Phase 7 detail)` section currently lags the ROADMAP). Tracked by a single `make track.add` row at landing.

---

## 🔧 Phase 8 — Self-Maintenance Agents (Ops Console, Auto-Scaler, Backup, DLQ Supervisor, Watcher Graduation)

**Goal:** Close the operational loop. Every Phase 6/7 maint hook (denylist clear, baseline reset, quarantine erase, retrain request, DLQ depth, replica scaling) gains a *publisher* and a *consumer* so the system runs unattended for the boring stuff — without ever touching scraper code (that is Phase 17 patcher's exclusive remit) and without ever auto-mutating predictors (humans gate that via `maint.event.v1{kind=retrain_approve}` in v1).

**Depends on:** Phase 4 (storage + reactor base), Phase 6 (drift events + ledger), Phase 7 (sec.alert + Lua denylist + quarantine plane).

**Pivot v3 placement:** maintenance agents live under `swarm/reactors/maint/` per [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) (write-side reactors, not predictors and not data-plane). Until Phase R2 lands the directory move, ship under the transitional path **`ai/swarm/agents/maint/`**, importable as `swarm.agents.maint.*` (matches Phase 4/5/6/7 layout — R2 is a `git mv`, not a rewrite). The **ops console** publisher (§8.1) lives at `xops/opsctl/` (a stdlib-only CLI, no swarm runtime — it publishes to the bus and exits) so an operator can use it on a host with no Python venv beyond what `xops/` already requires.

**Scope discipline (binding):**

- **Phase 8 agents are reactors, not data sources and not predictors.** They consume events emitted by Phase 6/7/4 and either (a) re-publish a control message on `maint.event.v1`, (b) call out to the runtime control plane (`docker compose --scale` / Kubernetes `Scale` subresource), or (c) touch Postgres in narrowly scoped, pre-approved ways (TTL prune, PII erase, dump + restore-verify, snapshot vacuum).
- **Phase 8 never edits scraper code or selectors.** The original §8.1 "schema-healer" auto-derived `scraper/selectors.json` from seed corpora — that responsibility moved to **`datasource/patcher/`** under Phase 17 ([`design/SCRAPER_PATCHER.md`](../design/SCRAPER_PATCHER.md)) when the Anthropic-Agent-SDK harness was locked (Decision A15). Phase 8 §8.6 keeps the *internal* schema-drift sentinel (Postgres column drift vs migrations, JSON Schema vs payload drift) — that is a different surface and stays here.
- **Phase 8 never auto-merges code.** Even the source-watcher LLM summarizer graduation (§8.4) only ever *narrates* what the deterministic differ already decided. The summarizer cannot override classifications; the §2.8 boundary test stays green.
- **Phase 8 never trains models.** Trainer is the consumer of `maint.event.v1{kind=retrain_request}` (Phase 6 emits, Phase 5/9 trainer consumes). Auto-scaler may *schedule* a trainer pod / cron run but never pulls the trigger on weights.

**Cross-phase alignment (binding):**

- **Phase 3 §3.2 SDK contract.** Every Phase 8 agent is an `Agent` (registers in `agent_registry`, heartbeats per `cfg.swarm_heartbeat_sec`, declares `subscribes`/`publishes`, deregisters on `SIGTERM`). Inherits `AgentRunner` retry/DLQ. Visible in `swarmctl ps` and `swarmctl topics` (Phase 3.4 contract preserved).
- **Phase 3 §3.3 bus semantics.** All Phase 8 handlers are **idempotent**:
  - Scaler keys on `(target_agent, desired_replicas, decision_window_id)` — replays of the same window do not re-issue scale calls.
  - Backup keys on `(job_id, backup_date_utc)` — re-running today's nightly dump is a no-op unless `--force`.
  - DLQ supervisor keys on `(topic, dlq_entry_id)` — replaying a DLQ entry that the original consumer already accepted is dropped via the Phase 4.7 `Ledger` Protocol.
  - Schema-drift sentinel keys on `(table, column_set_fingerprint)`.
- **Phase 3 §3.5 topic catalog (wire authority).** Phase 8 lands no new topics — `maint.event.v1` and `maint.dlq.v1` already exist. New `maint.event.v1.kind` values join the open-enum allow-list (§7.4 pattern):
  `retrain_approve`, `scale_decision`, `scale_throttled`, `backup_started`, `backup_completed`, `backup_verify_failed`, `quarantine_pruned`, `dlq_replayed`, `dlq_escalated`, `schema_drift_detected`, `pattern_allowlist_added`, `pattern_allowlist_expired`, `denylist_decimate`, `pii_erased`. The §7.4 producer-set allow-list is widened from `{drift.v1, ops_console}` to `{drift.v1, ops_console, maint.scaler.v1, maint.backup.v1, maint.dlq.v1, maint.schema.v1, maint.sec.v1, source_watcher}` — boundary test in `test_boundary_discipline.py` is loosened in the same PR as §8.0 lands, exactly as Phase 7 loosened it for `ops_console`.
- **Phase 4.5 / 4.7 storage + reactor base.** Backup (§8.3) reads from the same Postgres that `storage.v1` writes to; it never goes through the bus for table reads. Reactor base supplies retry/backoff and the `Ledger` Protocol used by the DLQ supervisor (§8.5).
- **Phase 6 `drift.v1`.** Already emits `maint.event.v1{kind=retrain_request}`. Phase 8 §8.2 scaler consumes the same kind to *prepare capacity* (warm a trainer pod, raise predictor replicas before retrain bursts) but does **not** start training — the trainer is the action-of-record. A Phase 8 manual override `kind=retrain_approve` carries `target=<predictor_id>` and `request_id=<drift_event_request_id>` so the trainer can correlate.
- **Phase 7 §7.4 SecAlertDebouncer + open-enum.** All Phase 8 alerts (`backup_verify_failed`, `dlq_escalated`, `schema_drift_detected`, `scale_throttled`) emit on `sec.alert.v1` with severities `info|warn|error|critical` and are **debounced per subject** through the existing `SecAlertDebouncer`. The §7.4 known-kinds set is extended in lock-step. Critical alerts (e.g. `backup_verify_failed`) bypass debounce per the §7.4 default.
- **Phase 7 §7.6 sec.rate.v1 sole-writer.** §8.1 ops console publishes `maint.event.v1{kind=denylist_clear}` — it does **not** publish `sec.denylist.v1` directly. The boundary test that pins `sec.rate.v1` as the sole `sec.denylist.v1` producer stays green; ops console only ever talks through the existing operator-override hook.
- **Phase 7 §7.3 denylist cardinality cap.** §8.8 sweeper consumes `sec.alert.v1{kind=denylist_growth_anomaly}` and runs the deferred "halve TTL of oldest decile" via a new Lua script `sec_denylist_decimate.lua` (versioned + SHA-pinned exactly like the existing two scripts; CI gate `make verify.lua` covers it). Decimation publishes `maint.event.v1{kind=denylist_decimate, target=<source>, decile_size, evicted_count}` for audit.
- **Phase 7 §7.5 quarantine TTL.** §8.3 backup agent owns the `quarantine_samples` TTL prune (`cfg.sec_quarantine_ttl_days`, default 30) and the `kind=quarantine_erase` PII path. Both go through the same nightly job — single audit trail, single failure mode.
- **Phase 2.8 source-watcher.** Migrates from cron-driven standalone to the SDK in §8.4. The `summarizer.py` stub flips `enabled=True` only when `cfg.source_watcher_summarizer_enabled=true` AND a valid model pin is configured (no `*-latest` IDs per CLAUDE.md doctrine). The deterministic differ + classifier remain authoritative; the summarizer may not change a classification (boundary test in `ai/swarm/source_watcher/tests/` already enforces; extended in §8.4).

**Forward-phase contracts (binding):**

- **Phase 9 API surface.** No Phase 8 agent exposes an HTTP endpoint. The ops console publishes to the bus; the operator authenticates against the Go API in Phase 9 (when admin endpoints land at `/v1/admin/maint/*` proxied to the same `maint.event.v1` topic). Until Phase 9, ops console runs locally and authenticates via filesystem (Unix-socket Postgres + bus auth from the Phase 2 internal CA). The `maint.event.v1` envelope already carries `client_id` so the Phase 9 admin handler attributes events.
- **Phase 11 compute.** Auto-scaler honors `cfg.predictor_max_vram_mb` and the device-probe priority (CUDA→ROCm→NPU→CPU). Scaling a predictor to `replicas: N+1` when GPU memory accounting projects an OOM is rejected with `kind=scale_throttled, reason=vram_budget_exceeded` and a debounced `sec.alert.v1{kind=scale_throttled, severity=warn}`.
- **Phase 12 chaos.** `make chaos-fill-dlq TOPIC=predict.vote N=5000` must be drained by §8.5 within `cfg.maint_dlq_drain_window_ms` or trip `sec.alert.v1{kind=dlq_escalated, severity=error}`. `make chaos-flap-replicas AGENT=consensus.v1` must be damped by the §8.2 hysteresis (the scaler does **not** issue back-to-back `scale_decision` events within `cfg.maint_scaler_min_decision_interval_s`). Phase 12 owns the assertions; Phase 8 owns the surfaces. Cross-phase circular-dep policy mirrors Phase 7: until Phase 12 lands, the §8.9 DoD bullet that requires Phase-12-catalogue entries is satisfied by **stub rows** in `docs/testing/phase12_catalogue.md`.
- **Phase 13a CalibrationProfile.** Auto-scaler reads `(profile_id, market)` cardinality from `predictor_calibration` to size the predictor pool — high-fan-out leagues get more replicas. Until 13a, `profile_id == league_id` (matches Phase 5 default); no schema migration.
- **Phase 14 K8s.** Each Phase 8 agent runs at `replicas: 1` (single-publication for `scale_decision`, `backup_completed`, `dlq_replayed` requires it). Compose mode invokes `docker compose --scale <svc>=N`; K8s mode patches `apps/v1.Deployment.spec.replicas` via the in-cluster client. The runtime adapter is a `RuntimeController` Protocol (in-process compose runner today, K8s client at Phase 14) — the scaler code never changes across the two backends.
- **Phase 16 emitter.** Backup verifications and scale decisions stay on the bus (control plane); they do **not** move to feeds. The audit trail of nightly dumps is a CSV append at `data/backups/audit.csv` (operator-facing, not customer-facing). PII erase events emit a `maint.event.v1{kind=pii_erased, target=<client_id>, table, row_count, erased_at}` audit row that **does** persist in the `maint_audit_log` table (migration `009_maint_audit.sql`) — required for right-to-erasure traceability.
- **Phase 17 patcher.** Patcher's allow-list (`extractor`/`schema`/`migration`/`fixture`) and Phase 8's allow-list are **disjoint**. The §8.6 schema-drift sentinel detects drift and emits `maint.event.v1{kind=schema_drift_detected, target=<table>}`; humans then either edit the schema themselves or escalate to the patcher's `migration` scope. Phase 8 itself never invokes the patcher harness.
- **Phase 20 monetization.** None of the maint surfaces are tier-gated — backup, scaler, DLQ supervisor, and ops console are operator infrastructure, not user features. Per [`design/MONETIZATION.md`](../design/MONETIZATION.md) the gate is at the Go edge for `/v1/predictions/*`, never at maint.

### 8.1 Ops console (`ops_console` publisher of `maint.event.v1`)

> The single human-facing publisher for every Phase 6/7/8 maint hook. Lives at `xops/opsctl/` as a stdlib-only CLI; in Phase 9 the same payloads are exposed at `/v1/admin/maint/*`.

- [ ] CLI entry point `xops/opsctl/__main__.py` invoked via `make ops.<cmd>` shortcuts (`ops.denylist-clear`, `ops.baseline-reset`, `ops.quarantine-erase`, `ops.quarantine-clear`, `ops.retrain-approve`, `ops.scale`, `ops.backup-now`, `ops.dlq-replay`).
- [ ] Each subcommand:
  - Validates inputs locally (`target` is a known subject; `kind` is in the open-enum allow-list; `client_id` defaults to the OS username).
  - Constructs an `Envelope` with `request_id = uuid4()`, `produced_at = now_utc()`, `schema_version = 1`.
  - Publishes to `maint.event.v1` via the same `Bus` Protocol used by the runtime (Redis Streams in prod, `InMemoryBus` in tests).
  - Waits ≤ `cfg.opsctl_ack_timeout_ms` (default 5000) for an `ack` envelope on `maint.ack.v1` carrying the same `request_id`. Times out → exit code 2 + a stderr line.
- [ ] **Audit row.** Every successful publish appends to `data/maint/opsctl_audit.csv` (append-only, fsync per write, schema = `ts_utc, user, host, kind, target, request_id, ack_received_ms`). The same row is mirrored to `maint_audit_log` (Postgres) once Phase 9 lands.
- [ ] **No bypass channels.** The CLI must NOT write directly to Postgres or Redis state — it only publishes envelopes. Boundary test: AST scan of `xops/opsctl/**.py` rejects `psycopg`, `redis.client.Redis.set/del/hset/zadd`, anything that opens a connection outside the published `Bus` Protocol.
- [ ] **`maint.ack.v1` schema.** New JSON schema at `ai/swarm/sdk/schemas/maint.ack.v1.json` carrying `{request_id, accepted: bool, accepted_by: <agent_id>, reason?: str, processed_at: iso}`. Each consumer of `maint.event.v1` MUST publish exactly one `maint.ack.v1` per consumed `request_id` (boundary test).
- [ ] **Idempotency guard.** Re-running `ops.denylist-clear --target <ip>` for an already-cleared subject is a no-op at the consumer side and surfaces `ack.accepted=true, reason="already_cleared"` — never a hard error (operators muscle-memory re-run; the system tolerates it).

### 8.2 Auto-scaler agent (`maint.scaler.v1`)

> Continuous control loop: read telemetry, decide desired replica counts per agent, call the runtime controller, audit. Hysteresis everywhere.

- [ ] **Inputs:** the agent maintains a rolling `cfg.maint_scaler_window_s` (default 60s) sketch over telemetry counters Phase 4.6 already publishes — stream lag per topic, agent CPU%, predictor latency p95, DLQ depth, plus the Phase 7 `sec.alert.v1{kind=rate_burst, severity≥warn}` signal for API-frontend scale-up.
- [ ] **Decision function:** `desired_replicas = clamp(min_replicas, ceil(observed_load / cfg.maint_scaler_target_load_per_replica), cfg.maint_scaler_max_replicas[<agent>])`. Per-agent caps live in `cfg.maint_scaler_max_replicas` (dict, validated at boot — refuses to start if any registered agent is missing an entry, mirrors the Phase 7 §7.6 endpoint-cost totality test). **Hard global cap** `cfg.maint_scaler_global_max_replicas` (default 64) prevents runaway in cloud (Phase 14).
- [ ] **Hysteresis & flap damping.**
  - Min interval between decisions per `(agent, runtime)` = `cfg.maint_scaler_min_decision_interval_s` (default 90s). Decisions inside the window are coalesced (latest desired wins, no scale call issued).
  - Scale-down requires the proposed lower replica count to hold for ≥ `cfg.maint_scaler_scale_down_grace_s` (default 300s) of consecutive samples. Scale-up has no grace (capacity emergencies are not damped).
  - On every emitted decision, publish `maint.event.v1{kind=scale_decision, target=<agent>, prev=N, next=M, reason, observed: {...}, decision_window_id}` for audit. Reason is one of `{lag_high, lag_low, cpu_high, cpu_low, p95_high, dlq_depth_high, sec_rate_burst, vram_budget_exceeded}`.
  - Throttled decisions (cap hit, vram refused, runtime returned non-zero) emit `kind=scale_throttled` + `sec.alert.v1{kind=scale_throttled, severity=warn}` (debounced).
- [ ] **Single-publication of `scale_decision`.** Exactly one event per `decision_window_id` even under at-least-once redelivery from telemetry. Guarded by the Phase 4.7 `Ledger` Protocol (in-memory now, Postgres at Phase 9). `replicas: 1` enforced at Phase 14.
- [ ] **Runtime adapters.** `RuntimeController` Protocol with two implementations:
  - `ComposeController` — invokes `docker compose -f <compose_file> up -d --scale <svc>=N --no-recreate`. The compose file path comes from `cfg.maint_scaler_compose_file`. Subprocess run with `check=True`, captured stderr, 30s timeout.
  - `K8sController` (Phase 14) — uses `kubernetes.client.AppsV1Api.patch_namespaced_deployment_scale`. RBAC: a dedicated `maint-scaler` ServiceAccount with `patch` on `deployments/scale` only (least-privilege; the Phase 14 manifest pins this).
  - Both implementations enforce the §8.2 hard caps **after** the runtime call returns success (defense-in-depth — if a human bypassed the agent and over-scaled in compose, the next decision tick scales it back down, with a `kind=scale_throttled, reason=manual_override_detected` audit event).
- [ ] **VRAM accounting** for predictors. Before issuing a scale-up that crosses the VRAM budget (`cfg.predictor_max_vram_mb` × replica count vs probed device memory), refuse + emit `scale_throttled, reason=vram_budget_exceeded`. CPU-only fallback path is honored (Phase 11).
- [ ] **Drift-driven warm-up (consumer of `maint.event.v1{kind=retrain_request}`).** When drift fires, the scaler may pre-warm a trainer pod via a `kind=scale_decision, target=trainer.v1, prev=0, next=1, reason=retrain_request_warmup`. The trainer remains a separate workload — the scaler never publishes weights and never publishes `kind=retrain_approve`.
- [ ] **Observability.** Exposes counters `maint_scaler_decisions_total{agent,reason,outcome}` and a gauge `maint_scaler_desired_replicas{agent}` via the existing telemetry agent.

### 8.3 Backup / retention agent (`maint.backup.v1`)

> Nightly Postgres dumps + restore-verify + TTL prune for everything that has a TTL: quarantine samples, schema snapshots, drift windows on disk (Phase 9), DLQ entries, opsctl audit. PII erase is a sibling operation on the same trust path.

- [ ] **Nightly dump.**
  - Job runs at `cfg.maint_backup_cron` (default `0 3 * * *` UTC; cron parsed by `croniter`). Skips if a successful run for today (UTC) already exists (idempotency).
  - `pg_dump -Fc -Z 9 --no-owner --no-privileges --jobs=cfg.maint_backup_pg_jobs` to `cfg.maint_backup_dir/YYYY-MM-DD/negelir.dump`.
  - Optional encryption-at-rest: if `cfg.maint_backup_encryption_key_path` is set, the dump is post-processed with `age` (passphrase from Docker secret / K8s SealedSecret — never from env). If unset, dump is left unencrypted with a stderr warning + `sec.alert.v1{kind=backup_unencrypted, severity=warn}` (debounced daily).
  - `kind=backup_started` published before dump; `kind=backup_completed{size_bytes, duration_ms, checksum_sha256, encrypted: bool}` after.
- [ ] **Restore-verify (mandatory daily).**
  - Spin up a throwaway Postgres in the same network (`postgres:16-alpine` named `negelir-restore-verify`, ephemeral volume).
  - `pg_restore --jobs=...` the new dump.
  - Run a fixed verification suite (`xops/backup/verify.sql`): `SELECT count(*) FROM <each table>`, all migrations applied (`SELECT max(version) FROM schema_migrations`), one round-trip read on the most recent `match_normalized` and `quarantine_samples` row.
  - On failure: emit `sec.alert.v1{kind=backup_verify_failed, severity=critical}` (bypasses debounce), keep the dump file (do **not** prune), exit non-zero. Operator must investigate.
  - On success: emit `kind=backup_completed{verified: true}` and prune dumps older than `cfg.maint_backup_retention_days` (default 14) and `cfg.maint_backup_retention_weeks` (default 4 weekly Sunday dumps kept — GFS-light).
- [ ] **TTL prune jobs (scheduled at the same cron tick, after the dump).**
  - `quarantine_samples` rows older than `cfg.sec_quarantine_ttl_days` (default 30) → DELETE. Emits `kind=quarantine_pruned{table, row_count, oldest_kept_at}`.
  - `schema_snapshots` rows older than `cfg.maint_schema_snapshot_retention_days` (default 90) → DELETE. Phase 4 snapshots fed by `storage.v1` accumulate.
  - `dlq_entries` (Phase 9 Postgres backend) older than `cfg.swarm_dlq_pg_retention_days` (default 14) → DELETE.
  - `opsctl_audit` and `maint_audit_log` rows older than `cfg.maint_audit_retention_days` (default 365) → DELETE. Note the longer retention — audit trail value is highest.
- [ ] **PII erase (consumer of `maint.event.v1{kind=quarantine_erase, target=<client_id>}`).**
  - Loads matching `quarantine_samples` rows by `client_id`, sets `raw_bytes_b64 = NULL`, sets `erased_at = now()`, leaves `quarantine_id` row in place for audit.
  - Emits `maint.event.v1{kind=pii_erased, target=<client_id>, table=quarantine_samples, row_count, erased_at}` and a corresponding `maint_audit_log` insert (right-to-erasure traceability per [`design/SECURITY.md`](../design/SECURITY.md)).
  - Acks via `maint.ack.v1` with `accepted=true, reason="erased <N> rows"` or `accepted=false, reason="no rows matched"`.
- [ ] **Disk-usage guard.** Before each dump, refuses to start if free space on `cfg.maint_backup_dir` < `2× last_dump_size + cfg.maint_backup_min_free_gb` (default 5 GB headroom). Emits `sec.alert.v1{kind=backup_disk_pressure, severity=error}`.
- [ ] **Safety floor.** TTL prunes are gated by `cfg.maint_backup_dry_run` (default `false` in prod, **`true` in mock profile**) — first run on a fresh dev stack must not delete data the operator hasn't seen yet.

### 8.4 Source-watcher SDK + LLM-summarizer graduation

> Phase 2.8 source-watcher migrates from `scheduler.py` cron loop to the swarm SDK. The deterministic differ + classifier stay authoritative; the LLM summarizer flips from `enabled=False` stub to a real client behind a model-pin gate.

- [ ] **SDK migration.** Subclass `Agent`; `subscribes=()` (still time-driven), `publishes=(SOURCE_WATCH_REPORT_V1,)` plus the existing `maint.event.v1{kind=baseline_reset}` and `proof.flag` surfaces. The internal scheduler stays — it now ticks via `AgentRunner` heartbeats instead of a standalone subprocess. Existing tests under `ai/swarm/source_watcher/tests/` retarget to the SDK harness; **classification rule outputs must be byte-identical pre/post migration** (golden-file regression test).
- [ ] **Summarizer graduation.** `cfg.source_watcher_summarizer_enabled` flips to `true` only when ALL of:
  - A non-`*-latest` model ID is configured at `cfg.source_watcher_summarizer_model_id` (CLAUDE.md doctrine — `*-latest` rejected at config validation).
  - The configured model is reachable from the agent's network namespace (probed at startup; failure → `enabled=False` runtime override + `sec.alert.v1{kind=summarizer_unreachable, severity=warn}`).
  - The deterministic differ has produced at least one non-empty `UpdatePlan` (the summarizer never narrates an empty diff).
- [ ] **Boundary test (binding).** AST-and-runtime scan asserting `summarizer.summarize(plan)` cannot mutate `plan.classification`, `plan.severity`, or `plan.fields_changed`. Returns Turkish narration string only. Existing test extended; failure on a future attempt to widen the summarizer's authority.
- [ ] **Cost cap.** Summarizer call wrapped in `cfg.source_watcher_summarizer_max_tokens_per_day` (default 50 000) ledger. Overflow → fall back to deterministic plan-derived string + `sec.alert.v1{kind=summarizer_cost_capped, severity=warn}` (debounced daily).
- [ ] **Versioning.** `source_watcher` chart key bumps `1.x → 2.0.0` on this graduation (per ROADMAP §2.8 note). The `swarm` chart key bumps minor for the §8.x landings.

### 8.5 DLQ supervisor (`maint.dlq.v1`)

> Drains, replays, escalates DLQ entries. The DLQ wires were laid in Phase 3.5 (`<topic>.dlq` Redis stream, `swarm_dlq_max_len`); Phase 8 ships the consumer that actually reads them.

- [ ] **Read loop.** Subscribes to all `<topic>.dlq` streams discovered via `swarmctl topics` at startup (and on every heartbeat — new topics are picked up live). Per-topic concurrency bounded by `cfg.maint_dlq_concurrency` (default 4).
- [ ] **Replay policy** (per entry, per topic):
  - First DLQ visit → wait `cfg.maint_dlq_replay_backoff_s` (default 60s), republish to the original topic with the same `request_id` + a `dlq_replay_count: 1` envelope header.
  - Second DLQ visit → wait `cfg.maint_dlq_replay_backoff_s × cfg.maint_dlq_backoff_factor` (default 60s × 4 = 240s), republish with `dlq_replay_count: 2`.
  - Third DLQ visit → escalate: emit `sec.alert.v1{kind=dlq_escalated, severity=error, subject=<topic>}` + `maint.event.v1{kind=dlq_escalated, target=<topic>, dlq_entry_id, original_envelope}`. Stop replaying. Operator decides via `ops.dlq-replay --topic <t> --id <id>` (forced replay, or `--drop` to acknowledge and remove).
- [ ] **Per-topic rate limit.** No more than `cfg.maint_dlq_replay_rps` (default 10) replays per topic per second — keeps a poisoned message from being thrashed against a still-broken consumer.
- [ ] **Idempotency.** Replays carry the original `request_id` so the consumer's existing idempotency guard (Phase 6 ledger, Phase 7 dedup, Phase 5 consensus single-publication) collapses dupes naturally. Boundary test: replaying an already-accepted `predict.vote` does not produce a second `predict.final`.
- [ ] **Audit.** Every replay emits `maint.event.v1{kind=dlq_replayed, target=<topic>, dlq_entry_id, replay_count}`.
- [ ] **Bounded state.** In-memory map of `(topic, dlq_entry_id) → (last_replay_at, replay_count)` capped at `cfg.maint_dlq_state_max` (default 100 000) with insertion-order LRU (mirrors the Phase 6 drift bounded-state pattern). Eviction is silent — escalation already covered the long-lived poison cases.

### 8.6 Internal schema-drift sentinel (`maint.schema.v1`)

> **Re-scoped from the original §8.1.** Scraper-selector healing moved to Phase 17 patcher (`extractor`/`schema` scopes). What stays here: detect drift between (a) JSON Schemas in `ai/swarm/sdk/schemas/` and live payloads on the bus, (b) Postgres column sets vs the migration-derived expected set, (c) `payloads.py` dataclass shape vs the matching JSON Schema. Phase 8 detects + reports; humans (or Phase 17 patcher under `migration` scope) fix.

- [ ] **Detector A — payload vs schema.** Tap `telemetry.v1`'s sample stream (Phase 4.6 already mirrors a configurable %); for each sampled envelope, run `swarm.sdk.schemas.validate(topic, payload)`. On mismatch → `maint.event.v1{kind=schema_drift_detected, target=<topic>, errors[], sample_envelope_id}` (debounced per `(topic, error_signature)` for `cfg.maint_schema_debounce_s`, default 3600).
- [ ] **Detector B — Postgres column drift.** Once per `cfg.maint_schema_pg_check_interval_s` (default 1h), run `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public'`, compare to the expected set derived from `migrations/*.sql` parsing. Drift → same `kind=schema_drift_detected, target=<table>`.
- [ ] **Detector C — dataclass vs schema.** AST scan at startup asserts every `@dataclass` in `payloads.py` has a matching JSON Schema with the same field set + types. Drift at startup → fail to start (loud failure, not an alert — code/schema drift is a release-time bug, not a runtime one).
- [ ] **Out of scope (binding).**
  - **Auto-derive selectors / extractors** — Phase 17 patcher only.
  - **Auto-apply migrations** — humans only. The sentinel emits the event; nothing in v1 runs `psql -f migrations/NNN_*.sql` unattended. (`cfg.maint_schema_auto_apply_enabled` exists in config for forward compatibility; defaults to `false` and is checked at startup with a warning if `true`.)

### 8.7 Pattern false-positive feedback loop (`maint.sec.v1` slice)

> Promotes the §7.x deferred FP loop. Operator clears a quarantined sample → the rule that triggered it auto-adds to a per-source allowlist with TTL.

- [ ] Subscribes to `maint.event.v1{kind=quarantine_clear, target=<quarantine_id>}` (Phase 7 publisher hook stub).
- [ ] Resolves `quarantine_id → (source, rule_id, hit_substring)` from `quarantine_samples`. Adds a row to `pattern_allowlist` table (migration `010_pattern_allowlist.sql`): `(source, rule_id, hit_fingerprint, expires_at = now() + cfg.maint_sec_allowlist_ttl_days, added_by_request_id)`.
- [ ] `sec.input.v1` reads the allowlist on each pattern hit — if `(source, rule_id, hit_fingerprint)` matches a non-expired row, the hit is suppressed (counted in `sec_input_allowlist_hits_total` for visibility, never silently lost).
- [ ] **Hard gate.** `cfg.sec_input_pattern_autolearn_enabled` defaults `false`. When `false`, the allowlist row is created with `expires_at = now()` (immediately expired — operator can `ops.allowlist-extend` to activate). When `true`, normal TTL applies. The default-off posture defers the auto-learn loop until Phase 13 lexicon work provides a labelled-negative corpus to validate suppressions against (per the §7.x deferral).
- [ ] Emits `maint.event.v1{kind=pattern_allowlist_added, target=<source>, rule_id, expires_at}` and `kind=pattern_allowlist_expired` on TTL expiry (a daily sweep at the §8.3 cron tick).

### 8.8 Sec-denylist sweeper (`maint.sec.v1` slice)

> Promotes the §7.3 deferred "halve TTL of oldest decile" sweeper. Activates only under cap-mode pressure.

- [ ] Subscribes to `sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}` (Phase 7 §7.3 publisher).
- [ ] On consume, runs new Lua script `infra/redis/lua/sec_denylist_decimate.lua` (versioned + SHA256 header + `make verify.lua` CI gate, exactly like the existing two scripts):
  - Identifies the oldest decile of `sec:denylist:_zset` members by score (= `expires_at_ms`).
  - Halves their remaining TTL via `EXPIRE` on the matching `sec:denylist:<subject>` keys (and updates the zset score).
  - Returns `{evicted_count, decile_size, new_zcard}` for audit.
- [ ] Emits `maint.event.v1{kind=denylist_decimate, target=<source>, evicted_count, decile_size, new_zcard}`.
- [ ] **Hysteresis.** No more than one decimate per `cfg.maint_sec_decimate_min_interval_s` (default 300s) per subject — prevents a single anomaly burst from cascading evictions.
- [ ] **Cap-mode exit.** When `ZCARD sec:denylist:_zset < cfg.sec_denylist_cap × cfg.sec_denylist_cap_exit_ratio` (default 0.7), the sweeper publishes `kind=denylist_cap_cleared` and the gateway exits subnet-mode (Phase 7 §7.3 cap flag clears naturally on the 300s TTL, this is a fast-path).

### 8.9 Definition of Done

**Surface coverage:**

- [ ] All 6 §8.x agents implemented under `ai/swarm/agents/maint/` (transitional path; R2 `git mv` to `swarm/reactors/maint/`): `maint.scaler.v1`, `maint.backup.v1`, `maint.dlq.v1`, `maint.schema.v1`, `maint.sec.v1` (covers §8.7+§8.8), source-watcher SDK migration in place. Ops console at `xops/opsctl/`.
- [ ] All 14 new `maint.event.v1.kind` values (`retrain_approve`, `scale_decision`, `scale_throttled`, `backup_started`, `backup_completed`, `backup_verify_failed`, `quarantine_pruned`, `dlq_replayed`, `dlq_escalated`, `schema_drift_detected`, `pattern_allowlist_added`, `pattern_allowlist_expired`, `denylist_decimate`, `pii_erased`) join the §7.4 known-kinds set; producer-set allow-list updated; boundary test green.
- [ ] `maint.ack.v1` topic + JSON schema landed; every Phase 6/7/8 consumer of `maint.event.v1` publishes exactly one ack per `request_id` (boundary test).
- [ ] New Lua script `sec_denylist_decimate.lua` carries VERSION + SHA256 header; `make verify.lua` CI gate covers it; embedded copy in `server/internal/sec/embedded/` synced; embedded-parity test green.

**Idempotency / single-publication:**

- [ ] `maint.scaler.v1`: exactly one `scale_decision` per `decision_window_id` under at-least-once redelivery (idempotency test).
- [ ] `maint.backup.v1`: re-running the daily cron tick after a successful run is a no-op (`backup_started` not emitted; idempotency test on `(job_id, backup_date_utc)`).
- [ ] `maint.dlq.v1`: replaying an already-accepted entry does not produce a second downstream emission (negative test against `predict.vote → predict.final` path with redelivery).

**Bounded state:**

- [ ] Scaler decision history capped at `cfg.maint_scaler_history_max` (default 1024) with insertion-order LRU.
- [ ] DLQ supervisor in-memory map capped at `cfg.maint_dlq_state_max` (default 100 000) with insertion-order LRU.
- [ ] Pattern allowlist daily sweep removes expired rows; table size bounded by TTL × emission rate (no unbounded growth proof test).

**Safety / hard caps:**

- [ ] Scaler refuses to exceed `cfg.maint_scaler_max_replicas[<agent>]` (per-agent) and `cfg.maint_scaler_global_max_replicas` (global). Triangle test covers the cfg keys; chaos test `make chaos-flap-replicas AGENT=consensus.v1` proves hysteresis (no back-to-back decisions inside `min_decision_interval_s`).
- [ ] Backup refuses to start when free disk < `2× last_dump + cfg.maint_backup_min_free_gb`. Mock-profile dry-run defaults to `true`. Restore-verify failure keeps the dump and pages a critical alert.
- [ ] DLQ replay rate per topic ≤ `cfg.maint_dlq_replay_rps`. Third visit escalates; no autonomous fourth replay.
- [ ] Auto-coder `maint.coder.v1` is **not** present (it is Phase 17 patcher's job). AST scan in CI rejects any `from swarm.agents.maint.coder` import.

**Boundary discipline (`test_boundary_discipline.py` extensions):**

- [ ] `maint.event.v1` producer set ⊆ `{drift.v1, ops_console, maint.scaler.v1, maint.backup.v1, maint.dlq.v1, maint.schema.v1, maint.sec.v1, source_watcher}` (loosened from the §7 set by exactly the Phase 8 reactors).
- [ ] `sec.denylist.v1` sole producer is still `sec.rate.v1` (§8.8 sweeper publishes via Lua under the existing key prefix; no new direct producer of the topic).
- [ ] Ops console publishes only on `maint.event.v1` (and reads `maint.ack.v1`); never on `sec.*`, `predict.*`, `freshness.*`, `match.*`.
- [ ] `xops/opsctl/**.py` AST-clean of `psycopg`/direct `redis.Redis.*` mutators.
- [ ] Source-watcher summarizer cannot mutate classifier output (existing boundary test extended to cover the SDK-migrated path).

**Observability + visibility:**

- [ ] Every Phase 8 agent appears in `swarmctl ps`; `maint.event.v1` and `maint.ack.v1` in `swarmctl topics`.
- [ ] Telemetry watch set extended to include `MAINT_ACK` (counters surface per-consumer ack latency + accepted/rejected ratios). Phase 4.6 watch-set test asserts.
- [ ] Live-emission JSON-Schema validation covers every Phase 8 emit (`test_phase8_swarm_demo_end_to_end`, mirroring the Phase 4 / Phase 6 live-emission probe pattern).
- [ ] `make swarm.demo` (extended) walks one `ops.denylist-clear` round-trip through the bus and asserts the ack latency budget (`< cfg.opsctl_ack_timeout_ms`).

**Phase 12 chaos catalogue stubs:**

- [ ] Stub rows in `docs/testing/phase12_catalogue.md` for `chaos-fill-dlq`, `chaos-flap-replicas`, `chaos-corrupt-dump`, `chaos-disk-pressure-backup` (one row per check, body = "TBD — implementation pending Phase 12"). Mirrors the Phase 7.4 catalogue-stub pattern; flips fully green when Phase 12 fills the bodies in.

**Versioning:**

- [ ] `swarm` chart key bumps **minor** at the Phase 8 landing (new agents + new topic). `source_watcher` bumps **major** (`1.x → 2.0.0`) at the SDK + summarizer graduation per §2.8 promise. `xops` bumps **minor** for the `opsctl` CLI. Subsequent Phase 8 review patches bump the affected key patch-level.

**Triangle test (config sync):**

- [ ] All Phase 8 cfg knobs (`maint_scaler_*` ×8, `maint_backup_*` ×9, `maint_dlq_*` ×6, `maint_schema_*` ×3, `maint_sec_*` ×2, `maint_audit_retention_days`, `opsctl_ack_timeout_ms`, `source_watcher_summarizer_*` ×2) appear in `xops/env/.env.example`, `ai/common/defaults.yaml`, and `ai/common/config.py`. `test_config_sync.py` stays green.

**Migrations:**

- [ ] `migrations/009_maint_audit.sql` lands the `maint_audit_log` table (additive — no DROP, per CLAUDE.md doctrine).
- [ ] `migrations/010_pattern_allowlist.sql` lands the `pattern_allowlist` table (additive).
- [ ] Both migrations apply cleanly on a fresh DB and as upgrades from migration 008.

**Doctrine / docs:**

- [ ] [`design/SWARM.md`](../design/SWARM.md) roster updated with the 6 maint agents + ownership notes.
- [ ] [`design/SECURITY.md`](../design/SECURITY.md) updated with the right-to-erasure flow (`quarantine_erase` → `pii_erased` audit row).
- [ ] [`design/CONFIGURATION.md`](../design/CONFIGURATION.md) gains a "Maintenance" section enumerating every Phase 8 cfg knob with default + range + safety note.
- [ ] CLAUDE.md scope table updated: ops console publishes maint events; patcher remains the only auto-mutator of scraper code (no overlap with Phase 8).

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

## 🌐 Phase 19 — Global Catalog (deferred long-tail)

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

## 🏗️ Phase R — Restructure Track (Production Pivot v3)

**Goal:** Move the code without breaking anything.

> **Sequencing — stop-the-world (2026-04-20; deferred path chosen 2026-04-28).**
> Earlier drafts suggested R1–R5 could "run in parallel with Phases 3–8". That
> turned out to be unrealistic: every Phase 3+ feature ships into one of
> the four target components (`server/`, `datasource/`, `swarm/`,
> `common/`) and would have to be rewritten mid-flight if the layout
> shifts under it. **R1–R6 run as a single stop-the-world sprint (no
> concurrent feature work).** The original plan offered two insertion
> windows: between Phase 2 and Phase 3, or — if explicitly deferred —
> between Phase 5 and Phase 6. **The deferred window has been chosen
> implicitly:** Phases 3 and 4 already shipped under the transitional
> `ai/swarm/sdk/` + `ai/swarm/agents/` paths agreed in their own
> alignment blocks (R2 is a `git mv`, not a rewrite). The R sprint
> therefore lands between Phase 5 design completion and Phase 6
> implementation kickoff. Estimated 1–2 weeks of focused work. Each
> sub-phase is individually reversible within the sprint.
**Anchor doc:** [`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) §§3, 7.

### R1 — Rename + path aliases

- [x] New chart keys added to `xops/versioning/chart.json`: `datasource_scraper`, `datasource_watcher`, `datasource_refresher`, `datasource_patcher`, `datasource_gitops`, `datasource_emitter`, `swarm`, `common` (all seeded at `0.1.0` / `0.2.x`; verified 2026-04-28).
- [ ] `version.py rename` subcommand lands; used to rename `source_watcher → datasource_watcher` in a single changelog row. *(Today both keys coexist — `source_watcher@1.4.0` and `datasource_watcher@0.1.0`. The rename ships with the actual file move in R2.)*
- [x] No files move yet; chart is the only change so far.

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
