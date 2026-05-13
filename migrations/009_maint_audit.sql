-- Phase 8 §8.14.1 — maintenance audit log (range-partitioned).
--
-- Append-only mirror of every operator publish via the §8.1 ops
-- console (and every `maint.event.v1{request_id}` ack landing on
-- `maint.ack.v1`). Two reads matter:
--
--   1) the human-facing dashboard ("show every maint command in the
--      last 7 days"), which scans the most recent partition;
--   2) the §8.15.7 hash-chain integrity check, which walks the chain
--      monotonically and so must read across partitions.
--
-- Range partitioning by `produced_at` (monthly) keeps drop-old cheap
-- (DROP PARTITION) and keeps the active partition warm in cache.
--
-- Partition naming: `maint_audit_log_pii_YYYY_MM`. The "_pii" suffix
-- is a forensic marker — the table can carry GDPR-bearing operator
-- inputs (e.g. denylisted IPs, user ids in quarantine_erase). The
-- `negelir_audit_pruner` role owns dropping old partitions; nobody
-- else gets DELETE on this table.
--
-- Hash chain (§8.15.7): each row carries `prev_hmac` (hex of HMAC-
-- SHA256 over the prior row) and `row_hmac` (hex over THIS row).
-- The first row's prev_hmac is the literal string "GENESIS". The
-- BEFORE-INSERT trigger stamps row_hmac so producers cannot forge it.

CREATE TABLE IF NOT EXISTS maint_audit_log_pii (
    id              BIGSERIAL,
    produced_at     TIMESTAMPTZ   NOT NULL,
    received_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    request_id      TEXT          NOT NULL,
    kind            TEXT          NOT NULL,
    target          TEXT          NOT NULL,
    client_id       TEXT          NOT NULL,
    accepted        BOOLEAN,           -- NULL until first ack lands
    accepted_by     TEXT[]        NOT NULL DEFAULT ARRAY[]::TEXT[],
    reasons         JSONB         NOT NULL DEFAULT '{}'::JSONB,
    payload         JSONB         NOT NULL,  -- full envelope (truncated to cfg.maint_ack_payload_max_bytes)
    prev_hmac       TEXT          NOT NULL,
    row_hmac        TEXT          NOT NULL,
    PRIMARY KEY (id, produced_at)
) PARTITION BY RANGE (produced_at);

-- Bootstrap partition (today + 12 months). xops/maint/audit_partitions.py
-- (§8.14.1b) takes over on a cron after first deploy.
CREATE TABLE IF NOT EXISTS maint_audit_log_pii_2025_01
    PARTITION OF maint_audit_log_pii
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE IF NOT EXISTS maint_audit_log_pii_2025_02
    PARTITION OF maint_audit_log_pii
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE IF NOT EXISTS maint_audit_log_pii_default
    PARTITION OF maint_audit_log_pii DEFAULT;

CREATE INDEX IF NOT EXISTS idx_maint_audit_request_id
    ON maint_audit_log_pii (request_id);
CREATE INDEX IF NOT EXISTS idx_maint_audit_kind_produced
    ON maint_audit_log_pii (kind, produced_at DESC);

-- §8.15.7 — BEFORE INSERT trigger stamps row_hmac. The function
-- re-derives the chain from prev_hmac + a stable serialization of
-- the row's columns. The HMAC key lives in `negelir_audit_secret`
-- (a one-row table — see migrations/009b_audit_secret.sql when it
-- lands; for the v1 bootstrap the key is read from
-- `cfg.maint_audit_hmac_key_b64` and pushed via SET LOCAL by the
-- trigger function callsite).
CREATE OR REPLACE FUNCTION maint_audit_stamp_row_hmac() RETURNS TRIGGER AS $$
DECLARE
    secret BYTEA;
    payload BYTEA;
BEGIN
    -- The session-level GUC carries the HMAC secret; production
    -- bootstrap sets it via `ALTER DATABASE ... SET maint.audit_key`.
    -- Test fixtures set it per-connection.
    BEGIN
        secret := decode(current_setting('maint.audit_key'), 'base64');
    EXCEPTION WHEN undefined_object THEN
        secret := convert_to('TEST_KEY_DO_NOT_USE_IN_PROD', 'UTF8');
    END;
    payload := convert_to(
        coalesce(NEW.prev_hmac, 'GENESIS') || '|' ||
        NEW.request_id || '|' ||
        NEW.kind || '|' ||
        NEW.target || '|' ||
        NEW.client_id || '|' ||
        NEW.produced_at::text,
        'UTF8'
    );
    NEW.row_hmac := encode(hmac(payload, secret, 'sha256'), 'hex');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- pgcrypto provides `hmac()`. Skip if missing (test envs without it
-- run the chain check in Python).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TRIGGER IF EXISTS trg_maint_audit_stamp ON maint_audit_log_pii;
CREATE TRIGGER trg_maint_audit_stamp
    BEFORE INSERT ON maint_audit_log_pii
    FOR EACH ROW
    EXECUTE FUNCTION maint_audit_stamp_row_hmac();

-- Pruner role — only this role gets DROP PARTITION authority.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'negelir_audit_pruner') THEN
        CREATE ROLE negelir_audit_pruner NOLOGIN;
    END IF;
END $$;

GRANT SELECT, INSERT ON maint_audit_log_pii TO PUBLIC;
GRANT DELETE, TRUNCATE ON maint_audit_log_pii TO negelir_audit_pruner;

-- INSERT-only enforcement (binding per §8.9).
-- Prevent UPDATE/DELETE except by the dedicated pruner role.
-- This makes the audit log append-only and immutable for auditing
-- purposes. The pruner role obtains DELETE authority solely for
-- TTL-based partition management.
REVOKE UPDATE, DELETE ON maint_audit_log_pii FROM PUBLIC;

-- §8.9 — BEFORE UPDATE OR DELETE trigger that raises audit_log_immutable
-- exception for all roles except negelir_audit_pruner. The application
-- role and negelir_backup cannot mutate audit rows by design — only
-- INSERT and SELECT are permitted for the general case.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS TRIGGER AS $$
BEGIN
    -- Allow mutations only for the negelir_audit_pruner role.
    -- The pruner obtains this role via SET ROLE only inside the
    -- retention prune transaction (§8.3).
    IF current_role != 'negelir_audit_pruner' THEN
        RAISE EXCEPTION 'audit_log_immutable: UPDATE/DELETE not allowed on maint_audit_log_pii';
    END IF;
    -- If we reach here (negelir_audit_pruner), proceed with the mutation.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_immutable ON maint_audit_log_pii;
CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON maint_audit_log_pii
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_immutable();

-- ---------------------------------------------------------------------------
-- Phase 8 §8.7 — pattern_allowlist version row for cache-reload race.
--
-- Co-located with the maint audit DDL per ROADMAP §8.9 (which assigns
-- the `pattern_allowlist_version` metadata scaffolding to this
-- migration). The sec.input.v1 reader polls this single-row table
-- every `cfg.sec_input_allowlist_reload_s` seconds (default 60s)
-- under `REPEATABLE READ` snapshot isolation: the same transaction
-- reads `version` from here and then `pattern` rows from
-- `pattern_allowlist`, so a writer committing between the two
-- SELECTs is invisible to the reader (the reader sees the OLD
-- version + OLD set OR the NEW version + NEW set, never a
-- half-applied state). The next poll tick catches the new state.
--
-- Single-row contract (singleton CHAR(1) PRIMARY KEY pinned to 'x')
-- — there is exactly one meta row for the whole allowlist. The
-- maint.sec.v1 writer bumps `version` after every successful state
-- transition (pending→active, active→expired, etc.) inside the same
-- advisory-lock-held transaction.

CREATE TABLE IF NOT EXISTS pattern_allowlist_meta (
    singleton  CHAR(1)      PRIMARY KEY DEFAULT 'x',
    version    BIGINT       NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pattern_allowlist_meta_singleton_chk CHECK (singleton = 'x')
);

-- Seed the singleton row idempotently so the reader never sees an
-- empty meta table (which would otherwise force a defensive code
-- path on first boot).
INSERT INTO pattern_allowlist_meta (singleton, version)
VALUES ('x', 0)
ON CONFLICT (singleton) DO NOTHING;
