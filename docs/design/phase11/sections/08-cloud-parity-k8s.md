# Phase 11.8 — Cloud parity & K8s

> Extracted from `docs/planning/ROADMAP.md` §11.8
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.8 Cloud parity & K8s

- [ ] Same image runs on **Azure NC-series** (NVIDIA), **AKS without GPU** (CPU-only), **GKE A2** (NVIDIA), **EKS Inf2** (Inferentia, opt-in extras image only — not primary), **bare-metal VPS** (CPU baseline).
- [ ] Phase 14 K8s manifests carry `nodeSelector: negelir.io/accel=<cuda|rocm|npu|cpu>` + matching tolerations; the device probe in §11.1 emits a self-reported label (`negelir.io/accel.detected`) so a Phase 8 admission webhook can refuse mis-scheduled pods.
- [ ] **Multi-GPU host.** Arbiter uses the §11.2 least-loaded-fit placement. MIG slicing is **not** in scope for Phase 11 (deferred to Phase 14, but the probe must report `mig_mode` so Phase 14 can plan).
- [ ] **GPU virtualization detection.** vGPU / passthrough / MIG / MPS modes are reported in `virt_mode`; auto-tuning (e.g. disabling persistence mode under vGPU where it's a no-op) follows.
