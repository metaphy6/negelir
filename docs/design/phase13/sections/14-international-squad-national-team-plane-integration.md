# Phase 13.14 — International squad / national-team plane integration (13a foundation; expanded 13c)

> Extracted from `docs/planning/ROADMAP.md` §13.14
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.14 International squad / national-team plane integration (13a foundation; expanded 13c)

- [ ] **National-team identity registry** (`country_id ↔ national_team_id`) — single source for international competitions; covered by `Player.eligibility`.
- [ ] **Squad rotation features.** Tournament-bubble effects (squad fatigue, rotation) modelled as a feature input to `international_*` profiles; per `COMPETITIONS.md` §1.2 international_championship.
- [ ] **Player-club separation.** Injury / suspension data (Phase 21 enrichment) joins on `Player.eligibility` — proof test `test_player_injury_at_club_propagates_to_national_squad.py`.
- [ ] **Friendly inclusion guard.** Pre-tournament friendlies feed sentiment + news only; never feed predictor training (proof test `test_friendly_excluded_from_training.py`).
- [ ] **FIFA international-window calendar.** Loader reads `xops/leagues/fifa_windows.yaml` (per FIFA-published schedule); club-fixture availability features mark players unavailable during their national side's window (proof test `test_fifa_window_unavailability.py`).
- [ ] **Naturalisation / dual-citizenship reconciliation.** `Player.eligibility` accepts multiple `national_team_id` entries with `effective_from` / `effective_to`; switching nationalities (e.g. Diego Costa) preserves history without rewriting old fixtures (proof test `test_dual_citizenship_history_preserved.py`).
- [ ] **U-team and women's competition isolation.** U-21 / U-19 / women's national-team competitions are separate `Competition` rows; their predictions never bleed into senior men's calibration (proof test `test_age_gender_competition_isolation.py`).
