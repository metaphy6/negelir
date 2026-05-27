-- Phase 9 §9.17.7 — Audit pipeline quarantine table.
--
-- api_audit_log_quarantine is a plain (unpartitioned) table that mirrors
-- the schema of api_audit_log.  It acts as a holding area for audit rows
-- written when the Writer has detected a hash-chain integrity break via
-- NotifyIntegrityBreak().
--
-- Rows are NOT passed through the api_audit_stamp_row_hmac() trigger
-- because the chain is already broken.  The trigger stamps them when the
-- operator drains the table back into api_audit_log via:
--
--   make audit.repair-api   (xops/makefile/audit_api.py repair-api)
--
-- After repair the operator restarts the pod so the Writer reverts to
-- normal mode.
--
-- Idempotent: safe to re-apply on already-migrated databases.

CREATE TABLE IF NOT EXISTS api_audit_log_quarantine (
    LIKE api_audit_log INCLUDING DEFAULTS INCLUDING CONSTRAINTS
);

-- Index mirrors the main table for efficient drain queries.
CREATE INDEX IF NOT EXISTS idx_aq_created_at
    ON api_audit_log_quarantine (created_at);
