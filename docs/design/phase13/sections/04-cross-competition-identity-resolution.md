# Phase 13.4 — Cross-competition identity resolution (the Galatasaray problem)

> Extracted from `docs/planning/ROADMAP.md` §13.4
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.4 Cross-competition identity resolution (the Galatasaray problem)

- [ ] `swarm/identity/anchor_resolver.py` — maintains a per-club anchor set (union of all observed name forms across all sources × all competitions); merge decision gated by `cfg.identity_merge_threshold` (default 0.94 cosine similarity over a small ≤ 50 MB embedding model, doctrine #4).
- [ ] **TR Lig 1 prerequisite.** Türkiye Kupası ingestion blocks on TR Lig 1 anchor coverage ≥ `cfg.cup_identity_coverage_min` (default 0.95) — proof test `test_turkiye_kupasi_blocks_on_lig1_coverage.py`.
- [ ] **Player-eligibility join.** `Player.eligibility: list[national_team_id]` populated for top-5 squads + TR national team in 13a; proof test `test_player_eligibility_resolves_across_club_and_country.py`.
- [ ] **Idempotent merges.** Re-running the resolver on the same anchor set is a no-op (`test_anchor_resolver_idempotent.py`).
- [ ] **Manual-review queue.** Ambiguous merges (similarity in `[0.85, 0.94)`) emit `proof.flag` instead of auto-merging; surfaced in the ops console (Phase 8).
- [ ] **No fabricated entries.** Anchor sets seed only from observed records — never hand-typed lists in code (doctrine #3). Lint refuses string-literal anchor seeds in `swarm/identity/`.
- [ ] **Soak test.** 4-week mock replay of Süper Lig + UCL + Türkiye Kupası produces zero false-merges and ≤ `cfg.identity_false_split_max_per_week` (default 1) false-splits.
- [ ] **Anchor-set immutability under unrelated edits.** Editing a non-anchor field (e.g. competition stage dates) does not perturb a single `stable_id` (proof test `test_unrelated_edit_no_anchor_shift.py`).
- [ ] **Identity-merge audit topic.** Every merge / split decision emits `identity.merge.v1{decision, similarity, anchor_set_before, anchor_set_after, actor=resolver|operator}` consumed by the Phase 8 console; the topic is replayable to reconstruct the resolver's state at any past time.
- [ ] **Adversarial alias collision corpus.** `ai/tests/fixtures/identity_attacks/` includes near-duplicate club names across confederations (e.g. "Real Madrid" vs "Real Madryt", "Liverpool" vs "Liverpool Montevideo"); resolver must keep them distinct under `cfg.identity_merge_threshold` (proof test `test_alias_collision_no_merge.py`).
- [ ] **Operator merge / split CLI.** `make identity.merge STABLE_IDS=a,b REASON=""` and `make identity.split STABLE_ID=x INTO=a,b REASON=""` are the only ways a human can override the resolver; both write a tracker row + the audit topic event.

#### 13.4.5 Cross-competition join contract

- [ ] **UCL/UEL/UECL group-draw join.** Every drawn club resolves to a `stable_id` already present in at least one domestic-league anchor set (proof test `test_ucl_group_join_complete.py`); a missing club blocks publication of that group's fixtures (no fabrication, doctrine #3).
- [ ] **Player on-loan dual eligibility.** A player on loan from club A to club B retains eligibility for both clubs' competitions until `loan_end_date`; predictor's lineup feature reads `eligible_at(date)` rather than a static list (proof test `test_loan_dual_eligibility.py`).
- [ ] **National-team ↔ club join under fatigue window.** A player who appeared in a national-team fixture within `cfg.fatigue_window_h` (default 72 h) of a club fixture flags `recent_international_minutes`; feature surfaces in the predictor's input (proof test `test_fatigue_window_propagates.py`).
