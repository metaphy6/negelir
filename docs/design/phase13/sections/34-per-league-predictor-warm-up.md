# Phase 13.34 — Per-league predictor warm-up

> Extracted from `docs/planning/ROADMAP.md` §13.34
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.34 Per-league predictor warm-up

> Retires assumption §13.0 #41.

- [ ] **`LeagueRow.warming_state ∈ {cold, warming, hot}`.** A newly activated (or post-quarantine) league enters `warming` for `cfg.league_warmup_min_h` (default 24).
- [ ] **Replay-based warm-up.** Warm-up replays the last `cfg.league_warmup_replay_n` (default 50) historical fixtures through the live predictor; emits per-fixture diff vs the historical realised log-loss; refuses to flip to `hot` when median diff > `cfg.league_warmup_max_diff` (default 0.04).
- [ ] **Warming leagues are publicly visible but flagged.** API surfaces `X-League-Warming: true`; frontend renders a "kalibrasyon devam ediyor" notice (TR UX).
- [ ] **Calibration doesn't update during warm-up.** No drift-fit, no profile mutation while warming; calibration freeze (per §13.18) reused.
- [ ] **Warm-up audit topic.** `league.warmup.v1{league_id, started_at, finished_at, replay_n, max_diff, decision}` consumed by the Phase 8 console; tracker row appended on flip-to-`hot`.
- [ ] **Cold ↔ warming ↔ hot FSM proof.** `test_league_warming_fsm.py` covers every legal and illegal transition (e.g. `cold → hot` direct is refused).
