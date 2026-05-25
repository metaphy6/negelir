# Phase 11.28 — OpenTelemetry tracing, on-demand profiling & flamegraph hook

> Extracted from `docs/planning/ROADMAP.md` §11.28
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.28 OpenTelemetry tracing, on-demand profiling & flamegraph hook

- [ ] **OTel spans.** Every inference path emits a span `compute.inference` with attributes `{agent, workload_class, device, gpu_uuid, engine, bundle_sha256, batch_size, queue_wait_ms, prefill_ms, decode_ms?, kv_cache_pages?, route.decision_id}`; child spans for `arbiter.lease`, `bundle.load`, `engine.compile`, `tokenize`, `forward`, `sample` (LLMs). Trace exporter is the Phase 12 collector.
- [ ] **Tail-latency root-cause hook.** When a request's latency exceeds `cfg.compute_tail_capture_threshold_p`, a token-bucketed (`cfg.compute_tail_capture_per_min`) capture fires: NVML snapshot, arbiter audit slice, and an opt-in `nsys`/`pyspy` capture (`cfg.compute_profiling_enabled`). Captures are scrubbed of inputs/outputs (security §11.11) and uploaded to `cfg.compute_profiling_sink`.
- [ ] **Per-agent profile bundles.** Each agent ships a default OTel resource block (`service.name, service.version, ai.bundle.sha`) so a tail-latency search across the cluster collapses to a few queries.
- [ ] **No tracing in CPU-only critical paths' hot loop.** The Phase 9 API and Phase 16 emitter still emit their own spans (their own contracts), but compute-side tracing is gated `cfg.compute_otel_enabled` to avoid leaking compute SDK symbols into CPU-only images.
