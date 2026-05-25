# Phase 13.68 — Catalog-driven metric label lifecycle

> Extracted from `docs/planning/ROADMAP.md` §13.68
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.68 Catalog-driven metric label lifecycle

> Retires assumption §13.0 #80. Cardinality must be bounded over
> time, not just at snapshot.

- [ ] **Tombstone-on-mutation.** When a league's `tier` / `quarantined` / `warming_state` / `deployment_phase` changes, telemetry emits a final tombstone sample for the prior label combination (zero or sentinel) and stops emitting that combo.
- [ ] **Rolling cardinality budget.** §13.10 cardinality budget is computed over a `cfg.metrics_cardinality_rolling_days` (default 90) window, not snapshot; CI lane runs `bench/metric_cardinality.py` to assert budget over a synthetic 50-league × 90-day churn scenario.
- [ ] **TSDB GC.** Phase 8 ops console exposes a "stale series" panel (no samples in > 30 days); ops can hard-delete via `make telemetry.gc STALE_DAYS=<n>` (audited).
- [ ] **Label whitelist.** `xops/lint/metric_label_whitelist.py` refuses any new metric whose label set isn't declared in `xops/telemetry/label_whitelist.yaml`; prevents accidental high-cardinality labels (e.g. `player_id`).
- [ ] **Per-replica recovery.** A replica restarting after a tier change re-reads the catalog, learns the current effective label, never resurrects a tombstoned series.
