# Phase 13.50 — Multi-region catalog consistency

> Extracted from `docs/planning/ROADMAP.md` §13.50
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.50 Multi-region catalog consistency

> Retires assumption §13.0 #62. Phase 14 packages the cluster, but
> the *invariant* that every region serves the same catalog hash is
> a Phase 13 contract.

- [ ] **`catalog_sha256` published per replica.** Phase 9 `/healthz` already exposes the field (§13.1); Phase 8 console adds a per-region rollup panel.
- [ ] **Cross-region drift alert.** `catalog.region.drift.v1{region_a, region_b, sha_a, sha_b, observed_at}` raised when two regions report divergent hashes for > `cfg.catalog_region_drift_max_s` (default 90 s); the alert auto-pages.
- [ ] **Traffic-shaping refusal.** Phase 14 routing layer refuses to send a request from region A's edge to region B's predictor while a drift alert is open (proof test `test_drift_blocks_cross_region_routing.py`).
- [ ] **Catalog reload coordinated by region.** §13.26 two-phase reload extends to a per-region quorum: a commit only fires when ≥ `cfg.catalog_reload_region_quorum_pct` (default 80 %) of regions have validated the propose; otherwise abort.
- [ ] **Disaster-region exclusion.** A region declared `degraded` by the Phase 14 health controller is excluded from quorum (otherwise a partitioned region perpetually blocks reloads); exclusion is audited per §13.21.
- [ ] **Per-region readiness lag SLO.** A region must reach the new catalog hash within `cfg.catalog_region_propagation_max_s` (default 60 s) of commit; sustained breach demotes the region to read-only via Phase 14.
