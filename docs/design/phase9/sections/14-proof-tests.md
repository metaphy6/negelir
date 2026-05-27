# Phase 9.14 — Proof tests (≥ 60 deterministic + 15 adversarial; mirrors §8.16 density)

> Extracted from `docs/planning/ROADMAP.md` §9.14
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.14 Proof tests (≥ 60 deterministic + 15 adversarial; mirrors §8.16 density)

**Routing & contract (Go, deterministic):**

- [x] `test_route_table_matches_openapi` — every gin route appears in `openapi.yaml` and vice-versa; cardinality match.
- [x] `test_endpoint_costs_total` — `sec.CheckTotality` against the gin router; allowFallback=false; empty result.
- [x] `test_response_problem_json_on_errors` — every 4xx/5xx body is `application/problem+json` with `{type, title, status, detail, request_id}`.
- [x] `test_pagination_cursor_tampering` — flip every byte position; assert 400 (no panic).
- [x] `test_pagination_cursor_filter_drift` — mint with `from=A`, fetch next page with `from=B`; 409.
- [x] `test_pagination_cursor_post_rotation` — rotate seal key; old cursor → 400 graceful.
- [x] `test_etag_if_none_match_304` — second request with `If-None-Match: <prediction_id>` → 304.
- [x] `test_request_id_echo_uuidv7` — server-minted ID is UUIDv7 (sortable timestamp prefix); client-supplied accepted as-is.
- [x] `test_body_size_cap_413` — POST `/v1/qa` with > `qa_input_max_bytes` → 413; assert `MaxBytesReader` short-circuits before handler.

**Identity & sessions:**

- [x] `test_bcrypt_cost_floor` — boot probe rejects sub-100ms host (mocked clock).
- [x] `test_jwt_kid_rotation_round_trip` — sign with kid_A, rotate to kid_B, verify pre-rotation token still valid until grace expires.
- [x] `test_jwt_purge_zeroizes_priv` — post-purge `.priv.pem` is zero-bytes then absent; on-disk forensic test.
- [x] `test_refresh_single_use_with_grace` — replay within grace returns same access; outside grace → 401 + sec.alert.
- [x] `test_jti_revocation_immediate` — revoke a live token; subsequent request → 401 within < 50ms (Redis EXISTS path).
- [x] `test_jti_revocation_set_pressure_alert` — fill revocation set to 80%; assert sec.alert emitted.
- [x] `test_self_registration_flag_blocks_default` — POST `/v1/auth/register` with default cfg → 403.
- [x] `test_register_subnet_cap` — 21 registers from same /24 in one hour → 21st returns 429.

**Request flow & RPC:**

- [x] `test_timeout_chain_validator_refuses_boot` — set `api_request_timeout_ms < consensus_window_ms`; refuse with explicit error.
- [x] `test_rpc_happy_path_round_trip` — mock predictor publishes `predict.final` ≥ proofreader; API returns 200 with `prediction_id` + `produced_at`.
- [x] `test_rpc_503_no_cache` — kill the predictor; assert 503 + `Retry-After`.
- [x] `test_rpc_503_with_cache_serves_cache` — populate `cache.v1`; same kill; assert 200 cache-hit + `X-Cache: hit`.
- [x] `test_swr_async_fanout_bounded` — flood 200 cache-stale reads; assert at most `api_swr_inflight_max` async `predict.request` published.
- [x] `test_cancellation_publishes_predict_cancel` — client disconnect mid-RPC; assert `predict.cancel.v1` on bus with same `request_id`.
- [x] `test_cancellation_post_final_dropped_silently` — cancel arrives after `predict.final`; no alert, no second response.
- [x] `test_reply_to_topic_per_pod_isolated` — two API pods; their `api.reply.*` streams non-overlapping; reaper sweeps the orphan stream within `api_reply_reaper_s`.
- [x] `test_predict_approved_only_never_predict_final` — boundary: API consumes `predict.approved.v1` only; assert via the swarmctl visibility helper.

**Idempotency & cache:**

- [x] `test_idempotency_replay_identical_body_same_response` — bytes-identical.
- [x] `test_idempotency_drift_409_and_alert` — same key, different body → 409 + sec.alert.
- [x] `test_idempotency_inflight_blocks_then_returns` — second request blocks on pubsub; first completes; second gets the same response.
- [x] `test_idempotency_inflight_timeout_425` — first request stalls; second hits `api_idempotency_inflight_wait_ms` → 425.

**Sec gate integration:**

- [x] `test_sec_input_quarantines_qa_returns_422` — known-bad payload from `injection_patterns.yaml` → 422 `qa_quarantined`.
- [x] `test_password_field_skips_normalize` — login password preserves leading whitespace through hash compare.
- [x] `test_xff_spoofed_untrusted_ignored` — `X-Forwarded-For` from non-trusted peer; subject_key derived from peer.
- [x] `test_subject_key_ipv6_64_collapse` — two IPv6 addresses sharing /64 share one rate bucket.
- [x] `test_lua_loader_refuses_boot_on_drift` — tamper with `sec_rate_check.lua` header; refuse boot with explicit error.

**Rate limit & quota:**

- [x] `test_rate_limit_lower_of_jti_and_ip_wins` — saturate IP bucket; jti bucket has room; still 429.
- [x] `test_denylist_short_circuit_429_no_body` — denylist via Lua mutate; subsequent request 429 with empty body.
- [x] `test_subnet_mode_on_capped_flag` — set `sec:denylist:capped`; subsequent IP buckets at /24.
- [x] `test_tier_quota_dormant_by_default` — flag off; cap=NULL; never throttles on tier.
- [x] `test_tier_quota_active_caps_at_limit` — flag on; cap=10; 11th req in 24h → 429.

**Backpressure:**

- [x] `test_backpressure_predict_request_backlog_switches_cache_only` — synthesize XLEN > threshold; GET serves cache or 503; POST `/v1/qa` → 425.
- [x] `test_slow_client_does_not_pin_goroutine` — write blocks > `api_response_write_timeout_ms`; goroutine returns; audit row 499.
- [x] `test_max_concurrent_semaphore_503` — N+1th request → immediate 503.

**mTLS & migrations:**

- [x] `test_mtls_boot_probe_refuses_on_failure` — bad CA bundle; boot fails with `tls_handshake_failed`.
- [x] `test_mtls_cert_expiring_soon_refuses_boot` — cert with `notAfter < now + 7d`; refuse.
- [x] `test_migrations_idempotent_012_013_014` — apply twice; second is no-op; row counts unchanged.

**Observability:**

- [x] `test_audit_chain_continuity_across_pods` — two pods write API audit rows concurrently; chain verifies.
- [x] `test_pii_erase_nullstamps_user_id_h` — erase user; subsequent audit dump shows null in the hashed column.
- [x] `test_metrics_cardinality_under_cap` — synth 1000 paths through router; cardinality estimator stays under `telemetry_max_series`.
- [x] `test_route_pattern_not_id_in_label` — request `/v1/matches/abc123/predictions`; metric label is `/v1/matches/:id/predictions`.

**Wire-authority boundary (Phase 3.6 enumerative):**

- [x] `test_api_gateway_sole_writer_api_request_v1` — registry walk; only producer.
- [x] `test_api_gateway_sole_writer_api_response_v1` — same.
- [x] `test_api_gateway_sole_writer_predict_cancel_v1` — same.
- [x] `test_api_does_not_publish_maint_or_sec` — AST scan + registry walk; API never writes to `maint.*` / `sec.*` / `auth.*` / `payment.*`.
- [x] `test_api_consumes_predict_approved_not_predict_final` — registry walk.
- [x] `test_event_correlation_id_dual_emit` — quarantine fired during a request → `sec.alert.v1.event_correlation_id == request_id` (per §8.16.9).

**Adversarial corpus (Phase 12 prerequisite — must be green at Phase 9 close, NEVER xfail):**

- [x] `adv_test_jwt_alg_none_attack` — token with `"alg":"none"` → 401, no fallback.
- [x] `adv_test_jwt_kid_path_traversal` — `"kid":"../../etc/passwd"` → 401, no file read.
- [x] `adv_test_jwt_hs256_with_pubkey_as_secret` — algorithm-confusion attack rejected.
- [x] `adv_test_jwt_expired_in_grace_clock_skew` — clock-skew tolerance ≤ `cfg.api_jwt_clock_skew_s=30` (new knob); beyond → 401.
- [x] `adv_test_idempotency_key_collision_user_isolation` — user A and user B use same client key; bodies stay isolated (no cross-user leak).
- [x] `adv_test_cursor_oracle_attack` — submit malformed cursors at high rate; assert no timing oracle (constant-time AES-GCM verify).
- [x] `adv_test_qa_prompt_injection_corpus_300` — Phase 12 corpus replayed at the API; assert each catches at sec gate, no leak through to `predict.request`.
- [x] `adv_test_qa_oversize_413_then_quarantine` — 1MB body → 413; multiple 413s in burst → throttle (cost-aware).
- [x] `adv_test_register_email_unicode_homoglyph` — `admin@negelir.com` vs `аdmin@negelir.com` (Cyrillic а) — both register without collision; deny-set treats as distinct.
- [x] `adv_test_password_unicode_norm_bypass` — composed vs decomposed Turkish password → bcrypt sees identical input (NFC pre-bcrypt only on registration; login uses raw — this is a deliberate one-way to avoid false-rejects on normalization drift; documented).
- [x] `adv_test_idempotency_inflight_double_submit_no_double_charge` — two parallel POSTs → exactly one `predict.request` published, both clients see the same response.
- [x] `adv_test_swr_thundering_herd` — 1000 stale-cache reads land at t=0; assert exactly 1 backend RPC fires.
- [x] `adv_test_cancellation_race_after_final` — cancel arriving 0..50ms after `predict.final`; assert NO duplicate response sent and NO panic.
- [x] `adv_test_open_redirect_in_oidc_callback` — `redirect_uri` parameter not in allow-list → 400 (even though provider is noop, the parameter validator runs).
- [x] `adv_test_log_field_no_pii` — synthetic request with email/IP in body; assert structured log carries `user_id_h`/`anon_subject_key` only, never the raw values.
