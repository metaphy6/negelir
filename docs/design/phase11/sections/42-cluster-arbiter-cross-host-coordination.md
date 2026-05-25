# Phase 11.42 — Cluster arbiter & cross-host coordination (Phase 14 hook)

> Extracted from `docs/planning/ROADMAP.md` §11.42
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.42 Cluster arbiter & cross-host coordination (Phase 14 hook)

> **Why this exists.** §11.2 is the per-host authority; without a thin
> cluster overlay, a global tenant cap, a fleet-wide brownout, a
> region-wide spot-eviction storm, or a cluster-shared bundle-pull
> rate-limit each devolves into N uncoordinated host-local decisions.
> This sub-phase ships the contract; the production K8s wiring lands
> in Phase 14.

- [ ] **Cluster-arbiter contract.** A small stateless service `xops/compute/cluster_arbiter.py` (Redis-backed; later promotable to NATS KV / etcd) exposes: `cluster.brownout(mode, reason)`, `cluster.tenant_cap(tenant_id, gpu_seconds_per_min)`, `cluster.bundle_pull_lease(bundle_sha)`, `cluster.engine_quarantine(engine, host_class, reason)`, `cluster.region_drain(region, reason)`. Each call is **idempotent** with a fencing token; conflicting calls resolve by latest-wins with audit.
- [ ] **Per-host arbiter remains authoritative.** Cluster decisions are **advisory, not mandatory**: the per-host arbiter (§11.2) consults the cluster signal at lease time and merges it with local state (a host already over-temperature does not need a cluster brownout to start refusing). When the cluster service is unreachable, hosts continue under their last-cached cluster state for `cfg.compute_cluster_cache_ttl_s` (default 300 s) then **fall back to local-only authority** with a `device.alert.v1{kind=cluster_arbiter_unreachable, severity=warn}`. The data path never blocks on the cluster service.
- [ ] **Cluster-bundle-pull coordination.** §11.27's coldstart-storm jitter is per-host; the cluster arbiter additionally rate-limits *fleet-wide* concurrent pulls of the **same** bundle SHA via `cluster.bundle_pull_lease`, capped at `cfg.compute_bundle_cluster_pull_max_concurrent`. A 100-pod redeploy never N-fanout-503s the bundle store.
- [ ] **Cluster brownout fan-out.** Operator engages brownout once on the cluster arbiter; per-host arbiters pick it up within `cfg.compute_cluster_brownout_propagation_s` (default 5 s) and apply §11.35 locally. Fan-out completion is observable via `negelir_cluster_brownout_propagation_seconds` histogram.
- [ ] **Cluster engine quarantine.** When `cluster.engine_quarantine` fires (e.g. operator confirms a cuDNN bug across the fleet), every host of matching `host_class` (§11.1) refuses that engine without each having to learn it the hard way. Local quarantines (§11.31) still operate per-host for engines the cluster has not yet judged.
- [ ] **Region drain.** A cloud zone outage marks every host in the region as `drain` (§11.2) via one cluster call; the per-host arbiters drain in parallel, in-flight requests migrate to peer regions, no request fails closed within the cloud's grace window.
- [ ] **Liveness.** The cluster arbiter is **not** in any inference critical path; its outage degrades policy precision, not request serving. SLO: cluster operations p95 ≤ 50 ms; outage detection ≤ `cfg.compute_cluster_health_s`. Deployed N=3 with leader election (Redlock); split-brain refuses writes (`cluster_split_brain` alert) and per-host arbiters fall back to last-cached state.
- [ ] **Audit.** Every cluster decision appends to `negelir:cluster_arbiter:audit` (Redis stream, capped); shipped to the ops console. Per-host arbiters append `cluster.applied.v1{decision_id, fencing_token, applied_at}` so the cluster observer can verify fan-out.
