# Pre-Phase 6 Roadmap — Mitigation & Readiness Plan

**Date:** 2026-04-29
**Author:** GitHub Copilot (Claude Opus 4.7)
**Scope:** Consolidate the two prior pre-Phase-6 audits
([round 1](pre-phase6-audit.md), [round 2](pre-phase6-audit-round2.md))
into a single executable plan, refresh status against the current
tree, and sequence the remaining work + the Phase 6 build itself.
**Phase target:** [ROADMAP §Phase 6 — Proofreader & Drift Agents](../planning/ROADMAP.md#-phase-6--proofreader--drift-agents).

---

## 0. TL;DR

The two prior audits surfaced **22 distinct findings** across the Go
server, scraper, training pipeline, swarm SDK / agents, migrations,
mock infra, and Phase 6 contract gaps. **17 of those are already
landed in the tree** (verified at the cited file:lines below — the
Go-server hardening G1/G2 turned out to be live too on a final
re-check). The remaining work splits cleanly into two waves:

- **Wave A — Hard blockers for Phase 6 kickoff (3 items).**
  Cache-topology decision (B2), legacy proofreader/drift cleanup (B3),
  and a forbidden-emit contract test for `match.outcome.v1` (T3).
  Without these, Phase 6 either bypasses the proofreader entirely
  (B2) or ships a parallel legacy/swarm split (B3) that we will pay
  for later.

- **Wave B — Phase 6 build itself (3 sub-phases per ROADMAP §6.1–§6.3).**
  Multi-proofreader voting → built-in checks → drift agent. Each
  sub-phase has its own DoD ticks, tracker rows, and version bumps.

- **Wave C — NIT polish (rate-limit overflow guard already shipped;
  remaining: M2 FK indexes, IM1 mock.verify CI gate, A4 calibration
  skew warn, PERF1–PERF3).** Land opportunistically after Wave B.

Severity legend: 🔴 prod-correctness · 🟠 silent drift / observability · 🟡 design debt · 🟢 perf

---

## 1. Status snapshot (re-verified 2026-04-29)

Findings re-checked against the live tree. Items marked ✅ landed are
no longer actionable; items marked 🟡 open feed Wave A or Wave C.

### From [round 1](pre-phase6-audit.md)

| ID | Finding | Status | Evidence |
|---|---|---|---|
| **B1** | `proof.flag` enum missing Phase 5 kinds | ✅ landed | [ai/swarm/sdk/schemas/proof.flag.json](../../ai/swarm/sdk/schemas/proof.flag.json#L19-L21) lists `late_vote_dropped`, `consensus_no_votes`, `consensus_overflow`. |
| **B2** | `cache_prediction_ttl_sec` declared but unconsumed | 🟡 **open** | Still no consumer; declared at [ai/common/config.py#L302](../../ai/common/config.py#L302). Must be wired by Phase 6.1 cache-topology decision. |
| **B3** | Legacy `ai/proofreader/` + `ai/model/drift.py` orphans | 🟡 **open** | [ai/proofreader/validator.py](../../ai/proofreader/validator.py), [ai/proofreader/cross_validator.py](../../ai/proofreader/cross_validator.py), [ai/model/drift.py](../../ai/model/drift.py) still wired into legacy pipeline only. |

### From [round 2](pre-phase6-audit-round2.md)

| ID | Finding | Status | Evidence |
|---|---|---|---|
| **T1** | No `match.outcome.v1` topic | ✅ landed | [ai/swarm/agents/topics.py#L29](../../ai/swarm/agents/topics.py#L29) `MATCH_OUTCOME = Topic("match.outcome.v1")`; producer at [ai/swarm/agents/storage.py#L260-L269](../../ai/swarm/agents/storage.py#L260-L269). |
| **P1** | `train_test_split` random vs rolling features | ✅ landed | [ai/model/trainer.py#L60-L130](../../ai/model/trainer.py#L60-L130) — chronological sort + sequential tail slice; comment cites the audit. |
| **A1** | `InMemoryLedger._seen` unbounded | ✅ landed | [ai/swarm/agents/reactor.py#L67-L74](../../ai/swarm/agents/reactor.py#L67-L74) — `OrderedDict` LRU bounded by `cfg.reactor_ledger_max_size`. |
| **M1** | Missing FK index on `match_normalized(raw_ref)` | ✅ landed | [migrations/006_indexes.sql](../../migrations/006_indexes.sql) present. |
| **SK1** | Validator default `additionalProperties=true` | ✅ landed | [ai/swarm/sdk/schemas/__init__.py#L100](../../ai/swarm/sdk/schemas/__init__.py#L100) — default flipped to `False`. |
| **S1** | `engine.py` swallows network errors | ✅ landed (refined) | [ai/scraper/engine.py#L66-L80](../../ai/scraper/engine.py#L66-L80) — `ConnectionError` / `Timeout` now log at `warning`, `HTTPError` at `error` with status. Acceptable for the dev-fallback path. |
| **S2** | `MackolikClient` session never closed | ✅ landed | [ai/scraper/mackolik.py#L141-L165](../../ai/scraper/mackolik.py#L141-L165) — `close()` + `__enter__` / `__exit__` + finalizer. |
| **A3** | Overflow flag emission not rate-limited | ✅ landed | [ai/swarm/agents/consensus.py#L217-L280](../../ai/swarm/agents/consensus.py#L217-L280) — `_overflow_last_flagged_ms` gated by `cfg.consensus_overflow_flag_min_interval_sec`. |
| **A5** | `_shallow_diff` truncated payloads on bus | ✅ landed | [ai/swarm/agents/storage.py#L103-L127](../../ai/swarm/agents/storage.py#L103-L127) — full diff stays on bus; `summarize_diff_for_telemetry` is a separate projection. |
| **C2** | `logger.propagate = False` global | ✅ landed | `grep "propagate" ai/common/logger.py` returns no matches. |
| **T2** | No `predict.proofreader_verdict.v1` schema | ✅ landed | [ai/swarm/sdk/schemas/predict.proofreader_verdict.v1.json](../../ai/swarm/sdk/schemas/predict.proofreader_verdict.v1.json) exists; producer + topic land in Wave B. |
| **G1** | Go handler loops do not check `ctx.Done()` | ✅ landed | All three `rows.Next()` loops at [server/cmd/api/main.go#L214](../../server/cmd/api/main.go#L214), [#L329](../../server/cmd/api/main.go#L329), [#L438](../../server/cmd/api/main.go#L438) poll `ctx.Done()`. |
| **G2** | No handler-level timeout | ✅ landed | [server/cmd/api/main.go#L107](../../server/cmd/api/main.go#L107) wraps the mux with `http.TimeoutHandler(r, cfg.HTTPHandlerTimeout(), …)`; knob `HTTP_HANDLER_TIMEOUT_SEC` (default `25s`) at [server/internal/config/config.go#L47](../../server/internal/config/config.go#L47). |
| **G3** | `config.MustLoad()` panics rather than returning error | 🟢 dead code | Both real callers ([server/cmd/api/main.go#L30](../../server/cmd/api/main.go#L30), [server/cmd/swarmctl/main.go#L41](../../server/cmd/swarmctl/main.go#L41)) already use `config.Load()`. `MustLoad()` is unused but still exported at [server/internal/config/config.go#L106](../../server/internal/config/config.go#L106). Drop opportunistically; not blocking. |
| **A4** | No assertion that votes share calibration version | 🟡 open | Soft-warn; Wave C. |
| **C1** | `cfg` ↔ `xops/env/.env.example` drift | 🟡 open | Periodic audit; Wave C. |
| **IM1** | `make mock.verify` not a CI gate | 🟡 open | Wave C. |
| **M2** | Other FK columns may lack indexes | 🟡 open | Audit migration `005_predictor.sql`; Wave C. |
| **T3** | No regression test that consensus is **forbidden** to publish `match.outcome.v1` | 🟡 **open** | Wave A — boundary discipline test, cheap to add. |
| **PERF1** | `_fuse_score_grids()` 3-pass | 🟢 deferred | Negligible. |
| **PERF2** | `freshness` event_id derived under storage lock | 🟢 deferred | NEEDS-VERIFICATION. |
| **PERF3** | Schema validator re-loads JSON each call | 🟢 deferred | NEEDS-VERIFICATION. |

---

## 2. Wave A — Hard blockers for Phase 6 kickoff

Each item below ships as its own commit + tracker row +
`make version.bump`, in order. Total estimated effort: small (≤ 1
working session per item).

### A.1 🔴 Decide cache topology and wire `cache_prediction_ttl_sec` (B2)

**Why first:** Phase 6.1 publishes `predict.final` to the API cache
**only** after proofreader majority. The current `cache.v1` agent
([ai/swarm/agents/cache.py](../../ai/swarm/agents/cache.py)) only
handles `MATCH_STORED`. Subscribing it directly to `predict.final`
would bypass the proofreader and violate ROADMAP §736 ("`predict.final`
is a CANDIDATE — never user-visible until the Phase 6 proofreader
quorum approves it").

**Decision required (pick one before any §6.1 code lands):**

- **Option A** — new topic `predict.approved.v1`, emitted by the
  proofreader fan-in only when quorum passes; `cache.v1` subscribes to
  it. **Recommended** (cleanest contract, smallest blast radius,
  matches `predict.proofreader_verdict.v1` already shipped at T2).
- Option B — proofreader as a `predict.final` middleware that
  re-emits on `predict.final.approved`.
- Option C — `cache.v1` joins `predict.final` × `proofreader.verdict`
  on `prediction_id` with an in-memory window.

**Deliverables for option A:**

- [ ] Add `PREDICT_APPROVED = Topic("predict.approved.v1")` to [topics.py](../../ai/swarm/agents/topics.py).
- [ ] Add `predict.approved.v1.json` schema (re-uses `predict.final.v1` shape + adds `approved_by[]` proofreader IDs and `approved_at`).
- [ ] Land schema row in §3.5 wire-authority table.
- [ ] Wire `cache.v1` subscription + use `cfg.cache_prediction_ttl_sec`.
- [ ] Contract test: `cache.v1` does **not** subscribe to `predict.final`.

**DoD tick:** ROADMAP §4.5 line 636 `[ ]` → `[x]` once cache is live.

### A.2 🟡 Retire legacy `ai/proofreader/` + `ai/model/drift.py` (B3)

**Why now:** Phase 6 places proofreaders + drift under `swarm/` per
[`design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md). Leaving
the legacy modules in place creates a "two proofreaders, two truths"
problem the moment Phase 6 ships.

**Deliverables (one commit):**

- [ ] Move re-usable rule-bodies (range / consistency / plausibility) from [ai/proofreader/validator.py](../../ai/proofreader/validator.py) into `ai/swarm/agents/proofreader/checks.py` as pure functions (no `Agent` wrapping yet — that's §6.1).
- [ ] Delete `ai/proofreader/` and `ai/model/drift.py`.
- [ ] Update legacy callers ([ai/pipeline/runner.py#L23](../../ai/pipeline/runner.py#L23), [ai/pipeline/training_pipeline.py#L149](../../ai/pipeline/training_pipeline.py#L149), [ai/data_showcase.py#L23](../../ai/data_showcase.py#L23)) to import from the new module or drop the call where the swarm path supersedes it.
- [ ] Add a regression test mirroring `test_p2p_module_removed`: `test_legacy_proofreader_removed` asserts the directory is gone.
- [ ] Re-run `make test.ai` to confirm no stale fixture references the old path.

### A.3 🟡 Add the boundary-discipline test for `match.outcome.v1` (T3)

**Why now:** Cheap (≤ 30 LOC); locks in the rule that **outcomes are
storage-side data**. Without it, a future Phase 6 proofreader could
"helpfully" emit derived outcomes from a passed prediction and corrupt
the drift agent's reference.

**Deliverable:**

- [ ] In `ai/swarm/agents/tests/test_consensus.py` (or new `test_boundary_discipline.py`), assert: `MATCH_OUTCOME not in consensus_v1.publishes` and the same for every Phase 5 predictor.

### A.4 � Go server hardening — already landed (G1 + G2); G3 dead-code only

**Re-verified 2026-04-29:** G1 and G2 are both live. The original
audit was based on an older snapshot; current `main.go` polls
`ctx.Done()` in every `rows.Next()` loop and the mux is wrapped with
`http.TimeoutHandler`. **No work owed in Wave A.**

G3 (the unused `MustLoad()` function) is pure dead code at
[server/internal/config/config.go#L106](../../server/internal/config/config.go#L106).
Delete it as a one-line cleanup whenever the next `server` patch lands;
not a blocker.

---

## 3. Wave B — Phase 6 build itself

The actual work specified by [ROADMAP §Phase 6](../planning/ROADMAP.md#-phase-6--proofreader--drift-agents).
Land in three commits, one per sub-phase. Each sub-phase ships its
tracker row + `make version.bump COMPONENT=swarm LEVEL=minor`.

### B.1 §6.1 Multi-proofreader voting

**Topology (assuming Wave A.1 chose Option A):**

```
predict.final  ──►  proofreader.v1 (×N)  ──► proofreader.verdict.v1
                                                 │
                                                 ▼
                                         (fan-in / quorum)
                                                 │
                                                 ▼
                                         predict.approved.v1  ──► cache.v1
                                                 │
                                                 ▼
                                              proof.flag (on fail)
```

**Contract decisions (lock in §6.1 design doc before coding):**

- [ ] **Quorum formula:** `≥ ⌊N/2⌋ + 1` (simple majority). N=3→2, N=5→3, N=7→4. Per ROADMAP §6.1 audit-D4 callout.
- [ ] **Quorum window:** new config `cfg.proofreader_quorum_window_ms` (default `200ms`); emit `proof.flag{kind=proofreader_no_quorum}` if quorum not reached in time.
- [ ] **Idempotency:** keyed on `(prediction_id, proofreader_id)`; the existing `Ledger` Protocol (Phase 4.7) is reused — bounded LRU lands automatically via Wave A's A1.
- [ ] **Fan-in agent:** new `proofreader_aggregator.v1` (singleton, `replicas: 1`) — mirrors `consensus.v1` topology. Predicate: emit `predict.approved.v1` once per `prediction_id` when verdict count hits quorum; emit `proof.flag` (with kinds `proofreader_quorum_failed`, `proofreader_no_quorum`) on the negative paths.

**Deliverables:**

- [ ] `ai/swarm/agents/proofreader/` package: `_base.py` (shared `Proofreader` Agent), `aggregator.py` (fan-in singleton).
- [ ] New topics: `PREDICT_APPROVED`, `PROOFREADER_VERDICT` in [topics.py](../../ai/swarm/agents/topics.py).
- [ ] Schemas: `predict.approved.v1.json` (Wave A.1), `predict.proofreader_verdict.v1.json` already exists (T2) — extend with `proofreader_id`, `verdict ∈ {pass, fail}`, `failed_checks[]`, `prediction_id`.
- [ ] New proof.flag kinds added to enum: `proofreader_quorum_failed`, `proofreader_no_quorum`, `proofreader_late_verdict_dropped`.
- [ ] Tests: quorum-pass (N=3, 2 pass), quorum-fail (N=3, 2 fail), late-verdict-dropped, no-quorum-window (1 pass + timeout), single-publication guarantee (mirror consensus's idempotency test).

### B.2 §6.2 Built-in proofreader checks

Each check is a pure function in `ai/swarm/agents/proofreader/checks.py`,
unit-tested independently, then composed by the `Proofreader` Agent
into a verdict.

- [ ] **Sanity:** `sum(probs) == 1 ± cfg.proofreader_sanity_eps` (default `1e-6`); no NaN; no negative.
- [ ] **Plausibility:** away-win probability > `cfg.proofreader_plausibility_max_away_win` (default `0.85`) for matches flagged in `derbies` (config-driven set per league).
- [ ] **Consistency:** marginal 1X2 distribution must match the score-grid sum within `cfg.proofreader_grid_consistency_tol` (default `1e-3`); skip when the predictor produced no grid.
- [ ] **Cross-source:** when implied probability from at least one external odds source is available on the record, |p_pred − p_implied| ≤ `cfg.proofreader_odds_max_drift` (default `0.20`). No-op when odds absent (Phase 9 wire-up).
- [ ] **Historical:** Brier vs the last-3-meetings empirical prior must be ≤ `cfg.proofreader_history_brier_max` (default `0.40`); skip when `<3` priors.

**Each check** ships with: a unit test for pass + at least one
adversarial fail (Rule 7); a config knob in [config.py](../../ai/common/config.py) + [defaults.yaml](../../ai/common/defaults.yaml) + [.env.example](../../xops/env/.env.example) (triangle test stays green); a `proof.flag.kind` constant.

### B.3 §6.3 Drift agent (`drift.v1`)

**Inputs:** `predict.final` + `match.outcome.v1` (already produced by storage). Joins on `prediction_id` → `match_id`.

**Deliverables:**

- [ ] `ai/swarm/agents/drift.py` — singleton (`replicas: 1`) maintaining rolling Brier / log-loss windows per `(league, market, predictor_id)` of size `cfg.drift_window_size` (default `200`).
- [ ] Trip rule (a): any window crosses `cfg.drift_accuracy_floor` (the same knob §5.4 already uses — single source).
- [ ] Trip rule (b): KS-test on input feature distribution rejects stationarity at `cfg.drift_pvalue` (default `0.01`). Implementation note: feature snapshots are sampled from the `freshness.events.v1` payload (full diff is now preserved on the bus per A5), not from a separate DB query — keeps the swarm-isolation invariant intact.
- [ ] Trip emits `maint.event{kind:retrain_request, target:<predictor>}` on the existing `models.events.v1` topic (extend the schema's `kind` enum).
- [ ] State persistence: in-memory dict keyed on `(league, market, predictor_id)` for v1; Phase 9 backs it with Postgres (deferred, mirrors §5.4 `predictor_*` tables pattern).
- [ ] Tests: synthetic 100-prediction stream that crosses the floor → trip; synthetic stable stream → no trip; KS-trip with shifted feature distribution; idempotency (one `retrain_request` per `(predictor, window)` until reset).

### B.4 Phase 6 DoD (mirror ROADMAP §Phase 6 checkbox set)

- [ ] All §6.1 checkboxes flipped after Wave B.1 lands.
- [ ] All §6.2 checkboxes flipped after Wave B.2 lands.
- [ ] All §6.3 checkboxes flipped after Wave B.3 lands.
- [ ] `make swarm.demo` extended (or new `make swarm.proofread`) showing happy-path: predictors → consensus → 3 proofreaders → cache.
- [ ] `swarmctl ps` and `swarmctl topics` show the new agents + topics (Phase 3.4 contract preserved).
- [ ] Triangle test green for every new config knob.
- [ ] `swarm` chart bumped to `0.4.0` after §6.3 lands; intermediate sub-phase patches bump patch-level.
- [ ] Tracker rows: `start` at the head of each sub-phase, `complete` at the end.

---

## 4. Wave C — Polish (parallel-safe with Wave B, land opportunistically)

| ID | Item | Component | Effort | Bump |
|---|---|---|---|---|
| **A4** | Soft-warn on calibration-version skew across votes in a window | `swarm` | tiny | patch |
| **C1** | Sync `cfg` fields ↔ `xops/env/.env.example` (run audit, close gaps) | `xops` | tiny | patch |
| **IM1** | Wire `make mock.verify` into CI before tests | `xops` | tiny | patch |
| **M2** | Audit `005_predictor.sql` FKs → add missing covering indexes | `ai` | small | patch |
| **PERF1** | Single-pass `_fuse_score_grids()` | `swarm` | tiny | patch |
| **PERF2** | Move `derive_event_id` outside storage lock | `swarm` | tiny | patch |
| **PERF3** | `functools.lru_cache` schema loader | `swarm` | tiny | patch |

---

## 5. Sequencing & tracker plan

```
   Wave A (blockers)          Wave B (Phase 6)              Wave C
   ─────────────────         ───────────────────          ─────────
   A.1 cache topology   ──►  B.1 §6.1 voting       ──►   in parallel
   A.2 legacy retire        B.2 §6.2 checks            with B.2 / B.3
   A.3 boundary test         B.3 §6.3 drift
```

**Tracker rows to write (one per commit):**

```bash
# Wave A
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.1 cache topology decision (Option A) + predict.approved.v1"
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.2 retired legacy ai/proofreader + ai/model/drift.py"
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.3 boundary-discipline test for match.outcome.v1"
# (Wave A.4 dropped — G1/G2 already live; G3 is dead-code cleanup, fold into next server patch.)

# Wave B (Phase 6 itself)
make track.add PHASE=6 STATUS=in-progress NOTE="Phase 6.1 multi-proofreader voting kickoff"
make track.add PHASE=6 STATUS=completed   --subphase 1 NOTE="§6.1 voting + aggregator + tests green"
make track.add PHASE=6 STATUS=in-progress --subphase 2 NOTE="§6.2 built-in checks kickoff"
make track.add PHASE=6 STATUS=completed   --subphase 2 NOTE="§6.2 5 checks + adversarial tests green"
make track.add PHASE=6 STATUS=in-progress --subphase 3 NOTE="§6.3 drift.v1 kickoff"
make track.add PHASE=6 STATUS=completed   --subphase 3 NOTE="§6.3 drift agent + KS-test + retrain emit"
make track.add PHASE=6 STATUS=completed                NOTE="Phase 6 DoD green; swarm bumped to 0.4.0"
```

**Version bumps (one per commit per AGENTS.md §6.1):**

- Wave A.1 → `swarm minor` (new topic + schema)
- Wave A.2 → `ai minor` (module deleted from `ai/`)
- Wave A.3 → `swarm patch` (test only)
- Wave B.1 → `swarm minor`
- Wave B.2 → `swarm minor`
- Wave B.3 → `swarm minor` → finally `swarm 0.3.x → 0.4.0` at the Phase 6 close

---

## 6. Locked-in decisions (human approval recorded 2026-04-29)

All five open decisions were resolved by the human at kickoff with
"continue with Option A; apply the rest with the recommended ones".
Recording for traceability:

1. **Cache topology (Wave A.1)** — ✅ **Option A:** new
   `predict.approved.v1` topic, emitted by the proofreader aggregator
   only when quorum passes. `cache.v1` subscribes to it.
2. **Proofreader replica count `N`** — ✅ `cfg.proofreader_replicas = 3`,
   `quorum = ⌊N/2⌋ + 1 = 2` for v1.
3. **Cross-source check (B.2)** — ✅ ship now as a **no-op when odds
   absent**; the check activates automatically once Phase 9 wires odds
   into the predictor feature dict.
4. **Drift state persistence (B.3)** — ✅ in-memory for v1; Postgres
   backing deferred to Phase 9, mirroring the `CalibrationStore`
   Protocol seam from §5.4.
5. **Legacy `ai/proofreader/` deletion (Wave A.2)** — 🟡 **revised
   2026-04-29 during execution.** The original audit counted 3
   callers; on extraction we discovered 7 additional callers in
   [ai/tests/test_unit.py](../../ai/tests/test_unit.py) (TestProofreader,
   TestCrossValidator, TestDriftDetector classes) plus the demo function
   `show_proofreading()` in [ai/data_showcase.py#L240](../../ai/data_showcase.py#L240).
   **New plan:** the rule bodies (range / consistency / plausibility)
   have been extracted into
   [ai/swarm/agents/proofreader/checks.py](../../ai/swarm/agents/proofreader/checks.py)
   as pure functions; the legacy `DataProofreader` shell now
   delegates to them so behaviour parity is enforced by both the
   legacy `TestProofreader` suite and the new
   [test_proofreader_checks.py](../../ai/swarm/agents/tests/test_proofreader_checks.py)
   adversarial suite. Full deletion of `ai/proofreader/` and
   `ai/model/drift.py` is **deferred to a post-Phase-6 cleanup commit**
   once the swarm-side replacement (B.1+B.2+B.3) is operational.
   This is safer than a synchronised rip-and-replace.

---

## 7. Self-review against AGENTS.md

Per AGENTS.md §3 + §6.1 this document is a planning artefact, not a
code change. Therefore: no tracker row is owed for the document
itself, and no `make version.bump` is required. **The first wave of
tracker rows + bumps lands when Wave A.1 commits.**

The doc respects:

- **Rule 1 (single-source config):** every new knob proposed (cache
  topology, proofreader thresholds, drift window size, KS p-value, Go
  handler timeout) is routed through `config.py` + `defaults.yaml` +
  `.env.example`.
- **Rule 6 (TR UX, EN infra):** all proposed code, comments, topics,
  metric names are English; no user-facing strings introduced.
- **Rule 7 (adversarial tests first-class):** every proofreader check
  ships with at least one negative test; drift agent ships with
  KS-trip + accuracy-floor-trip tests.
- **Rule 9 (no `git`):** the `make track.add` / `make version.bump`
  lines in §5 are intended for the agent itself to run at commit
  time; no `git` invocations.
- **Rule 10 (tests track code):** every Wave A and Wave B item names
  the test it ships with.
- **§3.4 (tick the ROADMAP):** Wave A.1 ticks ROADMAP §4.5 line 636;
  Wave B.1–B.3 tick the §6.1 / §6.2 / §6.3 checkbox sets in full.

*Document ends.*
