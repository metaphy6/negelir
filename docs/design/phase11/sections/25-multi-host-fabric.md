# Phase 11.25 — Multi-host fabric (NCCL / RDMA / GPUDirect — Phase 14 contract)

> Extracted from `docs/planning/ROADMAP.md` §11.25
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.25 Multi-host fabric (NCCL / RDMA / GPUDirect — Phase 14 contract)

> **Why this exists.** Phase 11 does not ship multi-host inference, but
> the routing/probe contracts must not paint Phase 14 into a corner.
> The bare minimum is: enumerate the fabric, refuse to lie about it,
> and reserve the failure rows.

- [ ] **Fabric probe.** §11.1 enumerates `{ib_devices: […], rdma_capable: bool, gpudirect_storage: bool, nccl_socket_ifname, fabric_topology_path}`. Absent fabric → reported, not synthesised.
- [ ] **NCCL discipline (when used).** `NCCL_ASYNC_ERROR_HANDLING=1`, `NCCL_DEBUG=INFO`, `TORCH_NCCL_BLOCKING_WAIT=1`, watchdog `cfg.nccl_watchdog_s` (failure-mode row 25). All NCCL leases coordinated via the §11.2 arbiter using a multi-GPU **set lease** (atomic acquire of N GPUs or refuse — partial acquisition is a known deadlock vector and must be impossible).
- [ ] **GPUDirect Storage (GDS).** When available and `cfg.compute_bundle_use_gds=true`, bundle pulls bypass the page cache; otherwise standard. Selection logged in `bundle.swap.v1`.
- [ ] **Tensor / pipeline parallelism (deferred).** Bundle manifest reserves `tp_size`, `pp_size` fields with default 1 so future bundles can declare topology without a schema bump.
