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

- [x] CLI entry point `xops/opsctl/__main__.py` invoked via `make ops.<cmd>` shortcuts (`ops.denylist-clear`, `ops.baseline-reset`, `ops.quarantine-erase`, `ops.quarantine-clear`, `ops.retrain-approve`, `ops.scale`, `ops.scale-pin`, `ops.scale-unpin`, `ops.backup-now`, `ops.backup-rotate-key`, `ops.restore`, `ops.dlq-replay`, `ops.dlq-resume`, `ops.allowlist-extend`, `ops.allowlist-approve`, `ops.allowlist-show`, `ops.maint-pause`, `ops.maint-resume`, `ops.spool-flush`, `ops.spool-show`, `ops.liveness`). _Closed: 23-subcommand surface registered in `xops/opsctl/subcommands/__init__.py::SUBCOMMANDS`; `ops.dlq-resume` is a thin alias of `ops.dlq-unfreeze` (same `maint.event.v1{kind=dlq_unfreeze}` envelope per §8.13.5)._
- [x] Each subcommand:
  - Validates inputs locally (`target` is a known subject; `kind` is in the open-enum allow-list; `client_id` defaults to the OS username; subject syntax is rule-checked — IPs for denylist subjects, `<source>:<rule_id>` for allowlist subjects, registered agent ids for scale targets).
  - Constructs an `Envelope` with `request_id = uuid4()`, `produced_at = now_utc()`, `schema_version = 1`, and `client_id = "<os_user>@<hostname>"`.
  - Publishes to `maint.event.v1` via the same `Bus` Protocol used by the runtime (Redis Streams in prod, `InMemoryBus` in tests).
  - Waits ≤ `cfg.opsctl_ack_timeout_ms` (default 5000) for the **expected ack set** (per the §0 ack semantics — set of `(accepted_by)` agents derived from kind→consumer routing). Partial-ack timeout → exit code 3 + structured stderr listing missing acks. Hard timeout (no acks at all) → exit code 2.
  - Supports `--dry-run` (validates + computes the expected ack set + prints the envelope to stdout, **does not publish**) and `--json` (machine-readable result for runbook automation).
- [x] **Destructive-command confirmation gate (binding).** Subcommands classified `destructive=true` in `xops/opsctl/_classify.py` REFUSE to publish without `--confirm-destructive=<typed-token>` where `<typed-token>` MUST equal a stable per-command derivation `sha256(f"{cmd}|{target}|{salient_args}")[:8]` printed by the CLI on the first dry-run-equivalent attempt (operator copy-pastes — defeats accidental shell-history re-runs). Default destructive set: `ops.scale --replicas 0`, `ops.scale` requesting `>50%` reduction vs current desired, `ops.dlq-replay --drop`, `ops.dlq-replay --topic sec.* --confirm-pii` (still requires `--confirm-pii` AND `--confirm-destructive`), `ops.quarantine-erase`, `ops.restore`, `ops.backup-rotate-key`, `ops.maint-pause --agent <id>` for any agent in `cfg.opsctl_critical_agents` (default = `{consensus.v1, sec.rate.v1, maint.backup.v1}`). Boundary test enumerates the destructive set against `_classify.py` and refuses orphans either way. _Closed: `TestDestructiveSetBoundary` in `xops/opsctl/tests/test_opsctl_phase81_subcommands.py` asserts the doctrine `ALWAYS_DESTRUCTIVE = {quarantine-erase, restore, backup-rotate-key}` and `ALWAYS_SAFE = {liveness, spool-show, allowlist-show, scale-unpin}` against `_classify.py` — orphan registrations either way fail the test._
- [x] **Bus-down spool.** If the bus publish fails (Redis unreachable, auth error, schema reject), the envelope is appended to `data/maint/opsctl_spool/<request_id>.envelope.json` (mode 0600) and the CLI exits 4. A separate `make ops.spool-flush` reattempts every spooled envelope in append order; flush is idempotent (consumer-side `request_id` dedup absorbs replays). The spool dir is bounded at `cfg.opsctl_spool_max_entries` (default 1024) — overflow refuses new publishes loud.
- [x] **Re-entrancy lock.** A per-`(host, kind, target)` advisory lockfile under `data/maint/opsctl_locks/` (acquired with `fcntl.flock` non-blocking) prevents two operator shells from publishing the same logical command in flight. Stale locks (older than `2 × opsctl_ack_timeout_ms`) are reaped on next acquire. _Closed: `xops/opsctl/_lock.py` (`reentrancy_lock` ctx manager + `_maybe_reap_stale` probe via O_RDONLY+flock+unlink); lockfile name = `{safe_kind}.{sha256_hex[:32]}.lock`; lockfiles 0600, parent dir 0700; stale factor configurable via `cfg.opsctl_lock_stale_factor` (default 2). Wired into `xops/opsctl/_runner.py::run_publish` so every destructive subcommand acquires before publish. Lock contention exits 1 (GENERIC_FAILURE) with audit-row + stderr note. Tests: `test_opsctl_lock.py` (filename determinism, acquire+release-unlinks, contention via held fd, stale-reap on backdated mtime)._
- [x] **Audit row.** Every successful publish appends to `data/maint/opsctl_audit.csv` (append-only, **`fsync` after each write AND after the underlying directory `fsync` on first creation**, schema = `ts_utc, user, host, kind, target, request_id, expected_ack_set, ack_received_count, exit_code, duration_ms`). The same row is mirrored to `maint_audit_log` (Postgres) once Phase 9 lands. File mode 0600.
- [x] **No bypass channels.** The CLI must NOT write directly to Postgres or Redis state — it only publishes envelopes. Boundary test: AST scan of `xops/opsctl/**.py` rejects `psycopg`, `redis.client.Redis.set/del/hset/zadd/expire`, `subprocess.*` invocations of `psql`/`redis-cli`, and any module-level network connection outside the published `Bus` Protocol.
- [x] **`maint.ack.v1` schema.** New JSON schema at `ai/swarm/sdk/schemas/maint.ack.v1.json` carrying `{request_id, accepted: bool, accepted_by: <agent_id>, reason?: str (≤ cfg.maint_ack_reason_max_bytes, default 512), details?: object (≤ cfg.maint_ack_details_max_bytes, default 2048; flat key/value, no nested arrays of objects), processed_at: iso, attempt: int}`. **Hard size cap** at `cfg.maint_ack_payload_max_bytes` (default 4096) is enforced at emit time; oversize acks are truncated with `reason="truncated:<original_len>"` and a `sec.alert.v1{kind=maint_ack_oversize, severity=warn}` (debounced per `accepted_by`) — prevents a buggy consumer from OOMing the publisher's wait-buffer. **Per-consumer semantics:** every consumer that processes a `maint.event.v1{request_id}` publishes exactly one `maint.ack.v1` with its own `accepted_by`. Re-deliveries published by the bus do **not** produce additional acks (the consumer's idempotency ledger collapses dupes; ack `attempt > 1` is reserved for explicit retries surfaced by the consumer). _Closed: schema lives at `ai/swarm/sdk/schemas/maint.ack.v1.json`; emit-time cap implemented in `ai/swarm/sdk/maint_ack.py::build_capped_maint_ack` (truncates `details`, preserves operator `reason` prefix when appending `" | truncated:<N>"`, independently clips `reason` at `maint_ack_reason_max_bytes` with `…` suffix, returns a `MaintAckOversizeNotice` for caller-side debouncing); `maint_ack_oversize` registered in `ai/swarm/agents/payloads.py::KNOWN_SEC_ALERT_KINDS`. Per-consumer ack-routing wiring lands with §8.0 base-class consumer landing._
- [x] **Idempotency guard.** Re-running `ops.denylist-clear --target <ip>` for an already-cleared subject is a no-op at the consumer side and surfaces `ack.accepted=true, reason="already_cleared"` — never a hard error (operators muscle-memory re-run; the system tolerates it).

### 8.2 Auto-scaler agent (`maint.scaler.v1`)

> Continuous control loop: read telemetry, decide desired replica counts per agent, call the runtime controller, audit. Hysteresis everywhere.

- [x] **Runtime selector.** `cfg.maint_runtime ∈ {compose, k8s, none}` (default `compose` in dev, `none` in tests, `k8s` in Phase 14). `none` makes the scaler a pure observer — emits `scale_decision` events but performs no runtime call (useful for shadow-mode rollout). Boot-time validation: refuses to start with `compose` selected if `cfg.maint_scaler_compose_file` does not exist. _(Closed: `ai/swarm/agents/maint/runtime.py` ships `NoopController` + `ComposeController` + `make_runtime_controller()` with file-existence boot validation; `cfg.maint_runtime` validator rejects unknown values; `k8s` raises `NotImplementedError` (refuse over silent-noop). Tests: `test_compose_controller_invokes_subprocess`, `test_compose_controller_refuses_missing_file`, `test_runtime_factory_selects_noop_by_default`, `test_runtime_factory_refuses_k8s_until_phase_14`, `test_cfg_rejects_unknown_maint_runtime`.)_
- [x] **Inputs:** the agent maintains a rolling `cfg.maint_scaler_window_s` (default 60s) sketch over telemetry counters Phase 4.6 already publishes — stream lag per topic, agent CPU%, predictor latency p95, DLQ depth, plus the Phase 7 `sec.alert.v1{kind=rate_burst, severity≥warn}` signal for API-frontend scale-up. Sketch storage uses constant-memory Welford (mean+variance) per signal, mirroring Phase 7 §7.2 streaming-statistic discipline; no unbounded backfill.
- [x] **Decision function:** `desired_replicas = clamp(min_replicas, ceil(observed_load / cfg.maint_scaler_target_load_per_replica), cfg.maint_scaler_max_replicas[<agent>])`. Per-agent caps live in `cfg.maint_scaler_max_replicas` (dict, validated at boot — refuses to start if any registered agent is missing an entry, mirrors the Phase 7 §7.6 endpoint-cost totality test). **Hard global cap** `cfg.maint_scaler_global_max_replicas` (default 64) prevents runaway in cloud (Phase 14).
- [x] **`decision_window_id` definition (binding).** `f"{agent}:{floor(monotonic_ns / cfg.maint_scaler_window_ns)}"` where `cfg.maint_scaler_window_ns` is derived from `maint_scaler_window_s × 1e9`. Anchored on **monotonic** clock, not wall-clock — survives NTP slews. Window-id collisions across pod restarts are absorbed by the `Ledger` (the post-restart agent reloads the last 2 windows from Postgres at Phase 9; in-memory only at v1, with a documented "first 2 windows after restart may double-publish" caveat covered by the Phase 14 leader-election guard below). _(Closed: `MaintScaler._window_id()` returns `f"{pod_instance_id}:{anchor_ns}"` using `swarm.sdk.clock.window_anchor_ns(...)` against `cfg.maint_scaler_clock_source` (CLOCK_BOOTTIME on Linux); test `test_decision_window_id_has_pod_instance_id_prefix`.)_
- [x] **Hysteresis & flap damping.**
  - Min interval between decisions per `(agent, runtime)` = `cfg.maint_scaler_min_decision_interval_s` (default 90s). Decisions inside the window are coalesced (latest desired wins, no scale call issued).
  - Scale-down requires the proposed lower replica count to hold for ≥ `cfg.maint_scaler_scale_down_grace_s` (default 300s) of consecutive samples. Scale-up has no grace (capacity emergencies are not damped).
  - On every emitted decision, publish `maint.event.v1{kind=scale_decision, target=<agent>, prev=N, next=M, reason, observed: {...}, decision_window_id}` for audit. Reason is one of `{lag_high, lag_low, cpu_high, cpu_low, p95_high, dlq_depth_high, sec_rate_burst, vram_budget_exceeded, retrain_request_warmup, manual_pin, manual_override_detected}`.
  - Throttled decisions (cap hit, vram refused, runtime returned non-zero, manual-pin override active) emit `kind=scale_throttled` + `sec.alert.v1{kind=scale_throttled, severity=warn}` (debounced).
- [x] **Operator-pin override (consumer of `maint.event.v1{kind=manual_scale_pin, target=<agent>, replicas=N, ttl_s=T}`).** Pins the desired replica count for `<agent>` to `N` for `T ≤ cfg.maint_scaler_pin_max_ttl_s` (default 3600). Auto-scaler decisions during the pin emit `scale_throttled, reason=manual_pin` and **do not** call the runtime. Pin expiry publishes `kind=manual_scale_pin_expired` and the loop resumes. `ops.scale-unpin` short-circuits via the same path. _(Closed: `MaintScaler._handle_pin()` honours `replicas=-1` cancel + `ttl_s` clamp via `cfg.maint_scaler_manual_pin_ttl_s`; `_expire_pins()` emits `manual_scale_pin_expired`; `tick()` emits `scale_throttled{reason=manual_pin_active}` for pinned targets. Tests: `test_manual_scale_pin_emits_decision_and_ack`, `test_pinned_target_emits_throttled_with_manual_pin_active`.)_
- [x] **`decision_window_id` post-restart safety.** The monotonic-anchored id is per-process; after a restart the counter resets. To prevent **ledger collision after restart** (a fresh `agent:0` window-id colliding with a pre-restart one already in the Postgres ledger at Phase 9), the id is prefixed with a stable `pod_instance_id`: `f"{agent}:{pod_instance_id}:{floor(monotonic_ns/window_ns)}"` where `pod_instance_id = sha256(boot_random_16B)[:8]` (re-rolled at every process start, persisted to `/run/maint/pod_instance_id` for crash-recovery within a single liveness cycle). Idempotency proof test: restart the scaler process mid-window, assert the next `scale_decision` carries a fresh `pod_instance_id` and the Phase 9 ledger does not flag a duplicate.
- [x] **Single-publication of `scale_decision`.** Exactly one event per `decision_window_id` even under at-least-once redelivery from telemetry. Guarded by the Phase 4.7 `Ledger` Protocol (in-memory now, Postgres at Phase 9). `replicas: 1` enforced at Phase 14 with **leader-election** (see §8.10) so rolling upgrades cannot briefly co-issue. _(Closed: `tick()` checks `st.last_window_ns >= window_anchor` before any decision; `_handle_retrain_request()` uses an LRU dedup keyed on `envelope.message_id × target`; `SingleProcessLeader.is_leader()` gates emission. Tests: `test_retrain_request_dedup_skips_duplicate`, `test_non_leader_no_decision_but_acks`. Postgres-backed ledger deferred to Phase 9.)_
- [x] **Runtime adapters.** `RuntimeController` Protocol with three implementations:
  - `ComposeController` (dev only) — invokes `docker compose -f <compose_file> up -d --scale <svc>=N --no-recreate`. The compose file path comes from `cfg.maint_scaler_compose_file`. Subprocess run with `check=True`, captured stderr, `cfg.maint_scaler_runtime_timeout_s` (default 30s) timeout, retries=0 (next decision tick is the retry surface). Requires the agent container to mount the host docker socket — **explicitly forbidden in prod** (Phase 14 K8sController is mandatory for cloud).
  - `K8sController` (Phase 14) — uses `kubernetes.client.AppsV1Api.patch_namespaced_deployment_scale`. RBAC: a dedicated `maint-scaler` ServiceAccount with `patch` on `deployments/scale` only (least-privilege; the Phase 14 manifest pins this). `NoopController` returns success; used for `cfg.maint_runtime=none`.
  - All three implementations enforce the §8.2 hard caps **after** the runtime call returns success (defense-in-depth — if a human bypassed the agent and over-scaled in compose, the next decision tick scales it back down, with a `kind=scale_throttled, reason=manual_override_detected` audit event).
- [x] **VRAM accounting source (binding).** Each predictor pod publishes `telemetry.v1{kind=device_probe, agent=<id>, vram_total_mb, vram_used_mb, device=cuda|rocm|npu|cpu}` once per heartbeat (Phase 11 contract). The scaler aggregates the latest probe per `(agent, host)` into `cfg.maint_scaler_vram_budget_mb` (computed = `Σ vram_total_mb − cfg.maint_scaler_vram_headroom_mb`, default headroom 1024). Before issuing a scale-up that would push `Σ vram_used_mb + (next−prev) × cfg.predictor_max_vram_mb` over the budget, refuse + emit `scale_throttled, reason=vram_budget_exceeded, observed:{budget_mb, projected_mb}`. CPU-only path bypasses VRAM checks entirely. Stale probes (`now − last_probe_at > 3 × heartbeat_sec`) are excluded from aggregation; if all probes are stale, scale-up of GPU-bound agents refuses with `reason=vram_telemetry_stale` (fail-safe). _(Closed: `MaintScaler.update_device_probe(...)` accepts `(vram_total_mb, vram_used_mb, vram_per_replica_mb)`; `_check_vram_budget(...)` enforces `vram_total_mb − cfg.maint_scaler_vram_headroom_mb` with a 5-decision-window staleness gate that refuses scale-up as `vram_telemetry_stale`. Tests: `test_vram_budget_exceeded_blocks_scale_up`, `test_vram_telemetry_stale_fail_safe`. Live `telemetry.v1{kind=device_probe}` consumer wiring deferred to Phase 11.)_
- [x] **Drift-driven warm-up (consumer of `maint.event.v1{kind=retrain_request}`).** When drift fires, the scaler may pre-warm a trainer pod via a `kind=scale_decision, target=trainer.v1, prev=0, next=1, reason=retrain_request_warmup`. The trainer remains a separate workload — the scaler never publishes weights and never publishes `kind=retrain_approve`. Warm-up is keyed on `(target_agent, retrain_request.request_id)` so concurrent drift events do not stack pods. _(Closed: `MaintScaler._handle_retrain_request()` warms only `trainer.v1`, never publishes `retrain_approve`, dedups via LRU on `envelope.message_id × target` (1024 cap), and emits a `scale_decision{prev, next, reason=retrain_request_warmup, observed}`. Tests: `test_retrain_request_warms_trainer_once`, `test_retrain_request_dedup_skips_duplicate`.)_
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
- [x] **PII erase (consumer of `maint.event.v1{kind=quarantine_erase, target=<client_id>}`).**
  - Loads matching `quarantine_samples` rows by `client_id`, sets `raw_bytes_b64 = NULL`, sets `erased_at = now()`, leaves `quarantine_id` row in place for audit.
  - Emits `maint.event.v1{kind=pii_erased, target=<client_id>, table=quarantine_samples, row_count, erased_at}` and a corresponding `maint_audit_log` insert (right-to-erasure traceability per [`design/SECURITY.md`](../design/SECURITY.md)).
  - Acks via `maint.ack.v1` with `accepted=true, reason="erased <N> rows"` or `accepted=true, reason="no rows matched"` (the absence of rows is a successful no-op, not an error — a client_id that was never seen is the desired state).
- [ ] **Disk-usage guard.** Before each dump, refuses to start if free space on `cfg.maint_backup_dir` < `max(2× last_dump_size, cfg.maint_backup_min_free_gb)` (default 5 GB headroom). Emits `sec.alert.v1{kind=backup_disk_pressure, severity=error}`. Refusal counts toward the catch-up debt — next tick retries.
- [ ] **Backup-age gauge.** Telemetry exposes `maint_backup_age_hours{verified=true|false}` (now − last successful verified backup); a separate watchdog rule fires `sec.alert.v1{kind=backup_age_alert, severity=error}` if the gauge exceeds `cfg.maint_backup_age_alert_h` (default 30h). Catches the silent-failure mode where the agent is alive but every dump is failing verify.
- [x] **Safety floor.** TTL prunes are gated by `cfg.maint_backup_dry_run` (default `false` in prod, **`true` in mock profile**) — first run on a fresh dev stack must not delete data the operator hasn't seen yet. `dry_run=true` still emits the same events with `dry_run: true, would_delete_count: N` so test assertions stay symmetric.
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

- [x] **Topic allow-list (binding).** The supervisor does **not** auto-subscribe to every discovered `<topic>.dlq`. The set is the intersection of `swarmctl topics` and `cfg.maint_dlq_replay_topics_allow` (a config list, default = `{predict.request, predict.vote, predict.final, scrape.classified, match.normalized, drift.v1, freshness.v1, cache.v1}`). **Sec/PII topics are excluded by default** — `sec.quarantine.v1.dlq`, `qa.request.v1.dlq`, and `sec.alert.v1.dlq` are never auto-replayed (replaying a quarantined raw payload would re-leak it through the wire). Their DLQs are still drained for telemetry (depth gauge), but operator-only replay through `ops.dlq-replay --topic sec.quarantine.v1.dlq --id <id> --confirm-pii --confirm-destructive=<token>` is the sole path. **Allow-list change mid-replay (binding).** The allow-list snapshot is taken at *tick start*; in-flight replays for a topic that has just been removed from the allow-list complete normally for entries already pulled this tick (avoids partial-batch poisoning), but no new entries from that topic are pulled in subsequent ticks until the topic is re-added. A `maint.event.v1{kind=dlq_topic_disabled_drained, target=<topic>, in_flight_count}` event records the transition. Conversely, a topic newly added to the allow-list is included in the **next** tick's round-robin (one-tick latency, deterministic — test-anchored).
- [x] **Read loop.** Subscribes to the allow-listed `<topic>.dlq` streams (re-evaluated on every heartbeat — new topics are picked up live, but only if they pass the allow-list). Per-topic concurrency bounded by `cfg.maint_dlq_concurrency` (default 4). The read loop is **async-cooperative**: a per-tick budget of `cfg.maint_dlq_max_replays_per_tick` (default 50) bounds the work done before yielding back to the heartbeat — guarantees the agent never misses its `swarm_heartbeat_sec` deadline regardless of backlog depth.
- [x] **Topic fairness (binding).** Within a single tick, the per-tick budget is split **round-robin across allow-listed topics with non-empty DLQs** — never FIFO over the union stream — so a single high-volume DLQ cannot starve smaller ones. The order is `sorted(active_topics)` for determinism (test-anchored). Per-topic share is `max(1, budget // len(active_topics))`; remainder distributed to topics in the same sorted order. Proof test: feed 1000 entries to `predict.vote.dlq` and 5 to `freshness.v1.dlq`, assert the small DLQ drains within `ceil(5 / per_tick_share)` ticks (no starvation).
- [x] **Poison-pattern detection.** When `≥ cfg.maint_dlq_consumer_broken_threshold` (default 5) **distinct** entries on the same topic escalate to `dlq_escalated` within `cfg.maint_dlq_consumer_broken_window_s` (default 600s), emit `sec.alert.v1{kind=consumer_likely_broken, severity=error, subject=<topic>}` (debounced per-topic) and **freeze replays** for that topic until operator unblock via `ops.dlq-resume --topic <t>`. Distinguishes "one bad payload" (1 escalation, replay rest) from "consumer is structurally broken" (5 different payloads all fail). Prevents the supervisor from being a load amplifier on a downed consumer.
- [x] **Replay policy** (per entry, per topic). `dlq_replay_count` is a **payload-level** field (NOT an envelope header — Envelope is sealed to the Phase 3 fields per §0). The supervisor wraps the replayed message in `{__dlq_meta: {dlq_replay_count, dlq_first_failed_at, dlq_topic_origin}, ...original_payload}` ONLY for topics whose payload schema explicitly opts in via `additionalProperties: {__dlq_meta: ...}`. For schemas that are sealed (`additionalProperties: false`), the metadata rides as **bus-level Redis Stream entry headers** read by the supervisor on its next visit (out-of-band of the envelope/payload — preserves the schema contract).
  - First DLQ visit → wait `cfg.maint_dlq_replay_backoff_s` (default 60s), republish to the original topic with the same `request_id` (in payload, per §0) + `dlq_replay_count=1` (per the rule above).
  - Second DLQ visit → wait `cfg.maint_dlq_replay_backoff_s × cfg.maint_dlq_backoff_factor` (default 60s × 4 = 240s), republish with `dlq_replay_count=2`.
  - Third DLQ visit → escalate: emit `sec.alert.v1{kind=dlq_escalated, severity=error, subject=<topic>}` + `maint.event.v1{kind=dlq_escalated, target=<topic>, dlq_entry_id, original_envelope}`. Stop replaying. Operator decides via `ops.dlq-replay --topic <t> --id <id>` (forced replay, or `--drop` to acknowledge and remove).
- [x] **Per-topic rate limit.** No more than `cfg.maint_dlq_replay_rps` (default 10) replays per topic per second — keeps a poisoned message from being thrashed against a still-broken consumer. Token-bucket per topic; bucket state is part of the bounded-state cap below.
- [x] **Backlog-pressure damping.** When `<topic>.dlq` depth exceeds `cfg.maint_dlq_backlog_alert` (default 1000), the agent emits `sec.alert.v1{kind=dlq_backlog_high, severity=warn, subject=<topic>}` (debounced) and **drops the per-topic replay rate to `replay_rps / 4`** until depth halves (positive feedback loop avoidance — a broken consumer should not be flooded harder).
- [x] **Idempotency.** Replays carry the original `request_id` so the consumer's existing idempotency guard (Phase 6 ledger, Phase 7 dedup, Phase 5 consensus single-publication) collapses dupes naturally. Boundary test: replaying an already-accepted `predict.vote` does not produce a second `predict.final`.
- [x] **Audit.** Every replay emits `maint.event.v1{kind=dlq_replayed, target=<topic>, dlq_entry_id, replay_count}`.
- [x] **Bounded state.** In-memory map of `(topic, dlq_entry_id) → (last_replay_at, replay_count)` capped at `cfg.maint_dlq_state_max` (default 100 000) with insertion-order LRU (mirrors the Phase 6 drift bounded-state pattern). Eviction is silent — escalation already covered the long-lived poison cases. **Eviction guard:** if the cap is hit AND no entry is older than `cfg.maint_dlq_replay_backoff_s × cfg.maint_dlq_backoff_factor × 3` (i.e. the cap is filling faster than the backoff window evicts), emit `sec.alert.v1{kind=dlq_state_pressure, severity=warn}` — the cap is undersized for current traffic.

### 8.6 Internal schema-drift sentinel (`maint.schema.v1`)

> **Re-scoped from the original §8.1.** Scraper-selector healing moved to Phase 17 patcher (`extractor`/`schema` scopes). What stays here: detect drift between (a) JSON Schemas in `ai/swarm/sdk/schemas/` and live payloads on the bus, (b) Postgres column sets vs the migration-derived expected set, (c) `payloads.py` dataclass shape vs the matching JSON Schema. Phase 8 detects + reports; humans (or Phase 17 patcher under `migration` scope) fix.

- [x] **Detector A — payload vs schema.** Tap `telemetry.v1`'s sample stream (Phase 4.6 already mirrors a configurable %); for each sampled envelope, run `swarm.sdk.schemas.validate(topic, payload)`. On mismatch → `maint.event.v1{kind=schema_drift_detected, target=<topic>, errors[], sample_envelope_id}` (debounced per `(topic, error_signature)` for `cfg.maint_schema_debounce_s`, default 3600). Sample rate is `cfg.maint_schema_sample_rate` (default 0.01) — full validation is not free; trades coverage for CPU.
- [x] **Detector B — Postgres column drift.** Once per `cfg.maint_schema_pg_check_interval_s` (default 1h), run `SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public'`, compare to the expected set derived from `migrations/*.sql` parsing. Drift → same `kind=schema_drift_detected, target=<table>`. The migration parser uses `sqlglot` (already a candidate dep for Phase 17 patcher) when available, falling back to a tolerant regex parser that handles `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN`, and inline `CHECK` constraints. **False-positive guard:** the parser tracks `unknown_constructs` (e.g. `CREATE FUNCTION`, partial-index `WHERE`); when a table's expected column set was assembled with any unknown_constructs in scope, a drift event for that table is downgraded to `severity=info` (not `warn`) and prefixed `parser_uncertain:` so an operator can distinguish parser failure from real drift.
- [x] **Detector C — dataclass vs schema.** AST scan at startup asserts every `@dataclass` in `payloads.py` has a matching JSON Schema with the same field set + types. **Scope of failure:** drift fails the *Phase 8 schema-sentinel agent* startup only (loud `SystemExit(1)` from the agent module's `__main__`); other agents in the registry are not killed. The Supervisor emits `sec.alert.v1{kind=schema_drift_detected, severity=critical}` for the missing agent. This contains the blast radius — code/schema drift is a release-time bug for one tracked surface, not a swarm-wide outage.
- [ ] **Out of scope (binding).**
  - **Auto-derive selectors / extractors** — Phase 17 patcher only.
  - **Auto-apply migrations** — humans only. The sentinel emits the event; nothing in v1 runs `psql -f migrations/NNN_*.sql` unattended. (`cfg.maint_schema_auto_apply_enabled` exists in config for forward compatibility; defaults to `false` and is checked at startup with a warning if `true`.)

### 8.7 Pattern false-positive feedback loop (`maint.sec.v1` slice)

> Promotes the §7.x deferred FP loop. Operator clears a quarantined sample → the rule that triggered it adds to a per-source allowlist (autolearn-on) **or** queues for explicit operator approval (autolearn-off, default).

- [x] Subscribes to `maint.event.v1{kind=quarantine_clear, target=<quarantine_id>}` (Phase 7 publisher hook stub).
- [x] Resolves `quarantine_id → (source, rule_id, hit_substring)` from `quarantine_samples`. Computes `hit_fingerprint = sha256(NFC(hit_substring))[:16]` (deterministic, language-stable, never stores the raw substring in the live allowlist row — PII contains-checks are operator-only via `ops.allowlist-show`).
- [x] **Two-mode insertion.** On-disk `state` is encoded as `CHAR(1) IN ('p','a','e')` (per migration 010); the `_ack_routing.py`-style `_state_codec.py` maps it to bus-event strings `'pending'|'active'|'expired'` (single source of truth, boundary-tested). Bus events ALWAYS use the long form; SQL ALWAYS uses the short form.
  - `cfg.sec_input_pattern_autolearn_enabled = true`: insert with `state='a', expires_at = now() + cfg.maint_sec_allowlist_ttl_days, added_by_request_id`. Emits `kind=pattern_allowlist_added`.
  - `cfg.sec_input_pattern_autolearn_enabled = false` (default): insert with `state='p', expires_at = NULL, proposed_at = now()`. Emits `kind=pattern_allowlist_pending` (informational; **does not** count as `added`). Operator promotes via `ops.allowlist-approve --id <row_id> --ttl-days N` → row flips to `state='a'` and a `kind=pattern_allowlist_added` event fires. Pending rows older than `cfg.maint_sec_allowlist_pending_ttl_days` (default 30) are pruned by §8.3.
- [ ] `sec.input.v1` reads only `state='a' AND (expires_at IS NULL OR expires_at > now())` rows on each pattern hit — if `(source, rule_id, hit_fingerprint)` matches, the hit is suppressed (counted in `sec_input_allowlist_hits_total` for visibility, never silently lost). The cache is refreshed via mtime-equivalent on a `pattern_allowlist_version` row in a metadata table (poll interval `cfg.sec_input_allowlist_reload_s`, default 60s) — same pattern as §7.4 sec.config fan-out (deliberately mtime-style, not bus fan-out). **Cache-reload race:** the version-row read uses `REPEATABLE READ` snapshot isolation against the same connection that subsequently reads `pattern_allowlist`, so promote-while-evaluating either sees the old version-row + old cache (next poll tick reloads) OR the new version-row + new cache (atomic refresh) — never a half-applied state. Proof test in §8.9 forces the race with `pg_advisory_lock` interleaving.
- [x] **SQL-injection guard.** All inserts/queries use parameterized statements (`psycopg.sql.Composed`, never f-string concat). Boundary test: AST scan of `ai/swarm/agents/maint/sec.py` rejects `cursor.execute(f"...")` and `"%s" %` patterns inside SQL builders. The hit_substring is **never** placed in a SQL `LIKE` or `=` clause — only the fingerprint hash is.
- [x] Emits `maint.event.v1{kind=pattern_allowlist_added|pattern_allowlist_pending|pattern_allowlist_expired}` accordingly. Expiry sweep runs at the §8.3 cron tick.

### 8.8 Sec-denylist sweeper (`maint.sec.v1` slice)

> Promotes the §7.3 deferred "halve TTL of oldest decile" sweeper. Activates only under cap-mode pressure.

- [x] Subscribes to `sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}` (Phase 7 §7.3 publisher).
- [x] On consume, runs new Lua script `infra/redis/lua/sec_denylist_decimate.lua` (VERSION + SHA256 header + `make verify.lua` CI gate + embedded copy at `server/internal/sec/embedded/` + `embedded_parity_test.go`, exactly like the existing two scripts):
  - Atomically (single Lua call — no client-side round-trips, no race with concurrent denylist mutations) identifies the oldest decile of `sec:denylist:_zset` members by score (= `expires_at_ms`).
  - Halves their remaining TTL: `new_score = now_ms + (old_score - now_ms) / 2`; `PEXPIREAT sec:denylist:<subject> new_score` AND `ZADD sec:denylist:_zset new_score subject` (single transaction — zset and key TTL never disagree).
  - **Cap-flag fast-clear.** If post-decimation `ZCARD < cfg.sec_denylist_cap × cfg.sec_denylist_cap_exit_ratio` (computed in Lua from the passed-in cap arg), executes `DEL sec:denylist:capped` and returns `cap_cleared=true`. Without this, the gateway's subnet-mode would persist for up to the 300s flag TTL even after the actual pressure drops — fast-clear is the user-facing reliability win.
  - **Concurrency safety.** A second decimate call entering while the first is mid-script is impossible (Redis Lua is atomic). Two *separate* alert consumers calling the script back-to-back are de-duplicated by the §8.8 hysteresis below; if hysteresis is bypassed (test path), the second call is still safe — the worst case is two halvings of the same TTL window, never an inconsistent zset.
  - **Mandatory args.** `now_ms` (ARGV[1]) and `cap` (ARGV[2]) are required; absence/zero returns `"error"` (mirrors the §7.3 v1.1.0 lesson — silent defaults broke lazy eviction).
  - Returns `{evicted_count, decile_size, new_zcard, cap_cleared: bool}` for audit.
- [x] Emits `maint.event.v1{kind=denylist_decimate, target=<source>, evicted_count, decile_size, new_zcard, cap_cleared}` and a separate `kind=denylist_cap_cleared` only when `cap_cleared=true` (operator-facing signal that subnet-mode is over).
- [x] **Decile-size boundary.** Decile is computed `decile_size = max(1, ZCARD // 10)`. When `ZCARD < 10`, decile_size = 1 (still meaningful). When `ZCARD == 0` the script is a no-op returning `evicted_count=0, decile_size=0, cap_cleared=false` (alert was spurious; agent records and debounces). Proof test covers both edges.
- [x] **Hysteresis.** No more than one decimate per `cfg.maint_sec_decimate_min_interval_s` (default 300s) **globally** (single zset, single global pressure signal — per-subject hysteresis is meaningless for a global cap). Tracked in agent state, not Redis (state survives within a single agent process; `replicas: 1` enforced). Hysteresis state survives leader handover via the §8.10 `Leader` Protocol's `last_action_at` slot in the K8s Lease annotation (Phase 14 only); compose-mode handover is N/A (single replica per service).

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
- [x] **Re-entrancy lock.** Two parallel `ops.denylist-clear --target X.X.X.X` shells: exactly one wins the per-`(host,kind,target)` `flock`; the other exits with a `lock_held` error code; no double publish on the bus. _Closed: `test_opsctl_lock.py::test_lock_contended_when_held_by_another_fd` proves a second `reentrancy_lock` acquisition with the file held by an external fd returns `acquired=False` with an explanatory note; `xops/opsctl/_runner.py::run_publish` then exits `LOCK_CONTENDED_EXIT` (= GENERIC_FAILURE) and writes an audit row before returning — no `publish_event` call is reached on the contention path._
- [x] **Spool ordering + corruption.** Bus-down spool: 10 envelopes appended in order, then bus restored — flush re-publishes in append order (asserted via `request_id` sequence). Corrupt one spool file mid-byte; flush skips it loud (`spool_entry_corrupted` alert) and continues with the rest. _Closed: `xops/opsctl/subcommands/spool_flush.py` walks `*.envelope.json` in deterministic filename order (creation-time prefix in the spool naming scheme); successful republishes unlink the entry; `BUS_DOWN_SPOOLED` re-publishes leave the new spool file in place and break (idempotent retry on next flush); malformed entries are renamed to `<name>.malformed` (loud-skip equivalent — operator-visible filename + audit row). Dir-level `fcntl.flock` on the spool directory (returns exit 8 `SPOOL_FLUSH_ALREADY_RUNNING` on contention) prevents two concurrent flushes. Tests: `test_opsctl_spool_flush.py` (empty-OK, full cycle spool→flush→ack→file removed, malformed entry quarantined to `.malformed`)._
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
- [~] **Destructive-command confirmation.** Run `ops.scale --target consensus.v1 --replicas 0` without `--confirm-destructive` → exits non-zero with `confirmation_required` and prints the expected token; re-run with the printed token publishes exactly once. Same shape for `ops.restore`, `ops.dlq-replay --drop`, `ops.maint-pause` against a critical agent. _Partial: token mechanism + gate are landed (`xops/opsctl/_token.py::derive_confirm_token` returns `sha256(f"{cmd}|{target}|{k=v,...}")[:8]`; `xops/opsctl/_runner.py::run_publish` enforces it on every `ALWAYS_DESTRUCTIVE` subcommand and prints the expected token to stderr on mismatch; dry-run is the safe-preview path and bypasses the gate). Now exercised on `quarantine-erase`, plus `scale` (via `replicas_zero` + `reduction_over_50pct` flags) and `dlq-replay` (via `drop` flag + REFUSE on `topic_sec` without `confirm_pii`) — `test_opsctl_phase8_batch_a1.py` proves all four CONFIRM/REFUSE branches end-to-end via dry-run. `test_opsctl_token.py` + `test_opsctl_token_gate.py` cover token determinism + audit-row gating. Remaining unticked because `ops.restore` / `ops.maint-pause` against critical agents land with §8.3 (restore agent) + §8.10 (full lease + critical-agent integration test) respectively._
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
- [x] **Dead-mans-switch.** A dedicated `maint.heartbeat.v1` (no — reuse `telemetry.v1{kind=maint_silence_check}`) periodic check: if `now − last_observed_maint_event_v1 > cfg.maint_silence_alert_h` (default 24h) AND the swarm has been up `> 1h` (boot-warm guard), emit `sec.alert.v1{kind=maint_silence_alert, severity=critical}` (bypass debounce). Catches the worst silent-failure mode: the maint plane is dead so it can't tell you it's dead. The check itself runs in **`telemetry.v1`** (already always-on; §8.x can't be both judge and patient). **Boundary update (binding):** telemetry was previously read-only counters; this is the **first** publish path from `telemetry.v1` onto `sec.alert.v1`. The §7.4 producer-set allow-list for `sec.alert.v1` widens by exactly one entry (`telemetry.v1`, kinds restricted to `{maint_silence_alert}` only — boundary test pins the kind allow-list per producer, not just the producer set).
- [x] **Self-isolation under cascading failure.** If a Phase 8 agent's own DLQ exceeds `cfg.maint_self_dlq_alert` (default 100 entries), the agent flips its bus subscriptions to read-only (acks only, no new actions), emits `sec.alert.v1{kind=maint_self_isolated, severity=critical}`, and waits for operator unblock via `ops.maint-resume --agent <id>`. Prevents the maint plane from amplifying outages it cannot keep up with.
- [x] **Operator-driven planned maintenance.** Symmetric `ops.maint-pause --agent <id> [--ttl-s T]` / `ops.maint-resume --agent <id>` — pauses an agent's *publish* path while leaving consume (and therefore ack-emission for in-flight requests) live, so the plane drains gracefully. Pause emits `maint.event.v1{kind=maint_paused, target=<id>, ttl_s, reason}`; expiry or explicit resume emits `kind=maint_resumed, target=<id>`. `ttl_s ≤ cfg.maint_pause_max_ttl_s` (default 7200). Pause is **distinct** from self-isolation (which is involuntary + critical-alerted); planned pause is operator-attributed (`paused_by` in payload) and carries `severity=info` only. Critical agents (`cfg.opsctl_critical_agents`, see §8.1 destructive set) may be paused only with `--confirm-destructive`. Auto-scaler treats a paused target as `manual_scale_pin{replicas=current}` for the pause TTL — no scale calls, no flap on resume.
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

- [x] All maint sub-budgets (`opsctl_spool/`, `opsctl_locks/`, `opsctl_audit.csv`, `agent_spool/`, `summarizer_ledger.json`, `pod_instance_id` files, `dr_drills.csv`) are individually capped today. Add a **cumulative** cap: at every §8.x agent's heartbeat, the `MaintStorageWarden` (lives in `swarm.sdk.maint_storage`) sums `du -sb data/maint/` and checks against `cfg.maint_storage_total_max_mb` (default 512 MB). Crossing 80% of the cap → `sec.alert.v1{kind=maint_storage_pressure, severity=warn}` (debounced 1h). Crossing 100% → emit `severity=error`, refuse all new spool writes (publish path errors loud with exit code 6 `maint_storage_full`), and flip every §8.x agent into observer mode until usage drops below 70% (single hysteresis band, prevents thrash).
- [x] **Per-subdir budget audit.** Cap is informational only when the sum of per-subdir caps is ≤ the global; if the operator widens a single per-subdir cap beyond the global headroom, boot validation refuses to start (`fail_safe_subdir_caps_exceed_global`). Single source of truth, single failure mode.
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

- [x] **Real bug.** §8.7's allowlist promote-while-eval race uses `pg_advisory_lock(<key>)`. PG advisory locks share a single global key namespace per database (`bigint` keyspace). Phase 9 trainer reactor will use them, the §8.14.1 audit-log retention pruner will use them (DETACH PARTITION + DROP), and the §8.13.4 forward-migrate-then-verify will use them. Two callers on the same key collide: one blocks, the other proceeds — silent deadlock or double-execution depending on lock variant (shared/exclusive).
- [x] **Registry (binding).** Single source of truth at `xops/maint/advisory_lock_keys.py`:
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
- [x] **Lock-hold-time guard.** `BoundLock` records the wall-clock acquire time; on `__exit__`, if held longer than `cfg.maint_advisory_lock_max_hold_ms` (default 5000ms — generous), emits `sec.alert.v1{kind=maint_advisory_lock_held_long, severity=warn, lock_name, hold_ms}` (debounced per lock_name). Catches accidental long transactions inside the lock.
- [x] **Proof tests.** (a) `ensure_unique` against a key registry with a duplicate → raises. (b) AST scan against a planted `cursor.execute("...pg_advisory_lock(...)")` → fails. (c) Held-too-long: take `BoundLock` and `time.sleep(6)` → assert one alert.

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

### 8.16 Seventh-pass deep-revision additions (registry-vs-config drift, ack-in-vacuum on spool flush, prune execution-order doctrine, ack metric cardinality, S3 multipart-upload-id TTL, Object-Lock boot probe, DLQ deny-prefix forward-compat, per-model VRAM footprint hints, maint-vs-sec topic crossover doctrine, fingerprint authentication strength, sec-plane backpressure symmetry, qa↔predict DLQ correlation, swarm.demo live-Redis profile, key-id derivation invariant, Phase-5 trainer prerequisite gate)

> Closing real gaps the prior six passes still missed. Found by walking the live registry / runtime contracts that prior passes referenced abstractly: §8.2's `cfg.maint_scaler_max_replicas` dict assumes the registered-agent set never changes between releases; §8.1's bus-down spool flush has no contract for acks that land after the flushing process has exited; §8.3 enumerates prune jobs but never pins their execution order, so a `quarantine_samples` prune that runs before the dump silently rewrites the dump's apparent state; the §8.9 telemetry watch-set extension to `MAINT_ACK` will produce a metric-cardinality blowup at scale (every kind × consumer × outcome); §8.12's `S3CompatibleTarget` persists a multipart upload id but AWS server-side aborts uploads after 24h by default — a longer agent outage strands the resume; §8.12's Object-Lock retain-until path has no boot-time reachability probe so a credential-loses-`s3:PutObjectRetention`-permission-overnight scenario fails silently per dump; §8.5's `RECURSION_DENY_SET` is enumerated, not prefix-rule-based, so future Phase 9/20 `auth.*.dlq` and `payment.*.dlq` topics inherit no protection; §8.2's VRAM accounting uses a single global `cfg.predictor_max_vram_mb` knob — XGBoost-50MB and Trendyol-LLM-1B-4GB are not the same; nothing pins when an event belongs on `maint.event.v1` vs `sec.alert.v1` (operators get a 50/50 mental-model coin-flip); §8.7's 16-byte `hit_fingerprint` is collision-resistant but not authenticated — a chosen-prefix attack lets an attacker craft a substring that collides with an allowlisted fingerprint and bypass the rule; §8.8's sec-decimater consumes `sec.alert.v1` with no shed-tier guard symmetric to §8.11's `maint.event.v1` watchdog; §8.5's qa.request.v1 PII-deny correctly blocks DLQ replay but leaves operators with no `qa_correlation_id` thread to follow into the (replayable) `predict.request.v1.dlq`; §8.9's `make swarm.demo` extension asserts `< opsctl_ack_timeout_ms` against an InMemoryBus where latency is nanoseconds — the budget passes trivially; §8.14.4 ships per-operator HMAC keys but never pins the `key_id` derivation, so two operators reviewing each other's PRs cannot mechanically validate the `infra/maint/opsctl_operators.json` mapping; §8.13.1 model-lineage doctrine assumes the Phase 5/9 trainer writes a sidecar that today's Phase 5 trainer does NOT write — an unflagged hard prerequisite.

#### 8.16.1 Registry-vs-config drift (scaler `max_replicas` dict)

- [x] **Real gap.** §8.2 says the scaler "refuses to start if any registered agent is missing an entry" in `cfg.maint_scaler_max_replicas`. Code lands in PRs before cfg keys are widened (cfg edits frequently lag agent registration in the same PR). A forgotten cfg edit blocks the entire scaler from starting — a deployment-ergonomics footgun, not a safety win. The "totality" doctrine (mirrors §7.6 endpoint-cost totality) is correct in spirit but wrong in failure mode for a registry that mutates per release.
- [x] **Doctrine (binding).** Replace refuse-to-start with **default-policy fallback**: agents with no explicit entry in `cfg.maint_scaler_max_replicas` fall back to `cfg.maint_scaler_default_max_replicas` (default `2` — small, reflects the conservative-by-default posture; never `1` because that's indistinguishable from "definitely don't scale me"). Each fallback emits ONE-shot `sec.alert.v1{kind=maint_scaler_unconfigured_agent, severity=warn, subject=<agent>}` per process lifetime and a `maint.event.v1{kind=maint_scaler_default_applied, target=<agent>, applied=N}` audit row — operators see exactly which agents are running on the default and can widen the cfg in the next PR. The `cfg.maint_scaler_global_max_replicas` hard cap (default 64) STILL applies — defaults can't bypass the global ceiling.
- [x] **Forward-compat for retired agents.** A cfg entry pointing at an agent that is no longer registered (operator forgot to clean cfg after agent removal) emits `sec.alert.v1{kind=maint_scaler_orphan_cfg, severity=info}` once at boot and is otherwise ignored — never a hard failure. Symmetric leniency in both directions.
- [x] **Boundary-test loosening.** The §8.9 boundary test that previously asserted "every registered agent has an explicit cfg entry" downgrades to a *lint* test (warn-only, doesn't fail CI) named `test_maint_scaler_max_replicas_explicit_coverage` — operators are nudged toward explicit declarations without blocking releases.
- [x] **Proof tests.** (a) Register a brand-new agent class in a unit harness without widening `cfg.maint_scaler_max_replicas`; assert scaler starts, agent is observed, default applied, both alerts emit exactly once. (b) Wire a cfg entry for an unregistered agent name; assert scaler starts, info alert emits, no crash.

#### 8.16.2 Ack-in-vacuum on bus-down spool flush

- [ ] **Real gap.** §8.1 ops console waits for `expected_ack_set` ≤ `cfg.opsctl_ack_timeout_ms` then exits. §8.1 also defines a bus-down spool: failed publishes spool to disk; `make ops.spool-flush` reattempts. The **flushing process** is a separate invocation — it publishes envelopes the original operator process abandoned. **Acks for those envelopes land on the bus, but no process is waiting** (the spool-flush invocation does not block on acks per envelope; that would serialize replay). Acks land in the maint-plane stream and… do what? Get GC'd? Inflate metric counters? Today's design is silent, which is the worst answer.
- [ ] **Doctrine (binding).** Two-tier wait policy:
  - **Foreground (`make ops.<cmd>` direct invocation):** unchanged — wait for `expected_ack_set` synchronously; exit codes 0/2/3 per §8.1.
  - **Spool-flush (`make ops.spool-flush`):** publish each spooled envelope, **do NOT block per-envelope on acks**, but record `expected_ack_set` + `flush_invocation_id` in `data/maint/opsctl_audit.csv` with `ack_received_count=PENDING`. A separate background reconciler running inside `maint.dlq.v1` (mode: ack-only consumer of `maint.ack.v1`) walks unresolved `flush_invocation_id` rows and back-fills `ack_received_count` as acks land, emitting `kind=spool_flush_acks_reconciled, flush_invocation_id, expected, received, missing[]` once the audit row is closed (all expected acks landed OR `cfg.opsctl_spool_ack_max_wait_h` (default 24h) elapsed). Missing acks past the deadline emit `sec.alert.v1{kind=spool_flush_acks_incomplete, severity=warn, missing_count}` (debounced per `flush_invocation_id`).
  - **Idempotency invariant.** Reconciler keys on `(flush_invocation_id, request_id, accepted_by)` — re-running the reconciler is a no-op for already-reconciled rows.
- [ ] **Why the DLQ supervisor.** It is the maint-plane agent already wired to `maint.ack.v1` for the §8.13.5 ack-trace test path AND already runs at `replicas:1` (per §8.10) so the reconciler runs exactly once. No new agent introduced; one new responsibility.
- [ ] **Proof tests.** (a) Publish 10 envelopes via spool-flush against an InMemoryBus with synthetic delay; restart the spool-flush process between publish and ack landing; assert reconciler back-fills the audit rows correctly. (b) Force one consumer to never ack; assert the missing-ack alert fires after `opsctl_spool_ack_max_wait_h`. (c) Re-run the reconciler twice in one tick; assert no duplicate `spool_flush_acks_reconciled` events.

#### 8.16.3 Backup TTL prune execution-order doctrine

- [ ] **Real gap.** §8.3 lists 6 prune targets (`quarantine_samples`, `schema_snapshots`, `dlq_entries`, `pattern_allowlist`, `opsctl_audit`, `maint_audit_log`) running "at the same cron tick after the dump". Order is unspecified. Two real bugs hide:
  - If `quarantine_samples` is pruned **before** the dump fires (operator misconfigures `cfg.maint_backup_cron` and the `make ops.backup-now` path runs prune-first), the dump's `quarantine_meta.csv` sanitized projection (§8.3) reflects post-prune state — a different reality than what was alive at backup time.
  - PG foreign keys: `predictor_outcomes.calibration_id` references `predictor_calibration.id` (Phase 5 migration `005_predictor.sql`); if Phase 9 lands a `dlq_entries.request_id` FK to `predict_calibration.prediction_id`, pruning calibration rows before dlq rows raises `ForeignKeyViolation` and aborts the entire prune transaction.
- [ ] **Doctrine (binding).** Pruning is a **single ordered sequence**, declared in `xops/maint/prune_order.py`:
  ```python
  PRUNE_ORDER: list[str] = [
      # Tier 1: leaf tables (no other table FKs into them)
      "opsctl_audit",
      "schema_snapshots",
      "pattern_allowlist",  # autolearn=false rows + expired
      # Tier 2: tables referenced only by Tier 1
      "dlq_entries",
      "quarantine_samples",  # raw_bytes nulled, audit row preserved
      # Tier 3: audit (must be last; everything else's prune may emit audit rows)
      "maint_audit_log",
  ]
  ```
  Boot validation runs `pg_dump --schema-only --table=...` once at agent start, parses FK declarations into a DAG, and asserts `PRUNE_ORDER` is a topological sort of "tables to prune" (FK target → source). Drift = `fail_safe_prune_order_invalid` + critical alert + refuse-to-start.
- [ ] **Backup-vs-prune ordering invariant.** The `maint.backup.v1` agent's tick is a **strict state machine**: `dump → restore-verify → prune`. Each phase emits its own `maint.event.v1` (`backup_started`, `backup_completed{verified:bool}`, `prune_started`, `prune_completed`) and the agent refuses to enter the next phase if the prior one didn't emit success. `make ops.backup-now --skip-prune` forces the legitimate operator override (e.g. emergency dump only); `--prune-only` is **forbidden** (no separate-prune-without-dump path — eliminates the misconfig that drops live data ahead of a dump).
- [ ] **Per-table prune metrics.** Telemetry exposes `maint_backup_prune_seconds{table,outcome}` histogram + `maint_backup_prune_rows_total{table}` counter per phase tick — operators see if any single table dominates the prune budget.
- [ ] **Proof tests.** (a) Boot validation: synthesize a schema with FK violating `PRUNE_ORDER` (e.g. `opsctl_audit` referencing `maint_audit_log`); assert refuse with `fail_safe_prune_order_invalid`. (b) State machine: simulate dump failure; assert prune phase never enters; emit chain shows `backup_started` then `backup_completed{verified:false}` then `prune_skipped, reason=dump_failed`. (c) `--prune-only` rejected with exit code 10 (NEW exit code: `prune_only_forbidden`).

#### 8.16.4 `maint.ack.v1` metric cardinality cap

- [ ] **Real gap.** §8.9 DoD says "Telemetry watch set extended to include `MAINT_ACK` (counters surface per-consumer ack latency + accepted/rejected ratios)". Naive labelling = `ack_latency_seconds{kind, accepted_by, accepted}` → `(36 known kinds) × (8 maint agents + ops_console) × (true/false) ≈ 600 series` at v1 and grows linearly with every new kind (§8.13/§8.14/§8.15 already added 30+ kinds). Prometheus best-practice ceiling for one metric family is ~10k series; we hit 1k just on Phase 8 launch and the ack metric is per-pod (× replicas). Real risk of a memory-bound agent metric explosion.
- [ ] **Doctrine (binding).**
  - **Counters:** `maint_ack_total{accepted_by, accepted}` only — `kind` label DROPPED. Operators see "consumer X accepted/rejected acks at rate Y", which is the operationally relevant signal. Kind-level breakdowns live in the audit log (§8.14.1) for postmortem.
  - **Latency:** `maint_ack_latency_seconds{accepted_by}` histogram (10 buckets, default `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]`) — operators see distribution per consumer.
  - **Per-kind ack rates:** exposed only via the `/metrics-debug` endpoint (Phase 9), gated on `cfg.telemetry_debug_enabled` (default `false` in prod, `true` in dev). When enabled, `maint_ack_total_debug{kind, accepted_by, accepted}` exists in parallel — operators opt-in for short windows during incident triage.
- [ ] **Cardinality boot guard.** Telemetry computes worst-case series count at boot from `KNOWN_MAINT_EVENT_KINDS × len(_ack_routing values()) × 2` and refuses to enable `telemetry_debug_enabled=true` if the projection exceeds `cfg.telemetry_debug_max_series` (default 5000) — fail-safe against accidental flag flip in prod with a wide kind set.
- [ ] **Proof tests.** (a) Enumerate metric series in a unit harness with all 36+ kinds registered; assert default series count ≤ 30 (8 consumers × 2 accepted + 8 consumers × 10 buckets ≈ 96 — under any sane Prometheus budget). (b) Enable debug flag; assert refusal when projected series > 5000.

#### 8.16.5 S3 multipart-upload-id TTL + AWS abort race

- [ ] **Real gap.** §8.12 persists `(upload_id, part_etags, byte_offsets)` to `.offsite_state.json` for resume. AWS S3 default lifecycle aborts incomplete multipart uploads at `bucket.LifecycleConfiguration.AbortIncompleteMultipartUpload.DaysAfterInitiation` (operators commonly set 7d, sometimes 1d for cost control). MinIO has similar behavior. Compatible APIs (R2, B2) vary. If the agent crashes/sleeps for longer than the bucket's abort window, the persisted `upload_id` references a server-side-aborted upload — `UploadPart` calls return `NoSuchUpload`, and today's code surfaces that as a fatal error per §8.12 retry budget.
- [ ] **Doctrine (binding).** Resume-flow protocol: (1) read `.offsite_state.json`; (2) probe upload-id liveness via `ListParts` against the bucket; (3) if `NoSuchUpload` → emit `maint.event.v1{kind=backup_offsite_upload_id_expired, dump_date, original_upload_id, age_h}` audit row, delete `.offsite_state.json`, and **restart the upload from scratch** (pre-existing parts on the server are no longer reachable; the bucket's lifecycle has reclaimed them). Restart-from-scratch is bounded by the §8.12 hard timeout `cfg.maint_backup_offsite_upload_timeout_h` (default 6h) — if the dump cannot be re-uploaded inside the timeout, the existing `backup_offsite_failed` path fires.
- [ ] **Probe staleness check.** At every resume attempt, the agent compares `now - .offsite_state.json.mtime` against `cfg.maint_backup_offsite_state_max_age_h` (default 18h — under 24h to leave headroom against AWS's 24h-default abort policy). Older state is treated as expired before even probing (saves an API call); same restart-from-scratch path.
- [ ] **Bucket lifecycle assertion at boot.** `S3CompatibleTarget` calls `GetBucketLifecycleConfiguration` once at agent boot; if the configured `AbortIncompleteMultipartUpload.DaysAfterInitiation < cfg.maint_backup_offsite_lifecycle_min_days` (default `2` — gives the agent a one-day recovery window even on aggressive bucket policies), emits `sec.alert.v1{kind=backup_offsite_lifecycle_too_aggressive, severity=warn, configured_days, required_min_days}` (debounced daily). Doesn't refuse to start (operator may have legitimate cost reasons), but the alert is loud.
- [ ] **Proof tests.** (a) Stub `ListParts` to return `NoSuchUpload`; assert resume restarts cleanly with the audit event + state file deletion. (b) State file `mtime > state_max_age_h`; assert restart-from-scratch without probing. (c) Bucket lifecycle stubbed to `DaysAfterInitiation=1`; assert warn alert fires.

#### 8.16.6 Object-Lock & WORM boot-time probe

- [ ] **Real gap.** §8.12 sets `x-amz-object-lock-mode=COMPLIANCE` per upload, with the boundary test asserting "attempted overwrite + delete during retention both 403". The boundary test runs in CI against MinIO (mock); production runs against an unverified bucket. Nothing in the §8.12 boot path probes the real production bucket — credentials lacking `s3:PutObjectRetention` (a common IAM-policy oversight when adopting Object-Lock after the bucket already exists), or buckets without Object-Lock enabled (must be set at bucket-creation time on AWS, cannot be added later), produce silent failures: every upload writes successfully but **without** retention metadata. The `kind=backup_offsite_uploaded` audit row would say `object_lock_until=<date>` based on the agent's intention, not the bucket's actual response.
- [ ] **Doctrine (binding).** Boot-time probe sequence (`S3CompatibleTarget.preflight()`):
  1. `GetBucketObjectLockConfiguration` — refuses with `fail_safe_offsite_object_lock_disabled` if `ObjectLockEnabled != "Enabled"` AND `cfg.maint_backup_offsite_object_lock_days > 0`. Mock profile may relax via `cfg.maint_backup_offsite_object_lock_required=false`.
  2. **Probe upload** of a 1KB sentinel object `negelir-preflight-<pod_instance_id>-<utc_iso>.bin` with `x-amz-object-lock-mode=COMPLIANCE` + `x-amz-object-lock-retain-until-date=now+60s` (60-second retention so the sentinel auto-cleans after the probe).
  3. Read-back the retention metadata via `GetObjectRetention`; assert mode + retain-until match. Mismatch → `fail_safe_offsite_retention_not_applied`.
  4. Attempt `DeleteObject` on the sentinel during retention; assert 403/`AccessDenied`. Mismatch (sentinel deleted) → `fail_safe_offsite_lock_not_enforced` (catastrophic — proves WORM is performative on this bucket).
  5. Wait for retention to lapse (60s + slack), GC the sentinel.
- [ ] **Cadence.** Probe runs at agent boot AND once per `cfg.maint_backup_offsite_preflight_interval_h` (default 24h) — credentials and bucket policies drift in production. Failure during recurring probes flips the agent into spool-mode (§8.11 bus circuit-breaker analog: spools dumps locally, stops attempting offsite uploads) until the next successful probe. Critical alert `kind=backup_offsite_preflight_failed` emits with the specific failure reason.
- [ ] **Proof tests.** (a) MinIO bucket without Object-Lock; assert refuse with `fail_safe_offsite_object_lock_disabled`. (b) MinIO bucket with Object-Lock + IAM policy missing `s3:PutObjectRetention`; assert refuse with `fail_safe_offsite_retention_not_applied`. (c) Recurring probe failure: simulate credential rotation that drops the permission mid-day; assert agent flips to spool-mode + critical alert.

#### 8.16.7 DLQ deny-prefix forward-compat

- [ ] **Real gap.** §8.14.5 hardcodes `RECURSION_DENY_SET = {"maint.dlq.v1.dlq", "maint.event.v1.dlq", "maint.ack.v1.dlq", "sec.alert.v1.dlq"}`. Phase 9 will land `auth.login.v1.dlq` / `auth.refresh.v1.dlq` (credentials in payload — never replay). Phase 20 will land `payment.intent.v1.dlq` (PCI-relevant — never replay). Phase 17 patcher lands `patcher.diff.v1.dlq` (proposed code diffs — never replay). Each phase will need to remember to extend the deny set; an oversight is a silent data-leak risk via DLQ replay.
- [ ] **Doctrine (binding).** Replace the enumerated set with a **layered ruleset** at `swarm.agents.maint.dlq.replay_policy.py`:
  ```python
  # Hard-coded deny prefixes (operator-overridable only via the cfg-level
  # exception list below; never via a code edit downstream).
  DENY_PREFIXES: tuple[str, ...] = (
      "maint.",       # control plane self-replay
      "sec.",         # security-sensitive payloads (qa, quarantine, alerts)
      "auth.",        # credentials in payload
      "payment.",     # PCI scope
      "patcher.",     # proposed code diffs / patch bundles
  )
  # Deny suffixes (always applied after prefix check).
  DENY_SUFFIXES: tuple[str, ...] = (".dlq.dlq",)  # double-dlq topology bug
  # Operator-attested exceptions (cfg list; rare, expensive — every entry
  # requires a docs/design/security-exception.md row + sign-off).
  ALLOW_OVERRIDES: tuple[str, ...] = tuple(cfg.maint_dlq_replay_allow_overrides)
  ```
  `is_replayable(topic) = not any(topic.startswith(p) for p in DENY_PREFIXES) and not any(topic.endswith(s) for s in DENY_SUFFIXES) or topic in ALLOW_OVERRIDES`. Boot-time enumerator emits `maint.event.v1{kind=dlq_replay_policy_loaded, deny_prefixes, deny_suffixes, allow_overrides}` so the active policy is auditable.
- [ ] **Override discipline.** Adding a topic to `ALLOW_OVERRIDES` requires (a) an entry in `docs/design/security_exceptions.md` (NEW doc) explaining why, (b) the responsible agent code sign-off, (c) a chaos catalogue stub at Phase 12 that exercises the replay path. CI gate `make verify.dlq-replay-policy` walks `ALLOW_OVERRIDES` against the docs file — orphans on either side fail.
- [ ] **Proof tests.** (a) Synthesize topic `auth.login.v1.dlq` in the swarmctl topics; assert `is_replayable == False`. (b) Add `auth.login.v1.dlq` to `ALLOW_OVERRIDES` without a docs row; assert `make verify.dlq-replay-policy` fails. (c) Double-`.dlq.dlq` (topology accident); assert always denied regardless of override.

#### 8.16.8 Per-model VRAM footprint hints

- [ ] **Real gap.** §8.2 VRAM budget arithmetic uses the single global `cfg.predictor_max_vram_mb` (default 1024). XGBoost / LightGBM models footprint ~50MB; Trendyol-LLM-1B (Phase 10) footprints ~4000MB; the §8.4 source-watcher summarizer (Phase 8) footprints zero (CPU/API). Treating them all as 1024MB is wasteful at the small end (refuses scale-up that would fit) and dangerous at the large end (admits scale-up that OOMs). The §8.2 doctrine "before issuing a scale-up that would push `Σ vram_used + (next-prev) × cfg.predictor_max_vram_mb` over the budget" produces silently wrong projections.
- [ ] **Doctrine (binding).** Each predictor agent declares a per-version VRAM footprint in `models.events.v1{kind=model_registered, agent_id, version, vram_footprint_mb, device_class ∈ {cpu, gpu_inference, gpu_training, npu}}` at registration time (Phase 5 trainer reactor emits when a new weight version lands; categorizer / sec.input emit at boot since they have static models). The §8.2 scaler maintains an in-memory `(agent_id → vram_footprint_mb)` map keyed off the **active version** advertised by the agent's most recent heartbeat. Projection becomes `Σ vram_used + (next-prev) × footprint(agent_id)` — exact math, not amortized.
- [ ] **Fallback policy.** Agents that have not (yet) emitted a `model_registered` event fall back to `cfg.predictor_max_vram_mb` (the legacy global) AND emit `sec.alert.v1{kind=vram_footprint_unknown, severity=info, subject=<agent>}` once per agent per process. Scale-up against an unknown-footprint agent is **refused** (`scale_throttled, reason=vram_footprint_unknown`) when GPU is the active device and `Σ vram_used > cfg.maint_scaler_vram_pessimistic_threshold_pct × budget` (default 0.6 = 60%) — when capacity is plentiful the unknown is admitted on the legacy default; when capacity is tight the unknown is treated as the safety hazard it is.
- [ ] **CPU-class agents.** `device_class=cpu` agents bypass the VRAM check entirely (footprint=0 by definition); their replicas count toward CPU-budget tracking instead. New `cfg.maint_scaler_cpu_budget_pct` (default 0.8 = 80% of detected cores per host) — the scaler refuses CPU-class scale-up that would push aggregate CPU-class replicas × 1 core over the budget. No-op pre-Phase 14 (single-host compose mode); active under K8s.
- [ ] **Proof tests.** (a) Register two predictors with footprints 50MB and 4000MB on a 8000MB budget; assert scaler admits 100 replicas of the small one OR 1 replica of the large one but refuses 2 replicas of the large one. (b) Unregistered agent + tight budget; assert refusal with `vram_footprint_unknown`. (c) Unregistered agent + plentiful budget; assert admission on legacy default + info alert.

#### 8.16.9 maint.event.v1 vs sec.alert.v1 crossover doctrine

- [ ] **Real gap.** Across §8.x, the same logical signal sometimes lands on `maint.event.v1` (e.g. `backup_started`), sometimes on `sec.alert.v1` (e.g. `backup_clock_skew`), sometimes on both (e.g. `backup_verify_failed` emits a maint.event AND a sec.alert per §8.3). Operators reading topic feeds get a 50/50 mental-model coin-flip. The actual rule used was author-judgment-at-write-time, not a doctrine.
- [ ] **Doctrine (binding).** Pin the crossover rule:
  - **`maint.event.v1`** is the **audit-trail topic**. EVERY maint plane action emits exactly ONE event here, including successful no-op paths (e.g. `backup_completed{verified:true}`, `prune_completed{rows:0}`, `manual_scale_pin_expired`). The audit log must be complete and queryable — operators reconstruct timelines from this stream.
  - **`sec.alert.v1`** is the **paging topic**. An event lands here ONLY if it requires operator attention NOW (severity ≥ warn) OR is a security signal (e.g. `opsctl_signature_invalid` regardless of severity). Routine successes (`backup_completed{verified:true}`) do NOT emit sec.alert. Routine failures that are self-healing within the agent's retry budget (e.g. one transient bus-publish failure) do NOT emit sec.alert; only failures that the agent cannot self-recover from do.
  - **Both topics** when an event is BOTH an audit-trail signal AND a paging signal (e.g. `backup_verify_failed` is auditable + pages). The two emissions must carry the **same `event_correlation_id`** (NEW required field on both `maint.event.v1` and `sec.alert.v1` payload schemas; sha256(`f"{kind}|{target}|{produced_at}"`)[:16]) so an operator can join them.
- [ ] **Producer-side enforcement.** `swarm.sdk.payloads.MaintEvent` and `SecAlert` factories share a `_dual_emit_helper.py` that, given a `(kind, severity, target)`, returns the topic-pair to publish to (one of `[maint.event.v1]`, `[sec.alert.v1]`, `[maint.event.v1, sec.alert.v1]`) per a static lookup table. Authors don't pick — the table picks for them. Adding a new kind requires adding its row to the table; orphans fail boundary tests.
- [ ] **Operator-facing doc.** `docs/guides/maint_topic_routing.md` (NEW) reproduces the table for human-readability + explains the `event_correlation_id` join pattern.
- [ ] **Proof tests.** (a) For every kind in `KNOWN_MAINT_EVENT_KINDS`, assert the dual-emit table returns a non-empty topic list. (b) `backup_verify_failed` emits to BOTH topics with the same `event_correlation_id`. (c) `backup_completed{verified:true}` emits to maint only. (d) `opsctl_signature_invalid` emits to sec only (no audit-redundant maint emission — the consumer's ack `accepted=false` is the audit anchor).

#### 8.16.10 Pattern allowlist fingerprint authentication strength

- [ ] **Real gap.** §8.7 stores `hit_fingerprint = sha256(NFC(hit_substring))[:16]` (16 bytes = 128 bits). Plain SHA-256 truncation is collision-resistant against birthday attacks at ~2^64 work — but it is **not authenticated**. An attacker who can observe a quarantined-then-allowlisted substring for `(source, rule_id)` can mount a chosen-prefix attack and craft a NEW substring with the same first-128-bit-truncated SHA-256 in roughly 2^64 work (high but not infeasible for a determined attacker against a long-lived allowlist row). With the bypass, the attacker's payload sails past the rule.
- [ ] **Doctrine (binding).** Replace plain truncated SHA with **HMAC-SHA256 keyed on a server-side secret**:
  - `hit_fingerprint = HMAC-SHA256(key=<server-secret>, msg=NFC(hit_substring))[:16]` — same 16-byte storage, but collision attacks now require knowing the server secret. The secret lives at `cfg.sec_input_allowlist_hmac_key_path` (default `/var/lib/negelir/secrets/allowlist_hmac.key`, mode 0400, generated on first boot via `make ops.bootstrap-allowlist-key`, NEVER readable by operators — only the `sec.input.v1` agent process can read it; same posture as the §8.15.7 audit-chain HMAC key).
  - **Backward-compat.** Existing rows (post-Phase-8-landing pre-§8.16-revision) used plain SHA. The migration adds `fingerprint_alg CHAR(1) DEFAULT 'h'` (h=hmac, s=sha — legacy). Eval-time matcher computes both algorithms and matches against either; on a legacy-row match, emits `maint.event.v1{kind=pattern_allowlist_legacy_hit, row_id, source, rule_id}` once per row (debounced) prompting operator-driven re-fingerprinting via `make ops.allowlist-rehash` (one-shot script that reads each `s`-row, recomputes with HMAC, writes a new `h`-row, marks the old `s`-row state='e').
  - **Key rotation.** HMAC key rotation requires re-fingerprinting EVERY active row (HMAC is keyed; old key produces different fingerprints than new). Rotation cadence is operator-driven (`make ops.rotate-allowlist-key` — generates new key, re-fingerprints active rows in a single transaction, writes audit). Hard cap `cfg.sec_input_allowlist_hmac_key_max_age_days` (default 365); past threshold the agent emits `sec.alert.v1{kind=allowlist_hmac_key_rotation_overdue, severity=warn}` daily.
- [ ] **Proof tests.** (a) Two distinct substrings with deliberately-colliding plain-SHA-256-truncated-to-128-bits (constructed via a precomputed test vector); assert HMAC fingerprints differ. (b) Re-fingerprint script: insert 100 legacy rows, run script, assert exactly 100 new HMAC rows + 100 legacy rows marked expired + audit event per row. (c) Key rotation: rotate, assert active-row count unchanged, eval-path matches the new fingerprints, old fingerprints no longer match.

#### 8.16.11 Sec-plane backpressure symmetry

- [ ] **Real gap.** §8.11 has a 3-tier shedding watchdog on `maint.event.v1` consumer lag. The §8.8 sec-decimater agent consumes `sec.alert.v1{kind=denylist_growth_anomaly, severity=critical}`. A flood of legitimate denylist_growth_anomaly alerts (e.g. an active DDoS firing the §7.3 cap repeatedly) spikes the sec.alert.v1 stream; the decimater agent's per-source ledger fills at the same rate the alerts arrive; the §8.10 self-isolation threshold (`maint_self_dlq_alert=100`) trips and the decimater goes observer-mode — at exactly the moment the system most needs it.
- [ ] **Doctrine (binding).** Symmetric watchdog on `sec.alert.v1` consumer-side specifically for §8.x consumers (`maint.sec.v1`, `maint.scaler.v1` for `scale_throttled` self-feedback, `maint.dlq.v1` for `consumer_likely_broken` consume): `cfg.sec_plane_lag_alert_ms` (default 5000ms — same as maint), `cfg.sec_plane_lag_alert_window_s` (default 60s). Same 3-tier shedding (same thresholds — symmetric ergonomics). **Critical exception:** sec-decimater action (Lua decimate call) is treated as an **emergency action** (per §8.15.9 noise-window override): under tier-3 sec-plane shed, decimater STILL fires (the system is under attack; shedding the response is the wrong move). Other §8.x sec-plane consumers shed normally.
- [ ] **Cross-plane independence.** Maint-plane shed and sec-plane shed are independent state machines — one being in tier-3 does not imply anything about the other. Boundary test: enumerate the 3-tier state product (4×4 = 16 combinations); each combination has an independently-defined emission policy.
- [ ] **Proof tests.** (a) Inject 6s lag in `sec.alert.v1`; assert tier-1 shedding alert + decimater STILL fires when an alert lands. (b) Inject 70s lag; assert tier-3; assert decimater STILL fires (emergency override); assert other §8.x sec-plane consumers shed. (c) Maint-plane in tier-3 + sec-plane in tier-0; assert sec-plane consumers operate normally regardless of maint state.

#### 8.16.12 qa↔predict DLQ correlation thread

- [ ] **Real gap.** §8.5 forbids auto-replay of `qa.request.v1.dlq` (PII). A real production qa.request that died downstream may have spawned 1-N `predict.request.v1` envelopes BEFORE failing; those predict.request envelopes can also DLQ if predictors died mid-flight. Operators investigating a qa.request failure today have no thread back to the predict.request DLQ entries that share the qa origin. Each is replayable independently, but the operator can't construct the right replay without manual log-spelunking.
- [ ] **Doctrine (binding).** Add **optional `qa_correlation_id`** to the `predict.request.v1` payload schema. When the Phase 7 `qa.input` agent fans out a qa.request into N predict.requests, it stamps each with the qa_correlation_id (= `qa.request.v1.envelope.message_id` per Phase 3 §3.2). `qa.request.v1` itself does NOT carry the field (it's the source). Predict.request DLQ entries thus carry the qa_correlation_id; `ops.dlq-show --topic predict.request.v1.dlq --qa-correlation-id <id>` lists the related entries. `ops.dlq-replay --topic predict.request.v1.dlq --qa-correlation-id <id>` replays them as a batch.
- [ ] **Schema versioning.** `predict.request.v1` payload schema bumps `kind_schema_version` 1→2 per §8.15.2 (additive optional field; no `kind_v2` needed). Old consumers that don't read the field are unaffected; new consumers see it.
- [ ] **Audit linkage.** When the §8.5 supervisor emits `kind=dlq_replayed` for an entry that carries `qa_correlation_id`, the audit row includes the field — operators can join across `dlq_replayed` audit rows to reconstruct the full qa session's downstream replays.
- [ ] **No PII bridging.** The `qa_correlation_id` is just an envelope id (random UUID) — it does NOT carry the qa text. Replaying predict.requests via this thread leaks no PII (the predict envelopes were already PII-stripped at the Phase 7 boundary).
- [ ] **Proof tests.** (a) Stub a qa.request fanning into 3 predict.requests; force all 3 to DLQ; assert `ops.dlq-show --qa-correlation-id <id>` returns exactly the 3 entries. (b) Replay-by-correlation-id; assert all 3 re-published with original ids preserved. (c) Old predict.request without qa_correlation_id (legacy schema_version 1); assert query returns it under "no correlation" bucket, not under the queried id.

#### 8.16.13 `swarm.demo` live-Redis profile + realistic latency budget

- [ ] **Real gap.** §8.9 DoD asserts `make swarm.demo` walks an `ops.denylist-clear` round-trip with `< cfg.opsctl_ack_timeout_ms` ack latency. The current `swarm.demo` uses `InMemoryBus` where publish-to-consume latency is sub-millisecond (function call). The 5000ms budget passes trivially with N orders of magnitude headroom — the test verifies nothing about real Redis Streams behavior.
- [ ] **Doctrine (binding).** Split into two demos:
  - **`make swarm.demo`** (default, dev): InMemoryBus, asserts logical correctness only (events emitted in the right order, ack received, audit row written). Latency budget removed.
  - **`make swarm.demo.live`** (NEW, opt-in, requires running Redis): launches the §2 mock Redis stack via `docker compose --profile demo`, runs the same workflow against real Redis Streams, asserts ack latency < `cfg.opsctl_ack_timeout_ms_live_demo` (NEW knob, default 1000ms — the **realistic** budget against Redis on localhost; the 5000ms knob is the hard ceiling for prod where network adds variance). Also asserts post-test cleanup (no leftover keys in the test prefix).
- [ ] **CI integration.** `make swarm.demo` runs in `make test.ai`; `make swarm.demo.live` runs in `make test.integration` (which is gated on the integration profile per repo doctrine). Phase 12 chaos tests inherit the live profile.
- [ ] **Proof tests.** (a) Run `make swarm.demo` against InMemoryBus; assert success without latency assertion. (b) Run `make swarm.demo.live` against mock Redis; assert latency < 1000ms; assert post-test Redis key sweep finds zero leftover keys with the test prefix.

#### 8.16.14 Operator key_id derivation invariant

- [ ] **Real gap.** §8.14.4 says "the matching public-id-only mapping `<key_id> → <operator_email>` is committed to `infra/maint/opsctl_operators.json`". §8.15.4 says "make ops.bootstrap-key" generates the key. NOWHERE is the `key_id` derivation specified. Two operators reviewing each other's PRs cannot mechanically validate the mapping (does my new operator's PR carry the right key_id for the secret on their laptop?). Today: trust + Slack screenshot. Tomorrow: reproducible cryptographic derivation.
- [ ] **Doctrine (binding).** `key_id = sha256(f"negelir-opsctl-key-v1|{operator_email}|{base64(key_bytes)}")[:16]` (HEX). The derivation:
  1. Binds the key_id to the operator email (a key holder cannot impersonate another operator by re-using their key_id).
  2. Binds to the key bytes (a chosen-collision attack would require finding two keys with the same SHA truncation AND for the same email — infeasible).
  3. Binds to a versioned domain separator (`negelir-opsctl-key-v1`) so future derivations can roll forward (`-v2`) without colliding with v1 ids.
- [ ] **`make ops.bootstrap-key` CLI.** Generates 32 random bytes → writes to `~/.negelir/opsctl_key` (mode 0600) → computes the canonical `key_id` per the derivation → prints to stdout the **operators.json line** the operator copy-pastes into their PR:
  ```json
  "<key_id>": {"email": "<operator-email>", "added_at": "<iso>", "revoked_at": null}
  ```
- [ ] **Self-verification.** A new `make ops.verify-key-id OPERATOR=<email>` reads the local key + email, recomputes `key_id`, asserts it matches the entry in `infra/maint/opsctl_operators.json`. Operators run this after pulling main to confirm their key still authenticates. Mismatch → `key_id_drift` exit + a clear runbook hint.
- [ ] **Boundary test.** `xops/maint/key_id.py::derive(email, key_bytes) -> str` is the single function used by both the CLI and consumer-side verification. AST scan asserts no other code path computes a key_id (single source of truth).
- [ ] **Proof tests.** (a) Derive key_id for a fixed (email, key) pair; assert the result is the documented test vector. (b) Two operators with identical key bytes but different emails produce different key_ids. (c) `make ops.verify-key-id` against a tampered operators.json; assert `key_id_drift` exit.

#### 8.16.15 Phase-5 trainer prerequisite gate for §8.13.1 model-lineage

- [ ] **Real gap.** §8.13.1 requires every model artifact to carry a `<artifact>.lineage.json` sidecar with `{predictor_id, version, trained_at, trainer_commit_sha, training_data_window_utc, source_calibration_row_ids, source_outcome_row_ids, hyperparameters_sha256}`. Phase 5 is implemented (per repo memory: `Phase 5 — IMPLEMENTED (predictors + consensus.v1 + reactors + backtest harness)`); the trainer reactor today does NOT write a lineage sidecar (it writes weights only). Shipping §8.13.1 against today's trainer means EVERY artifact is missing the sidecar, EVERY load fires `backup_model_lineage_missing`, the alert is constant noise → operators silence the rule → the entire §8.13.1 invariant is performative.
- [ ] **Doctrine (binding).** §8.13.1 is **gated on Phase 5.x landing the lineage sidecar writer**. Two coordinated changes:
  1. **Phase 5.x patch (lands FIRST, separate PR before Phase 8 §8.13.1 ships):** `ai/swarm/agents/reactor.py::TrainerReactor` is extended to write `<artifact>.lineage.json` alongside every weight save. The lineage fields are derived from the trainer's input (training_data_window from the request envelope; source_*_row_ids from the rows the trainer actually read; commit_sha from the build metadata). New tracker row `5,trainer-lineage,in-progress,...` precedes Phase 8 implementation.
  2. **Phase 8 §8.13.1 startup-time backfill:** for any pre-existing artifact missing a sidecar, the §8.13.1 agent emits ONE info event `kind=backup_model_lineage_legacy, target=<artifact>` (not the warn alert) so operators see the legacy set without paging fatigue. Backfill-via-retraining is operator-driven (`make ops.retrain-for-lineage PREDICTOR=<id>`); backfill is NEVER automatic (auto-retraining without operator gate violates the Phase 8 doctrine "never trains models").
- [ ] **Hard prerequisite assertion.** §8.13.1 `RegistryAuditor.preflight()` reads the `xops/versioning/chart.json` `swarm` minor version; refuses to start if the swarm version is below the Phase 5.x patch that introduces the lineage writer (`fail_safe_lineage_writer_missing`). New chart.json entry: a per-component `min_compatible_with` map asserting cross-component version floors. Boot-time validator at `xops/versioning/version.py::validate_compatibility()` walks the map and refuses on violation.
- [ ] **`min_compatible_with` registry.** First entries:
  ```json
  "swarm": {"min_compatible_with": {"ai": "1.4.0"}},
  "infra_mock": {"min_compatible_with": {"swarm": "0.22.0"}},
  ```
  Phase 8 §8.13.1 lands an entry `"swarm": {... "ai": "1.5.0"}` once the trainer lineage patch ships at ai 1.5.0. Operators have a mechanical guard against partial upgrades.
- [ ] **Proof tests.** (a) Boot §8.13.1 with chart.json indicating swarm < lineage-writer-min; assert refuse with `fail_safe_lineage_writer_missing`. (b) Boot with chart.json at the right floor; assert successful boot AND legacy backfill path emits `backup_model_lineage_legacy` for pre-existing artifacts (no warn alerts). (c) `xops/versioning/version.py::validate_compatibility()` against a synthesized chart with violating constraint; assert raise.

#### 8.16.16 Cross-section additions to §8.9 DoD

- [ ] All proof tests in §8.16.1–§8.16.15 land alongside the §8.9 ones (adds ~35 new proof tests).
- [ ] New chaos catalogue stubs in `docs/testing/phase12_catalogue.md` (8): `chaos-scaler-unconfigured-agent`, `chaos-spool-flush-ack-vacuum`, `chaos-prune-fk-violation`, `chaos-s3-multipart-id-expired`, `chaos-object-lock-permission-loss`, `chaos-sec-plane-flood`, `chaos-allowlist-fingerprint-collision`, `chaos-min-compatible-version-violation`.
- [ ] New `maint.event.v1` kinds (8): `maint_scaler_default_applied`, `spool_flush_acks_reconciled`, `prune_started`, `prune_completed`, `prune_skipped`, `backup_offsite_upload_id_expired`, `dlq_replay_policy_loaded`, `pattern_allowlist_legacy_hit`, `backup_model_lineage_legacy`. New `sec.alert.v1` kinds (10): `maint_scaler_unconfigured_agent`, `maint_scaler_orphan_cfg`, `spool_flush_acks_incomplete`, `backup_offsite_lifecycle_too_aggressive`, `backup_offsite_preflight_failed`, `vram_footprint_unknown`, `allowlist_hmac_key_rotation_overdue`, `sec_plane_lag_high`, `key_id_drift` (operator-CLI surface), `fail_safe_lineage_writer_missing` (boot-refusal surface). All join the §7.4 known-kinds set; per-kind sub-schemas under `ai/swarm/sdk/schemas/maint.event.v1/<kind>.json` per §0 + §8.15.2 versioning discipline. **Per-topic dual-emit table (§8.16.9) updated** with all new kinds — boundary test green.
- [ ] New cfg knobs for triangle test: `maint_scaler_default_max_replicas`, `opsctl_spool_ack_max_wait_h`, `maint_backup_offsite_state_max_age_h`, `maint_backup_offsite_lifecycle_min_days`, `maint_backup_offsite_object_lock_required`, `maint_backup_offsite_preflight_interval_h`, `maint_dlq_replay_allow_overrides` (list), `maint_scaler_vram_pessimistic_threshold_pct`, `maint_scaler_cpu_budget_pct`, `sec_input_allowlist_hmac_key_path`, `sec_input_allowlist_hmac_key_max_age_days`, `sec_plane_lag_alert_ms`, `sec_plane_lag_alert_window_s`, `opsctl_ack_timeout_ms_live_demo`, `telemetry_debug_enabled`, `telemetry_debug_max_series`. The §8.9 triangle-test bullet's knob inventory grows accordingly (~16 new knobs).
- [ ] New exit code pinned in `xops/opsctl/_exit_codes.py`: `10=prune_only_forbidden` (operator passed `--prune-only` to `ops.backup-now`). Boundary test enumerates `_exit_codes.py` against `_classify.py` and the documented runbook (now `5..10` continuous range).
- [ ] **`event_correlation_id` field added to BOTH `maint.event.v1.json` and `sec.alert.v1.json` payload schemas (required when the kind is in the dual-emit set per §8.16.9; null/omitted otherwise).** Schema-version bumps: `maint.event.v1` schema_version unchanged (additive optional via per-kind sub-schema), `sec.alert.v1` schema_version 1→2. Producer-side helper `swarm.sdk.payloads.dual_emit_correlation_id(kind, target, produced_at)` is the single source for the value; AST scan rejects ad-hoc derivations.
- [ ] **Doctrine docs sync.** NEW `docs/guides/maint_topic_routing.md` per §8.16.9 (operator-facing crossover doctrine + dual-emit table). NEW `docs/design/security_exceptions.md` per §8.16.7 (DLQ replay-policy override registry). `docs/guides/backup_runbook.md` extended with §8.16.5 + §8.16.6 (multipart-resume + Object-Lock preflight troubleshooting). `docs/guides/opsctl_security.md` extended with §8.16.14 key_id derivation + verification flow.
- [ ] **Migration delta.** No new migration consumed. `migrations/010_pattern_allowlist.sql` (still pre-implementation) gains `fingerprint_alg CHAR(1) DEFAULT 'h' CHECK (fingerprint_alg IN ('h','s'))` from §8.16.10 — single in-place edit before Phase 8 implementation begins.
- [ ] **Versioning chart additions.** `xops/versioning/chart.json` gains a top-level `compatibility` block per §8.16.15 storing `{component: {min_compatible_with: {other_component: version, ...}}}`. New `make version.compatibility-check` validates the constraints across the chart on boot and CI. Round-trip test asserts the chart edit is canonical.
- [ ] **Versioning addendum.** §8.16 lands as an additive doctrine revision; `swarm` chart key gains a **patch** bump on top of the §8.15 patch (still pre-implementation, design only — Phase 8 has not shipped); `xops` patch for the new `xops/maint/prune_order.py` + `xops/maint/key_id.py` + `swarm.sdk.payloads.dual_emit_correlation_id` helper + `make version.compatibility-check` + `make swarm.demo.live` + `make ops.bootstrap-allowlist-key` + `make ops.rotate-allowlist-key` + `make ops.allowlist-rehash` + `make ops.bootstrap-key` + `make ops.verify-key-id` + `make ops.retrain-for-lineage` + `make verify.dlq-replay-policy` flags; `docs` minor for the two new docs (`maint_topic_routing.md`, `security_exceptions.md`) + extended runbooks.

---

## 🟦 Phase 9 — Go REST API & Identity (Public Surface)

**Goal:** A clean, versioned, securely-bounded REST API in Go that Flutter and external clients can call. **Public surface = single ingress for the swarm.** Every byte that crosses this boundary is sanitized, authenticated, authorised, rate-limited, audited, and either served from cache or dispatched as a swarm RPC with a hard latency budget.
**Depends on:** Phase 2 (internal CA + mock stack), Phase 3 (SDK + bus), Phase 4 (`cache.v1`, `match.normalized`), Phase 5 (`predict.request` / `consensus.v1` round-trip + `prediction_id` + `produced_at`), Phase 6 (`predict.approved.v1` — what the API actually serves; raw `predict.final` is a CANDIDATE), Phase 7 (`server/internal/sec/` — sanitize / patterns / XFF / costs / Lua loader / GCRA in-process bucket).
**Forward-coupled to:** Phase 10 (NLP humanizer — `/v1/qa` body shape), Phase 11 (compute device probe — does NOT run on the API), Phase 12 (chaos + adversarial corpus → API gates), Phase 13a (`profile_id` resolution from URL path), Phase 14 (K8s — replicas:N for the API, replicas:1 for `consensus.v1`), Phase 16 (Emitter — alternative read backend behind `CalibrationStore`/feeds), Phase 19 (GA SLOs), Phase 20 (tier enforcement — built-but-dormant edge-only at this exact tier).

### 9.0 Forward-phase + cross-phase alignment

- [ ] **Pivot v3 home.** Phase 9 lands under `server/internal/{api,auth,rpc,handlers,middleware,authz,errors}/` per [`docs/design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md). The Phase 7 `server/internal/sec/` library is consumed, not re-implemented.
- [ ] **Wire authority delta (additive to §3.5).** Phase 9 adds **TWO new bus topics** and is the **sole writer** for both:
  - `api.request.v1` — fan-in audit of every accepted public request (post-auth, post-sec gate, pre-RPC). Single producer = `api.gateway.v1`. Consumers: `telemetry.v1`, `audit.v1` (per Phase 8 §8.13.2 hash-chain mirror) — open enum so future Phase 19 SLO consumers can subscribe.
  - `api.response.v1` — fan-out audit of every response sent (status, latency_ms, bytes, cache_hit, degraded, request_id). Same producer/consumer set as `api.request.v1`.
  - **Boundary tests (Phase 3.6 enumerative):** `api.gateway.v1` is sole writer for both topics; consumer-set bounded; AST scan confirms no other agent ever publishes to either; `swarm.sdk.wire_contracts.API_TOPIC_V1_ALLOWED_PRODUCERS = ("api.gateway.v1",)`.
- [ ] **Migration delta.** Phase 8 §8.13.x (model lineage etc.) lands `010..011`. Phase 9 lands `012_users_and_sessions.sql`, `013_api_audit_partitions.sql`, `014_jwt_keys.sql`. Phase 10/14 slide accordingly. Doctrine: idempotent + range-partitioned by month (mirrors §8.14.1 + §8.13.2).
- [ ] **Versioning bumps (chart.json).** `server` minor on first `/v1` route landing; `server` patch per subsequent handler; `xops` patch for the `make api.*` targets; `docs` minor for the new `docs/design/API.md` + `docs/guides/api_runbook.md`. `compatibility` block (per §8.16.15) gains `"server": {"min_compatible_with": {"swarm": "<predict.request producer min>", "ai": "<consensus min>"}}`.
- [ ] **Cross-phase forward contracts re-asserted (do NOT silently violate):**
  - §3.3 idempotency: `request_id` is generated by **the API**, round-tripped unchanged through `predict.request → predict.vote → predict.final → predict.approved → API response`. **Constraint:** `cfg.api_request_timeout_ms ≥ cfg.consensus_window_ms + cfg.api_consensus_overhead_ms + cfg.proofreader_window_ms` (the full path, not just consensus). Boundary test enforces.
  - §5 `prediction_id` is deterministic `sha256(match|market|request_id|calibration_version)[:16]`; the API surfaces it as the `ETag`/`X-Prediction-Id` header. ETag-conditional GET (`If-None-Match`) returns `304` against the cached row.
  - §6 the API serves **`predict.approved.v1`**, NEVER raw `predict.final`. Mistake here ships unflagged predictions to users. Boundary test pins.
  - §7 the API uses `server/internal/sec/` exactly as shipped — no parallel sanitizer, no parallel pattern engine, no parallel rate library. AST scan rejects re-implementation in `server/internal/api/`.
  - §11 the API process MUST run on CPU only (`NEGELIR_DEVICE=cpu` in its container) — GPU is for predictors. Boundary asserts `torch`/`cuda` not imported in any `server/...` Go transitive dep (cgo audit).
  - §13a `profile_id` = league_id today; the API extracts from `/v1/leagues/{id}/...` and stamps the bus envelope. Phase 13a swap to catalog-driven needs zero handler change.
  - §14 the API is replicas:N stateless — all per-request state in Redis (sessions, idempotency cache, RPC waiters keyed on `reply_to`). No in-process map survives pod restart.
  - §20 tier enforcement is at THIS edge (`tier_quota.go` middleware) — predictors never know the tier. Built-but-dormant flag `cfg.api_tier_enforcement_enabled=false` until Phase 20 lands.

### 9.1 Surface (v1) — full route table + semantics

```
# Liveness (separate from readiness — K8s probes need both)
GET    /v1/healthz                                  # liveness — process up; never depends on PG/Redis/bus
GET    /v1/readyz                                   # readiness — PG/Redis/bus all green AND this pod owns ≥1 fresh `cache.v1` entry
GET    /v1/version                                  # build SHA + chart.json snapshot

# Catalog (read-mostly; Phase 4 `cache.v1` warm)
GET    /v1/leagues                                  # paginated, cursor
GET    /v1/leagues/{league_id}/fixtures?from=&to=   # `from`/`to` ISO-8601 UTC, ≤ cfg.api_fixture_window_max_days (default 14)
GET    /v1/matches/{match_id}                       # ETag = match_normalized.row_hash

# Predictions (RPC against swarm — Phase 5 path)
GET    /v1/matches/{match_id}/predictions?market=   # comma-separated markets ⊆ cfg.api_allowed_markets
                                                    # ETag = prediction_id
                                                    # Response carries: produced_at, calibration_version,
                                                    #                   degraded, degraded_reason, prediction_id
                                                    # 503 + Retry-After when consensus times out AND no cache
                                                    # 410 Gone when match_id retired (Phase 13b deprecation)

# Q&A (Phase 10 NLP — body sanitized through sec.input.v1, fanned out to predict.requests via qa_correlation_id per §8.16.12)
POST   /v1/qa                                       # body { "q": str (≤ cfg.qa_input_max_bytes), "locale": "tr-TR" }
                                                    # 202 + qa_correlation_id when answer needs >1 predict.request
                                                    # 200 inline when answer is single-source / cache-hit

# Identity
POST   /v1/auth/register                            # locked behind cfg.api_self_registration_enabled (default false)
POST   /v1/auth/login                               # → access (15m) + refresh (30d, rotated on use)
POST   /v1/auth/refresh                             # rotates refresh; old refresh blacklisted in Redis until original expiry
POST   /v1/auth/logout                              # revokes refresh; access tokens unaffected (short TTL is the policy)
GET    /v1/me                                       # JWT-derived; never reads bus
PATCH  /v1/me                                       # tz, locale, notification opt-ins; bcrypt re-hash on password change

# Operator / dormant tier surface (built but dormant per §9.15)
GET    /v1/me/quota                                 # returns tier + remaining/window; static when tier-flag disabled
```

- [ ] **Content-type discipline.** Every response is `application/json; charset=utf-8`. Errors follow RFC 7807 `application/problem+json`. **Boundary test:** every handler in `server/internal/handlers/` returns one of the two; `text/html` / `text/plain` body bytes rejected at the response-writer wrapper.
- [ ] **Time discipline.** Every timestamp ISO-8601 UTC with `Z` suffix; never local zone, never naïve, never epoch-int in JSON output (epoch only for ETag derivation). Triangle test: cfg knob `cfg.api_time_format="iso8601_utc"` is the only legal value (config validator rejects anything else — leaves room for future `rfc9557` extension behind a flag, not a typo).
- [ ] **Pagination = opaque encrypted cursor, NEVER offset.** Cursor body = `AES-GCM(seal_key, json{table, last_pk, query_filter_hash, expires_at_unix})`; seal_key in `data/api/cursor_key` (mode 0400, rotated alongside JWT keys per §9.2). Cursor TTL = `cfg.api_cursor_ttl_s` (default 1800s). Tampered / expired cursors → `400 invalid_cursor`. Filter-hash mismatch (caller changed `from=` mid-pagination) → `409 cursor_filter_drift`. **Proof tests:** (a) tampered byte at any position → 400; (b) cursor older than TTL → 400; (c) different `from=` than the one that minted the cursor → 409; (d) cursor minted with rotated-out key → 400 (graceful) NOT panic.
- [ ] **Header inventory (binding).** Request: `Authorization: Bearer <jwt>`, `Idempotency-Key: <client-uuid-v4>` (POST /v1/qa + POST /v1/auth/* only; mandatory for POST mutations), `If-None-Match: <etag>`, `Accept-Language` (Phase 10 picks Turkish even if missing), `X-Forwarded-For` (consumed via §7.6 `DeriveClientIP`), `X-Request-ID` (echoed back; if absent, server mints a UUIDv7 — sortable). Response: `ETag`, `X-Request-ID`, `X-RateLimit-Remaining` / `X-RateLimit-Reset` (per-token + per-IP both echoed; lower wins), `X-Prediction-Id`, `X-Calibration-Version`, `X-Degraded` (`true` if `degraded`), `X-Cache` (`hit|miss|stale|bypass`), `Sunset` (RFC 8594, set when route is in deprecation window per §9.11), `Retry-After` (on 429/503).
- [ ] **HTTP error taxonomy (closed enum, mirrors `internal/errors/codes.go`).** Codes: `400 invalid_request | invalid_cursor`, `401 unauthenticated | token_expired | token_revoked`, `403 forbidden | tier_required`, `404 not_found | match_retired`, `409 conflict | cursor_filter_drift | idempotency_key_replay_with_different_body`, `410 gone`, `413 payload_too_large`, `415 unsupported_media_type`, `422 unprocessable | qa_quarantined`, `425 too_early` (consensus warming, retry hinted), `429 rate_limited | tier_quota_exceeded | denylisted` (`Retry-After`), `499 client_disconnected` (audit-only, never sent), `500 internal` (rate-limited log; no stack to client), `502 upstream_consensus_failure`, `503 service_unavailable | bus_unreachable | consensus_window_blown` (`Retry-After`), `504 rpc_timeout`. **Boundary test:** every code emitted by the handlers is in the enum; AST scan asserts no `c.JSON(503, gin.H{"error": "..."})` ad-hoc strings outside `internal/errors`.
- [ ] **Body-size cap (defense in depth, even before §7.6 sec gate).** `cfg.api_request_max_bytes` (default 64 KB; `/v1/qa` sub-cap = `cfg.qa_input_max_bytes`; `/v1/auth/login` sub-cap = 4 KB). Server-side `http.MaxBytesReader` BEFORE handler dispatch — bcrypt-bomb / RAM-exhaustion defense. Returns `413` with `application/problem+json`.

### 9.2 Identity, sessions, and key lifecycle

- [ ] **User store.** `users(id, email_lower CITEXT UNIQUE, password_hash TEXT, password_alg CHAR(1), created_at, last_login_at, locale, tz, tier_id INT REFERENCES tiers(id) DEFAULT 1, status SMALLINT)`. Migration `012_users_and_sessions.sql`; `email_lower` gets the unique index; `email` original-case kept in a separate column for display. **No PII in JWT** — only `sub` (user_id UUIDv4) + scopes.
- [ ] **Password hashing.** `bcrypt cost=12` (matches OWASP 2024 floor); `cfg.api_bcrypt_cost` is the knob; cost re-hash on login when stored cost < target (transparent to user). `password_alg='b'` today; reserves `'a'` (argon2id) for future swap. **Hard rule:** `bcrypt` cost must yield ≥ 250 ms on the API container — startup probe asserts on cold start with a single test hash; refuse boot if < 100 ms (defends against accidentally landing on a beefy host that turns the cost into a no-op).
- [ ] **JWT (RS256 + KID rotation).** Key store on disk `data/api/jwt_keys/<kid>.{pub,priv}.pem` (priv mode 0400). At first run: generate `kid_001`, atomic write, set as ACTIVE. Active key set in `jwt_keys` table (mig `014`); columns `(kid, alg, pub_pem, priv_pem_path, generated_at, rotated_in_at, rotated_out_at, status ∈ {pending, active, retired})`. **Verifiers accept any key with status ∈ {active, retired}** (so old tokens keep working until natural expiry); signers ONLY use active. **Rotation runbook (`make api.rotate-jwt-key`):** generate `kid_NNN` → state=`pending` → 60s warm wait (so all replicas pick it up via `mtime` poll on the keystore dir, default `cfg.api_jwt_key_poll_s=10`) → atomic flip to `active` (old → `retired`) → after `cfg.api_jwt_retired_grace_s` (default = max access-token TTL + 60s) → `purged` (priv file zeroized via `os.WriteFile` w/ random + remove). **Proof tests:** (a) token signed with rotated-out kid still verifies inside grace; (b) token signed with purged kid → 401 `token_expired`; (c) replica that missed the poll window still verifies via DB-backed lookup fallback (the keystore mtime poll is an OPTIMIZATION, not the source of truth — DB is); (d) corrupt `.priv.pem` on boot → refuse-to-start with `jwt_key_unreadable` exit-code (NEVER fall back to plaintext / HS256).
- [ ] **Token shape.** Access JWT TTL = `cfg.api_access_ttl_s` (default 900s). Refresh = opaque random 32-byte b64url stored in Redis `auth:refresh:<sha256(token)[:16]>` with TTL `cfg.api_refresh_ttl_s` (default 30d). **Refresh rotation:** every `/v1/auth/refresh` mints a NEW refresh + invalidates the old one (single-use). **Replay window:** `cfg.api_refresh_replay_grace_s` (default 30s) — within grace, accept the old refresh ONCE so a network retry doesn't lock the user out (idempotency on the refresh endpoint). Outside grace → `401 token_revoked` AND emit `sec.alert.v1{kind=refresh_token_replay, severity=warn}` (operator visibility). **Logout:** revokes refresh; access tokens cannot be revoked (short TTL is the policy — documented). For server-driven kill-switch, see §9.2 below.
- [ ] **Server-driven access-token revocation (escape hatch).** Token introspection cache in Redis `auth:rev:<jti>` (set when an operator runs `make api.revoke-jti JTI=...`; TTL = remaining token life). Verifier checks the deny-set on EVERY request via Redis `EXISTS` (sub-ms). **Cost-bounded:** the deny-set holds at most `cfg.api_revocation_set_max=10000` entries (LRU eviction); operator alerted at 80% via `sec.alert.v1{kind=jti_revocation_set_pressure}`.
- [ ] **mTLS to internal services.** API → swarm bus (Redis Streams), API → Postgres, API → cache Redis (if separate): all use the Phase 2 internal CA (`infra/mock/ca/`). Server cert at `data/api/tls/api.{crt,key}` (priv mode 0400); client cert per service at `data/api/tls/client_{redis,pg,bus}.{crt,key}`. Cert TTL = 90 days; renewal cron at 60-day mark via `make api.tls-rotate` (subprocess to the existing Phase 2 cert-mint script). **Boot probe:** issue a 1-byte ping over each mTLS-wrapped client BEFORE binding the public listener; refuse boot on TLS handshake failure (loud — prevents the API from going green on plaintext fallback to a service that rejected mTLS). Proof tests use the in-repo CA.
- [ ] **OIDC plug-point (interface, no provider).** `internal/auth/oidc.Provider` interface with `Discover() / Exchange(code) / Userinfo(token) / IDTokenClaims()`; default impl `NoopProvider` returns `not_configured`. Loader looks for `OIDC_*` env keys; absent → noop. **Forbidden in this phase:** bundling Google/MS/GH SDKs (doctrine "no external secret-manager dep" extends to identity providers in v1).
- [ ] **Self-registration default OFF.** `/v1/auth/register` returns `403 forbidden` unless `cfg.api_self_registration_enabled=true`. When on, integrates with `server/internal/sec` rate (`endpoint_costs.yaml` cost=3) and a per-IP /24 cap of `cfg.api_register_cap_per_subnet_per_h=20` to prevent mass-account-spray.

### 9.3 Request flow (RPC pattern, idempotency, cache-first, cancellation)

```
client →[mTLS termination handled by service mesh in K8s; gin in compose]→
       → req-id mint (UUIDv7) → §7.6 sec gate (sanitize + pattern + XFF + cost)
       → JWT verify (deny-set probe)  → tier check (dormant)
       → idempotency-key lookup (POST mutations)
       → publish api.request.v1 (audit)
       → cache.v1 GET (read endpoints) — HIT → respond + audit + return
       → MISS → publish predict.request{request_id, reply_to=`api.reply.<pod>.<short_uuid>`}
              → wait Redis Streams XREAD on reply_to until cfg.api_request_timeout_ms
              → first message wins; subsequent ignored; reply_to ttl=window+5s autodelete
       → publish api.response.v1
       → respond
```

- [ ] **Per-pod reply_to topic.** `api.reply.<pod_instance_id>.<request_short_uuid>` — bounded namespace; `MAXLEN ~ 1` per stream (single message expected); reaper sweeps stale streams every `cfg.api_reply_reaper_s` (default 60s). **Boundary:** the API is the SOLE consumer of any `api.reply.*` stream; AST scan + boundary test confirm no other agent reads/writes.
- [ ] **Timeout-budget chaining.** `cfg.api_request_timeout_ms` (default 2500) ≥ `cfg.consensus_window_ms` + `cfg.proofreader_window_ms` + `cfg.api_consensus_overhead_ms` (default 200) + transit jitter budget `cfg.api_transit_jitter_ms` (default 100). **Boot validator** at `internal/config/validate.go` refuses to start if the inequality is violated — no sleep, no prayer, no race-on-prod.
- [ ] **Cancellation propagation.** Client disconnect (`r.Context().Done()`) → publish `predict.cancel.v1{request_id}` to bus → consensus.v1 marks the row `cancelled` and stops fan-out scoring. `predict.cancel.v1` is a NEW topic (single producer = `api.gateway.v1`; consumer = `consensus.v1` only). **Boundary tests** + idempotency: cancellation arriving after `predict.final` is dropped without alerting (race expected, not pathological).
- [ ] **Idempotency-Key cache.** Redis `idem:<sha256(user_id|method|path|body_hash)>` → `{response_status, response_body_sha256, request_id, expires_at}` with TTL `cfg.api_idempotency_ttl_s` (default 86400). Same key + same body → return the stored response (203 `X-Replayed: true` echo). Same key + DIFFERENT body → `409 idempotency_key_replay_with_different_body` + `sec.alert.v1{kind=idempotency_drift, severity=warn}`. **Proof tests:** (a) double-POST returns identical bytes; (b) drift detected; (c) inflight request (no stored response yet) → second request blocks on a Redis pubsub channel `idem:wait:<key>` for max `cfg.api_idempotency_inflight_wait_ms` then returns `425 too_early`; (d) poll the wait keyspace at boot to clean stale waiters from prior pod (no zombie blockers).
- [ ] **Cache-first for read endpoints.** GET `/v1/matches/{id}/predictions` first reads `cache.v1` (Phase 4 — keyed on `(match_id, market_set, calibration_version)`). HIT serves immediately + sets `X-Cache: hit`. MISS issues the RPC. **Stale-while-revalidate:** if cache row is older than `cfg.api_cache_stale_after_s` but younger than `cfg.api_cache_max_age_s`, serve `X-Cache: stale` and ASYNC-publish a `predict.request` (caller doesn't wait). **Proof test:** SWR async fan-out is bounded — at most `cfg.api_swr_inflight_max=64` async requests across the pod (Redis SETNX gate keyed on `swr_lock:<match_id>:<market_set>`); excess are no-op'd.
- [ ] **503 + Retry-After contract.** Timeout WITHOUT cache → `503 service_unavailable` + `Retry-After: <ceil(cfg.api_request_timeout_ms/1000)+1>`. Bus unreachable (Redis down) → `503 bus_unreachable` + `Retry-After: 5`. Consensus window blown (predictors all DLQ'd) → `503 consensus_window_blown` + `Retry-After: 10`. Distinct sub-codes so client telemetry can branch.

### 9.4 OpenAPI source-of-truth + handler generation

- [ ] **`server/api/openapi.yaml` is binding.** Go handlers generated via `oapi-codegen` (`make api.gen`). CI gate: `make api.gen-check` regenerates into a tmpdir and `git diff --exit-code` against committed handlers — drift fails the build.
- [ ] **Schema validation in tests.** Every handler test asserts response body validates against the OpenAPI schema (via `kin-openapi` runtime validator — dev/test only, not in hot path). Adversarial test: malformed handler (returns extra field) → schema validator catches before merge.
- [ ] **Swagger UI.** `make api.docs` serves on `localhost:8081` (compose service `api-docs`, profile=`docs`); production image OMITS the docs binary. **No `/v1/docs` route on the public API** — security doctrine.
- [ ] **OpenAPI extensions used (binding):** `x-rate-cost` (per route — totality-checked at boot via §7.6 `CheckTotality`); `x-deprecated-on`, `x-sunset-on` (drives the `Sunset` header per §9.11); `x-tier-required` (dormant; consumed by `tier_quota.go` middleware once §20 lands); `x-idempotent-mutation` (drives the Idempotency-Key requirement). Loader at `internal/api/spec_loader.go` fails boot if any route lacks the required extensions.

### 9.5 Wire-authority additions, schemas, envelope discipline

- [ ] **`api.request.v1` schema** (`ai/swarm/sdk/schemas/api.request.v1.json`): `{request_id, user_id?, anon_subject_key, route, method, status_anticipated:null, accepted_at, sec_gate_ms, auth_ms}`. `additionalProperties:false`. Per §8.16.9 dual-emit doctrine, when a Phase 7 quarantine fires for the same request, the matching `sec.alert.v1` carries the `event_correlation_id = request_id`.
- [ ] **`api.response.v1` schema** (`ai/swarm/sdk/schemas/api.response.v1.json`): `{request_id, status, latency_ms, bytes_out, cache, degraded, prediction_id?, calibration_version?, error_code?}`. **Bytes_out is computed on the actual response writer** (gzipped if applicable) so the audit row is truthful.
- [ ] **`predict.cancel.v1` schema** (new): `{request_id, cancelled_at, reason ∈ {client_disconnect, deadline_exceeded, operator_kill}}`. Producer set bounded to `api.gateway.v1`.
- [ ] **Envelope discipline.** API uses the existing Phase 3 envelope (`message_id`, `topic`, `schema_version`, `produced_at`, `producer`, `kind_schema_version`); `client_id` payload field carries the user_id when present, else `anon:<sha256(subject_key)>[:12]`. **Never** put raw IP in payload (§7.6 `SubjectKey` masked form only). Boundary test scans for IP-shaped strings in published payloads.
- [ ] **Trace propagation.** API mints W3C `traceparent` if absent; `X-Request-ID` is its alias for client-side echo. The trace_id rides the envelope per §8.15.6 and threads through `predict.request → vote → final → approved → api.response.v1`.

### 9.6 Phase-7 sec gate wiring (the integration tier §7.7 deferred)

- [ ] **Library, not parallel impl.** All gates use `server/internal/sec/`: `sec.QAInputGate` for `/v1/qa` body, `sec.ScriptLoader.Verify(loadFn)` at boot for the 2 Lua scripts (refuse-to-start on header-SHA256 drift OR EVALSHA mismatch — closes the §7.7 "Go gateway middleware" deferral).
- [ ] **Endpoint-cost totality** (`sec.CheckTotality(routerPatterns, allowFallback=false)`): boot scans the gin router patterns against `ai/common/security/endpoint_costs.yaml`; refuses to start if any new route lacks an explicit cost entry. **Operator workflow:** add route → CI fails on totality → operator updates `endpoint_costs.yaml` + bumps the doc → ship. Coverage gate makes "I forgot to set the cost" structurally impossible.
- [ ] **XFF derivation.** `cfg.api_trusted_proxies` (CIDR list) parsed via `sec.ParseTrustedProxies`; `sec.DeriveClientIP(xff, peer, trusted)` per request; `sec.SubjectKey(ip, ipv4=32, ipv6=64)` for the per-IP rate bucket. Boundary test: spoofed XFF with untrusted prefix is ignored.
- [ ] **Password-field bypass.** `/v1/auth/login` and `/v1/auth/register` route the password through `sec.PasswordPasses` (length-cap only; no Unicode normalize; no pattern engine). Boundary test: password with leading/trailing whitespace verifies identically before and after sanitize would have run elsewhere.
- [ ] **GCRA in-process bucket** (`sec.SecondaryBucket`) for fail-open per-pod ceiling ahead of the Lua bucket — protects against Redis brown-out without denying users (Allow/Throttle only, never Deny). **Critical:** Phase-7 Lua bucket is the ONLY denial source; in-process bucket throttles by 503 + `Retry-After: 1` (transient hint), Lua bucket returns 429 + the real `Retry-After`. Distinct status codes so client telemetry can distinguish.

### 9.7 Rate limiting, quotas, denylist

- [ ] **Two-tier rate limit.** L1 = §7.6 in-process GCRA (per pod); L2 = §7.3 Lua bucket (per Redis cluster, authoritative). Token-cost = `endpoint_costs.yaml` value. Subject keys: `(jti or anon_subject_key, route_pattern)` for primary; `(SubjectKey(ip), route_pattern)` for IP. Lower-of-two wins. **Headers** `X-RateLimit-Remaining: <min(jti, ip)>` + `X-RateLimit-Reset: <epoch_s>`.
- [ ] **Burst budget.** `cfg.api_burst_capacity` per subject; `cfg.api_burst_refill_per_s`. Cost-aware: `/v1/qa` consumes 5 tokens (per `endpoint_costs.yaml`), `/v1/healthz` consumes 0.
- [ ] **Denylist short-circuit.** Subject in `sec:denylist:<key>` → immediate 429 `denylisted` (no body content; no logging beyond the `api.request.v1` row marked `status=429,denylisted=true`). Lua `sec_denylist_mutate` v1.1.0 lazy-eviction (per §7.3 v1.1.0 audit lesson) means this path is always truthful.
- [ ] **Subnet-mode escape.** When `sec:denylist:capped` is set (§7.3 cap flag), API switches to `SubjectKey(ip)` /24 (IPv4) or /64 (IPv6) bucketing for new requests until flag clears. Header `X-RateLimit-Mode: subnet` is set so client telemetry can attribute throttling correctly. **Proof test:** flip the cap flag mid-test; assert subsequent requests bucket on subnet.
- [ ] **Tier quotas (built but dormant per §20).** `internal/middleware/tier_quota.go` reads `users.tier_id`; checks `tiers.daily_request_cap` (table seeded with one row `{tier_id=1, name='free', cap=NULL}` until §20 ships); when `cfg.api_tier_enforcement_enabled=true`, denies with `429 tier_quota_exceeded`. Counter in Redis `tier:<tier_id>:<user_id>:<utc_yyyymmdd>` TTL 26h.

### 9.8 Observability — RED metrics, structured logs, audit

- [ ] **RED metrics** (Prometheus, `:9091/metrics` on a separate port, NOT public): `api_requests_total{route, status, method, cache, degraded}`, `api_request_duration_seconds_bucket{route, method}` (10ms..2500ms), `api_inflight_rpcs{route}`, `api_cache_hit_ratio{route}` (computed gauge — not a counter), `api_jwt_verify_duration_seconds`, `api_sec_gate_duration_seconds`, `api_idempotency_replays_total{result}`. **Cardinality cap:** `route` is the OpenAPI pattern (e.g. `/v1/matches/:id`), NEVER the substituted ID. `status` is the status code class + exact (`200`, `2xx`, `4xx`, `5xx` summary alongside exact). Boot validator estimates worst-case series count (route × status × method × cache × degraded ≈ 30 × 8 × 3 × 4 × 2 ≈ 5760) and refuses if `cfg.telemetry_max_series` would be exceeded.
- [ ] **Structured logs (JSON, stderr).** Per request: `{ts, request_id, trace_id, route, method, status, latency_ms, user_id_h?, anon_subject_key, ip_subject, sec_gate_ms, auth_ms, cache, degraded, error_code?}`. `user_id_h` = sha256(user_id)[:12] — NEVER raw user_id. Log sampling at `cfg.api_log_sample_pct` (default 100 in dev, 10 in prod) for 2xx; **always 100% for 4xx/5xx**.
- [ ] **Audit hash-chain (Phase 8 §8.13.2 mirror).** `api.response.v1` consumer in the maint plane writes to `api_audit_log` partitioned by month, prev_hmac/row_hmac chain identical to `maint_audit_log`. `make audit.verify-api` walks the chain. **PII discipline:** the chain stores `user_id_h`, NEVER email. Right-to-erasure via `make api.erase-user USER=...` purges `users` row + emits `pii_erased` (Phase 8 path) + null-stamps `user_id_h` columns (the hash is irreversible but a determined attacker with a small user set could rainbow-table; null-stamp post-erasure is belt-and-braces).
- [ ] **Trace export.** OTLP gRPC to `cfg.telemetry_otlp_endpoint` if set; else no-op (no stdout-JSON trace dump — too noisy). Span attributes are a subset of the structured log fields (no PII).
- [ ] **SLO definition (binding for §19 GA gate).** Availability ≥ 99.5% (excluding planned maint windows per §8.16.13 noise window), p95 latency ≤ 250 ms for cache-hit reads, p95 ≤ 800 ms for cache-miss predictions, error rate ≤ 0.5%. Burn-rate alerts via `sec.alert.v1{kind=api_slo_burn, severity=warn|critical}` based on multi-window multi-burn-rate (Google SRE workbook recipe; thresholds in `cfg.api_slo_burn_*`).

### 9.9 Idempotency, cache, backpressure (deeper than §9.3)

- [ ] **Backpressure on the bus.** When Redis Streams `XLEN predict.request.v1 > cfg.api_predict_request_backlog_high` (default 5000), API switches to **cache-only mode**: GET serves cache or 503; POST `/v1/qa` returns `425 too_early` with `Retry-After: 10`. Backpressure flag held in Redis `api:backpressure:on` with TTL 30s, refreshed by the §8.x scaler when it sees the same lag — NOT by the API itself (the API does not write to maint plane). Boundary test: API never publishes `maint.event.v1` / `sec.alert.v1`; AST scan asserts.
- [ ] **Cache invalidation respect.** Phase 4 `CacheInvalidationReactor` writes `cache:<key>:gen` integers; API reads + GETs as `cache.v1<key, gen>`. Stale-gen reads bypass cache (`X-Cache: bypass`).
- [ ] **Backpressure on the response side.** Slow client (TCP send buffer full > `cfg.api_response_write_timeout_ms` default 5000): `c.Writer.CloseNotify()` → audit row `status=499 client_disconnected`, abort handler. **Never** keep a goroutine blocked on a slow client — DoS surface.
- [ ] **Connection caps.** `http.Server.MaxHeaderBytes = 32 KB`; `http.Server.IdleTimeout = 60s`; `cfg.api_max_concurrent_requests` (default 5000) enforced via a semaphore middleware — overflow returns 503 immediately.

### 9.10 Deployment, mTLS bootstrap, secret rotation

- [ ] **Compose profile.** `docker-compose.yml` gains an `api` service (profile=`default`); depends_on=`{redis, pg, mocksrv}` healthy. mTLS certs mounted from `infra/mock/ca/` in dev; from `data/api/tls/` in prod-like profile. `make api.up` / `make api.down` shortcuts.
- [ ] **K8s manifest stub** (Phase 14 fills detail): the API is replicas:N (default N=2), no leader election, stateless. Liveness probe = `/v1/healthz`, readiness probe = `/v1/readyz`. PDB = `minAvailable=1`.
- [ ] **Secret rotation runbook** (`docs/guides/api_runbook.md`): JWT key (`make api.rotate-jwt-key`), cursor key (`make api.rotate-cursor-key`), bcrypt cost bump (`make api.bump-bcrypt-cost`), mTLS cert (`make api.tls-rotate`), JTI revocation (`make api.revoke-jti JTI=...`). Each is operator-only (no auto-rotate yet — follows the Phase 8 §8.15.4 doctrine: lifecycle is operator-attested in v1).
- [ ] **First-run bootstrap.** `make api.init` creates: (a) JWT keypair `kid_001`; (b) cursor seal key; (c) mTLS bundle if `--with-tls` (defaults true in compose, false on `init` in CI). Idempotent — re-running is a no-op when files exist.

### 9.11 Versioning, deprecation, sunset policy

- [ ] **`/v1` is the public contract.** Breaking changes cut `/v2` — never break `/v1` in place.
- [ ] **Deprecation window** = 90 days minimum (`cfg.api_deprecation_window_days`). Deprecated routes return `Sunset: <RFC 8594 date>` + `Link: </v2/...>; rel="successor-version"` headers; OpenAPI marks them with `x-deprecated-on` / `x-sunset-on`. Past the sunset date → `410 gone` with `Link` to the successor.
- [ ] **Field-level deprecation.** Deprecated response field carries a sibling `<field>_deprecated: true` for one minor version then is removed in the next minor. OpenAPI validator gates.
- [ ] **Schema-version stamping.** Every JSON response carries `meta.schema_version` (tracks `cfg.api_schema_version`, bumps additively per `chart.json` `server` minor). Client SDKs key cache invalidation on this.

### 9.12 Triangle test & cfg knobs (mandatory)

- [ ] **One source of truth.** Every Phase 9 cfg key listed below appears in `ai/common/config.py`, `server/internal/config/config.go`, `ai/common/defaults.yaml`, AND `xops/env/.env.example` with `# shared` marker. `test_config_sync` covers all three sides; Go-side parity asserted by `server/internal/config/sync_test.go`.
- [ ] **Knob inventory (v1):** `api_request_timeout_ms=2500`, `api_consensus_overhead_ms=200`, `api_transit_jitter_ms=100`, `api_request_max_bytes=65536`, `qa_input_max_bytes=4096`, `api_fixture_window_max_days=14`, `api_allowed_markets=[ms,au_2.5,btts,ah_home,modal_score]`, `api_cursor_ttl_s=1800`, `api_idempotency_ttl_s=86400`, `api_idempotency_inflight_wait_ms=1500`, `api_swr_inflight_max=64`, `api_cache_stale_after_s=30`, `api_cache_max_age_s=300`, `api_reply_reaper_s=60`, `api_predict_request_backlog_high=5000`, `api_max_concurrent_requests=5000`, `api_response_write_timeout_ms=5000`, `api_bcrypt_cost=12`, `api_access_ttl_s=900`, `api_refresh_ttl_s=2592000`, `api_refresh_replay_grace_s=30`, `api_revocation_set_max=10000`, `api_jwt_key_poll_s=10`, `api_jwt_retired_grace_s=960`, `api_self_registration_enabled=false`, `api_register_cap_per_subnet_per_h=20`, `api_burst_capacity=60`, `api_burst_refill_per_s=2`, `api_trusted_proxies=""`, `api_log_sample_pct=10`, `api_tier_enforcement_enabled=false`, `api_deprecation_window_days=90`, `api_schema_version=1`, `api_slo_burn_window_s=3600`, `api_slo_burn_threshold=2.0`, `api_time_format="iso8601_utc"`.
- [ ] **Boot validator.** `internal/config/validate.go` enforces: (a) timeout chain inequality; (b) bcrypt cost ≥ 10; (c) `api_request_timeout_ms ≥ 100`; (d) all TLS cert paths exist + readable + not expired (refuse if `notAfter < now + 7d`); (e) JWT keystore non-empty + at least one ACTIVE row.

### 9.13 Definition of Done (binding — mirrors §8.9 density)

- [ ] All `[ ]` items in §9.0–§9.12 ticked.
- [ ] Migrations `012`, `013`, `014` apply idempotently on a fresh PG; `make db.migrate` green.
- [ ] OpenAPI generation: `make api.gen-check` green; every route has `x-rate-cost`, `x-idempotent-mutation` (POST/PATCH only), `x-tier-required` (default `none`).
- [ ] Triangle test (config sync) green for all knobs in §9.12; Go-side `sync_test.go` mirrors Python `test_config_sync.py`.
- [ ] `swarmctl topics` shows `api.request.v1`, `api.response.v1`, `predict.cancel.v1` with the correct producers.
- [ ] `swarmctl ps` shows the API gateway agent shim — see §9.14 boundary tests for why this matters.
- [ ] `make test` green: Python (no regression) + Go (`go test ./server/...` ≥ the proof tests below).
- [ ] `make swarm.demo.live` (per §8.16.13) extended: spin up API → register a test user → login → POST `/v1/qa` → assert end-to-end < 1500ms with real Redis + mock predictors (skip-if-no-Redis).
- [ ] `docs/design/API.md` lands (NEW; binding contract for all Phase 9 surfaces); `docs/guides/api_runbook.md` lands (operator surfaces); both linked from `AGENTS.md` §1.7.

### 9.14 Proof tests (≥ 60 deterministic + 15 adversarial; mirrors §8.16 density)

**Routing & contract (Go, deterministic):**

- [ ] `test_route_table_matches_openapi` — every gin route appears in `openapi.yaml` and vice-versa; cardinality match.
- [ ] `test_endpoint_costs_total` — `sec.CheckTotality` against the gin router; allowFallback=false; empty result.
- [ ] `test_response_problem_json_on_errors` — every 4xx/5xx body is `application/problem+json` with `{type, title, status, detail, request_id}`.
- [ ] `test_pagination_cursor_tampering` — flip every byte position; assert 400 (no panic).
- [ ] `test_pagination_cursor_filter_drift` — mint with `from=A`, fetch next page with `from=B`; 409.
- [ ] `test_pagination_cursor_post_rotation` — rotate seal key; old cursor → 400 graceful.
- [ ] `test_etag_if_none_match_304` — second request with `If-None-Match: <prediction_id>` → 304.
- [ ] `test_request_id_echo_uuidv7` — server-minted ID is UUIDv7 (sortable timestamp prefix); client-supplied accepted as-is.
- [ ] `test_body_size_cap_413` — POST `/v1/qa` with > `qa_input_max_bytes` → 413; assert `MaxBytesReader` short-circuits before handler.

**Identity & sessions:**

- [ ] `test_bcrypt_cost_floor` — boot probe rejects sub-100ms host (mocked clock).
- [ ] `test_jwt_kid_rotation_round_trip` — sign with kid_A, rotate to kid_B, verify pre-rotation token still valid until grace expires.
- [ ] `test_jwt_purge_zeroizes_priv` — post-purge `.priv.pem` is zero-bytes then absent; on-disk forensic test.
- [ ] `test_refresh_single_use_with_grace` — replay within grace returns same access; outside grace → 401 + sec.alert.
- [ ] `test_jti_revocation_immediate` — revoke a live token; subsequent request → 401 within < 50ms (Redis EXISTS path).
- [ ] `test_jti_revocation_set_pressure_alert` — fill revocation set to 80%; assert sec.alert emitted.
- [ ] `test_self_registration_flag_blocks_default` — POST `/v1/auth/register` with default cfg → 403.
- [ ] `test_register_subnet_cap` — 21 registers from same /24 in one hour → 21st returns 429.

**Request flow & RPC:**

- [ ] `test_timeout_chain_validator_refuses_boot` — set `api_request_timeout_ms < consensus_window_ms`; refuse with explicit error.
- [ ] `test_rpc_happy_path_round_trip` — mock predictor publishes `predict.final` ≥ proofreader; API returns 200 with `prediction_id` + `produced_at`.
- [ ] `test_rpc_503_no_cache` — kill the predictor; assert 503 + `Retry-After`.
- [ ] `test_rpc_503_with_cache_serves_cache` — populate `cache.v1`; same kill; assert 200 cache-hit + `X-Cache: hit`.
- [ ] `test_swr_async_fanout_bounded` — flood 200 cache-stale reads; assert at most `api_swr_inflight_max` async `predict.request` published.
- [ ] `test_cancellation_publishes_predict_cancel` — client disconnect mid-RPC; assert `predict.cancel.v1` on bus with same `request_id`.
- [ ] `test_cancellation_post_final_dropped_silently` — cancel arrives after `predict.final`; no alert, no second response.
- [ ] `test_reply_to_topic_per_pod_isolated` — two API pods; their `api.reply.*` streams non-overlapping; reaper sweeps the orphan stream within `api_reply_reaper_s`.
- [ ] `test_predict_approved_only_never_predict_final` — boundary: API consumes `predict.approved.v1` only; assert via the swarmctl visibility helper.

**Idempotency & cache:**

- [ ] `test_idempotency_replay_identical_body_same_response` — bytes-identical.
- [ ] `test_idempotency_drift_409_and_alert` — same key, different body → 409 + sec.alert.
- [ ] `test_idempotency_inflight_blocks_then_returns` — second request blocks on pubsub; first completes; second gets the same response.
- [ ] `test_idempotency_inflight_timeout_425` — first request stalls; second hits `api_idempotency_inflight_wait_ms` → 425.

**Sec gate integration:**

- [ ] `test_sec_input_quarantines_qa_returns_422` — known-bad payload from `injection_patterns.yaml` → 422 `qa_quarantined`.
- [ ] `test_password_field_skips_normalize` — login password preserves leading whitespace through hash compare.
- [ ] `test_xff_spoofed_untrusted_ignored` — `X-Forwarded-For` from non-trusted peer; subject_key derived from peer.
- [ ] `test_subject_key_ipv6_64_collapse` — two IPv6 addresses sharing /64 share one rate bucket.
- [ ] `test_lua_loader_refuses_boot_on_drift` — tamper with `sec_rate_check.lua` header; refuse boot with explicit error.

**Rate limit & quota:**

- [ ] `test_rate_limit_lower_of_jti_and_ip_wins` — saturate IP bucket; jti bucket has room; still 429.
- [ ] `test_denylist_short_circuit_429_no_body` — denylist via Lua mutate; subsequent request 429 with empty body.
- [ ] `test_subnet_mode_on_capped_flag` — set `sec:denylist:capped`; subsequent IP buckets at /24.
- [ ] `test_tier_quota_dormant_by_default` — flag off; cap=NULL; never throttles on tier.
- [ ] `test_tier_quota_active_caps_at_limit` — flag on; cap=10; 11th req in 24h → 429.

**Backpressure:**

- [ ] `test_backpressure_predict_request_backlog_switches_cache_only` — synthesize XLEN > threshold; GET serves cache or 503; POST `/v1/qa` → 425.
- [ ] `test_slow_client_does_not_pin_goroutine` — write blocks > `api_response_write_timeout_ms`; goroutine returns; audit row 499.
- [ ] `test_max_concurrent_semaphore_503` — N+1th request → immediate 503.

**mTLS & migrations:**

- [ ] `test_mtls_boot_probe_refuses_on_failure` — bad CA bundle; boot fails with `tls_handshake_failed`.
- [ ] `test_mtls_cert_expiring_soon_refuses_boot` — cert with `notAfter < now + 7d`; refuse.
- [ ] `test_migrations_idempotent_012_013_014` — apply twice; second is no-op; row counts unchanged.

**Observability:**

- [ ] `test_audit_chain_continuity_across_pods` — two pods write API audit rows concurrently; chain verifies.
- [ ] `test_pii_erase_nullstamps_user_id_h` — erase user; subsequent audit dump shows null in the hashed column.
- [ ] `test_metrics_cardinality_under_cap` — synth 1000 paths through router; cardinality estimator stays under `telemetry_max_series`.
- [ ] `test_route_pattern_not_id_in_label` — request `/v1/matches/abc123/predictions`; metric label is `/v1/matches/:id/predictions`.

**Wire-authority boundary (Phase 3.6 enumerative):**

- [ ] `test_api_gateway_sole_writer_api_request_v1` — registry walk; only producer.
- [ ] `test_api_gateway_sole_writer_api_response_v1` — same.
- [ ] `test_api_gateway_sole_writer_predict_cancel_v1` — same.
- [ ] `test_api_does_not_publish_maint_or_sec` — AST scan + registry walk; API never writes to `maint.*` / `sec.*` / `auth.*` / `payment.*`.
- [ ] `test_api_consumes_predict_approved_not_predict_final` — registry walk.
- [ ] `test_event_correlation_id_dual_emit` — quarantine fired during a request → `sec.alert.v1.event_correlation_id == request_id` (per §8.16.9).

**Adversarial corpus (Phase 12 prerequisite — must be green at Phase 9 close, NEVER xfail):**

- [ ] `adv_test_jwt_alg_none_attack` — token with `"alg":"none"` → 401, no fallback.
- [ ] `adv_test_jwt_kid_path_traversal` — `"kid":"../../etc/passwd"` → 401, no file read.
- [ ] `adv_test_jwt_hs256_with_pubkey_as_secret` — algorithm-confusion attack rejected.
- [ ] `adv_test_jwt_expired_in_grace_clock_skew` — clock-skew tolerance ≤ `cfg.api_jwt_clock_skew_s=30` (new knob); beyond → 401.
- [ ] `adv_test_idempotency_key_collision_user_isolation` — user A and user B use same client key; bodies stay isolated (no cross-user leak).
- [ ] `adv_test_cursor_oracle_attack` — submit malformed cursors at high rate; assert no timing oracle (constant-time AES-GCM verify).
- [ ] `adv_test_qa_prompt_injection_corpus_300` — Phase 12 corpus replayed at the API; assert each catches at sec gate, no leak through to `predict.request`.
- [ ] `adv_test_qa_oversize_413_then_quarantine` — 1MB body → 413; multiple 413s in burst → throttle (cost-aware).
- [ ] `adv_test_register_email_unicode_homoglyph` — `admin@negelir.com` vs `аdmin@negelir.com` (Cyrillic а) — both register without collision; deny-set treats as distinct.
- [ ] `adv_test_password_unicode_norm_bypass` — composed vs decomposed Turkish password → bcrypt sees identical input (NFC pre-bcrypt only on registration; login uses raw — this is a deliberate one-way to avoid false-rejects on normalization drift; documented).
- [ ] `adv_test_idempotency_inflight_double_submit_no_double_charge` — two parallel POSTs → exactly one `predict.request` published, both clients see the same response.
- [ ] `adv_test_swr_thundering_herd` — 1000 stale-cache reads land at t=0; assert exactly 1 backend RPC fires.
- [ ] `adv_test_cancellation_race_after_final` — cancel arriving 0..50ms after `predict.final`; assert NO duplicate response sent and NO panic.
- [ ] `adv_test_open_redirect_in_oidc_callback` — `redirect_uri` parameter not in allow-list → 400 (even though provider is noop, the parameter validator runs).
- [ ] `adv_test_log_field_no_pii` — synthetic request with email/IP in body; assert structured log carries `user_id_h`/`anon_subject_key` only, never the raw values.

### 9.15 Forward-phase contracts (do NOT break later phases)

- [ ] **Phase 10 (NLP).** `/v1/qa` request body `{q, locale}` is closed for v1; Phase 10 humanizer adds `humanize: bool` (default false) — additive minor bump. The qa handler MUST stamp `qa_correlation_id` (per §8.16.12) on every spawned `predict.request.v1`; boundary test guards.
- [ ] **Phase 11 (compute).** API container is `cfg.compute_class=cpu_only`; cgo build tags exclude CUDA. Boundary: `cmd/api/main.go` build-tagged `//go:build cpu_only`.
- [ ] **Phase 12 (chaos).** New chaos catalogue stubs land alongside §9.13: `chaos-api-redis-flap` (assert 503 not 5xx panic), `chaos-api-pg-drop` (assert health degrades gracefully — readyz turns red, livez stays green), `chaos-api-bus-flood` (assert backpressure mode engages), `chaos-api-jwt-key-purge-mid-request` (assert in-flight requests with retired kid still complete), `chaos-api-half-replica-kill` (assert N-1 replicas continue serving + reply-stream reaper sweeps orphans).
- [ ] **Phase 13a (catalog).** `profile_id = league_id` resolution lives in ONE function `internal/api/profile.go::ResolveProfileID(leagueID)`; Phase 13a swap to catalog-driven changes the body of this one function with no handler diff. Boundary test: every place a profile_id is stamped on a bus envelope routes through this function (AST scan).
- [ ] **Phase 14 (K8s).** API replicas:N proven at chaos N=3; `consensus.v1` MUST stay replicas:1 (per §5.3 single-publication guarantee). Phase 9 readyz probe explicitly tolerates `consensus.v1` not being co-located.
- [ ] **Phase 16 (Emitter).** API reads through `CalibrationStore` Protocol (per §5 forward block); swapping the in-memory backend for the Phase 16 feed-plane backend changes 0 handler lines. Boundary test: `internal/handlers/predictions.go` imports the Protocol interface, never the concrete impl.
- [ ] **Phase 19 (GA).** SLO burn-rate alerts (§9.8) drive the GA gate. `make api.slo-report` produces a 28-day rolling SLO summary; GA blocks if availability < 99.5% or p95 outside budget.
- [ ] **Phase 20 (monetization).** Tier enforcement is dormant flag-only at this phase; `tier_quota.go` middleware ships unloaded behind `cfg.api_tier_enforcement_enabled=false`. Phase 20 flips the flag, lands the `tiers` catalog rows, and adds Stripe webhooks at `/v1/billing/*` (NEW routes — do NOT pre-expose). Boundary: no `/v1/billing/*` route exists in v1.

### 9.16 Versioning addendum

- [ ] `server` minor bump on first `/v1` route landing; subsequent routes bump patch.
- [ ] `xops` patch for `make api.{init,gen,gen-check,docs,up,down,rotate-jwt-key,rotate-cursor-key,bump-bcrypt-cost,tls-rotate,revoke-jti,erase-user,slo-report}`.
- [ ] `docs` minor for NEW `docs/design/API.md` + NEW `docs/guides/api_runbook.md`; AGENTS.md §1.7 anchor list updated.
- [ ] `compatibility` block (§8.16.15): `server.min_compatible_with.swarm = "<predict.request producer floor>"`, `.ai = "<consensus + proofreader floor>"`. `make version.compatibility-check` green.

### 9.17 Performance hardening & resilience patterns (binding)

> **Why this section exists.** §9.1–§9.16 specify *what* the API does. §9.17
> specifies *how fast* and *how robustly* it does it. Every item here is
> a binding contract — if a code change regresses any of them, CI must
> fail. The targets below are p95/p99 wall-clock on a 2-vCPU/4-GiB
> container under `cfg.api_max_concurrent_requests` load, measured by
> `make api.bench` (k6 driver, NEW; lands with this section).

#### 9.17.1 Go runtime tuning (refuse-to-start gates)

- [ ] **`GOMAXPROCS` from cgroup.** Import `go.uber.org/automaxprocs` (single tiny dep, no transitive). Boot log line `runtime.gomaxprocs=<N> source=cgroup|env|default`. **Boundary test:** `runtime.GOMAXPROCS(0)` ≤ container CPU quota — refuse boot when over (prevents the 64-core scheduler thrash on a 2-vCPU pod).
- [ ] **`GOMEMLIMIT` mandatory.** `cfg.api_go_mem_limit_mib` (default 80% of cgroup `memory.max` resolved at boot via `xops/api/cgroup_probe.go`). Set via `debug.SetMemoryLimit(bytes)`. Refuse boot if cgroup limit unreadable AND `cfg.api_go_mem_limit_mib=0` (forbids unbounded heap).
- [ ] **`GOGC` tuned, not default.** `cfg.api_go_gc_percent=50` (default 100 is too lazy under our allocation pattern — JSON encode + Redis pipeline). `debug.SetGCPercent(cfg)`. **Proof:** `test_gc_pause_p99_under_5ms` runs the bench corpus and asserts `runtime/metrics` `/gc/pauses:seconds` p99 ≤ 5ms.
- [ ] **No `init()`-time allocation > 1 MiB.** AST scan rejects `make([]T, > 1<<20)` and `bytes.Repeat(..., > 1<<20)` outside `_test.go`. Heap baseline at first request must be < 32 MiB on a no-traffic pod (boot probe asserts via `runtime.ReadMemStats`).
- [ ] **`net/http` server defaults overridden** (Go defaults are wrong for public APIs):
  - `ReadHeaderTimeout = cfg.api_read_header_timeout_ms` (default 5s) — Slowloris defense.
  - `ReadTimeout = cfg.api_read_timeout_ms` (default 10s).
  - `WriteTimeout = cfg.api_write_timeout_ms` (default 15s — must exceed `api_request_timeout_ms` + `api_response_write_timeout_ms`; boot validator enforces).
  - `IdleTimeout = cfg.api_idle_timeout_ms` (default 60s).
  - `MaxHeaderBytes = 32 << 10`.
  - `H2C` enabled via `golang.org/x/net/http2/h2c` for in-mesh gRPC-over-HTTP/2 future-compat (does NOT enable HTTP/2 cleartext on the public listener — only on the in-cluster sidecar listener, behind mTLS).

#### 9.17.2 Hot-path zero-allocation discipline

- [ ] **Response writer pooling.** `internal/api/respond/pool.go` — `sync.Pool` for `*bytes.Buffer` (returned with `Cap() ≤ 64 KiB`; oversize buffers are dropped not pooled — prevents pinning 1 MiB buffers from one giant QA reply). Every JSON response goes through `respond.JSON(w, status, payload)` which acquires from pool, encodes via a pooled `*json.Encoder` with `SetEscapeHTML(false)`, writes, returns. **Proof:** `test_respond_zero_alloc` uses `testing.AllocsPerRun` to assert ≤ 4 allocs per JSON response on the cache-hit path.
- [ ] **Header allocation discipline.** Headers set via `w.Header().Set(...)` only on values whose key/value are pre-canonicalized at compile time (constants in `internal/api/headers/keys.go`). No `fmt.Sprintf` in the response-write hot path (lint rule).
- [ ] **String concatenation in hot path.** Every `+` on strings inside the request handler is an `strings.Builder` or a `strconv.AppendInt(buf, ...)` instead. Lint rule: `staticcheck -checks SA6005,SA1019` + custom `xops/lint/no_hot_concat.py` AST scan over `internal/api/handlers/`.
- [ ] **JSON decoder reuse for request bodies.** `decoder := json.NewDecoder(io.LimitReader(r.Body, cfg.api_request_max_bytes)); decoder.DisallowUnknownFields()`. **Boundary:** `DisallowUnknownFields()` MUST be on for every POST/PATCH handler (defense-in-depth alongside OpenAPI schema validator); AST scan asserts.
- [ ] **`io.Copy` with pre-sized buffer.** Where the response body is streamed (not envisioned for v1 but reserved for `/v1/leagues/.../export.csv` future), `io.CopyBuffer` with a 32 KiB pooled buffer; never `io.Copy` (allocates 32 KiB per call).

#### 9.17.3 Connection pool sizing (Postgres, Redis, bus)

- [ ] **PostgreSQL via `pgxpool`** (NOT `database/sql` — pgx is faster + binary protocol + COPY support).
  - `cfg.api_pg_pool_max_conns` = `min(cgroup_cpu * 4, pg_max_connections * 0.25 / replicas)`; default = 25 per pod, formula validated at boot — refuse if it would push the cluster past 80% of `pg_max_connections`.
  - `MaxConnIdleTime = 5m`, `MaxConnLifetime = 1h`, `MaxConnLifetimeJitter = 5m` (avoids thundering-herd reconnect at the hour mark).
  - `HealthCheckPeriod = 30s`. `BeforeConnect` sets `application_name = "negelir-api/<pod_instance_id>"` (so DBA can attribute load).
  - `statement_cache_capacity = 256` per conn (named-prepared statements for hot queries — `users SELECT BY email_lower`, `match_normalized SELECT BY id`, audit INSERT).
  - **Read replica routing** (built but dormant — `cfg.api_pg_replica_url=""` default): when set, GETs route to replica; POSTs/PATCHes always primary. Replica lag check via `pg_last_wal_replay_lsn` every `cfg.api_pg_replica_lag_check_s=10`; lag > `cfg.api_pg_replica_lag_max_ms=500` falls back to primary + emits `sec.alert.v1{kind=pg_replica_lag_high}`.
- [ ] **Redis via `go-redis/v9`** with two distinct clients (don't share — different SLOs):
  - `cacheClient`: `PoolSize = cfg.api_redis_cache_pool_size` (default 50), `MinIdleConns = 10`, `PoolTimeout = 100ms` (fail fast — fall through to MISS).
  - `busClient` (for XREAD reply streams): `PoolSize = cfg.api_redis_bus_pool_size` (default 20), `ReadTimeout = api_request_timeout_ms + 500ms` (XREAD BLOCK budget).
  - `MaxRetries = 0` on both — retries belong in the resilience layer (§9.17.4), not silently in the driver.
  - **Pipelining** for batched audit writes (§9.17.7).
- [ ] **No connection pool per request.** Lint rule: `pgx.Connect`/`redis.NewClient` called outside `internal/bootstrap/` is a build error.

#### 9.17.4 Resilience: circuit breakers, bulkheads, hedging, retry budgets

- [ ] **Circuit breaker per upstream** (`pg`, `redis_cache`, `redis_bus`, `swarm_rpc`). Implementation: `sony/gobreaker` (one tiny dep). States: `closed → open → half-open`. Trip on `cfg.api_breaker_fail_ratio=0.5` over `cfg.api_breaker_window_s=10` window with `cfg.api_breaker_min_requests=20`. Open duration `cfg.api_breaker_open_s=15`; half-open admits 1 probe. **Open state behavior:** PG-open → 503 `service_unavailable` for endpoints that need PG; cache-open → bypass cache (fall through to RPC); bus-open → 503 `bus_unreachable`. **Per-breaker `sec.alert.v1`** kinds: `breaker_opened`, `breaker_half_open`, `breaker_closed` (severity=warn, debounced 60s).
- [ ] **Bulkhead per upstream.** Bounded semaphore (`golang.org/x/sync/semaphore`) sized to `pool_size * 0.8` — last 20% of pool reserved for `/v1/healthz` + `/v1/readyz` so a saturated app surface never starves liveness. **Proof:** `test_bulkhead_protects_healthz` saturates PG bulkhead; `/v1/healthz` still responds < 50ms.
- [ ] **Hedged RPC for cache-miss reads** (defeats long-tail latency). For GET `/v1/matches/:id/predictions` cache-MISS: publish primary `predict.request` at t=0; if no reply by `cfg.api_hedge_after_ms=200` AND `cfg.api_hedging_enabled=true` AND p99 of recent RPC latency > p50 × 3, publish a HEDGE `predict.request` with `request_id_hedge=<original>:h1`. First reply wins; both are dedup'd at the `consensus.v1` ledger via existing idempotency on `request_id` (the `:h1` suffix is stripped before the consensus dedup key — design: hedge is request-level, not consensus-level). **Hedge budget:** `cfg.api_hedge_budget_pct=10` of recent total RPC count; never hedge more than 10% of traffic. **Proof:** `test_hedge_budget_capped` floods misses; assert hedge count ≤ 10%.
- [ ] **Singleflight for cache-MISS** (different from §9.3 SWR — that's stale-revalidate). `golang.org/x/sync/singleflight` keyed on `(match_id, market_set, calibration_version)`. 1000 concurrent cache-MISS requests for the same key fan out to ONE `predict.request` and all wait on the same RPC. **Proof:** `test_singleflight_collapses_cache_miss_herd` — 500 parallel MISS for same match → exactly 1 `predict.request` published.
- [ ] **Retry budget (token bucket per upstream).** Naive retry-on-failure amplifies outages. Token bucket: `cfg.api_retry_budget_per_s=10` tokens/s + `cfg.api_retry_budget_capacity=50` burst per upstream. Out-of-budget retries are FAILED IMMEDIATELY (no extra latency, no extra load). **Proof:** `test_retry_budget_prevents_amplification` — sustained upstream failure; retry rate caps at budget.
- [ ] **Deadline propagation.** Every outbound call (`pg`, `redis`, `bus`) takes `ctx` derived from `r.Context()` with `context.WithTimeout(ctx, remaining_budget)`. Remaining budget = `request_deadline - now() - jitter_safety(50ms)`. **Boundary:** AST scan rejects `context.Background()` / `context.TODO()` in `internal/api/handlers/`.
- [ ] **Panic recovery middleware.** Top-of-stack `defer recover()` — emits `sec.alert.v1{kind=api_panic, severity=critical}` with stack-trace SHA256 (NOT the trace itself; trace goes to local stderr only — PII risk in handler args), then `500 internal`. **Proof:** `test_panic_recovery_emits_alert_and_500` — handler panics; client sees 500; alert fires; pod stays up.
- [ ] **Graceful shutdown.** SIGTERM → stop accepting new conns (`server.Shutdown(ctx)` with `cfg.api_shutdown_grace_s=30`) → drain in-flight (semaphore wait) → close PG pool → close Redis pool → publish final `api.response.v1` rows for in-flight → exit 0. K8s `preStop` hook = `sleep 5` to bridge endpoint-removal lag. **Proof:** `test_graceful_shutdown_drains_inflight` — start 10 long-running requests; SIGTERM; all complete with 200; new requests during drain get 503 + `Connection: close`.

#### 9.17.5 Per-endpoint latency budgets (binding SLO floors — tighter than §9.8)

| Route | p50 | p95 | p99 | Notes |
|---|---|---|---|---|
| `GET /v1/healthz` | ≤ 1ms | ≤ 5ms | ≤ 10ms | No I/O; reserved bulkhead. |
| `GET /v1/readyz` | ≤ 10ms | ≤ 50ms | ≤ 100ms | PG/Redis/bus 1-byte pings, parallel. |
| `GET /v1/version` | ≤ 1ms | ≤ 5ms | ≤ 10ms | In-memory chart snapshot. |
| `GET /v1/leagues` | ≤ 5ms | ≤ 25ms | ≤ 50ms | Cache-hit path. |
| `GET /v1/matches/:id` | ≤ 5ms | ≤ 25ms | ≤ 50ms | Cache-hit path. |
| `GET /v1/matches/:id/predictions` (cache hit) | ≤ 5ms | ≤ 25ms | ≤ 50ms | — |
| `GET /v1/matches/:id/predictions` (cache miss) | ≤ 200ms | ≤ 800ms | ≤ 2000ms | RPC path; hedge active. |
| `POST /v1/auth/login` | ≤ 250ms | ≤ 350ms | ≤ 500ms | bcrypt-bound (cost=12 ≈ 250ms). |
| `POST /v1/auth/refresh` | ≤ 5ms | ≤ 20ms | ≤ 50ms | Redis lookup + JWT sign. |
| `POST /v1/qa` (cache hit) | ≤ 10ms | ≤ 50ms | ≤ 100ms | — |
| `POST /v1/qa` (single RPC) | ≤ 250ms | ≤ 800ms | ≤ 2000ms | — |
| `POST /v1/qa` (multi-RPC, 202 path) | ≤ 50ms | ≤ 100ms | ≤ 200ms | Returns immediately with `qa_correlation_id`. |

- [ ] **`make api.bench`** (NEW; xops patch): k6 driver hits each endpoint at `cfg.api_bench_target_rps` (default 200 RPS) for 60s against the compose stack with mock predictors. Asserts every row above. CI gate: bench job runs nightly + on PRs touching `server/internal/api/**`.
- [ ] **Latency histogram per route** in `api_request_duration_seconds_bucket{route, method}` with buckets `[1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 200ms, 500ms, 1s, 2.5s]` — sized for the table above (default Prometheus buckets are `[5ms..10s]` which crushes resolution at our scale).

#### 9.17.6 Caching layers (in-memory L0 ahead of Redis L1)

- [ ] **In-process LRU L0** (`hashicorp/golang-lru/v2`) for the hottest keys per pod. Sized: `cfg.api_l0_cache_max_entries=10000`, eviction on entry count + `cfg.api_l0_cache_max_bytes=64 << 20` (64 MiB cap). TTL per entry = `min(cache.v1 TTL, cfg.api_l0_max_ttl_s=5)` — short TTL so cache invalidation only needs to reach Redis, not every pod.
- [ ] **Negative cache.** 404s on `/v1/matches/:id` cached in L0 for `cfg.api_negative_cache_s=10` to absorb scrape bots probing random IDs. Scope: only 404 + 410; never 5xx (would mask transient outages).
- [ ] **Cache stampede protection beyond singleflight.** When L0 entry expires, only one goroutine fetches; others wait on a per-key `sync.Cond` (max wait = `cfg.api_l0_refresh_max_wait_ms=200` then fall through to direct fetch — bounded queue depth).
- [ ] **L0 invalidation respects `cache:<key>:gen`.** Background goroutine per pod subscribes to Redis keyspace notifications (`__keyevent@0__:set` on `cache:*:gen`) and evicts matching L0 entries within `cfg.api_l0_invalidation_lag_max_ms=500`. Fallback: every L0 read also checks the gen counter (extra Redis round-trip on hit, cheap pipeline). **Proof:** `test_l0_invalidation_within_500ms` — write to `cache:X:gen`; assert L0 eviction within budget.

#### 9.17.7 Audit pipeline performance

- [ ] **`api.request.v1` + `api.response.v1`** writes are the hottest publish path. Batched via Redis pipeline — `cfg.api_audit_batch_max=64` rows or `cfg.api_audit_batch_max_ms=10ms`, whichever first. Boundary: batching MUST NOT delay the response — audit publish is on a separate goroutine fed by a bounded channel `cfg.api_audit_chan_cap=4096`. **Channel-full policy:** drop the audit row + emit `sec.alert.v1{kind=api_audit_dropped, severity=warn}` (debounced 60s). **NEVER** block the response on audit (audit is fan-out, not gating).
- [ ] **Audit shipper backpressure.** When the channel is > 80% full for > 5s, switch to sampling at `cfg.api_audit_sample_pct_under_pressure=10%` for 2xx; **always 100% for 4xx/5xx + sec-relevant events** (login attempts, revocations). Restore 100% when channel < 50% for 30s.
- [ ] **`audit_log_integrity_break` recovery.** If hash-chain verifier (§8.13.2) detects a break in the API audit chain, API switches to **chain-rewrite-quarantine** mode: subsequent rows append to `api_audit_log_quarantine` partition until operator runs `make audit.repair-api`. Reads / writes to the public surface are **NOT blocked** — audit integrity is not a request-path dependency.

#### 9.17.8 TLS / TCP performance

- [ ] **TLS session resumption.** `tls.Config.ClientSessionCache = tls.NewLRUClientSessionCache(1024)` for outbound mTLS (PG, Redis, bus). Inbound: `SessionTicketKey` rotated every 24h via `make api.rotate-tls-session-key` (separate from cert rotation; cert rotation triggers session cache flush implicitly).
- [ ] **TLS cipher suite pin.** Server only accepts TLS 1.3 + TLS 1.2 with the AEAD ciphers (`TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`, `TLS_ECDHE_*_GCM_*`). Boot validator pins via `tls.Config.MinVersion = tls.VersionTLS12 + CipherSuites = [...]`.
- [ ] **TCP_NODELAY enabled** on the listener (Go default for HTTP servers, but assert via `SO_KEEPALIVE` probe + `TCP_USER_TIMEOUT` set to `cfg.api_tcp_user_timeout_ms=20000`).
- [ ] **`SO_REUSEPORT` on Linux** (via `socketreuse` package or raw `syscall.Setsockopt`) — multiple acceptor goroutines, one per `GOMAXPROCS`. Boundary: asserted at boot via `lsof -i :<port>` parity test in dev (`make api.up && make api.assert-reuseport`).
- [ ] **HTTP/2 enabled on inbound** (default in `net/http` w/ TLS; explicitly assert at boot — no `H2_DISABLED` accidental disablement).

#### 9.17.9 Backpressure feedback loops (closed-loop, not open-loop)

- [ ] **PID-style adaptive rate limiter** on top of §9.7 fixed buckets. When `api_requests_total{status=~"5.."}` rate exceeds `cfg.api_adaptive_error_rate_threshold=0.02` over 30s, the adaptive controller multiplies all subject-key bucket refill rates by `cfg.api_adaptive_shed_factor=0.5` for `cfg.api_adaptive_shed_duration_s=60`. Restored gradually (`* 1.1` per 10s) once error rate drops below threshold. **Proof:** `test_adaptive_shed_engages_on_error_burst` — synthesize 5xx burst; assert refill rate halved within 30s.
- [ ] **Inflight-aware shedding.** When `api_inflight_rpcs / api_max_concurrent_requests > 0.85` for > 5s, return 503 IMMEDIATELY for new requests with `tier_id < cfg.api_priority_tier_floor` (dormant — defaults to 0, all requests equal until §20). Headers: `X-Shed-Reason: inflight_pressure`, `Retry-After: 5`.
- [ ] **Bus-feedback signal.** Subscribe to `maint.event.v1{kind=scaler_replicas_pinned}` (§8.x scaler emits when pinning above target due to lag). When fired, API enters degraded-mode banner — sets `X-Degraded-Cluster: true` on every response, encourages clients to widen their own retry intervals.

#### 9.17.10 Observability for performance

- [ ] **`pprof` endpoint on the metrics port** (`:9091/debug/pprof/*`) — never on the public listener. Authenticated via cluster-internal mTLS only; `cfg.api_pprof_enabled=true` default in dev, `false` in prod (operator opts in for live debugging via `make api.pprof-enable POD=...` which short-lives a flag in Redis `api:pprof:<pod>` TTL 1h).
- [ ] **Continuous CPU profiling sample.** 10-second profile every 10 minutes shipped to `data/api/profiles/<pod>/<utc>.pprof.gz` (rotated, max 7d). Operator inspects via `make api.profile-show LATEST`. Cost: < 1% CPU overhead.
- [ ] **Allocation tracking gauge.** `api_alloc_per_request_bytes` histogram (computed from `runtime.MemStats.Mallocs` delta around `ServeHTTP` — sampled at `cfg.api_alloc_sample_rate=0.001`; 1 in 1000 requests). Regression alert: p99 > 50 KiB → `sec.alert.v1{kind=api_alloc_regression, severity=warn}`.

#### 9.17.11 Definition of Done additions (binding, on top of §9.13)

- [ ] All `[ ]` items in §9.17.1–§9.17.10 ticked.
- [ ] `make api.bench` green on every PR touching `server/internal/api/**` or `server/internal/handlers/**`.
- [ ] `runtime/metrics` GC pause p99 ≤ 5ms under bench load.
- [ ] All breakers + bulkheads have a documented runbook entry in `docs/guides/api_runbook.md` (which states to do when each fires).
- [ ] `test_l0_invalidation_within_500ms`, `test_singleflight_collapses_cache_miss_herd`, `test_hedge_budget_capped`, `test_bulkhead_protects_healthz`, `test_panic_recovery_emits_alert_and_500`, `test_graceful_shutdown_drains_inflight`, `test_retry_budget_prevents_amplification`, `test_adaptive_shed_engages_on_error_burst`, `test_respond_zero_alloc`, `test_gc_pause_p99_under_5ms` — all green.
- [ ] Triangle test extends to ~30 new cfg knobs introduced by §9.17 (Python config side adds them as documented mirrors even though the code path is Go-only — keeps the single-source doctrine intact).
- [ ] `chart.json` `compatibility` block updated with min versions of `gobreaker`, `automaxprocs`, `golang-lru/v2`, `pgx/v5`, `go-redis/v9`, `golang.org/x/sync` pinned (no `*-latest`; per CLAUDE.md doctrine).

#### 9.17.12 Knob inventory addendum (extends §9.12)

`api_go_mem_limit_mib=0` (0 = derive from cgroup), `api_go_gc_percent=50`, `api_read_header_timeout_ms=5000`, `api_read_timeout_ms=10000`, `api_write_timeout_ms=15000`, `api_idle_timeout_ms=60000`, `api_pg_pool_max_conns=25`, `api_pg_replica_url=""`, `api_pg_replica_lag_check_s=10`, `api_pg_replica_lag_max_ms=500`, `api_redis_cache_pool_size=50`, `api_redis_bus_pool_size=20`, `api_breaker_fail_ratio=0.5`, `api_breaker_window_s=10`, `api_breaker_min_requests=20`, `api_breaker_open_s=15`, `api_hedge_after_ms=200`, `api_hedging_enabled=true`, `api_hedge_budget_pct=10`, `api_retry_budget_per_s=10`, `api_retry_budget_capacity=50`, `api_shutdown_grace_s=30`, `api_l0_cache_max_entries=10000`, `api_l0_cache_max_bytes=67108864`, `api_l0_max_ttl_s=5`, `api_negative_cache_s=10`, `api_l0_refresh_max_wait_ms=200`, `api_l0_invalidation_lag_max_ms=500`, `api_audit_batch_max=64`, `api_audit_batch_max_ms=10`, `api_audit_chan_cap=4096`, `api_audit_sample_pct_under_pressure=10`, `api_tcp_user_timeout_ms=20000`, `api_adaptive_error_rate_threshold=0.02`, `api_adaptive_shed_factor=0.5`, `api_adaptive_shed_duration_s=60`, `api_priority_tier_floor=0`, `api_pprof_enabled_dev=true`, `api_pprof_enabled_prod=false`, `api_alloc_sample_rate=0.001`, `api_jwt_clock_skew_s=30`, `api_bench_target_rps=200`.

#### 9.17.13 New `sec.alert.v1` kinds (open-enum; mirrors §7.4 doctrine)

`breaker_opened`, `breaker_half_open`, `breaker_closed`, `pg_replica_lag_high`, `api_panic`, `api_audit_dropped`, `api_alloc_regression`, `api_adaptive_shed_engaged`, `api_adaptive_shed_lifted`, `api_inflight_pressure_shed`, `api_l0_invalidation_lag`, `api_hedge_budget_exhausted`. Each carries `event_correlation_id` per §8.16.9; producer set bounded to `api.gateway.v1`.

---

## 🇹🇷 Phase 10 — Turkish-First NLP Layer

**Goal:** Turn messy Turkish user input into structured intents + entities, dispatch to predictors / data agents, and emit Turkish-fluent, **proofread**, **calibration-aware**, **citation-bearing**, **PII-clean** answers — with deterministic templates as the floor and a tightly-fenced ≤ 1 B humanizer LLM as opt-in polish (never as a decision-maker).
**Depends on:** Phase 5 (predict.approved / consensus + degraded flag), Phase 6 (proofreader gate), Phase 7 (sec.input.v1 / qa.request.v1 cross-language schema + dedup window), Phase 9 (API gateway timeout chain inequality, JWT identity, audit pipeline, RFC 7807 error shape, hedge/cancel topics), Phase 13a (LeagueCatalog + canonical names + lexicon source-of-truth).
**Anchor doc:** [`design/TURKISH_NLP.md`](../design/TURKISH_NLP.md) (rewritten in lockstep with this phase).

### 10.0 Forward-phase alignment & doctrine

- [ ] **Wire authority (Phase 3 §3.5 additions).** Phase 10 lands four new topics:
  - `qa.intent.v1` (data) — published by `nlp.intent.v1` after sec-pass + normalize + classify; consumer = `nlp.dispatcher.v1`. Schema at `ai/swarm/sdk/schemas/qa.intent.v1.json` (`additionalProperties:false`).
  - `qa.answer.v1` (data) — published by `nlp.answer.v1` (or `nlp.proofreader.v1` post-block); consumer = API gateway response stream + `cache.v1` + `telemetry.v1`. Schema at `ai/swarm/sdk/schemas/qa.answer.v1.json`.
  - `nlp.event.v1` (control, kind-discriminated per §8.16.2 doctrine) — kinds: `lexicon_reloaded`, `lexicon_unreadable`, `humanizer_disabled`, `humanizer_breaker_open`, `proofreader_blocked`, `pii_in_answer_redacted`, `intent_classifier_degraded`, `dictionary_overflow`, `slot_resolution_failed`, `did_you_mean_offered`. Producer set bounded to `nlp.intent.v1`, `nlp.answer.v1`, `nlp.proofreader.v1`. Consumer = `telemetry.v1` + (operator console at Phase 8).
  - `nlp.alert.v1` (data) — narrow alert channel for NLP-class events that need operator visibility WITHOUT widening the §7.4 `sec.alert.v1` producer-set (which is bounded to `sec.*` + `maint.*`). Severity ∈ {info,warn,error,critical}; debounced via `swarm.sdk.AlertDebouncer` mirroring `SecAlertDebouncer`.
- [ ] **Boundary discipline (binding, AST-asserted in §10.20).**
  - NLP **never** subscribes to raw `qa.request` (control-plane). Only `qa.request.v1` (sanitized data-plane). Mirrors §7.5 doctrine.
  - NLP **never** subscribes to `predict.final` (Phase 5 candidate). Only `predict.approved.v1` (Phase 6 gated) — closes the "user got an unproofread prediction" hole.
  - NLP **never** publishes to `sec.*`, `maint.*`, `auth.*`, `payment.*`, `patcher.*`. Outbound topics are exactly `{qa.intent.v1, qa.answer.v1, nlp.event.v1, nlp.alert.v1, predict.request.v1, data.request.v1}`. Boundary test enforces (registry-walk, mirrors `test_boundary_discipline.py::test_sec_alert_v1_producer_set_*`).
  - NLP **never** writes to Postgres directly. Reads canonical lexicons via Phase 16 emitter feeds; reads predictions via consensus consumer; reads facts via `data.request.v1` → Phase 4 storage agent. Single-source doctrine intact.
- [ ] **Cross-phase contracts.**
  - Phase 7 `qa.request.v1` dedup window (`cfg.qa_request_v1_dedup_window_s`) is the lower bound for `cfg.nlp_request_dedup_window_s` (refuse-boot inequality validator: `nlp_request_dedup_window_s ≥ qa_request_v1_dedup_window_s + 30`).
  - Phase 9 timeout chain inequality extends to: `api_request_timeout_ms ≥ nlp_pipeline_timeout_ms + nlp_dispatch_overhead_ms`, and `nlp_pipeline_timeout_ms ≥ consensus_window_ms + nlp_consensus_overhead_ms + (humanizer_max_latency_ms IF cfg.nlp_humanize)`. Boot validator (Phase 9 §9.17.4 deadline-propagation guard) refuses start on violation.
  - Phase 5 `predict.approved.v1{degraded:true, degraded_reason}` MUST be carried through to `qa.answer.v1{degraded:true, degraded_reason}` — never silently dropped (else operators believe NLP is the source of an off-call). Boundary test enforces.
  - Phase 13a LeagueCatalog is the **sole** source for canonical team / player / league / competition names. NLP lexicons are **derivatives** (alias → canonical) generated by `make nlp.lexicon-build` from `ai/common/league_catalog.yaml` + per-league preset modules; lexicons checked in but `make verify.nlp-lexicons` AST-asserts no canonical name diverges from catalog.
  - Phase 11 device probe carries the humanizer LLM under the `nlp.humanizer.v1` agent class with `predictor_max_vram_mb`-equivalent `nlp_humanizer_max_vram_mb=2048` AND `cpu_only` parity test (Δ output character distribution ≤ ε for greedy decoding seed=1337) — required because the humanizer can be the only LLM in the stack on a CPU-only laptop.
  - Phase 12 chaos catalogue gains: `chaos.kill-humanizer`, `chaos.lexicon-corrupt`, `chaos.intent-classifier-flap`, `chaos.predict-approved-degraded-flood`. Each must surface in `qa.answer.v1` as a documented degraded-mode response, never as a 5xx to the user (graceful degradation per §10.10).
  - Phase 14 K8s: `nlp.humanizer.v1` is `replicas:N` BUT must hold a per-pod GPU lease (Phase 11 §11.2 round-robin scheduler) — refuses to start if lease unattainable AND `cfg.nlp_humanize=true` (cleanly degrades to template-only mode, emits `nlp.event.v1{kind=humanizer_disabled, reason=no_device}`).
  - Phase 16 Emitter: `LexiconStore` Protocol (in-memory → Postgres → Feed) so the NLP code never changes across the 3 backends; mirrors §5 `CalibrationStore` pattern.
  - Phase 19 (deferred-tail leagues): adding a T3 league only adds lexicon rows; NLP code does not change. Boundary test (`test_nlp_no_per_league_branch`) AST-rejects `if league_id == ...` anywhere under `ai/swarm/agents/nlp/`.
  - Phase 20 monetization: `qa.answer.v1` carries `tier_id_required` (computed from intent class via `cfg.nlp_intent_tier_map`), API gateway honors it; NLP itself is **tier-blind** (single-source doctrine — entitlement decisions live in Phase 9 middleware, NLP just labels).

### 10.1 Input normalization (deterministic, ordered, idempotent)

- [ ] **Binding step list** (any reordering breaks downstream tests):
  1. Length cap (re-asserted from §7.6 — defense in depth; rejects oversize that escaped sec.input.v1 due to schema drift). Hard cap = `cfg.nlp_input_max_codepoints` (default 512; sec gate `cfg.sec_input_max_len` is bytes-cap floor).
  2. NFC normalize.
  3. Control-char + zero-width + RTL-override strip (mirrors `sanitize_text` from `ai/swarm/agents/sec/input.py`; deduplicated via shared helper `ai/common/text/normalize.py::canonical_normalize` to prevent Python/Go drift). The Go gateway sanitizer (`server/internal/sec/sanitize.go`) is the byte-for-byte reference — `test_nlp_sanitize_matches_go_reference` runs the same 200-payload corpus through both and asserts byte-equality.
  4. Turkish-aware lowercase (I→ı, İ→i; codepoint-explicit table; NEVER `str.lower()`). Reuses `ai/common/text/turkish.py::lowercase_tr`.
  5. Punctuation normalization (curly quotes → straight; em-dash → hyphen-space-hyphen; multiple spaces collapse).
  6. Diacritic restoration (table-driven, see §10.3). Bounded edit cost.
  7. Tokenization (whitespace + punctuation split + Turkish suffix-aware tokenizer rules from `zemberek-python`; vendored snapshot pinned in `ai/nlp/vendor/zemberek_rules.json`, version-stamped).
  8. Token-level typo correction (see §10.3). Bounded budget.
- [ ] **Idempotency guarantee.** `normalize(normalize(x)) == normalize(x)` — property-tested with `hypothesis` (≥ 1000 examples; seed-pinned).
- [ ] **Determinism guarantee.** Same input → byte-identical output across 1000 runs across CPython 3.11/3.12 (Python `hash()` randomization MUST NOT enter the path; AST guard `test_nlp_no_set_iteration_in_normalize` rejects iteration over `set()` / `dict.keys()` without explicit `sorted(...)`).
- [ ] **Bounded latency.** p95 ≤ 5 ms on `cfg.nlp_input_max_codepoints` cap (CI gate via `make nlp.bench`).

### 10.2 Lexicon system (versioned, hot-reloadable, integrity-checked)

- [ ] **Layout.** `ai/nlp/lexicon/`:
  - `teams.tr.yaml` — `{canonical_id: <league_catalog_team_id>, names: [...], aliases: [...]}`
  - `players.tr.yaml` — `{canonical_id, names, aliases, deprecated_after?}`
  - `leagues.tr.yaml` — `{canonical_id: <league_catalog_id>, names, aliases}`
  - `competitions.tr.yaml` — `{canonical_id: <competition_catalog_id>, names, aliases}` (Phase 13a §13.x)
  - `markets.tr.yaml` — `{canonical_id ∈ closed enum: 1x2, ms, au_2.5, kg, btts, iy_ms, ah_home, ...; names, aliases}`
  - `dialects.tr.yaml` — slang / regionalisms / common abbreviations → canonical token sequence.
  - `entities_negative.tr.yaml` — known false-positives (e.g., "fener" alone is ambiguous; require `bahce` co-token).
- [ ] **Versioning.** Each file carries `_meta: {schema_version: 1, lexicon_version: <semver>, generated_at_utc, generator: nlp.lexicon-build}`. Schema-version mismatch refuses load.
- [ ] **Atomic swap.** Hot-reload via mtime poll (`cfg.nlp_lexicon_reload_s=30`); load into shadow, validate (every alias maps back to a canonical that exists in LeagueCatalog OR markets enum OR is explicitly marked `freeform: true`), swap under `threading.Lock`. Failure → keep old, debounced `nlp.alert.v1{kind=lexicon_unreadable, severity=error}`. Mirrors §7.5 SecInputAgent pattern reload doctrine.
- [ ] **Build pipeline.** `make nlp.lexicon-build` regenerates from LeagueCatalog + per-league preset modules + a hand-curated alias delta file (`ai/nlp/lexicon/_aliases_delta.tr.yaml`). `make verify.nlp-lexicons` AST-asserts: (a) every canonical_id resolves; (b) no two canonical_ids share an alias without an `entities_negative` disambiguator; (c) all alias strings pass through §10.1 normalize and re-resolve to the same canonical (round-trip property).
- [ ] **Integrity.** Each lexicon file SHA256 captured at load; mtime-poll skip-if-unchanged optimization keyed on the SHA (defends against editor-touch-without-change, and against truncated/partial writes — partial file → SHA mismatch with prior cached → refuse swap).
- [ ] **Cardinality cap.** `cfg.nlp_lexicon_max_entries_per_file=50000`; over-cap → `nlp.alert.v1{kind=dictionary_overflow, severity=warn}` and refuse load (defends against Phase 19 long-tail explosion silently bloating memory).
- [ ] **Bounded memory.** Aliases stored in a single `dict[str, AliasHit]` (frozen `AliasHit = (canonical_id, kind, lexicon_version)`) per file; total RSS budget `cfg.nlp_lexicon_max_rss_mb=128` validated at load.

### 10.3 Typo correction & diacritic restoration (bounded-cost)

- [ ] **Symspell-style** structure (vendored in `ai/nlp/vendor/symspell.py`) over the union of team/player/league/competition aliases. Edit budget = `cfg.nlp_typo_max_edit_distance=2` for tokens of length ≥ 5, =1 for length 3-4, =0 for length ≤ 2 (single-char tokens like "gs" must hit the abbreviation table, not fuzzy-match).
- [ ] **Per-query budget.** Total fuzzy lookups capped at `cfg.nlp_typo_max_lookups_per_query=8`. Beyond → emit `nlp.event.v1{kind=did_you_mean_offered}` and short-circuit to a "Did you mean?" reformulation (NEVER a guess).
- [ ] **Diacritic restoration table.** `ai/nlp/lexicon/_diacritics.tr.yaml` — frequency-weighted mapping of ASCIIfied form → canonical form, generated from the union of lexicons + a corpus-derived word-frequency baseline (`ai/nlp/data/tr_word_freq.txt`, sourced from open Turkish Wikipedia dump SHA-pinned in `xops/versioning/chart.json` compatibility block). NO LLM in this path (per AGENTS.md Rule 4 + Rule 1).
- [ ] **Ambiguity policy.** When two restorations are within `cfg.nlp_diacritic_tie_break_ratio=1.5x` frequency, do NOT auto-choose; preserve original token + flag for the entity resolver to disambiguate via context (e.g., co-occurring league name).
- [ ] **Cost ceiling.** Total normalize+typo+diacritic stage capped at `cfg.nlp_normalize_stage_timeout_ms=20` (deadline propagation per Phase 9 §9.17.4); on timeout → fall through to raw token sequence + `nlp.event.v1{kind=normalize_timeout}`. Better degraded answer than no answer.

### 10.4 Intent classifier (fastText, calibrated, abstaining)

- [ ] **Model.** fastText supervised, ≤ 20 MB on disk, `cfg.nlp_intent_model_path` (default `data/models/nlp/intent.tr.bin`). SHA-pinned via `make nlp.intent-pin`. CPU-only; <1 ms per query on RTX-4080m and <5 ms on AVX-2 desktop CPU (CI gate).
- [ ] **Closed intent enum** (versioned in `ai/swarm/sdk/schemas/_intent_enum.json`, `additionalProperties:false`, schema_version=1):
  - `predict.match_outcome` (1x2)
  - `predict.over_under` (au/under thresholds)
  - `predict.btts`
  - `predict.handicap`
  - `predict.score_grid` (exact score)
  - `data.fixture_lookup` (team / date)
  - `data.kickoff_time`
  - `data.standings`
  - `data.head_to_head`
  - `data.player_card_risk` (Phase 21 enrichment-bound — guarded by feature flag)
  - `summary.next_week`
  - `summary.matchday`
  - `meta.help`
  - `meta.unsupported` (sole graceful-bail intent)
  - `meta.adversarial` (any of: prompt-injection-like, off-topic, abuse — auto-routed to template `meta.adversarial.tr.j2`)
- [ ] **Calibration.** Platt-scaling (per-intent) calibration on the held-out validation slice; `nlp.intent.v1` emits `predict.intent_distribution` (top-k softmax probabilities + calibrated confidence). Stored alongside `intent.tr.bin` as `intent.tr.calibration.json`.
- [ ] **Abstention threshold.** `cfg.nlp_min_intent_conf=0.55` (pinned via §10.18 evaluation harness); below → "Did you mean?" with the top-3 intents + best-guess entity hooks (e.g., "Galatasaray maçı için: skor mu, tahmin mi, kadro mu?"). Never guess silently.
- [ ] **Drift guard.** Rolling accuracy on a 1000-query slice tracked via `nlp.event.v1{kind=intent_classifier_degraded}` when accuracy drops below `cfg.nlp_intent_accuracy_floor=0.92`; auto-routes new traffic to template-only fallback (no LLM polish on degraded intent path).
- [ ] **Versioning.** Model version + calibration version stamped on every `qa.intent.v1` envelope (`intent_model_version`, `intent_calibration_version`); allows post-hoc audit of "why did the system choose intent X for query Y on date Z".

### 10.5 Entity extraction (gazetteer + small CRF, span-resolved)

- [ ] **Hybrid pipeline.**
  1. Gazetteer pass: longest-non-overlapping match against the lexicons (§10.2). Each hit carries `(span_start, span_end, kind ∈ {team, player, league, competition, market}, canonical_id, confidence=1.0, lexicon_version)`.
  2. CRF pass: small linear-chain CRF over BIO tags for `{date, time, weekday, ordinal, money_amount, score}`. Vendored via `python-crfsuite`; model ≤ 5 MB; SHA-pinned.
  3. Conflict resolution: (a) gazetteer overrides CRF on token overlap; (b) within gazetteer, longest-match wins; (c) ties broken by `entities_negative.tr.yaml` rules then by `cfg.nlp_entity_kind_priority` ordered list.
- [ ] **Date / time resolver** (`ai/nlp/dates_tr.py`): "bugün", "yarın", "cuma", "önümüzdeki hafta", "27 Nisan saat 21:30" → `(start_utc, end_utc, granularity)`. **All resolution against `cfg.nlp_clock_now()` injection point** (test-substitutable; mirrors §8.16.1 boottime/monotonic doctrine for clock discipline).
- [ ] **Ambiguity policy.** Multi-canonical hits (e.g., "fenerli" ambiguous between "Fenerbahçe SK" and "Fenerbahçe Beko") → emit `nlp.event.v1{kind=slot_resolution_failed, candidates: [...]}`, fall through to "Did you mean?". Never silently pick.
- [ ] **PII guard at extraction.** If CRF matches a span looking like phone-number / email / credit-card → drop span (do NOT publish in `qa.intent.v1`) AND emit `nlp.alert.v1{kind=pii_detected_in_input, severity=warn}` (operator visibility; user-facing answer is unaffected).
- [ ] **Bounded latency.** p95 ≤ 8 ms on cap-length input; CI bench gate.

### 10.6 Slot resolver & dispatch (intent + entities → bus action)

- [ ] **`nlp.dispatcher.v1` agent.** Subscribes to `qa.intent.v1`. Translates `(intent, entities)` → exactly one of:
  - `predict.request.v1{match_id, market, request_id, qa_correlation_id, league_id, profile_id}` — for any `predict.*` intent that fully resolves to a single fixture + market.
  - `data.request.v1{kind, params, request_id, qa_correlation_id}` — for `data.*` intents (Phase 4 storage agent answers).
  - `qa.answer.v1` directly — for `meta.*` intents (no compute needed).
  - `qa.answer.v1{kind=disambiguation}` — when slot resolution surfaces multiple plausible fixtures (top-3 with kickoff times).
- [ ] **Deterministic backoff.** When intent is `predict.*` but a single fixture cannot be resolved (e.g., "tahmin" with no team mention), do NOT default to "today's headline match" — emit a `disambiguation` answer listing fixtures from `cfg.nlp_default_fixture_window_h=48`. Avoids silent guessing.
- [ ] **Multi-fixture intents.** `summary.next_week` / `summary.matchday` resolve to a fan-out: dispatcher publishes N `predict.request.v1` (capped at `cfg.nlp_summary_max_fixtures=10`) with a shared `summary_correlation_id`; the answer agent (§10.7) aggregates on `predict.approved.v1` arrival within `cfg.nlp_summary_aggregation_timeout_ms=2500` (deadline-propagated from `nlp_pipeline_timeout_ms`); under-collected → degraded answer with explicit "X / Y maç hazır" note.
- [ ] **`qa_correlation_id` invariant.** Generated at dispatch; round-tripped on `predict.request.v1` (Phase 9 §9.15 forward contract — already pinned), then on `predict.approved.v1` (additive field in Phase 5 schema). Boundary test: every `qa.answer.v1` carries the originating `qa.request.v1.request_id` AND the dispatch `qa_correlation_id`.
- [ ] **Idempotency.** `(qa_correlation_id, intent, entity_hash)` is the dedup key; replay safe (mirrors Phase 7 `RequestIdDeduper` pattern). Window = `cfg.nlp_dispatch_dedup_window_s=600`.

### 10.7 Answer generation (template-first, Turkish-morphology-aware)

- [ ] **Template registry.** `ai/nlp/templates/<intent>.tr.j2` — one template per intent in the closed enum (§10.4). Coverage gate: `test_nlp_template_per_intent` walks the enum and asserts a file exists.
- [ ] **Jinja2 environment** (`ai/nlp/render.py`):
  - `autoescape=False` (output is Turkish text, not HTML; XSS guard at API serialization layer per Phase 9 §9.4).
  - `undefined=jinja2.StrictUndefined` — missing slot raises (caught and routed to `meta.unsupported` template; never empty string).
  - Custom filters (vendored at `ai/nlp/jinja_filters_tr.py`): `dative`, `accusative`, `locative`, `ablative`, `genitive`, `plural` (suffix-harmony aware via vowel-class tables); `kickoff_time` (locale-aware, "Cumartesi 21:30"); `match_label` ("Galatasaray–Fenerbahçe"); `confidence_band` (probability → "yüksek/orta/düşük güven" via `cfg.nlp_confidence_bands` thresholds).
- [ ] **Suffix-harmony test harness.** `test_nlp_suffix_harmony` runs every filter against a 200-row pinned table of `(stem, expected_locative, expected_dative, ...)` covering: front/back vowels, rounded/unrounded, terminal-consonant assimilation (k→ğ, p→b), apostrophe handling for proper nouns ("Galatasaray'da" not "Galatasarayda"). Pinned via golden file; drift = test fail.
- [ ] **Citation block (mandatory for `predict.*` intents).** Every templated answer ends with a structured citation block: `prediction_id`, `produced_at_utc`, `model_versions: [predictor_id@version, ...]`, `calibration_version`, and (when `degraded:true`) `degraded_reason`. The block is included BEFORE humanizer rephrasing and is invariant across humanizer output (the proofreader §10.9 enforces preservation byte-for-byte).
- [ ] **Confidence rendering.** Probability → calibrated confidence band (default 3 bands: < 0.55 = "düşük", 0.55-0.75 = "orta", > 0.75 = "yüksek"), pinned via `cfg.nlp_confidence_bands`. Raw probability is included in the citation block; the user-facing prose uses the band.
- [ ] **Degraded-mode rendering.** `predict.approved.v1{degraded:true}` → template gains an explicit Turkish disclaimer ("Tahmin sınırlı veriyle üretildi: <reason>") AND humanizer is bypassed for the disclaimer line (preserves operator-vetted phrasing under degraded conditions).

### 10.8 Humanizer LLM (opt-in, fenced, decoding-constrained)

- [ ] **Default OFF.** `cfg.nlp_humanize=false`. Flips on per-deployment via single config change.
- [ ] **Model.** Pinned by exact version in `xops/versioning/chart.json` compatibility block (NEVER `*-latest` per CLAUDE.md). Default candidate `Trendyol-LLM-1B-base@<sha>`; <= 1 B params; quantized GGUF for CPU; bf16 for GPU.
- [ ] **Role.** Rephrase the templated answer for tone. **NEVER** decides the prediction; **NEVER** generates citation block; **NEVER** introduces facts not in the templated answer.
- [ ] **Decoding constraints (binding).**
  - `temperature=0.3`, `top_p=0.9`, `repetition_penalty=1.05`, `max_new_tokens=cfg.nlp_humanizer_max_new_tokens=120`.
  - Stop sequences include the citation block delimiter (humanizer cannot bleed into citations).
  - Logit bias against fabricated-fact triggers (numerals not in the source template; team names not in the source template; English words from a pinned blocklist `ai/nlp/data/en_word_blocklist.txt`).
- [ ] **Latency budget.** Per-call hard cap `cfg.nlp_humanizer_max_latency_ms=600` (deadline-propagated). Breach → fall back to template, emit `nlp.event.v1{kind=humanizer_disabled, reason=latency}`, open a circuit breaker (gobreaker-style) for `cfg.nlp_humanizer_breaker_open_s=60` — refuses humanize for that window, emits `nlp.event.v1{kind=humanizer_breaker_open}` once on transition.
- [ ] **Drift guard.** Output character-level edit distance vs templated answer must be ≤ `cfg.nlp_humanizer_max_edit_ratio=0.6` (LLM is rephrasing, not authoring). Over-cap → discard, fall back to template, emit `nlp.alert.v1{kind=nlp_humanizer_drift, severity=warn}`.
- [ ] **GPU sharing.** Phase 11 §11.2 round-robin scheduler — humanizer holds a single-LLM lease; coexistence with Phase 8 patcher LLM is by lease swap, not concurrent load.
- [ ] **CPU parity test (Phase 11 §11.3).** Same input + greedy seed=1337 → byte-identical output across CUDA / CPU within ε for tokens (deterministic decode required); else `cpu_only` test fails.

### 10.9 TR-quality proofreader agent (`nlp.proofreader.v1`)

- [ ] **Subscribes** `qa.answer.v1` (pre-publish channel — internal to NLP plane via `_pre_answer_topic`, not a bus topic to avoid double-emission). **Publishes** `qa.answer.v1` (post-block) OR `qa.answer.v1{kind=proofreader_blocked}` plus `nlp.alert.v1`.
- [ ] **Deterministic gates** (any failure → block):
  1. **Citation block present and unmodified** for any `predict.*` answer (sha256 over the citation block compared against the dispatcher-stamped value).
  2. **No mid-sentence English** (regex over a pinned EN-word blocklist; allowlist for proper nouns from LeagueCatalog like "Premier League").
  3. **Length bounds** `cfg.nlp_min_answer_chars=20 ≤ len ≤ cfg.nlp_max_answer_chars=600`.
  4. **PII redaction.** Phone-number / email / credit-card / TC-kimlik-no patterns (regex from `ai/common/security/patterns.py` — single source) → redact (replace with `[***]`) AND emit `nlp.alert.v1{kind=nlp_pii_in_answer, severity=error}`.
  5. **Forbidden phrases.** Pinned blocklist (`ai/nlp/data/forbidden_phrases.tr.yaml`) — covers self-promotion ("ben bir yapay zekayım"), liability disclaimers user wouldn't expect ("yatırım tavsiyesi değildir" — moved to a separate disclaimer slot), and known jailbreak echoes.
  6. **Suffix-harmony probe.** Sample 5 random `<noun>'<suffix>` constructions in the answer; assert each passes `ai/common/text/turkish.py::suffix_harmony_ok`.
- [ ] **Block taxonomy.** `nlp.event.v1{kind=proofreader_blocked, reason ∈ {citation_drift, mid_sentence_english, length_under, length_over, pii_redacted, forbidden_phrase, suffix_harmony}}`. Operators see exactly why.
- [ ] **Fail-safe.** Proofreader exception → emit template-only answer (NEVER block the user on proofreader bug); emit `nlp.alert.v1{kind=nlp_proofreader_failed, severity=error}`.

### 10.10 Graceful degradation matrix (binding)

| Failure | User-visible behavior | Bus event |
|---|---|---|
| Lexicon load fail | Continue with prior lexicon; on cold start, dispatch `meta.unsupported` template | `nlp.alert.v1{kind=lexicon_unreadable}` |
| Intent classifier missing/corrupt | Route every query to `meta.unsupported` with retry-later message | `nlp.alert.v1{kind=intent_classifier_unavailable, severity=critical}` |
| Intent confidence below floor | "Did you mean?" with top-3 intent suggestions | `nlp.event.v1{kind=did_you_mean_offered}` |
| Slot resolution ambiguous | Disambiguation answer listing top-3 fixtures | `nlp.event.v1{kind=slot_resolution_failed}` |
| `predict.approved.v1` timeout (`> cfg.nlp_predict_wait_timeout_ms`) | "Tahmin şu an hazır değil, lütfen biraz sonra tekrar deneyin." (template `predict.timeout.tr.j2`) | `nlp.alert.v1{kind=nlp_predict_timeout, severity=warn}` |
| `predict.approved.v1{degraded:true}` | Templated answer + explicit Turkish disclaimer (humanizer skipped on disclaimer line) | none (degraded flag flows through) |
| Humanizer fail / over-budget | Template-only answer; circuit-breaker opens | `nlp.event.v1{kind=humanizer_disabled}` |
| Proofreader block | Pre-block templated answer (PII redacted) | `nlp.event.v1{kind=proofreader_blocked}` + `nlp.alert.v1` |
| Bus down (publish fails) | API gateway returns 503 with retry-after; NLP spools intent for replay (mirrors Phase 8 opsctl spool, capped at `cfg.nlp_spool_max_entries=1000`) | `nlp.alert.v1{kind=nlp_bus_down, severity=critical}` |

The matrix is enumeratively tested (`test_nlp_degradation_matrix.py`).

### 10.11 Wire schemas (binding, schema_version=1)

- [ ] `qa.intent.v1.json`:
  ```
  {request_id, qa_correlation_id, sanitized_text, locale ∈ {tr-TR}, intent ∈ <closed enum §10.4>,
   intent_confidence ∈ [0,1], intent_distribution: [{intent, p}, ...],
   entities: [{kind, canonical_id, span_start, span_end, source ∈ {gazetteer, crf}}, ...],
   resolved_at_utc, intent_model_version, intent_calibration_version, lexicon_versions: {teams, ..., dialects}}
  ```
- [ ] `qa.answer.v1.json`:
  ```
  {request_id, qa_correlation_id, locale, intent, answer_text, answer_format ∈ {plain, markdown_safe},
   citations: [{kind ∈ {prediction, fact, fixture, source}, prediction_id?, source_id?, produced_at_utc,
                 model_versions[], calibration_version}],
   degraded: bool, degraded_reason?, humanizer_used: bool, proofreader_status ∈ {pass, blocked, redacted},
   tier_id_required ∈ <Phase 20 enum>, emitted_at_utc, nlp_pipeline_version}
  ```
- [ ] `nlp.event.v1.json` — kind-discriminated `oneOf` per §8.16.2 doctrine; per-kind sub-schemas under `ai/swarm/sdk/schemas/nlp.event.v1/<kind>.json`.
- [ ] `nlp.alert.v1.json` — mirrors `sec.alert.v1` shape (kind, severity, subject, debounce_key, details ≤ 2KB, emitted_at_utc); open-enum on `kind` per §7.4 doctrine; debounce via `swarm.sdk.AlertDebouncer` (pulled out of `SecAlertDebouncer` into a shared base `_BaseAlertDebouncer`).
- [ ] **`predict.request.v1` additive field.** `qa_correlation_id` (already pinned at Phase 9 §9.15); `predict.approved.v1` additive field `qa_correlation_id` is the missing piece — schema_version 1→2 additive (mirrors §9.2 KID rotation doctrine: additive only). Boundary test asserts every NLP-originated `predict.request.v1` carries it.
- [ ] **Cross-language schema parity.** Same `make verify.schemas` gate that covers `qa.request.v1` extends to all four new topics (Go gateway needs only `qa.answer.v1` for response serialization — pure data, no schema duplicate logic).

### 10.12 Performance, caching, and backpressure

- [ ] **L0 intent cache** (in-process, mirrors §9.17.6 doctrine). Key = `sha256(normalized_text|locale)`; value = `(intent, intent_confidence, entity_hash)`. `cfg.nlp_intent_cache_max_entries=10000`, TTL `cfg.nlp_intent_cache_ttl_s=300`. Negative-cache `meta.unsupported` only (never cache `predict.*` outputs — those depend on time-varying state).
- [ ] **L1 answer cache (Phase 4 `cache.v1` plane reuse).** Key = `(qa_correlation_id-stable-hash) = sha256(intent|entity_hash|fixture_window_bucket|model_versions_hash|calibration_version)`. TTL = `cfg.nlp_answer_cache_ttl_s=120` for `data.*`, `=60` for `predict.*` (predictions evolve). Invalidation reactor subscribes to `predict.approved.v1` and bumps the bucket.
- [ ] **Singleflight collapse.** Mirrors §9.17.4 — concurrent identical queries collapse to a single dispatch (`nlp.dispatcher.v1` keyed on `(qa_correlation_id-stable-hash)` with sync.Cond-equivalent in Python `threading.Event` map).
- [ ] **Latency budget table** (binding, p50 / p95 / p99 in ms, end-to-end NLP plane only — gateway+sec budget on top per Phase 9 §9.17.5):
  | Path | p50 | p95 | p99 |
  |---|---|---|---|
  | `meta.help` (cache hit) | 5 | 25 | 50 |
  | `data.fixture_lookup` (storage hit) | 30 | 100 | 200 |
  | `predict.*` template-only | 250 | 800 | 1500 |
  | `predict.*` humanized | 350 | 1200 | 2000 |
  | `summary.next_week` (10 fixtures) | 800 | 2200 | 3500 |
- [ ] **Backpressure.** When `qa.intent.v1` queue depth > `cfg.nlp_queue_pressure_threshold=100`: (a) disable humanizer (template-only mode) for `cfg.nlp_pressure_humanize_off_s=60`; (b) widen `nlp_intent_cache_ttl_s` 2x; (c) emit `nlp.alert.v1{kind=nlp_queue_pressure, severity=warn}` (debounced 60s).

### 10.13 Idempotency, dedup, replay safety

- [ ] **Producer-side `RequestIdDeduper`** at every NLP agent ingress (mirrors Phase 7 `swarm.sdk.dedup`). Window = `cfg.nlp_request_dedup_window_s=600` (≥ §10.0 inequality lower bound). Rejects double-publish from `qa.request.v1` Streams retry.
- [ ] **`(qa_correlation_id, intent_model_version, calibration_version)` audit key.** Two requests with the same correlation but different model/calibration versions MUST produce two distinct `qa.answer.v1` envelopes (the user is allowed to see "the system updated its mind"); cache (§10.12 L1) keys include both versions.
- [ ] **Spool on bus down.** NLP agents spool `qa.intent.v1` → disk (`data/nlp/spool/`, fcntl-flock per (`agent`, `qa_correlation_id`), `0700` dir / `0600` file, mtime-ordered replay) when bus publish fails ≥ `cfg.nlp_bus_failure_circuit_threshold=3` consecutive. Mirrors §8.1 opsctl spool. Cap `cfg.nlp_spool_max_entries=1000`; over-cap → drop oldest + `nlp.alert.v1{kind=nlp_spool_overflow, severity=critical}`.

### 10.14 Observability (structured, PII-clean)

- [ ] **Structured logs.** Every NLP plane log line carries `qa_correlation_id`, `request_id`, `intent`, `intent_confidence`, `entity_count`, `humanizer_used`, `proofreader_status`. **Never** the raw or sanitized text (PII discipline; mirrors Phase 9 §9.8).
- [ ] **Metrics (RED + custom).** Cardinality bounded by intent enum + degraded flag (no per-team labels — explosion guard mirrors §9.8):
  - `nlp_pipeline_latency_seconds{stage ∈ {normalize, intent, entities, dispatch, predict_wait, render, humanize, proofread}, intent}` histogram with §9.17.5-aligned buckets.
  - `nlp_intent_confidence{intent}` summary (p50 / p95 / p99).
  - `nlp_humanizer_breaker_state{state ∈ {closed, open, half_open}}` gauge.
  - `nlp_proofreader_block_total{reason}` counter.
  - `nlp_lexicon_version{file}` info gauge (operator can correlate version → behavior change).
- [ ] **Tracing.** W3C trace propagation (Phase 9 §9.5) extended through NLP pipeline; per-stage span on every request.
- [ ] **Sampled answer audit.** 1-in-`cfg.nlp_answer_sample_inverse=1000` answers captured (PII-redacted text + envelope) into `data/nlp/audit/<date>/<qa_correlation_id>.json` for offline quality review. Capped daily volume `cfg.nlp_answer_sample_daily_cap=5000`.

### 10.15 Adversarial & safety integration with Phase 7

- [ ] **Defense-in-depth.** Even though sec.input.v1 already classifies `qa.request` and produces `qa.request.v1`, NLP runs a **second-pass deterministic injection probe** on the normalized text against the same `ai/common/security/injection_patterns.yaml` (single-source) — defends against an injection that survived sanitize because rules drifted. Hit → route intent to `meta.adversarial`, emit `nlp.alert.v1{kind=nlp_secondary_injection_hit, severity=warn}`.
- [ ] **Hallucination guard.** Templated answer must reference only canonical entities present in the resolved entity list OR static template-baked phrases (`make nlp.template-lint` AST-asserts no `{{ free_text }}` slot in any template — only structured-slot interpolation).
- [ ] **Off-topic handling.** `meta.adversarial` template returns a polite Turkish redirection ("Bu konuda yardımcı olamıyorum; lütfen futbolla ilgili bir soru sorun.") — fixed phrasing, humanizer bypassed, proofreader still runs PII check.
- [ ] **Adversarial corpus alignment with Phase 12.** Phase 12 §12.2 fixture set (`ai/tests/fixtures/adversarial/`) is the **single source** for NLP adversarial tests too; NLP DoD requires 100% block of every entry mapped to NLP plane (no `xfail`).

### 10.16 Calibration & degraded-flag flow-through

- [ ] **Hard rule.** `predict.approved.v1{degraded:true, degraded_reason}` → `qa.answer.v1{degraded:true, degraded_reason}` byte-for-byte preserved. AST-asserted at the answer agent (`test_nlp_degraded_flag_round_trip`).
- [ ] **Calibration version stamping.** Every `predict.*` answer carries `calibration_version` from `predict.approved.v1`; mismatched versions across fixtures in a `summary.*` aggregation → multiple citation entries (one per version), explicit Turkish note ("X tahmin için kalibrasyon güncellendi").
- [ ] **Confidence narration discipline.** Banded confidence text MUST never contradict the raw probability (e.g., raw 0.51 with band-text "yüksek güven" → block). Proofreader §10.9 gate #7 checks this via `(prob, band, text-keywords)` cross-check table.

### 10.17 Multi-locale forward hook (TR-tr default; future-safe)

- [ ] `locale ∈ {tr-TR}` enum at v1; structured to additively gain `en-GB` / `en-US` post-Phase-13a without schema break (per §8.16.2 versioning doctrine).
- [ ] All template paths keyed `ai/nlp/templates/<intent>.<locale>.j2`; NLP code resolves locale via `cfg.nlp_default_locale` + per-request override (Phase 9 honors `Accept-Language`, lossy-mapped to supported set).
- [ ] Lexicons future-keyed by locale (`teams.tr.yaml` → `teams.tr-TR.yaml` post-rename in §R-locale, deferred). v1 ships TR-only; symlinks for forward path.

### 10.18 Evaluation harness (versioned, CI-gated)

- [ ] **Golden corpus.** `ai/tests/fixtures/turkish_queries.yaml` — ≥ 250 entries (from §10.4 originally 200; expanded), each row: `{id, raw, locale, expected_intent, expected_entities, expected_template_id, expected_disambiguation: bool, tags: [clean|no_diacritics|typo|slang|code_switch|adversarial|temporal]}`.
- [ ] **Distribution targets.** clean=60, no_diacritics=60, typos=50, slang=30, code_switch=20, adversarial=20, temporal=10.
- [ ] **CI gates.**
  - Intent accuracy ≥ `cfg.nlp_intent_accuracy_floor=0.92` over (clean ∪ no_diacritics ∪ typos).
  - Entity F1 ≥ 0.90 over the same slice.
  - 100% "did-you-mean" for low-confidence cases (no silent guesses).
  - 100% block on adversarial slice.
  - 100% suffix-harmony golden table.
  - p95 normalize ≤ 5 ms; p95 entity extraction ≤ 8 ms; p99 template render ≤ 10 ms (`make nlp.bench`).
- [ ] **Regression diff.** `make nlp.eval-diff BASELINE=<sha>` produces a markdown report comparing intent/entity/render outcomes vs a baseline corpus run; required attachment on any PR touching `ai/swarm/agents/nlp/**` (CI gate via `xops/lint/nlp_eval_diff_present.py`).
- [ ] **Property tests.** `hypothesis` strategies for: (a) normalize idempotency; (b) gazetteer round-trip (alias → canonical → alias-set membership); (c) suffix-harmony filters on random vowel-class stems; (d) template render never raises `StrictUndefined` on the closed intent enum.

### 10.19 Triangle-test config knobs (~36 new keys)

All knobs land in `ai/common/config.py` + `defaults.yaml` + `xops/env/.env.example` in the same commit (Phase 1 doctrine). Bidirectional sync test (`test_config_sync` + Go-side `TestEnvSync` if any cross to gateway, e.g., `nlp_humanizer_max_latency_ms` for §10.0 inequality validator).

Categories: input cap (1), normalize stage timeout (1), typo budgets (3), diacritic tie-break (1), intent model + abstention + drift (4), entity priority (2), dispatch + dedup + summary (4), template render limits (3), humanizer (7), proofreader (4), cache (4), latency targets (1 per row → table-mirrored), backpressure (3), spool (3), audit sampling (2), locale (1), evaluation floors (3).

### 10.20 Definition of Done

1. **Wire schemas landed.** `qa.intent.v1`, `qa.answer.v1`, `nlp.event.v1` (per-kind sub-schemas), `nlp.alert.v1` all in `ai/swarm/sdk/schemas/`; `additionalProperties:false`; cross-language gate green.
2. **Boundary tests green** (registry-walk):
   - `test_nlp_does_not_subscribe_to_qa_request_raw`
   - `test_nlp_does_not_subscribe_to_predict_final`
   - `test_nlp_outbound_topic_set_is_bounded` (exactly the §10.0 set)
   - `test_nlp_does_not_publish_sec_or_maint`
   - `test_nlp_no_per_league_branch` (AST scan)
   - `test_nlp_no_set_iteration_in_normalize` (AST scan)
   - `test_nlp_no_str_lower_in_normalize` (AST scan, mirrors §10.1 step 4)
3. **Triangle test extended** with the ~36 new cfg knobs; Go-side TestEnvSync covers the inequality-relevant ones.
4. **Idempotency proof tests.** Replay `qa.request.v1` with identical `request_id` 5x → exactly one `qa.intent.v1` and one `qa.answer.v1`. Mirrors Phase 7 `RequestIdDeduper` test pattern.
5. **Schema parity at live emission.** End-to-end test (`make swarm.demo.nlp`) validates every NLP-emitted message against its schema (mirrors §4.8 / §6 pattern).
6. **Degradation matrix exhaustive** (`test_nlp_degradation_matrix.py`) — every row in §10.10 has a positive proof.
7. **Suffix-harmony golden table** 100% pass.
8. **Adversarial corpus** 100% block (no `xfail`); golden corpus accuracy gates green.
9. **Latency bench** (`make nlp.bench`) within budgets in §10.12 table; CI-gated on PRs touching `ai/swarm/agents/nlp/**` or `ai/nlp/**`.
10. **PII guard tests** — phone / email / credit-card / TC-kimlik-no in input → not in `qa.intent.v1`; in any candidate answer → redacted by proofreader and logged.
11. **Citation-block invariance** — humanizer cannot mutate the citation block (sha256 round-trip test).
12. **Calibration / degraded flow-through.** Synthetic `predict.approved.v1{degraded:true}` → `qa.answer.v1{degraded:true}`.
13. **Spool drain.** Bus-down chaos test (`chaos.bus-flap-nlp`) shows zero data loss up to `nlp_spool_max_entries`.
14. **Humanizer breaker.** Latency-injection test opens breaker, blocks humanize for `nlp_humanizer_breaker_open_s`, emits one `humanizer_breaker_open` event on transition.
15. **Lexicon hot-reload.** mtime-touch + content-change → atomic swap within `nlp_lexicon_reload_s + 5s`; mtime-touch + content-identical (SHA match) → no swap, no event.
16. **`make swarm.demo.nlp`** end-to-end: a 12-query corpus (4 clean / 4 typos / 2 slang / 2 adversarial) flows from `qa.request.v1` → `qa.intent.v1` → dispatch → `predict.approved.v1` (mocked or real) → `qa.answer.v1` with all proof tests green; compose-mode runs in < 30s.
17. **Versioning.** `swarm` + `docs` minor bumps in same commit as land. Chart compatibility block gains pinned versions: `fasttext`, `python-crfsuite`, `jinja2`, vendored `zemberek_rules.json` SHA, humanizer LLM SHA.
18. **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4 — every checkbox in §10.0–§10.19 flipped to `[x]` in the same commit (or a §10.x sub-phase tracked as `[~]`/`[ ]` with explicit deferral note in the tracker row).
19. **All `[ ]` items in §10.21.1–§10.21.13 ticked.** This is the binding hardening addendum; landing §10.0–§10.20 without §10.21 is **not done**.
20. **All `[ ]` items in §10.22.1–§10.22.14 ticked.** This is the binding **Turkish-language correctness** addendum — Phase 10's primary differentiator. Landing §10.0–§10.21 without §10.22 ships an integrity-clean pipeline that still mishandles real-world Turkish input → **not done**.
21. **All `[ ]` items in §10.23.1–§10.23.13 ticked.** This is the binding **operability, rollout, and serving-quality** addendum. §10.21 hardened the integrity floor; §10.22 hardened the TR-language input floor; §10.23 hardens the **production-serving floor** — fairness, canary, partial-failure semantics, output formatting, timezone, accessibility, cost-budget, cache-coherence, capacity planning, DR drills, CVE policy. Landing §10.0–§10.22 without §10.23 ships a correct-but-fragile system that breaks under first contact with real multi-tenant traffic, model rotations, or partial dependency failures → **not done**.
22. **All `[ ]` items in §10.24.1–§10.24.14 ticked.** This is the binding **TR-input completeness floor** addressing fifth-pass residual classes of *wrong-Turkish* input that §10.22 (TR-language correctness) leaves under-specified: vowel-harmony violations, repeated-character emphasis, digit-letter leetspeak, decomposed-İ NFC corner case, run-on multi-question splitting, negation-aware intent, compound / sponsor-affixed club names, honorific role prefixes, emoji-as-hint discipline, hashtag / @-mention / URL / HTML-entity hygiene, decimal-vs-score numeric disambiguation, garden-path backtracking & abstention floor, empty / pathological input. Landing §10.0–§10.23 without §10.24 ships a system that is well-behaved on clean Turkish but degrades audibly on the real-world messy input that fans actually send → **not done**.
23. **All `[ ]` items in §10.25.1–§10.25.14 ticked.** This is the binding **lifecycle, conversation, and time-travel** addendum — sixth-pass residue addressing real gaps the prior 5 passes left under-specified: multi-turn conversational context, streaming response (SSE / chunked humanizer w/ mid-stream proofreader gate), time-travel audit re-render bundles, cross-artifact compatibility quartet (lexicon × intent × CRF × calibration × template), intent-model retraining lifecycle (data sourcing + canary + rollback), lexicon contributor governance (PR-gated alias_delta + two-reviewer rule for high-leverage tables), did-you-mean feedback loop (suggestion-acceptance → active-learning queue), lexicon coverage telemetry (entity-hit-rate per intent class as drift leading indicator), end-to-end right-to-erasure (Phase 8 `quarantine_erase` propagation through NLP audit + L1 cache + spool), per-tenant compliance ban-list overlay (advertiser/legal carve-outs at render-time, classifier-blind), boot-dependency graph (Phase 5 calibration-store late-arrival + GPU-lease leak on humanizer process death), summary fan-out overflow (matchday >10 fixtures: salience-ranked top-N with explicit Turkish disclosure rather than silent truncation), religious/holiday calendar in date resolver (Ramazan, Kurban Bayramı, Cumhuriyet Bayramı, milli maç haftası). Landing §10.0–§10.24 without §10.25 ships a stateless single-shot system that is correct on the first message but cannot serve real multi-message conversations, cannot reproduce a 6-month-old answer for audit, has no human-curated lexicon governance loop, and silently truncates matchday summaries → **not done**.
24. **All `[ ]` items in §10.26.1–§10.26.14 ticked.** This is the binding **morphological correctness, input modality, and counterfactual handling** addendum — seventh-pass residue addressing three classes of real-world Turkish input pathology that prior passes left producing *confidently wrong* answers (not just degraded ones): (a) **morphological-analyzer ambiguity** (Zemberek top-K parses with confidence floor, gazetteer cross-check, proper-noun bypass — the prior single-best-parse spec silently mis-routes agglutinated proper nouns); (b) **input-modality variance** (voice-to-text fillers and missing punctuation, mobile-IME Q vs F vs swipe layouts producing distinct typo distributions, autocorrect-cascade detection, long-form copy-paste artifacts including NBSP / curly quotes / em-dashes / soft hyphens / citation tails — none handled coherently before); (c) **counterfactual / conditional / modal-aspect intent firewall** (*"yenseydi" / "olur muydu" / "oynayacak mıydı"* must NOT route to `predict.*` future-only predictors — closed modality-marker table + deterministic routing override + tier-blind refusal for obligative *"oynamalı"* advice queries). Plus: lexicon supply-chain defenses (PR-flood diff cap, typo-squat detector, ortho-confusable canonical guard, alias provenance min-appearances), multi-turn correction grammar (*"öyle değil, X demek istedim"*), envelope HMAC over the full `qa.answer.v1` body (Phase 9 cache-poisoning defense — extends §10.21.8 citation HMAC to the body), football-specific bilingual concept vocab (*ofsayt/offside/var kararı/handikap*), per-subject empty-input anomaly observability. Landing §10.0–§10.25 without §10.26 ships a system that is operationally clean and conversationally aware but still mis-routes counterfactual past queries to the predictor (worst class of error: confidently wrong, not gracefully degraded), mis-extracts proper-noun morphology under Zemberek, and treats voice / mobile / paste input as if it were desktop-typed → **not done**.

25. **All `[ ]` items in §10.27.1–§10.27.14 ticked.** This is the binding **match-lifecycle, abuse-resilience, regulatory-compliance, and operator-tooling** addendum — eighth-pass residue addressing six classes of real-world failure prior passes left unhandled: (a) **fixture-state-aware dispatch** (live / postponed / cancelled / suspended / abandoned matches must NOT silently route to pre-match predictors — that produces *confidently wrong* answers indistinguishable from valid predictions); (b) **calibration-vs-fixture-state freshness gate** (calibration trained on pre-match state must refuse a 65-minute-in live query, not extrapolate); (c) **forensic incident response** (operator-driven complaint trace from `request_id` → byte-identical re-render with all original artifacts, in-flight bad-batch kill switch by content pattern, operator preview mode that impersonates user without writing audit / training-data); (d) **coordinated-abuse detector** (multi-request slow-burn patterns: did-you-mean queue poisoning, cohort-correlated shadow-training pollution, account-takeover style-shift signals — orthogonal to per-request §7 sec rate limit); (e) **schema-version downgrade for old clients** (`qa.answer.v1` is now schema=3 after §10.24.5 + §10.26.8; old SDK clients negotiate via `Accept: application/vnd.negelir.qa-answer+json; version=1` → server downgrades by stripping additive-only fields, never silently breaks); (f) **regulatory disclosure invariant** (KVKK Art 11 user-rights footer on first per-conversation answer, Turkish gambling-law disclaimer band on every `predict.*` answer, GDPR-Art-22-equivalent automated-decision notice — all template-managed, humanizer-bypassed, locale-resolved). Plus: cross-pod lexicon-swap consistency window (drain-before-swap protocol so two pods do not return divergent answers at the swap edge), anti-leakage gates on shadow→training (degraded / quarantined / proofreader-blocked rows EXCLUDED from `make nlp.intent-train` corpus, eval-set-vs-train-set membership manifest), edge-platform answer-format profile forward hook (WhatsApp 4096-char / SMS 160-char / TTS-friendly — dormant at v1 with reserved enum), live-score data-plane separation (live queries route to `data.request.v1{kind=live_state}` not `predict.request.v1` — defends against "what is the score?" being answered with a stale prediction), and per-conversation entity-graph snapshot for time-travel re-render (extends §10.25.3 audit bundle to include the conversation context that produced the answer). Landing §10.0–§10.26 without §10.27 ships a system that handles a single pre-match Turkish query well but: confidently mis-answers live-match queries, has no operator response to a production incident beyond "wait for the next deploy", lets old clients break on schema additions, ships predictions without the regulatory disclaimers Turkish law requires, and trains its next-generation classifier on its own degraded outputs → **not done**.

26. **All `[ ]` items in §10.28.1–§10.28.15 ticked.** This is the binding **authentic-Turkish floor** addendum — ninth-pass residue addressing the specific classes of *authentically wrong Turkish* the prior eight passes left producing confidently-wrong answers: (a) **orthographic-rule tolerance** for the rules native speakers most often break — consonant softening (`ünsüz yumuşaması` p→b/ç→c/t→d/k→ğ and the inverse), vowel drop (`ünlü düşmesi` akıl+ı→aklı), consonant assimilation (`ünsüz benzeşmesi` -de/-da↔-te/-ta), soft-g loss (g↔ğ); (b) **structural robustness** for input shapes the morphology pipeline assumed away — no-space concatenated compounds (mobile-keyboard reality: *galatasarayfenerbahçe*), structurally incomplete fragments (hanging conjunction / dangling postposition), distractor-preamble strip (greeting + vocative + opinion-filler before the actual question dilutes classifier confidence), ALL-CAPS / shout normalization (disable capitalization-as-entity-hint when the entire message is uppercase); (c) **TR-specific PII detection & redaction** (TC kimlik no with mod-10/mod-11 checksum, IBAN-TR with mod-97, Turkish mobile / landline phone formats, vehicle plates, VKN — single-source `tr_pii.py` shared cross-language with the Phase 7 Go sec layer; runs BEFORE length cap so PII can never split across the cap boundary); (d) **loan-word transliteration unification** (closed table for *ofsayt/offside/ofsayd/ofsait* etc., bypasses Symspell for known variants); (e) **meta / rhetorical / non-answerable question routing** (closed table for *"sen ne biliyorsun ki"*, *"yardım edebilir misin"*, *"ne diyorsun lan"* — short-circuits BEFORE classifier so dispatcher cannot leak rhetorical questions into predict.* / data.*); (f) **resource-discipline guards that keep the long pipeline honest under load** — per-request CPU + RSS budget enforcement via `signal.setitimer` + `resource.setrlimit` (defends against worst-case Symspell × Zemberek × CRF × multi-subquery combinatorial blow-up that wall-clock alone cannot bound), Symspell / CRF hot-reload back-pressure (concurrent-rebuild cap + per-rebuild RSS reservation + per-request budget grace during the swap window — defends against false-positive `cpu_budget_exceeded` flap during normal lexicon deploys), classifier-vs-extractor confidence-skew detector (silent both-confident-but-disagreeing case surfaces as telemetry; not a hard gate at v1, forward-phase hook for retraining loop). Landing §10.0–§10.27 without §10.28 ships a system that handles careful clean-Turkish input but mis-canonicalises consonant-alternated proper nouns, leaks TR PII to audit / spool, dilutes intent confidence on natural conversational preambles, can be DoS'd by a Symspell-pathological token under contention, and has no observability of the silent classifier-vs-extractor disagreement class → **not done**.

27. **All `[ ]` items in §10.29.1–§10.29.16 ticked.** This is the binding **deep-morphology, telegraphic-input, and silent-failure floor** addendum — tenth-pass residue addressing the residual class of *confidently-wrong Turkish* the prior nine passes left under-specified: (a) **deep morphology beyond §10.28.1** — geminate restoration on Arabic/Persian-origin doubled-consonant stems (`hak→hakkı`, `sır→sırrı`), stem-final vowel deletion before vowel-initial suffix (`oğul→oğlu`, `burun→burnu`, distinct from §10.28.1 stem-internal drop), `-nk → -ng` cluster softening (`renk→rengi`, distinct from generic `-k → -ğ`), pronominal dative irregularity (`ben→bana`/`o→ona` paradigm + lexicon-bypass guard so Symspell cannot resolve them to player surnames), loan-word plural-as-singular drift (`datalar→data`, suppress double-plural detection); (b) **structural intent gaps** — verbal-noun gerund (`-ma/-me`) vs nominalisation (`-mak/-mek`) ambiguity that flips the *subject* of the question (must offer disambiguation, never silently pick), reduplicated-emphasis full-word collapse (`yeşil yeşil` distinct from intra-token `evettttt`), coordinator-driven multi-fixture parsing with new comparative intent (`ya da/veya/ya...ya` → `predict.match_outcome.comparative` fan-out, not first-found-entity wrong pick), telegraphic-style intent inference (no-`?`-no-`mı`-no-verb queries like `Galatasaray bugün` deterministically routed to `data.fixture_lookup` with closed whitelist + AST guard rejecting any `predict.*` leak), `ki` colloquial-vs-formal context disambiguation (relative comma-bound vs emphatic sentence-final); (c) **silent-failure integrity floor — three independent gates prior nine passes missed** — single-source `tr_normalize_spec.json` with cross-language byte-parity gate (Python NLP normalize and Go sec sanitize must produce byte-identical output on a 1000-row corpus, both implementations refuse boot on spec-SHA mismatch — closes the injection-bypass class where gateway sees one canonicalisation and NLP sees another), prediction-id determinism gate as a *second* independent integrity check beyond §10.21.8 envelope HMAC (NLP re-derives `sha256(match_id|market|request_id|calibration_version)` and rejects mismatched envelopes — defends against operator-HMAC-key-leak + cache-poisoning where envelope is HMAC-valid but producer was the attacker), pipeline-version monotonicity gate (Redis-backed max-seen + L0 cache version-aware reject so an emergency rollback cannot read newer-pipeline-version cached outputs the older code cannot interpret). Landing §10.0–§10.28 without §10.29 ships a system that mis-canonicalises Arabic/Persian-origin geminate stems, mis-handles irregular pronominal dative as typo'd surnames, silently picks one of two valid subject readings on verbal-noun ambiguity, mis-routes coordinator multi-fixture queries to a single arbitrary fixture, abstains on telegraphic queries that have unambiguous intent, allows Python and Go normalize implementations to silently drift apart (injection bypass class), trusts every HMAC-valid envelope without re-verifying the deterministic prediction_id (catches operator-key-leak), and crashes or returns garbage when emergency-rolled-back pods read newer-version cached outputs → **not done**.

### 10.21 Hardening, integrity, and second-order safety (binding addendum)

> Mirrors the §9.17 pattern: §10.0–§10.20 are the surface contract; §10.21
> is the integrity floor underneath. Every `[ ]` here is binding for
> Phase 10 DoD (per §10.20 item 19). New cfg knobs land alongside §10.19
> in the same triangle commit.

#### 10.21.1 Determinism & numerical reproducibility (beyond §10.1 / §10.4)

- [ ] **No `set` / `dict` iteration in any decision path.** AST guard `test_nlp_no_unsorted_iteration_in_decision_path` walks `ai/swarm/agents/nlp/**` + `ai/nlp/**` and rejects iteration over `set(...)`, `frozenset(...)`, `dict.keys()`, `dict.items()`, `dict.values()` without a wrapping `sorted(...)` (or `OrderedDict` / `tuple` literal). Existing §10.1 guard is normalize-only; this widens to intent classifier post-processing, entity conflict resolution, dispatcher routing, template slot ordering, citation block construction.
- [ ] **`hypothesis` settings pinned globally for NLP suite.** `ai/swarm/agents/nlp/tests/conftest.py` sets `hypothesis.settings.register_profile("nlp_ci", database=None, derandomize=True, max_examples=cfg.nlp_hypothesis_max_examples=1000)` and `load_profile("nlp_ci")` at import. Without `database=None`, CI cache divergence between runners makes shrink-to-different-counterexample non-deterministic.
- [ ] **fastText load-time SHA verification.** `intent.tr.bin` opened, sha256 computed, compared against `intent.tr.bin.sha256` sidecar (built by `make nlp.intent-pin`). Mismatch → refuse start with `nlp.alert.v1{kind=nlp_intent_model_sha_mismatch, severity=critical}`. Defends against silent file corruption (bit-rot) and against `numpy` ABI shifts that could re-serialize the binary differently across upgrades.
- [ ] **Numpy + fastText version pin.** Compatibility block in `xops/versioning/chart.json` records exact `numpy` + `fasttext` wheel versions. Boot probe asserts `numpy.__version__` + `fasttext.__version__` match — refuse start on drift (per CLAUDE.md "no `*-latest`" doctrine).
- [ ] **CRF model determinism.** `python-crfsuite` `Tagger.tag()` is deterministic but feature-extraction order isn't if features are dicts; AST guard rejects `dict(...)` literal in feature builder, requires `list[tuple[str, float]]` (insertion-ordered + explicit).
- [ ] **Greedy-decode parity.** Humanizer §10.8 `cpu_only` parity test extends to: same `(input, seed=1337, temperature=0.0, top_p=1.0)` → byte-identical token IDs across CUDA / CPU / Metal (mock-Metal for CI). Δ tolerance = **zero tokens** (greedy is deterministic by construction); any drift = test fail.
- [ ] **Proof:** `test_nlp_decision_path_iteration_is_sorted`, `test_nlp_hypothesis_profile_loaded_with_no_database`, `test_nlp_intent_model_sha_verified_at_load`, `test_nlp_compatibility_versions_pinned`, `test_nlp_crf_features_are_ordered`, `test_nlp_humanizer_greedy_byte_identical_across_devices`.

#### 10.21.2 Memory lifecycle & resource leaks

- [ ] **Lexicon old-generation eviction contract.** §10.2 `threading.Lock`-protected swap leaves the OLD `dict[str, AliasHit]` retained by in-flight requests. Each `LexiconStore` holds at most `cfg.nlp_lexicon_max_old_generations=2` retired snapshots; older generations are dropped (refcount → 0 once last in-flight request returns). Generation handle = monotonic int; debug log at swap captures `(old_gen, new_gen, in_flight_count)`.
- [ ] **fastText / CRF reload via process-restart, not in-process swap.** Re-loading `intent.tr.bin` mid-process leaks mmap regions on most libc allocators. NLP-pod model-reload contract: SIGTERM → graceful drain (Phase 9 §9.17.4 pattern) → K8s rolls a fresh pod. **No in-process model hot-swap.** AST guard `test_nlp_no_in_process_model_reload` rejects `fasttext.load_model(...)` outside `__init__`.
- [ ] **Symspell dictionary lifetime.** Built once at boot from current lexicon snapshot; on lexicon swap, REBUILT (not mutated). Old Symspell instance dereferenced atomically with old lexicon generation. Memory test (`test_nlp_symspell_no_growth_on_repeated_swaps`) probes RSS after 100 swaps — Δ < 5 MiB.
- [ ] **Jinja2 environment uses bytecode cache + precompiled templates.** `Environment(loader=FileSystemLoader, bytecode_cache=FileSystemBytecodeCache(cfg.nlp_jinja_bcc_dir, pattern="__nlp_%s.cache"), auto_reload=False)`. AST guard rejects `Environment().from_string(...)` anywhere under `ai/nlp/render.py` (string-template compilation in hot path = unbounded codegen).
- [ ] **Singleflight event-map sweeper.** §10.12 `threading.Event` map is keyed on hash; resolved-and-popped on result delivery, BUT a crashed dispatcher leaves orphaned events. Background sweeper (`cfg.nlp_singleflight_sweep_interval_s=30`) drops events older than `cfg.nlp_singleflight_event_max_age_s=60` and emits `nlp.event.v1{kind=singleflight_event_swept, count=N}` (debounced). Cap on map size = `cfg.nlp_singleflight_max_inflight=2048`; over-cap → reject + `nlp.alert.v1{kind=nlp_singleflight_overflow, severity=warn}`.
- [ ] **RSS ceiling per pod.** `cfg.nlp_pod_rss_max_mb=2048` (lexicons 128 + intent.tr.bin 20 + crf 5 + jinja2 cache 50 + symspell 100 + python overhead 200 + humanizer 1024 + headroom). Boot validator computes the sum from sub-knobs and refuses start if it exceeds the cap (catches operator over-tuning a sub-knob).
- [ ] **Proof:** `test_nlp_lexicon_old_gen_evicted_after_inflight_drain`, `test_nlp_no_in_process_model_reload` (AST), `test_nlp_symspell_no_growth_on_repeated_swaps`, `test_nlp_jinja_bcc_used_no_string_template_compile` (AST), `test_nlp_singleflight_sweeper_drops_orphans`, `test_nlp_pod_rss_budget_validated_at_boot`.

#### 10.21.3 Atomic multi-file lexicon swap (all-or-nothing)

- [ ] **Real bug §10.2 misses.** Six lexicon files swap independently. If `players.tr.yaml` validates but `competitions.tr.yaml` parse-fails mid-poll cycle, the in-memory state has new players paired with old competitions — referential integrity violated (a new player's `team_canonical_id` may not exist in the not-yet-swapped teams snapshot). Cross-file invariants (player→team, fixture→competition) silently break.
- [ ] **Atomic swap policy.** `cfg.nlp_lexicon_swap_atomicity ∈ {per_file, all_or_nothing}` default `all_or_nothing`. Under `all_or_nothing`, the poll cycle: (1) re-read SHA of all 6+1 files; (2) if any changed, load **all** changed files into shadow; (3) run cross-file referential validator (`ai/nlp/lexicon/_xref.py::validate_xref(snapshot)`); (4) if all pass, atomic swap of the whole `LexiconSnapshot` under one lock; (5) else REVERT shadow + emit `nlp.alert.v1{kind=nlp_lexicon_atomic_swap_failed, severity=error, failing_files: [...], reason}`.
- [ ] **Cross-file referential validator.** Asserts: (a) every `player.team_canonical_id` resolves in `teams`; (b) every `team.league_canonical_id` resolves in `leagues`; (c) every `competition.parent_id` resolves; (d) every alias in `dialects` expands to canonical-token-sequence whose tokens resolve via `teams ∪ players ∪ markets`; (e) every `entities_negative` rule references at least one declared canonical_id.
- [ ] **Bounded swap latency.** Whole-snapshot swap p95 ≤ 50 ms (lock held only for the dict-pointer flip — validation runs OUTSIDE the lock). Probe in CI bench.
- [ ] **Proof:** `test_nlp_lexicon_swap_is_all_or_nothing` (corrupt 1 of 6 files mid-cycle → all reverted), `test_nlp_lexicon_xref_validator_catches_dangling_player_team`, `test_nlp_lexicon_swap_lock_hold_under_50ms`.

#### 10.21.4 Concurrency hazards (singleflight scope, breaker scope, lock ordering)

- [ ] **Humanizer breaker scope is per-pod by default.** §10.8 breaker is `cfg.nlp_humanizer_breaker_scope ∈ {pod, cluster}` default `pod`. Cluster-scope (Redis-backed) is opt-in for stampede-protection in dense replica deployments — but doctrine note: cluster-scope adds a Redis round-trip on every humanize call → only flip on after measuring per-pod breaker open-rate above 5%. Both modes proof-tested.
- [ ] **Singleflight scope is per-pod.** Cross-pod collapse is intentionally NOT done — the cost (Redis lock per query) outweighs the benefit at v1 scale. Documented in `docs/design/TURKISH_NLP.md` and asserted by `test_nlp_singleflight_does_not_use_redis` (AST scan rejects `redis.lock` import in `ai/swarm/agents/nlp/dispatcher.py`).
- [ ] **Lock ordering invariant.** Across NLP plane the only locks held are: (a) per-LexiconStore lock; (b) per-key singleflight `threading.Event`. Strict ordering: lexicon → singleflight (never reverse). AST guard `test_nlp_lock_ordering_no_reverse_acquisition` walks `with self._lexicon_lock` and `with self._sf_event` blocks and asserts the order.
- [ ] **No GIL-released call inside a lock.** Lexicon lock is held only for pointer-swap (microseconds); MUST NOT enclose any I/O, fastText predict, or CRF tag. AST guard `test_nlp_no_io_under_lexicon_lock` rejects `with self._lexicon_lock:` blocks containing `open(`, `requests.`, `predict(`, `tag(`, `predict_one(`.
- [ ] **Proof:** `test_nlp_humanizer_breaker_per_pod_isolated`, `test_nlp_humanizer_breaker_cluster_scope_redis_path` (skip-if-no-redis), `test_nlp_singleflight_does_not_use_redis` (AST), `test_nlp_lock_ordering_no_reverse_acquisition` (AST), `test_nlp_no_io_under_lexicon_lock` (AST).

#### 10.21.5 Unicode confusables / homoglyph defense (defense-in-depth atop sec.input)

- [ ] **Real attack §10.1 misses.** Sec gate strips zero-widths but does NOT collapse confusable-script characters: "Galаtasaray" (Cyrillic а U+0430 instead of Latin a U+0061) survives sec, fails gazetteer exact-match, falls to fuzzy → resolves to a different team OR misses entirely. CVE-2021-42574-style trojan-source attacks (directional formatting beyond U+202E — U+2066–U+2069) similarly survive a naive RTL-strip.
- [ ] **Confusables-fold stage** added to §10.1 normalize as step 3.5 (between strip and Turkish lowercase). Source: Unicode TR39 Confusables.txt (SHA-pinned in chart.json compatibility block); folded to ASCII-Turkish-extended (a-zçğıöşü). Stored as immutable `dict[int, str]` (codepoint → replacement). NEVER applied to passwords (already excluded by §7.1 password-bypass; reasserted here for the NLP plane).
- [ ] **Bidi formatting strip extends beyond U+202E.** Strip set: U+202A (LRE), U+202B (RLE), U+202C (PDF), U+202D (LRO), U+202E (RLO), U+2066 (LRI), U+2067 (RLI), U+2068 (FSI), U+2069 (PDI). Single source: `ai/common/text/normalize.py::BIDI_STRIP_CODEPOINTS` frozenset; AST asserts the frozenset has all 9 codepoints.
- [ ] **Homoglyph attack on canonical-id resolution.** After confusables fold, the gazetteer pass MUST use the folded form for exact match; if the folded form differs from raw, original raw form is preserved in `qa.intent.v1.entities[].original_text` for audit but resolution uses folded. Audit log carries `confusables_resolved_count` per query.
- [ ] **Proof:** `test_nlp_confusables_cyrillic_a_resolves_to_galatasaray` (corpus probe), `test_nlp_bidi_strip_covers_all_9_codepoints`, `test_nlp_confusables_fold_skipped_for_password_field` (boundary), `test_nlp_confusables_table_sha_pinned` (chart compat).

#### 10.21.6 Template safety (no raw user text reach)

- [ ] **Real bug §10.7 misses.** `test_nlp_template_per_intent` proves coverage but not safety: a template could render `{{ entity.original_text }}` (preserved per §10.21.5 for audit) which is **raw user input** routed back through prose. That defeats `make nlp.template-lint` which only checks for `free_text` placeholders.
- [ ] **AST template lint widened.** `make nlp.template-lint` now AST-rejects ANY of the following inside an `{{ ... }}` interpolation: `entity.original_text`, `entity.raw`, `*.user_text`, `*.normalized_text`, `kwargs.get(`, `request.*`. Allowlist: `entity.canonical_id`, `entity.kind`, `entity.span_start`, `entity.span_end`, predefined filter outputs (`team | match_label`, `kickoff | kickoff_time`).
- [ ] **Runtime guard (defense-in-depth).** Custom Jinja2 `Environment.finalize` callable that asserts no string slot equals the original `qa.request.v1.text` substring (length ≥ 6). Hit → block render, emit `nlp.alert.v1{kind=nlp_template_render_used_raw_user_text, severity=critical}`. Should never fire if the AST lint passes; this is the runtime "shouldn't happen" alarm.
- [ ] **Citation block templating.** Citation block renders from a single closed-schema `dict` (`prediction_id`, `produced_at_utc`, `model_versions[]`, `calibration_version`, `degraded_reason?`); no other slots permitted. AST asserts citation template uses ONLY these fields. Block rendered to a normalized canonical form (sorted keys, fixed whitespace) so the §10.9 sha256 round-trip is byte-stable.
- [ ] **Proof:** `test_nlp_template_lint_rejects_entity_original_text`, `test_nlp_template_finalize_blocks_raw_user_substring`, `test_nlp_citation_block_canonical_form_is_byte_stable`.

#### 10.21.7 PII discipline depth (logs, spool, audit sampling)

- [ ] **Real bug §10.14 misses.** "Logs never carry text" is a developer convention; nothing prevents an `except Exception as e: logger.error("intent fail: %s", e)` from spilling user text into stderr if `e.args[0]` happens to contain it. Need a structural guard.
- [ ] **PII-scrubbing log filter.** `ai/swarm/agents/nlp/_log_filter.py::PIIScrubFilter` registered on every NLP-plane logger (`add_log_filter` called in agent `__init__`). Walks every log record's `args` + `msg` + `exc_info` and applies the §10.9 PII regex set (phone / email / credit-card / TC-kimlik) AND a "long-string" heuristic — any unrecognized string ≥ `cfg.nlp_log_max_unredacted_str_len=64` chars → replaced with `[REDACTED:len=N:sha8=XXXXXXXX]`. AST guard `test_nlp_every_logger_has_pii_scrub_filter` walks `__init__` of each NLP agent class and asserts `add_log_filter(PIIScrubFilter())`.
- [ ] **Spool payload PII strip.** §10.13 spool writes `qa.intent.v1` to disk; even sanitized, the text COULD contain user-typed personal context. `cfg.nlp_spool_payload_pii_strip=true` (default true); spool envelope drops `sanitized_text` field on write, replaces with `sanitized_text_sha256` for replay correlation. On replay, the agent fetches the original `qa.request.v1` from the bus by `request_id` (still in stream within retention window) — if the bus is also down and original text is unavailable, the spooled envelope is dropped + `nlp.alert.v1{kind=nlp_spool_replay_text_unavailable, severity=warn}`. Trade-off pinned: prefer dropping a request over storing PII at rest.
- [ ] **Sampled answer audit redaction whitelist.** §10.14 captures answers; redaction whitelist explicitly: `qa_correlation_id`, `request_id`, `intent`, `intent_confidence`, `entity_count`, `proofreader_status`, `humanizer_used`, `degraded`, `degraded_reason`, `tier_id_required`, `model_versions[]`, `calibration_version`, `nlp_pipeline_version`, `lexicon_versions`, `produced_at_utc`. Everything else (incl. `answer_text`, `entities[]`) PII-redacted via the same regex set. Boot test asserts the whitelist is a closed set (no `*` glob).
- [ ] **Spool dir + audit dir mode.** `data/nlp/spool/` and `data/nlp/audit/` enforced to `0700` parent / `0600` files at agent startup; mismatch → refuse start (mirrors §8.3 backup file-mode doctrine).
- [ ] **Proof:** `test_nlp_log_filter_redacts_phone_in_exception_args`, `test_nlp_log_filter_redacts_long_unrecognized_strings`, `test_nlp_every_logger_has_pii_scrub_filter` (AST), `test_nlp_spool_envelope_strips_text_field`, `test_nlp_spool_replay_drops_when_original_unavailable`, `test_nlp_audit_whitelist_is_closed_set`, `test_nlp_spool_audit_dir_modes_enforced_at_startup`.

#### 10.21.8 Citation integrity & signature verification (cross-phase Phase 5)

- [ ] **Real attack §10.7/§10.9 misses.** §10.9 proofreader gate #1 asserts citation byte-stability across humanizer (defends against the LLM mangling citations). It does NOT defend against a forged `predict.approved.v1` envelope with a tampered citation — proofreader trusts whatever the consensus agent emitted. If the bus is compromised or a malicious worker injects a fake `predict.approved.v1`, NLP renders the forged citation and signs it as the system's answer.
- [ ] **Phase 5 forward contract addition.** `predict.approved.v1.citation_signature` (additive, schema_version 2→3 — landed when §10.21 lands) = HMAC-SHA256 over `(prediction_id || produced_at_utc || model_versions_canonical || calibration_version)` keyed on `cfg.predict_citation_hmac_key_path` (mode 0400, agent-only readable, mirrors §8.15.4 audit-chain key doctrine).
- [ ] **NLP verifies on consume.** `cfg.nlp_predict_citation_hmac_required ∈ {off, warn, enforce}` default `warn` at v1 (key rollout takes time across agents). Under `enforce`: missing or invalid signature → drop the envelope, emit `nlp.alert.v1{kind=nlp_citation_signature_verify_failed, severity=critical}`, route the user query to a `predict.timeout` template (NEVER render unverified citation). Under `warn`: render but emit alert.
- [ ] **Key rotation runbook.** `make nlp.rotate-citation-key` mirrors `ops.rotate-allowlist-key` (§8.15.4): generates new key, dual-acceptance window `cfg.predict_citation_hmac_key_grace_s=86400` (24h), then retires old. Key-id stamped on every signature for rotation safety. Phase 9 §9.13 gains the matching CI gate that `enforce` mode is on by Phase 14.
- [ ] **Proof:** `test_nlp_citation_signature_verified_under_enforce`, `test_nlp_forged_citation_dropped_under_enforce`, `test_nlp_warn_mode_renders_with_alert`, `test_nlp_citation_key_rotation_dual_window_accepts_both`.

#### 10.21.9 Cold-start, readiness, & boot budget

- [ ] **Real bug §10.0 / Phase 14 readiness misses.** A NLP pod could pass liveness (process up) while still loading the 128 MiB of lexicons + 20 MiB intent.tr.bin + Symspell dictionary build (which itself is O(|aliases|) ≈ seconds). During that window K8s could route traffic to it → 503 storm.
- [ ] **`nlp.ready` boot stages.** Pod tracks 6 stages monotonically: `(0) starting → (1) lexicons_loaded → (2) intent_model_loaded → (3) crf_loaded → (4) symspell_built → (5) jinja_warmed → (6) gpu_lease_acquired_or_skipped`. Readiness probe returns 200 only at stage 6. Each stage emits `nlp.event.v1{kind=cold_start_stage, stage, elapsed_ms}`.
- [ ] **Boot budget.** `cfg.nlp_boot_budget_s=30` total; per-stage caps (`lexicons=10s, intent_model=3s, crf=2s, symspell=10s, jinja_warm=2s, gpu_lease=3s`). Budget breach → readiness stays 503 + `nlp.alert.v1{kind=nlp_cold_start_timeout, severity=critical, last_stage}`. K8s restart kicks in via `livenessProbe` after `cfg.nlp_boot_liveness_grace_s=60`.
- [ ] **Jinja warm.** Warm stage iterates the closed intent enum and renders each template against a fixture slot dict (no I/O, no humanize) — populates the bytecode cache + asserts every template parses. Render failure at warm = refuse readiness.
- [ ] **Drain on SIGTERM.** Mirrors Phase 9 §9.17.4 graceful shutdown: stop accepting `qa.intent.v1` consumes (release stream group) → drain in-flight (semaphore wait, max `cfg.nlp_shutdown_grace_s=20`) → flush spool to bus or disk → release GPU lease → exit 0.
- [ ] **Proof:** `test_nlp_readiness_503_until_stage_6`, `test_nlp_per_stage_budget_enforced`, `test_nlp_jinja_warm_renders_every_intent_template`, `test_nlp_graceful_shutdown_drains_inflight_no_loss`, `test_nlp_cold_start_alert_carries_last_stage`.

#### 10.21.10 Confidence band stability & calibration mismatch policy

- [ ] **Real bug §10.7 / §10.16 misses.** Confidence bands `[low|mid|high]` are pinned at thresholds `[0.55, 0.75]` but the interval semantics are unspecified — `prob = 0.55` could be either low or mid depending on `<` vs `<=`. Across CPython versions or if a future change uses `numpy.float32` rounding, the band call could flip silently.
- [ ] **Pinned half-open intervals.** `low = [0.0, cfg.nlp_confidence_band_lower=0.55)`, `mid = [0.55, cfg.nlp_confidence_band_upper=0.75)`, `high = [0.75, 1.0]`. AST asserts the comparator is `<` for upper bound, `>=` for lower — i.e. `if prob < lower: return "low"; if prob < upper: return "mid"; return "high"`. Property test `test_nlp_band_boundary_intervals` probes 0.0, 0.5499, 0.55, 0.5501, 0.7499, 0.75, 0.7501, 1.0 and asserts the canonical mapping.
- [ ] **Float32-vs-float64 drift guard.** Calibrated probability is computed in float64; band call MUST take float64 (no implicit downcast). AST guard `test_nlp_band_signature_is_float` rejects any call site passing `numpy.float32` to `confidence_band`.
- [ ] **Calibration mismatch policy in summary fan-out.** §10.16 says "multiple citations" when versions diverge across fixtures in a `summary.*` aggregation; §10.21 pins the policy as `cfg.nlp_summary_calibration_mismatch_policy ∈ {note, refuse}` default `note` (render with explicit Turkish disclosure). Under `refuse` (operator-elected for high-stakes deployments), the summary degrades to "Bu hafta için tahminler farklı kalibrasyon sürümleriyle üretildiği için birleşik özet sunulamıyor." with a per-fixture link. Both paths proof-tested.
- [ ] **Proof:** `test_nlp_band_boundary_intervals` (8-point probe), `test_nlp_band_signature_is_float` (AST), `test_nlp_summary_calibration_mismatch_note_mode`, `test_nlp_summary_calibration_mismatch_refuse_mode`.

#### 10.21.11 Cross-phase contract additions (Phase 8 / 9 / 14 / 16 / 20)

- [ ] **Phase 8 patcher boundary.** `ai/swarm/agents/nlp/**` is **outside** the patcher's scope-allow-list (per CLAUDE.md scope table: only `extractor / schema / migration / fixture / detector_tuning`). Boundary test `test_patcher_scope_excludes_nlp_paths` walks the patcher scope registry and asserts no entry matches `nlp/**`. NLP failures route to humans via `proof.flag` (mirrors Phase 5 doctrine for predictor failures).
- [ ] **Phase 9 RFC 7807 problem+json error mapping.** When the API gateway surfaces an NLP failure to the client, the mapping is binding (single source `server/internal/api/errors_nlp.go`):
  | NLP terminal state | HTTP | `type` URI suffix | `title` (TR) |
  |---|---|---|---|
  | `meta.unsupported` rendered | 200 | n/a (not an error) | n/a |
  | `proofreader_blocked` (PII or forbidden phrase) | 200 | n/a | n/a (degraded answer rendered) |
  | `nlp_predict_timeout` | 504 | `/errors/nlp/predict-timeout` | "Tahmin zaman aşımına uğradı" |
  | `nlp_bus_down` | 503 | `/errors/nlp/bus-down` | "Sistem geçici olarak kullanılamıyor" |
  | `intent_classifier_unavailable` | 503 | `/errors/nlp/classifier-unavailable` | "Servis hazır değil" |
  | `nlp_cold_start_timeout` | 503 | `/errors/nlp/cold-start-timeout` | "Servis henüz hazır değil" |
  | `nlp_citation_signature_verify_failed` (enforce mode) | 502 | `/errors/nlp/upstream-integrity` | "Üst sistem doğrulama hatası" |
  All other NLP terminal states render as 200 with degraded payload (NEVER 5xx — graceful degradation per §10.10).
- [ ] **Phase 14 readiness probe contract.** K8s `readinessProbe` HTTP `GET /v1/internal/nlp/ready` → 200 only at boot stage 6 (§10.21.9). `livenessProbe` → 200 if process responds at all (no model state required). `startupProbe` → 200 at boot stage ≥ 1 (lexicons loaded — proves the pod isn't stuck in Python startup). Three distinct probes; documented in §14 K8s manifest.
- [ ] **Phase 16 emitter feed schema bump handling.** When `LexiconStore` (Phase 16 Protocol) feed emits a new schema version > the NLP-pinned `cfg.nlp_lexicon_feed_max_supported_schema_version`, NLP REFUSES the swap (keeps prior generation), emits `nlp.alert.v1{kind=nlp_lexicon_feed_schema_too_new, severity=warn}`, and continues serving on the older snapshot. Operator must ship NLP upgrade before turning off the older emitter. Proof: `test_nlp_refuses_lexicon_swap_on_feed_schema_too_new`.
- [ ] **Phase 20 monetization tier × humanizer doctrine.** Pinned: `tier_id_required` is a **per-intent** function (`cfg.nlp_intent_tier_map`), NOT a per-`humanizer_used` function. Humanized vs templated answer for the same intent yields the same tier. Rationale: humanize is server-side polish, not a feature the user opts into. AST asserts `nlp.dispatcher.v1` does not branch tier lookup on `humanizer_used`.
- [ ] **Phase 13a LeagueCatalog evergreen propagation.** When LeagueCatalog changes (per `make catalog.publish` event), `make nlp.lexicon-build` is triggered automatically by a CI job (`xops/ci/nlp_lexicon_rebuild.yml`); resulting lexicon diff committed via `make git` (human-only). NLP at runtime is mtime-poll-driven (§10.2) — the file change drives the swap. Boundary test: `test_nlp_lexicon_does_not_query_league_catalog_at_runtime` (NLP must not import `ai/common/league_catalog.py` directly; only consumes the generated lexicon files).

#### 10.21.12 Knob inventory addendum (~14 new keys, on top of §10.19)

`nlp_hypothesis_max_examples=1000`, `nlp_lexicon_max_old_generations=2`, `nlp_jinja_bcc_dir="data/nlp/jinja_cache"`, `nlp_singleflight_sweep_interval_s=30`, `nlp_singleflight_event_max_age_s=60`, `nlp_singleflight_max_inflight=2048`, `nlp_pod_rss_max_mb=2048`, `nlp_lexicon_swap_atomicity="all_or_nothing"`, `nlp_humanizer_breaker_scope="pod"`, `nlp_log_max_unredacted_str_len=64`, `nlp_spool_payload_pii_strip=true`, `predict_citation_hmac_key_path="infra/predict/citation_hmac.key"`, `predict_citation_hmac_key_grace_s=86400`, `nlp_predict_citation_hmac_required="warn"`, `nlp_boot_budget_s=30`, `nlp_boot_liveness_grace_s=60`, `nlp_shutdown_grace_s=20`, `nlp_confidence_band_lower=0.55`, `nlp_confidence_band_upper=0.75`, `nlp_summary_calibration_mismatch_policy="note"`, `nlp_lexicon_feed_max_supported_schema_version=1`. Triangle-test extends. Go-side `TestEnvSync` covers `predict_citation_hmac_*` (gateway will eventually publish via Phase 9 §9.15) and `nlp_humanizer_max_latency_ms` (already covered by §10.0 inequality).

#### 10.21.13 New `nlp.event.v1` and `nlp.alert.v1` kinds + DoD additions

- [ ] **New `nlp.event.v1` kinds** (open-enum, registered): `cold_start_stage`, `confusables_resolved`, `singleflight_event_swept`, `lexicon_old_generation_evicted`. Per-kind sub-schemas under `ai/swarm/sdk/schemas/nlp.event.v1/<kind>.json`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered): `nlp_intent_model_sha_mismatch` (critical), `nlp_lexicon_atomic_swap_failed` (error), `nlp_singleflight_overflow` (warn), `nlp_template_render_used_raw_user_text` (critical), `nlp_spool_replay_text_unavailable` (warn), `nlp_citation_signature_verify_failed` (critical), `nlp_cold_start_timeout` (critical), `nlp_lexicon_feed_schema_too_new` (warn).
- [ ] **DoD proof tests aggregate** (new in §10.21, all required for Phase 10 closure):
  - §10.21.1 — 6 tests (determinism + version pin + greedy parity)
  - §10.21.2 — 6 tests (memory lifecycle + AST guards)
  - §10.21.3 — 3 tests (atomic swap + xref + lock-hold)
  - §10.21.4 — 5 tests (breaker scope + lock ordering + AST guards)
  - §10.21.5 — 4 tests (confusables + bidi + password-bypass + SHA pin)
  - §10.21.6 — 3 tests (template lint widened + finalize guard + canonical citation form)
  - §10.21.7 — 7 tests (PII filter + spool + audit whitelist + dir modes)
  - §10.21.8 — 4 tests (citation HMAC verify under warn/enforce + key rotation)
  - §10.21.9 — 5 tests (readiness staging + budget + jinja warm + drain)
  - §10.21.10 — 4 tests (band intervals + float dtype + summary mismatch policy)
  - §10.21.11 — 6 tests (patcher boundary + RFC7807 mapping + 3 K8s probes + Phase 16 schema bump + tier×humanizer + LeagueCatalog import boundary)
  - **Total: ≈ 53 new proof tests added on top of the §10.20 baseline.**
- [ ] **Chart compatibility additions.** Pin `numpy` wheel version, `fasttext` wheel version, Unicode TR39 `Confusables.txt` SHA, `python-crfsuite` wheel version (already implied at §10.20 item 17 — restated here as binding floor).
- [ ] **`make swarm.demo.nlp` extends** to exercise: (a) confusables-fold path (Cyrillic а in a team name); (b) lexicon swap fail-revert (corrupt one of 6 files); (c) citation-signature warn-mode missing-key (asserts alert fires, render proceeds); (d) cold-start staging (every stage event observed in order). All within the < 30s compose budget (per §10.20 item 16).

### 10.22 Turkish-language input robustness (binding addendum — "messy Turkish" floor)

> **Why this addendum exists.** §10.1–§10.21 build a deterministic,
> integrity-clean pipeline. They do **not** by themselves guarantee that
> real-world Turkish input — typed on a US keyboard with no diacritics,
> in colloquial register, with attached/detached `de`/`da`/`ki`/`mi`
> particles in the wrong places, with omitted apostrophes on proper-noun
> suffixation, mixed with English brand and league names, abbreviated
> ("GS-FB", "RM"), or written in regional dialect — is parsed correctly.
> §10.22 is the binding **language-quality floor**: any Phase 10
> deployment that ships without these gates may pass §10.21 hardening
> tests yet still mis-route the median Turkish football fan's query.
>
> **Doctrine reminder.** Per AGENTS.md Rule 4 (smallest model that
> works) and CLAUDE.md (no LLM in decision paths), every rule below is
> **deterministic** — table-driven, tokenizer-driven, regex-driven, or
> CRF-feature-driven. The humanizer LLM (§10.8) **never** participates
> in the input-understanding side of the pipeline. The §10.4 fastText
> classifier is the only ML in the input path, and §10.21.1 already
> pinned its determinism floor. Everything in §10.22 hardens the
> deterministic path **before** the classifier sees the text.
>
> **Single source for the rules.** Every table referenced below lives
> at `ai/nlp/lang_tr/` (NEW directory created in this phase): one YAML
> per rule family, frozen-via-SHA, hot-reloadable through the same §10.2
> atomic-swap mechanism (extended to cover this directory in
> §10.22.14). LeagueCatalog (Phase 13a) remains the sole source of
> canonical team / league / competition / player names — §10.22 only
> adds **how the user might spell those names wrong** and how to recover
> the canonical form.

#### 10.22.1 ASCIIfication tolerance (no-diacritic Turkish input)

- [ ] **Real failure mode §10.3 underspecifies.** Default Turkish PC users
  type without `ç ğ ı ö ş ü` (and almost never the rare `â î û`):
  *"galatasaray fenerbahce maci tahmin"*, *"besiktas trabzon ne zaman
  oynuyor"*, *"unlu santrforun cezasi var mi"*. The diacritic-restore
  table in §10.3 is real but the **integration contract** is missing:
  what happens when a token has multiple plausible restorations
  (*"sik" → "şık"* or *"sık"*; *"ucu" → "üçü"* or *"ucu"*), and how
  does the gazetteer behave under restored vs unrestored ambiguity.
- [ ] **Two-stage restoration policy.** §10.3 already pins the
  frequency-tie-break ratio (`cfg.nlp_diacritic_tie_break_ratio=1.5x`).
  §10.22.1 pins the **integration**: (a) gazetteer pass (§10.5) runs
  **twice** — first against the raw-ASCIIfied lexicon (every alias is
  also stored in its `unidecode`d form via the build pipeline of §10.2),
  then against the restored form; (b) longest-non-overlapping match
  across both passes; (c) if both passes hit different canonicals,
  prefer the restored-form hit ONLY when its frequency-weighted
  confidence exceeds the ASCII hit by `cfg.nlp_ascii_vs_restored_margin=0.2`.
- [ ] **ASCIIfied alias index built at lexicon-load.** `make nlp.lexicon-build`
  emits a sibling `*.tr.ascii.idx` per lexicon file: `dict[ascii_alias →
  list[(canonical_id, original_alias, frequency_score)]]`. Conflict
  exposed at build time: when two different canonicals share an
  ASCIIfied alias (*"saray"* maps to "Galatasaray" and "Bağdat Sarayı"),
  build refuses unless an `entities_negative.tr.yaml` rule covers the
  ambiguity. Operator either resolves the disambiguator or accepts an
  explicit allow-list entry in `ai/nlp/lexicon/_ascii_collisions.tr.yaml`.
- [ ] **Hard-call vs soft-call restoration.** Tokens with frequency >
  `cfg.nlp_diacritic_hard_call_min_freq=10000` (per `tr_word_freq.txt`)
  → restore even when ratio fails (the dominant form is overwhelmingly
  correct: *"futbol" never means anything else*). Below threshold →
  preserve original + flag to entity resolver.
- [ ] **Per-character risk scoring.** Some letter swaps are far more
  ambiguous than others (*"i↔ı"* loses information; *"u↔ü"* often
  preserves meaning; *"o↔ö"* shifts vowel class which can break suffix
  harmony downstream). Restoration policy carries a per-character risk
  weight from `ai/nlp/lang_tr/diacritic_risk.tr.yaml`; total token risk
  > `cfg.nlp_diacritic_max_risk_per_token=2.5` → keep ASCII form even
  if a single restoration is unique.
- [ ] **Proof:** `test_nlp_ascii_pass_resolves_galatasaray_no_diacritics`
  (corpus 100 queries), `test_nlp_ascii_collision_build_refuses_without_allowlist`,
  `test_nlp_diacritic_restore_prefers_high_freq_form`,
  `test_nlp_diacritic_high_risk_token_keeps_ascii`,
  `test_nlp_double_pass_gazetteer_picks_longer_match` (parameterized 20 cases).

#### 10.22.2 Apostrophe discipline on proper-noun suffixation

- [ ] **Real failure mode.** Turkish writes proper-noun + suffix with an
  apostrophe (*"Galatasaray'ın"*, *"Real Madrid'e"*), but users
  routinely omit it (*"Galatasarayın"*, *"Real Madride"*) or place it
  wrongly (*"Galata'sarayın"*, *"Realmadrid'in"*). §10.5 gazetteer
  longest-match against an unkeyed alias list misses the suffixed form,
  and §10.7 `match_label`/`team` filter renders the OUTPUT incorrectly
  if the apostrophe rule isn't applied symmetrically.
- [ ] **Input-side suffix-stripper.** Pre-gazetteer step:
  `ai/common/text/turkish.py::strip_proper_noun_suffix(token)` returns
  `(stem, suffix_class)` for any token matching the pattern
  `^[A-ZÇĞİÖŞÜ][^']*('?)([a-zçğıiöşü]{1,4})$` where the trailing 1–4
  lowercase chars match a known suffix family (genitive, dative,
  accusative, locative, ablative, plural, person-marker). The stripped
  stem is what goes through the gazetteer; the suffix is preserved as
  a slot annotation `entities[].grammatical_suffix` so the answer
  generator (§10.7) can reproduce it correctly.
- [ ] **Output-side filter discipline.** Every Jinja2 morphology filter
  (`dative`, `accusative`, `locative`, `ablative`, `genitive`) MUST
  inject the apostrophe when the stem is in the proper-noun set
  (LeagueCatalog teams + leagues + players + competitions + venues).
  Filter signature changes from `dative(name)` to `dative(name,
  proper=False)`; `match_label` / `team` filters auto-set
  `proper=True`. AST guard `test_nlp_morph_filters_set_proper_for_canonical_entities`
  asserts every emit site uses the right flag.
- [ ] **Foreign-stem apostrophe rule.** Non-Turkish proper nouns ending
  in a consonant cluster that doesn't match Turkish vowel harmony
  (*"Manchester City"*, *"Bayern"*, *"PSG"*) MUST always carry the
  apostrophe before the suffix; the rule is "if last vowel of stem is
  ambiguous in TR vowel-class system, use back-vowel suffix and
  apostrophe" (e.g., *"PSG'ye"* not *"PSG'ye"*-with-front-vowel). Table
  at `ai/nlp/lang_tr/foreign_stem_overrides.tr.yaml` overrides the
  vowel-harmony default per known stem (covers ~200 frequent foreign
  team / league names; build refuses if an entry doesn't resolve to a
  LeagueCatalog canonical).
- [ ] **Apostrophe-noise tolerance.** Input may contain typographic
  apostrophes `'`, `'`, `'`, `` ` ``, `´` — §10.1 step 5 normalizes
  to ASCII `'`. AST guard asserts `'` is the only apostrophe character
  reaching the suffix-stripper.
- [ ] **Proof:** `test_nlp_strip_suffix_recovers_galatasarayin_to_galatasaray`,
  `test_nlp_strip_suffix_recovers_realmadride_to_real_madrid`,
  `test_nlp_morph_filter_renders_apostrophe_for_proper_noun`
  (20-case golden table including *"Manchester City'nin"*, *"PSG'ye"*,
  *"Trabzonspor'a"*), `test_nlp_apostrophe_normalization_to_ascii`,
  `test_nlp_foreign_stem_overrides_resolve_to_catalog`.

#### 10.22.3 Buffer-consonant renderer (-y / -n / -s / -ş)

- [ ] **Real failure mode.** When a Turkish suffix beginning with a
  vowel (`-a`, `-e`, `-ı`, `-i`, `-u`, `-ü`) attaches to a stem ending
  in a vowel, a buffer consonant is required: `Trabzon` + `-a` →
  `Trabzon'a`, but `Galatasaray` + `-a` → `Galatasaray'a` (no buffer
  needed because stem ends in `y`). For *"Bursa"* + `-a` →
  `Bursa'ya` (insert `y`); for possessive `-ı` after vowel-ending
  stem: *"Bursa"* + `-ı` → `Bursa'sı` (insert `s`). Without this rule
  the answer text reads non-grammatically, which is the most-flagged
  category in human review of Turkish-NLP outputs.
- [ ] **`buffer_consonant(stem, suffix_class) -> str` helper.**
  Single source at `ai/common/text/turkish.py`; called from every
  morphology filter. Decision matrix:
  ```
  stem_last_char ∈ vowels AND suffix_class ∈ {dat, acc, abl} → 'y'
  stem_last_char ∈ vowels AND suffix_class == possessive_3sg  → 's'
  stem_last_char ∈ vowels AND suffix_class == compound_marker → 'n'
  stem_last_char ∈ vowels AND suffix_class == verb_passive_3sg → 'ş'
  otherwise → ''
  ```
  Tabled in `ai/nlp/lang_tr/buffer_consonant.tr.yaml` for testability;
  AST asserts the helper consults the table (no hardcoded branches).
- [ ] **Suffix-vowel-class lookup.** Suffix vowel chosen by 4-way
  harmony (front-rounded / front-unrounded / back-rounded /
  back-unrounded) from `ai/nlp/lang_tr/vowel_harmony_4way.tr.yaml`.
  Already implicit in §10.7 filters; §10.22.3 makes the table the
  single source and asserts every filter consults it (no inline vowel
  literals — AST guard).
- [ ] **Foreign-stem opt-out.** Some foreign stems are pronounced with
  a final consonant even though spelled with a vowel (*"Lyon"* — final
  `n` is silent in French but pronounced in Turkish; suffix attaches
  as if consonant-final). Per-stem override in
  `foreign_stem_overrides.tr.yaml::pronunciation_class`.
- [ ] **Golden table proof.** `ai/nlp/lang_tr/golden/buffer_golden.yaml`
  — 300 rows of `(stem, suffix_class, expected_output)` covering every
  frequent team / league / venue / player name in the v1 catalog.
  100% pass required by §10.20 / §10.22 DoD.
- [ ] **Proof:** `test_nlp_buffer_consonant_table_drives_decision`
  (AST), `test_nlp_buffer_golden_table_100_percent`,
  `test_nlp_buffer_consonant_handles_lyon_foreign_pronunciation_override`,
  `test_nlp_no_inline_vowel_literals_in_morph_filters` (AST scan
  rejects regex / string literal containing only vowel chars in
  `ai/nlp/jinja_filters_tr.py`).

#### 10.22.4 Particle disambiguation: "de/da", "ki", "mi/mı/mu/mü"

- [ ] **Real failure mode — the most common Turkish writing error.**
  - **`de` / `da` (also vs locative)**: *"Galatasarayda maç var"* (=
    "match at Galatasaray"; locative — must be ATTACHED) vs
    *"Galatasaray da kazandı"* (= "Galatasaray, too, won"; conjunction
    — must be DETACHED). Users routinely write the wrong form;
    intent / entity extractor must read the **intended** sense.
  - **`ki`**: *"evdeki maç"* (= "the match at home"; relative — must
    be ATTACHED) vs *"söyledi ki ..."* (= "he said that ..."; complement
    — must be DETACHED).
  - **`mi/mı/mu/mü`**: question particle — must always be SEPARATE
    (*"oynuyor mu?"*); users frequently attach (*"oynuyormu?"*).
- [ ] **Token-level normalizer.** New step **8a** in §10.1 (between
  tokenization and typo correction; doesn't change semantic order
  because §10.1 step 8 is "typo correction" — particle normalization
  is a more structural pre-typo pass):
  - Detach attached `mi/mı/mu/mü` from any token where the substring
    matches the question-particle vowel-harmony rule AND removing it
    leaves a valid Turkish-shaped stem (vowel-final or
    consonant-final, respects vowel harmony of stem).
  - Attached vs detached `de/da` / `ki`: do NOT silently re-attach;
    instead carry an annotation `tokens[].particle_attachment_repaired`
    so the §10.4 fastText classifier sees the canonical form (always
    detached) AND the §10.5 gazetteer can match either form.
  - **Never** auto-detach `de/da` from a stem where doing so changes
    the canonical entity (e.g., do NOT split *"Edirne"* → *"Edirn"* +
    *"e"* — `Edirne` is an indivisible canonical city name).
    Decision rule: only normalize when the stem-after-detach is in
    the lexicon stem-set OR is a verb root recognised by the Zemberek
    rules subset.
- [ ] **Particle rules in `ai/nlp/lang_tr/particles.tr.yaml`** — single
  source: `mi_variants: [mi, mı, mu, mü, miyim, misin, miyiz, ...]`
  with vowel-harmony match per stem class. Same for `de_da_pairs` and
  `ki_pairs`. AST asserts no hardcoded particle string in `_normalize.py`.
- [ ] **Adversarial caution.** Particle normalization is adversarially
  exploitable: *"sen de gel"* (= "you come too") vs *"sende gel"* (=
  ungrammatical). Normalizer must NEVER force-detach in cases that
  generate a non-Turkish-shaped stem. Test corpus
  `ai/tests/fixtures/turkish_particles.yaml` (≥ 60 rows) covers
  positive AND negative cases, with `expected_change: bool`.
- [ ] **Proof:** `test_nlp_question_particle_detached_from_oynuyormu`,
  `test_nlp_de_da_attachment_recovered_for_galatasarayda_locative`,
  `test_nlp_de_da_not_split_when_stem_is_canonical_entity`
  (Edirne / Adana / Konya regression set), `test_nlp_ki_attached_in_evdeki`,
  `test_nlp_particle_rules_loaded_from_yaml_only` (AST),
  `test_nlp_particle_normalizer_adversarial_corpus` (60-row
  parametrized — all positive AND negative outcomes pinned).

#### 10.22.5 Colloquial / dialect / abbreviation expansion

- [ ] **Real failure mode.** Spoken-Turkish-typed-on-keyboard:
  *"yapıcaz"* (= "yapacağız" / "we will do"), *"geliyo"* (= "geliyor"),
  *"di mi"* / *"dimi"* (= "değil mi"), *"bişey"* / *"birşey"* (= "bir
  şey"), *"napıyo"* (= "ne yapıyor"), *"abi"* (vocative; should not
  carry semantic weight). Plus team abbreviations: *"GS"* → Galatasaray,
  *"FB"* → Fenerbahçe, *"BJK"* → Beşiktaş, *"TS"* → Trabzonspor — and
  composite *"GS-FB"* → match between the two.
- [ ] **Two-table normalizer.** `ai/nlp/lang_tr/dialect.tr.yaml` (token
  → canonical-token-sequence; e.g., *"yapıcaz" → "yapacağız"*) + the
  existing `dialects.tr.yaml` per §10.2 (which becomes a **subset**
  for entity-related dialect — team-name abbreviations). Two tables,
  one purpose split: linguistic vs entity. Build asserts they are
  disjoint (no token in both).
- [ ] **Abbreviation table format.** `ai/nlp/lang_tr/abbreviations.tr.yaml`:
  `{abbreviation, expansion_canonical_id, ambiguity_class ∈ {hard,
  soft}, requires_co_token: [...]}`. Hard = always expand (e.g.,
  "GS" never means anything else in football context). Soft = expand
  only with required co-token (e.g., "RM" could be Real Madrid OR
  "ruh hali" — requires `[madrid, real, futbol, maç]` neighbour). The
  ambiguity class is the input to the §10.5 conflict resolver.
- [ ] **Composite-abbreviation pattern.** *"GS-FB"*, *"FB vs BJK"*,
  *"GS Fener"* — handled at the **dispatcher** (§10.6), not at the
  tokenizer. After gazetteer resolution, when two team entities resolve
  AND the token between them matches `cfg.nlp_match_separator_pattern`
  (default `^(-|–|—|vs\.?|x|×|/)$`), the dispatcher promotes the pair
  to a `match_lookup` slot (Phase 4 storage agent answers via
  `data.fixture_lookup` keyed on `team_a_id, team_b_id`). Without a
  separator (*"GS Fener"*), the dispatcher requires a co-token like
  *"maç"* / *"derbi"* / *"karşılaşma"* to trigger the same path;
  otherwise it falls through to disambiguation.
- [ ] **Vocative / filler stripping.** Tokens like *"abi"*, *"reis"*,
  *"hocam"*, *"bro"*, *"kanka"* are dropped from the token stream
  pre-classifier (do NOT influence intent). Table at
  `ai/nlp/lang_tr/vocative_filler.tr.yaml`; build asserts every token
  is documented; AST asserts the strip step exists and consults the
  table.
- [ ] **Proof:** `test_nlp_dialect_yapicaz_expands_to_yapacagiz`,
  `test_nlp_abbreviation_gs_resolves_to_galatasaray`,
  `test_nlp_abbreviation_rm_requires_co_token`,
  `test_nlp_match_separator_promotes_to_match_lookup`
  (parametrized over `[-, –, —, vs, x, ×, /]`),
  `test_nlp_vocative_filler_dropped_does_not_change_intent`,
  `test_nlp_dialect_and_entity_dialect_tables_are_disjoint` (build).

#### 10.22.6 Date / time / score / weekday TR-specific parsing

- [ ] **Real failure mode §10.5 underspecifies.** Turkish users write:
  - **Times**: *"21:30"*, *"21.30"*, *"21,30"*, *"21de"*, *"saat 9"*,
    *"akşam 9"*, *"21'de"*, *"21'inde"* (locative inflection on
    numerical clock).
  - **Dates**: *"27/04"*, *"27.04"*, *"27 nisan"*, *"27 Nisan"*,
    *"27nisan"*, *"27.04.2026"*, *"27 nisan 2026"*, *"önümüzdeki
    cuma"*, *"haftaya"*, *"hafta sonu"*, *"sonraki hafta"*,
    *"gelecek pazartesi"*. Year is frequently omitted; default
    resolution = "next occurrence in [now, now + `cfg.nlp_date_default_window_days=180`]".
  - **Scores**: *"1-0"*, *"1:0"*, *"1 0"*, *"bir sıfır"* (Turkish
    numerals), *"1'e 0"*, *"1-0'lık"* (with possessive).
  - **Weekdays**: *"pazartesi"* / *"Pazartesi"* (TDK convention is
    lowercase except sentence-start); *"pzt"* / *"sal"* / *"çar"* /
    *"per"* / *"cum"* / *"cmt"* / *"paz"* abbreviations.
- [ ] **Per-class CRF feature templates** (extends §10.5 step 2). One
  feature template file per class (`time.tmpl`, `date.tmpl`,
  `score.tmpl`, `weekday.tmpl`) under `ai/nlp/lang_tr/crf_templates/`;
  trained CRF model carries the template hash in its sidecar so model
  + template stay in sync (refuse-load on hash mismatch — mirrors
  §10.21.1 fastText SHA pin).
- [ ] **Number-word resolver.** `ai/nlp/lang_tr/number_words.tr.yaml`
  — table for *"sıfır"* → 0 ... *"yirmi"* → 20 plus *"otuz"*,
  *"kırk"*, ..., *"yüz"*, *"bin"*, *"milyon"*; composite (*"yirmi
  bir"* → 21) computed via `ai/common/text/turkish.py::parse_number_word`.
  Used by score parser to accept *"bir sıfır"*.
- [ ] **Locative-on-clock disambiguation.** *"21'de"* (= "at 21:00")
  vs *"21'i"* (= "the 21st [of the month]") — distinguished by suffix
  class, not just regex. Suffix-stripper from §10.22.2 reused.
- [ ] **Default time-of-day resolver.** *"akşam"* + numerical hour
  resolves to PM if hour < 12; *"sabah"* / *"öğleden önce"* → AM;
  *"gece yarısı"* → 00:00. Table at
  `ai/nlp/lang_tr/time_of_day.tr.yaml`. Match-time-typical bias:
  unqualified hour 1–11 in football context defaults to PM (matches
  rarely play AM); operator-tunable via `cfg.nlp_time_default_period`.
- [ ] **Date relative to now.** *"haftaya"*, *"önümüzdeki hafta"*,
  *"gelecek hafta"*, *"hafta sonu"*, *"yarın"*, *"öbürsü gün"* /
  *"öbür gün"*, *"dün"*, *"evvelki gün"* — all resolved against
  `cfg.nlp_clock_now()` (already pinned at §10.5 for testability).
- [ ] **Year-omission default.** Fixture lookup defaults to "next
  occurrence in [now, now + `cfg.nlp_date_default_window_days=180`]";
  if no fixture matches → disambiguation answer enumerating top-3
  candidates with explicit year.
- [ ] **Proof:** `test_nlp_time_dot_separator_resolves_2130`,
  `test_nlp_time_locative_21de_resolves_to_2100`,
  `test_nlp_date_27_nisan_no_year_resolves_to_next_occurrence`,
  `test_nlp_score_bir_sifir_word_form_parses_to_1_0`,
  `test_nlp_weekday_abbreviation_cmt_resolves_to_saturday`,
  `test_nlp_weekday_case_insensitive`,
  `test_nlp_aksam_9_resolves_to_2100`,
  `test_nlp_haftaya_resolves_to_now_plus_7d_bounded`,
  `test_nlp_crf_template_hash_matches_model_sidecar` (refuse-load on
  drift).

#### 10.22.7 Match-pattern parsing (multi-format team-vs-team)

- [ ] **Real failure mode.** Users describe a fixture in many ways:
  - *"Galatasaray-Fenerbahçe"*, *"Galatasaray Fenerbahçe maçı"*,
    *"GS - FB"*, *"GS-FB derbisi"*, *"galatasaray vs fenerbahce"*,
    *"galatasaray ile fenerbahçe"*, *"galatasaray fenere karşı"*.
  - Including a date / matchday: *"27 Nisan GS-FB"*, *"derbi
    cumartesi"*, *"haftaya Trabzon Beşiktaş"*.
- [ ] **Dispatcher-side composite-entity resolver.** Already partially
  pinned in §10.22.5 (separator-driven). §10.22.7 expands to:
  - Word-bridges: `cfg.nlp_match_word_bridges = ["ile", "karşı",
    "vs", "vs.", "ve"]` — when two team entities are separated by
    one of these tokens (with optional intervening punctuation), they
    promote to a `match_lookup` slot.
  - Adjacency rule: two team entities with no intervening sentence
    boundary AND a co-token `match_co_tokens =
    ["maç", "maçı", "derbi", "karşılaşma", "fikstür", "oyun"]` within
    `cfg.nlp_match_adjacency_radius=4` tokens → also promotes.
  - Date / matchday adjacency: a resolved date/time entity within
    `cfg.nlp_fixture_date_adjacency_radius=8` tokens of a team-pair
    entity is bound to it as the fixture filter.
- [ ] **Order-insensitive fixture lookup.** Once `(team_a_id, team_b_id)`
  resolves, the storage-agent query (Phase 4) must be order-insensitive
  (matches both home / away). Forward contract: `data.request.v1{kind=
  fixture_lookup, team_pair: [a_id, b_id]}` where the pair is
  alphabetically sorted before publish (deterministic dedup-friendly).
- [ ] **Proof:** `test_nlp_match_word_bridge_ile_promotes_to_match_lookup`,
  `test_nlp_match_adjacency_co_token_derbi_promotes_pair`,
  `test_nlp_date_adjacent_to_pair_binds_fixture_filter`,
  `test_nlp_team_pair_sorted_before_dispatch`
  (deterministic-dedup probe).

#### 10.22.8 Code-switching (TR / EN intermix) handling

- [ ] **Real failure mode.** *"manchester city formdaymış"*,
  *"premier league standings"*, *"fixture nasıl?"*,
  *"city'nin kadrosu"*, *"liverpool maçında kim sakat?"* — English
  team / league / common-noun mixed with Turkish syntax. Pure-TR
  classifier may abstain or mis-classify.
- [ ] **Bilingual gazetteer pass.** Lexicon files already store
  English-canonical names (*"Premier League"*, *"Manchester City"*).
  §10.22.8 pins: gazetteer pass (§10.5) is **case-insensitive** AND
  the §10.22.1 ASCIIfied alias index covers EN spellings (a no-op
  for plain ASCII, but ensures the same code path).
- [ ] **English-token tolerance in classifier.** fastText n-gram
  features cope with EN tokens natively; §10.18 evaluation harness
  `code_switch=20` slice already gates intent accuracy on this.
  §10.22.8 raises the gate: code-switch slice MUST hit
  `cfg.nlp_intent_accuracy_floor` (=0.92) — same as the clean slice
  (was previously implicitly weaker).
- [ ] **English suffix-noise tolerance.** Users sometimes English-pluralize
  Turkish stems (*"galatasaraylar"* — ungrammatical) or vice-versa
  (*"city'nin"* — Turkish suffix on EN stem, handled by §10.22.2
  apostrophe rule + §10.22.3 buffer-consonant via foreign-stem
  override). Test corpus `ai/tests/fixtures/turkish_code_switch.yaml`
  covers ≥ 30 mixed-language queries with `expected_intent` and
  `expected_entities`.
- [ ] **NEVER translate the user's text.** No machine translation
  layer in either direction; humanizer §10.8 is bound to TR-only
  output via the EN-blocklist in proofreader gate #2 (§10.9). AST
  asserts no `translate(`, `translation`, `googletrans`, `deep_translator`
  symbol anywhere under `ai/swarm/agents/nlp/**` and `ai/nlp/**`.
- [ ] **Proof:** `test_nlp_code_switch_manchester_city_resolves_to_canonical`,
  `test_nlp_code_switch_intent_accuracy_meets_floor`
  (full code-switch corpus), `test_nlp_no_translation_dependency`
  (AST), `test_nlp_english_pluralized_galatasaraylar_recovers_to_galatasaray`.

#### 10.22.9 Offensive language / slang gate

- [ ] **Real failure mode.** Users curse, joke, abuse the bot. Two
  sub-cases that need different handling:
  - **Direct abuse at the bot** — e.g., *"amk yapay zeka"* — must
    not be parroted back, must not fail loud, must route gracefully.
  - **Offensive content as part of a real query** — e.g.,
    *"hakemin amına koyim niye penaltı vermedi"* (= angry but
    contains a real intent: penalty / referee question). The intent
    extraction must succeed; the offensive tokens are stripped from
    any answer text but DO NOT block answering.
- [ ] **Closed taxonomy.** `ai/nlp/lang_tr/offensive.tr.yaml` —
  three classes: `mild` (everyday vulgar; e.g., *"saçmalık"*, *"abi
  ya"*) — no action; `slur` (targeted slurs incl. ethnic / sexist /
  homophobic) — strip-and-answer + `nlp.alert.v1{kind=
  nlp_slur_in_input, severity=warn}` (debounced — operator
  visibility, not user-visible block); `severe_threat` (death
  threats, doxxing patterns, instructions to harm) — route to
  `meta.adversarial`, do NOT answer the question.
- [ ] **Tokenizer-level stripping for `slur` class.** Replace each
  matched token with a sentinel `<STRIPPED>` BEFORE classifier sees
  text (so the classifier doesn't learn slur → intent association).
  Sentinel acts as a generic noise token; entity / intent extraction
  proceeds normally on the remaining stream.
- [ ] **NEVER quote-back any class.** §10.21.6 already forbids raw
  user text in templates; §10.22.9 reasserts: even sanitized,
  the offensive tokens are NEVER reproduced in `qa.answer.v1`.
  Proofreader §10.9 gate #4 extends to scan for offensive-table
  matches in the rendered answer (defense-in-depth — should never
  fire because templates don't carry user text, but if it does, the
  answer is blocked + critical alert).
- [ ] **Adversarial-jailbreak echoes.** Already covered by §10.9
  gate #5 (forbidden phrases). §10.22.9 adds the `slur` table to
  the same gate (single source — the gate consults both).
- [ ] **Proof:** `test_nlp_slur_token_stripped_before_classifier`,
  `test_nlp_severe_threat_routes_to_adversarial`,
  `test_nlp_mild_offensive_does_not_block`,
  `test_nlp_proofreader_blocks_slur_in_rendered_answer`
  (defense-in-depth fail-loud), `test_nlp_offensive_table_loaded_with_three_classes`.

#### 10.22.10 Foreign-team transliteration variants

- [ ] **Real failure mode.** *"Bayer Münih"* / *"Bayer Munih"* /
  *"Bayern"* (the user's confusion between Bayer Leverkusen and
  Bayern München is real); *"Mancester"* / *"Mancester Citi"* /
  *"Manchester Citi"* / *"M. City"* / *"Man City"*; *"Inter"* /
  *"Internazionale"* / *"Inter Milan"*; *"Atletico"* / *"Athletico"*
  (commonly confused with Athletic Bilbao); *"Saint Etienne"* /
  *"Sant Etienne"* / *"St Etienne"*.
- [ ] **Phonetic-collision allow-list.** `ai/nlp/lang_tr/phonetic_aliases.tr.yaml`
  — manually curated list of `(phonetic_form, canonical_id, requires_co_token?,
  confused_with: [...])`. The `confused_with` field drives the
  `entities_negative.tr.yaml` rules: *"Bayer Münih"* alone resolves
  to Bayern München with a `nlp.event.v1{kind=
  phonetic_alias_resolved_with_confusion_warning, confused_with:
  ['Bayer Leverkusen']}` event so operators can see how often the
  user's "wrong" spelling is being silently corrected.
- [ ] **Non-Latin script support (deferred but pinned).** Arabic /
  Cyrillic / Greek football terms not in scope at v1; gazetteer
  build refuses any entry with non-Latin characters AND no
  Latin-transliteration sibling. Forward hook: locale `tr-TR` only
  at v1 per §10.17; future locale additions reopen the question.
- [ ] **Build-time collision report.** `make nlp.lexicon-build`
  emits `data/nlp/build_reports/phonetic_collisions.md` listing
  every `confused_with` pair. Reviewed in PR by humans (CI-gated:
  PR refuses merge if the file changed without a same-PR
  acknowledgement file `ai/nlp/lexicon/_phonetic_review.md` updated).
- [ ] **Proof:** `test_nlp_phonetic_bayer_munih_resolves_to_bayern_with_event`,
  `test_nlp_phonetic_table_entries_resolve_to_catalog`,
  `test_nlp_phonetic_collisions_report_generated`,
  `test_nlp_no_non_latin_script_in_v1_lexicon` (build).

#### 10.22.11 Locale-tag normalization & fallback chain

- [ ] **Real failure mode §10.17 underspecifies.** API gateway honors
  `Accept-Language`; users may send `tr`, `tr-TR`, `tr-CY` (Cyprus),
  `tr-DE` (German Turkish diaspora), `tr-NL`, or even malformed
  tags. v1 supports only `tr-TR`; everything else MUST graceful-fall.
- [ ] **Fallback chain.** `cfg.nlp_locale_fallback_chain =
  ["tr-TR"]` (closed list at v1). Resolver:
  1. Parse incoming tag via BCP-47 rules (lowercase region,
     uppercase country); reject malformed → fall through.
  2. Exact match in chain → use it.
  3. Language-only match (`tr-*` → `tr-TR`) → use base locale.
  4. No match → `cfg.nlp_default_locale=tr-TR` + emit
     `nlp.event.v1{kind=locale_fallback_used, requested, resolved}`
     (debounced 60s per requested tag — bounded cardinality).
- [ ] **Per-request override.** API surfaces an explicit
  `?locale=tr-TR` query param (Phase 9); param > header > default.
  Forward-compat: when a second locale is added, no schema change
  needed — just update the chain.
- [ ] **Proof:** `test_nlp_locale_tr_only_falls_back_to_tr_tr`,
  `test_nlp_locale_tr_de_falls_back_with_event`,
  `test_nlp_locale_malformed_falls_back_default`,
  `test_nlp_locale_param_overrides_header`.

#### 10.22.12 Lexicon-feed integrity (Phase 16 supply-chain signature)

- [ ] **Real attack §10.21.8 / §10.21.11 partially miss.** §10.21.8
  signs `predict.approved.v1` citations; §10.21.11 forces
  feed-schema-version refusal. Neither covers the case where Phase 16
  emitter publishes a **lexicon feed** with the same schema_version
  but adversarial / poisoned content (e.g., a malicious team alias
  mapping that re-routes "Galatasaray" queries to a different
  canonical_id; or a `dialects.tr.yaml` rule that injects an
  attacker-controlled token sequence into common queries).
- [ ] **Feed signature.** Phase 16 emitter signs every lexicon feed
  payload with `cfg.nlp_lexicon_feed_hmac_key_path` (mode 0400,
  shared between emitter and NLP via secret-mount; rotated via
  `make nlp.rotate-lexicon-key` with 24h dual-acceptance window —
  mirrors §10.21.8 citation-key rotation). NLP REFUSES to swap a
  feed payload that fails signature verify; emits `nlp.alert.v1{kind=
  nlp_lexicon_feed_signature_invalid, severity=critical}`. Bypass
  switch: `cfg.nlp_lexicon_feed_signature_required ∈ {off, warn,
  enforce}` default `warn` at v1 (consistent with §10.21.8 rollout
  doctrine), `enforce` post-Phase-14.
- [ ] **Fail-closed default for sensitive lexicons.** `markets.tr.yaml`
  AND `entities_negative.tr.yaml` ALWAYS require valid signature
  regardless of the global `*_required` setting (rationale: market
  enum + disambiguators are the highest-leverage corruption targets
  — a single bad market mapping mis-routes every betting query).
  Hard-coded list at `ai/swarm/agents/nlp/_critical_lexicons.py`.
- [ ] **Signature key rotation runbook.** `make nlp.rotate-lexicon-key`
  shipped alongside the agent; same dual-window pattern as
  §10.21.8. Operator runbook entry in `docs/guides/nlp_runbook.md`
  (NEW file in this phase).
- [ ] **Build-pipeline signature.** `make nlp.lexicon-build` emits
  signed bundles for non-feed-driven path too (when running from
  in-repo source pre-Phase-16); SHA-only verify at load (no HMAC)
  for in-repo flow, HMAC verify for Phase 16 feed flow. Boundary
  test: NLP runtime never trusts a SHA-only artifact when running
  in `cfg.nlp_lexicon_source ∈ {file, feed}` mode `feed`.
- [ ] **Proof:** `test_nlp_lexicon_feed_invalid_signature_refused_in_enforce`,
  `test_nlp_lexicon_feed_warn_mode_swaps_with_alert`,
  `test_nlp_critical_lexicons_always_enforce_regardless_of_global_mode`,
  `test_nlp_lexicon_key_rotation_dual_acceptance_window`,
  `test_nlp_lexicon_runtime_rejects_sha_only_artifact_in_feed_mode`.

#### 10.22.13 Turkish-quality telemetry & error-class metrics

- [ ] **Per-rule-class counters** (cardinality bounded — closed set):
  - `nlp_input_repair_total{class ∈ {ascii_restored, particle_detached_mi,
    particle_repaired_de_da, particle_repaired_ki, apostrophe_inserted,
    suffix_recovered, abbreviation_expanded, dialect_expanded,
    vocative_dropped, slur_stripped, code_switch_token, phonetic_alias_resolved,
    confusables_folded}}` — counter incremented per repair event.
  - `nlp_input_repair_density` histogram of (repairs / token-count)
    per query — high values indicate degrading input quality (or
    classifier confusion); §10.18 evaluation harness gates p95 ≤
    `cfg.nlp_repair_density_p95_max=0.5` on the clean slice.
  - `nlp_disambiguation_offered_total{cause ∈ {low_intent_conf,
    ambiguous_entity, ambiguous_match_pair, ambiguous_date,
    confused_phonetic_alias}}` counter.
  - `nlp_offensive_input_total{class ∈ {mild, slur, severe_threat}}`
    counter (debounce on emit, not on count — count is always
    truthful).
- [ ] **Per-day quality dashboard.** Operator-facing aggregation over
  the above — tail of `nlp_input_repair_density` is the leading
  indicator of incoming input-quality drift (e.g., a viral tweet
  drives a flood of code-switched / dialect input). Documented in
  `docs/guides/nlp_runbook.md` with action thresholds.
- [ ] **Sampled-answer audit slice tagging.** §10.14 sampling
  extends to record the per-rule-class repair list per sampled query
  (PII-redacted: only the class names, not the original tokens).
  Allows offline correlation of "repairs applied" vs "human-judged
  answer correctness".
- [ ] **Proof:** `test_nlp_repair_counters_increment_per_class`
  (parametrized), `test_nlp_repair_density_metric_bounded_in_clean_slice`,
  `test_nlp_disambiguation_cause_bounded_enum`,
  `test_nlp_offensive_counter_truthful_under_debounce`.

#### 10.22.14 Knob inventory + DoD aggregate

- [ ] **New cfg knobs (~22, on top of §10.19 + §10.21.12):**
  `nlp_ascii_vs_restored_margin=0.2`,
  `nlp_diacritic_hard_call_min_freq=10000`,
  `nlp_diacritic_max_risk_per_token=2.5`,
  `nlp_match_separator_pattern="^(-|–|—|vs\\.?|x|×|/)$"`,
  `nlp_match_word_bridges=["ile", "karşı", "vs", "vs.", "ve"]`,
  `nlp_match_co_tokens=["maç","maçı","derbi","karşılaşma","fikstür","oyun"]`,
  `nlp_match_adjacency_radius=4`,
  `nlp_fixture_date_adjacency_radius=8`,
  `nlp_date_default_window_days=180`,
  `nlp_time_default_period="pm"`,
  `nlp_locale_fallback_chain=["tr-TR"]`,
  `nlp_lexicon_feed_hmac_key_path="infra/nlp/lexicon_feed_hmac.key"`,
  `nlp_lexicon_feed_hmac_key_grace_s=86400`,
  `nlp_lexicon_feed_signature_required="warn"`,
  `nlp_lexicon_source="file"` (file at v1; feed post-Phase-16),
  `nlp_repair_density_p95_max=0.5`,
  `nlp_lang_tr_dir="ai/nlp/lang_tr"`,
  `nlp_lang_tr_reload_s=30` (mirrors §10.2 lexicon mtime poll cadence
   for the `lang_tr/*.yaml` rule tables — same atomic-swap discipline,
   distinct lock so language-rule reload doesn't block lexicon reads).
  Triangle test extends; Go-side `TestEnvSync` covers
  `nlp_lexicon_feed_hmac_*` (Phase 16 emitter is Go-friendly per
  §16 Pivot v3 ownership — when emitter ships, the gateway-equivalent
  signature-publishing path needs the shared knob).
- [ ] **New `nlp.event.v1` kinds** (open-enum, registered):
  `phonetic_alias_resolved_with_confusion_warning`,
  `locale_fallback_used`,
  `dialect_expanded`,
  `abbreviation_expanded`,
  `particle_repaired`,
  `apostrophe_inserted`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `nlp_slur_in_input` (warn, debounced),
  `nlp_lexicon_feed_signature_invalid` (critical),
  `nlp_repair_density_anomaly` (warn — fires when 10-min rolling
   p95 of repair-density exceeds the cfg cap).
- [ ] **New build artifacts.** `data/nlp/build_reports/phonetic_collisions.md`
  (CI-tracked); `ai/nlp/lexicon/_phonetic_review.md` (PR-gated
  acknowledgement file).
- [ ] **DoD proof tests aggregate (new in §10.22):**
  - §10.22.1 — 5 tests
  - §10.22.2 — 5 tests
  - §10.22.3 — 4 tests (incl. 300-row golden table)
  - §10.22.4 — 6 tests
  - §10.22.5 — 6 tests
  - §10.22.6 — 9 tests
  - §10.22.7 — 4 tests
  - §10.22.8 — 4 tests
  - §10.22.9 — 5 tests
  - §10.22.10 — 4 tests
  - §10.22.11 — 4 tests
  - §10.22.12 — 5 tests
  - §10.22.13 — 4 tests
  - **Total: ≈ 65 new proof tests added on top of §10.20 + §10.21
    baseline.**
- [ ] **`make swarm.demo.nlp` extends** to cover the §10.22 paths:
  one query per family (ASCII-only, dropped-apostrophe,
  attached-question-particle, dialect, abbreviation, code-switch,
  date+match-pair, foreign-transliteration, locale-fallback,
  offensive-with-real-intent). All within the < 30s compose budget
  (per §10.20 item 16 — additional queries amortize via singleflight
  and L0 cache hits on shared sub-paths).
- [ ] **Documentation.** `docs/design/TURKISH_NLP.md` rewritten in
  lockstep with §10.22 — every rule table referenced here gets a
  prose explanation + worked examples in the design doc.
  `docs/guides/nlp_runbook.md` (NEW): operator-facing playbook
  covering lexicon swap, key rotation, repair-density alert
  triage, code-switch & dialect drift response. `docs` minor bump
  alongside the §10.22 land per AGENTS.md §6.1.

### 10.23 Operability, rollout, serving quality (binding addendum — "production-serving floor")

> **Why this addendum exists.** §10.0–§10.20 specify the surface
> contract; §10.21 the integrity floor; §10.22 the TR-language
> correctness floor. None of those tell us how to **roll out a new
> intent model without a 5-minute accuracy regression**, how to
> **isolate a single abusive tenant from starving the humanizer queue**,
> what to display when **7 of 10 fixtures in a summary fan-out come
> back** (and 3 timed out), how to format **"1.000 TL" vs "1,000 TL"**
> per Turkish locale convention, how to keep a screen-reader-using fan
> from getting noise-decorated emoji answers, what timezone the
> rendered "21:30" is in, how to bound the **per-request cost in tokens
> × USD**, what happens to the L0 cache when the **lexicon swaps
> mid-request on one pod but not another**, how to plan **NLP capacity
> from a 3× traffic spike**, how to **drill a full lexicon corruption
> recovery**, and what the **CVE response runbook** is when
> `python-crfsuite` ships a critical advisory at 02:00 UTC.
>
> §10.23 closes those gaps. Each rule below is operationally binding;
> none introduce ML — they are deployment, scheduling, formatting, and
> runbook contracts. The combined floor (§10.21 + §10.22 + §10.23) is
> what "production-ready Turkish-NLP plane" means in this codebase.
>
> **Doctrine reminder.** AGENTS.md Rule 5 (scale symmetry — same code
> at 1 replica or 1000), Rule 8 (phase gates — DoD is binding), and
> CLAUDE.md (no `*-latest` model IDs) all apply. Every rollout knob
> below is single-source per Rule 1; every observable per-tenant /
> per-tier metric is cardinality-bounded per §10.14.

#### 10.23.1 Multi-tenant fairness & abuse isolation inside the NLP plane

- [ ] **Real failure mode.** §10.12 cap "queue > 100 → disable
  humanizer" is global. A single noisy tenant (or compromised account)
  flooding `qa.request.v1` at 50 QPS can blow the queue → humanizer
  disabled for everyone → tier-paying users see degraded answers
  caused by another tenant's behaviour. Phase 7 rate-limit at the
  gateway exists, but it is per-IP / per-account, NOT per-NLP-stage —
  a tenant within their gateway budget can still saturate the humanizer
  GPU lease.
- [ ] **Per-tenant fair-queue at NLP intake.** `qa.request.v1` consumer
  on the NLP pod implements weighted-fair-queueing keyed by
  `cfg.nlp_fairness_key ∈ {tenant_id, account_id, ip_bucket}` default
  `account_id` (Phase 9 stamps `account_id` onto every `qa.request.v1`;
  unauthenticated → `ip_bucket` derived from /24). Each key gets one
  virtual queue with `cfg.nlp_per_tenant_inflight_max=8` concurrent
  intake slots; over-cap → request queued behind that key's own slots,
  NOT behind other tenants. Implementation: deterministic round-robin
  over the keys with non-empty queues (per AGENTS.md Rule 5 — single
  pod or 1000 pods, the same code path). Cardinality cap on tracked
  keys = `cfg.nlp_fairness_max_tracked_keys=10000` (LRU eviction with
  `nlp.event.v1{kind=fairness_key_evicted}` debounced).
- [ ] **Humanizer GPU lease fair-share.** The humanizer breaker (§10.8)
  is global; the GPU lease (§10.21.9 stage 6) is per-pod. Per-tenant
  weighted-fair scheduling extends to humanizer admission: each tenant
  gets a token-bucket of `cfg.nlp_per_tenant_humanizer_burst=4` and
  refill `cfg.nlp_per_tenant_humanizer_refill_per_s=2`. Over-budget →
  request silently degrades to template-only answer (NOT an error;
  user sees a slightly less polished sentence — degraded path is
  already proof-tested in §10.10). `degraded_reason="humanizer_tenant_budget_exceeded"`
  added to the §10.10 enum.
- [ ] **Abuse detection signal.** `nlp_tenant_intake_rate{key_class}`
  histogram (key classes: `account_paid`, `account_free`,
  `ip_anonymous`, `ip_known_proxy`) — when a single key sustains >
  `cfg.nlp_tenant_abuse_qps_threshold=10` for `cfg.nlp_tenant_abuse_window_s=60`,
  emit `nlp.alert.v1{kind=nlp_tenant_intake_abuse, severity=warn,
  key_class, qps_observed}` (debounced 5min per key class — bounded
  cardinality). Phase 7 sec.alert.v1 is the right place for *blocking*
  decisions; this NLP-side alert is observability only.
- [ ] **Closed-set tenant-class enum.** `cfg.nlp_tenant_class_enum =
  ["account_paid", "account_free", "ip_anonymous", "ip_known_proxy"]`
  — single source. AST guard `test_nlp_no_unbounded_tenant_label`
  rejects any metric / log / event that emits `tenant_id` directly
  (high-cardinality leak); only the closed `key_class` enum may appear
  in observable surfaces.
- [ ] **Proof:** `test_nlp_per_tenant_inflight_cap_isolates_noisy_tenant`
  (chaos: tenant A floods 50 QPS, tenant B sees < `cfg.nlp_p95_total_ms`
  latency unchanged), `test_nlp_humanizer_tenant_budget_degrades_to_template`,
  `test_nlp_fairness_key_eviction_lru_bounded`,
  `test_nlp_tenant_class_enum_closed` (AST), `test_nlp_no_raw_tenant_id_in_metrics`
  (AST registry walk).

#### 10.23.2 Canary rollout & shadow-mode for intent model + lexicons

- [ ] **Real failure mode.** A new `intent.tr.bin` with subtly
  different boundary behaviour (e.g., calibration shift) deployed to
  100% of pods at once = blast-radius of a bad model = entire user
  base. Same for a lexicon swap that introduces a new alias collision.
  §10.21.9 cold-start drains gracefully but does NOT compare new vs
  old behaviour before promotion.
- [ ] **Pod-level rollout percentage.** K8s `Deployment` ships new
  pods with `cfg.nlp_intent_model_canary_pct=10` (env-var driven —
  the 10% of pods with `NLP_CANARY=1` at startup load
  `intent.tr.bin.canary` and the matching calibration file; the rest
  load `intent.tr.bin`). API gateway routes by hashing
  `(account_id // bucket_size)` → sticky per-account assignment so a
  single user sees consistent classifier behaviour during the canary
  window. Sticky bucket size = `cfg.nlp_canary_account_bucket_size=1000`.
- [ ] **Shadow-mode evaluation.** Independent of canary routing,
  `cfg.nlp_intent_shadow_mode ∈ {off, on}` default `off`; when `on`,
  every pod (canary OR baseline) runs BOTH models on every request
  and records `(input_hash, baseline_intent, baseline_conf,
  canary_intent, canary_conf, agreement)` to a sampled audit stream
  `nlp.shadow.v1` (cardinality bounded — sampling rate
  `cfg.nlp_shadow_sample_rate=0.01`). Only the baseline answer is
  delivered to the user. Operator runs `make nlp.shadow-report` over
  the last 24h of `nlp.shadow.v1` records to compute disagreement
  rate, intent-distribution KL-divergence, and per-intent confidence
  delta histograms.
- [ ] **Promotion gate.** `make nlp.canary-promote` refuses to flip
  `cfg.nlp_intent_model_canary_pct=100` unless: (a) shadow-mode has
  run for ≥ `cfg.nlp_canary_min_shadow_hours=72`; (b) disagreement
  rate ≤ `cfg.nlp_canary_max_disagreement_rate=0.03`; (c) per-intent
  confidence drift |Δp95| ≤ `cfg.nlp_canary_max_confidence_drift=0.05`;
  (d) §10.18 evaluation harness PASSES on the canary model
  end-to-end. Refusal returns a structured report on which gate
  failed.
- [ ] **Same gates apply to lexicon swap.** A NEW lexicon snapshot
  carries a `lexicon_version_id`; canary pods serve from the new
  snapshot, baseline from the old; same shadow / promotion gates
  apply (with `disagreement` defined as "different gazetteer
  resolution for the same input").
- [ ] **Rollback is a one-command.** `make nlp.canary-rollback` flips
  the env-var on the canary pods (K8s rolling restart) AND emits
  `nlp.alert.v1{kind=nlp_canary_rolled_back, severity=warn,
  model_or_lexicon, reason}`.
- [ ] **Proof:** `test_nlp_canary_routing_is_account_sticky`,
  `test_nlp_shadow_mode_records_disagreements`,
  `test_nlp_canary_promote_refuses_below_min_hours`,
  `test_nlp_canary_promote_refuses_on_disagreement_breach`,
  `test_nlp_canary_promote_refuses_on_eval_harness_fail`,
  `test_nlp_canary_rollback_emits_alert`,
  `test_nlp_lexicon_canary_uses_same_gates`.

#### 10.23.3 Continuous-evaluation drift detection (post-deploy regression)

- [ ] **Real failure mode.** §10.18 evaluation harness gates **at
  deploy time**. Real-world traffic distribution drifts (new league
  starts, transfer window, viral storyline) → the deployed model
  silently underperforms on emerging slices weeks after the gate
  passed. No mechanism to detect this without humans noticing user
  complaints.
- [ ] **Weekly automated re-evaluation.** `xops/ci/nlp_weekly_eval.yml`
  cron job (Monday 03:00 UTC): (a) sample
  `cfg.nlp_weekly_eval_sample_size=2000` queries from the last 7 days
  of `nlp.shadow.v1` (PII-scrubbed per §10.21.7); (b) human-label
  pipeline (separate workflow — PR-style review with 3-of-5 labeller
  agreement; results land in `data/nlp/weekly_eval/YYYY-WW/labels.yaml`);
  (c) re-run §10.18 evaluation harness against the labelled slice;
  (d) emit `nlp.alert.v1{kind=nlp_weekly_eval_regression, severity=warn,
  intent_accuracy_delta, slice}` if absolute accuracy on any slice
  drops by > `cfg.nlp_weekly_eval_max_accuracy_drop=0.03` from the
  prior week.
- [ ] **Decoupling from traffic.** Sample is representative-sampled
  by `(intent_class, has_entity, has_dialect, has_code_switch,
  hour_of_day_bucket)` strata, NOT pure random — protects against a
  noisy storyline week from making the eval all-about-Galatasaray.
  Stratification pinned in `ai/nlp/eval/_sample.py`; AST asserts the
  strata enum is closed.
- [ ] **No PII leaves the system.** Sampled queries are
  PII-scrubbed AND length-truncated to
  `cfg.nlp_weekly_eval_sample_max_chars=200` AND any token NOT in the
  combined `(LeagueCatalog ∪ ai/nlp/lang_tr/* ∪ TR top-10k word freq)`
  set is replaced with `<UNK>` before labelling. Labellers see only
  the sanitized form.
- [ ] **Auto-degrade on sustained regression.** When 2 consecutive
  weekly evals show > `cfg.nlp_weekly_eval_consecutive_drop_threshold=0.05`
  cumulative drop, the next `make nlp.canary-promote` of any newer
  model is REFUSED until a human acknowledges via
  `data/nlp/weekly_eval/YYYY-WW/ack.yaml` (PR-merged). Forces human
  attention on persistent regressions.
- [ ] **Proof:** `test_nlp_weekly_eval_sample_stratified_correctly`,
  `test_nlp_weekly_eval_pii_scrubbed`,
  `test_nlp_weekly_eval_unknown_tokens_replaced`,
  `test_nlp_weekly_eval_alert_fires_on_threshold`,
  `test_nlp_canary_promote_refuses_on_consecutive_regression_without_ack`.

#### 10.23.4 Summary fan-out partial-failure semantics

- [ ] **Real failure mode §10.6 underspecifies.** A `summary.weekend`
  query fans out to N=10 fixtures via §10.6 `nlp.dispatcher.v1`. If 3
  predictions time out and 7 succeed, what does the user see? Today
  the contract is silent → renderer either blocks the whole answer
  (unfair to the 7 that succeeded) or silently omits the 3 (lying by
  omission). Neither is acceptable.
- [ ] **K-of-N quorum policy.** `cfg.nlp_summary_min_fixture_quorum=0.6`
  (60% of fan-out fixtures must respond within
  `cfg.nlp_summary_fanout_timeout_ms=2500`). Three outcomes:
  - **Quorum met (≥ 60% returned):** render answer with TR-disclosed
    omission ("10 maçtan 7'si için tahmin hazır; kalan 3'ün durumu için
    sayfaya bakın."). Per-fixture skip enumerated as a sub-list with
    `degraded_reason` per fixture (closed enum: `predict_timeout`,
    `predict_unavailable`, `data_lookup_failed`,
    `calibration_mismatch_refused` per §10.21.10).
  - **Quorum missed but ≥ 1 returned:** render a **per-fixture-only**
    answer (NOT a summary) with TR disclosure ("Tüm maçları kapsayan
    bir özet hazırlanamadı; gelen tahminler aşağıda.") and degraded
    reason at the answer level.
  - **Zero returned:** standard `nlp_predict_timeout` template (per
    §10.10 row 7).
- [ ] **Per-fixture timeout independence.** Fan-out timeouts are
  per-fixture, NOT cumulative. A single slow fixture cannot block
  the others — `asyncio.as_completed` pattern with hard
  per-future timeout. AST guard `test_nlp_summary_fanout_no_gather`
  rejects `asyncio.gather(...)` in the dispatcher (it propagates the
  slowest tail latency and binds futures to the cancelled context).
- [ ] **Stable Turkish disclosure templates.** `summary_partial.tr.j2`
  and `summary_per_fixture_only.tr.j2` (NEW templates) — each with
  slot for `(returned_count, total_count, missing_fixtures[].label,
  missing_fixtures[].degraded_reason_tr)`. Reason-translation table
  at `ai/nlp/lang_tr/degraded_reasons.tr.yaml` (closed enum →
  user-facing TR string). Every `degraded_reason` enum value MUST
  have a TR translation; build refuses on missing entries.
- [ ] **Citation-block accommodation.** Citations §10.7 / §10.21.6
  carry the per-fixture model_versions list; in a partial summary
  the citation block reflects ONLY the returned fixtures (NOT the
  intended N). Calibration-mismatch policy from §10.21.10 still
  applies across the returned subset.
- [ ] **Proof:** `test_nlp_summary_quorum_met_renders_partial_with_disclosure`,
  `test_nlp_summary_quorum_missed_renders_per_fixture_only`,
  `test_nlp_summary_zero_returns_renders_predict_timeout_template`,
  `test_nlp_summary_fanout_no_gather_in_dispatcher` (AST),
  `test_nlp_summary_per_fixture_independent_timeout`
  (chaos: 3 fixtures sleep 5s, 7 return at 100ms → answer at p95 ≤ 2.7s),
  `test_nlp_degraded_reason_tr_translation_table_complete` (build).

#### 10.23.5 Output-side TR formatting discipline (numbers, dates, scores)

- [ ] **Real failure mode.** Turkish convention: thousands separator
  `.`, decimal `,` (German style); time format `HH:MM` (24h, never
  am/pm); date `DD.MM.YYYY` or `DD Ay YYYY`; football scores
  `home-away` (no space). Default Python / Jinja2 / Go formatting
  emits `1,000.5` (US), `9:30 PM`, `2026-04-27`, `1 - 0` — all WRONG
  for TR users and visibly amateurish.
- [ ] **Single-source TR formatter.** `ai/common/text/tr_format.py`:
  - `tr_format_number(value, decimals=0) -> str` — `1234.56` →
    `"1.234,56"`; uses `decimal.Decimal` for exact rounding (no
    binary-float drift). Banker's rounding default; configurable via
    `cfg.nlp_format_number_rounding ∈ {bankers, half_up}` default
    `bankers` (matches scikit-learn / standard ML probability
    rounding).
  - `tr_format_money(value, currency="TRY") -> str` — `1234.56` →
    `"1.234,56 TL"` for TRY, `"1.234,56 €"` for EUR (suffix table
    at `ai/nlp/lang_tr/currency_suffix.tr.yaml`).
  - `tr_format_clock(dt, tz="Europe/Istanbul") -> str` — always 24h
    `HH:MM`; tz-aware (see §10.23.6).
  - `tr_format_date(d) -> str` — default `"27 Nisan 2026"` (long
    form); month names in `ai/nlp/lang_tr/month_names.tr.yaml`. Short
    form `tr_format_date_short(d)` → `"27.04.2026"`.
  - `tr_format_score(home, away) -> str` — `"1-0"` (ASCII hyphen, no
    space). Final-score shorthand consistent with §10.22.6 input
    parsing.
- [ ] **Jinja2 filter registration.** Every formatter exported as a
  Jinja2 filter (`number_tr`, `money_tr`, `clock_tr`, `date_tr`,
  `date_tr_short`, `score_tr`). AST guard
  `test_nlp_no_python_default_format_in_templates` rejects any
  template emitting `{{ value }}` for fields whose type is `int`,
  `float`, `Decimal`, `datetime`, `date` — must use a `_tr` filter.
  Filter signatures introspected from `ai/nlp/render.py`.
- [ ] **Locale-pinned via babel optional dep.** `babel` is OPTIONAL —
  not a hard dependency (CLAUDE.md prefers smallest stack). When
  installed, locale formatting via `babel.numbers.format_decimal(
  value, locale='tr_TR')` is used for cross-validation in tests
  (regression: `tr_format_number(1234.56) == babel.format_decimal(
  1234.56, locale='tr_TR')` — proof at test time only). Production
  uses our own deterministic implementation; `babel` is dev-only.
- [ ] **Negative-zero, infinity, NaN policy.** Formatters refuse
  `float('inf')`, `float('-inf')`, `float('nan')` — raise
  `ValueError` (callers must clamp upstream). `-0.0` formats as
  `"0"` (not `"-0"`). Guard tests pin every edge case.
- [ ] **Proof:** `test_tr_format_number_thousands_dot_decimal_comma`
  (parametrized over 30 values), `test_tr_format_money_try_suffix`,
  `test_tr_format_clock_always_24h_no_am_pm`,
  `test_tr_format_date_long_form_uses_tr_month_names`,
  `test_tr_format_score_no_space_ascii_hyphen`,
  `test_tr_format_negative_zero_renders_zero`,
  `test_tr_format_inf_nan_raises`,
  `test_nlp_no_python_default_format_in_templates` (AST),
  `test_tr_format_matches_babel_when_available` (skip-if-no-babel).

#### 10.23.6 Timezone discipline (render TZ vs storage TZ)

- [ ] **Real failure mode.** "Maç saat 21:30'da" — in WHICH timezone?
  Turkish users assume Europe/Istanbul (UTC+3, no DST since 2016).
  But fixture data may carry kickoff in UTC (Phase 4 storage convention)
  or in the venue's local TZ (UEFA fixtures across Europe). Rendering
  a UTC-stored time as Istanbul-local requires explicit conversion;
  silent assumption = users miss matches by hours.
- [ ] **Storage TZ = UTC, render TZ = Europe/Istanbul (default).**
  `cfg.nlp_render_timezone="Europe/Istanbul"` (single default at v1
  per §10.17 locale chain). All `qa.answer.v1` rendered times go
  through `tr_format_clock(dt_utc, tz=cfg.nlp_render_timezone)`. AST
  guard `test_nlp_no_naive_datetime_in_render` rejects any naive
  `datetime` (no tzinfo) reaching a formatter — must be UTC-aware
  on the wire and converted at format time.
- [ ] **Citation always carries UTC.** Per §10.21.6 / §10.21.8 the
  citation block carries `produced_at_utc` (ISO-8601 with `Z` suffix,
  microsecond precision). Render TZ applies to user-visible body
  ONLY; citation is byte-stable across TZ changes.
- [ ] **DST-edge / leap-second tests.** Even though Turkey has no DST
  since 2016, storage may carry pre-2016 kickoffs (historical eval),
  AND `Europe/Istanbul` IANA tz database row covers historical DST
  transitions. Test corpus pins:
  `tr_format_clock(2014-03-30T01:30:00Z) == "04:30"` (DST window),
  `tr_format_clock(2014-03-30T02:30:00Z) == "06:30"` (post-spring-forward),
  `tr_format_clock(2026-04-27T18:30:00Z) == "21:30"` (current).
  Leap-second handling: Python `datetime` doesn't model leap seconds
  → assert that any input claiming `:60` seconds raises (no silent
  truncation).
- [ ] **`zoneinfo` SHA pin.** `cfg.nlp_zoneinfo_dir` defaults to
  system zoneinfo; production deployments override to a pod-shipped
  `zoneinfo/` directory whose SHA is recorded in `chart.json`
  compatibility block (mirrors §10.21.5 confusables-table SHA pin).
  Boot probe asserts `Europe/Istanbul` row present + SHA matches.
  Defends against a host-OS tzdata downgrade silently changing
  rendered times.
- [ ] **Forward hook for venue-local TZ.** When future locales add
  `tr-DE`, `tr-CY`, etc. (§10.22.11), per-locale render TZ default
  table at `ai/nlp/lang_tr/locale_render_tz.tr.yaml`. v1 entry: only
  `tr-TR → Europe/Istanbul`.
- [ ] **Proof:** `test_nlp_clock_renders_istanbul_offset_currently_plus3`,
  `test_nlp_clock_naive_datetime_rejected` (AST + runtime),
  `test_nlp_dst_window_2014_renders_correctly` (3-point probe),
  `test_nlp_leap_second_input_rejected`,
  `test_nlp_zoneinfo_sha_pinned_at_boot`,
  `test_nlp_citation_always_utc_z_suffix`.

#### 10.23.7 Accessibility & answer-format negotiation

- [ ] **Real failure mode.** Default answers pepper text with emoji
  (⚽ 🏆 🟢 🔴) and decorative chars (▶ ✓ ✗); screen readers (NVDA,
  JAWS, VoiceOver) read these as "soccer ball, trophy, large green
  circle, large red circle, play button" — verbose and disruptive
  for blind / low-vision users. Unicode "soft hyphen" (U+00AD) and
  combining marks similarly confuse assistive tech.
- [ ] **Closed `answer_format` enum on `qa.request.v1`.**
  `cfg.nlp_answer_formats = ["plain", "markdown_safe", "screen_reader"]`
  (Phase 9 wires the param; defaults `plain`). Each formats the
  same answer payload differently:
  - `plain`: current default; emoji and decorative chars allowed
    from the closed `cfg.nlp_decorative_set` only (no free-text emoji
    from the LLM — humanizer's tokenizer-mask already excludes the
    emoji range per §10.8 decoding constraints; reasserted here as
    binding).
  - `markdown_safe`: GFM (CommonMark + extensions) safe subset; no
    inline HTML; emoji preserved; tables for fixture lists; bold for
    canonical names.
  - `screen_reader`: emoji STRIPPED entirely; decorative chars
    replaced with semantic markers (`✓` → `"evet"`, `✗` → `"hayır"`);
    every number is space-separated for natural reading
    (`"yüzde 67"` not `"%67"`); soft-hyphen and combining marks
    NORMALIZED out (`unicodedata.normalize('NFC', ...)` then strip
    U+00AD).
- [ ] **Per-format renderer.** `ai/nlp/render_format.py` —
  `render(answer_blocks, format)` dispatches; each format has its
  own template directory under `ai/nlp/templates/<format>/`. Templates
  share the same slot dict (§10.21.6 closed schema); no per-format
  template logic in code. AST guard `test_nlp_per_format_templates_share_slots`
  asserts every template across the three format dirs declares the
  same Jinja2 variable set.
- [ ] **Format negotiation precedence.** `?answer_format=` query
  param > `Accept` header (`text/plain` → `plain`,
  `text/markdown` → `markdown_safe`, `text/x-screen-reader` → custom
  MIME for SR clients) > default `plain`.
- [ ] **Default decorative set.** `cfg.nlp_decorative_set = ["⚽",
  "🏆", "🟢", "🔴", "🟡"]` — closed list at v1; AST asserts no other
  emoji codepoints reach the `plain` template output. The
  humanizer tokenizer-mask (§10.8) is the FIRST defense; this is
  the second — proofreader §10.9 gate scans rendered output for
  emoji not in the set, blocks + alerts on hit.
- [ ] **Proof:** `test_nlp_screen_reader_format_strips_all_emoji`,
  `test_nlp_screen_reader_format_normalizes_combining_marks`,
  `test_nlp_screen_reader_renders_percent_as_words`,
  `test_nlp_markdown_safe_no_inline_html` (regex on rendered output),
  `test_nlp_format_negotiation_param_over_header_over_default`,
  `test_nlp_per_format_templates_share_slots` (AST),
  `test_nlp_decorative_set_closed_at_render` (proofreader gate).

#### 10.23.8 Per-request cost-of-serving budget

- [ ] **Real failure mode.** Humanizer is the dominant per-request
  cost (GPU lease seconds × wall-clock × electricity ≈ stable
  per-token). At v1 this is on-prem GPU so "cost" is wall-clock; at
  Phase 20 monetization-on it's a hard $ ceiling per tier. No
  mechanism today bounds total humanizer-tokens per request, per
  tenant per minute, or per pod per hour.
- [ ] **Per-request token budget.** `cfg.nlp_max_humanizer_tokens_per_request=120`
  (already implied by §10.8 `max_new=120` decode cap, restated here
  as the binding doctrine — single source). Over-budget would be
  caught at decode time; this restatement makes the cost-budget
  contract explicit.
- [ ] **Per-tenant per-minute budget.** `cfg.nlp_max_humanizer_tokens_per_tenant_per_min=2400`
  (= 20 humanized requests × 120 tokens). Tracked via a sliding
  60s window per `cfg.nlp_fairness_key` (reuse §10.23.1
  infrastructure). Over-budget → degrade to template per §10.23.1
  `humanizer_tenant_budget_exceeded` reason. Counter is process-local
  + best-effort gossip via Redis (`cfg.nlp_humanizer_budget_redis_key_prefix=
  "nlp:humanizer:budget:"`, TTL 120s); cross-pod budget enforcement
  is best-effort, NOT strict (Redis outage → fall back to per-pod
  budget × pod-count estimate; documented as acceptable slop).
- [ ] **Per-pod per-hour ceiling.** `cfg.nlp_max_humanizer_tokens_per_pod_per_hour=720000`
  (= 100 req/min sustained × 60 min × 120 tokens). Over-ceiling →
  pod globally degrades humanizer for `cfg.nlp_humanizer_pod_cooldown_s=300`,
  emits `nlp.alert.v1{kind=nlp_humanizer_pod_budget_exceeded,
  severity=warn}`. Defends against runaway loops or model-mode
  pathology emitting maximum-length completions on every request.
- [ ] **Phase 20 hook.** When monetization is on, the per-tenant budget
  is OVERRIDDEN by the tier's allowed tokens; v1 default budgets are
  the floor for free tier. Tier mapping pinned in §10.21.11 contract
  (`tier_id_required` is per-intent; tokens-per-tenant-per-min is
  per-tier — both single-source via Phase 20 config).
- [ ] **Cost telemetry.** `nlp_humanizer_tokens_emitted_total{tenant_class,
  intent}` counter (cardinality bounded by closed enums); per-hour
  rollup feeds the §10.23.10 capacity-planning model.
- [ ] **Proof:** `test_nlp_per_request_token_cap_enforced_at_decode`,
  `test_nlp_per_tenant_per_min_budget_degrades_to_template`,
  `test_nlp_per_pod_per_hour_ceiling_triggers_cooldown`,
  `test_nlp_redis_outage_falls_back_to_per_pod_budget`,
  `test_nlp_humanizer_token_counter_cardinality_bounded`.

#### 10.23.9 Cross-pod cache-coherence & poisoning defense

- [ ] **Real failure mode.** §10.12 L0 intent cache and L1 answer
  cache (`cache.v1`) key on `(normalized_text, lexicon_version,
  intent_model_version)`. Today only `normalized_text` is in the key
  → if pod A has lexicon v17 and pod B has v18 (rolling lexicon
  swap mid-request), pod B can serve a v17 cached answer attributing
  it to v18 → citation/version mismatch is silent.
- [ ] **Versioned cache keys.** Cache key = `sha256(normalized_text ||
  intent_model_version || lexicon_version_id || calibration_version ||
  cfg.nlp_pipeline_version)`. ALL components MUST be present; AST
  guard `test_nlp_cache_key_includes_all_versions` walks the cache
  put/get sites and asserts the key-builder consults all 5 fields.
- [ ] **Atomic version-stamping.** Versions captured at request entry
  (snapshot read of all 4 version fields under one read of an
  immutable `VersionSnapshot` struct that is replaced atomically on
  any swap) — NEVER read individually mid-request (would yield a
  torn snapshot under concurrent swap). Snapshot held for the
  request's lifetime.
- [ ] **TTL is short.** L0 cache TTL = `cfg.nlp_l0_cache_ttl_s=300`
  (already pinned in §10.12); L1 (`cache.v1`) TTL =
  `cfg.nlp_l1_answer_cache_ttl_s=600`. Both are short relative to
  lexicon swap cadence (mtime poll = 30s default per §10.2). After
  lexicon swap, stale entries in L0/L1 with old version-key are
  unreachable (different key) → naturally evict via TTL. No
  cross-pod cache invalidation needed (the version in the key IS
  the invalidation).
- [ ] **Cache poisoning defense.** L1 (`cache.v1` shared via Redis
  per Phase 7) — adversary with Redis write access could craft a
  fake `(key, value)` pair. Each cached answer is HMAC-signed with
  `cfg.nlp_l1_cache_hmac_key_path` (mode 0400, mirrors §10.21.8 key
  doctrine); on cache hit, signature verified before deserialization.
  Verify-fail → drop entry, emit `nlp.alert.v1{kind=
  nlp_l1_cache_signature_invalid, severity=warn}`, fall through to
  fresh compute. Phase 7 Redis is trusted in v1 but the signature
  closes the door even on supply-chain compromise.
- [ ] **Cache stampede — single-flight reasserted.** §10.12 already
  pins per-pod single-flight; §10.23.9 reasserts that single-flight
  IS the correct stampede protection — no thundering-herd Redis-side
  lock needed. Cross-pod stampede on a viral query is bounded by
  pod-count (each pod computes once, then all share via L1).
- [ ] **Proof:** `test_nlp_cache_key_includes_all_5_version_fields`
  (AST), `test_nlp_version_snapshot_held_for_request_lifetime`,
  `test_nlp_l1_cache_signature_verified_on_hit`,
  `test_nlp_l1_cache_signature_invalid_drops_and_alerts`,
  `test_nlp_lexicon_swap_naturally_evicts_l0_via_versioned_key`
  (chaos: swap mid-traffic → no stale-version answer observable).

#### 10.23.10 Capacity planning model & bottleneck documentation

- [ ] **Real failure mode.** Operators face "we're hitting 70% CPU,
  do we add a pod?" — without an explicit capacity model the answer
  is guessed. §10.12 latency table tells per-stage budget but doesn't
  derive the throughput ceiling.
- [ ] **Per-pod throughput model documented.** `docs/design/TURKISH_NLP.md`
  gains a "Capacity model" section with:
  - **Little's Law derivation**: `throughput_pod = parallelism /
    avg_latency` per stage.
  - **Per-stage parallelism**:
    - Normalize / lexicon / intent / entity / dispatcher = CPU-bound,
      parallelism = `cfg.nlp_intake_workers=8` (default; sized for
      4 vCPU pod).
    - Humanizer = GPU-lease serialized, parallelism = `1` (per pod).
  - **Per-stage avg latency** (from §10.12 table p50 column):
    normalize 5ms, intent 25ms, entity 40ms, render 30ms, humanizer
    300ms (when used), proofreader 15ms.
  - **Throughput ceiling** (without humanizer): `8 / 0.115s ≈ 70 QPS`
    per pod. With humanizer (default ON): `1 / 0.300s ≈ 3.3 QPS`
    per pod for humanized fraction × `cfg.nlp_humanizer_request_rate=0.6`
    → effective ~ 5.5 QPS per pod under default config. Pinned
    numbers in the doc with provenance (which `make nlp.bench` row
    they came from + git SHA of the bench).
- [ ] **`make nlp.capacity-report`** — generates a fresh capacity
  estimate from the latest `nlp.bench` run + current cfg values;
  output `data/nlp/capacity_report.md` with throughput-per-pod,
  bottleneck stage, and "to handle X QPS you need Y pods" calculator.
  CI runs on PRs that touch any §10.19 / §10.21.12 / §10.22.14 /
  §10.23.13 cfg knob and updates the report.
- [ ] **Bottleneck assertion at start.** Boot probe checks
  `cfg.nlp_intake_workers ≤ os.cpu_count() * 2` (oversubscription
  guard) and `cfg.nlp_intake_workers ≥ 2` (under-subscription guard
  — single-worker pods deadlock on singleflight in adversarial
  patterns). Refuse start on either.
- [ ] **3× spike rehearsal.** `make nlp.spike-test` (NEW;
  human-invoked, NOT in CI by default — too expensive): synthetic
  load generator hits a 3-pod stack at 3× current sustained QPS for
  5 minutes; success criteria = no `nlp.alert.v1{severity=critical}`
  fires AND p99 stays within `cfg.nlp_p99_total_ms` × 1.5. Documented
  in `docs/guides/nlp_runbook.md`. Run quarterly per ops convention.
- [ ] **Proof:** `test_nlp_intake_workers_validated_at_boot`,
  `test_nlp_capacity_report_generated_on_cfg_change` (CI gate),
  `test_nlp_capacity_model_doc_contains_required_sections` (doc
  presence test).

#### 10.23.11 Disaster recovery drill (full-lexicon corruption + pod restart)

- [ ] **Real failure mode.** §10.21.3 atomic-swap-or-revert defends
  against a single mid-poll corruption. It does NOT exercise
  recovery from the case where the source-of-truth lexicon files
  on disk are corrupted (filesystem rot, accidental `git push --force`
  reverting a lexicon update, deploy-script bug writing zero-byte
  files) AND every pod restarts at once (deploy event coinciding
  with corruption). Then atomic-swap has nothing valid to swap to →
  pods refuse boot → entire NLP plane down.
- [ ] **Bootstrap-fallback lexicon.** A minimal "safe-mode" lexicon
  shipped in the container image at `ai/nlp/lexicon_safe_mode/`
  (read-only, baked-in, NOT mtime-poll watched). Contains: top-100
  team aliases (LeagueCatalog v1 floor), top-10 intent templates,
  closed market enum, no dialect/abbreviation entries. When primary
  lexicon load FAILS at boot AND `cfg.nlp_safe_mode_fallback_enabled=true`
  (default `true`), pod boots in safe mode → readiness probe returns
  200 with header `X-NLP-Safe-Mode: true` AND every emitted
  `qa.answer.v1` carries `degraded=true,
  degraded_reason="lexicon_safe_mode_active"`. Operator sees
  perpetual `nlp.alert.v1{kind=nlp_safe_mode_active,
  severity=critical, debounce=300s}` until primary lexicon recovers.
- [ ] **Recovery contract.** Once primary lexicon recovers (operator
  fixes the source file → mtime-poll detects valid swap), pod EXITS
  safe mode atomically (next mtime-poll cycle detects valid lexicon
  → atomic swap to primary → safe-mode flag flipped off → next
  request renders without degraded flag). NO pod restart required.
  Proof: chaos test corrupts lexicon, all 3 pods enter safe mode,
  then restores, all 3 pods exit safe mode within
  `cfg.nlp_lexicon_reload_s + 5s`.
- [ ] **DR drill runbook.** `docs/guides/nlp_runbook.md` (per §10.22
  scope) gains a "Disaster recovery drills" section covering:
  - Full lexicon corruption scenario.
  - Intent model corruption scenario (no safe-mode model — pod
    refuses boot per §10.21.1; humans must restore from
    `data/nlp/model_history/<sha>/intent.tr.bin` archive).
  - Citation-key compromise scenario (rotate immediately per
    §10.21.8).
  - Lexicon-feed-key compromise scenario (rotate per §10.22.12).
  - Time-budget per scenario: ≤ 15 min for lexicon corruption (safe
    mode auto-engages), ≤ 60 min for model corruption (manual
    restore), ≤ 30 min for any key rotation (dual-acceptance window
    means no service disruption).
- [ ] **Quarterly drill cadence.** `make nlp.dr-drill` (human-only
  — destructive) — corrupts a copy of the lexicon in a staging pod,
  asserts safe-mode engages within budget, then restores and asserts
  recovery within budget. Run quarterly; result logged to
  `docs/reports/nlp_dr_drill_YYYY-Q.md`.
- [ ] **Proof:** `test_nlp_safe_mode_engages_when_primary_lexicon_corrupt`,
  `test_nlp_safe_mode_serves_with_degraded_flag`,
  `test_nlp_safe_mode_exits_atomically_on_primary_recovery`,
  `test_nlp_safe_mode_lexicon_size_bounded` (≤ 100 teams, ≤ 1MiB —
  no scope creep into the safe-mode artifact),
  `test_nlp_dr_drill_runbook_sections_present` (doc presence).

#### 10.23.12 Dependency CVE response policy

- [ ] **Real failure mode.** Phase 10 depends on `fasttext`,
  `python-crfsuite`, `jinja2`, `numpy`, `babel` (optional),
  `unicode-tables` (Confusables.txt source), `zoneinfo` (system
  tzdata). A critical CVE in any (e.g., Jinja2 sandbox-escape
  CVE-2024-XXXXX hypothetical) requires a coordinated patch ship.
  No documented response runbook = ad-hoc panic = slow patch.
- [ ] **CVE feed monitoring.** `xops/ci/nlp_cve_scan.yml` — daily
  CI job runs `pip-audit` against `ai/requirements.txt` (pinned per
  §10.21.1) AND polls GitHub Security Advisories for each pinned
  dependency. Any CRITICAL (CVSS ≥ 9.0) or HIGH (CVSS ≥ 7.0)
  advisory matching a pinned version → opens a GitHub issue
  automatically with label `phase:10` + `cve` + severity, AND
  emits a Slack/PagerDuty page (operator-configured, optional).
- [ ] **Response time targets.** Pinned in `docs/guides/nlp_runbook.md`:
  - **Critical (CVSS ≥ 9.0)**: patch ship target ≤ 24h. If patch
    not available upstream → mitigations documented (e.g., Jinja2
    sandbox CVE → enforce stricter `Environment(autoescape=True,
    sandbox=True)` config; AST guard already enforces no
    `from_string` per §10.21.2 → most exploit vectors closed).
  - **High (CVSS 7.0–8.9)**: patch ship target ≤ 7 days.
  - **Medium / Low**: bundle into next regular dependency-bump cycle.
- [ ] **Mitigations catalogue.** `ai/nlp/security/mitigations.md`
  (NEW) — running list of dependency CVE classes and the
  defense-in-depth measure already in place that mitigates them
  (e.g., "Jinja2 RCE via from_string → AST guard rejects from_string;
  sandbox-escape via filter chaining → custom finalize callback
  validates types"). Reviewed in PR for every dep version bump.
- [ ] **SBOM emission.** `make nlp.sbom` emits a CycloneDX-format
  SBOM at `data/nlp/sbom.json` covering all NLP-plane direct + transitive
  Python deps + the lexicon files (which carry their own provenance:
  source URL, SHA, license — many football-data lexicons are derived
  from openfootball.json which is ODbL-licensed; license
  attribution required). CI publishes the SBOM as a release artifact
  (Phase 14 release scope).
- [ ] **License attribution for lexicon-derived data.** Some team
  / league names are trademarked (UEFA, FIFA marks); LeagueCatalog
  Phase 13a is the registered source-of-truth and carries its own
  legal review. `data/nlp/build_reports/license_attribution.md`
  (CI-generated) lists every external data source feeding the
  lexicons + the legal basis (fair use for canonical names,
  attribution for openfootball-derived aliases).
- [ ] **Proof:** `test_nlp_cve_scan_ci_job_present` (workflow file
  presence), `test_nlp_runbook_cve_response_section_present`,
  `test_nlp_mitigations_catalogue_present`,
  `test_nlp_sbom_includes_all_pinned_deps`,
  `test_nlp_license_attribution_report_generated_in_build`.

#### 10.23.13 Knob inventory + DoD aggregate (~25 new keys, on top of §10.19 + §10.21.12 + §10.22.14)

- [ ] **New cfg knobs:**
  `nlp_fairness_key="account_id"`,
  `nlp_per_tenant_inflight_max=8`,
  `nlp_fairness_max_tracked_keys=10000`,
  `nlp_per_tenant_humanizer_burst=4`,
  `nlp_per_tenant_humanizer_refill_per_s=2`,
  `nlp_tenant_abuse_qps_threshold=10`,
  `nlp_tenant_abuse_window_s=60`,
  `nlp_tenant_class_enum=["account_paid","account_free","ip_anonymous","ip_known_proxy"]`,
  `nlp_intent_model_canary_pct=10`,
  `nlp_canary_account_bucket_size=1000`,
  `nlp_intent_shadow_mode="off"`,
  `nlp_shadow_sample_rate=0.01`,
  `nlp_canary_min_shadow_hours=72`,
  `nlp_canary_max_disagreement_rate=0.03`,
  `nlp_canary_max_confidence_drift=0.05`,
  `nlp_weekly_eval_sample_size=2000`,
  `nlp_weekly_eval_max_accuracy_drop=0.03`,
  `nlp_weekly_eval_consecutive_drop_threshold=0.05`,
  `nlp_weekly_eval_sample_max_chars=200`,
  `nlp_summary_min_fixture_quorum=0.6`,
  `nlp_summary_fanout_timeout_ms=2500`,
  `nlp_format_number_rounding="bankers"`,
  `nlp_render_timezone="Europe/Istanbul"`,
  `nlp_zoneinfo_dir=""` (empty = system),
  `nlp_decorative_set=["⚽","🏆","🟢","🔴","🟡"]`,
  `nlp_max_humanizer_tokens_per_request=120`,
  `nlp_max_humanizer_tokens_per_tenant_per_min=2400`,
  `nlp_max_humanizer_tokens_per_pod_per_hour=720000`,
  `nlp_humanizer_pod_cooldown_s=300`,
  `nlp_humanizer_request_rate=0.6`,
  `nlp_humanizer_budget_redis_key_prefix="nlp:humanizer:budget:"`,
  `nlp_l0_cache_ttl_s=300`,
  `nlp_l1_answer_cache_ttl_s=600`,
  `nlp_l1_cache_hmac_key_path="infra/nlp/l1_cache_hmac.key"`,
  `nlp_intake_workers=8`,
  `nlp_safe_mode_fallback_enabled=true`,
  `nlp_pipeline_version="1.0.0"`.
  Triangle test extends. Go-side `TestEnvSync` covers
  `nlp_render_timezone` (gateway needs it to render error responses
  consistently per RFC7807 mapping in §10.21.11) and
  `nlp_l1_cache_hmac_*` (gateway shares the L1 read path — Phase 7
  cache.v1 doctrine).
- [ ] **New `nlp.event.v1` kinds** (open-enum, registered):
  `fairness_key_evicted`,
  `cache_signature_dropped`,
  `safe_mode_engaged`,
  `safe_mode_exited`,
  `canary_shadow_disagreement`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `nlp_tenant_intake_abuse` (warn, debounced 5min),
  `nlp_canary_rolled_back` (warn),
  `nlp_weekly_eval_regression` (warn),
  `nlp_humanizer_pod_budget_exceeded` (warn),
  `nlp_l1_cache_signature_invalid` (warn),
  `nlp_safe_mode_active` (critical, debounced 300s).
- [ ] **New degraded-reason enum entries** (per §10.10):
  `humanizer_tenant_budget_exceeded`,
  `lexicon_safe_mode_active`,
  `summary_quorum_missed_per_fixture_only`,
  `calibration_mismatch_refused` (already pinned in §10.21.10 — reasserted).
  Each MUST have a TR translation in `degraded_reasons.tr.yaml`
  (per §10.23.4); build refuses on missing.
- [ ] **New build artifacts.** `data/nlp/capacity_report.md`,
  `data/nlp/sbom.json`, `data/nlp/build_reports/license_attribution.md`,
  `docs/reports/nlp_dr_drill_YYYY-Q.md` (quarterly).
- [ ] **DoD proof tests aggregate (new in §10.23):**
  - §10.23.1 — 5 tests (fairness + abuse isolation)
  - §10.23.2 — 7 tests (canary + shadow + promotion gates)
  - §10.23.3 — 5 tests (weekly eval + auto-degrade)
  - §10.23.4 — 6 tests (summary partial-failure semantics)
  - §10.23.5 — 9 tests (TR formatting incl. babel cross-validation)
  - §10.23.6 — 6 tests (timezone + DST + zoneinfo SHA)
  - §10.23.7 — 7 tests (accessibility + format negotiation)
  - §10.23.8 — 5 tests (cost-of-serving budget)
  - §10.23.9 — 5 tests (cache coherence + signature)
  - §10.23.10 — 3 tests (capacity model + boot validation)
  - §10.23.11 — 5 tests (DR safe-mode + recovery)
  - §10.23.12 — 5 tests (CVE scan + SBOM + license attribution)
  - **Total: ≈ 68 new proof tests added on top of §10.20 + §10.21 +
    §10.22 baseline. Cumulative Phase 10 proof-test count ≈ 250+.**
- [ ] **Chart compatibility additions.** Pin `babel` (optional dep
  version), `pip-audit` (CVE-scan tool version), CycloneDX schema
  version, IANA tzdata baseline date (e.g., `2026a`).
- [ ] **`make swarm.demo.nlp` extends** to cover §10.23 paths:
  one query each for: (a) tenant-fairness isolation under load (3
  tenants, 1 noisy); (b) canary routing + shadow-mode disagreement
  recording; (c) summary fan-out with 2 of 5 fixtures timing out
  (quorum-met partial-render); (d) `?answer_format=screen_reader`
  query (emoji-stripped output asserted byte-stable); (e) safe-mode
  engage/exit via injected lexicon corruption + recovery. All within
  the < 30s compose budget; if budget is tight, sub-set selectable
  via `make swarm.demo.nlp.fast` (fast-path) vs
  `make swarm.demo.nlp.full` (covers all of §10.21 + §10.22 + §10.23).
- [ ] **Documentation extensions.** `docs/design/TURKISH_NLP.md`
  gains: Capacity Model section, Output-Formatting section,
  Accessibility section, Tenant-Fairness section.
  `docs/guides/nlp_runbook.md` (per §10.22 scope) gains: Canary
  rollout playbook, Weekly-eval triage, DR drill procedures, CVE
  response runbook, Cost-budget tuning. `docs` minor bump alongside
  the §10.23 land per AGENTS.md §6.1.

### 10.24 TR-input completeness floor (binding addendum — "wrong-Turkish tolerance, exhaustive")

> **Why this addendum exists.** §10.22 is the TR-language *correctness*
> floor — it covers the well-defined classes of messy input (no
> diacritics, missing apostrophes, mis-attached particles, dialect,
> abbreviations, code-switching, foreign transliteration, locale tags,
> offensive language, lexicon-feed integrity). Real Turkish football
> input is *messier still*: **wrong** suffixes that violate vowel
> harmony, repeated-character emphasis (*"evettttt"*), digit-letter
> leetspeak (*"g4latasaray"*), the Turkish dotted-i NFC corner case
> (`İ` decomposed as `I` + COMBINING DOT ABOVE), run-on multi-question
> input, negation-bearing intent (*"sakat değil mi"*), compound /
> hyphenated club names (*"Çaykur Rizespor"*, *"MKE Ankaragücü"*),
> emoji-as-team-signal, hashtag / @-mention noise, HTML entity escapes
> arriving from web clients, decimal comma vs score-line ambiguity
> (*"1,5 üst"* vs *"1,0"*), number-word concatenation (*"ikiyüzon"*),
> garden-path parses where the first gazetteer hit blocks the right
> intent, and adversarial random-token floods that classifier must
> abstain on instead of guessing. §10.24 is the binding **TR-input
> completeness floor**: every gate below corresponds to a class of
> real user input observed on Turkish football forums / WhatsApp
> groups / Twitter that §10.0–§10.23 leave under-specified.
>
> **Doctrine reminder.** Same as §10.22: **deterministic, table-driven,
> no LLM in the input path.** The §10.4 fastText classifier remains
> the single ML touchpoint. Every §10.24 rule lands as a YAML table
> under `ai/nlp/lang_tr/` (extending the §10.22.14 directory) or as a
> pure-Python helper in `ai/common/text/turkish.py` with an AST guard
> that rejects inline literals duplicating the table.
>
> **Single-source posture.** Where §10.24 reuses an existing knob (e.g.,
> `nlp_normalize_stage_timeout_ms` from §10.3), it does NOT introduce
> a new one — the cap stays a single number; only the work it bounds
> grows. Where a new behavioural axis genuinely needs its own knob
> (~17 new keys aggregated in §10.24.14), the triangle test extends
> in the same commit, mirrors the §10.22.14 doctrine.

#### 10.24.1 Vowel-harmony-violation tolerance (wrong-suffix recovery)

- [ ] **Real failure mode.** Native and non-native users routinely write
  suffixes that violate Turkish vowel harmony: *"Galatasaraye"* (should
  be *"Galatasaray'a"*), *"Fenerbahçeya"* (should be *"Fenerbahçe'ye"*),
  *"oynayacaklarmi"* (should be *"oynayacaklar mı"*), *"kazanmadi"*
  (should be *"kazanmadı"* — bare missing diacritic AND wrong vowel
  class for negation suffix). §10.22.2 strips well-formed suffixes;
  §10.24.1 covers **mal-formed** suffixes where the apostrophe is
  missing AND the suffix vowel is wrong.
- [ ] **Two-pass suffix stripper.** Extends `strip_proper_noun_suffix`
  (§10.22.2) with a fallback pass: when the trailing 1–4 lowercase
  chars do NOT match a vowel-harmony-correct suffix family, attempt
  a **harmony-tolerant** strip — every recognised suffix family has a
  closed `tolerated_vowels` set in `ai/nlp/lang_tr/suffix_families.tr.yaml`
  (e.g., dative `-a/-e` tolerates `-ı/-i/-u/-ü/-y/-ya/-ye` as wrong
  spellings; the stem still resolves). Stripped stem proceeds through
  gazetteer; the answer generator (§10.7) renders the **correct**
  vowel-harmonic form regardless of what the user typed.
- [ ] **Binding constraint.** Harmony-tolerant strip MUST NOT alter the
  canonical entity (e.g., never split *"Edirne"* → *"Edirn"* + *"e"*
  even via the tolerant pass). Reuses the §10.22.4 stem-set guard:
  attempted strip is rejected if the resulting stem matches any
  canonical entity prefix in the lexicon AND removing the trailing
  chars would destroy meaning. Closed list at
  `ai/nlp/lang_tr/_no_strip_canonicals.tr.yaml` (regenerated by
  `make nlp.lexicon-build` from team / city / venue names with
  trailing vowels).
- [ ] **Repair-event emission.** Every harmony-tolerant strip emits
  `nlp.event.v1{kind=suffix_harmony_repaired, original_suffix,
  resolved_suffix_class}` (debounced 60s per `(stem, suffix)` pair —
  bounded cardinality at runtime because suffix_class enum is closed
  and stems are gazetteer-bounded).
- [ ] **Proof:** `test_nlp_galatasaraye_resolves_to_galatasaray_dative`,
  `test_nlp_oynayacaklarmi_detaches_question_particle_under_wrong_harmony`,
  `test_nlp_harmony_tolerant_strip_never_splits_no_strip_canonicals`
  (parametrized over the full `_no_strip_canonicals` table),
  `test_nlp_suffix_harmony_repaired_event_emitted_with_debounce`.

#### 10.24.2 Repeated-character & emphasis normalization

- [ ] **Real failure mode.** *"evettttt"*, *"süüüüper"*, *"hayııır"*,
  *"gooool"*, *"yaaaa"*, *"ofsayttttt"*. Naive typo correction (§10.3
  Symspell) does NOT recover these — edit distance from *"evet"* to
  *"evettttt"* is 4, exceeding the budget. Unrepaired, they break
  gazetteer + classifier (out-of-vocabulary tokens with no lexicon
  hit). Currently §10.1 step 6 (diacritic restore) does not handle
  this; §10.3 typo correction is too narrow.
- [ ] **New step 7a in §10.1** (between Zemberek tokenization and
  Symspell typo correction). `collapse_repeated_chars(token)`:
  - If token has run of ≥ 3 identical chars (case-insensitive in TR
    sense per §10.1 step 4), collapse to ≤ 2 (preserves intentional
    Turkish doubles: *"abi"* / *"saat"* / *"dikkat"* — only the
    excess is dropped).
  - Then re-test against lexicon + Symspell with the original budget
    (so *"evettttt"* → *"evett"* → *"evet"* in 1 edit).
  - If collapse yields a new word that resolves AND has frequency >
    `cfg.nlp_repeat_collapse_min_freq=100` per `tr_word_freq.txt`,
    accept; else preserve original.
- [ ] **Bounded cost.** Collapse is O(token-length); per-token cap
  `cfg.nlp_repeat_collapse_max_len=64` — beyond this the token is
  flagged as `garbage` and dropped from the classifier input
  (defends against single-token DoS like a 4096-char `aaaaaaa…`).
- [ ] **Closed allow-list of legit triples.** A small allow-list of
  Turkish words that legitimately carry triple chars (none in
  standard Turkish, but loanwords like *"www"* in URLs) at
  `ai/nlp/lang_tr/repeat_allowlist.tr.yaml`. Empty at v1 — explicit
  empty file with `_meta.schema_version=1` so adding entries later
  is auditable.
- [ ] **Proof:** `test_nlp_evettttt_collapses_to_evet_via_symspell`,
  `test_nlp_intentional_double_abi_preserved`,
  `test_nlp_repeat_collapse_does_not_break_saat_dikkat`
  (parametrized golden), `test_nlp_extreme_repeat_token_dropped_as_garbage`,
  `test_nlp_repeat_collapse_idempotent` (property test, hypothesis ≥ 500).

#### 10.24.3 Digit ↔ letter confusable folding (leetspeak / numeral substitution)

- [ ] **Real failure mode.** *"g4latasaray"* (a → 4), *"f3nerbahce"*
  (e → 3), *"bjk1903"* (year embedded), *"fb5"* (random suffix). Some
  are intentional (year suffixes); some are bot-evasion / playful;
  some are typo-via-Shift-key (`§` instead of `5`). §10.21.5 covers
  Latin-vs-Cyrillic confusables but NOT digit-vs-letter.
- [ ] **Fold table at `ai/nlp/lang_tr/digit_letter_confusables.tr.yaml`**:
  `{"4": "a", "3": "e", "0": "o", "1": "i", "5": "s", "7": "t"}`. Pre-
  classifier, AFTER §10.21.5 confusable fold AND BEFORE diacritic
  restore. **Conditional fold**: only apply when the resulting token
  resolves to a lexicon entry that the original (digit-bearing) form
  did not — defends against destroying year suffixes. Algorithm:
  1. If raw token resolves in lexicon → keep raw, do not fold.
  2. Else apply fold; if folded token resolves → use folded form +
     emit `nlp.event.v1{kind=digit_letter_confusable_folded}`.
  3. Else preserve raw token (let later passes handle it / fall
     through to gazetteer-miss).
- [ ] **Year-suffix preservation.** *"BJK1903"*, *"GS1905"*,
  *"FB1907"* — closed allow-list at
  `ai/nlp/lang_tr/year_suffix_allowlist.tr.yaml` mapping
  `(team_abbreviation, year)` → canonical_id. Match here pre-empts
  the digit-fold pass (the year is meaningful identification).
- [ ] **Proof:** `test_nlp_g4latasaray_folds_to_galatasaray`,
  `test_nlp_bjk1903_resolves_via_year_allowlist_no_fold`,
  `test_nlp_digit_fold_only_when_folded_form_resolves`,
  `test_nlp_digit_fold_does_not_destroy_score_lines`
  (parametrized: *"1-0"*, *"3:2"*, *"2 1"* preserved literally).

#### 10.24.4 Turkish dotted/dotless `i` NFC corner case

- [ ] **Real failure mode §10.1 step 2 underspecifies.** Unicode NFC
  does NOT normalize the Turkish-specific decomposition `İ` (U+0130)
  → `I` (U+0049) + COMBINING DOT ABOVE (U+0307). Some browsers /
  IMEs / mobile keyboards emit the decomposed form. §10.1 step 4
  (Turkish lowercase) maps `İ` → `i`, but the decomposed sequence
  `I` + U+0307 hits the lowercase rule for plain `I` and becomes
  `ı` + U+0307 — semantically broken (loses the dot, becomes the
  dotless letter with a stranded combining mark).
- [ ] **Pre-lowercase composition pass.** New step 3.4 in §10.1
  (between strip-controls/RTL/zero-widths and the Turkish lowercase):
  `compose_turkish_dotted_i(text)` — rejoins `I` + U+0307 → `İ`,
  `i` + U+0307 → `i` (idempotent normalization step). Also handles
  the symmetric case `J` + U+0307 (rare but possible from typo) →
  `J` (drops stray combining mark on non-dotted-i carriers).
- [ ] **Single-source mapping.** Table at
  `ai/common/text/_turkish_compose.py` (frozen dict; AST guard
  rejects inline literal). Reused by Go-side sec layer
  (`server/internal/sec/sanitize.go::LowercaseTurkish` extended in
  same commit; mirrors the §7.6 single-source doctrine — both Python
  and Go consult the same intent, byte-for-byte cross-language test
  added to §10.20 boundary suite).
- [ ] **Combining-mark tail strip.** After the Turkish-specific
  composition pass, strip any remaining COMBINING DOT ABOVE / BELOW
  / DIAERESIS / CIRCUMFLEX (U+0300–U+036F range) that did not get
  consumed by NFC. Defends against attacker stacking 100 combining
  marks on a single base character (CPU-bound regex would normally
  suffice; cap at 4 stripped marks per token then drop the token if
  more remain — `nlp.alert.v1{kind=excessive_combining_marks,
  severity=warn, debounced 60s}`).
- [ ] **Proof:** `test_nlp_decomposed_capital_i_recomposes_to_dotted_i`,
  `test_nlp_decomposed_lowercase_i_drops_stray_dot`,
  `test_nlp_compose_turkish_dotted_i_byte_parity_python_go`
  (cross-language fixture), `test_nlp_excessive_combining_marks_drops_token_with_alert`,
  `test_nlp_compose_idempotent` (hypothesis ≥ 1000).

#### 10.24.5 Run-on / multi-question input splitting

- [ ] **Real failure mode.** Users send compound queries:
  *"galatasaray kazandı mı fenerbahçe ne zaman oynar"*,
  *"GS-FB skoru ne ve haftaya kim oynayacak"*. §10.4 classifier has
  no sentence-segmentation step — the classifier sees the full
  string and outputs ONE intent (typically low-confidence on the
  combined surface form). Result: low-conf abstention → did-you-mean,
  even though both halves are individually answerable.
- [ ] **Lightweight TR sentence segmenter.** New step 7b in §10.1
  (after Zemberek tokenization, before typo correction).
  `split_questions(tokens) -> list[list[token]]` using:
  - Punctuation boundaries (`.`, `!`, `?`, `;`).
  - Question-particle (`mi/mı/mu/mü`) end markers — known via
    §10.22.4 detached-particle table.
  - Coordinating conjunction `ve` at clause boundary (heuristic:
    presence of TWO question-words / TWO team entities flanking).
  - Fixed cap `cfg.nlp_max_subqueries=3` — beyond, treat as one
    big query (graceful degradation: classifier abstains, did-you-mean
    answer offered with the first sub-query candidate).
- [ ] **Per-subquery dispatch.** Each subquery flows the rest of the
  §10.1–§10.6 pipeline independently; results are aggregated into a
  single `qa.answer.v1` payload with `parts: [{intent, body, citation}]`
  array (additive schema bump `qa.answer.v1` schema_version 1→2 —
  consumer fallback: legacy clients see the first part only). Single
  `qa_correlation_id` for the whole compound; per-part
  `subquery_correlation_id` for tracing.
- [ ] **Anti-amplification cap.** Compound-query fan-out budget per
  request: `cfg.nlp_max_subqueries=3` AND combined fan-out (subqueries
  × per-subquery summary fan-out) ≤ `cfg.nlp_summary_max_fixtures=10`
  (single source — already in §10.6). Over-budget → degrade to first
  subquery only + explicit Turkish disclosure.
- [ ] **Proof:** `test_nlp_two_question_compound_splits_into_two_subqueries`,
  `test_nlp_compound_query_each_part_dispatches_independently`,
  `test_nlp_compound_query_aggregated_answer_carries_parts_array`,
  `test_nlp_compound_query_over_budget_degrades_first_only`,
  `test_nlp_compound_query_with_only_one_real_question_does_not_split`
  (false-positive guard).

#### 10.24.6 Negation-aware intent

- [ ] **Real failure mode.** *"sakat değil mi"* (= "isn't he injured?"
  — same intent as *"sakat mı"* but with negation framing),
  *"kazanmadı mı"* (= "didn't they win?"), *"oynayacak mı oynamayacak
  mı"* (rhetorical). The classifier currently treats negation as a
  surface feature; the **same intent** label fires for both polarities,
  but the **answer template** must reflect the negation framing
  (otherwise the rendered Turkish reads non-grammatically).
- [ ] **Negation marker extraction.** New entity span kind `negation`
  added to §10.5 entity enum. Markers: `değil`, `yok`, *V-ma/-me*
  verbal negation suffix (*"oynamayacak"*, *"kazanmadı"*), `hiç`,
  `asla`, `ne ... ne`. Extracted via gazetteer (closed list in
  `ai/nlp/lang_tr/negation_markers.tr.yaml` — small, ~30 entries).
- [ ] **Template polarity slot.** Every `predict.*` and `data.*`
  template carries a `polarity ∈ {affirm, negate}` slot; renderer
  picks the right Turkish phrasing (template authors implement both
  branches; `make nlp.template-lint` (§10.7) extends to assert every
  template defines both — refuses build if a template uses `polarity`
  but only renders the affirm branch).
- [ ] **Double-negation collapse.** *"kazanmadı değil mi"* (= rhetorical
  affirmation) → polarity `affirm` (mathematical: two negations
  cancel). Closed table at `ai/nlp/lang_tr/double_negation.tr.yaml`
  enumerates the recognised collapse patterns; outside the table →
  fall through to single-negation (do NOT silently collapse).
- [ ] **Proof:** `test_nlp_sakat_degil_mi_resolves_to_negate_polarity`,
  `test_nlp_kazanmadi_extracts_negation_via_verbal_suffix`,
  `test_nlp_template_lint_refuses_polarity_without_negate_branch`
  (CI gate), `test_nlp_double_negation_collapses_to_affirm_via_table`,
  `test_nlp_unknown_double_negation_falls_through_to_single`.

#### 10.24.7 Compound / hyphenated club name handling

- [ ] **Real failure mode.** Turkish club names commonly carry corporate
  / sponsor / city prefixes that the user may include or omit:
  *"MKE Ankaragücü"* / *"Ankaragücü"*; *"Çaykur Rizespor"* / *"Rize"*
  / *"Rizespor"*; *"İstanbul Başakşehir"* / *"Başakşehir"*;
  *"Yukatel Kayserispor"* (sponsor changes seasonally —
  *"Mondihome Kayserispor"* prior season). Naive longest-non-overlapping
  gazetteer (§10.5) on the abbreviated form does NOT match the
  canonical entry that includes the prefix.
- [ ] **Affix-tolerant gazetteer pass.** Lexicon `teams.tr.yaml`
  carries an `affixes: {prefix: [], suffix: []}` block per canonical
  entry (e.g., `MKE Ankaragücü` → `prefix: [MKE]`, `suffix: []`).
  Gazetteer build emits both the full form AND every affix-stripped
  form into the alias index, with a `frequency_score` favouring the
  full form (so when both *"MKE Ankaragücü"* and *"Ankaragücü"*
  appear in the same query, the longer match still wins per §10.5
  longest-non-overlapping rule).
- [ ] **Sponsor-rotation discipline.** Sponsor prefixes are season-
  scoped — `affixes.prefix` entries carry `valid_from_season` /
  `valid_until_season` fields (mirrors LeagueCatalog season schema).
  `make nlp.lexicon-build` consumes the active season window from
  Phase 13a `cfg.league_catalog_active_season` and emits sponsor
  prefixes only for the current season; historical sponsors are
  emitted as `historical_aliases` (resolved with a `nlp.event.v1{kind=
  historical_alias_used, season}` event so operators see when fans
  query with last-season's sponsor name).
- [ ] **City-name disambiguation.** *"Rize"* alone is ambiguous (city
  vs club shorthand). Gazetteer entry for the bare city carries
  `disambiguator_required: true`; resolution requires a co-token
  from `cfg.nlp_club_co_tokens=["maç","skor","kadro","fikstür",
  "puan","forma","hocası","teknik"]` within
  `cfg.nlp_club_disambiguation_radius=4` tokens; otherwise → routes
  through the §10.6 disambiguation answer offering both city and
  club options.
- [ ] **Proof:** `test_nlp_mke_ankaragucu_full_form_wins_over_short`,
  `test_nlp_short_ankaragucu_alone_resolves_to_canonical`,
  `test_nlp_historical_sponsor_emits_event`,
  `test_nlp_bare_city_rize_requires_co_token_for_club`,
  `test_nlp_lexicon_build_filters_sponsors_by_active_season`.

#### 10.24.8 Honorific / role-prefix normalization

- [ ] **Real failure mode.** *"hoca Buruk istifa etti mi"* (= "did
  manager Buruk resign?"), *"teknik direktör Mourinho"*,
  *"antrenör Montella"*, *"başkan Dursun Özbek"*. The honorific is a
  semantic role tag, not part of the person's name — gazetteer match
  on the full string fails, and stripping the honorific naively
  destroys the role context.
- [ ] **Honorific table at `ai/nlp/lang_tr/honorifics.tr.yaml`.** Closed
  list of TR football honorifics with their `role_class ∈ {manager,
  assistant_manager, president, captain, goalkeeper_coach, scout,
  player_generic}`. Detected at gazetteer step (§10.5) as a separate
  entity kind `role_prefix`; the following 1–3 tokens are tried as a
  person-name resolution against the lexicon's `players.tr.yaml`.
- [ ] **Role-bearing intent narrowing.** When `role_prefix=manager`
  and the person resolves, the dispatcher (§10.6) prefers
  `data.team_management_state` over `data.player_card_risk` for
  ambiguous intents — closes a real failure where *"hoca sakat mı"*
  (nonsensical: managers don't get injured the same way) currently
  routes to player-injury intent.
- [ ] **Person-name fallback chain.** Single-token person mention
  resolves via:
  1. Exact full-name match in `players.tr.yaml`.
  2. Last-name match → if multiple candidates, pick the one currently
     active for a team mentioned elsewhere in the same query.
  3. If still ambiguous → §10.6 disambiguation answer.
  Closed at v1; future versions may add similarity matching on
  romanized variants.
- [ ] **Proof:** `test_nlp_honorific_hoca_extracts_role_prefix`,
  `test_nlp_role_prefix_manager_narrows_intent_dispatch`,
  `test_nlp_lastname_resolution_prefers_currently_active_player`,
  `test_nlp_honorific_table_loaded_with_role_classes`.

#### 10.24.9 Emoji / pictograph as semantic *signal*, never decision

- [ ] **Real failure mode.** *"GS ❤️ "*, *"🔴🟡 maç ne zaman"* (Galatasaray
  colours), *"⚽ skor"*, *"🏆 şampiyon kim olur"*. Stripping all emoji
  loses meaningful entity hints; passing emoji to the classifier
  breaks fastText n-gram features (out-of-vocabulary unicode).
- [ ] **Emoji-to-hint table at `ai/nlp/lang_tr/emoji_hints.tr.yaml`.**
  Each emoji maps to a `hint` kind ∈ `{team_color, sport_football,
  market_outcome_win, market_outcome_loss, generic_decoration}` plus
  optional `team_color → [team_id, ...]` for color-pair hints
  (yellow+red → Galatasaray; yellow+navy → Fenerbahçe; black+white
  → Beşiktaş). Hints are **advisory only** — they bump entity
  resolution confidence but never override an explicit textual
  entity match.
- [ ] **Strip-after-hint-extraction.** Emoji are extracted and
  recorded as `entities[].hints` BEFORE classifier sees text; the
  classifier input is emoji-free (per §10.23.7 screen-reader format
  doctrine — same source). AST guard
  `test_nlp_classifier_input_emoji_free` walks the pipeline and
  asserts no codepoint in the Unicode `Emoji` property reaches the
  classifier feature extractor.
- [ ] **Decoration-only carrying.** Emoji classified as
  `generic_decoration` (e.g., 😂 ✨ 🙏 ) provide NO hint and are simply
  stripped — equivalent to noise tokens. Closed enum guarantees no
  emoji is silently treated as semantically meaningful without a
  table entry; build asserts every emoji codepoint frequency-observed
  in `data/nlp/eval/turkish_real_corpus.txt` is either in the table
  or in the closed `decorative_set` (§10.23.7).
- [ ] **No emoji ever rendered in the answer** (extends §10.23.7
  doctrine to all formats by default; opt-in via
  `cfg.nlp_answer_decorative_emoji_enabled=false` default; flipping
  to true requires `screen_reader` format to still strip per its own
  contract).
- [ ] **Proof:** `test_nlp_emoji_color_hint_recorded_as_advisory`,
  `test_nlp_classifier_input_emoji_free`,
  `test_nlp_emoji_hints_never_override_explicit_entity_match`,
  `test_nlp_unmapped_emoji_in_corpus_fails_build`,
  `test_nlp_answer_carries_no_emoji_by_default` (across all formats).

#### 10.24.10 Hashtag, @-mention, URL / HTML-entity hygiene

- [ ] **Real failure mode.** *"#GSFB skor"*, *"@galatasaray ne zaman
  oynar"*, *"https://maclive.tr/gs-fb maçta ne oldu"*, HTML-escaped
  *"galatasaray &amp; fenerbah&ccedil;e"* (from web copy-paste).
- [ ] **Hashtag handling.** New step 5a in §10.1 (after punctuation
  normalization, before diacritic restore). `#TOKEN` is split into
  `#` (dropped) + `TOKEN` (re-tokenized via §10.22.5 abbreviation
  table — so `#GSFB` → `[GS, FB]` → match-pair via §10.22.7 word-
  bridge inference). If the post-split tokens do NOT resolve, the
  entire hashtag is dropped (do NOT pass `#TOKEN` to the classifier).
- [ ] **@-mention handling.** `@TOKEN` is treated as a strong
  team-entity hint when `TOKEN` resolves to a known team handle
  (closed map at `ai/nlp/lang_tr/social_handles.tr.yaml` —
  `@galatasaray` → Galatasaray; `@fenerbahce` → Fenerbahçe;
  `@efootball_tr` → ignored / not-a-team). Strict allow-list — any
  mention not in the table is dropped (defends against
  attacker-controlled mention injecting fake entity hints).
- [ ] **URL stripping.** Any token matching the §10.21.5 URL regex
  (single source from sec layer) is stripped pre-classifier; the
  domain is recorded as `request_metadata.urls_seen[]` for operator
  visibility (NEVER passed to the answer or the LLM). Forward
  contract: when Phase 16 emitter publishes a `qa.answer.v1`, the
  URL list is NOT carried (PII / phishing vector — single source
  for stripping at NLP intake).
- [ ] **HTML-entity unescape.** New step 1.5 in §10.1 (between length
  cap and NFC). `html.unescape(text)` — handles `&amp;`, `&ccedil;`,
  `&#252;`, `&#x00FC;`. AST guard
  `test_nlp_html_unescape_runs_before_nfc` asserts the order (NFC
  on the *unescaped* form, not the escaped). Bounded: the unescape
  cannot grow input length (HTML entities are always ≥ 4 chars
  representing 1 codepoint), so no bypass of §10.1 length cap.
- [ ] **Proof:** `test_nlp_hashtag_gsfb_resolves_to_match_pair`,
  `test_nlp_at_mention_galatasaray_strong_hint`,
  `test_nlp_unknown_at_mention_dropped`,
  `test_nlp_url_stripped_recorded_in_metadata_only`,
  `test_nlp_html_entity_unescape_runs_before_nfc`,
  `test_nlp_html_unescape_does_not_bypass_length_cap`.

#### 10.24.11 Decimal-comma / score-line numeric disambiguation

- [ ] **Real failure mode.** *"1,5 üst"* (= "over 1.5" — TR uses comma
  as decimal separator) vs *"1,0 maç skoru"* (= "score 1-0" — comma
  as thematic separator). *"2.5 alt"* (Turkish-typed but with `.`
  separator). *"3,5 - 4,5 arası"* (range). The §10.5 score CRF
  template currently treats every two-digit-comma-digit pattern as
  a candidate score, mis-classifying decimal odds-line markets.
- [ ] **Context-aware numeric disambiguation.** New rule in
  `ai/nlp/lang_tr/numeric_context.tr.yaml`:
  - `\d+[,\.]\d+` followed-or-preceded within 2 tokens by `[üst,
    alt, ust, alt]` → market-line decimal (`market=ou`,
    `line=parsed`); both `,` and `.` accepted.
  - `\d+[-:,]\d+` flanked by `[skor, sonuç, score, biten, ilk yarı,
    iy]` → score line (`market=score`, `home=N`, `away=M`).
  - Bare `\d+,\d+` with NO context co-token AND digits both ≤ 9 →
    ambiguous → §10.6 disambiguation answer offering both
    interpretations (do NOT silently pick).
- [ ] **Score / market template share NO numeric parser.** AST guard
  rejects calling `score_parser` and `market_line_parser` on the
  same span — the disambiguation step picks ONE before parsing.
- [ ] **TR locale numeric format on output.** All numbers rendered in
  answers go through `ai/common/text/tr_format.py::tr_format_number`
  / `tr_format_money` (§10.23.5 — single source) — input may be
  comma-or-dot, output is always TR locale (comma decimal, dot
  thousands). Cross-language byte parity test added: same input →
  same byte output across Python and Go consumers.
- [ ] **Proof:** `test_nlp_one_comma_five_ust_resolves_to_ou_15`,
  `test_nlp_one_comma_zero_skor_resolves_to_score_1_0`,
  `test_nlp_bare_decimal_no_context_routes_to_disambiguation`,
  `test_nlp_score_and_market_parser_never_called_on_same_span`
  (AST), `test_nlp_numeric_output_always_tr_locale_format`.

#### 10.24.12 Garden-path backtracking & abstention discipline

- [ ] **Real failure mode.** *"kara kartal puan durumu"* (= Beşiktaş
  nickname "Black Eagle" + "standings"). The first gazetteer pass
  may match *"kara"* (= "black", color literal) AND *"kartal"* (=
  district name on Anatolian side of Istanbul) as separate spans,
  blocking the *"Kara Kartal"* compound team-nickname match.
  Result: classifier sees fragmented entities + low intent
  confidence → did-you-mean.
- [ ] **Backtracking trigger.** When intent confidence < the
  abstention threshold (§10.4 `cfg.nlp_min_intent_conf=0.55`) BUT
  there exists a multi-span entity coalescence that would yield a
  higher-confidence intent, re-run the gazetteer pass with the
  coalesced span as a single token (one retry only — bounded). The
  multi-token-nickname allow-list lives at
  `ai/nlp/lang_tr/team_nicknames.tr.yaml` (*"Kara Kartal"* →
  Beşiktaş; *"Sarı Kanaryalar"* → Fenerbahçe; *"Cim Bom"* →
  Galatasaray; *"Bordo Mavililer"* → Trabzonspor).
- [ ] **Backtrack budget.** `cfg.nlp_backtrack_max_attempts=1` (one
  retry per query); over-budget → fall through to abstention. Budget
  enforced in the dispatcher (§10.6) post-classifier; never reached
  on a clean intent.
- [ ] **Abstention-corpus floor.** Adversarial corpus
  (§10.18 + §10.21) includes a 50-row `random_token_flood` slice —
  100% MUST trigger `meta.unsupported` or `did_you_mean`, not a
  guessed predict / data intent. Closes the real failure where the
  classifier would emit a low-but-above-threshold intent on garbage
  input.
- [ ] **Proof:** `test_nlp_kara_kartal_compound_resolves_to_besiktas_after_backtrack`,
  `test_nlp_backtrack_capped_at_one_retry`,
  `test_nlp_random_token_flood_routes_to_meta_unsupported`
  (50-row slice, 100% pass), `test_nlp_compound_nickname_table_resolves_to_catalog`.

#### 10.24.13 Empty / pathological / single-character input

- [ ] **Real failure mode.** Empty body `""`, whitespace-only `"   "`,
  single-character `"a"` / `"?"`, all-punctuation `"!!!??!"`,
  zero-information `"merhaba"` (greeting — not a football query).
  Currently §10.1 step 1 caps length but does NOT define floor
  behaviour; classifier may produce undefined output on empty token
  list.
- [ ] **Floor gate.** New §10.1 step 0 (BEFORE length cap):
  `assert_minimum_signal(text)`:
  - Empty / whitespace-only → return canned `qa.answer.v1{intent=
    meta.help}` (Turkish greeting + "Bana bir maç ya da takım
    sorabilirsin"). Skip the entire pipeline; emit
    `nlp.event.v1{kind=empty_input_floor_response}`.
  - Token-count post-tokenization < `cfg.nlp_min_tokens=1` AND no
    digits / no entity → same canned response.
  - Greeting-only input (matched against
    `ai/nlp/lang_tr/greetings.tr.yaml` — *"merhaba"*, *"selam"*,
    *"selamün aleyküm"*, *"slm"*, *"meraba"*, *"merhabalar"*) →
    canned `meta.help` answer with greeting echo (the ONE place the
    answer carries a back-reference to user input — explicitly
    safe: greeting table is closed; no user free text).
- [ ] **Single-character non-question input.** `"a"`, `"x"` →
  `meta.help` canned answer + `meta.unsupported_too_short` event.
- [ ] **All-punctuation input.** `"!!!"`, `"???"`, `"..."` → same
  canned response.
- [ ] **Proof:** `test_nlp_empty_input_returns_canned_help_no_pipeline`,
  `test_nlp_whitespace_only_input_handled`,
  `test_nlp_single_char_input_handled`,
  `test_nlp_all_punctuation_input_handled`,
  `test_nlp_greeting_input_returns_help_with_safe_echo`,
  `test_nlp_greetings_table_is_closed_set`
  (no user free text in echo path).

#### 10.24.14 Knob inventory + DoD aggregate

- [ ] **New cfg knobs (~17, on top of §10.22.14):**
  `nlp_repeat_collapse_min_freq=100`,
  `nlp_repeat_collapse_max_len=64`,
  `nlp_max_subqueries=3`,
  `nlp_min_tokens=1`,
  `nlp_backtrack_max_attempts=1`,
  `nlp_club_co_tokens=["maç","skor","kadro","fikstür","puan","forma","hocası","teknik"]`,
  `nlp_club_disambiguation_radius=4`,
  `nlp_answer_decorative_emoji_enabled=false`,
  `nlp_combining_mark_max_per_token=4`,
  `nlp_digit_letter_fold_enabled=true`,
  `nlp_negation_enabled=true`,
  `nlp_compound_query_enabled=true`,
  `nlp_emoji_hint_enabled=true`,
  `nlp_hashtag_handling_enabled=true`,
  `nlp_at_mention_handling_enabled=true`,
  `nlp_html_unescape_enabled=true`,
  `nlp_harmony_tolerant_strip_enabled=true`.
  Triangle test extends; Go-side `TestEnvSync` covers any knob
  consumed by `server/internal/sec/sanitize.go`
  (`nlp_combining_mark_max_per_token` flows cross-language —
  bytes-parity contract from §10.24.4).
- [ ] **New `nlp.event.v1` kinds** (open-enum, registered):
  `suffix_harmony_repaired`,
  `digit_letter_confusable_folded`,
  `historical_alias_used`,
  `compound_query_split`,
  `empty_input_floor_response`,
  `garden_path_backtrack_succeeded`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `excessive_combining_marks` (warn, debounced 60s).
- [ ] **Updated wire schema.** `qa.answer.v1` schema_version 1→2
  additive: `parts: [{intent, body, citation, polarity,
  subquery_correlation_id}]` array (legacy clients see top-level
  `intent` + `body` from `parts[0]` via consumer-side fallback —
  schema-evolution doctrine §10.21.11). Boundary test: producer
  ALWAYS populates `parts[]` (single-question case = 1-element
  array) so consumers may rely on it; legacy `intent` / `body`
  duplicated for `parts[0]` only.
- [ ] **DoD proof tests aggregate (new in §10.24):**
  - §10.24.1 — 4 tests
  - §10.24.2 — 5 tests (incl. hypothesis property)
  - §10.24.3 — 4 tests
  - §10.24.4 — 5 tests (incl. cross-language bytes parity)
  - §10.24.5 — 5 tests
  - §10.24.6 — 5 tests
  - §10.24.7 — 5 tests
  - §10.24.8 — 4 tests
  - §10.24.9 — 5 tests
  - §10.24.10 — 6 tests
  - §10.24.11 — 5 tests
  - §10.24.12 — 4 tests (incl. 50-row flood corpus)
  - §10.24.13 — 6 tests
  - **Total: ≈ 63 new proof tests on top of §10.20 + §10.21 + §10.22 + §10.23 baseline.**
- [ ] **`make swarm.demo.nlp.full` extends** to cover the §10.24
  paths: one query each for harmony-violation recovery, repeated-char
  collapse, digit-letter fold, decomposed-İ NFC composition, run-on
  multi-question split, negation framing, MKE Ankaragücü
  affix-tolerant match, hoca-honorific role narrowing, color-emoji
  hint, hashtag/mention hygiene, decimal-vs-score disambiguation,
  Kara Kartal nickname backtrack, empty-input canned help. Total
  demo runtime stays ≤ 60s for `.full` (per §10.23 split — the
  `.fast` variant remains < 30s).
- [ ] **Cross-phase contracts updated.**
  - **Phase 7 sec layer.** §10.24.4 Turkish-dotted-i compose helper
    is shared with `server/internal/sec/sanitize.go`; cross-language
    byte parity test added to the §10.20 boundary suite (mirrors
    §7.6 doctrine — single source for normalization rules).
  - **Phase 9 API gateway.** `qa.answer.v1` schema bump 1→2 adds
    the `parts[]` field; gateway response renderer prefers
    `parts[]` when present, falls back to top-level fields for
    schema-version=1 producers (forward-compat consumer doctrine).
  - **Phase 13a LeagueCatalog.** Sponsor-affix discipline
    (§10.24.7) consumes `cfg.league_catalog_active_season`;
    catalog-loader change at Phase 13a does NOT change NLP code —
    only regenerates lexicons via `make nlp.lexicon-build`.
  - **Phase 16 Emitter.** Hint structures (§10.24.9 emoji,
    §10.24.10 social-handle) flow through `LexiconStore` Protocol
    same as §10.22 lexicons — no NLP code change across in-memory
    → Postgres → feed swap.
  - **Phase 19 long-tail leagues.** Compound-name affix table
    (§10.24.7) grows additively per league; AST guard
    `test_nlp_no_per_league_branch` (already in §10.20) still
    holds — no `if league_id == ...` introduced.
- [ ] **Documentation.** `docs/design/TURKISH_NLP.md` gains a
  "Wrong-Turkish Tolerance Catalogue" section enumerating every
  §10.24 rule with worked examples (real-Turkish-fan corpus
  excerpts, PII-scrubbed). `docs/guides/nlp_runbook.md` gains a
  "Repair-density triage by class" section pointing operators at
  the §10.22.13 telemetry counters extended in §10.24.

### 10.25 Lifecycle, conversation, and time-travel addendum (binding)

> **Why this section exists.** §10.0–§10.24 specify a *correct, robust,
> messy-input-tolerant, production-served* single-shot pipeline. They
> say nothing about (a) how a second message in the same conversation
> reuses the first, (b) how an answer streams to the client when a 600
> ms humanizer run would otherwise pin the response, (c) how an auditor
> reproduces a 6-month-old answer byte-identically, (d) how the four
> versioned artifacts (lexicon × intent × CRF × calibration × template)
> are kept compatible across rollouts, (e) how the intent model itself
> is retrained, (f) who writes new lexicon entries and how they are
> reviewed, (g) how a `did-you-mean` suggestion accepted by the user
> feeds back into the system, (h) how to detect when lexicons have
> stopped covering real input, (i) how a Phase 8 `quarantine_erase`
> propagates through NLP's caches and spool, (j) how an advertiser /
> legal ban-list overrides at render-time without poisoning the
> classifier, (k) what happens when Phase 5 `consensus.v1` is not yet
> emitting at NLP cold-start, (l) what happens when a Saturday matchday
> has more than `nlp_summary_max_fixtures` fixtures, and (m) how Turkish
> religious / national holidays interact with the date resolver. Every
> `[ ]` here is binding for Phase 10 DoD (per §10.20 item 23). New cfg
> knobs land alongside §10.19 / §10.21.12 / §10.22.14 / §10.23.13 /
> §10.24.14 in the same triangle commit.

#### 10.25.1 Multi-turn conversation context (stateful follow-ups, bounded scope)

- [ ] **Real gap §10.0–§10.24 misses.** Every `qa.request.v1` is treated
  as stateless. A user asking "Galatasaray Fenerbahçe maçı ne zaman?"
  followed by "tahmin ne?" forces the second query through the full
  pipeline with no context — intent classifier hits `meta.unsupported`
  (no entity), dispatcher fires `did-you-mean`. Real chat UX is broken.
- [ ] **`qa.context.v1` (data plane, additive).** New topic;
  `additionalProperties:false`; producer = `nlp.dispatcher.v1`;
  consumer = `nlp.intent.v1`. Schema:
  `{conversation_id (uuid), turn_index (≥0), entities[] (frozen
  resolved entities from prior turn — NOT raw text), intent (last),
  expires_at_utc, schema_version=1}`. NEVER carries text — the entity
  list is the only conversational handle. PII guarantee identical to
  §10.21.7 spool: text is fetched on-demand from the bus by
  `request_id` if needed, never persisted in the context envelope.
- [ ] **Conversation lifetime caps.** `cfg.nlp_conversation_max_turns=8`
  (hard cap; over-cap → context dropped, fresh start, info event);
  `cfg.nlp_conversation_idle_ttl_s=180` (3 min idle → expire);
  `cfg.nlp_conversation_redis_key_prefix="nlp:ctx:"`; per-pod LRU L0 +
  Redis L1 (mirrors §10.23.9 5-component cache key, +`conversation_id`
  as 6th component). Redis-down → fall-through to stateless (NEVER
  block on context).
- [ ] **Authority of explicit re-mention.** When the new turn contains
  an entity that conflicts with the carried context (user changes
  team), the new entity wins; carried entities of the same `kind` are
  evicted; `nlp.event.v1{kind=conversation_entity_overridden}` debounced.
  Closed precedence rules in `ai/nlp/conversation/precedence.tr.yaml`.
- [ ] **Conversation-id authority.** API gateway (Phase 9) mints
  `conversation_id` per session token (per device, not per user — multi-
  device users get distinct contexts deliberately to avoid cross-device
  surprise). Anonymous users get `conversation_id = null`; NLP runs
  stateless. Boundary test: `test_nlp_anonymous_request_has_no_context`.
- [ ] **Adversarial.** Carried context MUST NOT survive a
  `proofreader_blocked` turn (e.g., a slur turn poisoning the next).
  Block → context cleared + `nlp.alert.v1{kind=conversation_context_cleared_after_block, severity=info}`.
- [ ] **Tier-aware (Phase 20 hook, dormant).** `cfg.nlp_conversation_enabled_tier_floor=0`
  default 0 (everyone); Phase 20 may flip to gate behind a tier.
- [ ] **Proof:** `test_nlp_followup_resolves_entity_from_context`,
  `test_nlp_context_capped_at_max_turns`, `test_nlp_context_idle_ttl_evicts`,
  `test_nlp_explicit_team_mention_overrides_context`,
  `test_nlp_proofreader_block_clears_context`,
  `test_nlp_redis_down_falls_through_to_stateless` (skip-if-no-redis).

#### 10.25.2 Streaming response (SSE / chunked humanizer w/ mid-stream proofreader gate)

- [ ] **Real gap §10.7 / §10.8 / §10.9 misses.** Humanizer p95 600 ms is
  acceptable for one-shot but feels broken in a chat UI vs the same
  time spent token-streaming. §10.9 proofreader is whole-answer; if
  applied post-stream, the user has already seen forbidden-phrase
  tokens before they're masked. Naïve streaming = PII / jailbreak echo.
- [ ] **Two-pass guarded streaming.** New mode
  `cfg.nlp_answer_streaming=disabled|guarded|off` default `disabled`
  at v1 (rolled out behind explicit operator flag). Under `guarded`:
  (1) template renders deterministically and is **fully** proofread
  via §10.9 → "skeleton" answer; (2) skeleton chunks emitted to client
  immediately as SSE; (3) humanizer runs in parallel on skeleton +
  context, producing "polish" tokens; (4) per-chunk proofreader gate
  (re-run §10.9 gates 2/4/5 — English drift, PII, forbidden-phrase —
  on each accumulated buffer of `cfg.nlp_streaming_proofread_chunk_chars=80`);
  (5) chunk fails gate → stream cuts to skeleton continuation +
  `nlp.alert.v1{kind=streaming_humanizer_chunk_blocked, severity=warn}`.
- [ ] **Citation block NEVER streamed.** Citation MUST land as the final
  whole-block frame after humanize completes; if humanize fails mid-
  stream, citation lands attached to the skeleton continuation. AST
  guard: `test_nlp_citation_never_in_streaming_chunk`.
- [ ] **Backpressure.** Slow client (write blocks > `cfg.nlp_streaming_write_timeout_ms=2000`)
  → cancel humanize, fall to skeleton-only completion, emit
  `nlp.event.v1{kind=streaming_client_slow_canceled}`. Mirrors Phase 9
  §9.17.4 slow-client doctrine.
- [ ] **Cancellation contract.** `predict.cancel.v1` (Phase 9) → also
  cancels the humanize call; in-flight chunks NOT sent after cancel.
  Boundary test: `test_nlp_streaming_honors_predict_cancel`.
- [ ] **Cache coherence.** Streamed answers cached as `(chunks[], final)`
  tuple under same §10.23.9 key; cache hit returns the assembled answer
  in one shot (NOT replayed as a stream — re-streaming a cached answer
  fakes "live generation" and is forbidden). AST guard:
  `test_nlp_cached_answer_never_re_streamed`.
- [ ] **Proof:** `test_nlp_streaming_skeleton_first_then_polish`,
  `test_nlp_streaming_chunk_blocked_on_pii`,
  `test_nlp_streaming_slow_client_cancels_humanize_in_under_2s`,
  `test_nlp_streaming_disabled_mode_falls_through_to_oneshot`,
  `test_nlp_citation_never_in_streaming_chunk` (AST),
  `test_nlp_cached_answer_never_re_streamed` (AST).

#### 10.25.3 Time-travel audit re-render bundle (forensic reproducibility)

- [ ] **Real gap §10.14 / §10.21.7 misses.** Sampled audit captures the
  answer text but not the artifact-snapshot needed to re-render it 6
  months later for legal / regulatory / drift-investigation purposes.
  Re-deriving requires: lexicon snapshot SHAs (all 6+1 files at swap
  generation), `intent.tr.bin.sha256`, `crf.tr.model.sha256`,
  calibration version, template git SHA, `pipeline_version`, fixture
  state from `predict.approved.v1`, `request_id`, normalized text.
- [ ] **`nlp_audit_bundle_sha` field added to sampled audit row.** Single
  hex string = sha256 over the canonical-form quintet
  `(lexicon_snapshot_sha, intent_model_sha, crf_model_sha,
  calibration_version, template_git_sha, pipeline_version)`. Acts as a
  pointer; the actual bundle lives in `data/nlp/audit_bundles/<sha>/`
  (immutable; populated on first observation; later requests with the
  same quintet reuse the same dir).
- [ ] **Bundle contents.** `manifest.json` (the quintet + UTC timestamp
  of first observation + retention class) + `lexicons/*.tr.yaml.sha256`
  (SHAs only — actual bytes recovered from Phase 16 lexicon feed
  cold-storage by SHA) + `intent.tr.bin.sha256` + `crf.tr.model.sha256`
  + `templates/*.j2.sha256` (resolved against repo `templates/` at
  `template_git_sha`). NEVER the raw model bytes (would explode disk
  + duplicate Phase 16 cold storage).
- [ ] **`make nlp.audit-rerender BUNDLE=<sha> REQUEST_ID=...`** runbook
  CLI: fetches the original `qa.request.v1` from Phase 8 backup if
  retention permits, fetches `predict.approved.v1` similarly, rebuilds
  a sandboxed Python venv pinned to the chart compat block of the
  bundle's date, re-renders, asserts byte-equality with the audited
  answer text. Operator-only; logged as `maint.event.v1{kind=nlp_audit_rerender_executed}`.
- [ ] **Retention.** Bundle dirs retained `cfg.nlp_audit_bundle_retention_days=2555`
  (7 years — matches `pii_erased` retention floor in §8.3 doctrine for
  legal-hold compatibility). Storage cost negligible (SHAs only, not
  bytes). Per-quintet dedup makes total dir count ≪ total request count.
- [ ] **Right-to-erasure interaction.** `quarantine_erase` (§10.25.9)
  nullstamps the audit ROW; bundle dir is unaffected (the bundle
  doesn't contain user PII — it's artifact metadata only).
- [ ] **Proof:** `test_nlp_audit_row_carries_bundle_sha`,
  `test_nlp_bundle_quintet_canonical_form_byte_stable`,
  `test_nlp_audit_rerender_dry_run_produces_byte_identical_answer`
  (compose-mode, mocked Phase 8 lookups),
  `test_nlp_bundle_dir_dedupes_across_requests`,
  `test_nlp_bundle_dir_contains_no_raw_user_text`.

#### 10.25.4 Cross-artifact compatibility matrix (lexicon × intent × CRF × calibration × template)

- [ ] **Real bug §10.21.1 / §10.21.2 / §10.21.4 misses.** Each artifact
  is SHA-pinned individually but nothing pins their *compatible
  product*. A new `intent.tr.bin` trained on a lexicon snapshot that
  introduced a new market alias may classify queries into a market enum
  value the calibration table doesn't have — silent miscalibration. A
  new template referencing `entity.role_class` (added in §10.24.8)
  paired with an old CRF that doesn't emit it → render-time
  `UndefinedError` under StrictUndefined.
- [ ] **`compatibility_matrix.json`** (new file at
  `ai/nlp/_compat/compatibility_matrix.json`, schema_version=1,
  `additionalProperties:false`). One row per `pipeline_version`. Each
  row pins the exact compatible quartet:
  `{pipeline_version, lexicon_set_sha (computed over sorted SHA list of
  all lexicon files at that snapshot), intent_model_sha, crf_model_sha,
  calibration_version_min..max, template_git_sha, humanizer_model_sha,
  introduced_at_utc, retired_at_utc?}`. Append-only; `retired_at_utc`
  set when a row is no longer accepted at boot.
- [ ] **Boot-time validator.** NLP agent at startup walks the matrix,
  finds the row matching its current `pipeline_version`, asserts every
  loaded artifact SHA matches; mismatch → refuse boot +
  `nlp.alert.v1{kind=nlp_compatibility_quartet_mismatch, severity=critical, missing: [...]}`.
- [ ] **Calibration version range.** Calibration is the only artifact
  that can move forward without a coordinated rollout (new calibration
  every Phase 5 retrain). Each compat row carries `calibration_version_min..max`;
  out-of-range → refuse the specific calibration (degrades to template-
  only mode for that intent group, NEVER renders a half-calibrated
  answer).
- [ ] **CI gate.** `make nlp.compat-validate` runs before any PR that
  touches `ai/nlp/lexicon/`, `intent.tr.bin*`, `crf.tr.model*`,
  `ai/nlp/templates/`, or the humanizer pin in chart.json. Refuses
  merge if a new artifact lands without a matching new matrix row.
- [ ] **Lockstep with `pipeline_version`.** §10.23.9 cache key already
  includes `pipeline_version`; the matrix bumps `pipeline_version` on
  every quartet change → cache naturally evicts. AST guard:
  `test_nlp_pipeline_version_bumped_when_quartet_changed`.
- [ ] **Proof:** `test_nlp_compat_matrix_loaded_at_boot`,
  `test_nlp_compat_quartet_mismatch_refuses_boot`,
  `test_nlp_calibration_out_of_range_degrades_to_template_for_intent_group`,
  `test_nlp_compat_matrix_append_only_no_row_mutation` (AST),
  `test_nlp_pipeline_version_bumped_when_quartet_changed` (CI gate).

#### 10.25.5 Intent-model retraining lifecycle (data sourcing, gating, rollback)

- [ ] **Real gap §10.4 misses.** Treats `intent.tr.bin` as an immutable
  SHA-pinned blob. Reality: classifier accuracy decays as fan slang
  evolves; we need a documented retraining loop with safety gates.
- [ ] **Data sourcing.** Training corpus assembled from `nlp.shadow.v1`
  weekly continuous-eval samples (§10.23.3) — already PII-scrubbed,
  trunc 200, UNK-replaced, 3-of-5 labelled. NEVER from raw audit logs;
  NEVER from `qa.request.v1` text directly; NEVER from a user-supplied
  upload. Boundary AST: `test_nlp_intent_trainer_imports_only_shadow_v1`.
- [ ] **`make nlp.intent-train`** (operator-driven, NEVER CI-auto-trains
  prod) writes a candidate `intent.tr.bin.candidate`; runs §10.18 eval
  harness; refuses to label as candidate if ANY of the §10.18 gates
  regress (intent acc, entity F1, did-you-mean coverage, adversarial
  block, suffix harmony golden) by > `cfg.nlp_intent_retrain_max_regression=0.005`
  on the held-out slice + dialect/code-switch/honorific/negation slices
  added by §10.24.
- [ ] **Canary promotion.** Mirrors §10.23.2 model-canary: pod-level env
  flag, 10% sticky on `(account_id // 1000)`; shadow-mode at 1%; 72h
  observation window; promote on `make nlp.intent-promote` only if
  shadow disagreement ≤ 0.03 AND |Δp95 confidence| ≤ 0.05 AND
  continuous-eval (§10.23.3) shows no regression.
- [ ] **Rollback runbook.** `make nlp.intent-rollback` swaps the active
  symlink back to the prior SHA-pinned blob; readiness drops + reboots
  pods; emits `maint.event.v1{kind=nlp_intent_rolled_back, from_sha,
  to_sha, reason}`. Time budget: ≤ 15 min from operator decision to
  full cluster on prior model.
- [ ] **Calibration coupling.** Every new intent model triggers a
  Platt-recalibration pass on the same shadow slice; the new
  `intent.tr.calibration.json` is pinned in the §10.25.4 compat row.
- [ ] **Proof:** `test_nlp_intent_train_refuses_on_regression`,
  `test_nlp_intent_canary_blocks_promote_on_disagreement`,
  `test_nlp_intent_rollback_reverts_within_budget` (compose-mode mock),
  `test_nlp_intent_trainer_data_source_is_shadow_only` (AST).

#### 10.25.6 Lexicon contributor governance (PR-gated alias delta, two-reviewer rule)

- [ ] **Real gap §10.2 misses.** Says "build pipeline regenerates from
  LeagueCatalog + per-league preset modules + a hand-curated alias
  delta file" but doesn't say **who** writes the delta, **how**
  conflicts are reviewed, **what** review is required for the
  highest-leverage tables (markets, entities_negative — corruption
  here mis-routes every betting query per §10.22.12 doctrine).
- [ ] **`ai/nlp/lexicon/_aliases_delta.tr.yaml`** is the only file
  humans edit; CODEOWNERS requires ≥ 1 reviewer for routine adds.
  `markets.tr.yaml` + `entities_negative.tr.yaml` + `dialect.tr.yaml` +
  `phonetic_aliases.tr.yaml` + `offensive.tr.yaml` are
  GENERATED-OR-HIGH-LEVERAGE: any direct edit requires **2 reviewers
  (CODEOWNERS rule)**, one of whom carries the `nlp-curator` GitHub
  team membership. CI: `make verify.nlp-codeowners` enforces.
- [ ] **`source` annotation per delta entry.** Every alias_delta row
  carries `{alias, canonical_id, kind, source: <free_text>, added_by_pr,
  added_at_utc}`. `source` must be one of: `tff_official`, `mackolik`,
  `nesine`, `openfootball`, `fan_corpus_<n>`, `operator_curation`. CI
  refuses unknown sources. Catches "someone made up an alias" bugs.
- [ ] **Conflict review.** `make nlp.lexicon-build` runs the §10.21.3
  cross-file referential validator BEFORE producing the build artifact.
  Any new alias that maps to a canonical not in LeagueCatalog →
  refuses build. New alias that collides with an existing alias under
  a *different* canonical → refuses build unless a corresponding
  `entities_negative` disambiguator is added in the same PR.
- [ ] **Acceptance corpus regression.** `make nlp.lexicon-eval`
  re-runs the §10.18 evaluation harness after lexicon-build but
  BEFORE accepting the diff. Any regression > 0.5% on entity F1 fails
  the PR. Same pattern as intent-model retraining gate (§10.25.5).
- [ ] **Per-league quota.** `cfg.nlp_lexicon_max_aliases_per_canonical=12`
  hard cap — defends against "quoting the manager's nickname graph"
  bloat that hurts Symspell precision. Over-quota → CI fail with
  message naming the offending canonical.
- [ ] **Proof:** `test_nlp_alias_delta_source_in_closed_set` (CI),
  `test_nlp_high_leverage_files_require_two_reviewers` (CODEOWNERS
  parse), `test_nlp_alias_collision_without_negative_disambiguator_fails_build`,
  `test_nlp_lexicon_eval_regression_blocks_pr`, `test_nlp_alias_per_canonical_quota_enforced`.

#### 10.25.7 Did-you-mean feedback loop (active learning, no PII echo)

- [ ] **Real gap §10.4 / §10.6 misses.** "Did-you-mean" abstention is a
  one-way door — the system never learns from which suggestion the
  user accepted. Over time, the same correctable inputs keep hitting
  the abstention path.
- [ ] **`qa.feedback.v1`** (data-plane, additive). Producer = API
  gateway (Phase 9, when the user clicks a suggestion or re-types
  within 30s of a `did-you-mean`); consumer = `nlp.dispatcher.v1` →
  active-learning queue. Schema:
  `{request_id, did_you_mean_offered_intents[], accepted_intent (or
  null if user retyped instead), original_qa_correlation_id,
  schema_version=1}`. NEVER carries text — accepted_intent is one of
  the closed enum values.
- [ ] **Active-learning queue.** Bounded ring buffer
  `cfg.nlp_active_learning_queue_max=10000` per pod; oldest evicted
  when full + `nlp.event.v1{kind=active_learning_queue_overflow}`
  debounced. Spilled to disk weekly via `make nlp.active-learning-spill`
  (operator-driven, mirrors §10.23.3 weekly cron).
- [ ] **Active-learning data hygiene.** Spilled rows are PII-scrubbed
  identically to §10.23.3 shadow rows; same 3-of-5 labeller agreement
  required before promotion into intent-retrain corpus (§10.25.5).
  Active-learning data is ONLY one input among many — never the sole
  source for a retrain (defends against feedback loops where an early
  classifier mistake re-trains itself).
- [ ] **Suggestion provenance.** `did_you_mean_offered_intents[]` MUST
  match exactly what was rendered to the user; mismatch in
  `qa.feedback.v1` (e.g., user accepted an intent that wasn't offered)
  → drop + `nlp.alert.v1{kind=feedback_provenance_mismatch, severity=warn}`.
  Defends against client-side tampering.
- [ ] **NEVER personalise.** Feedback signal aggregates across users
  only (no per-user adaptation in v1). AST guard:
  `test_nlp_feedback_processor_does_not_branch_on_user_id`.
- [ ] **Proof:** `test_nlp_feedback_v1_schema_round_trip`,
  `test_nlp_feedback_provenance_mismatch_dropped`,
  `test_nlp_feedback_queue_overflow_evicts_oldest`,
  `test_nlp_feedback_processor_does_not_branch_on_user_id` (AST),
  `test_nlp_feedback_spill_pii_scrubbed_identically_to_shadow`.

#### 10.25.8 Lexicon coverage telemetry (entity-hit-rate as drift leading indicator)

- [ ] **Real gap §10.14 / §10.22.13 misses.** Tracks input-repair density
  (a quality-of-input signal) but NOT lexicon coverage (a quality-of-
  lexicon signal). When a new fan-coined nickname ("Cimbom Junior" for
  a youth player who debuted last week) hits 10% of queries before the
  lexicon ships an alias, we have no leading signal — we only see the
  downstream rise in `did-you-mean` and `meta.unsupported`.
- [ ] **`nlp_lexicon_coverage` histogram.** Per-intent-class buckets
  `{0.0, 0.25, 0.5, 0.75, 1.0}` — fraction of resolvable-class tokens
  in the input that hit the gazetteer (numerator = gazetteer-hit
  tokens of class team/player/league/competition/market; denominator
  = all "content" tokens after stopword strip). Computed per query;
  exported to telemetry.v1.
- [ ] **`nlp_unresolved_token_top_k`** (rolling, capped at
  `cfg.nlp_unresolved_token_top_k=50` per hour, PII-scrubbed via the
  long-string heuristic from §10.21.7). Operators see "the 50 most
  common tokens we couldn't resolve last hour" → directly actionable
  alias_delta candidates. Capped count + per-token sha8 prevents
  exfiltration vector. Reset hourly.
- [ ] **Drift alerts.** `cfg.nlp_lexicon_coverage_p50_floor=0.6` per
  intent class on a 1h sliding window; sustained breach for > 30 min
  → `nlp.alert.v1{kind=lexicon_coverage_below_floor, intent_class,
  observed_p50, severity=warn}`. Multiple intent classes breaching
  simultaneously upgrades to `severity=error` (likely lexicon
  catastrophe — Phase 16 feed corruption suspected).
- [ ] **Coverage staleness.** `cfg.nlp_lexicon_max_age_days=14`; lexicon
  files unchanged for that long → daily `nlp.alert.v1{kind=lexicon_stale,
  severity=info}`. Catches "Phase 16 feed pipeline silently broke
  upstream" weeks earlier than coverage drift would.
- [ ] **Proof:** `test_nlp_coverage_histogram_per_intent_class`,
  `test_nlp_unresolved_top_k_pii_scrubbed_and_capped`,
  `test_nlp_coverage_below_floor_alert_fires`,
  `test_nlp_lexicon_stale_alert_after_14_days` (mock clock).

#### 10.25.9 End-to-end right-to-erasure (Phase 8 → NLP audit + L1 cache + spool)

- [ ] **Real gap §10.21.7 misses.** Pins NLP audit redaction whitelist
  but never wires `quarantine_erase` (§8.3 / §8.16) through to NLP's
  on-disk state. A user erasure request leaves `nlp_audit_log` rows
  with `qa_correlation_id` linkable to the now-erased predictor row,
  L1 `cache.v1` answer entries cache-keyed on `(user_id_h, ...)`, and
  spool envelopes in `data/nlp/spool/` carrying `qa_correlation_id`.
- [ ] **NLP subscribes to `maint.event.v1{kind=quarantine_erase}`** (the
  ack contract was already defined in §8.0; this is the real consumer
  for the NLP plane). On receipt: (a) `UPDATE nlp_audit_log SET ...
  user_id_h=NULL, qa_correlation_id_h=hash(qa_correlation_id) WHERE
  user_id_h=<target>`; (b) `redis.del(cache:answer:<user_id_h>:*)` via
  `SCAN+UNLINK` (cap `cfg.nlp_erase_scan_batch=500`); (c) walk
  `data/nlp/spool/` for envelopes with matching `user_id_h` → `unlink`.
  Emits `maint.ack.v1{accepted=true, accepted_by="nlp.audit.v1"}` on
  completion or `accepted=false` w/ reason on failure.
- [ ] **Idempotency.** Multiple erase events for the same `user_id_h`
  → second is a no-op (no rows match) but STILL acks success.
  Mirrors §8.1 denylist_clear idempotency lesson.
- [ ] **Audit-bundle dirs untouched.** §10.25.3 bundles contain artifact
  metadata only — no user PII — so erase does not propagate there.
  Pinned doctrine; documented in `nlp_runbook.md`.
- [ ] **Conversation context erase.** `qa.context.v1` Redis state is
  also erased: `redis.del(nlp:ctx:<conversation_id>)` for every
  conversation_id linked to the erased user (linkage table
  `data/nlp/conversation_index.sqlite` or Redis sorted set, single-
  source choice pinned in `cfg.nlp_conversation_index_backend ∈
  {redis, sqlite}` default `redis`).
- [ ] **Proof:** `test_nlp_quarantine_erase_nullstamps_audit_row`,
  `test_nlp_quarantine_erase_evicts_l1_cache`,
  `test_nlp_quarantine_erase_unlinks_spool_envelopes`,
  `test_nlp_quarantine_erase_idempotent_on_already_erased`,
  `test_nlp_quarantine_erase_clears_conversation_context`,
  `test_nlp_quarantine_erase_emits_ack` (per §8.0 ack contract).

#### 10.25.10 Per-tenant compliance ban-list overlay (advertiser / legal carve-outs)

- [ ] **Real gap.** Some deployments need to suppress specific terms in
  rendered answers (advertiser conflicts: "rakip bahis sitesi adı";
  legal: a banned trademark; defamation-safe: a player accused of an
  offence). §10.22.9 offensive-language gate is global; per-tenant
  carve-outs are an orthogonal axis.
- [ ] **`ai/nlp/compliance/banlist.tr.yaml`** (per-tenant; structure:
  `tenant_id: [{term, action ∈ {redact, refuse, replace_with},
  replace_text?, expires_at_utc?, source_pr_url, added_by, added_at}]`).
  Atomic-swap mtime-poll (mirrors §10.2 lexicon discipline; distinct
  lock); `cfg.nlp_compliance_reload_s=60`; SHA-pinned per snapshot.
- [ ] **Render-time only.** Ban-list applied AFTER §10.9 proofreader,
  BEFORE returning to API gateway. NEVER fed to classifier or entity
  extractor — keeps the classifier tenant-blind (mirrors §10.0
  Phase 20 doctrine: NLP is tier-blind; same applies to compliance).
- [ ] **`refuse` action.** Replaces the entire answer with a closed-
  template `meta.compliance_refused.<locale>.j2` ("Bu konuda bilgi
  veremiyoruz."). Citation block preserved. `nlp.event.v1{kind=
  compliance_refusal_triggered, tenant_id_h, term_sha8}` (term itself
  NEVER logged — only its sha8 prefix).
- [ ] **`redact` / `replace_with`.** Token-level substitution on the
  rendered answer string; multiple substitutions applied in a single
  pass (sorted by `len(term) desc` — longest first, prevents partial
  overlap pathology). AST guard: substitution code uses no regex on
  user-controlled patterns (defends against ReDoS via tenant config).
- [ ] **Cache-key extension.** `(tenant_id, banlist_snapshot_sha)`
  added as the 7th + 8th components of the §10.23.9 cache key (was 5,
  context made 6, ban-list makes 7-8). Atomic ban-list swap evicts
  cache for that tenant naturally.
- [ ] **Proof:** `test_nlp_banlist_redacts_term_in_rendered_answer`,
  `test_nlp_banlist_refuse_returns_closed_template_with_citation`,
  `test_nlp_banlist_substitution_longest_first_no_partial_overlap`,
  `test_nlp_banlist_never_seen_by_classifier_or_extractor` (AST),
  `test_nlp_banlist_term_never_logged_in_clear` (AST + log-filter probe),
  `test_nlp_banlist_swap_evicts_per_tenant_cache`.

#### 10.25.11 Boot-dependency graph (Phase 5 cold-start, GPU-lease leak on humanizer crash)

- [ ] **Real gap §10.21.9 misses.** Boot stages 1-6 cover NLP-internal
  state but the pipeline is unusable until Phase 5 `consensus.v1` is
  emitting `predict.approved.v1` for AT LEAST a smoke-set of fixtures.
  At cluster cold-start (compose-up or K8s rolling deploy), NLP can
  pass readiness while consensus is still warming → 503-but-200
  paradox: `/v1/qa` accepts the request, fans out `predict.request.v1`,
  times out, returns degraded.
- [ ] **Boot stage 6.5 added.** `consensus_smoke_observed`: NLP at boot
  publishes a single canary `predict.request.v1{match_id=<sentinel>,
  market=1x2, request_id=nlp-boot-canary-<pod>, qa_correlation_id=null}`
  and waits up to `cfg.nlp_boot_consensus_smoke_timeout_s=10` for the
  matching `predict.approved.v1`. Success → readiness 200. Timeout →
  readiness stays 503 + `nlp.alert.v1{kind=nlp_consensus_smoke_failed,
  severity=warn}` (warn not critical — cluster-wide cold start can
  validly take longer; auto-promotes to critical at 60s via
  `cfg.nlp_boot_consensus_smoke_critical_s=60`).
- [ ] **Sentinel match.** `cfg.nlp_boot_consensus_sentinel_match_id="nlp:boot:canary"`
  recognised by Phase 5 consensus as a fast-path response (returns a
  pre-canned `predict.approved.v1` with `degraded=true,
  degraded_reason=boot_canary` — never hits real predictors). Boundary
  test in Phase 5: `test_consensus_recognises_nlp_boot_canary`.
- [ ] **GPU-lease leak on humanizer crash.** §10.21.4 breaker is
  per-pod; §10.0 says lease via Phase 11. If the humanizer subprocess
  crashes (segfault on bad input, OOM kill), the in-process Python
  agent process MAY survive but the GPU lease record in Redis is
  orphaned for `cfg.compute_lease_ttl_s` (Phase 11 default 600s),
  blocking the next pod's lease acquisition. Real bug.
- [ ] **Subprocess supervisor.** Humanizer runs in a `multiprocessing.Process`
  child supervised by the agent (mirrors `aitext.v1` Phase 11 pattern,
  if not already pinned, this section pins it). Child death detected
  via `Process.exitcode != None`; supervisor immediately
  releases the GPU lease (Redis `DEL compute:lease:nlp.humanizer.v1:<pod>`),
  emits `nlp.alert.v1{kind=humanizer_subprocess_died, exitcode,
  severity=error}`, opens the §10.21.4 breaker for the rest of the
  breaker window (recovery via §10.10 "humanizer fail" row → template
  fallback), and respawns child after `cfg.nlp_humanizer_respawn_cooldown_s=30`.
  AST guard: `test_nlp_humanizer_runs_in_subprocess_not_thread`.
- [ ] **Proof:** `test_nlp_readiness_503_until_consensus_smoke`,
  `test_nlp_consensus_smoke_promotes_to_critical_at_60s`,
  `test_consensus_recognises_nlp_boot_canary` (Phase 5),
  `test_nlp_humanizer_subprocess_death_releases_gpu_lease`,
  `test_nlp_humanizer_subprocess_death_opens_breaker`,
  `test_nlp_humanizer_runs_in_subprocess_not_thread` (AST).

#### 10.25.12 Summary fan-out overflow (matchday > nlp_summary_max_fixtures)

- [ ] **Real bug §10.6 misses.** `cfg.nlp_summary_max_fixtures=10` cap
  silently truncates a Saturday with 9 Süper Lig + 6 1.Lig fixtures;
  the user sees "10 maç" but doesn't know 5 were dropped. Worse:
  truncation is FIFO by `predict.request.v1` arrival order — non-
  deterministic across pods.
- [ ] **Salience-ranked overflow.** When fixture count > cap, NLP
  computes a salience score per fixture and selects top-N. Single-
  source `ai/nlp/dispatcher/salience.py::compute_salience(fixture) ->
  float` over the closed feature set: `(league_tier from LeagueCatalog,
  is_derby from `derbies.tr.yaml`, kickoff_proximity_to_query_time,
  prior_user_team_mentions_in_conversation_context (§10.25.1))`.
  Deterministic; tie-break on `match_id` lex-sort. AST guard:
  `test_nlp_salience_inputs_in_closed_set`.
- [ ] **Explicit Turkish disclosure.** Answer carries
  `truncated_count=N, top_n_by="öncelik (lig sıralaması, derbi, saat)"`
  + a closed-template line: "Bu hafta {total} maç var; en öne çıkan
  {n} tanesini özetledim. Diğerleri için lig listelerine bakabilirsiniz."
  NEVER silent truncation. AST: `test_nlp_summary_truncation_disclosed_in_answer`.
- [ ] **Hard upper cap.** `cfg.nlp_summary_max_fixtures_hard=20` (cap
  on cap — at this size even salience-ranked output is too long for
  template clarity). Over the hard cap → degrade entirely to a list-
  only meta answer with the disclosure + a per-league link table.
- [ ] **Caching.** Salience-ranked top-N cache key includes
  `query_time_bucket=hour-truncated` and the closed feature set hash,
  so the same query 5 minutes later hits the same cache entry.
- [ ] **Proof:** `test_nlp_summary_overflow_uses_salience_not_fifo`,
  `test_nlp_summary_truncation_disclosed_in_answer`,
  `test_nlp_summary_hard_cap_degrades_to_list_meta`,
  `test_nlp_salience_deterministic_across_pods`,
  `test_nlp_salience_inputs_in_closed_set` (AST).

#### 10.25.13 Religious / national holiday calendar in date resolver

- [ ] **Real gap §10.5 / §10.22.6 misses.** Date resolver covers "yarın"
  / "cuma" / "27 Nisan saat 21:30" but NOT culturally-grounded Turkish
  date references: "bayramda maç var mı" (Ramazan / Kurban — moving
  dates), "Cumhuriyet Bayramı'nda kim oynar" (29 Ekim, fixed), "milli
  maç haftası" (FIFA windows — moving). These return `meta.unsupported`
  today, which is a fan-visible quality bug.
- [ ] **`ai/nlp/dates/holidays_tr.yaml`** (single-source).  Each entry:
  `{key (closed enum: ramazan_bayrami | kurban_bayrami | yilbasi |
  cumhuriyet_bayrami | zafer_bayrami | gencler_bayrami |
  ulusal_egemenlik | demokrasi_bayrami), name_tr, name_aliases[],
  date_kind ∈ {fixed_gregorian, fixed_hijri_observed, fifa_window},
  fixed_md? (e.g., "10-29"), hijri_year_lookup? (per-year computed
  by `ai/nlp/dates/hijri.py` — vendored deterministic lookup, NEVER
  network), fifa_window_lookup? (per-year from `openfootball` feed
  cached locally + SHA-pinned per year)}`.
- [ ] **Lookup horizon.** `cfg.nlp_holiday_lookup_horizon_days=540`
  (~18 months — covers any "next year's bayram" query). Refuses to
  resolve dates beyond horizon → falls back to numeric-date prompt.
- [ ] **Hijri determinism.** `hijri.py` is a vendored table for the next
  20 years (small file, ~400 rows, SHA-pinned in chart compat block);
  table generated by `make nlp.hijri-rebuild` from a deterministic
  astronomical algorithm (Umm al-Qura observed dates), NEVER from a
  live API. Per-year discrepancy with Turkey's official calendar
  (Diyanet) noted in a `_diyanet_overrides.tr.yaml` allow-list.
- [ ] **FIFA window cache.** Per-year `data/nlp/fifa_windows/<year>.json`
  populated from openfootball feed at lexicon-build time; SHA-pinned;
  fallback if file absent → `meta.unsupported` (NEVER guess).
- [ ] **Holiday-as-context.** When holiday entity is present + "maç var
  mı" intent, dispatcher routes to `data.fixture_lookup` with
  `(start_utc, end_utc)` derived from the holiday's resolved date
  range. Fan-friendly UX without changing intent enum.
- [ ] **Proof:** `test_nlp_resolves_ramazan_bayrami_2026`,
  `test_nlp_resolves_cumhuriyet_bayrami_fixed_date`,
  `test_nlp_resolves_fifa_window_from_openfootball_cache`,
  `test_nlp_holiday_beyond_horizon_returns_meta_unsupported`,
  `test_nlp_hijri_table_sha_pinned_in_chart`,
  `test_nlp_diyanet_override_table_respected`.

#### 10.25.14 Knob inventory + new event/alert kinds + DoD additions

- [ ] **New cfg knobs (~22):** `nlp_conversation_max_turns=8`,
  `nlp_conversation_idle_ttl_s=180`, `nlp_conversation_redis_key_prefix="nlp:ctx:"`,
  `nlp_conversation_enabled_tier_floor=0`, `nlp_conversation_index_backend="redis"`,
  `nlp_answer_streaming="disabled"`, `nlp_streaming_proofread_chunk_chars=80`,
  `nlp_streaming_write_timeout_ms=2000`, `nlp_audit_bundle_retention_days=2555`,
  `nlp_intent_retrain_max_regression=0.005`,
  `nlp_active_learning_queue_max=10000`, `nlp_unresolved_token_top_k=50`,
  `nlp_lexicon_coverage_p50_floor=0.6`, `nlp_lexicon_max_age_days=14`,
  `nlp_erase_scan_batch=500`, `nlp_compliance_reload_s=60`,
  `nlp_boot_consensus_smoke_timeout_s=10`,
  `nlp_boot_consensus_smoke_critical_s=60`,
  `nlp_boot_consensus_sentinel_match_id="nlp:boot:canary"`,
  `nlp_humanizer_respawn_cooldown_s=30`,
  `nlp_summary_max_fixtures_hard=20`,
  `nlp_holiday_lookup_horizon_days=540`,
  `nlp_lexicon_max_aliases_per_canonical=12`. Plus 8 feature-flag
  toggles (one per §10.25.1–§10.25.13 sub-section, default `false`
  except `nlp_conversation_enabled=true`). Triangle test extends.
  Go-side `TestEnvSync` covers `nlp_humanizer_respawn_cooldown_s` and
  the streaming knobs (Phase 9 SSE handler will read them).
- [ ] **New `qa.context.v1` topic** registered in §3.5 wire authority
  (additive). Producer set bounded to `nlp.dispatcher.v1`; consumer
  bounded to `nlp.intent.v1`. `additionalProperties:false` schema.
- [ ] **New `qa.feedback.v1` topic** registered in §3.5 wire authority
  (additive). Producer set bounded to `api.gateway.v1`; consumer
  bounded to `nlp.dispatcher.v1`. `additionalProperties:false` schema.
- [ ] **New `nlp.event.v1` kinds** (open-enum, registered):
  `conversation_entity_overridden`, `streaming_client_slow_canceled`,
  `active_learning_queue_overflow`, `compliance_refusal_triggered`,
  `nlp_intent_rolled_back`, `nlp_audit_rerender_executed`. Per-kind
  sub-schemas under `ai/swarm/sdk/schemas/nlp.event.v1/<kind>.json`.
- [ ] **New `nlp.alert.v1` kinds** (open-enum, registered):
  `conversation_context_cleared_after_block` (info),
  `streaming_humanizer_chunk_blocked` (warn),
  `nlp_compatibility_quartet_mismatch` (critical),
  `feedback_provenance_mismatch` (warn),
  `lexicon_coverage_below_floor` (warn / error on multi-class),
  `lexicon_stale` (info),
  `nlp_consensus_smoke_failed` (warn → critical at 60s),
  `humanizer_subprocess_died` (error).
- [ ] **DoD proof tests aggregate** (new in §10.25, all required for
  Phase 10 closure):
  - §10.25.1 — 6 tests (multi-turn context)
  - §10.25.2 — 6 tests (streaming + AST guards)
  - §10.25.3 — 5 tests (audit bundle + re-render)
  - §10.25.4 — 5 tests (compatibility matrix)
  - §10.25.5 — 4 tests (intent retrain lifecycle)
  - §10.25.6 — 5 tests (lexicon governance)
  - §10.25.7 — 5 tests (feedback loop)
  - §10.25.8 — 4 tests (coverage telemetry)
  - §10.25.9 — 6 tests (right-to-erasure end-to-end)
  - §10.25.10 — 6 tests (compliance ban-list)
  - §10.25.11 — 6 tests (boot dependency + GPU-lease)
  - §10.25.12 — 5 tests (summary overflow salience)
  - §10.25.13 — 6 tests (holiday calendar)
  - **Total: ≈ 69 new proof tests added on top of §10.21/§10.22/§10.23/§10.24
    aggregate.** Cumulative Phase 10: ≈ 320+ proof tests.
- [ ] **Chart compatibility additions.** Pin Unicode TR39 confusables
  rev (already in §10.21), `hijri.py` vendored table SHA, openfootball
  FIFA-window seed SHA, Diyanet override table SHA. Pin
  `python-multiprocessing` semantics by recording the host glibc
  version range that was tested for subprocess supervisor (defends
  against silent fork() vs spawn() differences).
- [ ] **`make swarm.demo.nlp.full`** extends to exercise (within the
  ≤ 60s compose budget, tightening from §10.23.13 baseline): (a) one
  multi-turn conversation (3 turns); (b) one streaming response
  (asserting skeleton-first then polish); (c) one re-render via
  `make nlp.audit-rerender` of a synthetic audit bundle; (d) one
  intent-rollback dry-run; (e) one compliance refuse triggered; (f)
  one summary overflow with disclosure rendered; (g) one holiday-
  context query ("bayramda maç var mı") resolved.
- [ ] **Documentation.** `docs/design/TURKISH_NLP.md` gains five new
  sections: "Conversational Context", "Streaming Response", "Audit
  Re-render Bundles", "Lexicon Contributor Guide", "Holiday Calendar".
  `docs/guides/nlp_runbook.md` gains: "Intent rollback runbook",
  "Right-to-erasure runbook", "Compliance ban-list operator workflow",
  "Cold-start consensus-smoke triage", "GPU-lease leak recovery".

### 10.26 Morphological correctness, input modality, and counterfactual handling (binding addendum)

> **Why a seventh pass.** §10.21 fixed integrity, §10.22 fixed
> TR-language correctness, §10.23 fixed serving, §10.24 fixed messy
> wrong-Turkish surface, §10.25 fixed lifecycle / conversation /
> time-travel. Three classes of real-world Turkish input pathology
> still slip through and cause user-visible wrong answers, not just
> degraded ones: (a) **morphological-analyzer ambiguity** — Zemberek
> routinely returns 5+ parses for a single agglutinated token and the
> wrong root resolves to the wrong canonical entity; (b) **input
> modality variance** — voice-to-text, mobile IME, and copy-paste
> long-form input each produce distinct, high-frequency artifact
> classes that desktop-typed corpora never see; (c) **counterfactual
> and modal-aspect intent** — "yenseydi", "oynayacak mıydı", "olur
> muydu" naively route to `predict.*` (future) when the user is
> asking about a hypothetical past, producing a *confidently wrong*
> answer instead of a graceful refusal. §10.26 closes all three with
> deterministic gates, closed tables, AST guards, and ~72 new proof
> tests on top of the §10.25 baseline.

#### 10.26.1 Morphological analyzer ambiguity discipline (Zemberek top-K + confidence floor)

- [ ] **Real bug §10.1 step 7 left open.** "Zemberek tokens"
  (vendored rules in `ai/nlp/vendor/zemberek_rules.json`) was
  spec'd as a single best-parse output. In production Zemberek-style
  analysers commonly emit 3–8 candidate parses for one Turkish
  token (e.g. `evine` → `ev+P3sg+Dat`, `evi+P3sg+Dat`,
  `ev+P2sg+Dat`, ...). Picking the lexicographically-first or
  longest-suffix parse silently mis-routes the wrong root downstream
  to the gazetteer, especially on proper nouns
  (*Galatasaray'ından* — possessive vs ablative collide on the
  surface form *-ından*).
- [ ] **Top-K parse acceptance.** `cfg.nlp_morph_topk=3` candidate
  parses retained per token. `MorphCandidate = (root, suffix_class,
  pos, confidence, ambiguity_class ∈ {unique, low, high,
  unparseable})`. Stored on the token, NOT collapsed at this stage.
- [ ] **Confidence floor + abstention.** Each parse carries a
  unigram-frequency-weighted confidence `0.0..1.0` from
  `ai/nlp/data/tr_morph_freq.json` (SHA-pinned, rebuilt from the
  same Wikipedia corpus as §10.3 diacritics). Floor
  `cfg.nlp_morph_min_confidence=0.55`; below floor → flag
  `ambiguity_class=high`. **Never** silently pick a low-confidence
  parse — emit `nlp.event.v1{kind=morph_parse_ambiguous,
  surface_form_sha8, candidate_count}` (debounced 60s, PII-safe via
  sha8 only).
- [ ] **Resolution arbitration (deterministic, ordered).** When
  multiple parses survive the confidence floor:
  1. **Gazetteer cross-check wins.** If exactly one candidate root
     matches a `lexicon_canonical_id` in §10.2, pick it.
  2. **POS preference per intent class.** Closed table
     `morph_pos_preferences.tr.yaml` (`predict.* → noun_proper >
     noun_common`, `data.player_card_risk → noun_proper`,
     `meta.help → any`).
  3. **Co-token context.** If a high-confidence neighbouring token
     (within radius `cfg.nlp_morph_context_radius=4`) selects a POS,
     prefer the matching parse on the ambiguous token.
  4. **Tie-break by frequency rank.** Higher unigram frequency wins.
  5. **Still tied** → emit `slot_resolution_failed` (per §10.5) and
     route to `did_you_mean` (NEVER guess).
- [ ] **Proper-noun morphology guard.** Proper-noun stems
  (`is_proper=True` from §10.22.2 `strip_proper_noun_suffix`)
  short-circuit the parser — Zemberek does not own proper-noun
  morphology and frequently truncates them
  (*Beşiktaş'tan* → `Beşik+taş` wrong-stem). AST guard
  `test_nlp_proper_noun_skips_zemberek` asserts the surface form
  reaches the gazetteer untransformed when `is_proper=True`. Bypass
  emits `nlp.event.v1{kind=morph_proper_noun_bypassed}` (debounced).
- [ ] **Unparseable token policy.** Zemberek returning zero parses
  is a **valid signal** (foreign word, code-switch, neologism,
  emoji-name); fall through to: (a) gazetteer pass, (b) §10.22.8
  bilingual gazetteer, (c) §10.24.10 abbrev table, (d) §10.3
  Symspell. Only if all four miss → token is "unresolved" and feeds
  the §10.25.8 `nlp_unresolved_token_top_k` telemetry. Never raise.
- [ ] **Ambiguity budget per query.** ≤ `cfg.nlp_morph_ambiguous_max_per_query=4`
  high-ambiguity tokens; over-budget → `did_you_mean` fallback with
  the first 2 unambiguous content tokens echoed back. Defends
  against pathologically agglutinated input
  (*"Galatasaraylılaştıramadıklarımızdan mısınız?"* — fun trivia,
  but not a useful classifier signal).
- [ ] **Determinism guarantee.** Same input + same
  `zemberek_rules.json` SHA + same `tr_morph_freq.json` SHA + same
  arbitration tables → byte-identical `MorphCandidate[]` ordering
  across runs. Hypothesis property test (≥ 500 examples,
  `derandomize=True`) seeds + hashes parser output.
- [ ] **Cross-language parity unaffected.** Morphology runs Python-
  side only — Go sec layer (Phase 7) does not parse morphology and
  does not need to mirror this. Boundary test
  `test_go_sec_layer_does_not_parse_morphology` asserts no Zemberek
  port lands under `server/internal/sec/`.

#### 10.26.2 Voice-to-text / ASR-input tolerance (binding)

- [ ] **Why this section.** Mobile clients (Phase 9 forward) will
  ship a speech-to-text affordance. ASR engines (Google/Apple/Yandex
  TR models) emit input that systematically violates assumptions
  baked into §10.1: no punctuation, no question marks, no
  capitalization (or wrong capitalization on proper nouns),
  hesitation tokens (*ııı*, *eee*, *şey*), filler words (*yani*,
  *aslında*, *ya*, *işte*), and missing diacritics on lower-frequency
  proper nouns the ASR LM hasn't seen. None of §10.22.4 (particle
  disambiguation), §10.22.5 (dialect/abbreviation), §10.24.5 (run-on
  multi-question split) handles this cleanly because they assume
  punctuation as a primary signal.
- [ ] **Detect ASR origin (heuristic, advisory).** New
  `request_metadata.input_source ∈ {keyboard, voice, paste,
  unknown}` (additive on `qa.request.v1`, `qa.context.v1` —
  schema_version 2→3, default `unknown`). When `voice`, opt-in to
  the ASR-tolerant path. Heuristic detector (server-side, runs even
  when client doesn't supply): zero `?` + zero `,` + length ≥ 40
  chars + ≥ 2 hesitation tokens → auto-mark `voice` and emit
  `nlp.event.v1{kind=asr_input_auto_detected}` (debounced 60s).
  Detector NEVER mutates the request — only sets the flag.
- [ ] **Hesitation / filler token table.** `ai/nlp/lang_tr/asr/fillers.tr.yaml`
  closed enum — `{ııı, eee, ee, ıı, mmm, hmmm, şey, yani, aslında,
  yaa, işte, falan, falan filan, ne bileyim}`. New §10.1 step 6.5
  `strip_asr_fillers` — runs ONLY when `input_source=voice` (do not
  strip *yani* from typed input — it is sometimes content-bearing).
  Per-query strip cap `cfg.nlp_asr_filler_strip_max=6` (over-cap →
  emit `asr_filler_overflow`, fall through to raw — defends against
  "ya ya ya ya ya ..." abuse).
- [ ] **Implicit punctuation reconstruction.** When `input_source=voice`,
  apply §10.24.5 `split_questions` with **relaxed** rules: any
  occurrence of `mi/mı/mu/mü` followed by ≥ 5 content tokens splits
  even without a question mark; `ve` + clause-boundary detection
  upgraded from passive to active. Boundary test enforces this is
  a no-op when `input_source=keyboard`.
- [ ] **Diacritic restoration aggressiveness toggle.** §10.3
  diacritic ambiguity tie-break ratio (`nlp_diacritic_tie_break_ratio=1.5x`)
  loosens to `cfg.nlp_diacritic_tie_break_ratio_voice=2.5x` when
  `input_source=voice` (ASR engines under-emit diacritics on
  low-frequency tokens; we accept more aggressive restoration on the
  voice path because the user's spoken input genuinely contained
  them).
- [ ] **Capitalization signal disabled on voice.** §10.22.2
  proper-noun detection MUST NOT short-circuit on capitalization
  alone when `input_source=voice` — ASR commonly lowercases
  everything OR over-capitalizes the first token of every
  utterance. Lexicon hit remains the sole authoritative proper-noun
  signal on this path. AST guard `test_nlp_voice_path_no_caps_short_circuit`.
- [ ] **Latency budget unchanged.** Voice path adds ≤ 3 ms p95 to
  §10.1 normalize stage (filler strip is one regex pass + table
  lookup). CI bench gate enforces.
- [ ] **Adversarial corpus extension.** §10.18 evaluation harness
  gains a `voice` slice of ≥ 30 transcribed utterances (curated
  from real ASR output of test reads, NOT synthesized — synthetic
  ASR has different artifact distribution per Rule 3). Slice gates
  are intent acc ≥ 0.85 (lower than clean per realism), entity F1
  ≥ 0.80; **abstention-on-low-confidence behaviour identical to
  keyboard path**.

#### 10.26.3 Mobile-IME pathologies (Q-keyboard / F-keyboard / swipe / autocorrect-cascade)

- [ ] **Why this matters.** Turkish mobile users split between Q
  (QWERTY) and F (Atatürk's official Turkish layout) keyboards —
  these produce **systematically different** typo-substitution
  matrices because adjacent keys differ. Symspell with a single
  edit-distance budget treats both equivalently and under-corrects
  one or over-corrects the other. Swipe keyboards add a third
  pattern: vowel-rich substitutions that Symspell rarely models.
  Autocorrect cascades produce the strangest class — a single
  mistyped letter triggers an autocorrect to a real-but-wrong word
  (*Galatasaray* → *Galatasarah* → autocorrect → *galatasaray* OK,
  but *Beşiktaş* → *Beşiktaa* → autocorrect → *beşiktas* — diacritic
  loss + final-consonant change).
- [ ] **Layout-aware confusable matrix.** `ai/nlp/lang_tr/ime/keyboard_confusables.tr.yaml`
  with three matrices: `q_layout`, `f_layout`, `swipe_vowel`. Each
  maps `(key, neighbour) → cost_multiplier` (default 1.0; adjacent
  keys 0.5; same-row-non-adjacent 0.8). Build pipeline
  `make nlp.ime-matrix-build` regenerates from public layout
  diagrams (SHA-pinned in chart) — no live download.
- [ ] **Layout detection (heuristic, advisory).** Optional
  `request_metadata.keyboard_hint ∈ {q, f, swipe, unknown}` on
  `qa.request.v1` (additive). When `unknown`, infer from typo
  pattern (run Symspell with both Q and F matrices on first 3
  ambiguous tokens; pick the matrix that yields more lexicon
  hits within budget). Inference cached per `client_id` (64-byte
  hash, NOT user_id) for `cfg.nlp_ime_layout_cache_s=3600`.
  Cache bypassed when `keyboard_hint` explicit.
- [ ] **Symspell extension.** `ai/nlp/vendor/symspell.py` gains
  `lookup(token, layout=None)` — when `layout` set, edit costs use
  the layout matrix; default budget unchanged. AST guard
  `test_nlp_symspell_layout_param_optional` asserts callers either
  pass `layout` explicitly or accept default-equal-weights.
- [ ] **Autocorrect-cascade detection.** Closed table
  `autocorrect_cascade.tr.yaml` of known cascades from observed
  corpora — `{wrong_form: canonical_form, layouts: [q, f]}`. Hit
  short-circuits Symspell + diacritic restoration for that token
  and emits `nlp.event.v1{kind=autocorrect_cascade_repaired}`
  (debounced 60s per cascade form). Single source — never
  inferred at runtime (would be unbounded).
- [ ] **Per-query layout-aware budget.** `cfg.nlp_typo_max_lookups_per_query`
  unchanged at 8; layout-aware lookups count as 0.5 each (cheaper
  search → more attempts allowed within same wall-clock budget).
  Boot validator asserts `0.5 * 8 < cfg.nlp_normalize_stage_timeout_ms / 2`.
- [ ] **Privacy.** `keyboard_hint` and `client_id`-keyed layout
  cache do NOT enter logs in clear; logs carry only
  `keyboard_hint_class ∈ {q, f, swipe, unknown}` (no client
  identification possible from log alone). PII discipline
  unchanged.

#### 10.26.4 Numerical and temporal Turkish completeness floor

- [ ] **Number-word ↔ digit bidirectional resolver.** §10.22.6
  spec'd `bir sıfır → 1-0` (score line) but left number-word
  resolution as a one-way street. Real input is bidirectional:
  *"2024 yılında"* and *"iki bin yirmi dört yılında"* must collapse
  to the same `(year=2024)` entity. NEW
  `ai/nlp/dates_tr.py::number_word_to_int(tokens) → (int, span)`
  + inverse `int_to_number_word(n, register='cardinal'|'ordinal')`.
  Closed Turkish lexicon `ai/nlp/lang_tr/numbers/number_words.tr.yaml`
  (sıfır..milyar). AST guard
  `test_nlp_number_resolver_bijective_on_0_to_9999` asserts
  `int_to_number_word(number_word_to_int(x)) == x` for every
  generated form.
- [ ] **Ordinal handling.** Closed forms only:
  - Word ordinals: *birinci, ikinci, üçüncü, ...* + *sonuncu*
  - Digit-ordinals with `'inci/'üncü/'üncü/'ıncı`: *3'üncü, 21'inci*
  - Suffix-ordinals: *3.* (dotted-numeric)
  All resolve to `OrdinalEntity{position: int, polarity:
  'forward'|'reverse'}` (`sonuncu` → reverse-1, *son* → reverse-1
  contextual, *önceki* → reverse-1 only with co-token like
  *hafta/maç*). Deterministic per closed table; never
  ML-predicted.
- [ ] **Fractional time.** `yarım/çeyrek/buçuk` resolver:
  *"yarım saat sonra"* → `+30min`, *"çeyrek saat sonra"* → `+15min`,
  *"iki buçuk saat sonra"* → `+150min`. Closed combinator over
  number-word-resolver output. Edge cases pinned in 30-row golden:
  *"buçukta"* (= half past the implicit hour — refuses without
  hour anchor; emits `slot_resolution_failed`).
- [ ] **Relative time enrichment.** Add to §10.5 date resolver:
  *önceki hafta, geçen hafta, geçen ay, geçen yıl, dünden önce,
  iki gün sonra, X gün önce, X hafta sonra, hafta sonu* — each
  resolves to `(start_utc, end_utc, granularity, polarity ∈
  {past, future, present})`. **Past polarity routes to historical
  intents (data.h2h, data.standings) NEVER to predict.\*** —
  closed table `temporal_intent_polarity.tr.yaml` enforces this
  routing constraint at the dispatcher. AST guard
  `test_nlp_past_polarity_never_routes_predict`.
- [ ] **DST-bridging clock arithmetic.** When relative time crosses
  Europe/Istanbul DST boundary (still observed historically pre-2016
  for past queries; post-2016 Türkiye is permanent UTC+3 — no DST
  active currently), use IANA tzdata (already SHA-pinned per
  §10.23.6); emit `nlp.event.v1{kind=temporal_dst_crossed}` with
  the crossing date for operator visibility on past queries
  (debounced).
- [ ] **Numeric format ambiguity (extends §10.24.11).** `1.234`
  is *one thousand two hundred thirty-four* in tr-TR (period as
  thousands separator) but `1.5` in same locale is *one point five*
  (period as decimal — borrowed from English betting odds context).
  Resolver examines co-tokens in radius 3: `[oran, kat, çarpan]`
  near `\d+\.\d+` → decimal (English betting); `[gol, sayı,
  taraftar]` → thousands (Turkish format). Ambiguous → emit
  disambiguation answer (NEVER silent pick).
- [ ] **Half-built number guard.** A user typing *"iki bin"* and
  pressing send has built half a number. Resolver returns
  `PartialNumberEntity{accumulator: 2000, unit_pending: True}` —
  dispatcher treats as unresolved and offers
  `did_you_mean: ["2000 yılı?", "2000. dakika?"]`. AST guard
  `test_nlp_partial_number_never_silently_completes`.

#### 10.26.5 Counterfactual / conditional / modal-aspect intent firewall

- [ ] **Real bug.** §10.4 intent enum has no slot for hypothetical-
  past queries. *"Galatasaray Fenerbahçe'yi yenseydi şampiyon
  olur muydu?"* (had Galatasaray beaten Fenerbahçe, would they
  have been champions?) classifies as `predict.match_outcome` with
  high confidence on a fastText keyword overlap → routes to
  predictors → returns a confidently wrong answer about the (now
  past) match. Worse: *"olur muydu"* (would it have been) marked
  as future-tense by the surface keyword `olur`.
- [ ] **Modal-aspect detector (deterministic, table-driven).** NEW
  `ai/nlp/lang_tr/modality/aspect_markers.tr.yaml` closed enum:
  - `counterfactual_past`: *yenseydi, oynasaydı, gelseydi,
    olsaydı, kazansaydı, olur muydu, olur muyduk*
  - `inferential_past`: *oynamış olur, kazanmış olur* (past
    inferential — historical lookup)
  - `epistemic_potential`: *oynayabilir, kazanabilir, olabilir*
    (potential — OK for `predict.*`)
  - `obligative`: *oynamalı, kazanmalı* (advice — refuse with
    explanation; no betting advice surface in v1)
  - `evidential_hearsay`: *oynamış, kazanmışmış, diyorlar*
    (hearsay — historical lookup)
- [ ] **Detection algorithm.** §10.5 entity pass gains
  `modality_class` extraction; pattern is suffix-tail match on
  any verb-position token. Suffix patterns regex-pinned in YAML;
  AST guard rejects inline regex literals in agent code.
- [ ] **Routing override (binding).** §10.6 dispatcher MUST NOT
  publish `predict.request.v1` when `modality_class ∈
  {counterfactual_past, inferential_past, evidential_hearsay,
  obligative}`. Routing table:
  - `counterfactual_past` → `meta.counterfactual_unsupported`
    template with explicit Turkish phrasing
    (*"Olmuş bir maçın farklı sonuçlanmış halini öngöremem; geçmiş
    sonuçlar için sorabilirsiniz."*) — humanizer-bypassed.
  - `inferential_past` → `data.h2h` if entities resolve, else
    `did_you_mean`.
  - `evidential_hearsay` → `data.h2h` (treats as past lookup).
  - `obligative` → `meta.advice_unsupported` template
    (*"Bahis tavsiyesi vermem; tahmin olasılıkları paylaşabilirim;
    bahis bilgisi için yetkili sitelere başvurun."*) —
    humanizer-bypassed; CRITICAL — also tier-blind (advice-refusal
    is a doctrine line, not a paywall).
- [ ] **Ambiguous modality.** When the modality classifier returns
  high confidence on `epistemic_potential` AND a past temporal
  entity is present (*"yarın oynayabilir mi"* with *yarın* → fine;
  *"dün oynayabilir mi"* → contradiction), prefer
  `meta.unsupported` with explicit disambiguation. AST guard
  `test_nlp_modal_x_temporal_contradiction_routes_unsupported`.
- [ ] **Proof-test density.** ≥ 30 modality cases curated by hand
  in `ai/nlp/tests/data/modality_corpus.tr.json` — each row pinned
  to expected (`modality_class`, `routed_intent`, `template`).
  100% gate, no `xfail`.

#### 10.26.6 Lexicon supply-chain defense (PR-flood, typo-squat, ortho-confusable canonical)

- [ ] **Real attack vector.** §10.25.6 added two-reviewer rule for
  high-leverage tables but did NOT cap PR diff size, did NOT detect
  typo-squat aliases (*Galaatasaray* alias added to a fake team
  canonical), did NOT detect ortho-confusable canonical IDs
  (someone introduces canonical_id `galatasaray_v2` colliding under
  §10.21.5 confusables fold with the real `galatasaray`).
- [ ] **PR diff size cap.** `make verify.nlp-lexicon-diff` (NEW;
  CI-gated) computes added-row count per file in the PR; hard cap
  `cfg.nlp_lexicon_pr_max_added_rows_per_file=200`, soft warn at
  50; over-cap → CI failure with explicit "split this PR" message.
  Defends against drive-by alias-flood.
- [ ] **Typo-squat detector.** For every newly added alias, run
  Symspell against the existing alias index of OTHER canonicals
  with edit budget 1. Hit on a different canonical → CI failure
  citing the collision. Over-ride only via explicit
  `_aliases_delta.tr.yaml::overrides` block listing both canonicals
  + a justification (e.g. legitimate near-collision *Adana
  Demirspor* vs *Adanaspor* — two real distinct teams).
- [ ] **Ortho-confusable canonical guard.** `make verify.nlp-lexicons`
  extends with: every canonical_id passes through §10.21.5
  confusables-fold; collision with another canonical's folded form
  → build failure (mirrors the §10.2 alias round-trip property,
  but on canonical IDs, which the prior pass missed because IDs
  are normally ASCII — but a malicious PR can use any UTF-8 code
  point). Closed allow-list under
  `lang_tr/_canonical_id_collision_allow.yaml` (empty at v1).
- [ ] **Alias age + provenance.** §10.25.6 added `source` field;
  this section adds `added_at_utc` and `min_corpus_appearances`
  (auto-populated by build pipeline from a SHA-pinned corpus
  excerpt — alias must appear ≥ N times across recent
  scraper output to ship; default `cfg.nlp_lexicon_min_alias_appearances=3`,
  override per row only with reviewer ack). Defends against
  pure-fabrication aliases.
- [ ] **Lexicon CI-bot impersonation defense.** The PR-flood
  attacker may try to impersonate the build bot. CODEOWNERS-derived
  `lexicon-build-bot` GH actor identity is the ONLY committer
  allowed to bypass §10.25.6 two-reviewer rule for auto-regenerated
  files (`teams.tr.yaml`, etc. that are derived from
  `_aliases_delta.tr.yaml` + LeagueCatalog). Boot-time validator
  in CI (NOT runtime) refuses any commit author mismatch on those
  files.

#### 10.26.7 Multi-turn correction grammar (extends §10.25.1)

- [ ] **Real gap.** §10.25.1 multi-turn conversation persists
  entities across turns but has no spec for *explicit user
  correction* — *"öyle değil, Beşiktaş demek istedim"* (not like
  that, I meant Beşiktaş). Without correction handling, the prior
  turn's wrong entity sticks for the rest of the conversation.
- [ ] **Correction-utterance detector.** Closed table
  `lang_tr/correction/correction_markers.tr.yaml`:
  - Negation-of-prior: *yok öyle değil, hayır onu demedim, yanlış
    anladın, ben X demek istedim*
  - Replacement: *X değil Y, X yerine Y, aslında Y*
  - Restart: *yok yok, baştan, unut onu*
- [ ] **Detection trigger + scope.** Detector fires only when
  `conversation_id` is bound AND there is at least one prior
  turn AND the current utterance starts with one of the markers
  OR contains a replacement bigram with high lexicon-hit rate on
  the second slot. False-positive rate target ≤ 1% on a
  hand-curated 100-row negative corpus.
- [ ] **Context-update semantics.** On detection:
  - `negation_of_prior` → mark prior turn's last entity as
    superseded; do NOT carry forward.
  - `replacement` → swap prior entity for the new one; emit
    `nlp.event.v1{kind=conversation_correction_applied}`.
  - `restart` → clear the conversation context entirely; emit
    `nlp.event.v1{kind=conversation_restarted_by_user}`.
- [ ] **Audit trail.** Every correction emits an audit row with
  the prior+new entity sha8 only (no raw text, mirrors §10.25.1
  PII discipline). Defense against an adversary using corrections
  to probe internal entity resolution.
- [ ] **Boundary.** Correction grammar is conversation-scoped
  ONLY. AST guard
  `test_nlp_correction_disabled_when_conversation_id_absent`.

#### 10.26.8 Output integrity envelope HMAC (extends §10.21.8)

- [ ] **Real gap §10.21.8 left open.** §10.21.8 added an HMAC over
  the prediction-citation block to detect a forged
  `predict.approved.v1` from a compromised bus worker. But the
  full `qa.answer.v1` envelope (including the body, citation,
  degraded flag, and `tier_id_required` per §10.0) is NOT covered.
  An attacker who can write to `cache.v1` directly (Phase 9 cache
  poisoning surface) can mutate the body field while the citation
  HMAC stays valid → user sees attacker-chosen text under a
  legitimate citation.
- [ ] **`qa.answer.v1.envelope_signature` (additive,
  schema_version 2→3).** HMAC-SHA256 over
  `(qa_correlation_id || produced_at_utc || body_canonical ||
  citation_canonical || degraded || degraded_reason ||
  tier_id_required || pipeline_version || compatibility_quartet_sha)`
  with `cfg.qa_answer_hmac_key_path` (mode 0400 — Phase 9 gateway-
  only readable; NLP writes it; gateway verifies it; bus worker
  cannot read it).
- [ ] **`body_canonical` derivation.** NFC-normalize body, replace
  every contiguous whitespace run with a single space, strip
  trailing whitespace per line, sha256 the bytes — pinned canonical
  form. Mirrors §10.21.6 citation-canonical doctrine.
- [ ] **Rollout discipline.** `cfg.nlp_answer_envelope_hmac_required
  ∈ {off, warn, enforce}` default `warn` at v1; `enforce` post
  Phase-14. `make nlp.rotate-answer-hmac-key` dual-acceptance
  window 24h.
- [ ] **Cache-write boundary.** AST guard
  `test_nlp_cache_writer_signs_envelope` asserts every
  `cache.v1{kind=qa_answer}` write includes `envelope_signature`.
- [ ] **Gateway-side verify** lives at Phase 9 §9.17.x (forward
  contract added to §10.0 cross-phase block) — Phase 9 gateway
  reads `cache.v1` for cached answers and MUST verify the HMAC
  before serving; on fail → emit
  `sec.alert.v1{kind=qa_answer_envelope_signature_invalid,
  severity=critical}`, evict cache entry, fall through to live
  RPC. Boundary test in Phase 9 enforces.

#### 10.26.9 Long-form copy-paste pathologies (binding)

- [ ] **Real-world input.** Users frequently paste a paragraph
  from a news article or social media as their question. This
  produces input that simultaneously violates §10.1 length cap,
  contains `\xa0` (non-breaking space — already strip-targeted in
  §10.1 step 3 but the step explicitly only strips
  *control/zero-width/RTL*, not whitespace variants), contains
  curly quotes (*"…"*, *'…'*), em-dashes (*—*), ellipsis (*…* as
  single codepoint U+2026), copy-paste artifacts from PDFs (soft
  hyphens U+00AD), and trailing source citations (`[1]`, `(via
  Twitter/X)`).
- [ ] **§10.1 step 3 widening.** Strip set extends to include:
  - Whitespace variants: `\xa0` (NBSP), `\u2007` (figure space),
    `\u202F` (narrow NBSP), `\u3000` (ideographic space) — all
    fold to ASCII space.
  - Soft-hyphen U+00AD: drop entirely (non-content; copy-paste
    artifact from PDF justification).
  - Quote canonicalization: `\u201C\u201D\u201E\u201F → "`,
    `\u2018\u2019\u201A\u201B → '` (and §10.22.2's apostrophe
    discipline already handled `\u02BC`).
  - Dash canonicalization: `\u2013\u2014\u2212 → -` (en-dash,
    em-dash, minus).
  - Ellipsis: `\u2026 → ...` (3 dots).
- [ ] **Determinism + idempotency.** All extensions tested by
  hypothesis property test; `normalize(normalize(x)) == normalize(x)`
  invariant from §10.1 must hold on the widened strip set
  (≥ 1000 examples, seed-pinned).
- [ ] **Length-cap ordering.** Strip extensions run AFTER length
  cap (per existing §10.1 step ordering — §10.1 step 1 is length
  cap, step 3 is strip). Boundary test
  `test_nlp_strip_runs_after_length_cap` asserts a 10000-char
  paste gets length-capped first (defends against attacker padding
  with millions of NBSPs hoping the strip will let it through).
- [ ] **Citation-tail stripper (closed enum).**
  `lang_tr/copy_paste/citation_tails.tr.yaml` with patterns
  `[via X], (via X), kaynak: X, source: X, [1], [2], (1), (2)`
  (anchored to end-of-string with optional whitespace). Stripped
  pre-classifier when `input_source=paste` OR detected
  heuristically (length ≥ 200 AND ends with one of the patterns).
  Stripped portion preserved in `request_metadata.stripped_tail`
  (for audit; never enters the answer).

#### 10.26.10 Football-specific bilingual vocabulary (extends §10.22.8)

- [ ] **Real gap.** §10.22.8 added a bilingual gazetteer pass for
  team / league names but football-specific *concept* vocab
  (positions, market types, in-game events, referee terms) lives
  in a half-Turkish half-English register that varies by media
  outlet and fan generation. *"Offside oldu mu?", "var kararı
  nedir?", "penaltı pozisyonu", "ekstra dakikalar / uzatma /
  added time"* all reach the classifier as code-switched and
  miss intent.
- [ ] **Closed football vocab table.** `lang_tr/football/vocab.tr.yaml`
  with schema `{canonical_concept, surface_forms_tr,
  surface_forms_en, register: media|fan|formal,
  intent_hint: optional}`. ~250 entries at v1 covering: position
  names (kaleci/keeper, defans/defender, ...), in-game events
  (gol, faul, ofsayt, korner, taç), market terms (handikap, çifte
  şans, alt/üst, karşılıklı gol/btts, ilk yarı, MS), referee
  terms (kırmızı kart, sarı kart, VAR, hakem, dördüncü hakem),
  competition events (devre arası, uzatma, penaltı atışları,
  tur atlama).
- [ ] **Resolver behaviour.** Each surface form maps to
  `canonical_concept` + optional `intent_hint` (e.g. *handikap* →
  intent_hint=`predict.handicap`; *btts* → `predict.btts`). The
  intent classifier (§10.4) is BIASED but not OVERRIDDEN — the
  hint becomes a fastText-input prefix marker
  `__concept_<canonical>__` that the model has been trained on.
  Hint without sufficient classifier confidence still abstains
  per §10.4 floor.
- [ ] **Bilingual abuse-token guard.** Some English football
  insults (*choke, bottle, parked the bus*) act as adversarial
  framing in TR queries about specific teams. Cross-reference
  with §10.22.9 offensive table — bilingual entries land in the
  same closed `offensive.tr.yaml` (kept single-source — vocab
  table never holds insults).
- [ ] **Build pipeline + governance.** Same two-reviewer
  `nlp-curator` rule as §10.25.6; added to CODEOWNERS scope.
  `make verify.nlp-football-vocab` AST-asserts: no entry
  duplicates a canonical_concept; every `intent_hint` resolves
  to a value in §10.4 closed enum.

#### 10.26.11 Empty / abuse-state observability (extends §10.24.13)

- [ ] **Real gap.** §10.24.13 handled the per-request empty-input
  floor but did NOT spec the cross-request anomaly signal. A
  spike of empty / single-char / pure-punctuation inputs from one
  `subject_key` (Phase 7 §7.6) is a behavioural fingerprint of
  abuse (script probing the floor; bot enumerating cost surface).
- [ ] **Per-subject empty-input rate gauge.** New
  `nlp_empty_input_rate_per_subject` histogram (cardinality
  bounded — top-K subjects only, per §10.14 PII discipline keys
  on `subject_key_sha8`, NOT raw subject). Anomaly detector:
  per-subject empty-rate > `cfg.nlp_empty_input_anomaly_threshold=0.3`
  over `cfg.nlp_empty_input_anomaly_window_s=300` AND
  per-subject request count ≥ 20 → emit
  `nlp.alert.v1{kind=nlp_empty_input_anomaly_per_subject,
  severity=warn}` (debounced 600s per subject).
- [ ] **Tier-blind by doctrine.** No tier-based exemption — alert
  fires on `account_paid` subjects same as anonymous (legitimate
  high-paid users do not produce 30%+ empty inputs in any
  observed corpus).
- [ ] **Boundary.** No automatic mitigation at NLP layer (rate-
  limit decisions live at Phase 7 sec gate). NLP only emits the
  signal; the §10.0 boundary discipline holds.

#### 10.26.12 Knob inventory addendum (extends §10.25.14)

`nlp_morph_topk=3`, `nlp_morph_min_confidence=0.55`,
`nlp_morph_context_radius=4`, `nlp_morph_ambiguous_max_per_query=4`,
`nlp_asr_filler_strip_max=6`, `nlp_diacritic_tie_break_ratio_voice=2.5`,
`nlp_ime_layout_cache_s=3600`, `nlp_lexicon_pr_max_added_rows_per_file=200`,
`nlp_lexicon_min_alias_appearances=3`, `nlp_answer_envelope_hmac_required=warn`,
`qa_answer_hmac_key_path`, `qa_answer_hmac_grace_s=86400`,
`nlp_empty_input_anomaly_threshold=0.3`,
`nlp_empty_input_anomaly_window_s=300`, plus 8 feature-flag
toggles (`nlp_morph_arbitration_enabled=true`,
`nlp_voice_path_enabled=true`, `nlp_ime_layout_aware_enabled=true`,
`nlp_temporal_polarity_routing_enabled=true`,
`nlp_modality_firewall_enabled=true`,
`nlp_correction_grammar_enabled=true`,
`nlp_long_paste_strip_extended_enabled=true`,
`nlp_football_vocab_hints_enabled=true`).

#### 10.26.13 New event / alert kinds (open-enum, mirrors §10.25.14 doctrine)

- `nlp.event.v1` kinds (debounced 60s unless noted):
  `morph_parse_ambiguous`, `morph_proper_noun_bypassed`,
  `asr_input_auto_detected`, `asr_filler_overflow`,
  `autocorrect_cascade_repaired`, `temporal_dst_crossed`,
  `temporal_polarity_routed_past`,
  `partial_number_disambiguation_offered`,
  `modality_routed_counterfactual`, `modality_routed_obligative`,
  `modality_routed_inferential_past`,
  `modality_routed_evidential_hearsay`,
  `conversation_correction_applied`,
  `conversation_restarted_by_user`,
  `paste_citation_tail_stripped`,
  `football_vocab_hint_emitted`.
- `nlp.alert.v1` kinds:
  `nlp_morph_ambiguity_rate_high` (warn; > 30% high-ambig over
  10min), `nlp_voice_path_diacritic_overaggressive` (warn; >
  20% restored on voice path), `nlp_lexicon_pr_diff_oversize`
  (warn; CI surface only — never user-facing),
  `nlp_lexicon_typo_squat_detected` (critical; CI surface),
  `nlp_lexicon_canonical_id_confusable_collision` (critical; CI
  surface), `nlp_answer_envelope_signature_invalid` (critical;
  Phase 9 emits, NLP receives via `maint.event.v1` for telemetry
  parity), `nlp_modality_x_temporal_contradiction` (warn; > 5%
  rate over 10min — model-quality regression signal),
  `nlp_empty_input_anomaly_per_subject` (warn; per-subject
  debounced 600s).
- `nlp.context.v1` (already exists per §10.25.1) — no schema
  change for §10.26.7 corrections; correction events are emitted
  out-of-band on `nlp.event.v1`.
- `qa.request.v1` schema_version 2→3 additive
  `request_metadata.input_source`, `request_metadata.keyboard_hint`.
- `qa.answer.v1` schema_version 2→3 additive
  `envelope_signature`, `body_canonical_sha`.

#### 10.26.14 Definition of Done additions (binding, on top of §10.25)

- [ ] All `[ ]` items in §10.26.1–§10.26.13 ticked.
- [ ] **§10.20 DoD item 24 added** — "All §10.26 ticks required."
- [ ] **~72 new proof tests** distributed:
  - §10.26.1 morphology: ≈ 14 (top-K, confidence floor, gazetteer
    cross-check, POS preference, co-token context, tie-break,
    proper-noun bypass, unparseable fall-through, ambiguity
    budget, determinism, parity, hypothesis-property, AST guard
    proper-noun, AST guard Go-no-morphology)
  - §10.26.2 ASR: ≈ 8 (auto-detect, filler strip happy + cap +
    abuse, relaxed split, diacritic loosening, capitalization
    short-circuit disabled, latency, voice-slice eval gate)
  - §10.26.3 IME: ≈ 7 (Q vs F lookup divergence, swipe,
    autocorrect cascade hit + miss, layout cache TTL, layout
    inference, AST optional-param, log-PII-hint-class-only)
  - §10.26.4 numeric/temporal: ≈ 9 (number-word bijection 0..9999
    sample, ordinal forms x3, fractional time x3,
    relative-temporal polarity, DST crossing, decimal-vs-thousands
    disambiguation, partial-number guard, AST guard past-routes-
    not-predict)
  - §10.26.5 modality: ≈ 6 (counterfactual route, inferential
    past, evidential hearsay, obligative refuse, epistemic OK,
    modal-x-temporal contradiction)
  - §10.26.6 lexicon supply-chain: ≈ 5 (PR diff cap, typo-squat
    detect, ortho-confusable canonical, alias provenance min-3,
    bot-impersonation refuse)
  - §10.26.7 correction: ≈ 5 (negation-of-prior, replacement,
    restart, false-positive corpus, AST guard
    no-correction-without-conversation-id)
  - §10.26.8 envelope HMAC: ≈ 5 (sign + verify happy, missing
    signature warn vs enforce, key rotation grace, cache-writer
    signs AST, gateway-verify boundary forward-contract)
  - §10.26.9 long-form paste: ≈ 6 (each whitespace variant,
    quotes, dashes, ellipsis, soft-hyphen, citation-tail,
    length-cap-ordering, hypothesis idempotency)
  - §10.26.10 football vocab: ≈ 4 (hint to classifier, abuse-
    bilingual via offensive table, build verify, intent_hint
    enum-membership)
  - §10.26.11 empty-input anomaly: ≈ 3 (rate trigger, debounce,
    AST guard no-mitigation-at-NLP-layer)
  - **Cumulative Phase 10: ≈ 390+ proof tests across §10.20 +
    §10.21 + §10.22 + §10.23 + §10.24 + §10.25 + §10.26.**
- [ ] **`make swarm.demo.nlp.full` extends** within ≤ 60s budget
  (tightening from §10.25 baseline) to exercise: (a) one
  morphologically ambiguous proper-noun input arbitrated via
  gazetteer cross-check; (b) one voice-path query with fillers
  stripped; (c) one autocorrect-cascade-repaired query; (d) one
  counterfactual-past query routed to `meta.counterfactual_unsupported`;
  (e) one paste-style input with citation-tail stripped; (f) one
  number-word year resolution; (g) one multi-turn correction;
  (h) one cache-served answer with envelope HMAC verified.
- [ ] **Chart compatibility additions.** Pin
  `tr_morph_freq.json` SHA, `keyboard_confusables.tr.yaml` source
  diagrams' SHA, `aspect_markers.tr.yaml` schema-version,
  `correction_markers.tr.yaml` schema-version, football vocab
  table SHA. No new third-party deps (all closed tables and
  pure-stdlib resolvers).
- [ ] **Documentation.** `docs/design/TURKISH_NLP.md` gains
  five new sections: "Morphological Arbitration", "Voice-to-Text
  Tolerance", "Mobile-IME Awareness", "Counterfactual & Modal-
  Aspect Firewall", "Output Envelope Integrity". `docs/guides/nlp_runbook.md`
  gains: "Morphology ambiguity-rate triage", "Voice-path
  diacritic-aggression triage", "Lexicon PR-flood incident
  response", "Envelope-HMAC key rotation".
- [ ] **Cross-phase contract updates.**
  - Phase 7 sec layer: no change (morphology is Python-only;
    boundary test asserts).
  - Phase 8 patcher scope: `nlp/lang_tr/modality/`,
    `nlp/lang_tr/correction/`, `nlp/lang_tr/numbers/`,
    `nlp/lang_tr/asr/`, `nlp/lang_tr/ime/`,
    `nlp/lang_tr/copy_paste/`, `nlp/lang_tr/football/` all
    EXCLUDED (mirrors §10.21.11) — language tables ship via human
    review, not auto-patch.
  - Phase 9 gateway: gains `qa.answer.v1` envelope HMAC
    verification (forward contract; Phase 9 §9.17.x picks up the
    obligation when implemented).
  - Phase 11 compute: morphological analyzer is CPU-only; AST
    guard rejects any `cuda` / `mps` import under `ai/nlp/morph/`.
  - Phase 13a LeagueCatalog: no change (morphology operates on
    surface forms; canonical IDs unchanged).
  - Phase 16 emitter: `LexiconStore` Protocol unchanged
    (morphology consumes the same lexicon snapshot).
  - Phase 19 long-tail leagues: morphology rules are language-
    level not league-level — no per-league branching introduced
    (AST guard `test_nlp_no_per_league_branch` from §10.0
    re-asserts on §10.26 code).
  - Phase 20 monetization: counterfactual + obligative refusals
    are tier-blind doctrine lines, not paywalls — explicit AST
    guard `test_nlp_modality_refusal_does_not_branch_tier`.

### 10.27 Match-lifecycle, abuse-resilience, regulatory compliance, and operator tooling (binding addendum)

> Mirrors the §10.21–§10.26 pattern. **Eighth** Phase 10 design pass.
> §10.21 = integrity floor; §10.22 = TR-language correctness; §10.23 =
> production serving; §10.24 = TR-input completeness; §10.25 =
> lifecycle / conversation / time-travel; §10.26 = morphology /
> input modality / counterfactual; §10.27 = **match-lifecycle, abuse,
> regulatory, operator tooling** — the residue that turns "a system
> that handles a single pre-match Turkish query well" into "a system
> that survives live football matches, production incidents, evolving
> client SDKs, and Turkish law". Every `[ ]` here is binding for
> Phase 10 DoD (per §10.20 item 25). New cfg knobs land alongside
> §10.19 in the same triangle commit.

#### 10.27.1 Fixture-state machine (binding closed enum) and dispatch routing

- [ ] **Closed enum.** `ai/common/fixture_state.py::FixtureState`
  ∈ `{scheduled, prematch_locked, in_play_first_half, halftime,
  in_play_second_half, in_play_extra_time, penalty_shootout,
  finished, postponed, suspended, abandoned, cancelled, awarded,
  unknown}` (14 values, schema_version=1, additive-only). Source
  of truth: Phase 4 storage agent's `match_normalized.state` field
  (extended additively); LeagueCatalog never emits these — they
  are runtime computed from the upstream feed by the datasource
  layer (Phase R1). NLP **never** infers state from kickoff_time
  alone (real bug class: a 21:00 kickoff with a 90-minute delayed
  start would otherwise be silently treated as "scheduled" at
  21:30 and route to pre-match predictors).
- [ ] **Lookup contract.** `nlp.dispatcher.v1` calls
  `FixtureStateLookup.get(match_id) → (state, as_of_utc, source)`
  via `data.request.v1{kind=fixture_state}` (NEW kind under the
  closed `data.request.v1` kind enum — additive). Reply MUST
  arrive within `cfg.nlp_fixture_state_lookup_timeout_ms=250`
  (deadline-propagated from `nlp_pipeline_timeout_ms`); on
  timeout → fall through to `unknown` with explicit
  `degraded_reason=fixture_state_unknown`. **NEVER** assume
  `scheduled` as a default — that would silently re-enable the
  pre-match predictor on a postponed match.
- [ ] **Routing matrix (binding, deterministic, table-driven in
  `ai/nlp/dispatch/fixture_state_routing.yaml`):**

  | State | `predict.*` intents | `data.*` intents | `summary.*` intents |
  |---|---|---|---|
  | `scheduled` / `prematch_locked` | route normally | route normally | route normally |
  | `in_play_*` / `halftime` / `penalty_shootout` | **REFUSE** → `meta.live_match_unsupported` template (humanizer-bypassed, Turkish "Maç şu an oynanıyor; canlı tahmin sunmuyorum, mevcut skoru paylaşırım") + auto-route the underlying match-id to `data.request.v1{kind=live_state}` | route to `data.request.v1{kind=live_state}` (NEW kind, additive) | refuse for affected fixture; remainder of summary proceeds |
  | `finished` | route to `data.request.v1{kind=h2h}` w/ outcome — NEVER `predict.*` | route normally | route normally |
  | `postponed` / `suspended` | refuse → `meta.fixture_postponed` template w/ new kickoff if known else `meta.fixture_postponed_unknown_reschedule` | route to `data.fixture_lookup` w/ explicit Turkish "ertelendi" disclosure | exclude from summary; mention in disclosure |
  | `abandoned` | refuse → `meta.fixture_abandoned` (rare; UEFA crowd-trouble cases) | route w/ disclosure | exclude w/ disclosure |
  | `cancelled` / `awarded` | refuse → `meta.fixture_cancelled` (awarded carries forfeit context) | route w/ awarded result if applicable | exclude |
  | `unknown` | refuse → `meta.fixture_state_unknown` (degraded) | route w/ degraded flag | refuse for affected fixture |

  AST `test_nlp_dispatcher_consults_fixture_state_before_predict`
  — every dispatcher branch that constructs `predict.request.v1`
  must be preceded by a `FixtureStateLookup.get` call; ordered by
  control-flow traversal not source-line ordering.
- [ ] **`data.request.v1{kind=live_state}` is a new closed kind**
  (additive, schema_version=1; consumer = Phase 4 storage agent's
  Pivot R1 successor). Out of scope for v1: betting markets on
  live state — that is a Phase 22+ capability and explicitly
  reserved (CLAUDE.md doctrine: never route a "live tahmin?"
  query to a predictor that has never seen a live state).
- [ ] **`meta.live_match_unsupported`, `meta.fixture_postponed`,
  `meta.fixture_postponed_unknown_reschedule`,
  `meta.fixture_abandoned`, `meta.fixture_cancelled`,
  `meta.fixture_state_unknown`** added to the §10.4 closed intent
  enum (additive; intent classifier never emits these — they are
  *router-injected* terminal intents). `make verify.nlp-templates`
  asserts a `<intent>.tr.j2` exists for each.
- [ ] **Idempotency under state change mid-RPC.** If the
  predictor RPC was already in flight when state flipped to
  `in_play_*` (kickoff happened during `predict.request →
  predict.approved` hop), the dispatcher discards the
  `predict.approved.v1` on arrival and emits the live-match
  refusal instead. New `nlp.event.v1{kind=fixture_state_flipped_during_rpc}`
  carries `(match_id, prior_state, new_state, rpc_age_ms)` —
  PII-clean, bounded cardinality (state pairs only).
- [ ] **Proof tests** (≥ 14 deterministic):
  `test_dispatcher_refuses_predict_on_in_play_state`,
  `test_dispatcher_routes_live_query_to_live_state_kind`,
  `test_dispatcher_treats_unknown_state_as_refuse_not_scheduled`,
  `test_dispatcher_postponed_routes_to_fixture_postponed_template`,
  `test_dispatcher_finished_routes_to_h2h_not_predict`,
  `test_dispatcher_abandoned_distinct_from_cancelled`,
  `test_dispatcher_awarded_carries_forfeit_context`,
  `test_dispatcher_state_lookup_timeout_falls_through_to_unknown`,
  `test_dispatcher_consults_state_before_every_predict_request_ast`,
  `test_dispatcher_state_flip_mid_rpc_discards_prediction`,
  `test_dispatcher_state_flip_mid_rpc_emits_event`,
  `test_summary_excludes_postponed_fixture_with_disclosure`,
  `test_meta_live_match_unsupported_template_humanizer_bypassed`,
  `test_fixture_state_routing_yaml_matches_enum_completeness`.

#### 10.27.2 Calibration-vs-fixture-state freshness gate

- [ ] **Real bug** the prior 7 passes missed: §10.21.10 pinned
  confidence-band stability for *probability* values but did not
  check that the calibration profile's *training horizon* is
  appropriate for the fixture's current state. Concretely: a
  pre-match calibration trained on minute-0 features will
  silently apply to a "what's the probability now?" query at
  minute 65 — answer would be probabilistically nonsensical.
- [ ] **Calibration freshness contract.** Every
  `predict.approved.v1` carries
  `calibration_state_horizon ∈ {prematch, live, both}`
  (additive on the existing schema_version 2 → 3; mirrors §10.0
  `degraded` round-trip). NLP rejects any approval whose horizon
  does not match the fixture's current state at answer-render
  time — emits `meta.calibration_horizon_mismatch` template and
  one `nlp.alert.v1{kind=calibration_horizon_mismatch, severity=error}`
  (debounced 300s per `(profile_id, state_class)` to bound
  cardinality). State change between RPC start and render time is
  the §10.27.1 case and takes precedence.
- [ ] **Backstop for v1.** Phase 5 / Phase 16 only train pre-match
  calibrations at v1 (live calibration is a Phase 22+ deliverable);
  setting `cfg.nlp_calibration_horizon_strict=true` (default true)
  hard-rejects any approval with `horizon != prematch` for v1
  delivery — defense in depth against an upstream miswiring.
- [ ] **Proof tests** (≥ 5):
  `test_nlp_rejects_live_horizon_calibration_in_v1`,
  `test_nlp_rejects_prematch_horizon_on_in_play_fixture`,
  `test_nlp_alert_calibration_horizon_mismatch_debounced`,
  `test_nlp_calibration_horizon_round_trip_through_qa_answer`,
  `test_nlp_calibration_horizon_strict_default_true_in_config_sync`.

#### 10.27.3 Forensic incident response — complaint trace rebuild

- [ ] **Real operator gap** — §10.25.3 ships time-travel re-render
  but only by `nlp_audit_bundle_sha`; no operator workflow goes
  from "user complaint → re-render". Add `make nlp.complaint-trace
  REQUEST_ID=<uuidv7>` (new xops/makefile/nlp.py command). Resolves
  request_id → audit row → bundle_sha → re-render → byte-identical
  comparison against the audit-stamped output → exit 0 (match) or
  exit 7 (drift) with a unified-diff report at
  `data/nlp/complaint_traces/<request_id>/diff.txt`. PII-redacted
  per §10.21.7 PIIScrubFilter.
- [ ] **Audit row resolution.** request_id (UUIDv7, sortable
  timestamp prefix per Phase 9 §9.1) → audit-CSV scan bounded to
  the 24h window centred on the embedded timestamp (rejects
  unbounded scans → operator paste-error defense). >1 match raises
  `RequestIdCollision` (real but extremely rare per UUIDv7);
  operator flag `--strict-uniqueness=false` allows the latest.
- [ ] **No PII in the trace dir.** Bundle sha + canonical inputs
  only; original user text **never** materialised on disk
  (mirrors §10.21.7 spool discipline). When the original text is
  needed for a deeper investigation, separate operator-confirmed
  workflow `make nlp.complaint-trace-with-text REQUEST_ID=...
  --confirm-pii` (typed-token confirmation gate, mirrors §8.1/§8.9
  doctrine; emits `maint.event.v1{kind=nlp_pii_recovered_for_trace,
  operator_id_h, request_id, reason_text_sha8}` audit row to
  `maint_audit_log` — operator accountability).
- [ ] **Proof tests** (≥ 6):
  `test_complaint_trace_byte_identical_when_artifacts_pinned`,
  `test_complaint_trace_exit_7_on_drift`,
  `test_complaint_trace_collision_strict_default`,
  `test_complaint_trace_no_raw_text_in_output_dir_default_path`,
  `test_complaint_trace_with_text_requires_confirm_pii_token`,
  `test_complaint_trace_with_text_emits_pii_recovered_audit_row`.

#### 10.27.4 In-flight bad-batch kill switch

- [ ] **Operator runbook step that does not exist today.** When
  the proofreader has a regression / template renders an
  unintended phrase / humanizer leaks an offensive token through
  the §10.22.9 gate, the only available action is "wait for the
  next deploy". Add `ops.nlp-kill-pattern` (new opsctl
  subcommand under §8 maint surface): operator submits a
  pattern-pack `{template_id?, intent_class?, lexicon_hit?,
  body_substring_sha8?, ttl_s ≤ cfg.opsctl_nlp_kill_max_ttl_s=3600}`
  via the standard maint envelope; NLP pods subscribe to
  `maint.event.v1{kind=nlp_kill_pattern_armed}` and rewrite any
  matching in-flight or cache-hit answer to the
  `meta.temporarily_unavailable` template until TTL expiry.
- [ ] **Cache invalidation.** Arming a kill-pattern publishes a
  bumped `cache:nlp:kill_gen` counter; L0 (§10.23.9) and L1
  caches treat all stored answers as stale until the next
  successful render confirms the new gen does not match.
  Operator-driven; not a freshness signal.
- [ ] **Audit + sec.alert.** Every armed pattern emits
  `maint.event.v1{kind=nlp_kill_pattern_armed,operator_id_h,
  pattern_pack_sha8,ttl_s}` and one
  `sec.alert.v1{kind=nlp_kill_pattern_armed,severity=warn,
  event_correlation_id=<maint_request_id>}` (per §8.16.9 dual-emit
  doctrine). Auto-disarmed at TTL expiry → matching `_disarmed`
  events. **No silent armed kill-patterns** — boot-time validator
  refuses start if a `armed` row exists past its TTL (operator
  forgot to disarm, system would silently filter forever).
- [ ] **Closed scope.** Pattern-pack matching is **deterministic
  and bounded**: substring-sha8 only (no live regex compile —
  defends against operator-supplied catastrophic backtracking),
  intent_class ∈ closed §10.4 enum, template_id ∈ closed registry,
  lexicon_hit canonical_id only. AST guard
  `test_nlp_kill_pattern_pack_no_regex_compile_path`.
- [ ] **Proof tests** (≥ 7):
  `test_kill_pattern_armed_rewrites_inflight_render`,
  `test_kill_pattern_armed_rewrites_cache_hit`,
  `test_kill_pattern_auto_disarms_at_ttl`,
  `test_kill_pattern_boot_refuses_on_stale_armed_row`,
  `test_kill_pattern_pack_no_regex_compile_path_ast`,
  `test_kill_pattern_emits_dual_maint_and_sec_alert`,
  `test_kill_pattern_ttl_capped_at_opsctl_nlp_kill_max_ttl_s`.

#### 10.27.5 Operator preview mode (impersonation without side effects)

- [ ] **Why.** Operators triaging an incident need to reproduce a
  user's view without (a) writing audit rows that pollute the
  forensic trace, (b) writing shadow-training rows that pollute
  the next intent retrain, (c) decrementing the user's tier
  quota (Phase 20 forward), (d) consuming budget under
  §10.23.8.
- [ ] **Header contract.** `X-NLP-Preview: true` header on
  `qa.request.v1` (gateway honours after operator-cert mTLS
  validation per Phase 9; the §10.21.7 PIIScrubFilter ensures
  no operator-introduced PII leaks). Server stamps
  `request_metadata.preview=true` on every downstream
  envelope; consumers MUST honour:
  - `nlp.shadow.v1` writer **drops** preview rows (AST guard
    `test_nlp_shadow_writer_drops_preview_rows`).
  - Audit pipeline writes to `data/nlp/audit_preview/<utc>/...`
    (separate dir, rotated weekly, NEVER fed to
    `make nlp.complaint-trace`).
  - Cache writes are **disabled** (preview answers never
    contaminate the user-facing cache).
  - Tier quota middleware (Phase 20) skips preview requests.
  - Humanizer cost accounting (§10.23.8) writes preview tokens
    to a separate per-operator counter (`nlp_preview_tokens_per_operator`)
    capped at `cfg.nlp_preview_token_budget_per_operator_per_h=2400`
    — defends against runaway operator-driven cost.
- [ ] **Boundary discipline.** AST guard
  `test_nlp_preview_flag_propagates_through_full_pipeline`
  (every envelope schema that traverses NLP carries the
  `request_metadata.preview` field; AST scan asserts no
  intermediate envelope drops it).
- [ ] **Proof tests** (≥ 5):
  `test_preview_request_does_not_write_shadow`,
  `test_preview_request_writes_to_separate_audit_dir`,
  `test_preview_request_does_not_populate_cache`,
  `test_preview_token_budget_capped_per_operator`,
  `test_preview_flag_propagates_full_pipeline_ast`.

#### 10.27.6 Coordinated abuse detector (orthogonal to per-request §7 sec)

- [ ] **Real attack class** prior passes missed: §7 sec rate-
  limits per-subject; §10.25.7 active-learning has anti-
  tampering on provenance mismatch. Neither catches **slow-burn
  coordinated** attacks: 1000 distinct accounts each submit one
  query/hour for a week, all crafted to nudge the next intent
  classifier retrain toward a chosen mis-classification. Each
  individual query is benign; the aggregate is not.
- [ ] **Detector.** `nlp.abuse.v1` (NEW agent class in
  `ai/swarm/agents/nlp/abuse.py`, replicas:1 — single-publisher
  for cluster-wide aggregates; consumes `nlp.shadow.v1` only,
  PII-clean by construction). Maintains 4 streaming aggregates
  over the rolling `cfg.nlp_abuse_window_h=168` (1 week):
  1. **Did-you-mean acceptance ratio per (offered_intent,
     accepted_intent) pair.** Sustained `accepted/offered >
     cfg.nlp_abuse_dym_acceptance_anomaly_ratio=4.0` ×
     `(prior 4-week ewma)` → `nlp.alert.v1{kind=nlp_abuse_did_you_mean_anomaly,
     severity=warn}`.
  2. **Cohort style-shift (account-takeover proxy).** Per
     `account_id_h`, rolling 7-day distribution over (locale,
     mean_token_length, intent_class top-3, voice/keyboard
     modality from §10.26.2) — KL-divergence vs. the prior
     30-day baseline > `cfg.nlp_abuse_style_shift_kl=0.6` →
     `nlp.alert.v1{kind=nlp_abuse_style_shift, severity=warn}`
     (per-account; debounced 24h per account_id_h). Phase 9
     auth surface consumes the alert and may trigger step-up
     auth (forward contract; not a hard block from NLP).
  3. **Shadow-training cohort correlation.** Per `(intent_class,
     subject_key_sha8_prefix_2)` bucket — if > 30% of new
     shadow-rows in the past 24h come from < 5 distinct
     prefix-2 buckets (1024 total possible), → `nlp.alert.v1
     {kind=nlp_abuse_shadow_concentration, severity=warn}`.
     `make nlp.intent-train` consumes the alert state and
     refuses to train (per §10.25.5 lifecycle gates) until
     operator ack via `make nlp.abuse-shadow-clear`.
  4. **"Same fingerprint, many accounts" graph signal.** Per
     `(client_fingerprint_hash, account_id_h)` edges over
     7d — Jaccard-similarity bucket flagged if > 100 distinct
     accounts share a single client_fingerprint_hash AND > 0.5
     of them appear in the same shadow-training-eligible bucket
     → `nlp.alert.v1{kind=nlp_abuse_account_farm, severity=error}`.
- [ ] **Closed alert kinds + open-enum AST guard.** All four
  kinds added to `KNOWN_NLP_ALERT_KINDS` (mirrors §7.4
  doctrine). Producer set bounded — only `nlp.abuse.v1` may
  emit; `test_only_nlp_abuse_v1_emits_abuse_kinds`.
- [ ] **Tier-blind.** Detector is account-class-agnostic; AST
  guard `test_nlp_abuse_detector_does_not_branch_tier`.
- [ ] **Proof tests** (≥ 8):
  `test_did_you_mean_anomaly_fires_above_ratio_floor`,
  `test_did_you_mean_anomaly_does_not_fire_at_baseline_drift`,
  `test_style_shift_fires_on_synthetic_kl_above_threshold`,
  `test_shadow_concentration_blocks_intent_train_until_ack`,
  `test_account_farm_emits_error_severity`,
  `test_abuse_detector_consumes_only_nlp_shadow_v1_ast`,
  `test_abuse_alert_producer_set_bounded`,
  `test_abuse_detector_does_not_branch_tier_ast`.

#### 10.27.7 Schema-version downgrade for old clients (qa.answer.v1 v3 → v1)

- [ ] **Real client-compat bug.** §10.24.5 bumped `qa.answer.v1`
  schema 1 → 2 (added `parts[]`); §10.26.8 bumped 2 → 3 (added
  `envelope_signature`). Old client SDKs pinned to schema=1 will
  see additional fields they don't recognise; some will
  hard-fail JSON-decode on `additionalProperties:false`-style
  client validators. Single-source doctrine: the *server*
  honours the client's requested schema version and downgrades.
- [ ] **Header contract** (Phase 9 forward addition):
  `Accept: application/vnd.negelir.qa-answer+json; version=1|2|3`
  (default = highest stable = 3 at landing). Server picks the
  intersection of `client_max ≤ server_supported ≤ client_min`
  and downgrades the response by **stripping additive-only
  fields** (`parts[1:]` collapsed into top-level for v1;
  `envelope_signature` omitted for v < 3). Schema for the
  downgraded body still validates against the version's pinned
  schema file (cross-language gate test).
- [ ] **Downgrade compatibility matrix** at
  `ai/swarm/sdk/schemas/qa.answer.v1.downgrade_matrix.json`
  (single-source — handler reads this, never hardcodes
  per-version logic in the renderer): `{from_version → to_version
  → list[strip_field_path]}`. AST asserts handler dispatches via
  this matrix only (`test_nlp_qa_answer_downgrade_handler_uses_matrix_only`).
- [ ] **Sunset for old versions.** `cfg.nlp_qa_answer_min_supported_version=1`;
  flipping to 2 emits 6-month `Sunset:` + `Deprecation:` headers
  per Phase 9 RFC 8594 doctrine, then refuses with 426 Upgrade
  Required at the deadline. Operator-toggleable; documented in
  `docs/guides/nlp_runbook.md` runbook.
- [ ] **Round-trip integrity invariant.** When envelope_signature
  was stripped (downgrade to v < 3), the *client* cannot verify
  HMAC; this is acceptable for v < 3 clients (they predate the
  feature) but the server SHOULD log the downgrade event to
  `nlp.event.v1{kind=qa_answer_downgraded, from=3, to=1,
  client_id_h, sha_envelope}` so operators can drive deprecation.
- [ ] **Proof tests** (≥ 6):
  `test_qa_answer_downgrade_v3_to_v1_strips_signature_and_collapses_parts`,
  `test_qa_answer_downgrade_v3_to_v2_keeps_parts_strips_signature`,
  `test_qa_answer_downgrade_v2_to_v1_collapses_parts_only`,
  `test_qa_answer_downgrade_handler_uses_matrix_only_ast`,
  `test_qa_answer_v1_min_supported_426_at_deadline`,
  `test_qa_answer_downgrade_emits_event_per_request`.

#### 10.27.8 Regulatory disclosure invariant (KVKK Art 11 + Turkish gambling law + GDPR Art 22 equivalent)

- [ ] **Why this is mandatory not optional.** Negelir produces
  algorithmic outputs about football match probabilities served
  to Turkish-resident users. Three regulatory regimes intersect:
  **KVKK Art 11** (data subject rights — must surface a path to
  view / correct / erase personal data); **Turkish gambling law**
  (predictions involving outcomes against a tier-priced surface
  trigger Spor Toto / Iddaa wording obligations and 18+ gating —
  even though Phase 20 monetization is dormant at v1, the
  prediction surface itself qualifies); **GDPR-Art-22-equivalent**
  KVKK Art 11/h (right not to be subject to a solely automated
  decision — predictions must be disclosed as such, not framed
  as expert advice).
- [ ] **Closed disclosure registry.** `ai/nlp/compliance/disclosures.tr.yaml`
  (single-source, hot-reloadable per §10.2 atomic-swap
  discipline; CODEOWNERS includes `nlp-compliance` reviewer per
  §10.25.6 governance):
  - `kvkk_user_rights_footer_first_per_conversation` — appended
    to the first answer of every new `conversation_id`
    (§10.25.1) by the renderer; suppressed on subsequent turns
    via in-memory `conversation_disclosures_emitted` set.
  - `gambling_law_disclaimer_band` — prepended to every
    `predict.*` answer; closed Turkish text, version-stamped,
    last 4 chars of `disclosure_sha8` recorded in
    `qa.answer.v1.disclosures[]` (NEW additive field on schema
    v3 → v4; falls under §10.27.7 downgrade as `[strip]` for
    v < 4).
  - `automated_decision_notice` — appended once per
    `conversation_id` to `predict.*` answers.
  - `eighteen_plus_gate` — prepended to first per-conversation
    `predict.*` answer if `request_metadata.user_age_attestation
    is None` AND `cfg.nlp_age_gating_enabled=true`. Defaults
    OFF at v1 (no auth → no age attestation); flipped ON when
    Phase 9 self-registration ships post-Phase-9 §9.2.
- [ ] **Renderer order (binding).** `[gambling_law_disclaimer_band]
  + [eighteen_plus_gate?] + body + [kvkk_user_rights_footer?] +
  [automated_decision_notice?]`. Humanizer-bypassed (§10.7
  doctrine — disclosures are byte-stable closed text, never
  rephrased). AST `test_nlp_disclosures_humanizer_bypassed`.
  `make nlp.template-lint` extended to assert no template ever
  templates a disclosure substring (defense in depth — keeps
  disclosures owned by the renderer, not template authors).
- [ ] **Locale resolution.** `disclosures.<locale>.yaml` per
  §10.17 forward hook; v1 ships `tr.yaml` only; missing locale
  falls back to `tr.yaml` w/ `nlp.event.v1{kind=disclosure_locale_fallback}`.
- [ ] **Audit.** Every emitted disclosure logs
  `nlp.event.v1{kind=disclosure_emitted, disclosure_id,
  disclosure_version, conversation_id, request_id}` so legal /
  compliance can prove on demand which exact text version was
  served at time T. PII-clean (no body text — disclosure_id +
  version + conversation_id only).
- [ ] **Closed enum + version policy.** `disclosure_id` ∈ closed
  enum (4 values at v1); each carries `version: <int>` +
  `effective_from_utc`. Bumping a disclosure version is a Phase
  10 / Phase 20 codepath that requires `nlp-compliance` reviewer;
  CODEOWNERS-enforced. Revoking a disclosure (rare; requires
  legal sign-off) is a separate 2-reviewer gate.
- [ ] **Cache key extension.** L0 / L1 cache key (per §10.25.10
  7-8 components) gains `disclosures_snapshot_sha` as a 9th
  component — atomic disclosure-text rotation invalidates the
  cache cluster-wide on next read (no stale disclosure ever
  served).
- [ ] **Proof tests** (≥ 9):
  `test_kvkk_footer_first_per_conversation_only`,
  `test_gambling_disclaimer_on_every_predict_answer`,
  `test_automated_decision_notice_first_per_conversation_only`,
  `test_disclosures_humanizer_bypassed_ast`,
  `test_template_lint_rejects_disclosure_substring_in_template`,
  `test_disclosures_locale_fallback_emits_event`,
  `test_disclosure_version_bump_requires_compliance_codeowner_via_make_verify`,
  `test_cache_key_includes_disclosures_snapshot_sha`,
  `test_qa_answer_disclosures_field_strippable_for_v_lt_4_clients`.

#### 10.27.9 Cross-pod lexicon-swap consistency window (drain-before-swap)

- [ ] **Real correctness bug** §10.21.5 missed: lexicon hot-reload
  is per-pod-mtime-poll; in a multi-pod deployment (Phase 14)
  pods see the new file at slightly different times within
  `cfg.nlp_lexicon_reload_s=30`. Two users hitting two pods
  during the swap edge see *different canonical resolutions*
  for the same query — silent A/B inconsistency.
- [ ] **Drain protocol.** `make nlp.lexicon-deploy LEXICON=<name>
  VERSION=<sha>` (new xops/makefile/nlp.py command) writes the
  new file with `_meta.swap_at_utc = now() + cfg.nlp_lexicon_swap_grace_s=120`
  marker. Pods load the file at mtime detection but DO NOT swap
  the active pointer until `now_utc() ≥ swap_at_utc`. All pods
  swap in a tight cluster-wide window (≤ NTP skew, typ. <1s)
  rather than over the full mtime-poll window.
- [ ] **Stragglers.** Pods that load the new file > 30s after
  `swap_at_utc` (mtime-poll missed it) emit
  `nlp.alert.v1{kind=lexicon_swap_late, severity=warn,
  pod_id, lag_s}` and proceed to swap immediately. Pods unable
  to load the file by `swap_at_utc + cfg.nlp_lexicon_swap_max_lag_s=600`
  emit `severity=error` and refuse new traffic (readiness 503
  mirrors §10.21.9 cold-start gate) until they catch up.
- [ ] **Atomicity preserved.** Within a single pod, §10.21.3
  all-or-nothing 6-file swap still applies; this addendum
  coordinates *across* pods, not within.
- [ ] **Cache coherence.** Lexicon swap bumps the
  `lexicon_snapshot_sha` cache-key component (§10.23.9) — old
  cache entries invalidate naturally as the new gen propagates.
- [ ] **Proof tests** (≥ 5):
  `test_lexicon_swap_at_utc_marker_respected_by_pods`,
  `test_lexicon_swap_late_emits_warn_alert`,
  `test_lexicon_swap_max_lag_pod_drains_to_503`,
  `test_lexicon_atomic_swap_within_pod_still_holds`,
  `test_lexicon_swap_bumps_cache_key_snapshot_sha`.

#### 10.27.10 Anti-leakage gates on shadow → training pipeline

- [ ] **Real bug** §10.25.5 left implicit: "data ONLY from
  `nlp.shadow.v1`" doesn't pin *which* shadow rows are eligible
  for training. Three classes of row are toxic to the next
  intent retrain:
  1. `degraded=true` rows — model would learn to mimic
     degraded behaviour.
  2. Quarantined rows (sec gate emitted `sec.quarantine.v1`
     for the underlying request) — model would learn from
     adversarial inputs.
  3. Proofreader-blocked rows (§10.9 fired) — model would
     learn from outputs the system itself rejected.
  4. Preview rows (§10.27.5) — model would learn from
     operator probes, not real user intent.
  5. Kill-pattern-rewritten rows (§10.27.4) — similar to
     proofreader-blocked.
- [ ] **Eligibility filter** in
  `ai/swarm/agents/nlp/training/eligibility.py` (single source);
  AST guard `test_nlp_intent_trainer_consults_eligibility_filter`
  (every `make nlp.intent-train` data-loader path passes through
  this filter). Filter emits a manifest at
  `data/nlp/training_manifests/<train_run_id>.json` listing
  excluded row counts per reason — operator-auditable proof of
  no leakage.
- [ ] **Eval-vs-train membership manifest.** §10.18 evaluation
  fixtures (≥ 250 entries) carry `request_id_h` (sha256 of the
  hand-curated entry); `make nlp.intent-train` MUST exclude any
  shadow row whose `request_id_h` matches an eval-set entry.
  AST `test_nlp_train_excludes_eval_set_membership` + manifest
  carries the cross-check sha to prove the exclusion ran.
- [ ] **Cohort-de-duplication.** Beyond per-row exclusion, group
  rows by `(subject_key_sha8_prefix_2)` and cap each bucket at
  `cfg.nlp_intent_train_max_rows_per_subject_bucket=500` to
  defend against the §10.27.6 abuse-class shadow concentration
  reaching the trainer even if the abuse detector missed it
  (defence in depth).
- [ ] **Proof tests** (≥ 7):
  `test_eligibility_excludes_degraded_rows`,
  `test_eligibility_excludes_quarantined_rows`,
  `test_eligibility_excludes_proofreader_blocked_rows`,
  `test_eligibility_excludes_preview_rows`,
  `test_eligibility_excludes_kill_pattern_rewritten_rows`,
  `test_train_excludes_eval_set_membership_via_manifest`,
  `test_train_caps_per_subject_bucket_under_abuse_threshold`.

#### 10.27.11 Edge-platform answer-format profile (forward hook; dormant at v1)

- [ ] **Forward hook only at Phase 10.** WhatsApp / Telegram /
  SMS / TTS deployments have hard constraints (4096-char body,
  no markdown, 160-char SMS, prosody-friendly phrasing for
  TTS). The accessibility addendum §10.23.7 already supports
  `cfg.nlp_answer_formats=[plain, markdown_safe, screen_reader]`;
  this extends to `[plain, markdown_safe, screen_reader,
  whatsapp_4096, sms_160, tts_neutral]` — the three new formats
  ship with **stub renderers** that emit a `meta.format_unsupported`
  template at v1 (so the negotiation surface exists but the
  channel itself is not enabled). Reserves the enum slot
  (additive-safe forward).
- [ ] **Negotiation.** `?answer_format=` query param > `Accept`
  header > `cfg.nlp_default_answer_format=plain`. AST
  `test_nlp_format_negotiation_order_pinned`.
- [ ] **Closed config.** `nlp_answer_format_enabled` map
  `{plain:true, markdown_safe:true, screen_reader:true,
  whatsapp_4096:false, sms_160:false, tts_neutral:false}` —
  defaults pinned; flipping requires per-channel renderer impl
  (Phase 22+ deliverables).
- [ ] **Proof tests** (≥ 4):
  `test_format_negotiation_order_query_then_accept_then_default`,
  `test_format_unsupported_returns_meta_template`,
  `test_format_enum_reserves_three_new_slots_additively`,
  `test_format_enabled_default_pins_three_new_off`.

#### 10.27.12 Per-conversation entity-graph snapshot (extends §10.25.3 audit bundle)

- [ ] **Real gap** §10.25.3 stores `(lexicon_set_sha, intent_sha,
  crf_sha, calibration_version, template_git_sha, pipeline_version)`
  but NOT the conversation context that produced the answer (the
  `qa.context.v1` entities-only graph from §10.25.1). Without it,
  a re-render of turn 5 of a 7-turn conversation cannot reproduce
  the answer because turn 5's entity inheritance from turns 1-4
  is lost.
- [ ] **Bundle extension.** `nlp_audit_bundle_sha` extended (single
  fixed extension; bumps `pipeline_version` once at landing) to
  include `conversation_entity_graph_sha` = sha256 over the
  canonical-serialised `qa.context.v1` snapshot at the moment of
  the request. Bundle directory gains
  `<sha>/conversation_entity_graph.json` (PII-clean — entity
  canonical_ids only, no text). Re-render reads this file and
  reconstructs the conversation context before dispatching.
- [ ] **Storage cost.** Quartet-dedup (§10.25.3) extends to
  quintet-dedup; expected bundle dir count remains ≪ requests
  because conversation graphs share canonical-id sets across
  many conversations.
- [ ] **Erasure compliance.** §10.25.9 right-to-erasure extended
  to walk the bundle dir's `conversation_entity_graph.json` and
  drop any reference to the erased user's `account_id_h` —
  bundle re-rendering survives (canonical_ids alone), only the
  cross-link to the deleted account is severed.
- [ ] **Proof tests** (≥ 4):
  `test_audit_bundle_includes_conversation_entity_graph_sha`,
  `test_audit_rerender_with_conversation_context_byte_identical`,
  `test_quintet_dedup_keeps_bundle_count_bounded`,
  `test_audit_erasure_drops_account_id_h_from_graph_file`.

#### 10.27.13 Knob inventory (~22 new) + new event/alert kinds + new `data.request.v1` kinds

- [ ] **New cfg knobs** (single-source; triangle test extends):
  `nlp_fixture_state_lookup_timeout_ms=250`,
  `nlp_calibration_horizon_strict=true`,
  `opsctl_nlp_kill_max_ttl_s=3600`,
  `nlp_preview_token_budget_per_operator_per_h=2400`,
  `nlp_abuse_window_h=168`,
  `nlp_abuse_dym_acceptance_anomaly_ratio=4.0`,
  `nlp_abuse_style_shift_kl=0.6`,
  `nlp_abuse_shadow_concentration_distinct_buckets_min=5`,
  `nlp_abuse_account_farm_jaccard_min=0.5`,
  `nlp_abuse_account_farm_account_count_min=100`,
  `nlp_qa_answer_min_supported_version=1`,
  `nlp_age_gating_enabled=false`,
  `nlp_lexicon_swap_grace_s=120`,
  `nlp_lexicon_swap_max_lag_s=600`,
  `nlp_intent_train_max_rows_per_subject_bucket=500`,
  `nlp_default_answer_format=plain`,
  `nlp_answer_format_enabled` (map; closed),
  `nlp_disclosure_locale_fallback_chain=[tr-TR]`,
  `nlp_complaint_trace_default_window_h=24`,
  `nlp_kill_pattern_arm_max_concurrent=8`,
  `nlp_preview_dir`,
  `nlp_complaint_trace_dir`.
  Plus 6 feature-flag toggles for §10.27.1/§10.27.4/§10.27.5/
  §10.27.6/§10.27.7/§10.27.11.
- [ ] **New `nlp.event.v1` kinds**:
  `fixture_state_flipped_during_rpc`, `qa_answer_downgraded`,
  `disclosure_emitted`, `disclosure_locale_fallback`,
  `nlp_pii_recovered_for_trace` *(also in maint.event.v1)*,
  `nlp_complaint_trace_completed`,
  `nlp_complaint_trace_drift_detected`,
  `nlp_kill_pattern_armed_locally`, `nlp_kill_pattern_disarmed_locally`.
- [ ] **New `nlp.alert.v1` kinds**:
  `calibration_horizon_mismatch` (error),
  `nlp_abuse_did_you_mean_anomaly` (warn),
  `nlp_abuse_style_shift` (warn),
  `nlp_abuse_shadow_concentration` (warn),
  `nlp_abuse_account_farm` (error),
  `lexicon_swap_late` (warn),
  `lexicon_swap_lag_drained_to_503` (error),
  `nlp_complaint_trace_drift` (warn),
  `nlp_kill_pattern_stale_armed_at_boot` (critical),
  `nlp_preview_token_budget_exhausted_per_operator` (warn).
- [ ] **New `maint.event.v1` kinds** (consumed by NLP):
  `nlp_kill_pattern_armed`, `nlp_kill_pattern_disarmed`
  (each carries operator_id_h + pattern_pack_sha8 + ttl_s);
  `nlp_pii_recovered_for_trace` (operator-attested PII recovery).
- [ ] **New `data.request.v1` kinds** (additive on §3.5 wire
  contract): `fixture_state`, `live_state`. Both consumer is
  Phase 4 / Pivot R1 storage agent; producer set bounded to
  `nlp.dispatcher.v1`.
- [ ] **Producer set guarantees.** All new `nlp.alert.v1` kinds
  remain bounded to `{nlp.intent.v1, nlp.answer.v1,
  nlp.proofreader.v1, nlp.dispatcher.v1, nlp.abuse.v1}` —
  `test_nlp_alert_v1_producer_set_remains_bounded_after_phase_10_27`
  (mirrors §7.4 doctrine).

#### 10.27.14 Cross-phase contracts (binding)

- [ ] **Phase 4 / Pivot R1 storage.** Adds `match_normalized.state`
  field (additive); emits via the `data.request.v1{kind=fixture_state}`
  reply. Boundary test: NLP never imports the storage agent
  directly (§10.0 doctrine — only via bus).
- [ ] **Phase 5 predictors.** Calibration profiles gain
  `state_horizon` field; trainer refuses to mark a profile as
  `pre_match_locked` AND `live_eligible` simultaneously at v1
  (binary flag for now; multi-horizon Phase 22+).
- [ ] **Phase 7 sec.** `qa.request.v1` schema additive: new
  `request_metadata.preview` boolean; `request_metadata.client_format_max_version`
  int (1-3 at landing). sec gate sees both, never mutates.
- [ ] **Phase 8 maint.** New `nlp_kill_pattern_*`,
  `nlp_pii_recovered_for_trace` kinds added to
  `KIND_TO_CONSUMERS` map (§8.0). Operator subcommand wiring
  for `ops.nlp-kill-pattern` + `ops.nlp-disarm-kill-pattern`.
  Patcher scope continues to EXCLUDE `nlp/`.
- [ ] **Phase 9 API gateway.** Honours `Accept:
  application/vnd.negelir.qa-answer+json; version=N` per
  §10.27.7; honours `X-NLP-Preview` per §10.27.5 (mTLS-gated);
  rejects `?answer_format=` values not in the §10.27.11 enum
  with 400 (validates BEFORE hitting NLP). Adds the
  `qa.answer.v1` envelope HMAC verifier (§10.26.8 picked up
  here). Forward contract.
- [ ] **Phase 11 compute.** `nlp.abuse.v1` is CPU-only; AST
  rejects `cuda`/`mps`/`rocm` imports under `ai/swarm/agents/nlp/abuse.py`.
  No change to humanizer compute model.
- [ ] **Phase 12 chaos.** New stubs:
  `chaos.fixture-state-flap` (asserts dispatcher routes by
  observed state, not assumed), `chaos.kill-pattern-mass-arm`
  (asserts cap `nlp_kill_pattern_arm_max_concurrent`),
  `chaos.lexicon-swap-staggered-pods` (asserts <1s cluster-wide
  window under §10.27.9), `chaos.client-pinned-old-schema-flood`
  (asserts downgrade matrix doesn't allocate per request).
- [ ] **Phase 13a LeagueCatalog.** No change at v1; fixture-state
  is a runtime/scrape-derived attribute, not a catalog one.
- [ ] **Phase 14 K8s.** `nlp.abuse.v1` is `replicas:1`
  (single-publisher; single-process aggregate state). Lease
  via the existing §8.10 Leader Protocol.
- [ ] **Phase 16 Emitter.** `LexiconStore` Protocol gains
  `swap_at_utc` plumbing (additive; in-memory backend is no-op).
- [ ] **Phase 19 long-tail.** Fixture-state routing is league-
  agnostic; AST `test_nlp_no_per_league_branch` re-asserts on
  §10.27 code surface.
- [ ] **Phase 20 monetization.** Disclosure registry is
  tier-blind (regulatory disclosures apply to every tier
  including free); preview-mode is operator-only and skips
  tier accounting; abuse detector is tier-blind. Three explicit
  AST guards: `test_nlp_disclosures_tier_blind`,
  `test_nlp_preview_skips_tier_quota`,
  `test_nlp_abuse_detector_tier_blind` (already in §10.27.6,
  re-asserted here to surface in cross-phase scan).

### 10.28 Authentic-Turkish floor — orthographic, structural, and resource discipline (binding addendum)

> **Why this section exists.** §10.21–§10.27 hardened integrity, TR-language correctness,
> production serving, wrong-Turkish input completeness, lifecycle, morphology / modality,
> and match-lifecycle / abuse / regulatory. Eight passes still left **specific classes of
> authentically wrong Turkish** under-handled — failures that surface as *confidently
> wrong* (not gracefully degraded) answers when a real Turkish-speaker types fast,
> mis-spells per the orthographic rules native speakers actually break, concatenates
> words without spaces (mobile keyboard reality), shouts in ALL CAPS, pastes in a
> distractor preamble, embeds a TC kimlik no in their question, or otherwise hits a
> pathology no §10.x addendum has yet pinned. §10.28 is the **authentic-Turkish floor**:
> orthographic-rule tolerance (the rules native speakers most often break), structural
> robustness (no-space compounds, fragments, distractor preambles), TR-specific PII,
> and the resource-discipline guards (per-request CPU / memory budget, hot-reload
> back-pressure, cross-component skew detector) that keep the long pipeline honest
> under load. Every `[ ]` here is binding for Phase 10 DoD (per §10.20 item 26 added
> alongside this section).

#### 10.28.1 Consonant softening / vowel-drop tolerance (`ünsüz yumuşaması` + `ünlü düşmesi`)

- [ ] **Real bug.** §10.22.2 strips proper-noun suffixes correctly *when present*, but
  silently mishandles the inverse: real users type the unsoftened form (e.g.
  *"Beşiktaşın maçı"* instead of canonical *"Beşiktaş'ın maçı"*, or *"kitabı"* when
  they mean *"kitap+ı"*) **and** the softened-without-apostrophe form (*"futbolcunun
  ayağı"* vs erroneous *"ayagı"*). Lexicon hits miss because the surface form drifted
  one consonant.
- [ ] **Closed table** `ai/nlp/lang_tr/spelling/consonant_alternations.tr.yaml`:
  per-canonical-stem `{stem, final_char, soften_to, soften_blocked: bool, source:
  manual|tdk}`. AST-asserted CODEOWNER `nlp-curator`. Initial set = every
  LeagueCatalog team / player / city stem ending in `{p,ç,t,k}` plus the closed
  TR-orthography exception list (proper nouns ending in `{p,t,k}` whose softening
  is *blocked* by tradition — e.g. *"Tokat→Tokatın"* not *"Tokadın"*; *"Halit→Halitin"*
  not *"Halidin"*). Build refuses if any canonical from LeagueCatalog isn't in the
  table when its final char is in `{p,ç,t,k}` (forces explicit decision).
- [ ] **New §10.1 step 8b** `tolerate_consonant_alternation(token, lexicon_index)`
  AFTER §10.22 particle disambiguation, BEFORE typo correction. Two probes per
  unresolved token: *(a)* try softening the final consonant (`p→b, ç→c, t→d, k→ğ`)
  and re-lookup; *(b)* try un-softening if the surface form ends in `{b,c,d,ğ}` and
  the un-softened canonical exists. Cost ≤ 2 lookups (cheap; far below
  `nlp_typo_max_lookups_per_query`). Hit emits `nlp.event.v1{kind=consonant_softening_repaired}`
  debounced 60s.
- [ ] **`ünlü düşmesi` (vowel drop in 2-syllable nouns)** — *"akıl+ı"* → *"aklı"*,
  *"burun+u"* → *"burnu"*, *"şehir+i"* → *"şehri"*. Closed table
  `vowel_drop_stems.tr.yaml` with `{full_stem, dropped_form, suffix_pattern}`. Symspell
  index includes BOTH forms; canonical-id collapse via `_xref.py::validate_xref`
  ensures both surface forms map to the same canonical (build refuses on collision).
  AST `test_nlp_vowel_drop_round_trip` asserts every entry resolves bidirectionally.
- [ ] **Hard guard.** Never apply consonant softening / vowel drop to a token already
  in `_no_strip_canonicals.tr.yaml` (extends §10.22.4). Concretely: tokens *"Edirne",
  "Manisa", "Adana"* etc. must not be re-spelled; lookup hits before alternation.
- [ ] **Proof tests.** ≥ 30-row golden `consonant_alternation_corpus.tr.json` with
  1:1 expected canonical_id per surface form; CI gate 100%. Hypothesis property test
  ≥ 500 examples: `tolerate_consonant_alternation(canonical) == canonical` for every
  closed-table canonical (idempotency).

#### 10.28.2 Consonant assimilation tolerance (`ünsüz benzeşmesi / sertleşmesi`)

- [ ] **Real bug.** TR locative suffix `-de/-da` becomes `-te/-ta` after voiceless
  consonants (`p, ç, t, k, f, h, s, ş`); user-typed *"futbolda"* (correct) vs
  *"futbolta"* (wrong) vs *"galatasarayda"* (correct) vs *"galatasarayta"* (wrong)
  must all resolve to the same intent / entity. The §10.22.4 particle table only
  handles the orthographic *space* particle, not the suffixed assimilation form.
- [ ] **Closed table** `ai/nlp/lang_tr/spelling/assimilation_pairs.tr.yaml` —
  `{voiced: 'de|da|den|dan', voiceless: 'te|ta|ten|tan', triggers: [voiceless_consonants]}`.
  Two-way fold inside the §10.22.4 particle step: any `-te/-ta/-ten/-tan` after a
  vowel-final stem is folded back to `-de/-da/-den/-dan` for canonicalisation
  (purely a normalize step; the original surface form preserved in
  `entities[].original_text` per §10.21.5).
- [ ] **Symmetric: `-le/-la` → `-yle/-yla` after vowel-final stems.** Both surface
  forms map to one canonical instrumental marker.
- [ ] **Hard guard.** Never apply to tokens that are themselves dictionary entries
  (e.g. *"Nokta"* is a word, not *"Nok"+ta*). Lookup precedence: lexicon hit > particle fold.
- [ ] **Proof tests.** 40-row golden `assimilation_corpus.tr.json` covering both
  directions × 4 suffix families × 5 trigger consonants; CI 100%.

#### 10.28.3 No-space compound splitting (`birleşik yazım`)

- [ ] **Real bug.** Mobile fans drop spaces (autocorrect race, fat-finger): *"galatasarayfenerbahçe
  derbisi"*, *"liverpoolmanutd"*, *"tahminneolur"*. §10.22.7 match-pattern parser
  assumes whitespace separation; this slice silently mis-classifies as one
  unresolvable mega-token → `meta.unsupported`.
- [ ] **`compound_splitter.py`** — bounded recursive longest-prefix split against
  `(lexicon ∪ TR top-5k word-frequency)`; max 4 splits per token; max 1 application
  per query (no quadratic blow-up on adversarial input). Greedy with one-step
  backtrack only when the residual tail itself fails to lex. Cost ceiling
  `nlp_compound_split_max_lookups_per_query=24` enforced via shared budget with §10.3 typo.
- [ ] **Decision rule.** Only emit a split when *all* resulting parts resolve to
  lexicon entries OR top-1k frequency-table words. Partial coverage → discard split,
  preserve original token, fall through to typo correction. Avoids producing
  hallucinated entity pairs from random concatenations.
- [ ] **PII safety.** AST `test_nlp_compound_splitter_skips_pii_kinds` — never
  attempt to split a token already flagged by §10.28.4 PII detector (otherwise a
  concatenated TC kimlik no could be split into "harmless" digits and lose its
  PII flag).
- [ ] **Telemetry.** `nlp.event.v1{kind=compound_word_split, parts_count, applied_strategy}`
  debounced 60s/intent_class.
- [ ] **Proof tests.** ≥ 25-row corpus covering 2-, 3-, and 4-way splits; 100% gate.
  10-row negative corpus (genuine single-token: *"Galatasaraylılar"* must NOT split into
  *"Galatasaray+lılar"* because the residual is a valid TR suffix-form not a top-1k word).
  Adversarial 50-row `random_concatenation_flood.tr.json` ≥ 95% routed to
  `meta.unsupported` (NEVER hallucinated entities).

#### 10.28.4 TR-specific PII detector & redactor

- [ ] **Real bug.** §10.5 / §10.21.7 PII discipline catches `phone | email | credit-card`
  via generic patterns. Turkish users routinely embed **TC kimlik no** (11-digit,
  mod-10 + mod-11 checksum), **IBAN-TR** (`TR` + 24 digits + ISO-13616 mod-97 check),
  **Turkish mobile phone** (`+90 5XX` / `0 5XX` formats), **Turkish landline**
  (`0212/0216/0312` ...), **vehicle plate** (`34 ABC 1234`), **VKN** (10-digit tax id).
  None of these have TR-specific detectors today; KVKK Art 6/8 exposure on data-at-rest.
- [ ] **`ai/common/security/tr_pii.py`** (single source — Phase 7 sec layer also
  imports this; cross-language Go port mirrors via the §10.24.4 pattern). Detectors:
  `detect_tc_kimlik(text) -> [Span]` (regex `\b\d{11}\b` + checksum validate; first
  digit ≠ 0 + Σ-rule); `detect_iban_tr(text)` (regex `\bTR\d{2}\s?(\d{4}\s?){5}\d{2}\b` +
  mod-97 == 1); `detect_phone_tr(text)` (closed regex set covering `+90`, `0`, and
  10-digit forms with optional separators); `detect_plate_tr(text)` (`\b\d{2}\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,4}\b`
  bounded, plate-number range 01-81); `detect_vkn(text)` (10-digit + Türkiye VKN
  algorithm).
- [ ] **Pipeline integration.** New §10.1 step 0.5 `redact_tr_pii` BEFORE length cap
  (oversized PII could otherwise be split across the cap boundary and one half slip
  through unredacted). Each detected span replaced with closed sentinel
  `[REDACTED:KIND:sha8=...]`; sha8 enables idempotent operator forensic recovery via
  the `make nlp.complaint-trace --confirm-pii` workflow (§10.27.3) without ever
  storing the raw PII at rest.
- [ ] **Per-kind alert.** Each detector hit emits `nlp.alert.v1{kind=nlp_pii_in_input_<kind>,
  severity=warn}` debounced per `(subject_key_sha8, kind)` for 600s. Aggregated
  daily by Phase 8 maint console.
- [ ] **Cross-language parity.** Phase 7 Go sec layer imports the same algorithm
  (port `server/internal/sec/tr_pii.go`); byte-parity test with the Python reference
  on a 200-row corpus (positives + negatives + boundary cases: 11-digit numbers that
  are NOT valid TC because checksum fails).
- [ ] **AST guards.** (a) `test_nlp_tr_pii_runs_before_length_cap` asserts step
  ordering. (b) `test_nlp_tr_pii_redacts_inplace_no_leak` walks every downstream
  payload (`qa.intent.v1`, `qa.answer.v1`, audit rows, spool envelopes, log strings)
  and asserts no surviving raw PII byte sequence with hypothesis ≥ 1000 examples.
  (c) `test_nlp_tr_pii_idempotent` — re-running detector on already-redacted text
  is a no-op.
- [ ] **Proof tests.** ≥ 60-row golden `tr_pii_corpus.json` (12 per kind × 5 kinds)
  with positive and adversarial-near-miss examples; CI 100%.

#### 10.28.5 Loan-word transliteration unification (`ofsayt/offside/ofsayd/ofsait`)

- [ ] **Real bug.** Football-specific bilingual vocab (§10.26.10) covered the
  *concept* table; doesn't address the *spelling-variant* problem where the same
  word has 3-5 attested Turkish-pronounced spellings (*"ofsayt"*, *"ofsait"*,
  *"offside"*, *"ofsayd"*, *"ofsayde"*). Symspell with edit-distance ≤ 2 over a
  single canonical may not reach all variants; some variants are edit-distance ≥ 3
  from the canonical.
- [ ] **Closed table** `ai/nlp/lang_tr/loanwords/transliteration_variants.tr.yaml` —
  `{canonical, variants: [...], domain: football|generic, source: corpus_freq>=N}`.
  Built via `make nlp.transliteration-build` from a frequency-curated TR football
  corpus + manual curation. Each variant is a primary alias in the lexicon; canonical
  is the resolution target. Bypasses Symspell entirely (deterministic table lookup
  is cheaper and more accurate for known variants).
- [ ] **AST guard `test_nlp_loanword_variants_dont_collide_across_domains`** —
  *"sayı"* is a Turkish word, not a transliteration of English *"si"*; build refuses
  if a variant string is also a TR top-1k frequency word in a different sense. Closed
  override file `_loanword_overrides.tr.yaml` for hand-arbitrated cases (e.g.
  *"set"* is both English *"set"* (volleyball) and TR *"set"* (collection); both
  uses retained, disambiguated by §10.5 co-token context).
- [ ] **Proof tests.** ≥ 40-row golden `loanword_corpus.tr.json` with 4-8 variants
  per canonical for football terms; 100% gate.

#### 10.28.6 Fragment / incomplete-sentence detection

- [ ] **Real bug.** Users hit Send by mistake or autocorrect drops the last word:
  *"Galatasaray ve"* (hanging conjunction), *"için"* (dangling postposition only),
  *"Beşiktaş maçı"* (subject only, no question). §10.24.13 handles single-char /
  empty / pure-greeting; this slice handles **structurally incomplete** fragments
  that have ≥ 2 tokens but no predicate.
- [ ] **`ai/nlp/lang_tr/fragments/`** — closed structural-pattern detector:
  *(a)* trailing conjunction (`ve, ile, veya, ya da, ama, fakat`); *(b)* trailing
  postposition (`için, gibi, kadar, ile, üzerine`); *(c)* missing verb particle
  (no question particle, no verb root, no inflected predicate); *(d)* nominal-only
  with no inflected suffix. Detection via Zemberek POS-tag tail check (pure
  `_NN_TRAILING / _CC_TRAILING / _PP_TRAILING` enums; AST guard `test_nlp_fragment_detector_uses_zemberek_only`
  rejects regex-based heuristics).
- [ ] **Routing.** Fragment → closed `meta.fragment_detected.<locale>.j2` template
  ("Sorduğunuz şey eksik kalmış görünüyor; tahmin mi, skor mu, kadro mu istiyorsunuz?")
  + entity hint of any partial canonical-resolved tokens ("Galatasaray"). NEVER guesses
  the missing predicate.
- [ ] **False-positive guard.** Closed allow-list for legitimate fragment-shaped
  queries that are actually complete in spoken TR (*"Galatasaray nasıl?"*, *"Skor?"*).
  Allow-list source: 30-row hand-curated `fragment_negative_corpus.tr.json`; CI
  100% pass-through.
- [ ] **Proof tests.** ≥ 25 fragment positives + 30 negative; FP rate ≤ 3%.

#### 10.28.7 Distractor-preamble stripping

- [ ] **Real bug.** Voice / paste / mobile users routinely prepend distractor
  preambles before the actual question: *"merhaba arkadaşlar bakın bence Galatasaray
  bu hafta kazanır mı?"*. §10.24.13 handles *pure* greetings (no payload after);
  doesn't strip a greeting / vocative preamble before a real question. Result:
  classifier confidence drops because the prefix dilutes the intent signal.
- [ ] **`preamble_strippers.tr.yaml`** — closed phrase set (≤ 200 entries):
  greeting families (`merhaba|selam|slm|meraba|kolay gelsin|iyi günler`),
  attention-grab (`bakın|baksanıza|bak ya|ya|şey|peki`), vocative
  (`arkadaşlar|hocam|abi|reis|kanka|dostum`), filler-opinion
  (`bence|bana göre|şahsen|valla|yani`). Each entry MUST be ≤ 3 tokens; longer
  phrases → REFUSE build (defends against poisoned-table attacks via overlong
  patterns).
- [ ] **New §10.1 step 6.7** `strip_preamble` AFTER ASR-filler strip (§10.26.2)
  BEFORE morphology. Cap = `nlp_preamble_max_strip_tokens=8` per query (defends
  against unbounded chained preambles); over-cap → emit
  `nlp.event.v1{kind=preamble_strip_capped}` and short-circuit.
- [ ] **Hard guard.** Never strip if the resulting tail has < 2 tokens (would
  collapse a vocative-only message to empty; §10.24.13 owns that path). AST
  `test_nlp_preamble_does_not_collapse_to_empty`.
- [ ] **Audit invariant.** Original full text preserved in spool / audit rows
  per §10.21.7 PII discipline; only the *classifier input* is the stripped form.
- [ ] **Proof tests.** ≥ 25-row corpus (preamble + real question pairs) — assert
  intent-confidence on the stripped form ≥ confidence on the raw form for ≥ 90% of
  the corpus (correctness signal); 10-row negative corpus where stripping must NOT
  fire (legitimate messages that begin with stripped-table words but use them as
  the entity, e.g. *"Selam'ın gol attığı maç"*).

#### 10.28.8 ALL-CAPS / shout normalization

- [ ] **Real bug.** *"GALATASARAY KAZANIR MI BU HAFTA?"* — fully valid TR question,
  but Symspell + Zemberek + lexicon all index lowercase forms; §10.1 step 4 lowers
  via the explicit Turkish-aware fold. The drop is silent. However, ALL-CAPS is
  *also a signal*: §10.5 entity disambiguation should not use Turkish capitalization
  as a weak entity-hint when the entire message is uppercase (everything looks like
  a proper noun — false positives explode).
- [ ] **`detect_all_caps(text) -> bool`** — ratio of uppercase letters to total
  letters ≥ `nlp_all_caps_threshold=0.85` AND total letters ≥ 4. Flag stored as
  `request_metadata.shout=true`. Pipeline behaviour: lowercase as normal (no change
  to §10.1 step 4); §10.5 capitalization-as-hint feature **disabled** when
  `shout=true` (entity resolution falls back to gazetteer + co-token only — same
  behaviour §10.26.2 voice path uses).
- [ ] **Telemetry.** `nlp_input_shout_total` counter; over-pressure
  (`shout_rate_per_subject > 0.5` over 5min, AND req_count ≥ 20) emits
  `nlp.alert.v1{kind=nlp_shout_rate_anomaly_per_subject, severity=warn}` debounced
  600s/subject. Tier-blind (per AGENTS.md monetization doctrine).
- [ ] **Output policy.** NEVER mirror shouting in the answer; templates are
  fixed-case. AST `test_nlp_template_renderer_does_not_propagate_shout` asserts no
  template branches on `shout`.
- [ ] **Proof tests.** ≥ 15-row corpus (clean shouts that should still resolve), ≥
  10-row negative (mostly-uppercase but punctuation-mixed must NOT trigger), ≥ 5-row
  edge cases (1-letter messages, no-letter messages must not divide-by-zero).

#### 10.28.9 Soft-g (`yumuşak g`) loss tolerance

- [ ] **Real bug.** TR `ğ` is hard to type on some IMEs / disappears in fast typing /
  is dropped by Latin transliteration tools: *"yaptıgını"* → *"yaptığını"*,
  *"degil"* → *"değil"*, *"sagol"* → *"sağol"*. Diacritic restoration (§10.3) covers
  the dotted-letter family but not the standalone `g↔ğ` swap (which §10.22.1
  weighting downplays as "low risk" — wrong for `ğ`-stem proper nouns where the
  difference is meaningful).
- [ ] **Closed `g_to_softg.tr.yaml`** — corpus-derived list of words where `g→ğ`
  swap produces a dictionary form (`degil→değil, dogru→doğru, agac→ağaç,
  yagmur→yağmur, sagol→sağol`). Build refuses if any entry's swap produces an
  ambiguous resolution (multiple canonicals); ambiguous cases go through
  context-disambiguation per §10.5.
- [ ] **Pipeline integration.** §10.1 step 6 (diacritic restore) extends with a
  dedicated `softg_restore` sub-pass keyed off this table; never folds blindly
  every `g`. Risk-weighted per §10.22.1 (`nlp_diacritic_softg_min_freq=500`).
- [ ] **Proof tests.** ≥ 30-row corpus; CI 100%; ≥ 15-row negative (words like
  *"gol"*, *"galatasaray"*, *"genç"* must NOT have `g→ğ` applied).

#### 10.28.10 Meta / rhetorical / non-answerable question routing

- [ ] **Real bug.** *"Sen ne biliyorsun ki?"*, *"yardım edebilir misin?"*,
  *"sen kimsin?"*, *"ne yaparsın?"* — these are not predict.* / data.* questions;
  they are meta-questions about the system. §10.4 closed enum has `meta.help`,
  `meta.unsupported`, `meta.adversarial` — under-utilised for the rhetorical
  / system-self questions class. Result: the rhetorical *"ne diyorsun lan?"*
  (rude rhetorical, NOT a request) routes to `data.h2h` (because of *"diyorsun"*)
  and produces a confidently wrong answer.
- [ ] **`meta_questions.tr.yaml`** — closed enumeration of rhetorical /
  system-self / non-answerable patterns split into 3 classes: `meta.system_self`
  (asking what the bot is / can do), `meta.rhetorical_dismissive` (rude rhetorical
  with no real intent), `meta.opinion_request` (asking the bot's opinion outside
  prediction; routed to a polite refusal — bot does not opine outside predict.*).
  Each entry is a fixed phrase or a closed Zemberek POS-pattern; AST rejects regex
  heuristics. Closed table size cap `nlp_meta_question_table_max=500`.
- [ ] **Routing override.** Detection happens AFTER §10.26.5 modality firewall but
  BEFORE intent classifier. Hit short-circuits to the matching `meta.*` template;
  classifier never sees the message (defends against "what do you think" leaking
  into `predict.*`).
- [ ] **Tier-blind.** Refusal templates are tier-blind (free + paid both get the
  polite refusal). AST `test_nlp_meta_questions_tier_blind`.
- [ ] **Proof tests.** ≥ 40-row golden across 3 classes; CI 100%; ≥ 15-row
  negative (genuine predict / data queries that contain meta-question-shaped
  fragments must NOT route to meta.*).

#### 10.28.11 Per-request CPU + memory budget enforcement

- [ ] **Real bug.** Worst-case combinatorial blow-up: §10.1 normalize + §10.3
  Symspell + §10.4 fastText + §10.5 Zemberek + CRF + §10.7 template render +
  §10.8 humanizer can stack, especially under §10.24.5 multi-subquery split (3
  subqueries × full pipeline). §10.0 timeout-chain inequality bounds wall-clock
  but does NOT bound CPU-seconds or RSS — a runaway query can pin a CPU core
  without exceeding wall-clock if the pod is contended.
- [ ] **`ai/nlp/runtime/budget.py`** — `RequestBudget` context manager:
  *(a)* `signal.setitimer(ITIMER_PROF, nlp_per_request_cpu_budget_ms / 1000)` on
  entry; SIGPROF handler raises `BudgetExceeded` (CPython only — AST guard
  `test_nlp_budget_signal_main_thread_only` rejects use under sub-thread); *(b)*
  `resource.setrlimit(RLIMIT_AS, current_rss + nlp_per_request_rss_budget_mb*1024**2)`
  on entry — process-wide cap raised on exit; *(c)* monotonic wall-clock check at
  every pipeline boundary as a backup.
- [ ] **Default budgets** (cfg-tunable). `nlp_per_request_cpu_budget_ms=200`
  (no humanizer) / `=800` (with humanizer); `nlp_per_request_rss_budget_mb=128`.
  Boot-time refuses if budgets are below `cfg.nlp_per_request_cpu_budget_min_ms=50`
  (defends against accidental zeroing).
- [ ] **Budget exhaustion → degraded path.** `BudgetExceeded` at any pipeline
  stage → fall-through to template-only with `degraded_reason=cpu_budget_exceeded`
  / `rss_budget_exceeded`; emits `nlp.alert.v1{kind=nlp_request_budget_exhausted,
  severity=warn}` debounced per stage 60s. NEVER returns 5xx (per §10.10
  graceful-degradation matrix invariant).
- [ ] **Subprocess discipline.** Humanizer (§10.25.11) runs in a subprocess
  already; subprocess inherits a separate `setrlimit` budget per spawn. Subprocess
  OOM → supervisor catches `BudgetExceeded` and treats as humanizer breaker open
  (§10.8 path, no new alert kind needed).
- [ ] **Proof tests.** *(a)* `test_nlp_runaway_normalize_cpu_budget_kicks` —
  inject a synthetic Symspell-pathological token; assert `BudgetExceeded` raised
  within `cpu_budget_ms × 1.5` (allows one pipeline step grace). *(b)*
  `test_nlp_rss_budget_kicks_on_lexicon_pathological_load` — synthetic 200MB
  allocation inside a normalize step; assert raised. *(c)* parametrized matrix
  covering 5 pipeline stages × 2 budget kinds (CPU / RSS) = 10 cases. *(d)*
  `test_nlp_budget_does_not_fire_on_clean_query` — 1000 representative clean
  queries, none exceed budget on a 2-vCPU container (CI gate, parametrised by
  `nlp_per_request_cpu_budget_ms`).

#### 10.28.12 Symspell / CRF hot-reload back-pressure

- [ ] **Real bug.** §10.21.2 specifies "Symspell rebuilt-not-mutated on swap" but
  doesn't bound *how many* concurrent rebuilds may run. A 6-file `nlp.lexicon-deploy`
  (§10.27.9) can fan out to 6 simultaneous Symspell rebuilds across pods; under
  high-QPS the rebuild pulls 50-200 MB transiently, racing the per-request RSS
  budget (§10.28.11). Result: false-positive RSS exhaustion alerts during a
  legitimate lexicon swap.
- [ ] **`nlp_lexicon_rebuild_concurrency_max=2`** — at most 2 of {teams, players,
  leagues, competitions, markets, dialects} may be rebuilding simultaneously per
  pod; remainder queue (FIFO; bounded queue cap `=8`; over-cap drops oldest +
  emits `nlp.alert.v1{kind=lexicon_rebuild_queue_overflow, severity=error}` —
  rare; means deploy cadence outpacing per-pod CPU budget).
- [ ] **Rebuild RSS reservation.** Each in-flight rebuild reserves
  `nlp_lexicon_rebuild_rss_reservation_mb=200` against the pod's `RLIMIT_AS`
  headroom; insufficient headroom → defer the rebuild (queue) and emit
  `nlp.event.v1{kind=lexicon_rebuild_deferred_for_rss}`. Defends §10.28.11 budget
  against the swap edge.
- [ ] **Per-request budget exception during swap.** Requests landing during an
  active rebuild get a one-time `nlp_per_request_rss_budget_swap_grace_mb=64`
  bonus on top of the normal budget, capped at `nlp_lexicon_swap_grace_s=120`
  window after the swap (§10.27.9 already gates the swap window). Cleanly avoids
  a flap of false `cpu_budget_exceeded` alerts during a normal deploy.
- [ ] **Proof tests.** *(a)* `test_nlp_lexicon_concurrent_rebuild_capped_at_two` —
  trigger 6 simultaneous rebuilds; assert at most 2 active, others queued. *(b)*
  `test_nlp_request_grace_during_lexicon_swap_window` — issue normal-load requests
  during a synthetic swap; assert no `cpu_budget_exceeded` fires.

#### 10.28.13 Cross-component classifier-vs-extractor confidence skew detector

- [ ] **Real bug.** §10.4 abstention floor + §10.5 entity ambiguity each fire
  independently. The pathological *both-confident-but-disagreeing* case has no
  guard: classifier says `predict.match_outcome` with conf=0.93 but extractor
  resolves zero `team` entities. Today: dispatcher emits a `disambiguation`
  answer, but no observability surfaces the silent contradiction → drift goes
  unnoticed across calibration cycles.
- [ ] **`SkewDetector`** in `nlp.dispatcher.v1`: per-decision compute
  `skew_score = max(0, intent_confidence - entity_coverage_ratio)` where
  `entity_coverage_ratio = (resolved_entity_kinds_required_by_intent /
  required_kinds)`. Required-kinds map per intent in
  `intent_required_entities.tr.yaml` (closed; CODEOWNER `nlp-curator`); e.g.
  `predict.match_outcome` requires `{team(2), kickoff_or_recent}`,
  `data.kickoff_time` requires `{team(2)}`, `meta.help` requires `{}` (no
  required kinds → skew always 0).
- [ ] **Telemetry only at v1.** Histogram `nlp_classifier_extractor_skew` per
  intent; rolling window `nlp_skew_window_s=600` p95 > `nlp_skew_alert_p95=0.4`
  on req_count ≥ 100 → `nlp.alert.v1{kind=nlp_classifier_extractor_skew_high,
  severity=warn}` debounced 600s/intent. NEVER changes routing decision at v1
  (would risk hard-coding a noisy gate); the dispatcher continues with
  disambiguation-fallback per §10.6. Forward-phase hook for Phase 5.x retraining
  loop to consume this signal.
- [ ] **Proof tests.** *(a)* `test_nlp_skew_detector_fires_on_synthetic_skew` —
  inject classifier_conf=0.95 + zero entities for `predict.*`; assert one alert
  after window. *(b)* `test_nlp_skew_detector_silent_on_meta_intents` —
  meta intents always 0 skew. *(c)* `test_nlp_skew_does_not_change_routing` —
  parametrised 50-row corpus; routing decisions identical with detector enabled
  vs disabled.

#### 10.28.14 Cross-phase contracts

- [ ] **Phase 4 (storage).** §10.28.4 PII redaction runs BEFORE storage of any
  audit / spool row; storage layer never sees raw TC kimlik / IBAN / phone.
  Boundary test (Phase 4 side): `test_storage_no_unredacted_tr_pii_at_rest`
  walks a synthetic day's audit rows and asserts zero raw matches against the
  TR-PII regex set.
- [ ] **Phase 5 (calibration).** Skew detector (§10.28.13) emits histogram
  consumed by Phase 5.x retraining trigger heuristic; not a hard dependency, no
  schema change at v1.
- [ ] **Phase 7 (sec layer).** TR-PII detector module (`tr_pii.py`) is
  cross-language single-source; Go sec layer imports the byte-equivalent port
  per §10.24.4 helper-sharing pattern. Boundary test asserts byte-parity on a
  200-row corpus across Python and Go drivers.
- [ ] **Phase 8 (patcher).** Patcher scope EXCLUDES `ai/nlp/lang_tr/spelling/`,
  `ai/nlp/lang_tr/loanwords/`, `ai/nlp/lang_tr/fragments/`,
  `ai/nlp/lang_tr/preamble_strippers.tr.yaml`,
  `ai/nlp/lang_tr/meta_questions.tr.yaml`,
  `ai/common/security/tr_pii.py` — orthographic and PII tables ship via human
  review; auto-patch could ship a regression that mis-classifies a real PII
  pattern as benign. Boundary test (Phase 8 side): patcher scope-registry walk.
- [ ] **Phase 9 (gateway).** Gateway honours the `request_metadata.shout`
  flag forwarded in `qa.intent.v1` for telemetry only; no header surface.
- [ ] **Phase 11 (compute).** §10.28.11 budget module is CPU-only; AST guard
  `test_nlp_budget_module_does_not_import_torch` re-asserts. The skew detector
  (§10.28.13) is also CPU-only.
- [ ] **Phase 12 (chaos).** New stubs:
  `chaos.tr-pii-flood` (assert TR-PII detector p99 latency < `nlp_tr_pii_p99_max_ms=15`
  under 200 RPS of PII-bearing input);
  `chaos.compound-flood` (assert §10.28.3 compound splitter does NOT exceed
  shared lookup budget under 1000 RPS of synthetic concatenated tokens);
  `chaos.lexicon-rebuild-storm` (6 simultaneous rebuilds + 200 RPS — assert
  zero false-positive `cpu_budget_exceeded` per §10.28.12 grace);
  `chaos.runaway-normalize` (synthetic Symspell-pathological corpus — assert
  100% caught by §10.28.11 CPU budget, zero pod OOMs).
- [ ] **Phase 13a (LeagueCatalog).** §10.28.1 consonant-alternation table
  build refuses if any LeagueCatalog stem ending in `{p,ç,t,k}` is missing a
  decision row. Forces explicit human curation when a new league lands.
- [ ] **Phase 14 (K8s).** No new probes; §10.28.11 budget exhaustion does NOT
  fail liveness (degraded path is graceful per §10.10). Readiness is unaffected.
- [ ] **Phase 16 (Emitter).** `LexiconStore` Protocol unchanged; new tables
  (`consonant_alternations`, `vowel_drop_stems`, `assimilation_pairs`,
  `loanword_variants`, `g_to_softg`, `meta_questions`, `preamble_strippers`,
  `intent_required_entities`) flow through the same Protocol.
- [ ] **Phase 19 (long-tail leagues).** All §10.28 tables grow additively per
  league; AST `test_nlp_no_per_league_branch` re-asserts on the new code surface.
- [ ] **Phase 20 (monetization).** All §10.28 paths are tier-blind (orthographic
  tolerance, PII redaction, fragment detection, preamble stripping, meta-question
  refusal, budget enforcement, skew detection — none gate on tier). Three
  explicit AST guards: `test_nlp_consonant_alternation_tier_blind`,
  `test_nlp_meta_question_tier_blind`, `test_nlp_request_budget_tier_blind`.

#### 10.28.15 Knob inventory + new event / alert kinds + DoD

- [ ] **~24 new cfg knobs** (additive, documented in `xops/env/.env.example`,
  Triangle-test extends): `nlp_compound_split_max_lookups_per_query=24`,
  `nlp_all_caps_threshold=0.85`, `nlp_diacritic_softg_min_freq=500`,
  `nlp_meta_question_table_max=500`, `nlp_preamble_max_strip_tokens=8`,
  `nlp_per_request_cpu_budget_ms=200`,
  `nlp_per_request_cpu_budget_humanize_ms=800`,
  `nlp_per_request_cpu_budget_min_ms=50`,
  `nlp_per_request_rss_budget_mb=128`,
  `nlp_lexicon_rebuild_concurrency_max=2`,
  `nlp_lexicon_rebuild_queue_max=8`,
  `nlp_lexicon_rebuild_rss_reservation_mb=200`,
  `nlp_per_request_rss_budget_swap_grace_mb=64`,
  `nlp_skew_window_s=600`, `nlp_skew_alert_p95=0.4`,
  `nlp_tr_pii_p99_max_ms=15`,
  plus 8 feature-flag toggles (`nlp_consonant_alternation_enabled=true`,
  `nlp_assimilation_fold_enabled=true`, `nlp_compound_split_enabled=true`,
  `nlp_tr_pii_redact_enabled=true`, `nlp_loanword_variants_enabled=true`,
  `nlp_fragment_detection_enabled=true`, `nlp_preamble_strip_enabled=true`,
  `nlp_meta_question_routing_enabled=true`).
- [ ] **New `nlp.event.v1` kinds**: `consonant_softening_repaired`,
  `vowel_drop_repaired`, `assimilation_folded`, `compound_word_split`,
  `loanword_variant_resolved`, `fragment_detected`, `preamble_strip_capped`,
  `softg_restored`, `meta_question_routed_<class>` (3 sub-kinds),
  `lexicon_rebuild_deferred_for_rss`.
- [ ] **New `nlp.alert.v1` kinds**: `nlp_pii_in_input_tc_kimlik`,
  `nlp_pii_in_input_iban`, `nlp_pii_in_input_phone`, `nlp_pii_in_input_plate`,
  `nlp_pii_in_input_vkn` (5 PII alert kinds, all warn-debounced per
  `(subject_key_sha8, kind)` 600s); `nlp_shout_rate_anomaly_per_subject` (warn);
  `lexicon_rebuild_queue_overflow` (error);
  `nlp_request_budget_exhausted` (warn, per-stage debounced);
  `nlp_classifier_extractor_skew_high` (warn, per-intent debounced).
- [ ] **~70 new proof tests** on top of §10.20+§10.21+§10.22+§10.23+§10.24+§10.25+§10.26+§10.27
  baseline; cumulative Phase 10 ≈ **535+ tests**. `make swarm.demo.nlp.full`
  extends ≤ 60s covering all 13 §10.28 paths (one positive + one negative per
  sub-section).
- [ ] **`make nlp.transliteration-build`** (NEW xops target) regenerates
  loanword-variants table; CI gate refuses PR diffs > 50 rows without
  `nlp-curator` CODEOWNER ack.
- [ ] **CODEOWNERS additions**: every new YAML under `ai/nlp/lang_tr/spelling/`,
  `ai/nlp/lang_tr/loanwords/`, `ai/nlp/lang_tr/fragments/`,
  `ai/nlp/lang_tr/preamble_strippers.tr.yaml`,
  `ai/nlp/lang_tr/meta_questions.tr.yaml`,
  `ai/nlp/lang_tr/intent_required_entities.tr.yaml`,
  `ai/common/security/tr_pii.py` requires `nlp-curator` (orthographic) +
  `nlp-compliance` (PII-related) reviewer. `make verify.nlp-codeowners`
  CI-gated.
- [ ] **Versioning.** `swarm` minor (or patch if no public surface change),
  `docs` minor in same commit. Chart compatibility block re-pinned (no new
  deps; pure-Python `signal` / `resource` / Zemberek already pinned).
- [ ] **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4 — every
  checkbox in §10.28.1–§10.28.15 flipped to `[x]` at landing, with the §10.20
  DoD item 26 also flipped.

### 10.29 Deep-morphology, telegraphic-input, and silent-failure floor (binding addendum)

> **Why this section exists.** §10.0–§10.28 hardened nine independent
> floors (integrity, TR-correctness, serving, completeness, lifecycle,
> morphology+modality, lifecycle+abuse+regulatory, authentic-Turkish).
> Tenth-pass review against real-world Turkish football queries
> surfaces a residual class of *confidently-wrong* cases: deep
> morphology beyond the rules already enumerated (geminate restoration,
> stem-vowel deletion, irregular pronoun datives, -nk → -ng softening),
> Turkish-football telegraphic style ("Galatasaray bugün?" with no
> question marker and no verb), coordinator-driven multi-fixture parses
> ("Galatasaray ya da Fenerbahçe"), gerund-vs-nominalisation ambiguity
> that flips the *subject* of the question, and three integrity gaps
> that nine passes missed. Each `[ ]` here is binding for Phase 10 DoD
> per §10.20 item 27 (added in this pass).

#### 10.29.1 Geminate restoration (Arabic/Persian-origin doubled consonants)

- [ ] **The problem.** Turkish single-stem stems borrowed from Arabic/Persian
  restore the dropped second consonant when a vowel-initial suffix attaches:
  `hak → hakkı` (right-acc), `sır → sırrı` (secret-acc), `his → hissi`
  (feeling-acc), `zan → zannı`, `şık → şıkkı`. Native speakers do this
  reflexively; ASCIIfication / Symspell / suffix-stripper currently treat
  `hakkı` as `hak+kı` (wrong: `kı` is not a Turkish suffix) → fall-through
  to typo correction → silent garbage.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/spelling/geminate_restoration.tr.yaml`
  — `{stem, doubled_form, source: arabic|persian|turkish, _meta:
  added_at_utc, min_corpus_appearances ≥ 3}`. New §10.1 step 8c
  `restore_geminate` AFTER §10.28.1 consonant-alternation, BEFORE typo
  correction. Symspell index gains both forms via `_xref` collapse to a
  single canonical id.
- [ ] **Build refusal.** `make verify.nlp-lexicons` AST-asserts every
  LeagueCatalog player surname ending in single `{p,t,k,c}` whose
  Arabic-origin form is geminate has an explicit decision row (`{stem,
  decision: geminate|invariant, source: human|corpus_majority}`).
- [ ] **Proof tests.** ≥30-row positive golden (hak→hakkı, sır→sırrı, his→
  hissi, zan→zannı, şık→şıkkı + every doubled-consonant LeagueCatalog
  surname); ≥15-row negative (gol→golü NOT gollü, top→topu NOT toppu);
  Hypothesis idempotency ≥500 (`restore_geminate(restore_geminate(x))
  == restore_geminate(x)`); cross-language byte-parity test against the
  Phase 7 Go sec layer (extracted single-source `tr_geminate.py` →
  ported to `server/internal/sec/tr_geminate.go`).

#### 10.29.2 Stem-final vowel deletion before suffix (`ünlü düşmesi`)

- [ ] **The problem.** Disyllabic stems with a high vowel in the second
  syllable drop that vowel before a vowel-initial suffix:
  `oğul → oğlu` (son-acc), `burun → burnu` (nose-acc), `ağız → ağzı`
  (mouth-acc), `omuz → omzu`, `karın → karnı`, `gönül → gönlü`,
  `boyun → boynu`. **Common in TR surnames** (Oğuz, Yağız, Yamaç) so
  hits LeagueCatalog. Distinct from §10.28.1 vowel-drop in that it is
  the *suffix-attachment* trigger, not a stem-internal alternation.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/spelling/vowel_drop_before_suffix.tr.yaml`
  — `{stem, dropped_form, suffix_classes: [acc,gen,dat,...]}`. Reuses
  §10.28.1 infrastructure but distinguished by `kind=before_suffix` enum.
  §10.5 entity extractor consults the table BEFORE gazetteer match so
  `Oğlu Mehmet'in` resolves to `Oğul Mehmet` (genitive) with explicit
  `entities[].morph={stem,dropped_vowel,suffix}` audit trail.
- [ ] **LeagueCatalog build refusal.** Any player/manager surname ending
  in `{Cl,Cn,Cr,Cz,Cm}` clusters where C is a stop must have a decision
  row (`drops|invariant`).
- [ ] **Proof tests.** 25-row positive + 10-row negative (gol→golü never
  drops; ev→evi never drops); LeagueCatalog-coverage assertion (every
  catalog surname matching the cluster pattern resolved); humanizer
  bypass test (humanizer must NOT rephrase `oğlu` back to `oğulu` —
  closed `meta.template.surface_morphology_invariant` lint rule).

#### 10.29.3 -nk → -ng softening (separate from generic -k → -ğ)

- [ ] **The problem.** Stems ending in `-nk` soften the `k` to `g` (not
  `ğ`) before vowel-initial suffix: `renk → rengi` (colour-acc), `ahenk
  → ahengi`, `çelenk → çelengi`. §10.28.1 generic k-softening rule
  produces `renk → renği` which is wrong — the spelling rule
  is specifically `nk → ng` (no breve). Misses today.
- [ ] **Fix.** Extend `consonant_alternations.tr.yaml` with `kind=nk_to_ng`
  branch keyed on the digraph; AST asserts the generic `-k → -ğ` branch
  fires only when the preceding character is NOT `n`.
- [ ] **Proof tests.** 12-row positive (5 catalog colours + 7 corpus
  words) + 8-row negative (`bank → bankı` NOT `bangı`; loanwords
  bypass); cross-language Go-side parity.

#### 10.29.4 Pronominal dative irregularity (`bana / sana / ona`)

- [ ] **The problem.** First/second-person/demonstrative pronouns have
  irregular dative forms: `ben → bana`, `sen → sana`, `o → ona`,
  `kim → kime` (regular but worth pinning), `bu → buna`, `şu → şuna`.
  Common in user opinion-framing: *"bana göre Galatasaray kazanır"*
  ("in my opinion Galatasaray wins"). Symspell currently treats `bana`
  as a typo of `bana?` lookups; sometimes resolves to a player surname
  with edit-distance 1 on a small lexicon → confidently wrong entity.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/morph/pronouns_irregular.tr.yaml`
  — full paradigm table (8 pronouns × 6 cases). New step 5.5 in §10.5
  entity extractor: `mark_pronouns` runs BEFORE gazetteer match;
  matched tokens annotated `kind=pronoun` and EXCLUDED from gazetteer +
  Symspell + CRF NER. AST guard `test_nlp_pronouns_skip_lexicon`
  rejects any code path that calls `lexicon.lookup(token)` after
  `pronoun_marked=True`.
- [ ] **Proof tests.** 48-row paradigm completeness (8 × 6); 20-row
  adversarial (every irregular dative paired with a similarly-spelled
  LeagueCatalog surname → assert pronoun wins); idempotency.

#### 10.29.5 Loanword plural-as-singular drift

- [ ] **The problem.** Turkish often borrows English/Italian plurals as
  singular and re-pluralises Turkish-style: `data → datalar`,
  `media → medyalar`, `link → linkler`, `mail → mailler`. Symspell may
  resolve `linkler` to `link + ler` (double-plural detection) and
  classifier sees a different token from the user's intent.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/loanwords/loan_singularisation.tr.yaml`
  — `{loan_form, accepted_plural, decision: singular|plural|both}`.
  Suffix stripper consults this BEFORE generic plural strip; matched
  tokens carry `morph.loan=true` to suppress §10.28.5
  transliteration-variant rewrite (which would over-fold).
- [ ] **Proof tests.** 30-row positive + 10-row negative; hot-reload
  proof; `_xref` build refusal on ambiguous decision.

#### 10.29.6 Verbal-noun gerund vs nominalisation ambiguity

- [ ] **The problem.** `-mak/-mek` (infinitive) vs `-ma/-me` (verbal
  noun) flips the **subject** of the question:
  - *"Galatasaray oynamak"* → "to play Galatasaray" (Galatasaray is the
    object — speaker plans to play AS Galatasaray, e.g. in a video game
    — should route to `meta.unsupported`).
  - *"Galatasaray'ın oynaması"* → "Galatasaray's playing" (Galatasaray
    is the subject — should route to `data.fixture_lookup`).
  - *"Galatasaray oynaması"* (missing genitive marker — common
    colloquial elision) → ambiguous, must offer disambiguation, NEVER
    silently pick.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/morph/verbal_nouns.tr.yaml`
  — recogniser table for the four surface forms (-mak/-mek/-ma/-me);
  combined with §10.5 entity-genitive marker detection produces a
  `subject_polarity ∈ {entity_subject, entity_object, ambiguous}` signal
  carried on `qa.intent.v1.entities[].syntactic_role`. Dispatcher
  routes ambiguous cases to disambiguation answer with explicit Turkish
  gloss ("Galatasaray'ın oynaması mı, yoksa Galatasaray oynamak mı?").
- [ ] **AST guard.** `test_nlp_verbal_noun_ambiguity_never_silently_resolved`
  rejects any §10.6 dispatcher branch that picks a single fixture when
  `subject_polarity == ambiguous`.
- [ ] **Proof tests.** 40-row corpus (10 entity-subject + 10
  entity-object + 20 ambiguous); 100% disambiguation-or-correct gate.

#### 10.29.7 Reduplicated-emphasis collapse

- [ ] **The problem.** Turkish emphasises adjectives by full-word
  repetition: *"yeşil yeşil"*, *"uzun uzun"*, *"kırmızı kırmızı"*. §10.24.2
  `collapse_repeated_chars` only handles intra-token char repeats
  (`evettttt → evet`), not whole-word repeats. Classifier may double-count
  features.
- [ ] **Fix.** New §10.1 step 7c `collapse_reduplication` AFTER 7a
  (intra-token) and BEFORE 7b (question split). Closed
  `ai/nlp/lang_tr/morph/reduplication_pairs.tr.yaml` whitelist (build
  refuses non-identical pairs and pairs that are not in the closed
  emphatic-adjective set — defends against legit phrases like *"maç
  maç"* meaning "match by match").
- [ ] **Proof tests.** 25-row positive + 15-row negative (`ev ev` →
  *home-by-home* NOT collapsed; `maç maç` → *match-by-match* preserved);
  hypothesis idempotency.

#### 10.29.8 Coordinator-driven multi-fixture parsing (`ya da / veya / ya … ya`)

- [ ] **The problem.** *"Galatasaray ya da Fenerbahçe kim kazanır?"* is a
  **two-fixture comparative**, not a single question. Today §10.6
  dispatcher picks first-found entity → confidently wrong fixture
  routing. Worse: *"Ya Galatasaray ya Fenerbahçe"* (correlative) is a
  three-token-window construction prior passes don't recognise.
- [ ] **Fix.** Closed `ai/nlp/lang_tr/morph/coordinating_particles.tr.yaml`
  — `{form: ya_da|veya|ya_X_ya|veyahut, polarity: disjunctive|inclusive}`.
  §10.24.5 split-questions step extends to recognise these as
  multi-entity boundaries (NOT sub-question boundaries — the question
  itself is one). §10.6 dispatcher emits a comparative intent
  (`predict.match_outcome.comparative`, NEW) routing to a multi-fixture
  fan-out with comparative aggregation template.
- [ ] **Wire schema additive.** `qa.intent.v1.intent_modifier ∈ {none,
  comparative, conditional}` (additive enum, default `none`); schema
  bumped 3→4 (additive).
- [ ] **Proof tests.** 35-row corpus (15 ya-da + 10 veya + 10
  correlative ya-X-ya); 100% routes to comparative path.

#### 10.29.9 Telegraphic-style intent inference (no question marker, no verb)

- [ ] **The problem.** Turkish football fans write telegraphically:
  *"Galatasaray bugün"* — no `?`, no verb, no `mı`. §10.4 abstention
  floor today routes this to `meta.help` ("did you mean?"). The user's
  intent is unambiguously `data.fixture_lookup` (entity + temporal
  entity + nothing else).
- [ ] **Fix.** New deterministic heuristic in §10.4 BEFORE classifier:
  `infer_telegraphic_intent(entities, intent_distribution) → intent | None`.
  Fires when ALL of:
  1. ≥1 high-confidence entity (gazetteer hit) of kind `team|player|
     league|competition`,
  2. ≥1 temporal entity (date / time / weekday),
  3. Token count ≤ `nlp_telegraphic_max_tokens=4`,
  4. No verb-form detected (Zemberek POS tag absent),
  5. No question marker AND no `mı/mi/mu/mü`.
  → routes to `data.fixture_lookup` with confidence stamped
  `confidence=0.65, reason=telegraphic_inference`. Closed config table
  `ai/nlp/lang_tr/intent_telegraphic.tr.yaml` per intent class enum
  (5 classes whitelisted: fixture_lookup / kickoff_time / standings /
  h2h / player_card_risk).
- [ ] **AST guard.** `test_nlp_telegraphic_inference_never_routes_predict`
  — telegraphic path EXCLUDES every `predict.*` intent (predictions
  require explicit user assent — *"tahmin"* / *"olur mu"* / *"kim
  kazanır"*). This is a tier-blind safety floor.
- [ ] **Proof tests.** 45-row corpus (3-token telegraphic / 4-token
  telegraphic / boundary cases — verb present cancels, missing temporal
  cancels, `mı` cancels); 0-row predict.* leak; ≥0.85 fixture-lookup
  recall on telegraphic slice; abstention floor still fires when ANY
  condition fails.

#### 10.29.10 Particle "ki" colloquial-vs-formal disambiguation

- [ ] **The problem.** §10.22.4 detached particle `ki` but treats every
  occurrence the same. Two distinct uses:
  - **Relative** (formal, comma-bound): *"Galatasaray kazandı, ki bu
    sürpriz"* — `ki` introduces a relative clause; should be stripped
    from intent classification (it's discourse glue, not lexical).
  - **Emphatic** (colloquial, sentence-final): *"Galatasaray kazandı ki!"*
    — `ki` is a polarity intensifier; should propagate as a polarity hint.
  Confusing them flips affirmative/exclamatory framing.
- [ ] **Fix.** Particle detacher gains context test: presence of comma
  immediately before/after `ki` → relative; sentence-final or
  exclamation-mark-bounded → emphatic. Closed
  `ai/nlp/lang_tr/spelling/ki_context.tr.yaml` for ambiguous cases
  (build-curated, not heuristic).
- [ ] **Proof tests.** 25-row positive (relative + emphatic) + 10-row
  ambiguous (must offer disambiguation OR fall through to most common
  reading with explicit `ki_disambiguation_low_confidence` event); 0
  silent picks on the ambiguous slice.

#### 10.29.11 Cross-language TR-normalize byte-parity gate (single-source contract)

- [ ] **The problem.** Phase 7 Go sec layer (`server/internal/sec/sanitize.go`)
  and Python NLP normalize (`ai/swarm/agents/nlp/normalize.py`) each
  reimplement Turkish lowercase, NFC, control-strip, etc. Cross-language
  byte-parity for `tr_pii.py` was added at §10.28.4, but the *normalize*
  pipeline itself was never byte-parity-gated. Real risk: a Turkish-i
  fold that produces different bytes on the two sides → identical user
  input is sanitized differently at the gateway vs the NLP intake →
  classifier sees different tokens than the sec gate inspected →
  injection bypass class.
- [ ] **Fix.** Single-source spec at
  `ai/common/text/tr_normalize_spec.json` (canonical step list, codepoint
  mappings, NFC discipline, length-cap order). Both Python and Go
  implementations carry SHA of the spec at boot; refuse boot on
  mismatch. NEW corpus-driven differential test:
  `test_tr_normalize_python_go_byte_parity` — 1000-row Turkish corpus
  (seed=2026, mix of clean / typo / homoglyph / leetspeak / shouting /
  ASCIIfied / NBSP-padded) → byte-identical output between the two
  implementations on every row. Failure = build break.
- [ ] **Spec versioning.** `tr_normalize_spec.json` carries
  `spec_version=1`; bumping requires both implementations updated in
  the same PR (CODEOWNERS = both Python and Go owners), CI gate refuses
  PRs that bump spec without touching both implementations.
- [ ] **Proof tests.** Round-trip property (`normalize(normalize(x)) ==
  normalize(x)` on both sides); empty-string / single-char / max-cap
  boundary tests; spec-SHA-mismatch boot-refuse test on both sides.

#### 10.29.12 Prediction-id determinism gate (independent of envelope HMAC)

- [ ] **The problem.** §10.21.8 envelope HMAC catches forged
  `predict.approved.v1` envelopes when the HMAC key is intact and
  protected. If the operator HMAC key leaks (compromised pod, dev key
  reused in prod), HMAC verification passes but the producer was the
  attacker. Prior passes had no second independent integrity gate.
- [ ] **Fix.** §5 specifies `prediction_id = sha256(match_id | market |
  request_id | calibration_version)` as deterministic. NLP receiver
  re-derives this from envelope fields and rejects when mismatched.
  Catches: (a) HMAC-key compromise where attacker-injected envelope
  carries forged match_id but reused prediction_id from a real
  prediction (cache poisoning); (b) bus-level replay where prediction_id
  was crafted with a different calibration_version than what the
  envelope claims.
- [ ] **Wire.** New cfg knob
  `nlp_predict_prediction_id_determinism_required ∈ {off, warn, enforce}`
  default `warn` at v1, `enforce` post-Phase-14. New `nlp.alert.v1`
  kind `predict_prediction_id_mismatch` (severity=critical, debounced
  per producer-pod since attack would be sustained). Mismatched
  envelope → drop + route to `predict.timeout` template (degraded
  graceful, no user surface change).
- [ ] **Proof tests.** Synthesise an envelope with valid HMAC but
  wrong prediction_id → assert (a) drop event, (b) critical alert
  fires, (c) user sees degraded answer not silent wrong answer;
  legitimate envelope passes silently.

#### 10.29.13 Pipeline-version monotonicity (cache.v1 + L0 cache safety)

- [ ] **The problem.** Cache key includes `pipeline_version` (§10.23.9).
  Operational rollback past a cached `pipeline_version=N` would cause
  `pipeline_version=N-1` pods to read cache entries the older code
  cannot interpret (additive-only doctrine protects schema, but
  cached *outputs* may have used templates / morphology rules that
  the older code lacks). Today the boot validator only checks
  `compatibility_matrix.json` quartet; doesn't pin pipeline_version
  monotonicity against the live cache.
- [ ] **Fix.** Boot probe writes `cache:nlp:pipeline_max_seen` (Redis
  key, MAX-update via Lua CAS); pods at boot refuse start if
  `cfg.nlp_pipeline_version < pipeline_max_seen` AND
  `cfg.nlp_allow_pipeline_downgrade=false` (default false). Operator
  override `make nlp.allow-downgrade VERSION=<n> TTL=<s>` for
  emergency rollback (sets a Redis key with TTL; bumps an
  audit + critical alert per pod that uses it).
- [ ] **L0 cache invariant.** L0 entry carries the writer pod's
  `pipeline_version`; reader rejects (treat as miss) when
  `cached_pv > self.pv`. Defends in-process against lazy rollouts
  where some pods are still on N+1 while others rolled back.
- [ ] **Proof tests.** Boot-refuse test on cache-newer-than-self;
  L0 reject-on-version-mismatch test; emergency-override audit test;
  Lua CAS race test (two pods racing to bump max-seen → exactly one
  observed value, no lost updates).

#### 10.29.14 Cross-phase additions

- [ ] **Phase 4 (R1 storage).** No schema impact. Audit walks of
  `match_normalized.audit_jsonb` get a NEW field
  `morph_decisions[]` (geminate / vowel-drop / pronoun) for forensic
  re-render fidelity (additive, nullable; existing rows unaffected).
- [ ] **Phase 5 (consensus).** No schema impact. New consumer test
  asserts predict.approved.v1 with mismatched prediction_id is
  rejected per §10.29.12 — but Phase 5 itself MUST keep emitting the
  current deterministic id (pre-existing requirement, re-asserted as
  AST guard `test_consensus_emits_deterministic_prediction_id`).
- [ ] **Phase 7 (sec).** Cross-language byte-parity gate per §10.29.11
  added to existing `test_sec_input_python_go_parity` family (which
  was a §10.28.4 PII-only gate; now covers full normalize spec).
  Boundary discipline unchanged — sec layer still does NOT call NLP
  morphology helpers.
- [ ] **Phase 8 (patcher).** Patcher EXCLUDES new tables under
  `ai/nlp/lang_tr/{spelling,morph,loanwords,intent_telegraphic,
  spelling/ki_context}/*.yaml` (orthographic + grammar tables ship
  via human review only — re-asserts §10.28.14 doctrine for the new
  files).
- [ ] **Phase 9 (gateway).** No new HTTP-surface change. Gateway
  honours additive `qa.intent.v1.intent_modifier` field via JSON
  passthrough only (no semantic decision at the API tier; NLP owns
  intent semantics). The `test_qa_intent_v1_schema_additive_only`
  Phase 9 forward gate is widened to validate the new enum values.
- [ ] **Phase 11 (compute).** Telegraphic-inference helper, geminate /
  vowel-drop / pronoun helpers all CPU-only — AST guard rejects
  CUDA/MPS imports under `ai/nlp/lang_tr/`.
- [ ] **Phase 12 (chaos).** New stubs: `chaos.tr-normalize-spec-drift`
  (mutate one byte in `tr_normalize_spec.json` → both implementations
  refuse boot), `chaos.predict-prediction-id-forgery` (inject envelope
  with forged prediction_id → asserted dropped + alert + degraded
  template), `chaos.pipeline-version-rollback` (pod with pv=N-1
  attempts boot when cache has pv=N entries → refuse), `chaos.telegraphic-flood`
  (1000 RPS telegraphic queries → assert no predict.* leak, p99 dispatch
  latency unchanged).
- [ ] **Phase 13a (LeagueCatalog).** Build refusal extends to include
  geminate-restoration and vowel-drop-before-suffix decision rows for
  every catalog player/manager surname; coverage test
  `test_league_catalog_morph_completeness`.
- [ ] **Phase 14 (K8s).** No new probes. Pipeline-version monotonicity
  check runs at boot (already inside readiness stage 1 per §10.21.9 —
  add validation step in same stage).
- [ ] **Phase 16 (Emitter).** `LexiconStore` Protocol unchanged; the 7
  new tables flow through unchanged (additive). Feed schema bumps
  follow §10.21.13 doctrine.
- [ ] **Phase 19 (long-tail leagues).** League-blind re-asserted: no
  per-league branch in any new code; AST guard `test_nlp_no_per_league_branch`
  walks the new modules.
- [ ] **Phase 20 (monetization).** Telegraphic inference, comparative
  intent, geminate restoration, pronoun bypass all tier-blind. 4 new
  explicit AST guards (one per feature) re-assert no `tier_id` branch.

#### 10.29.15 Knob inventory & wire additions

- [ ] **~16 new cfg knobs:** `nlp_telegraphic_max_tokens=4`,
  `nlp_telegraphic_min_entity_confidence=0.85`,
  `nlp_telegraphic_inference_enabled=true`,
  `nlp_geminate_restoration_enabled=true`,
  `nlp_vowel_drop_before_suffix_enabled=true`,
  `nlp_pronoun_lexicon_bypass_enabled=true`,
  `nlp_loanword_singularisation_enabled=true`,
  `nlp_verbal_noun_disambiguation_enabled=true`,
  `nlp_reduplication_collapse_enabled=true`,
  `nlp_coordinator_split_enabled=true`,
  `nlp_ki_context_disambiguation=true`,
  `nlp_predict_prediction_id_determinism_required=warn`,
  `nlp_pipeline_version=<int>` (single-source from chart),
  `nlp_allow_pipeline_downgrade=false`,
  `nlp_tr_normalize_spec_path`, `nlp_tr_normalize_spec_required=enforce`.
- [ ] **8 new `nlp.event.v1` kinds** (open enum per §8.16.2):
  `geminate_restored`, `vowel_dropped_before_suffix`,
  `pronoun_lexicon_bypassed`, `loanword_singularised`,
  `verbal_noun_disambiguation_offered`, `reduplication_collapsed`,
  `coordinator_split_applied`, `telegraphic_intent_inferred`,
  `ki_context_disambiguated`.
- [ ] **5 new `nlp.alert.v1` kinds** (debounced per §10.21.13 doctrine):
  `tr_normalize_spec_drift` (critical, refuse boot),
  `predict_prediction_id_mismatch` (critical, debounced 60s per
  producer-pod), `pipeline_version_downgrade_blocked` (critical),
  `pipeline_version_downgrade_emergency_override_used` (warn,
  per-override), `verbal_noun_ambiguity_rate_high` (warn, debounced 600s).
- [ ] **~50 new proof tests** on top of cumulative §10.0–§10.28
  ≈ 535+ → cumulative Phase 10 ≈ 585+ tests.
- [ ] **`make swarm.demo.nlp.full`** extends ≤ 60 s budget covering 6
  §10.29 paths (geminate, vowel-drop, pronoun, telegraphic,
  comparative, byte-parity).

#### 10.29.16 Definition of Done additions

- [ ] All `[ ]` items in §10.29.1–§10.29.15 ticked.
- [ ] §10.20 DoD item 27 added (this section's binding).
- [ ] CODEOWNERS updated: `ai/nlp/lang_tr/spelling/{geminate_restoration,
  ki_context}.tr.yaml`, `ai/nlp/lang_tr/morph/*.tr.yaml`,
  `ai/nlp/lang_tr/loanwords/loan_singularisation.tr.yaml`,
  `ai/nlp/lang_tr/intent_telegraphic.tr.yaml`,
  `ai/common/text/tr_normalize_spec.json` require `nlp-curator`
  (orthographic / grammar) reviewer; `tr_normalize_spec.json` *also*
  requires Go owner (cross-language single-source). `make
  verify.nlp-codeowners` CI-gated.
- [ ] **Versioning.** `swarm` patch (no public surface change beyond
  additive intent_modifier enum); `docs` minor in same commit. Chart
  compatibility block re-pinned (no new deps; `signal` / `resource` /
  Zemberek already pinned at §10.21).
- [ ] **Tracker row + ROADMAP checkbox flips** per AGENTS.md §3 + §3.4
  — every checkbox in §10.29.1–§10.29.16 flipped to `[x]` at landing,
  with §10.20 DoD item 27 also flipped.

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
