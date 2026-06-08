# Phase 11.14 — LLM-class serving primitives

> Extracted from `docs/planning/ROADMAP.md` §11.14
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.14 LLM-class serving primitives

- [x] **Dynamic-shape & CUDA Graphs bucketing.** LLM prefill / decode is captured as a small set of CUDA Graphs keyed on **bucketed** sequence length (powers-of-two up to a cap, plus a max-length bucket). Inputs are right-padded to the next bucket; bucket selection is logged and the bucket cache size is capped (`cfg.cuda_graph_bucket_max`) to avoid graph-cache explosion under variable-length traffic.
- [x] **KV-cache management.** Paged-attention KV cache with `cfg.kv_cache_pages_per_seq_max` and a global `cfg.kv_cache_total_mb` cap; eviction is LRU at the session level with a **never-evict-mid-decode** invariant. Cache stats (`hit_pct`, `paged_out_total`, `eviction_total`) are exported.
- [x] **Speculative decoding hook.** Architecture supports an optional draft-model (≤ 100 M params) on CPU with the target model on GPU; **off by default** until measured to help. The hook is a `Backend.generate_with_draft(target, draft, request)` interface so the loop is testable without an LLM in CI.
- [x] **Streaming output.** LLM agents emit tokens via Redis stream (`negelir:llm:<agent>:<request_id>`) so the Phase 9 API can SSE-stream to the client without buffering whole responses on the GPU process.
- [x] **Sampler determinism.** Even with `temperature > 0`, `(temperature, top_p, top_k, seed)` is recorded on every emitted answer; replaying the same tuple + same input + same `compute_provenance` reproduces the same tokens. Tested.
- [x] **Per-request cancellation.** Client disconnect (Phase 9 API) propagates a cancel that breaks out of the decode loop within `cfg.llm_cancel_grace_ms`. GPU time isn't burned on dead clients.
