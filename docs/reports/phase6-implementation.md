# Phase 6 — Proofreader & Drift: Fresh-Eyes Audit + Implementation Roadmap

> **Status:** DRAFT — awaiting human review. **No code edits have
> been made.** This document is the agreed-upon next step before
> any implementation work resumes on Phase 6.
>
> **Audience:** the next agent / human pair that lands the fix
> waves. Read it top-to-bottom; the findings are ordered by
> severity and the roadmap at the end is the dependency-ordered
> fix list.
>
> **Scope:** every file that ROADMAP §6 / `pre-phase6-actions.md`
> claims is part of Phase 6 — proofreader package, drift agent,
> the Phase 6 payloads + topics + schemas, the boundary tests, and
> the config triangle (`ai/common/config.py` + `defaults.yaml` +
> `xops/env/.env.example`).
>
> **Method:** the audit was performed without trusting any prior
> doc. Each ROADMAP §6 claim was checked against the actual file.
> Tests were read for what they prove (not what their names
> promise). Suite baseline: **899 passed, 6 skipped, 2 xfailed**
> (verified at the start of this audit; no run-time changes).

---

## 1. Executive summary

**Verdict: ship-with-fixes.** Phase 6 is structurally sound but
carries one *silent* configuration regression that affects Phase 5
behaviour (a duplicate dataclass field shadows the legacy
`drift_accuracy_floor` knob), one *operational* gap (no production
swarm bootstrap registers Phase 6 agents — they pass tests but
never run on a real bus), and one *robustness* hazard (a single
replica raising an internal exception is converted into a `reject`
vote, which is fatal regardless of quorum and lets one buggy
replica DoS the whole pipeline). The remaining issues are minor:
documentation drift in `pre-phase6-actions.md`, doc inversion in
the "drift_accuracy_floor" name (it's a Brier ceiling), and a
runner-loop gap (`flush_expired` is never invoked on a wall-clock
tick) that Phase 6 inherits from Phase 5.

The core algorithms — quorum aggregator with running counters,
ledger-idempotent finalise, rolling Brier window with
reference-counted `models_in_window`, LRU-bounded `_pending` /
`_settled`, debounced trip-once-per-window-rollover — are
correctly implemented and well-tested. The two named topics
(`predict.proofreader_verdict.v1` and `predict.approved.v1`),
their schemas, and the Phase 6 dataclasses (`ProofreaderVerdict`,
`PredictApproved`, `MaintEvent`, `MatchOutcome`) are present,
match the ROADMAP §6 contract, and pass byte-identical wire
tests. Boundary discipline is enforced by parameterised tests
across all five rules.

What's left is a focused fix wave (4 blockers / majors, 3 minors)
that should be small in diff size — total estimate ≈ 250-350 LoC
added + tests, no schema changes, no API breakage.

---

## 2. Per-file audit

For each file: **purpose** (one line) → **what it actually does**
→ **assumptions** → **discrepancies vs ROADMAP §6** → **verdict**.

### 2.1 `ai/swarm/agents/proofreader/aggregator.py`

**Purpose:** Sole producer of `predict.approved.v1`; consumes
`predict.final` candidates and `predict.proofreader_verdict.v1`
votes; tallies quorum inside a window; emits `proof.flag` for the
six failure modes.

**What it does:**
- Subscribes `(PREDICT_FINAL, PROOFREADER_VERDICT)`, publishes
  `(PREDICT_APPROVED, PROOF_FLAG)`, name
  `proofreader_aggregator.v1`.
- Per-`prediction_id` `_Pending` record stores the candidate +
  per-replica verdicts in a `dict[proofreader_id]`. Running tally
  fields `_accept_warn_count` / `_reject_count` are maintained
  by `set_verdict()` so quorum / reject checks are O(1) (the
  Phase 5 pre-audit fix carried over here too).
- `_pending` is insertion-ordered for LRU eviction; bound is
  `cfg.consensus_max_pending` (shared with consensus — see
  finding F-3 below).
- `_finalize` is **ledger-idempotent on `prediction_id`**; a
  redelivered candidate or verdict can never produce a second
  approval. Late verdicts after finalise emit
  `proofreader_late_verdict_dropped`.
- `flush_expired(now_ms=…)` scans `_pending` for windows that
  have elapsed since `first_seen_ms` and emits no-quorum flags.
- Overflow eviction buffers the evicted `_Pending` *inside the
  lock* but emits the `proofreader_overflow` flag *after the
  lock is released* (mirrors the consensus-overflow pattern).
- A single `reject` is fatal regardless of quorum
  (§6.1 contract).

**Assumptions (verified):**
- `prediction_id` is content-derived (Phase 5), so collision
  risk after LRU eviction is negligible.
- The runner / scheduler invokes `flush_expired` on a wall-clock
  tick. **Not actually wired** — see finding F-2.
- `proofreader_id` is unique per replica class — verified by
  `test_replicas_have_distinct_names_and_correct_topics`.

**Discrepancies / risks:**
- The class has no production registration. See F-1.
- `_lock` is held during `_handle_*`; this serializes the agent
  with itself, which is fine for a single runner thread but
  means K8s-replica scaling of the *aggregator* is impossible
  without external coordination. ROADMAP §6.1 implicitly assumes
  one aggregator instance per swarm, but it isn't asserted
  anywhere. Minor — the boundary test could pin it.
- `verdict_count` in `proofreader_no_quorum` is the number of
  *distinct replicas* that voted, not the total messages
  received. The payload field name is honest, but operators
  reading the flag need to understand that "verdict_count: 1"
  with `proofreader_replicas=3` means two replicas didn't vote.

**Verdict:** Correct as-implemented. Wiring + threading caveats
go to the roadmap.

---

### 2.2 `ai/swarm/agents/proofreader/replicas.py`

**Purpose:** Three concrete `_BaseProofreaderAgent` subclasses
(Sanity / Plausibility / Consistency) that each subscribe to
`predict.final`, run **one** pure check from
`prediction_checks.py`, and emit one
`predict.proofreader_verdict.v1`.

**What it does:**
- `_BaseProofreaderAgent.handle()` parses `PredictFinal`, calls
  `self._check(final)`, builds the verdict, emits one message.
- The dispatch shell catches **any** exception from `_check` and
  converts it to `verdict="reject"`. **This is the source of
  finding F-4 (Major).**
- `flags` is set to `list(self.checks_run)` only when `verdict !=
  "accept"`; the payload's `__post_init__` validates `flags ⊆
  checks_run`.
- Each replica reads its threshold from `cfg` at `__init__` time
  (not at handle-time). Live config reloads require a restart.
  Documented behaviour, not a bug — but worth the operator note.

**Assumptions (verified):**
- One replica instance per check — `test_replicas_have_distinct_names…`
  confirms three distinct names.
- `score_grid` may be absent (`None`) — Consistency returns
  `accept` in that case; `test_consistency_replica_accepts_when_no_grid`.

**Discrepancies / risks:**
- **F-4 (Major):** `except Exception → reject`. A code bug in any
  one replica becomes a `reject` vote, and one reject vetoes
  approval regardless of quorum. One buggy replica → entire
  prediction stream silently killed. The right behaviour: emit
  a `proof.flag` with kind `proofreader_internal_error` and
  *don't* vote. Or, at most, emit a `warn` so the candidate
  still has a path to quorum if the other replicas accept.
- The `**kw: object` typing in subclass `__init__` and the `# type:
  ignore[arg-type]` are technical debt that mypy hides; minor.

**Verdict:** Correct happy-path; F-4 is a real correctness gap.

---

### 2.3 `ai/swarm/agents/proofreader/prediction_checks.py`

**Purpose:** Pure functions for the three replica checks. No
imports from agents / bus / payload modules — bottom of the
dependency graph.

**What it does:**
- `sanity_check(distribution, eps)` — every market_outcome value
  is finite, in [0,1], sum within `eps` of 1.0; reject on any
  failure.
- `plausibility_check(distribution, max_outcome_prob)` — warn
  when any outcome > cap; non-numeric values are silently
  skipped (sanity owns that branch).
- `grid_consistency_check(distribution, tol)` — if `score_grid`
  is present, its 1X2 marginals must match `market_outcomes`
  within `tol`; otherwise reject. `score_grid=None` → accept.

**Assumptions (verified):**
- Only 1X2 marginals are checked from `score_grid` — the
  docstring acknowledges OU/BTTS extension is deferred.
- `market_outcomes` keys are `"H"`, `"D"`, `"A"` exactly (case-
  sensitive). Predictor / consensus code emits this casing
  consistently, but there's no normalisation pass — see F-7.

**Discrepancies / risks:**
- None functional. Test coverage is good (10+ cases).
- The "sanity" name is semi-misleading: it doesn't validate the
  *meaning* of the keys, just the numerics. If a predictor
  emitted `{"home": 0.5, "draw": 0.3, "away": 0.2}` the sanity
  check would pass and grid_consistency would silently accept
  too (no `H`/`D`/`A` keys present → marginals diverge from `0`,
  flagged only if `score_grid` is also attached). Minor —
  upstream contract enforcement.

**Verdict:** Correct.

---

### 2.4 `ai/swarm/agents/proofreader/checks.py` (legacy, kept alive)

**Purpose:** The legacy match-data checks (range / consistency /
plausibility) that the pre-Phase-6 `DataProofreader` used to own.
Re-exported by the legacy shell; tested by
`test_legacy_proofreader_shell.py` for byte-identical parity.

**What it does:** Faithful copy of the legacy logic, parameterised
on a `dict` match payload. `range_check`, `consistency_check`,
`plausibility_check` each return `(errors, warnings)`.

**Discrepancies:**
- These rules operate on **match records**, not on **predictions**.
  They live next to the new prediction-level checks in the same
  package, which is mildly confusing. The `__init__.py` re-exports
  both flavours under different names (`plausibility_check` vs
  `prediction_plausibility_check`). Worth a docstring at package
  level disambiguating; not a correctness issue.

**Verdict:** Correct; minor naming hygiene.

---

### 2.5 `ai/swarm/agents/drift.py`

**Purpose:** Sole producer of `maint.event.v1{kind=retrain_request}`.
Subscribes to `predict.approved.v1` (record predicted distribution)
and `match.outcome.v1` (settle, compute Brier).

**What it does:**
- Per-`(league_id, market)` rolling Brier window. `_Window` keeps
  `entries: deque[(brier, frozenset(models))]`, a reference-counted
  `Counter` for `models_in_window`, and a running `_brier_sum`. All
  operations are O(|models per entry|) — popleft correctly
  decrements the per-model refcount.
- LRU-bounded `_pending` (`cfg.drift_max_pending`, default 100k)
  and `_settled` (`cfg.drift_max_settled`, default 100k).
- Trip semantics:
  - Only fires when the window is **full** (`len(entries) >=
    window_size`).
  - Compares `mean_b > self._floor` (note: `_floor` is a Brier
    *ceiling*, see F-5 — the comparison direction is correct).
  - Debounce: `_tripped: set[(league, market)]` blocks re-trip
    until `mean_b <= floor` again.
- On trip, emits one `MaintEvent(kind=retrain_request)` per model
  in `models_in_window`. v1 attribution = "every model that
  contributed to in-window predictions" — acknowledged
  conservatism (per-predictor Brier is Phase 9).
- Settles only `market == "1x2"` from `MatchOutcome`. Other
  markets sit in `_pending` until evicted by LRU. Documented;
  acceptable for v1.
- Idempotent on redelivered outcomes via `_settled`.

**Assumptions (verified):**
- `outcome.outcome_1x2 ∈ {H, D, A}` — enforced by
  `MatchOutcome.__post_init__`.
- `predict.approved.v1` carries `final.contributing_models` and
  `final.distribution.market_outcomes` — both required, agent
  drops the message with a warning if missing.
- One drift agent instance per swarm (single producer of
  `maint.event.v1`); enforced by the boundary tests.

**Discrepancies / risks:**
- **F-5 (Minor):** Naming inversion. `cfg.drift_accuracy_floor`
  is the threshold for a Brier *ceiling* (lower Brier = better,
  so we trip when `mean > floor`). ROADMAP §6.3 acknowledges
  this and defers an alias `drift_brier_ceiling` to Phase 9.
  Worth at minimum fixing the field's docstring to reduce
  surprise; an alias property is even better.
- **F-1 (Blocker):** No production registration — same gap as
  the proofreader agents. The drift agent can never observe a
  real `predict.approved.v1` until something registers it on a
  live bus.
- The `models_in_window` retrain attribution can over-fire when
  one predictor is good and another is bad (both share the
  bucket). The doc acknowledges this is the v1 substitute. Minor.
- Market case sensitivity: `key[1] == "1x2"` is exact-match. If
  any producer emits `"1X2"`, it never settles. F-7.

**Verdict:** Correct + well-tested algorithm. Production wiring
+ naming polish needed.

---

### 2.6 `ai/swarm/agents/topics.py`

All four Phase 6 constants are present and match the ROADMAP §6
contract:

| Constant | String | ROADMAP claim | Match? |
|---|---|---|---|
| `PREDICT_APPROVED` | `predict.approved.v1` | §6 cross-phase block | ✓ |
| `PROOFREADER_VERDICT` | `predict.proofreader_verdict.v1` | §6.1 | ✓ |
| `MAINT_EVENT` | `maint.event.v1` | §6.3 | ✓ |
| `MATCH_OUTCOME` | `match.outcome.v1` | §5 (storage), reused §6.3 | ✓ |

**Discrepancy:** `pre-phase6-actions.md` §1.3 says the verdict
topic is `proof.verdict.v1` and the schema lives at
`proof.verdict.json`. The actual code/topic is
`predict.proofreader_verdict.v1` with schema
`predict.proofreader_verdict.v1.json`. **The pre-action doc is
stale, not the code.** F-6 below.

---

### 2.7 `ai/swarm/agents/payloads.py` — Phase 6 dataclasses

**`ProofreaderVerdict`** — frozen dataclass with `__post_init__`
validation: verdict ∈ {accept, warn, reject}, score ∈ [0,1],
`flags ⊆ checks_run`. Round-trips via `as_dict` /
`from_dict`. ✓

**`PredictApproved`** — frozen, validates: `approved_by` non-empty,
`verdict_count >= len(approved_by)`, `quorum >= 1`,
`len(approved_by) >= quorum`, `final` is the full
`PredictFinal` dict, `final.prediction_id == prediction_id`. ✓

**`MaintEvent`** — frozen, validates: `kind ∈ {retrain_request,
recalibration_request}`, `reason ∈ {brier_floor, logloss_floor,
feature_ks}` when kind is retrain_request, `target` non-empty.
The `feature_ks` reason is reserved for the deferred KS-test
branch; the v1 drift agent only emits `brier_floor`. ✓

**`MatchOutcome`** — frozen, validates: scores >= 0, `outcome_1x2 ∈
{H, D, A}`. Optional fields for OU/BTTS, league_id, record_id. ✓

**`ProofFlagKind`** — closed-vocabulary class; the six Phase 6
kinds match the schemas exactly. Verified by
`test_proof_flag_kinds.py::test_registry_matches_schema_enum`. ✓

**Verdict:** All payloads are correct, validate aggressively, and
have byte-identical round-trip tests.

---

### 2.8 `ai/swarm/sdk/schemas/*.json`

All four Phase 6 schemas exist with the expected names:

- `predict.approved.v1.json`
- `predict.proofreader_verdict.v1.json`
- `maint.event.v1.json`
- `match.outcome.v1.json` (Phase 5, reused)

Validation is exercised by
`ai/swarm/agents/tests/test_schemas_match_payloads.py` against
example payloads built from each dataclass. The
`test_schemas_additional_properties.py` test confirms `additionalProperties:
false` is set where expected.

**Verdict:** No drift between code and schema.

---

### 2.9 `ai/common/config.py` — Phase 6 knobs

**The 10 Phase 6 knobs are present** and triangle-mirrored in
`xops/env/.env.example` and `ai/common/defaults.yaml`:

| Field | Env | Default | Triangle |
|---|---|---|---|
| `proofreader_replicas` | `NEGELIR_PROOFREADER_REPLICAS` | 3 | ✓ |
| `proofreader_quorum_window_ms` | `…_QUORUM_WINDOW_MS` | 200 | ✓ |
| `proofreader_sanity_eps` | `…_SANITY_EPS` | 0.01 | ✓ |
| `proofreader_plausibility_max_prob` | `…_PLAUSIBILITY_MAX_PROB` | 0.85 | ✓ |
| `proofreader_grid_consistency_tol` | `…_GRID_CONSISTENCY_TOL` | 0.05 | ✓ |
| `drift_window_size` | `NEGELIR_DRIFT_WINDOW_SIZE` | 50 | ✓ |
| `drift_accuracy_floor` | `NEGELIR_DRIFT_ACCURACY_FLOOR` | 0.30 | **F-3 (Blocker)** |
| `drift_pvalue` | `…_PVALUE` | 0.01 | ✓ |
| `drift_max_pending` | `…_MAX_PENDING` | 100000 | ✓ |
| `drift_max_settled` | `…_MAX_SETTLED` | 100000 | ✓ |

Plus the derived `proofreader_quorum` `@property` (computes
`⌊N/2⌋+1`, always ≥1 — verified). ✓

**F-3 (Blocker):** `drift_accuracy_floor` is **defined twice**:
- Line 262 (Phase 5, env `NEGELIR_DRIFT_FLOOR`, default 0.35)
- Line 392 (Phase 6, env `NEGELIR_DRIFT_ACCURACY_FLOOR`, default 0.30)

In a Python dataclass, the second declaration silently shadows
the first. **Effect:** the Phase 5 legacy `ai/model/drift.py`
detector (which reads `cfg.drift_accuracy_floor` and was tuned for
the 0.35 default) now silently uses 0.30, and the
`NEGELIR_DRIFT_FLOOR` env var has no effect at all. Operators
who set it think they're tuning the legacy detector but they're
not — the value is silently discarded.

The legacy `drift_accuracy_window` (line 261, env
`NEGELIR_DRIFT_WINDOW`, default 30) survives because it has a
distinct field name from the Phase 6 `drift_window_size` (line
391, env `NEGELIR_DRIFT_WINDOW_SIZE`, default 50) — both fields
exist and both are read by their respective consumers. So the
window split is intentional and works; only the floor is broken.

**Effect on `defaults.yaml`:** documents both 0.35 and 0.30 as
if they were different knobs (lines 107 and 190). Operator
confusion is the inevitable downstream cost.

---

### 2.10 Tests

| File | LoC | What it actually proves |
|---|---|---|
| `test_proofreader_aggregator.py` | 397 | Quorum (pass / fail / `warn`-counts-as-yes), reject-veto fatal-regardless-of-quorum, verdicts-before-final ordering, ledger idempotency on candidate + verdict re-emit, late-verdict drop with flag, no-quorum window-elapsed flag (via `flush_expired`), `flush_all`, malformed message drops, replica vote-flip overwrites the running tally correctly, single-replica edge case, default `quorum` reads `cfg.proofreader_quorum`. |
| `test_proofreader_replicas.py` | 179 | Replica identity / topic contract, malformed input is dropped silently, sanity accept / reject by sum, plausibility warn / accept by cap, consistency accept-when-no-grid / reject on diverging marginals, **end-to-end three-replica → aggregator → predict.approved happy path** (no real bus). |
| `test_prediction_checks.py` | 189 | Pure-function adversarial coverage (NaN, negatives, missing keys, `score_grid` malformed entries, etc.). |
| `test_proofreader_checks.py` | 168 | Legacy match-record range / consistency / plausibility coverage. |
| `test_legacy_proofreader_shell.py` | 187 | Byte-identical contract: `DataProofreader.validate_match` ≡ direct composition of the three pure functions across a 10-case matrix incl. the gpt5-Codex#2 `"x"` non-numeric crash repro. |
| `test_drift.py` | 274 | Brier helper sanity (perfect / uniform / max-wrong), agent contract, malformed payload drops, half-full window does NOT trip, full-window breach emits one MaintEvent per contributing model, full-window-within-floor does not trip, debounce (no re-trip until recovery), redelivered outcome no-double-score, isolated buckets per league. |
| `test_phase6_bug_fixes.py` | 266 | The four pre-Phase-6 sweep regressions: `_settled` LRU, `_pending` LRU, `models_in_window` shrinks on popleft, end-to-end "model_A rolled out is not retrained", aggregator overflow → `proof.flag` emission. |
| `test_boundary_discipline.py` | ≈220 | Five rules: storage-only `match.outcome.v1` producer (vs predictors / consensus / aggregator / replicas), cache does NOT subscribe to `predict.final` and DOES subscribe to `predict.approved.v1`, `predict.approved.v1` aggregator-only, `maint.event.v1` drift-only, `predict.proofreader_verdict.v1` per-replica only with aggregator as sole consumer. |
| `test_match_outcome.py` | 201 | `match.outcome.v1` schema registered; storage emits exactly once on terminal status; nested score block accepted; non-terminal / unchanged / fixture / missing-scores all correctly suppress. |
| `test_proof_flag_kinds.py` | 73 | Closed-vocabulary registry matches schema enum byte-for-byte. |

**Skipped / xfailed inventory (relevant to Phase 6):** none. The
6 skipped tests in the suite are all unrelated (mock-data /
optional Redis backends).

**Test-coverage gap audit:**
- ✓ Quorum policy variants (N=1 unanimity, N=3 default).
- ✓ Reject-veto fatal regardless of quorum.
- ✓ Replica vote-flip preserves running counters.
- ✓ Late verdict / duplicate approval / overflow flags.
- ✓ Drift LRU bounds, model-window cleanup, debounce.
- ✗ **No test that a buggy replica (raises) does not silently
  veto** — F-4 below.
- ✗ **No test that `flush_expired` is invoked by the runner on
  a wall-clock tick** — there's no production-side glue, so the
  no-quorum flag is only producible from inside tests. F-2.
- ✗ **No test verifying `cfg.drift_accuracy_floor` reads the
  correct default** — would catch F-3 trivially.
- ✗ **No test that the swarm bootstrap registers Sanity /
  Plausibility / Consistency / Aggregator / Drift on a real bus
  + runner pair** — there is no swarm bootstrap. F-1.
- ✗ **No assertion that `proofreader_aggregator.v1` is the
  unique instance per swarm** (boundary test could pin this).

---

## 3. Cross-phase alignment

| Phase 6 contract | Counter-party | Aligned? | Notes |
|---|---|---|---|
| `predict.final` consumer | Phase 5 consensus produces it | ✓ | Replica subscribes; aggregator subscribes. |
| `predict.approved.v1` producer | Phase 4 cache subscribes | ✓ | Cache wired in `cache.py`. |
| `predict.approved.v1` consumer (drift) | Phase 6.3 drift | ✓ | Drift subscribes. |
| `match.outcome.v1` producer | Phase 5 storage | ✓ | Single-emission-on-terminal-status verified by `test_match_outcome.py`. |
| `match.outcome.v1` consumer | Phase 6.3 drift | ✓ | Drift subscribes. |
| `maint.event.v1` producer | Phase 6.3 drift | ✓ | Single producer per boundary test. |
| `maint.event.v1` consumer (trainer) | **Phase 5 TrainerReactor** | ⚠️ | Telemetry subscribes for metrics; no trainer-side subscriber yet. Phase 6.3 → Phase 9 hand-off is the next dependency. |
| `proof.flag` producer (Phase 6 kinds) | Phase 4 telemetry consumer | ✓ | Six new kinds in the registry; schema enum kept in lockstep. |
| `cfg.proofreader_quorum` derived from `proofreader_replicas` | Aggregator default | ✓ | `test_aggregator_quorum_default_from_config`. |
| Phase 5 `consensus_max_pending` reuse | Aggregator's pending bound | ⚠️ | Aggregator borrows the consensus knob — fine for v1 but should have its own knob if they ever need to diverge. F-9. |
| `cfg.drift_accuracy_floor` consumer (Phase 5 model/drift) | `ai/model/drift.py` | ❌ | **F-3 silent regression** — Phase 5 detector now uses 0.30 instead of its tuned 0.35. |

---

## 4. Findings registry

Numbered, severity-ordered. Each finding has a one-line shape, a
recommended fix, and a rough diff-size estimate.

### F-1 — No production swarm bootstrap registers Phase 6 agents · **Blocker**

**Shape.** `SanityProofreader`, `PlausibilityProofreader`,
`ConsistencyProofreader`, `ProofreaderAggregatorAgent`, and
`DriftAgent` are constructed **only** in tests. There is no
`swarm/main.py` or equivalent bootstrap that registers them on a
real bus / runner pair. `grep` for the class names across `ai/**`
finds zero non-test instantiations. Same gap exists for Phase 4
agents but the impact is more visible at Phase 6 because Phase 6
is the first place where the user-visible `predict.approved.v1`
contract depends on agent wiring.

**Why it matters.** ROADMAP §6.4 DoD says "predict.approved.v1
emitted on the bus once quorum reached". This is true in the
unit tests but not in any deployable artifact. The pipeline is
silently inert at runtime.

**Fix.** Add `ai/swarm/bootstrap.py` (or extend whatever Phase 4
shipped as the bootstrap) that registers all Phase 4-6 agents
against the configured `swarm_bus_kind` and starts an
`AgentRunner` per agent. Add a smoke test that spawns the
bootstrap with a fake in-memory bus, drives one
`predict.request` end-to-end, and asserts a `predict.approved.v1`
lands on the bus.

**Diff:** ~120 LoC bootstrap module + 80 LoC smoke test.
**Dependency:** none — pure addition. Should land first.

---

### F-2 — `flush_expired` never invoked from the runner · **Blocker**

**Shape.** `ProofreaderAggregatorAgent.flush_expired` and
`ConsensusAgent.flush_expired` are designed to be called on a
wall-clock tick to advance time when no message arrives to
trigger `handle()`. The `AgentRunner` (`ai/swarm/sdk/runner.py`)
has a `tick_sec` loop but does not call `flush_expired` on the
agent.

**Why it matters.** Without this, the no-quorum / window-elapsed
path is unreachable in production. A prediction stuck at 1/2
votes sits in `_pending` until LRU eviction (which emits a
*different* flag — `proofreader_overflow`, not
`proofreader_no_quorum`). Operators get the wrong signal; the
SLA budget (`api_consensus_overhead_ms`) accounting becomes
fictional.

**Fix.** Extend `AgentRunner` to detect `flush_expired` on the
agent and call it once per tick (or with a configurable
flush_interval_sec to avoid hot-loop overhead). Add a runner
test that proves the call happens for both `ConsensusAgent` and
`ProofreaderAggregatorAgent`. Add an end-to-end test that
asserts `proofreader_no_quorum` lands on the bus when the
verdicts never reach quorum.

**Diff:** ~40 LoC runner change + 60 LoC tests.
**Dependency:** F-1 (the bootstrap test exercises this path
implicitly). Land second.

---

### F-3 — `drift_accuracy_floor` declared twice; legacy default silently overwritten · **Blocker**

**Shape.** `ai/common/config.py` defines `drift_accuracy_floor`
on line 262 (Phase 5, default 0.35, env `NEGELIR_DRIFT_FLOOR`)
and again on line 392 (Phase 6, default 0.30, env
`NEGELIR_DRIFT_ACCURACY_FLOOR`). Python dataclass evaluation
keeps the second; the first is dead. `NEGELIR_DRIFT_FLOOR` env
var is silently ignored.

**Why it matters.** `ai/model/drift.py` is a Phase 5 detector
tuned for a 0.35 floor; it now reads 0.30. That changes
detection behaviour without anyone changing config. The triangle
docs (`defaults.yaml` lines 107 / 190 and `.env.example` lines
117 / 267) still show both knobs as if they were independent.

**Fix.** Decide policy:
- **Option A (preferred):** rename the Phase 6 field to
  `drift_brier_ceiling` (the semantically honest name), point
  the drift agent at it, and restore `drift_accuracy_floor =
  0.35` for the legacy detector. Add an alias `@property` if
  any external caller still imports the old name.
- **Option B:** delete the legacy line-262 field, accept that
  the legacy detector now uses 0.30, document it in the tracker
  + version bump.
- Either way, **add a unit test** (`test_config_no_duplicate_fields`)
  that walks `dataclasses.fields(_Cfg)` and asserts no two
  fields have the same name or same env var.
- Update `.env.example` and `defaults.yaml` triangle entries.

**Diff:** ~30 LoC config + 25 LoC test + triangle doc rows.
**Dependency:** none. Safe to land first.

---

### F-4 — Replica internal exception → reject (single-replica DoS) · **Major**

**Shape.** `_BaseProofreaderAgent.handle` line 88-94:
```python
try:
    verdict, score, details = self._check(final)
except Exception:
    _log.exception("%s: check raised; emitting reject", self.name)
    verdict, score, details = ("reject", 1.0, [f"…: internal check error"])
```
combined with the aggregator's "any reject is fatal regardless
of quorum" rule means **one buggy replica DoS-es the entire
prediction stream** until somebody notices the reject flood.

**Why it matters.** Doctrine §2 Rule 4 ("smallest model that
works") and Rule 7 ("adversarial tests are first-class") imply
that internal failures should not be confused with content
violations. A code bug in Plausibility shouldn't kill a
prediction that Sanity + Consistency both accept.

**Fix.** Change the except branch to:
- emit a `proof.flag` of a **new** kind
  `proofreader_internal_error` (add to `ProofFlagKind` registry +
  schema enum), and
- emit a `ProofreaderVerdict(verdict="warn", score=0.0,
  flags=["internal_error"], …)` so the candidate still has a
  path to quorum if the others accept; the warn vote counts as
  a yes (matching today's plausibility-warn semantics) but the
  flag tells operators which replica is broken.
- Alternatively: emit nothing (no verdict) and only the flag.
  This is cleaner but means a 3/3 replica swarm with one
  broken replica falls below quorum — possibly surprising.

Recommended: emit both the flag and a `warn` vote. Add a unit
test that injects a `monkeypatch` raising `_check` and asserts
the candidate is approved when the other two replicas accept.

**Diff:** ~40 LoC replicas + payload registry + schema + ~50 LoC
tests.
**Dependency:** none.

---

### F-5 — `drift_accuracy_floor` is a misnomer (Brier is a ceiling) · **Minor**

**Shape.** Lower Brier = better; the agent trips when
`mean > floor`. So `drift_accuracy_floor` is semantically a
*ceiling*. ROADMAP §6.3 acknowledges this and reserves
`drift_brier_ceiling` for Phase 9.

**Why it matters.** Operator confusion. A new on-call may set
"floor=0.10" expecting tighter tolerance and effectively *relax*
the trigger.

**Fix.** Two options, not mutually exclusive:
- Add a `@property drift_brier_ceiling(self) -> float` returning
  the same value, and update the drift agent's docstring +
  trip-line comment to use the property name.
- If F-3 is fixed via Option A above, just rename the field.

**Diff:** ~5 LoC + docstring updates.
**Dependency:** F-3 (do them in the same fix wave).

---

### F-6 — `pre-phase6-actions.md` documents the wrong topic / schema name · **Minor (doc only)**

**Shape.** `pre-phase6-actions.md` §1.3 says proofreaders produce
`proof.verdict.v1` with schema `swarm/sdk/schemas/proof.verdict.json`.
The actual code/topic is `predict.proofreader_verdict.v1` with
schema `predict.proofreader_verdict.v1.json`.

**Why it matters.** The next agent reading the pre-action doc as
context will believe the wrong topic name and may try to
"reconcile" the code with the doc.

**Fix.** Edit `pre-phase6-actions.md` to use the actual topic +
schema names. Do **not** rename the topic in code — the existing
name correctly mirrors the `predict.*` family naming.

**Diff:** ~6 LoC doc edit.
**Dependency:** none. Could land standalone.

---

### F-7 — Market key case sensitivity has no normalisation pass · **Minor**

**Shape.** `DriftAgent` settles only when
`approved.market == "1x2"` (lowercase, exact). `prediction_checks`
expects `market_outcomes` keys in `{"H", "D", "A"}` (uppercase,
exact). Predictor / consensus emit consistently today, but no
contract test pins it; a future predictor migration that uses
`"1X2"` or `"home"` would silently break drift / consistency.

**Why it matters.** Defence in depth. Phase 13a multi-league /
multi-market work will add new predictors and the silent-drop
path is hard to debug.

**Fix.** Add a one-liner normalisation in
`PredictApproved.__post_init__` (lower-case `market`) and in
`prediction_checks` (uppercase the outcome keys before lookup).
Pin the contract with a test.

**Diff:** ~15 LoC + ~30 LoC tests.
**Dependency:** none. Low priority; land in a polish wave.

---

### F-8 — Per-replica thresholds cached at `__init__`; no live reload · **Minor / Cosmetic**

**Shape.** `SanityProofreader(eps=…)` reads
`cfg.proofreader_sanity_eps` once at construction. Same for
plausibility cap and consistency tolerance. Live config reloads
require restarting the agent.

**Why it matters.** Future ops dashboards may want to tune
thresholds without a deploy. ROADMAP doesn't promise live reload
for these knobs, so this is more a documentation note than a
bug.

**Fix.** Document explicitly in the replica docstrings that
threshold changes require restart. If live reload becomes a
requirement later, switch to reading `_cfg` at `_check` time.

**Diff:** ~6 LoC docstrings only.
**Dependency:** none.

---

### F-9 — Aggregator borrows `consensus_max_pending`; no dedicated knob · **Cosmetic**

**Shape.** `ProofreaderAggregatorAgent.__init__` defaults
`max_pending = cfg.consensus_max_pending`. This is fine for v1
because aggregator load is strictly ≤ consensus load, but the
two queues have different shapes and growth dynamics.

**Why it matters.** A future change that bumps consensus's queue
to absorb a burst would silently bump the aggregator too.

**Fix.** Add `proofreader_aggregator_max_pending` knob (default
copies `consensus_max_pending`); update triangle.

**Diff:** ~15 LoC + triangle rows. Defer until Phase 14 unless
something forces it sooner.

---

### F-10 — `ProofreaderAggregator` single-instance assumption is implicit · **Cosmetic**

**Shape.** The aggregator's `_pending` and ledger live in one
process. Running two aggregator instances against the same bus
would split-brain the quorum (each sees half the verdicts) and
double-emit `predict.approved.v1`. ROADMAP §6.1 implies "one
aggregator per swarm" but no code or test asserts it.

**Fix.** Add a runtime guard in the bootstrap (only one
`proofreader_aggregator.v1` registered per swarm) **and** a
boundary test asserting that. The Phase 9 durable ledger will
make multi-instance possible later; this guard prevents
accidental misconfiguration in the meantime.

**Diff:** ~10 LoC bootstrap guard + 10 LoC test.
**Dependency:** F-1.

---

## 5. Implementation roadmap

Dependency-ordered. Each wave includes: code change → test
addition → tracker row → version bump.

### Wave 1 — Configuration safety (lands first; no runtime impact otherwise)

1. **F-3** Resolve duplicate `drift_accuracy_floor` (Option A:
   rename Phase 6 field to `drift_brier_ceiling`, restore
   legacy field, add alias property if needed).
2. **F-5** Drop the misnomer once F-3 lands (the new name is
   already correct).
3. Add `test_config_no_duplicate_fields`.
4. Update `defaults.yaml` + `.env.example` + any references in
   docstrings / docs.
5. **F-6** Edit `pre-phase6-actions.md` topic + schema names.

**Outcome:** legacy detector restored to its tuned threshold, no
silent config shadowing possible going forward.

**Risk:** zero — pure rename + de-dup.

---

### Wave 2 — Replica-failure isolation (one buggy replica should not DoS the pipeline)

1. **F-4** Add `ProofFlagKind.PROOFREADER_INTERNAL_ERROR`,
   schema enum entry, and registry test.
2. Change `_BaseProofreaderAgent.handle` exception branch to
   emit `(verdict="warn", score=0.0)` + a `proof.flag`.
3. Add `test_replica_internal_exception_does_not_veto` that
   monkeypatches `_check` to raise and asserts the candidate
   reaches `predict.approved.v1` when the other replicas
   accept.

**Outcome:** failure-isolation guarantee promised by ROADMAP
§6.2 ("a bug in plausibility cannot mute sanity") becomes true
in the dispatch layer, not just the rule layer.

**Risk:** low — the change is in the dispatch shell; existing
tests stay green.

---

### Wave 3 — Production wiring (makes Phase 6 actually run)

1. **F-1** Add `ai/swarm/bootstrap.py` (or extend Phase 4
   bootstrap) that registers all Phase 4-6 agents on the
   configured bus + runner. Honour `proofreader_replicas` (spawn
   N copies of each replica).
2. **F-10** Bootstrap-side guard: assert a single
   `proofreader_aggregator.v1` and a single `drift.v1` per
   swarm.
3. **F-2** Extend `AgentRunner.run` to call `flush_expired` once
   per `flush_interval_sec` tick (configurable, default = the
   relevant window). Detect the method via `hasattr`.
4. End-to-end smoke test using the in-memory bus that drives
   `predict.request → vote × N → final → verdicts × N → approved`
   and asserts the approval lands on the bus.
5. Second smoke test: verdicts that never reach quorum result in
   a `proofreader_no_quorum` flag after `flush_interval_sec`.

**Outcome:** the DoD claim "predict.approved.v1 emitted on the
bus once quorum reached" becomes operationally true.

**Risk:** medium — first place the wiring is exercised end-to-end.
Expect to find one or two integration glitches (e.g., agent name
collisions in the registry).

---

### Wave 4 — Polish (defer if budget tight)

1. **F-7** Market key normalisation (`PredictApproved` lowercases
   `market`; `prediction_checks` uppercases outcome keys).
2. **F-8** Replica restart-required docstrings.
3. **F-9** `proofreader_aggregator_max_pending` config knob.

---

## 6. Open questions (need human decision)

1. **F-3 Option A vs Option B.** Rename to `drift_brier_ceiling`
   and restore the 0.35 legacy floor (preserves Phase 5 tuned
   behaviour), or keep the field name and accept that the legacy
   detector now uses 0.30? Recommendation: Option A.
2. **F-4 `warn`-vote vs no-vote on internal error.** Recommended
   above is `warn` (counts toward quorum). The alternative is
   no-vote (replica falls silent). Which fits the operator
   model better?
3. **Bootstrap scope.** Should the new `swarm/bootstrap.py`
   also register Phase 4 agents (storage / cache / categorizer
   / processor / etc.) or just Phase 5 + 6? Recommendation:
   register everything available so we have a single deployable
   unit; gate per-agent activation on env vars if needed.
4. **Trainer subscriber for `maint.event.v1`.** Phase 6.3 emits
   the event but no trainer agent subscribes today. Is a
   minimal `TrainerReactor` that logs the request enough for
   this fix wave, or should we wait for Phase 9 / proper
   trainer wiring?
5. **Boundary test scope expansion.** Should Wave 3 also pin
   "no two `proofreader_aggregator.v1` instances per swarm" via
   a registry-level test rather than a bootstrap-level guard?
   The registry already enforces unique agent names so the
   guard may be redundant — needs a quick check.

---

## 7. Self-review notes

I re-read this document end-to-end before publishing. Things to
flag honestly:

- **What I did NOT verify in this audit.** I did not run a
  multi-process integration test against Redis. The boundary
  tests + unit tests cover the static topology and the
  per-agent logic; an end-to-end smoke test is part of Wave 3
  precisely because it does not exist today.
- **What I assumed.** I assumed `prediction_id` is content-derived
  upstream (per Phase 5) so collision after LRU eviction is
  benign. If that ever changes, the aggregator's ledger
  semantics need re-review.
- **What might be wrong.** F-2's claim that `flush_expired` is
  unreachable in production rests on grep results showing no
  caller in `ai/swarm/sdk/runner.py`. There may be an external
  scheduler I missed; the fix wave still wants the runner-side
  call as defence in depth.
- **Severity calibration.** I marked F-1 (no bootstrap), F-2
  (no flush tick), and F-3 (duplicate config field) as
  **Blockers** because each is sufficient to make Phase 6 not
  ship in a deployable state. F-4 is **Major** because the
  pipeline still works in the happy path but fails open-loop
  if a replica has a bug — that's "production hazard" rather
  than "broken on day 1". Reviewers may legitimately disagree
  with this calibration; please push back if so.
- **Diff-size estimates.** All "≈ N LoC" numbers are coarse and
  optimistic. Real diffs tend to be 30-50 % bigger once
  docstrings, comments, and adjacent test fixtures are
  included. Treat them as relative ordering, not commitments.
- **Things this audit deliberately deferred.**
  - The KS-test branch (`feature_ks` reason in `MaintEvent`) —
    correctly reserved in the wire format; build-out is Phase 9.
  - Per-predictor Brier — same reason.
  - Cross-source proofreader (`proof.cross_source.v1` topic) —
    skeleton acknowledged in pre-action doc, no implementation
    visible; not in v1 scope.
  - Historical-prediction proofreader — same.
  - Strict-majority quorum mode — only useful at ≥5 replicas;
    not needed at v1 default of 3.

---

## 8. Acceptance criteria for marking Phase 6 "done" after the fix waves

The following must all hold green simultaneously:

1. `make test.ai` passes (target: ≥ 905 passed after the new tests
   land; current baseline 899).
2. The new bootstrap smoke test produces `predict.approved.v1`
   on an in-memory bus end-to-end.
3. `cfg.drift_accuracy_floor` (or its renamed successor) reads
   the documented default with no env vars set; the legacy
   `ai/model/drift.py` consumer is unaffected.
4. Triangle (`config.py` ↔ `defaults.yaml` ↔ `.env.example`) has
   exactly one row per Phase 6 knob; no shadowed fields.
5. Boundary tests still pass after the bootstrap is added; the
   single-instance guards for aggregator + drift are asserted.
6. `pre-phase6-actions.md` no longer contradicts the actual topic
   / schema names.
7. ROADMAP §6 checkboxes reviewed once more — flip any that the
   bootstrap + flush-tick fixes now satisfy (`AGENTS.md` §3.4).
8. `make track.add` row + `make version.bump` for `swarm` (minor
   for F-1/F-2, patch for the rest) and `docs` (patch).

---

*End of audit. Awaiting human review.*
