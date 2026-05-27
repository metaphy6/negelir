# API Runbook — Phase 9 REST API Operations

> **Audience:** operators, on-call engineers.
> **Anchor:** `docs/design/phase9/sections/10-deployment-mtls-bootstrap-secret-rotation.md`
> and `docs/design/phase9/sections/02-identity-sessions-and-key-lifecycle.md`.
>
> **Operator attestation requirement.** Every secret-rotation procedure in
> this runbook is **operator-only and requires explicit human action**. There
> is no automated rotation in v1 (Phase 8 §8.15.4 doctrine: lifecycle is
> operator-attested). Before executing any rotation:
>
> 1. Confirm you have write access to the repo and to the running compose stack.
> 2. Record the rotation in the ops log (Slack `#ops-alerts`, or equivalent).
> 3. After completion, confirm the verification step listed under each procedure.
> 4. If a step fails, follow the **Recovery** instructions before escalating.

---

## Prerequisites

All operations below require:

- `make env` — env file (`xops/env/.env`) must exist and be populated.
- `make api.up` — compose stack must be running (`api`, `postgres`, `redis`).
- `openssl` on host `PATH` (for JWT key generation and mTLS renewal).
- Linux / macOS host with standard POSIX utilities.

Verify stack health before any rotation:

```bash
make health        # all services should show "healthy"
make api.up        # no-op if already running; safe to run
```

---

## Quick reference

| Target | Purpose | Safe to repeat? |
|--------|---------|----------------|
| `make api.rotate-jwt-key` | New RS256/ES256 keypair, old → retired | Yes (idempotent kid numbering) |
| `make api.rotate-cursor-key` | New 32-byte AES-256-GCM seal key | Yes (old key backed up) |
| `make api.bump-bcrypt-cost COST=N` | Raise bcrypt work factor | Yes (refuses to lower) |
| `make api.tls-rotate` | Renew all mTLS service certs | Yes (force=True, re-issues) |
| `make api.revoke-jti JTI=<uuid>` | Deny-list a single token immediately | Yes |

---

## 1. JWT key rotation

**Schedule:** every 90 days, or immediately on key-compromise.

### Steps

```bash
make api.rotate-jwt-key
# With custom warm-wait (default 10s): pass env-override is not available yet;
# warm wait is set at 10s in the implementation.
```

**What it does:**

1. Generates `kid_NNN` RSA-2048 keypair via `openssl genrsa` →
   `data/api/jwt_keys/kid_NNN.priv.pem` (mode 0600) and
   `data/api/jwt_keys/kid_NNN.pub.pem`.
2. Inserts the new key into `jwt_keys` table with `status='pending'`.
3. Waits 10 s for all API replicas to discover the pending key via their
   `cfg.api_jwt_key_poll_s` poll loop.
4. Atomically promotes: previous `active` → `retired`, new `pending` → `active`.

**Key lifecycle:**

```
pending  →  active  →  retired  →  purged
           (step 4)   (90-day    (priv key
                        grace)     zeroized)
```

Retired keys remain in `jwt_keys` so existing tokens signed with them
continue to verify until natural expiry (`cfg.api_jwt_retired_grace_s`,
default 86400 s). After that period the `purged` step (manual or future
cron) removes the private key material from disk.

### Verification

```bash
# Check the jwt_keys table:
docker compose exec postgres psql -U negelir -d negelir \
  -c "SELECT kid, status, rotated_in_at FROM jwt_keys ORDER BY generated_at;"
# Expected: exactly one row with status='active', others 'retired' or 'purged'.

# Check the API health endpoint:
make api ENDPOINT=health
# Expected: {"jwt_key_status":"active","kid":"kid_NNN",...}
```

### Recovery

If the `promote` step failed (tool printed `stuck in pending state`):

```bash
docker compose exec postgres psql -U negelir -d negelir -c \
  "BEGIN;
   UPDATE jwt_keys SET status='retired', rotated_out_at=now() WHERE status='active';
   UPDATE jwt_keys SET status='active', rotated_in_at=now() WHERE kid='kid_NNN';
   COMMIT;"
```

If the generate step produced a corrupt key:

```bash
rm data/api/jwt_keys/kid_NNN.priv.pem data/api/jwt_keys/kid_NNN.pub.pem
make api.rotate-jwt-key   # re-runs; kid numbering increments
```

### Rolling restart

After rotation, trigger a rolling restart of API replicas so they swap to
the new signing key (replicas continue to verify retired-key tokens
transparently during the grace period):

```bash
docker compose restart api
```

---

## 2. JTI revocation (emergency escape hatch)

**When:** a token (or refresh token) is suspected compromised before natural
expiry — e.g. after a logout-not-confirmed incident, credential theft, or
session fixation.

### Steps

```bash
make api.revoke-jti JTI=<jti-uuid>
# Optional: pass TTL matching remaining token lifetime (default 900s = 15 min):
# make api.revoke-jti JTI=<uuid> TTL=3600
```

> The `JTI` value is found in the `jti` claim of the JWT (`jwt-cli decode <token>`).

**What it does:**

1. Sets `auth:rev:<jti> = 1` in Redis with the given TTL (EX).
2. Adds the JTI to the sorted-set index `auth:rev:idx` (for cardinality
   tracking and LRU eviction audit).
3. All request verifiers check this set before serving any request.

### Verification

```bash
docker compose exec redis redis-cli GET "auth:rev:<jti>"
# Expected: "1"

docker compose exec redis redis-cli TTL "auth:rev:<jti>"
# Expected: a positive number <= TTL passed to the command
```

### Notes

- Revocation is TTL-scoped: the deny-set entry expires automatically when the
  TTL elapses. There is no persistent revocation list.
- Use `TTL=<remaining_seconds>` when you know the exact expiry; the default
  900 s matches `cfg.api_access_ttl_s`. For refresh tokens use
  `TTL=$(cfg.api_refresh_ttl_s)` (default 604800 = 7 days).

---

## 3. Cursor key rotation

**Schedule:** alongside JWT key rotation (same 90-day cycle), or immediately
on suspected exposure of `data/api/cursor_key`.

### Steps

```bash
make api.rotate-cursor-key
```

**What it does:**

1. If `data/api/cursor_key` exists, renames it to
   `data/api/cursor_key.retired.<unix_ts>` (forensic backup).
2. Generates 32 cryptographically-random bytes via `secrets.token_bytes(32)`.
3. Writes the raw bytes to `data/api/cursor_key` (mode 0600).
4. Prints the base64url encoding of the new key to stdout for manual
   verification — **do not store this in any log**.

> **Impact:** all pagination cursors minted with the old key immediately
> become invalid. Callers receive `400 invalid_cursor` and restart pagination
> from the beginning. This is the expected and documented client behaviour.

### Verification

```bash
ls -la data/api/cursor_key           # should exist, size 32 bytes, mode 0600
ls -la data/api/cursor_key.retired.* # previous key(s) backed up
wc -c data/api/cursor_key            # must print: 32 <path>
```

### Rolling restart

```bash
docker compose restart api
```

After restart, verify pagination with a fresh request:

```bash
make api ENDPOINT=matches   # should return cursor token in X-Cursor header
```

### Recovery (accidental rotation)

If the rotation was accidental and you need to restore the previous key:

```bash
mv data/api/cursor_key data/api/cursor_key.new.<ts>
mv data/api/cursor_key.retired.<ts> data/api/cursor_key
docker compose restart api
```

---

## 4. mTLS certificate renewal

**Schedule:** at the 60-day mark of the 90-day cert lifetime. The compose
healthcheck logs a warning when a cert is within 30 days of expiry.

### Steps

```bash
make api.tls-rotate
```

**Prerequisites:** Phase 2 internal CA must be initialised at `infra/mock/ca/`.
If not present: `make mock.setup`.

**What it does:**

1. Re-issues four leaf certs from `infra/mock/ca/root.key` using `openssl`:
   - `data/api/tls/api.{crt,key}` — API server cert (SAN=`api`)
   - `data/api/tls/client_redis.{crt,key}` — Redis mTLS client cert
   - `data/api/tls/client_pg.{crt,key}` — Postgres mTLS client cert
   - `data/api/tls/client_bus.{crt,key}` — bus (Redis Streams) client cert
2. Copies `infra/mock/ca/root.crt` → `data/api/tls/ca.crt` (verifier chain).
3. All private keys are mode 0600.

Cert TTL = 825 days (per Phase 2 `LEAF_DAYS`). The 90-day renewal schedule
is a security policy, not a hard expiry — old certs remain valid for 825 days.

### Verification

```bash
# Check new cert expiry:
openssl x509 -noout -dates -in data/api/tls/api.crt

# Verify cert is signed by the CA:
openssl verify -CAfile data/api/tls/ca.crt data/api/tls/api.crt
# Expected: data/api/tls/api.crt: OK
```

### Rolling restart

```bash
docker compose restart api
# Optionally restart dependent services if their client certs changed:
docker compose restart redis postgres
```

After restart, verify mTLS is accepted:

```bash
make health    # all services should show "healthy"
make api ENDPOINT=readyz   # must return 200
```

### Recovery

If `make api.tls-rotate` fails mid-way (partial renewal):

```bash
# Re-run — issue_leaf uses force=True so it is idempotent:
make api.tls-rotate
```

If the CA root key is lost (`infra/mock/ca/root.key` missing), all certs must
be regenerated from a new CA. **This is a breaking change** — all existing
mTLS connections will fail until all services receive new certs signed by the
new CA. Escalate to the platform team before proceeding.

---

## 5. Bcrypt cost bump

**Schedule:** whenever hardware benchmarks show the current cost factor
produces < 250 ms hash time (OWASP 2023 guidance) or when upgrading to
significantly faster hardware.

### Steps

```bash
# Check current cost:
grep NEGELIR_API_BCRYPT_COST xops/env/.env

# Bump to new value (example: 12 → 13):
make api.bump-bcrypt-cost COST=13
```

The `COST=N` argument is required. Allowed range: `[10, 14]` (enforced by
`server/internal/config/config.go`). The tool refuses to lower the cost.

**What it does:**

1. Validates `N` is in `[10, 14]` and `N >= current`.
2. Updates `NEGELIR_API_BCRYPT_COST=N` in `xops/env/.env` in-place.
3. Rolling restart picks up the new value.
4. Existing password hashes (`$2b$12$…`) remain valid — the Go auth layer
   re-hashes them at the new cost on the next successful login
   (`password.go: lazy_rehash`). No forced logout.

### Verification

```bash
# Confirm the env file was updated:
grep NEGELIR_API_BCRYPT_COST xops/env/.env   # should show the new value

# After restart, time a test hash (requires the API to be running):
make api ENDPOINT=debug/hash-time   # returns current hash latency in ms
```

### Rolling restart

```bash
docker compose restart api
```

### Recovery

If the cost was bumped too high (hash time > 1 s causing timeouts):

```bash
# Lower the cost in the env file manually (the tool prevents this to avoid
# accidental weakening — edit directly when intentionally reverting):
sed -i 's/^NEGELIR_API_BCRYPT_COST=.*/NEGELIR_API_BCRYPT_COST=12/' xops/env/.env
docker compose restart api
```

---

## Other operations

### PII erasure (GDPR right-to-erasure)

```bash
make api.erase-user USER=<user-id-or-email>
```

Purges the `users` row, emits `pii_erased` on `maint.event.v1`, and
null-stamps `user_id_h` columns in the audit partition. **Irreversible.**

### SLO burn-rate report

```bash
make api.slo-report
```

Produces a 28-day rolling SLO summary (availability, p50/p95/p99 latency,
error budget). Phase 19 GA gate blocks if availability < 99.5 % or p95
outside budget.

### OpenAPI codegen

```bash
make api.gen         # regenerate handlers from server/api/openapi.yaml
make api.gen-check   # CI gate: regenerate into tmpdir, assert no diff
make api.docs        # serve Swagger UI on localhost:8081 (profile=docs)
```

---

## Post-rotation verification checklist

After any rotation procedure, verify:

| Check | Command | Expected |
|-------|---------|----------|
| API healthy | `make health` | all services `healthy` |
| API readyz | `make api ENDPOINT=readyz` | `200 OK` |
| JWT key active | `make api ENDPOINT=health` | `jwt_key_status: active` |
| No auth errors | `docker compose logs api --tail 50` | no `jwt_key_unreadable` |
| Redis accessible | `docker compose exec redis redis-cli PING` | `PONG` |

---

## 6. Circuit breaker & bulkhead operations (§9.17.4)

> **Background.** The API maintains four circuit breakers (`pg`, `redis_cache`,
> `redis_bus`, `swarm_rpc`) and a bulkhead semaphore per upstream. When a
> breaker opens or a bulkhead saturates, the API downgrades gracefully rather
> than cascading. Each event emits a `sec.alert.v1` bus message.

### 6.1 Diagnosing a tripped breaker

```bash
# Real-time breaker state (exposes the internal prom metric)
make api ENDPOINT=metrics | grep 'api_breaker_state'
# Tail recent alerts
docker compose logs api --tail 100 | grep 'breaker_opened\|breaker_half_open'
```

| Metric value | Meaning |
|---|---|
| `0` | `closed` — normal operation |
| `1` | `half_open` — one probe admitted |
| `2` | `open` — all requests for this upstream rejected |

### 6.2 Per-breaker runbook

#### `pg` breaker (PostgreSQL)

**Fires when:** ≥ 50% of PG calls fail over a 10-second window with ≥ 20
requests (`NEGELIR_API_BREAKER_FAIL_RATIO=0.5`, `NEGELIR_API_BREAKER_WINDOW_S=10`,
`NEGELIR_API_BREAKER_MIN_REQUESTS=20`).

**Open-state behaviour:** endpoints that require PG return `503 service_unavailable`.
Endpoints backed by Redis cache only continue normally.

**Recovery steps:**

```bash
# 1. Check PG health
docker compose exec postgres pg_isready -U negelir
# 2. Check pgxpool saturation
make api ENDPOINT=metrics | grep 'api_pg_pool'
# 3. If PG is healthy, the breaker will self-recover after the half-open probe
#    succeeds (NEGELIR_API_BREAKER_OPEN_S=15 by default).
# 4. If PG is unhealthy, fix the upstream and wait for recovery.
make api.up   # restarts the stack if containers are down
```

**Escalation:** if breaker flaps (open→half_open→open repeatedly), check for a
thundering-herd reconnect: adjust `NEGELIR_API_BREAKER_MIN_REQUESTS` upward or
lower `NEGELIR_API_PG_POOL_MAX_CONNS` to reduce concurrency.

---

#### `redis_cache` breaker

**Fires when:** cache client fails at ≥ 50% over 10 s with ≥ 20 requests.

**Open-state behaviour:** cache layer is bypassed — all requests fall through to
the RPC path. This is **degraded but not down**: predictions still served, at
higher latency. Monitor `api_cache_bypass_total` gauge.

**Recovery steps:**

```bash
docker compose exec redis redis-cli PING        # confirm Redis is alive
make api ENDPOINT=metrics | grep 'api_redis'    # check pool utilisation
# Breaker self-recovers once Redis responds to the half-open probe.
```

---

#### `redis_bus` breaker

**Fires when:** bus (XREAD reply-stream) client fails at ≥ 50% over 10 s.

**Open-state behaviour:** `503 bus_unreachable` on all prediction endpoints
(cache-miss path requires the bus). Auth and health endpoints are unaffected.

**Recovery steps:**

```bash
docker compose logs redis --tail 50             # check bus-side Redis
make api ENDPOINT=metrics | grep 'api_bus'
# If bus Redis is a separate instance, check its health separately.
```

---

#### `swarm_rpc` breaker

**Fires when:** swarm RPC (predict.request/predict.response cycle) fails at ≥ 50%
over 10 s.

**Open-state behaviour:** prediction endpoints return `503`. Cache-hit paths
are unaffected (L0 + L1 still serve warm entries).

**Recovery steps:**

```bash
docker compose logs swarm --tail 100 | grep 'ERROR\|PANIC'
make api ENDPOINT=metrics | grep 'api_swarm_rpc'
# The hedge budget (NEGELIR_API_HEDGE_BUDGET_PCT=10) is a separate safety valve:
# when the breaker is closed but p99 latency is high, hedged RPCs kick in.
# If hedge rate spikes, check swarm replica count and queue depth.
```

---

### 6.3 Bulkhead saturation

Each upstream's semaphore is sized to `pool_size × 0.8`. The remaining 20%
is reserved for `/v1/healthz` and `/v1/readyz`.

**Symptoms:** `503 bulkhead_full` on app routes while health probes still succeed.

**Diagnosis:**

```bash
make api ENDPOINT=metrics | grep 'api_bulkhead_inflight\|api_bulkhead_rejected'
```

**Remedies:**

| Knob | Effect | Safe to change? |
|---|---|---|
| `NEGELIR_API_PG_POOL_MAX_CONNS` | Larger pool → larger bulkhead | Yes; validate formula at boot |
| `NEGELIR_API_REDIS_CACHE_POOL_SIZE` | Larger cache pool → larger bulkhead | Yes |
| `NEGELIR_API_REDIS_BUS_POOL_SIZE` | Larger bus pool → larger bulkhead | Yes |
| `NEGELIR_API_MAX_CONCURRENT_REQUESTS` | Horizontal cap on total in-flight | Yes |

Scale the API horizontally first (additional replicas) before raising pool sizes;
the formula `min(cgroup_cpu × 4, pg_max_connections × 0.25 / replicas)` re-runs
at boot and will refuse to start if it would push the cluster past 80% PG saturation.

---

## Troubleshooting

| Symptom | Cause | Remedy |
|---------|-------|--------|
| `401 token_expired` on valid token | KID retired or purged too early | Check `jwt_keys` table; re-issue `make api.rotate-jwt-key` |
| `400 invalid_cursor` mid-pagination | Cursor key rotated | Expected — client restarts pagination |
| `503` on all requests | GCRA ceiling hit / Redis brownout | Check `make health`; scale Redis |
| `429` on all requests | Lua GCRA bucket exhausted | Check `NEGELIR_API_RATE_*` config |
| Boot failure `jwt_key_unreadable` | Corrupt or missing `.priv.pem` | Re-run `make api.rotate-jwt-key` |
| Boot failure `totality_gate` | New route missing cost entry | Add to `ai/common/security/endpoint_costs.yaml` |
| Boot failure `mtls_handshake` | Expired or mismatched mTLS cert | Re-run `make api.tls-rotate` |
| `openssl: command not found` | openssl not on PATH | `apt install openssl` (Debian/Ubuntu) or `brew install openssl@3` |
| psql fails in `rotate-jwt-key` | Postgres container not running | `make api.up` then retry |
