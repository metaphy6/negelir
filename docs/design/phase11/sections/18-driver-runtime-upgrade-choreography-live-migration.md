# Phase 11.18 — Driver / runtime upgrade choreography & live migration

> Extracted from `docs/planning/ROADMAP.md` §11.18
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.18 Driver / runtime upgrade choreography & live migration

- [ ] **Drain-before-upgrade.** Before any driver / runtime / cuDNN / OpenVINO upgrade, the host is set to `drain` via §11.2 (or a single GPU if upgrade is per-GPU). New leases are refused; existing leases finish; agents whose workload class accepts an alternate device migrate to the alternate; the rest are restarted on a peer host.
- [ ] **Upgrade gate.** Upgrades cannot proceed while any LLM-class lease is held (`cfg.upgrade_max_drain_wait_s` cap; over-budget → page on-call). Persistence mode + clock locks are restored after upgrade; the probe re-fingerprints; the new tuple is checked against `quirks.json` (§11.16) before the host is undrained.
- [ ] **Canary-host upgrade.** Fleet upgrades roll one host at a time (Phase 14 K8s integration); a hard floor of `cfg.upgrade_canary_observe_s` (default 10 min) of normal traffic + bench passes before the next host upgrades. Bench regression > §11.9 hard-floor → upgrade halted, host quarantined.
- [ ] **Live migration (deferred path).** When `cuda-checkpoint` (NVIDIA) or CRIU + GPU plugin (ROCm) is available, the choreographer exposes a `migrate(host_a, host_b)` operation: snapshot LLM session state on A, transfer (Phase 14 storage class), restore on B, swap routing. **Not on the Phase 11 critical path** (gated `cfg.compute_live_migration_enabled=false`); the contract and the ops command land here so Phase 14 can plug it in without re-architecting.
