-- Phase 7 §7.2 — Source fingerprint state for sec.scrape.v1.
--
-- The streaming-statistic baseline replaces what would otherwise be a
-- per-source LRU of raw samples (the retired `sec_scrape_baseline_max_per_source`
-- knob). Three sketches per source cover the three detection axes:
--
--   * `welford_state` — Welford's online algorithm for byte-size
--     mean / variance (numerically stable; supports merge across
--     `sec.scrape.v1` replicas at flush time).
--     Shape: {"mean": float, "M2": float, "count": int, "updated_at": iso}.
--
--   * `p2_state` — the Jain–Chlamtac P² algorithm tracking running
--     median + p95 of per-fetch byte sizes without storing samples.
--     Shape: {"markers": [5 floats], "positions": [5 ints], ...}.
--     Used to flag "size_delta_pct" trips against a robust quantile.
--
--   * `countmin_state` — count-min sketch over selector-shape
--     fingerprints (BYTEA-packed for compactness; the streaming
--     extractor in `sec.scrape.v1` decodes lazily).
--
--   * `simhash_64` — 64-bit SimHash of the *DOM skeleton* (tag +
--     class names only, content stripped). Persisted as BIGINT
--     because Postgres has no native 64-bit unsigned; producers
--     reinterpret-cast at read time. Hamming distance vs current
--     fetch is compared to `cfg.sec_scrape_simhash_max_distance`.
--
-- All four columns are agent-mutable: `sec.scrape.v1` is the SOLE
-- writer (and runs as a single-instance agent per the §7.5
-- single-writer invariant — to be added to bootstrap.SINGLE_INSTANCE_AGENTS
-- when the agent ships in §7.2). Sample_count gates the warmup
-- window (`cfg.sec_scrape_warmup_samples`); detection is suppressed
-- until count >= warmup.
--
-- `last_flush_at` records the most recent persistence point so the
-- agent's restart path can rebuild from disk + replay the bus tail
-- since flush — same recovery pattern as `proofreader_aggregator.v1`
-- and `consensus.v1`.

CREATE TABLE IF NOT EXISTS source_fingerprints (
    source          TEXT        PRIMARY KEY,
    welford_state   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    p2_state        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    countmin_state  BYTEA       NOT NULL DEFAULT ''::bytea,
    simhash_64      BIGINT,
    sample_count    BIGINT      NOT NULL DEFAULT 0 CHECK (sample_count >= 0),
    last_flush_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Watchdog query: which sources are stale (no flush in > 2× flush
-- interval)?  Cheap on a small table but the index keeps it O(log n).
CREATE INDEX IF NOT EXISTS idx_source_fingerprints_last_flush_at
    ON source_fingerprints (last_flush_at);
