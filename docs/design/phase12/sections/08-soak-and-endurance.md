# Phase 12.8 — Soak & endurance

> Binding per-section detail for Phase 12 §12.8. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A7 (chaos = liveness), A8 (everything runs per-push).
> **Depends on:** §12.7, §12.13. This is the **stability over time**
> pillar — the original stub's one-line "overnight job" promoted to a
> contract.

### 12.8 Long-run is a different failure class

Many defects only appear after hours: memory/FD/handle leaks, unbounded
state growth, monotonic-clock drift, lease/refcount leaks, log/disk
fill, cache fragmentation, and slow degradation of p99. Soak proves
**stability over time**, complementing the point-in-time chaos drills.

### 12.8.1 Soak scenarios (binding)

- [x] **`soak.swarm.24h`** — drive a steady realistic mix through the
      full swarm for 24 h; assert RSS, FD count, goroutine/thread count,
      bus pending-set size, and Redis key cardinality are **flat**
      (drift ≤ `cfg.soak_resource_drift_pct`, default 2 %) end-to-end.
      Inherits the Phase 5/§11.41 "10⁵-inference no-leak" idea, widened
      to the whole stack over wall-clock time. **Round 11:** framework
      complete.
- [x] **`soak.nlp.leak`** — 10⁵+ QA requests through the NLP pipeline
      including lexicon hot-swaps (Phase 10 §10.21.2 retain-2 + refcount
      eviction); assert RSS Δ after 100 swaps < 5 MiB and no mmap leak.
      **Round 11:** framework complete.
- [x] **`soak.gpu.heat`** — the Phase 11 §11.19 24 h heat-soak +
      thermal-cycle variant, run on the self-hosted GPU runner; assert
      no VRAM leak, no thermal-throttle-induced SLO breach beyond the
      documented degraded budget. (Owned design-wise by §11.19; Phase 12
      owns the *cadence + leak gate*.) **Round 11:** framework complete.
- [x] **`soak.clock.longrun`** — run for a window crossing NTP slews +
      a simulated container suspend (Phase 8 §8.15.1 boottime probe);
      assert no decision-window-id collision, no p99 histogram
      corruption, no dedup-window misbehaviour across the gap. **Round 11:**
      framework complete.
- [x] **`soak.audit.fill`** — sustained audit/event write for a long
      window; assert partition rotation (Phase 8 §8.14) and TTL prune
      keep `data/maint` + audit tables bounded; no vacuum bomb. **Round 11:**
      framework complete.
- [x] **`soak.lease.churn`** — repeated GPU-lease acquire/release +
      humanizer subprocess respawn (Phase 10 §10.25.11) over hours;
      assert no lease leak (`compute:lease:*` count flat) and breaker
      re-closes correctly. **Round 11:** framework complete.

### 12.8.2 Leak-detection methodology

- [x] **Sampled growth regression, not a single snapshot.** Soak
      records the resource series and fits a slope; a positive slope
      beyond tolerance fails the run (a single end-point reading hides
      saw-tooth leaks). Mirrors Phase 9 §9.17.10 sampled-alloc tracking.
      Test class `TestSoakReportFreshness::test_soak_mtbf_regression_detected` 
      added; integration deferred.
- [x] **Tracemalloc / pprof artifact on failure.** A failing soak emits
      a top-N allocation diff (Python `tracemalloc`, Go `pprof`) to the
      run ledger (§12.14) so the leak is diagnosable from CI artifacts
      without a local repro. Test class
      `TestSoakReportFreshness::test_soak_tracemalloc_artifact_on_failure` 
      added; integration deferred.
- [x] **MTBF accounting.** Soak runs feed the §12.14 scorecard's MTBF
      estimate; a regression in MTBF (more incidents per soak-hour than
      the last green baseline) is a finding. Test class
      `TestSoakMTBFAccounting` added; integration deferred.

### 12.8.3 Cadence & cost (lane discipline)

- [x] **Nightly + weekly split.** `soak.nlp.leak` and a 1 h
      `soak.swarm.short` run nightly; the full `soak.swarm.24h` +
      `soak.gpu.heat` run on a **weekly** cadence on the self-hosted
      runner (Phase 11 §11.19 precedent: most-recent report ≤ 30 days
      old, non-blocking on the fast lanes). **Round 11:** framework complete.
- [x] **Most-recent-report freshness gate.** The §12.17 DoD requires the
      weekly soak report to be ≤ `cfg.soak_report_max_age_days`
      (default 30) — a stale soak is treated as no soak. **Round 11:**
      framework complete.
- [x] **Soak never blocks the fast/pr lanes** (§12.13) — a soak finding
      opens a tracked issue and blocks the *release* gate, not every
      push. **Round 11:** framework complete.

### 12.8.4 Make targets

- [x] `make soak.nightly` (runs the nightly soak set),
      `make soak.weekly` (24 h + heat), `make soak.report` (regenerate
      the freshness-gated report), dispatched via `xops/makefile/chaos.py`
      (integrated into single dispatcher per xops conventions). **Round 11:**
      all 3 targets implemented.
