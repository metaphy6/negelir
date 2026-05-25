# Phase 9.13 — Definition of Done (binding — mirrors §8.9 density)

> Extracted from `docs/planning/ROADMAP.md` §9.13
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.13 Definition of Done (binding — mirrors §8.9 density)

- [ ] All `[ ]` items in §9.0–§9.12 ticked.
- [ ] Migrations `012`, `013`, `014` apply idempotently on a fresh PG; `make db.migrate` green.
- [ ] OpenAPI generation: `make api.gen-check` green; every route has `x-rate-cost`, `x-idempotent-mutation` (POST/PATCH only), `x-tier-required` (default `none`).
- [ ] Triangle test (config sync) green for all knobs in §9.12; Go-side `sync_test.go` mirrors Python `test_config_sync.py`.
- [ ] `swarmctl topics` shows `api.request.v1`, `api.response.v1`, `predict.cancel.v1` with the correct producers.
- [ ] `swarmctl ps` shows the API gateway agent shim — see §9.14 boundary tests for why this matters.
- [ ] `make test` green: Python (no regression) + Go (`go test ./server/...` ≥ the proof tests below).
- [ ] `make swarm.demo.live` (per §8.16.13) extended: spin up API → register a test user → login → POST `/v1/qa` → assert end-to-end < 1500ms with real Redis + mock predictors (skip-if-no-Redis).
- [ ] `docs/design/API.md` lands (NEW; binding contract for all Phase 9 surfaces); `docs/guides/api_runbook.md` lands (operator surfaces); both linked from `AGENTS.md` §1.7.
