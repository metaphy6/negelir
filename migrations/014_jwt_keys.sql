-- Phase 9 §9.2 — JWT key store.
--
-- Stores RS256 (and future ES256) key metadata. Private key material
-- lives on disk at data/api/jwt_keys/<kid>.priv.pem (mode 0400); this
-- table holds only the path to the private key file and the full
-- public key PEM (safe to expose to verifiers).
--
-- Status lifecycle (§9.2 rotation runbook):
--   pending  — generated but not yet promoted; verifiers ignore,
--              signers ignore.
--   active   — current signing key; at most ONE row may be active
--              (enforced by the unique partial index below).
--   retired  — rotated out; verifiers STILL accept tokens signed by
--              this key until natural JWT expiry (grace period
--              cfg.api_jwt_retired_grace_s).
--   purged   — priv key file zeroized and removed; public key PEM
--              retained for forensic log verification only.
--
-- Rotation runbook: make api.rotate-jwt-key  (§9.2)
--
-- Idempotent: safe to re-apply on already-migrated databases.

CREATE TABLE IF NOT EXISTS jwt_keys (
    kid              TEXT        NOT NULL PRIMARY KEY,
    alg              TEXT        NOT NULL DEFAULT 'RS256',
    pub_pem          TEXT        NOT NULL,
    -- Absolute path to the private key file (mode 0400).
    -- Empty string when status = 'purged' (file has been removed).
    priv_pem_path    TEXT        NOT NULL DEFAULT '',
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_in_at    TIMESTAMPTZ,
    rotated_out_at   TIMESTAMPTZ,
    status           TEXT        NOT NULL DEFAULT 'pending',
    CONSTRAINT jwt_keys_alg_chk    CHECK (alg    IN ('RS256', 'ES256')),
    CONSTRAINT jwt_keys_status_chk CHECK (status IN ('pending', 'active', 'retired', 'purged'))
);

-- Verifier hot path: look up by kid for status and pub_pem.
CREATE INDEX IF NOT EXISTS idx_jwt_keys_status
    ON jwt_keys (status);

-- Enforce at most one active key at a time.
-- A unique partial index on status='active' rejects a second INSERT
-- with status='active' before the old one is flipped to 'retired'.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jwt_keys_single_active
    ON jwt_keys (status)
    WHERE status = 'active';

-- updated_at auto-bump on any row mutation (rotation events).
CREATE OR REPLACE FUNCTION jwt_keys_bump_updated() RETURNS TRIGGER AS $$
BEGIN
    -- no-op function: jwt_keys has no updated_at column; this hook exists
    -- as a placeholder for the §9.2 audit-event pg_notify on key rotation.
    PERFORM pg_notify('jwt_key_rotated', json_build_object(
        'kid',    NEW.kid,
        'status', NEW.status
    )::text);
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_jwt_keys_notify ON jwt_keys;
CREATE TRIGGER trg_jwt_keys_notify
    AFTER UPDATE OF status ON jwt_keys
    FOR EACH ROW
    EXECUTE FUNCTION jwt_keys_bump_updated();
