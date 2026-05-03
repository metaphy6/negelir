# Phase 4 → 6 — Third-Pass Audit (Pre-Phase-7 Cleanup)

> **Status:** *All approved action items have shipped — see §1.6
> implementation log. Tests:
> `933 passed / 6 env-gated skips / 2 documented xfails` (was
> `550 / 6 / 2` for the swarm subset before this pass; +4 new
> tests cover M1, M2, M3 explicitly).*
> **Auditor brief:** the second pass already shipped (B1, N1, N2,
> e2e regression test for `score_grid` shape). Before
> Phase 7 (`sec.input.v1` / `sec.scrape.v1` / `sec.rate.v1`) starts
> introducing **new producers and new topics**, this pass walks
> Phase 4 – 6 a third time looking for the next layer of issues:
> latent invariant gaps, in-process clock semantics, fusion-shape
> guards, test coverage that hides single-actor behaviour, and
> doctrine drift that Phase 7 will inherit.
>
> Methodology: same as the first-pass report — read every Phase 4 – 6
> agent and the wire layer; cross-check against
> [`docs/planning/ROADMAP.md`](../planning/ROADMAP.md) §§ 4 – 7;
> run a probing subagent for breadth, then **manually verify every
> claim** against the source before recording it (the subagent
> over-reported severity on three findings — they are not in this
> report).

---

## 0. Verdict at a glance

| Phase | Implementation | Severity of newly-found drifts | Phase 7 impact |
|---|---|---|---|
| 4 — Core worker agents | ✅ matches design | **MAJOR ×1**, MINOR ×2 | high: Phase 7 adds two new producers wired through this layer |
| 5 — Predictor swarm + consensus | ✅ matches design | **MAJOR ×2**, MINOR ×1 | low: Phase 7 does not touch fusion |
| 6 — Proofreader + drift | ✅ matches design | **MAJOR ×1** | medium: Phase 7 `sec.input.v1` runs *upstream of* NLP, but `proof.flag` will receive new kinds |
| Cross-cutting | n/a | NIT ×3 | n/a |

**Headline:** there are **no surviving BLOCKERs** — the first-pass
B1 is fixed and tested. There are **four MAJORs** that are cheap to
clear before Phase 7 starts, plus a small set of minors and
documentation NITs. The largest single risk for Phase 7 is the
in-process **wall-clock LRU windows** in consensus / aggregator /
drift (M2 below): Phase 7 adds `sec.rate.v1` which is itself a
sliding-window agent, so we should fix the pattern *once* across
Phase 4 – 6 first instead of carrying a known foot-gun into a fourth
agent.

---

## 1. Scope and method

### 1.1 What this audit covers

- Phase 4.1 – 4.7, Phase 5.1 – 5.6, Phase 6.1 – 6.4 — all sub-sections.
- The **forward boundary** with Phase 7 (`sec.alert` topic, sec
  agents' subscription footprint per ROADMAP §7).
- Single-instance discipline as it stands today, against the
  agent set Phase 7 will add.

### 1.2 What this audit does **not** cover

- Phase 9 (Postgres seams) — already covered in the first pass.
- Pivot v3 layout migration — outside scope; flagged only where it
  creates an easy/hard cliff for the Phase 7 work.
- Phase 14 multi-replica — only the single-instance guard is checked.

### 1.3 Files re-read in full

[`bootstrap.py`](../../ai/swarm/bootstrap.py),
[`consensus.py`](../../ai/swarm/agents/consensus.py),
[`drift.py`](../../ai/swarm/agents/drift.py),
[`proofreader/aggregator.py`](../../ai/swarm/agents/proofreader/aggregator.py),
[`storage.py`](../../ai/swarm/agents/storage.py),
[`reactor.py`](../../ai/swarm/agents/reactor.py),
[`telemetry.py`](../../ai/swarm/agents/telemetry.py),
[`predictors/_grid.py`](../../ai/swarm/agents/predictors/_grid.py),
[`predict.final.json`](../../ai/swarm/sdk/schemas/predict.final.json),
[`predict.vote.json`](../../ai/swarm/sdk/schemas/predict.vote.json),
[`predict.approved.v1.json`](../../ai/swarm/sdk/schemas/predict.approved.v1.json),
ROADMAP §§ 4 – 7,
[first-pass report](./phase4-to-6-implementation.md),
[Phase 6 implementation report](./phase6-implementation.md),
[Phase 6 second-pass report](./phase6-second-pass.md).

### 1.4 Findings the subagent suggested that I am **not** carrying

For transparency — these were proposed by an exploratory subagent
pass and **rejected after manual verification**:

- *"`predict.final.json` is missing `degraded` / `degraded_reason`."*
  Both fields are present at
  [`predict.final.json` L28-L29](../../ai/swarm/sdk/schemas/predict.final.json).
- *"Telemetry counters have unbounded label cardinality."* Counters
  are keyed by **topic only** (`msgs_by_topic`, `dlq_by_topic`,
  `latency_n`, `latency_ms_total`), and the topic enum is the
  fixed `_WATCHED_TOPICS` tuple at
  [`telemetry.py` L46-L72](../../ai/swarm/agents/telemetry.py).
  Cardinality is bounded by the topic count.
- *"Reactor naive-datetime guard silently disables age check."*
  The reactor's parse-error path is documented and intentional —
  the ledger guard is the safety net (see
  [`reactor.py` L143-L145](../../ai/swarm/agents/reactor.py)). The
  `tzinfo is None` branch correctly normalizes to UTC before the
  comparison; the silent except only fires on a true `ValueError`,
  which is a producer contract violation that the ledger
  short-circuits. Worth a *log warning* (carried as **N1** below)
  but not a correctness bug.

### 1.5 Self-review errata (post-publication)

A pre-implementation re-read flushed three findings I had carried
that do **not** survive a careful look at the current code. They
are withdrawn here:

- **(was N2) — "Bootstrap builds *N* processor instances but does
  not assert label-set disjointness."** Withdrawn:
  [`bootstrap.py::build_agents` L122-L148](../../ai/swarm/bootstrap.py)
  wires only the predictor pipeline + cache + telemetry. Phase 4
  producers (storage, processors, categorizer, scrapers) live
  upstream and "are wired by the (separate) datasource bootstrap
  that lands with Phase R1" (per the same docstring at L116-L119).
  There is no `_build_processors` to assert against in the swarm
  bootstrap today. The disjointness check belongs to the
  Phase R1 datasource bootstrap when it lands.
- **(was N5) — "Drift's `_handle_outcome` builds messages inside
  `self._lock`, asymmetric with aggregator."** Withdrawn:
  drift's `_emit_retrain_requests` *constructs* `Message` objects
  inside the lock and returns them up to the handler caller; the
  runner publishes after `handle()` returns. The aggregator's
  `_drain_overflow_locked` does the same thing — builds messages
  inside the lock, returns them, caller emits after release. The
  two patterns are identical. No fix needed.
- **M4 partially wrong.** Originally claimed both `drift.v1` and
  `proofreader_aggregator.v1` use wall-clock for in-process LRU
  windows. Drift withdrawn: it uses only `_clock_iso` for the
  wire-format `produced_at`; its `_pending` evicts purely by
  insertion order and its `_windows` are size-bounded. No in-
  process clock math is exposed to NTP skew. The aggregator claim
  stands.
- **M1 framing partially wrong.** `storage.v1` is **not**
  instantiated by `build_agents()` today (same R1 footnote as
  above). Adding it to `SINGLE_INSTANCE_AGENTS` is still correct
  as a forward-looking guard (the frozenset is the contract for
  *any* bootstrap, including the upcoming datasource one), but
  the regression test must instantiate `StorageAgent` explicitly
  to exercise the path. Severity stands; framing in §3 / §7 is
  updated below.

### 1.6 Implementation log (post-approval)

All approved action items in §7 have shipped in this same pass.
Test suite delta: `550 / 6 / 2` (swarm only) →
`933 passed / 6 skipped / 2 xfailed` (full `ai/` suite, +4 new
tests for the changes here).

| # | Item | Files touched | Status |
|---|---|---|---|
| 1 | M1 — `storage.v1` in `SINGLE_INSTANCE_AGENTS` | [`bootstrap.py`](../../ai/swarm/bootstrap.py), [`test_bootstrap.py`](../../ai/swarm/tests/test_bootstrap.py) | ✅ shipped + new `test_build_swarm_refuses_duplicate_storage` + existing test relaxed for the "not-yet-wired" case |
| 2 | M2 — Consensus monotonic clock | [`consensus.py`](../../ai/swarm/agents/consensus.py), [`test_consensus.py`](../../ai/swarm/agents/tests/test_consensus.py) | ✅ shipped + new `test_consensus_window_survives_backward_clock_skew` |
| 3 | M3 — `_fuse_score_grids` shape guard + flag | [`consensus.py`](../../ai/swarm/agents/consensus.py), [`payloads.py`](../../ai/swarm/agents/payloads.py), [`proof.flag.json`](../../ai/swarm/sdk/schemas/proof.flag.json), [`test_consensus.py`](../../ai/swarm/agents/tests/test_consensus.py) | ✅ shipped + new `test_mismatched_score_grid_emits_flag_and_excludes_bad_grid` and new `ProofFlagKind.PREDICTOR_GRID_SHAPE_MISMATCH` |
| 4 | M4 (aggregator) — monotonic clock | [`aggregator.py`](../../ai/swarm/agents/proofreader/aggregator.py) | ✅ shipped (drift portion withdrawn — drift exposes no in-process ms clock; see §1.5) |
| 5 | C3 — cap `proof.flag.detail` at 1 KB | [`payloads.py`](../../ai/swarm/agents/payloads.py), [`proof.flag.json`](../../ai/swarm/sdk/schemas/proof.flag.json), [`processor.py`](../../ai/swarm/agents/processor.py), [`categorizer.py`](../../ai/swarm/agents/categorizer.py), [`replicas.py`](../../ai/swarm/agents/proofreader/replicas.py) | ✅ shipped — central `truncate_proof_detail` helper + schema `maxLength: 1024` |
| 6 | N1 — reactor warns on unparseable timestamps | [`reactor.py`](../../ai/swarm/agents/reactor.py) | ✅ shipped — `pass` replaced with `_log.warning(...)` |
| 7 | N3 — render `last_seen` in Prometheus output | [`telemetry.py`](../../ai/swarm/agents/telemetry.py) | ✅ shipped as `negelir_bus_last_seen_epoch{topic=…}` (epoch-second gauge; ISO kept off-wire to bound label cardinality) |
| 8 | C2 — control-plane comments on schemas | [`predict.request.json`](../../ai/swarm/sdk/schemas/predict.request.json), [`predict.vote.json`](../../ai/swarm/sdk/schemas/predict.vote.json), [`predict.final.json`](../../ai/swarm/sdk/schemas/predict.final.json) | ✅ shipped — descriptions now state "control-plane topic — unversioned by design (ROADMAP §3.7)" |

**Items deferred to a follow-up pass** (out of scope for the
"ship before Phase 7" budget, kept on the §7 action queue for
visibility):

- Item 8 N4 — multi-voter / multi-replica `test_phase6_score_grid_e2e.py`
  (the existing 1-voter test still passes; the M3 flag emission is
  already covered by the unit test above).
- Item 9 C1 — addendum on `phase4-to-6-implementation.md` test count.
- Item 10 §5.5 — end-to-end drift→trainer recovery loop test.
- Item 11 §5.6 — every-`ProofFlagKind` emission assertion.

These are all test-coverage hardening; none are blockers for
Phase 7 wiring (`sec.input.v1` / `sec.scrape.v1` / `sec.rate.v1`
introduce orthogonal topics that don't depend on these gaps).

---

## 2. Verdict per phase, with file:line citations

### 2.1 Phase 4 — Core worker agents

| ID | Severity | Issue | Cite |
|---|---|---|---|
| **M1** | MAJOR | `storage.v1` is a sole producer of `match.stored` / `freshness.events.v1` / `match.outcome.v1` but is **not in `SINGLE_INSTANCE_AGENTS`**. (Forward-looking: storage is wired by the not-yet-landed Phase R1 datasource bootstrap; closing the gap in the contract now means the R1 bootstrap inherits the guard.) | [`bootstrap.py` L62-L66](../../ai/swarm/bootstrap.py), [`storage.py` L134-L138](../../ai/swarm/agents/storage.py) |
| N1 | MINOR | Reactor's `fromisoformat` `ValueError` path silently disables the age window with no `_log.warning` | [`reactor.py` L143-L145](../../ai/swarm/agents/reactor.py) |
| N3 | MINOR | `_Counters.last_seen` is updated per observation but never rendered in the Prometheus exposition — dead state | [`telemetry.py` L82-L114](../../ai/swarm/agents/telemetry.py) |

### 2.2 Phase 5 — Predictor swarm + consensus

| ID | Severity | Issue | Cite |
|---|---|---|---|
| **M2** | MAJOR | `consensus.v1` measures fusion-window timeouts using **wall-clock ms** (`datetime.now(...).timestamp() * 1000`). A backward NTP correction or container-cold-start clock jump can keep stale pending entries alive past `cfg.consensus_window_ms`. In-process semantics call for `time.monotonic()`. | [`consensus.py` L191-L193](../../ai/swarm/agents/consensus.py) |
| **M3** | MAJOR | `_fuse_score_grids` averages grids cell-by-cell but **does not assert all contributing grids share the same dimensions**. A predictor emitting a different `max_goals` would corrupt fusion silently. No test guards this. | [`consensus.py` `_fuse_score_grids`](../../ai/swarm/agents/consensus.py), [`_grid.py` L70-L114](../../ai/swarm/agents/predictors/_grid.py) |
| N4 | MINOR | Multi-voter (≥ 4 predictors) e2e regression for the `score_grid` shape contract is still missing — yesterday's `test_phase6_score_grid_e2e.py` runs with `min_voters=1` and a single predictor, which is the *minimum* useful guard for B1 but not the realistic production path | [`test_phase6_score_grid_e2e.py`](../../ai/swarm/agents/tests/test_phase6_score_grid_e2e.py) |

### 2.3 Phase 6 — Proofreader + drift

| ID | Severity | Issue | Cite |
|---|---|---|---|
| **M4** | MAJOR | Same wall-clock LRU foot-gun as M2 — `proofreader_aggregator.v1` stamps `first_seen_ms` from `datetime.now(...).timestamp()` for its quorum window. (Drift was originally listed here too — retracted: drift uses only `_clock_iso` for wire-format `produced_at`; its pending eviction is pure insertion-order LRU and its windows are size-bounded, so no in-process clock math is exposed to skew.) | [`aggregator.py` `_clock_ms` callsites](../../ai/swarm/agents/proofreader/aggregator.py) |

### 2.4 Cross-cutting

| ID | Severity | Issue | Cite |
|---|---|---|---|
| C1 | NIT | The first-pass report's headline says *"the Phase 4–6 test suite is at 387 passing / 0 failing on 2026-04-30"*. Current swarm suite is **550 passed / 6 env-gated skips / 2 documented xfails**. Either land a postscript on the prior report or note the delta in the §0 verdict of any future report. | [`phase4-to-6-implementation.md` §0](./phase4-to-6-implementation.md) |
| C2 | NIT | `predict.vote.json` and `predict.request.json` are correctly unversioned per ROADMAP §3.7 (control plane), but the schema files themselves carry no `comment` marker explaining why they lack `.v1`. Operators reading `ai/swarm/sdk/schemas/` cannot tell at a glance which schemas are control-plane vs data-plane. Add a one-line `"comment": "control-plane: unversioned by design"`. | [`predict.vote.json`](../../ai/swarm/sdk/schemas/predict.vote.json), [`predict.request.json`](../../ai/swarm/sdk/schemas/predict.request.json) |
| C3 | NIT | `proof.flag.detail` is free-text and uncapped at the schema level. A buggy producer could put a multi-KB string on the bus. Add `"maxLength": 1024` to the `detail` property in [`proof.flag.json`](../../ai/swarm/sdk/schemas/proof.flag.json) and a constructor-side truncation in `payloads.py`. | [`payloads.py::ProofFlag`](../../ai/swarm/agents/payloads.py) |

---

## 3. Detailed write-ups for the four MAJORs

### M1 — `storage.v1` missing from `SINGLE_INSTANCE_AGENTS`

**Symptom (latent).** `bootstrap.py` lists the single-instance set
as exactly:

```python
SINGLE_INSTANCE_AGENTS: frozenset[str] = frozenset({
    "consensus.v1",
    "proofreader_aggregator.v1",
    "drift.v1",
})
```

The docstring on line 117 of the same file even acknowledges that
storage is a Phase 4 producer, and the per-record-type comment in
[`agents/__init__.py` L14, L23](../../ai/swarm/agents/__init__.py)
makes clear `storage.v1` is the sole emitter of `match.stored`,
`freshness.events.v1`, and `match.outcome.v1`. Storage is **not**
instantiated by `build_agents()` today — the same docstring at
L116-L119 explicitly defers Phase 4 producer wiring to the
"separate datasource bootstrap that lands with Phase R1" — so the
invariant is currently unenforceable, but the **frozenset is the
cross-bootstrap contract**: whatever wires storage next must obey
it. Today the contract is silent.

**Why it matters before Phase 7.** Phase 7.2 adds `sec.scrape.v1`,
which itself watches `scrape.raw` and may want to share the storage
plumbing for quarantined samples. Phase R1 will land between now
and then. An operator wiring the new datasource bootstrap could
plausibly add a second `StorageAgent` (e.g., to write quarantine
to a separate store) without realizing it breaks the sole-producer
invariant. Close the gap in the contract now, when the change is
one-line.

**Recommended fix.** Add `"storage.v1"` to `SINGLE_INSTANCE_AGENTS`
and extend
[`test_bootstrap.py::test_build_swarm_refuses_duplicate_single_instance_agent`](../../ai/swarm/tests/test_bootstrap.py)
to cover storage by **explicitly constructing two `StorageAgent`
instances** and passing them to `build_swarm` via the `agents=`
kwarg (the existing parametrized test for the other three single-
instance agents already follows this pattern). Update the docstring
on the frozenset to enumerate the four sole-producer / single-
window agents (storage, consensus, aggregator, drift).

### M2 — Consensus uses wall-clock for in-process LRU windows

**Symptom (latent).** `consensus.v1`'s pending fusion table is
keyed by `(match_id, market, request_id)` and stamped with:

```python
self._clock_ms = clock_ms or (
    lambda: datetime.now(timezone.utc).timestamp() * 1000.0
)
```

Eviction (`_PendingFusion.is_stale`) compares `now_ms - first_seen_ms`
against `_window_ms`. If the system clock is corrected backward
(NTP step on a long-running container, or cold-start before
`chronyd` settles), `now_ms < first_seen_ms` and the staleness check
*never fires* until the wall clock catches up. The LRU eviction
under saturation will still evict by insertion order, but the
window-based timeout is broken for the duration of the skew.

**Why it matters before Phase 7.** Phase 7.3 introduces
`sec.rate.v1` — an explicit token-bucket / sliding-window agent.
We should not propagate the wall-clock pattern into a fourth agent
without first auditing the existing three. Fixing M2/M4 once
establishes the convention for sec.rate.

**Recommended fix.** Two-step:

1. Replace the default `_clock_ms` factory with `time.monotonic`-based
   millisecond stamps (`lambda: int(time.monotonic() * 1000)`) in
   `consensus.v1`, `proofreader_aggregator.v1`, and `drift.v1`.
2. Keep `clock_ms` as a constructor parameter so tests can inject
   a deterministic stub (this preserves the existing test stubs).

Cross-process / on-the-wire timestamps in payloads (`emitted_at`,
`stored_at`, `produced_at`) **stay wall-clock** — they are part of
the bus contract and reactors compare them across producers. Only
the in-process LRU stamps move to monotonic.

Add a regression test that injects a "clock jumps backward" stub
and asserts pending entries still evict at `_window_ms`.

### M3 — `_fuse_score_grids` does not assert grid-shape uniformity

**Symptom (latent).** `consensus._fuse_score_grids` averages
contributing votes' `score_grid` payloads element-wise. It does not
assert that all grids share the same dimensions. Today every
predictor uses `_grid.score_grid(..., max_goals=MAX_GOALS=8)` so the
shape is always 9×9. If a future predictor (Phase 7 anomaly model,
Phase 13a per-league profile, or even a config knob bumping
`MAX_GOALS`) emits a different size, the fusion will silently
truncate to the smallest grid (or worse, IndexError mid-loop).

**Why it matters before Phase 7.** Phase 7's `sec.input.v1` will
not emit grids, but Phase 12 adversarial-test catalogue and Phase
13a per-league predictors will. The shape contract should be
enforced at fusion time, not discovered when the proofreader
consistency check rejects every prediction in production.

**Recommended fix.** In `_fuse_score_grids`, after collecting the
list of grids, assert all have the same `len(grid)` and that every
row has the same `len(row)`. On mismatch, **drop the offending
vote** (with a `proof.flag` of kind `predictor_grid_shape_mismatch`)
and continue fusion with the remaining grids. Add a unit test in
`test_consensus.py` that submits two votes with mismatched grids
and asserts the bad one is flagged + excluded.

### M4 — Aggregator shares M2's wall-clock pattern

**Symptom.** Same `datetime.now(...).timestamp() * 1000` pattern at
the constructor of `proofreader_aggregator.v1`. Backward NTP
correction lets stale `_pending` entries survive past
`proofreader_quorum_window_ms`. (Drift was originally listed in this
finding; on a closer read drift uses only `_clock_iso` and pure
insertion-order LRU on its `_pending` map, so it is not exposed to
clock skew. Withdrawn from M4 — see also §1.5.)

**Why it matters before Phase 7.** Same as M2 — fix the pattern
once. A single PR should land M2 + M4 together.

**Recommended fix.** Same as M2, applied to the aggregator's clock
callsite in lockstep with consensus.

---

## 4. Phase 7 readiness checklist

Things Phase 7 will inherit from Phase 4 – 6 and should be clean
**before** the new agents start landing:

- [ ] **Single-instance frozenset reflects every sole producer.**
      Today it covers consensus, aggregator, drift. Storage is
      missing (M1). Close before Phase 7 adds new agents that may
      tempt a second storage replica.
- [ ] **In-process LRU windows use a monotonic clock.** Three
      agents today; if we fix them now, Phase 7's `sec.rate.v1`
      sliding-window agent inherits the convention instead of the
      foot-gun (M2 + M4).
- [ ] **Fusion-shape contract is asserted at the producer/consumer
      boundary.** `_fuse_score_grids` should reject mismatched
      grids before they corrupt the average (M3). Phase 7 won't
      add grids, but Phase 12 adversarial tests will exercise this
      surface, so closing it now means one less Phase 12 finding.
- [ ] **`proof.flag.detail` length-capped at the schema.** Phase 7
      will add new `proof.flag` kinds (`prompt_injection`,
      `dom_anomaly`, `rate_limit_burst`); each will carry a `detail`
      string. Cap once at the schema level (C3) before three
      defense agents start writing to the field independently.
- [ ] **First-pass report's TL;DR is accurate.** C1 — small
      bookkeeping; an addendum or footnote.
- [ ] **Phase 7 ↔ Phase 12 circular dependency is acknowledged.**
      ROADMAP §7.4 DoD requires *"All checks have a corresponding
      entry in [Phase 12](#-phase-12--adversarial--chaos-test-suite)
      test catalogue"*, but Phase 12 isn't done yet. The first
      Phase 7 increment should ship with stub Phase 12 entries
      ("`sec.input.v1` adversarial coverage TBD") so the gate is
      green when Phase 12 lands.

None of these block code changes — they are **proposals for the
human** to approve before any of M1 – M4 / N1 – N5 / C1 – C3 are
implemented. Each fix is small, but the order matters for Phase 7
convention-setting (M2 + M4 first, then M1, then M3, then the
NITs).

---

## 5. Test coverage gap analysis

What is **not** exercised today that Phase 7 will add load to:

1. **Multi-voter `score_grid` regression.** N4. Today's e2e test
   runs `min_voters=1` with a single predictor. The realistic
   4-predictor + 3-replica path is only covered by unit tests of
   each layer in isolation.

2. **Backward-clock skew on consensus / aggregator / drift.**
   Required to prove M2/M4 are real. Should land with the fix.

3. **Storage second-instance refusal.** Required to prove M1
   is fixed and stays fixed.

4. **Mismatched-grid fusion.** Required to prove M3.

5. **Drift trip → maint event → trainer recovery loop, end-to-end.**
   `test_drift.py` exercises the trip; `test_trainer_reactor.py`
   exercises the reactor. There is no test that drives the full
   loop (drift trips → emits `maint.event` → trainer reactor
   debounces → `model.trained` lands → drift resets the bucket).
   Phase 7 doesn't break this, but it's a gap that should be
   closed before Phase 8 (self-maintenance) which builds on it.

6. **Every `ProofFlagKind` exercised in at least one e2e path.**
   Today `test_proof_flag_kinds.py` covers the enum and round-trip
   serialization. There is no test that asserts every kind is
   actually emitted by *some* agent in a full swarm demo run. Phase
   7 will add new kinds; we should land the discipline before then.

---

## 6. Doctrine and convention alignment

Spot-checks against AGENTS.md doctrine for the Phase 4 – 6 surface:

- **Rule 1 (single-source config).** ✅ Spot-checked
  `consensus_window_ms`, `consensus_min_voters`,
  `proofreader_aggregator_max_pending`, `drift_window_size`,
  `drift_brier_ceiling`, `drift_max_pending`, `drift_max_settled`.
  All three triangle points (`config.py`, `defaults.yaml`,
  `xops/env/.env.example`) carry each knob; `test_config_sync` is
  the standing guard.
- **Rule 2 (containerized only).** ✅ All Phase 4 – 6 agents are
  process-friendly; no host-only assumptions.
- **Rule 3 (no fabricated production data).** ✅ The only synthetic
  data lives under `ai/swarm/agents/tests/` and `ai/tests/`.
- **Rule 6 (Turkish UX, English infra).** ✅ All log messages,
  metric names, comments are English; no user-facing strings in
  this layer.
- **Rule 7 (adversarial tests).** ⚠ Mostly ✅; gaps documented in
  §5 (1, 2, 4, 6).
- **Rule 8 (phase gates).** ⚠ ROADMAP §7.4 DoD points to a Phase 12
  catalogue that doesn't exist yet — see Phase 7 readiness checklist
  bullet 6.
- **Rule 10 (tests track code, always).** ✅ The first-pass and
  second-pass audit fixes all carried matching test changes; the
  M1 – M4 fixes proposed here would each carry their own test row.

---

## 7. Proposed action items (pending human approval)

Ordered by *impact × cheapness*, not severity:

| # | Action | Files | Cost |
|---|---|---|---|
| 1 | Land M2 + M4 together: switch in-process LRU clocks to `time.monotonic`-based ms across consensus, aggregator, drift; add backward-skew regression test | `consensus.py`, `aggregator.py`, `drift.py`, `tests/` | small |
| 2 | Land M1: add `"storage.v1"` to `SINGLE_INSTANCE_AGENTS`; extend `test_bootstrap.py` | `bootstrap.py`, `tests/test_bootstrap.py` | trivial |
| 3 | Land M3: add shape-uniformity assertion in `_fuse_score_grids` with `proof.flag` for the rejected vote; add unit test | `consensus.py`, `tests/test_consensus.py`, `payloads.py` (new flag kind) | small |
| 4 | Land C3: cap `proof.flag.detail` at 1 KB in schema + payload constructor | `proof.flag.json`, `payloads.py` | trivial |
| 5 | Land N1: replace silent except with `_log.warning` in reactor's age-window guard | `reactor.py` | trivial |
| 6 | Land N3: either render `last_seen` in Prometheus output or remove the field | `telemetry.py` | trivial |
| 7 | Land C2: add `comment` field to control-plane schemas distinguishing them from data-plane | `predict.vote.json`, `predict.request.json` | trivial |
| 8 | Land N4: extend the e2e regression to multi-voter + multi-replica realistic path | `tests/test_phase6_score_grid_e2e.py` | small |
| 9 | Land C1: addendum / footnote on first-pass report TL;DR with current 550-test count | `docs/reports/phase4-to-6-implementation.md` | trivial |
| 10 | Land §5.5: end-to-end drift → trainer recovery loop test | `tests/` (new) | medium |
| 11 | Land §5.6: every-kind-emitted assertion test | `tests/test_proof_flag_kinds.py` | small |

If approved, each action becomes its own commit with a tracker row
and an `ai` (or `docs`) version bump per AGENTS.md §6.1. Items 1 – 4
are the minimum viable cleanup before Phase 7 starts; items 5 – 11
can land in parallel with Phase 7.1 work.

---

## 8. Self-review checklist (auditor's own honesty pass)

- [x] Re-read both prior reports
      ([first-pass](./phase4-to-6-implementation.md),
      [Phase 6 second-pass](./phase6-second-pass.md)) before
      drafting; explicitly excluded already-shipped findings.
- [x] Re-read ROADMAP §§ 4 – 7 before drafting; cross-referenced
      Phase 7's surface to scope "what does Phase 7 inherit?".
- [x] Manually verified every subagent finding against source;
      rejected three over-claims (§1.4) and downgraded severities
      where the subagent over-reported.
- [x] Every finding cites file:line.
- [x] Every recommended fix has a one-paragraph implementation
      sketch and an estimated cost.
- [x] No code, tracker rows, or version bumps have been written.
      §7 is a proposal queue, not a checklist of completed work.

---

## 9. TL;DR

- **No surviving BLOCKERs.** First-pass B1 is fixed and tested;
  second-pass N1/N2 are fixed.
- **Four MAJORs**, all cheap:
  1. `storage.v1` missing from single-instance set (M1) —
     forward-looking guard for the Phase R1 datasource bootstrap.
  2. Consensus and aggregator use wall-clock for in-process
     LRU windows; backward NTP skew breaks the timeout (M2 + M4).
  3. `_fuse_score_grids` does not assert grid-shape uniformity
     (M3).
- **Three MINORs and three NITs** — log-warning, dead state, schema
  length cap, doc accuracy, control-plane schema marker, multi-
  voter e2e coverage.
- **Phase 7 readiness:** fix M2 + M4 *first* so `sec.rate.v1`
  inherits the right clock convention; fix M1 second so the new
  defense agents land into a clean single-instance frozenset; the
  rest can ship in parallel with Phase 7 work.
- **Test coverage gaps** (multi-voter grid e2e, backward-skew
  regression, drift→trainer recovery loop, every-flag-kind
  emission) are tracked but most can wait until after the M-fix
  PRs land.
- **Self-review (§1.5)** withdrew two MINOR findings (N2, N5) and
  reframed M1 after a careful re-read of the current bootstrap.
  Reflected throughout the report.

The codebase is genuinely clean. This pass is the last
nip-and-tuck before Phase 7 expands the surface.
