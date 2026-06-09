# Phase 13.59 — Guest-team membership plane

> Extracted from `docs/planning/ROADMAP.md` §13.59
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.59 Guest-team membership plane

> Retires assumption §13.0 #71.

- [x] **`GuestEntry` Reference-plane entity.** `(competition_id, season_id, stable_id, host_confederation, guest_confederation, reason, invited_at)`.
- [x] **Identity isolation.** §13.4 anchor resolver does **not** merge a guest team's anchors into the host confederation's set; proof test `test_guest_entry_no_anchor_pollution.py`.
- [x] **Calibration profile.** Guest-team fixtures use the `inter_confederation_friendly_or_special` calibration profile by default; per-competition override allowed.
- [x] **Audit on invite.** §13.21 audit on every guest entry; predictor refuses to publish predictions for the guest team in the host competition until both confederations' identity sets resolve.
- [x] **Cross-confederation backtest.** Backtest corpus must include ≥ 1 guest-team fixture per relevant competition (Copa Libertadores has CONCACAF guests historically; FIFA Club World Cup mixes all).
