# Phase 11.24 — ARM / Graviton / Ampere Altra / Apple Silicon CPU baseline

> Extracted from `docs/planning/ROADMAP.md` §11.24
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.24 ARM / Graviton / Ampere Altra / Apple Silicon CPU baseline

- [ ] **aarch64 CI lane.** A second CI lane builds and tests `ai-cpu:<digest>` for `linux/arm64` (Graviton 3/4, Ampere Altra, Apple Silicon under Rosetta-free Docker). The §11.4 parity matrix runs on aarch64 and the published tolerances must hold; a wider tolerance is **not** acceptable as a workaround.
- [ ] **NEON / SVE / SVE2 / BF16 gating.** §11.1 CPU fingerprint enumerates `neon, sve, sve2, bf16` (Neoverse V1+); §11.3 governor selects the matching wheel. Falling through to a baseline wheel emits `device.alert.v1{kind=arm_simd_baseline}` so ops sees why latency is off.
- [ ] **llama.cpp ARM backend.** CPU LLM path on aarch64 uses the ARM-optimised quantization kernels (`q4_0_4_4`, `q4_0_4_8`, `q4_0_8_8`); choice is recorded in the bundle audit so a parity mismatch with x86_64 is traceable to the kernel, not the model.
- [ ] **Cross-arch bundle determinism.** Predictor `cpu↔cpu` parity tests (§11.4) run with one host x86_64 and one host aarch64; the published tolerance applies across both.
