# Phase 13.48 — Adversarial-corpus rotation & growth bound

> Extracted from `docs/planning/ROADMAP.md` §13.48
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.48 Adversarial-corpus rotation & growth bound

> Retires assumption §13.0 #55.

- [ ] **Per-family LRU cap.** `cfg.adversarial_corpus_max_per_family` (default 500); oldest-not-pinned cases evicted on overflow.
- [ ] **Pinning.** Cases born from a real demotion / quarantine / Phase 17 patcher artifact carry `pinned=true` (set by §13.28's auto-append) and are exempt from rotation.
- [ ] **Eviction audit.** Each eviction emits `corpus.evicted.v1{family, league_id, sha256}` so an investigator can recover an evicted case from cold storage if needed.
- [ ] **Coverage invariant.** Eviction policy must preserve at least one case per `(league_id, family)` tuple if any exist; `xops/lint/corpus_coverage.py` refuses an eviction batch that would orphan a tuple.
- [ ] **Cross-corpus dedup.** Two cases with byte-identical `seed_payload_sha256` are deduplicated at append time (no double-counting against the cap).
