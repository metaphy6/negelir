# Phase 9.3 — Request flow (RPC pattern, idempotency, cache-first, cancellation)

> Extracted from `docs/planning/ROADMAP.md` §9.3
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.3 Request flow (RPC pattern, idempotency, cache-first, cancellation)

```
client →[mTLS termination handled by service mesh in K8s; gin in compose]→
       → req-id mint (UUIDv7) → §7.6 sec gate (sanitize + pattern + XFF + cost)
       → JWT verify (deny-set probe)  → tier check (dormant)
       → idempotency-key lookup (POST mutations)
       → publish api.request.v1 (audit)
       → cache.v1 GET (read endpoints) — HIT → respond + audit + return
       → MISS → publish predict.request{request_id, reply_to=`api.reply.<pod>.<short_uuid>`}
              → wait Redis Streams XREAD on reply_to until cfg.api_request_timeout_ms
              → first message wins; subsequent ignored; reply_to ttl=window+5s autodelete
       → publish api.response.v1
       → respond
```

- [x] **Per-pod reply_to topic.** `api.reply.<pod_instance_id>.<request_short_uuid>` — bounded namespace; `MAXLEN ~ 1` per stream (single message expected); reaper sweeps stale streams every `cfg.api_reply_reaper_s` (default 60s). **Boundary:** the API is the SOLE consumer of any `api.reply.*` stream; AST scan + boundary test confirm no other agent reads/writes.
- [x] **Timeout-budget chaining.** `cfg.api_request_timeout_ms` (default 2500) ≥ `cfg.consensus_window_ms` + `cfg.proofreader_window_ms` + `cfg.api_consensus_overhead_ms` (default 200) + transit jitter budget `cfg.api_transit_jitter_ms` (default 100). **Boot validator** at `internal/config/validate.go` refuses to start if the inequality is violated — no sleep, no prayer, no race-on-prod.
- [x] **Cancellation propagation.** Client disconnect (`r.Context().Done()`) → publish `predict.cancel.v1{request_id}` to bus → consensus.v1 marks the row `cancelled` and stops fan-out scoring. `predict.cancel.v1` is a NEW topic (single producer = `api.gateway.v1`; consumer = `consensus.v1` only). **Boundary tests** + idempotency: cancellation arriving after `predict.final` is dropped without alerting (race expected, not pathological).
- [x] **Idempotency-Key cache.** Redis `idem:<sha256(user_id|method|path|body_hash)>` → `{response_status, response_body_sha256, request_id, expires_at}` with TTL `cfg.api_idempotency_ttl_s` (default 86400). Same key + same body → return the stored response (203 `X-Replayed: true` echo). Same key + DIFFERENT body → `409 idempotency_key_replay_with_different_body` + `sec.alert.v1{kind=idempotency_drift, severity=warn}`. **Proof tests:** (a) double-POST returns identical bytes; (b) drift detected; (c) inflight request (no stored response yet) → second request blocks on a Redis pubsub channel `idem:wait:<key>` for max `cfg.api_idempotency_inflight_wait_ms` then returns `425 too_early`; (d) poll the wait keyspace at boot to clean stale waiters from prior pod (no zombie blockers).
- [x] **Cache-first for read endpoints.** GET `/v1/matches/{id}/predictions` first reads `cache.v1` (Phase 4 — keyed on `(match_id, market_set, calibration_version)`). HIT serves immediately + sets `X-Cache: hit`. MISS issues the RPC. **Stale-while-revalidate:** if cache row is older than `cfg.api_cache_stale_after_s` but younger than `cfg.api_cache_max_age_s`, serve `X-Cache: stale` and ASYNC-publish a `predict.request` (caller doesn't wait). **Proof test:** SWR async fan-out is bounded — at most `cfg.api_swr_inflight_max=64` async requests across the pod (Redis SETNX gate keyed on `swr_lock:<match_id>:<market_set>`); excess are no-op'd.
- [x] **503 + Retry-After contract.** Timeout WITHOUT cache → `503 service_unavailable` + `Retry-After: <ceil(cfg.api_request_timeout_ms/1000)+1>`. Bus unreachable (Redis down) → `503 bus_unreachable` + `Retry-After: 5`. Consensus window blown (predictors all DLQ'd) → `503 consensus_window_blown` + `Retry-After: 10`. Distinct sub-codes so client telemetry can branch.
