# Phase 12.7 — Resource exhaustion & performance-under-stress

> Binding per-section detail for Phase 12 §12.7. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A1 (flat coverage ≠ resilience), A7 (chaos = liveness).
> **Depends on:** §12.4. This is the **performance / efficiency**
> pillar the original stub omitted entirely.

### 12.7 Exhaust every bounded resource on purpose

Every resource the system bounds by config must be driven **past** its
bound under test, to prove the bound is enforced and the over-limit path
is graceful (refuse / shed / degrade), never a crash, OOM-kill, or
unbounded growth.

### 12.7.1 Exhaustion scenarios (binding)

- [ ] **`chaos.cpu-saturate`** — pin all vCPUs with adversarial input
      (Symspell-pathological for NLP per Phase 10 §10.28.11, deep PMF
      grids for predictor); assert the per-request CPU budget gate fires
      (`request_budget_exhausted`), the request degrades to the
      template/cheap path, and **no** request returns a 5xx where
      graceful degradation is specified.
- [ ] **`chaos.rss-pressure`** — drive RSS toward the pod budget
      (`nlp_per_request_rss_budget_mb`, `nlp_pod_rss_max_mb`); assert the
      `RLIMIT_AS` guard refuses the over-budget request, the lexicon
      rebuild back-pressure (Phase 10 §10.28.12) holds, and the pod does
      not get OOM-killed.
- [ ] **`chaos.fd-exhaust`** — exhaust file descriptors / sockets;
      assert pools are bounded, new work sheds with a structured
      `service_unavailable`, and existing in-flight work completes.
- [ ] **`chaos.conn-pool-starve`** — set PG `max_connections` low
      (extends Phase 8 P12-8-O); assert acquire-timeout → structured
      refusal, no partial write, clean retry next tick.
- [ ] **`chaos.disk-pressure`** — fill the data volume toward the cap
      (extends Phase 8 P12-8-D / P12-8-Q); assert backup/spool/audit
      refuse-to-write before corruption, emit a pressure alert, and
      recover when space frees.
- [ ] **`chaos.queue-depth-flood`** — push bus/intake queue depth past
      the backpressure threshold; assert humanizer auto-disables (Phase
      10 §10.12), cache TTL doubles, and the adaptive shed (Phase 9
      §9.17.9) engages — then lifts cleanly when depth falls.
- [ ] **`chaos.cache-stampede`** — N concurrent misses on one hot key;
      assert singleflight collapses them to one upstream RPC (Phase 9
      §9.17.6, Phase 10 §10.12) — no thundering herd.

### 12.7.2 Latency-budget regression gates (the perf pillar)

- [ ] **Per-route budget table is a gate, not a doc.** The Phase 9
      §9.17.5 p50/p95/p99 table and the Phase 10 §10.31.12 per-intent
      SLO classes become **CI-enforced** under load: `make load.api` and
      `make load.nlp` drive RPS and fail if any percentile exceeds its
      budget × `cfg.load_regression_tolerance` (default 1.10).
- [ ] **Noise-aware comparison.** Like Phase 11 §11.9's bench gate, the
      load gate compares mean ± stdev against a baseline report with a
      hard-floor fallback, so a noisy runner does not produce false
      regressions — but a real regression is caught.
- [ ] **Under-fault budgets.** A load run **with** a §12.6 fault active
      (e.g. 500 ms added latency) asserts the degraded budget (the
      documented degraded SLO), proving the system stays inside a
      *defined* envelope even while impaired.
- [ ] **Zero-alloc / GC pause hot paths.** The Phase 9 §9.17.2 zero-alloc
      and §9.17.11 GC-pause proofs are re-run under sustained load (not
      just micro-bench) so an allocation regression surfaces under
      realistic pressure.

### 12.7.3 Efficiency assertions (cost of serving)

- [ ] **Humanizer token ceiling under flood.** Drive QA traffic and
      assert per-tenant + per-pod humanizer token ceilings (Phase 10
      §10.23.8) hold, degrading to template under budget — a runaway
      cost is a chaos finding, not a billing surprise.
- [ ] **Fast-path retention.** Under a mixed clean/dirty input flood,
      assert the NLP normalize fast-path (Phase 10 §10.34.2) still serves
      ~80 % of traffic on the zero-alloc path — a regression that pushes
      clean input onto the slow path is a perf finding.

### 12.7.4 Make targets

- [ ] `make chaos.cpu-saturate`, `make chaos.rss-pressure`,
      `make chaos.fd-exhaust`, `make chaos.conn-pool-starve`,
      `make chaos.disk-pressure`, `make chaos.queue-depth-flood`,
      `make chaos.cache-stampede`.
- [ ] `make load.api`, `make load.nlp`, `make load.predictor` — k6 /
      Locust drivers under `xops/bench/` (reuse the existing
      `xops/bench/api_bench.js` k6 harness), dispatched via
      `xops/makefile/bench.py`; nightly lane, baseline-compared.
