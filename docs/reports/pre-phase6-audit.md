# Pre-Phase 6 Audit — Soundness, Gaps, Performance

*Date: 2026-04-29 · Scope: Phases 0 → 5 + cross-cutting infra · Author: Copilot (Claude Opus 4.7)*

## 0. TL;DR

Phases 0–5 are **functionally green** (665/665 ai tests, multiple recent audit passes
documented in `/memories/repo/negelir-status.md`), but starting Phase 6 today
would inherit **5 concrete bugs/gaps** and **6 design-debt items** that will
either silently corrupt observability or force a costly Phase 6 refactor.
Address §1 + §2 before opening Phase 6, then drive §3 in parallel with the
Phase 6 build.

Severity legend: 🔴 prod-correctness · 🟠 silent drift / observability · 🟡 design debt · 🟢 perf

---

## 1. Verified bugs (fix BEFORE Phase 6 kickoff)

### 🔴 B1 · `proof.flag` schema enum is missing the kinds Phase 5 already emits

**Where:** [ai/swarm/sdk/schemas/proof.flag.json](ai/swarm/sdk/schemas/proof.flag.json#L13-L20)

The enum lists 6 kinds:
`upstream_missing, decode_failed, empty_parse, parser_exception, invalid_record, low_confidence_classification`.

[ai/swarm/agents/consensus.py](ai/swarm/agents/consensus.py) emits **3 kinds the
schema does not declare**:
- `late_vote_dropped` ([consensus.py#L316](ai/swarm/agents/consensus.py#L316))
- `consensus_no_votes` ([consensus.py#L446](ai/swarm/agents/consensus.py#L446))
- `consensus_overflow` ([consensus.py#L265](ai/swarm/agents/consensus.py#L265))

The `validate()` helper at
[ai/swarm/sdk/schemas/__init__.py#L100-L104](ai/swarm/sdk/schemas/__init__.py#L100-L104)
**does** enforce `enum`. The Phase 5 swarm-demo test deliberately produces no
proof.flags ([test_phase5_swarm_demo.py#L158](ai/swarm/agents/tests/test_phase5_swarm_demo.py#L158)
"No proof.flag (no degradation, no late votes)"), and the Phase 5 consensus
unit tests don't run `validate()` on emitted flags — so the regression slipped
past the live-emission guard added in Audit Pass 4 (memory line 142).

**Action:** extend the enum with the three Phase 5 kinds + the kinds Phase 6
will introduce, OR drop the enum from the wire schema and keep a `KIND_REGISTRY`
constant in code for telemetry-bucket cardinality control. Pick one.
Recommend the latter — the enum will keep growing.

**Test gap:** add to `test_phase5_swarm_demo.py` (or a dedicated proof.flag
contract test) a fan-in case that fires `late_vote_dropped` /
`consensus_no_votes` / `consensus_overflow` and runs them through `validate()`.

---

### 🟠 B2 · `cache_prediction_ttl_sec` is wired through config but never consumed

**Where:**
- declared [ai/common/config.py#L302](ai/common/config.py#L302)
- validated [ai/common/config.py#L441](ai/common/config.py#L441)
- documented [ai/common/defaults.yaml#L157](ai/common/defaults.yaml#L157)
- `xops/env/.env.example` carries the key

`grep_search` finds **zero** call sites that read `cfg.cache_prediction_ttl_sec`.
[ai/swarm/agents/cache.py](ai/swarm/agents/cache.py) only handles
`MATCH_STORED` and uses `cache_record_ttl_sec`. ROADMAP §4.5 line 636 explicitly
marks the `predict.final` subscription as `[ ]` deferred.

**Risk:** Phase 6 will wire this — but if you wire it as `cache.v1` subscribing
directly to `predict.final`, you violate the gate contract that ROADMAP §736
spells out: *"`predict.final` is a CANDIDATE — never user-visible until the
Phase 6 proofreader quorum approves it."* Subscribing the cache directly to
`predict.final` would bypass the proofreader entirely.

**Action:** decide cache topology in §6.1 design **first**:
- Option A — new topic `predict.approved.v1` (proofreader majority → cache).
- Option B — proofreader as a `predict.final` middleware that re-emits the
  payload on `predict.final.approved` only.
- Option C — proofreader writes to a `proofreader.verdict.v1` topic + cache
  joins on `(prediction_id, verdict=pass)` with a tiny in-memory join window.

Option A is the cleanest contract; pick it unless there's a strong reason not
to. Then `cache_prediction_ttl_sec` finally becomes live.

---

### 🟡 B3 · Legacy `ai/proofreader/` and `ai/model/drift.py` are pre-bus orphans

**Where:**
- [ai/proofreader/validator.py](ai/proofreader/validator.py) — `DataProofreader`,
  range/consistency/plausibility checks.
- [ai/proofreader/cross_validator.py](ai/proofreader/cross_validator.py) — source
  agreement, majority vote, conflict quarantine.
- [ai/model/drift.py](ai/model/drift.py) — rolling accuracy `DriftDetector`.

These are **synchronous, dataclass-based, log-to-stdout** modules wired into the
**legacy training pipeline** only:
- [ai/pipeline/runner.py#L23](ai/pipeline/runner.py#L23)
- [ai/pipeline/training_pipeline.py#L149](ai/pipeline/training_pipeline.py#L149)
- [ai/data_showcase.py#L23](ai/data_showcase.py#L23)

They are not `Agent` subclasses, hold no `subscribes`/`publishes`, and never see
the bus. Pivot v3 (COMPONENT_LAYOUT.md) places proofreaders + drift under
`swarm/proofreaders/` and `swarm/drift/`.

**Action — decide ONCE, pin in §6.1:**
1. **Port** the pure-function checks (range tables, score consistency, possession,
   plausibility) into a new module `ai/swarm/agents/proofreaders/_checks.py`
   that the new bus agent imports.
2. **Deprecate** `cross_validator.py` — its responsibility is now Phase 6.2's
   "Cross-source agreement with implied probability". Don't extend it.
3. **Keep** `ai/model/drift.py` ONLY as a building block — the `DriftDetector`
   itself is fine, but the new `drift.v1` agent must consume bus events
   (see B7 below), not `Outcome` lists.

The wrong move is to add a "Phase 6" hat onto `ai/proofreader/validator.py`
in place. That guarantees a Phase R2 rip-up.

---

### 🟠 B4 · No `match.outcome.v1` topic exists — drift agent has nothing to consume

**Where:** [ai/swarm/agents/topics.py](ai/swarm/agents/topics.py) lists 12 topics;
none publish *resolved* match results that the drift agent needs to score
predictions retroactively.

ROADMAP §6.3 says the drift agent maintains "rolling Brier / log-loss windows
per league × market × predictor". To compute Brier you need `(prediction, actual_outcome)`
pairs. Today:
- `predict.final` → carries the prediction (good).
- `match.stored` / `match.normalized` → carries `match_detail` records, but
  the drift agent would have to *re-derive* who won from the payload, then
  *join* against an in-memory predictions cache. That's coupling the drift
  agent to storage internals.

**Action:** during Phase 6 design, add to the topic catalog and ship the
schemas/payloads in the same diff as the drift agent:
- `match.outcome.v1` — emitted by storage when a `match_detail` arrives with
  `status=finished`, payload `{match_id, ft_home, ft_away, outcome_1x2, btts,
  total_goals, …}`. Idempotency-keyed on `(stable_id, status_finished)`.
- `maint.event.v1` — emitted by drift agent on retrain trigger
  (ROADMAP §6.3 last bullet). Phase 8 schema-healer also needs this.

Don't smuggle these contracts in piecemeal — they're all Phase 6.

---

### 🟡 B5 · `consensus_brier_window` knob exists but no Brier scorer does

**Where:** [ai/common/config.py#L313](ai/common/config.py#L313).

This is a placeholder for the deferred "Brier-rolling weight learning" (memory
line 41 "Still deferred…Brier-rolling weight learning"). Phase 6.3 will
*also* maintain rolling Brier (per the §6.3 spec). **Don't ship two rolling
Brier stores in two agents.**

**Action:** make the Phase 6 drift agent the single owner of rolling Brier per
`(league, market, predictor)`. Consensus reads the latest weight from the same
`predictor_weights` table that drift writes (migration `005_predictor.sql`
already ships this table — memory line 38). Decide on the topology now to
avoid double-write contention later.

---

## 2. Architectural decisions Phase 6 must lock before coding

### 🟡 D1 · Source-watcher (Phase 2.8) vs `drift.v1` (Phase 6.3) — name collision

**Where:** [ai/swarm/source_watcher/](ai/swarm/source_watcher/) classifies
*upstream-schema* drift (per ROADMAP §2.8). Phase 6.3's `drift.v1` watches
*model-performance + input-distribution* drift. Both are legitimately called
"drift", and both will need rolling-window plumbing.

**Action:** pin the names + ownership in COMPONENT_LAYOUT.md / SWARM.md
**before** the Phase 6 PR opens:
- `source_watcher` → `datasource.drift.v1` (post-R2). Fires `freshness.events.v1`
  + escalates to patcher per SCRAPER_PATCHER §4.
- `drift.v1` → `swarm.drift.v1` (post-R2). Fires `maint.event.v1` per §6.3.

They share **zero** state and **zero** topics. Different planes (datasource vs
swarm). The only crossover is via the bus on telemetry counters.

---

### 🟡 D2 · `proof.flag` is becoming a god-topic — split or cap

**Where:** [ai/swarm/sdk/schemas/proof.flag.json](ai/swarm/sdk/schemas/proof.flag.json#L4)
("intentionally loose…each producer adds its own context fields").

Today's producers: scrapers, categorizer, processors, consensus. Phase 6 adds:
N proofreaders × ~6 check kinds + drift agent × 2 trip kinds. By Phase 7 the
sec.* agents will also want a slot. The schema is already `additionalProperties: true`
so it scales structurally — but the consumer side (proofreader, drift, security)
will subscribe to `proof.flag` to *learn from each other* and the cardinality
of `kind` becomes the de-facto routing key, with no schema enforcement.

**Action — pick one before Phase 6 fans out producers:**
- Keep one topic, but freeze a `KindRegistry` enum in
  `ai/swarm/agents/payloads.py` and have every producer pull `kind` from there.
  Add a `test_proof_flag_kind_in_registry` contract test that validates
  registry ↔ schema enum agreement.
- Split into `proof.flag.scrape.v1` / `proof.flag.predict.v1` /
  `proof.flag.security.v1`. More topics, cleaner subscribers, harder to migrate.

Recommend option 1 for Phase 6; defer option 2 to Phase 14 if cardinality bites.

---

### 🟡 D3 · Where does `predict.final.score_grid` come from when only DC + xgb_xg produce it?

**Where:** ROADMAP §737 "the proofreader skips the consistency check for those
[markets without a grid]." Today consensus *does* fuse grids
([consensus.py `_fuse_score_grids`](ai/swarm/agents/consensus.py)), but only
2 of 4 predictors emit one. Result: the fused grid is the **average of two
models**, no longer a swarm-weighted view.

**Action:** in §6.2 consistency-check spec, document that
`score_grid is not None ⇒ contributing_models contains at least 2 score-grid
producers`. Otherwise the consistency check is comparing 1X2 fused-from-4 to a
score-grid fused-from-2 — those *will* disagree more often than the user expects,
and the proofreader will trip false positives.

---

### 🟢 D4 · Quorum math: `⌈N/2⌉ + 1` with `N=3` requires **3** voters, not 2

ROADMAP §6.1 says "≥ ⌈N/2⌉ + 1 proofreaders pass it (configurable quorum)".

For N=3: `⌈3/2⌉ + 1 = 2 + 1 = 3`. That means **all** proofreaders must pass
— a single failure vetoes. With `cfg.proofreader_count=3` (default) the system
is one flaky proofreader away from publishing nothing.

**Action:** clarify in §6.1 whether the formula intends **strict super-majority**
(intended? then default N=5 — needs 4) or **simple majority** (then formula
should be `⌊N/2⌋ + 1`, which gives 2 for N=3). The latter matches the prose
"more than half". Pick one, fix the formula in ROADMAP.

---

## 3. Performance & efficiency carryover items

### 🟢 P1 · Local `from common.config import cfg` inside hot reactor paths

**Where:** [reactor.py#L240](ai/swarm/agents/reactor.py#L240),
[telemetry.py#L138](ai/swarm/agents/telemetry.py#L138),
[cache.py — module-level import is fine](ai/swarm/agents/cache.py#L26).

Reactor + telemetry import `cfg` lazily "to keep cfg load lazy". `cfg` is a
module-level singleton — once anything has touched `common.config`, the import
is a dict lookup. The lazy-import pattern is dead weight (and slightly slower
than a module-level import because Python re-walks `sys.modules` every call).

**Action:** promote both to module-level. Negligible perf, but removes a
"why-is-this-here?" tax for new contributors.

---

### 🟢 P2 · `consensus._max_pending` LRU eviction emits a `proof.flag` per evicted key

**Where:** [consensus.py#L260-L280](ai/swarm/agents/consensus.py#L260-L280).

Default `consensus_max_pending=4096`. If Phase 6 adds N proofreaders each
fanning out their own decisions, then a sustained burst (e.g., a chaos test or
a Phase 12 kill-50%-predictors run) can evict the entire 4096-key set and
flood `proof.flag` with 4096 messages → telemetry counter spike → potential
storage backpressure.

**Action:** rate-limit overflow flags to **one per N seconds** (configurable,
e.g., `consensus_overflow_flag_interval_sec=10`) with a counter rolled into
each batched flag (`{kind: "consensus_overflow", evicted_count: N, ...}`).
Phase 6 is a good moment because the flag will land in the proofreader's lap.

---

### 🟢 P3 · `_fuse_score_grids` is pure-Python triple loop

**Where:** [consensus.py `_fuse_score_grids`](ai/swarm/agents/consensus.py).

Today: `O(R·C·N_votes)` per finalize. With `R=C=11` and `N=2 grid-emitting
voters`, that's 242 float ops per predict — fine. **Don't** numpy-ify yet.
Revisit if Phase 6.2's per-cell consistency check needs the grid in numpy
form anyway (in which case keep the fusion in pure Python and convert once
at the gate boundary, not inside fusion).

---

### 🟢 P4 · `features_version` is plumbed through PredictVote but every predictor passes `""`

**Where:** [payloads.py PredictVote.features_version](ai/swarm/agents/payloads.py#L380).

Phase 6.2's "historical plausibility" check needs to know which feature build
produced a vote (so e.g. an Elo-baseline vote isn't compared against a
last-3-meetings prior trained on a different schema). Today the field is dead
storage. Plumb it from `_grid.py` / each predictor module's `__version__`
**now** (one line each), not after Phase 6.2 starts firing false positives.

---

### 🟢 P5 · CalibrationStore handoff is by-reference — verify immutability

**Where:** [consensus.py — `_PendingFusion.calibration_table`](ai/swarm/agents/consensus.py),
[predictors/_base.py CalibrationStore Protocol](ai/swarm/agents/predictors/_base.py).

The pending key caches the `CalibrationTable` instance ("single calibration-store
hit per request" — memory line 26). If Phase 6 introduces a `TrainerReactor`
update mid-window that **mutates** the same table object instead of upserting a
new one, two consensus windows can fuse with mismatched calibration.

**Action:** add a Phase 5 regression test
`test_calibration_table_is_swap_not_mutate`:
1. Seed `InMemoryCalibrationStore` with v1.
2. Open a pending consensus window.
3. Trigger an upsert to v2.
4. Drop the in-flight vote → assert finalized prediction carries `calibration_version=1`.

This guards Phase 6 from writing a TrainerReactor that breaks the contract.

---

### 🟢 P6 · No CI partitioning for the 665-test suite

The full ai suite is now 665 tests (from 596 in Audit Pass 3). Phase 6 adds:
- ≥3 proofreader unit tests × ≥6 check kinds = ~20 cases
- drift agent (rolling Brier, KS, retrain trigger) ≈ 10 cases
- New schemas, contract tests for new topics ≈ 8 cases
- End-to-end through `swarm.demo` extension ≈ 3 cases

Estimate post-Phase 6: ~700 tests. Still tractable, but the
`test_predictor_cpu_parity.py` heavy-loop tests (24 cases per memory) are
already the long tail.

**Action:** before Phase 6, mark the heavy parity tests with a `slow` pytest
marker and add `make test.fast` (excluding `slow`) to the bookkeeping
Make targets. Land it as a Phase 5 cleanup, not Phase 6 scope creep.

---

## 4. Concrete pre-Phase 6 work order

Sequence the cleanup in this order — all are local/reversible, none open new
phase scope:

| # | Item | Files | Estimated diff size |
|---|------|-------|--------------------|
| 1 | B1 fix: `proof.flag` enum + KindRegistry + contract test | `proof.flag.json`, new `payloads.py::ProofFlagKind`, `test_proof_flag_kinds.py` | small |
| 2 | P5 fix: calibration immutability regression test | `test_consensus.py` | tiny |
| 3 | P4 fix: plumb `features_version` into all 5 predictors | `predictors/*.py`, `_grid.py`, +1 assertion in `test_predictors.py` | small |
| 4 | P1 cleanup: hoist lazy `cfg` imports | `reactor.py`, `telemetry.py` | tiny |
| 5 | P6 cleanup: `slow` marker + `make test.fast` | `conftest.py`, `Makefile`, `xops/makefile/test.py` | small |
| 6 | D1 doc decision: source_watcher vs drift naming | COMPONENT_LAYOUT.md, SWARM.md | doc-only |
| 7 | D4 doc fix: quorum formula | ROADMAP §6.1 | doc-only |

Items 1–5 each warrant their own commit + tracker row + `make version.bump`
per AGENTS.md §3 / §6.1. Items 6–7 are doc-only and can be batched.

Then open Phase 6 with the architectural choices in §2 already pinned in the
design doc.

---

## 5. What's NOT broken (audit-confirmed green)

To prevent re-auditing already-clean ground:

- **Bus performance.** `InMemoryBus.read` islice fix and `_pending` dict
  conversion (memory lines 18–19) bring read/ack to O(count)/O(1). Verified.
- **Reclaim throttling.** `AgentRunner` no longer reclaims every tick per
  topic (memory line 20). Verified.
- **Telemetry coverage.** `predict.request/vote/final` + `models.events.v1`
  added to telemetry (memory line 21). Verified.
- **Consensus quorum-empty path.** `note_request` is now reachable from the
  bus (memory lines 30–34). Verified.
- **Schema↔payload drift.** `test_dataclass_payload_satisfies_schema`
  (Audit Pass 3 B3, memory) covers six payloads. Plus the Phase 5 cpu-parity
  suite. The drift class B1 surfaces above is **enum cardinality** drift, not
  shape drift — a different test family.
- **Config triangle.** `defaults.yaml` ↔ `config.py` ↔ `.env.example`
  guard tests are green; SWARM_* prefix added in Audit Pass 4 (memory line 146).
- **Phase 5 single-publication + idempotency.** Ledger-keyed on deterministic
  `prediction_id` (memory line 26). Verified.
- **Score-grid fusion uses Poisson recurrence.** ~3-5x speedup over per-cell
  factorial (memory line 27). Verified.

---

## 6. Long-shot: questions for the human before Phase 6 PR

1. Quorum formula in ROADMAP §6.1 — strict super-majority (`⌈N/2⌉+1`,
   default N=5) or simple majority (`⌊N/2⌋+1`, default N=3)? **§D4 above.**
2. Cache topology: A / B / C from §B2? Recommend **A** (`predict.approved.v1`).
3. Are `ai/proofreader/validator.py` range tables authoritative, or should
   Phase 6 re-derive from `betting_markets.json`? **§B3.**
4. KS-test feature drift in §6.3 — ship in same PR (needs feature snapshot
   store + scipy or hand-rolled KS) or land accuracy-floor first and KS
   later? Recommend **defer KS to a §6.3.b sub-phase**.

---

*End of audit. Tracker entry recommended: `make track.add PHASE=5 STATUS=in-progress
NOTE="Pre-Phase 6 audit recorded gaps B1–B5, design decisions D1–D4, perf items P1–P6
at docs/reports/pre-phase6-audit.md"`. No version bump — doc-only.*
