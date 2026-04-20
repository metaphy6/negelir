# Data Pipeline — Scrape → Process → Train → Serve

> **Status:** Active reference. Describes *what* the project ingests, *how*
> it's transformed, and *why* each piece exists. Anchors every design doc
> that mentions "the data" (CONTENT_FRESHNESS, MOCK_DATA_SERVER, SWARM,
> ARCHITECTURE).
> **Audience:** Anyone wondering "what does Negelir actually feed its
> AI?". If this doc and code disagree, code wins and this doc gets a
> patch in the same commit.
> **Doctrine:** AGENTS.md §2 rules 1, 3, 5, 6.
> **Pivot v3 addendum:** Under Phase 16+, Postgres/Redis are no longer the swarm's read surface. The swarm reads **feeds** emitted by `datasource/emitter`. The Record contract in §4 is still canonical; the emitter just lifts it to per-plane NDJSON/Parquet files. See [`EMITTER.md`](EMITTER.md) for the on-wire format and [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) for the producer/consumer boundary.

The project answers Turkish-language football questions using models
trained on **public** football data. This file fixes the scope of "the
data" once and refers everything else to it.

---

## 1. The five data planes

We split everything we touch into five planes. **Each plane has a
different shape, lifetime, refresh cadence, and consumer.** Conflating
them is the #1 cause of accidentally retraining on yesterday's lineup
or serving last week's odds.

| # | Plane | Examples | Mutability | Cadence | Primary consumer |
|---|---|---|---|---|---|
| 1 | **Reference** | Teams, players, venues, leagues, seasons, competitions | Slow-changing (transfers, renames) | Daily–weekly | Joins, identity resolution |
| 2 | **Schedule** | Fixtures, postponements, kick-off times, referees | Slow until match-week, then volatile | Hourly → minutes near KO | Pipeline scheduler, predictor input |
| 3 | **Live** | Score, period, minute, goal/card/sub events, lineup confirmation | Per-second during match | Seconds–minutes | Live predictor, alert agent |
| 4 | **Editorial** | News articles, columns, transfer rumours, commentator takes | Append-mostly, occasional edits | Minutes–hours | Sentiment / NLP, narrative features |
| 5 | **Market** | Bookmaker odds, pre-match + in-play, suspensions | Continuous tick | Seconds | Calibration, value-flag agent |

Every record we store carries a `plane` tag and the rules for *what
counts as a change*, *what counts as fresh*, and *who is allowed to
overwrite it* are defined per-plane (see §6 and CONTENT_FRESHNESS).

---

## 2. Sources and what each one supplies

The four sources are the only upstreams we touch. Mock vhosts mirror
them 1:1 so dev / CI / prod read the *same* extractor code.

| Source | Real domain | Mock vhost | Planes covered | Notes |
|---|---|---|---|---|
| **Mackolik** | mackolik.com | `mackolik.local` | Reference, Schedule, Live, Editorial | Primary TR-language source; richest live coverage |
| **Nesine** | nesine.com | `nesine.local` | Schedule, Market | Bulletin + odds; the canonical TR betting catalogue |
| **TFF** | tff.org | `tff.local` | Reference, Schedule | Authoritative for fixture IDs, referees, official renames |
| **OpenFootball** | github.com/openfootball | `openfootball.local` | Reference (historical) | YAML/JSON dumps; bootstraps team & season tables |

`xops/mock/sources.py` is the single registry. Adding a fifth source
means: add a row there, capture seeds via `make mock.capture`, write
an extractor (§4), write differs (CONTENT_FRESHNESS §7) — never
touching scraper call-sites.

> **Doctrine reminder.** AGENTS.md rule 3: tests and dev *must* read
> from the mock vhosts (`NEGELIR_SCRAPE_PROFILE=mock`). Real upstreams
> are only contacted by `make mock.capture`, which is rate-limited
> and respects `robots.txt`.

---

## 3. End-to-end flow

```
            ┌────────────────────────────────────────────────────────┐
            │                  REAL  INTERNET                        │
            │  (mackolik · nesine · tff · openfootball)              │
            │  ↑ touched ONLY by `make mock.capture` (rate-limited)  │
            └────────────────────────────────────────────────────────┘
                              │
                              ▼  bytes (HTML/JSON) + headers
            ┌────────────────────────────────────────────────────────┐
            │              SEED CORPUS (frozen)                      │
            │  infra/mock/seeds/{<host>/<path>.{html,json,headers}}  │
            │  + manifest.json (sha256, captured_at, status)         │
            └────────────────────────────────────────────────────────┘
                              │
                              ▼  served byte-for-byte over fake TLS
            ┌────────────────────────────────────────────────────────┐
            │  nginx-mock + mocksrv  →  https://*.local/             │
            └────────────────────────────────────────────────────────┘
                              │
                              ▼  identical scraper code path
        ╔═══════════════════════════════════════════════════════════╗
        ║                  PIPELINE (per source)                    ║
        ║                                                           ║
        ║  ① CAPTURE    raw bytes + status + headers + ts           ║
        ║         │                                                 ║
        ║         ▼                                                 ║
        ║  ② EXTRACT   bytes → list[Record]   (per-plane schemas)   ║
        ║         │                                                 ║
        ║         ▼                                                 ║
        ║  ③ NORMALIZE record → record (canonical names, UTC, IDs)  ║
        ║         │                                                 ║
        ║         ▼                                                 ║
        ║  ④ DIFF      (old, new) → list[RecordEvent]               ║
        ║         │                                                 ║
        ║         ▼                                                 ║
        ║  ⑤ EMIT      RecordEvent → Redis Streams (freshness.*)    ║
        ╚═══════════════════════════════════════════════════════════╝
                              │
                ┌─────────────┼──────────────┬─────────────────┐
                ▼             ▼              ▼                 ▼
         ┌───────────┐ ┌──────────────┐ ┌──────────┐ ┌─────────────┐
         │ STORAGE   │ │ FEATURE      │ │ NLP /    │ │ TRAINER     │
         │ (Postgres)│ │ STORE (cache)│ │ SENTIMENT│ │ (gated by   │
         │ matches,  │ │ per-fixture  │ │ per      │ │  events;    │
         │ lineups,  │ │ feature row  │ │ article  │ │  not byte   │
         │ odds, …   │ │              │ │          │ │  delta)     │
         └─────┬─────┘ └──────┬───────┘ └────┬─────┘ └──────┬──────┘
               └──────────────┴──────┬───────┴──────────────┘
                                     ▼
                          ┌─────────────────────┐
                          │ PREDICTOR SWARM     │
                          │  → consensus        │
                          │  → calibrated p     │
                          └──────────┬──────────┘
                                     ▼
                              Go REST API (Phase 9)
                                     ▼
                              Flutter client
```

The whole left half (everything down to ⑤) is the same code in
mock and prod — only `NEGELIR_SCRAPE_PROFILE` flips the resolver
between `*.local` and the real hosts.

---

## 4. The Record contract — what the AI actually sees

Every plane's bytes are normalized into the same `Record` envelope
before anything downstream looks at them. Defined in
`ai/common/schemas/records.py` (Phase 4).

```python
class Record(TypedDict):
    record_type: Literal[
        "team", "player", "venue", "competition", "season",          # plane 1
        "fixture",                                                    # plane 2
        "score", "lineup",                                            # plane 3
        "article", "commentary",                                      # plane 4
        "odds",                                                       # plane 5
    ]
    plane: Literal["reference", "schedule", "live", "editorial", "market"]
    source_key: str                  # "mackolik" | "nesine" | "tff" | "openfootball"
    upstream_id: str | None          # source-native ID when available
    stable_id: str                   # what the rest of the system joins on
    captured_at: str                 # ISO-8601 UTC (envelope clock)
    occurred_at: str | None          # event-time when the source dates it
    extractor_version: str           # e.g. "mackolik.fixture@3"
    canonical_version: str           # bumps with alias / TZ rule changes
    payload: dict                    # plane-specific schema (see CONTENT_FRESHNESS §3)
    raw_ref: str                     # path into the snapshot store for byte-replay
```

**Hard rules:**

1. `stable_id` is computed by the identity strategy (CONTENT_FRESHNESS
   §2). Once minted for a record, it never changes.
2. The `payload` schema per `record_type` is the single source for
   "what features can be derived". Trainers/feature-stores must not
   read fields outside `payload`.
3. `extractor_version` and `canonical_version` travel with every
   record forever. Re-canonicalizing history is opt-in, never
   automatic.

---

## 5. From Record to AI — three feed-forward paths

A normalized `Record` is consumed in three independent ways. Mixing
them is what blurs "training data" with "live input" and creates leaky
features.

### 5.1 Training feed (offline, replayable)

- **Source:** Postgres `matches`, `lineups`, `outcomes` tables built
  from historical `Record`s with `record_type ∈ {fixture, score,
  lineup}` whose `payload.status == finished`.
- **Cut-off discipline:** every training row has an `as_of_utc`. A
  feature for fixture `F` can only use records with
  `captured_at ≤ as_of_utc < kickoff(F)`. Enforced by
  `ai/model/features.py` and tested with leakage probes.
- **Cadence:** retraining is **event-gated**, not time-gated. The
  trainer wakes on `score.finalized`, `fixture.cancelled`, or
  `dataset.recomposed` events from CONTENT_FRESHNESS — never on a
  cron tick. This is how Phase 6 (drift) avoids retraining loops.

### 5.2 Inference feed (online, append-only)

- **Source:** the latest non-degraded `Record` per
  `(record_type, stable_id)` — read from the Redis-backed feature
  store, not from Postgres directly.
- **Live planes only update narrow features:** a `score.changed`
  event refreshes `current_score`, `minute`, `momentum_*`; it does
  *not* trigger feature re-derivation for any other fixture.
- **Editorial / market planes:** sentiment scores and odds-implied
  probabilities are precomputed by their respective agents and stored
  as features, never re-read inline by the predictor.

### 5.3 NLP feed (Turkish UX)

- **Source:** `record_type ∈ {article, commentary}` with
  `payload.body_text` already cleaned by the extractor (no nav, no
  ads — see CONTENT_FRESHNESS §3).
- **Pipeline:** sentiment → entity linking → narrative tags → stored
  as a per-fixture feature vector. Inputs to the user-facing answer
  generator (Phase 10) come *only* from this feed; raw scrapes never
  reach the LLM.

---

## 6. Per-plane storage, retention, and "what counts as a change"

| Plane | Storage | Retention | Counts as change when… | Does **not** count as change when… |
|---|---|---|---|---|
| Reference | Postgres `teams`, `players`, `venues`; OpenFootball seed | Forever (slow journal table) | Canonical name moves, transfer event, new venue | Casing, whitespace, alias-table refresh |
| Schedule | Postgres `fixtures` + Redis index | Forever (audit trail of moves) | `kickoff_utc` shifts > 5 min, `status` flips | Page reorder, ad rotation, byte-noise |
| Live | Redis hot, Postgres `score_events` cold | 90 days hot, forever cold | Numeric score delta, new event in `events[]`, `status` → `finished` | Re-render of the same minute, ticker reorder |
| Editorial | Postgres `articles`, body in object store | 365 days online, then S3-cold | `body_sha256` differs **and** token-Levenshtein on cleaned text > N | Whitespace, cookie banner, byline reformat |
| Market | TimescaleDB hypertable (Phase 5 prerequisite) | 30 days at tick resolution, forever at 1-min downsample | Decimal-odds delta > per-market threshold, `is_suspended` flip | Bookmaker reordering, header refresh |

The "counts as change" column is the *exact* contract enforced by the
per-plane differs in CONTENT_FRESHNESS §7. Anything else — a byte
flip, a CDN reshuffle, a CSS-class rename — is **not** a content
change and must not propagate.

---

## 7. Identity, joins, and why this is hard

The whole pipeline is a tree of joins on `stable_id`:

- `score.match_stable_id` joins the live plane to the schedule plane.
- `lineup.match_stable_id` joins lineups to fixtures.
- `commentary.target_team` joins editorial sentiment to the reference
  plane.
- `odds.match_stable_id` joins markets to fixtures.

If `stable_id` is wrong **once**, the join produces phantom records
forever. The identity strategy (upstream ID > composite > URL >
fingerprint) is therefore the most-tested code path in the project.
See CONTENT_FRESHNESS §2 for the exhaustive rules.

---

## 8. What we explicitly do **not** scrape

Documenting non-goals is doctrine (AGENTS.md §2 rule 3).

- **Social media (Twitter/X, Reddit, Discord).** No API access we can
  reproduce in CI; rate limits don't fit the mock model; sentiment
  signal is noisy without identity-graph work that's out of scope.
- **Closed odds APIs.** We read the public bulletin from Nesine; we
  do not embed paid feeds.
- **Player-tracking data (xG, sprint maps, heatmaps).** Not exposed
  on the four sources; would require StatsBomb / Wyscout licences.
- **Live video streams.** Out of scope by definition.
- **User-generated content (forum posts, comments).** Identity and
  abuse risk too high for this phase.

If a future phase needs any of the above, it gets its own roadmap
phase, its own mock vhost, and its own extractor — never bolted onto
an existing source.

---

## 9. Where this document is enforced

- `xops/mock/sources.py` — source registry; CI fails if §2 of this
  doc lists a source not present there (and vice versa).
- `ai/common/schemas/records.py` — Record envelope; `record_type`
  literals must match §1's plane table (lint check).
- `ai/model/features.py` — leakage probe asserts §5.1's cut-off
  discipline.
- CONTENT_FRESHNESS.md §3 — payload schemas referenced by §4 here.
- MOCK_DATA_SERVER.md — implementation of the seed corpus referenced
  by §3 here.

---

## 10. Reading order for new contributors

1. **This doc** (you are here) — *what* the data is.
2. [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) — *which component owns which step* (Pivot v3).
3. [`MOCK_DATA_SERVER.md`](MOCK_DATA_SERVER.md) — *how* we get it
   without hitting the real internet.
4. [`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md) — *when* we say a
   record changed and what to do about it.
5. [`EMITTER.md`](EMITTER.md) — *how* the swarm reads the data (Pivot v3).
6. [`SCRAPER_PATCHER.md`](SCRAPER_PATCHER.md) — *what* happens when a source breaks (Pivot v3).
7. [`SWARM.md`](SWARM.md) — *who* (which agents) does each step.
8. [`ARCHITECTURE.md`](ARCHITECTURE.md) — *where* it all runs.

---

## 11. Emitter handoff (Pivot v3)

Phase 16 introduces a **Record → Feed** boundary. Everything described
in §§3–5 of this document up to "inserted/upserted into Postgres"
stays identical. What changes is how the swarm *reads* that state.

| Before Phase 16 | Phase 16 onward |
|---|---|
| Swarm predictors read Postgres with `psycopg` | Swarm predictors call `common.feeds.FeedReader.stream(...)` |
| Trainers run SQL windows against a replica | Trainers call `FeedReader.snapshot(plane=..., as_of=...)` and get Parquet partitions |
| Schema drift is found at query time | Schema drift is impossible: each Record is written through a `common/schemas/feeds/*.json` validator with an explicit `record_version` |
| Moving the swarm to another environment required a Postgres dump | Moving the swarm requires copying one S3 prefix |

**The Record contract from §4 is unchanged.** The emitter is a lossless
projection: `db_row → Record(envelope+payload) → NDJSON line` and
`hour_of_records → Parquet partition`. See [`EMITTER.md`](EMITTER.md)
§§3, 5, 6 for the on-disk format, versioning rules, and writer
semantics.

Enforcement:

- `test_swarm_isolation.py` — grep gate: `swarm/**/*.py` files cannot
  import `psycopg`, `redis`, or any `datasource.*` module.
- `test_emitter_is_lossless.py` — round-trip test: emit a day's
  Records, read them back through `FeedReader`, assert byte-for-byte
  equality with the Postgres snapshot for the same window.
- `test_snapshot_equals_stream.py` — the Parquet snapshot for an hour
  equals the union of NDJSON lines in that hour (modulo encoding).
