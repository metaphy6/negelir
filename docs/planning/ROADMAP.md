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
- [Phase 8 — Self-Maintenance Agents (Ops Console, Auto-Scaler, Backup + Off-Host DR, DLQ Supervisor, Watcher Graduation)](#-phase-8--self-maintenance-agents-ops-console-auto-scaler-backup--off-host-dr-dlq-supervisor-watcher-graduation)
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
- [x] **Migrations.** `migrations/007_quarantine.sql` (the `quarantine_samples` table, including the `erased_at` PII-erasure column per §7.1) and `migrations/008_source_fingerprints.sql` (streaming-statistic baseline state, **not** raw samples — schema carries serialized Welford / P² / count-min state per source) land with this phase; both are additive (no `DROP`). **Migration-numbering reservation (revised 2026-05-05 to resolve the §8.9 collision — Phase 8 lands before Phase 9 per dependency graph and therefore claims the lower numbers):** Phase 8 reserves `009_*`–`011_*` (`009_maint_audit.sql`, `010_pattern_allowlist.sql`, `011_backup_role.sql` — see §8.9); Phase 9 user / tier / auth tables start at `012_*` with `013_*` reserved for Phase 9.x follow-ups; Phase 10 NLP starts at `014_*`. To be documented in [`migrations/README.md`](../../migrations/) when Phase 8 lands so future phases don't collide.

### 7.8 Pivot v3 alignment & follow-ups

- [ ] **Per-league burst multiplier.** Phase 13a per-league overrides via `LeagueConfig.sec_burst_multiplier`; `sec.rate.v1` resolves the multiplier from JWT preferred-league claim or the request's `league_id`. Until then, the global threshold is the right default.
- [ ] **Quarantine → feeds plane.** Phase 16 emitter migration of `sec.quarantine.v1` to `feeds/sec_quarantine.v1.parquet` — keeps long-tail forensic storage off the bus. The `QuarantineSample` dataclass already maps 1:1 to the parquet row.
- [ ] **Denylist leader election.** Multi-replica `sec.rate.v1` requires Postgres-backed leader election (Phase 14.x); single replica is the v1 invariant.
- [ ] **Sec.input classifier promotion.** v1 ships a deterministic-only fallback (no classifier on disk). The first labelled-corpus drop (Phase 13 lexicon work) unlocks the small classifier; until then, `sec_input_classifier_path` defaults to empty and the agent skips step 5 (verdict short-circuits to `pass` on rule-inconclusive payloads, with a `sec.alert.v1{severity=info}` for visibility — fail-open consistent with §7.7).
- [ ] **False-positive feedback loop (deferred to Phase 8.x).** When an operator clears a quarantined sample (`maint.event.v1{kind=quarantine_clear}`), the deterministic rule-id that triggered it should auto-add to a per-source allowlist with a TTL (operator-tunable). v1 does not auto-learn — every clear is a manual edit to `injection_patterns.yaml`. The Phase 8 maint command exists at landing but the auto-learn loop is gated behind `cfg.sec_input_pattern_autolearn_enabled` (default false) until Phase 13 lexicon work provides a labelled-negative corpus to validate suppressions against.
- [ ] **WAF bypass parity.** SECURITY.md explicitly excludes a WAF; if a deploy adds one (cloud profile), the gateway middleware must continue to enforce all checks (defense-in-depth) — covered by an integration test that runs the gateway with `SEC_ASSUME_UPSTREAM_WAF=true` and confirms quarantine still fires.
- [ ] **SECURITY.md sync.** This phase's revisions (IPv6 prefix bucketing, XFF trust boundary, denylist cardinality cap, baseline warm-up, streaming-statistic baseline, generalized alert debounce, open-enum pattern, pattern hot-reload, gateway secondary bucket, PII-erasure path, defense-in-depth contract) land as a SECURITY.md update **in the same PR** as this ROADMAP revision so the design doc and the plan stay in lock-step (the existing `Defense agents (Phase 7 detail)` section currently lags the ROADMAP). Tracked by a single `make track.add` row at landing.

---

## 🔧 Phase 8 — Self-Maintenance Agents (Ops Console, Auto-Scaler, Backup + Off-Host DR, DLQ Supervisor, Watcher Graduation)

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
- **Phase 3 §3.5 topic catalog (wire authority).** Phase 8 lands **one** new topic — `maint.ack.v1` (per-consumer acknowledgements; `maint.event.v1` and `maint.dlq.v1` already exist). The §3.5 wire-authority table grows by exactly one row (`maint.ack.v1` → schema `ai/swarm/sdk/schemas/maint.ack.v1.json`, producer set `{any consumer of maint.event.v1}`, consumer set `{ops_console, maint.* operator-replay paths}`). New `maint.event.v1.kind` values join the open-enum allow-list (§7.4 pattern):
  `retrain_approve`, `scale_decision`, `scale_throttled`, `backup_started`, `backup_completed`, `backup_verify_failed`, `backup_verify_orphan_swept`, `backup_verify_key_rotated`, `backup_cold_verify_completed`, `backup_cold_verify_failed`, `backup_offsite_uploaded`, `backup_offsite_failed`, `backup_restore_started`, `backup_restore_completed`, `quarantine_pruned`, `dlq_replayed`, `dlq_escalated`, `dlq_topic_disabled_drained`, `schema_drift_detected`, `pattern_allowlist_added`, `pattern_allowlist_pending`, `pattern_allowlist_promoted`, `pattern_allowlist_expired`, `denylist_decimate`, `denylist_cap_cleared`, `pii_erased`, `maint_silence_alert`, `backup_age_alert`, `manual_scale_pin`, `manual_scale_pin_expired`, `backup_key_rotated`, `maint_plane_throttled`, `maint_plane_recovered`, `maint_paused`, `maint_resumed`, `maint_unknown_kind`. Plus **five** new `sec.alert.v1` kinds: `consumer_likely_broken`, `maint_plane_lag_high`, `summarizer_unreachable`, `backup_clock_skew`, `maint_ack_oversize` (the first three were already named in §8.4/§8.5/§8.11 prose; the latter two are introduced by this revision). The §7.4 producer-set allow-list is widened from `{drift.v1, ops_console}` to `{drift.v1, ops_console, maint.scaler.v1, maint.backup.v1, maint.dlq.v1, maint.schema.v1, maint.sec.v1, source_watcher, telemetry.v1}` — boundary test in `test_boundary_discipline.py` is loosened in the same PR as §8.0 lands, exactly as Phase 7 loosened it for `ops_console`. **Per-producer kind allow-list** also pinned: `telemetry.v1` may publish `sec.alert.v1` ONLY with `kind=maint_silence_alert` (test asserts).
- **Ack semantics (binding).** `maint.ack.v1` is **per-consumer**, not per-event. A `maint.event.v1{kind=retrain_request}` consumed by both `trainer.v1` (action-of-record) and `maint.scaler.v1` (warm-up) yields **two** acks — one from each, distinguished by `accepted_by`. Ops console (§8.1) waits for **all expected acks** computed from the live consumer registry at publish-time (`set(swarmctl topics --consumers maint.event.v1) ∩ {agents that accept this kind}`). Boundary test pins the kind→consumer-set mapping in `ai/swarm/agents/maint/_ack_routing.py` (single source of truth). **Empty expected-ack set is a hard error** — if no registered consumer accepts a `kind`, the publish is rejected at ops console with exit code 5 (`no_consumer_for_kind`) before hitting the bus; prevents fire-and-forget envelopes that nobody owns.
- **Envelope vs payload (binding).** Phase 3 §3.2 `Envelope` carries `{message_id, trace_id, topic, producer, created_at, schema_version, attempt}` — nothing else. Phase 8 fields **`request_id`, `client_id`, `produced_at`** all live in the **payload** (`maint.event.v1.json` schema), NOT the envelope. The §8.1 prose "envelope already carries client_id" is wrong and is corrected here. The §8.5 `dlq_replay_count` is also a payload field (added to `maint.event.v1` payload optionally; see §8.5). The runner's `attempt` envelope counter is a *bus-level* retry counter (incremented on redelivery within one consumer group); it is distinct from `dlq_replay_count` (which counts *operator-or-supervisor-driven re-publishes after DLQ landing*). Tests pin both: envelope schema additions → version bump; payload field additions → `additionalProperties:false` discipline preserved.
- **`maint.event.v1` per-kind payload-shape discipline (binding).** The top-level schema is a JSON-Schema `oneOf` discriminated on `kind` (mirrors the JSON-Schema 2020-12 dependent-schemas idiom). Each known kind has its own sub-schema pinning the legal payload fields — `scale_decision` requires `{target, prev:int, next:int, reason, observed:object, decision_window_id}`; `backup_completed` requires `{job_id, backup_date_utc, size_bytes, duration_ms, checksum_sha256, encrypted:bool, encryption_key_version:int|null, verified:bool}`; `pii_erased` requires `{target, table, row_count, erased_at}`; etc. Per-kind sub-schemas live at `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json` and are loaded into the `oneOf` automatically by `swarm.sdk.schemas.load_topic_schema('maint.event.v1')`. Adding a new `kind` requires (a) the kind in the §7.4 known-kinds set, (b) the per-kind sub-schema file, and (c) a payload-shape proof test in `test_phase8_maint_event_kind_shapes.py`. Boundary test asserts: every kind in the `_ack_routing.py` map has a matching sub-schema, and every sub-schema has a matching kind; orphans on either side fail CI. Producers use `swarm.sdk.payloads.MaintEvent.<kind>(**fields)` factories that validate at emit time; consumers narrow on `kind` before reading kind-specific fields. **Forward compat:** unknown kinds in a redelivered envelope after a downgrade are dropped with `sec.alert.v1{kind=maint_unknown_kind, severity=warn}` (debounced per-kind), never blanket-rejected — preserves rolling upgrades.
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
- **Phase 14 K8s.** Each Phase 8 agent runs at `replicas: 1` (single-publication for `scale_decision`, `backup_completed`, `dlq_replayed` requires it). Compose mode invokes `docker compose --scale <svc>=N`; K8s mode patches `apps/v1.Deployment.spec.replicas` via the in-cluster client. The runtime adapter is a `RuntimeController` Protocol (in-process compose runner today, K8s client at Phase 14) — the scaler code never changes across the two backends. **Persistent storage requirements (binding for Phase 14):** `maint.backup.v1` MUST mount a PVC at `cfg.maint_backup_dir` (default `/var/lib/negelir/backups`, `ReadWriteOnce`, ≥ `cfg.maint_backup_pvc_size_gb`); `xops/opsctl/` MUST mount a PVC at `data/maint/opsctl_spool/` (small, RWX if multiple operator pods). The §8.3 SidecarVerifier `Job` mounts the **same backup PVC read-only** (`accessModes: [ReadOnlyMany]` derived via VolumeSnapshot when the SC supports it; falls back to `ReadWriteOnce` if the agent suspends writes for the verify window). Phase 14 manifests pin both. Without the PVC declarations the agents refuse to start (`fail_safe_no_persistent_storage`).
- **Phase 16 emitter.** Backup verifications and scale decisions stay on the bus (control plane); they do **not** move to feeds. The audit trail of nightly dumps is a CSV append at `data/backups/audit.csv` (operator-facing, not customer-facing). PII erase events emit a `maint.event.v1{kind=pii_erased, target=<client_id>, table, row_count, erased_at}` audit row that **does** persist in the `maint_audit_log` table (migration `009_maint_audit.sql`) — required for right-to-erasure traceability.
- **Phase 17 patcher.** Patcher's allow-list (`extractor`/`schema`/`migration`/`fixture`) and Phase 8's allow-list are **disjoint**. The §8.6 schema-drift sentinel detects drift and emits `maint.event.v1{kind=schema_drift_detected, target=<table>}`; humans then either edit the schema themselves or escalate to the patcher's `migration` scope. Phase 8 itself never invokes the patcher harness.
- **Phase 20 monetization.** None of the maint surfaces are tier-gated — backup, scaler, DLQ supervisor, and ops console are operator infrastructure, not user features. Per [`design/MONETIZATION.md`](../design/MONETIZATION.md) the gate is at the Go edge for `/v1/predictions/*`, never at maint.

### 8.1 Ops console (`ops_console` publisher of `maint.event.v1`)

> The single human-facing publisher for every Phase 6/7/8 maint hook. Lives at `xops/opsctl/` as a stdlib-only CLI; in Phase 9 the same payloads are exposed at `/v1/admin/maint/*`.

- [ ] CLI entry point `xops/opsctl/__main__.py` invoked via `make ops.<cmd>` shortcuts (`ops.denylist-clear`, `ops.baseline-reset`, `ops.quarantine-erase`, `ops.quarantine-clear`, `ops.retrain-approve`, `ops.scale`, `ops.scale-pin`, `ops.scale-unpin`, `ops.backup-now`, `ops.backup-rotate-key`, `ops.restore`, `ops.dlq-replay`, `ops.dlq-resume`, `ops.allowlist-extend`, `ops.allowlist-approve`, `ops.allowlist-show`, `ops.maint-pause`, `ops.maint-resume`, `ops.spool-flush`, `ops.spool-show`, `ops.liveness`).
- [ ] Each subcommand:
  - Validates inputs locally (`target` is a known subject; `kind` is in the open-enum allow-list; `client_id` defaults to the OS username; subject syntax is rule-checked — IPs for denylist subjects, `<source>:<rule_id>` for allowlist subjects, registered agent ids for scale targets).
  - Constructs an `Envelope` with `request_id = uuid4()`, `produced_at = now_utc()`, `schema_version = 1`, and `client_id = "<os_user>@<hostname>"`.
  - Publishes to `maint.event.v1` via the same `Bus` Protocol used by the runtime (Redis Streams in prod, `InMemoryBus` in tests).
  - Waits ≤ `cfg.opsctl_ack_timeout_ms` (default 5000) for the **expected ack set** (per the §0 ack semantics — set of `(accepted_by)` agents derived from kind→consumer routing). Partial-ack timeout → exit code 3 + structured stderr listing missing acks. Hard timeout (no acks at all) → exit code 2.
  - Supports `--dry-run` (validates + computes the expected ack set + prints the envelope to stdout, **does not publish**) and `--json` (machine-readable result for runbook automation).
- [ ] **Destructive-command confirmation gate (binding).** Subcommands classified `destructive=true` in `xops/opsctl/_classify.py` REFUSE to publish without `--confirm-destructive=<typed-token>` where `<typed-token>` MUST equal a stable per-command derivation `sha256(f"{cmd}|{target}|{salient_args}")[:8]` printed by the CLI on the first dry-run-equivalent attempt (operator copy-pastes — defeats accidental shell-history re-runs). Default destructive set: `ops.scale --replicas 0`, `ops.scale` requesting `>50%` reduction vs current desired, `ops.dlq-replay --drop`, `ops.dlq-replay --topic sec.* --confirm-pii` (still requires `--confirm-pii` AND `--confirm-destructive`), `ops.quarantine-erase`, `ops.restore`, `ops.backup-rotate-key`, `ops.maint-pause --agent <id>` for any agent in `cfg.opsctl_critical_agents` (default = `{consensus.v1, sec.rate.v1, maint.backup.v1}`). Boundary test enumerates the destructive set against `_classify.py` and refuses orphans either way.
- [ ] **Bus-down spool.** If the bus publish fails (Redis unreachable, auth error, schema reject), the envelope is appended to `data/maint/opsctl_spool/<request_id>.envelope.json` (mode 0600) and the CLI exits 4. A separate `make ops.spool-flush` reattempts every spooled envelope in append order; flush is idempotent (consumer-side `request_id` dedup absorbs replays). The spool dir is bounded at `cfg.opsctl_spool_max_entries` (default 1024) — overflow refuses new publishes loud.
- [ ] **Re-entrancy lock.** A per-`(host, kind, target)` advisory lockfile under `data/maint/opsctl_locks/` (acquired with `fcntl.flock` non-blocking) prevents two operator shells from publishing the same logical command in flight. Stale locks (older than `2 × opsctl_ack_timeout_ms`) are reaped on next acquire.
- [ ] **Audit row.** Every successful publish appends to `data/maint/opsctl_audit.csv` (append-only, **`fsync` after each write AND after the underlying directory `fsync` on first creation**, schema = `ts_utc, user, host, kind, target, request_id, expected_ack_set, ack_received_count, exit_code, duration_ms`). The same row is mirrored to `maint_audit_log` (Postgres) once Phase 9 lands. File mode 0600.
- [ ] **No bypass channels.** The CLI must NOT write directly to Postgres or Redis state — it only publishes envelopes. Boundary test: AST scan of `xops/opsctl/**.py` rejects `psycopg`, `redis.client.Redis.set/del/hset/zadd/expire`, `subprocess.*` invocations of `psql`/`redis-cli`, and any module-level network connection outside the published `Bus` Protocol.
- [ ] **`maint.ack.v1` schema.** New JSON schema at `ai/swarm/sdk/schemas/maint.ack.v1.json` carrying `{request_id, accepted: bool, accepted_by: <agent_id>, reason?: str (≤ cfg.maint_ack_reason_max_bytes, default 512), details?: object (≤ cfg.maint_ack_details_max_bytes, default 2048; flat key/value, no nested arrays of objects), processed_at: iso, attempt: int}`. **Hard size cap** at `cfg.maint_ack_payload_max_bytes` (default 4096) is enforced at emit time; oversize acks are truncated with `reason="truncated:<original_len>"` and a `sec.alert.v1{kind=maint_ack_oversize, severity=warn}` (debounced per `accepted_by`) — prevents a buggy consumer from OOMing the publisher's wait-buffer. **Per-consumer semantics:** every consumer that processes a `maint.event.v1{request_id}` publishes exactly one `maint.ack.v1` with its own `accepted_by`. Re-deliveries published by the bus do **not** produce additional acks (the consumer's idempotency ledger collapses dupes; ack `attempt > 1` is reserved for explicit retries surfaced by the consumer).
- [ ] **Idempotency guard.** Re-running `ops.denylist-clear --target <ip>` for an already-cleared subject is a no-op at the consumer side and surfaces `ack.accepted=true, reason="already_cleared"` — never a hard error (operators muscle-memory re-run; the system tolerates it).

### 8.2 Auto-scaler agent (`maint.scaler.v1`)

> Continuous control loop: read telemetry, decide desired replica counts per agent, call the runtime controller, audit. Hysteresis everywhere.

- [ ] **Runtime selector.** `cfg.maint_runtime ∈ {compose, k8s, none}` (default `compose` in dev, `none` in tests, `k8s` in Phase 14). `none` makes the scaler a pure observer — emits `scale_decision` events but performs no runtime call (useful for shadow-mode rollout). Boot-time validation: refuses to start with `compose` selected if `cfg.maint_scaler_compose_file` does not exist.
- [ ] **Inputs:** the agent maintains a rolling `cfg.maint_scaler_window_s` (default 60s) sketch over telemetry counters Phase 4.6 already publishes — stream lag per topic, agent CPU%, predictor latency p95, DLQ depth, plus the Phase 7 `sec.alert.v1{kind=rate_burst, severity≥warn}` signal for API-frontend scale-up. Sketch storage uses constant-memory Welford (mean+variance) per signal, mirroring Phase 7 §7.2 streaming-statistic discipline; no unbounded backfill.
- [ ] **Decision function:** `desired_replicas = clamp(min_replicas, ceil(observed_load / cfg.maint_scaler_target_load_per_replica), cfg.maint_scaler_max_replicas[<agent>])`. Per-agent caps live in `cfg.maint_scaler_max_replicas` (dict, validated at boot — refuses to start if any registered agent is missing an entry, mirrors the Phase 7 §7.6 endpoint-cost totality test). **Hard global cap** `cfg.maint_scaler_global_max_replicas` (default 64) prevents runaway in cloud (Phase 14).
- [ ] **`decision_window_id` definition (binding).** `f"{agent}:{floor(monotonic_ns / cfg.maint_scaler_window_ns)}"` where `cfg.maint_scaler_window_ns` is derived from `maint_scaler_window_s × 1e9`. Anchored on **monotonic** clock, not wall-clock — survives NTP slews. Window-id collisions across pod restarts are absorbed by the `Ledger` (the post-restart agent reloads the last 2 windows from Postgres at Phase 9; in-memory only at v1, with a documented "first 2 windows after restart may double-publish" caveat covered by the Phase 14 leader-election guard below).
- [ ] **Hysteresis & flap damping.**
  - Min interval between decisions per `(agent, runtime)` = `cfg.maint_scaler_min_decision_interval_s` (default 90s). Decisions inside the window are coalesced (latest desired wins, no scale call issued).
  - Scale-down requires the proposed lower replica count to hold for ≥ `cfg.maint_scaler_scale_down_grace_s` (default 300s) of consecutive samples. Scale-up has no grace (capacity emergencies are not damped).
  - On every emitted decision, publish `maint.event.v1{kind=scale_decision, target=<agent>, prev=N, next=M, reason, observed: {...}, decision_window_id}` for audit. Reason is one of `{lag_high, lag_low, cpu_high, cpu_low, p95_high, dlq_depth_high, sec_rate_burst, vram_budget_exceeded, retrain_request_warmup, manual_pin, manual_override_detected}`.
  - Throttled decisions (cap hit, vram refused, runtime returned non-zero, manual-pin override active) emit `kind=scale_throttled` + `sec.alert.v1{kind=scale_throttled, severity=warn}` (debounced).
- [ ] **Operator-pin override (consumer of `maint.event.v1{kind=manual_scale_pin, target=<agent>, replicas=N, ttl_s=T}`).** Pins the desired replica count for `<agent>` to `N` for `T ≤ cfg.maint_scaler_pin_max_ttl_s` (default 3600). Auto-scaler decisions during the pin emit `scale_throttled, reason=manual_pin` and **do not** call the runtime. Pin expiry publishes `kind=manual_scale_pin_expired` and the loop resumes. `ops.scale-unpin` short-circuits via the same path.
- [ ] **`decision_window_id` post-restart safety.** The monotonic-anchored id is per-process; after a restart the counter resets. To prevent **ledger collision after restart** (a fresh `agent:0` window-id colliding with a pre-restart one already in the Postgres ledger at Phase 9), the id is prefixed with a stable `pod_instance_id`: `f"{agent}:{pod_instance_id}:{floor(monotonic_ns/window_ns)}"` where `pod_instance_id = sha256(boot_random_16B)[:8]` (re-rolled at every process start, persisted to `/run/maint/pod_instance_id` for crash-recovery within a single liveness cycle). Idempotency proof test: restart the scaler process mid-window, assert the next `scale_decision` carries a fresh `pod_instance_id` and the Phase 9 ledger does not flag a duplicate.
- [ ] **Single-publication of `scale_decision`.** Exactly one event per `decision_window_id` even under at-least-once redelivery from telemetry. Guarded by the Phase 4.7 `Ledger` Protocol (in-memory now, Postgres at Phase 9). `replicas: 1` enforced at Phase 14 with **leader-election** (see §8.10) so rolling upgrades cannot briefly co-issue.
- [ ] **Runtime adapters.** `RuntimeController` Protocol with three implementations:
  - `ComposeController` (dev only) — invokes `docker compose -f <compose_file> up -d --scale <svc>=N --no-recreate`. The compose file path comes from `cfg.maint_scaler_compose_file`. Subprocess run with `check=True`, captured stderr, `cfg.maint_scaler_runtime_timeout_s` (default 30s) timeout, retries=0 (next decision tick is the retry surface). Requires the agent container to mount the host docker socket — **explicitly forbidden in prod** (Phase 14 K8sController is mandatory for cloud).
  - `K8sController` (Phase 14) — uses `kubernetes.client.AppsV1Api.patch_namespaced_deployment_scale`. RBAC: a dedicated `maint-scaler` ServiceAccount with `patch` on `deployments/scale` only (least-privilege; the Phase 14 manifest pins this). `NoopController` returns success; used for `cfg.maint_runtime=none`.
  - All three implementations enforce the §8.2 hard caps **after** the runtime call returns success (defense-in-depth — if a human bypassed the agent and over-scaled in compose, the next decision tick scales it back down, with a `kind=scale_throttled, reason=manual_override_detected` audit event).
- [ ] **VRAM accounting source (binding).** Each predictor pod publishes `telemetry.v1{kind=device_probe, agent=<id>, vram_total_mb, vram_used_mb, device=cuda|rocm|npu|cpu}` once per heartbeat (Phase 11 contract). The scaler aggregates the latest probe per `(agent, host)` into `cfg.maint_scaler_vram_budget_mb` (computed = `Σ vram_total_mb − cfg.maint_scaler_vram_headroom_mb`, default headroom 1024). Before issuing a scale-up that would push `Σ vram_used_mb + (next−prev) × cfg.predictor_max_vram_mb` over the budget, refuse + emit `scale_throttled, reason=vram_budget_exceeded, observed:{budget_mb, projected_mb}`. CPU-only path bypasses VRAM checks entirely. Stale probes (`now − last_probe_at > 3 × heartbeat_sec`) are excluded from aggregation; if all probes are stale, scale-up of GPU-bound agents refuses with `reason=vram_telemetry_stale` (fail-safe).
- [ ] **Drift-driven warm-up (consumer of `maint.event.v1{kind=retrain_request}`).** When drift fires, the scaler may pre-warm a trainer pod via a `kind=scale_decision, target=trainer.v1, prev=0, next=1, reason=retrain_request_warmup`. The trainer remains a separate workload — the scaler never publishes weights and never publishes `kind=retrain_approve`. Warm-up is keyed on `(target_agent, retrain_request.request_id)` so concurrent drift events do not stack pods.
- [ ] **Observability.** Exposes counters `maint_scaler_decisions_total{agent,reason,outcome}`, gauges `maint_scaler_desired_replicas{agent}` and `maint_scaler_vram_budget_mb{host}`, and a histogram `maint_scaler_runtime_call_seconds{controller,outcome}` via the existing telemetry agent.

### 8.3 Backup / retention agent (`maint.backup.v1`)

> Nightly Postgres dumps + restore-verify + TTL prune for everything that has a TTL: quarantine samples, schema snapshots, drift windows on disk (Phase 9), DLQ entries, opsctl audit. PII erase is a sibling operation on the same trust path.

- [ ] **Scheduler.** Job ticks via `AgentRunner` heartbeats (no extra process). The agent stores `cfg.maint_backup_cron` (default `0 3 * * *` UTC) and a stdlib-only cron evaluator (`xops/backup/cron.py` — supports `m h dom mon dow` with `*`/`,`/`-`/`/N`; **no `croniter` dep** to honor the `xops/` stdlib-preference doctrine; rejects unsupported syntax loud at boot). On each heartbeat, computes `next_due_at` from the **last successful run timestamp** (loaded from `data/backups/audit.csv` first row of the day; absent → epoch); fires when `now ≥ next_due_at`. **Wall-clock skew safety (binding).** Cron evaluation is wall-clock by definition (operators schedule "3 AM UTC", not monotonic offsets), but every fire records both `wall_clock_utc` AND `monotonic_ns_at_fire` to `data/backups/audit.csv`. If two consecutive ticks show `wall_clock_utc` going **backwards** by more than `cfg.maint_backup_clock_step_back_alert_s` (default 300s — covers small NTP corrections, traps real backwards steps), the agent refuses to fire until the next forward-progress wall-clock tick passes the prior recorded `next_due_at`, AND emits `sec.alert.v1{kind=backup_clock_skew, severity=error, observed:{step_back_s, last_fire_at, now_at}}`. Forward leaps > 24h are also flagged (`kind=backup_clock_skew, severity=warn, scope=forward`) — the catch-up policy below handles them, the alert is operator visibility only. Idempotency on `(job_id, backup_date_utc)` ultimately absorbs both directions; the alert is the early warning. **Catch-up policy:** missed ticks (agent down across the cron time) trigger **one** make-up run on next start, marked `reason=catch_up` in the event; further missed ticks are coalesced (we only ever owe one backup, never N). If the make-up is more than `cfg.maint_backup_max_skew_h` (default 36h) late → emit `sec.alert.v1{kind=backup_age_alert, severity=error}` and run anyway.
- [ ] **Nightly dump.**
  - Skips if a successful run for today (UTC) already exists (idempotency on `(job_id, backup_date_utc)`).
  - `pg_dump -Fd -Z 9 --no-owner --no-privileges --jobs=cfg.maint_backup_pg_jobs` to a directory `cfg.maint_backup_dir/YYYY-MM-DD/negelir.dumpdir/`. **Format-jobs invariant:** `--jobs > 1` requires `-Fd` (directory format); `-Fc` (custom) is single-threaded. The agent picks `-Fd` whenever `pg_jobs > 1`, else `-Fc` to a `negelir.dump` file. Boot validation refuses misconfiguration.
  - **PII-aware dump policy.** `quarantine_samples.raw_bytes_b64` is **excluded** from the nightly dump via `--exclude-table-data=quarantine_samples` and re-included as a sanitized projection (`(quarantine_id, source, rule_id, hit_fingerprint, created_at, erased_at)`) written to `negelir.quarantine_meta.csv` alongside the dump. Right-to-erasure invariant: a backup older than the quarantine TTL never contains pre-erasure raw bytes (Phase 16 GDPR-style stance per [`design/SECURITY.md`](../design/SECURITY.md)). **Restore semantics (binding):** the projection CSV is **operator-only forensic evidence**, not a `pg_restore` input. After restore, `quarantine_samples` will be empty (schema present, no rows) — this is by design; the table re-fills from live ingest. The CSV is preserved in the dump dir under operator-managed access (mode 0600, never auto-loaded). DoD test asserts post-restore row-count is zero AND the CSV is parsable + matches the row count that *would* have been included pre-erasure.
  - **PG role least-privilege (binding).** The agent connects via a dedicated PG role `negelir_backup` granted **`pg_read_all_data`** + `USAGE` on `pg_catalog` only — never the application role. Boot validation runs `SELECT current_user, current_setting('is_superuser')` and refuses to start if `current_user != 'negelir_backup'` or if it is a superuser. Migration `011_backup_role.sql` (additive, idempotent `CREATE ROLE IF NOT EXISTS`) lands the role with **`CONNECTION LIMIT cfg.maint_backup_pg_conn_limit`** (default = `maint_backup_pg_jobs + 2` headroom); boot validation re-asserts `pg_jobs + 2 ≤ pg_role_connlimit` and refuses on misconfig (prevents `pg_dump --jobs=N` from starving the application connection pool — the cap is enforced server-side, not client-side). Production secrets supply only the backup-role password to the agent. **Password rotation runbook:** `ops.backup-rotate-pg-secret` documented at `docs/guides/backup_runbook.md` rotates the secret via the same `K8s Secret` patch + agent rolling restart that key-rotation uses; rotation cadence target is ≤ 90d (operator-driven, not automated in v1; cadence-overdue gauge `maint_backup_pg_secret_age_days` exposed at telemetry, alert at 100d).
  - Optional encryption-at-rest: if `cfg.maint_backup_encryption_key_dir` (a **directory** of versioned recipient public keys named `keys.vN.age.pub`, plus an optional `keys.vN.recipients.txt` listing **multiple** age recipients per version for K-of-N decryption resilience) is set, the dump is encrypted by streaming `tar -cf - <dump_dir>/ | age -R <recipients...> > <dump>.tar.age` (the `-Fd` directory format demands tar-then-encrypt; encrypting per-file would leak structure metadata). Decryption inverts: `age -i <key> -d | tar -xf -`. **Two-class recipient model (binding — fixes the prior "private keys never enter cluster" contradiction with restore-verify needing decrypt access).** Each `keys.vN.recipients.txt` MUST split into two named groups:
    - **DR-class recipients** (≥ `cfg.maint_backup_min_dr_recipients`, default 2 in prod): private halves live **strictly off-cluster** (operator hardware token / KMS / sealed paper). Used only for human-driven disaster recovery (`ops.restore --confirm-destructive`). NEVER materialize in any pod, ConfigMap, or Secret.
    - **Verify-class recipient** (exactly 1, optional in mock, mandatory in prod when `cfg.maint_backup_verify_mode=full`): private half lives in a Kubernetes Secret named `negelir-backup-verify-key` in the dedicated `negelir-maint-verify` namespace, mounted **only** by the SidecarVerifier Job (RBAC: `get` on this single named Secret, no `list`). The verify key is rotated **per dump** by default (ephemeral verify keys; `cfg.maint_backup_verify_key_rotate_per_dump`, default `true` in prod) — agent generates a new keypair, encrypts to it alongside the DR recipients for the current dump only, deletes the private half from the Secret immediately after verify completes. Compromise of the verify key buys the attacker access to **at most one** dump, never historical archives. Compose-mode (`LocalSubprocessVerifier`) reads the verify key from a 0600 file under `cfg.maint_backup_dir/.verify_keys/vN.age.key` (operator-protected, gitignored).
    Audit row `maint_audit_log{kind=backup_verify_key_rotated, dump_date, recipient_fingerprint}` per rotation. Boundary test rejects a `recipients.txt` that does not classify each recipient into exactly one of `{dr, verify}`. **Multi-recipient default within DR class:** at least `cfg.maint_backup_min_dr_recipients` (default 2 in prod, 1 in mock) — single-recipient DR keys are a single point of disaster-recovery failure. Old key versions are kept on disk for restore — **never deleted automatically**. Key rotation is operator-driven: `ops.backup-rotate-key` adds a new `vN+1` and re-emits a `maint.event.v1{kind=backup_key_rotated, prev_v=N, new_v=N+1, dr_recipient_count, verify_recipient_count}` event. **DR public keys are repo-checkable (`infra/maint/backup_keys/dr/`); verify public keys are agent-generated and never committed; both private halves enter the cluster only under the rules above.** If the dir is unset, dump is left unencrypted with a stderr warning + `sec.alert.v1{kind=backup_unencrypted, severity=warn}` (debounced daily); in prod profile (`cfg.maint_runtime != none` AND `cfg.profile=='prod'`) unencrypted dumps are **refused** outright (`fail_safe_no_encryption_in_prod`).
  - **Checksum ordering (binding).** SHA-256 is computed **after** the dump file is `fsync`'d to disk (the disk is the integrity boundary, not memory). The checksum is then recorded in `negelir.checksum.txt` next to the dump and re-verified by reading from disk **before** restore-verify starts. A mid-write power loss therefore fails closed.
  - `kind=backup_started{job_id, backup_date_utc, reason}` published before dump; `kind=backup_completed{size_bytes, duration_ms, checksum_sha256, encrypted: bool, encryption_key_version: int|null}` after.
- [ ] **Restore-verify (mandatory daily, runtime-aware).**
  - **Mechanism is pluggable.** A `RestoreVerifier` Protocol with two implementations:
    - `LocalSubprocessVerifier` (compose-only, dev): spawns an ephemeral `postgres:16-alpine` container via the same compose file (`docker compose -f <file> --profile restore-verify up -d`) on a dedicated profile that is **never** part of the default `make up`. Requires the same docker-socket caveat as `ComposeController` and is forbidden in prod.
    - `SidecarVerifier` (Phase 14): a Kubernetes `Job` template (committed at `infra/k8s/jobs/restore-verify.yaml`) is created via the API server using a least-privilege ServiceAccount (`create,get,list,watch,delete` on `jobs` and `delete` on `persistentvolumeclaims` in a dedicated namespace `negelir-maint-verify`). The Job mounts the **backup PVC read-only** (or a VolumeSnapshot-cloned RWO) at `/dump` and an **ephemeral PVC** for the throwaway Postgres at `/var/lib/postgresql/data` (`emptyDir.sizeLimit = 2× last_dump_size`). The agent watches the Job to completion, scrapes its `pg_restore` exit code + verify-suite output, then deletes the Job AND its ephemeral PVC. **Crash-cleanup invariant:** on agent restart, an `OwnerReference`-scoped sweep deletes orphaned `negelir-maint-verify/restore-verify-*` Jobs+PVCs older than `cfg.maint_backup_verify_orphan_ttl_h` (default 6h) at boot — prevents PVC leaks if the agent died mid-watch. Sweep emits `maint.event.v1{kind=backup_verify_orphan_swept, count}` for audit.
  - `pg_restore --jobs=...` the new dump (or `pg_restore --list` first to validate the TOC if the verify mode is downgraded by `cfg.maint_backup_verify_mode ∈ {full, toc_only}` — `toc_only` is a forward escape hatch for very-large-DB ops, default `full`).
  - Run a fixed verification suite (`xops/backup/verify.sql`): `SELECT count(*) FROM <each table>`, all migrations applied (`SELECT max(version) FROM schema_migrations` matches the in-tree max from `migrations/*.sql`), round-trip reads on the most recent `match_normalized` and `quarantine_samples` rows, and a sanity probe against `pattern_allowlist` + `maint_audit_log`.
  - On failure: emit `sec.alert.v1{kind=backup_verify_failed, severity=critical}` (bypasses debounce), keep the dump file (do **not** prune), exit non-zero. Operator must investigate. **Quarantine the bad dump:** rename the dump dir to `<date>.failed/` so the next nightly cron does not see it as today's success and the disk-usage guard accounts for it; also set `maint_backup_age_hours{verified=true}` based on the **last verified** dump only (failed dumps do not satisfy the age gauge — silent-failure mode covered).
  - On success: emit `kind=backup_completed{verified: true}` and prune dumps older than `cfg.maint_backup_retention_days` (default 14) and `cfg.maint_backup_retention_weeks` (default 4 weekly Sunday dumps kept — GFS-light). All key versions referenced by retained dumps are also retained.
- [ ] **Weekly cold-verify (binding — silent storage rot).** Once per `cfg.maint_backup_cold_verify_cron` (default `0 5 * * 0` UTC, Sunday 05:00 — after the nightly), the agent picks the **oldest still-retained Sunday dump** and runs the same restore-verify pipeline against it (separate `RestoreVerifier` invocation, separate ephemeral PVC). Catches bit-rot / S3 lifecycle bugs / silent encryption-key loss long before the dump is needed for real DR. Outcome emits `kind=backup_cold_verify_completed{dump_date, duration_ms, verified:true}` or `kind=backup_cold_verify_failed{dump_date, error}` + `sec.alert.v1{kind=backup_verify_failed, severity=critical, scope=cold}`. Cold-verify failures DO NOT prune the dump (operator decides).
- [ ] **Restore runbook (`ops.restore` — binding).** Operator-driven, never automated. `make ops.restore DATE=YYYY-MM-DD [TARGET=<conn-string>] [DRY_RUN=1]` invokes `ops.restore`, which: (a) refuses without `--confirm-destructive=<token>` (§8.1 destructive gate); (b) refuses if `TARGET` resolves to the live application Postgres unless `--confirm-overwrite-live` is also passed (default behavior is to restore into an ephemeral target named `negelir_restore_<date>` that the operator then promotes manually); (c) decrypts using a **DR-class** private key (verify-class keys are explicitly rejected at decryption — surface error `dr_key_required`); (d) pipes `age -d | tar -xf - | pg_restore --jobs=cfg.maint_backup_pg_jobs --no-owner --no-privileges`; (e) emits `maint.event.v1{kind=backup_restore_started{target, dump_date, requested_by}}` and `kind=backup_restore_completed{target, duration_ms, exit_code}` to the bus AND `maint_audit_log`; (f) runs `xops/backup/verify.sql` post-restore to confirm row counts match the dump's recorded checksums. Documented at `docs/guides/backup_runbook.md` with worked examples for the three scenarios (DR-from-offsite, point-in-time-from-archive, accidental-table-drop-recovery).
- [ ] **TTL prune jobs (scheduled at the same cron tick, after the dump).**
  - All prunes execute as a **single transaction per table** with a `LIMIT cfg.maint_backup_prune_batch` (default 10 000) loop until 0 rows; prevents long table locks.
  - `quarantine_samples` rows older than `cfg.sec_quarantine_ttl_days` (default 30) → DELETE. Emits `kind=quarantine_pruned{table, row_count, oldest_kept_at}`.
  - `schema_snapshots` rows older than `cfg.maint_schema_snapshot_retention_days` (default 90) → DELETE. Phase 4 snapshots fed by `storage.v1` accumulate.
  - `dlq_entries` (Phase 9 Postgres backend) older than `cfg.swarm_dlq_pg_retention_days` (default 14) → DELETE.
  - `pattern_allowlist` rows with `expires_at < now()` → DELETE (one event `kind=pattern_allowlist_expired{count}`).
  - `opsctl_audit` and `maint_audit_log` rows older than `cfg.maint_audit_retention_days` (default 365) → DELETE. Note the longer retention — audit trail value is highest.
- [ ] **PII erase (consumer of `maint.event.v1{kind=quarantine_erase, target=<client_id>}`).**
  - Loads matching `quarantine_samples` rows by `client_id`, sets `raw_bytes_b64 = NULL`, sets `erased_at = now()`, leaves `quarantine_id` row in place for audit.
  - Emits `maint.event.v1{kind=pii_erased, target=<client_id>, table=quarantine_samples, row_count, erased_at}` and a corresponding `maint_audit_log` insert (right-to-erasure traceability per [`design/SECURITY.md`](../design/SECURITY.md)).
  - Acks via `maint.ack.v1` with `accepted=true, reason="erased <N> rows"` or `accepted=true, reason="no rows matched"` (the absence of rows is a successful no-op, not an error — a client_id that was never seen is the desired state).
- [ ] **Disk-usage guard.** Before each dump, refuses to start if free space on `cfg.maint_backup_dir` < `max(2× last_dump_size, cfg.maint_backup_min_free_gb)` (default 5 GB headroom). Emits `sec.alert.v1{kind=backup_disk_pressure, severity=error}`. Refusal counts toward the catch-up debt — next tick retries.
- [ ] **Backup-age gauge.** Telemetry exposes `maint_backup_age_hours{verified=true|false}` (now − last successful verified backup); a separate watchdog rule fires `sec.alert.v1{kind=backup_age_alert, severity=error}` if the gauge exceeds `cfg.maint_backup_age_alert_h` (default 30h). Catches the silent-failure mode where the agent is alive but every dump is failing verify.
- [ ] **Safety floor.** TTL prunes are gated by `cfg.maint_backup_dry_run` (default `false` in prod, **`true` in mock profile**) — first run on a fresh dev stack must not delete data the operator hasn't seen yet. `dry_run=true` still emits the same events with `dry_run: true, would_delete_count: N` so test assertions stay symmetric.
- [ ] **Permissions.** All files in `cfg.maint_backup_dir` are written with mode 0600 (umask 0077 in the agent process); the parent dir is mode 0700. Verified at startup; refuses to start on looser perms.

### 8.4 Source-watcher SDK + LLM-summarizer graduation

> Phase 2.8 source-watcher migrates from `scheduler.py` cron loop to the swarm SDK. The deterministic differ + classifier stay authoritative; the LLM summarizer flips from `enabled=False` stub to a real client behind a model-pin gate.

- [ ] **SDK migration.** Subclass `Agent`; `subscribes=()` (still time-driven), `publishes=(SOURCE_WATCH_REPORT_V1,)` plus the existing `maint.event.v1{kind=baseline_reset}` and `proof.flag` surfaces. The internal scheduler stays — it now ticks via `AgentRunner` heartbeats instead of a standalone subprocess. Existing tests under `ai/swarm/source_watcher/tests/` retarget to the SDK harness; **classification rule outputs must be byte-identical pre/post migration** (golden-file regression test).
- [ ] **Summarizer graduation.** `cfg.source_watcher_summarizer_enabled` flips to `true` only when ALL of:
  - A non-`*-latest` model ID is configured at `cfg.source_watcher_summarizer_model_id` (CLAUDE.md doctrine — `*-latest` rejected at config validation).
  - The configured model is reachable from the agent's network namespace (probed at startup; failure → `enabled=False` runtime override + `sec.alert.v1{kind=summarizer_unreachable, severity=warn}`).
  - The deterministic differ has produced at least one non-empty `UpdatePlan` (the summarizer never narrates an empty diff).
- [ ] **Boundary test (binding).** AST-and-runtime scan asserting `summarizer.summarize(plan)` cannot mutate `plan.classification`, `plan.severity`, or `plan.fields_changed`. Returns Turkish narration string only. Existing test extended; failure on a future attempt to widen the summarizer's authority.
- [ ] **Cost cap (two-tier).** Per-call ceiling `cfg.source_watcher_summarizer_max_tokens_per_call` (default 4096 — clamps `max_tokens` on the API request itself, prevents a single bursty diff from eating the daily budget) AND per-day ledger `cfg.source_watcher_summarizer_max_tokens_per_day` (default 50 000). Either overflow → fall back to deterministic plan-derived string + `sec.alert.v1{kind=summarizer_cost_capped, severity=warn, scope=<per_call|per_day>}` (debounced daily per scope). Day boundaries are UTC midnight; counter persisted at `data/maint/summarizer_ledger.json` (mode 0600, atomic write via temp+rename) so restarts within a day do not reset the budget.
- [ ] **Versioning.** `source_watcher` chart key bumps `1.x → 2.0.0` on this graduation (per ROADMAP §2.8 note). The `swarm` chart key bumps minor for the §8.x landings.

### 8.5 DLQ supervisor (`maint.dlq.v1`)

> Drains, replays, escalates DLQ entries. The DLQ wires were laid in Phase 3.5 (`<topic>.dlq` Redis stream, `swarm_dlq_max_len`); Phase 8 ships the consumer that actually reads them.

- [ ] **Topic allow-list (binding).** The supervisor does **not** auto-subscribe to every discovered `<topic>.dlq`. The set is the intersection of `swarmctl topics` and `cfg.maint_dlq_replay_topics_allow` (a config list, default = `{predict.request, predict.vote, predict.final, scrape.classified, match.normalized, drift.v1, freshness.v1, cache.v1}`). **Sec/PII topics are excluded by default** — `sec.quarantine.v1.dlq`, `qa.request.v1.dlq`, and `sec.alert.v1.dlq` are never auto-replayed (replaying a quarantined raw payload would re-leak it through the wire). Their DLQs are still drained for telemetry (depth gauge), but operator-only replay through `ops.dlq-replay --topic sec.quarantine.v1.dlq --id <id> --confirm-pii --confirm-destructive=<token>` is the sole path. **Allow-list change mid-replay (binding).** The allow-list snapshot is taken at *tick start*; in-flight replays for a topic that has just been removed from the allow-list complete normally for entries already pulled this tick (avoids partial-batch poisoning), but no new entries from that topic are pulled in subsequent ticks until the topic is re-added. A `maint.event.v1{kind=dlq_topic_disabled_drained, target=<topic>, in_flight_count}` event records the transition. Conversely, a topic newly added to the allow-list is included in the **next** tick's round-robin (one-tick latency, deterministic — test-anchored).
- [ ] **Read loop.** Subscribes to the allow-listed `<topic>.dlq` streams (re-evaluated on every heartbeat — new topics are picked up live, but only if they pass the allow-list). Per-topic concurrency bounded by `cfg.maint_dlq_concurrency` (default 4). The read loop is **async-cooperative**: a per-tick budget of `cfg.maint_dlq_max_replays_per_tick` (default 50) bounds the work done before yielding back to the heartbeat — guarantees the agent never misses its `swarm_heartbeat_sec` deadline regardless of backlog depth.
- [ ] **Topic fairness (binding).** Within a single tick, the per-tick budget is split **round-robin across allow-listed topics with non-empty DLQs** — never FIFO over the union stream — so a single high-volume DLQ cannot starve smaller ones. The order is `sorted(active_topics)` for determinism (test-anchored). Per-topic share is `max(1, budget // len(active_topics))`; remainder distributed to topics in the same sorted order. Proof test: feed 1000 entries to `predict.vote.dlq` and 5 to `freshness.v1.dlq`, assert the small DLQ drains within `ceil(5 / per_tick_share)` ticks (no starvation).
- [ ] **Poison-pattern detection.** When `≥ cfg.maint_dlq_consumer_broken_threshold` (default 5) **distinct** entries on the same topic escalate to `dlq_escalated` within `cfg.maint_dlq_consumer_broken_window_s` (default 600s), emit `sec.alert.v1{kind=consumer_likely_broken, severity=error, subject=<topic>}` (debounced per-topic) and **freeze replays** for that topic until operator unblock via `ops.dlq-resume --topic <t>`. Distinguishes "one bad payload" (1 escalation, replay rest) from "consumer is structurally broken" (5 different payloads all fail). Prevents the supervisor from being a load amplifier on a downed consumer.
- [ ] **Replay policy** (per entry, per topic). `dlq_replay_count` is a **payload-level** field (NOT an envelope header — Envelope is sealed to the Phase 3 fields per §0). The supervisor wraps the replayed message in `{__dlq_meta: {dlq_replay_count, dlq_first_failed_at, dlq_topic_origin}, ...original_payload}` ONLY for topics whose payload schema explicitly opts in via `additionalProperties: {__dlq_meta: ...}`. For schemas that are sealed (`additionalProperties: false`), the metadata rides as **bus-level Redis Stream entry headers** read by the supervisor on its next visit (out-of-band of the envelope/payload — preserves the schema contract).
  - First DLQ visit → wait `cfg.maint_dlq_replay_backoff_s` (default 60s), republish to the original topic with the same `request_id` (in payload, per §0) + `dlq_replay_count=1` (per the rule above).
  - Second DLQ visit → wait `cfg.maint_dlq_replay_backoff_s × cfg.maint_dlq_backoff_factor` (default 60s × 4 = 240s), republish with `dlq_replay_count=2`.
  - Third DLQ visit → escalate: emit `sec.alert.v1{kind=dlq_escalated, severity=error, subject=<topic>}` + `maint.event.v1{kind=dlq_escalated, target=<topic>, dlq_entry_id, original_envelope}`. Stop replaying. Operator decides via `ops.dlq-replay --topic <t> --id <id>` (forced replay, or `--drop` to acknowledge and remove).
- [ ] **Per-topic rate limit.** No more than `cfg.maint_dlq_replay_rps` (default 10) replays per topic per second — keeps a poisoned message from being thrashed against a still-broken consumer. Token-bucket per topic; bucket state is part of the bounded-state cap below.
- [ ] **Backlog-pressure damping.** When `<topic>.dlq` depth exceeds `cfg.maint_dlq_backlog_alert` (default 1000), the agent emits `sec.alert.v1{kind=dlq_backlog_high, severity=warn, subject=<topic>}` (debounced) and **drops the per-topic replay rate to `replay_rps / 4`** until depth halves (positive feedback loop avoidance — a broken consumer should not be flooded harder).
- [ ] **Idempotency.** Replays carry the original `request_id` so the consumer's existing idempotency guard (Phase 6 ledger, Phase 7 dedup, Phase 5 consensus single-publication) collapses dupes naturally. Boundary test: replaying an already-accepted `predict.vote` does not produce a second `predict.final`.
- [ ] **Audit.** Every replay emits `maint.event.v1{kind=dlq_replayed, target=<topic>, dlq_entry_id, replay_count}`.
- [ ] **Bounded state.** In-memory map of `(topic, dlq_entry_id) → (last_replay_at, replay_count)` capped at `cfg.maint_dlq_state_max` (default 100 000) with insertion-order LRU (mirrors the Phase 6 drift bounded-state pattern). Eviction is silent — escalation already covered the long-lived poison cases. **Eviction guard:** if the cap is hit AND no entry is older than `cfg.maint_dlq_replay_backoff_s × cfg.maint_dlq_backoff_factor × 3` (i.e. the cap is filling faster than the backoff window evicts), emit `sec.alert.v1{kind=dlq_state_pressure, severity=warn}` — the cap is undersized for current traffic.

### 8.6 Internal schema-drift sentinel (`maint.schema.v1`)

> **Re-scoped from the original §8.1.** Scraper-selector healing moved to Phase 17 patcher (`extractor`/`schema` scopes). What stays here: detect drift between (a) JSON Schemas in `ai/swarm/sdk/schemas/` and live payloads on the bus, (b) Postgres column sets vs the migration-derived expected set, (c) `payloads.py` dataclass shape vs the matching JSON Schema. Phase 8 detects + reports; humans (or Phase 17 patcher under `migration` scope) fix.

- [ ] **Detector A — payload vs schema.** Tap `telemetry.v1`'s sample stream (Phase 4.6 already mirrors a configurable %); for each sampled envelope, run `swarm.sdk.schemas.validate(topic, payload)`. On mismatch → `maint.event.v1{kind=schema_drift_detected, target=<topic>, errors[], sample_envelope_id}` (debounced per `(topic, error_signature)` for `cfg.maint_schema_debounce_s`, default 3600). Sample rate is `cfg.maint_schema_sample_rate` (default 0.01) — full validation is not free; trades coverage for CPU.
- [ ] **Detector B — Postgres column drift.** Once per `cfg.maint_schema_pg_check_interval_s` (default 1h), run `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public'`, compare to the expected set derived from `migrations/*.sql` parsing. Drift → same `kind=schema_drift_detected, target=<table>`. The migration parser uses `sqlglot` (already a candidate dep for Phase 17 patcher) when available, falling back to a tolerant regex parser that handles `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN`, and inline `CHECK` constraints. **False-positive guard:** the parser tracks `unknown_constructs` (e.g. `CREATE FUNCTION`, partial-index `WHERE`); when a table's expected column set was assembled with any unknown_constructs in scope, a drift event for that table is downgraded to `severity=info` (not `warn`) and prefixed `parser_uncertain:` so an operator can distinguish parser failure from real drift.
- [ ] **Detector C — dataclass vs schema.** AST scan at startup asserts every `@dataclass` in `payloads.py` has a matching JSON Schema with the same field set + types. **Scope of failure:** drift fails the *Phase 8 schema-sentinel agent* startup only (loud `SystemExit(1)` from the agent module's `__main__`); other agents in the registry are not killed. The Supervisor emits `sec.alert.v1{kind=schema_drift_detected, severity=critical}` for the missing agent. This contains the blast radius — code/schema drift is a release-time bug for one tracked surface, not a swarm-wide outage.
- [ ] **Out of scope (binding).**
  - **Auto-derive selectors / extractors** — Phase 17 patcher only.
  - **Auto-apply migrations** — humans only. The sentinel emits the event; nothing in v1 runs `psql -f migrations/NNN_*.sql` unattended. (`cfg.maint_schema_auto_apply_enabled` exists in config for forward compatibility; defaults to `false` and is checked at startup with a warning if `true`.)

### 8.7 Pattern false-positive feedback loop (`maint.sec.v1` slice)

> Promotes the §7.x deferred FP loop. Operator clears a quarantined sample → the rule that triggered it adds to a per-source allowlist (autolearn-on) **or** queues for explicit operator approval (autolearn-off, default).

- [ ] Subscribes to `maint.event.v1{kind=quarantine_clear, target=<quarantine_id>}` (Phase 7 publisher hook stub).
- [ ] Resolves `quarantine_id → (source, rule_id, hit_substring)` from `quarantine_samples`. Computes `hit_fingerprint = sha256(NFC(hit_substring))[:16]` (deterministic, language-stable, never stores the raw substring in the live allowlist row — PII contains-checks are operator-only via `ops.allowlist-show`).
- [ ] **Two-mode insertion.** On-disk `state` is encoded as `CHAR(1) IN ('p','a','e')` (per migration 010); the `_ack_routing.py`-style `_state_codec.py` maps it to bus-event strings `'pending'|'active'|'expired'` (single source of truth, boundary-tested). Bus events ALWAYS use the long form; SQL ALWAYS uses the short form.
  - `cfg.sec_input_pattern_autolearn_enabled = true`: insert with `state='a', expires_at = now() + cfg.maint_sec_allowlist_ttl_days, added_by_request_id`. Emits `kind=pattern_allowlist_added`.
  - `cfg.sec_input_pattern_autolearn_enabled = false` (default): insert with `state='p', expires_at = NULL, proposed_at = now()`. Emits `kind=pattern_allowlist_pending` (informational; **does not** count as `added`). Operator promotes via `ops.allowlist-approve --id <row_id> --ttl-days N` → row flips to `state='a'` and a `kind=pattern_allowlist_added` event fires. Pending rows older than `cfg.maint_sec_allowlist_pending_ttl_days` (default 30) are pruned by §8.3.
- [ ] `sec.input.v1` reads only `state='a' AND (expires_at IS NULL OR expires_at > now())` rows on each pattern hit — if `(source, rule_id, hit_fingerprint)` matches, the hit is suppressed (counted in `sec_input_allowlist_hits_total` for visibility, never silently lost). The cache is refreshed via mtime-equivalent on a `pattern_allowlist_version` row in a metadata table (poll interval `cfg.sec_input_allowlist_reload_s`, default 60s) — same pattern as §7.4 sec.config fan-out (deliberately mtime-style, not bus fan-out). **Cache-reload race:** the version-row read uses `REPEATABLE READ` snapshot isolation against the same connection that subsequently reads `pattern_allowlist`, so promote-while-evaluating either sees the old version-row + old cache (next poll tick reloads) OR the new version-row + new cache (atomic refresh) — never a half-applied state. Proof test in §8.9 forces the race with `pg_advisory_lock` interleaving.
- [ ] **SQL-injection guard.** All inserts/queries use parameterized statements (`psycopg.sql.Composed`, never f-string concat). Boundary test: AST scan of `ai/swarm/agents/maint/sec.py` rejects `cursor.execute(f"...")` and `"%s" %` patterns inside SQL builders. The hit_substring is **never** placed in a SQL `LIKE` or `=` clause — only the fingerprint hash is.
- [ ] Emits `maint.event.v1{kind=pattern_allowlist_added|pattern_allowlist_pending|pattern_allowlist_expired}` accordingly. Expiry sweep runs at the §8.3 cron tick.

### 8.8 Sec-denylist sweeper (`maint.sec.v1` slice)

> Promotes the §7.3 deferred "halve TTL of oldest decile" sweeper. Activates only under cap-mode pressure.

- [ ] Subscribes to `sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}` (Phase 7 §7.3 publisher).
- [ ] On consume, runs new Lua script `infra/redis/lua/sec_denylist_decimate.lua` (VERSION + SHA256 header + `make verify.lua` CI gate + embedded copy at `server/internal/sec/embedded/` + `embedded_parity_test.go`, exactly like the existing two scripts):
  - Atomically (single Lua call — no client-side round-trips, no race with concurrent denylist mutations) identifies the oldest decile of `sec:denylist:_zset` members by score (= `expires_at_ms`).
  - Halves their remaining TTL: `new_score = now_ms + (old_score - now_ms) / 2`; `PEXPIREAT sec:denylist:<subject> new_score` AND `ZADD sec:denylist:_zset new_score subject` (single transaction — zset and key TTL never disagree).
  - **Cap-flag fast-clear.** If post-decimation `ZCARD < cfg.sec_denylist_cap × cfg.sec_denylist_cap_exit_ratio` (computed in Lua from the passed-in cap arg), executes `DEL sec:denylist:capped` and returns `cap_cleared=true`. Without this, the gateway's subnet-mode would persist for up to the 300s flag TTL even after the actual pressure drops — fast-clear is the user-facing reliability win.
  - **Concurrency safety.** A second decimate call entering while the first is mid-script is impossible (Redis Lua is atomic). Two *separate* alert consumers calling the script back-to-back are de-duplicated by the §8.8 hysteresis below; if hysteresis is bypassed (test path), the second call is still safe — the worst case is two halvings of the same TTL window, never an inconsistent zset.
  - **Mandatory args.** `now_ms` (ARGV[1]) and `cap` (ARGV[2]) are required; absence/zero returns `"error"` (mirrors the §7.3 v1.1.0 lesson — silent defaults broke lazy eviction).
  - Returns `{evicted_count, decile_size, new_zcard, cap_cleared: bool}` for audit.
- [ ] Emits `maint.event.v1{kind=denylist_decimate, target=<source>, evicted_count, decile_size, new_zcard, cap_cleared}` and a separate `kind=denylist_cap_cleared` only when `cap_cleared=true` (operator-facing signal that subnet-mode is over).
- [ ] **Decile-size boundary.** Decile is computed `decile_size = max(1, ZCARD // 10)`. When `ZCARD < 10`, decile_size = 1 (still meaningful). When `ZCARD == 0` the script is a no-op returning `evicted_count=0, decile_size=0, cap_cleared=false` (alert was spurious; agent records and debounces). Proof test covers both edges.
- [ ] **Hysteresis.** No more than one decimate per `cfg.maint_sec_decimate_min_interval_s` (default 300s) **globally** (single zset, single global pressure signal — per-subject hysteresis is meaningless for a global cap). Tracked in agent state, not Redis (state survives within a single agent process; `replicas: 1` enforced). Hysteresis state survives leader handover via the §8.10 `Leader` Protocol's `last_action_at` slot in the K8s Lease annotation (Phase 14 only); compose-mode handover is N/A (single replica per service).

### 8.9 Definition of Done

**Surface coverage:**

- [ ] All 6 §8.x agents implemented under `ai/swarm/agents/maint/` (transitional path; R2 `git mv` to `swarm/reactors/maint/`): `maint.scaler.v1`, `maint.backup.v1`, `maint.dlq.v1`, `maint.schema.v1`, `maint.sec.v1` (covers §8.7+§8.8), source-watcher SDK migration in place. Ops console at `xops/opsctl/`.
- [ ] All 24 new `maint.event.v1.kind` values + 3 new `sec.alert.v1.kind` values (per the §3.5 list above) join the §7.4 known-kinds set; producer-set allow-list updated; per-producer kind allow-list (`telemetry.v1` → `{maint_silence_alert}` only) pinned; boundary test green.
- [ ] `maint.ack.v1` topic + JSON schema landed; §3.5 wire-authority table grows by exactly one row (added in the same PR). Per-consumer ack semantics enforced by the central `_ack_routing.py` map (boundary test pins kind→consumer-set).
- [ ] New Lua script `sec_denylist_decimate.lua` carries VERSION + SHA256 header; `make verify.lua` CI gate covers it; embedded copy in `server/internal/sec/embedded/` synced; embedded-parity test green; Python reference `_python_reference_decimate` mirrors the Lua exactly (1000-tuple deterministic sweep parity, mirrors §7.7 v1.1.0 pattern).

**Idempotency / single-publication:**

- [ ] `maint.scaler.v1`: exactly one `scale_decision` per `decision_window_id` under at-least-once redelivery (idempotency test). Pre/post-restart double-publish window covered by leader-election (§8.10) at Phase 14 and acknowledged in v1 docs as "first 2 windows after restart may double-publish; absorbed by Postgres ledger at Phase 9".
- [ ] `maint.backup.v1`: re-running the daily cron tick after a successful run is a no-op (`backup_started` not emitted; idempotency test on `(job_id, backup_date_utc)`). Catch-up policy proof: agent down across cron time → exactly one make-up run, marked `reason=catch_up`. Two consecutive missed ticks coalesce to one.
- [ ] `maint.dlq.v1`: replaying an already-accepted entry does not produce a second downstream emission (negative test against `predict.vote → predict.final` path with redelivery).
- [ ] `maint.sec.v1` decimate: parallel triggers within `min_interval_s` collapse to one Lua call (hysteresis test).

**Bounded state / performance:**

- [ ] Scaler decision history capped at `cfg.maint_scaler_history_max` (default 1024) with insertion-order LRU.
- [ ] DLQ supervisor in-memory map capped at `cfg.maint_dlq_state_max`; cap-pressure alert fires when fill rate outpaces backoff (proof test).
- [ ] Pattern allowlist daily sweep removes expired rows; table size bounded by TTL × emission rate (no unbounded growth proof test); `pending` rows pruned at `pending_ttl_days`.
- [ ] DLQ read loop yields back to heartbeat within `swarm_heartbeat_sec` even with 10k backlog entries (loop-budget test, asserts no missed heartbeat).
- [ ] Backup TTL prune executes in batched transactions of `≤ maint_backup_prune_batch` rows (lock-hold-time test — no single statement holds a table lock > `cfg.maint_backup_prune_max_lock_ms`, default 500ms).

**Safety / hard caps:**

- [ ] Scaler refuses to exceed `cfg.maint_scaler_max_replicas[<agent>]` (per-agent) and `cfg.maint_scaler_global_max_replicas` (global). Triangle test covers the cfg keys; chaos test `make chaos-flap-replicas AGENT=consensus.v1` proves hysteresis (no back-to-back decisions inside `min_decision_interval_s`).
- [ ] Operator scale-pin honored for `≤ pin_max_ttl_s`; auto-scaler decisions during pin emit `scale_throttled, reason=manual_pin` and **do not** call the runtime (proof test on the runtime mock).
- [ ] VRAM-budget refusal proven via two scenarios: (a) all probes stale → `reason=vram_telemetry_stale`, (b) projected exceedance → `reason=vram_budget_exceeded`. CPU-only path bypasses VRAM checks (third scenario).
- [ ] Backup refuses to start when free disk < `max(2× last_dump, min_free_gb)`. Mock-profile dry-run defaults to `true`. Restore-verify failure keeps the dump and pages a critical alert. PII-aware dump: `quarantine_samples.raw_bytes_b64` is excluded by default (proof test reads the dump TOC and asserts the column is excluded).
- [ ] Backup file mode 0600, parent dir 0700 (proof test stats the artifacts).
- [ ] Backup checksum is computed post-`fsync` and re-verified pre-restore (kill-9 mid-dump test: post-restart, the partial dump is detected via missing/short checksum and re-run, never falsely considered "completed").
- [ ] DLQ replay rate per topic ≤ `cfg.maint_dlq_replay_rps`; allow-list excludes `sec.quarantine.v1.dlq` / `sec.alert.v1.dlq` / `qa.request.v1.dlq` from auto-replay (boundary test). Operator-only replay path requires `--confirm-pii`.
- [ ] Auto-coder `maint.coder.v1` is **not** present (it is Phase 17 patcher's job). AST scan in CI rejects any `from swarm.agents.maint.coder` import.
- [ ] Schema sentinel Detector C drift fails only the schema-sentinel agent's startup, not the registry boot (negative test: inject a synthetic dataclass-vs-schema mismatch, assert other agents in the same registry start successfully).

**Boundary discipline (`test_boundary_discipline.py` extensions):**

- [ ] `maint.event.v1` producer set ⊆ `{drift.v1, ops_console, maint.scaler.v1, maint.backup.v1, maint.dlq.v1, maint.schema.v1, maint.sec.v1, source_watcher}` (loosened from the §7 set by exactly the Phase 8 reactors).
- [ ] `maint.ack.v1` producer set ⊆ `{any registered consumer of maint.event.v1}`; consumer set ⊆ `{ops_console}` (operator waits for acks; agents do not consume each others' acks).
- [ ] `sec.denylist.v1` sole producer is still `sec.rate.v1` (§8.8 sweeper publishes via Lua under the existing key prefix; no new direct producer of the topic).
- [ ] Ops console publishes only on `maint.event.v1` (and reads `maint.ack.v1`); never on `sec.*`, `predict.*`, `freshness.*`, `match.*`.
- [ ] `xops/opsctl/**.py` AST-clean of `psycopg`/direct `redis.Redis.*` mutators / `subprocess` invocations of `psql`/`redis-cli`.
- [ ] `ai/swarm/agents/maint/sec.py` AST-clean of unparameterized SQL (no `cursor.execute(f"...")`, no `"%s" %` inside SQL builders — SQL-injection guard for the pattern_allowlist path).
- [ ] Source-watcher summarizer cannot mutate classifier output (existing boundary test extended to cover the SDK-migrated path).

**Observability + visibility:**

- [ ] Every Phase 8 agent appears in `swarmctl ps`; `maint.event.v1`, `maint.ack.v1`, and all `<topic>.dlq` streams in `swarmctl topics`.
- [ ] Telemetry watch set extended to include `MAINT_ACK` (counters surface per-consumer ack latency + accepted/rejected ratios). Phase 4.6 watch-set test asserts.
- [ ] Live-emission JSON-Schema validation covers every Phase 8 emit (`test_phase8_swarm_demo_end_to_end`, mirroring the Phase 4 / Phase 6 live-emission probe pattern).
- [ ] `make swarm.demo` (extended) walks one `ops.denylist-clear` round-trip through the bus and asserts the ack latency budget (`< cfg.opsctl_ack_timeout_ms`), and one full `--dry-run` path that publishes nothing.
- [ ] Dead-mans-switch (§8.10) fires `kind=maint_silence_alert` if no `maint.event.v1` has been observed in `cfg.maint_silence_alert_h` (default 24h); proof test forces silence and asserts the alert.
- [ ] `maint_backup_age_hours` gauge surfaces; `kind=backup_age_alert` fires past threshold (proof test).

**Phase 12 chaos catalogue stubs:**

- [ ] Stub rows in `docs/testing/phase12_catalogue.md` for `chaos-fill-dlq`, `chaos-flap-replicas`, `chaos-corrupt-dump`, `chaos-disk-pressure-backup`, `chaos-stale-vram-probes`, `chaos-poison-quarantine-dlq`, `chaos-bus-partition-opsctl`, `chaos-leader-split-brain`, `chaos-maint-plane-lag`, `chaos-bus-circuit-breaker`, `chaos-pvc-mid-restore-verify`, `chaos-clock-step-back`, `chaos-offsite-target-down`, `chaos-bit-rot-old-dump`, `chaos-pg-conn-pool-starve` (one row per check, body = "TBD — implementation pending Phase 12"). Mirrors the Phase 7.4 catalogue-stub pattern; flips fully green when Phase 12 fills the bodies in.

**Second-pass proof tests (deep-review additions):**

- [ ] **Empty expected-ack set rejected.** `ops.<cmd>` with a `kind` no consumer accepts exits 5 (`no_consumer_for_kind`) BEFORE bus publish; envelope is not visible on `maint.event.v1`.
- [ ] **Re-entrancy lock.** Two parallel `ops.denylist-clear --target X.X.X.X` shells: exactly one wins the per-`(host,kind,target)` `flock`; the other exits with a `lock_held` error code; no double publish on the bus.
- [ ] **Spool ordering + corruption.** Bus-down spool: 10 envelopes appended in order, then bus restored — flush re-publishes in append order (asserted via `request_id` sequence). Corrupt one spool file mid-byte; flush skips it loud (`spool_entry_corrupted` alert) and continues with the rest.
- [ ] **Decision window post-restart.** Restart `maint.scaler.v1` mid-window; assert the post-restart `pod_instance_id` differs from the pre-restart one and the post-restart `scale_decision` events do not collide with pre-restart ledger entries on `(agent, decision_window_id)`.
- [ ] **K8s verify-Job orphan cleanup.** Simulate agent crash mid-watch (kill -9 during `pg_restore`); on next agent boot, assert the orphaned Job + ephemeral PVC under `negelir-maint-verify` are deleted within `verify_orphan_ttl_h` and `kind=backup_verify_orphan_swept` is published exactly once.
- [ ] **Failed dump quarantined.** Force `pg_restore` failure (corrupt the TOC); assert dump dir is renamed to `<date>.failed/`, next cron does not skip the day, age gauge keeps reporting from the **last verified** dump.
- [ ] **DLQ topic fairness.** 1000 entries on `predict.vote.dlq` + 5 on `freshness.v1.dlq`; small DLQ drains within ⌈ 5 / per_tick_share ⌉ ticks; ratio of replays per tick across topics is ≤ 1 + remainder.
- [ ] **DLQ poison-pattern alert.** Feed 5 distinct payloads on one topic that all escalate within `consumer_broken_window_s`; assert `consumer_likely_broken` fires exactly once (debounced) AND replays for that topic freeze; `ops.dlq-resume --topic <t>` clears the freeze.
- [ ] **DLQ payload-vs-schema discipline.** For schemas with `additionalProperties:false`, assert the supervisor does NOT inject `__dlq_meta` into the payload (ride out-of-band on Redis Stream entry headers); for opt-in schemas, assert it does. Payload schema validation passes both ways.
- [ ] **Per-call summarizer cap.** Force a single 200k-token diff; assert API request `max_tokens ≤ 4096`, fall-back deterministic narration is published, `summarizer_cost_capped{scope=per_call}` fires; daily counter increments by `≤ max_tokens_per_call`.
- [ ] **Allowlist promote-while-evaluating race.** Use `pg_advisory_lock` to interleave: operator promotes `pending→active` while `sec.input.v1` is mid-evaluation. Assert the eval sees a self-consistent snapshot (either old version-row + old cache OR new + new), never a split state. Retry under load 100×.
- [ ] **Decimate boundary cases.** (i) `ZCARD == 0` → no-op, returns `evicted_count=0, decile_size=0, cap_cleared=false`. (ii) `ZCARD < 10` → `decile_size=1`, evicts exactly 1. (iii) Post-decimation `ZCARD == cap × exit_ratio` exactly → `cap_cleared=true` (boundary inclusive).
- [ ] **Decimate cap-flag fast-clear under contention.** Concurrent denylist mutations during decimate (Lua atomicity); assert `sec:denylist:capped` is DELETE'd exactly once when the post-script ZCARD crosses the threshold; gateway transitions out of subnet-mode within one poll tick.
- [ ] **Maint plane lag watchdog.** Inject 6s consumer lag on `maint.event.v1` → tier-1 shedding + 1 alert. Ramp to 70s → tier-3 observer mode + 1 alert. Clear → 1 recovery event. Assert at most 1 event per tier transition (no per-tick re-emission).
- [ ] **Bus circuit-breaker per-agent spool.** Kill the bus during scaler emit; assert 3 consecutive failures flip the agent to `bus_degraded`, subsequent emits land in `data/maint/agent_spool/maint.scaler.v1/`. Restore bus; assert spool drains in arrival order on the next tick. Critical-severity alert during outage either succeeds or triggers `maint_self_isolated` — never silently spooled.
- [ ] **Leader split-brain.** Block K8s API (`coordination.k8s.io/v1` 503); assert losing pod transitions to observer within `lease_duration + 5s` BEFORE attempting any publish. Restore API; assert exactly one leader resumes, no duplicate `scale_decision` for the overlap window.
- [ ] **Backup PG role enforcement.** Attempt to start the backup agent under a non-`negelir_backup` role; assert it refuses with `fail_safe_wrong_pg_role`. Attempt under `negelir_backup` with superuser flag; assert refuse `fail_safe_superuser`.
- [ ] **Backup encryption multi-recipient.** Configure a key dir with 2 recipients; encrypt + assert the resulting `.tar.age` is decryptable by **either** recipient's private key independently. Configure with 1 recipient under `profile=prod`; assert agent refuses to start with `fail_safe_min_recipients`.
- [ ] **Backup unencrypted refused in prod.** Set `profile=prod`, leave `encryption_key_dir` unset; assert agent refuses (`fail_safe_no_encryption_in_prod`). Mock profile: warn + emit `backup_unencrypted` debounced daily.
- [ ] **Telemetry as new sec.alert producer.** Boundary test asserts `telemetry.v1` may publish `sec.alert.v1` ONLY with `kind=maint_silence_alert`; any other kind from telemetry fails the producer-kind allow-list.
- [ ] **`maint.event.v1` per-kind shape.** Boundary + round-trip test: every kind in `_ack_routing.py` has a matching sub-schema under `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json`; emitting via the typed factory validates; emitting an unknown kind in a redelivery (after rolling-upgrade downgrade) is dropped with `kind=maint_unknown_kind` alert (debounced), never blanket-rejected.
- [ ] **Destructive-command confirmation.** Run `ops.scale --target consensus.v1 --replicas 0` without `--confirm-destructive` → exits non-zero with `confirmation_required` and prints the expected token; re-run with the printed token publishes exactly once. Same shape for `ops.restore`, `ops.dlq-replay --drop`, `ops.maint-pause` against a critical agent.
- [ ] **Backup wall-clock backwards step.** Step the test clock back 600s mid-cron-window; assert next tick refuses to fire (no duplicate `backup_started` for the same `backup_date_utc`) AND emits `kind=backup_clock_skew, severity=error`. Forward-leap > 24h emits `severity=warn, scope=forward`; catch-up policy still produces exactly one make-up run.
- [ ] **PG connection-limit isolation.** Configure `pg_jobs=8` against a `negelir_backup` role with `CONNECTION LIMIT=10`; backup succeeds and the application connection pool reports zero `too_many_connections` events during the dump. Mis-configure to `CONNECTION LIMIT=4`; agent refuses to start (`fail_safe_pg_conn_limit_too_low`).
- [ ] **Two-class encryption recipient.** Encrypt with 2 DR + 1 verify recipient; assert (a) verify-only private key successfully decrypts inside SidecarVerifier, (b) `ops.restore` REFUSES that same verify key with `dr_key_required`, (c) any DR private key successfully drives `ops.restore`, (d) verify keypair is rotated per dump (different fingerprint between two consecutive nightlies).
- [ ] **Restore round-trip.** Nightly dump on a fresh DB seeded with N rows across all tables → `ops.restore DATE=... TARGET=<ephemeral>` → row counts match per `verify.sql`; `quarantine_samples` is empty by design; `maint_audit_log` carries the matched `backup_restore_started` + `backup_restore_completed` pair.
- [ ] **Weekly cold-verify catches storage rot.** Bit-flip a single byte in an older retained dump's middle file; cold-verify fires `kind=backup_cold_verify_failed` + `severity=critical` alert; nightly continues unaffected; the corrupted dump is NOT auto-pruned.
- [ ] **Audit-log INSERT-only.** Attempt `UPDATE` and `DELETE` on `maint_audit_log` as the application role; assert both raise `audit_log_immutable`. Same as `negelir_backup`. Retention prune as `negelir_audit_pruner` succeeds only inside the explicit `SET ROLE` transaction; outside the transaction the role can't be assumed.
- [ ] **`maint.ack.v1` payload cap.** Consumer returns a 64KB `details` blob; assert publisher truncates to `cfg.maint_ack_payload_max_bytes`, fires `kind=maint_ack_oversize` (debounced per `accepted_by`), and the truncated ack still satisfies the operator wait-for-acks loop.
- [ ] **DLQ allow-list mid-replay.** Operator removes `predict.vote` from `maint_dlq_replay_topics_allow` while 50 entries are in flight from the current tick; assert in-flight 50 complete normally, no new entries pulled in subsequent ticks, `kind=dlq_topic_disabled_drained{target=predict.vote, in_flight_count=50}` fires once.
- [ ] **`pattern_allowlist` partial-index plan.** `EXPLAIN (FORMAT JSON, BUFFERS)` of the `sec.input.v1` eval query against a populated table (10k expired + 100 active rows) confirms the planner uses `idx_pattern_allowlist_active` (not the full index); buffers read ≤ active-row footprint.
- [ ] **Off-host replication round-trip (§8.12).** Seeded mock S3 (minio) target; nightly dump uploads with multipart, manifest checksum verified; agent kill mid-upload → next tick resumes (idempotent multipart upload); verify the uploaded blob is decryptable end-to-end via a DR key into a clean target. Failure modes: target unreachable for 24h → `kind=backup_offsite_failed` + critical alert; target object-lock retention prevents accidental overwrite (assert via mocked `WORM` enforcement).
- [ ] **Planned-pause symmetry (§8.10).** `ops.maint-pause --agent maint.scaler.v1 --ttl-s 600` halts publish path; in-flight ack emission still works; auto-scaler reads pause as `manual_scale_pin{replicas=current}` (no scale calls during the pause window); ttl expiry emits `kind=maint_resumed`; explicit `ops.maint-resume` short-circuits TTL.

**Versioning:**

- [ ] `swarm` chart key bumps **minor** at the Phase 8 landing (new agents + new topic). `source_watcher` bumps **major** (`1.x → 2.0.0`) at the SDK + summarizer graduation per §2.8 promise. `xops` bumps **minor** for the `opsctl` CLI. `infra_mock` bumps **patch** for the `restore-verify` compose profile. Subsequent Phase 8 review patches bump the affected key patch-level.

**Triangle test (config sync):**

- [ ] All Phase 8 cfg knobs (`maint_runtime`, `maint_scaler_*` ×11 incl. `pin_max_ttl_s`/`vram_headroom_mb`/`runtime_timeout_s`/`window_ns` derived/`history_max`, `maint_backup_*` ×24 incl. `max_skew_h`/`age_alert_h`/`prune_batch`/`prune_max_lock_ms`/`verify_mode`/`encryption_key_dir`/`min_dr_recipients`/`verify_key_rotate_per_dump`/`pvc_size_gb`/`verify_orphan_ttl_h`/`clock_step_back_alert_s`/`pg_conn_limit`/`cold_verify_cron`/`offsite_target`/`offsite_endpoint`/`offsite_bucket`/`offsite_multipart_threshold_mb`/`offsite_bw_kbps`/`offsite_upload_timeout_h`/`offsite_object_lock_days`/`offsite_age_alert_h`/`offsite_retention_days`, `maint_dlq_*` ×10 incl. `replay_topics_allow`/`backlog_alert`/`max_replays_per_tick`/`consumer_broken_threshold`/`consumer_broken_window_s`, `maint_schema_*` ×4 incl. `sample_rate`, `maint_sec_*` ×3 incl. `allowlist_pending_ttl_days`, `maint_audit_retention_days` + `maint_audit_retention_days_overrides` dict, `maint_silence_alert_h`, `maint_self_dlq_growth_alert`, `maint_plane_lag_alert_ms`, `maint_plane_lag_alert_window_s`, `maint_plane_recovery_window_s`, `maint_agent_spool_max_entries`, `maint_pause_max_ttl_s`, `maint_ack_payload_max_bytes`, `maint_ack_reason_max_bytes`, `maint_ack_details_max_bytes`, `opsctl_ack_timeout_ms`, `opsctl_spool_max_entries`, `opsctl_critical_agents`, `source_watcher_summarizer_*` ×3 incl. `max_tokens_per_call`) appear in `xops/env/.env.example`, `ai/common/defaults.yaml`, and `ai/common/config.py`. `test_config_sync.py` stays green.

**Migrations:**

- [ ] `migrations/009_maint_audit.sql` lands the `maint_audit_log` table (additive — no DROP, per CLAUDE.md doctrine). Includes `pattern_allowlist_version` metadata row scaffolding for §8.7 mtime-style cache reload. **INSERT-only enforcement (binding):** `REVOKE UPDATE, DELETE ON maint_audit_log FROM PUBLIC` + a `BEFORE UPDATE OR DELETE` trigger that raises `audit_log_immutable` for every role except a dedicated `negelir_audit_pruner` role (used solely by the §8.3 retention prune, which obtains the role via `SET ROLE` only inside the prune transaction). The application role and `negelir_backup` cannot mutate audit rows by design. Per-table retention overrides supported via `cfg.maint_audit_retention_days_overrides` dict (default `{pii_erased: 2555}` — 7 years for right-to-erasure breach evidence per [`design/SECURITY.md`](../design/SECURITY.md)); `kind`s without an override use the global `cfg.maint_audit_retention_days` (default 365).
- [ ] `migrations/010_pattern_allowlist.sql` lands the `pattern_allowlist` table (additive) with `state CHAR(1) CHECK (state IN ('p','a','e'))` (pending/active/expired), `proposed_at`, `expires_at`, `added_by_request_id`. Carries TWO indexes: (a) full B-tree on `(source, rule_id, hit_fingerprint, state)` for operator queries via `ops.allowlist-show`; (b) **partial index** `idx_pattern_allowlist_active ON (source, rule_id, hit_fingerprint) WHERE state='a' AND (expires_at IS NULL OR expires_at > now())` — the hot read path from `sec.input.v1` exclusively hits the partial index, keeping eval-time index size O(active rows) rather than O(historical rows). Note: PG partial-index `WHERE` predicates with `now()` are non-deterministic; the actual migration uses `WHERE state='a'` for the partial index (PG-supported) and the `expires_at` filter is applied at query time on the already-narrow active subset (covered-index fast path). Proof test asserts `EXPLAIN (FORMAT JSON)` of the eval query uses the partial index, not the full one.
- [ ] `migrations/011_backup_role.sql` lands the least-priv `negelir_backup` PG role (additive, idempotent) with `pg_read_all_data` grant + USAGE on `pg_catalog`. Boot validation (§8.3) refuses to start under any other role.
- [ ] All three migrations apply cleanly on a fresh DB and as upgrades from migration 008. Migration round-trip test runs Detector B against the post-migration schema and asserts zero false-positive drift. **Restore-empty quarantine proof:** after a full backup-restore cycle on a DB that contained N quarantine_samples rows, assert post-restore `SELECT count(*) FROM quarantine_samples == 0` AND the sibling `negelir.quarantine_meta.csv` parses to exactly N rows with the documented columns (PII excluded).

**Doctrine / docs:**

- [ ] [`design/SWARM.md`](../design/SWARM.md) roster updated with the 6 maint agents + ownership notes.
- [ ] [`design/SECURITY.md`](../design/SECURITY.md) updated with the right-to-erasure flow (`quarantine_erase` → `pii_erased` audit row) **and** the PII-aware backup policy (raw bytes excluded; sanitized projection only).
- [ ] [`design/CONFIGURATION.md`](../design/CONFIGURATION.md) gains a "Maintenance" section enumerating every Phase 8 cfg knob with default + range + safety note.
- [ ] CLAUDE.md scope table updated: ops console publishes maint events; patcher remains the only auto-mutator of scraper code (no overlap with Phase 8).

### 8.10 Liveness, leader-election, and dead-mans-switch

> Cross-cutting reliability concerns that span every §8.x agent. Pulled out of the per-agent sections to keep the contracts explicit.

- [ ] **Liveness probes (Phase 14 K8s).** Every §8.x agent exposes the same `/healthz` (Phase 14 sidecar) backed by `Agent.heartbeat_age_s() < 3 × cfg.swarm_heartbeat_sec`. The K8s `livenessProbe` uses HTTP GET on `/healthz` with `failureThreshold=3, periodSeconds=heartbeat_sec`. Compose mode: a `make ops.liveness` smoke check polls each agent's bus heartbeat and fails loud on stale ones.
- [ ] **Leader-election (Phase 14, binding for `replicas: 1` agents).** `maint.scaler.v1`, `maint.backup.v1`, `maint.dlq.v1`, `maint.schema.v1`, **and** `maint.sec.v1` all use the standard K8s `coordination.k8s.io/v1.Lease` client (15s lease, 10s renew, 5s retry). DLQ supervisor and sec-allowlist/decimate are included because (a) two supervisors would double-replay every DLQ entry and double-emit `dlq_replayed`, and (b) two sec-decimaters would race on the §8.8 hysteresis timer (the Lua atomicity protects Redis state but the audit trail would double). On lease loss, the agent enters "observer mode" — continues consuming for ledger warmth but **does not publish**. Compose mode: only one replica per service is ever started (compose enforces). The leader-election adapter is a `Leader` Protocol with `KubernetesLeader` and `SingleProcessLeader` implementations; agent code calls `if not self.leader.is_leader(): return` before every emit. Boundary test asserts every emit path is gated AND the §8.10 leader-required set matches the registered agent ids exactly (orphans on either side fail CI).
- [ ] **Dead-mans-switch.** A dedicated `maint.heartbeat.v1` (no — reuse `telemetry.v1{kind=maint_silence_check}`) periodic check: if `now − last_observed_maint_event_v1 > cfg.maint_silence_alert_h` (default 24h) AND the swarm has been up `> 1h` (boot-warm guard), emit `sec.alert.v1{kind=maint_silence_alert, severity=critical}` (bypass debounce). Catches the worst silent-failure mode: the maint plane is dead so it can't tell you it's dead. The check itself runs in **`telemetry.v1`** (already always-on; §8.x can't be both judge and patient). **Boundary update (binding):** telemetry was previously read-only counters; this is the **first** publish path from `telemetry.v1` onto `sec.alert.v1`. The §7.4 producer-set allow-list for `sec.alert.v1` widens by exactly one entry (`telemetry.v1`, kinds restricted to `{maint_silence_alert}` only — boundary test pins the kind allow-list per producer, not just the producer set).
- [ ] **Self-isolation under cascading failure.** If a Phase 8 agent's own DLQ exceeds `cfg.maint_self_dlq_alert` (default 100 entries), the agent flips its bus subscriptions to read-only (acks only, no new actions), emits `sec.alert.v1{kind=maint_self_isolated, severity=critical}`, and waits for operator unblock via `ops.maint-resume --agent <id>`. Prevents the maint plane from amplifying outages it cannot keep up with.
- [ ] **Operator-driven planned maintenance.** Symmetric `ops.maint-pause --agent <id> [--ttl-s T]` / `ops.maint-resume --agent <id>` — pauses an agent's *publish* path while leaving consume (and therefore ack-emission for in-flight requests) live, so the plane drains gracefully. Pause emits `maint.event.v1{kind=maint_paused, target=<id>, ttl_s, reason}`; expiry or explicit resume emits `kind=maint_resumed, target=<id>`. `ttl_s ≤ cfg.maint_pause_max_ttl_s` (default 7200). Pause is **distinct** from self-isolation (which is involuntary + critical-alerted); planned pause is operator-attributed (`paused_by` in payload) and carries `severity=info` only. Critical agents (`cfg.opsctl_critical_agents`, see §8.1 destructive set) may be paused only with `--confirm-destructive`. Auto-scaler treats a paused target as `manual_scale_pin{replicas=current}` for the pause TTL — no scale calls, no flap on resume.
- [ ] **Proof tests.** (a) leader-election: kill the leader pod, assert second pod becomes leader within 2× lease duration and resumes publishing. (b) dead-mans-switch: stop all `maint.event.v1` producers in a test harness, advance the clock past the threshold, assert the alert fires exactly once (debounce-bypass). (c) self-isolation: feed 100 poisoned events to `maint.scaler.v1`, assert it stops issuing scale calls and emits `maint_self_isolated`. (d) leader split-brain: simulate K8s API partition (lease unreachable) — assert losing pod transitions to observer within `lease_duration + 5s` BEFORE attempting any publish, never co-issuing.

### 8.11 Maint plane backpressure & self-shedding

> The maint plane exists to handle outages; it must not become an outage itself. Cross-cutting backpressure rules.

- [ ] **`maint.event.v1` consumer-lag watchdog.** When the median consumer lag on `maint.event.v1` exceeds `cfg.maint_plane_lag_alert_ms` (default 5000ms) for `cfg.maint_plane_lag_alert_window_s` (default 60s), emit `sec.alert.v1{kind=maint_plane_lag_high, severity=warn}` (debounced) and apply graded shedding:
  - **Tier 1 (lag > 5s):** scaler suppresses **non-emergency** decisions (`reason ∈ {lag_low, cpu_low, p95_high}` → drop; emergency reasons `{vram_budget_exceeded, manual_pin, retrain_request_warmup}` always emit). DLQ supervisor halves `max_replays_per_tick`.
  - **Tier 2 (lag > 15s):** scaler scale-down decisions are entirely paused (only scale-up emergencies emit). DLQ supervisor enters drain-only mode (no replays, only escalations). §8.6 schema sentinel reduces sample rate to 0.1× config.
  - **Tier 3 (lag > 60s):** every §8.x agent stops emitting non-critical events; emits a final `maint.event.v1{kind=maint_plane_throttled, tier=3}` then enters observer-only mode until lag clears below 1s for `cfg.maint_plane_recovery_window_s` (default 120s). Recovery emits `kind=maint_plane_recovered`.
- [ ] **No self-amplification.** Tier 2/3 shedding events are themselves emitted at most **once per tier transition**, not periodically — prevents the shedding signal from amplifying the plane it is shedding.
- [ ] **Per-agent self-throttle on own DLQ.** Independent of plane-wide lag: if any §8.x agent's own `<id>.dlq` depth grows by more than `cfg.maint_self_dlq_growth_alert` (default 50) per minute, the agent halves its own emit rate (token-bucket on its own producer side) until growth is non-positive for 2 minutes. Less drastic than §8.10 self-isolation; catches early-warning signs.
- [ ] **Bus circuit-breaker.** Three consecutive bus-publish failures within 30s → agent enters `bus_degraded` mode: subsequent publishes go to `data/maint/agent_spool/<agent>/` (bounded by `cfg.maint_agent_spool_max_entries`, default 512), drained on first successful re-publish. Mirrors §8.1 opsctl spool but agent-side. Critical alerts (`severity=critical`) bypass the spool and either succeed or trigger `maint_self_isolated`.
- [ ] **Proof tests.** (i) lag watchdog: inject 6s lag in test bus, assert tier-1 shedding + alert; ramp to 70s, assert tier-3 + observer mode; clear lag, assert recovery event. (ii) self-amplification: assert at-most-one tier-2 event per tier transition under sustained lag (no per-tick re-emission). (iii) own-DLQ growth-rate throttle: feed 60 poisoned events to a maint agent within 60s, assert emit-rate halves, no immediate self-isolation (that's the §8.10 hard threshold). (iv) bus circuit-breaker: kill the bus mid-emit, assert spool fills, restore bus, assert spool drains in arrival order.

### 8.12 Disaster recovery & off-host backup replication

> A backup that lives only on the host whose disk just died is a useless backup. Every nightly artifact must replicate to a second failure domain before it is considered "complete-for-DR-purposes". The on-host artifact remains the primary restore source for routine operations (faster, no egress); the off-host copy is the disaster floor.

- [ ] **Replication target abstraction.** `OffsiteBackupTarget` Protocol with three first-class implementations:
  - `S3CompatibleTarget` — S3, MinIO, R2, GCS-via-S3-API, Backblaze B2. Uses pure-Python `urllib3` + signed PUT (no `boto3` to honor the `xops/` stdlib-preference; the auth signer lives at `xops/backup/s3_sigv4.py`). Multipart upload mandatory for dumps `>` `cfg.maint_backup_offsite_multipart_threshold_mb` (default 64). Requires `cfg.maint_backup_offsite_endpoint`, `cfg.maint_backup_offsite_bucket`, `cfg.maint_backup_offsite_access_key_id`, `cfg.maint_backup_offsite_secret_access_key_secret_ref` (K8s SecretKeyRef in cloud profile, file path in compose; never the literal value in config).
  - `RsyncSshTarget` — operator-managed second host. Wraps `rsync -aHAXz --partial --inplace --bwlimit=cfg.maint_backup_offsite_bw_kbps` over SSH with strict host-key checking. Useful for self-hosted and air-gapped deployments.
  - `NoopTarget` — explicit selection only (`cfg.maint_backup_offsite_target=none`); used in dev/mock. Boot validation refuses `none` when `cfg.profile=='prod'` (`fail_safe_no_offsite_in_prod`).
- [ ] **Upload window.** Replication kicks off **after** restore-verify succeeds (never replicate an unverified dump); runs concurrently with the next nightly's TTL prune. Bandwidth-capped at `cfg.maint_backup_offsite_bw_kbps` (default 50 000 KB/s in prod, unlimited in mock) so it doesn't compete with daytime ingest. Hard timeout at `cfg.maint_backup_offsite_upload_timeout_h` (default 6h) — overruns abort + emit `kind=backup_offsite_failed{reason=timeout, uploaded_bytes}`.
- [ ] **Idempotent multipart resume.** Upload state (multipart upload ID, completed part ETags, byte offsets) persisted to `data/backups/<date>/.offsite_state.json` (mode 0600, atomic temp+rename). Agent crash mid-upload → next tick reads state and resumes from the last completed part (S3 multipart UploadPart semantics; rsync `--partial --inplace`). State file is deleted on successful `CompleteMultipartUpload` / rsync exit-zero.
- [ ] **Object-Lock / WORM (S3 path, binding for prod).** When `cfg.maint_backup_offsite_object_lock_days > 0` (default 30 in prod, 0 in mock), every uploaded object is written with `x-amz-object-lock-mode=COMPLIANCE` + `x-amz-object-lock-retain-until-date=now+N`. Prevents ransomware deletion of the off-host floor. Boundary test against MinIO with object-lock-enabled bucket asserts attempted overwrite and attempted delete during retention both 403 (`ObjectLockedException`). Object-lock mismatch at upload-time is fail-loud (`fail_safe_object_lock_misconfig`), never silent fallback.
- [ ] **Per-object integrity.** Each uploaded object carries a sidecar `<dump>.sha256.txt` + `<dump>.manifest.json` (`{date, size_bytes, checksum_sha256, encryption_key_versions:[…], producer_pod_instance_id, uploaded_at_utc}`). Manifest checksum independently verified post-upload via HEAD + range-GET probe (first 4KB + last 4KB) before the upload is considered complete and `kind=backup_offsite_uploaded` is emitted.
- [ ] **Offsite age gauge.** Telemetry exposes `maint_backup_offsite_age_hours` (now − last successful `kind=backup_offsite_uploaded`); separate from `maint_backup_age_hours`. Watchdog `sec.alert.v1{kind=backup_age_alert, scope=offsite, severity=critical}` fires when offsite age > `cfg.maint_backup_offsite_age_alert_h` (default 48h). Catches the failure mode where local backups succeed but replication has been broken for days.
- [ ] **Offsite retention.** Independent of on-host retention. Default `cfg.maint_backup_offsite_retention_days` = 90 (prod) / 7 (mock) — longer-tail recovery window. Pruning of expired offsite objects requires the object-lock retention to have lapsed; pre-lapse delete attempts are silent no-ops (Object Lock enforces; agent records but doesn't error).
- [ ] **DR drill cadence.** Operator runbook at `docs/guides/dr_drill_runbook.md` documents a quarterly DR drill: (a) provision a fresh PG instance in a separate region/datacenter, (b) `ops.restore --from-offsite DATE=... TARGET=<dr-conn>`, (c) run `xops/backup/verify.sql` against the restored instance, (d) record drill outcome in `data/backups/dr_drills.csv`. Cadence-overdue gauge `maint_backup_dr_drill_age_days` (alert at 100d).
- [ ] **Boundary discipline.** AST scan asserts `xops/backup/offsite/**.py` carries no imports from `swarm.*`, `psycopg`, or `redis.client.Redis.*` mutators (offsite is a pure replicator — reads from disk, writes to remote, emits to bus only). Credentials are read once at startup from the secret reference and NEVER logged (a regex sweep of `make test.ai` output ensures no key id / secret string leaks at WARN/ERROR level — pinned via a `secret_smoke.py` post-test hook).
- [ ] **Versioning.** `xops` chart key bumps **minor** for `xops/backup/offsite/`; `infra_mock` bumps **patch** for the MinIO compose profile used in §8.9 proof tests.

### 8.13 Fourth-pass deep-revision additions (model-artifact DR, plane storage cap, spool aging, restore version-invariant, pause/resume idempotency, key-compromise runbook)

> Closing real gaps surfaced by the fourth-pass review: backups today protect Postgres but say nothing about the **trained model artifacts on disk**; `data/maint/` has many bounded sub-budgets but no global cap; spool entries can fester forever after a `kind` is retired; restore-verify is silent about migration-version skew between the dump and in-tree; pause/resume semantics are not idempotent; encryption-key compromise has no runbook.

#### 8.13.1 Model-artifact backup discipline

- [ ] **Doctrine (binding).** Trained model artifacts under `data/models/<predictor_id>/<version>/` (XGBoost / LightGBM JSON, ONNX, calibration JSON sidecars) are **NOT** included in the nightly Postgres dump (logical pg_dump cannot reach the host filesystem, and inlining them would balloon the dump beyond reasonable verify windows). Two concrete options, **both required at v1**:
  - (a) **Reproducibility floor.** Every artifact carries a sidecar `<artifact>.lineage.json` containing `{predictor_id, version, trained_at, trainer_commit_sha, training_data_window_utc, source_calibration_row_ids, source_outcome_row_ids, hyperparameters_sha256}`. Postgres rows referenced by `source_*_row_ids` ARE in the dump (`predictor_calibration` / `predictor_outcomes` per migration `005_predictor.sql`). After a worst-case restore, the trainer can re-derive byte-equivalent artifacts from the calibration / outcome rows + commit sha at `cfg.maint_backup_model_reproducibility_window_h` (default 24h) latency. Boundary test: `ai/swarm/agents/tests/test_phase8_model_lineage.py` retrains a sample predictor from the lineage record and asserts the resulting hyperparameter/feature hash matches the original.
  - (b) **Cold artifact mirror.** A separate nightly tarball `models-YYYY-MM-DD.tar.zst` (zstd, level 9) of `data/models/` is uploaded to the same `OffsiteBackupTarget` as §8.12, encrypted with the same DR-class recipients, retained per `cfg.maint_backup_model_offsite_retention_days` (default 30 — shorter than the PG retention because models are reproducible). Hosted alongside the PG dump under `models/<date>/`. **NOT** part of restore-verify (verifying a 5 GB model tarball every night is wasted compute) — instead a **monthly** cold-verify pass extracts the oldest retained tarball into a throwaway dir, runs `predictor.load(...)` on each artifact, and asserts the load completes; failure → `kind=backup_model_cold_verify_failed` + `severity=critical`.
- [ ] New `maint.event.v1` kinds: `backup_model_uploaded`, `backup_model_offsite_failed`, `backup_model_cold_verify_completed`, `backup_model_cold_verify_failed`, `backup_model_lineage_drift` (lineage sidecar missing or hash mismatch on a live artifact).
- [ ] New `sec.alert.v1` kind: `backup_model_lineage_missing` (debounced per `predictor_id`, severity=warn) — surfaces when a trainer landed an artifact without a lineage sidecar (the Phase 5 trainer reactor must always write one; this is the post-hoc audit).
- [ ] **Boundary discipline.** AST scan asserts `data/models/` is **never** read inside the §8.3 `pg_dump` path (no false positive of "we forgot to back up models" — the doctrine is explicit, not accidental).

#### 8.13.2 `data/maint/` global storage cap

- [ ] All maint sub-budgets (`opsctl_spool/`, `opsctl_locks/`, `opsctl_audit.csv`, `agent_spool/`, `summarizer_ledger.json`, `pod_instance_id` files, `dr_drills.csv`) are individually capped today. Add a **cumulative** cap: at every §8.x agent's heartbeat, the `MaintStorageWarden` (lives in `swarm.sdk.maint_storage`) sums `du -sb data/maint/` and checks against `cfg.maint_storage_total_max_mb` (default 512 MB). Crossing 80% of the cap → `sec.alert.v1{kind=maint_storage_pressure, severity=warn}` (debounced 1h). Crossing 100% → emit `severity=error`, refuse all new spool writes (publish path errors loud with exit code 6 `maint_storage_full`), and flip every §8.x agent into observer mode until usage drops below 70% (single hysteresis band, prevents thrash).
- [ ] **Per-subdir budget audit.** Cap is informational only when the sum of per-subdir caps is ≤ the global; if the operator widens a single per-subdir cap beyond the global headroom, boot validation refuses to start (`fail_safe_subdir_caps_exceed_global`). Single source of truth, single failure mode.
- [ ] Telemetry exposes `maint_storage_used_bytes{subdir}` (per-subdir gauge) + `maint_storage_total_bytes` (rollup) once per heartbeat.

#### 8.13.3 Spool entry aging + retired-kind handling

- [ ] **Spool entries have a max age.** Both `data/maint/opsctl_spool/` (§8.1) and `data/maint/agent_spool/<agent>/` (§8.11 bus circuit-breaker) prune entries older than `cfg.maint_spool_entry_max_age_h` (default 168h = 7d) on every flush attempt. Pruned entries emit `maint.event.v1{kind=spool_entry_aged_out, target=<agent>, request_id, age_h, kind}` (audit) and `sec.alert.v1{kind=spool_entry_aged_out, severity=warn}` (debounced per agent).
- [ ] **Retired-kind handling (binding).** When `flush` encounters an envelope whose `kind` is no longer in the live `KNOWN_MAINT_EVENT_KINDS` set (e.g. a kind retired by a Phase 8.x patch landed during the spool's lifetime), the envelope is **not silently dropped and not silently retained** — it is moved to `data/maint/<spool>/.retired/` with a sidecar `<request_id>.retired.json` capturing `{kind, retired_at_version, current_version}`, and a `sec.alert.v1{kind=spool_entry_retired_kind, severity=warn}` fires. Operator decides via `ops.spool-show --retired` and either `ops.spool-flush --force-retired` (re-publish anyway, accepting the unknown-kind drop the consumer will perform per §0 forward-compat) or manual delete. Same shape applies if the envelope's `schema_version` is below the agent's `cfg.swarm_min_supported_schema_version`.
- [ ] **Proof tests.** (a) Aging: write a 200h-old envelope, assert flush prunes it + emits both events. (b) Retired-kind: register a kind, write a spool entry with that kind, retire the kind from the known-kinds set in the same process, assert flush moves the envelope to `.retired/` with sidecar; `ops.spool-flush --force-retired` re-publishes. (c) Schema-outdated: same shape with `schema_version`.

#### 8.13.4 Restore version-invariant

- [ ] **Manifest captures dump-time migration state (binding).** The §8.3 dump manifest (`negelir.manifest.json`) gains `migrations_at_dump_time: {max_version: int, applied_versions: [int...], repo_commit_sha: str|null}`. `repo_commit_sha` is best-effort (read from `xops/versioning/build_metadata.json` written at container build; null when running outside a built image — the agent emits `sec.alert.v1{kind=backup_commit_sha_unavailable, severity=info}` once at boot, never per-dump).
- [ ] **Restore-verify version-skew handling.** `LocalSubprocessVerifier` and `SidecarVerifier` both: (a) read the manifest's `max_version`, (b) load the in-tree migrations under `migrations/*.sql`, (c) compute `version_gap = in_tree_max_version - manifest.max_version`, (d) if `version_gap > cfg.maint_backup_max_version_gap` (default 5 — covers ~quarterly migration cadence), refuse with `kind=backup_dump_too_old` + `sec.alert.v1{severity=error}` (operator must escalate to a manual restore using the historical commit). Otherwise, run **`pg_restore` first**, then **apply migrations `(manifest.max_version, in_tree_max_version]` forward** in numeric order, then **run `verify.sql`**. This makes `verify.sql` always evaluate against the in-tree schema regardless of dump age — eliminates the silent-failure mode where today's `verify.sql` returns 0 rows on a column that didn't exist in last week's dump.
- [ ] **Forward-only assumption (binding).** The Phase 8 doctrine assumes migrations are forward-only and additive (CLAUDE.md doctrine: never `DROP`). Restore-verify therefore never runs migrations *backward*. A future destructive migration (Phase 14+) requires explicit escape-hatch design.
- [ ] **Proof tests.** (a) Synthetic dump from migration 010, in-tree at 014, gap=4 → restore succeeds, migrations 011-014 apply, `verify.sql` passes. (b) Same with gap=10 → refuse + alert. (c) Manifest missing migration metadata (legacy dump from before this revision) → fall-back behavior: skip forward-migrate, run `verify.sql` against the dump's schema only; emit `kind=backup_legacy_manifest, severity=info`.

#### 8.13.5 Pause / resume / self-isolation idempotency matrix

- [ ] **All four operator-driven state-change verbs are idempotent at the consumer side.** Re-issuing the same logical command on an agent already in the target state is **never** a hard error. Instead, the consumer ack carries `accepted=true, reason="already_<state>"` and the publisher exits 0 (operators muscle-memory re-run). The matrix:
  | Current state \ Command | `maint-pause` | `maint-resume` | `dlq-resume` |
  |---|---|---|---|
  | running | accept → paused | accept (no-op, `already_running`) | accept (no-op, `already_running`) |
  | paused | accept (no-op, `already_paused`; TTL refreshes if larger) | accept → running | accept (no-op, `paused_not_blocked`) |
  | self-isolated | reject (`requires_resume_first`, exit 7) | accept → running (clears self-isolation flag) | accept (no-op or partial — replays still frozen) |
  | dlq-frozen | accept → paused (still frozen) | accept (frozen subset preserved) | accept → running for the named topic only |
- [ ] **Self-isolation precedence.** A self-isolated agent IGNORES `maint-pause` (emits `kind=maint_pause_rejected, reason=self_isolated`) — the operator must `maint-resume` first to clear the involuntary state, then optionally `maint-pause` for planned work. Prevents the operator from "pausing" an agent that is already in critical-alerted involuntary stop and forgetting to investigate the root cause.
- [ ] **TTL refresh semantics.** `maint-pause --ttl-s T2` against an already-paused agent: if `T2 > remaining_ttl` → refresh to `T2`; if `T2 ≤ remaining_ttl` → no-op (preserve longer pause). Never silently shortens. Audit row records both `requested_ttl` and `effective_ttl`.
- [ ] **Proof tests.** (a) `pause`-while-paused: ack `already_paused`, exit 0, second pause-event `kind=maint_paused, action=ttl_refresh|no_op` carries explicit action field. (b) `resume`-while-running: ack `already_running`, exit 0. (c) `pause` against self-isolated → reject exit 7, emits `maint_pause_rejected`. (d) Full sequence: `self_isolate → pause` rejected → `resume` → `pause(T=600)` → `pause(T=300)` no-op → `pause(T=1200)` refresh → wait expiry → `kind=maint_resumed`.

#### 8.13.6 Encryption-key compromise runbook

- [ ] **Operator runbook at `docs/guides/backup_key_compromise_runbook.md` (binding deliverable for §8.9 doctrine bullet).** Three scenarios, three procedures:
  - **Verify-class key compromise.** Scoped impact: at most ONE dump per the per-dump rotation policy (§8.3). Procedure: rotate immediately via `ops.backup-rotate-key --scope verify` (regenerates the verify keypair, deletes the old Secret); the dump that *was* encrypted to the compromised verify key is re-encrypted to a fresh verify key during the next nightly's restore-verify pass (the dump's DR-class encryption is unaffected). No data loss possible.
  - **DR-class key compromise (single recipient of N).** Scoped impact: the compromised half can decrypt every dump that included it as a recipient. Procedure: (1) revoke from `infra/maint/backup_keys/dr/recipients.txt` and commit; (2) `ops.backup-rotate-key --scope dr --add-recipient <new-pub>` adds a fresh DR public key alongside the surviving ones; (3) **old dumps are NOT re-encrypted** (compute and storage cost prohibitive for multi-month archives) — they remain decryptable by the surviving DR recipients AND by the compromised key (treat as "trusted but compromised"); (4) operator decides whether to delete affected old dumps from offsite (within the Object-Lock retention window, deletes are no-ops; after retention, prune is allowed); (5) emit `kind=backup_key_compromise_acknowledged, scope=dr, recipient_fingerprint, action=revoke` for the audit trail.
  - **Full DR-class compromise (all N recipients).** Catastrophic. Procedure: rotate ALL DR recipients in one operation; trigger an emergency nightly via `ops.backup-now --reason=key_emergency` so the next dump is encrypted to ONLY the new keys; flag every offsite dump older than the rotation as "not-confidential-anymore" in `dr_drills.csv` for the operator's risk review. **No automation can decide whether to delete those dumps** — operator-only call.
- [ ] **Server-enforced PG password aging.** §8.3 already exposes `maint_backup_pg_secret_age_days` gauge with alert at 100d. Add: agent **refuses to start** when `age > cfg.maint_backup_pg_secret_max_age_days` (default 120d, hard cap; ≥ alert threshold + grace window). Forces operator to rotate; combined with the alert at 100d gives a 20d operator window before hard-fail. New event `kind=backup_pg_secret_expired` + `sec.alert.v1{kind=backup_pg_secret_expired, severity=critical}` at refusal.
- [ ] **Proof tests.** (a) Verify-key rotation: assert old key cannot decrypt a fresh nightly. (b) DR-key revocation: encrypt with [k1, k2, k3], revoke k1, encrypt next nightly → decryptable by k2/k3 only; old dump still decryptable by k1/k2/k3 (no re-encryption). (c) PG-secret age refusal: set `pg_secret_age_days=121`, assert agent refuses with `fail_safe_pg_secret_expired`.

#### 8.13.7 Cross-section additions to §8.9 DoD

- [ ] All proof tests in §8.13.1–§8.13.6 land alongside the §8.9 ones.
- [ ] New chaos catalogue stubs in `docs/testing/phase12_catalogue.md` (4): `chaos-model-lineage-missing`, `chaos-maint-storage-fill`, `chaos-spool-retired-kind`, `chaos-restore-version-skew`.
- [ ] New `maint.event.v1` kinds (10): `backup_model_uploaded`, `backup_model_offsite_failed`, `backup_model_cold_verify_completed`, `backup_model_cold_verify_failed`, `backup_model_lineage_drift`, `spool_entry_aged_out`, `spool_entry_retired_kind`, `backup_legacy_manifest`, `backup_pg_secret_expired`, `backup_key_compromise_acknowledged`. New `sec.alert.v1` kinds (6): `backup_model_lineage_missing`, `maint_storage_pressure`, `spool_entry_aged_out`, `spool_entry_retired_kind`, `backup_dump_too_old`, `backup_pg_secret_expired`. All join the §7.4 known-kinds set; per-kind sub-schemas under `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json` per §0 discipline.
- [ ] New cfg knobs for triangle test: `maint_backup_model_reproducibility_window_h`, `maint_backup_model_offsite_retention_days`, `maint_storage_total_max_mb`, `maint_spool_entry_max_age_h`, `maint_backup_max_version_gap`, `maint_backup_pg_secret_max_age_days`. (`maint_backup_pg_secret_age_days` alert threshold already counted in §8.9.) The §8.9 triangle-test bullet's knob inventory grows accordingly.
- [ ] **Versioning addendum.** §8.13 lands as an additive revision; `swarm` chart key gains a **patch** bump on top of the §8.x landing's minor (no new agent surface, only new kinds + cross-cutting reliability invariants); `xops` patch for the new `MaintStorageWarden` helper + `ops.backup-rotate-key --scope` + `ops.spool-show --retired` flags; `docs` minor for the two new runbooks (`backup_key_compromise_runbook.md`, augmented `backup_runbook.md`).

### 8.14 Fifth-pass deep-revision additions (audit-log partitioning, per-file dump checksum manifest, `age` supply-chain pin, opsctl ACL + signed envelopes, DLQ recursion guard, ack trace propagation, schema-sentinel rps cap, trainer scale-target sole-writer, `pg_dump` nice + verify-PG version invariant, spool-flush dir lock + newest-first ordering)

> Closing real gaps surfaced by the fifth-pass review: `maint_audit_log` retention prune is a yearly DELETE-storm against a single table (PG range-partition + DETACH is the correct idiom); the dump checksum is computed post-encryption-tar and therefore cannot detect silent corruption of an individual file *inside* the `-Fd` directory dump before encryption; the `age` binary is referenced in critical decryption paths with no version pin or supply-chain doctrine; opsctl's destructive-token defeats accidental re-runs but not a compromised operator host (no Redis ACL, no per-subcommand authz); the DLQ supervisor could in principle subscribe to `maint.dlq.v1.dlq` and recursively replay its own failures; `maint.ack.v1` carries `request_id` but not `trace_id`, so distributed-trace correlation breaks at the ack edge; the schema-sentinel sample-rate knob has no rps cap (a misconfig to `1.0` against `predict.vote` is a self-DoS); the auto-scaler may warm trainer pods on `retrain_request` while the trainer itself self-scales, producing duplicate scale calls; `pg_dump --jobs=N` runs at default nice level on a shared PG and the ephemeral verify-PG image is hardcoded with no version-skew guard; `ops.spool-flush` has per-`(host,kind,target)` flocks but no flush-iterator-level lock, so two concurrent flushes can re-publish the same envelope twice (consumer dedup absorbs but the audit row is misleading and the spool-drain ordering is non-deterministic).

#### 8.14.1 `maint_audit_log` range-partitioning (vacuum-bomb fix)

- [ ] **Partition discipline (binding).** Migration `009_maint_audit.sql` creates `maint_audit_log` as a **range-partitioned table on `created_at` by month** (PG 14+ declarative partitioning), with partitions named `maint_audit_log_YYYY_MM`. The retention prune (§8.3) flips from per-row `DELETE WHERE created_at < cutoff` to **`ALTER TABLE maint_audit_log DETACH PARTITION maint_audit_log_YYYY_MM CONCURRENTLY`** followed by `DROP TABLE` of the detached partition — O(1) regardless of row count, no vacuum amplification, no autovacuum lock contention against the live INSERT path. The pruner role `negelir_audit_pruner` is granted `ALTER` on the parent table and `DROP` on `maint_audit_log_YYYY_MM_*` matched partitions only (least-privilege; no blanket `DROP` grant).
- [ ] **Per-kind retention overrides via partition-key encoding.** The `cfg.maint_audit_retention_days_overrides` dict (default `{pii_erased: 2555}` per §8.9) is enforced by **moving** rows that match an override `kind` into a sibling partition family `maint_audit_log_pii_YYYY_MM` (also range-partitioned) at insert time via a `BEFORE INSERT` trigger that routes by `kind`. The pruner walks both families with the appropriate cutoffs. Trade-off: triggers add per-insert latency (microseconds), but the retention-correctness invariant is mechanical — no application code can forget to apply the override.
- [ ] **Partition pre-creation.** A maintenance job (runs at the §8.3 cron tick, before the dump) ensures the next 3 months of partitions exist (`CREATE TABLE IF NOT EXISTS ... PARTITION OF ... FOR VALUES FROM (...) TO (...)`). Missing partition at INSERT time → PG raises `no_partition_of_relation_for_row`; agent emits `sec.alert.v1{kind=maint_audit_partition_missing, severity=critical}` and falls back to a temporary `maint_audit_log_default` partition (which is included in the next prune cycle and re-distributed). Catches operator clock-skew + missed-cron windows.
- [ ] **Proof tests.** (a) Insert 1M rows, prune 6mo retention → assert single `ALTER ... DETACH` per partition + `DROP TABLE`, total wall-clock ≤ 5s, no row-level lock observed via `pg_locks` snapshot. (b) Insert with `kind=pii_erased` → assert row lands in `maint_audit_log_pii_*` partition, not the standard family. (c) Pre-create job: simulate next-month gap → assert partition appears at next cron tick; simulate live INSERT into a missing future partition → fallback default partition + critical alert. (d) Pruner role authorization: attempt `DROP` of arbitrary table as `negelir_audit_pruner` → fails; attempt `DROP` of a matched audit partition → succeeds.

#### 8.14.2 Per-file dump checksum manifest (silent-corruption integrity gap)

- [ ] **Real bug.** §8.3 says the SHA-256 lives in `negelir.checksum.txt` next to the dump and is computed post-`fsync`. For `-Fd` directory format, this is the checksum of the **post-encryption tarball** (`.tar.age`). A silent corruption of a single file inside the dump dir BEFORE the tar+age step (disk bit-flip during `pg_dump`'s parallel writes; FS metadata corruption; misbehaving disk cache) produces a different post-tar tarball than expected, but the checksum is computed *over* that already-corrupted tarball — the hash matches itself. Restore-verify reads the same dump back and may fail late, or worse, succeed with corrupted rows that pass the row-count probe but contain garbage payloads. The cold-verify (§8.3) catches this eventually, but only weeks later.
- [ ] **Fix.** Between `pg_dump` completion and the `tar | age` pipeline, the agent walks the dump dir, computes SHA-256 per file (relative paths), and writes `negelir.files.sha256.txt` (one `<hex>  <relpath>` line per file, **inside** the dump dir so it is part of the encrypted tarball). The post-encryption checksum `negelir.checksum.txt` (over the `.tar.age` blob) stays — it covers tar/age corruption. Restore-verify decrypts, untars, **first** verifies every file against `negelir.files.sha256.txt` (failure → `kind=backup_dump_file_corrupted{file, expected, actual}` + `sec.alert.v1{severity=critical}`), then runs `pg_restore`. Adds ~5-10s wall-clock to verify on a 10GB dump (single-pass SHA over already-paged-in files); negligible against the existing verify window.
- [ ] **Cold-verify reuses the same manifest.** Weekly cold-verify checks both the outer tarball checksum AND the inner per-file manifest — bit-rot detection now operates at file granularity (operator runbook entry: `kind=backup_cold_verify_failed` payload includes `corrupted_files: [...]`).
- [ ] **Migration of legacy dumps.** Dumps written before this revision land lack the inner manifest; restore-verify falls back to outer-checksum-only with `kind=backup_legacy_no_file_manifest, severity=info` (one-shot per dump, not per-restore). After the §8.14 landing, every new dump carries the manifest.
- [ ] **Proof tests.** (a) Bit-flip a single byte in one file inside the dump dir post-`pg_dump`, pre-tar → assert restore-verify fires `backup_dump_file_corrupted` with the exact file path, exit non-zero, dump is renamed to `<date>.failed/` per §8.3 quarantine. (b) Bit-flip in the outer tarball post-encryption → existing outer-checksum guard catches it (regression — already covered, re-asserted here). (c) Dump dir with no inner manifest (legacy) → restore proceeds with `backup_legacy_no_file_manifest` audit row, no failure.

#### 8.14.3 `age` binary supply-chain pin

- [ ] **Doctrine (binding).** The `age` encryption binary is a **first-class build-time dependency** of the `maint.backup.v1` agent and the `ops.restore` CLI. Pinned in the agent's container image at `cfg.maint_backup_age_binary_version` (default `1.2.0`, the upstream release), installed from the upstream release-tagged GitHub binary with the upstream-published checksum verified at image-build time (Dockerfile RUN block: `curl -sSfL <release-url> | sha256sum -c <pinned-hash> && tar -xz`). NOT installed via `apt`/`apk` package managers (those carry distro-level lag and substitute the upstream binary). The Dockerfile pin is **the** source of truth; runtime asserts at agent boot via `subprocess.run(['age', '--version'], check=True, capture_output=True)` and refuses to start if the parsed version != `cfg.maint_backup_age_binary_version` (`fail_safe_age_version_mismatch`). Forward-compat: ops can override via the cfg knob to roll forward without an image rebuild, but the boot assertion still fires loud on mismatch — surfaces silent corruption of the binary or operator-driven downgrades.
- [ ] **Supply-chain provenance.** `infra/maint/age_binary_provenance.txt` (committed) records `{version, sha256, source_url, sigstore_cert_identity_if_any, recorded_at}` per pinned version. CI gate `make verify.age-pin` re-fetches the pinned URL, recomputes the SHA, and asserts it matches the recorded value — drift = supply-chain incident. Operators upgrade the pin via `ops.backup-bump-age VERSION=<v>` (CLI fetches, checksums, updates Dockerfile + provenance file in one PR + runs `make verify.age-pin`); the doctrine forbids hand-edits.
- [ ] **Restore-side parity.** The `ops.restore` CLI (which runs on operator workstations, not in the agent container) reads `cfg.maint_backup_age_binary_version` from the same chart, calls `age --version`, and refuses with `fail_safe_age_version_mismatch_local` if the operator's local `age` differs. Forces operators to install the canonical version (documented in the runbook). Mock profile relaxes the assertion to a `severity=warn` log line.
- [ ] **Proof tests.** (a) Run agent boot with `age` of a different version → assert refuse with `fail_safe_age_version_mismatch`, no spool writes, no cron tick. (b) Run `make verify.age-pin` against a tampered provenance file (wrong sha) → assert exit non-zero with `provenance_drift`. (c) Run `ops.restore` on a host with no `age` installed → assert `age_binary_not_found` exit + runbook link.

#### 8.14.4 opsctl Redis ACL + per-subcommand authorization (signed envelopes)

- [ ] **Real gap.** Today opsctl authenticates to Redis with the same credentials the runtime uses. A compromised operator host (or a misplaced shell history with a `--confirm-destructive` token) can publish *any* `maint.event.v1` kind. Destructive-token defeats finger-fumble, not malice.
- [ ] **Redis ACL (binding).** A dedicated Redis ACL user `negelir_opsctl` is provisioned by the §2 mock-data setup AND the Phase 14 K8s Secret manifest. ACL: `+publish maint.event.v1 +subscribe maint.ack.v1 +client +ping`, NOTHING else. No `+get`/`+set`/`+del`, no access to other streams, no `+evalsha` (Lua). Boot validation in opsctl runs `ACL WHOAMI` and refuses to start if the response is anything other than `negelir_opsctl` (`fail_safe_wrong_redis_user`). Prevents accidental run with the application user's credentials (which would have full bus access).
- [ ] **Signed envelope (binding).** Every opsctl-published envelope carries a payload field `op_signature: <hex>` = `HMAC-SHA256(key=<per-operator-key>, msg=f"{request_id}|{kind}|{target}|{produced_at}")`. The per-operator key lives at `~/.negelir/opsctl_key` (mode 0600, 32 random bytes, generated on first run via `make ops.bootstrap-key`); the matching public-id-only mapping `<key_id> → <operator_email>` is committed to `infra/maint/opsctl_operators.json`. **Consumers of `maint.event.v1` (the §8.x agents) verify the signature before acting** — invalid signature → ack with `accepted=false, reason="op_signature_invalid"` AND emits `sec.alert.v1{kind=opsctl_signature_invalid, severity=critical, subject=<key_id>}` (bypasses debounce). Phase 9 admin endpoint signs server-side using a service identity in the same key registry. Mock profile may set `cfg.opsctl_require_signature=false` to skip verification (default `true` in prod; `false` in mock).
- [ ] **Per-subcommand authorization map.** `infra/maint/opsctl_authz.yaml` (committed) maps `<kind> → list[key_id]` (or `*` for any registered operator). Defaults: every kind allows `*` EXCEPT the destructive set (per §8.1) which lists explicit key_ids only. Consumer-side enforcement: a kind that the signing key is not authorized for → ack `reason="op_not_authorized"` + `sec.alert.v1{kind=opsctl_unauthorized, severity=critical, subject=<key_id>, requested_kind}`. Cumulative effect: a leaked operator key cannot publish destructive ops without also being on the explicit allow list for that op.
- [ ] **Proof tests.** (a) Start opsctl with the application Redis user → refuse with `fail_safe_wrong_redis_user`. (b) Publish an envelope with `op_signature` over a tampered `target` → assert consumer-side ack `op_signature_invalid` + critical alert. (c) Publish `ops.restore` with a key not in the authz allow-list → ack `op_not_authorized` + critical alert. (d) Boot the §2 mock stack and assert the `negelir_opsctl` ACL is created with the documented surface (no `+set`, no `+evalsha`).

#### 8.14.5 DLQ supervisor recursion guard

- [ ] **Real bug.** §8.5 reads `swarmctl topics` ∩ `cfg.maint_dlq_replay_topics_allow` for its source set. `maint.dlq.v1.dlq` is a topic (the supervisor's own failures land there). If an operator widens the allow-list with a wildcard or auto-derives it, the supervisor can subscribe to its own DLQ — every supervisor failure spawns a replay attempt, which can fail, which spawns a replay attempt, etc.
- [ ] **Hardcoded blacklist (binding).** `cfg.maint_dlq_replay_topics_deny` (NOT operator-overridable; pinned in code at `swarm.agents.maint.dlq.RECURSION_DENY_SET = {"maint.dlq.v1.dlq", "maint.event.v1.dlq", "maint.ack.v1.dlq", "sec.alert.v1.dlq"}`). The allow-list is intersected with `swarmctl topics` and **set-differenced** with the deny set; orphans on the operator-supplied allow-list trigger `sec.alert.v1{kind=dlq_recursion_blocked, subject=<topic>, severity=warn}` once at boot for visibility. The supervisor's own DLQ depth is still surfaced via telemetry (`<topic>.dlq` length gauge from §4.6) — operators see backlog without auto-replay amplifying it.
- [ ] **maint.event.v1.dlq escalation path.** A maint-event landing in DLQ means a Phase 8 agent rejected it (signature invalid, schema invalid, etc). Operator-only `ops.dlq-replay --topic maint.event.v1.dlq --id <id> --confirm-destructive=<token>` is the sole replay path; `--confirm-pii` not required (these are control-plane events, no user payloads).
- [ ] **Proof test.** Inject `maint.dlq.v1.dlq` into the operator-supplied allow-list config → assert agent boot emits `dlq_recursion_blocked` and the active subscription set excludes it. Pump 100 entries into `maint.dlq.v1.dlq` → assert zero auto-replay attempts (verified via telemetry counter `maint_dlq_replays_total{topic="maint.dlq.v1.dlq"} == 0`).

#### 8.14.6 `maint.ack.v1` carries `trace_id` (distributed-trace correlation)

- [ ] **Real gap.** Phase 3 §3.2 envelope carries `trace_id`. Today's `maint.ack.v1.json` payload (per §8.1) carries `request_id` but not `trace_id` — a Jaeger-style trace stops at the publish edge and resumes in a new trace at the ack consumer. Operators correlate manually via `request_id`, which works for one-off CLIs but breaks audit pipelines that span multiple operations.
- [ ] **Schema addition.** `maint.ack.v1.json` payload gains `trace_id: str` (required when the consumer's processing envelope carried one; null only for synthetic / test acks). Consumers MUST copy the trace_id from the `maint.event.v1` envelope they are acking, NOT generate a fresh one. Boundary test pins this: a consumer that emits an ack with a `trace_id` not present in any recent `maint.event.v1` for the same `request_id` fails the test.
- [ ] **Trace-context propagation in spool replays.** When an envelope is rehydrated from spool (§8.1 + §8.11), the original `trace_id` is preserved (the spool file is the entire envelope including header fields per the existing schema). Acks for spool-flushed envelopes carry the original trace_id, not a fresh one — operators see one trace span the spool gap.
- [ ] **Versioning.** `maint.ack.v1` schema_version bumps `1 → 2`; the additive field is backward-compatible at the consumer (older agents that don't read `trace_id` are unaffected); producers writing schema_version=1 still work but emit `sec.alert.v1{kind=maint_ack_legacy_schema, severity=info}` once-per-`accepted_by` per process lifetime as a soft nudge to upgrade.
- [ ] **Proof tests.** (a) Round-trip: publish a `maint.event.v1` with `trace_id=T`, assert every ack carries `trace_id=T`. (b) Spool replay: spool an envelope with `trace_id=T`, restart the agent, flush spool, assert the ack from the consumer carries `trace_id=T` (not a new id). (c) Boundary: synthesize an ack with `trace_id=T'` for a `request_id` whose only `maint.event.v1` had `trace_id=T` → boundary test fails.

#### 8.14.7 Schema-sentinel validation rps cap (self-DoS guard)

- [ ] **Real gap.** §8.6 Detector A samples `cfg.maint_schema_sample_rate` (default 0.01) of `telemetry.v1`'s mirror. Default math against `predict.vote` at peak (~1000 rps) = 10 validates/sec, fine. A misconfig to `1.0` against the whole telemetry firehose burns CPU and starves the agent's heartbeat — the schema sentinel itself self-isolates per §8.10 and the operator loses the drift signal.
- [ ] **Hard cap (binding).** `cfg.maint_schema_validate_max_rps` (default 50). The agent maintains a token-bucket per-process; over-budget validates are dropped (sampled-out) and counted in `maint_schema_validates_dropped_total{topic}` (gauge). When dropped-rate exceeds 10% of attempted-rate over a 60s window, emit `sec.alert.v1{kind=maint_schema_sample_rate_too_high, severity=warn}` (debounced) — surfaces the misconfig. Boundary cap on the cap: `cfg.maint_schema_validate_max_rps ≤ 500` (boot-validated; refuses larger values with `fail_safe_validate_rps_cap_exceeded` — pure protection against finger-fumble in the safety knob itself).
- [ ] **Proof tests.** (a) Set sample_rate=1.0 against a 200-rps test bus → assert validates land at ≤ `validate_max_rps`, dropped counter increments, alert fires once. (b) Set `validate_max_rps=10000` → boot refuses with `fail_safe_validate_rps_cap_exceeded`.

#### 8.14.8 Trainer scale-target sole-writer (warm-up race)

- [ ] **Real gap.** §8.2 may emit `kind=scale_decision, target=trainer.v1, prev=0, next=1, reason=retrain_request_warmup` on `retrain_request`. The trainer (Phase 5/9) is the action-of-record consumer of the same event and may self-scale (e.g. if it implements its own queue depth → desired_replicas mapping). Two writers, two scale calls, double-warm.
- [ ] **Boundary (binding).** The set of valid `scale_decision.target` values is partitioned: `cfg.maint_scaler_self_scaling_targets` (default `{trainer.v1}`) is OFF-LIMITS to the auto-scaler — emits trip `scale_throttled, reason=self_scaling_target` AND `sec.alert.v1{kind=scaler_target_forbidden, severity=warn}` (debounced per target). `retrain_request_warmup` is replaced by a softer signal: the scaler emits a `maint.event.v1{kind=trainer_warmup_hint, target=trainer.v1, retrain_request_id, projected_window_s}` (NEW kind) which the trainer MAY consume to pre-warm itself. The trainer remains the sole writer of its own replicas.
- [ ] **Proof tests.** (a) Auto-scaler attempts `scale_decision{target=trainer.v1}` in a unit harness → assert `scale_throttled` + `scaler_target_forbidden` alert + zero runtime calls. (b) On `retrain_request`, assert `kind=trainer_warmup_hint` is emitted instead. (c) Boundary: enumerate registered agents, assert every member of `self_scaling_targets` is also in the registered agent set (orphan check both ways).

#### 8.14.9 `pg_dump` nice level + verify-PG version invariant

- [ ] **Nice level (binding).** `pg_dump --jobs=N` against a shared PG cluster competes with user queries. The §8.3 subprocess is wrapped: `nice -n cfg.maint_backup_pg_dump_nice_level <pg_dump...>` (default `10` — significantly lower priority than interactive queries; configurable down to `0` for dev / dedicated-PG deployments). On Linux, the agent additionally calls `ionice -c 2 -n 7` (best-effort I/O class, lowest priority) when `cfg.maint_backup_pg_dump_ionice=true` (default `true`). Mock profile uses nice=0 (no contention concerns; speeds up tests).
- [ ] **Verify-PG version invariant (binding).** The ephemeral verify-PG image is currently hardcoded as `postgres:16-alpine` in the §8.3 prose; this is wrong because (a) the source PG version may differ (Phase 14 may upgrade to PG 17 before the verify image catches up), (b) `pg_restore` of a dump from a *newer* server into an *older* server is unsupported and may silently fail or restore garbage. New cfg knob `cfg.maint_backup_verify_pg_image` (default `postgres:16-alpine`) is the pin; the source server's version is read from `negelir.manifest.json` (added field `server_version_num: int` from `SHOW server_version_num`) and the agent boot-validates `verify_pg_image_version_num >= source_server_version_num`. Mismatch → refuse with `fail_safe_verify_pg_too_old` and `sec.alert.v1{kind=backup_verify_pg_version_mismatch, severity=critical}`. Operator runbook: bump the cfg knob (and rebuild the SidecarVerifier Job manifest) before upgrading the source PG.
- [ ] **Proof tests.** (a) Verify subprocess wrapping: stub `subprocess.run` and assert the `argv[0]` is `nice` and `-n 10` precedes `pg_dump`. (b) Dump from PG 17 against verify image PG 16 (mocked manifest version_num=170000, image version_num=160000) → assert refuse with `fail_safe_verify_pg_too_old`. (c) Mock profile: assert `nice_level=0`, no `ionice` call.

#### 8.14.10 Spool-flush dir-level lock + newest-first ordering

- [ ] **Real gap.** §8.1 has `data/maint/opsctl_locks/<host>-<kind>-<target>.lock` for the **publish** path (prevents two operator shells from publishing the same logical command). It does NOT cover the **flush** iterator: `make ops.spool-flush` walks `data/maint/opsctl_spool/` and re-publishes every envelope. Two concurrent flush invocations re-publish the same envelopes twice — consumer dedup via `request_id` absorbs the dupes, but the audit row is misleading (`ack_received_count` doubles), and the iteration order is non-deterministic across invocations.
- [ ] **Flush-level flock (binding).** `ops.spool-flush` acquires a non-blocking `fcntl.flock` on `data/maint/opsctl_spool/.flush.lock` (mode 0600); concurrent invocations exit immediately with code 8 (`spool_flush_already_running`) and a stderr hint. Stale lock (process died mid-flush) is reaped on next acquire if `mtime > 2 × cfg.opsctl_ack_timeout_ms`. The agent-side spool flush (§8.11 bus circuit-breaker) uses the analogous `data/maint/agent_spool/<agent>/.flush.lock`.
- [ ] **Newest-first ordering (binding).** Both spool flushes iterate in **newest-first** order (sorted by `<request_id>.envelope.json` mtime descending). Rationale: when the bus comes back, fresh operator intent is more valuable than a 6-day-old enqueued action; dropping order on stale entries also lets the §8.13.3 max-age prune reclaim space without re-publishing soon-to-be-aged-out events. Boundary test pins the iteration order.
- [ ] **Drain-budget per flush.** Each flush invocation drains at most `cfg.opsctl_spool_flush_max_per_run` (default 100) envelopes, then exits with a `kind=spool_flush_partial, drained, remaining` audit event. Operator re-runs to drain more (or sets up a cron). Bounds the wall-clock cost of a single flush against a wedged bus that drops the connection mid-drain.
- [ ] **Proof tests.** (a) Two parallel `ops.spool-flush` → exactly one wins, the other exits 8; total bus publishes equal spool entry count, never double. (b) Spool 200 entries with timestamps spread across 7 days; `flush_max_per_run=100` → first invocation publishes the 100 newest, second publishes the next 100 in newest-first order. (c) Stale-lock reap: write a flush.lock with mtime older than the timeout × 2, run flush → assert lock is reaped + flush proceeds.

#### 8.14.11 Cross-section additions to §8.9 DoD

- [ ] All proof tests in §8.14.1–§8.14.10 land alongside the §8.9 ones (adds ~30 new proof tests).
- [ ] New chaos catalogue stubs in `docs/testing/phase12_catalogue.md` (5): `chaos-audit-prune-storm` (verify partition DETACH stays sub-second under 10M-row table), `chaos-dump-file-bitflip-pre-tar` (verify per-file manifest catches it), `chaos-age-binary-tampered` (verify boot refuses), `chaos-opsctl-signature-forged` (verify consumer-side rejection + critical alert), `chaos-spool-flush-concurrent` (verify exactly-once flush).
- [ ] New `maint.event.v1` kinds (3): `trainer_warmup_hint`, `spool_flush_partial`, `backup_legacy_no_file_manifest`. New `sec.alert.v1` kinds (10): `maint_audit_partition_missing`, `backup_dump_file_corrupted`, `dlq_recursion_blocked`, `maint_ack_legacy_schema`, `maint_schema_sample_rate_too_high`, `scaler_target_forbidden`, `backup_verify_pg_version_mismatch`, `opsctl_signature_invalid`, `opsctl_unauthorized`, `fail_safe_age_version_mismatch_local`. All join the §7.4 known-kinds set; per-kind sub-schemas under `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json` per §0 discipline.
- [ ] New cfg knobs for triangle test: `maint_backup_age_binary_version`, `maint_backup_pg_dump_nice_level`, `maint_backup_pg_dump_ionice`, `maint_backup_verify_pg_image`, `maint_schema_validate_max_rps`, `maint_scaler_self_scaling_targets`, `opsctl_require_signature`, `opsctl_spool_flush_max_per_run`. The §8.9 triangle-test bullet's knob inventory grows accordingly.
- [ ] New exit codes pinned in `xops/opsctl/_exit_codes.py`: `5=no_consumer_for_kind` (already), `6=maint_storage_full` (already), `7=requires_resume_first` (already), `8=spool_flush_already_running` (NEW). Boundary test enumerates `_exit_codes.py` against `_classify.py` and the documented runbook.
- [ ] **Doctrine docs sync.** `docs/guides/backup_runbook.md` extended with `age` install/pin section + verify-PG version-bump procedure. `docs/guides/dr_drill_runbook.md` extended with the per-file manifest verification step. NEW `docs/guides/opsctl_security.md` documents the Redis ACL setup, signed-envelope key generation, and the per-subcommand authz file.
- [ ] **Migration delta.** `migrations/009_maint_audit.sql` is **revised in-place** to land partitioned (this revision precedes any actual schema landing — Phase 8 has not shipped yet, so the migration file does not yet exist on disk; the §8.14.1 design supersedes the §8.9 single-table design before Phase 8 implementation begins). No additional migration number is consumed.
- [ ] **Versioning addendum.** §8.14 lands as an additive doctrine revision; `swarm` chart key gains a **patch** bump on top of the §8.13 patch (still pre-implementation, design only); `xops` patch for the new opsctl ACL/signature surface, the `make verify.age-pin` gate, and `ops.bootstrap-key` / `ops.backup-bump-age` flags; `docs` minor for the new `opsctl_security.md` runbook and the two extended runbooks.

### 8.15 Sixth-pass deep-revision additions (clock-source identity, sub-schema versioning, advisory-lock registry, operator-key lifecycle, audit-log row caps + integrity chain, K8s RBAC catalogue, shed-tier handover, DLQ-drop audit, scheduler noise-windows, verify-concurrency cap + offsite credential rotation + restore-verify forensic capture)

> Closing real gaps the prior five passes still missed. The §8.10 monotonic-clock anchor pauses across container suspend on Linux (Phase 14 in-place resize, node drain) — `decision_window_id` will collide. §0 says "new kind needs a new sub-schema" but never specifies how `<kind>.v2` coexists with `<kind>.v1` consumers mid-rolling-upgrade. §8.7 reaches for `pg_advisory_lock` with no key namespace — collision with Phase 9 trainer reactor is a silent deadlock waiting to happen. §8.14.4 introduces per-operator HMAC keys but skips revocation, rotation cadence, rolling-upgrade cache-coherency, emergency kill-switch, and per-key abuse rate-limits. `maint_audit_log` per-kind sub-schemas allow arbitrary `details` blobs (e.g. `dlq_escalated.original_envelope`) — the §8.13.2 storage cap notices the disk is full, but only after a single megabyte-row already landed. The Phase 14 implementer must hunt across §8.x to assemble the full RBAC + namespace + Secret + PVC catalogue. `opsctl_audit.csv` is fsync+append-only against accidental loss but a root-on-host can `> file.csv` it; the "Postgres mirror once Phase 9 lands" promise leaves a gap. §8.11 tier-3 observer mode is in-process state — the new leader after handover doesn't inherit it and re-amplifies the lag the prior leader was actively shedding. `ops.dlq-replay --drop` is documented but never enumerated as an audit `kind`, so dropped poison entries vanish from the forensic trail. The §8.3 nightly raises PG/IO load enough to fool the §8.2 scaler into spurious scale-up flaps. Sunday cold-verify and Sunday nightly restore-verify can both fire near midnight with no concurrency lock. Offsite credentials have no hot-reload path. Failed restore-verify quarantines the dump but discards `pg_restore` stderr — operators have no postmortem evidence.

#### 8.15.1 Clock-source identity + container-suspend resilience

- [ ] **Real bug.** §8.2's `decision_window_id` and §8.3's `monotonic_ns_at_fire` use Python `time.monotonic_ns()` — under the covers, CPython binds to `CLOCK_MONOTONIC` on Linux. POSIX permits `CLOCK_MONOTONIC` to **pause** while the system is suspended (kernel param `CONFIG_SUSPEND` defaults vary; Linux 5.10+ generally pauses). Phase 14 in-place pod resize and graceful node drain trigger short suspends. After resume, two different scaler windows can share the same `floor(monotonic_ns/window_ns)` because the monotonic clock "stood still" across the suspend — even with the `pod_instance_id` prefix from §8.2, a suspend-resume *within a single process lifetime* defeats the prefix because `pod_instance_id` does not change. `CLOCK_BOOTTIME` (Linux-specific; Python 3.7+ exposes it via `time.clock_gettime(time.CLOCK_BOOTTIME)`) advances **including** suspended time and is the correct anchor for window IDs that must be globally monotonic across suspend boundaries.
- [ ] **Doctrine (binding).** A new helper `swarm.sdk.clock.window_anchor_ns()` is the single API for window-id math. It picks `CLOCK_BOOTTIME` on Linux, `mach_absolute_time` (Python `time.monotonic_ns` already maps to it) on macOS (no suspend in container scenarios), and falls back to `time.monotonic_ns()` elsewhere with a one-shot boot warning + `sec.alert.v1{kind=maint_clock_source_unsupported, severity=warn}` (debounced per-pod). `cfg.maint_scaler_clock_source ∈ {auto, boottime, monotonic}` (default `auto` = the helper above; `boottime` forces and refuses to start if unavailable; `monotonic` is the legacy escape hatch for testing). Boot validation logs the resolved source and emits `maint.event.v1{kind=maint_clock_source_changed, target=<agent>, prev=null|<old>, current=<resolved>, suspend_resilient: bool}` — operators see the choice and any change across upgrades.
- [ ] **Where the change applies.** `decision_window_id` (§8.2), `pod_instance_id` heartbeat (§8.2), `monotonic_ns_at_fire` (§8.3), DLQ supervisor's per-tick budget timer (§8.5), agent-spool `flock` mtime comparisons (§8.11), and the §8.14.10 stale-flush-lock reaper. Anything that today reads `time.monotonic_ns()` in agent code switches to the helper. **Wall-clock readers (cron evaluator, `audit.csv` timestamps) are unchanged** — those are documented wall-clock by design.
- [ ] **Suspend-detection probe.** Agent measures `delta_monotonic = boottime - monotonic` once per heartbeat; a step-up of more than `cfg.maint_clock_suspend_alert_s` (default 30s) within one heartbeat interval indicates a suspend just happened. Logs `maint.event.v1{kind=maint_clock_source_changed, action=suspend_detected, gap_s, recovered_at_utc}` once per event (debounced 60s) for postmortem correlation with double-publish near-misses.
- [ ] **Proof tests.** (a) Unit: monkey-patch the helper to return `boottime` and `monotonic` separately, simulate a 60s suspend (boottime advances, monotonic does not), assert two consecutive `decision_window_id` values differ — they would NOT differ under raw `monotonic`. (b) Boot validation: set `clock_source=boottime` on a stubbed Darwin (no `CLOCK_BOOTTIME`), assert refuse with `fail_safe_clock_source_unavailable`. (c) Suspend-detection: synthesize a 90s gap between heartbeats, assert one `maint_clock_source_changed{action=suspend_detected, gap_s≈90}` event.

#### 8.15.2 Per-kind sub-schema versioning doctrine

- [ ] **Real gap.** §0 says every kind has a sub-schema at `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json`, and §8.13.7 + §8.14.11 register new kinds. Nothing specifies what happens when an existing kind's sub-schema needs a new field. Bumping the parent topic's `schema_version` (envelope-level) breaks every consumer of every other kind during the rolling-upgrade window. Hand-waving "additive only" leaves no enforcement.
- [ ] **Doctrine (binding).** Each per-kind sub-schema carries its own `kind_schema_version: int` (NOT the envelope's `schema_version`). Adding a kind: ship `<kind>.json` with `kind_schema_version: 1`. Adding an **optional** field to an existing kind: bump `kind_schema_version` by 1, list the field as optional with a documented default-when-absent, leave the parent topic `schema_version` unchanged — old consumers ignore the field. Adding a **required** field, removing a field, narrowing a type, or any breaking change: forbidden in-place. Instead, ship a sibling `<kind>.v2.json` with `kind_schema_version: 1` AND register a new `kind_v2` value (e.g. `scale_decision_v2`); the old `kind` continues unchanged for the deprecation window. Both kinds appear in the `_ack_routing.py` map; ops console may emit either at the operator's discretion; consumers narrow on the `kind` string and can support both.
- [ ] **Producer-side validation.** `swarm.sdk.payloads.MaintEvent.<kind>(**fields)` factories check `kind_schema_version` of the loaded sub-schema against an in-code constant; mismatch (e.g. agent code expects v3 but on-disk schema is v2) → `SystemExit(1)` at boot with `fail_safe_kind_schema_drift{kind, code_version, file_version}`. Catches accidental partial schema upgrades (file edited, factory not).
- [ ] **Consumer-side tolerance.** Consumers using `swarm.sdk.payloads.MaintEvent.from_dict(payload)` get back a typed dataclass with all known fields; unknown fields (introduced by a newer `kind_schema_version`) are preserved on a `_extra: dict[str, Any]` slot accessible by name. Consumers that need a field they don't know about must opt-in to the higher kind_schema_version explicitly; never silent "field exists but I'll ignore it".
- [ ] **Deprecation path.** A `kind` superseded by `<kind>_v2` is annotated `"deprecated": true, "superseded_by": "<kind>_v2", "deprecation_window_until": "YYYY-MM-DD"` in the sub-schema. Producers emitting a deprecated kind log a one-shot warning per process. After the documented window, the `<kind>` is moved to a `retired/` subdir and removed from `_ack_routing.py`; spool entries with the retired kind go through the §8.13.3 retired-kind path.
- [ ] **Boundary tests.** (a) Sub-schema enumerator asserts every kind file carries `kind_schema_version: int`. (b) For every `<kind>` with `kind_schema_version > 1`, a backward-compat test loads the v1 example payload and asserts the current factory accepts it (additive-only enforcement). (c) Producer-vs-file version mismatch test (boot-validation refuses).

#### 8.15.3 PG advisory-lock key registry

- [ ] **Real bug.** §8.7's allowlist promote-while-eval race uses `pg_advisory_lock(<key>)`. PG advisory locks share a single global key namespace per database (`bigint` keyspace). Phase 9 trainer reactor will use them, the §8.14.1 audit-log retention pruner will use them (DETACH PARTITION + DROP), and the §8.13.4 forward-migrate-then-verify will use them. Two callers on the same key collide: one blocks, the other proceeds — silent deadlock or double-execution depending on lock variant (shared/exclusive).
- [ ] **Registry (binding).** Single source of truth at `xops/maint/advisory_lock_keys.py`:
  ```python
  # All Postgres advisory-lock keys used by Negelir live here. Append-only.
  ADVISORY_LOCK_KEYS: dict[str, int] = {
      "maint.allowlist.promote_while_eval": 1_001,
      "maint.audit.retention_prune":         1_002,
      "maint.backup.restore_verify_concurrency": 1_003,
      "maint.dlq.replay_global_lock":        1_004,
      "trainer.weights_swap":                2_001,
      # Phase 9+: reserve 3_000-3_999 for API-side locks
  }
  ```
  Boot validation in every agent that uses advisory locks (`from xops.maint.advisory_lock_keys import ADVISORY_LOCK_KEYS, ensure_unique`) calls `ensure_unique()` which asserts no value duplicates. A `BoundLock` wrapper (`xops/maint/advisory_lock.py`) is the only sanctioned API: `with BoundLock("maint.audit.retention_prune", conn, mode="exclusive"): ...`. Boundary test asserts (a) `ensure_unique(ADVISORY_LOCK_KEYS) == True`, (b) AST-scan of `ai/**` and `xops/**` rejects raw `cursor.execute("SELECT pg_advisory_lock(...)")` calls — every advisory-lock use must go through `BoundLock`. Key-collision attempts at runtime (`BoundLock` constructor checks the key string is registered) raise `AdvisoryLockKeyUnregistered` and emit `sec.alert.v1{kind=advisory_lock_key_collision, severity=critical}`.
- [ ] **Lock-hold-time guard.** `BoundLock` records the wall-clock acquire time; on `__exit__`, if held longer than `cfg.maint_advisory_lock_max_hold_ms` (default 5000ms — generous), emits `sec.alert.v1{kind=maint_advisory_lock_held_long, severity=warn, lock_name, hold_ms}` (debounced per lock_name). Catches accidental long transactions inside the lock.
- [ ] **Proof tests.** (a) `ensure_unique` against a key registry with a duplicate → raises. (b) AST scan against a planted `cursor.execute("...pg_advisory_lock(...)")` → fails. (c) Held-too-long: take `BoundLock` and `time.sleep(6)` → assert one alert.

#### 8.15.4 Operator HMAC key lifecycle (revocation, rotation, kill-switch, per-key rate limit)

- [ ] **Real gap.** §8.14.4 ships per-operator HMAC keys + `infra/maint/opsctl_operators.json` mapping `<key_id> → <operator_email>`. Missing: revocation when an operator leaves, rotation cadence, rolling-upgrade cache-coherency (the operators.json is read by every agent — when the file changes, only the pods that have re-read it will reject the revoked key), emergency kill-switch (suspect mass compromise), and per-key abuse rate-limit (a stolen key with valid signature can publish at line rate).
- [ ] **Revocation (binding).** `infra/maint/opsctl_operators.json` schema extended: `{"<key_id>": {"email": "...", "added_at": "iso", "revoked_at": "iso"|null, "revocation_reason": "...|null"}}`. Revocation is **soft** (`revoked_at` set), never hard-delete (audit preservation). Consumers reject signatures from any key with `revoked_at != null` AND `now() > revoked_at + cfg.opsctl_key_revocation_grace_s` (default 60s — short window for in-flight envelopes the operator already published before revocation was requested). Within the grace window, accepted with `accepted=true, reason="grace_window_pre_revocation"`. After the grace window, ack `accepted=false, reason="key_revoked"` + `sec.alert.v1{kind=opsctl_signature_invalid, subject=<key_id>, severity=critical}` per §8.14.4 (critical alert path is reused — a revoked key publishing post-grace is indistinguishable from forgery from the consumer's POV).
- [ ] **Rotation cadence (binding).** Each key carries an implicit max age `cfg.opsctl_key_max_age_days` (default 365). Once per heartbeat the agent computes `max(now - added_at)` across all non-revoked keys; if any exceeds the threshold, emits `sec.alert.v1{kind=opsctl_key_rotation_overdue, key_id, age_days, severity=warn}` (debounced daily). Past `max_age + cfg.opsctl_key_revocation_grace_days` (default 30d) → keys are auto-revoked at consumer side regardless of `revoked_at` field (`accepted=false, reason="key_age_exceeded"`); operator-attested rotations come via `make ops.rotate-key OPERATOR=<email>` which adds a fresh key_id and marks the old one revoked in one PR.
- [ ] **Cache coherency (binding).** Agents poll `infra/maint/opsctl_operators.json` via the same mtime-style mechanism §7.4 uses for sec patterns: `cfg.opsctl_operators_reload_s` (default 60s). On reload, the cache is atomic-swapped; in-flight signature verifications complete against the snapshot they captured at request entry (no race). Mismatch detection: when a signature verifies under the current cache but would have failed under the previous cache (operator just-now rotated), accepted with a one-shot info log per `(key_id, request_id)` for forensic clarity. Consumers MUST NOT cache the operators.json longer than `2 × reload_s` — reload-failure (e.g. file missing) flips the consumer to a fail-safe mode where ALL signatures fail, emitting `sec.alert.v1{kind=opsctl_operators_unreadable, severity=critical}` (bypass debounce).
- [ ] **Emergency kill-switch.** `infra/maint/opsctl_kill_switch` (file presence check on each consume, NOT cached — a single `stat()` per envelope is cheap). When the file exists and `mtime > now - cfg.opsctl_kill_switch_max_age_h` (default 24h — file becomes stale and is treated as removed; forces operator to refresh deliberately), ALL opsctl envelopes are rejected with ack `accepted=false, reason="kill_switch_active"` regardless of signature validity. Use case: suspected mass key compromise. The kill-switch file contents are operator-readable narration ("rotating all keys; back online by 14:00 UTC"); `ops.kill-switch-status` reports current state.
- [ ] **Per-key rate-limit (binding).** A token-bucket per `key_id` at `cfg.opsctl_key_rate_limit_per_min` (default 30 — generous for human ops; far below line rate). Bucket state is per-process at v1 (single-process per leader-elected agent; cross-process at Phase 14 K8s requires Redis-backed counter, deferred). Over-budget envelopes ack `accepted=false, reason="key_rate_limited"` + `sec.alert.v1{kind=opsctl_key_rate_limited, subject=<key_id>, severity=warn}` (debounced 5min per key_id). Caps a stolen key's blast radius even if signature + authz pass.
- [ ] **Audit kinds.** `maint.event.v1{kind=opsctl_key_revoked, key_id, revoked_by, reason}` and `kind=opsctl_key_rotated, prev_key_id, new_key_id, operator_email}` published by `ops.revoke-key` / `ops.rotate-key`. Both go through the existing destructive-token gate.
- [ ] **Proof tests.** (a) Revocation grace: revoke key at T, publish at T+30s → accepted with `grace_window_pre_revocation`; publish at T+90s (default grace=60s) → rejected with `key_revoked` + critical alert. (b) Auto-revoke on age: stub a key with `added_at = now - 400d`, default `max_age=365 + grace=30`, publish at day 401 → rejected with `key_age_exceeded`. (c) Cache coherency: rotate key in operators.json, immediately publish using the new key_id BEFORE the consumer's poll tick → accepted (consumer sees new file via the on-demand reload triggered by an unknown-key cache miss; fall back to file re-read once before failing), assert the rejected-then-accepted path emits no false-critical alert. (d) Kill-switch: touch the file, publish → all rejected with `kill_switch_active`. (e) Per-key rate limit: 50 envelopes in 60s with `limit=30` → first 30 accepted, remaining 20 rejected with `key_rate_limited`; assert one debounced alert.

#### 8.15.5 `maint_audit_log` per-row size cap + per-kind details budget

- [ ] **Real gap.** §8.14.1 partitions the audit log by month; §8.14.5 caps `maint.ack.v1` payload at 4KB. The `maint_audit_log` rows themselves are unbounded — `dlq_escalated` carries `original_envelope` (potentially the entire failing payload), `schema_drift_detected` carries `errors[]` (potentially every drift line), `backup_dump_file_corrupted` carries `corrupted_files[]` (potentially thousands of paths on a worst-case bit-rot event). One pathological INSERT can exceed PG `toast` limits, kill autovacuum throughput, and balloon the partition.
- [ ] **Per-row hard cap (binding).** `cfg.maint_audit_row_max_bytes` (default 16384 = 16KB). Enforced by the §8.14.1 `BEFORE INSERT` trigger: rows whose serialized JSONB `details` column exceeds the cap are **truncated** to a sentinel `{"_truncated": true, "_original_size_bytes": <N>, "_kind": "<kind>", "_first_4kb": "<base64-of-first-4096-bytes>"}` and the original is written to `data/maint/audit_oversize/<row_id>.json` (mode 0600, capped by §8.13.2 storage cap which already covers `data/maint/`). Sec alert `kind=audit_row_oversize, subject=<event_kind>, severity=warn` (debounced per event_kind 1h). Operators investigate the oversize file out-of-band; the audit row stays small enough for fast queries.
- [ ] **Per-kind details budget.** `cfg.maint_audit_per_kind_details_max_bytes` (dict; defaults: `{dlq_escalated: 8192, schema_drift_detected: 4096, backup_dump_file_corrupted: 8192, default: 2048}`) — producer-side validation at the `MaintEvent.<kind>(...)` factory caps `details` BEFORE emit, with the same sentinel pattern (lossy truncation that preserves the kind + first-4KB-of-original). Producer-side cap is the soft fence; the trigger-side cap (above) is the backstop. Both must agree on the sentinel format (single helper at `swarm.sdk.maint_audit.truncate_oversize`).
- [ ] **Proof tests.** (a) Producer factory called with a 32KB `details` for `kind=dlq_escalated` (per-kind cap=8KB) → returned payload is the sentinel + original written to `audit_oversize/`; INSERT into PG succeeds. (b) Trigger backstop: bypass the producer (raw INSERT of a 24KB row for `kind=default` with cap=2KB) → trigger truncates, alert fires. (c) Sentinel round-trip: read back the truncated row + sidecar file, assert reconstruction is byte-identical to original.

#### 8.15.6 K8s namespace + RBAC + Secret + PVC catalogue (single source)

- [ ] **Real gap.** Phase 14 implementer must hunt: `negelir-maint-verify` namespace (§8.3), `maint-scaler` SA + `patch deployments/scale` (§8.2), `coordination.k8s.io/v1.Lease` get/create/update for `replicas:1` agents (§8.10), Secret access `negelir-backup-verify-key` (§8.3), backup PVC + verify PVC + opsctl spool PVC (§0 Phase 14 contract), `negelir_backup` PG role (§8.3), `negelir_audit_pruner` PG role (§8.14.1), `negelir_opsctl` Redis ACL user (§8.14.4). Today scattered across 9 sub-sections; no single table.
- [ ] **Catalogue (binding).** Single doc table at `docs/design/MAINT_DEPLOYMENT_CATALOGUE.md` enumerating, for every §8.x agent: `(agent_id, k8s_namespace, service_account, rbac_rules, secrets_referenced, pvcs_mounted, pg_role, redis_acl_user, lease_name, network_egress)`. The table is the source of truth for the Phase 14 manifests; CI test (Phase 14) asserts every cell maps to a named-and-versioned manifest under `infra/k8s/maint/`. **For Phase 8's purposes (pre-Phase-14)**, the catalogue exists in doc-only form; the columns reserved for K8s manifests are filled with `pending Phase 14` until then.
- [ ] **Authoritative columns** also include the Phase 8 dev-side surfaces: `compose_service_name, compose_volumes, host_paths` so the same catalogue is the source of truth in compose mode too. A boundary test in the §8.9 DoD walks the catalogue and asserts every named compose-service exists in `docker-compose.yml` (or its maint-specific override file).
- [ ] **No new agents introduced here.** This sub-section is pure documentation consolidation — the deliverable is the catalogue file + CI gate + cross-reference back-links from §8.2/§8.3/§8.5/§8.6/§8.10/§8.14.1/§8.14.4 to the catalogue. Boundary test: every `cfg.opsctl_critical_agents` entry has a row; every `cfg.maint_scaler_self_scaling_targets` entry has a row; orphans on either side fail CI.

#### 8.15.7 `opsctl_audit.csv` integrity chain (hash-chain HMAC)

- [ ] **Real gap.** §8.1's `opsctl_audit.csv` is fsync+append-only against accidental loss; the §8.14.1 PG mirror is the strong-tamper-resistant tier but lands "once Phase 9 router wires the admin endpoint". A root-on-host between Phase 8 and Phase 9 can `> opsctl_audit.csv` and lose the entire ops trail; subsequent appends would land in an empty file with no detectable break.
- [ ] **Hash-chain (binding).** Each row gains two columns: `prev_hmac, row_hmac`. `row_hmac = HMAC-SHA256(key=<agent-side-key>, msg=f"{prev_hmac}|{ts_utc}|{user}|{host}|{kind}|{target}|{request_id}")`. The HMAC key lives at `cfg.audit_chain_hmac_key_path` (default `/var/lib/negelir/secrets/audit_chain.key`, mode 0400, generated on first run via `make ops.bootstrap-audit-key`, NEVER readable by the operator — only the maint-backup agent process and the K8s ServiceAccount in Phase 14 can read it). The genesis row carries `prev_hmac = sha256("negelir-audit-chain-v1")[:32]` (constant). A truncation or row-rewrite by a hostile root breaks the chain at the first surviving row whose `prev_hmac` doesn't match the recomputed hash of the prior row.
- [ ] **Continuous verification.** A new `kind=audit_chain_verify` cron tick (runs hourly inside `maint.backup.v1`) walks the file, recomputes the chain, on break emits `sec.alert.v1{kind=audit_log_integrity_break, severity=critical, file_path, first_break_row}` (bypass debounce). The same verification runs at agent boot (catches tampering during pod restart). Verification is O(N) but the file is bounded by `cfg.opsctl_audit_max_bytes` rotation (NEW knob, default 10MB; rotated as `opsctl_audit.csv.<N>` with the chain continuing across rotation: rotated file's last row's `row_hmac` = `prev_hmac` of the new file's first row).
- [ ] **PG mirror parity (Phase 9).** When the §8.1 PG mirror lands at Phase 9, the same `prev_hmac, row_hmac` columns flow into `maint_audit_log`; the integrity-chain verifier additionally cross-checks PG-row-N matches CSV-row-N for the same `request_id`. PG-side advantage: the §8.14.1 INSERT-only trigger means even root-on-host can't silently rewrite history if the PG mirror is healthy.
- [ ] **Proof tests.** (a) Append 10 rows, recompute chain → green. (b) Truncate the file to row 5, append fresh row 6 → next verification fires `audit_log_integrity_break` with `first_break_row=6`. (c) Edit row 3's `kind` field by hand → break detected at row 4 (prev_hmac mismatch). (d) Rotation: write 10 rows, rotate, write 5 more → cross-file chain verifies green; tamper with the rotated file's last row → break detected at the first row of the post-rotation file. (e) Boot-time verification: synthesize a broken chain, start the agent, assert the alert fires before the first cron tick.

#### 8.15.8 Backpressure shed-tier survives leader handover

- [ ] **Real gap.** §8.11 tier-3 observer mode is in-process state. When `replicas:1` agents (§8.10 leader-elected set) lose their lease mid-shedding, the new leader inherits zero shed state — and immediately resumes publishing at full rate, re-amplifying the plane lag the prior leader was actively shedding. Worst case: leader churn during a real plane-wide incident produces a publish-rate sawtooth that perpetuates the incident.
- [ ] **Lease-annotation persistence (binding).** The K8s `coordination.k8s.io/v1.Lease` object owned by each `replicas:1` agent gains JSON-serialized annotations: `negelir.io/maint-shed-tier: "0|1|2|3"`, `negelir.io/maint-shed-since-utc: "iso"`, `negelir.io/maint-shed-reason: "..."`. The leader updates these atomically with each tier transition (single `Lease.update()` call — avoids split-brain across two API objects). On lease acquisition, the new leader reads the annotations and **inherits the shed tier** for at least `cfg.maint_plane_recovery_window_s` (default 120s, same as §8.11 recovery window) before it can independently decide to lower the tier. Compose mode: annotations live at `data/maint/lease/<agent>.shed_state.json` (mode 0600; written atomically via temp+rename); same inherit-on-start behavior at boot (catches process restart, not just leader handover).
- [ ] **Cross-pod coherency.** Tier transitions are still **one event per transition** (§8.11 self-amplification rule), but the new leader emits a `kind=maint_plane_throttled, tier=<inherited>, action=inherited_from_lease, prior_leader_pod_instance_id` event on first tick after acquisition — operators see the inheritance + can correlate handover-driven double-events would have been (§8.11 says one-per-transition, this is one-per-handover-with-inheritance, semantically distinct).
- [ ] **Boundary test.** §8.10 leader-required set walked: every entry has the lease-annotation read/write hook (AST scan). Compose-mode `data/maint/lease/<agent>.shed_state.json` writers walked: every shed-tier transition emits the annotation update.
- [ ] **Proof tests.** (a) Leader-A transitions to tier 2, lease handover to Leader-B simulated mid-tier → Leader-B reads tier=2 from annotation, holds for `recovery_window_s`, emits one `inherited_from_lease` event. (b) Leader-A transitions to tier 3 then crashes; new leader after 30s reads tier=3, holds full window. (c) Compose-mode equivalent: Leader-A writes shed_state.json at tier 2, restart Leader-A (single replica) → on boot reads its own state and re-enters tier 2 (handles process flap, not just leadership flap).

#### 8.15.9 `dlq_dropped` audit kind + scheduler noise-windows

- [ ] **Real gap A — dropped-poison forensic gap.** §8.5's `ops.dlq-replay --drop` is documented as the operator's manual surface to acknowledge-and-remove a poison entry. No `kind=dlq_dropped` event is enumerated in §3.5 or §0; the dropped entry vanishes from the trail. Operators can reconstruct only via the `opsctl_audit.csv` row (which records the *opsctl invocation* but not the *original failing envelope's request_id* → the link to upstream investigation is broken).
- [ ] **Fix.** Add `kind=dlq_dropped` to the §0 known-kinds list. Sub-schema requires `{topic, dlq_entry_id, original_request_id, original_envelope_summary: {topic, producer, attempt, last_error}, dropped_by, drop_reason}`. The `original_envelope_summary` is the §8.15.5-capped summary, NOT the full envelope (which already exists in DLQ; we don't re-archive it). Emitted by `ops.dlq-replay --drop` consumer (the DLQ supervisor itself, on receipt of the operator-driven drop request — operator's opsctl envelope carries `kind=dlq_drop_request`, supervisor acks AND emits `kind=dlq_dropped` for the audit channel).
- [ ] **Real gap B — scheduler noise-windows.** §8.3 nightly raises PG/IO/network load substantially during pg_dump --jobs=N + age streaming + offsite multipart upload. The §8.2 scaler reads predictor latency p95 + DLQ depth and may scale up predictors during the backup window — wasted resources, false flap, recovery scale-down 10 min later when the next §8.2 window observes "nothing wrong".
- [ ] **Fix.** `cfg.maint_scaler_noise_windows` (list of cron expressions; default `["0 3-5 * * *", "0 5 * * 0"]` — covers §8.3 nightly 03:00-05:00 + Sunday 05:00 cold-verify). During an active noise window, the scaler suppresses load-driven decisions (`reason ∈ {lag_high, cpu_high, p95_high, dlq_depth_high}`) and emits `kind=scale_throttled, reason=noise_window_active, observed:{noise_window: "<cron>"}` once per affected target per window entry. Emergency reasons (`vram_budget_exceeded`, `manual_pin`, `retrain_request_warmup`, `sec_rate_burst`) ALWAYS fire — capacity emergencies and security signals trump noise suppression. Window evaluation reuses the §8.3 stdlib cron evaluator. Info-level `sec.alert.v1{kind=scaler_noise_window_active, severity=info}` once per window-entry-edge (transition), not per tick.
- [ ] **Proof tests.** (a) `ops.dlq-replay --drop --topic predict.vote --id <id>` → assert DLQ supervisor publishes `kind=dlq_dropped` with the original request_id; ack from ops console contains both the opsctl request_id and the dropped envelope's request_id. (b) Stub current time inside `0 3-5 * * *` noise window, inject `lag_high` signal → assert `scale_throttled, reason=noise_window_active`, no runtime call. (c) Same window, inject `vram_budget_exceeded` → assert scale call DOES fire (emergency override). (d) Window-edge transitions: walk the clock across `02:55→03:00→05:01` boundaries, assert exactly two `scaler_noise_window_active` info events (one entry-edge, one exit-edge — though exit-edge optional for noise reduction; pin which one in the test).

#### 8.15.10 Verify-concurrency cap, offsite credential hot-reload, restore-verify forensic capture

- [ ] **Real gap A — verify concurrency.** Sunday cold-verify (§8.3) and Sunday nightly restore-verify (post-dump) can both fire near the Sunday-05:00 cron edge. Two ephemeral PVCs, two `pg_restore --jobs=N` against the same verify image — under-provisioned verify clusters OOM; both may fail with no useful error. No global concurrency lock today.
- [ ] **Fix A.** Single PG advisory lock `maint.backup.restore_verify_concurrency` (registered in the §8.15.3 registry). Both code paths acquire it before spawning the ephemeral verify resources; second acquirer waits up to `cfg.maint_backup_verify_lock_timeout_s` (default 1800s = 30 min, generous) then either retries or yields with `kind=verify_concurrency_blocked, scope=cold|nightly` audit + `sec.alert.v1{kind=verify_concurrency_blocked, severity=warn}` (debounced). Yield policy: cold-verify YIELDS to nightly (cold-verify can re-run next Sunday; nightly is daily). Lock is released in a `finally` block — agent crash mid-verify releases automatically (PG advisory locks die with the connection).
- [ ] **Real gap B — offsite credential rotation.** §8.12 reads `S3CompatibleTarget` access keys at startup. Operator rotates the S3 access key (90d cadence per security best practice) → either restart the agent (loses partial multipart upload from the §8.12 idempotent-resume logic; restart-races against leader handover) OR keep the old key alive (security risk).
- [ ] **Fix B.** Credentials are read via a `CredentialProvider` Protocol with two implementations: `FileSecretProvider` (compose mode; mtime-poll the secret file every `cfg.maint_backup_offsite_cred_reload_s`, default 60s; atomic-swap on change) and `K8sSecretProvider` (Phase 14; uses `k8s.io/client-go` watch on the named Secret with the same atomic-swap semantics). Active multipart uploads CONTINUE on the old credentials until completion (S3 multipart upload state is server-side keyed off the upload ID and the original credentials' STS context; switching mid-stream may invalidate it). New uploads use the new credentials. Credential age is tracked: `cfg.maint_backup_offsite_credential_max_age_days` (default 90); past threshold the agent emits `sec.alert.v1{kind=offsite_credential_rotation_required, severity=warn, age_days}` (daily debounce); past `max_age + grace_days` (default 30) the agent stops new uploads and emits `severity=critical` (refuses-to-upload-but-keeps-running so the rest of the maint plane is unaffected; operator-facing forced rotation).
- [ ] **Real gap C — restore-verify forensic capture.** §8.3 quarantines failed dumps to `<date>.failed/` but `pg_restore --jobs=...`'s stderr/stdout/exit-code are discarded (the agent only captures the exit code via `subprocess.run(..., capture_output=True)` — the captured streams are logged at runtime then thrown away). Operator postmortem has nothing to work with.
- [ ] **Fix C.** Failed restore-verify writes a forensic sidecar to `<date>.failed/verify_forensic.json`: `{verifier_kind: "local|sidecar", pg_restore_exit_code, pg_restore_stderr (≤ 64KB tail), pg_restore_stdout (≤ 64KB tail), verify_sql_results: [{query, error|row_count}], duration_ms, verify_pg_image, manifest_server_version_num, file_manifest_failures: [...] (from §8.14.2)}`. Mode 0600. Bounded to `cfg.maint_backup_forensic_max_bytes` (default 256KB total; truncate the largest field first to fit). Audit kind `kind=verify_forensic_captured, target=<date>, size_bytes` enumerated in §0.
- [ ] **Proof tests.** (a) Concurrency: race cold-verify and nightly start within 1s of each other → assert exactly one acquires the advisory lock first, the other emits `verify_concurrency_blocked` + waits-then-yields per policy. (b) Credential reload: rotate the secret file mid-running multipart upload → assert in-flight upload completes on old creds (mock the S3 backend to track the credential identity per request); next upload uses new creds. (c) Forensic capture: force a `pg_restore` failure with a 100KB stderr → assert sidecar exists, stderr is tail-truncated to 64KB, audit kind emitted with `size_bytes` matching file size.

#### 8.15.11 Cross-section additions to §8.9 DoD

- [ ] All proof tests in §8.15.1–§8.15.10 land alongside the §8.9 ones (adds ~25 new proof tests).
- [ ] New chaos catalogue stubs in `docs/testing/phase12_catalogue.md` (6): `chaos-container-suspend-window` (verify §8.15.1 boottime survives), `chaos-revoked-key-replay` (verify §8.15.4 grace + post-grace rejection), `chaos-audit-truncate-attack` (verify §8.15.7 hash-chain catches it), `chaos-leader-handover-mid-shed` (verify §8.15.8 inheritance), `chaos-noise-window-emergency-override` (verify §8.15.9 vram_budget_exceeded fires through suppression), `chaos-verify-concurrency-deadlock` (verify §8.15.10 yield).
- [ ] New `maint.event.v1` kinds (5): `maint_clock_source_changed`, `opsctl_key_revoked`, `opsctl_key_rotated`, `dlq_dropped`, `verify_forensic_captured`. New `sec.alert.v1` kinds (10): `maint_clock_source_unsupported`, `advisory_lock_key_collision`, `maint_advisory_lock_held_long`, `opsctl_key_rotation_overdue`, `opsctl_operators_unreadable`, `opsctl_key_rate_limited`, `audit_row_oversize`, `audit_log_integrity_break`, `verify_concurrency_blocked`, `offsite_credential_rotation_required`, `scaler_noise_window_active` (info-only). All join the §7.4 known-kinds set; per-kind sub-schemas under `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json` per §0 + §8.15.2 versioning discipline.
- [ ] New cfg knobs for triangle test: `maint_scaler_clock_source`, `maint_clock_suspend_alert_s`, `maint_advisory_lock_max_hold_ms`, `opsctl_key_max_age_days`, `opsctl_key_revocation_grace_s`, `opsctl_operators_reload_s`, `opsctl_kill_switch_max_age_h`, `opsctl_key_rate_limit_per_min`, `maint_audit_row_max_bytes`, `maint_audit_per_kind_details_max_bytes` (dict), `audit_chain_hmac_key_path`, `opsctl_audit_max_bytes`, `maint_scaler_noise_windows` (list), `maint_backup_verify_lock_timeout_s`, `maint_backup_offsite_cred_reload_s`, `maint_backup_offsite_credential_max_age_days`, `maint_backup_forensic_max_bytes`. The §8.9 triangle-test bullet's knob inventory grows accordingly (~17 new knobs).
- [ ] New exit code pinned in `xops/opsctl/_exit_codes.py`: `9=opsctl_key_revoked` (operator's local key rejected pre-publish via `ACL WHOAMI` parity check). Boundary test enumerates `_exit_codes.py` against `_classify.py` and the documented runbook (now `5..9` continuous range).
- [ ] **Doctrine docs sync.** NEW `docs/design/MAINT_DEPLOYMENT_CATALOGUE.md` per §8.15.6. `docs/guides/opsctl_security.md` extended with §8.15.4 lifecycle (revocation/rotation/kill-switch). `docs/guides/backup_runbook.md` extended with §8.15.10 credential rotation procedure + forensic-capture postmortem walkthrough. `docs/design/SECURITY.md` cross-link added to the audit-chain HMAC discipline.
- [ ] **Migration delta.** No new migration consumed. `migrations/009_maint_audit.sql` (still pre-implementation) gains the `prev_hmac CHAR(64)` + `row_hmac CHAR(64)` columns from §8.15.7, and the §8.14.1 `BEFORE INSERT` trigger gets the §8.15.5 row-size cap branch — both edits are to the same not-yet-shipped migration file, no schema-number conflict.
- [ ] **Versioning addendum.** §8.15 lands as an additive doctrine revision; `swarm` chart key gains a **patch** bump on top of the §8.14 patch (still pre-implementation, design only); `xops` patch for the new `xops/maint/advisory_lock.py` + `swarm/sdk/clock.py` + `ops.revoke-key` / `ops.rotate-key` / `ops.kill-switch-status` / `ops.bootstrap-audit-key` flags; `docs` minor for the new `MAINT_DEPLOYMENT_CATALOGUE.md` + extended runbooks.

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
