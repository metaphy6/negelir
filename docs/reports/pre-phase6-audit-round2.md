# Pre-Phase 6 Audit — Round 2 (Deep Codebase Review)

**Date:** 2026-04-29
**Scope:** All 10 areas specified; round-1 GREEN items excluded.
**Auditor:** GitHub Copilot (Claude Opus 4.7) via Explore subagent + manual citation verification.
**Predecessor:** [`pre-phase6-audit.md`](pre-phase6-audit.md) (round 1, all 7 items implemented).

> **Verification status of citations.** All `path:line` citations
> have been spot-checked against the workspace. Where the original
> exploration "inferred" a finding without a hard citation, this
> report either drops it or downgrades it to **NEEDS-VERIFICATION**.
> One subagent finding was **disproved on review** and is shown
> stricken below so it does not get re-flagged.

---

## 0. TL;DR — Highest-Risk Items

1. **🔴 T1 · No `match.outcome.v1` topic** — Phase 6 drift agent has no
   outcome stream to compute Brier from. ROADMAP §6.3 cannot be
   wired without first emitting outcomes from the storage agent.
   Verified: [`ai/swarm/agents/topics.py`](../../ai/swarm/agents/topics.py)
   declares no outcome topic. **Blocks Phase 6 design.**
2. **🔴 P1 · Random `train_test_split` after rolling-window features**
   — features for a test match include stats from training matches
   that share their pre-match window. Verified at
   [ai/model/trainer.py#L77-L100](../../ai/model/trainer.py#L77-L100).
   Phase 6 backtests will report inflated accuracy. **Fix before any
   Phase 6 backtest is published.**
3. **🔴 A1 · `InMemoryLedger._seen` grows unbounded forever** —
   verified at
   [ai/swarm/agents/reactor.py#L55-L70](../../ai/swarm/agents/reactor.py#L55-L70).
   No TTL, no eviction. Multi-day swarm OOMs.
4. **🔴 M1 · Missing FK index on `match_normalized(raw_ref)`** —
   verified absent in
   [migrations/004_pipeline.sql](../../migrations/004_pipeline.sql)
   (migration creates the FK at `raw_ref BIGINT REFERENCES …` but no
   matching `CREATE INDEX`). Cleanup of `raw_scrapes` will table-scan
   `match_normalized`.
5. **🟠 SK1 · Schema validator defaults `additionalProperties=True`**
   — verified at
   [ai/swarm/sdk/schemas/__init__.py#L77](../../ai/swarm/sdk/schemas/__init__.py#L77).
   Typo'd payload keys pass validation silently. New Phase 6 producers
   will inherit the looseness unless we flip the default *or* every
   schema sets it explicitly.

---

## 1. Go Server (`server/`)

> **Note.** Findings G1–G3 below were produced by the subagent. I
> have not independently re-read every cited line; treat them as
> NEEDS-VERIFICATION until you skim the file. The pattern descriptions
> are still useful as a checklist.

### 🟠 G1 · Handler loops do not check `ctx.Done()` between rows · NEEDS-VERIFICATION

**Location (per subagent):** `server/cmd/api/main.go#L159-L185`

**Symptom:** `pool.Query(ctx, …)` is called with `c.Request.Context()`
but the subsequent `rows.Next()` loop does not poll `ctx.Done()`.
A cancelled client doesn't stop the server-side scan.

**Why it matters for Phase 6:** Proofreader fan-out can produce
concurrent slow queries; the connection pool (default `DBMaxConns=10`)
can starve.

**Suggested fix:** Inside the loop:
```go
for rows.Next() {
    select {
    case <-ctx.Done(): return
    default:
    }
    // ...
}
```

### 🟡 G2 · No handler-level timeout (only connection-level) · NEEDS-VERIFICATION

`HTTPReadTimeout` / `HTTPWriteTimeout` cap I/O, not handler compute.
Wrap the mux with `http.TimeoutHandler(r, 30*time.Second, …)`.

### 🟢 G3 · `config.MustLoad()` panics rather than returning error · NEEDS-VERIFICATION

If `MustLoad()` exists in `server/internal/config/config.go`, prefer
removing it in favour of the existing `Load() (*Config, error)` so
startup failures log cleanly.

---

## 2. AI Scraper Subsystem (`ai/scraper/`)

### 🟠 S1 · `engine.py` swallows three exception classes and returns `[]` · CONFIRMED

**Location:** [ai/scraper/engine.py#L66-L74](../../ai/scraper/engine.py#L66-L74)

```python
except requests.ConnectionError:  # L66
    ...
    return []                       # L68
except requests.Timeout:            # L69
    ...
    return []                       # L71
except Exception as e:              # L72
    ...
    return []                       # L74
```

A transient network problem looks identical to "no matches available"
to the caller.

**Why it matters for Phase 6:** Phase 6 reactors that depend on a
freshness signal arriving (cache invalidator, drift agent) will go
silent without a way to distinguish *"upstream returned 0 fixtures"*
from *"upstream is down"*. Drift will not fire on a downed source —
which is the worst outcome.

**Suggested fix:** Re-raise (or return a categorised result) for
`Timeout` / `ConnectionError`; keep the bare `Exception` handler only
if it logs and re-raises. At minimum bump the log level from `debug`
to `error`. Equivalent fixes also apply to lines 89 and 99.

### 🟡 S2 · `MackolikClient` opens `requests.Session` and never closes it · CONFIRMED

**Location:** [ai/scraper/mackolik.py#L136](../../ai/scraper/mackolik.py#L136)

No `__del__`, `close()`, or context-manager support. Per-instance TCP
connections accumulate during the backtest sweep.

**Suggested fix:** Implement `close()` + `__enter__`/`__exit__`; have
the orchestrator use `with MackolikClient(...) as client:`.

### 🟡 S3 · No verified rate limiter on the engine itself · NEEDS-VERIFICATION

The Phase 2 mock stack hosts the only rate-limiter we trust; the
real-upstream engine path is loosely policed. Worth a focused read of
[`engine.py`](../../ai/scraper/engine.py) and
[`real_data.py`](../../ai/scraper/real_data.py) to confirm no path
bypasses the source-watcher's rate ceiling.

---

## 3. Pipeline & Training (`ai/pipeline/`, `ai/model/`)

### 🔴 P1 · `train_test_split` happens after rolling-window features are computed · CONFIRMED

**Location:** [ai/model/trainer.py#L77-L100](../../ai/model/trainer.py#L77-L100)

Verified text:
```python
X, y = extract_real_dataset(min_history=5, matches=raw_matches)
...
X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
    X, y, sample_weights, test_size=cfg.training_test_split,
    random_state=cfg.training_random_seed, stratify=y,
)
```

`extract_real_dataset(..., min_history=5)` uses **prior matches** as
features. A random split places match A in the test set whose features
include match B that ended up in the training set — classical temporal
leakage on rolling-window features.

**Why it matters for Phase 6:** The proofreader and drift detector
both consume the trainer's accuracy signal. Inflated test accuracy
means the proofreader's "is this prediction in-distribution"
threshold is mis-calibrated and the drift agent's reference baseline
is wrong from day 1.

**Suggested fix:** Time-based split. Order matches by kickoff,
take the last N% as test, build features on each split independently.
Outline:
```python
raw_matches.sort(key=lambda m: m.kickoff)
split_at = int(len(raw_matches) * (1 - cfg.training_test_split))
train_raw, test_raw = raw_matches[:split_at], raw_matches[split_at:]
X_train, y_train = extract_real_dataset(min_history=5, matches=train_raw)
X_test,  y_test  = extract_real_dataset(min_history=5, matches=test_raw)
```
Add a regression test that asserts no test-match `kickoff` is earlier
than the latest train-match `kickoff` − feature-window.

### 🟡 P2 · Silent dropout when teams have fewer than `min_history` priors · NEEDS-VERIFICATION

`extract_real_dataset(min_history=5)` likely returns fewer rows than
`len(raw_matches)`. Confirm in
[ai/model/real_features.py](../../ai/model/real_features.py) and add
a `log.warning` reporting `(dropped, total)`. Cheap, low-risk.

---

## 4. Cross-Cutting (`ai/common/`)

### 🟡 C1 · Audit `cfg` fields vs `xops/env/.env.example` · NEEDS-VERIFICATION

The subagent flagged `mackolik_known_seasons` and `source_priority` as
candidates. Run `grep -E "cfg\.\w+" ai/**/*.py | sort -u` and diff
against the `.env.example` keys; bring any orphans into the example
file with a doc comment.

### 🟠 C2 · Logger sets `propagate = False` globally · CONFIRMED

**Location:** [ai/common/logger.py#L61](../../ai/common/logger.py#L61)

Disabling propagation prevents container log collectors from capturing
Negelir output unless the app explicitly attaches a stream handler. As
the swarm scales (Phase 6 adds proofreader / drift workers), centralised
log aggregation gets harder.

**Suggested fix:** Remove `logger.propagate = False`; configure the
root logger explicitly in `ai/main.py` for CLI runs and let agent
runners inherit it.

---

## 5. Swarm SDK (`ai/swarm/sdk/`)

### 🟠 SK1 · Validator defaults `additionalProperties=True` · CONFIRMED

**Location:** [ai/swarm/sdk/schemas/__init__.py#L77](../../ai/swarm/sdk/schemas/__init__.py#L77)

```python
additional = schema.get("additionalProperties", True)
```

Schemas that omit `additionalProperties` accept any extra key. A
typo like `"maker_id"` instead of `"market_id"` validates clean and
gets dropped silently downstream.

**Why it matters for Phase 6:** New Phase 6 schemas
(`predict.proofreader_verdict.v1`, `match.outcome.v1`) will inherit
the looseness unless we change the default *now*.

**Suggested fix:** Flip the default to `False` and audit every
existing schema in `ai/swarm/sdk/schemas/*.json` to add
`"additionalProperties": false` (or `true` with a comment if a
schema legitimately needs extension). Add a contract test that
fails if a schema lacks an explicit declaration.

### 🟡 SK2 · Validator does not check JSON-schema `$ref` or `oneOf` constructs · NEEDS-VERIFICATION

The hand-rolled validator is intentionally tiny. If any schema uses
`$ref` / `oneOf` / `anyOf`, it'll be silently ignored. Worth a quick
grep over `ai/swarm/sdk/schemas/*.json` to confirm we don't rely on
those constructs.

---

## 6. Swarm Agents (`ai/swarm/agents/`)

### 🔴 A1 · `InMemoryLedger._seen` grows unbounded · CONFIRMED

**Location:** [ai/swarm/agents/reactor.py#L55-L70](../../ai/swarm/agents/reactor.py#L55-L70)

```python
class InMemoryLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[tuple[str, str]] = set()

    def mark_processed(self, reactor: str, event_id: str) -> None:
        with self._lock:
            self._seen.add((reactor, event_id))
```

No TTL, no LRU. After 1M events the set is 1M tuples in RAM, per
reactor instance. Phase 6 adds at least two more reactors; each
inherits the leak.

**Why it matters for Phase 6:** Multi-day swarm runs OOM. Phase 6
backtests in particular replay months of matches in a single
process — `_seen` blows up fast.

**Suggested fix:** Either swap to a TTL-bounded set with periodic
sweep, or back the in-memory path with a fixed-size LRU
(e.g. `collections.OrderedDict` with `move_to_end` + `popitem`).
Add a test that asserts `len(ledger._seen)` stays bounded under
2× `max_size` events.

### ❌ ~~A2 · Consensus `._pending` leaks `_PendingFusion` after finalize~~ · DISPROVED

> **Subagent flagged this as critical; manual review of
> [`ai/swarm/agents/consensus.py`](../../ai/swarm/agents/consensus.py)
> shows it is wrong.** Every exit path deletes the key:
>
> - All-voters-in finalize: `del self._pending[key]` (around line 348)
> - `flush_expired()`: `del self._pending[key]` inside the lock
> - `flush_all()`: `self._pending.pop(k)` for every key
> - Late-vote drop: `self._pending.pop(key, None)`
>
> Pending bookkeeping is correctly cleaned. **Do not "fix" this; the
> finding was based on partial reading.**

### 🟡 A3 · Overflow flag emission is not rate-limited · NEEDS-VERIFICATION

In a chaos test where bursts of >`cfg.consensus_max_pending` predictions
arrive repeatedly, each burst emits a fresh overflow flag, flooding
`proof.flag` consumers. A 10s suppression window on
`_overflow_last_flagged_at` is enough.

### 🟡 A4 · No assertion that all votes for a window share calibration version · NEEDS-VERIFICATION

The §5.2 invariant says the *first* vote pins the calibration table for
the window (and the round-1 P5 test now guards that). What's not
asserted: every subsequent vote's `features_version` / model artifact
was trained against the *same* calibration version. If a trainer
retrains mid-window and a predictor immediately re-loads, vote N+1
mathematically uses a different calibration than vote 0, but consensus
fuses them as if they were comparable. Add a soft-warn (log + telemetry
counter); only escalate to drop-vote if data shows it's frequent.

### 🟠 A5 · `storage._shallow_diff` truncates payloads on the bus · NEEDS-VERIFICATION

If the storage agent really truncates the diff at 16 fields and ships
a `_truncated: true` placeholder on `freshness.events.v1`, reactors
that need to know *which* fields changed (Phase 6 proofreader: "skip
unchanged scoreline") are blind. Recommend keeping the full diff on
the bus message and truncating only for the telemetry projection.
Verify line numbers and current behaviour in
[`ai/swarm/agents/storage.py`](../../ai/swarm/agents/storage.py)
before changing.

---

## 7. Infra/Mock (`infra/mock/`, `xops/mock/`)

### 🟡 IM1 · `make mock.verify` is not a CI gate · NEEDS-VERIFICATION

If a developer edits `infra/mock/seeds/` without refreshing the
manifest, drift goes uncaught until someone runs the verify target
locally. Wire `make mock.verify` into CI before tests run, or as a
`conftest.py` session-start hook.

---

## 8. Migrations

### 🔴 M1 · No FK index on `match_normalized(raw_ref)` · CONFIRMED

**Location:** [migrations/004_pipeline.sql](../../migrations/004_pipeline.sql)
declares `raw_ref BIGINT REFERENCES raw_scrapes(id) ON DELETE SET NULL`
without a covering index. Cleanup of `raw_scrapes` then needs a
sequential scan of `match_normalized` to find children.

**Why it matters for Phase 6:** Phase 6 will run extended backtests
that periodically prune `raw_scrapes` to keep disk in check; without
the index those prunes lock the table.

**Suggested fix:** New migration `006_indexes.sql`:
```sql
CREATE INDEX IF NOT EXISTS idx_match_normalized_raw_ref
    ON match_normalized (raw_ref)
    WHERE raw_ref IS NOT NULL;
```
(Partial index — most rows have `raw_ref` set; the WHERE clause keeps
the index small if any are NULL.)

### 🟡 M2 · Other FK columns may be missing indexes · NEEDS-VERIFICATION

Audit every `REFERENCES` declaration across `migrations/001..005.sql`
and add a covering index for any column on the *child* side that the
swarm queries by. Likely candidates: any FK in
`migrations/005_predictor.sql`.

---

## 9. Test Coverage Gaps for Phase 6

### 🔴 T1 · No `match.outcome.v1` topic · CONFIRMED

**Location:** [ai/swarm/agents/topics.py](../../ai/swarm/agents/topics.py)
declares no outcome topic. ROADMAP §6.3 says drift tracks "rolling
Brier per predictor"; Brier needs an outcome stream.

**Why it matters for Phase 6:** Without it, the drift agent must
either re-derive the outcome from `match.stored` payloads (tight
coupling to the storage projection) or query the DB on every event
(latency + load). Both are anti-patterns the Phase 4 design was meant
to prevent.

**Suggested fix:** Add the topic + schema in this round. Storage
agent emits it whenever a `match.stored` event arrives with a
terminal status (e.g. `final`, `finished`). Schema sketch:
```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["match_id", "final_home", "final_away",
               "outcome_1x2", "outcome_at"],
  "properties": {
    "match_id": {"type": "string"},
    "final_home": {"type": "integer", "minimum": 0},
    "final_away": {"type": "integer", "minimum": 0},
    "outcome_1x2": {"type": "string", "enum": ["H", "D", "A"]},
    "outcome_ou25": {"type": "string", "enum": ["over", "under"]},
    "outcome_btts": {"type": "string", "enum": ["yes", "no"]},
    "outcome_at": {"type": "string", "format": "date-time"}
  }
}
```
Also: add the same topic to `swarmctl topics` and the consumer-side
tests.

### 🟠 T2 · No `predict.proofreader_verdict.v1` (or equivalent) · NEEDS-VERIFICATION

Phase 6 will need a topic carrying the proofreader's pass/fail
verdict per prediction so the cache reactor can subscribe selectively.
ROADMAP §4.5 references this contract but no schema exists yet. Spec
it before writing the proofreader code.

### 🟠 T3 · No regression test that consensus emits `match.outcome.v1` is *forbidden* · DESIGN

Once T1 lands, add a contract test that the **consensus** agent
*does not* publish to `match.outcome.v1` (boundary discipline:
outcomes are storage-side data, not prediction-side). Mirrors the
existing `proof.flag` back-emission ban.

---

## 10. Performance & Efficiency

These are **NIT-level** and should land only after the criticals.

### 🟢 PERF1 · `_fuse_score_grids()` makes 3 passes over an 81-cell grid

[ai/swarm/agents/consensus.py](../../ai/swarm/agents/consensus.py).
Negligible today. Document; revisit if grid size grows.

### 🟢 PERF2 · `freshness` event_id derived inside the storage lock

If `derive_event_id` involves a sha256 it's CPU work under the lock.
Compute before acquiring the lock. NEEDS-VERIFICATION on exact
location.

### 🟢 PERF3 · Schema validator re-loads JSON on each `validate()` call · NEEDS-VERIFICATION

Quick check of [`ai/swarm/sdk/schemas/__init__.py`](../../ai/swarm/sdk/schemas/__init__.py)
recommended; if `load(topic)` reads from disk every call, cache it
with `functools.lru_cache`.

---

## Recommended Order of Operations

Apply in this sequence; each warrants its own commit + tracker row +
`make version.bump` per `AGENTS.md` §6.1.

| # | Item | Component | Effort | Bumps | Why first |
|---|---|---|---|---|---|
| 1 | **T1** add `match.outcome.v1` topic + schema + storage producer + tests | `swarm` | small | minor | unblocks Phase 6 design |
| 2 | **P1** time-based train/test split + leakage regression test | `ai` | small | minor | inflated test acc poisons §6.3 baselines |
| 3 | **A1** bound `InMemoryLedger` (TTL or LRU) + bound test | `swarm` | small | patch | prevents OOM in long runs |
| 4 | **M1** `006_indexes.sql` adding partial index on `match_normalized(raw_ref)` | `ai` | tiny | patch | Phase 6 cleanup queries |
| 5 | **SK1** flip schema validator default to `additionalProperties=false`, audit each schema, add contract test | `swarm` | small | **major** (breaking) | Phase 6 schemas inherit looseness otherwise |
| 6 | **S1** categorize scraper exceptions; promote log level | `ai` | small | patch | drift can't fire on silent upstream failures |
| 7 | **C1** sync `cfg` fields ↔ `xops/env/.env.example` | `xops` | tiny | patch | ops clarity |
| 8 | **A3** rate-limit overflow flags | `swarm` | tiny | patch | telemetry backpressure |
| 9 | **A5** keep full diff on bus, truncate only for telemetry | `swarm` | small | minor | Phase 6 reactor needs it |
| 10 | **G1/G2** Go handler context check + handler-level timeout | `server` | small | patch | concurrent proofreader load |
| 11 | **A4** soft-warn on calibration-version skew across votes in a window | `swarm` | tiny | patch | rare correctness gap |
| 12 | **T2** spec `predict.proofreader_verdict.v1` schema (no producer yet) | `swarm` | tiny | minor | unblocks Phase 6.1 |
| 13 | **C2** drop `logger.propagate = False` | `ai` | tiny | patch | log aggregation |
| 14 | **S2** make `MackolikClient` a context manager | `ai` | tiny | patch | resource leak |
| 15 | **PERF3** cache `load()` for schemas | `swarm` | tiny | patch | hot-path cleanup |

> **Items 1–5 are blockers for Phase 6 kickoff.** Items 6–15 can be
> applied in parallel with the first proofreader / drift skeleton
> work.

---

## What was disproved on review

- **A2 (consensus `_pending` leak)** — the subagent missed all four
  cleanup sites. Documented above and ignored.

## Items deliberately not re-flagged (already GREEN per round 1)

ProofFlagKind registry / proof.flag enum (B1), lazy `cfg` imports
(P1 round 1), `features_version` on predictors (P4 round 1),
calibration swap-not-mutate test (P5 round 1), `slow` marker +
`make test.fast` (P6 round 1), `source_watcher` ↔ `swarm/drift/`
boundary (D1 round 1), simple-majority quorum formula (D4 round 1).

---

*Report ends. Recommended tracker entry once you start applying:*

```bash
make track.add PHASE=5 STATUS=in-progress \
  NOTE="Pre-Phase 6 audit round 2 saved; starting with T1 (match.outcome.v1)"
```
