// Package middleware provides Phase 9 Gin middleware for the API gateway.
//
// Middleware chain (applied outermost-first):
//   - RequestID         — mints UUIDv7 X-Request-ID; echoes client-supplied value
//   - BodySizeCap       — http.MaxBytesReader(cfg.api_request_max_bytes) → 413
//   - BackpressureCheck — reads api:backpressure:on (set by §8.x scaler); POST → 425 when active
//   - CacheGenCheck    — generation-aware GET cache reads (cache:<k>:gen + cache.v1:<k>:<gen>); X-Cache: hit|bypass
//   - SecGate           — delegates to server/internal/sec (Phase 7 library)
//   - Authenticate      — JWT verification; populates Gin context with claims
//   - TierQuota         — built-but-dormant; enforces tier_quota when flag enabled
//   - RateHeaders       — echoes X-RateLimit-Remaining / X-RateLimit-Reset
//   - AuditEmitter      — publishes api.request.v1 + api.response.v1
//
// No middleware in this package reimplements logic already in server/internal/sec.
package middleware
