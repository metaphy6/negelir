# Phase 13.6 — Mock-stack & source-coverage onboarding

> Extracted from `docs/planning/ROADMAP.md` §13.6
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.6 Mock-stack & source-coverage onboarding

- [ ] **Per-source coverage matrix in the catalog row** (`source_coverage` mapping; LEAGUE_CATALOG.md §3 sample). At least one source per `Reference` and `Schedule` plane is mandatory for T2; `Live` and `Market` mandatory for T1.
- [ ] **Mock seeds captured.** `make mock.capture SOURCE=<source> LEAGUE=<league_id>` populates `infra/mock/seeds/<source>/<league_id>/`; `infra/mock/seeds/manifest.json` updated atomically; `make mock.verify` green per AGENTS.md §5.
- [ ] **Source-watcher** (`ai/swarm/source_watcher/`) trained on the new league's seed corpus before the league activates; deterministic classifier rules unchanged (Phase 2.8 doctrine).
- [ ] **Robots.txt + ToS audit per source.** `xops/mock/sources.py` row carries the source's robots-respect contract; new sources fail CI without it.
- [ ] **Per-confederation source plan.**
  - 13a: openfootball (history), mackolik / nesine (TR-language coverage), tff (TR official), uefa.com (UCL/UEL/UECL official, scoped to public endpoints).
  - 13b: + per-country federation site for TR / EU non-Top-5; soccerway/fbref deferred to 13c.
  - 13c: fifa.com (WC + qualifiers), confederation sites (CONMEBOL / AFC / CAF / CONCACAF / OFC).
- [ ] **DoS / rate-limit headroom.** Adding a source bumps the per-host rate-limit budget; capacity check via Phase 11 §11.34 admission preflight against the host's ingest budget.
- [ ] **Mock-corpus completeness gate.** `make leagues.readiness` blocks T2 promotion when the per-source coverage matrix has any `Reference` or `Schedule` plane gap (proof test `test_t2_blocks_on_seed_gap.py`); blocks T1 promotion on `Live`/`Market` gaps. (Retires assumption §13.0 #32.)
- [ ] **Per-source contract test.** `test_source_contract_<source>.py` asserts the extractor produces every field documented in the source's row of `xops/mock/sources.py`; an upstream HTML reshuffle that drops a field fails the contract before Phase 17 patcher is invoked.
- [ ] **Seed-staleness budget.** Each source row carries `seed_max_age_days` (default 90); CI fails when any source's seed is older than its budget. Encourages periodic `make mock.capture` refreshes.
- [ ] **Source-poisoning quarantine drill.** `make mock.poison SOURCE=<s> SEED=<id>` injects a deliberately-malformed seed; §13.15 reactor isolation + Phase 7 sec.input quarantine must catch it without crashing other leagues (proof test `test_poisoned_seed_quarantined.py`).
