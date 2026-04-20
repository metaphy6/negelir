# `datasource/` — The Ingestion Group

> **Status:** Canonical. Describes the Production Pivot v3
> **data-source** worker group.
> **Audience:** Anyone writing a scraper, adding a new upstream, or
> wiring a new ingestion agent.
> **Doctrine:** AGENTS.md §2, especially rules 1, 3, 4, 5, 7, 9.
> **Sibling docs:** [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md)
> (anchor), [`EMITTER.md`](EMITTER.md) (feed contract),
> [`SCRAPER_PATCHER.md`](SCRAPER_PATCHER.md) (auto-patching agent),
> [`DATA_PIPELINE.md`](DATA_PIPELINE.md) (what we ingest).

`datasource/` is the worker group that **owns everything between the
outside world and the feed files the swarm consumes**. The swarm
itself is downstream; it must not reach back into this group.

---

## 1. Six single-word components

| Component | Role in one sentence | Phase |
|---|---|---|
| [`scraper`](#2-scraper) | Fetches bytes from the real internet (or the mock) with rate limits, retries, and per-source etiquette. | Phase 4 (already partially landed in `ai/scraper/`) |
| [`watcher`](#3-watcher) | Detects *structural* drift of upstream sites (schema changes, DOM rewrites, soft-blocks). Today's Source-Watcher Agent. | Phase 2.8 (shipped) |
| [`refresher`](#4-refresher) | Detects *content* change per `Record` (score ticks, lineup swaps, article edits). The CONTENT_FRESHNESS agent. | Phase 3 |
| [`patcher`](#5-patcher) | When `watcher` or `refresher` says "this source broke", the patcher proposes code / schema / migration edits to fix it. | Phase R3 |
| [`gitops`](#6-gitops) | Opens PRs for whatever `patcher` produces, tracks review, and auto-merges after 7 days when the 5-gate policy is green. | Phase R3 |
| [`emitter`](#7-emitter) | Projects Postgres + Redis state into NDJSON live feeds and Parquet training snapshots for the swarm. | Phase R3 |

Supporting modules (not independent components): `pipeline/`
(orchestration glue), `qid/` (question-input collector),
`proofreader/` (scrape-time cross-validator).

---

## 2. `scraper`

**Path:** `datasource/scraper/`
**Language:** Python 3.12
**Runtime:** one process per source (`scraper.mackolik.v1`,
`scraper.nesine.v1`, `scraper.tff.v1`, `scraper.openfootball.v1`) OR
one multiplexed process when cardinality is small — controlled by
`NEGELIR_SCRAPER_MODE={multi,single}`.

### 2.1 Responsibilities

- Fetch bytes from the URL resolved by `NEGELIR_SCRAPE_PROFILE`
  (`real` → live hosts, `mock` → `*.local` vhosts served by
  `server-mock`).
- Honour per-source rate limits from
  [`xops/mock/sources.py`](../../xops/mock/sources.py).
- Emit `scrape.raw` on the bus with `{source, url, status, bytes,
  headers, sha256, captured_at}` — **no parsing**.
- On `4xx`/`5xx`: exponential backoff with jitter; publish
  `sec.alert` after `N` consecutive fails.

### 2.2 What scraper does NOT do

- It does not parse HTML.
- It does not write to the DB.
- It does not know what a "Record" is.
- It does not decide whether to retry a parse failure (that's
  `patcher`).

### 2.3 Proof tests

- `datasource/scraper/tests/test_rate_limit.py` — token-bucket
  honours per-source config within ±10 % over 1000 requests.
- `datasource/scraper/tests/test_mock_roundtrip.py` — fetch any
  mock URL, assert sha256 equals the seed manifest entry.
- `datasource/scraper/tests/test_profile_switch.py` — flipping
  `NEGELIR_SCRAPE_PROFILE` between `real` and `mock` swaps the
  resolved host without touching scraper code (the same assertion
  already exists today; Pivot keeps it green).

---

## 3. `watcher`

**Path:** `datasource/watcher/` (renamed from `ai/swarm/source_watcher/`)
**Language:** Python 3.12
**Runtime:** single process, scheduled.

See [`docs/testing/source-watcher-60pct-stress.md`](../testing/source-watcher-60pct-stress.md)
for current capabilities + shortcomings and the roadmap entries that
close them. Post-Pivot the agent keeps its logic; only its module
path changes.

Planned improvements captured in ROADMAP Phase R2.4:

- `_dom_fingerprint` envelope field (closes the 60%-rewrite gap).
- Per-source learned-baseline mode.
- Mock-vhost end-to-end test.

---

## 4. `refresher`

**Path:** `datasource/refresher/`
**Language:** Python 3.12
**Runtime:** one process per plane (so blast-radius of a bug in one
plane does not leak).

See [`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md) for the full
contract. Summary:

- Subscribes to `match.normalized`, `record.stored` (DATA_PIPELINE §5).
- Applies per-plane "counts as change" rules (DATA_PIPELINE §6).
- Emits `freshness.events.v1` stream: `score.changed`, `lineup.confirmed`,
  `fixture.rescheduled`, `article.edited`, `odds.moved`, `record.retracted`.
- Drives the reactors in `swarm/reactors/` (Phase 4.7).

**Why it lives in `datasource/`, not `swarm/`:** the refresher owns
the *semantics* of "did this Record change." That's a property of the
data, not of the consumer. Keeping it here preserves the isolation
rule.

---

## 5. `patcher`

**Path:** `datasource/patcher/`
**Language:** Python 3.12 + Anthropic Agent SDK (Haiku → Sonnet → Opus,
harness-routed; see [SCRAPER_PATCHER.md §12](SCRAPER_PATCHER.md#12-model-providers-anthropic-agent-sdk))
**Runtime:** single process, gated by `NEGELIR_PATCHER=1`.

Covered in depth in [`SCRAPER_PATCHER.md`](SCRAPER_PATCHER.md). Short
summary for this doc:

The patcher takes a **failure artifact** (parse error + raw bytes +
watcher verdict + refresher degraded signal) and produces a **diff
bundle**: a git patch over the repo that could include

- Python extractor changes (`datasource/scraper/extractors/<source>.py`).
- New or modified SQL migrations (`migrations/NNN_*.sql`).
- Updated selector files (`datasource/scraper/selectors.json`).
- Updated test fixtures (`infra/mock/seeds/<source>/...`).
- Updated schema registry (`common/schemas/records.py`).

The patcher **never writes to the repo directly**. It hands the
bundle to `gitops`.

---

## 6. `gitops`

**Path:** `datasource/gitops/`
**Language:** Python 3.12
**Runtime:** single process; needs GitHub API credentials.

Covered in depth in [`SCRAPER_PATCHER.md §5`](SCRAPER_PATCHER.md#5-gitops-the-pr-driver).
Summary:

- Takes a diff bundle from `patcher`, opens a PR with a standard
  title `[patcher] <source>: <short>` and a body linking the failure
  artifact.
- Attaches labels: `patcher`, `<source>`, `scope:<files>`,
  `severity:<sev>`.
- Polls PR status every `cfg.gitops_poll_min` (default 15 min).
- After 7 calendar days, if the **5-gate policy** is green (see
  SCRAPER_PATCHER §6) and no `hold` label is set, auto-merges with
  squash strategy and a provenance trailer.
- On post-merge regression (detected via shadow predictor disagreement
  or CI turning red in `main`), opens a revert PR immediately.

---

## 7. `emitter`

**Path:** `datasource/emitter/`
**Language:** Python 3.12
**Runtime:** single process; one writer per plane; append-only.

Fully specified in [`EMITTER.md`](EMITTER.md). One-sentence recap:
**emitter** is the *only* component that reads both Postgres and Redis
and writes files into a layout the swarm consumes. It does so via
two formats:

- **Live NDJSON** (`feeds/<plane>/<source>/<YYYY-MM-DD>.ndjson[.zst]`)
  for streaming consumption during predictions.
- **Training Parquet** (`snapshots/<plane>/<asof=YYYY-MM-DDThh>/<source>.parquet`)
  for offline training runs.

---

## 8. Compose profiles

Matches [COMPONENT_LAYOUT.md §4](COMPONENT_LAYOUT.md#4-compose-profiles):

| Profile | `datasource/*` services |
|---|---|
| `datasource` | `scraper`, `watcher`, `refresher`, `emitter` |
| `patcher` | `patcher`, `gitops` |
| `all` | above + every other group |

`patcher` is a **separate** profile from `datasource` on purpose:
it's the only service that holds a GitHub token, and in most deploys
it runs in a different security posture (own namespace, own node
pool, egress allow-list limited to `api.github.com`).

Invocation:

```bash
make up PROFILES=core,server,datasource,swarm         # typical prod
make up PROFILES=core,mock,datasource,patcher         # patcher dev-loop
make up PROFILES=core,mock,datasource                 # data-pipeline smoke
```

---

## 9. Interfaces (what each component expects and produces)

```
                 ┌─────────────────────────────────────────────────────┐
                 │                        BUS                          │
                 │                   Redis Streams                     │
                 └──┬──────────────┬──────────────┬──────────────┬─────┘
                    │              │              │              │
          scrape.raw│  freshness.* │  patcher.*   │  emitter.*   │
                    │              │              │              │
 ┌──────────┐       │   ┌──────────────┐       ┌──────────────┐ │
 │ scraper  │───────┘   │ watcher      │       │ patcher      │─┘
 └──────────┘           └──────────────┘       └──────┬───────┘
                                                      │ diff bundle
                                                      ▼
                                               ┌──────────────┐
                                               │  gitops      │───► api.github.com
                                               └──────────────┘
 ┌──────────┐           ┌──────────────┐       ┌──────────────┐
 │ refresher│           │ emitter      │       │ proofreader  │
 │  (Plane) │──emits───►│              │───writes files──►   │ (scrape-time)
 └──────────┘           └──────────────┘                      │
                                ▲                              │
                                │                              │
                       SELECT / XREAD                           │
                       (postgres, redis)                        │
                                                                ▼
                                                       swarm/* consumes
```

Every arrow is a tested contract:

- `scrape.raw` → `match.normalized`: `datasource/pipeline/tests/test_pipeline_roundtrip.py`
- `match.normalized` → `freshness.events.v1`: `datasource/refresher/tests/test_event_emission.py`
- parse failure → `patcher.request`: `datasource/patcher/tests/test_failure_routing.py`
- diff bundle → opened PR: `datasource/gitops/tests/test_pr_lifecycle.py` (records HTTP via `vcrpy`)
- DB state → feed file: `datasource/emitter/tests/test_projection_roundtrip.py`

---

## 10. What changes for the outside world

The outside world sees **no behavioural change** from Pivot v3. The
public API (`server/api`) is unchanged. The mock stack still serves
the same bytes. The Flutter client (future) sees the same REST
surface.

The internal changes the v3 pivot introduces:

1. Python modules move from `ai.*` to `datasource.*` / `swarm.*` /
   `common.*`. Shim imports preserve the old paths for one release.
2. The mock server binary is renamed (`mocksrv` → `mock`) and absorbed
   into `server` with `MODE=mock`.
3. New components ship: `emitter`, `patcher`, `gitops`, `refresher`.
4. Compose gains profiles; overlay files go away.
5. Version chart gets new keys.

No user-visible data change. No breaking config-key changes (they are
additive).
