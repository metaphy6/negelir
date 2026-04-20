# 🗺️ Negelir — Master Roadmap (Swarm Pivot Edition)

> **Version:** 2.0.0 — *Swarm Pivot*
> **Date:** 2026-04-19
> **Status:** Active. Single source of truth.
> **Supersedes:** all prior `ROADMAP.md`, `MULTI_LEAGUE_ROADMAP.md`, `IMPLEMENTATION_ROADMAP.md`, `REFACTORING_ROADMAP.md`, `FEASIBILITY.md`, and any P2P planning doc. **Those documents have been deleted; this is what remains.**

---

## 📜 Pivot Summary

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
| **13** | Multi-League Preset Expansion | Pre-configured `LeagueConfig` presets for top European leagues + cups (architecture is already league-agnostic from Phase 4) | 4 |
| **14** | Cloud-Ready Packaging | Docker → K8s manifests, CSP-agnostic | 9 |
| **15** | Frontend Handoff (Flutter) | API contract frozen, sample client | 9 |

```
0 ─→ 1 ─→ 2 ─→ 3 ─→ 4 ─→ 5 ─→ 6 ─→ 9 ─→ 14 ─→ 15
                          ├─→ 7 ─┤
                          ├─→ 8 ─┤
                          ├─→ 10 ┤
                          ├─→ 11 ┤
                          └─→ 12 ┘
                          │
                          └─→ 13 (parallel)
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
- [ ] CI gate: `pytest xops/versioning/tests/` runs as part of `make test`. *(Today these tests pass standalone; wiring them into the default `make test` target is part of the Phase 1 lint/CI sweep.)*

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
- [x] Strict mode (`NEGELIR_STRICT=1`) refuses unknown env keys with the `NEGELIR_` / `SCRAPE_` / `P2P_` prefixes (the latter only to error loudly if someone re-introduces them).

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

### 2.1 Topology

```
       /etc/hosts (managed by `make hosts-install`)
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

`make hosts-install` adds:

```
127.0.0.1   mackolik.local nesine.local tff.local openfootball.local
```

> ⚠️ Uses `.local` TLDs to avoid colliding with real DNS. The scraper config flips between
> real and mock by an env switch (`NEGELIR_SCRAPE_PROFILE=real|mock`); no code changes.

`make hosts-uninstall` cleanly removes them. Both targets are **idempotent** and bail out with a clear message if `/etc/hosts` is not writable, suggesting `sudo`.

### 2.4 Seed corpus

- [x] `infra/mock/seeds/` holds **frozen** captures: `*.html`, `*.json`, response headers (sibling `<file>.headers.json`), status codes. Seeded for all 4 sources on 2026-04-20.
- [x] `xops/mock/capture_engine.py` + `xops/makefile/mock.py::capture` perform rate-limited captures (1.5s inter-request delay; only declared paths, no crawling). Agent-runnable per AGENTS.md §2 #10; only git ops remain AI-restricted.
- [x] nginx serves seeds via `mocksrv` upstream (manifest-keyed `(host, path)` routing; `try_files`-style exact-match — no lua needed since mocksrv handles path logic in Go).
- [x] `infra/mock/seeds/manifest.json` records per entry: source URL, capture date, sha256, byte size, status, content_type. Re-generated atomically by `capture_all()`.

### 2.5 Integrity guarantees

- [x] `xops/mock/verify.py` re-hashes every seed and compares to `manifest.json`. Now wired into `make test` via `xops/makefile/tests.py` (runs alongside AI + swarm + versioning suites).
- [x] **Property test:** `xops/mock/tests/test_manifest_contract.py` parametrizes over every manifest entry and asserts (a) payload file exists, (b) sha256 matches, (c) byte count matches, (d) extension matches `content_type`, (e) every registered source in `xops/mock/sources.py` has at least one seed.

### 2.6 Makefile UX

```
make mock-up           # bring up nginx-mock + seeded postgres
make mock-down         # tear down
make hosts-install     # write /etc/hosts entries (sudo)
make hosts-uninstall   # remove them
make mock-ca-trust     # rebuild & re-trust CA inside agent images
make mock-capture      # ⚠️ hits the real internet, refreshes seeds
make mock-verify       # offline integrity check
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

### 3.1 Message bus

- [ ] **Local / small prod:** Redis Streams (already in stack). Topics are stream keys; consumer groups give per-agent durability.
- [ ] **Large prod (future):** drop-in NATS JetStream — the SDK exposes a `Bus` interface; Redis and NATS are two implementations.
- [ ] All messages are **CBOR-encoded** with a strict schema (`schemas/*.cddl`). JSON kept only for human debugging.

### 3.2 Agent SDK

`ai/swarm/sdk/` (Python) and `server/internal/swarm/` (Go) expose an identical contract:

```python
class Agent(Protocol):
    name: str                      # e.g. "scraper.mackolik.v1"
    subscribes: list[Topic]        # topics this agent consumes
    publishes:  list[Topic]        # topics it produces (declared up-front)
    async def handle(msg: Message) -> Iterable[Message]: ...
```

- [ ] Auto-registers in `agent_registry` Redis hash on start; deregisters on `SIGTERM`.
- [ ] Heartbeat every `cfg.swarm_heartbeat_sec`; supervisor marks dead after `3×` missed beats.
- [ ] Built-in metrics: `msg_consumed`, `msg_published`, `errors`, `latency_ms` (Prometheus-format `/metrics`).
- [ ] Built-in tracing: every message carries a `trace_id`; agents span-wrap their `handle`.

### 3.3 Supervisor

A tiny Go binary `cmd/swarmctl`:

- [ ] `swarmctl ps` — list registered agents, last heartbeat, message lag.
- [ ] `swarmctl restart <name>` — safe restart through the orchestrator.
- [ ] `swarmctl scale <name> <n>` — change desired replica count (writes to `agent_desired_state` hash; docker-compose `--scale` or K8s deployment patches react).
- [ ] `swarmctl drain <name>` — stop assigning work but let in-flight messages finish.

### 3.4 Topic catalog

| Topic prefix | Producer | Consumer(s) | Payload |
|---|---|---|---|
| `scrape.request` | API gateway, scheduler | scrapers | `{league, source, target_date}` |
| `scrape.raw` | scrapers | categorizer | `{source, url, payload, sha256}` |
| `match.normalized` | processor | predictor, storage | canonical `Match` record |
| `predict.request` | API gateway | predictor swarm | `{match_id, market}` |
| `predict.vote` | individual predictors | consensus agent | `{match_id, market, dist, model_id}` |
| `predict.final` | consensus | proofreader, storage, API cache | calibrated `Prediction` |
| `proof.flag` | proofreader | drift, security | `{prediction_id, reason}` |
| `sec.alert` | security agents | supervisor, telemetry | `{kind, source, severity}` |
| `maint.event` | self-maint | supervisor | `{kind, target, action}` |

### 3.5 Definition-of-Done for Phase 3

- [ ] A trivial echo-agent (`agents/examples/echo.py`) starts in compose, registers, processes 1000 messages without leak.
- [ ] `swarmctl ps` shows all running agents with green heartbeats.
- [ ] Bus implementation can be swapped to a stub (`InMemoryBus`) for unit tests with no agent code change.

---

## 🛠️ Phase 4 — Core Worker Agents (Scrape → Categorize → Process → Store)

**Goal:** A clean linear pipeline of small, replaceable agents that turn a scrape request into a normalized `Match` row in Postgres.
**Depends on:** Phase 2, Phase 3

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

### 4.7 Definition of Done

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

### 8.3 Auto-coder agent (`maint.coder.v1`) — *opt-in, isolated*

- [ ] **Disabled by default.** Enable with `NEGELIR_AUTOCODER=1`.
- [ ] Scope: only `scraper/parsers/*.py`, only against `proof.flag{kind:parse_failed}` cases the schema-healer couldn't fix.
- [ ] Generates a candidate patch using a small local code-LLM (e.g. `qwen2.5-coder-1.5b` or `starcoder2-3b`) on the GPU.
- [ ] Patch is tested in a sandboxed container against the failing seed; only commits if **(a)** the new test passes, **(b)** the existing test suite still passes, **(c)** the diff stays under `cfg.autocoder_max_diff_lines`.
- [ ] Always opens a PR — never pushes to main directly.

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

## 🌍 Phase 13 — Multi-League Preset Expansion

**Goal:** Ship pre-tuned `LeagueConfig` presets for the top European leagues and major cups. The architecture is **already league-agnostic** — every agent in Phases 4–12 reads `LeagueConfig` rather than hardcoding any league. This phase only adds *data* (presets, calibration tables, lexicons), not code branches.
**Depends on:** Phase 4

> ℹ️ The seeded default since v2.0.0 is the **Turkish Süper Lig** (`tr_super_lig`, alias `super_lig`). Presets below are added as new entries in `ai/common/league_config.py::LEAGUE_CONFIGS`; no scraper / predictor / proofreader code changes.

### 13.1 League preset roster (initial)

- [x] 🇹🇷 Süper Lig — *seeded default since v2.0.0*
- [ ] 🇬🇧 Premier League
- [ ] 🇪🇸 La Liga
- [ ] 🇩🇪 Bundesliga
- [ ] 🇮🇹 Serie A
- [ ] 🇫🇷 Ligue 1
- [ ] 🇪🇺 Champions League (knockout) — knockout-aware features

### 13.2 LeagueConfig hardening

- [ ] Per-league: home-advantage Elo, Dixon-Coles ρ, calibration table, lexicon overrides.
- [ ] Aliases (`super_lig` → `tr_super_lig`) preserved.
- [ ] Per-source URL templates live in `LeagueConfig.scrape_endpoints` (already partially modelled today via `openfootball_path` / `footballdata_country`).

### 13.3 NLP per league

- [ ] Foreign team names get TR transliteration: "Real Madrid" → "Real Madrid", "Bayern" → "Bayern Münih" with both forms accepted on input.
- [ ] Entity extraction lexicons are *per league*, merged at runtime.

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

---

## 📒 Appendix B — Definition of Done (Per Phase)

Every phase ships only when **all** of the following are true:

1. ✅ All checkbox items in the phase are checked.
2. ✅ A new section in `docs/design/` (or update of one) exists for any architectural choice.
3. ✅ `make test` is green on a fresh clone, including any new adversarial / chaos tests.
4. ✅ `make lint` is green (`no_magic.py`, `ruff`, `mypy --strict` for new modules, `golangci-lint`).
5. ✅ `make up-dev` brings the system up and a smoke script (`make smoke`) passes.
6. ✅ The phase has a one-paragraph entry added to `CHANGELOG.md` (under "Unreleased") describing the user-visible delta.
7. ✅ No new env var exists that is undocumented in `.env.example`.
8. ✅ No new agent exists without a `README.md` describing topics, schema, model size, device requirements.

> 🎯 **Mantra:** *Small agents. Real data. Centralized config. Containerized always. Turkish out, English in.*
