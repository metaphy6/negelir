-- Phase 7 §7.1 — Quarantine sample storage.
--
-- `sec.input.v1` (and later `sec.scrape.v1`) emit `sec.quarantine.v1`
-- envelopes whenever they reject a payload. `storage.v1` is the SOLE
-- consumer that lands them here; the API gateway and the swarm runner
-- never read this table.
--
-- Doctrine notes:
--
--   * `raw_bytes` is BYTEA (not TEXT) because the offending payload
--     may contain arbitrary control bytes (zero-width spoofing,
--     compression bombs, malformed UTF-8). Producers cap it at
--     `cfg.sec_quarantine_payload_max_bytes` BEFORE base64 encoding;
--     the decode happens in the storage agent.
--
--   * `bytes_sha256` joins back to `sec.alert.v1.evidence_ref` so an
--     alert never inlines the offending bytes (cardinality + log-
--     injection guard). Held as TEXT (lowercase hex) for grep-ability.
--
--   * `pii_redacted` is a producer-side flag: `true` means a known
--     sensitive field was scrubbed before quarantine (e.g. the auth
--     password buffer per §7.1). The right-to-erasure column
--     `erased_at` separately marks rows scrubbed via DSAR / GDPR
--     after the fact — `raw_bytes` MUST be replaced with a 1-byte
--     tombstone when this is set, never NULLed (storage agent
--     enforces; constraint below pins the invariant).
--
--   * `verdict` is constrained to the literal "quarantine" today;
--     the column is kept open-shape so future verdicts (e.g.
--     "review") can be added without a schema migration.
--
--   * Index on `(detected_at)` powers the TTL sweeper
--     (`cfg.sec_quarantine_ttl_days`); index on `bytes_sha256` powers
--     the sec.alert.v1 → sec.quarantine.v1 join from dashboards.

CREATE TABLE IF NOT EXISTS quarantine_samples (
    quarantine_id   TEXT        PRIMARY KEY,
    source          TEXT        NOT NULL CHECK (source IN ('qa', 'scrape')),
    raw_bytes       BYTEA       NOT NULL,
    verdict         TEXT        NOT NULL CHECK (verdict IN ('quarantine')),
    reasons         TEXT[]      NOT NULL CHECK (cardinality(reasons) >= 1),
    detected_at     TIMESTAMPTZ NOT NULL,
    pii_redacted    BOOLEAN     NOT NULL DEFAULT FALSE,
    client_id       TEXT,
    ip              TEXT,
    bytes_sha256    TEXT        NOT NULL CHECK (bytes_sha256 ~ '^[0-9a-f]{64}$'),
    erased_at       TIMESTAMPTZ,
    -- Right-to-erasure invariant: when erased_at is set, raw_bytes is
    -- the 1-byte tombstone (0x00). Producers never write a 1-byte
    -- payload (cap is bytes >= sha256-of-empty would imply length==0);
    -- 1 byte is unambiguously a post-erasure marker.
    CONSTRAINT quarantine_samples_erased_invariant
        CHECK (erased_at IS NULL OR octet_length(raw_bytes) = 1)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_samples_detected_at
    ON quarantine_samples (detected_at);

CREATE INDEX IF NOT EXISTS idx_quarantine_samples_bytes_sha256
    ON quarantine_samples (bytes_sha256);

CREATE INDEX IF NOT EXISTS idx_quarantine_samples_source_detected
    ON quarantine_samples (source, detected_at DESC);
