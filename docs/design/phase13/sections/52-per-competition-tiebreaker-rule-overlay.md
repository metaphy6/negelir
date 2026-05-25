# Phase 13.52 — Per-competition tiebreaker rule overlay

> Extracted from `docs/planning/ROADMAP.md` §13.52
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.52 Per-competition tiebreaker rule overlay

> Retires assumption §13.0 #64. Group-stage tiebreaker order is not
> universal — UEFA puts H2H before goal-difference; FIFA does the
> opposite; Premier League uses goal-difference then goals scored
> then H2H.

- [ ] **`Competition.tiebreaker_rules: list[str]`** ordered enum sequence over `{points, h2h_points, h2h_goal_diff, h2h_goals_scored, h2h_away_goals, goal_diff, goals_scored, away_goals, fewer_yellow_cards, fewer_red_cards, drawing_of_lots, ranking_points}`.
- [ ] **Standings-recompute consumes the list deterministically.** Same fixture history + same rule list → byte-identical standings (proof test `test_tiebreaker_recompute_deterministic.py`).
- [ ] **Per-format defaults.** Defaults: UEFA continental → H2H first; FIFA → goal-diff first; PL → goal-diff first; documented in `COMPETITIONS.md` §4.
- [ ] **Lint forbids hardcoded tiebreakers.** `xops/lint/no_hardcoded_tiebreakers.py` refuses any literal-list tiebreaker chain in `swarm/proofreader/standings*.py`.
- [ ] **Adversarial-corpus regression.** `ai/tests/fixtures/standings/` includes a known historical group where ordering differed under H2H-first vs GD-first; `test_known_historical_tiebreak.py` confirms our rule reproduces the federation's published table.
