# Phase 9.17 — Performance hardening & resilience patterns (binding)

> Extracted from `docs/planning/ROADMAP.md` §9.17
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.17 Performance hardening & resilience patterns (binding)

> **Why this section exists.** §9.1–§9.16 specify *what* the API does. §9.17
> specifies *how fast* and *how robustly* it does it. Every item here is
> a binding contract — if a code change regresses any of them, CI must
> fail. The targets below are p95/p99 wall-clock on a 2-vCPU/4-GiB
> container under `cfg.api_max_concurrent_requests` load, measured by
> `make api.bench` (k6 driver, NEW; lands with this section).

#### 9.17.1 Go runtime tuning (refuse-to-start gates)

- [x] **`GOMAXPROCS` from cgroup.** Import `go.uber.org/automaxprocs` (single tiny dep, no transitive). Boot log line `runtime.gomaxprocs=<N> source=cgroup|env|default`. **Boundary test:** `runtime.GOMAXPROCS(0)` ≤ container CPU quota — refuse boot when over (prevents the 64-core scheduler thrash on a 2-vCPU pod).
- [x] **`GOMEMLIMIT` mandatory.** `cfg.api_go_mem_limit_mib` (default 80% of cgroup `memory.max` resolved at boot via `xops/api/cgroup_probe.go`). Set via `debug.SetMemoryLimit(bytes)`. Refuse boot if cgroup limit unreadable AND `cfg.api_go_mem_limit_mib=0` (forbids unbounded heap).
- [x] **`GOGC` tuned, not default.** `cfg.api_go_gc_percent=50` (default 100 is too lazy under our allocation pattern — JSON encode + Redis pipeline). `debug.SetGCPercent(cfg)`. **Proof:** `test_gc_pause_p99_under_5ms` runs the bench corpus and asserts `runtime/metrics` `/gc/pauses:seconds` p99 ≤ 5ms.
- [x] **No `init()`-time allocation > 1 MiB.** AST scan rejects `make([]T, > 1<<20)` and `bytes.Repeat(..., > 1<<20)` outside `_test.go`. Heap baseline at first request must be < 32 MiB on a no-traffic pod (boot probe asserts via `runtime.ReadMemStats`).
- [x] **`net/http` server defaults overridden** (Go defaults are wrong for public APIs):
  - `ReadHeaderTimeout = cfg.api_read_header_timeout_ms` (default 5s) — Slowloris defense.
  - `ReadTimeout = cfg.api_read_timeout_ms` (default 10s).
  - `WriteTimeout = cfg.api_write_timeout_ms` (default 15s — must exceed `api_request_timeout_ms` + `api_response_write_timeout_ms`; boot validator enforces).
  - `IdleTimeout = cfg.api_idle_timeout_ms` (default 60s).
  - `MaxHeaderBytes = 32 << 10`.
  - `H2C` enabled via `golang.org/x/net/http2/h2c` for in-mesh gRPC-over-HTTP/2 future-compat (does NOT enable HTTP/2 cleartext on the public listener — only on the in-cluster sidecar listener, behind mTLS).

#### 9.17.2 Hot-path zero-allocation discipline

- [x] **Response writer pooling.** `internal/api/respond/pool.go` — `sync.Pool` for `*bytes.Buffer` (returned with `Cap() ≤ 64 KiB`; oversize buffers are dropped not pooled — prevents pinning 1 MiB buffers from one giant QA reply). Every JSON response goes through `respond.JSON(w, status, payload)` which acquires from pool, encodes via a pooled `*json.Encoder` with `SetEscapeHTML(false)`, writes, returns. **Proof:** `test_respond_zero_alloc` uses `testing.AllocsPerRun` to assert ≤ 4 allocs per JSON response on the cache-hit path.
- [x] **Header allocation discipline.** Headers set via `w.Header().Set(...)` only on values whose key/value are pre-canonicalized at compile time (constants in `internal/api/headers/keys.go`). No `fmt.Sprintf` in the response-write hot path (lint rule).
- [x] **String concatenation in hot path.** Every `+` on strings inside the request handler is an `strings.Builder` or a `strconv.AppendInt(buf, ...)` instead. Lint rule: `staticcheck -checks SA6005,SA1019` + custom `xops/lint/no_hot_concat.py` AST scan over `internal/api/handlers/`.
- [x] **JSON decoder reuse for request bodies.** `decoder := json.NewDecoder(io.LimitReader(r.Body, cfg.api_request_max_bytes)); decoder.DisallowUnknownFields()`. **Boundary:** `DisallowUnknownFields()` MUST be on for every POST/PATCH handler (defense-in-depth alongside OpenAPI schema validator); AST scan asserts.
- [x] **`io.Copy` with pre-sized buffer.** Where the response body is streamed (not envisioned for v1 but reserved for `/v1/leagues/.../export.csv` future), `io.CopyBuffer` with a 32 KiB pooled buffer; never `io.Copy` (allocates 32 KiB per call).

#### 9.17.3 Connection pool sizing (Postgres, Redis, bus)

- [x] **PostgreSQL via `pgxpool`** (NOT `database/sql` — pgx is faster + binary protocol + COPY support).
  - `cfg.api_pg_pool_max_conns` = `min(cgroup_cpu * 4, pg_max_connections * 0.25 / replicas)`; default = 25 per pod, formula validated at boot — refuse if it would push the cluster past 80% of `pg_max_connections`.
  - `MaxConnIdleTime = 5m`, `MaxConnLifetime = 1h`, `MaxConnLifetimeJitter = 5m` (avoids thundering-herd reconnect at the hour mark).
  - `HealthCheckPeriod = 30s`. `BeforeConnect` sets `application_name = "negelir-api/<pod_instance_id>"` (so DBA can attribute load).
  - `statement_cache_capacity = 256` per conn (named-prepared statements for hot queries — `users SELECT BY email_lower`, `match_normalized SELECT BY id`, audit INSERT).
  - **Read replica routing** (built but dormant — `cfg.api_pg_replica_url=""` default): when set, GETs route to replica; POSTs/PATCHes always primary. Replica lag check via `pg_last_wal_replay_lsn` every `cfg.api_pg_replica_lag_check_s=10`; lag > `cfg.api_pg_replica_lag_max_ms=500` falls back to primary + emits `sec.alert.v1{kind=pg_replica_lag_high}`.
- [x] **Redis via `go-redis/v9`** with two distinct clients (don't share — different SLOs):
  - `cacheClient`: `PoolSize = cfg.api_redis_cache_pool_size` (default 50), `MinIdleConns = 10`, `PoolTimeout = 100ms` (fail fast — fall through to MISS).
  - `busClient` (for XREAD reply streams): `PoolSize = cfg.api_redis_bus_pool_size` (default 20), `ReadTimeout = api_request_timeout_ms + 500ms` (XREAD BLOCK budget).
  - `MaxRetries = 0` on both — retries belong in the resilience layer (§9.17.4), not silently in the driver.
  - **Pipelining** for batched audit writes (§9.17.7).
- [x] **No connection pool per request.** Lint rule: `pgx.Connect`/`redis.NewClient` called outside `internal/bootstrap/` is a build error.

#### 9.17.4 Resilience: circuit breakers, bulkheads, hedging, retry budgets

- [x] **Circuit breaker per upstream** (`pg`, `redis_cache`, `redis_bus`, `swarm_rpc`). Implementation: `sony/gobreaker` (one tiny dep). States: `closed → open → half-open`. Trip on `cfg.api_breaker_fail_ratio=0.5` over `cfg.api_breaker_window_s=10` window with `cfg.api_breaker_min_requests=20`. Open duration `cfg.api_breaker_open_s=15`; half-open admits 1 probe. **Open state behavior:** PG-open → 503 `service_unavailable` for endpoints that need PG; cache-open → bypass cache (fall through to RPC); bus-open → 503 `bus_unreachable`. **Per-breaker `sec.alert.v1`** kinds: `breaker_opened`, `breaker_half_open`, `breaker_closed` (severity=warn, debounced 60s).
- [x] **Bulkhead per upstream.** Bounded semaphore (`golang.org/x/sync/semaphore`) sized to `pool_size * 0.8` — last 20% of pool reserved for `/v1/healthz` + `/v1/readyz` so a saturated app surface never starves liveness. **Proof:** `test_bulkhead_protects_healthz` saturates PG bulkhead; `/v1/healthz` still responds < 50ms.
- [x] **Hedged RPC for cache-miss reads** (defeats long-tail latency). For GET `/v1/matches/:id/predictions` cache-MISS: publish primary `predict.request` at t=0; if no reply by `cfg.api_hedge_after_ms=200` AND `cfg.api_hedging_enabled=true` AND p99 of recent RPC latency > p50 × 3, publish a HEDGE `predict.request` with `request_id_hedge=<original>:h1`. First reply wins; both are dedup'd at the `consensus.v1` ledger via existing idempotency on `request_id` (the `:h1` suffix is stripped before the consensus dedup key — design: hedge is request-level, not consensus-level). **Hedge budget:** `cfg.api_hedge_budget_pct=10` of recent total RPC count; never hedge more than 10% of traffic. **Proof:** `test_hedge_budget_capped` floods misses; assert hedge count ≤ 10%.
- [x] **Singleflight for cache-MISS** (different from §9.3 SWR — that's stale-revalidate). `golang.org/x/sync/singleflight` keyed on `(match_id, market_set, calibration_version)`. 1000 concurrent cache-MISS requests for the same key fan out to ONE `predict.request` and all wait on the same RPC. **Proof:** `test_singleflight_collapses_cache_miss_herd` — 500 parallel MISS for same match → exactly 1 `predict.request` published.
- [x] **Retry budget (token bucket per upstream).** Naive retry-on-failure amplifies outages. Token bucket: `cfg.api_retry_budget_per_s=10` tokens/s + `cfg.api_retry_budget_capacity=50` burst per upstream. Out-of-budget retries are FAILED IMMEDIATELY (no extra latency, no extra load). **Proof:** `test_retry_budget_prevents_amplification` — sustained upstream failure; retry rate caps at budget.
- [x] **Deadline propagation.** Every outbound call (`pg`, `redis`, `bus`) takes `ctx` derived from `r.Context()` with `context.WithTimeout(ctx, remaining_budget)`. Remaining budget = `request_deadline - now() - jitter_safety(50ms)`. **Boundary:** AST scan rejects `context.Background()` / `context.TODO()` in `internal/api/handlers/`.
- [x] **Panic recovery middleware.** Top-of-stack `defer recover()` — emits `sec.alert.v1{kind=api_panic, severity=critical}` with stack-trace SHA256 (NOT the trace itself; trace goes to local stderr only — PII risk in handler args), then `500 internal`. **Proof:** `test_panic_recovery_emits_alert_and_500` — handler panics; client sees 500; alert fires; pod stays up.
- [x] **Graceful shutdown.** SIGTERM → stop accepting new conns (`server.Shutdown(ctx)` with `cfg.api_shutdown_grace_s=30`) → drain in-flight (semaphore wait) → close PG pool → close Redis pool → publish final `api.response.v1` rows for in-flight → exit 0. K8s `preStop` hook = `sleep 5` to bridge endpoint-removal lag. **Proof:** `test_graceful_shutdown_drains_inflight` — start 10 long-running requests; SIGTERM; all complete with 200; new requests during drain get 503 + `Connection: close`.

#### 9.17.5 Per-endpoint latency budgets (binding SLO floors — tighter than §9.8)

| Route | p50 | p95 | p99 | Notes |
|---|---|---|---|---|
| `GET /v1/healthz` | ≤ 1ms | ≤ 5ms | ≤ 10ms | No I/O; reserved bulkhead. |
| `GET /v1/readyz` | ≤ 10ms | ≤ 50ms | ≤ 100ms | PG/Redis/bus 1-byte pings, parallel. |
| `GET /v1/version` | ≤ 1ms | ≤ 5ms | ≤ 10ms | In-memory chart snapshot. |
| `GET /v1/leagues` | ≤ 5ms | ≤ 25ms | ≤ 50ms | Cache-hit path. |
| `GET /v1/matches/:id` | ≤ 5ms | ≤ 25ms | ≤ 50ms | Cache-hit path. |
| `GET /v1/matches/:id/predictions` (cache hit) | ≤ 5ms | ≤ 25ms | ≤ 50ms | — |
| `GET /v1/matches/:id/predictions` (cache miss) | ≤ 200ms | ≤ 800ms | ≤ 2000ms | RPC path; hedge active. |
| `POST /v1/auth/login` | ≤ 250ms | ≤ 350ms | ≤ 500ms | bcrypt-bound (cost=12 ≈ 250ms). |
| `POST /v1/auth/refresh` | ≤ 5ms | ≤ 20ms | ≤ 50ms | Redis lookup + JWT sign. |
| `POST /v1/qa` (cache hit) | ≤ 10ms | ≤ 50ms | ≤ 100ms | — |
| `POST /v1/qa` (single RPC) | ≤ 250ms | ≤ 800ms | ≤ 2000ms | — |
| `POST /v1/qa` (multi-RPC, 202 path) | ≤ 50ms | ≤ 100ms | ≤ 200ms | Returns immediately with `qa_correlation_id`. |

- [x] **`make api.bench`** (NEW; xops patch): k6 driver hits each endpoint at `cfg.api_bench_target_rps` (default 200 RPS) for 60s against the compose stack with mock predictors. Asserts every row above. CI gate: bench job runs nightly + on PRs touching `server/internal/api/**`.
- [x] **Latency histogram per route** in `api_request_duration_seconds_bucket{route, method}` with buckets `[1ms, 5ms, 10ms, 25ms, 50ms, 100ms, 200ms, 500ms, 1s, 2.5s]` — sized for the table above (default Prometheus buckets are `[5ms..10s]` which crushes resolution at our scale).

#### 9.17.6 Caching layers (in-memory L0 ahead of Redis L1)

- [x] **In-process LRU L0** (`hashicorp/golang-lru/v2`) for the hottest keys per pod. Sized: `cfg.api_l0_cache_max_entries=10000`, eviction on entry count + `cfg.api_l0_cache_max_bytes=64 << 20` (64 MiB cap). TTL per entry = `min(cache.v1 TTL, cfg.api_l0_max_ttl_s=5)` — short TTL so cache invalidation only needs to reach Redis, not every pod.
- [x] **Negative cache.** 404s on `/v1/matches/:id` cached in L0 for `cfg.api_negative_cache_s=10` to absorb scrape bots probing random IDs. Scope: only 404 + 410; never 5xx (would mask transient outages).
- [x] **Cache stampede protection beyond singleflight.** When L0 entry expires, only one goroutine fetches; others wait on a per-key `sync.Cond` (max wait = `cfg.api_l0_refresh_max_wait_ms=200` then fall through to direct fetch — bounded queue depth).
- [x] **L0 invalidation respects `cache:<key>:gen`.** Background goroutine per pod subscribes to Redis keyspace notifications (`__keyevent@0__:set` on `cache:*:gen`) and evicts matching L0 entries within `cfg.api_l0_invalidation_lag_max_ms=500`. Fallback: every L0 read also checks the gen counter (extra Redis round-trip on hit, cheap pipeline). **Proof:** `test_l0_invalidation_within_500ms` — write to `cache:X:gen`; assert L0 eviction within budget.

#### 9.17.7 Audit pipeline performance

- [x] **`api.request.v1` + `api.response.v1`** writes are the hottest publish path. Batched via Redis pipeline — `cfg.api_audit_batch_max=64` rows or `cfg.api_audit_batch_max_ms=10ms`, whichever first. Boundary: batching MUST NOT delay the response — audit publish is on a separate goroutine fed by a bounded channel `cfg.api_audit_chan_cap=4096`. **Channel-full policy:** drop the audit row + emit `sec.alert.v1{kind=api_audit_dropped, severity=warn}` (debounced 60s). **NEVER** block the response on audit (audit is fan-out, not gating).
- [x] **Audit shipper backpressure.** When the channel is > 80% full for > 5s, switch to sampling at `cfg.api_audit_sample_pct_under_pressure=10%` for 2xx; **always 100% for 4xx/5xx + sec-relevant events** (login attempts, revocations). Restore 100% when channel < 50% for 30s.
- [x] **`audit_log_integrity_break` recovery.** If hash-chain verifier (§8.13.2) detects a break in the API audit chain, API switches to **chain-rewrite-quarantine** mode: subsequent rows append to `api_audit_log_quarantine` partition until operator runs `make audit.repair-api`. Reads / writes to the public surface are **NOT blocked** — audit integrity is not a request-path dependency.

#### 9.17.8 TLS / TCP performance

- [x] **TLS session resumption.** `tls.Config.ClientSessionCache = tls.NewLRUClientSessionCache(1024)` for outbound mTLS (PG, Redis, bus). Inbound: `SessionTicketKey` rotated every 24h via `make api.rotate-tls-session-key` (separate from cert rotation; cert rotation triggers session cache flush implicitly).
- [x] **TLS cipher suite pin.** Server only accepts TLS 1.3 + TLS 1.2 with the AEAD ciphers (`TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`, `TLS_ECDHE_*_GCM_*`). Boot validator pins via `tls.Config.MinVersion = tls.VersionTLS12 + CipherSuites = [...]`.
- [x] **TCP_NODELAY enabled** on the listener (Go default for HTTP servers, but assert via `SO_KEEPALIVE` probe + `TCP_USER_TIMEOUT` set to `cfg.api_tcp_user_timeout_ms=20000`).
- [x] **`SO_REUSEPORT` on Linux** (via `socketreuse` package or raw `syscall.Setsockopt`) — multiple acceptor goroutines, one per `GOMAXPROCS`. Boundary: asserted at boot via `lsof -i :<port>` parity test in dev (`make api.up && make api.assert-reuseport`).
- [x] **HTTP/2 enabled on inbound** (default in `net/http` w/ TLS; explicitly assert at boot — no `H2_DISABLED` accidental disablement).

#### 9.17.9 Backpressure feedback loops (closed-loop, not open-loop)

- [x] **PID-style adaptive rate limiter** on top of §9.7 fixed buckets. When `api_requests_total{status=~"5.."}` rate exceeds `cfg.api_adaptive_error_rate_threshold=0.02` over 30s, the adaptive controller multiplies all subject-key bucket refill rates by `cfg.api_adaptive_shed_factor=0.5` for `cfg.api_adaptive_shed_duration_s=60`. Restored gradually (`* 1.1` per 10s) once error rate drops below threshold. **Proof:** `test_adaptive_shed_engages_on_error_burst` — synthesize 5xx burst; assert refill rate halved within 30s.
- [x] **Inflight-aware shedding.** When `api_inflight_rpcs / api_max_concurrent_requests > 0.85` for > 5s, return 503 IMMEDIATELY for new requests with `tier_id < cfg.api_priority_tier_floor` (dormant — defaults to 0, all requests equal until §20). Headers: `X-Shed-Reason: inflight_pressure`, `Retry-After: 5`.
- [x] **Bus-feedback signal.** Subscribe to `maint.event.v1{kind=scaler_replicas_pinned}` (§8.x scaler emits when pinning above target due to lag). When fired, API enters degraded-mode banner — sets `X-Degraded-Cluster: true` on every response, encourages clients to widen their own retry intervals.

#### 9.17.10 Observability for performance

- [x] **`pprof` endpoint on the metrics port** (`:9091/debug/pprof/*`) — never on the public listener. Authenticated via cluster-internal mTLS only; `cfg.api_pprof_enabled=true` default in dev, `false` in prod (operator opts in for live debugging via `make api.pprof-enable POD=...` which short-lives a flag in Redis `api:pprof:<pod>` TTL 1h).
- [x] **Continuous CPU profiling sample.** 10-second profile every 10 minutes shipped to `data/api/profiles/<pod>/<utc>.pprof.gz` (rotated, max 7d). Operator inspects via `make api.profile-show LATEST`. Cost: < 1% CPU overhead.
- [x] **Allocation tracking gauge.** `api_alloc_per_request_bytes` histogram (computed from `runtime.MemStats.Mallocs` delta around `ServeHTTP` — sampled at `cfg.api_alloc_sample_rate=0.001`; 1 in 1000 requests). Regression alert: p99 > 50 KiB → `sec.alert.v1{kind=api_alloc_regression, severity=warn}`.

#### 9.17.11 Definition of Done additions (binding, on top of §9.13)

- [x] All `[ ]` items in §9.17.1–§9.17.10 ticked.
- [x] `make api.bench` green on every PR touching `server/internal/api/**` or `server/internal/handlers/**`.
- [x] `runtime/metrics` GC pause p99 ≤ 5ms under bench load.
- [x] All breakers + bulkheads have a documented runbook entry in `docs/guides/api_runbook.md` (which states to do when each fires).
- [x] `test_l0_invalidation_within_500ms`, `test_singleflight_collapses_cache_miss_herd`, `test_hedge_budget_capped`, `test_bulkhead_protects_healthz`, `test_panic_recovery_emits_alert_and_500`, `test_graceful_shutdown_drains_inflight`, `test_retry_budget_prevents_amplification`, `test_adaptive_shed_engages_on_error_burst`, `test_respond_zero_alloc`, `test_gc_pause_p99_under_5ms` — all green.
- [x] Triangle test extends to ~30 new cfg knobs introduced by §9.17 (Python config side adds them as documented mirrors even though the code path is Go-only — keeps the single-source doctrine intact).
- [x] `chart.json` `compatibility` block updated with min versions of `gobreaker`, `automaxprocs`, `golang-lru/v2`, `pgx/v5`, `go-redis/v9`, `golang.org/x/sync` pinned (no `*-latest`; per CLAUDE.md doctrine).

#### 9.17.12 Knob inventory addendum (extends §9.12)

`api_go_mem_limit_mib=0` (0 = derive from cgroup), `api_go_gc_percent=50`, `api_read_header_timeout_ms=5000`, `api_read_timeout_ms=10000`, `api_write_timeout_ms=15000`, `api_idle_timeout_ms=60000`, `api_pg_pool_max_conns=25`, `api_pg_replica_url=""`, `api_pg_replica_lag_check_s=10`, `api_pg_replica_lag_max_ms=500`, `api_redis_cache_pool_size=50`, `api_redis_bus_pool_size=20`, `api_breaker_fail_ratio=0.5`, `api_breaker_window_s=10`, `api_breaker_min_requests=20`, `api_breaker_open_s=15`, `api_hedge_after_ms=200`, `api_hedging_enabled=true`, `api_hedge_budget_pct=10`, `api_retry_budget_per_s=10`, `api_retry_budget_capacity=50`, `api_shutdown_grace_s=30`, `api_l0_cache_max_entries=10000`, `api_l0_cache_max_bytes=67108864`, `api_l0_max_ttl_s=5`, `api_negative_cache_s=10`, `api_l0_refresh_max_wait_ms=200`, `api_l0_invalidation_lag_max_ms=500`, `api_audit_batch_max=64`, `api_audit_batch_max_ms=10`, `api_audit_chan_cap=4096`, `api_audit_sample_pct_under_pressure=10`, `api_tcp_user_timeout_ms=20000`, `api_adaptive_error_rate_threshold=0.02`, `api_adaptive_shed_factor=0.5`, `api_adaptive_shed_duration_s=60`, `api_priority_tier_floor=0`, `api_pprof_enabled_dev=true`, `api_pprof_enabled_prod=false`, `api_alloc_sample_rate=0.001`, `api_jwt_clock_skew_s=30`, `api_bench_target_rps=200`.

#### 9.17.13 New `sec.alert.v1` kinds (open-enum; mirrors §7.4 doctrine)

`breaker_opened`, `breaker_half_open`, `breaker_closed`, `pg_replica_lag_high`, `api_panic`, `api_audit_dropped`, `api_alloc_regression`, `api_adaptive_shed_engaged`, `api_adaptive_shed_lifted`, `api_inflight_pressure_shed`, `api_l0_invalidation_lag`, `api_hedge_budget_exhausted`. Each carries `event_correlation_id` per §8.16.9; producer set bounded to `api.gateway.v1`.

---
