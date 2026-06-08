# Phase 11.26 — Shadow inference & dark-launch (binding for Phase 6 retrain promotion)

> Extracted from `docs/planning/ROADMAP.md` §11.26
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.26 Shadow inference & dark-launch (binding for Phase 6 retrain promotion)

- [x] **Shadow router mode.** A bundle promoted to `shadow` is loaded alongside the live bundle (subject to §11.2 VRAM accounting) and serves a sampled mirror of live traffic; results are diffed against the live bundle's outputs without touching the user response. Diffs land in `bundle.shadow.diff.v1{old_sha, new_sha, input_hash, kl_divergence?, prediction_delta?}`.
- [x] **Promotion gate.** A shadow bundle is eligible for promotion (hot-swap, §11.15) only when shadow diff metrics over the trailing `cfg.shadow_window_min` minutes meet the per-workload thresholds in `xops/compute/shadow_promotion.json` (e.g. predictor: KL ≤ 5e-3, 99th-percentile per-outcome delta ≤ 5e-3; LLM: pass-rate of an automatic style/safety probe ≥ 99 %). Below threshold → promotion refused, page on-call.
- [x] **Cost cap.** Shadow traffic is bounded by `cfg.shadow_traffic_pct` (default 5 %) and `cfg.shadow_max_concurrent_bundles` (default 1) so dark-launch can never starve the live path.
- [x] **Replay coupling.** Shadow diffs are tagged with the §11.4 `compute_provenance` of *both* sides so a surprise can be replayed via §11.15.
