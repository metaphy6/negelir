-- ══════════════════════════════════════════════════════════
--  Negelir — Phase 4 Pipeline Tables
--  PostgreSQL 16
--
--  Tables that back the Phase 4 scrape → categorize → process →
--  store agent loop. The Record envelope (DATA_PIPELINE.md §4)
--  is the canonical shape; these tables persist projections.
-- ══════════════════════════════════════════════════════════

-- 4.1 Raw scrape captures (output of scraper.<source>.v1).
-- One row per (source, target, fetched_at). The `bytes_sha256`
-- field gives the storage agent + freshness watcher a stable
-- handle without paging the bytes. Bytes themselves live in
-- the FS / object store (column kept nullable for in-DB testing).
CREATE TABLE IF NOT EXISTS raw_scrapes (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,             -- 'mackolik' | 'nesine' | 'tff'
    target          TEXT NOT NULL,             -- e.g. fixture URL or scrape spec
    league_id       TEXT,
    competition_id  TEXT,
    bytes_sha256    TEXT NOT NULL,             -- hex digest of bytes
    bytes           BYTEA,                     -- inlined for tests; nullable
    content_type    TEXT,
    http_status     INTEGER NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trace_id        TEXT NOT NULL,
    UNIQUE (source, target, fetched_at)
);

CREATE INDEX IF NOT EXISTS idx_raw_scrapes_source_fetched
    ON raw_scrapes (source, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_scrapes_sha
    ON raw_scrapes (bytes_sha256);

-- 4.2 Categorizer verdicts (one per raw_scrape).
CREATE TABLE IF NOT EXISTS scrape_categories (
    raw_scrape_id   BIGINT PRIMARY KEY REFERENCES raw_scrapes(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,             -- 'fixture_list'|'match_detail'|'lineup'|'odds'|'irrelevant'
    confidence      DOUBLE PRECISION NOT NULL,
    classifier_id   TEXT NOT NULL,             -- e.g. 'rules.v1' | 'linsvc.v1'
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4.3 Normalized records (output of processor.<kind>.v1).
-- Stores the JSON payload; specialized tables (matches, lineups,
-- odds) are downstream projections.
CREATE TABLE IF NOT EXISTS match_normalized (
    id              BIGSERIAL PRIMARY KEY,
    record_type     TEXT NOT NULL,             -- 'fixture'|'match_detail'|'lineup'|'odds'
    plane           TEXT NOT NULL,             -- 'reference'|'schedule'|'live'|'editorial'|'market'
    source          TEXT NOT NULL,
    source_match_id TEXT NOT NULL,
    league_id       TEXT,
    competition_id  TEXT,
    stable_id       TEXT NOT NULL,             -- canonical cross-source identifier
    extractor_version TEXT NOT NULL,
    canonical_version INTEGER NOT NULL DEFAULT 1,
    payload         JSONB NOT NULL,
    raw_ref         BIGINT REFERENCES raw_scrapes(id) ON DELETE SET NULL,
    trace_id        TEXT NOT NULL,
    stored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_match_id, record_type)
);

CREATE INDEX IF NOT EXISTS idx_match_normalized_stable
    ON match_normalized (stable_id, record_type);
CREATE INDEX IF NOT EXISTS idx_match_normalized_plane
    ON match_normalized (plane, stored_at DESC);

-- 4.7 Freshness events (the bus stream is the primary surface; this
-- table is the durable audit trail for replay).
CREATE TABLE IF NOT EXISTS freshness_events (
    event_id        TEXT PRIMARY KEY,          -- envelope.message_id
    record_id       BIGINT REFERENCES match_normalized(id) ON DELETE CASCADE,
    plane           TEXT NOT NULL,
    record_type     TEXT NOT NULL,
    change_kind     TEXT NOT NULL,             -- 'created'|'updated'|'invalidated'
    diff_summary    JSONB,
    emitted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trace_id        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_freshness_events_emitted
    ON freshness_events (emitted_at DESC);

-- 4.7 Per-reactor processed-event ledger (idempotency guard).
-- Each reactor inserts (reactor_name, event_id) before doing work;
-- a unique constraint blocks accidental re-processing. CONTENT_FRESHNESS §15.2.
CREATE TABLE IF NOT EXISTS reactor_processed_events (
    reactor_name    TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (reactor_name, event_id)
);

-- 4.6 Telemetry sink (forensic queries; Prometheus is the live surface).
CREATE TABLE IF NOT EXISTS telemetry_events (
    id              BIGSERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'info', -- 'info'|'warning'|'error'
    payload         JSONB NOT NULL,
    trace_id        TEXT,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_topic_observed
    ON telemetry_events (topic, observed_at DESC);
