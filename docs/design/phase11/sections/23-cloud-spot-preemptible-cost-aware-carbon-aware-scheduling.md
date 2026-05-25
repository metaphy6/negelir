# Phase 11.23 — Cloud spot/preemptible, cost-aware & carbon-aware scheduling

> Extracted from `docs/planning/ROADMAP.md` §11.23
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.23 Cloud spot/preemptible, cost-aware & carbon-aware scheduling

- [ ] **Spot / preemptible signal handling.** A small `xops/compute/spot_watcher.py` daemon polls the cloud metadata service for eviction notices (AWS `/latest/meta-data/spot/instance-action`, GCP `/computeMetadata/v1/instance/preempted`, Azure scheduled events) and triggers a §11.18 host drain on receipt. Eviction-to-drain-ack p99 ≤ `cfg.spot_eviction_ack_max_s`. Failure-mode row 21 binds.
- [ ] **Cost table (per device, per region).** `cfg.compute_cost_table_<device>` maps `(provider, instance_family, region, accel_class) → usd_per_hour` and is consulted by the router (§11.13) as a tie-breaker between equally-suitable devices: prefer cheaper at equal latency-headroom. Counters in §11.9 (`negelir_compute_cost_usd_per_million_inferences`) make the trade-off auditable; never fabricated when the table is unset.
- [ ] **Carbon-aware batch scheduling.** Training (§11.12) and overnight bench (§11.9) consult `cfg.carbon_intensity_feed_url` (e.g. WattTime / ElectricityMaps); jobs whose deadline allows it are deferred to lower-carbon windows. Realtime / interactive workloads are **never** delayed for carbon. Decisions emitted as `train.schedule.v1{deferred_until, carbon_intensity_now, carbon_intensity_then, kg_co2_saved_estimated}`.
- [ ] **Off-peak training window.** A configurable cron-style window `cfg.training_offpeak_window` (default empty = always-on) lets ops bias training to off-peak grid hours without touching code.
- [ ] **Cost guardrail.** A per-day spend cap `cfg.compute_daily_usd_cap` (computed from §11.9 counters); breach refuses new `batch`/`training` leases with `cost_cap_exceeded`, never `realtime`. Audited.
