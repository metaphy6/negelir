# Phase 12 §12.14.3 — Degraded-Mode Catalogue

> **Binding single-source reference** for every graceful-degradation mode a
> chaos test asserts. Each row corresponds to a `degraded_reason` enum value,
> the HTTP triple (status, Content-Type, body), and the `X-*` headers the
> system emits when operating at reduced capacity.

## Overview

A chaos test **asserts** a degraded mode by:
1. **Injecting a fault** (network latency, storage denial, auth key loss, etc.)
2. **Observing the system's response** within a budget (MTTD ≤ `cfg.chaos_mttd_budget_ms`)
3. **Validating** the response matches the row below

This catalogue closes the loop with:
- **Phase 9 §9.17 RFC 7807 table** (API graceful degradation)
- **Phase 10 §10.10 9-row NLP matrix** (humanizer disabled, proofreader bypass, etc.)
- **Phase 11 §11.10 failure modes** (GPU fallback, thermal throttle, etc.)

**Anti-pattern**: a chaos test that says "I'll just expect whatever it does today"
(§12.14.3). Every test references a row in this catalogue.

---

## Degraded-Mode Registry

| ID | System | Reason | HTTP Status | Content-Type | Response Body | X-Headers | Notes |
|----|--------|--------|-------------|--------------|---------------|-----------|-------|
| DM-API-001 | Go API | `storage_unavailable` | 503 | application/json | `{"error_id":"storage_unavailable","error":"database connection pool exhausted"}` | `X-Retry-After: 30` | Phase 9 §9.17.1 — DB connection pool starvation (conn-pool-starve chaos) |
| DM-API-002 | Go API | `rate_limited` | 429 | application/json | `{"error_id":"rate_limit_exceeded","error":"API rate limit hit"}` | `X-RateLimit-Limit: 100`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset: <unix_ts>` | Phase 9 §9.17.2 — per-key token-bucket exhausted |
| DM-API-003 | Go API | `auth_failed` | 401 | application/json | `{"error_id":"unauthorized","error":"invalid or revoked token"}` | — | Phase 9 §9.17.3 — JWT signature invalid / revoked / expired |
| DM-API-004 | Go API | `cache_unavailable` | 502 | application/json | `{"error_id":"dependency_degraded","error":"cache layer offline"}` | `X-Degraded-Reason: redis_fail_open` | Phase 9 §9.17.1 — Redis flap triggers fail-open (secondary buckets) |
| DM-NLP-001 | NLP dispatcher | `normalize_disabled` | 200 | application/json | `{"intent":null,"entities":[],"humanizer_used":false,"reason":"normalizer_offline"}` | — | Phase 10 §10.10 A1 — normalizer unavailable, skip to humanizer |
| DM-NLP-002 | NLP dispatcher | `humanizer_disabled` | 200 | application/json | `{"intent":"<raw>","entities":[...],"humanizer_used":false,"reason":"humanizer_disabled"}` | — | Phase 10 §10.10 B2 — humanizer circuit-breaker open (latency budget exceeded) |
| DM-NLP-003 | NLP dispatcher | `proofreader_bypass` | 200 | application/json | `{"intent":"<raw>","entities":[...],"proofreader_status":"bypassed"}` | — | Phase 10 §10.10 C1 — proofreader queue depth flood, unproofed render |
| DM-COMPUTE-001 | GPU | `thermal_throttle` | 200 | application/json | `{"prediction":"<cached_model_output>","reason":"gpu_thermal_throttle"}` | — | Phase 11 §11.10 B2 — GPU temp > threshold, fallback to CPU / cached result |
| DM-COMPUTE-002 | GPU | `memory_pressure` | 200 | application/json | `{"prediction":"<inference_lite>","reason":"gpu_oom_pressure"}` | — | Phase 11 §11.10 B3 — VRAM pressure, switch to smaller batch |
| DM-MAINT-001 | Maintenance plane | `maint_circuit_open` | 200 | application/json | `{"status":"operational","maint_plane":"degraded"}` | `X-Maint-Circuit: open` | Phase 8 §8.9 — bus circuit-breaker open after consecutive failures |
| DM-AUDIT-001 | Audit | `audit_chain_break` | 500 | application/json | `{"error_id":"audit_integrity_failure","error":"hash chain mismatch"}` | — | Phase 9 §9.8 + Phase 8 §8.15.7 — audit trail hash-chain tampering detected |

---

## Adding a New Degraded Mode

When a new graceful-degradation path is implemented (e.g., Phase 13 league catalog):

1. **Add a row** with columns: ID (DM-SYSTEM-NNN), System, Reason, HTTP triple, headers, Notes
2. **Reference the owning phase** (e.g. §13.54 for tamper detection)
3. **Create a chaos test** that injects the fault and asserts the row
4. **Register the test** in `docs/testing/phase12_catalogue.md` (e.g. P12-13-A)

**Example**: To add "catalog unavailable" degraded mode:
```markdown
| DM-CAT-001 | Catalog | `catalog_unavailable` | 503 | application/json | `{"error_id":"catalog_unavailable","error":"league registry unreachable"}` | `X-Retry-After: 60` | Phase 13 §13.50 — multi-region catalog quorum lost, read-only mode |
```

Then add a test:
```python
def test_chaos_catalog_unavailable_degraded_mode():
    # Inject: deny Postgres at network layer (Toxiproxy)
    # Assert: HTTP 503 + error body matches DM-CAT-001
    # Verify: detected within MTTD budget + within_budget=true in ledger
    ...
```

---

## Ledger Schema Integration

Each chaos run appends a row to `data/chaos/ledger.jsonl` (§12.14.1):

```json
{
  "run_id": "chaos-2026-06-08T14:32:05Z-P12-13-A",
  "catalogue_id": "P12-13-A",
  "expected_signal": "DM-CAT-001",
  "observed_signal": "DM-CAT-001",
  "detected": true,
  "mttd_ms": 1250,
  "verdict": "pass"
}
```

The `expected_signal` must exist in this file (§12.14.3 linter).

