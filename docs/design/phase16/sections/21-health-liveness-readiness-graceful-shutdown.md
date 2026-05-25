# Phase 16.21 — Health, liveness, readiness & graceful shutdown (NEW; ledger #15)

> Extracted from `docs/planning/ROADMAP.md` §16.21
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.21 Health, liveness, readiness & graceful shutdown (NEW; ledger #15)

- [ ] **Liveness probe** `GET /healthz/live` — returns 200 unless the writer event loop has been blocked > `cfg.emitter_liveness_block_threshold_ms` (default 5000) or fsync queue depth > `cfg.emitter_fsync_queue_max_depth` (default 1000).
- [ ] **Readiness probe** `GET /healthz/ready` — returns 200 only when (a) writer leases acquired for all assigned `(plane, source)` partitions, (b) registry SHA matches `GET /schemas`, (c) disk usage < `cfg.emitter_disk_usage_block_pct`, (d) pointer-stream publisher connected. Returns 503 with structured body otherwise (`{checks: {...}, failed: [...]}`).
- [ ] **Graceful shutdown.** SIGTERM → flip `/healthz/ready` to 503 immediately → drain in-flight writes within `cfg.emitter_shutdown_grace_s` (default 25 s, K8s default termination grace 30 s) → release leases → exit 0. Force-kill at grace+5s if drain stalls; `kill -9` test (already in §16.18) covers the worst case.
- [ ] **Compute governor binding** (Phase 11 §11.40). Emitter claims `cfg.emitter_thread_budget` (default 2) via the §11.3 governor; over-spawn is refused.
- [ ] Proof tests: `test_liveness_blocks_event_loop.py`, `test_readiness_503_on_disk_full.py`, `test_readiness_503_on_lease_loss.py`, `test_graceful_shutdown_within_grace.py`, `test_sigterm_flips_ready_immediately.py`, `test_emitter_thread_budget_respected.py` (already in Phase 11 §11.40 but counted here too).
