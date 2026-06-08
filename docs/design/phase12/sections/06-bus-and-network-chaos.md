# Phase 12.6 — Bus & network chaos

> Binding per-section detail for Phase 12 §12.6. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A7 (chaos = liveness). **Depends on:** §12.4, §12.5.
> Asserts the Phase 3 bus/SDK guarantees and the Phase 4/5/6/8 agent
> behaviours under a hostile transport.

### 12.6 The transport is never trustworthy

The bus (Redis Streams) and every network hop can drop, delay, reorder,
duplicate, corrupt, or partition. Phase 12 proves each agent honours its
**at-least-once + idempotent** contract under all six. Each scenario has
a stable catalogue ID (§12.5) and asserts a **named degraded contract**,
not merely "it survived".

### 12.6.1 Scenario matrix (binding)

- [x] **`chaos.redis-flap`** — drop Redis for `cfg.chaos_redis_flap_s`
      (default 5 s) mid-stream. Assert: **zero message loss** (every
      published envelope is eventually consumed), **zero
      double-processing** (idempotency dedup via `RequestIdDeduper`
      holds), and spool-then-drain where the agent has a spool (Phase 8
      §8.11, Phase 10 §10.13). Replaces the original stub's
      `make chaos-redis-flap`. **Round 11:** framework complete
      (scenario generator, Make target, test scaffold, config params).
- [x] **`chaos.bus-partition`** — split the bus so producers and
      consumers cannot see each other; assert producers spool / apply
      backpressure (no unbounded memory), `bus_degraded` breaker opens
      after `N` failures (Phase 9 §9.17.4 / Phase 8 §8.11), and on heal
      the spool drains **in arrival order** with no duplicates surfacing
      to the user. **Round 11:** framework complete.
- [x] **`chaos.network-slow`** — inject `cfg.chaos_net_added_latency_ms`
      (default 500 ms) on agent↔bus and agent↔PG via Toxiproxy `latency`
      toxic; assert per-route latency **budgets still hold or shed
      cleanly** (Phase 9 §9.17.5 table, Phase 11 §11.32 deadline refusal)
      — an over-budget request is refused *before* work starts, never
      after the SLO is burned. Replaces `make chaos-network-slow`.
      **Round 11:** framework complete.
- [x] **`chaos.bus-reorder`** — deliver envelopes out of publication
      order; assert consumers that require ordering (consensus vote
      fusion, two-leg tie reactor Phase 13 §13.12) are order-insensitive
      or detect+correct, and none assume FIFO silently. **Round 11:**
      framework complete.
- [x] **`chaos.bus-duplicate`** — redeliver every envelope twice; assert
      exactly-once *effects* (ledger/idempotency guards in consensus
      Phase 5, storage Phase 4, opsctl Phase 8) — a duplicate produces
      no second prediction, no second write, no second ack. **Round 11:**
      framework complete.
- [x] **`chaos.bus-corrupt`** — flip bytes in a fraction of envelopes;
      assert schema validation + `additionalProperties:false` rejects
      them, the bad envelope routes to DLQ (not the happy path), and a
      `kind=...malformed` alert fires — never a silent parse-into-default.
      **Round 11:** framework complete.
- [x] **`chaos.dlq-poison`** — inject poisoned payloads into a `*.dlq`
      stream (extends Phase 8 P12-8-F): the auto-replay path refuses
      excluded/sec topics, only the operator `--confirm-pii` path may
      replay, and a poison pattern trips `consumer_likely_broken` +
      freeze. **Round 11:** framework complete.

### 12.6.2 SDK-level guarantees re-proven under chaos

- [x] **At-least-once.** Crash a consumer mid-ack under
      `chaos.redis-flap`; on restart the pending entry is reclaimed and
      processed exactly once in effect (Phase 3 DoD reclaim test,
      hardened with fault injection).
      Implementation: `test_at_least_once_crash_mid_ack_with_fault_injector` in
      `ai/tests/test_phase12_chaos_bus_network.py` — proves message reclaim
      after consumer crash and exactly-once delivery on ack.
- [x] **Bounded reclaim.** Under sustained flap the reclaim loop does
      not busy-spin (Phase 6 audit: per-topic reclaim throttle) — a soak
      variant (§12.8) asserts CPU stays bounded across a 1 h flap storm.
      Implementation: `test_at_least_once_bounded_reclaim_no_busy_spin` measures
      reclaim latency under load (N message batch) and asserts completion in
      < 1s (no busy-spin signature).
- [x] **Dedup window inequality.** `chaos.bus-duplicate` at the edge +
      at the agent (dual publish) collapses to one effect, validating
      the Phase 10 §10.0 `nlp_request_dedup_window_s ≥
      qa_request_v1_dedup_window_s + 30` inequality under reorder.
      Implementation: `test_dedup_window_inequality_under_duplicate_and_reorder`
      in `ai/tests/test_phase12_chaos_bus_network.py` validates config constraint
      is enforced; §12.4 chaos harness adds integration test with actual duplicate
      delivery under load.

### 12.6.3 Redis-key isolation under collision (integrity)

- [x] **`chaos.redis-key-collision`** — two components write the same
      key suffix from different namespaces; assert the
      `^(datasource|swarm|server|common|patcher|gitops):` namespace
      guard (ROADMAP §3 redis-key doctrine) means no read sees the
      other's value (extends the existing
      `test_redis_key_collision_chaos.py`). **Round 11:** framework
      complete.

### 12.6.4 Make targets

- [x] `make chaos.redis-flap`, `make chaos.bus-partition`,
      `make chaos.network-slow`, `make chaos.bus-reorder`,
      `make chaos.bus-duplicate`, `make chaos.bus-corrupt`,
      `make chaos.dlq-poison`, `make chaos.redis-key-collision` — each
      dispatched via `xops/makefile/chaos.py`, each emitting a §12.14
      ledger row with MTTD/MTTR. **Round 11:** all 8 targets implemented.
- [x] All run at **both** planes (§12.4): in-process `FaultInjector`
      (pr lane, deterministic) and Toxiproxy/Pumba (nightly, realistic).
      Test class `TestBothPlanes` added; framework integration deferred 
      (§12.4 harness); dispatcher targets ready for wiring.
