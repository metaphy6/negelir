-- Phase 7: Schema snapshots for adaptive scraper intelligence
-- Stores successful scrape→field mappings as training data
-- and discovered schemas pending/adopted by the source-watcher / patcher.

CREATE TABLE IF NOT EXISTS schema_snapshots (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,
    endpoint        VARCHAR(256) NOT NULL,
    dom_skeleton    JSONB NOT NULL,
    field_locations JSONB NOT NULL,
    fingerprint     JSONB NOT NULL,
    captured_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_schema_source ON schema_snapshots(source, endpoint);

CREATE TABLE IF NOT EXISTS discovered_schemas (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,
    endpoint        VARCHAR(256) NOT NULL,
    selectors       JSONB NOT NULL,
    confidence      FLOAT NOT NULL,
    discovery_layer VARCHAR(16) NOT NULL,
    peer_votes      INT DEFAULT 1,
    adopted         BOOLEAN DEFAULT FALSE,
    discovered_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_discovered_source ON discovered_schemas(source, endpoint);
CREATE INDEX idx_discovered_adopted ON discovered_schemas(adopted);
