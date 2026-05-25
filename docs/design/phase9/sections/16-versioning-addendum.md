# Phase 9.16 — Versioning addendum

> Extracted from `docs/planning/ROADMAP.md` §9.16
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.16 Versioning addendum

- [ ] `server` minor bump on first `/v1` route landing; subsequent routes bump patch.
- [ ] `xops` patch for `make api.{init,gen,gen-check,docs,up,down,rotate-jwt-key,rotate-cursor-key,bump-bcrypt-cost,tls-rotate,revoke-jti,erase-user,slo-report}`.
- [ ] `docs` minor for NEW `docs/design/API.md` + NEW `docs/guides/api_runbook.md`; AGENTS.md §1.7 anchor list updated.
- [ ] `compatibility` block (§8.16.15): `server.min_compatible_with.swarm = "<predict.request producer floor>"`, `.ai = "<consensus + proofreader floor>"`. `make version.compatibility-check` green.
