# Phase 22.9 — Metric rename table

Generated at Phase 22.9 bullet 1: `make phase22.metric-scan`

## Conformance pattern

```
^(datasource|swarm|server|common|patcher|gitops)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$
```

## Summary

Total metrics found: 31
Conforming: 29
Non-conforming: 2

## Notes

**Metric scope:** Phase 22.9 scans for non-conforming metrics in the transitional layout
(before Phase 22.2-22.7 package moves). Most metrics in `common/telemetry.py` were already
renamed to `common_*` namespace during Phase 22.3 (common/ merge) and prior work. The 2
metrics listed below still retain their non-conforming `nlp_*` names in test code as part
of the Phase 22.9 §22.9.5 dual-emission window (both old and new names emitted for 30 days
post-rename to prevent alert gaps).

## Non-conforming metrics

| Old Name | New Name | Type | Files |
|----------|----------|------|-------|
| `nlp_input_repair_total` | `common_input_repair_total` | telemetry_sink | ai/tests/test_22_9_dual_emission_removed_after_window.py |
| `nlp_pipeline_latency_seconds` | `common_pipeline_latency_seconds` | telemetry_sink | ai/tests/test_22_9_dual_emission_active_within_window.py |
