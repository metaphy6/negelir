# Phase 13.30 — Player transfer & loan plane

> Extracted from `docs/planning/ROADMAP.md` §13.30
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.30 Player transfer & loan plane

> Retires assumption §13.0 #37.

- [ ] **`Transfer` Reference-plane entity.** `(transfer_id, player_id, from_club_id, to_club_id, window, transfer_date, fee_eur?, loan?, loan_end_date?, recall_clause?, sell_on_pct?)`; `window ∈ {summer, winter, emergency}`.
- [ ] **`eligible_at(player_id, date, competition_id) → bool`** — single oracle; consumes transfers + cup-tied rules (UCL cup-tie: a player cannot represent two clubs in the same continental edition); proof test `test_cup_tied_rule_blocks_post_transfer.py`.
- [ ] **Loan dual-eligibility join.** Generalises §13.4.5 — loans split into `parent_eligibility` (paused) + `loan_eligibility` (active until `loan_end_date`); recall-clause activation re-flips them with audit.
- [ ] **Transfer-window calendar.** `xops/leagues/transfer_windows.yaml` per league + per season; predictor's "squad-stability" feature reads window-open / window-closed booleans; proof test `test_transfer_window_calendar.py`.
- [ ] **Free-agent + bosman handling.** A player with no `to_club_id` (free agent) is unavailable for any club's predictions until a new transfer lands; lint refuses a fabrication of a synthetic free-agent transfer (doctrine #3).
- [ ] **Source-conflict reconciliation.** Two sources reporting different fees collapse to one `Transfer` with `field_provenance` (per §13.36); proofreader does **not** emit predictions that depend on `fee_eur` until quorum.
- [ ] **Privacy.** `fee_eur`, `salary_eur`, `agent_id` are `data_class=pii` per Phase 11 §11.39; admin-token only at the API edge.
