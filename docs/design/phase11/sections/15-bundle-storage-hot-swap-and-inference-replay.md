# Phase 11.15 — Bundle storage, hot-swap, and inference replay

> Extracted from `docs/planning/ROADMAP.md` §11.15
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.15 Bundle storage, hot-swap, and inference replay

- [ ] **Lazy-load from object store.** Bundles ≥ `cfg.compute_bundle_inline_max_mb` (default 200 MB) are **not** baked into the image; they live in MinIO/S3 and are pulled at warm-up by `bundle_loader.py`. Pull is verified against the bundle's SHA-256 and cosign signature (§11.11) before mapping into device memory; partial / corrupt downloads are quarantined. Pulls go through `cfg.compute_bundle_concurrent_pulls_max` to avoid network thrash.
- [ ] **Local bundle cache.** Pulled bundles cache to `cfg.compute_bundle_cache_dir` (LRU, `cfg.compute_bundle_cache_max_mb`); cache is shared across agents on the same host via a file lock so two agents don't pull the same bundle twice.
- [ ] **Hot-swap (zero-drop).** Swapping `bundle_v` → `bundle_v+1`: (1) loader pulls + verifies `v+1` to local cache, (2) router opens a parallel handle on a free device or a co-resident slot, (3) router shifts new requests to `v+1` while letting `v` drain its in-flight queue, (4) `v` is unloaded after `cfg.bundle_drain_max_s`. The swap is logged as `bundle.swap.v1{old_sha, new_sha, drained, forced}`. **No request observes mid-swap mismatch**; the consensus layer (Phase 5) tags each emitted prediction with the bundle SHA so downstream parity tests are unambiguous.
- [ ] **Atomic rollback.** A swap can be reversed within `cfg.bundle_rollback_window_s`; rollback is the same drain-then-promote in reverse. Triggered by drift detector (Phase 6) or manually from the ops console.
- [ ] **Inference replay contract.** A `prediction.v1` carries `compute_provenance` (§11.4) and a stable `input_hash`. `xops/compute/replay.py PREDICTION_ID` re-runs the prediction on a host whose `host_compute_fingerprint` matches and asserts byte-equality (predictors) or token-equality given the same sampler tuple (LLMs). Mismatch is the §11.10 row 20 failure. The replay tool is a test target, an ops tool, and the foundation for the §11.20 nightly smoke.
