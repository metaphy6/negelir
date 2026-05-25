# Phase 11.21 — Inference engine matrix & per-engine tuning

> Extracted from `docs/planning/ROADMAP.md` §11.21
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.21 Inference engine matrix & per-engine tuning

> **Why this exists.** "Run the model on CUDA" is not a backend choice
> — it's a family. PyTorch eager, `torch.compile`/Inductor, ONNX
> Runtime, TensorRT (and TensorRT-LLM), vLLM, SGLang, llama.cpp,
> ExecuTorch, OpenVINO all coexist and have **wildly** different
> determinism, cold-start, throughput, and bug profiles. Without an
> explicit per-engine contract, the project will silently drift to
> "whatever the agent author imported last".

- [ ] **Engine registry.** `xops/compute/engines.json` enumerates every supported engine: `{name, vendor, runtime_min, runtime_max, supports_dtypes, supports_dynamic_shape, supports_cuda_graphs, supports_paged_attention, deterministic_when, default_for: [workload_class…], known_quirks_ref}`. The router (§11.13) selects an engine alongside the device; selection is a pair `(device, engine)` and is logged on `route.decision.v1`.
- [ ] **Engine cache.** TensorRT engines, ONNX-Runtime session caches, and `torch.compile` Inductor artifacts share the §11.7 `compute_artifact_cache_dir` keyed by `(bundle_sha256, engine_name, engine_version, host_compute_fingerprint, dtype, allocator_conf, deterministic_flags)`. Any change to *any* key component recompiles; the engine SHA is recorded in `compute_provenance.engine_sha`.
- [ ] **Engine refresh.** Engine upgrades are choreographed exactly like driver upgrades (§11.18 — drain → upgrade → re-bench → undrain). The cache is **not** invalidated wholesale on engine upgrade; entries are validated lazily on first use and recompiled on key mismatch (avoids cold-start storms after a routine upgrade).
- [ ] **Per-engine determinism contract.** Each engine declares `deterministic_when={fp32+seed+no_tf32, …}` in the registry. Predictors may only use engines whose `deterministic_when` covers their parity tolerance (§11.4); the lint rule `xops/lint/predictor_engine_determinism.py` enforces it at PR time.
- [ ] **Quirk binding.** Every engine entry carries a `known_quirks_ref` pointer into `xops/compute/quirks.json` (§11.16); the lint refuses an engine entry without at least an empty quirks bucket so drift is visible.
