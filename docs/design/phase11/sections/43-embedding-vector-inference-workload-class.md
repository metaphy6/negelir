# Phase 11.43 — Embedding & vector-inference workload class (Phase 21 enrichment hook)

> Extracted from `docs/planning/ROADMAP.md` §11.43
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.43 Embedding & vector-inference workload class (Phase 21 enrichment hook)

> **Why this exists.** Phase 21 enrichment (player markets, transfer
> graph, weather context) needs embedding inference at scale —
> different shape (large dense batches, GEMM-bound, no KV-cache),
> different SLO (offline rebuild vs. online query), different cost
> profile. Treating embeddings as `predictor_micro` mis-batches them
> with PMF calls and torpedoes both latencies. The contract lands now
> so Phase 21 plugs in without re-architecting the router.

- [ ] **Two new workload classes.** `embedding_online` (per-query, ≤ 50 ms p95, batch ≤ `cfg.embedding_online_batch_max`, default 32) and `embedding_offline` (rebuild jobs, throughput-optimised, batch up to `cfg.embedding_offline_batch_max`, default 1024). Both declared in `xops/compute/workload_matrix.json` with their own preferred-device list (typically `[gpu, npu, cpu]` for online; `[gpu, cpu]` for offline) and their own `fallback_chain` (§11.31).
- [ ] **Dedicated batcher.** The §11.9 batcher is parameterised per workload class (it already is); embedding classes get aggressive batch-wait (`cfg.embedding_online_batch_max_wait_ms` default 8 ms; `cfg.embedding_offline_batch_max_wait_ms` default 200 ms) since coalescing dwarfs first-token latency for dense matmul.
- [ ] **No KV-cache.** Embedding agents never touch the §11.14 / §11.22 paged KV cache; their bundle manifest declares `kv_cache_required=false` and the loader refuses to allocate any. This frees significant VRAM headroom on shared GPUs and is asserted by `proof_embedding_no_kv_alloc`.
- [ ] **Provenance for vector outputs.** A vector embedding emitted by the system carries the same `compute_provenance` block (§11.4) plus `output_dim` and `normalisation` (`l2 | none`); replay (§11.15) for embeddings asserts cosine similarity within `cfg.embedding_replay_cos_min` (default 0.9999) — bit-equality is not required since downstream cosine search is the contract, not bit-equality.
- [ ] **Offline-rebuild scheduling.** `embedding_offline` jobs are `priority=batch` to the §11.2 arbiter and consult §11.23 carbon / cost windows; they never preempt `realtime` and are the first to be `shed_batch`-brownout'd.
- [ ] **Vector-store handoff.** The emitted embedding's payload schema is the Phase 16 emitter's responsibility; this sub-phase only commits the compute-side workload class + provenance. The Phase 21 design doc binds the downstream vector index format.
