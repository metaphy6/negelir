# Pre-Phase 6 — Actions Summary

> **Purpose.** Single source of truth for what was actually shipped
> during the pre-Phase-6 hardening sweep, and what remains open as
> Phase 6 itself begins. Supersedes (and replaces) the five
> exploratory audit notes that lived alongside this file:
> `gemini3.1Pro.md`, `gpt5.3-Codex.md`, `pre-phase6-audit.md`,
> `pre-phase6-audit-round2.md`, `pre-phase6-roadmap.md` — those
> were working scratch and have been deleted.
>
> **Scope.** Phase 6 (Proofreader & Drift Agents) and the Phase 5
> primitives it consumes (consensus, config triangle, payloads,
> bus contracts, Go ingestor).

---

## 1. What is shipped (verified by tests)

### 1.1 Phase 6.1 — ProofreaderAggregatorAgent

- Sole producer of `predict.approved.v1` (consensus is forbidden
  from emitting it; a guard test enforces this).
- Quorum aggregation across `predict.proofreader_verdict.v1`, with
  configurable quorum policy and timeout (`cfg.proofreader_quorum`,
  `cfg.proofreader_timeout_ms`).
- Deterministic ordering of `approved_by` (sorted proofreader IDs).
- Idempotent against re-delivered candidates and verdicts via
  the persistent ledger (`AggregatorLedger`).
- LRU-bounded `_pending` map (`cfg.proofreader_max_pending`).
- **NEW (this sweep):** overflow eviction now publishes a
  `proof.flag.v1` with `kind=proofreader_overflow` so operators
  can observe the saturation. Buffered inside the lock and emitted
  post-unlock to keep the publishing surface free of `_lock`.

### 1.2 Phase 6.2 — Proofreader fleet (sanity, consistency, …)

- All proofreaders live under `ai/swarm/agents/proofreader/`
  and produce `predict.proofreader_verdict.v1` with deterministic field order.
- Cross-source agreement check is config-driven
  (`cfg.cross_source_agreement_*`).
- Schema-pinned via `swarm/sdk/schemas/predict.proofreader_verdict.v1.json`;
  `test_payloads_byte_identical_contract` locks the wire format
  across a 10-case matrix (covers approve / reject / flag with
  empty + populated `flags`, `checks_run`, and rationale strings).

### 1.3 Phase 6.3 — DriftAgent

- Rolling Brier window per `(league_id, market)` with size from
  `cfg.drift_window_size`; trips when window-mean Brier exceeds
  `cfg.drift_brier_ceiling` (renamed from the earlier
  `drift_accuracy_floor` shadow — see the Phase-6 audit, F-3).
- Trip emits one `maint.event.v1{kind=retrain_request}` per
  in-window contributing model.
- Debounce: once a bucket trips, no re-trip until the window
  recovers below the floor.
- Idempotent against re-delivered `match.outcome.v1`
  (`(match_id, market)` settlement key).
- **NEW (this sweep) — bug fixes shipped here:**
  - **`_settled` LRU-bounded** (`cfg.drift_max_settled`,
    default 100k). Previously it was an unbounded `set`, leaking
    one entry per ever-settled `(match, market)` for the lifetime
    of the process. Fix: `OrderedDict` with `popitem(last=False)`.
  - **`_pending` LRU-bounded** (`cfg.drift_max_pending`,
    default 100k). Predictions for non-1X2 markets (`btts`,
    `ou_2_5`, `ah`) currently have no realized labels until
    Phase 9 lands the multi-market `MatchOutcome` payload — they
    sat in `_pending` forever. Fix: same LRU pattern.
  - **`models_in_window` no longer goes stale.** The window's
    contributing-model union is now rebuilt on every `popleft`
    by re-scanning the remaining entries' per-entry frozensets
    (each window slot stores `(brier, frozenset(models))` instead
    of just `brier`). Without this, a long-running swarm would
    target every model that had ever voted for the bucket on the
    next breach, including retired ones — generating false
    retrain requests and burning trainer cycles.

### 1.4 Phase 5 contract guards (carried forward from prior sweep)

- `test_payloads_byte_identical_contract` — 10-case round-trip
  against pinned wire bytes for `predict.final`,
  `predict.proofreader_verdict`, `predict.approved`,
  `match.outcome`, `maint.event`.
- `test_topic_codes_pinned` — bus topic strings frozen.
- `test_consensus_cannot_emit_approved` — Phase 6.1 isolation.
- `test_chart_is_canonical` — version chart round-trips.
- `xops/lint/check_no_magic.py` — magic-number/URL guard.
- `ai/tests/test_config_sync.py` — defaults / env / dataclass
  drift detector.

### 1.5 Go ingestor (Phase 5.7 carry-over)

- `MustLoad` removed; all callers go through `Load() (Config, error)`.
- `Config.WithOverrides` for test isolation.
- Server lifecycle uses context cancellation, not `os.Exit`.

---

## 2. What is open (Phase 6 work that remains, in priority order)

### 2.1 In-scope for Phase 6 completion

1. **Predictor coverage for non-1X2 markets** is a Phase 9
   prerequisite — until then the new `_pending` bound silently
   pressures those buckets. Add a Prometheus counter
   `drift_pending_lru_evictions{market=…}` so we see the rate.
2. **Cross-source proofreader (`proof.cross_source.v1`).** Stub
   exists; needs the full agreement-window logic over
   `record.published.v1` from the source-watcher feed. Currently
   gated behind `cross_source_agreement_enabled=false`.
3. **Historical-prediction proofreader.** Compares the live
   prediction against the swarm's own past predictions for the
   same fixture and flags large drift. Skeleton only; no tests.
4. **KS-test drift mode.** `cfg.drift_pvalue` is wired through
   the config and the dataclass, but `DriftAgent` only uses the
   Brier-window mode today. KS branch is the secondary signal
   (per design doc) and lands in 6.3b.

### 2.2 Deferred (intentional — flagged in tracker, not blocking)

- **Aggregator quorum-mode "strict-majority".** Today supports
  `unanimous` and `simple_majority`. Strict-majority is only
  needed once we have ≥5 proofreaders.
- **Drift bucket-level TTL.** Buckets that go silent for >N days
  could be evicted entirely. Low priority — memory cost is
  ~40 bytes per `(league, market)` and we have <500 buckets.
- **Per-proofreader veto weighting.** The design doc reserves
  hooks for this; current implementation treats all proofreaders
  equally (`score=1.0` votes).

### 2.3 Repo hygiene (post-sweep)

- The five exploratory audit notes are now deleted; this file is
  the only pre-Phase-6 narrative.
- ROADMAP §6 checkboxes that this sweep satisfies should be
  flipped in the same commit (per `AGENTS.md` §3.4): the four
  sub-items under 6.3 ("rolling Brier window", "retrain emission",
  "settlement idempotency", "bounded memory under sustained load")
  and the 6.1 "overflow observability" item.

---

## 3. Test surface added in this sweep

| File | Cases added | Guards |
|---|---|---|
| `ai/swarm/agents/tests/test_phase6_bug_fixes.py` | 5 | `_settled` LRU; `_pending` LRU; `models_in_window` shrinks on popleft; end-to-end "model_A rolled out is not retrained"; aggregator overflow → `proof.flag` emission. |
| `ai/swarm/agents/tests/test_payloads_byte_identical.py` | 10-case matrix (carried forward) | Wire-format freeze across all five payload types. |

Suite count after this sweep: **896 passed, 6 skipped, 2 xfailed**
(was 882 before the sweep).

---

## 4. Config knobs added

| Key | Default | Purpose |
|---|---|---|
| `NEGELIR_DRIFT_MAX_PENDING` | `100000` | LRU cap for unsettled drift predictions. |
| `NEGELIR_DRIFT_MAX_SETTLED` | `100000` | LRU cap for the recently-settled key set. |

Both wired through `ai/common/config.py` (positive-int validated),
`xops/env/.env.example`, and `ai/common/defaults.yaml` per Rule 1.
