# Phase 11.13 — Heterogeneous concurrent routing (`ai/swarm/sdk/compute_router.py`)

> Extracted from `docs/planning/ROADMAP.md` §11.13
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.13 Heterogeneous concurrent routing (`ai/swarm/sdk/compute_router.py`)

> **Why this is binding.** A Meteor/Lunar Lake host has CPU + iGPU + NPU
> simultaneously; an NVIDIA workstation can have a dGPU **and** an Intel
> NPU on the same motherboard. The original Phase 11 selected one tier
> globally and left the others idle. This sub-phase replaces "selection"
> with "routing".

- [ ] **Workload classes.** Five canonical classes derived from agent metadata: `predictor_micro` (tiny GBM/Elo, ≤ 10 ms target), `predictor_deep` (XGB-class, fp32 parity-bound), `classifier_small` (sec.input `categorizer.v1`, INT8-friendly), `humanizer_llm` (sub-1 B LLM), `coder_llm` (Phase 8 coder). Each class declares its **preferred device list**, **acceptable device list**, **dtype constraints**, **VRAM ceiling**, and **latency SLO** in `xops/compute/workload_matrix.json`.
- [ ] **Routing decision.** For each request the router scores every available device against the workload class's preferences using `(latency_p95_recent, queue_depth, vram_largest_free_block, lease_state, thermal_headroom, peer_link_locality, remaining_deadline_ms)` and picks the highest-score device that satisfies hard constraints (dtype, VRAM, runtime, **deadline-reachable** per §11.32). Score weights live in config; tested for stability.
- [ ] **Concurrent backends.** A predictor on CPU, a classifier on NPU, a humanizer on dGPU all serve in parallel from the same agent process where the workload classes allow. The router holds **independent** lease handles per device; no single chokepoint.
- [ ] **Sticky routing.** The router tries to keep a session's requests on the same device (warm KV-cache, hot bundle); breaks stickiness only on hard constraint violation (queue saturation, eviction, thermal). Sticky window is `cfg.compute_router_sticky_window_s`.
- [ ] **Backpressure & admission control.** When all candidate devices saturate (queue depth > `cfg.compute_router_admit_max_qd`), the request is **rejected with `service_busy`** before consuming GPU time, propagating a `Retry-After` upstream (Phase 9 API). No silent queueing past the bound — bounded queues only.
- [ ] **Routing decisions audited.** Every non-trivial route (anything beyond the obvious "only one device available") logs `route.decision.v1{request_id, workload_class, device, score, alternates, reason}` (sampled at `cfg.compute_router_audit_sample_rate`).
