# Phase 11.22 — Continuous batching, prefix caching & disaggregated prefill/decode (LLM-class)

> Extracted from `docs/planning/ROADMAP.md` §11.22
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.22 Continuous batching, prefix caching & disaggregated prefill/decode (LLM-class)

> **Why this exists.** Static batching (§11.9) is fine for predictors and
> sec.input. LLM-class agents (humanizer, coder, sec.input fallback)
> waste 60–80 % of GPU time under static batching when prefill lengths
> vary. Continuous batching + prefix caching is the difference between
> "1 humanizer per dGPU" and "8 humanizers per dGPU" without changing
> the model.

- [ ] **Continuous-batching scheduler.** LLM agents use a vLLM-class scheduler (own implementation behind a `Backend` interface, or pinned vLLM/SGLang version per the §11.21 registry). New requests join an in-flight batch at any decode step; bounded by `cfg.llm_continuous_batch_max_seqs` and `cfg.llm_continuous_batch_max_tokens`.
- [ ] **Prefix-cache (radix tree).** Common prompt prefixes (system prompt, persona, RAG header) hit a shared KV-cache; metric `negelir_llm_prefix_cache_hit_pct{agent}` is exported and the §11.9 cold-start budget is **tightened** when prefix-cache hit-rate is sustained ≥ `cfg.llm_prefix_cache_warm_threshold` (default 60 %). Prefix-cache invalidation is keyed by `bundle_sha256` so a hot-swap (§11.15) cannot serve mixed-prefix output.
- [ ] **Chunked prefill.** Long prompts are chunked at `cfg.llm_chunked_prefill_size` so a single 8 k-token prefill cannot block decoding of small-batch peers; tail latency p99 stays bounded under bursty long-prompt arrival.
- [ ] **Disaggregated prefill/decode (deferred contract).** The router exposes a `(prefill_device, decode_device)` decision shape so a future deployment can run prefill on dGPU and decode on iGPU/NPU. Off by default (`cfg.llm_disagg_enabled=false`); the **interface** lands here so Phase 14 can wire it without re-architecture.
- [ ] **Fairness inside the LLM batch.** Per-tenant / per-agent weights from §11.17 propagate into the continuous-batch scheduler so one chatty caller cannot monopolise decode slots.
- [ ] **Cancellation under continuous batching.** A cancelled request (Phase 9 client disconnect, §11.14) is removed from the in-flight batch within `cfg.llm_cancel_grace_ms` **without** flushing peers' KV-cache; tested.
