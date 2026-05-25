# Phase 13.13 — Era-aware rules & friendly-exclusion enforcement

> Extracted from `docs/planning/ROADMAP.md` §13.13
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.13 Era-aware rules & friendly-exclusion enforcement

- [ ] **Away-goals era cutoff.** `Competition.stages[*].away_goals_rule_active` honoured at predict time; era cutover lives in the YAML, never in code.
- [ ] **`international_friendly` publish-gate.** `swarm/predictor/_publish_gate.py` refuses to publish friendlies; API returns `409 Conflict` with `X-Reason: competition_excluded`. Proof test `test_friendlies_never_published.py`.
- [ ] **Format → market filter.** `single_knockout` refuses "double chance — draw" market emission; `final_only` refuses "to qualify for next round" market; lint refuses an extractor mapping these markets for those formats.
- [ ] **Path-dependent priors** for `multi_stage_qualifier` are bounded — a team that has not yet played in the qualifier returns `cold_start` for the "to qualify for tournament" market (no fabrication, doctrine #3).
- [ ] **Extra-time + penalty-shootout modeling.** `single_knockout` and `two_leg_knockout` outputs include `outcome_in_90 | outcome_in_120 | outcome_pens` with conditional probabilities summing to 1 ± 1e-6 (proof test `test_knockout_conditional_probs_sum.py`).
- [ ] **VAR-era cutoff.** Per-competition `var_active_from` field; pre-VAR backtests use a different prior for late-game red-card / penalty rates (proof test `test_var_era_prior_shift.py`).
- [ ] **Golden-goal / silver-goal era awareness.** Pre-2004 UEFA knockouts honour golden/silver-goal extra-time semantics (sudden-death termination); proof test `test_golden_goal_era_terminates_on_first_goal.py`.
- [ ] **COVID 5-sub era.** `Competition.rules_variant.max_subs_window` honours the 2020-onward IFAB amendment (5 subs in 3 windows); pre-2020 backtests stay at 3-sub semantics (proof test `test_covid_sub_era_window.py`).
- [ ] **Concussion-substitute additivity.** Concussion subs are additive to the standard limit and do not consume a substitution window; predictor's "time-to-fatigue" feature accounts for the additional fresh leg (proof test `test_concussion_sub_additive.py`).
- [ ] **Drinks-break stamina recovery.** Hot-weather competitions (Qatar 2022, summer Süper Lig) declare `drinks_breaks: bool` per fixture; predictor's late-game stamina decay slows when set (proof test `test_drinks_break_late_stamina.py`).
- [ ] **Olympic-football eligibility overlay.** Olympic men's tournament is U-23 with three overage outfield + one overage GK; eligibility resolver applies the overlay only to Olympic competitions (proof test `test_olympic_eligibility_overlay.py`).
- [ ] **Lint forbids hardcoded era constants.** `xops/lint/no_hardcoded_eras.py` refuses any `if year < 2021` / `if season >= '2020-21'` / similar literals in `swarm/predictor/` and `swarm/proofreader/` — eras live in YAML, never in code (proof test `test_no_hardcoded_era_constants.py`).

#### 13.13.5 Rules-variant overlay

- [ ] **`Competition.rules_variant` payload.** Captures sub limit (3 / 5 / 5+1 in extra time), max subs allowed in extra time, ABBA penalty order vs ABAB, IFAB-trial flags (e.g. permanent concussion subs), match length variations (futsal-style halves are out of scope but the schema reserves the field). Predictor reads from the overlay; §13.0 #30 retired.
- [ ] **Lint forbids hard-coded rules constants** in `swarm/predictor/` and `swarm/proofreader/`; `xops/lint/no_hardcoded_rules.py` scans for `MAX_SUBS = ` / `PENALTY_ORDER = ` / similar literals.
- [ ] **Rules-variant resolution test.** `test_rules_variant_resolution.py` asserts predictor output for the same fixture differs when the rules variant changes (e.g. 3-sub vs 5-sub effect on late-game goal probability).
