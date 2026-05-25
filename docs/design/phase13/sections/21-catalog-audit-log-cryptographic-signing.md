# Phase 13.21 — Catalog audit log + cryptographic signing

> Extracted from `docs/planning/ROADMAP.md` §13.21
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.21 Catalog audit log + cryptographic signing

> The catalog YAML is a high-privilege configuration surface. Retires
> assumptions §13.0 #22 and #33.

- [ ] **Append-only audit ledger.** `data/leagues/audit/<utc_ts>.json` per mutation: `{actor, before_sha256, after_sha256, diff, reason, signature}`; `xops/leagues/audit.py` produces and verifies entries.
- [ ] **Signature scheme.** Each entry signed with the actor's git-commit GPG/SSH key; loader verifies signature chain at boot. Unsigned entries fail validation; CI fails on chain break.
- [ ] **Tracker-row + chart-bump enforcement.** Any catalog YAML diff in a commit must be accompanied by a `phases.csv` append row and (for tier-bearing fields) a `xops/versioning/chart.json` bump for that league's component key. Lint refuses the diff otherwise.
- [ ] **Tampering detection.** `make leagues.audit.verify` re-computes hashes across the ledger; any mismatch alerts and quarantines the entire catalog (refusing further mutations) until ops investigates.
- [ ] **Read-only mode.** `cfg.league_catalog_readonly=true` prevents any mutation except via `make leagues.audit.verify --rebuild` after a verified disaster recovery.
- [ ] **Compaction policy.** Append-only ledger compacted at `cfg.league_audit_compaction_days` (default 365) into a signed-merkle-root snapshot; pre-compaction segments archived per Phase 16 §16.8 cold storage; verifier walks the merkle chain across compactions (proof test `test_audit_log_merkle_chain_across_compaction.py`). Retires assumption §13.0 #57.
- [ ] **Tamper-proof retention.** Compaction never re-orders or deletes a row's effective payload; only the storage representation changes. Lint refuses a compaction routine that drops `actor` / `signature` / `before_sha256`.
- [ ] **Operator key revocation.** Revoking a former operator's signing key via `make leagues.audit.revoke KEY=<fingerprint> REASON=""` does not invalidate historical signatures (chain stays valid); future submissions from that key are refused.
