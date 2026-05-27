# API.md — Negelir REST API Binding Contract

> **Status:** Phase 9 binding surface contract.
> **Source of truth for routes:** `server/api/openapi.yaml` (generated code
> is gated by `make api.gen-check`; this document is the human-readable
> companion).
> **Operator surfaces:** `docs/guides/api_runbook.md`.
> **Swarm integration:** see §7 (bus topics, shim registration).

---

## §1. Design constraints

| Constraint | Value |
|---|---|
| Canonical route spec | `server/api/openapi.yaml` |
| Code generator | `oapi-codegen v2` — `make api.gen` |
| Spec drift gate | `make api.gen-check` (CI) — fails on any uncommitted drift |
| Breaking-change policy | `/v1` is frozen; breaking changes cut `/v2`. Additive (new optional fields, new routes) are allowed in `/v1` without version bump. |
| Deprecation | `x-deprecated-on` + `x-sunset-on` in `openapi.yaml` → `Sunset` / `Link` response headers (§9.11); 410 Gone past sunset. |
| Time format | `iso8601_utc` — all timestamps in RFC 3339 UTC (e.g. `2026-05-26T12:00:00Z`). |
| Compute class | `cpu_only` build tag; CUDA paths excluded from binary (Phase 11 may extend). |

---

## §2. OpenAPI extension vocabulary

Every route in `openapi.yaml` carries three Phase 9 extensions.
The boot gate `api.BootValidateSpec()` refuses startup if any operation
is missing one.

| Extension | Type | Meaning |
|---|---|---|
| `x-rate-cost` | `integer` | Token cost charged to the per-subject GCRA bucket on each call. `0` = free (health probes). |
| `x-tier-required` | `string` | Minimum account tier (`none` / `free` / `pro` / `elite`). All Phase 9 routes default to `none`; dormant until Phase 20. |
| `x-idempotent-mutation` | `bool` | `true` on state-changing `POST`/`PUT`/`PATCH`/`DELETE` routes. Presence makes the `Idempotency-Key` header mandatory. |
| `x-deprecated-on` | `string` | ISO-8601 date the route entered deprecation. Drives `Sunset` header emission. |
| `x-sunset-on` | `string` | ISO-8601 date after which the route is removed (returns 410). |

---

## §3. Route inventory

### 3.1 Legacy `/api/v1` group

Kept for backward compatibility; mirrors the `/v1` group below.
All legacy routes use `x-tier-required: none`.

| Method | Path | Op-ID | Rate cost | Idempotent-mutation | Auth |
|---|---|---|---|---|---|
| GET | `/api/v1/health` | `legacyHealth` | 0 | false | none |
| GET | `/api/v1/matches` | `legacyListMatches` | 1 | false | none |
| GET | `/api/v1/matches/{id}` | `legacyGetMatch` | 1 | false | none |
| GET | `/api/v1/teams` | `legacyListTeams` | 1 | false | none |
| GET | `/api/v1/teams/{id}` | `legacyGetTeam` | 1 | false | none |
| POST | `/api/v1/scrape/trigger` | `legacyScrapeTrigger` | 3 | **true** | none |
| GET | `/api/v1/features/{match_id}` | `legacyGetFeatures` | 2 | false | none |

### 3.2 `/v1` group (stable public API)

| Method | Path | Op-ID | Rate cost | Idempotent-mutation | Auth |
|---|---|---|---|---|---|
| GET | `/v1/healthz` | `liveness` | 0 | false | none |
| GET | `/v1/readyz` | `readiness` | 0 | false | none |
| GET | `/v1/matches/{id}` | `getMatch` | 1 | false | none |
| GET | `/v1/matches/{id}/predictions` | `getPredictions` | 2 | false | none |
| POST | `/v1/qa` | `qa` | 5 | false | none |
| GET | `/v1/leagues` | `listLeagues` | 1 | false | none |
| GET | `/v1/leagues/{id}/fixtures` | `getLeagueFixtures` | 1 | false | none |
| GET | `/v1/me` | `getProfile` | 1 | false | **Bearer** |
| POST | `/v1/auth/login` | `authLogin` | 3 | **true** | none |
| POST | `/v1/auth/register` | `authRegister` | 3 | **true** | none (disabled by default) |
| POST | `/v1/auth/refresh` | `authRefresh` | 3 | **true** | none |

### 3.3 Route parameters

**Path parameters:**

| Parameter | Routes | Type | Notes |
|---|---|---|---|
| `{id}` | matches, teams, leagues | `string` | Opaque identifier (DB primary key string form). |
| `{match_id}` | `/api/v1/features/{match_id}` | `string` | Same semantic as `{id}` in v1 routes. |

**Query parameters:**

| Parameter | Routes | Type | Notes |
|---|---|---|---|
| `league` | `legacyListMatches` | `string` | League filter (optional). |
| `date` | `legacyListMatches` | `date` | ISO-8601 date filter (optional). |
| `market` | `getPredictions` | `string` | Comma-separated market IDs (default: `1x2`). Example: `1x2,btts`. |

---

## §4. Authentication

### 4.1 Token type

RS256 JWT (Phase 9 §9.2). All protected routes accept:
```
Authorization: Bearer <access_token>
```

### 4.2 Token shape

| Claim | Meaning |
|---|---|
| `sub` | User UUID (stable across token refreshes). |
| `jti` | Unique token ID — checked against the revocation deny-set on every request. |
| `exp` | Expiry (default `900` s / 15 min; `NEGELIR_API_ACCESS_TTL_S`). |
| `kid` | Key ID of the signing RS256 keypair (rotated every 90 days). |

### 4.3 Token lifecycle

1. `POST /v1/auth/login` → returns `{access_token, refresh_token, token_type: "Bearer", expires_in}`.
2. `POST /v1/auth/refresh` (with `{refresh_token}`) → new access token; refresh token is single-use with a replay-grace window (`NEGELIR_API_REFRESH_REPLAY_GRACE_S`, default 30 s).
3. `POST /v1/auth/register` — disabled by default (`NEGELIR_API_SELF_REGISTRATION_ENABLED=false`); returns 403 when disabled.
4. Access token revocation: via `make api.revoke-jti JTI=<uuid>` (runbook §5). Revoked JTIs are stored in the Redis deny-set (`auth:rev:idx`; cap `NEGELIR_API_REVOCATION_SET_MAX`, default 10 000).

### 4.4 Body-size caps (bcrypt-bomb defence)

| Route | Cap env var | Default |
|---|---|---|
| Global | `NEGELIR_API_REQUEST_MAX_BYTES` | 65 536 B |
| `/v1/qa` | `NEGELIR_QA_INPUT_MAX_BYTES` | 4 096 B |
| `/v1/auth/login` | `NEGELIR_AUTH_LOGIN_MAX_BYTES` | 4 096 B |

---

## §5. Rate limiting

### 5.1 Architecture

Two tiers enforced in sequence:

1. **Redis GCRA (primary)** — per-subject token bucket, keyed by IP subject (IPv4 /32 or configurable prefix; IPv6 /64 by default). Implemented via Lua EVALSHA (`bootLuaGates` on startup verifies SHA parity). Redis timeout: `NEGELIR_SEC_RATE_REDIS_TIMEOUT_MS` (default 50 ms).
2. **In-process secondary bucket** — GCRA bucket per subject, held in an LRU (max 50 000 subjects). Engages when Redis is unreachable.

### 5.2 Token costs per route

See §3 route table column **Rate cost**. Key costs:
- Health probes: **0** (always free).
- Standard data reads: **1**.
- Feature vector / predictions: **2**.
- Scrape trigger / auth: **3**.
- NLP Q&A: **5** (highest cost; enforces responsible use).

### 5.3 Bucket knobs

| Env var | Default | Meaning |
|---|---|---|
| `NEGELIR_API_BURST_CAPACITY` | 60 | Max tokens accumulated while idle. |
| `NEGELIR_API_BURST_REFILL_PER_S` | 2.0 | Tokens added per second. |
| `NEGELIR_SEC_RATE_PRE_AUTH_CAPACITY` | 30 | Pre-auth bucket capacity. |
| `NEGELIR_SEC_RATE_PRE_AUTH_REFILL_PER_S` | 0.5 | Pre-auth refill. |

### 5.4 Rate-limit response

HTTP `429 Too Many Requests` with headers:
```
X-RateLimit-Remaining: <tokens remaining>
X-RateLimit-Reset:     <unix epoch of next refill>
Retry-After:           <seconds>
```
Body: `{"error": "rate limit exceeded", "code": "rate_limited"}`.

---

## §6. Cache behaviour

### 6.1 Prediction SWR (stale-while-revalidate)

`GET /v1/matches/{id}/predictions` uses a two-layer SWR cache:

| Phase | Condition | Response |
|---|---|---|
| Fresh HIT | age < `NEGELIR_API_CACHE_STALE_AFTER_S` (30 s) | Served immediately; `X-Cache: hit`. |
| Stale HIT | 30 s ≤ age < `NEGELIR_API_CACHE_MAX_AGE_S` (300 s) | Served from cache + async `predict.request.v1` refresh triggered; `X-Cache: stale`. |
| MISS | age ≥ 300 s or absent | Synchronous RPC to predictor swarm. |

Pod-level SWR goroutine cap: `NEGELIR_API_SWR_INFLIGHT_MAX` (default 64).

### 6.2 Match / team list cache

`GET /api/v1/matches` and `/api/v1/teams` use a simple TTL cache:
- Matches: `CACHE_MATCHES_TTL_SEC` (default 300 s).
- Teams: `CACHE_TEAMS_TTL_SEC` (default 600 s).

### 6.3 Backpressure

When `predict.request.v1` stream is overloaded (XLEN > `NEGELIR_API_PREDICT_REQUEST_BACKLOG_HIGH`, default 5 000), the Phase 8 scaler sets Redis key `api:backpressure:on` (TTL 30 s). The `BackpressureCheck` middleware then returns `425 Too Early` for `POST /v1/qa` and any route depending on a live predictor RPC.

---

## §7. Swarm integration

### 7.1 Bus topics owned by `api.gateway.v1`

| Topic | Direction | Description |
|---|---|---|
| `api.request.v1` | **publish** | Outbound RPC request envelope to predictor swarm. |
| `api.response.v1` | **publish** | Response envelope back to the originating client coroutine. |
| `predict.cancel.v1` | **publish** | Cancels an in-flight prediction RPC (client disconnect / timeout). |
| `predict.request.v1` | **subscribe** | Inbound prediction requests from the API (read by predictor agents). |

Wire authority is enforced statically in `server/cmd/swarmctl/main.go`
`wireAuthorityProducers` map (Go side) and in `ai/swarm/sdk/wire_contracts.py`
`API_TOPIC_V1_ALLOWED_PRODUCERS` / `PREDICT_CANCEL_V1_ALLOWED_PRODUCERS`
constants (Python side). Both must be updated together when the topic set changes.

### 7.2 Agent shim registration

`api.gateway.v1` registers in two ways:

1. **Static manifest** (Phase 9 §9.13) — `swarmctl ps` always shows the shim
   via `staticAgentManifest` in `server/cmd/swarmctl/main.go`, regardless of
   Redis state.
2. **Runtime heartbeat** — the API server writes the Redis key
   `agent:api.gateway.v1:heartbeat` (SET, RFC 3339 string, no TTL) on startup.
   `swarmctl ps` reads this for the `LAST_HEARTBEAT` column. After
   `SWARM_HEARTBEAT_SEC * 3` seconds (default 15 s) without a refresh the
   entry is marked `✗STALE`.

---

## §8. Error envelope

All error responses use the `ErrorEnvelope` schema:
```json
{"error": "<human message>", "code": "<machine code>", "request_id": "<trace_id>"}
```

`request_id` mirrors the `X-Request-ID` response header (the W3C trace ID
seeded by the `TraceParent` middleware).

### 8.1 HTTP status codes

| Code | Meaning | Common cause |
|---|---|---|
| 200 | OK | Normal success. |
| 201 | Created | `POST /v1/auth/register` success. |
| 202 | Accepted | `POST /api/v1/scrape/trigger` enqueued. |
| 204 | No Content | `GET /v1/matches/{id}/predictions` — no calibration data yet. |
| 400 | Bad Request | Body validation failed; malformed JSON. |
| 401 | Unauthorized | Missing / expired / revoked JWT. |
| 403 | Forbidden | Self-registration disabled; insufficient tier (dormant Phase 20). |
| 404 | Not Found | Resource does not exist. |
| 425 | Too Early | Predictor backpressure active or idempotency-key inflight wait timed out. |
| 429 | Too Many Requests | Rate limit exceeded. |
| 503 | Service Unavailable | Readiness probe failed (PG or Redis unreachable); concurrency semaphore overflow. |

---

## §9. Observability

### 9.1 Structured access log (stderr)

JSON log per request. Sampled at `NEGELIR_API_LOG_SAMPLE_PCT` (default 10 %)
for 2xx; 4xx/5xx always logged.

Fields: `time`, `method`, `path`, `status`, `latency_ms`, `request_id`,
`rate_subject`, `x_cache` (predictions only).

### 9.2 Prometheus RED metrics

Served on internal port `NEGELIR_TELEMETRY_METRICS_PORT` (default `:9091/metrics`).
**Never exposed on the public API port.**

Key counter: `api_requests_total{method, path, status}`.

Cardinality boot gate: `NEGELIR_TELEMETRY_MAX_SERIES` (default 10 000). The
server refuses to start if the worst-case series count would exceed this value.

### 9.3 OTLP traces

When `NEGELIR_TELEMETRY_OTLP_ENDPOINT` is set (`host:port`, no scheme), spans
are exported via OTLP gRPC. When empty (default) the tracing subsystem is a
complete no-op. Trace ID is the `X-Request-ID` / `traceparent` header value.

---

## §10. Request timeout budget

The server enforces a **SLA budget** validated at boot (§9.0 `Validate()`):

```
APIRequestTimeoutMs ≥ ConsensusWindowMs + ProofreaderQuorumWindowMs
                     + APIConsensusOverheadMs + APITransitJitterMs
```

Defaults:
- `NEGELIR_API_REQUEST_TIMEOUT_MS` = 2500 ms  
- `NEGELIR_CONSENSUS_WINDOW_MS` = 750 ms  
- `NEGELIR_PROOFREADER_QUORUM_WINDOW_MS` = 200 ms  
- `NEGELIR_API_CONSENSUS_OVERHEAD_MS` = 200 ms  
- `NEGELIR_API_TRANSIT_JITTER_MS` = 100 ms  

`make swarm.demo.live` end-to-end smoke test target: < 1500 ms with real Redis
and mock predictors.

---

## §11. Concurrency caps

| Cap | Env var | Default | Behaviour on overflow |
|---|---|---|---|
| In-flight requests / pod | `NEGELIR_API_MAX_CONCURRENT_REQUESTS` | 5 000 | 503 immediately; `X-Overflow: true` |
| SWR goroutines / pod | `NEGELIR_API_SWR_INFLIGHT_MAX` | 64 | Async refresh silently skipped |
| Max header bytes | (hardcoded) | 32 KiB | 431 Request Header Fields Too Large |
| Idle connection TTL | (hardcoded) | 60 s | Connection closed |

---

## §12. Idempotency

Routes with `x-idempotent-mutation: true` require the `Idempotency-Key` header
(arbitrary string ≤ 255 chars). The key is SHA-256 hashed with the subject ID,
method, and path to produce a Redis key (`idem:<sha256>`). The stored response
is replayed for `NEGELIR_API_IDEMPOTENCY_TTL_S` (default 86 400 s / 24 h).

If a second request arrives with the same idempotency key while the first is
still processing, the second blocks for up to
`NEGELIR_API_IDEMPOTENCY_INFLIGHT_WAIT_MS` (default 1500 ms), then returns 425.

---

## §13. mTLS (production)

`NEGELIR_API_MTLS_ENABLED=true` (default `false` in dev) enables mutual TLS
for all backend connections (Redis, PostgreSQL, bus). Client cert bundle lives
in `NEGELIR_API_TLS_DIR` (default `data/api/tls`). See `docs/guides/api_runbook.md`
§3 for cert rotation procedure.

---

## §14. Forward contracts

| Phase | Contract |
|---|---|
| Phase 10 | `POST /v1/qa` handler routes to the Turkish NLP swarm agent. Currently a stub. |
| Phase 16 | `CalibrationStore` backend for `/v1/matches/{id}/predictions` is swapped to the feed-plane backend (zero handler-code changes). |
| Phase 20 | `x-tier-required` enforcement activated; `NEGELIR_API_TIER_ENFORCEMENT_ENABLED=true`. |
