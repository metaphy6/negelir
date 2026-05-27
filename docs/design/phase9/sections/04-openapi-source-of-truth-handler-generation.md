# Phase 9.4 — OpenAPI source-of-truth + handler generation

> Extracted from `docs/planning/ROADMAP.md` §9.4
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 9.4 OpenAPI source-of-truth + handler generation

- [x] **`server/api/openapi.yaml` is binding.** Go handlers generated via `oapi-codegen` (`make api.gen`). CI gate: `make api.gen-check` regenerates into a tmpdir and `git diff --exit-code` against committed handlers — drift fails the build.
- [x] **Schema validation in tests.** Every handler test asserts response body validates against the OpenAPI schema (via `kin-openapi` runtime validator — dev/test only, not in hot path). Adversarial test: malformed handler (returns extra field) → schema validator catches before merge.
- [x] **Swagger UI.** `make api.docs` serves on `localhost:8081` (compose service `api-docs`, profile=`docs`); production image OMITS the docs binary. **No `/v1/docs` route on the public API** — security doctrine.
- [x] **OpenAPI extensions used (binding):** `x-rate-cost` (per route — totality-checked at boot via §7.6 `CheckTotality`); `x-deprecated-on`, `x-sunset-on` (drives the `Sunset` header per §9.11); `x-tier-required` (dormant; consumed by `tier_quota.go` middleware once §20 lands); `x-idempotent-mutation` (drives the Idempotency-Key requirement). Loader at `internal/api/spec_loader.go` fails boot if any route lacks the required extensions.
