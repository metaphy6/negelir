# Phase 13.43 — Sandbox-league lane

> Extracted from `docs/planning/ROADMAP.md` §13.43
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.43 Sandbox-league lane

> Retires assumption §13.0 #50.

- [ ] **`__sandbox__` reserved `league_id`.** Always present in the catalog; not surfaced on the public `/v1/catalog` (admin-only).
- [ ] **Smoke-E2E target.** `make leagues.sandbox.smoke` runs predictor + proofreader + emitter + (optionally) patcher against a curated synthetic competition under the sandbox league.
- [ ] **Metric isolation.** All `negelir_league_*` metrics for `__sandbox__` carry `sandbox=true` label; cardinality budget §13.10 excludes the sandbox.
- [ ] **Monetization isolation.** Sandbox bypasses all entitlement / quota checks (Phase 20); never invoiced.
- [ ] **Patcher-target permission.** Phase 17 patcher artifacts targeted at the sandbox have a relaxed scope contract (still scope-bounded) so the harness can be exercised without touching real-league code.
- [ ] **Lint.** `xops/lint/no_sandbox_in_prod_code.py` refuses any reference to `__sandbox__` in `swarm/predictor/` outside the predictor's bootstrap path; sandbox is for test/dev usage, not production logic.
