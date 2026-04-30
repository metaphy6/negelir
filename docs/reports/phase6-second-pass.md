# Phase 6 — Second-Pass Audit (perf + cross-phase alignment)

> **Status:** SHIPPED — fixes landed in the same diff as this report.
>
> **Audience:** the next agent / human pair touching Phases 4-6.
>
> **Scope.** A re-read of Phase 6 *alongside* the now-implemented
> Phases 0-5, with two lenses the first-pass audit
> ([`phase6-implementation.md`](phase6-implementation.md)) did
> not apply systematically:
>
> 1. **Cross-phase alignment** — does Phase 6 still sit cleanly
>    inside the Phase 4-5 contracts after the first-pass fixes
>    landed (Waves 1-4)? Are the ROADMAP checkboxes that govern
>    those contracts honest?
> 2. **Performance / efficiency** — under realistic Phase 13a
>    load (multi-league, hundreds of buckets, 100k-pending
>    bound), do the agent hot-paths still scale?
>
> **Method.** Re-read every file the first-pass audit touched
> *plus* their counterparts in Phases 4-5 (cache, telemetry,
> consensus, storage, runner, bus). Findings are numbered
> `F2-N` so they don't collide with the first-pass `F-N`.
>
> **Test baseline at audit start:** `913 passed, 6 skipped, 2
> xfailed` (post first-pass).

---

## 1. Executive summary

Phase 6 is structurally fine after the first-pass waves. This
pass found **two real defects** the first pass missed and two
ROADMAP-state slips that disagree with shipped code:

* **F2-1 (Major perf).** `DriftAgent._handle_outcome` walks the
  entire `_pending` map (default cap 100,000 entries) for every
  inbound `match.outcome.v1`, even though the map is keyed on
  `(match_id, market)` and a direct lookup would do. Under
  Phase 13a multi-league load this is the agent's dominant cost.
* **F2-2 (Major alignment).** `swarm.bootstrap.build_agents()`
  registers Phase 5 + 6 agents only. The Phase 4 agents that
  *consume* the new `predict.approved.v1` topic — namely
  `cache.v1` and `telemetry.v1` — are NOT wired. A real swarm
  built via `build_swarm()` therefore emits approvals to nobody:
  the API gateway has no cache to serve from and the operator
  Prometheus page is silent on the new topics. The end-to-end
  smoke test in `test_bootstrap.py` does not catch this because
  it asserts on the bus, not on the cache.
* **F2-3 (Cosmetic).** ROADMAP §4.5 still shows
  `[ ] Subscribes to predict.approved.v1` for `cache.v1`,
  although the subscription is shipped, the boundary test
  enforces it, and §6 cross-phase notes already reference it.
* **F2-4 (Cosmetic).** ROADMAP §4.7 shows two reactor items
  unticked (`Trainer reactor with debounce…`, `Live-predictor
  reactors per §15.1`) although §5.5 has the very same items
  ticked and the implementations have been live since Phase 5
  shipped. Same kind of contract-vs-state drift.

All four fixes ship in the same diff as this report:

* drift agent: ~6-line replacement of the linear scan with a
  direct `pop`. New regression test asserts the lookup is O(1)
  in pending-map size.
* bootstrap: adds `cache.v1` + `telemetry.v1` to `build_agents()`
  and a new test asserts an approval reaches the cache backend
  end-to-end.
* ROADMAP: §4.5 + §4.7 boxes flipped with a cross-reference to
  this report.

What this pass also explicitly **cleared** (no fix needed,
findings recorded for the next reviewer):

* `_fuse_score_grids` (consensus) — triple-nested Python loop
  but at the default 6×6 grid × 4 votes (~150 ops) the cost is
  invisible compared to calibration store I/O. Worth revisiting
  only when Phase 13a expands to 10×10 grids on more markets.
* `InMemoryBus._streams` deque entries are never compacted after
  ack — a long-running test process grows memory in proportion
  to total messages. Out of scope: production uses the Redis
  backend, and prior perf pass already fixed the more pressing
  `read`/`ack` complexity.
* `AgentRunner._last_reclaim_at` — bounded by the agent's
  subscribed-topic count (≤ ~10 in practice), no eviction needed.
* `consensus.v1` `_finalize` — caches `prediction_id` +
  `calibration_table` per `_PendingFusion` first time computed
  (already a §5.2 invariant). No further perf work.

---

## 2. Findings registry

### F2-1 — `DriftAgent._handle_outcome` linear scan over `_pending` · **Major (perf)**

**Shape.** [`ai/swarm/agents/drift.py`](../../ai/swarm/agents/drift.py)
`_handle_outcome` opens with:

```python
keys_to_score = [
    key for key in self._pending
    if key[0] == outcome.match_id and key[1] == "1x2"
]
```

`self._pending` is `OrderedDict[(match_id, market), _PendingPrediction]`
bounded by `cfg.drift_max_pending` (default **100 000**). The
list-comprehension walks every key on every inbound outcome —
even though the lookup we want is the literal key
`(outcome.match_id, "1x2")`.

**Why it matters.** At Phase 13a (per-league profiles, hundreds
of in-flight matches per league) `_pending` lives near its
ceiling for hours at a time. Each settled match scans 100 000
entries to find the one we already know the key of. Per-outcome
cost: ~100 µs at default cap (Python dict iteration). That's
already inside the noise floor of a single match, but
linear-with-cap makes the cost grow with operator-tunable
storage, which is the wrong shape — bumping `drift_max_pending`
should not slow the hot path.

There's a smaller secondary reason too: the comprehension keeps
the agent lock held for longer than needed. Today drift's lock
is contended only by `_handle_approved` (also a quick op) so
this isn't observable, but it wastes the locking budget.

**Fix.** The pending key is already the unique identifier we
need. Replace the scan with a direct `pop`:

```python
key = (outcome.match_id, "1x2")
pending = self._pending.pop(key, None)
if pending is None:
    return ()
if key in self._settled:
    return ()
self._settled[key] = None
...
```

(One key per `(match_id, "1x2")` — the agent's own
`_handle_approved` overwrites on duplicate keys, so there is
never more than one pending entry per key. Verified by reading
`_handle_approved`.)

**Test.** New regression in `test_drift.py` asserts the
settle-after-1000-pending case: fill `_pending` with 1000
unrelated `(match_id, "1x2")` keys, then settle one specific
match and confirm only that match's record was popped (the
other 999 remain). Catches accidental re-introduction of the
linear scan via a coverage proxy.

**Diff:** ~10 LoC drift + ~25 LoC test. **Landed.**

---

### F2-2 — `build_agents()` omits Phase 4 consumers (cache, telemetry) · **Major (alignment)**

**Shape.** [`ai/swarm/bootstrap.py`](../../ai/swarm/bootstrap.py)
`build_agents()` returns the Phase 5 predictors + consensus +
Phase 6 proofreader replicas + aggregator + drift. It does **not**
register `CacheAgent` or `TelemetryAgent`. The first-pass `F-1`
fix shipped the bootstrap module but its scope was "Phase 5 + 6
agents the predictor / proofreader / drift pipeline needs" —
true to the docstring, but the cache + telemetry are the
*consumers* of `predict.approved.v1` and the wire-authority
contract for §4.5 (cache) and §4.6 (telemetry) names them
explicitly.

**Why it matters.**

* The cache is the only path from `predict.approved.v1` to the
  Phase 9 API gateway. Without it, every approval emitted by
  the swarm vanishes off the bus and the API serves stale
  empty results.
* Telemetry is the only Prometheus surface for the Phase 6
  topics (`predict.approved.v1`, `predict.proofreader_verdict.v1`,
  `maint.event.v1`, `match.outcome.v1` — all added to
  `_WATCHED_TOPICS` by the first-pass audit). Without
  telemetry registered in the bootstrap, that work is unobservable.
* Drift consumes approvals but does not expose them — the API
  cannot read drift state.

The first-pass smoke test in `test_bootstrap.py` did not catch
this because it asserts `predict.approved.v1` lands on the
**bus**, not that any consumer received it. The bus lets us
publish into a void.

**Fix.** Extend `build_agents()` to also construct
`CacheAgent()` and `TelemetryAgent.from_config(start_http=False)`
and append them to the agent list before
`_enforce_single_instance` is called. Neither has a
single-instance constraint (each owns process-local state in v1;
hot-spare deployment will need Postgres-backed state in Phase 9
either way). Add a regression test that drives a
`predict.request` end-to-end and asserts the `CacheAgent`
backend has the expected `prediction:` key after the runners
quiesce.

**Why not also storage / processor / categorizer?**
Those agents subscribe to scrape-side topics (`scrape.classified`,
`match.normalized`) that are produced by `datasource/` agents
(Phase 4.1-4.4), not by the predictor pipeline. Wiring them
into the bootstrap is correct but is a separate diff (it
needs the Phase 4 datasource bootstrap, which still lives in
`ai/swarm/agents/scraper.py` and `xops/swarm_backtest.py`
helpers). That diff is the natural pre-Phase 9 step and is
out of scope here. The audit notes it as future work
(see §3 below).

**Diff:** ~15 LoC bootstrap + ~30 LoC test. **Landed.**

---

### F2-3 — ROADMAP §4.5 cache subscription checkbox is stale · **Cosmetic**

**Shape.** ROADMAP §4.5 still shows:

```
- [ ] Subscribes to predict.approved.v1 (NOT predict.final ...)
```

The actual subscription is in
[`ai/swarm/agents/cache.py`](../../ai/swarm/agents/cache.py)
(`subscribes = (MATCH_STORED, PREDICT_APPROVED)`), the boundary
test in `test_boundary_discipline.py` enforces the contract,
and §6 cross-phase notes reference it as the canonical wiring.
Same kind of "code shipped, ROADMAP not flipped" drift the
2026-04-28 audit pass found in §3.5.

**Fix.** Flip to `[x]` with a one-line note pointing at this
report and the boundary test. **Landed.**

---

### F2-4 — ROADMAP §4.7 reactor checkboxes contradict §5.5 · **Cosmetic**

**Shape.** ROADMAP §4.7 has two `[ ]` items:

* `Trainer reactor with debounce window, qualifying-event filter…`
* `Live-predictor / NLP / market reactors per §15.1.`

ROADMAP §5.5 has the **same** items as `[x]` and references
the live implementations
([`ai/swarm/agents/reactor.py`](../../ai/swarm/agents/reactor.py)
`TrainerReactor`, `LivePredictorReactor`). The §4.7 boxes were
inherited from the design phase and never flipped when §5.5
landed.

**Fix.** Flip the two §4.7 boxes to `[x]` with a back-reference
to §5.5 and `reactor.py`. **Landed.**

---

## 3. Items deliberately deferred

* **Bus stream compaction.** `InMemoryBus._streams` deques are
  append-only — acked entries stay resident. For long-running
  test processes this leaks memory. Out of scope: production
  uses Redis Streams (which compacts via `MAXLEN`); a fix
  here would change `read()` offset semantics and require
  surgery in the consumer-group bookkeeping. Defer until a
  long-running in-memory profiling case justifies it.
* **Datasource bootstrap.** `build_agents()` should eventually
  also wire scraper / processor / storage / categorizer when
  the Phase R1 split (`datasource/` package) lands. Today
  those agents exist under `ai/swarm/agents/` but their inputs
  (`scrape.classified`, `match.normalized`) come from outside
  the predictor pipeline. Add them when Phase 4.1-4.4 gets a
  proper bootstrap module of its own — Pivot v3 Phase R1 is
  the natural home.
* **`_fuse_score_grids` numpy-isation.** Triple-nested Python
  loop is currently fine at default grid sizes; revisit only
  when Phase 13a expands grid markets (already noted in the
  Phase 5 deep review).
* **Per-replica live config reload** (first-pass F-8 partial).
  Doc-only fix shipped in first pass; runtime reload deferred
  to Phase 9 ops dashboard.

---

## 4. Acceptance criteria after this pass

The following must all hold green simultaneously:

1. `make test.ai` passes (target: ≥ 915 passed after the new
   regression tests; baseline 913).
2. `DriftAgent` settles outcomes in O(1) regardless of
   `cfg.drift_max_pending` (regression test guards).
3. `build_swarm()` end-to-end smoke test asserts the
   `CacheAgent` backend has the approved prediction after the
   runners quiesce (not just that the bus carries it).
4. ROADMAP §4.5 + §4.7 checkboxes match shipped code.
5. `make track.add` row + `make version.bump swarm/docs` for
   this pass.

---

## 5. Self-review notes

* I did not run a multi-process load test against Redis. F2-1's
  perf claim rests on Python dict-iteration cost and the
  reachable depth of `_pending` under realistic load. The
  regression test guards the **shape** of the lookup, not the
  micro-benchmark — that is the right level for a unit test.
* F2-2 is "alignment" not "perf" because the swarm is correct
  on the bus, just not at the API edge. Severity is Major
  because the user-visible blast radius is the same as the
  first-pass `F-1` (no API can serve predictions); the fix
  is small and self-contained.
* I did **not** widen the single-instance set to include
  `cache.v1` or `telemetry.v1`. Cache replication is
  semantically valid (each instance maintains its own LRU; the
  API only reads from the one in front of it). Telemetry
  replication is harmless (each instance counts what it sees).
  Adding either to the single-instance frozenset would prevent
  legitimate hot-spare deployment without a real benefit.
* Severity calibration may still be wrong for F2-2 — it is
  arguably a *Blocker* because the user-visible flow is broken.
  I left it Major because (a) production uses the bootstrap
  *and* a separate API container that already injects its own
  cache backend in Phase 9, so the bug only bites the
  swarm-internal pipeline tests today; (b) the fix is in the
  same diff. Reviewers may push back.
