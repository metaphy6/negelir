# Phase 11.37 — Multi-arch image dispatch (`linux/amd64` + `linux/arm64`)

> Extracted from `docs/planning/ROADMAP.md` §11.37
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.37 Multi-arch image dispatch (`linux/amd64` + `linux/arm64`)

- [ ] **Manifest-list build.** `make image.compute` produces a manifest list for `ai-cpu`, `ai-gpu` (amd64 only by design — no consumer ARM CUDA), `ai-npu` (amd64 only); puller resolves to the correct arch automatically.
- [ ] **Refuse arch mismatch fast.** Container start runs a 1-line arch check (`uname -m` vs `cfg.expected_arch`); mismatch exits with `device.alert.v1{kind=arch_mismatch, expected, observed, severity=critical}` *before* importing any compiled extension (which is where mismatches usually segfault).
- [ ] **Per-arch wheel pinning.** `requirements.txt` is split into `requirements.<arch>.txt` only where pin sets diverge (e.g. `torch+cu124` is amd64-only); the runtime-matrix lint (§11.1) cross-checks per arch.
- [ ] **CI matrix.** Every PR runs CPU lint + smoke on both arches via QEMU-emulated arm64 (slow) **or** a real arm64 self-hosted runner when available; the §11.4 parity matrix runs on real arm64 nightly (per §11.24).
