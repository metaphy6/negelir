# Phase 16.22 — Cost & egress budgets (NEW; ledger #16)

> Extracted from `docs/planning/ROADMAP.md` §16.22
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.22 Cost & egress budgets (NEW; ledger #16)

- [ ] **Per-driver cost ledger** (already wired in §16.8): `feeds_store_cost_usd_total{driver,op}` accumulates per the `xops/feeds/pricing.yaml` table; `cfg.feeds_store_daily_usd_cap` (default $5 dev) circuit-breaks.
- [ ] **Egress cost ledger.** `feeds_store_egress_bytes_total{driver,destination_region}` × per-region price = `feeds_store_egress_usd_total`; cross-region reads are tagged `destination_region=remote` so they bill against the egress cap.
- [ ] **KMS Decrypt budget.** `cfg.feeds_kms_decrypts_per_minute_max` (default 1000) — readers cache plaintext data keys for `cfg.feeds_kms_data_key_ttl_s` (default 600) per Phase 14 envelope-encryption pattern.
- [ ] **Cost panel.** Phase 8 ops console exposes a "feeds spend last 24h / last 7d" panel; alert `FeedsSpendBudgetExceeded` fires at 80 % of daily cap.
- [ ] Proof tests: `test_egress_budget_caps.py`, `test_kms_decrypt_rate_limited.py`, `test_kms_data_key_cached_within_ttl.py`, `test_cost_panel_renders.py`.
