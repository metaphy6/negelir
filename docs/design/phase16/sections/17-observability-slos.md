# Phase 16.17 — Observability & SLOs

> Extracted from `docs/planning/ROADMAP.md` §16.17
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.17 Observability & SLOs

- [ ] **Metrics (Prometheus, scraped from emitter `:9100/metrics`):** `emitter_records_written_total{plane,source,version}`, `emitter_write_latency_ms` (histogram), `emitter_manifest_age_ms` (gauge — flips alarm if > `cfg.emitter_manifest_max_age_ms`, default 30 000), `emitter_disk_usage_pct{volume}`, `emitter_lease_holder_changes_total{plane,source}`, `emitter_oversize_records_truncated_total`, `emitter_snapshot_build_seconds` (histogram), `feed_reader_lag_ms{plane,source,consumer}`, `feed_reader_checksum_mismatch_total`, `feed_reader_corrupt_line_total`, `feed_reader_guessed_path_rejects_total`, `feeds_store_retry_total{driver,op,outcome}`.
- [ ] **SLOs (binding for Phase 16 sign-off):** writer `p99` per-record latency < 5 ms (local disk), < 50 ms (S3); manifest age `p99` < 5 s; reader `stream()` cold-start < 250 ms; reader `snapshot()` for one `(plane, source, day)` < 2 s; integrity sweep wall-time on the mock corpus < 60 s.
- [ ] **Alert rules** (`xops/observability/alerts/emitter.yaml`): `EmitterManifestStale`, `EmitterDiskUsageHigh`, `EmitterLeaseFlapping` (> 3 changes / 5 min), `FeedReaderLagHigh`, `FeedsIntegrityViolation`, `FeedsSnapshotBuildSlow`. Each alert routes per the Phase 7 `sec.alert.v1` severity ladder.
- [ ] Proof tests: `test_emitter_metrics_exposed.py`, `test_alert_rules_load_in_promtool.py`, `test_slo_budget_enforced_in_ci.py` (a synthetic load fails CI if median write latency exceeds 2× the SLO on the reference workload).
