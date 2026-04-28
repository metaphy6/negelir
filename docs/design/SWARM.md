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

For each `(match_id, market, request_id)`:

1. Collect votes from every **expected** `pred.*.v1` agent until
   `cfg.consensus_window_ms` elapses **or** every expected voter has
   voted, whichever fires first. The expected set is constructor-
   injected; runtime `agent_registry` querying is a Phase 14.x
   follow-up (see ROADMAP §5.6).
2. **Drop** votes with `confidence < cfg.consensus_min_confidence`
   silently — the swarm simply has one fewer voter. Default `0.0`
   means the filter is off; raise it once your roster's confidences
   are calibrated. (Wired in 2026-04-28 review; was previously
   documented but unimplemented.)
3. Compute weighted average using per-predictor weights (rolling
   Brier-loss; refreshed nightly by `TrainerReactor`, never on the
   hot path).
4. Apply per-`(profile_id, market)` isotonic calibration. The
   `CalibrationTable` is fetched **at most once per request** —
   cached on the per-key pending accumulator so neither the
   late-vote guard nor the final emission re-hits the store
   (ROADMAP §5.2 invariant; locked in by
   `test_calibration_store_is_hit_at_most_once_per_request`).
5. Publish `predict.final` carrying: distribution, weights,
   contributing model IDs, calibration version, swarm-confidence,
   `degraded` + `degraded_reason`, deterministic `prediction_id`,
   `produced_at`.

**Bounded pending set.** The in-flight accumulator is capped at
`cfg.consensus_max_pending` (default 4096); overflow evicts the
oldest insertion + emits `proof.flag(kind=consensus_overflow)`.
Keeps consensus's memory bounded if predictors permanently DLQ.

Quorum rule for Proofreader (Phase 6):

```
publish_to_cache iff  (pass_count >= ceil(N/2) + 1)  and  (drift.v1 not tripped)
```

## 📨 Message envelope (JSON in v1; CBOR upgrade in Phase 9)

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

JSON for v1 (per ROADMAP §3.1) — human-debuggable, zero new deps,
carried natively by `redis-py`. The `Bus` interface is encoding-
agnostic via a `Codec` seam, so a CBOR+CDDL upgrade in Phase 9 is
purely additive (no agent code changes). `swarmctl tail --json`
stays the human view either way.

## 🧪 Testability

- `InMemoryBus` Python + Go implementation makes unit tests deterministic.
- A `BusRecorder` writes every test-time message to a fixture file; a corresponding `BusReplayer` re-runs them in CI to detect regressions in agent ordering / payload shape.
