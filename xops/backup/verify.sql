-- xops/backup/verify.sql — Phase 8 §8.3 restore-verify probes.
--
-- Run inside a freshly-restored scratch database. Returns a
-- per-table row count plus the schema-migrations watermark; the
-- maint.backup.v1 agent compares the result against the source
-- DB census to decide ok / verify_failed.
--
-- Doctrine: read-only, no DDL, no DML. Adding a probed table is a
-- swarm minor bump (the verify_summary surface widens).

SELECT 'matches'              AS table, count(*) AS row_count FROM matches
UNION ALL
SELECT 'predict_final',                count(*)               FROM predict_final
UNION ALL
SELECT 'players',                      count(*)               FROM players
UNION ALL
SELECT 'schema_snapshots',             count(*)               FROM schema_snapshots
UNION ALL
SELECT 'pipeline_runs',                count(*)               FROM pipeline_runs
UNION ALL
SELECT 'predictor_audit',              count(*)               FROM predictor_audit
UNION ALL
SELECT 'quarantine_samples',           count(*)               FROM quarantine_samples
UNION ALL
SELECT 'source_fingerprints',          count(*)               FROM source_fingerprints
UNION ALL
SELECT 'maint_audit_log',              count(*)               FROM maint_audit_log
UNION ALL
SELECT 'pattern_allowlist',            count(*)               FROM pattern_allowlist;

-- Watermark probe — must match the source DB exactly.
SELECT '_schema_max_version' AS table, max(version)::bigint AS row_count
FROM schema_migrations;
