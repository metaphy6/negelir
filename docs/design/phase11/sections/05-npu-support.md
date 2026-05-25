# Phase 11.5 — NPU support (Intel OpenVINO + AMD XDNA + Apple MPS)

> Extracted from `docs/planning/ROADMAP.md` §11.5
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.5 NPU support (Intel OpenVINO + AMD XDNA + Apple MPS)

- [ ] **Intel NPU (Meteor / Lunar / Arrow Lake).** OpenVINO IR conversion pipeline (`xops/compute/openvino_convert.py`) for `categorizer.v1` and `sec.input.v1` (both ≤ 60 MB on disk). Conversion runs at image build, the IR file is shipped inside the image, and a SHA-256 of the IR + the calibration dataset + the OpenVINO version is recorded in the bundle manifest.
- [ ] **OpenVINO compiled-blob cache.** The first inference compiles the IR for the specific NPU/GPU; the resulting blob is cached at `cfg.openvino_blob_cache_dir` (tmpfs in dev, persistent volume in prod) keyed by `(ir_sha256, openvino_version, device_uuid, host_compute_fingerprint)`. Cuts cold start by 5–10× on NPU. Cache misses are counted (`negelir_compiled_blob_cache_misses_total`).
- [ ] **AMD XDNA (Ryzen AI 300/PRO).** Stretch goal behind `cfg.npu_vendor=amd`. Pinned to a specific XRT release (documented in `COMPUTE_DEVICES.md`); not on any agent's critical path.
- [ ] **Apple MPS (dev-loop only).** `cfg.allow_mps=true` (default `false`) enables Mac dev hosts; never selected by `auto` in CI/prod. A nightly **dev-host parity test** (run by maintainers, results posted to `docs/reports/bench/mps-<date>.md`) catches MPS divergence early; failure does not block CI. **MPS gotchas** (documented in `COMPUTE_DEVICES.md`): no fp64 (predictors that use fp64 anywhere fall back to CPU); a known set of ops fall back silently — the wrapper sets `PYTORCH_ENABLE_MPS_FALLBACK=1` **and** asserts `MPSFallbackCount == 0` for predictor parity runs.
- [ ] **OpenVINO async-infer queue.** NPU/iGPU inference uses `AsyncInferQueue` with depth `cfg.openvino_async_queue_depth` (default 4 per device); the agent batcher (§11.9) feeds it. Queue depth is exported as a metric so the operator can spot saturation.
- [ ] **Graceful absence.** No NPU? `device.json` records `npu: unavailable`, the workload routes via §11.13 to CPU; **no `if has_npu` business-logic branches** — only the backend module differs.
