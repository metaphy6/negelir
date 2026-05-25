# Phase 13.32 — Suspension & card-accumulation tracker

> Extracted from `docs/planning/ROADMAP.md` §13.32
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.32 Suspension & card-accumulation tracker

> Retires assumptions §13.0 #39 and #60.

- [ ] **`Card` Live-plane entity.** `(fixture_id, player_id, minute, card_type, reason_code?, source_id)`; `card_type ∈ {yellow, second_yellow, straight_red, blue}`.
- [ ] **`DisciplinaryRule` per `Competition`.** `Competition.disciplinary_rules: {yellow_threshold_per_phase: int, reset_at: stage_id?, suspension_match_count_per_red: int, escalation_table: list}`; defaults documented per league.
- [ ] **`SuspensionLedger` per `(player_id, competition_id)`.** Append-only; running totals computed by deterministic fold; `available_for(fixture_id) → bool` derived from the ledger + rule.
- [ ] **Per-competition reset semantics.** UCL clears at QF, EURO at semi-final, Süper Lig at season; `test_card_reset_at_quarter_final.py` covers each rule.
- [ ] **Cross-competition independence.** A yellow card in a domestic cup never carries into the league's competition (same player, different ledger); proof test `test_card_ledger_per_competition.py`.
- [ ] **Retroactive sanctions.** Federation post-match additional bans (violent conduct caught on video) modify the suspension ledger via `make suspension.add PLAYER=<id> COMPETITION=<id> MATCHES=<n> REASON=""`; emits audit event; per §13.40.5 marks `retroactive_at`.
- [ ] **Predictor feature surface.** "Player available" feature reads the ledger; a missing key suspension flips the predictor's confidence widening per `cfg.suspension_confidence_widen` (default 1.05×).
