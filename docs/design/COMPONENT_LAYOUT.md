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

## 3. What moves where

This is the exhaustive list of the Pivot v3 relocation. Everything
not on this list stays put.

### 3.1 Moving into `server/`

| Current path | New path | Notes |
|---|---|---|
| `server/cmd/api/` | `server/cmd/api/` | Unchanged. |
| `server/cmd/mocksrv/` | `server/cmd/mock/` | Rename binary `mocksrv` → `mock`. |
| *(new)* | `server/cmd/internal/` | New RPC surface for swarm agents; extracted from today's implicit `ai ↔ server` HTTP calls. |
| `server/internal/config/` | `server/internal/config/` | Unchanged; grows one new `Mode` value. |

Run mode flips via `-mode {api,internal,mock}` or `SERVER_MODE=`.
Config layer already supports this (Phase 1.2).

### 3.2 Moving into `datasource/`

| Current path | New path | Notes |
|---|---|---|
| `ai/scraper/` | `datasource/scraper/` | Full move, preserving the selectors/field_discovery/self_healing split. |
| `ai/swarm/source_watcher/` | `datasource/watcher/` | Single-word rename; module name becomes `datasource.watcher`. |
| *(new)* | `datasource/refresher/` | Home for the CONTENT_FRESHNESS agent (Phase 3). |
| *(new)* | `datasource/patcher/` | New component; auto-patching scraper. See [SCRAPER_PATCHER.md](SCRAPER_PATCHER.md). |
| *(new)* | `datasource/gitops/` | New component; PR driver + 7-day auto-merge policy. |
| *(new)* | `datasource/emitter/` | New component; projects DB/Redis state into NDJSON/Parquet feeds. See [EMITTER.md](EMITTER.md). |
| `ai/pipeline/` | `datasource/pipeline/` | Orchestration glue between scraper → extractor → store → emitter. |
| `ai/qid/` | `datasource/qid/` | QID collector is an ingestion concern. |
| `ai/proofreader/` (scrape-time cross-validator) | `datasource/proofreader/` | The scrape-time cross-validator stays with ingestion. The prediction-time proofreader lives in `swarm/proofreaders/`. |

### 3.3 Staying in `swarm/`

| Current path | New path | Notes |
|---|---|---|
| `ai/model/` | `swarm/predictors/` | Full move; one sub-package per predictor model. |
| `ai/nlp/` | `swarm/nlp/` | Turkish pipeline. |
| `ai/tqu/` | `swarm/nlp/tqu/` | Nest under NLP. |
| `ai/trc/` | `swarm/trc/` | Phase 10 response composer. |
| `ai/orchestrator/` | `swarm/orchestrator/` | Swarm-level state machine (not ingestion). |
| *(new)* | `swarm/reactors/` | Phase 4.7 reactor SDK. |

### 3.4 Moving into `common/`

| Current path | New path | Notes |
|---|---|---|
| `ai/common/config.py` | `common/config/python/` | Python view. |
| `server/internal/config/` (tagged schema only) | `common/config/schema.yaml` | Both languages read from this. |
| *(new)* | `common/schemas/records.py` | Canonical Record envelope (DATA_PIPELINE §4). |
| *(new)* | `common/schemas/feeds/` | JSONSchema per feed type (EMITTER §3). |
| *(new)* | `common/bus/` | Redis Streams / NATS adapter shared by every Python component. |

### 3.5 Retired / absorbed

| Path | Fate |
|---|---|
| `ai/` | Empty after migration; removed. Replaced by `datasource/`, `swarm/`, `common/`. |
| `docker-compose.mock.yml` | Absorbed into the base compose as the `mock` profile. |
| `server/cmd/mocksrv` (binary name) | Renamed to `mock`. Any `mocksrv` references become aliases during one transition release, then drop. |

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

## 5. Versioning chart additions

[`xops/versioning/chart.json`](../../xops/versioning/chart.json)
gains new components. Existing `ai` and `source_watcher` entries are
**renamed** to match the new layout (the CLI supports rename via a
one-shot migration record in the changelog).

| Chart key | Role | Starts at | Notes |
|---|---|---|---|
| `server` | Unchanged | current | gains `mock` sub-mode |
| `datasource_scraper` | scraper binary | 1.0.0 (from `ai`'s scraper share) | |
| `datasource_watcher` | schema drift detector | from renamed `source_watcher` | keeps history |
| `datasource_refresher` | content-freshness agent | 0.1.0 | new |
| `datasource_patcher` | auto-patcher | 0.1.0 | new; gated behind `NEGELIR_PATCHER=1` |
| `datasource_gitops` | PR driver | 0.1.0 | new |
| `datasource_emitter` | feed projector | 0.1.0 | new |
| `swarm` | AI consumers | 1.0.0 (from `ai`'s model/nlp/trc/orchestrator share) | |
| `common` | shared libs | 0.1.0 | new |
| `infra_mock` | unchanged | current | retains history |

The rename `source_watcher → datasource_watcher` is recorded as a
`"rename": {"from": "source_watcher", "to": "datasource_watcher"}`
changelog row by a new `version.py rename` subcommand landed in
Phase R1.

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

- `common/tests/test_swarm_isolation.py` — grep-based check that no
  file under `swarm/` imports `psycopg` / `requests` / `datasource.*`.
- `common/tests/test_datasource_isolation.py` — no file under
  `datasource/` imports `fastapi` / `flask` / `swarm.*`.
- `common/tests/test_server_isolation.py` — no file under `server/`
  contains `XGBoost` / `torch` imports (Go only).

---

## 7. Migration safety

Pivot v3 is a **big move**. The migration is phased (see ROADMAP
Phase R1–R5) and every step is individually reversible:

- **R1** renames chart keys + landings path aliases (no code moves).
- **R2** moves `scraper` + `watcher` to `datasource/` behind shim
  imports (`from ai.scraper import *` keeps working for one release).
- **R3** lands `emitter`, `refresher`, `patcher`, `gitops` skeletons.
- **R4** deletes shims; `ai/` tree is removed.
- **R5** enforces the three isolation tests from §6.

Between R2 and R4 the old `ai.*` import path still resolves. CI
warns on each shim hit; the warning count must hit zero before R4
ships.

---

## 8. Open questions (deferred to the phases that own them)

- **Emitter storage backend.** Local disk is the Phase R3 default.
  S3-compatible object store (MinIO in dev, Azure Blob / AWS S3 in
  prod) is the Phase 14 extension. Covered in [EMITTER.md §7](EMITTER.md#7-storage-and-retention).
- **Patcher LLM choice.** Phase R3 picks between `qwen2.5-coder-7b`
  and `deepseek-coder-v2-lite-7b`. Decision captured in
  [SCRAPER_PATCHER.md §4](SCRAPER_PATCHER.md#4-which-llm).
- **Inter-component wire format.** `datasource → server/internal`
  today goes over HTTP+JSON. Phase R3 may switch to gRPC+protobuf
  if latency budgets demand it; SWARM.md Phase 3 covers bus transport
  separately.
- **Namespace in Python imports.** `datasource.watcher` vs
  `negelir.datasource.watcher`. Phase R2 decides based on how we
  package for distribution. Today's AGENTS.md does not commit.
