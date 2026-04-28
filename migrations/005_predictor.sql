-- ══════════════════════════════════════════════════════════
--  Negelir — Phase 5 Predictor / Consensus Tables
--  PostgreSQL 16
--
--  Tables that back the Phase 5 predictor swarm + consensus loop:
--    * predictor_weights:    per-(predictor, profile, market) weight
--                            learned from a rolling Brier-score
--                            window. consensus.v1 reads this, the
--                            TrainerReactor writes nightly rollups.
--    * predictor_calibration: isotonic-regression tables stored as
--                            JSONB, versioned per (profile, market).
--                            CalibrationStore Protocol reads through
--                            here in the Postgres backend.
--    * predictor_outcomes:   ground truth per (match, market) so
--                            backtests can replay against history.
--
--  `profile_id` is the Phase 13a CalibrationProfile id. Until 13a
--  lands the catalog loader, callers pass `profile_id = league_id`
--  (and the column simply carries that value). Switching to real
--  profiles is a data migration, not a schema change.
-- ══════════════════════════════════════════════════════════

-- 5.1 Per-predictor fusion weights.
CREATE TABLE IF NOT EXISTS predictor_weights (
    predictor_id    TEXT        NOT NULL,
    profile_id      TEXT        NOT NULL,
    market          TEXT        NOT NULL,         -- '1x2'|'ah'|'ou_2_5'|'btts'
    weight          DOUBLE PRECISION NOT NULL,    -- in [0, 1] post-normalization
    brier_score     DOUBLE PRECISION,             -- rolling window score
    samples         INTEGER     NOT NULL DEFAULT 0,
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMPTZ,                  -- NULL = currently active
    PRIMARY KEY (predictor_id, profile_id, market, valid_from)
);

CREATE INDEX IF NOT EXISTS idx_predictor_weights_active
    ON predictor_weights (predictor_id, profile_id, market)
    WHERE valid_to IS NULL;

-- 5.2 Versioned isotonic calibration tables (CalibrationStore protocol).
--
-- `table` is a JSONB blob shaped like
--   {"x": [0.0, 0.1, ...], "y": [0.02, 0.09, ...]}
-- where `x` are the predictor outputs and `y` the calibrated
-- probabilities (monotone non-decreasing). consensus.v1 fits a step
-- function from this and applies it per-outcome.
CREATE TABLE IF NOT EXISTS predictor_calibration (
    profile_id      TEXT        NOT NULL,
    market          TEXT        NOT NULL,
    version         INTEGER     NOT NULL,
    table_jsonb     JSONB       NOT NULL,
    samples         INTEGER     NOT NULL DEFAULT 0,
    fit_metric      DOUBLE PRECISION,
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMPTZ,
    PRIMARY KEY (profile_id, market, version)
);

CREATE INDEX IF NOT EXISTS idx_predictor_calibration_active
    ON predictor_calibration (profile_id, market, version DESC)
    WHERE valid_to IS NULL;

-- 5.3 Ground-truth outcomes for backtest replay.
--
-- `outcome` is the realized market outcome (e.g. for '1x2': 'H'|'D'|'A';
-- for 'ou_2_5': 'over'|'under'). `details` carries supplemental fields
-- (e.g. final score, goal counts) so backtests can re-derive other
-- markets without re-querying source records.
CREATE TABLE IF NOT EXISTS predictor_outcomes (
    match_id        TEXT        NOT NULL,
    market          TEXT        NOT NULL,
    outcome         TEXT        NOT NULL,
    details         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    outcome_at      TIMESTAMPTZ NOT NULL,
    league_id       TEXT,
    profile_id      TEXT,
    PRIMARY KEY (match_id, market)
);

CREATE INDEX IF NOT EXISTS idx_predictor_outcomes_league
    ON predictor_outcomes (league_id, outcome_at DESC);
