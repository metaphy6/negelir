# Phase 13.67 — Market-line anomaly detector

> Extracted from `docs/planning/ROADMAP.md` §13.67
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.67 Market-line anomaly detector

> Retires assumption §13.0 #79. Defensive integrity — the detector
> raises a flag, never trades.

- [x] **`xops/leagues/market_line_anomaly.py`.** Subscribes to public-odds feed (where licensed; otherwise mock-stack-only) per source; computes implied probability per market.
- [x] **Anomaly definition.** External implied prob deviates > `cfg.line_movement_anomaly_pct` (default 25 %) from our prediction within a `cfg.line_movement_window_min` (default 60 min) window without a corresponding news-stream entry → flag.
- [x] **`proof.flag.v1{kind=market_line_anomaly, fixture_id, market_id, our_prob, external_prob, observed_at}`.** Surfaces on Phase 8 console; never auto-blocks publish (informational by default).
- [x] **Integrity-flag escalation.** Sustained anomaly (≥ `cfg.line_movement_anomaly_persistence_min`, default 30 min) escalates to a §13.39 `IntegrityFlag` of severity `warn`; `severity=suspended_competitively` only by human review.
- [x] **Per-jurisdiction policy.** Detector disabled in jurisdictions where wagering-data ingestion is regulated (Phase 9 admin-token-only surface); declared per `LeagueRow.line_anomaly_policy ∈ {off, internal_only, public}`.
- [x] **No fabrication.** Lint refuses any synthetic-odds injection outside of `tests/`.
