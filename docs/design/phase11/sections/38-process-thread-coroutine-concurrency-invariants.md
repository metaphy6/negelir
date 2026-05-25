# Phase 11.38 — Process / thread / coroutine concurrency invariants

> Extracted from `docs/planning/ROADMAP.md` §11.38
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.38 Process / thread / coroutine concurrency invariants

> **Why this exists.** The arbiter's "single per-host" claim and the
> router's "per-process state" claim each assume a concurrency model
> that is never written down. Without it a future asyncio refactor
> will silently break mutual exclusion.

- [ ] **Arbiter threading model.** The arbiter is **process-singleton**: one in-process instance per agent process, shared via a module-level reference. All arbiter calls are coroutine-safe (asyncio lock around the Lua-script invocation) and thread-safe (the in-process lock is `threading.Lock`). Cross-process coordination is the Redis Lua script (§11.2). Documented in `COMPUTE_DEVICES.md` and asserted by `test_arbiter_concurrent_calls`.
- [ ] **Router threading model.** Router state (recent p95s, sticky map, matrix pointer) is read-mostly; updates use copy-on-write atomic-pointer swaps. Sticky map is a bounded `OrderedDict` behind a `threading.Lock` (≤ 1 µs critical section). No request waits on another request's router work.
- [ ] **No fork-after-import-torch.** §11.3 already bans fork after CUDA init; this extends to **all** GPU-backend imports (torch, openvino, xgboost-gpu, tensorrt). The supervisor sets `multiprocessing.set_start_method("spawn", force=True)` at the earliest possible point; tested.
- [ ] **GIL hot-loop discipline.** The continuous-batch scheduler (§11.22) and the router's score loop (§11.13) are pure-Python on the request hot path; both are profiled to keep their per-call cost ≤ `cfg.compute_router_p99_overhead_us` (default 200 µs) so the GIL never becomes the bottleneck. Regression gated in §11.9 bench.
