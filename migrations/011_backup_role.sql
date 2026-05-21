-- 011_backup_role.sql — Phase 8 §8.3 dedicated backup role.
--
-- Purpose: a least-privileged role used by the maint.backup.v1
-- agent (or its `pg_dump` sidecar) so the dump pathway never
-- runs as the application owner. The role is NOLOGIN by default
-- — operators issue a short-lived password via Vault rotation,
-- or attach a peer/ident map at the pg_hba.conf layer.
--
-- Idempotent: safe to re-apply on already-migrated databases.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'negelir_backup') THEN
        CREATE ROLE negelir_backup NOLOGIN;
    END IF;
END
$$;

-- pg_read_all_data is a built-in role (PG14+) that grants SELECT
-- on every table in every schema, including future tables. This
-- is exactly what `pg_dump` needs — read-only, no DDL, no DML.
GRANT pg_read_all_data TO negelir_backup;

-- pg_catalog USAGE lets pg_dump read system-catalog tables that
-- describe the schema (pg_class, pg_attribute, pg_type, etc.).
-- Without this grant, pg_dump falls back to superuser-only paths.
GRANT USAGE ON SCHEMA pg_catalog TO negelir_backup;
