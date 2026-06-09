# Phase 13.19 — Promotion / relegation & season rollover

> Extracted from `docs/planning/ROADMAP.md` §13.19
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.19 Promotion / relegation & season rollover

> When a club drops to a lower division (or is promoted), its
> `stable_id` is preserved but its `active_competition_id` changes.
> Cross-season identity must survive the rollover. Retires assumption
> §13.0 #20.

- [x] **`team_membership(team_id, season_id, competition_id, role)` join table.** `role ∈ {participant, qualifier, host_country}`; replaces any code that statically assumes "team X is in league Y". Landed: table + loader in schema; proof test confirmed.
- [x] **Rollover tooling.** `make leagues.rollover LEAGUE=<id> NEW_SEASON=<id>` ingests the federation-published participant list, computes promoted-in / relegated-out diff, refuses if any team lacks an anchor set in §13.4, writes a tracker row. Landed: `xops/makefile/leagues.py rollover` target; proof test confirmed.
- [x] **Predictor cold-start for promoted clubs.** Newly promoted clubs hit a `cold_start` flag in their first season's predictions; calibration profile widens CI per `cfg.cold_start_widen_factor` (default 1.25×) until N matches realised. Proof test `test_promoted_team_cold_start.py`. Landed: cold_start gate in predictor; profile reads flag; CI multiplier applied; proof test confirmed.
- [x] **Stable-ID preservation.** `test_promoted_team_keeps_stable_id.py` asserts a club promoted from TR Lig 1 to Süper Lig retains its `stable_id` (no rebirth) and that historical fixtures still join correctly. Landed: proof test confirmed.
- [x] **Cross-season identity merge guard.** §13.4 anchor resolver runs at every rollover; new candidate aliases trigger the manual-review queue, not auto-merge. Landed: rollover logic enforces manual review; proof test confirmed.
