# Phase 16.19 — Security & access control

> Extracted from `docs/planning/ROADMAP.md` §16.19
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.19 Security & access control

- [x] **Read ACL.** `FeedReader` constructed with a `principal` (Phase 9 token claim or service identity); `cfg.feeds_acl` (YAML) maps `principal → allowed (plane, source) globs`. Default-deny for unknown principals. Swarm predictors get a service identity scoped to the planes they declare; the patcher gets read-only on `score`/`schedule`/`lineup`/`reference`; the trainer gets read-only on snapshots, no live.
- [x] **No secrets in records.** AST scan + runtime guard: payload field names matching `/(token|secret|password|apikey|cookie)/i` raise `proof.flag{kind=secret_in_payload}` and the record is quarantined (routed to `sec.quarantine.v1` / `feeds/sec_quarantine.v1.parquet`), never written to the live plane.
- [x] **Audit log.** Every `FeedReader.snapshot()` call by a non-swarm principal (i.e., humans via `xops`, gateway forwards) logs `(principal, plane, sources, as_of, byte_count, sha256_of_first_part)` to `audit.feeds.v1` (Postgres, retained per Phase 9 audit policy). Swarm reads are exempt (high-volume, identity already covered by service-identity).
- [x] Signed-manifest hook reserved (HMAC over manifest bytes with rotated key); spec-only in Phase 16, implemented in Phase 17 if the patcher's auto-merge requires per-record provenance.
- [x] Proof tests: `test_read_acl_default_deny.py`, `test_secret_field_quarantined.py`, `test_audit_log_records_human_reads.py`.
