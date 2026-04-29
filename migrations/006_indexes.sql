-- Pre-Phase-6 audit M1 — index `match_normalized.raw_ref`.
--
-- The FK `match_normalized.raw_ref → raw_scrapes(id)` exists from
-- migration 004 but no covering index does. Two read paths now scan
-- it routinely:
--   * Storage agent `_shallow_diff` joining new records to their
--     scrape origin.
--   * Phase 4.7 freshness reactors that follow `record → raw scrape`
--     when emitting plane-bounded side effects.
--
-- We use a partial index because `raw_ref` is nullable (the FK is
-- `ON DELETE SET NULL`); under load the null fraction is high and a
-- partial index keeps the index small.

CREATE INDEX IF NOT EXISTS idx_match_normalized_raw_ref
    ON match_normalized (raw_ref)
    WHERE raw_ref IS NOT NULL;
