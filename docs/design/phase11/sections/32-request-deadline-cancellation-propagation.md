# Phase 11.32 — Request-deadline & cancellation propagation (binding for Phase 9 API)

> Extracted from `docs/planning/ROADMAP.md` §11.32
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.32 Request-deadline & cancellation propagation (binding for Phase 9 API)

> **Why this exists.** §11.13 routes on *recent* p95; §11.14 cancels on
> client disconnect. Neither answers "this specific request has 80 ms
> left on its budget — should the router even start?" Without an
> explicit deadline, the system happily burns GPU time on requests
> whose SLO is already violated.

- [ ] **End-to-end deadline.** Every inference request carries `deadline_mono_ns` set at the API edge (Phase 9) from `received_mono_ns + min(api_budget, client_X-Deadline-Ms)`. The deadline propagates through router → arbiter → engine → sampler as a single integer; it is never recomputed downstream.
- [ ] **Admission against remaining budget.** §11.13 router rejects with `HTTP 504 Gateway Timeout` + `X-Compute-Reason: deadline_unreachable` when `expected_wait_ms + p95_compute_ms > remaining_ms − cfg.compute_deadline_safety_ms`. Counted in `negelir_compute_admission_refused_total{reason=deadline}`.
- [ ] **In-flight cancellation.** A request whose deadline expires mid-decode triggers a cooperative cancel via the §11.14 mechanism within `cfg.llm_cancel_grace_ms`; KV-cache for that sequence is reclaimed, the response is `504` with `X-Compute-Reason: deadline_expired_in_flight`. **Peers in the same continuous batch are not affected** (proof binds to §11.22).
- [ ] **Queue-jumping prohibited.** A short-deadline request does *not* preempt a long-deadline one (avoids a starvation vector); it is either admitted on the next scheduler tick or refused. Priority remains the §11.2 axis; deadline is the admission axis.
- [ ] **Replay propagates deadline.** Stored `prediction.v1` provenance includes the *honoured* compute time and the *requested* deadline so replay (§11.15) can reconstruct admission decisions for post-mortems.
