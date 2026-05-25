-- Phase 8 §8.7 — pattern_allowlist FP-loop state.
--
-- Operator-confirmed false positives flow through this table. The
-- `state` column is a one-character codec (CHECK-constrained):
--
--   'p' — pending: a quarantined sample matched this pattern, the
--         operator has not yet confirmed it as a FP. The maint.sec.v1
--         FP loop accumulates qids here.
--   'a' — active: operator confirmed the FP; the parent rule
--         suppresses further matches of this pattern. Active for
--         `cfg.maint_sec_pattern_ttl_s` seconds, then transitions
--         to 'e'.
--   'e' — expired: pattern is no longer suppressing the parent rule.
--         A new match restarts the lifecycle at 'p'.
--
-- Single-writer is enforced by advisory lock LOCK_MAINT_SEC_ALLOWLIST
-- (xops/maint/advisory_lock_keys.py). Reads are unrestricted.

CREATE TABLE IF NOT EXISTS pattern_allowlist (
    id              BIGSERIAL PRIMARY KEY,
    pattern         TEXT          NOT NULL UNIQUE,
    fingerprint_alg CHAR(1)       NOT NULL DEFAULT 'h',
    state           CHAR(1)       NOT NULL,
    parent_rule     TEXT          NOT NULL DEFAULT '',
    qids            TEXT[]        NOT NULL DEFAULT ARRAY[]::TEXT[],
    promoted_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT pattern_allowlist_state_chk CHECK (state IN ('p', 'a', 'e')),
    CONSTRAINT pattern_allowlist_alg_chk CHECK (fingerprint_alg IN ('h', 's'))
);

-- Hot read path: only active patterns suppress the parent rule.
-- A partial index keeps it tiny even when the table accumulates
-- expired rows for forensic purposes.
CREATE INDEX IF NOT EXISTS idx_pattern_allowlist_active
    ON pattern_allowlist (pattern)
    WHERE state = 'a';

-- Expiry sweep reads this — composite to support the planned
-- WHERE state='a' AND expires_at < now() in §8.7b.
CREATE INDEX IF NOT EXISTS idx_pattern_allowlist_expires
    ON pattern_allowlist (expires_at)
    WHERE state = 'a';

-- updated_at auto-bump on any row mutation.
CREATE OR REPLACE FUNCTION pattern_allowlist_bump_updated() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pattern_allowlist_bump ON pattern_allowlist;
CREATE TRIGGER trg_pattern_allowlist_bump
    BEFORE UPDATE ON pattern_allowlist
    FOR EACH ROW
    EXECUTE FUNCTION pattern_allowlist_bump_updated();
