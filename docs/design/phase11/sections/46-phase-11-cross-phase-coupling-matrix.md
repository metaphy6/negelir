# Phase 11.46 — Phase 11 cross-phase coupling matrix (closing audit)

> Extracted from `docs/planning/ROADMAP.md` §11.46
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.46 Phase 11 cross-phase coupling matrix (closing audit)

> Reverse-index of every cross-phase commitment in this file so the
> next agent doesn't have to grep. Anything new touching Phase 11
> updates this table in the same diff.

| Other phase | What Phase 11 owes | Where |
|---|---|---|
| Phase 5 | Predictor parity tolerances, deterministic flags, compute_provenance schema, bundle hot-swap zero-drop | §11.4, §11.15, proofs |
| Phase 6 | Training compute path, GradScaler, dataloader determinism, shadow-promotion gate | §11.12, §11.26 |
| Phase 7 | sec.input device contract, NaN/Inf finite-check + quarantine handshake | §11.4, §11.10 row 14 |
| Phase 8 | Telemetry consumer (`device_probe`), VRAM accounting, drain choreography, ops-console endpoints, scaler preflight | §11.1, §11.2, §11.18, §11.34 |
| Phase 9 | `/healthz` contract, backpressure status matrix, deadline propagation, `X-Compute-Reason` enum | §11.30, §11.32, §11.44 |
| Phase 10 | Humanizer GPU residency, LLM serving primitives, sampler-determinism replay | §11.14, §11.22 |
| Phase 12 | Every §11.10 row → chaos test; every proof in §11.20 has its `make chaos.*` analogue or smoke variant | §11.10, §11.20 |
| Phase 14 | K8s device plugins, manifest-list dispatch, MIG, CRIU live migration, image-signing admission, region-drain | §11.7, §11.8, §11.18, §11.37, §11.42, §11.44 |
| Phase 16 | Emitter CPU-only build tag + governor binding + data_class capture inheritance | §11.11, §11.39, §11.40 |
| Phase 17 | Patcher CPU-only build tag + governor binding + scoped artifact-cache isolation | §11.11, §11.39, §11.40 |
| Phase 20 | Per-tenant counters + quotas + adapter eligibility (built dormant) | §11.17, §11.33 |
| Phase 21 | Embedding workload classes + vector-inference provenance | §11.43 |
