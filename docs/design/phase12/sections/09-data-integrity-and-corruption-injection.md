# Phase 12.9 — Data-integrity & corruption injection

> Binding per-section detail for Phase 12 §12.9. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A6 (adversarial = only prompt injection), A7. **Depends
> on:** §12.4, §12.5. This is the **integrity** pillar — proving every
> checksum, HMAC, hash-chain, and idempotency guard actually catches
> tampering, not just that it exists.

### 12.9 Corrupt it and prove the guard fires

The system has many integrity primitives, each added by a sister phase.
Phase 12's job is to **tamper** at each and prove the guard fires with
the documented signal, plus that the *recovery* path is correct. An
integrity primitive with no corruption test is unproven.

### 12.9.1 Integrity primitives under test (binding)

| Primitive | Owning phase | Tamper scenario | Must fire |
|---|---|---|---|
| Citation HMAC on `predict.approved.v1` | 5/10 §10.21.8 | forge signature with wrong key | drop + `citation_signature_verify_failed` (critical) |
| Answer envelope HMAC | 10 §10.26.8 | mutate body post-sign | block ship + critical alert |
| Outbound answer checksum | 10 §10.31.11 | in-process middleware mutation | block ship + `outbound_checksum_mismatch` |
| Inbound request checksum | 10 §10.34.4 | flip a byte after gateway sign | drop + `inbound_checksum_mismatch` + 504 |
| `prediction_id` determinism | 10 §10.29.12 | inject mismatched envelope | reject + `predict_prediction_id_mismatch` |
| Opsctl envelope signature | 8 §8.14.4 | forge with rotated-away key | reject + `opsctl_signature_invalid` (critical) |
| Audit-log hash-chain | 8 §8.15.7 | truncate/alter a CSV row | `audit_log_integrity_break` + `first_break_row` |
| Backup per-file SHA manifest | 8 §8.14.2 | bit-flip a dump file pre-tar | `backup_dump_file_corrupted` + `<date>.failed/` |
| Backup archive checksum | 8 §8.13 | bit-rot after fsync | `backup_checksum_mismatch`, age from last verified |
| Prediction signed envelope | 13 §13.54 | mutate stored payload | `predictions.tamper_detected.v1` ≤ 60 s |
| Lexicon feed HMAC | 10 §10.22.12 / 16 | forge feed payload | reject swap + `lexicon_feed_signature_invalid` |
| Cross-language normalize spec SHA | 10 §10.29.11 | mutate one spec byte | both impls **refuse boot** |

- [ ] Every row has a stable catalogue ID (§12.5) and a proof test that
      (a) demonstrates the tamper is **caught** and (b) demonstrates the
      **clean** path still passes (both-direction proof, §12.0).

### 12.9.2 Corruption injection mechanics

- [x] **`corrupt` op in `FaultInjector`** (§12.4) flips bytes in a
      payload/file at a named offset deterministically; the same seed
      corrupts the same byte, so a caught/missed result is reproducible.
      (xops/chaos/scenarios.py::FaultInjector, ai/tests/test_phase12_fault_injector.py)
- [ ] **Storage corruption** uses the namespaced chaos store (§12.2.2):
      a throwaway PG schema / `*_chaos` keyspace, so a corruption drill
      can never damage a real artifact.
- [ ] **Schema-drift injection** mutates a topic schema version /
      `additionalProperties` and asserts the loader refuses unknown
      major (Phase 11 §11.36, Phase 13 §13.27) rather than silently
      coercing.

### 12.9.3 Idempotency & replay integrity

- [ ] **`chaos.replay-storm`** — replay a captured (synthetic) envelope
      stream 5× through every idempotent consumer; assert exactly-once
      *effect* everywhere (consensus ledger Phase 5, storage upsert
      Phase 4, opsctl Phase 8, NLP dedup Phase 10). Extends the Phase 4
      §4.8 + Phase 10 §10.20 5× replay DoD into a chaos drill.
- [ ] **`chaos.split-write`** — kill an agent mid multi-step write
      (dump→verify→prune Phase 8; two-leg tie aggregate Phase 13 §13.12);
      assert no partial/torn state — the operation either completed or
      left no trace, and the next tick recovers cleanly.
- [ ] **Right-to-erasure under chaos** — issue `quarantine_erase` (Phase
      8 / Phase 10 §10.25.9) during a bus flap; assert the erasure is
      idempotent on re-delivery and leaves **zero** residual PII in
      cache / spool / conversation context after heal.

### 12.9.4 Data-at-rest no-PII proof under chaos

- [ ] **`chaos.audit-pii-scan`** — after a chaos run that floods PII-
      bearing input (extends Phase 10 §10.28.14 PII-at-rest test), scan
      every audit row / spool envelope / log sink and assert **zero**
      raw TR-PII matches; a slip is a critical finding, not a warning.

### 12.9.5 Make targets

- [x] `make chaos.tamper-hmac`, `make chaos.checksum-mismatch`,
      `make chaos.audit-chain-break`, `make chaos.replay-storm`,
      `make chaos.split-write`, `make chaos.erasure-under-chaos`,
      `make chaos.audit-pii-scan` — dispatchers registered in
      xops/makefile/chaos.py, tests stubbed pending CI harness.
- [x] `make verify.integrity-coverage` — asserts every integrity
      primitive enumerated in §12.9.1 has a corresponding test or
      catalogue ID (xops/makefile/verify.py::cmd_integrity_coverage)
      ID + green proof test (a primitive added by a sister phase with no
      tamper test fails this gate).
