# Phase 11.7 — Image strategy (cpu / gpu / npu flavors) + compiled-artifact cache

> Extracted from `docs/planning/ROADMAP.md` §11.7
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.7 Image strategy (cpu / gpu / npu flavors) + compiled-artifact cache

- [x] **Three image flavors** built from a common `ai-base` per `COMPUTE_DEVICES.md` §Image-strategy: `ai-cpu:<digest>` (default in prod, target ≤ 800 MB compressed), `ai-gpu:<digest>` (CUDA 12.4 + cuDNN 9, target ≤ 4 GB), `ai-npu:<digest>` (OpenVINO 2025 + Intel GPU/NPU drivers, target ≤ 2 GB). Selection: `AI_IMAGE_FLAVOR=cpu|gpu|npu` (compose substitutes the tag). ROCm uses the `ai-gpu` tag with `--build-arg ACCEL=rocm` for now (separate flavor lands when there's a real ROCm host in CI). Image size budgets are enforced by a CI gate.
- [x] **Reproducible builds.** Every image is `docker buildx build --provenance=true --sbom=true`; the wheels are pinned (CUDA wheel index URL is pinned, OpenVINO wheel version is pinned). The image SHA, wheel digests, and chosen device pin are recorded in the build manifest under `xops/versioning/build-manifest.json`. Images are **signed with cosign** and verified at deploy time (Phase 14 binding). The SBOM is **re-verified at container start** (`xops/compute/verify_sbom.py`): the running image's layer digests must match the build-manifest SBOM, otherwise the container exits with `sec.alert.v1{kind=sbom_mismatch, severity=critical}` rather than serving with an undocumented runtime.
- [x] **Compiled-artifact cache.** `torch.compile` inductor cache, OpenVINO compiled blobs (§11.5), and TensorRT engines (when enabled) all live under `cfg.compute_artifact_cache_dir` keyed by `host_compute_fingerprint`. Cache survives container restarts via a named volume. Eviction is LRU with `cfg.compute_artifact_cache_max_mb` cap. Cache hit/miss metrics published.
- [x] **No host installs.** Per Rule 2 — no `pip install` on the dev host; no host CUDA install in CI. The CI matrix runs CPU on every PR and GPU/NPU on a nightly self-hosted runner only.
- [x] **Compose runtime.** `docker-compose.yml` uses `runtime: nvidia` + `deploy.resources.reservations.devices` for CUDA hosts; the same compose file works on a CPU-only host because the GPU resources block is gated behind `${NEGELIR_GPU_ENABLED:-false}` via a profile. A compose **healthcheck** runs the device probe and refuses the container as unhealthy if `device != requested && requested != auto`.
- [x] **Container hardening.** GPU containers run with `--security-opt=no-new-privileges`, `--cap-drop=ALL`, `--read-only` root FS (writable tmpfs for `/var/run/negelir`), and a non-root UID. Disallowed in prod: `--privileged`.
