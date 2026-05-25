# Phase 9.12 — Triangle test & cfg knobs (mandatory)

> Extracted from `docs/planning/ROADMAP.md` §9.12
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.12 Triangle test & cfg knobs (mandatory)

- [ ] **One source of truth.** Every Phase 9 cfg key listed below appears in `ai/common/config.py`, `server/internal/config/config.go`, `ai/common/defaults.yaml`, AND `xops/env/.env.example` with `# shared` marker. `test_config_sync` covers all three sides; Go-side parity asserted by `server/internal/config/sync_test.go`.
- [ ] **Knob inventory (v1):** `api_request_timeout_ms=2500`, `api_consensus_overhead_ms=200`, `api_transit_jitter_ms=100`, `api_request_max_bytes=65536`, `qa_input_max_bytes=4096`, `api_fixture_window_max_days=14`, `api_allowed_markets=[ms,au_2.5,btts,ah_home,modal_score]`, `api_cursor_ttl_s=1800`, `api_idempotency_ttl_s=86400`, `api_idempotency_inflight_wait_ms=1500`, `api_swr_inflight_max=64`, `api_cache_stale_after_s=30`, `api_cache_max_age_s=300`, `api_reply_reaper_s=60`, `api_predict_request_backlog_high=5000`, `api_max_concurrent_requests=5000`, `api_response_write_timeout_ms=5000`, `api_bcrypt_cost=12`, `api_access_ttl_s=900`, `api_refresh_ttl_s=2592000`, `api_refresh_replay_grace_s=30`, `api_revocation_set_max=10000`, `api_jwt_key_poll_s=10`, `api_jwt_retired_grace_s=960`, `api_self_registration_enabled=false`, `api_register_cap_per_subnet_per_h=20`, `api_burst_capacity=60`, `api_burst_refill_per_s=2`, `api_trusted_proxies=""`, `api_log_sample_pct=10`, `api_tier_enforcement_enabled=false`, `api_deprecation_window_days=90`, `api_schema_version=1`, `api_slo_burn_window_s=3600`, `api_slo_burn_threshold=2.0`, `api_time_format="iso8601_utc"`.
- [ ] **Boot validator.** `internal/config/validate.go` enforces: (a) timeout chain inequality; (b) bcrypt cost ≥ 10; (c) `api_request_timeout_ms ≥ 100`; (d) all TLS cert paths exist + readable + not expired (refuse if `notAfter < now + 7d`); (e) JWT keystore non-empty + at least one ACTIVE row.
