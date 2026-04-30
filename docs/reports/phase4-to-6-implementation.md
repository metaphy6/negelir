# Phase 4 → 6 — Fresh-Eye Implementation Audit & Forward Roadmap

> **Status:** *Audit only — no code, tracker rows, or version bumps
> have been written. Action items in §7 are proposals pending human
> approval.*
> **Auditor brief:** treat the codebase as unknown; verify Phase 4
> (core worker agents), Phase 5 (predictor swarm + consensus), and
> Phase 6 (proofreader + drift) on three axes:
> 1. **Assumption** — does the design in `ROADMAP.md` actually fit
>    the rest of the system?
> 2. **Implementation** — does the code on disk match that design?
> 3. **Action** — for any drift, **fix or revert**?
>
> Methodology: read every binding doc anchor (`AGENTS.md`,
> `ROADMAP.md` §§4–6, `docs/design/SWARM.md`,
> `DATA_PIPELINE.md`, `CONTENT_FRESHNESS.md`), then read every
> Phase 4–6 agent module under [ai/swarm/agents/](../../ai/swarm/agents),
> the topic + payload + schema layer, the bootstrap, the cfg triangle
> ([ai/common/config.py](../../ai/common/config.py),
> [ai/common/defaults.yaml](../../ai/common/defaults.yaml),
> [xops/env/.env.example](../../xops/env/.env.example)), and the
> swarm test suite. Then run `pytest ai/swarm/agents/tests` to
> establish ground truth, and run a targeted Python repro for the
> one suspected contract violation.

---

## 0. Verdict at a glance

| Phase | Assumption | Implementation | Severity of open drifts |
|---|---|---|---|
| 4 — Core worker agents | ✅ correct | ✅ matches design | **NIT** (one stale comment) |
| 5 — Predictor swarm + consensus | ✅ correct | ✅ matches design | none |
| 6 — Proofreader + drift | ✅ correct | ⚠ **one cross-phase contract violation** | **BLOCKER** ×1, MINOR ×1 |

**Headline:** the implementation is generally tighter than the
ROADMAP narrative — many micro-audits already shipped (F-1 through
F-10, F2-1..F2-4, F3-1..F3-3, A1..A5, P1, etc.) and the Phase 4–6
test suite is at **387 passing / 0 failing** on 2026-04-30. **One
real bug** survived the prior audit passes: the `score_grid` shape
emitted by `pred.dixon_coles.v1` and `pred.xgb_xg.v1` is
**incompatible** with the shape that
`grid_consistency_check` expects, so every `predict.final` that
carries a real Poisson grid is **fatally rejected** by the
consistency proofreader in production. No end-to-end test exercises
the real predictor → consensus → proofreader path with a grid-bearing
vote, which is why the regression hid. See **B1** in §3.

---

## 1. Scope and method

### 1.1 What this audit covers

- **Phase 4** sub-sections 4.1 – 4.7 per
  [docs/planning/ROADMAP.md](../planning/ROADMAP.md): scrape topics,
  scrapers per source, categorizer, processors, storage, cache,
  telemetry, freshness events.
- **Phase 5** sub-sections 5.1 – 5.6: predictor base / context,
  six concrete predictors, consensus fusion, calibration store
  protocol, swarm-backtest harness, single-replica invariants.
- **Phase 6** sub-sections 6.1 – 6.4: proofreader replicas + check
  rules, aggregator + quorum, `predict.approved.v1` contract,
  drift detector + maintenance events.

### 1.2 What this audit does **not** cover

- Phase 9 (Postgres-backed Ledger / CalibrationStore / RecordStore)
  — only the **protocol seams** are checked here.
- Phase 14 (multi-replica leader-election) — only the
  single-instance invariant guard is checked here.
- Phase 16 (datasource emitter feeds) — only the boundary contract
  with Phase 4 storage/freshness is checked here.

### 1.3 Files read in full

Agent modules: [`scraper/_base.py`](../../ai/swarm/agents/scraper/_base.py),
[`categorizer.py`](../../ai/swarm/agents/categorizer.py),
[`processor.py`](../../ai/swarm/agents/processor.py),
[`storage.py`](../../ai/swarm/agents/storage.py),
[`cache.py`](../../ai/swarm/agents/cache.py),
[`telemetry.py`](../../ai/swarm/agents/telemetry.py),
[`reactor.py`](../../ai/swarm/agents/reactor.py),
[`consensus.py`](../../ai/swarm/agents/consensus.py),
[`drift.py`](../../ai/swarm/agents/drift.py),
[`proofreader/aggregator.py`](../../ai/swarm/agents/proofreader/aggregator.py),
[`proofreader/replicas.py`](../../ai/swarm/agents/proofreader/replicas.py),
[`proofreader/prediction_checks.py`](../../ai/swarm/agents/proofreader/prediction_checks.py),
[`predictors/_grid.py`](../../ai/swarm/agents/predictors/_grid.py),
[`predictors/dixon_coles.py`](../../ai/swarm/agents/predictors/dixon_coles.py),
[`predictors/xgb_form.py`](../../ai/swarm/agents/predictors/xgb_form.py),
[`bootstrap.py`](../../ai/swarm/bootstrap.py),
[`topics.py`](../../ai/swarm/agents/topics.py).

Wire layer:
[ai/swarm/sdk/schemas/predict.vote.json](../../ai/swarm/sdk/schemas/predict.vote.json),
[predict.final.json](../../ai/swarm/sdk/schemas/predict.final.json),
[predict.approved.v1.json](../../ai/swarm/sdk/schemas/predict.approved.v1.json).

Cfg triangle:
[ai/common/config.py](../../ai/common/config.py) (lines 320–650),
[ai/common/defaults.yaml](../../ai/common/defaults.yaml) (Phase 4–6 section),
[xops/env/.env.example](../../xops/env/.env.example) (lines 215–260).

Tests sampled:
[`tests/test_prediction_checks.py`](../../ai/swarm/agents/tests/test_prediction_checks.py),
[`tests/test_proofreader_replicas.py`](../../ai/swarm/agents/tests/test_proofreader_replicas.py),
[`tests/test_consensus.py`](../../ai/swarm/agents/tests/test_consensus.py),
[`tests/test_phase5_swarm_demo.py`](../../ai/swarm/agents/tests/test_phase5_swarm_demo.py),
[`tests/test_phase6_bug_fixes.py`](../../ai/swarm/agents/tests/test_phase6_bug_fixes.py),
[ai/swarm/tests/test_bootstrap.py](../../ai/swarm/tests/test_bootstrap.py).

### 1.4 Severity scale

| Tag | Meaning |
|---|---|
| **BLOCKER** | Production correctness issue. Must be fixed before next phase. |
| **MAJOR** | Silent contract drift; latent bug that will bite at scale or under load. |
| **MINOR** | Implementation works but documentation, naming, or telemetry is misleading. |
| **NIT** | Cosmetic / stale-comment / typo. |

### 1.5 Ground truth

```
$ PYTHONPATH=ai pytest ai/swarm/agents/tests -q
... 387 passed in 4.26s
```

The bug surfaced in §3 (B1) is **not** caught by any of these 387
tests — see B1.4 for the smallest reproducer the audit ran by hand.

---

## 2. Phase 4 — Core worker agents

### 2.1 Topics catalogue ([`topics.py`](../../ai/swarm/agents/topics.py))

**Assumption:** ROADMAP §3.5 lists every Phase-4 topic as
`scrape.request`, `scrape.raw`, `scrape.classified`,
`match.normalized`, `match.stored`, `freshness.events.v1`,
`proof.flag`, `telemetry`. Plus the Phase 5/6 control topics
(`predict.*`, `match.outcome.v1`, `models.events.v1`,
`maint.event.v1`).

**Implementation:** all 14 topic constants present and named
exactly per ROADMAP §3.5; `MATCH_OUTCOME` is correctly versioned
`match.outcome.v1` (not the historical `match.outcome` to keep
schema migration deterministic).

**Verdict:** ✅ **correct, no action.**

### 2.2 Scraper base ([`scraper/_base.py`](../../ai/swarm/agents/scraper/_base.py))

**Assumption (ROADMAP §4.2):** one scraper agent per source
(mackolik, nesine, tff, openfootball); per-source token-bucket
rate limit; mock vs real profile resolution via
`cfg.scrape_profile`; 404 → `proof.flag` (`UPSTREAM_MISSING`); 5xx
→ raise (DLQ via runner retry budget). No global `requests` import
(lazy resolution so unit tests don't need network).

**Implementation:** matches doctrine line for line.

- `_next_allowed_at` per (source) token bucket using
  `cfg.scrape_rate_limit` ([`_base.py:71-103`](../../ai/swarm/agents/scraper/_base.py#L71-L103)).
- 404 emits `PROOF_FLAG{kind=UPSTREAM_MISSING}` rather than raising
  ([`_base.py:131-156`](../../ai/swarm/agents/scraper/_base.py#L131-L156)) — this is the documented
  "expected miss" path (e.g. cancelled fixture URL).
- 5xx **does** raise; the runner's retry budget + DLQ swallow it.
  Never returns synthetic bytes (Rule 3).
- Lazy `_RealFetchClient` for `requests` — unit tests pass
  without `requests` installed.
- All four concrete scrapers (mackolik / nesine / tff /
  openfootball) are 10-line declarative shells over the base.

**Verdict:** ✅ **correct.** No action.

### 2.3 Categorizer ([`categorizer.py`](../../ai/swarm/agents/categorizer.py))

**Assumption (ROADMAP §4.3):** rule-based deterministic classifier
that labels `scrape.raw` payloads into
`{fixture_list, match_detail, lineup, odds, irrelevant}`; below
a confidence floor → emit `PROOF_FLAG`; pluggable seam for a
LinearSVC swap (Phase 8).

**Implementation:**

- Priority-ordered keyword + URL rules; JSON content-type heuristic
  for openfootball ([`categorizer.py:57-138`](../../ai/swarm/agents/categorizer.py#L57-L138)).
- `LOW_CONFIDENCE_CLASSIFICATION` and `EMPTY_PARSE` /
  `DECODE_FAILED` flags are **distinct** kinds — operators can
  triage them independently.
- `set_model()` hook present but unused; `cfg.categorizer_min_conf`
  drives the floor with no fallback constant.

**Verdict:** ✅ **correct.** No action.

### 2.4 Processors ([`processor.py`](../../ai/swarm/agents/processor.py))

**Assumption (ROADMAP §4.4):** per-record-type processors
(fixture, match_detail, lineup, odds) consume `scrape.classified`,
emit `match.normalized` Records carrying a stable `extractor_version`
and a stable `_id`. Phase 4 deliberately ships toy regex parsers;
real per-source extractors are out of scope here (Phase R1
datasource pivot).

**Implementation:**

- `EXTRACTOR_VERSION = "phase4.v1"` ([`processor.py:32`](../../ai/swarm/agents/processor.py#L32))
  — stable string per ROADMAP §3.7 versioning rule.
- `_stable_id = sha1(source:source_match_id)[:16]`
  ([`processor.py:175-185`](../../ai/swarm/agents/processor.py#L175-L185))
  — collision-resistant, deterministic across replicas.
- `_PLANE_BY_TYPE` ([`processor.py:37-47`](../../ai/swarm/agents/processor.py#L37-L47))
  maps `record_type → plane`: `fixture→schedule`,
  `match_detail/lineup→live`, `odds→market`. Matches §3 plane scope.

**Drift found — N1 (NIT):** [`processor.py:181`](../../ai/swarm/agents/processor.py#L181) carries
the comment `Cross-source resolution lives in Phase 6 QID`. QID is
under [`ai/qid/`](../../ai/qid) and is scheduled for **Phase 9**, not 6.
Stale label inherited from a much earlier roadmap. Action: see N1
in §7.

**Verdict:** ✅ **correct + 1 NIT comment.**

### 2.5 Storage ([`storage.py`](../../ai/swarm/agents/storage.py))

**Assumption (ROADMAP §4.5):** the storage agent is the **sole
producer** of `match.stored`, `freshness.events.v1`, and
`match.outcome.v1`. Diffing is per-key-shallow (full keys, not
truncated strings — that's the telemetry projection's job).
`match.outcome.v1` is only emitted when a `match_detail` record
crosses into a terminal status with a final score.

**Implementation:**

- `InMemoryRecordStore` keyed `(source, source_match_id, record_type)`
  ([`storage.py:31-68`](../../ai/swarm/agents/storage.py#L31-L68)) — Phase 9 swaps for Postgres
  via the `RecordStore` Protocol.
- Full key-level `_shallow_diff` lives in storage; truncation for
  telemetry happens **only** in the telemetry projection (A5 audit
  fix from prior pass).
- `MATCH_STORED` is always emitted; `FRESHNESS_EVENTS` only on
  created/updated; `MATCH_OUTCOME` only when terminal status +
  score present ([`storage.py:204-256`](../../ai/swarm/agents/storage.py#L204-L256)).
- `derive_match_outcome` covers 1x2, OU2.5, BTTS — matches
  consensus's market list.

**Verdict:** ✅ **correct.** No action.

### 2.6 Cache ([`cache.py`](../../ai/swarm/agents/cache.py))

**Assumption (ROADMAP §4.6 + §6.4 boundary):** cache subscribes
`MATCH_STORED` (record cache) and `PREDICT_APPROVED` (prediction
cache). It **must not** subscribe `predict.final` — that would
leak un-proofread predictions into the API surface. Tests must
enforce.

**Implementation:**

- Subscribes exactly `(MATCH_STORED, PREDICT_APPROVED)`
  ([`cache.py:60-72`](../../ai/swarm/agents/cache.py#L60-L72)). Boundary discipline test
  enforces non-subscription to `predict.final`.
- `InMemoryCacheBackend` is thread-safe with TTL; Phase 9 swaps
  for Redis via the `CacheBackend` Protocol.
- No fallback constants — reads `cfg` directly.

**Verdict:** ✅ **correct.** No action.

### 2.7 Telemetry ([`telemetry.py`](../../ai/swarm/agents/telemetry.py))

**Assumption (ROADMAP §4.7):** counts every Phase 4–6 topic; binds
to `127.0.0.1` by default (OWASP A05); naive datetimes treated as
UTC; minimal Prometheus surface (msgs / dlq / latency_avg).

**Implementation:**

- `_WATCHED_TOPICS` is the union of every Phase 4 + 5 + 6 topic
  constant ([`telemetry.py:46-72`](../../ai/swarm/agents/telemetry.py#L46-L72)).
- Bind defaults to `127.0.0.1`; A1-A4 audit fixes for naive
  datetime + non-Decimal counters are in.
- Prom counters have stable names; metric labels do not include
  `source_match_id` (cardinality bound).

**Verdict:** ✅ **correct.** No action.

### 2.8 Reactors ([`reactor.py`](../../ai/swarm/agents/reactor.py))

**Assumption (ROADMAP §4.8):** reactor base enforces idempotency
(via `Ledger`), plane scope (`allowed_planes`), max age, and
**no-back-emission** to `freshness.events.v1`. Order is
check → react → mark (inbox pattern). Concrete reactors:
`FeatureStoreReactor`, `CacheInvalidationReactor`,
`TrainerReactor`, `LivePredictorReactor`.

**Implementation:**

- `ReactorBase` order is `Ledger.already_processed` → `react()` →
  `Ledger.mark_processed` ([`reactor.py:165-208`](../../ai/swarm/agents/reactor.py#L165-L208)) —
  classic inbox pattern.
- `InMemoryLedger` is bounded LRU at
  `cfg.reactor_ledger_max_size`. Phase 9 swaps for Postgres via
  the `Ledger` Protocol.
- `FeatureStoreReactor` and `CacheInvalidationReactor` are pure
  side-effect emitters, no back-emission to `freshness.events.v1`.
- `TrainerReactor` debounces by `cfg.trainer_debounce_min_sec` and
  enforces `cfg.trainer_accuracy_floor`; emits `MODEL_TRAINED` with
  `samples=0` (intentional — payload is "training requested" not
  "training completed"; documented in payload doc).
- `LivePredictorReactor`: plane→market mapping
  `{live:(1x2,ah), market:(ah,ou_2_5,btts)}`; deterministic
  `request_id = f"r-{ev.event_id}-{market}"` so retries dedupe.

**Verdict:** ✅ **correct.** No action.

---

## 3. Phase 5 — Predictor swarm + consensus

### 3.1 Predictor base + context
([`predictors/_base.py`](../../ai/swarm/agents/predictors/_base.py))

**Assumption (ROADMAP §5.1):** `PredictorAgent` exposes
`predictor_id`, `features_version`, `predict(ctx) →
(distribution, confidence)`. Subscribes `PREDICT_REQUEST`,
publishes `PREDICT_VOTE`. `CalibrationStore` is a Protocol so
Phase 9 can swap to Postgres / Phase 16 to feed.

**Implementation:** matches. `softmax` helper deduped here.
`FeatureSource` Protocol noted as a §5.6 follow-up — not yet
written but no consumer needs it (predictors read `ctx.features`
directly). Acceptable for Phase 5 ship; will be required at Phase 9
when feature store lands.

**Verdict:** ✅ **correct.** No action this phase.

### 3.2 Score grid math ([`predictors/_grid.py`](../../ai/swarm/agents/predictors/_grid.py))

**Assumption:** dedupe Poisson + DC + market projections into one
helper used by `dixon_coles` and `xgb_xg`. Recurrence
`P(k)=P(k-1)·λ/k` instead of factorial. `MAX_GOALS=8` covers
>99.9%.

**Implementation:** matches. `score_grid()` returns a
**`list[list[float]]`** (a 2D matrix of shape `(MAX_GOALS+1) ×
(MAX_GOALS+1)`), with `grid[h][a] = P(home=h, away=a)`.

> **Important:** the *shape* of the grid is the seed of bug **B1**
> below. Note this carefully.

**Verdict:** ✅ **correct on its own;** see B1 for the cross-phase
shape contract.

### 3.3 Concrete predictors

Files audited: [`elo.py`](../../ai/swarm/agents/predictors/elo.py),
[`dixon_coles.py`](../../ai/swarm/agents/predictors/dixon_coles.py),
[`xgb_form.py`](../../ai/swarm/agents/predictors/xgb_form.py),
[`xgb_xg.py`](../../ai/swarm/agents/predictors/xgb_xg.py),
[`lgbm_market.py`](../../ai/swarm/agents/predictors/lgbm_market.py).

**Assumption:** five predictors plus the optional LGBM (gated by
`cfg.predictor_market_features_enabled`). Each emits
`{market_outcomes: dict, score_grid: list[list[float]] | None}`
per the schema in [predict.vote.json](../../ai/swarm/sdk/schemas/predict.vote.json#L20).

**Implementation:**

- `pred.dixon_coles.v1` ([`dixon_coles.py:49-67`](../../ai/swarm/agents/predictors/dixon_coles.py#L49-L67))
  emits `score_grid = grid` where `grid` is the **2D matrix** from
  `_grid.score_grid()`.
- `pred.xgb_xg.v1` (same pattern, same shape).
- `pred.elo.v1`, `pred.xgb_form.v1`, `pred.lgbm_market.v1`
  all emit `score_grid: None` ([`xgb_form.py:108`](../../ai/swarm/agents/predictors/xgb_form.py#L108)).

**Verdict:** ✅ shape is **internally consistent** with the schema
description (`"2D list|null"`). The mismatch is downstream — see B1.

### 3.4 Consensus ([`consensus.py`](../../ai/swarm/agents/consensus.py))

**Assumption (ROADMAP §5.2):** subscribe `(PREDICT_REQUEST,
PREDICT_VOTE)`. `note_request` opens a fusion window;
votes drive fusion; per-vote confidence floor
`cfg.consensus_min_confidence`; LRU cap on `_pending`; rate-limited
overflow flag; degraded flag when voters < `cfg.consensus_min_voters`;
profile resolution `vote.profile_id || vote.league_id || "default"`;
single-store-hit invariant by caching `(prediction_id,
calibration_table)` in `_PendingFusion`; flush on window timeout.

**Implementation:** matches in full
([`consensus.py:380-560`](../../ai/swarm/agents/consensus.py#L380-L560)).
Score-grid fusion at [`consensus.py:121-160`](../../ai/swarm/agents/consensus.py#L121-L160) does
**element-wise averaging across the 2D matrices** and emits a
`list[list[float]]` of identical shape. Late vote → drops with
`LATE_VOTE_DROPPED` flag. `flush_expired` is correctly tied to
`cfg.swarm_flush_interval_ms` via the runner.

**Verdict:** ✅ **correct.** No action.

### 3.5 Calibration store seam

**Assumption (ROADMAP §5.5):** `CalibrationStore` Protocol with an
in-memory default; Phase 9 swaps for Postgres; Phase 16 swaps for
feed-driven calibration.

**Implementation:** Protocol defined; in-memory default; consensus
hits the store **once** per `_PendingFusion` and caches the table.

**Verdict:** ✅ **correct.** No action.

### 3.6 Backtest harness ([`xops/swarm_backtest.py`](../../xops/swarm_backtest.py))

**Assumption (ROADMAP §5.3):** offline driver that replays a
fixture corpus through the swarm and reports per-predictor and
ensemble metrics.

**Implementation:** present and wired through `make swarm.backtest`.
Not deeply audited this pass — the suite under
`ai/swarm/agents/tests` exercises the wire layer; the backtest is
an operator tool, not a doctrine surface.

**Verdict:** ✅ **correct as Phase 5 tool.** No action.

### 3.7 Single-instance invariant

**Assumption (ROADMAP §5 + 6.4):** `consensus.v1`,
`proofreader_aggregator.v1`, and `drift.v1` are single-replica
until Phase 14 leader-election lands.

**Implementation:** `bootstrap._enforce_single_instance`
([`bootstrap.py:194-211`](../../ai/swarm/bootstrap.py#L194-L211)) raises
`SingleInstanceViolation` at boot if any of those three appears
twice. Test enforces.

**Verdict:** ✅ **correct.** No action.

---

## 4. Phase 6 — Proofreader + drift

### 4.1 Replicas + roster ([`proofreader/replicas.py`](../../ai/swarm/agents/proofreader/replicas.py))

**Assumption (ROADMAP §6.1):** one shell, three concrete check
replicas (sanity / plausibility / consistency), each emits exactly
one `ProofreaderVerdict` per `(request_id, prediction_id)`.
`PROOFREADER_POLICY_CLASSES` is the **single source of truth** for
the roster; `cfg.proofreader_quorum` derives `⌊N/2⌋+1` from it (so
operators cannot drift the two — F3-1 fix).

**Implementation:** matches. F-4 fix (internal exception → warn +
`PROOFREADER_INTERNAL_ERROR` flag) in. Verdict.flags = `checks_run`
when verdict ≠ accept; rationale = joined details.

**Verdict:** ✅ **correct.** No action.

### 4.2 Prediction-level checks ([`proofreader/prediction_checks.py`](../../ai/swarm/agents/proofreader/prediction_checks.py))

**Assumption (ROADMAP §6.2):** pure functions over a `predict.final`
distribution; three rules — `sanity_check`, `plausibility_check`,
`grid_consistency_check`.

**Implementation:**

- `sanity_check` — probs sum to 1±ε; reject is fatal. ✅
- `plausibility_check` — warn (counts toward quorum) when any
  outcome > `max_outcome_prob`. ✅
- `grid_consistency_check` — **see B1 below**. The function
  iterates the grid expecting **`list[dict{home: int, away: int,
  prob: float}]`**, but consensus emits **`list[list[float]]`**
  (2D matrix from `_grid.score_grid()`). Result: every grid-bearing
  prediction is rejected.

### 4.3 Aggregator ([`proofreader/aggregator.py`](../../ai/swarm/agents/proofreader/aggregator.py))

**Assumption (ROADMAP §6.4):** the aggregator is the **sole
producer** of `predict.approved.v1`. Quorum policy is
`⌊N/2⌋+1` of `accept | warn`; `reject` is fatal regardless of
quorum. Idempotent on `prediction_id` via `Ledger`. Bounded
`_pending` LRU. Late verdict → `late_verdict_dropped` flag. Five
flag kinds total.

**Implementation:** matches in full
([`aggregator.py:167-460`](../../ai/swarm/agents/proofreader/aggregator.py#L167-L460)).
Running counters `_accept_warn_count` / `_reject_count` (F-2 perf
fix) avoid recomputing on every verdict.

> **Note on `proofreader_aggregator_max_pending`** (`cfg`):
> the ROADMAP §6.4 narrative mentions "shares
> `consensus_max_pending`" as the bound. The implementation gives
> the aggregator its **own** knob
> ([config.py:371](../../ai/common/config.py#L371))
> that **defaults to the same value** (4096) and whose docstring
> says it "mirrors `consensus_max_pending`". This is a deliberate
> parallel knob (operators may need to tune them separately under
> proofreader latency pressure) — **not a drift**, but the ROADMAP
> wording could be tightened. Logged as **N2** in §7.

**Verdict:** ✅ **correct.** No action beyond N2.

### 4.4 Drift detector ([`drift.py`](../../ai/swarm/agents/drift.py))

**Assumption (ROADMAP §6.3):** subscribes
`(PREDICT_APPROVED, MATCH_OUTCOME)`. Maintains a sliding window
per (model, market). Computes Brier; trips when Brier exceeds
`cfg.drift_brier_ceiling` *or* accuracy falls below
`cfg.drift_accuracy_floor` (separate knobs — different metrics,
opposite directions, F-3 fix). Emits `MaintEvent{kind=
"retrain_request"}` per contributing model. `_tripped` set
debounces re-fires until recovery.

**Implementation:** matches. `_Window` uses ref-counted Counter
for `models_in_window` (perf fix); O(1) outcome settle via
`(match_id, "1x2")` pop (F2-1 fix). Bounded `_pending` /
`_settled` LRU.

**Verdict:** ✅ **correct.** No action.

### 4.5 `predict.approved.v1` contract

**Assumption:** the `predict.approved.v1` payload carries the
`predict.final` verbatim under `final` so downstream consumers do
not need a join. Cache subscribes here, never to `predict.final`.

**Implementation:** schema confirms
([predict.approved.v1.json](../../ai/swarm/sdk/schemas/predict.approved.v1.json));
cache subscription confirms (§2.6); aggregator is sole producer.

**Verdict:** ✅ **correct.** No action.

---

## 5. Cross-phase findings

### 5.1 Boundary discipline tests

The `tests/test_boundary_discipline.py` suite enforces:
- Only `storage.v1` produces `match.stored`,
  `freshness.events.v1`, `match.outcome.v1`.
- Only `consensus.v1` produces `predict.final`.
- Only `proofreader_aggregator.v1` produces `predict.approved.v1`.
- Cache does not subscribe to `predict.final`.

All passing. ✅

### 5.2 Cfg triangle

Spot-checked every Phase 4–6 knob in all three files
([config.py](../../ai/common/config.py),
[defaults.yaml](../../ai/common/defaults.yaml),
[xops/env/.env.example](../../xops/env/.env.example)). The
`test_config_sync` strict-mode test guards drift. ✅

### 5.3 Topic-versioning hygiene

`match.outcome.v1`, `predict.approved.v1`,
`predict.proofreader_verdict.v1`, `models.events.v1`,
`maint.event.v1`, `freshness.events.v1` are **all** suffixed `.v1`
per ROADMAP §3.7. Phase-4 control topics (`scrape.*`,
`match.normalized`, `match.stored`, `predict.request`,
`predict.vote`, `predict.final`, `proof.flag`, `telemetry`) are
**not** suffixed — that is also per §3.7 (control plane is
unversioned; data-plane / candidate-plane is versioned). ✅

### 5.4 Tests vs. real wire path — coverage gap

The 387 swarm-agent tests pass, but the test suite organises into
**unit** scope (one agent at a time) and **demo** scope
(`test_phase5_swarm_demo.py` runs the full pipeline but only
asserts on the consensus output, not on proofreader verdicts of a
real grid-bearing vote).

There is **no end-to-end test** that:

1. Builds the real `build_agents()` swarm, **and**
2. Drives a real `pred.dixon_coles.v1` or `pred.xgb_xg.v1` vote
   into consensus, **and**
3. Asserts that the resulting `predict.final` is *approved* (not
   rejected by the consistency proofreader).

This coverage hole is the reason **B1 below survived prior audit
passes**.

---

## 6. Findings (numbered)

### B1 — **BLOCKER**: `score_grid` shape contract violation between Phase 5 consensus and Phase 6 consistency proofreader

**File pair:**

- Producer: [ai/swarm/agents/predictors/_grid.py](../../ai/swarm/agents/predictors/_grid.py#L67-L113)
  → returns `list[list[float]]` (2D matrix `grid[home][away]`).
- Producer: [ai/swarm/agents/predictors/dixon_coles.py:64-67](../../ai/swarm/agents/predictors/dixon_coles.py#L64-L67)
  → emits `"score_grid": grid` (the 2D matrix).
- Producer: [ai/swarm/agents/predictors/xgb_xg.py](../../ai/swarm/agents/predictors/xgb_xg.py)
  → same shape.
- Producer: [ai/swarm/agents/consensus.py:121-160](../../ai/swarm/agents/consensus.py#L121-L160)
  → averages 2D matrices element-wise; emits `list[list[float]]`.
- Consumer: [ai/swarm/agents/proofreader/prediction_checks.py:153-184](../../ai/swarm/agents/proofreader/prediction_checks.py#L153-L184)
  → expects `list[dict{home: int, away: int, prob: float}]`.

**Reproducer (ran during this audit):**

```python
from swarm.agents.predictors.dixon_coles import DixonColesPredictor
from swarm.agents.predictors._base import PredictorContext
from swarm.agents.payloads import PredictRequest
from swarm.agents.proofreader.prediction_checks import grid_consistency_check

p = DixonColesPredictor()
req = PredictRequest(
    request_id="r1", match_id="m1", market="1x2",
    league_id="tr1", profile_id="tr1",
    requested_at="2026-04-30T00:00:00+00:00",
    features={"home_xg": 1.4, "away_xg": 1.1},
    metadata={},
)
dist, conf = p.predict(PredictorContext(request=req, features=req.features))
# dist["score_grid"] is list[list[float]] of shape (9, 9)
v, _, flags = grid_consistency_check(dist, tol=0.05)
# v == "reject"
# flags == ["consistency: score_grid entry not a dict"]
```

**Production blast radius:**

- `consistency` is in `PROOFREADER_POLICY_CLASSES`; quorum is
  `⌊3/2⌋+1 = 2`; `reject` is fatal regardless of quorum.
- Therefore **every** `predict.final` whose `score_grid != None`
  would be aggregator-flagged `kind=rejected` and **no
  `predict.approved.v1` would ever be emitted** for a grid-bearing
  prediction.
- In the production roster, `pred.dixon_coles.v1` and
  `pred.xgb_xg.v1` always emit a grid; `pred.elo.v1`,
  `pred.xgb_form.v1`, `pred.lgbm_market.v1` emit `None`. The fused
  consensus carries a non-`None` grid whenever **any** vote in the
  window does — which is the default case.
- Net: **~100% of real predictions are silently vetoed in
  production**, and this is currently invisible because no
  end-to-end test asserts the approved-rate floor.

**Why prior audits missed it:**

- `test_prediction_checks.py` fixtures hand-build the grid as a
  list of `{home, away, prob}` dicts ([line 139](../../ai/swarm/agents/tests/test_prediction_checks.py#L139)).
  Those tests prove the rule **for the shape they tested**,
  which is not the shape consensus emits.
- `test_consensus.py` ([line 47](../../ai/swarm/agents/tests/test_consensus.py#L47))
  tests grid fusion shape but does not pipe the result through a
  proofreader.
- `test_phase5_swarm_demo.py` ([line 147](../../ai/swarm/agents/tests/test_phase5_swarm_demo.py#L147))
  asserts only that `pf.distribution["score_grid"] is not None`.
- The `consistency.score_grid_marginals` flag in
  [test_proofreader_replicas.py:143](../../ai/swarm/agents/tests/test_proofreader_replicas.py#L143)
  uses the dict-of-dicts shape too.

**Correct contract — choose ONE source of truth:**

| Option | Shape | Pros | Cons |
|---|---|---|---|
| **A. Standardise on 2D matrix** (status quo of producers; rewrite `grid_consistency_check` + tests + schema description) | `list[list[float]]` | Predictors stay fast; matches `_grid.py` math; `predict.vote.json` schema description already says "2D list". | One non-trivial check rewrite + ~6 fixture rewrites. |
| **B. Standardise on list-of-dicts** (status quo of the check; rewrite predictors + consensus fusion + schema) | `list[{home, away, prob}]` | Matches the current check + a couple of tests. | Predictors lose the matrix shape that `_grid.py` math is built around; consensus fusion gets ~3× more code; schema description must be edited; **performance regression** on hot path. |

**Recommended action (proposal — pending approval):** **Option A.**

1. Rewrite `grid_consistency_check` to iterate
   `for h in range(n): for a in range(len(grid[h])):` and accumulate
   `H/D/A` marginals from `grid[h][a]`.
2. Rewrite `test_grid_consistency_*` fixtures in
   `test_prediction_checks.py` to use the 2D shape.
3. Rewrite the equivalent fixture in
   `test_proofreader_replicas.py:135`.
4. Tighten the `score_grid` schema description in
   `predict.vote.json` and `predict.final.json` (currently
   `"2D list|null"` — make it formal).
5. **Add an end-to-end regression test** under
   `ai/swarm/tests/` (or `ai/swarm/agents/tests/`) that builds the
   full `build_agents()` swarm, drives one
   `pred.dixon_coles.v1` request through, and asserts that
   `predict.approved.v1` is emitted (this is the **real** missing
   test that would have caught B1 immediately, per Rule 10).

**Severity:** **BLOCKER** — Phase 6 cannot be considered shippable
in its current form. The proofreader silently nukes 100% of
grid-bearing predictions; the only reason CI is green is that no
test exercises the path.

---

### N1 — **NIT**: stale "Phase 6 QID" comment in processor.py

**File:** [ai/swarm/agents/processor.py:181](../../ai/swarm/agents/processor.py#L181).

**Current:** `# Cross-source resolution lives in Phase 6 QID.`

**Reality:** QID is under [`ai/qid/`](../../ai/qid) and per
ROADMAP is scheduled for **Phase 9** (cross-source dedup +
canonical entity resolution).

**Recommended action (proposal):** edit the comment to
`# Cross-source resolution lives in Phase 9 QID.` — single-line
doc fix.

**Severity:** **NIT** — no behavioural impact.

---

### N2 — **MINOR (doc-only)**: clarify aggregator pending bound naming

**Files:**
- [ai/common/config.py:367-373](../../ai/common/config.py#L367-L373)
- [ROADMAP.md §6.4](../planning/ROADMAP.md) — narrative says
  "shares `consensus_max_pending`" while the implementation gives
  the aggregator a parallel `proofreader_aggregator_max_pending`
  knob defaulting to the same `4096`.

**Recommended action (proposal):** edit ROADMAP §6.4 to say "the
aggregator carries its own bound `proofreader_aggregator_max_pending`,
which defaults to `consensus_max_pending` so operators see one
number unless they tune them apart." No code change.

**Severity:** **MINOR (doc-only)**.

---

## 7. Forward roadmap (proposals — DO NOT IMPLEMENT YET)

> Per the human's hard constraint, the items below are **proposals
> only**. No code edits, no tracker rows, no `make track.add`, no
> `make version.bump` until this audit is read and approved.

### 7.1 Recommended fix order

| # | Item | Type | Risk | Est. blast radius |
|---|---|---|---|---|
| 1 | **B1 — `score_grid` shape contract**: rewrite `grid_consistency_check` for 2D matrix; rewrite affected fixtures; add end-to-end regression test that asserts `predict.approved.v1` for a real DC vote. | code + tests | low (the math is unchanged; the rewrite is mechanical) | `proofreader/prediction_checks.py`, `tests/test_prediction_checks.py`, `tests/test_proofreader_replicas.py:135`, **new** `tests/test_phase6_score_grid_e2e.py`. Optional schema description tightening. |
| 2 | **N1** stale comment in `processor.py:181` — change "Phase 6 QID" → "Phase 9 QID". | doc | none | one line. |
| 3 | **N2** ROADMAP §6.4 wording — clarify aggregator pending bound is its own knob with same default. | doc | none | one paragraph in ROADMAP. |

### 7.2 Pre-flight checklist before opening the fix PR

- [ ] Re-run `PYTHONPATH=ai pytest ai/swarm/agents/tests -q` — 387
      tests + 1 new e2e = 388 passing.
- [ ] Re-run `make test.ai` to capture the full suite count.
- [ ] Tick the satisfied checkboxes in
      [ROADMAP.md §6.2](../planning/ROADMAP.md) (consistency check
      proven against the *real* shape) and §6.4 (cache cannot serve
      un-approved predictions — proven by e2e).
- [ ] Tracker rows: one `complete` for B1 with `--note "Phase 5↔6
      score_grid contract reconciled; e2e regression test added"`,
      and a separate `note` row for N1 + N2 doc tweaks.
- [ ] Version bumps: `swarm` (patch — internal contract fix) and
      `docs` (patch — N1+N2). Then `project` (patch) so the build
      counter ticks.

### 7.3 Out of scope (deliberately)

- The deferred `FeatureSource` Protocol — Phase 5 ships without it
  and no consumer needs it; Phase 9 will require it.
- Postgres swap of `Ledger` / `CalibrationStore` / `RecordStore` /
  `CacheBackend` — Phase 9.
- Multi-replica leader election for the three single-instance
  agents — Phase 14.
- Datasource emitter feeds — Phase 16.

---

## 8. Self-review checklist

- [x] Re-read every binding ROADMAP checkbox under Phase 4, 5, 6.
- [x] Cited file:line for every claim in §§2–6.
- [x] Ran the full Phase 4–6 swarm test suite (`387 passed`).
- [x] Ran a hand-built reproducer for B1 to **prove the bug
      empirically**, not just by code reading.
- [x] Distinguished proposals (§7) from facts (§§2–6) and stayed
      out of code per the human's hard constraint.
- [x] Verified the cfg triangle for every Phase 4–6 knob.
- [x] Verified the boundary discipline tests are in force.
- [x] Verified single-instance enforcement at boot.
- [x] Did **not** invent a `[~]` half-state; left ROADMAP
      checkboxes alone pending approval.

---

## 9. TL;DR for the human reviewer

- **Phases 4 and 5 are clean.** The implementation matches the
  design and the tests cover the surface. One stale comment (N1).
- **Phase 6 has one real, blocking bug (B1).** The consistency
  proofreader's `score_grid` shape contract is the wrong way around
  — it expects a list of dicts, but the predictors and consensus
  emit a 2D matrix. In production this would silently veto every
  grid-bearing prediction. **No end-to-end test** exercises the
  path, which is why prior audits missed it.
- **Recommended fix:** Option A in §6.B1 — rewrite the check + a
  handful of fixtures for the 2D shape, and add the missing
  end-to-end regression test. Doc fixes for N1 and N2 alongside.
- **Hard constraint respected:** no edits made to code, tracker,
  ROADMAP, or version chart. Awaiting your read + approval before
  starting.
