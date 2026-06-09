# Phase 13.46 — Match-clock semantics

> Extracted from `docs/planning/ROADMAP.md` §13.46
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.46 Match-clock semantics

> Retires assumption §13.0 #53.

- [x] **`Competition.match_clock` payload.** `{regulation_min: int, et_enabled: bool, et_min: int, et_stoppage_min: int, golden_goal_active: bool, silver_goal_active: bool, halves: int, half_min: int, drinks_breaks_allowed: bool}`.
- [x] **Feature normalization.** Predictor features that read minutes (e.g. "goals after 60th minute") always normalise via `match_clock.regulation_min`; proof test `test_late_goal_feature_normalized.py` runs the same predictor on a 90-minute and a hypothetical 80-minute competition and asserts the feature normalises correctly.
- [x] **Stoppage-time bounds.** `Live.minute` accepted in `[0, regulation_min + cfg.stoppage_max_min]` (default 15 stoppage); higher values quarantine the record per Phase 7 sec.input.
- [x] **Era-overlay reuse.** §13.13 era flags (golden / silver-goal) live inside `match_clock`; lint refuses two competing sources of truth.

#### 13.46.5 Fixture-clash detector

> Retires assumption §13.0 #56.

- [x] **`swarm/proofreader/clash_detector.py`.** Detects when the same `player_id` resolves into two simultaneous fixtures across competitions (national + club; two cup ties same date); emits `proof.flag.v1{kind=fixture_clash}`.
- [x] **Time overlap definition.** Clash = `[kickoff_utc, kickoff_utc + match_clock.regulation_min + cfg.clash_buffer_min]` overlap (default buffer 60 minutes for travel).
- [x] **Federation resolution required.** A clash blocks publish for both fixtures' lineup-dependent predictions (1X2 still publishes, "player to score" does not) until federation publishes the eligibility resolution.
- [x] **Proof test.** `test_fixture_clash_blocks_lineup_predictions.py` covers a manufactured national-team / club clash.
