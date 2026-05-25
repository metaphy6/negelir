# Phase 11.35 — Hard reservations, brownout, and guaranteed QoS

> Extracted from `docs/planning/ROADMAP.md` §11.35
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.35 Hard reservations, brownout, and guaranteed QoS

> **Why this exists.** §11.2 weighted-fair-share is fair *within* a
> tier; it does not guarantee that `realtime` always has X % of the
> GPU. A sustained `realtime` spike from one tenant can still starve
> another tenant's `realtime` floor.

- [ ] **Per-class reservations.** `cfg.compute_reservations.<workload_class>` declares the floor (e.g. `predictor_micro=20%`, `sec_input=10%`) of GPU time / VRAM that the arbiter **must** keep available for that class. Reservations sum to ≤ 100 %; `cfg.compute_reservations_unreserved` is the burst pool.
- [ ] **Brownout modes.** Operator-engaged states with audited transitions: `normal` (default), `shed_training` (refuse all `training` leases), `shed_batch` (also refuse `batch`), `shed_interactive` (only `realtime` served), `read_only` (refuse all writes — used during incident response). Set via ops console + SIGHUP; emitted as `device.alert.v1{kind=brownout, mode, by, reason}`. Inverse `un-brownout` re-admits.
- [ ] **Brownout SLO contract.** Each mode publishes the latency / availability target it preserves in `docs/design/COMPUTE_DEVICES.md`; chaos test (Phase 12) asserts the contract under synthetic load.
- [ ] **Reservations interact with §11.27 idle.** A reserved class that has no traffic does not block idle power capping — the cap is restored on first lease as in §11.27, but the reservation itself is bookkeeping, not a constant power draw.
