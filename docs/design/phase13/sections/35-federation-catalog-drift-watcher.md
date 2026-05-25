# Phase 13.35 — Federation-catalog drift watcher

> Extracted from `docs/planning/ROADMAP.md` §13.35
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.35 Federation-catalog drift watcher

> Retires assumption §13.0 #42.

- [ ] **Per-league `federation_canonical_url`** in the catalog row; for FIFA / UEFA-organised competitions, `competition.federation_canonical_url` overrides the league's.
- [ ] **Scheduled crawl + structural diff.** `xops/leagues/federation_drift.py` runs every `cfg.federation_drift_check_h` (default 24); diff fields: participant list, format (`group_then_knockout` etc.), stage dates, season name.
- [ ] **`proof.flag.v1{kind=catalog_drift, league_id, fields[]}`.** Surfaces on Phase 8 console; T1 promotion blocks while a flag is unresolved.
- [ ] **Drift-resolution audit.** `make leagues.drift.acknowledge LEAGUE=<id> FIELD=<f> RESOLUTION=""` writes a tracker row + signed audit entry per §13.21.
- [ ] **No auto-mutation.** Drift watcher never edits the catalog YAML; only flags and notifies. Doctrine #3 (no fabrication) — federation-published changes still require human review + signed audit entry.
- [ ] **Polite crawling.** Watcher honours per-source `robots.txt` + ToS hash per §13.25; refuses to fetch if either drifted.
