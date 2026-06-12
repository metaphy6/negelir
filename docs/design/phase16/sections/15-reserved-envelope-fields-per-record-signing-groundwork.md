# Phase 16.15 — Reserved envelope fields & per-record signing groundwork (NEW; ledger #20)

> Extracted from `docs/planning/ROADMAP.md` §16.15
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.15 Reserved envelope fields & per-record signing groundwork (NEW; ledger #20)

> Phase 17's auto-merge story may want HMAC-per-Record. Reserve the surface now.

- [x] **Reserved fields shipped always-default-`null`** in the envelope schema: `signature: str|null`, `signature_alg: enum|null` (`hmac-sha256-v1`), `signing_key_id: str|null`. Reader exposes them but does not verify in Phase 16.
- [x] **Verify-passes-on-null** lint: any code path that calls `verify_signature(record)` must succeed when `signature=null` (so adding signing is non-breaking). Lint rule `xops/lint/feeds_signature_optional.py`.
- [x] **Phase 17 hook documented**: when `cfg.feeds_signing_enabled=true` (Phase 17 flips), writer fills these fields per `xops/feeds/signing.py` (spec-only here); the signing surface is defined in `Phase 17 §17.x` and references ledger #14 / #38 for the isolation gate and key rotation story.
- [x] **Field-provenance field** (Phase 13.36) reserved similarly: `field_provenance: dict|null` with the per-field source map; readers expose it; planes that opt in (`schedule`, `score`, `lineup`, `market`) populate it now.
- [x] Proof tests: `test_signature_field_reserved.py`, `test_field_provenance_round_trip.py`, `test_verify_signature_passes_on_null.py`.
