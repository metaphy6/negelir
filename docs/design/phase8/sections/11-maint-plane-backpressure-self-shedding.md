# Phase 8.11 — Maint plane backpressure & self-shedding

> Extracted from `docs/planning/ROADMAP.md` §8.11
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 8.11 Maint plane backpressure & self-shedding

> The maint plane exists to handle outages; it must not become an outage itself. Cross-cutting backpressure rules.

- [x] **`maint.event.v1` consumer-lag watchdog.** When the median consumer lag on `maint.event.v1` exceeds `cfg.maint_plane_lag_alert_ms` (default 5000ms) for `cfg.maint_plane_lag_alert_window_s` (default 60s), emit `sec.alert.v1{kind=maint_plane_lag_high, severity=warn}` (debounced) and apply graded shedding:
  - **Tier 1 (lag > 5s):** scaler suppresses **non-emergency** decisions (`reason ∈ {lag_low, cpu_low, p95_high}` → drop; emergency reasons `{vram_budget_exceeded, manual_pin, retrain_request_warmup}` always emit). DLQ supervisor halves `max_replays_per_tick`.
  - **Tier 2 (lag > 15s):** scaler scale-down decisions are entirely paused (only scale-up emergencies emit). DLQ supervisor enters drain-only mode (no replays, only escalations). §8.6 schema sentinel reduces sample rate to 0.1× config.
  - **Tier 3 (lag > 60s):** every §8.x agent stops emitting non-critical events; emits a final `maint.event.v1{kind=maint_plane_throttled, tier=3}` then enters observer-only mode until lag clears below 1s for `cfg.maint_plane_recovery_window_s` (default 120s). Recovery emits `kind=maint_plane_recovered`.
- [x] **No self-amplification.** Tier 2/3 shedding events are themselves emitted at most **once per tier transition**, not periodically — prevents the shedding signal from amplifying the plane it is shedding.
- [x] **Per-agent self-throttle on own DLQ.** Independent of plane-wide lag: if any §8.x agent's own `<id>.dlq` depth grows by more than `cfg.maint_self_dlq_growth_alert` (default 50) per minute, the agent halves its own emit rate (token-bucket on its own producer side) until growth is non-positive for 2 minutes. Less drastic than §8.10 self-isolation; catches early-warning signs.
- [x] **Bus circuit-breaker.** Three consecutive bus-publish failures within 30s → agent enters `bus_degraded` mode: subsequent publishes go to `data/maint/agent_spool/<agent>/` (bounded by `cfg.maint_agent_spool_max_entries`, default 512), drained on first successful re-publish. Mirrors §8.1 opsctl spool but agent-side. Critical alerts (`severity=critical`) bypass the spool and either succeed or trigger `maint_self_isolated`.
- [x] **Proof tests.** (i) lag watchdog: inject 6s lag in test bus, assert tier-1 shedding + alert; ramp to 70s, assert tier-3 + observer mode; clear lag, assert recovery event. (ii) self-amplification: assert at-most-one tier-2 event per tier transition under sustained lag (no per-tick re-emission). (iii) own-DLQ growth-rate throttle: feed 60 poisoned events to a maint agent within 60s, assert emit-rate halves, no immediate self-isolation (that's the §8.10 hard threshold). (iv) bus circuit-breaker: kill the bus mid-emit, assert spool fills, restore bus, assert spool drains in arrival order.
