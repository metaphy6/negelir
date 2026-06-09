# Phase 13.47 — Data-portability export (GDPR Art 20 / KVKK)

> Extracted from `docs/planning/ROADMAP.md` §13.47
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.47 Data-portability export (GDPR Art 20 / KVKK)

> Retires assumption §13.0 #54.

- [x] **`make export.actor ACTOR=<token_sha8>`** produces a portable JSON of every PII record + signed receipt; honoured per Phase 9 + Phase 11 §11.39.
- [x] **Export SLA.** Export honoured within `cfg.gdpr_export_max_days` (default 30); long-running exports surface progress via the Phase 8 console.
- [x] **Receipt signature.** Export tarball includes a signed receipt `{actor_token_sha8, generated_at, sha256, signer_key_id}`; auditable via `make export.verify`.
- [x] **Retention after export.** Exporting does not delete; deletion is a separate `make players.forget` (§13.24) workflow.
- [x] **Per-jurisdiction policy.** EU / TR / CA jurisdictions each have a YAML overlay (`xops/leagues/portability_policy.yaml`); KVKK timelines (60 days TR) and CCPA (45 days) honoured per actor's jurisdiction.
