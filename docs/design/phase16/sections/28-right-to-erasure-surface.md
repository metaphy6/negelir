# Phase 16.28 — Right-to-erasure (GDPR) surface (NEW; ledger #26)

> Extracted from `docs/planning/ROADMAP.md` §16.28
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.28 Right-to-erasure (GDPR) surface (NEW; ledger #26)

> Phase 9 wires the request endpoint; Phase 16 owns the data surface.

- [x] **Erasure request flow:** `POST /admin/erasure {subject_id, scope: enum, jurisdiction}` → enqueues `erasure.request.v1` on the bus; emitter consumes and:
  1. Locates every Record where `payload` references `subject_id` (via per-plane `erasure_index` materialised from `data_class=pii` partitions).
  2. Writes a tombstone Record per match (`reason=erasure_request`, `request_id`, `requested_at`).
  3. Triggers immediate snapshot rebuild for the affected `(plane, as_of)` partitions.
  4. For files past `cfg.feeds_erasure_key_shred_horizon_days` (default 90 — beyond hot retention), schedules per-file KMS data-key shred (Phase 14 wires the actual shred call).
  5. Publishes `erasure.completed.v1{request_id, planes, snapshots_rebuilt, files_shredded, completed_at}`.
- [x] **SLA**: `cfg.feeds_erasure_sla_h` (default 720 = 30 d, GDPR ceiling); `feeds_erasure_overdue_total` counter pages on overrun.
- [x] **Audit trail.** Every erasure request logged in `audit.feeds.v1` with operator identity + jurisdiction; ledger entries are themselves write-once (Phase 14 object-lock when available).
- [x] **Per-jurisdiction overlay** (Phase 14 §14 cross-link). Erasure scope honours `LeagueRow.data_residency` and `cfg.feeds_jurisdiction_erasure_overlay` (e.g. EU GDPR vs Brazil LGPD) for which planes/fields qualify as PII.
- [x] **Negative test.** Erasing a `public`-class record is refused (`error.code=ERASURE_NON_PII_REFUSED`) — prevents accidental data destruction via mis-targeted requests.
- [x] Proof tests: `test_erasure_request_creates_tombstone.py`, `test_erasure_rebuilds_affected_snapshots.py`, `test_erasure_key_shred_marks_cold_storage_unreadable.py`, `test_erasure_completes_within_sla.py`, `test_erasure_overdue_pages.py`, `test_erasure_non_pii_refused.py`, `test_erasure_audit_trail_complete.py`, `test_per_jurisdiction_erasure_overlay.py`.
