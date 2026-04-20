# `emitter` — Feed Contract Between `datasource/` and `swarm/`

> **Status:** Canonical. Defines the exact file formats, layouts, and
> schemas the `datasource/emitter` writes and the `swarm/*` agents
> consume.
> **Audience:** Anyone writing a predictor, a feature, a reactor, a
> training script, or any other consumer of ingested data.
> **Doctrine:** AGENTS.md §2 rules 1, 2, 5, 7, 8.
> **Sibling docs:** [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md),
> [`DATA_PIPELINE.md`](DATA_PIPELINE.md),
> [`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md),
> [`DATA_SOURCE.md`](DATA_SOURCE.md).

The swarm must not read Postgres, must not hold a Redis connection,
must not know what a scraper is. It must only read **feeds**. This
document is the single contract that makes that possible.

---

## 1. Why two formats

Two consumers, two workloads.

| Consumer | Workload shape | Latency budget | Row count per read |
|---|---|---|---|
| **Live predictors** / reactors | Stream small diffs | < 250 ms | 1 – 50 |
| **Trainer** (offline) | Bulk scan months of history | Minutes are fine | 10⁶ – 10⁸ |

NDJSON is unbeatable for (1): it's append-only, streamable, one line
= one Record, every language parses it out of the box, `tail -f`
works. Parquet is unbeatable for (2): columnar, typed, 10–50× faster
than JSON for ML reads, native predicate push-down, every ML library
(pandas, polars, pyarrow, duckdb, Spark) speaks it.

YAML, MessagePack, protobuf, CBOR were considered and rejected:
YAML parsing is slow and ambiguous; the others add a schema-compiler
step for a local-first project whose consumers are all Python. We
reserve the right to revisit protobuf if the bus transport (SWARM
Phase 3) chooses it.

---

## 2. On-disk layout

```
feeds/                               # root; typically a volume or S3 prefix
├── manifest.json                    # top-level index (see §5)
│
├── live/                            # NDJSON streams (one file per day per source)
│   ├── reference/
│   │   ├── mackolik/2026-04-20.ndjson.zst
│   │   ├── tff/2026-04-20.ndjson.zst
│   │   └── openfootball/2026-04-20.ndjson.zst
│   ├── schedule/
│   │   └── <source>/<date>.ndjson.zst
│   ├── score/                       # the live plane (DATA_PIPELINE §1)
│   │   └── mackolik/2026-04-20.ndjson.zst
│   ├── lineup/
│   │   └── mackolik/2026-04-20.ndjson.zst
│   ├── editorial/
│   │   └── mackolik/2026-04-20.ndjson.zst
│   └── market/
│       └── nesine/2026-04-20.ndjson.zst
│
├── snapshots/                       # Parquet training snapshots
│   ├── _metadata/                   # pyarrow-compatible metadata
│   ├── reference/
│   │   └── asof=2026-04-20T00/      # hive-partitioned
│   │       ├── source=mackolik/part-0000.parquet
│   │       └── source=tff/part-0000.parquet
│   ├── schedule/
│   │   └── asof=2026-04-20T00/
│   │       └── source=<s>/part-0000.parquet
│   ├── score/
│   │   └── asof=2026-04-20T00/
│   │       └── source=<s>/part-0000.parquet
│   ├── lineup/
│   │   └── asof=2026-04-20T00/
│   │       └── source=<s>/part-0000.parquet
│   ├── editorial/
│   │   └── asof=2026-04-20T00/
│   │       └── source=<s>/part-0000.parquet
│   └── market/
│       └── asof=2026-04-20T00/
│           └── source=<s>/part-0000.parquet
│
└── cold/                            # zstd-compressed monthly rollups (Phase 14)
    └── <plane>/<YYYY-MM>/<source>.parquet
```

**Partition keys.** Every Parquet directory is hive-partitioned by
`asof` (UTC hour) and `source`. Trainers use predicate push-down:

```python
import pyarrow.dataset as ds
matches = ds.dataset("feeds/snapshots/score", partitioning="hive") \
            .to_table(filter=ds.field("asof") >= "2026-01-01T00")
```

**File rotation.**

- NDJSON: one file per `(plane, source, UTC calendar day)`. Closed at
  00:00 UTC and compressed with zstd level 3. The day's hot file is
  uncompressed for append speed.
- Parquet: new snapshot every `cfg.emitter_snapshot_interval_hours`
  (default 1). Each snapshot is point-in-time for `as_of_utc`.

---

## 3. Record schema (wire format)

Every line of every NDJSON file, and every row of every Parquet
snapshot, is a single `Record` envelope. The envelope schema is the
exact one from [DATA_PIPELINE.md §4](DATA_PIPELINE.md#4-the-record-contract--what-the-ai-actually-sees),
serialized per format.

### 3.1 NDJSON

One JSON object per line, UTF-8, no trailing comma, `\n` separator,
keys alphabetically sorted (for idempotent diffs in reviews):

```json
{"canonical_version":"v1","captured_at":"2026-04-20T19:32:14Z","extractor_version":"mackolik.score@3","occurred_at":"2026-04-20T19:32:10Z","payload":{"away":{"name":"Fenerbahçe","score":1},"home":{"name":"Galatasaray","score":2},"minute":78,"status":"live"},"plane":"live","raw_ref":"s3://seeds/mackolik/20260420/fixtures/0001.html","record_type":"score","source_key":"mackolik","stable_id":"mackolik:fixture:20260420-001","upstream_id":"20260420-001"}
```

One line per Record. Writers must write line-by-line with flush,
never per-batch buffered. Readers must treat each line
independently; one broken line never aborts the stream.

### 3.2 Parquet

Columns map 1:1 to envelope keys, with `payload` stored as a nested
struct matching the plane's schema. Column ordering is fixed. Every
snapshot carries a footer metadata entry
`negelir.emitter.version=<semver>`.

Schema is generated from
[`common/schemas/records.py`](../../common/schemas/records.py)
at emitter build time; the script fails CI if the generated Parquet
schema drifts from the TypedDict.

### 3.3 Per-plane payload schemas

Each plane's `payload` substructure is frozen in
`common/schemas/feeds/<plane>.json` (JSONSchema draft 2020-12). The
exhaustive field list lives there; here is the **shape** for each:

| Plane | `payload` required keys | Plane-specific notes |
|---|---|---|
| `reference` | `kind` (team\|player\|venue\|…), `name`, `aliases`, `country`, `updated_at` | Slow-changing. Never deleted, only `retired_at` set. |
| `schedule` | `match_stable_id`, `kickoff_utc`, `home`, `away`, `competition`, `status` | `status ∈ {scheduled, postponed, cancelled, finished}`. |
| `score` | `match_stable_id`, `minute`, `status`, `home`, `away`, `events[]` | `events[]` is monotonic append-only within a match. |
| `lineup` | `match_stable_id`, `side` (home\|away), `starters[]`, `bench[]`, `formation` | `confirmed: bool`; unconfirmed lineups are also emitted but flagged. |
| `editorial` | `url`, `title`, `body_text`, `authors[]`, `published_at`, `edited_at` | `body_text` already ad-stripped (DATA_PIPELINE §5.3). |
| `market` | `match_stable_id`, `bookmaker`, `market_code`, `selections[]`, `is_suspended` | One Record per `(match, bookmaker, market)` tick. |

Schemas are versioned. See §4.

---

## 4. Schema registry and versioning

A **schema version** is per `record_type`, not per emitter. A trainer
that works on `score@v1` continues to work when the emitter ships
`score@v2`, because the emitter also writes the older format until
the registry marks v1 `end-of-life`.

### 4.1 Registry layout

```
common/schemas/feeds/
├── reference.v1.json
├── schedule.v1.json
├── score.v1.json
├── score.v2.json          # new fields added; v1 still emitted
├── lineup.v1.json
├── editorial.v1.json
├── market.v1.json
└── registry.json          # index: {record_type: [{version, status, from, to}]}
```

`status` ∈ `{active, deprecated, eol}`. Emitter writes every
`active` version in parallel; deprecated versions are still written
for a minimum of 90 days; EOL versions raise a CI error if anything
still writes them.

### 4.2 Breaking vs compatible changes

Per SemVer-for-schemas:

| Change | Compatible? | Version bump |
|---|---|---|
| Add an optional field | yes | **patch** (`score.v1` stays readable) |
| Tighten an enum | no | **major** (new version) |
| Rename a field | no | **major** |
| Change a type | no | **major** |
| Widen an enum | yes | **minor** |
| Drop a deprecated field after 90 days | no (but scheduled) | **major** with EOL record in registry |

### 4.3 Proof tests

- `common/schemas/tests/test_registry_consistent.py` — every
  `<plane>.v*.json` appears in `registry.json` and vice versa.
- `datasource/emitter/tests/test_writes_all_active_versions.py` —
  when `registry.json` marks `score@v1` active and `score@v2` active,
  emitter writes both paths.
- `swarm/predictors/tests/test_reads_versioned.py` — a predictor
  declaring `score@v1` stays green when `v2` is introduced.

---

## 5. `feeds/manifest.json`

Top-level index written atomically on each emitter tick. Consumers
`stat`+read this file to discover what's available without scanning
the tree.

```json
{
  "emitter_version": "0.3.2",
  "generated_at": "2026-04-20T19:40:00Z",
  "planes": {
    "reference": {
      "live":  {"mackolik": {"latest_file": "feeds/live/reference/mackolik/2026-04-20.ndjson.zst",
                             "last_record_at": "2026-04-20T19:38:41Z",
                             "record_count_today": 142}},
      "snapshots": {"latest_asof": "2026-04-20T19:00:00Z",
                    "paths": {"mackolik": "feeds/snapshots/reference/asof=2026-04-20T19/source=mackolik/part-0000.parquet"}}
    },
    "score": { ... },
    ...
  },
  "schema_registry_sha256": "<hash of common/schemas/feeds/>",
  "record_count_total": 12934219
}
```

Clients must treat `manifest.json` as the **only** discovery surface.
Guessing paths is forbidden.

---

## 6. Writer semantics (what emitter guarantees)

1. **At-least-once.** A Record may appear more than once in NDJSON
   if emitter crashes mid-write. Consumers must be idempotent on
   `(record_type, stable_id, captured_at)`.
2. **Monotonic per `(plane, source)`**. Within one NDJSON file,
   `captured_at` is non-decreasing.
3. **Atomic manifest.** `manifest.json` is written to
   `manifest.json.tmp` then `rename()`d. Readers never see a partial
   file.
4. **No in-place edits.** NDJSON files are append-only; Parquet
   snapshots are write-once. Retractions go through the
   `record.retracted` event in the CONTENT_FRESHNESS stream, not by
   rewriting history.
5. **Clock is UTC.** `captured_at` and `occurred_at` are ISO-8601
   with a `Z` suffix. Local time is an emitter bug.
6. **Compression boundary.** `*.ndjson.zst` is compressed with zstd
   level 3 (configurable). Today's hot file is the uncompressed
   `*.ndjson`; it is rotated to `*.ndjson.zst` at midnight UTC.

### 6.1 Proof tests

- `datasource/emitter/tests/test_atomic_manifest.py` — kill emitter
  mid-write; reader never sees a broken `manifest.json`.
- `datasource/emitter/tests/test_at_least_once_duplicates.py` —
  force-restart emitter mid-batch, assert consumer reads
  duplicates (not missing records) and that keying by
  `(stable_id, captured_at)` deduplicates cleanly.
- `datasource/emitter/tests/test_monotonic_captured_at.py` — a day
  of NDJSON has non-decreasing `captured_at` within each source.
- `datasource/emitter/tests/test_utc_only.py` — no `offset != Z`
  timestamp survives the pipeline.

---

## 7. Storage and retention

### 7.1 Local dev (Phase R3)

- Filesystem volume mounted at `/data/feeds` on `emitter`, `swarm`,
  `trainer` containers.
- 30-day retention for NDJSON, 365-day for snapshots.
- `make feeds.prune` — deletes expired files safely (checks manifest
  coverage first).

### 7.2 Prod / cloud (Phase 14)

- S3-compatible object store (MinIO in the dev stack, Azure Blob /
  AWS S3 in prod).
- Same directory layout under a configurable prefix
  (`NEGELIR_FEEDS_URI=s3://negelir-feeds/`).
- Lifecycle rules: NDJSON older than 30 days moves to cold storage
  and is rolled up to monthly Parquet (`cold/<plane>/<YYYY-MM>/`).
- Immutability: snapshot buckets are opt-in write-once (object
  lock), so Parquet files cannot be silently rewritten.

### 7.3 Proof tests

- `datasource/emitter/tests/test_s3_roundtrip.py` (uses MinIO in
  docker) — write + read via the S3 driver is byte-identical to the
  local-disk driver.
- `datasource/emitter/tests/test_retention.py` — `make feeds.prune`
  after a fake 40-day run keeps snapshots, discards expired NDJSON.

---

## 8. Consumer APIs

Consumers never open files directly. A small **`feeds` library** in
`common/feeds/` wraps both formats:

```python
# common/feeds/__init__.py
from common.feeds import FeedReader

reader = FeedReader("/data/feeds")       # or "s3://negelir-feeds/"

# Live streaming — yields Records as they arrive
for record in reader.stream(plane="score", sources=["mackolik"],
                            since="2026-04-20T19:00:00Z"):
    handle(record)

# Point-in-time training snapshot
df = reader.snapshot(plane="schedule",
                     as_of="2026-04-20T19:00:00Z",
                     sources=["mackolik", "tff"])
# → polars.DataFrame
```

This library is the **only** supported way for the swarm to read
feeds. Any direct path manipulation in swarm code is rejected by the
isolation test in `common/tests/test_swarm_isolation.py`.

### 8.1 Contract tests

- `common/feeds/tests/test_reader_roundtrip.py` — write Records via
  emitter, read them via `FeedReader.stream` and `FeedReader.snapshot`,
  assert byte-equal on payload.
- `common/feeds/tests/test_reader_handles_version_skew.py` —
  `FeedReader` surfaces `score@v1` and `score@v2` side-by-side; caller
  opts into the version set they understand.
- `common/feeds/tests/test_reader_rejects_guessed_paths.py` — reader
  refuses any path not referenced by `manifest.json`.

---

## 9. What the emitter does NOT do

- **No derivation.** Emitter is a projection, not a transformation.
  Features (`momentum_score`, `last_5_result`, …) are computed by
  dedicated `swarm/feature/*` agents on top of feeds. That keeps
  the feed schema small and stable.
- **No sentiment, no NLP.** Sentiment scores are a *feature*; they
  live in the feature store, computed by `swarm/nlp/*`.
- **No model scoring.** Predictions are written back through
  `server/internal`, not the emitter.
- **No data repair.** If Postgres has a bad row, fix it at the
  source (retraction event from `refresher`), don't paper over it
  in emitter.

---

## 10. Phased delivery

See ROADMAP Phase R3 for the landing plan. Summary:

| Sub-phase | Deliverable | Proof |
|---|---|---|
| R3.1 | `FeedWriter` + NDJSON live feeds for `reference` plane | `test_projection_roundtrip` green |
| R3.2 | NDJSON live feeds for all 6 planes | 6 proof tests + property fuzzer |
| R3.3 | Parquet snapshots | `test_parquet_snapshot_identical_to_ndjson_union` |
| R3.4 | `FeedReader` lib + swarm consumes feeds (not DB) | `test_swarm_isolation` green |
| R3.5 | Schema registry + version skew tests | 3 proof tests |
| R3.6 | S3 driver + MinIO in compose | `test_s3_roundtrip` green |
| R3.7 | Cold-storage rollup (Phase 14 prerequisite) | `test_cold_rollup_coverage` green |

---

## 11. Open questions

- **Columnar live format?** Arrow IPC streams (`.arrows`) would beat
  NDJSON on read throughput, but parsing is harder in non-Python
  consumers. Decision deferred: Phase R3 ships NDJSON; revisited when
  the first non-Python swarm consumer lands.
- **Per-Record signing?** For the patcher's PR-auto-merge story we
  may want an HMAC per Record proving the emitter wrote it. Not in
  scope for Pivot v3; tracked in SCRAPER_PATCHER open questions.
- **Schema evolution in Parquet.** Today we write a new subdirectory
  per major version. Alternative: rely on Arrow's schema unification.
  Decision: we stay directory-scoped — simpler to reason about for
  trainers.
