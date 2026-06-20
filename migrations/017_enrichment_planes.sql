-- Phase 21.7: Enrichment planes storage schema
-- Creates all 10 enrichment tables per ENRICHMENT_DATA.md §8

CREATE TABLE IF NOT EXISTS transfers (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    from_team_id TEXT,
    to_team_id TEXT,
    effective_at TIMESTAMPTZ NOT NULL,
    confidence TEXT NOT NULL CHECK (confidence IN ('rumour', 'agreed', 'official')),
    transfer_type TEXT,
    fee_estimated_usd NUMERIC,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(player_id, effective_at, confidence)
);

CREATE TABLE IF NOT EXISTS contracts (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    contract_type TEXT,
    wage_usd_annual NUMERIC,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(player_id, team_id, starts_at)
);

CREATE TABLE IF NOT EXISTS suspensions (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    competition_id TEXT NOT NULL,
    expires_after_match_id TEXT,
    matches_remaining INT,
    reason TEXT,
    effective_from TIMESTAMPTZ NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(player_id, competition_id, effective_from)
);

CREATE TABLE IF NOT EXISTS injuries (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    fixture_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('fit', 'doubtful', 'out', 'suspended', 'international_duty')),
    status_confidence TEXT,
    source_confidence TEXT,
    source_url_hash TEXT,
    asserted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(player_id, fixture_id, status, source_confidence)
);

CREATE TABLE IF NOT EXISTS availability (
    id BIGSERIAL PRIMARY KEY,
    player_id TEXT NOT NULL,
    fixture_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('fit', 'doubtful', 'out', 'suspended', 'international_duty')),
    source_confidence TEXT,
    source_url_hash TEXT,
    asserted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(player_id, fixture_id, status)
);

CREATE TABLE IF NOT EXISTS referee_assignments (
    id BIGSERIAL PRIMARY KEY,
    fixture_id TEXT NOT NULL UNIQUE,
    main_referee_id TEXT NOT NULL,
    assistant1_id TEXT,
    assistant2_id TEXT,
    fourth_official_id TEXT,
    announced_at TIMESTAMPTZ NOT NULL,
    last_minute_change BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS referee_profiles (
    id BIGSERIAL PRIMARY KEY,
    referee_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    nationality TEXT,
    yellows_per_match NUMERIC,
    reds_per_match NUMERIC,
    penalties_per_match NUMERIC,
    home_win_pct NUMERIC,
    last_updated TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS weather_forecasts (
    id BIGSERIAL PRIMARY KEY,
    venue_id TEXT NOT NULL,
    valid_at TIMESTAMPTZ NOT NULL,
    conditions TEXT,
    wind_kph NUMERIC,
    precip_mm_per_hr NUMERIC,
    temp_celsius NUMERIC,
    humidity_pct NUMERIC,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(venue_id, valid_at)
);

CREATE TABLE IF NOT EXISTS weather_actuals (
    id BIGSERIAL PRIMARY KEY,
    venue_id TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    conditions TEXT,
    wind_kph NUMERIC,
    precip_mm_per_hr NUMERIC,
    temp_celsius NUMERIC,
    humidity_pct NUMERIC,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(venue_id, observed_at)
);

CREATE TABLE IF NOT EXISTS pitch_conditions (
    id BIGSERIAL PRIMARY KEY,
    venue_id TEXT NOT NULL,
    condition TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(venue_id, observed_at)
);

-- Indexes for common query patterns
CREATE INDEX idx_transfers_player_id ON transfers(player_id);
CREATE INDEX idx_transfers_effective_at ON transfers(effective_at DESC);
CREATE INDEX idx_contracts_player_id ON contracts(player_id);
CREATE INDEX idx_contracts_team_id ON contracts(team_id);
CREATE INDEX idx_suspensions_player_id ON suspensions(player_id);
CREATE INDEX idx_suspensions_competition_id ON suspensions(competition_id);
CREATE INDEX idx_injuries_player_id ON injuries(player_id);
CREATE INDEX idx_injuries_fixture_id ON injuries(fixture_id);
CREATE INDEX idx_availability_player_id ON availability(player_id);
CREATE INDEX idx_availability_fixture_id ON availability(fixture_id);
CREATE INDEX idx_referee_assignments_fixture_id ON referee_assignments(fixture_id);
CREATE INDEX idx_referee_profiles_name ON referee_profiles(name);
CREATE INDEX idx_weather_forecasts_venue_id ON weather_forecasts(venue_id);
CREATE INDEX idx_weather_forecasts_valid_at ON weather_forecasts(valid_at DESC);
CREATE INDEX idx_weather_actuals_venue_id ON weather_actuals(venue_id);
CREATE INDEX idx_weather_actuals_observed_at ON weather_actuals(observed_at DESC);
CREATE INDEX idx_pitch_conditions_venue_id ON pitch_conditions(venue_id);

-- Retention policies (TTL enforced by Phase 8 maintenance agent)
-- weather_forecasts: 30 days
-- suspensions: 90 days after expiry
-- All others: indefinite
