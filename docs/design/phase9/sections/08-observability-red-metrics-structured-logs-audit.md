# Phase 9.8 — Observability — RED metrics, structured logs, audit

> Extracted from `docs/planning/ROADMAP.md` §9.8
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.8 Observability — RED metrics, structured logs, audit

- [ ] **RED metrics** (Prometheus, `:9091/metrics` on a separate port, NOT public): `api_requests_total{route, status, method, cache, degraded}`, `api_request_duration_seconds_bucket{route, method}` (10ms..2500ms), `api_inflight_rpcs{route}`, `api_cache_hit_ratio{route}` (computed gauge — not a counter), `api_jwt_verify_duration_seconds`, `api_sec_gate_duration_seconds`, `api_idempotency_replays_total{result}`. **Cardinality cap:** `route` is the OpenAPI pattern (e.g. `/v1/matches/:id`), NEVER the substituted ID. `status` is the status code class + exact (`200`, `2xx`, `4xx`, `5xx` summary alongside exact). Boot validator estimates worst-case series count (route × status × method × cache × degraded ≈ 30 × 8 × 3 × 4 × 2 ≈ 5760) and refuses if `cfg.telemetry_max_series` would be exceeded.
- [ ] **Structured logs (JSON, stderr).** Per request: `{ts, request_id, trace_id, route, method, status, latency_ms, user_id_h?, anon_subject_key, ip_subject, sec_gate_ms, auth_ms, cache, degraded, error_code?}`. `user_id_h` = sha256(user_id)[:12] — NEVER raw user_id. Log sampling at `cfg.api_log_sample_pct` (default 100 in dev, 10 in prod) for 2xx; **always 100% for 4xx/5xx**.
- [ ] **Audit hash-chain (Phase 8 §8.13.2 mirror).** `api.response.v1` consumer in the maint plane writes to `api_audit_log` partitioned by month, prev_hmac/row_hmac chain identical to `maint_audit_log`. `make audit.verify-api` walks the chain. **PII discipline:** the chain stores `user_id_h`, NEVER email. Right-to-erasure via `make api.erase-user USER=...` purges `users` row + emits `pii_erased` (Phase 8 path) + null-stamps `user_id_h` columns (the hash is irreversible but a determined attacker with a small user set could rainbow-table; null-stamp post-erasure is belt-and-braces).
- [ ] **Trace export.** OTLP gRPC to `cfg.telemetry_otlp_endpoint` if set; else no-op (no stdout-JSON trace dump — too noisy). Span attributes are a subset of the structured log fields (no PII).
- [ ] **SLO definition (binding for §19 GA gate).** Availability ≥ 99.5% (excluding planned maint windows per §8.16.13 noise window), p95 latency ≤ 250 ms for cache-hit reads, p95 ≤ 800 ms for cache-miss predictions, error rate ≤ 0.5%. Burn-rate alerts via `sec.alert.v1{kind=api_slo_burn, severity=warn|critical}` based on multi-window multi-burn-rate (Google SRE workbook recipe; thresholds in `cfg.api_slo_burn_*`).
