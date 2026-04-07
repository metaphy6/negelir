-- ══════════════════════════════════════════════════════════
--  Negelir — Player Registry Schema
--  Phase 5: Dynamic player→team resolution
-- ══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS players (
    player_id    SERIAL PRIMARY KEY,
    source_id    VARCHAR(32) NOT NULL,       -- mackolik player ID
    name         VARCHAR(128) NOT NULL,
    team_id      VARCHAR(36) REFERENCES teams(uuid),
    position     VARCHAR(32),
    joined_at    TIMESTAMP,
    left_at      TIMESTAMP,                  -- NULL = currently on team
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(name);
