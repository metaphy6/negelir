# Phase 9.7 — Rate limiting, quotas, denylist

> Extracted from `docs/planning/ROADMAP.md` §9.7
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.7 Rate limiting, quotas, denylist

- [x] **Two-tier rate limit.** L1 = §7.6 in-process GCRA (per pod); L2 = §7.3 Lua bucket (per Redis cluster, authoritative). Token-cost = `endpoint_costs.yaml` value. Subject keys: `(jti or anon_subject_key, route_pattern)` for primary; `(SubjectKey(ip), route_pattern)` for IP. Lower-of-two wins. **Headers** `X-RateLimit-Remaining: <min(jti, ip)>` + `X-RateLimit-Reset: <epoch_s>`.
- [x] **Burst budget.** `cfg.api_burst_capacity` per subject; `cfg.api_burst_refill_per_s`. Cost-aware: `/v1/qa` consumes 5 tokens (per `endpoint_costs.yaml`), `/v1/healthz` consumes 0.
- [x] **Denylist short-circuit.** Subject in `sec:denylist:<key>` → immediate 429 `denylisted` (no body content; no logging beyond the `api.request.v1` row marked `status=429,denylisted=true`). Lua `sec_denylist_mutate` v1.1.0 lazy-eviction (per §7.3 v1.1.0 audit lesson) means this path is always truthful.
- [x] **Subnet-mode escape.** When `sec:denylist:capped` is set (§7.3 cap flag), API switches to `SubjectKey(ip)` /24 (IPv4) or /64 (IPv6) bucketing for new requests until flag clears. Header `X-RateLimit-Mode: subnet` is set so client telemetry can attribute throttling correctly. **Proof test:** flip the cap flag mid-test; assert subsequent requests bucket on subnet.
- [x] **Tier quotas (built but dormant per §20).** `internal/middleware/tier_quota.go` reads `users.tier_id`; checks `tiers.daily_request_cap` (table seeded with one row `{tier_id=1, name='free', cap=NULL}` until §20 ships); when `cfg.api_tier_enforcement_enabled=true`, denies with `429 tier_quota_exceeded`. Counter in Redis `tier:<tier_id>:<user_id>:<utc_yyyymmdd>` TTL 26h.
