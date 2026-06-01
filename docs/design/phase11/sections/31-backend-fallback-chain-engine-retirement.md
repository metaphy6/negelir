# Phase 11.31 — Backend fallback chain & engine retirement

> Extracted from `docs/planning/ROADMAP.md` §11.31
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.31 Backend fallback chain & engine retirement

> **Why this exists.** When a TensorRT engine hits a known cuDNN bug
> mid-decode, the right answer is "fall through to torch eager on the
> same GPU, then to CPU baseline" — not "503 the request". The original
> Phase 11 had no explicit chain, so each agent improvised. This
> sub-phase makes the chain a first-class, audited contract.

- [ ] **Per-workload-class chain.** `xops/compute/workload_matrix.json` declares an ordered `fallback_chain` per workload class, e.g. `predictor_deep: [tensorrt_fp32, torch_inductor_fp32, torch_eager_fp32, cpu_xgboost]`. The router (§11.13) walks the chain on `engine.error.v1` events; each step counts in `negelir_compute_fallback_step_total{workload_class, from_engine, to_engine, reason}`. CPU baseline is **always** the terminal step — the chain never ends in `503` while the CPU path can serve the workload at SLO.
- [ ] **Bounded walk.** The chain walk is bounded by `cfg.compute_fallback_max_steps` (default 3) per request and by `cfg.compute_fallback_max_wall_ms` (default = 30 % of `remaining_deadline_ms`); over either bound the request returns `503 X-Compute-Reason: fallback_exhausted` rather than burning the budget. The bound is per-request, not per-process; bursts cannot collectively exhaust shared engine state.
- [ ] **Engine quarantine.** When an engine emits `engine.error.v1` more than `cfg.compute_engine_error_quarantine_threshold` times within `cfg.compute_engine_error_quarantine_window_s` on a given device, that `(engine, device)` pair is **quarantined**: the router stops selecting it as the preferred engine for `cfg.compute_engine_quarantine_cooldown_s` (default 600 s). Quarantine is per-`(engine, device, host_compute_fingerprint)`; a cuDNN bug that fires on one host does not pre-emptively quarantine peers — each host learns independently. Quarantine state is shared via the §11.42 cluster arbiter so a fleet-wide bad engine is detected fast.
- [ ] **Quarantine release.** A quarantined pair returns to rotation either (a) after the cooldown plus a successful canary inference (§11.18 canary mechanism reused), or (b) explicitly via the ops console `compute.unquarantine` command (audited). Re-quarantine within `cfg.compute_engine_re_quarantine_grace_s` doubles the cooldown (exponential up to a 24 h cap) so a flapping engine cannot soak up retries forever.
- [ ] **Provenance under fallback.** The emitted `prediction.v1.compute_provenance` records the **engine that actually produced the answer**, plus a compact `fallback_path` array of `(engine, error_class)` tuples for every step that was tried and failed. Replay (§11.15) follows the same path — a stored prediction made on the second engine in the chain is replayed on that engine, not on the preferred one.
- [ ] **Determinism preserved.** Predictor parity (§11.4) holds across every engine in the chain: each step is itself parity-bound to the CPU baseline within the published tolerance. An engine that cannot meet that tolerance must not appear in a predictor's chain — `xops/lint/predictor_engine_determinism.py` (§11.21) enforces this on PR.
- [ ] **No silent data fall-through.** A fallback step that would return a different *kind* of answer (e.g. an engine that lacks a required output head) is refused at admission, not at runtime — the chain only contains engines that satisfy the workload's full output schema. Tested.
- [ ] **Audit.** Every chain walk emits `compute.fallback.v1{request_id, workload_class, chain, terminal_step, reason}`; sampled at `cfg.compute_fallback_audit_sample_rate` for non-error walks (engine retired during a routine drain) and always for error walks.
