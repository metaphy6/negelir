# Phase 13.36 — Source-attribution & field-provenance plane

> Extracted from `docs/planning/ROADMAP.md` §13.36
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.36 Source-attribution & field-provenance plane

> Retires assumption §13.0 #43. The cornerstone of accountability for
> downstream proofreader / patcher decisions.

- [ ] **`field_provenance: dict[field_name → {source_id, observed_at, ingest_id}]`** on every `Fixture`, `Live`, and `Card` record; mandatory for T1 leagues, optional with warning for T2.
- [ ] **Schema-gate.** Storage refuses a Reference-plane mutation lacking `field_provenance` for any field that originates from a scrape; lint refuses a hand-written record without the field (doctrine #3).
- [ ] **Conflict resolution policy.** When two sources disagree on a field, reactor consults a per-source `trust_weight` (in `xops/mock/sources.py`) and the most-recent observation; ties resolved by lexicographic source ID (deterministic — tested by `test_source_conflict_deterministic.py`).
- [ ] **Provenance audit feed.** `provenance.conflict.v1{record_id, field, sources[], resolution}` consumed by the Phase 8 console; per-source trust weights are tunable but mutations follow the §13.21 audit-log policy.
- [ ] **Patcher consumption.** Phase 17 patcher's `diagnostic.json` is required to include `field_provenance` for any field referenced in the failing extractor; lint refuses an artifact without it.
- [ ] **PII handling.** `field_provenance` values are tokenised when the field is `data_class=pii` per Phase 11 §11.39; raw source URLs never leak into the public API.
