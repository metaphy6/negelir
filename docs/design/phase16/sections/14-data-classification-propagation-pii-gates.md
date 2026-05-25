# Phase 16.14 — Data classification propagation & PII gates (NEW; ledger #12)

> Extracted from `docs/planning/ROADMAP.md` §16.14
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.14 Data classification propagation & PII gates (NEW; ledger #12)

> Phase 11 introduced `data_class` labels; Phase 16 must propagate them so the read ACL (§16.19) can filter by classification.

- [ ] **Envelope field `data_class`.** Required, enum `{public, internal, restricted, pii}`. Default `public`. Writer derives from the source plane's declared default plus per-row overrides supplied by upstream (e.g., `editorial.payload.author_email` flips the row to `pii`).
- [ ] **Class-segregated partitions.** `restricted` and `pii` records land in `feeds/region=<r>/class=<c>/(live|snapshots)/<plane>/...` so a misconfigured ACL cannot accidentally serve them from the public partition.
- [ ] **Mixed-class refusal.** Writer refuses to mix classes within one NDJSON file: a record with class higher than the partition's declared class triggers `proof.flag{kind=class_mismatch}` and routes to the correct partition (or quarantines if no matching partition exists).
- [ ] **Encryption at rest** (Phase 14 wire-up). `restricted` and `pii` partitions require `cfg.feeds_at_rest_encryption_enabled=true` for writes (default `true` in prod, `false` in dev); writer refuses otherwise.
- [ ] Proof tests: `test_data_class_required_in_envelope.py`, `test_pii_record_filtered_by_acl.py`, `test_writer_refuses_mixed_class_partition.py`, `test_pii_partition_requires_encryption.py`.
