<!-- 
  last_verified_against_code: 2026-06-15
  This document was last verified to be accurate against the live codebase on the above date.
  See ROADMAP.md Phase 18.8 for staleness policy.
-->
# Component Layout — Production Pivot v3

> **Status:** Canonical. This doc defines **what lives where** after the
> Production Pivot. Supersedes the implicit layout described in
> `ROADMAP.md` v2.0.0.
> **Audience:** Anyone touching directory structure, compose, or CI.
> **Doctrine:** AGENTS.md §2 rules 1, 2, 5.
> **Sibling docs:** [`DATA_SOURCE.md`](DATA_SOURCE.md),
> [`EMITTER.md`](EMITTER.md), [`SCRAPER_PATCHER.md`](SCRAPER_PATCHER.md),
> [`SWARM.md`](SWARM.md), [`DATA_PIPELINE.md`](DATA_PIPELINE.md).

Before Production Pivot v3 the repository had two first-class
top-level components: `ai/` (everything that wasn't Go) and `server/`
(the Go API). The Mock-Data Dev Stack and the Source-Watcher Agent
accreted inside `ai/`. That worked through Phase 2 but three things
broke down as we approached Phase 3+:

1. **Concern mixing.** The AI swarm had to know how scraping worked.
2. **Dev vs prod asymmetry.** The mock stack looked like "dev-only
   scaffolding" instead of a first-class production capability.
3. **Growing feature surface inside `ai/`.** Source-watcher, a future
   content-refresher, a future auto-patcher — all colocated with
   predictors.

This pivot separates concerns into **four top-level components**.

---

## 1. The four components

```
negelir/
├── server/          ── single Go binary, three run modes
│   ├── api          (Flutter-facing REST, public)
│   ├── internal     (swarm-facing RPC, private VPC)
│   └── mock         (serves mock vhosts — replaces old mocksrv)
│
├── datasource/      ── worker group (Python) that OWNS the data
│   ├── scraper      (fetches bytes from real or mock upstreams)
│   ├── watcher      (schema-drift detector; today's source-watcher)
│   ├── refresher    (per-Record change detection; CONTENT_FRESHNESS agent)
│   ├── patcher      (AI auto-patcher; edits code + schema + migrations)
│   ├── gitops       (GitHub PR driver + 7-day auto-merge policy)
│   └── emitter      (serializes DB/Redis → AI-ready feed files)
│
├── swarm/           ── AI consumers only; no scraping concerns
│   ├── predictors/
│   ├── proofreaders/
│   ├── drift/
│   ├── defense/
│   ├── nlp/
│   └── reactors/    (freshness-event reactors; Phase 4.7)
│
└── common/          ── shared libraries (config, schemas, bus SDK)
    ├── config       (Python + Go mirror)
    ├── schemas      (Record envelope, feed manifests, bus messages)
    └── bus          (Redis Streams / NATS adapter)
```

Each top-level is:

- Its own directory tree with its own `requirements.txt` or `go.mod`.
- Its own container image.
- Its own entry in [`xops/versioning/chart.json`](../../xops/versioning/chart.json).
- Its own compose profile (see §4).
- Its own tests (mostly) — cross-component tests live in `common/`.

---

## 2. Responsibility matrix

| Concern | Owner | Does NOT own |
|---|---|---|
| Public REST for Flutter clients | `server` (mode=api) | Any scraping, any ML inference |
| Data access endpoints for swarm agents | `server` (mode=internal) | Writes to the data tables |
| Serving mock websites for dev/CI/validation | `server` (mode=mock) | Anything other than bytes from `infra/mock/seeds/` |
| Fetching bytes from upstreams | `datasource/scraper` | Parsing / normalization (delegates to extractors) |
| Detecting source structural drift | `datasource/watcher` | Emitting freshness events |
| Detecting per-Record content change | `datasource/refresher` | Structural concerns |
| Editing Python / SQL / extractor code in response to parse failures | `datasource/patcher` | Any write to main branch (delegates to `gitops`) |
| Opening / reviewing / merging PRs | `datasource/gitops` | Producing diffs (delegates to `patcher`) |
| Projecting Postgres + Redis state into **feeds** the swarm consumes | `datasource/emitter` | Any read outside the project's own DB |
| Running ML models for prediction | `swarm/predictors` | Knowing where the data came from |
| Turkish-language user-facing answer generation | `swarm/nlp` | Scraping, normalization |
| Prompt-injection / abuse defense | `swarm/defense` | Enforcing rate-limits at the HTTP layer (that's `server/api`) |

The pivot rule in one line: **`datasource` produces, `swarm` consumes,
`server` exposes.** No component crosses that boundary.

---

## 3. What moves where — Phase 22 Final Flat Root Layout

After Phase 22, all Python packages live at the repo root with no intermediate
folders. The structure is:

- `server/` — Go REST API + mock server (unchanged)
- `scraper/` — Data ingestion (previously `datasource/scraper/`)
- `datasource_watcher/` — Schema drift detection (previously `datasource/watcher/`)
- `refresher/` — Content freshness agent (previously `datasource/refresher/`)
- `patcher/` — Auto-patcher (previously `datasource/patcher/`)
- `gitops/` — PR driver + merge policy (previously `datasource/gitops/`)
- `emitter/` — Feed projector (previously `datasource/emitter/`)
- `pipeline/` — Ingestion orchestration (previously `datasource/pipeline/`)
- `qid/` — QID collector (previously `datasource/qid/`)
- `proofreader/` — Scrape-time validator (previously `datasource/proofreader/`)
- `swarm/` — AI agents + predictors + NLP (moved from `ai/swarm/`)
- `common/` — Shared libraries (moved from `ai/common/`)
- `nlp/` — Turkish language pipeline (previously `swarm/nlp/`)
- `tqu/` — Turkish NLP utilities (previously `swarm/nlp/tqu/`)
- `trc/` — Response composer (previously `swarm/trc/`)
- `orchestrator/` — Swarm state machine (previously `swarm/orchestrator/`)
- `model/` — Predictors (previously `swarm/predictors/`)
- `reactors/` — Reactor SDK (previously `swarm/reactors/`)

All imports use `PYTHONPATH=.` (set in Dockerfile). The intermediate
`ai/`, `datasource/`, and `ai/datasource/` folders are deleted.

---

## 4. Compose profiles

Single `docker-compose.yml`. Every service declares a
`profiles:` key. No overlay files.

| Profile | Services brought up | Use case |
|---|---|---|
| `core` | `postgres`, `redis` | Skeleton for everything else |
| `server` | + `server-api` | Public REST for Flutter |
| `internal` | + `server-internal` | RPC surface for swarm |
| `mock` | + `server-mock`, `nginx-mock` | Fake internet for dev / CI / scraper-patcher validation |
| `datasource` | + `scraper`, `watcher`, `refresher`, `emitter` | The ingestion pipeline |
| `patcher` | + `patcher`, `gitops` | Auto-patching surface (opt-in; has access to GitHub token) |
| `swarm` | + `swarm-*` | All AI consumers |
| `observability` | + `prometheus`, `grafana`, `loki` | Telemetry stack |
| `all` | everything above | Laptop-scale "bring the whole thing up" |

Invocation:

```bash
make up PROFILES=core,server,datasource,swarm   # typical prod
make up PROFILES=core,mock,datasource,patcher   # patcher dev-loop
make up PROFILES=all                            # kitchen-sink
```

The `make up` target defaults to `core,server,swarm` (a reasonable
minimum). `PROFILES=` overrides. See [DATA_SOURCE.md §5](DATA_SOURCE.md#5-compose-profiles).

---

## 5. Versioning chart (Phase 22 Final State)

After Phase 22, the versioning chart reflects the flat root layout. Each
package at the root level has its own SemVer entry:

| Chart key | Role | Starts at | Notes |
|---|---|---|---|
| `server` | Go REST API + mock | current | unchanged |
| `scraper` | Data ingestion | 1.0.0 | moved to root |
| `datasource_watcher` | Schema drift detector | from v2 | moved to root |
| `refresher` | Content-freshness agent | 0.1.0 | moved to root |
| `patcher` | Auto-patcher | 0.1.0 | moved to root |
| `gitops` | PR driver | 0.1.0 | moved to root |
| `emitter` | Feed projector | 0.1.0 | moved to root |
| `swarm` | AI agents + predictors | 1.0.0 | moved to root |
| `common` | Shared libraries | 0.1.0 | moved to root |
| `infra_mock` | unchanged | current | retains history |
| `docs` | Documentation | varies | tracks design doc updates |
| `xops` | Repo automation | varies | tracks tooling updates |

The flat root layout is the final state. No further migrations planned.

---

## 6. Data-flow guarantee (pictorial)

```
 ┌───────────────────────┐     ┌──────────────────────────────┐
 │ EXTERNAL / MOCK SITES │◄────┤ datasource/scraper           │
 │ mackolik · nesine · …│     │  (bytes → raw capture)       │
 └───────────────────────┘     └───────────────┬──────────────┘
                                               │ raw bytes
                                               ▼
                               ┌──────────────────────────────┐
                               │ datasource/pipeline          │
                               │  extract → normalize → store │
                               └───────────────┬──────────────┘
                                               │ Records (DATA_PIPELINE §4)
                                               ▼
                                      ┌──────────────────┐
                                      │   postgres       │
                                      │   redis          │
                                      └─────────┬────────┘
                                                │ SELECT / XREAD
                                                ▼
                                ┌────────────────────────────────┐
                                │ datasource/emitter             │
                                │ DB state → NDJSON (live)       │
                                │          → Parquet (snapshots) │
                                └───────────────┬────────────────┘
                                                │ files on disk / S3
                                                ▼
 ┌───────────────────────┐     ┌────────────────────────────────┐
 │ datasource/watcher    │     │  swarm/* (predictors, nlp, …) │
 │ datasource/refresher  │     │  consume feeds ONLY            │
 │ datasource/patcher    │◄────┤                                │
 │ datasource/gitops     │     │                                │
 └───────────────────────┘     └────────────────────────────────┘
                                                │
                                                ▼
                               ┌────────────────────────────────┐
                               │  server (api / internal / mock)│
                               │  publishes predictions         │
                               └────────────────────────────────┘
```

Invariants:

1. `swarm/*` **only reads feed files** and **only writes back through
   `server/internal`**. It never opens a Postgres connection, never
   calls a scraper, never decides if a Record "changed."
2. `datasource/*` **only writes DB/Redis + feeds**. It never serves
   HTTP to clients. It never runs a predictor.
3. `server/*` **only serves HTTP**. It holds no state beyond its own
   token / session caches.

These three invariants are enforced by three CI tests:

- `common/tests/test_swarm_isolation.py` — asserts no file under
  `swarm/` imports `psycopg` / `requests` / `datasource.*`.
- `common/tests/test_datasource_isolation.py` — no file under
  `datasource/` imports `fastapi` / `flask` / `swarm.*`.
- `common/tests/test_server_isolation.py` — no file under `server/`
  contains `XGBoost` / `torch` imports (Go only).

> **Implementation note.** The Python isolation tests use **AST-based
> import-graph analysis** (`ast.walk` over each component's `*.py`,
> collecting `Import` / `ImportFrom` nodes and checking against an
> explicit per-component allow-list), not naïve `grep`. Grep is too
> brittle here: `common/bus/` legitimately depends on Redis, and
> several `swarm/` agents legitimately import `common.bus.*` —
> distinctions that string matching cannot make. The Go isolation
> test (`server/`) uses `go list -deps` to walk module imports
> rather than grepping source.

---

## 7. Migration safety — Phase 22 Flat Root Layout

The Phase 22 migration is the **final** relocation. It consolidates the entire
Python codebase to the repo root in a single coordinated move:

- All `datasource/*` packages move to `<package>/` at root
- All `swarm/*` packages move to `<package>/` at root
- All `common/*` packages move to `<package>/` at root
- The `ai/` tree is deleted entirely
- All imports rewritten to `PYTHONPATH=.`
- The layout is now **frozen** — no further root-level migrations

The migration is verified by:

1. **Isolation gates:** `make isolation.check --full` passes (Phase 18 enforcement)
2. **Import sweep:** No `ai.*` or `datasource.*` imports remain (test_22_13_no_ai_import_anywhere.py)
3. **Documentation:** No backtick `ai/` paths in docs (test_22_12_roadmap_no_ai_path_backtick_references.py)
4. **Phase ledger:** All present phase-ledger lints pass after path updates
5. **30-day burn-in:** Zero regressions for 30 calendar days post-merge (Phase 22.13)

Once Phase 22 lands, the flat root layout is the canonical architecture.
Phases 18, 19, 21 ship under the transitional layout; Phase 17 ships natively
on the flat root layout after Phase 22 completes.

---

## 8. Open questions (deferred to the phases that own them)

- **Emitter storage backend.** Local disk is the Phase R3 default.
  S3-compatible object store (MinIO in dev, Azure Blob / AWS S3 in
  prod) is the Phase 14 extension. Covered in [EMITTER.md §7](EMITTER.md#7-storage-and-retention).
- **Patcher LLM choice.** **Decided 2026-04-20.** The patcher uses
  the **Anthropic Agent SDK** with a tiered model harness (Haiku →
  Sonnet → Opus, deterministically routed by the patcher harness).
  See [SCRAPER_PATCHER.md §12](SCRAPER_PATCHER.md#12-model-providers-anthropic-agent-sdk)
  for the canonical design and ROADMAP Decision A15 for the carve-out
  to AGENTS.md §2 rule 4. The local-model alternative
  (qwen2.5-coder, deepseek-coder) is retained as a documented
  contingency only.
- **Inter-component wire format.** `datasource → server/internal`
  today goes over HTTP+JSON. Phase R3 may switch to gRPC+protobuf
  if latency budgets demand it; SWARM.md Phase 3 covers bus transport
  separately.
- **Namespace in Python imports.** `datasource.watcher` vs
  `negelir.datasource.watcher`. Phase R2 decides based on how we
  package for distribution. Today's AGENTS.md does not commit.
