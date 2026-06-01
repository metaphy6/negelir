# Phase 16.8 — Storage backends (R3.6)

> Extracted from `docs/planning/ROADMAP.md` §16.8
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.8 Storage backends (R3.6)

- [ ] Local-disk driver (default) and S3-compatible driver behind one `FeedsStore(Protocol)` (`open_append`, `put_object`, `get_object`, `list_prefix`, `head_object`, `rename_atomic`).
- [ ] S3 driver: SSE-S3 by default; SSE-KMS hook gated on `cfg.feeds_s3_kms_key_arn` (Phase 14 wire-up). Etag verification on every read; conditional PUT (`If-None-Match: *`) on snapshot writes to prevent silent overwrite.
- [ ] **Cold-start uses manifest, not LIST** (ledger #10). `cfg.feeds_s3_list_fallback_enabled` (default `off` in prod, `on` in dev) gates LIST as a degraded recovery path; lint forbids LIST in any reader hot path.
- [ ] **Transparent retry** with capped exponential backoff on `5xx` / `SlowDown` / `RequestTimeout`; budget surfaced as `feeds_store_retry_total{driver,op,outcome}` counter and bounded by `cfg.feeds_store_retry_max_per_op` (default 5) and `cfg.feeds_store_retry_total_per_minute` (default 100, circuit-breaks on exceed).
- [ ] **Per-driver per-op cost ledger** (ledger #16). `feeds_store_cost_usd_total{driver,op}` accumulates from a static price table at `xops/feeds/pricing.yaml` (per-region S3 list/get/put/delete + KMS Decrypt). Hard cap `cfg.feeds_store_daily_usd_cap` (default $5 dev, env-tunable prod) breaks circuit + pages.
- [ ] Proof tests: `test_s3_roundtrip.py` (MinIO compose-side container; byte-identical to local-disk driver), `test_s3_etag_verified_on_read.py`, `test_s3_conditional_put_blocks_overwrite.py`, `test_s3_retry_budget_capped.py`, `test_s3_cost_budget_caps.py`, `test_cold_start_uses_manifest_not_list.py`, `test_no_list_in_reader_hot_path.py` (lint).
