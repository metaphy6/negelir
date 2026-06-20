-- Down migration for Phase 21.25 enrichment audit table
-- Note: dropping the audit table discards all jurisdiction-gating decisions.
-- This is acceptable only in non-production environments (dev/CI).

DROP TABLE IF EXISTS enrichment_audit CASCADE;
