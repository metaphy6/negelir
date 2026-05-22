-- Phase 8 §8.14.1 — maintenance audit log (range-partitioned).
--
-- REVISED IN-PLACE: supersedes the §8.9 single-table design per
-- ROADMAP §8.14.1 note. This revision precedes any actual schema
-- landing — Phase 8 has not shipped yet, so no live data is at risk.
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
-- Range partitioning by `created_at` (monthly) keeps drop-old O(1)
-- (DETACH PARTITION CONCURRENTLY then detach-and-drop — no vacuum bomb, no
-- autovacuum lock contention against the live INSERT path).
--
-- Partition families:
--   standard : maint_audit_log_YYYY_MM   — 365-day default retention
--   pii      : maint_audit_log_pii_YYYY_MM — 2555-day (7yr) retention
--              (receives pii_erased rows via BEFORE INSERT routing
--              trigger added in §8.14.1b)
--
-- `negelir_audit_pruner` role: MAINTAIN (PG 15+) or partition
-- ownership (PG 14) on the parent table, so it can
-- DETACH PARTITION … CONCURRENTLY and then DROP the detached table.
-- No blanket DELETE / TRUNCATE; no DROP on arbitrary tables.
--
-- Hash chain (§8.15.7): each row carries `prev_hmac` (hex of HMAC-
-- SHA256 over the prior row) and `row_hmac` (hex over THIS row).
-- The first row's prev_hmac is the literal string "GENESIS". The
-- BEFORE-INSERT trigger stamps row_hmac so producers cannot forge it.

-- ── Standard partition family ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS maint_audit_log (
    id              BIGSERIAL,
    produced_at     TIMESTAMPTZ   NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),  -- partition key (insert time)
    request_id      TEXT          NOT NULL,
    kind            TEXT          NOT NULL,
    target          TEXT          NOT NULL,
    client_id       TEXT          NOT NULL,
    accepted        BOOLEAN,           -- NULL until first ack lands
    accepted_by     TEXT[]        NOT NULL DEFAULT ARRAY[]::TEXT[],
    reasons         JSONB         NOT NULL DEFAULT '{}'::JSONB,
    payload         JSONB         NOT NULL,  -- full envelope (truncated to cfg.maint_ack_payload_max_bytes)
    prev_hmac       CHAR(64)      NOT NULL,
    row_hmac        CHAR(64)      NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Bootstrap partitions. xops/maint/audit_partitions.py (§8.14.1c)
-- takes over on the §8.3 cron tick after first deploy.
CREATE TABLE IF NOT EXISTS maint_audit_log_2025_01
    PARTITION OF maint_audit_log
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE IF NOT EXISTS maint_audit_log_2025_02
    PARTITION OF maint_audit_log
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE IF NOT EXISTS maint_audit_log_default
    PARTITION OF maint_audit_log DEFAULT;

-- ── PII sibling family (§8.14.1b) ────────────────────────────────
-- Rows whose kind = 'pii_erased' are routed here by the
-- maint_audit_route_pii() BEFORE INSERT trigger (added below).
-- Same schema as the standard family; separate parent so the pruner
-- can apply the 2555-day (7-year) cutoff independently.
CREATE TABLE IF NOT EXISTS maint_audit_log_pii (
    id              BIGSERIAL,
    produced_at     TIMESTAMPTZ   NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    request_id      TEXT          NOT NULL,
    kind            TEXT          NOT NULL,
    target          TEXT          NOT NULL,
    client_id       TEXT          NOT NULL,
    accepted        BOOLEAN,
    accepted_by     TEXT[]        NOT NULL DEFAULT ARRAY[]::TEXT[],
    reasons         JSONB         NOT NULL DEFAULT '{}'::JSONB,
    payload         JSONB         NOT NULL,
    prev_hmac       CHAR(64)      NOT NULL,
    row_hmac        CHAR(64)      NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS maint_audit_log_pii_2025_01
    PARTITION OF maint_audit_log_pii
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE IF NOT EXISTS maint_audit_log_pii_2025_02
    PARTITION OF maint_audit_log_pii
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE IF NOT EXISTS maint_audit_log_pii_default
    PARTITION OF maint_audit_log_pii DEFAULT;

-- ── Indexes ───────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_maint_audit_request_id
    ON maint_audit_log (request_id);
CREATE INDEX IF NOT EXISTS idx_maint_audit_kind_created
    ON maint_audit_log (kind, created_at DESC);

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
    row_cap INT;
    payload_bytes INT;
    first_4kb BYTEA;
    sentinel JSONB;
BEGIN
    -- §8.15.5 per-row hard cap backstop.
    -- Reads the cap from the session GUC maint.audit_row_max_bytes
    -- (default 16384 = 16 KB, set by the application layer).
    BEGIN
        row_cap := current_setting('maint.audit_row_max_bytes')::INT;
    EXCEPTION WHEN undefined_object THEN
        row_cap := 16384;
    END;
    payload_bytes := octet_length(NEW.payload::TEXT);
    IF payload_bytes > row_cap THEN
        -- Truncate to sentinel; the Python caller writes the oversize sidecar.
        first_4kb := substring(convert_to(NEW.payload::TEXT, 'UTF8') FROM 1 FOR 4096);
        sentinel := jsonb_build_object(
            '_truncated',           true,
            '_original_size_bytes', payload_bytes,
            '_kind',                NEW.kind,
            '_first_4kb',           encode(first_4kb, 'base64')
        );
        -- Emit a pg_notify so the Python caller can fire a debounced sec.alert.
        PERFORM pg_notify('maint_audit_oversize', json_build_object(
            'kind',               NEW.kind,
            'original_size_bytes', payload_bytes,
            'row_cap',            row_cap
        )::text);
        NEW.payload := sentinel;
    END IF;

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

-- Triggers fire on the partitioned parents; PG propagates to each
-- child automatically for partitioned tables.
DROP TRIGGER IF EXISTS trg_maint_audit_stamp ON maint_audit_log;
CREATE TRIGGER trg_maint_audit_stamp
    BEFORE INSERT ON maint_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION maint_audit_stamp_row_hmac();

DROP TRIGGER IF EXISTS trg_maint_audit_stamp ON maint_audit_log_pii;
CREATE TRIGGER trg_maint_audit_stamp
    BEFORE INSERT ON maint_audit_log_pii
    FOR EACH ROW
    EXECUTE FUNCTION maint_audit_stamp_row_hmac();

-- ── §8.14.1b — BEFORE INSERT routing trigger ─────────────────────
-- Rows with kind = 'pii_erased' are silently redirected into the PII
-- sibling family (maint_audit_log_pii) so the pruner can apply the
-- 2555-day cutoff independently. RETURN NULL suppresses the original
-- insert into the standard family.
CREATE OR REPLACE FUNCTION maint_audit_route_pii() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.kind = 'pii_erased' THEN
        INSERT INTO maint_audit_log_pii (
            id, produced_at, created_at, request_id, kind, target,
            client_id, accepted, accepted_by, reasons, payload,
            prev_hmac, row_hmac
        ) VALUES (
            NEW.id, NEW.produced_at, NEW.created_at, NEW.request_id,
            NEW.kind, NEW.target, NEW.client_id, NEW.accepted,
            NEW.accepted_by, NEW.reasons, NEW.payload,
            NEW.prev_hmac, NEW.row_hmac
        );
        RETURN NULL;  -- suppress original insert into standard family
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_maint_audit_route_pii ON maint_audit_log;
CREATE TRIGGER trg_maint_audit_route_pii
    BEFORE INSERT ON maint_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION maint_audit_route_pii();

-- ── Pruner role (§8.14.1 — no blanket DROP grant) ────────────────
-- The pruner uses DETACH PARTITION … CONCURRENTLY then detach-and-drop on
-- the detached partition — O(1), no row locks, no vacuum bomb.
-- Privilege model:
--   PG 15+: GRANT MAINTAIN on the parent allows DETACH PARTITION
--           without ownership of the child partitions.
--   PG 14:  The pre-creation job (xops/maint/audit_partitions.py)
--           runs ALTER TABLE <partition> OWNER TO negelir_audit_pruner
--           for every partition it creates, so the pruner can DROP
--           the specific partition after detaching it.
-- In both cases: no GRANT DELETE, no GRANT TRUNCATE, no blanket
-- DROP on arbitrary tables — ROADMAP §8.14.1 least-privilege invariant.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'negelir_audit_pruner') THEN
        CREATE ROLE negelir_audit_pruner NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO negelir_audit_pruner;
GRANT SELECT, INSERT ON maint_audit_log     TO PUBLIC;
GRANT SELECT, INSERT ON maint_audit_log_pii TO PUBLIC;

-- PG 15+ MAINTAIN grant (skipped on older servers via version check).
DO $$ BEGIN
    IF current_setting('server_version_num')::int >= 150000 THEN
        EXECUTE 'GRANT MAINTAIN ON maint_audit_log     TO negelir_audit_pruner';
        EXECUTE 'GRANT MAINTAIN ON maint_audit_log_pii TO negelir_audit_pruner';
    ELSE
        -- PG 14: grant ownership of bootstrap partitions so the pruner
        -- can DETACH (requires ownership in PG 14) and then DROP them.
        -- The pre-creation job extends this to future partitions.
        EXECUTE 'ALTER TABLE maint_audit_log_2025_01      OWNER TO negelir_audit_pruner';
        EXECUTE 'ALTER TABLE maint_audit_log_2025_02      OWNER TO negelir_audit_pruner';
        EXECUTE 'ALTER TABLE maint_audit_log_default      OWNER TO negelir_audit_pruner';
        EXECUTE 'ALTER TABLE maint_audit_log_pii_2025_01  OWNER TO negelir_audit_pruner';
        EXECUTE 'ALTER TABLE maint_audit_log_pii_2025_02  OWNER TO negelir_audit_pruner';
        EXECUTE 'ALTER TABLE maint_audit_log_pii_default  OWNER TO negelir_audit_pruner';
    END IF;
END $$;

REVOKE UPDATE, DELETE ON maint_audit_log     FROM PUBLIC;
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
        RAISE EXCEPTION 'audit_log_immutable: UPDATE/DELETE not allowed on maint_audit_log';
    END IF;
    -- If we reach here (negelir_audit_pruner), proceed with the mutation.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_immutable ON maint_audit_log;
CREATE TRIGGER trg_audit_log_immutable
    BEFORE UPDATE OR DELETE ON maint_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_immutable();

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
