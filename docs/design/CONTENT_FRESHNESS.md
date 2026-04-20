# Content-Freshness Agent — Design Sketch

> **Status:** Design proposal (Phase 3+). Not implemented.
> **Audience:** Anyone reviewing or eventually implementing the agent
> that detects *real-world content* changes (new fixtures, score
> updates, lineups, articles, commentary, odds) — as distinct from the
> Source-Watcher Agent which detects *structural* drift.
> **Scope reference:** [`DATA_PIPELINE.md`](DATA_PIPELINE.md) defines
> *what* the project ingests and the five planes (reference, schedule,
> live, editorial, market). **This document only describes detecting
> changes inside that scope** — it does not redefine it. If the two
> docs disagree, DATA_PIPELINE wins.
> **Doctrine alignment:** AGENTS.md §2 rules 1, 3, 5, 6, 7, 8 and
> ROADMAP.md §Guiding Principles. Anything contradicting either of
> those takes precedence over this sketch.

This document is intentionally tedious. The agent is meant to be built
once and run forever; ambiguity here will become noisy events,
phantom retractions, and false retraining triggers later.

---

## 0. Scope — what "freshness" means here, exactly

**Freshness here means: detecting that a *known logical record*
changed in a *semantically meaningful* way, and emitting one typed
event per change.** It does not mean re-downloading pages, refreshing
caches, or rebuilding the seed corpus.

### 0.1 In scope

The agent operates on the `Record` envelope defined in
[`DATA_PIPELINE.md`](DATA_PIPELINE.md#4-the-record-contract--what-the-ai-actually-sees)
and only on the six `record_type`s listed there: `fixture`, `score`,
`lineup`, `article`, `commentary`, `odds`. For each `(source_key,
record_type, stable_id)` it answers exactly two questions per tick:

1. **Did anything change?** — by comparing the latest normalized
   record against the prior `current.json` for that triple.
2. **Does the change matter?** — by running the per-record-type
   differ (§7) whose thresholds are explicit, configurable, and
   replayable.

Only when both answers are "yes" does an event leave the agent.

### 0.2 Explicitly out of scope

| Out of scope | Why | Where it actually lives |
|---|---|---|
| Re-downloading whole pages on a timer | Wasteful and pointless when nothing changed | Capture layer (§6) uses conditional GET; 304 short-circuits the rest |
| Refreshing the entire site | Sites are not the unit of change — *records* are | Per-record diff (§7) |
| Refreshing the seed corpus | That is `make mock.capture`, agent-runnable but human-driven | DATA_PIPELINE §3 + `xops/mock/capture_engine.py` |
| Detecting DOM / HTML structural drift | That's the Source-Watcher's job | `datasource/watcher/` (post-Pivot v3, see [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) §3; current path during the migration is `ai/swarm/source_watcher/`, Phase 2.8) |
| Cleaning article text, parsing tables | That's the extractor's job (§4) | Per-source extractors |
| Computing sentiment, entities, narrative tags | That's NLP's job, downstream of our events | `swarm/nlp/sentiment.py` (post-Pivot v3; today: `ai/nlp/sentiment.py`), Phase 10 |
| Deciding whether to retrain | Trainer subscribes to our events and decides | `swarm/predictors/.../trainer.py` (post-Pivot v3; today: `ai/model/trainer.py`), Phase 5/6 |
| Live websocket streams | Polling is enough for v1; same record contract holds when streams arrive later | Future Phase |

> See **§15** for the full event-to-reactor matrix that names every
> downstream consumer and what it actually does on receipt.

### 0.3 The "delta only" promise

The unit of work is **one (source_key, record_type, stable_id) per
tick**. The agent **never** emits "the page changed", "the site
refreshed", or "N bytes differ". It emits exactly one of:

- A **typed change event** for that triple (`score.changed`,
  `lineup.changed`, `article.updated`, …).
- A **first-seen event** when a new `stable_id` appears
  (`fixture.added`, `article.added`, …).
- A **retraction event** after the configured grace period of
  consecutive misses (`record.retracted`).
- **Nothing.**

Byte-level deltas that don't move any payload field above its
per-type threshold (whitespace, ad rotation, CDN reordering, header
churn, cookie banners) produce **no event**. This is what "quiet by
default" means in §0.4.

### 0.4 Goals, non-goals, and what "reliable" means here

**Goal.** For every source the project scrapes, detect — within a
bounded latency — that *new or changed real-world content* exists
inside the six record types listed in §0.1, emit a typed event per
record, and gate downstream actions (retrain, re-evaluate, refresh
model inputs, alert).

**Non-goals.**

- Replacing the Source-Watcher Agent (that one stays focused on
  *structural* drift).
- Performing the actual training. We emit events; the orchestrator
  decides what to do.
- Doing semantic NLP on the article body inside this agent. We extract
  a normalized record and hand it off; sentiment runs in
  [`ai/nlp/sentiment.py`](../../ai/nlp/sentiment.py).
- Live-streaming (websocket) capture in v1. Polling is enough; streams
  can be added later behind the same record contract.

**Reliability bar.**

- **Idempotent** — running the same tick twice produces the same
  events at most once.
- **Replayable** — any historical snapshot pair can be re-diffed
  offline and produce identical events (deterministic pipeline).
- **Crash-safe** — a SIGKILL mid-write must not corrupt the store or
  emit a half-event.
- **Order-tolerant** — late or out-of-order captures must not invent
  fake "deletions".
- **Schema-evolution-safe** — bumping an extractor must not rewrite
  history or invalidate old snapshots.
- **Bounded** — disk, memory, network, and event-bus footprint are
  all explicitly capped.
- **Quiet-by-default** — emits nothing on no-change, regardless of
  byte-level noise.

---

## 1. Layered architecture

```
                ┌──────────────────────────────────────────────────┐
                │              Scheduler  (per-source cadence)     │
                └────────────────┬─────────────────────────────────┘
                                 │ source_key
                                 ▼
   ┌───────────┐         ┌──────────────┐        ┌───────────────┐
   │ Capture   │─────────▶│  Extractor  │───────▶│  Normalizer   │
   │ (HTTP)    │ raw bytes│  (per-src)  │ records│  (canonical)  │
   └───────────┘         └──────────────┘        └───────┬───────┘
                                                         │
                                       ┌─────────────────▼──────────────┐
                                       │  Identity resolver             │
                                       │  (stable_id per record)        │
                                       └─────────────────┬──────────────┘
                                                         │
                                       ┌─────────────────▼──────────────┐
                                       │  Snapshot store (append-only)  │
                                       └─────────────────┬──────────────┘
                                                         │
                                                         ▼
                                       ┌────────────────────────────────┐
                                       │  Record differ                 │
                                       │  (per-record-type rules)       │
                                       └─────────────────┬──────────────┘
                                                         │
                                                         ▼
                                       ┌────────────────────────────────┐
                                       │  Event emitter (typed, signed) │
                                       └─────────────────┬──────────────┘
                                                         │
                                       ┌─────────────────▼──────────────┐
                                       │  Bus (Redis stream)            │
                                       └─────────────────┬──────────────┘
                                                         │
                  consumers: orchestrator, sentiment, retrain trigger, dashboards
```

Every layer is a pure function of its input plus injected I/O — same
pattern as `source_watcher`. Tests inject in-memory fakes for capture
+ clock + bus.

---

## 2. The hardest problem: stable identity

**Most freshness systems break here.** If you can't reliably say "this
match record on Tuesday is the same match as Wednesday's", you'll
generate phantom adds + deletes every poll and your downstream
consumers will burn cycles.

### 2.1 Identity strategies, in priority order

| Order | Strategy | Use when | Risk |
|---|---|---|---|
| 1 | Upstream stable ID (e.g. Mackolik `match_id`, TFF fixture ID) | Always preferred when present in markup or URL | URL ID can change with a redesign — store provenance |
| 2 | Composite natural key (date + home_team_canonical + away_team_canonical + competition) | Fixtures, lineups | Team renames break it; needs alias map |
| 3 | URL canonicalization (strip tracking params, lowercase host, normalize path) | Articles, blog posts | Site can rotate URLs; keep `(canonical_url, content_hash)` cross-index |
| 4 | Content fingerprint (shingled MinHash over normalized text) | Editorials with no stable URL | Probabilistic → must be backed by a confidence threshold |

The agent **must record which strategy resolved each record**
(`identity.method = "upstream_id" | "composite" | "url_canonical" | "fingerprint"`)
so a later analyst can audit drift in identity quality.

### 2.2 Canonicalization rules (per record type) — these must be frozen and versioned

- **Team names**: NFC unicode, casefold, strip honorifics (`SK`,
  `FC`, `A.Ş.`), apply alias table (`infra/aliases/teams.yaml`).
  Alias table is **append-only**; renames create a new alias row,
  never overwrite.
- **Datetimes**: parse → UTC → ISO-8601 with second precision. Source
  TZ stored separately for audit (`captured_tz`).
- **URLs**: lowercase scheme+host, drop fragment, drop tracking params
  from a maintained denylist (`utm_*`, `gclid`, `fbclid`, …),
  trailing-slash off, percent-encoding normalized.
- **Article body**: stripped of nav/ads/cookie banners *by extractor*;
  the normalizer only does whitespace collapse + NFC.

These rules live in `datasource/refresher/canonical.py` (during the
R2/R3 migration: `ai/swarm/content_freshness/canonical.py`) and are
**pure functions**. Versioned via a `CANONICAL_VERSION` constant.

---

## 3. Record taxonomy (the contract every extractor implements)

The `Record` envelope is owned by
[`DATA_PIPELINE.md §4`](DATA_PIPELINE.md#4-the-record-contract--what-the-ai-actually-sees)
and lives in `common/schemas/records.py` post-Pivot v3
(transitional shim: `ai/common/schemas/records.py`). This agent only
constrains the freshness-relevant subset: the six `record_type`s
listed in §0.1 and the `payload` keys each differ in §7 reads from.

Per-type payload schemas (all keys mandatory; missing → extractor
reports `degraded=True`, agent emits no false-negative):

| Type | Mandatory payload keys |
|---|---|
| `fixture` | `kickoff_utc`, `home_team`, `away_team`, `competition`, `round`, `venue?`, `status` ∈ `{scheduled, in_progress, finished, postponed, cancelled}` |
| `score` | `match_stable_id`, `home_score`, `away_score`, `period` ∈ `{1H, HT, 2H, ET, FT}`, `minute?`, `events: [GoalEvent, CardEvent, SubEvent]` |
| `lineup` | `match_stable_id`, `side` ∈ `{home, away}`, `formation?`, `xi: [Player×11]`, `bench: [Player×N]`, `confirmed: bool` |
| `article` | `title`, `published_utc`, `author?`, `body_text` (cleaned), `tags`, `body_sha256` |
| `commentary` | `match_stable_id?`, `author`, `published_utc`, `body_text`, `body_sha256`, `target_team?`, `target_player?` |
| `odds` | `match_stable_id`, `bookmaker`, `market`, `selection`, `decimal_odds`, `observed_utc`, `is_suspended: bool` |

These payload schemas are validated with `jsonschema` at extractor
exit. Validation failure ⇒ extractor returns a `DegradedExtraction`
with the failing keys logged; **no silent skips, no synthetic
defaults**.

---

## 4. Extractor contract (one per source)

```python
class Extractor(Protocol):
    source_key: str
    extractor_version: str          # SemVer per source
    record_types: frozenset[str]    # what this extractor produces

    def extract(self, raw: bytes, *, captured_at: str, upstream_url: str) -> ExtractResult: ...
```

```python
@dataclass(frozen=True)
class ExtractResult:
    records: list[Record]
    degraded: list[DegradedRecord]   # parsed but failed validation
    parser_diagnostics: dict         # selector hits/misses, fallback uses
    duration_ms: int
```

**Hard rules for extractors.**

1. **Never raise on malformed input.** Return `degraded` entries with
   reasons. Raising kills a tick for *all* records; degraded entries
   leave the rest of the page useful.
2. **Pure**, no I/O, no `time.now()` (caller injects `captured_at`).
   Reproducible from `(raw, captured_at, upstream_url)` alone.
3. **Selector resilience**: every CSS/XPath has a primary + at least
   one fallback. Use of fallback bumps
   `parser_diagnostics["fallback_used"]` so the source_watcher's
   classifier can correlate with structural drift later.
4. **Bounded output**: hard cap on records per extraction
   (configurable per type, default 5000) to defend against a hostile
   or runaway page.
5. **No DOM-dependent ordering**: records sort deterministically by
   `stable_id` before return.

---

## 5. Snapshot store — append-only, content-addressed

```
infra/freshness/store/
├── raw/
│   └── <source_key>/<yyyy>/<mm>/<dd>/<sha256>.bin     # immutable raw bytes
│   └── <source_key>/<yyyy>/<mm>/<dd>/<sha256>.meta.json (status, headers, fetch_ms)
└── records/
    └── <source_key>/<record_type>/<stable_id>/
        ├── current.json                                # latest accepted record
        └── history/<captured_at>.json                  # every accepted update
```

Why this shape:

- **Raw is content-addressed**, so refetching unchanged bytes never
  grows storage. The `mock.capture` flow already proves this works.
- **`current.json`** is the only mutable file in the store and is
  written via `tmp + rename` (POSIX atomic) — survives `kill -9`
  mid-write.
- **History is append-only.** Replaying a window means walking
  `history/` for each record — deterministic, no DB needed.
- **Pruning** is per-record (`HISTORY_KEEP_PER_RECORD`, default 100)
  and per-raw (`RAW_KEEP_DAYS`, default 30). Pruning is a separate
  `make freshness.prune` target, not a side-effect of capture.

A small SQLite index sits next to it (`infra/freshness/index.db`)
holding `(source_key, record_type, stable_id) → (current_path,
last_seen_at, last_changed_at, etag)` so range queries don't walk the
FS. **The FS is the source of truth; the index is rebuildable from
disk** by `make freshness.reindex`. *Never* let the index become
authoritative.

---

## 6. Capture layer — the rate-limit, robots, and freshness signals

Per-source config (single source: `xops/freshness/sources.py`,
mirroring [`xops/mock/sources.py`](../../xops/mock/sources.py)):

```python
SOURCES = [
    FreshnessSource(
        key="mackolik",
        targets=[
            Target("fixtures",   "/lig/{league}/fikstur",      poll="hourly",  during_match="60s"),
            Target("scores",     "/lig/{league}/canli",        poll="600s",   during_match="15s"),
            Target("articles",   "/haberler",                  poll="hourly"),
            Target("commentary", "/yorum",                     poll="2h"),
        ],
        rate_limit_rps=0.5,
        robots_must_allow=True,
        send_if_modified_since=True,
        send_if_none_match=True,
        per_target_overrides={...},
    ),
    ...
]
```

Mandatory client behaviour:

| Concern | Rule |
|---|---|
| `robots.txt` | Fetched once per 24h, cached. Disallowed paths refuse to fire (raise → degraded tick). |
| Conditional GET | Always send `If-Modified-Since` + `If-None-Match` from the `meta.json` of the prior raw. 304 ⇒ short-circuit, no extractor work, no event. |
| Rate limit | Token bucket per `source_key`, shared across replicas via a Redis `INCR` window. |
| Backoff | Exponential on 429/503 with `Retry-After` honoured; persisted in the index so a restart doesn't blast the source. |
| Timeouts | Connect 5s, read 15s, total 30s — all configurable. Timeout ⇒ degraded tick, *not* a "removal" event. |
| User-Agent | Single canonical UA from config; never rotate to evade blocks (doctrine: no fabricated production data, no adversarial scraping). |
| TLS | Strict; `verify=True`. Mock vhosts use the local CA already wired by `make mock.trust` (per [`MOCK_DATA_SERVER.md`](MOCK_DATA_SERVER.md) §🔑 — the `mock.ca-trust` name was retired during Phase 2). |

**Live-during-match cadence**: the scheduler (§8) reads
`during_match` from the latest known `fixture` records and tightens
cadence only for sources with an in-progress match. This avoids
hammering the editorial endpoints when only the score endpoint is
interesting.

---

## 7. Differ — per-record-type rules, not one giant function

For each `(source_key, record_type)`, a tiny pure function decides
what changed and what it means. Returns a list of typed `RecordEvent`s.

```python
def diff_score(old: Record | None, new: Record) -> list[RecordEvent]:
    if old is None:
        return [event("score.first_seen", new)]
    if new["payload"]["status"] == "finished" and old["payload"]["status"] != "finished":
        return [event("score.finalized", new, prev=old)]
    if (new["payload"]["home_score"], new["payload"]["away_score"]) \
       != (old["payload"]["home_score"], old["payload"]["away_score"]):
        return [event("score.changed", new, prev=old, delta={...})]
    if new["payload"]["events"] != old["payload"]["events"]:
        return [event("score.events_updated", new, prev=old, delta=...)]
    return []  # no-op
```

Why per-type:

- **No accidental noise.** A whitespace twiddle in an article body is
  the *expected* class of difference; the article differ knows to
  ignore it. A whitespace twiddle in a score is impossible by
  construction (typed integers).
- **Deterministic threshold per type.** Article body: emit
  `article.updated` only if normalized-text token-Levenshtein > N
  (configurable, default `5`) OR the title changed OR `published_utc`
  changed. Below threshold ⇒ silent. This is the only place "fuzzy"
  sneaks in, and it's bounded and configurable.
- **Replay-safe.** Re-running the differ on the same `(old, new)`
  pair always yields the same events.

**A retraction mechanism is required**: if upstream removes a record,
we *do not* immediately delete. We mark `last_seen_at` and only emit
`record.retracted` after `RETRACTION_GRACE` consecutive misses
(default 3 polls). This is the single most common source of false
alerts and must not be skipped.

---

## 8. Scheduler — per-source cadence with safeties

Reuses the `scheduler.loop` pattern in
[`ai/swarm/source_watcher/scheduler.py`](../../ai/swarm/source_watcher/scheduler.py)
but with:

- **Per-target cadence** (cron-like spec) rather than a single
  `interval_s`.
- **Jitter** (`±10%`) to avoid thundering herd across replicas.
- **Lease per target** in Redis (`SET NX PX`) so multi-replica
  deploys don't double-fetch.
- **Soft halt on consecutive failures**: 5 consecutive `degraded`
  ticks for a target ⇒ fire `source.degraded` event, drop cadence to
  10× normal, alert.
- **Drift compensation**: scheduler records actual fire times and
  corrects schedule, never compounds drift.

Cold start strategy:

- First tick per target = capture only, no events emitted (we have no
  `old` to diff against, except the *very* explicit `*.first_seen`
  events which downstream may filter).
- Mark first capture in the index so reindex/restore is unambiguous.

---

## 9. Event taxonomy — small, frozen, typed

| Event | Severity | Triggered when |
|---|---|---|
| `fixture.added` | info | New fixture stable_id seen |
| `fixture.rescheduled` | warn | `kickoff_utc` moves > 5 min |
| `fixture.cancelled` | warn | `status` → `cancelled`/`postponed` |
| `score.first_seen` | info | New live match |
| `score.changed` | info | Numeric score delta |
| `score.events_updated` | info | New goal/card/sub event in the events list |
| `score.finalized` | info | `status` → `finished` |
| `lineup.published` | info | First confirmed XI for a side |
| `lineup.changed` | warn | Confirmed XI changes after publication |
| `article.added` | info | New article stable_id |
| `article.updated` | info | Article body diff above threshold |
| `article.retracted` | warn | After grace period of misses |
| `commentary.added` | info | New commentary entry |
| `commentary.updated` | info | Body diff above threshold |
| `odds.moved` | info | Decimal odds delta above per-market threshold |
| `odds.suspended` | warn | `is_suspended` flips true |
| `source.degraded` | warn | Capture/extract failures over threshold |
| `record.retracted` | warn | Generic missing-after-grace |

Event envelope (immutable, signed):

```json
{
  "schema": "freshness.event/v1",
  "event_id": "<uuid7>",
  "event_type": "score.changed",
  "occurred_at": "2026-04-20T17:42:11Z",
  "source_key": "mackolik",
  "record_type": "score",
  "stable_id": "match:mackolik:1234567",
  "payload_ref": "infra/freshness/store/records/mackolik/score/match:mackolik:1234567/history/2026-04-20T17-42-11Z.json",
  "prev_ref": "...",
  "delta": {...},
  "extractor_version": "mackolik@1.4.2",
  "canonical_version": "1",
  "agent_version": "content_freshness@0.1.0"
}
```

- `event_id` is **deterministic** = `uuid5(namespace, source_key +
  stable_id + occurred_at + event_type)`. Replay produces the same
  event_id ⇒ downstream dedup is trivial.
- Bus = Redis Streams (`XADD`); consumer groups for orchestrator /
  sentiment / retrain trigger.
- A nightly job snapshots the stream tail to
  `infra/freshness/events/<date>.jsonl` for cold replay.

---

## 10. Schema & extractor evolution

This is where most "build once, run forever" projects rot.

- **Extractor version is part of every record.** Bumping it doesn't
  rewrite history — old records keep their old version. The differ
  must be **tolerant of version mismatch**: if
  `old.extractor_version != new.extractor_version`, run a
  (registered) `migrator(old, target_version)` before diffing.
  Migrators are pure functions.
- **`canonical_version`** does the same job for the canonicalization
  rules. Changing alias rules ⇒ bump `CANONICAL_VERSION` ⇒ the
  differ refuses to diff across versions and instead emits
  `record.canonical_changed` once, then resumes.
- **No destructive migrations.** Re-canonicalizing history is opt-in
  via `make freshness.recanonicalize` which writes a new history line
  per record, never deletes.
- **Adding a new record type** = (1) add to `record_type` literal;
  (2) write extractor; (3) write differ; (4) write at least 3
  fixtures; (5) bump `content_freshness` minor version. PR template
  enforces this.

---

## 11. Failure modes, called out explicitly

| Mode | Detection | Reaction |
|---|---|---|
| Source returns 5xx | HTTP layer | Backoff + degraded tick. **No retraction events.** |
| Source soft-blocks (200 + Cloudflare HTML) | `source_watcher` already catches this; freshness agent listens for `source_watcher`'s `schema_breaking` events on the same key and pauses captures until human ack. | — |
| Extractor selector breaks (returns 0 records on a known-non-empty page) | `parser_diagnostics["records_per_target"]` baseline check | Degraded tick, alert; no retraction events |
| Clock skew (source publishes future timestamps) | Compare to local UTC + 24h tolerance | Tag record with `timestamp_anomaly=true`; do not let it shift kickoff comparisons |
| Duplicate stable_ids in one extraction | Detected at normalize step | Drop later duplicate, log, surface in diagnostics |
| Out-of-order capture (`captured_at` < latest in store) | Index check at write | Reject; no rewrite of history |
| Disk full | Write fails atomically; tick aborts | `source.degraded` event with reason; agent keeps trying capture+extract but skips persist |
| Index corruption | Reindex command rebuilds from FS | One CLI; runs cold |
| Bus down | Local on-disk WAL (`infra/freshness/wal/`) | Drain WAL on bus reconnect; events keep deterministic IDs so replay is safe |
| Process restart mid-write | `tmp + rename` atomicity + WAL | No partial state visible to readers |
| Two replicas race | Redis lease per `(source_key, target)` | Loser skips silently |

Every "Reaction" above must have a test that proves it.

---

## 12. Observability — non-negotiable

- **Metrics** (Prometheus naming, doctrine-compliant English keys):
  - `freshness_capture_total{source,target,status}`
  - `freshness_capture_duration_ms{source,target}` (histogram)
  - `freshness_records_extracted_total{source,record_type,status=ok|degraded}`
  - `freshness_events_emitted_total{event_type,source}`
  - `freshness_store_bytes{kind=raw|records}`
  - `freshness_lease_contention_total{source,target}`
  - `freshness_clock_skew_seconds{source}` (gauge)
- **Tracing**: one span per tick, child spans per `(capture, extract,
  normalize, diff, emit)`.
- **Per-source dashboard**: capture-success rate, time-to-detect
  (synthetic content injected into mock vhost ⇒ measure detection
  latency), event volume by type, degraded-tick rate.
- **Alerts** (default thresholds, all configurable):
  - Capture-success rate < 95% over 1h.
  - Zero events from a source over its expected cadence × 3.
  - `freshness_events_emitted_total{event_type="record.retracted"}`
    spike (potential identity-method regression).
  - Disk usage above 80% of cap.
- **Log shape**: structured JSON, one line per event emit, never
  stdout-dump raw HTML.

---

## 13. Configuration surface — single source of truth

Every tunable in [`ai/common/config.py`](../../ai/common/config.py),
every key documented in
[`xops/env/.env.example`](../../xops/env/.env.example). Naming
convention `NEGELIR_FRESHNESS_*`.

Mandatory keys (initial set):

```
NEGELIR_FRESHNESS_ENABLED=true
NEGELIR_FRESHNESS_PROFILE=mock|real                 # mock = read from infra/mock vhosts; aligns with NEGELIR_SCRAPE_PROFILE values
NEGELIR_FRESHNESS_HISTORY_KEEP_PER_RECORD=100
NEGELIR_FRESHNESS_RAW_KEEP_DAYS=30
NEGELIR_FRESHNESS_RETRACTION_GRACE_TICKS=3
NEGELIR_FRESHNESS_ARTICLE_BODY_DIFF_TOKENS=5
NEGELIR_FRESHNESS_ODDS_MIN_DELTA=0.05
NEGELIR_FRESHNESS_RATE_LIMIT_RPS_DEFAULT=0.5
NEGELIR_FRESHNESS_TIMEOUT_TOTAL_S=30
NEGELIR_FRESHNESS_BUS_STREAM=freshness.events.v1
NEGELIR_FRESHNESS_WAL_DIR=infra/freshness/wal
```

No magic numbers anywhere else. The `lint.py` rule that already
polices `ai/` extends to this package.

---

## 14. Testing strategy — three layers

1. **Pure-function unit tests** (fast, hermetic):
   - canonicalizer: 50+ team-name fixtures (Turkish unicode, alias
     rotations).
   - identity resolver: every strategy + the fallback chain.
   - per-type differs: every event-type has at least one
     `(old, new) → expected_events` table-test.
   - schema validators.

2. **Mock-vhost integration** (uses the existing Phase 2 stack):
   - Author seed corpus pairs in `infra/freshness/test_corpora/`
     (e.g., `mackolik_score_t0.html`, `mackolik_score_t1.html`).
   - End-to-end run: capture → extract → diff → emit; assert event
     stream matches a golden file.
   - Inject synthetic mutations (new article, score bump, lineup
     swap, retraction) by patching the vhost; verify detection
     latency.
   - **Adversarial fixtures** (per doctrine #7): truncated HTML,
     mojibake, identical-bytes-different-content,
     200-with-Cloudflare-page, time-zone trickery, alias collision.

3. **Long-running soak** (CI nightly, mock-only):
   - 24-hour simulated run with scripted source mutations every
     minute.
   - Assert: zero `record.retracted` false positives, zero crashes,
     bounded memory, bounded disk.

Test data is *never* fabricated production data — only synthetic
corpora committed under `tests/`.

---

## 15. What happens when a change is detected — system reaction

The freshness module **emits, never acts**. Side-effects belong to
named subscribers (the *reactors*), each of which owns one downstream
concern. This split is non-negotiable: the same event must produce
the same reactions whether replayed offline, fired by a soak test, or
dispatched by the live scheduler.

### 15.1 Event → reactor matrix

| Event | Severity | Reactor(s) | Side-effect (idempotent on `event_id`) | Latency budget |
|---|---|---|---|---|
| `fixture.added` | info | scheduler-reactor, feature-store-reactor | Schedule capture cadence for the new fixture; pre-allocate empty feature row | < 5s |
| `fixture.rescheduled` | warn | scheduler-reactor, alert-reactor | Re-arm capture cadence; notify ops if shift > 24h | < 5s |
| `fixture.cancelled` | warn | feature-store-reactor, predictor-reactor, alert-reactor | Mark fixture inactive; void any pending predictions; notify | < 10s |
| `score.first_seen` | info | live-predictor-reactor, cache-reactor | Spin up live-prediction loop for the match; warm Redis hot keys | < 2s |
| `score.changed` | info | feature-store-reactor, live-predictor-reactor | Update `current_score`/`minute`/`momentum_*`; re-run live predictor for **this match only** | < 2s |
| `score.events_updated` | info | feature-store-reactor, narrative-reactor | Append new goal/card/sub event; refresh narrative tags for this match | < 5s |
| `score.finalized` | info | trainer-reactor, evaluator-reactor, cache-reactor | Add row to retrain candidate set; record outcome for accuracy tracking; invalidate live-cache | < 30s |
| `lineup.published` | info | feature-store-reactor, predictor-reactor | Materialize lineup features (avg-age, missing-key-player, formation); re-run pre-match predictor | < 10s |
| `lineup.changed` | warn | feature-store-reactor, predictor-reactor, alert-reactor | Recompute lineup features; re-run predictor; notify if change inside KO − 30 min window | < 10s |
| `article.added` | info | nlp-reactor | Run sentiment/entity pipeline; store per-fixture sentiment vector | < 60s |
| `article.updated` | info | nlp-reactor | Re-run sentiment **only** for the updated body; replace prior vector for this `stable_id` | < 60s |
| `article.retracted` | warn | nlp-reactor, alert-reactor | Soft-delete sentiment row (kept for audit); notify | < 60s |
| `commentary.added` | info | nlp-reactor | Same as `article.added`, with `target_team`/`target_player` joins | < 60s |
| `commentary.updated` | info | nlp-reactor | Same as `article.updated` | < 60s |
| `odds.moved` | info | market-reactor, value-flag-reactor | Append to TimescaleDB hypertable; recompute implied-prob features; flag value if `\|model_p − implied_p\| > threshold` | < 1s |
| `odds.suspended` | warn | market-reactor, alert-reactor | Mark market suspended; pause value-flag for that selection | < 1s |
| `source.degraded` | warn | scheduler-reactor, alert-reactor, source-watcher | Drop cadence to 10× normal; notify; correlate with structural drift | < 10s |
| `record.retracted` | warn | feature-store-reactor, alert-reactor | Soft-delete; **never** hard-delete (audit trail) | < 30s |

### 15.2 Reactor invariants (apply to every row above)

1. **Idempotent on `event_id`.** A reactor that has already acted on
   a given `event_id` is a no-op. Backed by a per-reactor processed-
   events table (`reactor_state.processed`).
2. **Plane-bounded blast radius.** A `score.changed` event for match
   `M` must only touch `M`'s features and `M`'s live predictor.
   Cross-match recomputation is forbidden at the reactor layer; it is
   a separate scheduled job.
3. **No reactor calls the scrapers.** Reactors read from the snapshot
   store (via the freshness agent's `payload_ref`) and from Postgres.
   They never trigger a fetch — only the scheduler does.
4. **No reactor emits events back to `freshness.events.v1`.**
   Reactor-emitted events go on dedicated streams
   (`features.updated.v1`, `predictions.refreshed.v1`,
   `alerts.fired.v1`) so the freshness agent's input is never its own
   output (no feedback loops).
5. **Bounded rework window.** A reactor may re-process events older
   than `REACTOR_REPLAY_WINDOW` (default 24h) only via an explicit
   `make reactor.replay` command — never automatically on restart.
6. **Failure isolation.** A reactor failure does not block other
   reactors. Each runs in its own consumer group; a stuck reactor
   triggers `reactor.degraded` after `N` consecutive failures.

### 15.3 The trainer reactor — special handling

The trainer is the most expensive reactor. Its behaviour is spelled
out separately because "retrain on every event" would be wasteful.

- **Debounce window:** events are aggregated into a sliding
  `RETRAIN_DEBOUNCE` window (default 30 min). The window resets on
  each new qualifying event.
- **Qualifying events:** `score.finalized`, `lineup.changed` (only
  before kickoff), `dataset.recomposed` (emitted by the operator
  when historical seeds change). Article/commentary/odds events do
  **not** qualify on their own.
- **Decision rule:** retrain fires when EITHER (a) ≥ N qualifying
  events accumulate in the window (`RETRAIN_MIN_EVENTS`, default 5)
  OR (b) the per-league accuracy on a holdout slice drops below
  `RETRAIN_ACCURACY_FLOOR` (default 0.55) — whichever comes first.
- **Cooldown:** after a retrain, no new retrain may fire for
  `RETRAIN_COOLDOWN` (default 6h) regardless of event volume.
- **Output:** publishes `model.trained` on `models.events.v1` with
  the new model SemVer. Predictors hot-swap on receipt; old model
  versions are kept for comparison until the next bump.

### 15.4 The reactor configuration surface

Every reactor's tunables live in `ai/common/config.py` under the
`NEGELIR_REACTOR_*` prefix. Mandatory keys (initial set):

```
NEGELIR_REACTOR_REPLAY_WINDOW_HOURS=24
NEGELIR_REACTOR_DEGRADED_AFTER_FAILURES=5
NEGELIR_REACTOR_RETRAIN_DEBOUNCE_MIN=30
NEGELIR_REACTOR_RETRAIN_MIN_EVENTS=5
NEGELIR_REACTOR_RETRAIN_ACCURACY_FLOOR=0.55
NEGELIR_REACTOR_RETRAIN_COOLDOWN_HOURS=6
NEGELIR_REACTOR_LIVE_PREDICTOR_MAX_RPS=20
NEGELIR_REACTOR_NLP_MAX_CONCURRENCY=4
```

### 15.5 What the freshness agent itself does **not** do

- It does **not** call the trainer.
- It does **not** invalidate caches.
- It does **not** write to Postgres `matches`/`features`/`outcomes`.
- It does **not** notify users.
- It does **not** decide whether a change is "important enough to act
  on" beyond the per-type differ thresholds in §7. Importance is the
  reactor's call.

This separation is the reason the freshness agent is small,
deterministic, and replayable.

### 15.6 Bidirectional links with the Source-Watcher

- Freshness agent **subscribes** to `source_watcher.schema_breaking`
  and pauses captures for the affected source until human ack.
- `source_watcher` **subscribes** to freshness agent's
  `source.degraded` to escalate severity (a structural drift that
  also degrades freshness is a P1; a structural drift alone is P3).

---

## 16. Phased delivery (each phase shippable on its own)

> **Phase numbering convention.** The `F1`–`F9` labels below are
> **freshness-internal** sub-phases of the agent’s own delivery; they
> are **not** the same as ROADMAP Phase 3.x (Swarm Foundation — bus,
> registry, supervisor) or Phase 4.x (Core Worker Agents). The
> roadmap-level entry points for this work are
> **ROADMAP §3** (the agent ships against the bus and SDK from there)
> and **ROADMAP §4.7** (the reactor SDK + the trainer / live-predictor
> reactors land there). Within those phases, ship in the F1–F9 order
> below.

| Sub-phase | Scope | Done when |
|---|---|---|
| **F1** Skeleton | Package layout, schemas, config, identity resolver, canonical rules, snapshot store, in-memory bus, no extractors yet | Unit tests green; `make freshness.reindex` works on empty store |
| **F2** First source | Mackolik fixture+score extractors only; mock-vhost integration tests; events to Redis stream | Detection latency < 60s in mock soak; zero false retractions in 24h run |
| **F3** Article + commentary | Mackolik articles + commentary extractors; sentiment hookup | Sentiment writes keyed by event_id are idempotent on replay |
| **F4** Multi-source | TFF + openfootball + (read-only) Nesine odds | Per-source dashboards live |
| **F5** Live cadence | `during_match` cadence based on fixture state | Tightening + relaxing demonstrated in soak |
| **F6** Hardening | WAL, lease, multi-replica, alerts | Chaos test: kill -9 mid-tick produces no orphans |
| **F7** Reactor SDK + first reactors | Reactor base class (idempotent on `event_id`, per-reactor consumer group, processed-events table); ship `feature-store-reactor` + `cache-reactor` first | Reactor invariants in §15.2 hold under chaos test |
| **F8** Trainer reactor | Debounce window, qualifying-event filter, accuracy-floor check, cooldown (§15.3) | Synthetic finalized match → retrain kicked within debounce + cooldown limits |
| **F9** NLP + predictor + market reactors | Wire `nlp-reactor`, `live-predictor-reactor`, `market-reactor` per §15.1 | End-to-end soak: every event class produces its mapped side-effect within latency budget |

Each freshness sub-phase ships its own version bump on the
`datasource_refresher` component in
[`xops/versioning/chart.json`](../../xops/versioning/chart.json) (the
chart key chosen by [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) §5 —
*not* a separate `content_freshness` key), and one tracker row per
shipped sub-phase per AGENTS.md §3.

---

## 17. Open decisions — please pin these before any code

These are forks in the road; whichever way you go is fine, but they
must be **decided** so the code is not ambiguous later.

1. **Bus**: Redis Streams (already in stack) vs. NATS / Kafka.
   Recommendation: Redis Streams for v1 — it's already there, scales
   to project's foreseeable volume, and consumer groups give the
   dedup we need.
2. **Identity for articles when no upstream ID**: URL canonical only,
   or URL + title fingerprint? Recommendation: **both**, with URL
   primary; fingerprint used as a tiebreaker and to detect
   URL-rotation (emit `article.url_rotated` event).
3. **Article body diff metric**: token-Levenshtein vs. cosine over
   TF-IDF vs. simhash. Recommendation: **simhash with Hamming
   distance ≤ 3 = no event** — bounded, deterministic, fast, no
   model.
4. **Retraction grace window**: ticks vs. wall-clock. Recommendation:
   wall-clock (e.g., 6h), because cadence varies per target.
5. **History retention**: per-record cap vs. age cap vs. both.
   Recommendation: both (`max(N records, M days)`), so a hot record
   keeps recent history and a cold one keeps a minimum.
6. **Multi-replica from day 1**: yes/no. Recommendation: design for
   it (lease + idempotency from the start) but ship single-replica
   until volume demands it.
7. **Encrypted at rest**: needed? Recommendation: not for v1 —
   content is public web data — but the snapshot store path is
   configurable so an ops-level disk encryption layer is possible
   later.
8. **Where the agent runs**: own container vs. inside the AI
   container. Recommendation: own container (per Pivot v3 the service
   is named `refresher` under the `datasource` compose profile — see
   [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) §4) —
   different cadence, different blast radius, independent restarts.

---

## 18. What to build first if approved

> **Path note.** The package directory below uses the **post-Pivot v3**
> layout (`datasource/refresher/`, per
> [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) §3). During the R2/R3
> migration window the work may temporarily land at
> `ai/swarm/content_freshness/` behind the same shim policy that
> covers the source-watcher move. The contracts in §§1–15 are
> path-independent.

Strict order, each step independently testable:

1. `datasource/refresher/` package skeleton + `schemas.py` +
   `canonical.py` (with unit tests).
2. `identity.py` resolver + alias table + tests against a Turkish-name
   corpus.
3. `snapshot_store.py` (raw + records) + `index.py` SQLite +
   `make freshness.reindex`.
4. `differ/` per-record modules + golden-file tests.
5. `extractors/mackolik/score.py` and a fixture pair under mock
   seeds.
6. `scheduler.py` + lease + cadence + jitter (re-using
   `source_watcher.scheduler` patterns).
7. `bus.py` (Redis Streams) + `wal.py` (file fallback) +
   dedup-by-event-id test.
8. `make freshness.run` (one-shot) and `make freshness.up` (loop, in
   container).
9. Soak harness in `datasource/refresher/tests/soak/`.

Everything else (more sources, sentiment hookup, retrain trigger) is
a clean addition on top of the above, because the contracts above are
stable.

---

## 19. Relationship to the Source-Watcher Agent

| Concern | Source-Watcher | Content-Freshness |
|---|---|---|
| Detects | Structural / schema drift, soft-blocks, status flips, mass truncation, hash-at-identical-bytes | New / changed real-world content (fixtures, scores, articles, commentary, odds) |
| Reads from | `infra/mock/seeds/` (the captured snapshot corpus) | Live upstreams (or mock vhosts under `NEGELIR_FRESHNESS_PROFILE=mock`) |
| Diffing model | One probe envelope per HTML target (`_raw_len`, `_sha256`, `_status`) + structural JSON diff | Typed records with stable identity, per-type diff rules |
| Output | Severity (cosmetic / semantic / schema_breaking) + `UpdatePlan` | Typed event stream on Redis with deterministic event_ids |
| LLM use | Narration only (Phase 8); never overrides rules | None in v1; sentiment runs as a downstream consumer |
| Cadence | On demand (`make watch.run`) | Continuous, per-target |
| Cross-talk | Subscribes to `content_freshness.source.degraded` to escalate severity | Subscribes to `source_watcher.schema_breaking` to pause captures |

Both agents must remain **separate processes**. Mixing "did the page
structure change?" with "is there new content today?" into one agent
makes both jobs harder to test and harder to operate.
