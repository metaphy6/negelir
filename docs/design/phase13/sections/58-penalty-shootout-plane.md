# Phase 13.58 — Penalty-shootout plane

> Extracted from `docs/planning/ROADMAP.md` §13.58
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.58 Penalty-shootout plane

> Retires assumption §13.0 #70. Shootouts are first-class outcomes,
> not a footnote.

- [ ] **`Shootout` Live-plane entity.** `(shootout_id, fixture_id, sequence: list[{order: int, team_id, taker_player_id?, outcome ∈ {scored, saved, missed, retake}}], winner_stable_id, finished_at)`.
- [ ] **ABBA / ABAB ordering.** §13.13.5 rules-variant declares the order; storage validates the sequence against the declared order; proof test `test_shootout_order_validation.py`.
- [ ] **Predictor "shootout-prone" feature.** Aggregate shootout history per team feeds a feature input to `single_knockout` / `two_leg_knockout` profiles.
- [ ] **Phase 21 player-markets join.** "First taker to miss" / "Sudden-death taker" markets read the sequence; lineup join via §13.30 transfer plane.
- [ ] **Source quorum on shootout.** Shootout sequences are scrape-error-prone (live-text reporters lag); reactor requires `cfg.shootout_source_quorum` (default 2 of N) before publishing the official sequence.
- [ ] **Era reuse.** Pre-1970 cup ties used coin-toss / replays instead of shootouts — `Competition.shootout_active_from` honoured.
