# Negelir — Data Sources, Fetch Mechanisms & Database Reference

> Detailed reference: what is scraped, how it flows, where it is stored, what queries run, and how the AI consumes it.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Sources](#2-data-sources)
3. [Scraping Process Mechanism](#3-scraping-process-mechanism)
4. [HTML Extraction — CSS Selectors](#4-html-extraction--css-selectors)
5. [Go Middleware Server — REST API & SQL Queries](#5-go-middleware-server--rest-api--sql-queries)
6. [PostgreSQL Database Schema](#6-postgresql-database-schema)
7. [Redis Cache Layer](#7-redis-cache-layer)
8. [JSON Structures — Full Examples](#8-json-structures--full-examples)
9. [Feature Extraction from Raw Data](#9-feature-extraction-from-raw-data)
10. [Data Provenance Obfuscation](#10-data-provenance-obfuscation)
11. [Environment Configuration](#11-environment-configuration)
12. [Scrape Task Lifecycle](#12-scrape-task-lifecycle)

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│              EXTERNAL DATA SOURCES  (HTTPS)                        │
│   Source A: arsiv.mackolik.com   — historical match archive        │
│   Source B: www.mackolik.com     — live scores & league tables     │
│   Source C: www.tff.org          — official TFF results            │
│   Source Extra: (user-defined via .env, comma-separated)           │
└──────────────────┬─────────────────────────────────────────────────┘
                   │ Rate-limited HTTPS (1 req / 5s per domain)
                   │ robots.txt respected
                   ▼
┌────────────────────────────────────────────────────────────────────┐
│           GO MIDDLEWARE SERVER  (Gin, port 8080)                   │
│                                                                    │
│  • Accepts scrape triggers via POST /api/v1/scrape/trigger         │
│  • Fetches external pages, parses HTML, stores structured data     │
│  • Caches hot queries in Redis (TTL varies per route)              │
│  • Exposes 7 REST endpoints to the AI module                       │
└──────┬─────────────────────────┬──────────────────────────────────┘
       │ pgxpool (max 10 conns)  │ go-redis
       ▼                         ▼
┌─────────────────┐     ┌────────────────────┐
│  PostgreSQL 16  │     │   Redis 7 (cache)  │
│  7 core tables  │     │  TTL: 60s – 300s   │
│  + 4 indexes    │     └────────────────────┘
└─────────────────┘
       │
       │ REST (HTTP) → GET /api/v1/matches, /teams, /features
       ▼
┌────────────────────────────────────────────────────────────────────┐
│           PYTHON AI MODULE  (Docker service, no exposed port)      │
│                                                                    │
│  ScrapingEngine → DataProofreader → FeatureEngineering             │
│  → GBDTInference → P2PConsensus → TQU → TRC → Turkish response    │
└────────────────────────────────────────────────────────────────────┘
```

**Stack:**
- Go 1.23, Gin v1.9, pgxpool v5.5, go-redis v9.4
- Python 3.11, requests, BeautifulSoup4, lxml, XGBoost, numpy

---

## 2. Data Sources

Sources are configured entirely via `.env` and passed to the AI container through Docker Compose. No source URL is ever hard-coded in application logic.

### Source A — Historical Match Archive

| | |
|---|---|
| Env var | `SCRAPE_SOURCE_A` |
| Default | `https://arsiv.mackolik.com` |
| Internal label | `source_a` |
| Purpose | Historical match results, half-time scores, detailed per-match statistics |
| Coverage | Last 5 seasons (per roadmap §2 scope) |
| CSS selector set | `source_a` in `selectors.json` |

**Fields extracted:**
- Full-time score (`home_score`, `away_score`)
- Half-time score (`ht_home_score`, `ht_away_score`)
- Match date, home team name, away team name
- Stats: possession %, shots on target, shots off target, corners, fouls

### Source B — Live Scores & League Tables

| | |
|---|---|
| Env var | `SCRAPE_SOURCE_B` |
| Default | `https://www.mackolik.com` |
| Internal label | `source_b` |
| Purpose | Live and recent match results, current league standings |
| CSS selector set | `source_b` in `selectors.json` |

**Fields extracted:**
- Recent match results (current season)
- League table: position, team, played, won, drawn, lost, GF, GA, GD, points

### Source C — Official TFF Results

| | |
|---|---|
| Env var | `SCRAPE_SOURCE_C` |
| Default | `https://www.tff.org` |
| Internal label | `source_c` |
| Purpose | Authoritative fixture list, confirmed final scores |
| CSS selector set | `source_c` in `selectors.json` |

**Fields extracted:**
- Fixture date, round, home team, away team
- Official confirmed score
- Referee identity (stored only as SHA-256 hash, never as name)

### Source Extra — User-Configured

| | |
|---|---|
| Env var | `SCRAPE_SOURCE_EXTRA` |
| Default | *(empty)* |
| Format | Comma-separated URLs: `https://site1.com,https://site2.com` |
| Internal label | `source_extra` |

Additional sources can be added without touching code — only the `.env` file.

**Example `.env`:**
```dotenv
SCRAPE_SOURCE_A=https://arsiv.mackolik.com
SCRAPE_SOURCE_B=https://www.mackolik.com
SCRAPE_SOURCE_C=https://www.tff.org
SCRAPE_SOURCE_EXTRA=https://example1.com,https://example2.com
```

---

## 3. Scraping Process Mechanism

### 3.1 Preferred Path: Go Middleware Delegation

The Python AI module **does not scrape directly in normal operation**. It delegates to the Go server:

```
AI module (ScrapingEngine)
  │
  ├─ Step 1: check_server_health()
  │     GET /api/v1/health
  │     → HTTP 200 {"status": "healthy", "database": true, "redis": true}
  │
  ├─ Step 2: trigger_server_scrape()
  │     POST /api/v1/scrape/trigger
  │     → HTTP 202 {"task_id": "manual_...", "status": "pending"}
  │     Go server: inserts row into scrape_tasks table
  │
  └─ Step 3: fetch_matches_from_server()
        GET /api/v1/matches?league_id=super_lig&season=2025-2026
        → JSON array of matches from PostgreSQL (Redis-cached 60s)
```

### 3.2 Fallback Path: Direct Scraping

If the Go server is unreachable, `ScrapingEngine` scrapes directly:

```
For each source in cfg.scrape_sources:
  For each page 1..N:
    _respect_rate_limit(domain)          # sleep if < 5s since last request
    response = requests.get(url,
        headers={"User-Agent": cfg.scrape_user_agent},
        timeout=10)
    html = response.text
    matches = parse_match_page(html, SELECTOR_CONFIG[source])
    # html goes out of scope → garbage collected immediately
    all_matches.extend(matches)
```

### 3.3 Rate Limiting

```python
# ai/scraper/engine.py — _respect_rate_limit()
def _respect_rate_limit(self, domain: str):
    last = self._last_request_time.get(domain, 0)
    elapsed = time.time() - last
    if elapsed < self.rate_limit:          # default: 5 seconds
        wait = self.rate_limit - elapsed
        log.debug(f"⏱️  Rate limit: {wait:.1f}s waiting ({domain})")
        time.sleep(wait)
    self._last_request_time[domain] = time.time()
```

| Setting | Default | Env var |
|---|---|---|
| Rate limit | 5 seconds per domain | `SCRAPE_RATE_LIMIT_SECONDS` |
| User-Agent | `Negelir/0.1 (Football Analysis Research)` | `SCRAPE_USER_AGENT` |
| Respect robots.txt | `true` | `SCRAPE_RESPECT_ROBOTS_TXT` |

### 3.4 HTML Processing (RAM-only)

HTML is never written to disk or database. Processing is entirely in-memory:

```
1. requests.get(url)  →  response.text (str in RAM)
                ↓
2. BeautifulSoup(html, "lxml")  →  soup object in RAM
                ↓
3. soup.select(match_row_selector)  →  per-row extraction
                ↓
4. ParsedMatch dataclass built per row
                ↓
5. Function returns list[ParsedMatch]
   → soup and html go out of scope → garbage collected
```

Log output confirming RAM-only:
```
📄 47 matches parsed (HTML discarded from memory ✓)
```

### 3.5 ParsedMatch — Raw Extracted Record

```python
@dataclass
class ParsedMatch:
    home_team:     str        # "Galatasaray" — display name from HTML
    away_team:     str        # "Fenerbahçe"
    home_score:    int | None # Full-time home goals (None if not played)
    away_score:    int | None # Full-time away goals
    ht_home_score: int | None # Half-time home goals
    ht_away_score: int | None # Half-time away goals
    match_date:    str        # "2025-11-02" ISO date string
    stats:         dict       # {"possession": 58, "shots_on": 7, ...}
```

**`stats` dict keys:**

| Key | Type | Range | Description |
|---|---|---|---|
| `possession` | int | 0–100 | Home team ball possession % |
| `shots_on` | int | 0–40 | Shots on target |
| `shots_off` | int | 0–40 | Shots off target |
| `corners` | int | 0–25 | Corner kicks |
| `fouls` | int | 0–40 | Fouls committed |

---

## 4. HTML Extraction — CSS Selectors

File: `ai/scraper/selectors.json`

Multiple comma-separated selectors per field — tried in order, first match wins.

### Source A — Historical Archive

```json
{
  "match_row":       "div.match-row, tr.match-item, .mac-satiri",
  "home_team":       ".home-team .name, .ev-sahibi, td:nth-child(2)",
  "away_team":       ".away-team .name, .deplasman, td:nth-child(4)",
  "score":           ".score-cell, .skor, td:nth-child(3)",
  "date":            ".match-date, .tarih, td:nth-child(1)",
  "stats_container": ".match-stats, .mac-istatistik",
  "possession":      ".possession, .topa-sahip-olma",
  "shots_on":        ".shots-on-target, .isabetli-sut",
  "shots_off":       ".shots-off-target, .isabetsiz-sut",
  "corners":         ".corners, .korner",
  "fouls":           ".fouls, .faul"
}
```

Score parsing regex:
```python
_SCORE_RE = re.compile(r"(\d+)\s*[-:]\s*(\d+)")
# matches: "2-1",  "2 : 1",  "3 - 0",  "2:1"
```

### Source B — Live Scores & Standings

```json
{
  "match_row":        ".match-card, .event-row",
  "home_team":        ".home .team-name",
  "away_team":        ".away .team-name",
  "score":            ".score, .result",
  "date":             ".date, .event-date",
  "league_table_row": ".standings-row, tr.team-row",
  "position":         ".pos, td:nth-child(1)",
  "team_name":        ".team, td:nth-child(2)",
  "points":           ".pts, td:last-child"
}
```

### Source C — Official TFF

```json
{
  "fixture_row": ".fixture, .musabaka",
  "home_team":   ".home, .ev",
  "away_team":   ".away, .dep",
  "score":       ".result, .sonuc",
  "date":        ".date, .tarih",
  "referee":     ".referee, .hakem"
}
```

### Parsing Logic

```python
def parse_match_page(html: str, selectors: dict) -> list[ParsedMatch]:
    soup = BeautifulSoup(html, "lxml")
    for sel in selectors["match_row"].split(","):
        rows = soup.select(sel.strip())
        for row in rows:
            match = _extract_match_from_row(row, selectors)
            if match and match.home_team and match.away_team:
                matches.append(match)
    # soup + html go out of scope here
    return matches
```

---

## 5. Go Middleware Server — REST API & SQL Queries

**Tech stack:** Go 1.23 · Gin v1.9 · pgxpool v5.5 (max 10 conns, 5s timeout) · go-redis v9.4

### Endpoints Summary

| Method | Path | Redis cache key | Redis TTL | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/health` | — | — | DB + Redis liveness |
| `GET` | `/api/v1/matches` | `matches:list` | 60s | Last 50 matches |
| `GET` | `/api/v1/matches/:id` | — | — | Single match detail |
| `GET` | `/api/v1/teams` | `teams:list` | 300s | All teams |
| `GET` | `/api/v1/teams/:id` | — | — | Single team |
| `POST` | `/api/v1/scrape/trigger` | — | — | Queue scrape task |
| `GET` | `/api/v1/features/:match_id` | — | — | Pre-computed features |

---

### GET /api/v1/health

No SQL. Uses `pool.Ping(ctx)` (TCP-level) and `rdb.Ping(ctx)`.

```json
{
  "status":   "healthy",
  "database": true,
  "redis":    true,
  "version":  "0.1.0"
}
```

---

### GET /api/v1/matches

**Query parameters:** `league_id` · `season`

**Redis lookup:** `GET matches:list` → cache hit returns immediately

**SQL (cache miss):**
```sql
SELECT id, home_team, away_team, match_date, league_id, season,
       home_score, away_score, match_week
FROM raw_matches
ORDER BY match_date DESC
LIMIT 50;
```

**Response:**
```json
{
  "matches": [
    {
      "id":         1,
      "home_team":  "Galatasaray",
      "away_team":  "Fenerbahçe",
      "match_date": "2025-11-02",
      "league":     "super_lig",
      "season":     "2025-2026",
      "home_score": 3,
      "away_score": 1,
      "match_week": 12
    }
  ],
  "count": 1
}
```

---

### GET /api/v1/matches/:id

**SQL:**
```sql
SELECT home_team, away_team, match_date, league_id, season,
       home_score, away_score, match_week, stats_json::text
FROM raw_matches
WHERE id = $1;
```

**Response:**
```json
{
  "id":         "1",
  "home_team":  "Galatasaray",
  "away_team":  "Fenerbahçe",
  "match_date": "2025-11-02",
  "league":     "super_lig",
  "season":     "2025-2026",
  "home_score": 3,
  "away_score": 1,
  "match_week": 12
}
```

---

### GET /api/v1/teams

**Redis lookup:** `GET teams:list` → cache hit returns immediately

**SQL (cache miss):**
```sql
SELECT uuid, display_name, league_id, internal_code
FROM teams
ORDER BY display_name;
```

**Response (abridged):**
```json
{
  "teams": [
    { "id": "team_008", "name": "Alanyaspor",  "internal_code": "ALN", "league": "super_lig" },
    { "id": "team_019", "name": "Ankaragücü",  "internal_code": "MKE", "league": "super_lig" },
    { "id": "team_005", "name": "Başakşehir",  "internal_code": "IBB", "league": "super_lig" },
    { "id": "team_003", "name": "Beşiktaş",    "internal_code": "BJK", "league": "super_lig" },
    { "id": "team_052", "name": "Bodrum FK",   "internal_code": "BOD", "league": "lig_1"     },
    { "id": "team_002", "name": "Fenerbahçe",  "internal_code": "FB",  "league": "super_lig" },
    { "id": "team_001", "name": "Galatasaray", "internal_code": "GS",  "league": "super_lig" }
  ],
  "count": 24
}
```

---

### GET /api/v1/teams/:id

**SQL:**
```sql
SELECT display_name, league_id, internal_code
FROM teams
WHERE uuid = $1;
```

---

### POST /api/v1/scrape/trigger

**SQL:**
```sql
INSERT INTO scrape_tasks (task_id, source_id, data_type, match_date, status)
VALUES ($1, 'manual_trigger', 'full_scrape', CURRENT_DATE, 'pending');
```

**Response (202 Accepted):**
```json
{
  "task_id": "manual_1743684000000000000",
  "status":  "pending",
  "message": "Scrape task queued"
}
```

---

### GET /api/v1/features/:match_id

**SQL:**
```sql
SELECT team_uuid, season, match_week, elo_rating, form_index, xg_approximation,
       avg_goals_scored_5, avg_goals_conceded_5, points_per_game_5
FROM team_features
WHERE match_week = $1
ORDER BY team_uuid;
```

**Response:**
```json
{
  "match_week": "12",
  "features": [
    {
      "team_uuid":  "team_001",
      "season":     "2025-2026",
      "match_week": 12,
      "elo":        1722.5,
      "form":       0.81,
      "xg":         1.94,
      "scored_5":   2.2,
      "conceded_5": 0.8,
      "ppg_5":      2.4
    }
  ]
}
```

---

## 6. PostgreSQL Database Schema

File: `migrations/001_initial.sql`

### Table: `teams`

```sql
CREATE TABLE teams (
    uuid          TEXT PRIMARY KEY,   -- 'team_001' (internal, never a real DB ID)
    display_name  TEXT NOT NULL,      -- 'Galatasaray'
    league_id     TEXT NOT NULL,      -- 'super_lig' | 'lig_1'
    internal_code TEXT NOT NULL,      -- 'GS' | 'FB' | 'BJK' ...
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

**Seed data (24 teams):**

```sql
INSERT INTO teams (uuid, display_name, league_id, internal_code) VALUES
  -- Süper Lig (19 teams)
  ('team_001', 'Galatasaray',      'super_lig', 'GS' ),
  ('team_002', 'Fenerbahçe',       'super_lig', 'FB' ),
  ('team_003', 'Beşiktaş',         'super_lig', 'BJK'),
  ('team_004', 'Trabzonspor',      'super_lig', 'TS' ),
  ('team_005', 'Başakşehir',       'super_lig', 'IBB'),
  ('team_006', 'Adana Demirspor',  'super_lig', 'ADS'),
  ('team_007', 'Antalyaspor',      'super_lig', 'ANT'),
  ('team_008', 'Alanyaspor',       'super_lig', 'ALN'),
  ('team_009', 'Kasımpaşa',        'super_lig', 'KSM'),
  ('team_010', 'Konyaspor',        'super_lig', 'KNY'),
  ('team_011', 'Sivasspor',        'super_lig', 'SVS'),
  ('team_012', 'Kayserispor',      'super_lig', 'KYS'),
  ('team_013', 'Gaziantep FK',     'super_lig', 'GFK'),
  ('team_014', 'Hatayspor',        'super_lig', 'HTY'),
  ('team_015', 'Samsunspor',       'super_lig', 'SAM'),
  ('team_016', 'Çaykur Rizespor',  'super_lig', 'RZE'),
  ('team_017', 'Pendikspor',       'super_lig', 'PND'),
  ('team_018', 'Fatih Karagümrük', 'super_lig', 'FKG'),
  ('team_019', 'Ankaragücü',       'super_lig', 'MKE'),
  -- 1. Lig (5 sample teams)
  ('team_050', 'Eyüpspor',         'lig_1', 'EYP'),
  ('team_051', 'Göztepe',          'lig_1', 'GOZ'),
  ('team_052', 'Bodrum FK',        'lig_1', 'BOD'),
  ('team_053', 'Sakaryaspor',      'lig_1', 'SKR'),
  ('team_054', 'Keçiörengücü',     'lig_1', 'KCG')
ON CONFLICT (uuid) DO NOTHING;
```

---

### Table: `raw_matches`

Primary scrape output buffer — one row per match.

```sql
CREATE TABLE raw_matches (
    id             SERIAL PRIMARY KEY,
    source_id      TEXT NOT NULL,       -- 'source_a' | 'source_b' | 'source_c' (never real URLs)
    league_id      TEXT NOT NULL,       -- 'super_lig'
    season         TEXT NOT NULL,       -- '2025-2026'
    match_week     INTEGER NOT NULL,
    home_team      TEXT NOT NULL,       -- display name (not UUID — resolved at feature stage)
    away_team      TEXT NOT NULL,
    home_score     INTEGER,             -- NULL for future fixtures
    away_score     INTEGER,
    ht_home_score  INTEGER,
    ht_away_score  INTEGER,
    match_date     DATE,
    stats_json     JSONB,               -- see stats_json structure below
    scraped_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(league_id, season, match_week, home_team, away_team)
);

CREATE INDEX idx_raw_matches_league_week ON raw_matches(league_id, season, match_week);
```

**`stats_json` JSONB structure:**
```json
{
  "possession":    58,
  "shots_on":       7,
  "shots_off":      5,
  "corners":        8,
  "fouls":         14,
  "yellow_cards":   3,
  "red_cards":      0
}
```

---

### Table: `team_features`

AI-computed feature cache — one row per team per week.

```sql
CREATE TABLE team_features (
    team_uuid              TEXT NOT NULL REFERENCES teams(uuid),
    season                 TEXT NOT NULL,
    match_week             INTEGER NOT NULL,
    computed_at            TIMESTAMPTZ DEFAULT NOW(),

    -- Rolling form windows (3 / 5 / 10 matches)
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

    -- Derived ratings
    elo_rating             REAL DEFAULT 1500.0,
    form_index             REAL,          -- composite: [0, 1]
    xg_approximation       REAL,          -- Poisson expected goals proxy

    -- Squad & tactical
    formation_stability    REAL,          -- [0,1] — 1.0 = never changes XI
    squad_rotation_gini    REAL,          -- Gini coeff of minutes distribution
    goal_concentration_hhi REAL,          -- HHI of goal-scorers by position slot

    -- Scheduling
    fixture_congestion_7d  REAL,          -- matches in last 7 days
    fixture_congestion_14d REAL,

    -- Management
    manager_tenure_weeks   INTEGER,
    manager_change_flag    BOOLEAN DEFAULT FALSE,
    derby_flag             BOOLEAN DEFAULT FALSE,

    -- Sentiment (numeric scores only — no text ever stored, per roadmap §2D)
    media_sentiment_score  REAL,          -- [-1.0, +1.0]
    fan_optimism_index     REAL,          -- [-1.0, +1.0]
    noise_seed             INTEGER,       -- for reproducible ±0.5% noise injection

    PRIMARY KEY (team_uuid, season, match_week)
);

CREATE INDEX idx_team_features_week ON team_features(season, match_week);
```

---

### Table: `analyses`

XGBoost inference results (local and P2P ensemble).

```sql
CREATE TABLE analyses (
    analysis_id      TEXT PRIMARY KEY,    -- SHA-256(match_id + model_version + timestamp)
    match_identifier TEXT NOT NULL,
    league_id        TEXT NOT NULL,
    season           TEXT NOT NULL,
    match_week       INTEGER NOT NULL,
    model_version    TEXT NOT NULL,       -- '0.1.0'
    adaptation_gen   INTEGER DEFAULT 0,   -- self-improvement generation counter
    result_json      JSONB NOT NULL,      -- see §8 for full structure
    confidence       REAL,
    is_ensemble      BOOLEAN DEFAULT FALSE,
    peers_consulted  INTEGER DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_analyses_match ON analyses(match_identifier);
```

**`result_json` JSONB structure:**
```json
{
  "model_version": "0.1.0",
  "confidence": 0.82,
  "distribution": {
    "home_win": 0.610,
    "draw":     0.245,
    "away_win": 0.145
  },
  "goal_metrics": {
    "expected_total_goals": 2.94,
    "over_2_5_prob":        0.681,
    "bts_prob":             0.452
  },
  "feature_importance": {
    "away_elo":       0.0353,
    "form_diff":      0.0301,
    "home_elo":       0.0250,
    "away_ppg_10":    0.0242,
    "home_goal_diff": 0.0228
  },
  "features_used": 91
}
```

---

### Table: `outcome_validations`

Post-match ground truth — drives model accuracy tracking and P2P reputation updates.

```sql
CREATE TABLE outcome_validations (
    match_identifier  TEXT PRIMARY KEY,
    actual_result     TEXT NOT NULL,       -- 'H' | 'D' | 'A'
    actual_home_goals INTEGER NOT NULL,
    actual_away_goals INTEGER NOT NULL,
    analysis_id       TEXT REFERENCES analyses(analysis_id),
    prediction_error  REAL,               -- |predicted_prob - actual|
    was_correct       BOOLEAN,
    validated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

### Table: `peer_reputation`

Distributed reputation graph — one row per P2P node.

```sql
CREATE TABLE peer_reputation (
    peer_node_id        TEXT PRIMARY KEY,
    accuracy_rolling_50 REAL DEFAULT 0.0,  -- accuracy over last 50 validated matches
    calibration_score   REAL DEFAULT 0.0,  -- Brier score derived
    total_validated     INTEGER DEFAULT 0,
    trust_level         TEXT DEFAULT 'new', -- new | low | medium | high | leader
    last_validated_at   TIMESTAMPTZ,
    first_seen_at       TIMESTAMPTZ DEFAULT NOW()
);
```

**Trust level thresholds and ensemble weights:**

| `trust_level` | Condition | Weight in ensemble |
|---|---|---|
| `new` | `total_validated < 10` | 0.1 |
| `low` | `accuracy < 0.40` | 0.2 |
| `medium` | `accuracy 0.40–0.59` | 0.5 |
| `high` | `accuracy 0.60–0.74` | 1.0 |
| `leader` | `accuracy ≥ 0.75` | 1.5 |

---

### Table: `scrape_tasks`

Distributed scraping coordination queue.

```sql
CREATE TABLE scrape_tasks (
    task_id       TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,       -- 'source_a' | 'source_b' | 'source_c'
    data_type     TEXT NOT NULL,       -- 'full_scrape' | 'incremental' | 'fixtures_only'
    match_date    DATE NOT NULL,
    status        TEXT DEFAULT 'pending',  -- pending | assigned | completed | failed
    assigned_node TEXT,                -- peer_node_id that claimed the task
    content_hash  TEXT,                -- SHA-256(html_body) for duplicate detection
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scrape_tasks_status ON scrape_tasks(status);
```

---

### Table: `data_quarantine`

Records rejected by DataProofreader — kept for manual review without polluting live data.

```sql
CREATE TABLE data_quarantine (
    id             SERIAL PRIMARY KEY,
    source_id      TEXT NOT NULL,
    match_week     INTEGER NOT NULL,
    reason         TEXT NOT NULL,      -- human-readable: "Out of range: home_score=20 (expected: 0-15)"
    raw_json       JSONB NOT NULL,     -- the problematic record
    quarantined_at TIMESTAMPTZ DEFAULT NOW(),
    resolved       BOOLEAN DEFAULT FALSE
);
```

---

## 7. Redis Cache Layer

Redis 7 provides short-lived caching in front of PostgreSQL for read-heavy paths.

| Cache key | Backed by | SQL reading | TTL |
|---|---|---|---|
| `matches:list` | `/api/v1/matches` | `raw_matches ORDER BY match_date DESC LIMIT 50` | 60s |
| `teams:list` | `/api/v1/teams` | `teams ORDER BY display_name` | 300s |

Cache lookup pattern (Go):
```go
cached, err := rdb.Get(ctx, "matches:list").Result()
if err == nil && cached != "" {
    // Cache hit — return without touching PostgreSQL
    c.Data(http.StatusOK, "application/json", []byte(cached))
    return
}
// Cache miss → query PostgreSQL → write result to cache (future: rdb.Set)
```

---

## 8. JSON Structures — Full Examples

### Raw Match → `raw_matches` table

```json
{
  "source_id":      "source_a",
  "league_id":      "super_lig",
  "season":         "2025-2026",
  "match_week":     12,
  "home_team":      "Galatasaray",
  "away_team":      "Fenerbahçe",
  "home_score":     3,
  "away_score":     1,
  "ht_home_score":  1,
  "ht_away_score":  0,
  "match_date":     "2025-11-02",
  "stats_json": {
    "possession":    58,
    "shots_on":       7,
    "shots_off":      5,
    "corners":        8,
    "fouls":         14,
    "yellow_cards":   3,
    "red_cards":      0
  }
}
```

### Feature Vector (91 named dimensions)

```
Group               Count   Feature names
──────────────────  ─────   ────────────────────────────────────────
Team Form (home)      12    home_avg_scored_{3,5,10}
                            home_avg_conceded_{3,5,10}
                            home_ppg_{5,10}  home_clean_sheet_10
                            home_{win,draw,loss}_ratio_5

Team Form (away)      12    (mirror of home, prefix: away_)

Elo & Derived          9    home_elo  away_elo  elo_diff
                            home_xg  away_xg  xg_diff
                            home_form_index  away_form_index  form_diff

Head-to-Head           6    h2h_home_win_pct  h2h_draw_pct  h2h_avg_goals
                            h2h_over25_pct  h2h_bts_pct  h2h_count

League Position        9    home/away_league_pos_norm  pos_diff
                            home/away_goal_diff
                            home/away_pts_gap_leader
                            home/away_pts_gap_relegation

Squad & Tactical       8    home/away_formation_stability
                            home/away_squad_rotation_gini
                            home/away_goal_concentration
                            home/away_avg_age

Contextual            11    home/away_fixture_congestion_{7d,14d}
                            home/away_manager_tenure
                            home/away_manager_change
                            derby_flag  season_phase  match_week_norm

Temporal               7    day_sin  day_cos  month_sin  month_cos
                            home_rest_days  away_rest_days  rest_diff

Sentiment / NLP        5    home/away_media_sentiment
                            home/away_fan_optimism
                            media_consensus_strength

Derived / Composite    8    style_matchup_index  fatigue_diff
                            home/away_momentum
                            home/away_scoring_consistency
                            surprise_index_{home,away}

Weather / Venue        4    temperature_bucket  precipitation_flag
                            wind_category  venue_type
──────────────────  ─────
TOTAL                 91
```

**Compact vector (match #0, synthetic seed 42):**
```
[1.12, 0.56, 0.79, 2.02, 1.72, 1.18, 1.94, 0.12, 2.16, 0.91,    ← home form
 0.37, 0.53, 1.96, 2.92, 0.22, 1.50, 0.01, 2.44, 1.94, 1.16,    ← away form
 2.19, 0.77, 0.76, 0.52,                                          ← more away form
 1431.9, 1456.5, 1579.4, 2.50, 0.14, 2.00, 0.45, 0.10, 2.38,    ← elo / xg
 0.20, 0.91, 2.24, 0.00, 0.50, 2.54,                             ← h2h
 0.86, 0.57, 0.18, 1.45, 0.97, 1.51, 2.44, 2.00, 2.22,          ← league + squad
 1.01, 1.79, 0.59, 0.94, 0.67, 0.81, 25.92, 29.78, 3.00,        ← contextual
 1.00, 2.00, 0.00, 27.77, 31.36, 0.00, 0.00, 1.00, 0.00,
 0.22, 0.63, -0.00, -0.12, -0.63, 12.00, 28.00, 6.00,            ← temporal
 0.16, 0.43, 0.37, -0.82, 0.20, 0.80,                            ← sentiment
 1.74, 0.33, 1.76, 0.74, 1.76, 0.62, 0.92,                       ← derived
 3.00, 0.00, 3.00, 1.00]                                          ← weather/venue
```

### GBDT Model Output (`analyses.result_json`)

```json
{
  "model_version": "0.1.0",
  "features_used": 91,
  "confidence": 0.82,
  "distribution": {
    "home_win": 0.610,
    "draw":     0.245,
    "away_win": 0.145
  },
  "goal_metrics": {
    "expected_total_goals": 2.94,
    "over_2_5_prob":        0.681,
    "bts_prob":             0.452
  },
  "feature_importance": {
    "away_elo":       0.0353,
    "form_diff":      0.0301,
    "home_elo":       0.0250,
    "away_ppg_10":    0.0242,
    "home_goal_diff": 0.0228
  }
}
```

### P2P Message Payload (over SimulatedTransport / asyncio queues)

```json
{
  "message_type":   "analysis",
  "sender_id":      "node_alpha",
  "schema_version": "1.0",
  "timestamp":      1743684000.0,
  "ttl_hours":      168,
  "content_hash":   "a3f2b1c9d4e0f5...",
  "payload": {
    "match_id":       "super_lig_2025-2026_wk12_GS_FB",
    "home_win_prob":  0.66,
    "draw_prob":      0.20,
    "away_win_prob":  0.14,
    "confidence":     0.82,
    "model_version":  "0.1.0"
  }
}
```

### TQU Classification Result

```json
{
  "success":    true,
  "intent_id":  "match_winner",
  "confidence": 0.92,
  "entities": {
    "team_refs":  ["team_001", "team_002"],
    "team_names": ["Galatasaray", "Fenerbahçe"],
    "min_goals":  null,
    "max_goals":  null,
    "threshold":  2.5,
    "half":       null,
    "match_ref":  null
  }
}
```

### TRC Turkish Response

```json
{
  "verdict":     "Büyük ihtimalle evet.",
  "explanation": "Galatasaray son 5 maçının 3'ünü kazanmış ve form endeksi yükselişte. Rakip takımın deplasman performansı zayıf — son 5 deplasmanında sadece 1 galibiyet var. Kafa kafaya istatistiklerde de Galatasaray lehine. Güven: %82.",
  "intent":      "match_winner",
  "model_version": "0.1.0"
}
```

---

## 9. Feature Extraction from Raw Data

### Pipeline

```python
# Step 1: Parse HTML → ParsedMatch
matches = parse_match_page(html, SELECTOR_CONFIG["source_a"])

# Step 2: Validate
result = proofreader.validate_batch(matches)   # returns ValidationResult

# Step 3: Convert to feature vector
vec = extract_features_for_match(match.__dict__)
# Returns np.ndarray shape (1, 91), dtype float32

# Step 4: Inject noise  (per roadmap §6.2 Stage 5)
noised = inject_noise(vec, noise_pct=0.005, seed=42)

# Step 5: Feature firewall
is_valid, error = model.validate_features(noised)

# Step 6: Inference
analysis = model.predict(noised)
```

### `extract_features_for_match(match_data: dict) → np.ndarray`

```python
def extract_features_for_match(match_data: dict) -> np.ndarray:
    vec = np.zeros(91, dtype=np.float32)
    col_to_idx = {col: i for i, col in enumerate(FEATURE_COLUMNS)}
    for key, idx in col_to_idx.items():
        if key in match_data:
            val = match_data[key]
            if val is not None:
                vec[idx] = float(val)
    return vec.reshape(1, -1)   # shape: (1, 91)
```

Fields in the match dict that share a name with any of the 91 `FEATURE_COLUMNS` are mapped directly by name. Missing fields default to `0.0` (safe for gradient boosted trees).

### Feature Firewall — Range Clipping

```python
FEATURE_RANGES = {
    "elo":       (-500, 3500),
    "ratio":     (0, 1),
    "pct":       (0, 100),
    "norm":      (0, 1),
    "sentiment": (-1, 1),
    "optimism":  (-1, 1),
    "sin":       (-1, 1),
    "cos":       (-1, 1),
    "flag":      (0, 1),
    "age":       (15, 45),
    "scored":    (0, 10),
    "conceded":  (0, 10),
    "default":   (-100, 100),
}

# Out-of-range values are CLIPPED, not rejected:
features[0, i] = np.clip(val, lo, hi)
```

### Proofreader — Validation Checks

**Range checks:**
```python
RANGES = {
    "home_score":   (0, 15),
    "away_score":   (0, 15),
    "possession":   (0, 100),
    "shots_on":     (0, 40),
    "shots_off":    (0, 40),
    "corners":      (0, 25),
    "fouls":        (0, 40),
    "yellow_cards": (0, 10),
    "red_cards":    (0, 5),
}
```

**Consistency checks:**
- `home_poss + away_poss ≈ 100` (±5 tolerance)
- `ht_home_score ≤ ft_home_score` (HT score cannot exceed FT)

**Plausibility checks:**
- Total goals ≥ 10 → `warning` (statistically rare)
- Single team ≥ 8 goals → `error` (implausible)

**Batch threshold:**
```python
batch_valid = (quarantined_count / total_count) < 0.30
# > 30% quarantined → reject entire batch
```

---

## 10. Data Provenance Obfuscation

Per roadmap §6.2, source identity is systematically removed at every stage:

| Stage | What is removed / obfuscated |
|---|---|
| HTML fetch | Raw HTML processed in RAM, never written to disk or DB |
| `source_id` | Stored as `source_a`, never as real URL |
| Team names | Replaced with internal UUIDs (`team_001`) in all DB tables |
| Player names | Never collected — represented as position slots (`ST_01`) |
| Referee names | Stored as SHA-256 hash, never as plaintext |
| Sentiment text | News/social text analyzed in RAM; only the float score kept |
| Feature noise | ±0.5% uniform noise makes exact feature reconstruction infeasible |
| Raw HTML | Zero bytes retained after `BeautifulSoup` parse scope exits |

---

## 11. Environment Configuration

Full `.env` reference:

```dotenv
# ── PostgreSQL ───────────────────────────────────────────────────
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=negelir
POSTGRES_USER=negelir
POSTGRES_PASSWORD=negelir_dev_2026

# ── Redis ────────────────────────────────────────────────────────
REDIS_HOST=redis
REDIS_PORT=6379

# ── Go Middleware ────────────────────────────────────────────────
SERVER_URL=http://server:8080
SERVER_PORT=8080

# ── Scraping Behaviour ───────────────────────────────────────────
SCRAPE_RATE_LIMIT_SECONDS=5
SCRAPE_USER_AGENT=Negelir/0.1 (Football Analysis Research)
SCRAPE_RESPECT_ROBOTS_TXT=true

# ── Data Sources ─────────────────────────────────────────────────
SCRAPE_SOURCE_A=https://arsiv.mackolik.com
SCRAPE_SOURCE_B=https://www.mackolik.com
SCRAPE_SOURCE_C=https://www.tff.org
SCRAPE_SOURCE_EXTRA=        # comma-separated, empty disables extra sources
```

Python `Config` class resolves these at import time:

```python
@property
def scrape_sources(self) -> list[dict[str, str]]:
    sources = []
    if self.scrape_source_a:
        sources.append({"name": "source_a", "label": "Statistics Archive",
                         "url": self.scrape_source_a})
    if self.scrape_source_b:
        sources.append({"name": "source_b", "label": "Live Scores",
                         "url": self.scrape_source_b})
    if self.scrape_source_c:
        sources.append({"name": "source_c", "label": "Official Results",
                         "url": self.scrape_source_c})
    for extra in self.scrape_source_extra.split(","):
        extra = extra.strip()
        if extra:
            sources.append({"name": "source_extra", "label": "Extra Source",
                             "url": extra})
    return sources
```

---

## 12. Scrape Task Lifecycle

```
POST /api/v1/scrape/trigger
        │
        ▼ SQL INSERT
scrape_tasks — status='pending', source_id='manual_trigger', data_type='full_scrape'
        │
        ▼ Go worker picks up task (or future P2P node)
status = 'assigned', assigned_node = 'node_alpha'
        │
        ▼ HTTP GET external source
        │   → _respect_rate_limit(domain)  [5s cooldown]
        │   → requests.get(url, headers={"User-Agent": ...})
        │   → content_hash = SHA-256(response.text)  [dedup guard]
        │
        ▼ HTML parse
        │   BeautifulSoup + CSS selectors → list[ParsedMatch]
        │   HTML goes out of scope → garbage collected
        │
        ▼ Proofreader gate
        │   range_checks + consistency_checks + plausibility_checks
        │
        ├─── passes ──▶ INSERT INTO raw_matches … ON CONFLICT DO NOTHING
        │               status = 'completed', completed_at = NOW()
        │
        └─── fails  ──▶ INSERT INTO data_quarantine (reason, raw_json)
                        status = 'failed'

AI module consumption:
  GET /api/v1/matches → reads raw_matches (Redis-cached 60s)
  GET /api/v1/features/{week} → reads team_features (computed by AI, stored back)
  POST /api/v1/scrape/trigger → queues next refresh
```

### Deduplication

The `UNIQUE` constraint on `raw_matches` prevents duplicate inserts:
```sql
UNIQUE(league_id, season, match_week, home_team, away_team)
```

The `content_hash` column in `scrape_tasks` (SHA-256 of the raw HTML body) provides an additional dedup layer across nodes in the P2P network — if two nodes scrape the same page, the second insert is a no-op.
