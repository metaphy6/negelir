# Phase 11.11 — Security & supply chain

> Extracted from `docs/planning/ROADMAP.md` §11.11
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.11 Security & supply chain

- [x] **Model file integrity.** Every model bundle (`.safetensors`, `.gguf`, OpenVINO IR) carries a SHA-256 in its manifest **and a cosign signature**; the loader verifies both before mapping into device memory. Mismatch → refuse to load + `sec.alert.v1{kind=model_integrity_fail, severity=critical}`. Signing key fingerprints documented in `docs/design/SECURITY.md`.
- [x] **Compiled-artifact integrity.** Cached TensorRT engines / OpenVINO blobs / `torch.compile` artifacts are HMAC-tagged with a key derived from `cfg.compute_artifact_cache_secret` + `host_compute_fingerprint` so a tampered cache file can't be silently loaded across hosts.
- [x] **No `*-latest` model IDs in code** (per CLAUDE.md). All model URIs in `ai/common/config.py` are version-pinned; the lint rule `xops/lint/no_latest_model.py` enforces it. A second lint rule `xops/lint/runtime_matrix_match.py` cross-checks `requirements.txt` against `xops/compute/runtime_matrix.json`.
- [x] **CUDA wheel index pinning.** The pip extra-index URL for CUDA wheels is pinned to NVIDIA's signed mirror; checksums recorded in the build manifest; supply-chain attacks land with the build, not at runtime.
- [x] **No GPU memory leak across tenants.** When the arbiter evicts a model, it explicitly zeroes the freed buffer (or recreates the CUDA context for LLM-class models) before granting the slot to the next agent. This protects against cross-agent VRAM scrape. Tested with a marker pattern (`test_gpu_memory_zeroed_between_tenants`).
- [x] **No prompt/data egress.** GPU containers have no outbound network in prod (`cfg.compute_egress=none`); telemetry goes through a sidecar that strips inputs/outputs from device-probe payloads.
- [x] **CPU-only build-tag enforcement.** Phase 9 API, Phase 16 emitter, and Phase 17 patcher are built with `-tags cpu_only` (Go) or import-shadowed `torch`/`xgboost`/`openvino` modules that raise on import (Python). The lint rule `xops/lint/cpu_only_imports.py` and a runtime test (`test_compute_isolation`) both enforce it.
