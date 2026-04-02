-- ══════════════════════════════════════════════════════════
--  Negelir — Initial Database Schema
--  PostgreSQL 16
-- ══════════════════════════════════════════════════════════

-- Teams registry (obfuscated identifiers per roadmap §6.2)
CREATE TABLE IF NOT EXISTS teams (
    uuid          TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    league_id     TEXT NOT NULL,
    internal_code TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Raw scraped match data (cached by Go server, consumed by AI)
CREATE TABLE IF NOT EXISTS raw_matches (
    id            SERIAL PRIMARY KEY,
    source_id     TEXT NOT NULL,       -- 'source_a', 'source_b' (never real URLs)
    league_id     TEXT NOT NULL,
    season        TEXT NOT NULL,
    match_week    INTEGER NOT NULL,
    home_team     TEXT NOT NULL,
    away_team     TEXT NOT NULL,
    home_score    INTEGER,
    away_score    INTEGER,
    ht_home_score INTEGER,
    ht_away_score INTEGER,
    match_date    DATE,
    stats_json    JSONB,               -- possession, shots, corners, etc.
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(league_id, season, match_week, home_team, away_team)
);

-- Transformed feature store (AI-processed, per roadmap §5.2)
CREATE TABLE IF NOT EXISTS team_features (
    team_uuid              TEXT NOT NULL REFERENCES teams(uuid),
    season                 TEXT NOT NULL,
    match_week             INTEGER NOT NULL,
    computed_at            TIMESTAMPTZ DEFAULT NOW(),
    -- Rolling averages
    avg_goals_scored_3     REAL,
    avg_goals_scored_5     REAL,
    avg_goals_scored_10    REAL,
    avg_goals_conceded_3   REAL,
    avg_goals_conceded_5   REAL,
    avg_goals_conceded_10  REAL,
    points_per_game_5      REAL,
    points_per_game_10     REAL,
    clean_sheet_ratio_10   REAL,
    home_win_ratio_10      REAL,
    away_win_ratio_10      REAL,
    -- Derived
    elo_rating             REAL DEFAULT 1500.0,
    form_index             REAL,
    xg_approximation       REAL,
    -- Squad & tactical
    formation_stability    REAL,
    squad_rotation_gini    REAL,
    goal_concentration_hhi REAL,
    -- Contextual
    fixture_congestion_7d  REAL,
    fixture_congestion_14d REAL,
    manager_tenure_weeks   INTEGER,
    manager_change_flag    BOOLEAN DEFAULT FALSE,
    derby_flag             BOOLEAN DEFAULT FALSE,
    -- Sentiment (bare floats, no text ever stored per roadmap §2D)
    media_sentiment_score  REAL,
    fan_optimism_index     REAL,
    -- Meta
    noise_seed             INTEGER,
    PRIMARY KEY (team_uuid, season, match_week)
);

-- AI analysis results
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id          TEXT PRIMARY KEY,
    match_identifier     TEXT NOT NULL,
    league_id            TEXT NOT NULL,
    season               TEXT NOT NULL,
    match_week           INTEGER NOT NULL,
    model_version        TEXT NOT NULL,
    adaptation_gen       INTEGER DEFAULT 0,
    result_json          JSONB NOT NULL,
    confidence           REAL,
    is_ensemble          BOOLEAN DEFAULT FALSE,
    peers_consulted      INTEGER DEFAULT 0,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

-- Outcome validations (post-match learning per roadmap §5.3.1)
CREATE TABLE IF NOT EXISTS outcome_validations (
    match_identifier    TEXT PRIMARY KEY,
    actual_result       TEXT NOT NULL,       -- 'H', 'D', 'A'
    actual_home_goals   INTEGER NOT NULL,
    actual_away_goals   INTEGER NOT NULL,
    analysis_id         TEXT REFERENCES analyses(analysis_id),
    prediction_error    REAL,
    was_correct         BOOLEAN,
    validated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Peer reputation (per roadmap §5.3.3)
CREATE TABLE IF NOT EXISTS peer_reputation (
    peer_node_id         TEXT PRIMARY KEY,
    accuracy_rolling_50  REAL DEFAULT 0.0,
    calibration_score    REAL DEFAULT 0.0,
    total_validated      INTEGER DEFAULT 0,
    trust_level          TEXT DEFAULT 'new',
    last_validated_at    TIMESTAMPTZ,
    first_seen_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Scrape task log (distributed coordination per roadmap §4.2)
CREATE TABLE IF NOT EXISTS scrape_tasks (
    task_id        TEXT PRIMARY KEY,
    source_id      TEXT NOT NULL,
    data_type      TEXT NOT NULL,
    match_date     DATE NOT NULL,
    status         TEXT DEFAULT 'pending',    -- pending, assigned, completed, failed
    assigned_node  TEXT,
    content_hash   TEXT,
    completed_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Data quarantine (proofreading per roadmap §5.1 Task Orchestrator)
CREATE TABLE IF NOT EXISTS data_quarantine (
    id            SERIAL PRIMARY KEY,
    source_id     TEXT NOT NULL,
    match_week    INTEGER NOT NULL,
    reason        TEXT NOT NULL,
    raw_json      JSONB NOT NULL,
    quarantined_at TIMESTAMPTZ DEFAULT NOW(),
    resolved      BOOLEAN DEFAULT FALSE
);

-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_raw_matches_league_week ON raw_matches(league_id, season, match_week);
CREATE INDEX IF NOT EXISTS idx_team_features_week ON team_features(season, match_week);
CREATE INDEX IF NOT EXISTS idx_analyses_match ON analyses(match_identifier);
CREATE INDEX IF NOT EXISTS idx_scrape_tasks_status ON scrape_tasks(status);

-- ══════════════════════════════════════════════════════════
--  Seed Data — Turkish Süper Lig & 1. Lig Teams
--  UUIDs are internal, per roadmap §6.2 Identity Obfuscation
-- ══════════════════════════════════════════════════════════

INSERT INTO teams (uuid, display_name, league_id, internal_code) VALUES
    -- Süper Lig
    ('team_001', 'Galatasaray',     'super_lig', 'GS'),
    ('team_002', 'Fenerbahçe',      'super_lig', 'FB'),
    ('team_003', 'Beşiktaş',        'super_lig', 'BJK'),
    ('team_004', 'Trabzonspor',     'super_lig', 'TS'),
    ('team_005', 'Başakşehir',      'super_lig', 'IBB'),
    ('team_006', 'Adana Demirspor', 'super_lig', 'ADS'),
    ('team_007', 'Antalyaspor',     'super_lig', 'ANT'),
    ('team_008', 'Alanyaspor',      'super_lig', 'ALN'),
    ('team_009', 'Kasımpaşa',       'super_lig', 'KSM'),
    ('team_010', 'Konyaspor',       'super_lig', 'KNY'),
    ('team_011', 'Sivasspor',       'super_lig', 'SVS'),
    ('team_012', 'Kayserispor',     'super_lig', 'KYS'),
    ('team_013', 'Gaziantep FK',    'super_lig', 'GFK'),
    ('team_014', 'Hatayspor',       'super_lig', 'HTY'),
    ('team_015', 'Samsunspor',      'super_lig', 'SAM'),
    ('team_016', 'Çaykur Rizespor', 'super_lig', 'RZE'),
    ('team_017', 'Pendikspor',      'super_lig', 'PND'),
    ('team_018', 'Fatih Karagümrük','super_lig', 'FKG'),
    ('team_019', 'Ankaragücü',      'super_lig', 'MKE'),
    -- 1. Lig (sample)
    ('team_050', 'Eyüpspor',        'lig_1', 'EYP'),
    ('team_051', 'Göztepe',         'lig_1', 'GOZ'),
    ('team_052', 'Bodrum FK',       'lig_1', 'BOD'),
    ('team_053', 'Sakaryaspor',     'lig_1', 'SKR'),
    ('team_054', 'Keçiörengücü',    'lig_1', 'KCG')
ON CONFLICT (uuid) DO NOTHING;
