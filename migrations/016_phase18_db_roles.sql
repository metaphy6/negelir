-- Phase 18.6 §18.6 ledger #11 — Per-component Postgres roles
--
-- Purpose: Create per-component database roles with minimal privileges:
--   datasource_writer    — RW on data planes (matches, players, etc), RO on lookup
--   swarm_reader         — no DB grants (swarm reads feeds, not DB); role exists for pg_hba explicit deny
--   server_reader        — RO on materialized views only (not live tables)
--   patcher_writer       — RW on patcher_* tables only (patcher_status, patcher_log)
--
-- Each role is NOLOGIN by default. Operators issue short-lived passwords via secrets store
-- or attach peer/ident auth at the pg_hba.conf layer.
--
-- Idempotent: safe to re-apply on already-migrated databases.

DO $$
BEGIN
    -- datasource_writer: manages the data ingestion pipeline
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'datasource_writer') THEN
        CREATE ROLE datasource_writer NOLOGIN;
    END IF;
    
    -- swarm_reader: exists for explicit deny in pg_hba.conf (swarm reads feeds, not DB directly)
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'swarm_reader') THEN
        CREATE ROLE swarm_reader NOLOGIN;
    END IF;
    
    -- server_reader: minimal privileges, materialized views only
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'server_reader') THEN
        CREATE ROLE server_reader NOLOGIN;
    END IF;
    
    -- patcher_writer: auto-patcher role, writes to patcher control tables
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'patcher_writer') THEN
        CREATE ROLE patcher_writer NOLOGIN;
    END IF;
END
$$;

-- Default schema usage (all roles can use public schema for reads)
GRANT USAGE ON SCHEMA public TO datasource_writer, swarm_reader, server_reader, patcher_writer;

-- datasource_writer gets RW on data-plane tables (to be populated by table ownership checks)
-- This is intentionally empty here; actual grants flow from table ownership comments (§18.6 ledger #24)
-- The initial placeholder: GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO datasource_writer;

-- swarm_reader: explicitly no table grants (reads feeds, not live DB)
-- pg_hba.conf will refuse connections from swarm_reader role

-- server_reader: RO on materialized views (none exist yet, placeholder)
-- To be populated as materialized views are created in later phases
-- Initial placeholder: GRANT SELECT ON ALL MATERIALIZED VIEWS IN SCHEMA public TO server_reader;

-- patcher_writer: RW on patcher_* tables
-- Initial placeholder: to be populated once patcher control tables are created
-- GRANT SELECT, INSERT, UPDATE ON TABLE patcher_status, patcher_log TO patcher_writer;
