# Phase 13.7 — Tier promotion gate (`xops/leagues/readiness.py`)

> Extracted from `docs/planning/ROADMAP.md` §13.7
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.7 Tier promotion gate (`xops/leagues/readiness.py`)

- [ ] **Single CLI** `make leagues.readiness LEAGUE=<id> TARGET_TIER=<T2|T1>` evaluates every gate in LEAGUE_CATALOG.md §2; output is a structured JSON report plus a human-readable table.
- [ ] **Promotion is a YAML edit gated by green report.** Lint refuses a `tier: T1` row whose readiness report `evaluated_at` is older than `cfg.league_readiness_report_max_age_h` (default 168 h = 7 days) or whose status is anything other than `pass`.
- [ ] **Beta window is wall-clock enforced** — promotion to T1 refuses unless `now() − beta_started_at ≥ 28 days` (`cfg.league_beta_min_days`); freezes preserve the clock so a calibrated league does not immediately get re-promoted on a config change.
- [ ] **Per-tier proof tests** (`make test.leagues`):
  - `test_t3_to_t2_gates.py` — synthetic league with deliberately missing data fails each individual T3→T2 gate.
  - `test_t2_to_t1_gates.py` — synthetic league with deliberately bad calibration fails the T2→T1 calibration gate.
  - `test_promotion_refuses_stale_report.py`.
  - `test_beta_window_wall_clock.py` (uses fake clock).
- [ ] **Tracker integration.** Promotion / demotion writes a tracker row automatically (per AGENTS.md §3) — no human bookkeeping needed.
- [ ] **Two-person rule for T1 promotion.** Promotion to T1 requires the readiness CLI to be invoked once with `--propose` (writes a `proposed` artifact) and once with `--confirm` by a different actor (validated against `git log --format='%aE'` of the `--propose` commit); proof test `test_t1_two_person_rule.py`.
- [ ] **Promotion dry-run mode.** `make leagues.readiness LEAGUE=<id> --dry-run` prints the would-be report without persisting it; used in PR review.
- [ ] **Readiness-report retention.** Last `cfg.league_readiness_report_retention` (default 30) reports per league are stored under `data/leagues/readiness/<league_id>/`; older ones rolled to cold storage per Phase 16 §16.8.
- [ ] **Promotion rollback.** `make leagues.promotion.rollback LEAGUE=<id> REASON=""` reverts the most recent T2→T1 promotion atomically (catalog flip + §13.66 cascade revoke + tracker row); proof test `test_promotion_rollback_atomic.py` confirms no torn state under concurrent reads.
- [ ] **Two-person rule freshness.** `--propose` artifact expires after `cfg.league_propose_max_age_h` (default 72 h); a `--confirm` against an expired propose fails with structured error and writes a tracker row.
- [ ] **Promotion → canary handoff.** A T1 promotion automatically lands as `deployment_phase=canary` per §13.61 before flipping to `full`; lint refuses a direct `T2 → T1 + full` in one commit.
