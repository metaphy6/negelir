# Phase 13.8 — Demotion + post-promotion watchdog

> Extracted from `docs/planning/ROADMAP.md` §13.8
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.8 Demotion + post-promotion watchdog

- [ ] **Auto-demotion watchdog** subscribes to `freshness.events.v1` + `swarm.drift` + per-league calibration summaries (Phase 11 telemetry); flips a T1 row to T2 + writes a tracker row + emits `ops.alert.v1{kind=league_demoted, league_id, reason}` when LEAGUE_CATALOG.md §2.3 conditions trigger.
- [ ] **Demotion is reversible only after 14 wall-clock days** (`cfg.league_demotion_min_days`); proof test `test_demotion_floor_enforced.py`.
- [ ] **Cool-down on preset edits.** Editing any non-`team_name_map` field of a T1 league preset auto-demotes that league to T2 until §13.7 re-passes; proof test `test_preset_edit_triggers_demotion.py`.
- [ ] **Per-league SLO dashboard.** Phase 8 ops console exposes `league/<league_id>` panel with all five §13.10 metrics; demotion banner appears on the panel within 30 s of the event.
- [ ] **Patcher artifact routing.** A `patcher.unable` artifact (Phase 17) tagged with `league_id` opens a 24 h timer; the watchdog auto-demotes if the artifact stays unresolved (LEAGUE_CATALOG.md §2.3).
- [ ] **Demotion hysteresis.** Watchdog requires `cfg.league_demotion_evidence_window_h` (default 6 h) of sustained breach — a single-spike SLO breach does not flip the tier (proof test `test_demotion_hysteresis.py`).
- [ ] **Per-league escalation playbook.** Every demotion auto-creates a runbook artifact under `docs/reports/runbooks/leagues/<league_id>/<utc_ts>.md` with the contributing metrics frozen; surfaces on the ops console.
- [ ] **Cascade-prevention guard.** If demotion of league A would cascade-demote league B (e.g. UCL drops because La Liga drops), the watchdog refuses the cascade and pages a human (proof test `test_no_demotion_cascade.py`).
