# Phase 13.12 — Two-leg tie reactor & idempotency

> Extracted from `docs/planning/ROADMAP.md` §13.12
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.12 Two-leg tie reactor & idempotency

- [ ] `swarm/proofreader/tie_reactor.py` — keyed on `tie_id = sorted([stable_id1, stable_id2])`; consumes both legs' `predict.final` candidates and emits one `predict.final.tie`.
- [ ] **Idempotent across leg arrival order** — replay legs in any order ⇒ identical tie prediction (proof test `test_tie_reactor_idempotent_under_replay.py`).
- [ ] **Idempotent across leg revision** — a corrected leg score re-emits the tie prediction with a monotonically-increasing `revision`; proof test `test_tie_reactor_revision_monotonic.py`.
- [ ] **Coverage** — every `two_leg_knockout` competition in the catalog has at least one tie in the backtest corpus.
- [ ] **Cross-source leg reconciliation.** Two sources reporting the same leg's score must collapse to one tie input; reactor refuses to compute tie until `cfg.tie_source_quorum` (default 1 of N — first-write-wins with reconcile on conflict).
- [ ] **Tie DLQ.** A tie that fails reconciliation lands in `predict.tie.dlq` with both legs' source provenance attached; surfaces on Phase 8 ops console; `make ties.replay TIE_ID=<id>` retries.
- [ ] **Three-leg edge case.** If a competition declares a `replay_leg` (e.g. neutral-venue replay after two-leg draw, historical FA Cup format), reactor accepts a third leg without breaking idempotency — the `tie_id` keys on the canonical pairing, `legs[]` accumulates monotonically (proof test `test_tie_reactor_three_legs.py`).
- [ ] **Aggregate winner determinism.** Tied aggregate → away-goals (era-aware §13.13) → extra-time → penalties; each step deterministic and audited (proof test `test_tie_winner_resolution_deterministic.py`).
- [ ] **Leg cancellation propagation.** A leg flipped to `abandoned` (§13.17) drops the tie's `predict.final.tie` and emits a `predict.invalidated` event; downstream Phase 16 emitter shards re-emit with the void payload.
