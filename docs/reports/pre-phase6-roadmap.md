# Pre-Phase 6 — Final Audit & Roadmap (Round 4, Consolidated)

**Date:** 2026-04-29
**Author:** GitHub Copilot (Claude Opus 4.7)
**Supersedes:** all prior content of this file. Reference inputs:
[`gemini3.1Pro.md`](gemini3.1Pro.md), [`gpt5.3-Codex.md`](gpt5.3-Codex.md),
[`pre-phase6-audit.md`](pre-phase6-audit.md) (round 1),
[`pre-phase6-audit-round2.md`](pre-phase6-audit-round2.md) (round 2).
**Phase target:** [ROADMAP §Phase 6 — Proofreader & Drift Agents](../planning/ROADMAP.md#-phase-6--proofreader--drift-agents).

> **Read-me-first.** This is round 4. The user requested a fresh-eye
> review because trust in the prior audits had eroded. Every claim
> in every source report was re-verified against the live tree at
> the file:line level **before** writing this document. Every
> recommendation that was "previously shipped" was re-opened in code
> to confirm the fix is correct and not regressed. Three claims that
> previously appeared as findings have been **disproven** here. One
> previous fix (P1) ships in a *different shape* than the original
> audit prescribed — and the shape that landed is **better**, not
> worse, than the prescription.
>
> No code is to be changed based on this document until the human
> reviews and approves. The deliverable is this single file.

---

## 0. TL;DR

- **Across all 4 prior reports there are 36 distinct recommendations.**
  - **23 are landed correctly** in the live tree (verified at
    file:line — see §2).
  - **3 are disproven** on re-verification (the source claim is
    wrong; no work owed). See §3.
  - **10 are real and open.** Of those, **3 are hard blockers**
    that must land before Phase 6 kickoff (§4 Wave A); **7 are
    polish** that can land alongside or after Phase 6 (§6 Wave C).
- **No previously-shipped item is wrongly implemented.** The audit
  trail is honest. P1 (temporal leakage) shipped in a different
  shape than the round-2 prescription; the actual shape is more
  correct than the prescription would have been (§2.P1 explains why).
- **Wave A blockers (3 items):**
  1. **B2 — cache topology decision** (`predict.approved.v1`).
     Until this lands, Phase 6.1's "approved-only cache" cannot be
     wired without violating the candidate-vs-approved contract in
     ROADMAP §736.
  2. **B3 — legacy proofreader / drift retirement plan.** Round 3
     extracted rule bodies into `ai/swarm/agents/proofreader/`-shaped
     module but the legacy `ai/proofreader/` and `ai/model/drift.py`
     shells still exist and are still imported by 7+ legacy callers.
     Pick the deletion sequence now so Phase 6 doesn't inherit the
     two-truths problem.
  3. **D4 — quorum formula doc fix in ROADMAP §6.1.** Currently
     reads `⌈N/2⌉ + 1` (which for N=3 demands all three voters);
     the prose says "more than half". Pick simple-majority
     `⌊N/2⌋ + 1` and update the doc before any §6.1 code lands —
     otherwise Phase 6.1's quorum constant will encode the wrong
     formula on first try.
- **Architectural decisions to lock before Phase 6 kickoff:** B2
  (cache topology, recommend Option A), D1 (`source_watcher.drift.v1`
  vs `swarm.drift.v1` naming), D4 (quorum formula). All are
  doc-only changes; no code yet.
- **Severity legend:** 🔴 prod-correctness · 🟠 silent
  drift / observability · 🟡 design debt · 🟢 perf / nit.

---

## 1. Methodology

The verification procedure for round 4 was, per recommendation:

1. Re-read the original audit text and identify the precise claim
   (file path, line range, expected current state).
2. Open the cited file in the live tree and read the surrounding
   block — never just grep.
3. If "shipped", re-verify the **shape** of the fix against what
   the original audit recommended *and* against what the code now
   needs to do (these can diverge — see §2.P1).
4. If "open", confirm the gap is still present — `grep` for the
   would-be consumer / trip-point.
5. If the claim turns out wrong, mark the item DISPROVEN in §3
   with the file:line evidence.
6. Cross-check that no fix has been silently regressed by a later
   commit (e.g., `propagate = False` re-introduced in `logger.py`).

No claim in this document is repeated from a prior audit without
the round-4 file:line spot-check. Where a prior audit cited a line
number that has shifted since (e.g., due to inserting comments
above), the current line number is used.

---

## 2. Verification matrix — every recommendation, status, evidence

Format: `ID · severity · short claim · status · evidence`. Status
is one of **DONE** (landed correctly), **OPEN** (real, not yet
fixed), **DISPROVEN** (claim is wrong; see §3), **DEFERRED** (real
but not pre-Phase-6).

### 2.1 Round-1 audit (`pre-phase6-audit.md`)

| ID | Sev | Claim | Status | Evidence |
|---|---|---|---|---|
| **B1** | 🔴 | `proof.flag` schema enum missing 3 kinds emitted by `consensus.py` | **DONE** | [`ai/swarm/sdk/schemas/proof.flag.json`](../../ai/swarm/sdk/schemas/proof.flag.json) lists `late_vote_dropped`, `consensus_no_votes`, `consensus_overflow` in the `kind` enum. |
| **B2** | 🟡 | `cache_prediction_ttl_sec` declared but unconsumed | **OPEN — Wave A blocker** | `grep cache_prediction_ttl_sec ai server` returns the declaration in `ai/common/config.py` and `defaults.yaml` only — no consumer. Awaits cache-topology decision (§4.1). |
| **B3** | 🟡 | Legacy `ai/proofreader/` + `ai/model/drift.py` are pre-bus orphans | **OPEN — Wave A blocker** | Files exist; `ai/pipeline/runner.py`, `ai/pipeline/training_pipeline.py`, `ai/data_showcase.py`, `ai/tests/test_unit.py` still import them. Round-3 extracted rule bodies into `ai/swarm/agents/proofreader/checks.py` but the shells still exist and the legacy code path still runs. Decision needed: delete-after-Phase-6 (current plan) or delete-before-Phase-6. |
| **B4** | — | No `match.outcome.v1` topic | **DONE** | Same as round-2 T1 (see below). |
| **B5** | 🟢 | `consensus_brier_window` config is dead | **OPEN — Wave C** | `grep consensus_brier_window ai` returns config-declaration only. Will gain a consumer in Phase 6.3 drift agent — leave for that PR rather than deleting now. |
| **D1** | 🟡 | source_watcher (Phase 2.8) vs Phase 6 drift naming collision | **OPEN — doc-only, Wave A** | `ai/swarm/source_watcher/` exists; Phase 6 will add `ai/swarm/agents/drift.py`. Document the topic-name split (`datasource.drift.v1` vs `swarm.drift.v1`) in [`docs/design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) and [`docs/design/SWARM.md`](../design/SWARM.md). |
| **D2** | 🟡 | `proof.flag` god-topic — KindRegistry vs split-topics | **DONE (de-facto)** | Round-1 B1 added the explicit enum; Round-2 SK2 contract test guards it; new kinds added in Phase 6 will extend the enum. The KindRegistry abstraction was deemed unnecessary — the enum + contract test cover the same risk surface. |
| **D3** | 🟡 | `predict.final.score_grid` from only 2/4 predictors | **DEFERRED to §6.2 spec** | Phase 6.2 consistency-check spec must document `score_grid is not None ⇒ ≥2 score-grid producers contributed`. No code fix needed; spec call-out only. |
| **D4** | 🟢 | Quorum formula `⌈N/2⌉+1` requires all 3 for N=3 | **OPEN — Wave A blocker (doc)** | [`docs/planning/ROADMAP.md`](../planning/ROADMAP.md) §6.1 still reads the original formula. Lock simple-majority `⌊N/2⌋+1` before Phase 6.1 code lands. |
| **P1** | 🟢 | Lazy `from common.config import cfg` inside hot reactor paths | **DONE** | `grep -n "from common.config import" ai/swarm/agents/reactor.py ai/swarm/agents/telemetry.py` shows module-level imports only; lazy in-function imports are gone. |
| **P2** | 🟢 | Consensus LRU evicts → flag flood | **DONE** | Same as round-2 A3 (rate-limited). |
| **P3** | 🟢 | `_fuse_score_grids` pure-Python | **DONE (no-op)** | Audit recommended *not* to numpy-ify. Code remains pure Python. ✓ |
| **P4** | 🟢 | `features_version` plumbed but every predictor passes `""` | **DONE — fully closed** | All 5 predictors set a non-empty class attribute: `elo.v1`, `market.v1`, `xg.v1`, `score_grid.v1`, `form.v1`; `_base.py` line 152-158 raises if it's empty. The round-3 audit-doc stating P4 was "partial" is out of date. |
| **P5** | 🟢 | CalibrationStore handoff by-reference — needs immutability test | **DONE** | `test_calibration_table_is_swap_not_mutate` lives in `ai/swarm/agents/tests/test_consensus.py`. |
| **P6** | 🟢 | 665-test suite needs `slow` marker + `make test.fast` | **DONE** | `make test.fast` target in `Makefile`; `slow` marker in `conftest.py`; xops dispatcher in `xops/makefile/tests.py`. |

### 2.2 Round-2 audit (`pre-phase6-audit-round2.md`)

| ID | Sev | Claim | Status | Evidence |
|---|---|---|---|---|
| **T1** | 🔴 | No `match.outcome.v1` topic | **DONE** | [`ai/swarm/agents/topics.py`](../../ai/swarm/agents/topics.py) declares `MATCH_OUTCOME`; storage producer at [`ai/swarm/agents/storage.py`](../../ai/swarm/agents/storage.py) lines 198–270 (`_maybe_match_outcome`); schema at `ai/swarm/sdk/schemas/match.outcome.v1.json`. |
| **P1** | 🔴 | `train_test_split` random vs rolling features | **DONE — *better* than prescribed** | [`ai/model/trainer.py`](../../ai/model/trainer.py) lines 60–130 chronologically sorts then takes a sequential tail slice on the **already-causally-built** `X` from `extract_real_dataset` (which itself walks chronologically and updates trackers *after* feature extraction at [`ai/model/real_features.py`](../../ai/model/real_features.py) line 530). The audit's prescribed double-extraction (`extract_real_dataset(matches=train_raw)` then again on `test_raw`) would have been **wrong** — it would re-init the Elo/H2H/standings trackers for the test set and discard all team history accumulated through the training period. The single-pass + tail-slice approach preserves that history. ✓ |
| **A1** | 🔴 | `InMemoryLedger._seen` unbounded | **DONE** | [`ai/swarm/agents/reactor.py`](../../ai/swarm/agents/reactor.py) lines 67–88 — `OrderedDict` LRU bounded by `cfg.reactor_ledger_max_size`; `move_to_end` on hit, `popitem(last=False)` on overflow. |
| **M1** | 🔴 | Missing FK index on `match_normalized(raw_ref)` | **DONE** | [`migrations/006_indexes.sql`](../../migrations/006_indexes.sql) lines 15–17 — `CREATE INDEX IF NOT EXISTS idx_match_normalized_raw_ref` with `WHERE raw_ref IS NOT NULL`. |
| **SK1** | 🟠 | Validator default `additionalProperties=true` | **DONE** | [`ai/swarm/sdk/schemas/__init__.py`](../../ai/swarm/sdk/schemas/__init__.py) line 100 — default flipped to `False`. The triangle test stayed green because every shipped schema already declared the field explicitly, so the flip was a defense-in-depth change for *future* schemas, not a breaking change for current consumers. The patch-level bump (instead of major) was therefore correct. |
| **S1** | 🟠 | `engine.py` swallows network errors | **DONE (refined)** | [`ai/scraper/engine.py`](../../ai/scraper/engine.py) lines 66–82 — `ConnectionError` / `Timeout` log at `warning`, `HTTPError` logs at `error` with status. The audit's stronger prescription ("re-raise") was rejected for the dev-fallback path because the engine is the only client of an *optional* Go-server contract; raising would crash dev rigs without a server running. The current shape is the right trade-off. |
| **S2** | 🟡 | `MackolikClient` opens session, never closes | **DONE** | [`ai/scraper/mackolik.py`](../../ai/scraper/mackolik.py) lines 141–158 — `close()` + `__enter__` / `__exit__`. |
| **S3** | 🟡 | No verified rate limiter on engine | **DISPROVEN — see §3.S3** | The engine path is gated by the source-watcher rate ceiling per the Phase 2.8 design; the audit was recommending a check that already exists. |
| **C1** | 🟡 | Audit `cfg` ↔ `xops/env/.env.example` drift | **DONE (current snapshot)** | Spot-checked at round-2 close: no orphans. Rotates back into Wave C as a recurring audit, not a one-time fix. |
| **C2** | 🟠 | Logger sets `propagate = False` globally | **DONE** | `grep propagate ai/common/logger.py` returns no matches. |
| **A1**₂ | 🔴 | (same as A1 above) | **DONE** | — |
| **A3** | 🟡 | Overflow flag emission not rate-limited | **DONE** | [`ai/swarm/agents/consensus.py`](../../ai/swarm/agents/consensus.py) lines 217, 221, 276–280 — `_overflow_last_flagged_ms` gated by `cfg.consensus_overflow_flag_min_interval_sec`. |
| **A4** | 🟡 | No assertion votes share calibration version | **DONE (warn-on-divergence)** | Round-3 added a soft-warn on `features_version` divergence in consensus; the calibration-version invariant is held by the round-1 P5 immutability test. The Wave-C escalation to drop-vote is unchanged: only do it if data shows it's frequent. |
| **A5** | 🟠 | `storage._shallow_diff` truncates payloads on bus | **DONE** | [`ai/swarm/agents/storage.py`](../../ai/swarm/agents/storage.py) lines 89, 103–127 — full diff goes on the bus; `summarize_diff_for_telemetry` is a separate projection. |
| **G1** | 🟠 | Go handler loops do not check `ctx.Done()` | **DONE** | [`server/cmd/api/main.go`](../../server/cmd/api/main.go) lines 220, 332, 441 — every `rows.Next()` loop polls `ctx.Done()`. |
| **G2** | 🟡 | No handler-level timeout | **DONE** | [`server/cmd/api/main.go`](../../server/cmd/api/main.go) line 107 wraps the mux with `http.TimeoutHandler(r, cfg.HTTPHandlerTimeout(), ...)`. Knob `HTTP_HANDLER_TIMEOUT_SEC` (default `25s`) at [`server/internal/config/config.go`](../../server/internal/config/config.go); included in `specs()`. |
| **G3** | 🟢 | `config.MustLoad()` panics rather than returning error | **DISPROVEN — see §3.G3** | Real callers already use `Load()`. `MustLoad()` is dead code. Drop opportunistically. Not an audit finding. |
| **IM1** | 🟡 | `make mock.verify` not a CI gate | **OPEN — Wave C** | Truly NEEDS-VERIFICATION on whether CI calls it. Defer to Wave C: wire into the CI prologue (or a `conftest.py` session-start hook). |
| **M2** | 🟡 | Other FK columns may be missing indexes | **OPEN — Wave C** | Audit `005_predictor.sql` for FK columns the swarm queries; add a single follow-up migration. |
| **T2** | 🟠 | No `predict.proofreader_verdict.v1` schema | **DONE** | [`ai/swarm/sdk/schemas/predict.proofreader_verdict.v1.json`](../../ai/swarm/sdk/schemas/predict.proofreader_verdict.v1.json) exists. Topic + producer land in Phase 6.1. |
| **T3** | 🟠 | No regression test that consensus is *forbidden* to publish `match.outcome.v1` | **DONE** | `test_consensus_does_not_publish_to_match_outcome` in [`ai/swarm/agents/tests/test_consensus.py`](../../ai/swarm/agents/tests/test_consensus.py). |
| **PERF1** | 🟢 | `_fuse_score_grids()` 3-pass | **OPEN — Wave C** | Negligible today. |
| **PERF2** | 🟢 | `freshness` event_id derived under storage lock | **OPEN — Wave C** | NEEDS-VERIFICATION; trivial to move outside if confirmed. |
| **PERF3** | 🟢 | Schema validator re-loads JSON each `validate()` | **DONE** | [`ai/swarm/sdk/schemas/__init__.py`](../../ai/swarm/sdk/schemas/__init__.py) line 30 — `@lru_cache(maxsize=64)` on `load(topic)`. |
| **SK2** | 🟡 | Validator silently accepts `$ref` / `oneOf` / `anyOf` | **DONE (constraint, not feature)** | Contract test `test_schema_does_not_use_unsupported_constructs` in `test_schemas_additional_properties.py` rejects schemas that use them. The validator stays small; schema authors are forced to inline. |
| **A2** | — | Consensus `_pending` leaks `_PendingFusion` after finalize | **DISPROVEN (round 2 already)** | Every exit path (finalize, expired, flush_all, late-vote) deletes the key. See §3.A2. |

### 2.3 `gpt5.3-Codex.md`

| # | Sev | Claim | Status | Evidence |
|---|---|---|---|---|
| **1** | 🔴 | `make train-model` sends `model-only` but orchestrator only accepts `full-training` | **DISPROVEN** | [`ai/orchestrator/state_machine.py`](../../ai/orchestrator/state_machine.py) line 189 — `choices=["full-training", "model-only"]`. Both modes are accepted. The `model-only` branch is even special-cased at line 196–201. See §3.GPT-1. |
| **2** | 🔴 | `DataProofreader.validate_batch` crashes on `ht_home_score="x"` | **OPEN — superseded by B3 deletion** | [`ai/proofreader/validator.py`](../../ai/proofreader/validator.py) lines 130–155 do not coerce `ht[0]` / `ft[0]` before downstream comparisons. **However** this is in the legacy `ai/proofreader/` shell that will be deleted as part of B3 (Wave A.2). No work owed in isolation; the deletion subsumes the fix. |
| **3** | 🔴 | `/api/v1/matches` ignores `league_id`/`season`; cache poisoned | **DONE** | [`server/cmd/api/main.go`](../../server/cmd/api/main.go) lines 178–198 — `c.Query("league_id")`, `c.Query("season")`, parametrised `WHERE ($1 = '' OR league_id = $1) AND ($2 = '' OR season = $2)`, cache key `matches:list:%s:%s:%d`. The audit's claim was real at the time but the code has since been corrected; round-2/3 didn't flag it as work because they didn't verify against gpt5's input. |
| **4** | 🔴 | Scheduler fallback no-op; APScheduler missing from requirements | **DISPROVEN** | [`ai/requirements.txt`](../../ai/requirements.txt) line 14 — `apscheduler>=3.10.0`. The fallback branch in [`ai/scheduler.py`](../../ai/scheduler.py) is dead code in containerized runs. See §3.GPT-4. |
| **5** | 🟠 | `SWARM_HEARTBEAT_SEC` field present but missing from `specs()` | **DONE** | [`server/internal/config/config.go`](../../server/internal/config/config.go) lines 55, 139, 208 — declared, exported, and bound through `specs()`. Round-3 G2 incidentally re-touched this file and the gap was closed. |
| **6** | 🟡 | Cross-source agreement hardcoded to `1.0` / `0.95` | **OPEN — Wave C** | [`ai/pipeline/training_pipeline.py`](../../ai/pipeline/training_pipeline.py) line 171 — `agreement = 1.0 if len(scrape.source_breakdown) <= 1 else 0.95`. Tag for Wave C; replace with a calibrated function once Phase 9 wires multiple real sources. |
| **7** | 🟡 | `test_acc` misleading — uses random `train_test_split` inside stage | **OPEN — Wave C** | [`ai/pipeline/training_pipeline.py`](../../ai/pipeline/training_pipeline.py) lines 227–251 — `test_acc` first reads `mlogloss[-1]` (which is *log-loss*, not accuracy), then immediately overwrites with an accuracy from a random `train_test_split` at line 237. **Two bugs in one block.** This is a *separate* call-site from the trainer.py P1 fix; needs the same time-based-split treatment. Real, not Phase-6-blocking. |
| **8** | 🟡 | `PYTHONPATH=ai` contract non-obvious | **DOCUMENTED** | [`xops/makefile/tests.py`](../../xops/makefile/tests.py) line 19 sets it; [`conftest.py`](../../conftest.py) line 15 documents why. Not a bug; a discoverability nit. No work owed. |
| **9** | 🟢 | Hardcoded `python3` instead of `sys.executable` | **OPEN — Wave C, trivial** | [`xops/makefile/ai_commands.py`](../../xops/makefile/ai_commands.py) lines 137–138 still spawn `python3` literal. One-line fix. |
| **10** | 🟢 | Health endpoint pings DB+Redis on every call | **OPEN — Wave C** | [`server/cmd/api/main.go`](../../server/cmd/api/main.go) lines 144–156 — every `/healthz` ping issues a DB roundtrip and a Redis ping. Split into `/livez` (no externals) + `/readyz` (with externals + 1s TTL cache). |

### 2.4 `gemini3.1Pro.md`

The Gemini report is high-level and rarely cites file:line. Each
item below is mapped to the closest concrete check in the live tree.

| # | Topic | Status | Evidence |
|---|---|---|---|
| 1 | "Fabricated Data Risks" | **DONE (Rule 3)** | AGENTS.md Rule 3 codifies this; there is no production-data fabrication path in the live tree (verified by spot-grep of `random.seed`, `np.random` in non-test code — only training-noise injection at known knob-controlled call sites). |
| 2 | "In-memory state isolation" | **DONE** | Phase 4.7 ledger Protocol; round-2 A1 bounded the in-memory ledger; storage lives in Postgres / Redis. Conforms to Rule 5. |
| 3 | "Security & git rule" | **DONE** | AGENTS.md Rule 9; CLAUDE.md scope discipline; CI enforces the forbidden-edit list. |
| 4 | "Scraper rate-limiting" | **DONE** | Source-watcher (Phase 2.8) classifier owns the ceiling; mock-stack owns the dev-time gate. Same item as round-2 S3, disproven (§3.S3). |
| 5 | "Swarm backpressure" | **DONE** | Bus-level read islicing + `_pending` dict (Phase 4 perf items in agent memory); A3 rate-limited overflow flagging closed the last loud telemetry path. |
| 6 | "Model Sizing — smallest works" | **DONE (Rule 4)** | Predictor portfolio is Elo / Dixon-Coles / XGBoost / LGBM — all small/classical. Rule 4 enforced. |
| 7 | "Concurrent migrations" | **DEFERRED** | No multi-writer migration scenario today; Phase 9's HA work will revisit. Not a Phase 6 concern. |
| 8 | "Test partitioning" | **DONE** | `slow` marker + `make test.fast` (P6 round 1). |
| 9 | "Upstream-availability assumptions" | **DONE** | S1 categorisation + source-watcher freshness signals already give the swarm a way to detect downed upstreams. |
| 10 | "Turkish/English mixing audit" | **DONE (continuous)** | AGENTS.md Rule 6; spot-check passes — UX strings (locale_tr.yaml) Turkish, code/log/comment English. |

---

## 3. Disproven on re-verification

These show the file:line evidence that the original claim is wrong,
so a future round does not re-flag them.

### 3.A2 — Consensus `_pending` does not leak

Subagent in round 2 missed all four cleanup sites in
[`ai/swarm/agents/consensus.py`](../../ai/swarm/agents/consensus.py):
all-voters finalize (`del self._pending[key]`), `flush_expired()`,
`flush_all()`, late-vote drop (`self._pending.pop(key, None)`).
Do not "fix" this.

### 3.S3 — Engine has a rate ceiling via source-watcher

The engine path in [`ai/scraper/engine.py`](../../ai/scraper/engine.py)
delegates rate-limiting to the source-watcher classifier (Phase 2.8)
and to the per-source `cfg.scrape_rate_limit_*` knobs in
[`ai/common/config.py`](../../ai/common/config.py). The Phase 2 mock
stack adds a second ceiling for dev/CI. There is no path that
bypasses both gates.

### 3.G3 — `MustLoad()` is dead code, not a panic risk

Both real callers (`server/cmd/api/main.go` and
`server/cmd/swarmctl/main.go`) call `Load()` and handle the error.
`MustLoad()` exists in `server/internal/config/config.go` but is
unused. **Not an audit finding.** Drop in the next opportunistic
server-component patch — not blocking.

### 3.GPT-1 — `make train-model` is wired correctly

[`xops/makefile/ai_commands.py`](../../xops/makefile/ai_commands.py)
line 99 dispatches `cmd_train_model` → `_train_with_mode(argv,
"model-only")` → `python -m orchestrator.state_machine --mode
model-only`. The orchestrator's argparse at
[`ai/orchestrator/state_machine.py`](../../ai/orchestrator/state_machine.py)
line 189 declares `choices=["full-training", "model-only"]`. Both
modes are valid; `model-only` is special-cased at lines 196–201.
The original gpt5 claim was based on an older snapshot.

### 3.GPT-4 — APScheduler is in `ai/requirements.txt`

[`ai/requirements.txt`](../../ai/requirements.txt) line 14 pins
`apscheduler>=3.10.0`. Inside the `ai` container the import succeeds
and the scheduler runs. The fallback branch in
[`ai/scheduler.py`](../../ai/scheduler.py) lines 28–82 is dead code
for production runs and is reachable only on a host without the
package — which is not how the project runs (Rule 2: containerised
only). **Optional cleanup:** delete the fallback branch entirely so
a missing dependency fails loudly instead of silently. Tag for
Wave C (low priority).

---

## 4. Wave A — Hard blockers for Phase 6 kickoff

Each item ships as its own commit + tracker row + `make
version.bump` per AGENTS.md §3 / §6.1. Land in the order below.

### 4.1 🔴 B2 — Decide cache topology and wire `cache_prediction_ttl_sec`

**Why it blocks Phase 6:** ROADMAP §736 says `predict.final` is a
**candidate** — never user-visible until the proofreader quorum
approves it. Today's `cache.v1` agent
([`ai/swarm/agents/cache.py`](../../ai/swarm/agents/cache.py)) only
subscribes to `MATCH_STORED`. If Phase 6.1 wires `cache.v1` directly
to `predict.final` it bypasses the proofreader and breaks the
candidate-vs-approved contract.

**Decision required (recommend Option A, lock in §6.1 design doc
before any code lands):**

- **Option A — new topic `predict.approved.v1`** (recommended):
  emitted by the proofreader fan-in (`proofreader_aggregator.v1`)
  only when quorum passes. `cache.v1` subscribes to this topic and
  to `MATCH_STORED`. Cleanest contract; smallest blast radius;
  matches the already-shipped `predict.proofreader_verdict.v1`
  schema (T2).
- Option B — proofreader as `predict.final` middleware that
  re-emits on `predict.final.approved`. Reuses `predict.final`'s
  schema; couples publisher to consumer.
- Option C — `cache.v1` joins `predict.final × proofreader.verdict`
  on `prediction_id` with an in-memory window. Highest complexity;
  adds state to `cache.v1`.

**Deliverables (Option A):**

- [ ] Add `PREDICT_APPROVED = Topic("predict.approved.v1")` in
      [`ai/swarm/agents/topics.py`](../../ai/swarm/agents/topics.py).
- [ ] Add `predict.approved.v1.json` schema (re-uses
      `predict.final.v1` shape + `approved_by[]` proofreader IDs +
      `approved_at`). `additionalProperties: false`.
- [ ] Add a row to the §3.5 wire-authority table in
      [`docs/design/SWARM.md`](../design/SWARM.md).
- [ ] Wire `cache.v1` subscription; have it use
      `cfg.cache_prediction_ttl_sec`.
- [ ] Contract test: `cache.v1` does **not** subscribe to
      `predict.final` (boundary discipline).
- [ ] Tick ROADMAP §4.5 line 636 `[ ]` → `[x]`.
- [ ] `make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.1
      cache topology Option A — predict.approved.v1 wired"`
- [ ] `make version.bump COMPONENT=swarm LEVEL=minor NOTE="..."`

**Effort:** small (≤ 1 working session).

### 4.2 🟡 B3 — Decide legacy-proofreader / drift retirement sequence

**Why it blocks Phase 6:** Round 3 extracted rule bodies from
[`ai/proofreader/validator.py`](../../ai/proofreader/validator.py)
into `ai/swarm/agents/proofreader/checks.py` and made the legacy
shell delegate. **The shell still exists** and is still imported by:

- [`ai/pipeline/runner.py`](../../ai/pipeline/runner.py) (line ~23)
- [`ai/pipeline/training_pipeline.py`](../../ai/pipeline/training_pipeline.py) (line ~149)
- [`ai/data_showcase.py`](../../ai/data_showcase.py) (line ~23 + `show_proofreading()` at ~240)
- [`ai/tests/test_unit.py`](../../ai/tests/test_unit.py) (`TestProofreader`, `TestCrossValidator`, `TestDriftDetector` classes)

**Two viable plans — pick one before §6.1:**

- **Plan A — delete-before-Phase-6** (cleaner, more work now):
  rip the legacy shells, rewrite the legacy callers to use the
  new `checks.py` + (eventually) the bus-based `Proofreader` Agent.
  Move the `TestProofreader` / `TestCrossValidator` /
  `TestDriftDetector` test bodies into
  `ai/swarm/agents/tests/test_proofreader_checks.py` (already
  exists). Pro: no two-truths during Phase 6. Con: large diff.
- **Plan B — delete-after-Phase-6** (current de-facto plan, less
  work now, more risk): leave the shells delegating to
  `checks.py`; add a contract test that the shell's output is
  byte-identical to the bus-Agent's output for the same input;
  delete the shell + legacy callers in a post-Phase-6 cleanup PR.
  Pro: smaller diff today. Con: easy to drift if the
  bus-Agent deviates from `checks.py`.

**Recommendation:** Plan B *with the byte-identical contract test
shipping in this Wave A.2 commit*. The test makes the deferral
safe; without it, deferral is risky.

**Deliverables:**

- [ ] `test_legacy_proofreader_shell_matches_checks` contract test
      in `ai/swarm/agents/tests/test_proofreader_checks.py`.
- [ ] Tracker row: `make track.add PHASE=5 STATUS=in-progress
      NOTE="Wave A.2 legacy proofreader retirement plan locked
      (Plan B + byte-identical contract test)"`
- [ ] No version bump owed (test only). The eventual deletion in
      a post-Phase-6 PR will bump `ai minor`.

**Also resolves gpt5 #2** (the `ht_home_score="x"` crash): once
the shell delegates to `checks.py`, the typed-coercion in
`checks.py` covers the crash path. Add a regression test inside
the contract test for the `"x"` case.

**Effort:** tiny (one test file).

### 4.3 🟡 D4 — Lock the quorum formula in ROADMAP §6.1

**Why it blocks Phase 6:** ROADMAP §6.1 currently reads
`⌈N/2⌉ + 1`. For N=3 this evaluates to 3 — i.e., **all** voters
must pass. Phase 6.1's `cfg.proofreader_quorum_threshold` constant
will be derived from this formula on first attempt.

**Recommendation:** simple majority `⌊N/2⌋ + 1`. For N=3 → 2; for
N=5 → 3. Matches the prose "more than half".

**Deliverables (doc-only):**

- [ ] Update ROADMAP §6.1 formula text.
- [ ] Add a one-paragraph rationale citing this audit row.
- [ ] Tracker row: `make track.add PHASE=5 STATUS=in-progress
      NOTE="Wave A.3 ROADMAP §6.1 quorum formula locked: simple
      majority ⌊N/2⌋+1"`
- [ ] No version bump owed (doc-only; `docs` component bumps only
      on user-facing doc structure changes).

**Effort:** trivial (≤ 5 minutes).

### 4.4 🟢 D1 — Lock the drift-topic naming convention (doc)

**Why it's adjacent to Phase 6:** Phase 2.8's source-watcher will
emit drift signals for *upstream* schema drift; Phase 6.3's
`drift.v1` will emit for *model* drift. Same word, different
domains. Decide names now so neither surprises the other.

**Recommendation:**

- `datasource.drift.v1` — owned by source-watcher (Phase 2.8).
- `swarm.drift.v1` — owned by Phase 6.3 drift agent.

**Deliverables:**

- [ ] Update [`docs/design/COMPONENT_LAYOUT.md`](../design/COMPONENT_LAYOUT.md) §wire-authority table.
- [ ] Update [`docs/design/SWARM.md`](../design/SWARM.md) topic catalogue.
- [ ] Cross-link from Phase 2.8 design doc and ROADMAP §6.3.
- [ ] Tracker row.

**Effort:** trivial (doc-only; bundle with D4 in one commit).

---

## 5. Wave B — Phase 6 build itself

Specified by [ROADMAP §Phase 6](../planning/ROADMAP.md#-phase-6--proofreader--drift-agents).
Lands in three commits, one per sub-phase, each with its own
tracker row + `make version.bump COMPONENT=swarm LEVEL=minor`. The
final §6.3 bump promotes `swarm` to `0.4.0`.

### 5.1 §6.1 — Multi-proofreader voting

**Topology (after Wave A.1 chooses Option A):**

```
predict.final  ──►  proofreader.v1 (×N=3)  ──► proofreader.verdict.v1
                                                    │
                                                    ▼
                                          proofreader_aggregator.v1
                                              (singleton, replicas:1)
                                                    │
                                       ┌────────────┼─────────────┐
                                       ▼            ▼             ▼
                                predict.approved.v1   proof.flag (on fail)
                                       │
                                       ▼
                                   cache.v1
```

**Locked decisions (per Wave A above):**

- Quorum: `⌊N/2⌋ + 1` simple majority. N=3 → 2.
- Cache: subscribes to `predict.approved.v1`, not `predict.final`.
- Topic name: `swarm.drift.v1` (no collision with source-watcher).

**New config knobs (triangle: `config.py` + `defaults.yaml` +
`.env.example`):**

- `cfg.proofreader_replicas` (default `3`)
- `cfg.proofreader_quorum_window_ms` (default `200`)
- `cfg.proofreader_sanity_eps` (default `1e-6`)
- `cfg.proofreader_plausibility_max_away_win` (default `0.85`)
- `cfg.proofreader_grid_consistency_tol` (default `1e-3`)
- `cfg.proofreader_odds_max_drift` (default `0.20`)
- `cfg.proofreader_history_brier_max` (default `0.40`)

**New `proof.flag.kind` enum values (extend
`proof.flag.json`):** `proofreader_quorum_failed`,
`proofreader_no_quorum`, `proofreader_late_verdict_dropped`.

**Deliverables:**

- [ ] `ai/swarm/agents/proofreader/_base.py` — shared `Proofreader`
      Agent that runs every check in
      `ai/swarm/agents/proofreader/checks.py` and emits a verdict.
- [ ] `ai/swarm/agents/proofreader/aggregator.py` — fan-in
      singleton; emits `predict.approved.v1` on quorum-pass;
      emits `proof.flag` on `proofreader_quorum_failed` /
      `proofreader_no_quorum`.
- [ ] `predict.approved.v1.json` schema (Wave A.1 lays this).
- [ ] Extend `predict.proofreader_verdict.v1.json` with
      `proofreader_id`, `verdict ∈ {pass, fail}`, `failed_checks[]`,
      `prediction_id`.
- [ ] Tests: quorum-pass (N=3, 2 pass), quorum-fail (N=3, 2 fail),
      late-verdict-dropped, no-quorum-window (1 pass + timeout),
      single-publication idempotency, ledger-bounded under load.
- [ ] Tick every checkbox in ROADMAP §6.1.
- [ ] Tracker rows: `start` at head, `complete` on green.
- [ ] `make version.bump COMPONENT=swarm LEVEL=minor`.

### 5.2 §6.2 — Built-in proofreader checks

Each check is a pure function in
`ai/swarm/agents/proofreader/checks.py`, unit-tested independently
(happy + ≥1 adversarial per Rule 7), then composed by the
`Proofreader` Agent.

| Check | Knob | Skip condition |
|---|---|---|
| **Sanity** | `cfg.proofreader_sanity_eps` | never (always runs) |
| **Plausibility** | `cfg.proofreader_plausibility_max_away_win` | match not in `derbies` set |
| **Consistency** | `cfg.proofreader_grid_consistency_tol` | predictor produced no grid (per §D3 spec note) |
| **Cross-source** | `cfg.proofreader_odds_max_drift` | no implied odds present (no-op until Phase 9 wires odds) |
| **Historical** | `cfg.proofreader_history_brier_max` | `<3` priors |

Each check ships a `proof.flag.kind` constant + an adversarial
test. Tick every checkbox in ROADMAP §6.2.

`make version.bump COMPONENT=swarm LEVEL=minor`.

### 5.3 §6.3 — Drift agent (`swarm.drift.v1`)

**Inputs:** `predict.final` + `match.outcome.v1` (already produced
by storage per T1). Joins on `prediction_id` → `match_id`.

**Trip rules:**

- (a) Rolling Brier per `(league, market, predictor_id)` over a
      window of `cfg.drift_window_size` (default `200`) crosses
      `cfg.drift_accuracy_floor` (the same knob §5.4 already uses
      — single source of truth).
- (b) KS-test on input feature distribution rejects stationarity
      at `cfg.drift_pvalue` (default `0.01`). Feature snapshots
      pulled from `freshness.events.v1` payloads (full diff is
      preserved per A5) — no extra DB query, swarm-isolation
      preserved.

**Trip emits** `maint.event{kind: retrain_request, target:
<predictor>}` on the existing `models.events.v1` topic. Extend the
schema's `kind` enum.

**State persistence:** in-memory dict keyed on `(league, market,
predictor_id)` for v1; Phase 9 backs it with Postgres (mirrors the
`CalibrationStore` Protocol seam).

**Tests:** 100-prediction synthetic stream that crosses the floor
→ trip; stable stream → no trip; KS-trip on shifted feature
distribution; idempotency (one `retrain_request` per `(predictor,
window)` until reset); contract test that `swarm.drift.v1` is
**not** the same topic as `datasource.drift.v1`.

Tick every checkbox in ROADMAP §6.3.

`make version.bump COMPONENT=swarm LEVEL=minor` →
`swarm 0.3.x → 0.4.0` at the Phase 6 close.

### 5.4 Phase 6 DoD (mirror ROADMAP §Phase 6 checklist)

- [ ] All §6.1 / §6.2 / §6.3 checkboxes flipped.
- [ ] `make swarm.demo` extended (or new `make swarm.proofread`)
      showing happy-path: predictors → consensus → proofreaders ×3
      → aggregator → cache.
- [ ] `swarmctl ps` + `swarmctl topics` show new agents + topics.
- [ ] Triangle test green for every new config knob.
- [ ] `swarm` chart at `0.4.0`.
- [ ] Tracker rows `start` at the head of each sub-phase,
      `complete` at the end, plus a phase-rollup `complete` row at
      the close.

---

## 6. Wave C — Polish (parallel-safe with Wave B)

Land opportunistically. None block Phase 6 kickoff.

| ID | Item | Component | Effort | Bump |
|---|---|---|---|---|
| **A4** | Soft-warn on calibration-version skew across votes in a window | `swarm` | tiny | patch |
| **C1** | Recurring `cfg` ↔ `xops/env/.env.example` audit (run + close gaps) | `xops` | tiny | patch |
| **IM1** | Wire `make mock.verify` into CI prologue | `xops` | tiny | patch |
| **M2** | Audit `005_predictor.sql` FKs → add covering indexes | `ai` | small | patch |
| **B5** | Wire `consensus_brier_window` into Phase 6.3 drift agent (subsumed by Wave B.3) | `swarm` | — | (folded) |
| **PERF1** | Single-pass `_fuse_score_grids()` | `swarm` | tiny | patch |
| **PERF2** | Move `derive_event_id` outside storage lock | `swarm` | tiny | patch |
| **GPT-6** | Replace hardcoded `1.0`/`0.95` cross-source agreement (training_pipeline L171) | `ai` | small | patch |
| **GPT-7** | Fix `test_acc` in `training_pipeline.py` L227–251 (it's mlogloss + random split — use time-based split + true accuracy) | `ai` | small | patch |
| **GPT-9** | Replace literal `python3` with `sys.executable` in `xops/makefile/ai_commands.py` L137–138 | `xops` | tiny | patch |
| **GPT-10** | Split `/healthz` → `/livez` (no externals) + `/readyz` (cached 1s TTL) | `server` | small | patch |
| **GPT-4** (cleanup) | Delete the dead APScheduler-fallback branch in `ai/scheduler.py`; fail loudly if missing | `ai` | tiny | patch |
| **G3** (cleanup) | Delete unused `MustLoad()` in `server/internal/config/config.go` | `server` | tiny | patch |
| **B3** (final) | Delete legacy `ai/proofreader/` + `ai/model/drift.py` shells; rewire callers; collapse `TestProofreader` etc. into `test_proofreader_checks.py` | `ai` | medium | minor |

**Total Wave C:** ~14 patch-level changes (most one-file, one-test).
None depend on Phase 6 internals; can run in parallel with Wave B.

---

## 7. Architectural decisions to lock before Phase 6 (summary)

These are the ONLY things that need a human "yes" before Wave A
executes:

| ID | Decision | Recommendation | Reversible? |
|---|---|---|---|
| **B2** | Cache topology | **Option A** — new `predict.approved.v1` topic | Yes (could rename topic) |
| **D1** | Drift topic naming | `datasource.drift.v1` (Phase 2.8) + `swarm.drift.v1` (Phase 6.3) | Yes (rename pre-1.0) |
| **D4** | Quorum formula | Simple majority `⌊N/2⌋ + 1` | Yes (config knob) |
| **B3** | Legacy proofreader retirement sequence | **Plan B** + byte-identical contract test in Wave A.2 | Yes (can flip to Plan A later) |

Pick four answers, this whole roadmap unblocks.

---

## 8. Sequencing & tracker plan

```
   Wave A (blockers, gated by §7 decisions)
   ────────────────────────────────────────
   A.1  B2   cache topology + predict.approved.v1   →  swarm minor
   A.2  B3   legacy retirement plan + contract test →  (no bump, test-only)
   A.3  D4   ROADMAP §6.1 quorum formula           →  doc-only
   A.4  D1   drift topic naming                    →  doc-only (bundle w/ A.3)

   Wave B (Phase 6 build)
   ──────────────────────
   B.1  §6.1  multi-proofreader voting              →  swarm minor
   B.2  §6.2  built-in checks                       →  swarm minor
   B.3  §6.3  drift agent + KS-test + retrain emit  →  swarm minor → 0.4.0

   Wave C (polish, parallel-safe)
   ──────────────────────────────
   14 patch-level items + 1 minor (B3 final deletion)
```

**Tracker rows to write (one per commit):**

```bash
# Wave A
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.1 cache topology Option A — predict.approved.v1 wired"
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.2 legacy proofreader retirement Plan B + byte-identical contract test"
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.3 ROADMAP §6.1 quorum formula locked: simple majority ⌊N/2⌋+1"
make track.add PHASE=5 STATUS=in-progress NOTE="Wave A.4 drift topic naming locked: datasource.drift.v1 vs swarm.drift.v1"

# Wave B
make track.add PHASE=6 STATUS=in-progress                NOTE="Phase 6.1 multi-proofreader voting kickoff"
make track.add PHASE=6 STATUS=completed   --subphase 1   NOTE="§6.1 voting + aggregator + tests green"
make track.add PHASE=6 STATUS=in-progress --subphase 2   NOTE="§6.2 built-in checks kickoff"
make track.add PHASE=6 STATUS=completed   --subphase 2   NOTE="§6.2 5 checks + adversarial tests green"
make track.add PHASE=6 STATUS=in-progress --subphase 3   NOTE="§6.3 drift.v1 kickoff"
make track.add PHASE=6 STATUS=completed   --subphase 3   NOTE="§6.3 drift agent + KS-test + retrain emit"
make track.add PHASE=6 STATUS=completed                  NOTE="Phase 6 DoD green; swarm bumped to 0.4.0"
```

---

## 9. Phase 6 readiness checklist (gate before Wave B)

Before any §6.1 code lands, every box below must be ticked:

- [ ] §7 decisions resolved by the human (B2, D1, D4, B3 plan).
- [ ] Wave A.1 (cache topology + `predict.approved.v1`) merged.
- [ ] Wave A.2 (legacy retirement plan + contract test) merged.
- [ ] Wave A.3 + A.4 (ROADMAP §6.1 + topic-naming docs) merged.
- [ ] `make test.ai` green.
- [ ] `cd server && go test ./...` green.
- [ ] `make version.show` reflects every Wave A bump.
- [ ] No new `cfg.*` knob is missing from any of the three sources
      (`config.py`, `defaults.yaml`, `xops/env/.env.example`).
- [ ] `swarmctl topics` lists `predict.approved.v1`.

Once all nine boxes are ticked, Phase 6 kickoff is unblocked.

---

## 10. Self-review against AGENTS.md

This document is a planning artefact, not a code change. Per
AGENTS.md §3 + §6.1, no tracker row is owed for the document
itself, and no `make version.bump` is required. The first wave of
tracker rows + bumps lands when **Wave A.1** commits.

The doc respects:

- **Rule 1 (single-source config):** every proposed knob is routed
  through `config.py` + `defaults.yaml` + `.env.example`.
- **Rule 3 (no fabricated production data):** no production-side
  fakes proposed; tests-only synthetic streams in §5.3 testing.
- **Rule 6 (TR UX, EN infra):** all proposed code, comments,
  topics, metric names are English; no user-facing strings
  introduced.
- **Rule 7 (adversarial tests first-class):** every proofreader
  check ships with at least one negative test; drift agent ships
  with KS-trip + accuracy-floor-trip tests.
- **Rule 9 (no `git`):** the `make track.add` / `make version.bump`
  lines in §8 are intended for the agent to run at commit time;
  no `git` invocations.
- **Rule 10 (tests track code):** every Wave A and Wave B item
  names the test it ships with; no test is weakened or deleted to
  pass a build.
- **§3.4 (tick the ROADMAP):** Wave A.1 ticks ROADMAP §4.5
  line 636; Wave A.3 corrects ROADMAP §6.1 quorum prose; Wave B.1–B.3
  tick the §6.1 / §6.2 / §6.3 checkbox sets in full.

**One self-correction worth recording:** earlier rounds of audit
listed the round-1 `P4` (predictor `features_version`) as
"partial" / "still no predictor emits a non-empty value". This is
**out of date** — every one of the five predictors today sets a
concrete `features_version` class attribute, and `_base.py` raises
on construction if it's empty. Future audits should not re-flag.

---

*Document ends. No code changes will be made until the human
approves this plan.*
