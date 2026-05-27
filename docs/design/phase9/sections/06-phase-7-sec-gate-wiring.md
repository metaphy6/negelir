# Phase 9.6 — Phase-7 sec gate wiring (the integration tier §7.7 deferred)

> Extracted from `docs/planning/ROADMAP.md` §9.6
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.6 Phase-7 sec gate wiring (the integration tier §7.7 deferred)

- [x] **Library, not parallel impl.** All gates use `server/internal/sec/`: `sec.QAInputGate` for `/v1/qa` body, `sec.ScriptLoader.Verify(loadFn)` at boot for the 2 Lua scripts (refuse-to-start on header-SHA256 drift OR EVALSHA mismatch — closes the §7.7 "Go gateway middleware" deferral).
- [x] **Endpoint-cost totality** (`sec.CheckTotality(routerPatterns, allowFallback=false)`): boot scans the gin router patterns against `ai/common/security/endpoint_costs.yaml`; refuses to start if any new route lacks an explicit cost entry. **Operator workflow:** add route → CI fails on totality → operator updates `endpoint_costs.yaml` + bumps the doc → ship. Coverage gate makes "I forgot to set the cost" structurally impossible.
- [x] **XFF derivation.** `cfg.api_trusted_proxies` (CIDR list) parsed via `sec.ParseTrustedProxies`; `sec.DeriveClientIP(xff, peer, trusted)` per request; `sec.SubjectKey(ip, ipv4=32, ipv6=64)` for the per-IP rate bucket. Boundary test: spoofed XFF with untrusted prefix is ignored.
- [x] **Password-field bypass.** `/v1/auth/login` and `/v1/auth/register` route the password through `sec.PasswordPasses` (length-cap only; no Unicode normalize; no pattern engine). Boundary test: password with leading/trailing whitespace verifies identically before and after sanitize would have run elsewhere.
- [x] **GCRA in-process bucket** (`sec.SecondaryBucket`) for fail-open per-pod ceiling ahead of the Lua bucket — protects against Redis brown-out without denying users (Allow/Throttle only, never Deny). **Critical:** Phase-7 Lua bucket is the ONLY denial source; in-process bucket throttles by 503 + `Retry-After: 1` (transient hint), Lua bucket returns 429 + the real `Retry-After`. Distinct status codes so client telemetry can distinguish.
