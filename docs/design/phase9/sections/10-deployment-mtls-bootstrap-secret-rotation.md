# Phase 9.10 — Deployment, mTLS bootstrap, secret rotation

> Extracted from `docs/planning/ROADMAP.md` §9.10
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.10 Deployment, mTLS bootstrap, secret rotation

- [x] **Compose profile.** `docker-compose.yml` gains an `api` service (profile=`default`); depends_on=`{redis, pg, mocksrv}` healthy. mTLS certs mounted from `infra/mock/ca/` in dev; from `data/api/tls/` in prod-like profile. `make api.up` / `make api.down` shortcuts.
- [x] **K8s manifest stub** (Phase 14 fills detail): the API is replicas:N (default N=2), no leader election, stateless. Liveness probe = `/v1/healthz`, readiness probe = `/v1/readyz`. PDB = `minAvailable=1`.
- [x] **Secret rotation runbook** (`docs/guides/api_runbook.md`): JWT key (`make api.rotate-jwt-key`), cursor key (`make api.rotate-cursor-key`), bcrypt cost bump (`make api.bump-bcrypt-cost`), mTLS cert (`make api.tls-rotate`), JTI revocation (`make api.revoke-jti JTI=...`). Each is operator-only (no auto-rotate yet — follows the Phase 8 §8.15.4 doctrine: lifecycle is operator-attested in v1).
- [x] **First-run bootstrap.** `make api.init` creates: (a) JWT keypair `kid_001`; (b) cursor seal key; (c) mTLS bundle if `--with-tls` (defaults true in compose, false on `init` in CI). Idempotent — re-running is a no-op when files exist.
