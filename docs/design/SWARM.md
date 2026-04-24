# 🐝 Swarm Design

> Companion to [`../planning/ROADMAP.md`](../planning/ROADMAP.md), Phase 3 onward.

## 🎯 Why a swarm?

A swarm is a **set of small, single-purpose processes coordinated by messages**.
We picked it over a monolith and over a "microservices over HTTP"
shape because:

- Each agent is **easy to reason about** (one job, one input topic, one output topic).
- The bus gives **at-least-once durability** without us writing it.
- Agents can be scaled **independently**: 1 of `consensus.v1` is plenty, but 8 of `predictor.xgb_xg.v1` may be ideal.
- **Failure is normal**: kill an agent and the supervisor restarts it; in-flight messages get retried by another consumer in the group.

## 👥 Roster (canonical)

> **Pivot v3 ownership note (2026-04-20).** The "ingestion-side"
> agents in this roster — `scraper.<source>.v1`, `categorizer.v1`,
> `processor.<kind>.v1`, `storage.v1`, `cache.v1`, `maint.schema.v1`,
> `maint.coder.v1` — moved out of `swarm/` and into the new
> `datasource/` component (see [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md) §3
> and [`DATA_SOURCE.md`](DATA_SOURCE.md)). `maint.schema.v1` and
> `maint.coder.v1` are **absorbed into `datasource/patcher/`** and
> drop as standalone agents (see [`SCRAPER_PATCHER.md`](SCRAPER_PATCHER.md)
> §1). They are kept in the table below for traceability — the bus
> contracts and message envelopes are unchanged; only the owning
> compose profile / package path moves. Pure-prediction agents
> (`pred.*`, `consensus`, `proofreader`, `drift`, `sec.*`,
> `maint.scaler`, `maint.backup`) stay under `swarm/` and are this
> document's primary subject.

| Agent | Phase | Owns (post-Pivot v3) | Stateless? | Default replicas | GPU? |
|---|---|---|---|---|---|
| `scraper.<source>.v1` | 4 | `datasource/scraper/` | yes | 1 / source | no |
| `categorizer.v1` | 4 | `datasource/scraper/` (categorization stage) | yes | 1 (NPU if avail) | optional |
| `processor.<kind>.v1` | 4 | `datasource/scraper/` (processing stage) | yes | 1 / kind | no |
| `storage.v1` | 4 | `datasource/emitter/` (Phase 16) | yes | 1 (single writer) | no |
| `cache.v1` | 4 | `datasource/emitter/` (Phase 16) | yes | 1 | no |
| `telemetry.v1` | 4 | `swarm/` shared infra | yes | 1 | no |
| `pred.elo.v1` | 5 | `swarm/predictors/` | yes | 2 | no |
| `pred.dixon_coles.v1` | 5 | `swarm/predictors/` | yes | 2 | no |
| `pred.xgb_form.v1` | 5 | `swarm/predictors/` | yes | 2 | yes (training) |
| `pred.xgb_xg.v1` | 5 | `swarm/predictors/` | yes | 2 | yes (training) |
| `pred.lgbm_market.v1` | 5 | `swarm/predictors/` | yes | 2 | yes (training) |
| `pred.tabnet.v1` | 5 | `swarm/predictors/` | yes | 1 | yes |
| `consensus.v1` | 5 | `swarm/predictors/` | yes | 1 | no |
| `proofreader.v1` | 6 | `swarm/proofreaders/` | yes | 3 (quorum) | no |
| `drift.v1` | 6 | `swarm/drift/` | yes | 1 | no |
| `sec.input.v1` | 7 | `swarm/defense/` | yes | 2 | optional |
| `sec.scrape.v1` | 7 | `swarm/defense/` | yes | 1 | no |
| `sec.rate.v1` | 7 | `swarm/defense/` | yes | 2 | no |
| `maint.schema.v1` | 8 | **absorbed into `datasource/patcher/`** | yes | n/a | no |
| `maint.scaler.v1` | 8 | `swarm/` shared infra | yes | 1 | no |
| `maint.coder.v1` | 8 | **absorbed into `datasource/patcher/`** | yes | n/a | yes |
| `maint.backup.v1` | 8 | `swarm/` shared infra | yes | 1 | no |

## 🤝 Consensus algorithm (Phase 5)

For each `(match_id, market)`:

1. Collect votes from every healthy `pred.*.v1` agent up to `cfg.consensus_window_ms`.
2. Drop votes with `confidence < cfg.consensus_min_confidence`.
3. Compute weighted average using per-predictor weights (rolling Brier-loss).
4. Apply per-market isotonic calibration (table loaded from Postgres, version logged).
5. Publish `predict.final` carrying: distribution, weights, contributing model IDs, calibration version, swarm-confidence.

Quorum rule for Proofreader (Phase 6):

```
publish_to_cache iff  (pass_count >= ceil(N/2) + 1)  and  (drift.v1 not tripped)
```

## 📨 Message envelope (CBOR)

```text
{
  "v":         1,                           // envelope version
  "trace_id":  "<uuid v7>",
  "produced":  "<rfc3339nano>",
  "by":        "pred.xgb_xg.v1@5",          // agent + replica id
  "topic":     "predict.vote",
  "key":       "match:42:market:ms",        // bus partition key
  "schema":    "predict.vote/2",            // versioned
  "payload":   { /* schema-specific */ }
}
```

CBOR for size + speed; JSON only via `swarmctl tail --json` for humans.

## 🧪 Testability

- `InMemoryBus` Python + Go implementation makes unit tests deterministic.
- A `BusRecorder` writes every test-time message to a fixture file; a corresponding `BusReplayer` re-runs them in CI to detect regressions in agent ordering / payload shape.
