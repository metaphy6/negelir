# Phase 9.1 — Surface (v1) — full route table + semantics

> Extracted from `docs/planning/ROADMAP.md` §9.1
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.1 Surface (v1) — full route table + semantics

```
# Liveness (separate from readiness — K8s probes need both)
GET    /v1/healthz                                  # liveness — process up; never depends on PG/Redis/bus
GET    /v1/readyz                                   # readiness — PG/Redis/bus all green AND this pod owns ≥1 fresh `cache.v1` entry
GET    /v1/version                                  # build SHA + chart.json snapshot

# Catalog (read-mostly; Phase 4 `cache.v1` warm)
GET    /v1/leagues                                  # paginated, cursor
GET    /v1/leagues/{league_id}/fixtures?from=&to=   # `from`/`to` ISO-8601 UTC, ≤ cfg.api_fixture_window_max_days (default 14)
GET    /v1/matches/{match_id}                       # ETag = match_normalized.row_hash

# Predictions (RPC against swarm — Phase 5 path)
GET    /v1/matches/{match_id}/predictions?market=   # comma-separated markets ⊆ cfg.api_allowed_markets
                                                    # ETag = prediction_id
                                                    # Response carries: produced_at, calibration_version,
                                                    #                   degraded, degraded_reason, prediction_id
                                                    # 503 + Retry-After when consensus times out AND no cache
                                                    # 410 Gone when match_id retired (Phase 13b deprecation)

# Q&A (Phase 10 NLP — body sanitized through sec.input.v1, fanned out to predict.requests via qa_correlation_id per §8.16.12)
POST   /v1/qa                                       # body { "q": str (≤ cfg.qa_input_max_bytes), "locale": "tr-TR" }
                                                    # 202 + qa_correlation_id when answer needs >1 predict.request
                                                    # 200 inline when answer is single-source / cache-hit

# Identity
POST   /v1/auth/register                            # locked behind cfg.api_self_registration_enabled (default false)
POST   /v1/auth/login                               # → access (15m) + refresh (30d, rotated on use)
POST   /v1/auth/refresh                             # rotates refresh; old refresh blacklisted in Redis until original expiry
POST   /v1/auth/logout                              # revokes refresh; access tokens unaffected (short TTL is the policy)
GET    /v1/me                                       # JWT-derived; never reads bus
PATCH  /v1/me                                       # tz, locale, notification opt-ins; bcrypt re-hash on password change

# Operator / dormant tier surface (built but dormant per §9.15)
GET    /v1/me/quota                                 # returns tier + remaining/window; static when tier-flag disabled
```

- [x] **Content-type discipline.** Every response is `application/json; charset=utf-8`. Errors follow RFC 7807 `application/problem+json`. **Boundary test:** every handler in `server/internal/handlers/` returns one of the two; `text/html` / `text/plain` body bytes rejected at the response-writer wrapper.
- [x] **Time discipline.** Every timestamp ISO-8601 UTC with `Z` suffix; never local zone, never naïve, never epoch-int in JSON output (epoch only for ETag derivation). Triangle test: cfg knob `cfg.api_time_format="iso8601_utc"` is the only legal value (config validator rejects anything else — leaves room for future `rfc9557` extension behind a flag, not a typo).
- [x] **Pagination = opaque encrypted cursor, NEVER offset.** Cursor body = `AES-GCM(seal_key, json{table, last_pk, query_filter_hash, expires_at_unix})`; seal_key in `data/api/cursor_key` (mode 0400, rotated alongside JWT keys per §9.2). Cursor TTL = `cfg.api_cursor_ttl_s` (default 1800s). Tampered / expired cursors → `400 invalid_cursor`. Filter-hash mismatch (caller changed `from=` mid-pagination) → `409 cursor_filter_drift`. **Proof tests:** (a) tampered byte at any position → 400; (b) cursor older than TTL → 400; (c) different `from=` than the one that minted the cursor → 409; (d) cursor minted with rotated-out key → 400 (graceful) NOT panic.
- [x] **Header inventory (binding).** Request: `Authorization: Bearer <jwt>`, `Idempotency-Key: <client-uuid-v4>` (POST /v1/qa + POST /v1/auth/* only; mandatory for POST mutations), `If-None-Match: <etag>`, `Accept-Language` (Phase 10 picks Turkish even if missing), `X-Forwarded-For` (consumed via §7.6 `DeriveClientIP`), `X-Request-ID` (echoed back; if absent, server mints a UUIDv7 — sortable). Response: `ETag`, `X-Request-ID`, `X-RateLimit-Remaining` / `X-RateLimit-Reset` (per-token + per-IP both echoed; lower wins), `X-Prediction-Id`, `X-Calibration-Version`, `X-Degraded` (`true` if `degraded`), `X-Cache` (`hit|miss|stale|bypass`), `Sunset` (RFC 8594, set when route is in deprecation window per §9.11), `Retry-After` (on 429/503).
- [x] **HTTP error taxonomy (closed enum, mirrors `internal/errors/codes.go`).** Codes: `400 invalid_request | invalid_cursor`, `401 unauthenticated | token_expired | token_revoked`, `403 forbidden | tier_required`, `404 not_found | match_retired`, `409 conflict | cursor_filter_drift | idempotency_key_replay_with_different_body`, `410 gone`, `413 payload_too_large`, `415 unsupported_media_type`, `422 unprocessable | qa_quarantined`, `425 too_early` (consensus warming, retry hinted), `429 rate_limited | tier_quota_exceeded | denylisted` (`Retry-After`), `499 client_disconnected` (audit-only, never sent), `500 internal` (rate-limited log; no stack to client), `502 upstream_consensus_failure`, `503 service_unavailable | bus_unreachable | consensus_window_blown` (`Retry-After`), `504 rpc_timeout`. **Boundary test:** every code emitted by the handlers is in the enum; AST scan asserts no `c.JSON(503, gin.H{"error": "..."})` ad-hoc strings outside `internal/errors`.
- [x] **Body-size cap (defense in depth, even before §7.6 sec gate).** `cfg.api_request_max_bytes` (default 64 KB; `/v1/qa` sub-cap = `cfg.qa_input_max_bytes`; `/v1/auth/login` sub-cap = 4 KB). Server-side `http.MaxBytesReader` BEFORE handler dispatch — bcrypt-bomb / RAM-exhaustion defense. Returns `413` with `application/problem+json`.
