# Phase 11.27 — Idle power management & elastic warm-pool

> Extracted from `docs/planning/ROADMAP.md` §11.27
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.27 Idle power management & elastic warm-pool

- [x] **Idle detector.** A device with no lease activity for `cfg.gpu_idle_threshold_s` (default 600 s) is marked `idle`; the arbiter (§11.2) requests a low power cap (`cfg.gpu_idle_power_limit_w`, e.g. 50 W on a 350 W GPU) via `nvidia-smi -pl` when allowed. First lease request restores `power_default_limit_w` before granting.
- [x] **Wake-cost accounting.** Restoring power limit + warming KV-cache adds latency; the wake-cost estimate is exported (`negelir_gpu_wake_cost_seconds_recent`) and the §11.9 cold-start budget is satisfied **including** wake cost (no hidden carve-out).
- [x] **Warm-pool.** A bounded set of bundles is kept resident on each device based on trailing demand (`cfg.warm_pool_top_n_per_device`, default 2); membership is recomputed every `cfg.warm_pool_recompute_s`. Eviction respects §11.2 anti-flap (`min_hold_ms`).
- [x] **Coldstart-storm protection.** On a fleet restart, bundle pre-warming is jittered (`cfg.warm_pool_jitter_s`) and rate-limited per object-store endpoint (`cfg.compute_bundle_concurrent_pulls_max`) so a redeploy does not 503 the bundle store.
