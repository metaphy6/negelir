# Phase 11.33 — Adapter (LoRA / IA³) hot-load & per-request swap

> Extracted from `docs/planning/ROADMAP.md` §11.33
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.33 Adapter (LoRA / IA³) hot-load & per-request swap

> **Why this exists.** Multi-tenant serving from one base model uses
> tiny per-tenant adapters that swap per request. The §11.15 hot-swap
> contract assumes a monolithic bundle; without an adapter contract,
> every tenant pays a full bundle reload.

- [ ] **Bundle-pair contract.** A bundle manifest may declare `base_bundle_sha256` (this *is* the base) **or** `requires_base_sha256` (this is an adapter overlay). Adapters declare `adapter_kind ∈ {lora, ia3, dora}`, `target_modules`, `rank`, and a `merge_cost_ms` measured at build time. Predictor bundles cannot be adapters (Phase 5 parity contract is on the base only).
- [ ] **Adapter cache.** Adapters are pulled and cached under `cfg.compute_adapter_cache_dir` keyed by `(base_sha256, adapter_sha256, dtype, host_compute_fingerprint)`; LRU with `cfg.compute_adapter_cache_max_count` (default 64). Pull goes through the §11.15 verified-signature path.
- [ ] **Per-request swap.** The router resolves `(base_sha256, adapter_sha256?)` from the request (tenant claim → adapter lookup, default `None`); the engine swaps adapter weights into the resident base within `cfg.compute_adapter_swap_p99_ms` (default 5 ms on dGPU). Swap is atomic per sequence (no half-adapter decode).
- [ ] **Concurrent multi-adapter decode.** When the engine supports it (vLLM-style), N requests with N different adapters share one in-flight batch; per-request adapter selection is a kernel-side gather. Bounded by `cfg.compute_concurrent_adapters_max` (default 16). Falls back to serialised adapter swap when the engine lacks the kernel.
- [ ] **Compute-provenance carries both SHAs.** `prediction.v1.compute_provenance.{base_sha256, adapter_sha256?}` so replay reproduces the exact merged weights.
- [ ] **Adapter eligibility (Phase 20 hook, dormant).** A tenant is allowed to use an adapter only if `(tenant_id, adapter_sha256)` is in the §11.17 allow-list; while `tenant_quota_enabled=false` this logs would-deny but never blocks.
