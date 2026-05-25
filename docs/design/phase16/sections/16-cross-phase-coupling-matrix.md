# Phase 16.16 — Cross-phase coupling matrix (lint-gated)

> Extracted from `docs/planning/ROADMAP.md` §16.16
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.16 Cross-phase coupling matrix (lint-gated)

> Mirrors Phase 13 §13.16. Refuses a PR that touches a referenced sub-section without updating this table.

| Other phase | What Phase 16 owes | Where |
|---|---|---|
| Phase 3 | `scrape.raw` / `match.normalized` envelope swap to feed-pointer; topic names unchanged | §16.11 |
| Phase 4 | Storage agent stream cursor + reconciliation read source | Cross-phase block above |
| Phase 4.6 | New telemetry watch set entries (`EMITTER_*`, `FEED_READER_*`) | §16.17 |
| Phase 5 | `CalibrationStore` + `FeatureSource` Feed backends | §16.5 |
| Phase 6 | `MatchOutcome` alias view; `feature_vectors.v1` plane; tombstone propagation from `freshness.events.v1` | §16.7, §16.13 |
| Phase 7 | `sec_quarantine.v1` plane migration; quarantine envelope `data_class` propagation | §16.14 |
| Phase 9 | Read ACL on `FeedReader`; gateway Go binding; audit log | §16.19 |
| Phase 11 | `data_class` envelope field; thread budget under governor; CPU-only build tag | §16.14, §16.21 |
| Phase 12 | Chaos / fault-injection tests (§16.23) integrated into chaos suite | §16.23 |
| Phase 13 | Per-league shard partition; market-roster refusal; cascade-invalidation feed; field-provenance plane | §16.12, §16.13, §16.15 |
| Phase 14 | S3 driver; cross-region replication descriptor; object-lock immutability; KMS at-rest encryption | §16.8, §16.12, §16.14 |
| Phase 17 | Patcher reads feeds for parity; signing fields populated; emitter write path outside patcher allow-list | §16.15 (signing), `CLAUDE.md` (scope) |
| Phase 18 | `test_no_db_imports.py` + `test_no_bus_data_topics.py` + `test_swarm_isolation.py` triad | §16.5 |
| Phase 21 | `enrich_<plane>.v1` planes via the same writer/reader/registry | Cross-phase block above |
| Phase 8 | Source-watcher fingerprint events pause writer; ack / patcher promotion path | §16.38 |
| Phase 6 | `feeds.snapshot.ready.v1` consumed by drift agent for joined `score ⋈ schedule` reads | §16.27 |
| Phase 9 | Right-to-erasure request endpoint forwards to `erasure.request.v1`; replay audit logs | §16.28, §16.35 |
| Phase 14 | KMS key-shred for cold storage erasure; per-region snapshot-ready streams; OTLP exporter wire-up; PITR cross-region | §16.28, §16.27, §16.30, §16.29 |
| Phase 17 | Patcher consumes trace-driven replay for diagnostic bundles; fingerprint promotion event resumes writer | §16.35, §16.38 |

`xops/lint/phase16_coupling_matrix.py` refuses a PR that touches a referenced sub-section without updating this table.
