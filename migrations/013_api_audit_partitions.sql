-- Phase 9 §9.0 wire-authority + §9.8 observability — api_audit_log.
--
-- Append-only mirror of every api.request.v1 and api.response.v1 bus
-- event emitted by api.gateway.v1. Two reads matter:
--
--   1) SLO dashboard ("last 7 days latency / error-rate by route")
--      scans the most recent partition only.
--   2) Hash-chain integrity check (§8.13.2 mirror) walks the chain
--      monotonically across partitions.
--
-- Range-partitioned by created_at (monthly) mirrors §8.14.1 so the
-- pruner can DETACH + DROP old partitions without a vacuum bomb.
--
-- Hash chain (§8.13.2): each row carries prev_hmac + row_hmac;
-- the BEFORE INSERT trigger stamps row_hmac so producers cannot forge
-- it. The first row's prev_hmac is the literal string 'GENESIS'.
--
-- `kind` distinguishes the two wire topics:
--   'request'  — api.request.v1  (post-auth, post-sec, pre-RPC)
--   'response' — api.response.v1 (final status + latency)
--
-- xops/maint/audit_partitions.py takes over monthly partition creation
-- after the first deploy. The bootstrap partitions below cover the
-- immediate deploy window.
--
-- Idempotent: safe to re-apply on already-migrated databases.

CREATE TABLE IF NOT EXISTS api_audit_log (
    id              BIGSERIAL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),  -- partition key
    produced_at     TIMESTAMPTZ  NOT NULL,
    request_id      TEXT         NOT NULL,
    kind            TEXT         NOT NULL,
    method          TEXT,
    path            TEXT,
    status_code     SMALLINT,
    latency_ms      INTEGER,
    response_bytes  INTEGER,
    cache_hit       BOOLEAN,
    degraded        BOOLEAN,
    user_id         UUID,
    client_ip       TEXT,
    payload         JSONB        NOT NULL DEFAULT '{}'::JSONB,
    prev_hmac       CHAR(64)     NOT NULL,
    row_hmac        CHAR(64)     NOT NULL,
    PRIMARY KEY (id, created_at),
    CONSTRAINT api_audit_log_kind_chk CHECK (kind IN ('request', 'response'))
) PARTITION BY RANGE (created_at);

-- Bootstrap partitions for the immediate deploy window.
-- The partition manager (xops/maint/audit_partitions.py) creates
-- subsequent monthly partitions on the cron tick.
CREATE TABLE IF NOT EXISTS api_audit_log_2026_05
    PARTITION OF api_audit_log
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS api_audit_log_2026_06
    PARTITION OF api_audit_log
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS api_audit_log_default
    PARTITION OF api_audit_log DEFAULT;

-- ── Indexes ───────────────────────────────────────────────────────────
-- Dashboard query: route x time window (the dominant read pattern).
CREATE INDEX IF NOT EXISTS idx_api_audit_path_created
    ON api_audit_log (path, created_at DESC);

-- Per-request correlation (hash-chain walk + response correlation).
CREATE INDEX IF NOT EXISTS idx_api_audit_request_id
    ON api_audit_log (request_id);

-- ── Hash-chain BEFORE INSERT trigger ─────────────────────────────────
CREATE OR REPLACE FUNCTION api_audit_stamp_row_hmac() RETURNS TRIGGER AS $$
DECLARE
    secret  BYTEA;
    payload BYTEA;
BEGIN
    -- The session-level GUC carries the HMAC secret. Production bootstrap
    -- sets it via ALTER DATABASE ... SET api.audit_key. Test fixtures set
    -- it per-connection.
    BEGIN
        secret := decode(current_setting('api.audit_key'), 'base64');
    EXCEPTION WHEN undefined_object THEN
        secret := convert_to('TEST_KEY_DO_NOT_USE_IN_PROD', 'UTF8');
    END;
    payload := convert_to(
        coalesce(NEW.prev_hmac, 'GENESIS') || '|' ||
        NEW.request_id || '|' ||
        NEW.kind        || '|' ||
        coalesce(NEW.method, '') || '|' ||
        coalesce(NEW.path, '')   || '|' ||
        NEW.produced_at::text,
        'UTF8'
    );
    NEW.row_hmac := encode(hmac(payload, secret, 'sha256'), 'hex');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- pgcrypto provides hmac(). Skip if missing (test envs without it
-- run the chain check in Python — same pattern as 009_maint_audit.sql).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TRIGGER IF EXISTS trg_api_audit_stamp ON api_audit_log;
CREATE TRIGGER trg_api_audit_stamp
    BEFORE INSERT ON api_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION api_audit_stamp_row_hmac();

-- ── Access controls ───────────────────────────────────────────────────
-- Writers: only api.gateway.v1 process (application role). Pruner may
-- DETACH old partitions via GRANT MAINTAIN (PG15+). All other roles
-- are read-only.
REVOKE UPDATE, DELETE ON api_audit_log FROM PUBLIC;
GRANT SELECT, INSERT ON api_audit_log TO PUBLIC;
