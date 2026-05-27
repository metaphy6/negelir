# Phase 9.9 — Idempotency, cache, backpressure (deeper than §9.3)

> Extracted from `docs/planning/ROADMAP.md` §9.9
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.9 Idempotency, cache, backpressure (deeper than §9.3)

- [x] **Backpressure on the bus.** When Redis Streams `XLEN predict.request.v1 > cfg.api_predict_request_backlog_high` (default 5000), API switches to **cache-only mode**: GET serves cache or 503; POST `/v1/qa` returns `425 too_early` with `Retry-After: 10`. Backpressure flag held in Redis `api:backpressure:on` with TTL 30s, refreshed by the §8.x scaler when it sees the same lag — NOT by the API itself (the API does not write to maint plane). Boundary test: API never publishes `maint.event.v1` / `sec.alert.v1`; AST scan asserts.
- [x] **Cache invalidation respect.** Phase 4 `CacheInvalidationReactor` writes `cache:<key>:gen` integers; API reads + GETs as `cache.v1<key, gen>`. Stale-gen reads bypass cache (`X-Cache: bypass`).
- [x] **Backpressure on the response side.** Slow client (TCP send buffer full > `cfg.api_response_write_timeout_ms` default 5000): `c.Writer.CloseNotify()` → audit row `status=499 client_disconnected`, abort handler. **Never** keep a goroutine blocked on a slow client — DoS surface.
- [x] **Connection caps.** `http.Server.MaxHeaderBytes = 32 KB`; `http.Server.IdleTimeout = 60s`; `cfg.api_max_concurrent_requests` (default 5000) enforced via a semaphore middleware — overflow returns 503 immediately.
