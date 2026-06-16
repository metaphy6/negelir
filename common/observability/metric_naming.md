# Metric Naming Convention (Phase 18.7 ledger #18)

**Pattern:** `{component}_{subsystem}_{verb}_{unit}`

## Components

Every metric must be prefixed with one of:
- `datasource` — scraper, extractor, emitter
- `swarm` — predictor, consensus
- `server` — Go REST API
- `common` — shared infrastructure
- `patcher` — auto-patcher
- `gitops` — Git ops worker
- `infra` — underlying services (Redis, Postgres, etc.)

## Subsystems

Named to reflect logical grouping. Examples:
- `emitter` (datasource subsystem)
- `consumer` (swarm subsystem)
- `handler` (server subsystem)
- `telemetry` (common subsystem)

## Verbs

Action or state being measured:
- `read`, `write`, `fetch`, `emit`
- `drop`, `error`, `retry`
- `lag` (for latency)
- `breach` (for threshold violations)

## Units

Final unit of measurement:
- `seconds`, `milliseconds`
- `bytes`, `kilobytes`, `megabytes`
- `total` (for counters)
- `ratio` (for proportions)
- `count` (for event counts)
- `gauge` (for scalar measurements)

## Examples

✅ Valid metrics:
- `datasource_emitter_write_bytes` — bytes written by emitter
- `swarm_consumer_lag_seconds` — consumer lag in seconds
- `server_handler_error_total` — total handler errors
- `common_telemetry_drop_total` — dropped telemetry events
- `patcher_retry_count` — retry attempts by patcher
- `isolation_violation_total` — isolation constraint violations

❌ Invalid metrics (rejected by CI):
- `emitter_bytes` — missing component prefix
- `datasource_lag` — missing unit suffix
- `swarm_predictions_generated_count` — subsystem + verb too verbose

## Labels

Every metric MUST include a `component` label so dashboards can group cleanly:

```python
import prometheus_client as pc

_metric = pc.Counter(
    "datasource_emitter_write_bytes",
    "Bytes written by datasource emitter",
    labelnames=["component", "plane"],  # component is mandatory
)

# Emit with required `component` label
_metric.labels(component="datasource", plane="main").inc(num_bytes)
```

## CI Enforcement

`xops/lint/metric_naming.py` asserts every emitted metric matches:
```
^(datasource|swarm|server|common|patcher|gitops|infra)_[a-z0-9_]+_(seconds|bytes|total|ratio|count|gauge)$
```

Violations block release.
