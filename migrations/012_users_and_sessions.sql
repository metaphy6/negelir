-- Phase 9 §9.2 — users, tiers, and user sessions.
--
-- `tiers` is the built-but-dormant Phase 20 quota tier table.
-- Phase 9 seeds it with the single "free" tier so `users.tier_id`
-- has a valid FK target from day one; Phase 20 adds named tiers.
--
-- `users` stores credentials and preferences. No PII leaves this
-- table via JWT — only `sub` (user_id UUIDv4) + scopes are ever
-- present in the token. email_lower uses CITEXT so uniqueness is
-- case-insensitive; the raw-case `email` column is kept for display.
--
-- `user_sessions` is the DB-backed audit trail of issued sessions.
-- The live session state (refresh token validity, revocation) lives
-- in Redis `auth:refresh:<sha256(token)[:16]>`. This table is the
-- durable forensic record, written on issue and on revoke.
--
-- Idempotent: safe to re-apply on already-migrated databases.

CREATE EXTENSION IF NOT EXISTS citext;

-- ── Tiers (Phase 20 hook; seeded here so FK always resolves) ─────────
CREATE TABLE IF NOT EXISTS tiers (
    id          SERIAL      PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    description TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the baseline "free" tier; skip if already present.
INSERT INTO tiers (id, name, description)
VALUES (1, 'free', 'Baseline tier — all users default here until Phase 20 activates tier enforcement')
ON CONFLICT (id) DO NOTHING;

-- ── Users ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    email           TEXT        NOT NULL,
    email_lower     CITEXT      NOT NULL,
    password_hash   TEXT        NOT NULL,
    -- 'b' = bcrypt (OWASP 2024 floor, cost >= 12 per §9.2)
    -- 'a' = argon2id (reserved for future transparent swap)
    password_alg    CHAR(1)     NOT NULL DEFAULT 'b',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    locale          TEXT        NOT NULL DEFAULT 'tr-TR',
    tz              TEXT        NOT NULL DEFAULT 'Europe/Istanbul',
    tier_id         INTEGER     NOT NULL DEFAULT 1 REFERENCES tiers(id),
    -- 0 = active   1 = suspended   2 = deleted (soft-delete;
    -- hard purge is the Phase 20 GDPR path)
    status          SMALLINT    NOT NULL DEFAULT 0,
    CONSTRAINT users_password_alg_chk CHECK (password_alg IN ('b', 'a')),
    CONSTRAINT users_status_chk        CHECK (status IN (0, 1, 2))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
    ON users (email_lower);

CREATE INDEX IF NOT EXISTS idx_users_tier_id
    ON users (tier_id);

CREATE INDEX IF NOT EXISTS idx_users_status
    ON users (status)
    WHERE status != 0;

-- ── User sessions (durable audit trail; live state is in Redis) ───────
CREATE TABLE IF NOT EXISTS user_sessions (
    id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- jti = the `jti` claim of the access JWT issued for this session.
    -- UNIQUE so `make api.revoke-jti` lookups are O(1).
    jti             UUID        NOT NULL,
    -- sha256(refresh_token_bytes) stored; NEVER the raw token.
    refresh_hash    CHAR(64)    NOT NULL,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    -- TEXT rather than INET so the sanitized / masked form from
    -- §9.1 DeriveClientIP can be stored (may be a /24 mask string).
    client_ip       TEXT,
    user_agent      TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_sessions_jti
    ON user_sessions (jti);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id
    ON user_sessions (user_id);

-- Revocation scan: active sessions not yet expired.
CREATE INDEX IF NOT EXISTS idx_user_sessions_active
    ON user_sessions (user_id, expires_at)
    WHERE revoked_at IS NULL;
