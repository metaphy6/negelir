# 🕷️ Negelir — Web Scraping & Data Pipeline Documentation

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Sources](#data-sources)
4. [Raw Data Format](#raw-data-format)
5. [Scraping Engine](#scraping-engine)
6. [CSS Selectors Configuration](#css-selectors-configuration)
7. [Data Parsing](#data-parsing)
8. [Data Proofreading & Validation](#data-proofreading--validation)
9. [Feature Engineering — From Raw Data to AI Input](#feature-engineering--from-raw-data-to-ai-input)
10. [Feature Vector Schema (91 Dimensions)](#feature-vector-schema-91-dimensions)
11. [How Data Feeds the AI Model](#how-data-feeds-the-ai-model)
12. [Database Schema](#database-schema)
13. [Go Middleware Server](#go-middleware-server)
14. [Security & Compliance](#security--compliance)
15. [Data Flow Diagram](#data-flow-diagram)

---

## Overview

Negelir's data pipeline collects Turkish football match data, validates it, transforms it into a 91-dimensional feature vector, and feeds it to an XGBoost GBDT model for match prediction. The system follows a strict **RAM-only processing** paradigm — raw HTML is never persisted to disk.

### Key Principles (from Roadmap §4.2)

- **Rate-limited**: Max 1 request per 5 seconds per domain
- **robots.txt-respecting**: Compliance with site crawling policies
- **RAM-only**: HTML is processed in memory and discarded immediately
- **No PII**: No personal data is collected or stored
- **Source anonymization**: Internal UUIDs replace source-identifying data (Roadmap §6.2)

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                           │
│   Source-A (Statistics)  Source-B (Live Scores)  Source-C      │
│        Archive              League Tables        (Official)   │
└────────────┬──────────────────┬──────────────────┬────────────┘
             │                  │                  │
             ▼                  ▼                  ▼
┌───────────────────────────────────────────────────────────────┐
│                    GO MIDDLEWARE SERVER                        │
│   • Triggers scraping       • Caches to PostgreSQL            │
│   • Rate limiting           • Redis caching                   │
│   • Health monitoring       • REST API for AI module          │
│   Endpoint: POST /api/v1/scrape/trigger                       │
└────────────────────────────┬──────────────────────────────────┘
                             │ JSON
                             ▼
┌───────────────────────────────────────────────────────────────┐
│                    AI SCRAPING ENGINE                          │
│   ai/scraper/engine.py                                        │
│   • Prefers Go server (cached data)                           │
│   • Fallback: direct scraping with rate limiting              │
│   • Uses CSS selectors from selectors.json                    │
└────────────────────────────┬──────────────────────────────────┘
                             │ ParsedMatch objects
                             ▼
┌───────────────────────────────────────────────────────────────┐
│                    HTML PARSER                                 │
│   ai/scraper/parsers.py                                       │
│   • BeautifulSoup + lxml                                      │
│   • Extracts: teams, scores, dates, stats                     │
│   • HTML discarded from RAM after parsing                     │
└────────────────────────────┬──────────────────────────────────┘
                             │ Raw match dicts
                             ▼
┌───────────────────────────────────────────────────────────────┐
│                    DATA PROOFREADER                            │
│   ai/proofreader/validator.py                                 │
│   • Range checks (goals 0-15, possession 0-100)              │
│   • Consistency checks (possession sums to ~100)              │
│   • Plausibility checks (>3σ deviation = suspect)             │
│   • Invalid data → quarantine, not discard                    │
└────────────────────────────┬──────────────────────────────────┘
                             │ Validated match data
                             ▼
┌───────────────────────────────────────────────────────────────┐
│                    FEATURE ENGINEERING                         │
│   ai/model/features.py                                        │
│   • 91 features per match (FEATURE_COLUMNS)                   │
│   • Rolling window stats, Elo, Poisson xG, H2H               │
│   • ±0.5% noise injection (Roadmap §6.2 Stage 5)             │
└────────────────────────────┬──────────────────────────────────┘
                             │ 1×91 numpy float32 array
                             ▼
┌───────────────────────────────────────────────────────────────┐
│                    GBDT MODEL (XGBoost)                        │
│   ai/model/inference.py                                       │
│   • Feature Vector Firewall (range validation)                │
│   • Inference < 300ms SLA                                     │
│   • Output: match probabilities, goal metrics, confidence     │
└───────────────────────────────────────────────────────────────┘
```

---

## Data Sources

Configured in `ai/scraper/selectors.json` with 3 source profiles:

| Source | Description | Data Type |
|--------|-------------|-----------|
| **Source-A** | Historical match data and statistics archive | Match results, scores, detailed stats (possession, shots, corners, fouls) |
| **Source-B** | Live scores and league tables | Match cards, results, standings |
| **Source-C** | Official results and fixture data | Fixtures, results, referee information |

Each source has its own CSS selector map for parsing different HTML structures.

---

## Raw Data Format

### From Go Server API (`GET /api/v1/matches`)

```json
{
    "count": 180,
    "matches": [
        {
            "id": "uuid-v4",
            "source_id": "source_001_match_42",
            "league_id": "super_lig",
            "season": "2025-2026",
            "match_week": 30,
            "home_team": "team_001",
            "away_team": "team_002",
            "home_score": 2,
            "away_score": 1,
            "ht_home_score": 1,
            "ht_away_score": 0,
            "match_date": "2026-04-05T19:00:00Z",
            "stats_json": {
                "possession_home": 56,
                "possession_away": 44,
                "shots_on_home": 6,
                "shots_on_away": 4,
                "shots_off_home": 8,
                "shots_off_away": 5,
                "corners_home": 7,
                "corners_away": 5,
                "fouls_home": 14,
                "fouls_away": 16
            },
            "scraped_at": "2026-04-03T07:00:00Z"
        }
    ]
}
```

### From HTML Parsing (`ParsedMatch` dataclass)

```python
@dataclass
class ParsedMatch:
    home_team: str       # "Galatasaray"
    away_team: str       # "Fenerbahçe"
    home_score: int      # 2
    away_score: int      # 1
    ht_home_score: int   # 1 (half-time)
    ht_away_score: int   # 0
    match_date: str      # "2026-04-05"
    stats: dict          # {"possession": 56, "shots_on": 6, ...}
```

### Historical Data File (`data/tr_super_lig_2024_25.json`)

```json
{
    "matches": [
        {
            "date": "2024-08-09",
            "round": "Matchday 1",
            "team1": "Galatasaray",
            "team2": "Hatayspor",
            "score": {
                "ft": [1, 0],
                "ht": [0, 0]
            }
        }
    ]
}
```

---

## Scraping Engine

**File**: `ai/scraper/engine.py`

The `ScrapingEngine` class coordinates data fetching with two strategies:

### Strategy 1: Go Middleware (Preferred)
```
ScrapingEngine → GET server:8080/api/v1/matches → JSON response
```
- Data is already cached in PostgreSQL by the Go server
- No rate limiting needed (internal API)
- Returns structured JSON with team UUIDs

### Strategy 2: Direct HTML Scraping (Fallback)
```
ScrapingEngine → HTTP GET (rate-limited, 5s/domain) → HTML → BeautifulSoup → ParsedMatch
```
- Used when Go server is unavailable
- Respects `_respect_rate_limit()` — max 1 request per 5 seconds per domain
- User-Agent: `Negelir/0.1 (Football Analysis Research)`

### Key Methods

| Method | Purpose |
|--------|---------|
| `fetch_matches_from_server()` | Get cached matches from Go server |
| `fetch_teams_from_server()` | Get team data from Go server |
| `trigger_server_scrape()` | Tell Go server to refresh its scraped data |
| `check_server_health()` | Verify Go server is reachable |
| `_respect_rate_limit(domain)` | Enforce 5s cooldown per domain |

---

## CSS Selectors Configuration

**File**: `ai/scraper/selectors.json`

Each source defines selectors for extracting structured data from HTML:

```json
{
    "match_row": "div.match-row, tr.match-item, .mac-satiri",
    "home_team": ".home-team .name, .ev-sahibi, td:nth-child(2)",
    "away_team": ".away-team .name, .deplasman, td:nth-child(4)",
    "score": ".score-cell, .skor, td:nth-child(3)",
    "date": ".match-date, .tarih, td:nth-child(1)",
    "possession": ".possession, .topa-sahip-olma",
    "shots_on": ".shots-on-target, .isabetli-sut",
    "corners": ".corners, .korner",
    "fouls": ".fouls, .faul"
}
```

Selectors use comma-separated fallbacks to handle different site structures. Turkish CSS class names (e.g., `.ev-sahibi`, `.isabetli-sut`) are included for Turkish football sites.

---

## Data Parsing

**File**: `ai/scraper/parsers.py`

### Parse Flow

1. HTML string → `BeautifulSoup(html, "lxml")`
2. Select all match rows using `match_row` selector
3. For each row, extract:
   - Home/away team names
   - Score (regex: `(\d+)\s*[-:]\s*(\d+)`)
   - Match date
   - Per-stat values (possession, shots, corners, fouls)
4. Return list of `ParsedMatch` objects
5. **BeautifulSoup and raw HTML go out of scope → garbage collected**

### Stats Extracted Per Match

| Stat | Description | Range |
|------|-------------|-------|
| `possession` | Ball possession % | 0-100 |
| `shots_on` | Shots on target | 0-40 |
| `shots_off` | Shots off target | 0-40 |
| `corners` | Corner kicks | 0-25 |
| `fouls` | Fouls committed | 0-40 |

---

## Data Proofreading & Validation

**File**: `ai/proofreader/validator.py`

Every match record passes through 3 validation layers before reaching the AI model:

### 1. Range Checks
| Field | Valid Range |
|-------|------------|
| `home_score`, `away_score` | 0 - 15 |
| `possession` | 0 - 100 |
| `shots_on`, `shots_off` | 0 - 40 |
| `corners` | 0 - 25 |
| `fouls` | 0 - 40 |
| `yellow_cards` | 0 - 10 |
| `red_cards` | 0 - 5 |

### 2. Consistency Checks
- Home + Away possession ≈ 100 (±5 tolerance)
- Half-time score ≤ Full-time score (per team)

### 3. Plausibility Checks
- Total goals ≥ 10 → warning (statistically rare)
- Single team scoring 8+ → error (implausible)
- >3σ deviation from historical averages → quarantine

### Quarantine Logic
- Failed records are quarantined, not discarded
- Batch validation fails if >30% of records are quarantined
- Quarantined records stored in `data_quarantine` DB table with reason

---

## Feature Engineering — From Raw Data to AI Input

**File**: `ai/model/features.py`

### Transformation Pipeline

```
Raw Match Data → Rolling Window Calculations → Elo Rating Updates
    → Poisson xG Computation → H2H Statistics → League Position
    → Contextual Features → Sentiment Analysis → 91-Feature Vector
    → ±0.5% Noise Injection → Model Input
```

### Feature Categories (from Roadmap §5.2)

| Category | Count | Source |
|----------|-------|--------|
| **A. Team Form (Rolling Windows)** | 24 | Last 3, 5, 10 match averages for scored/conceded/PPG/win ratio |
| **B. Elo & Derived** | 9 | Custom Elo ratings, Poisson xG, form indices |
| **C. Head-to-Head** | 6 | H2H win %, draw %, avg goals, over 2.5 %, BTS % |
| **D. League Position** | 8 | Normalized positions, goal diff, gap to leader/relegation |
| **E. Squad & Tactical** | 8 | Formation stability, rotation Gini, goal concentration, avg age |
| **F. Contextual** | 7 | Fixture congestion, manager tenure/change, derby flag, season phase |
| **G. Temporal** | 7 | Day/month sine/cosine encoding, rest days, rest diff |
| **H. Sentiment** | 5 | Media sentiment, fan optimism, consensus strength |
| **I. Derived** | 8 | Style matchup, fatigue diff, momentum, scoring consistency, surprise index |
| **J. Weather/Venue** | 4 | Temperature bucket, precipitation flag, wind, venue type |
| **Total** | **91** | |

---

## Feature Vector Schema (91 Dimensions)

```
Index  Feature Name                    Type     Range        Description
─────  ──────────────────────────────  ───────  ───────────  ─────────────────────────────────
0-2    home_avg_scored_3/5/10          float    [0, 10]      Rolling avg goals scored (home)
3-5    home_avg_conceded_3/5/10        float    [0, 10]      Rolling avg goals conceded (home)
6      home_ppg_5                      float    [0, 3]       Points per game (last 5)
7      home_ppg_10                     float    [0, 3]       Points per game (last 10)
8      home_clean_sheet_10             float    [0, 1]       Clean sheet rate (last 10)
9-11   home_win/draw/loss_ratio_5      float    [0, 1]       Result ratios (last 5)
12-23  away_avg_scored/conceded/ppg... float    (same)       Mirror of home features for away team
24-26  home_elo, away_elo, elo_diff    float    [-500, 3500] Custom Elo ratings
27-29  home_xg, away_xg, xg_diff      float    [0, 5]       Poisson expected goals
30-32  home/away_form_index, form_diff float    [0, 1]       Normalized form index
33-38  h2h_home_win_pct → h2h_count   float    [0, 1/10]    Head-to-head statistics
39-41  home/away_league_pos_norm, diff float    [0, 1]       Normalized league position
42-43  home/away_goal_diff             float    [-50, 50]    Season goal difference
44-47  home/away_pts_gap_leader/releg  float    [0, 100]     Gap to leader/relegation zone
48-55  formation_stability → avg_age   float    varies       Squad & tactical metrics
56-57  home/away_fixture_congestion_7  int      [0, 5]       Matches in last 7 days
58-59  home/away_fixture_congestion_14 int      [0, 8]       Matches in last 14 days
60-61  home/away_manager_tenure        int      [1, 10]      Manager matches
62-63  home/away_manager_change        binary   {0, 1}       Recent manager change
64     derby_flag                      binary   {0, 1}       Istanbul derby matches
65     season_phase                    int      {0,1,2,3}    Start/Mid/End/Playoff
66     match_week_norm                 float    [0, 1]       Normalized week (round/38)
67-70  day_sin/cos, month_sin/cos      float    [-1, 1]      Cyclical time encoding
71-73  home/away_rest_days, rest_diff  int      [1, 21]      Days since last match
74-78  media_sentiment → consensus_str float    [-1, 1]      NLP sentiment features
79-80  style_matchup_index, fatigue    float    [0, 1]       Tactical derived features
81-82  home/away_momentum              float    [-1, 1]      Form acceleration (2nd derivative)
83-84  home/away_scoring_consistency   float    [0, 1]       1 - std(goals)
85-86  surprise_index_home/away        float    [0, 2]       PPG volatility
87     temperature_bucket              int      {0,1,2}      Winter/Mild/Hot
88     precipitation_flag              binary   {0, 1}       Rain/snow
89     wind_category                   int      {0,1,2}      Calm/Moderate/Strong
90     venue_type                      int      {0,1}        Home=0, Away=1
```

### Noise Injection (Roadmap §6.2, Stage 5)
```python
# ±0.5% uniform noise applied to all features to prevent back-calculation
noise = rng.uniform(1 - 0.005, 1 + 0.005, size=features.shape)
noised_features = features * noise
```

---

## How Data Feeds the AI Model

### Step-by-Step Flow

1. **Scraping**: Go server fetches HTML → parses → stores in PostgreSQL
2. **Fetch**: AI module calls `GET /api/v1/matches` → receives JSON array
3. **Validate**: `DataProofreader.validate_batch()` checks ranges, consistency, plausibility
4. **Feature Extract**: `extract_features_for_match()` maps match dict → 1×91 numpy array
5. **Firewall**: `GBDTInference.validate_features()` checks ranges per feature type
6. **Inference**: `model.predict_proba(features)` → [P(home_win), P(not_home_win)]
7. **Post-process**: Normalize to 3-class distribution [home, draw, away]
8. **Goal Metrics**: Compute over/under, BTS from Poisson xG model
9. **Response**: TRC templates compose Turkish natural-language answer

### Model Architecture

- **Algorithm**: XGBoost GBDT (Gradient Boosted Decision Trees)
- **Objective**: Binary classification (PoC) / 3-class softprob (historical test)
- **Features**: 91 per match
- **Training Data**: Synthetic (PoC) / Turkish Super Lig 2024-25 (historical)
- **Ensemble**: 55% XGBoost + 45% Poisson model (historical test mode)
- **Inference SLA**: < 300ms per prediction
- **Confidence**: Entropy-based (1 - normalized entropy of output distribution)

### Feature Vector Firewall (Roadmap §5.6.2)

Before inference, every feature is validated against type-specific ranges:

| Feature Type | Valid Range |
|-------------|------------|
| `elo` | -500 to 3500 |
| `ratio`, `norm` | 0 to 1 |
| `pct` | 0 to 100 |
| `sentiment`, `optimism` | -1 to 1 |
| `sin`, `cos` | -1 to 1 |
| `flag` | 0 to 1 |
| `age` | 15 to 45 |
| `scored`, `conceded` | 0 to 10 |

Out-of-range values are **clamped** (not rejected) to maintain robustness.

---

## Database Schema

**File**: `migrations/001_initial.sql`

### Core Tables

| Table | Purpose | Key Columns |
|-------|---------|------------|
| `teams` | Team registry | `id` (UUID), `display_name`, `league_id`, `internal_code` |
| `raw_matches` | Scraped match data | `source_id`, `home_team`, `away_team`, `home_score`, `away_score`, `ht_home_score`, `ht_away_score`, `stats_json`, `scraped_at` |
| `team_features` | Computed feature vectors | `team_id`, `season`, `match_week`, `features_json` |
| `analyses` | AI predictions | `match_id`, `distribution_json`, `confidence`, `model_version` |
| `outcome_validations` | Post-match validation | `analysis_id`, `actual_result`, `was_correct` |
| `peer_reputation` | P2P node scores | `node_id`, `accuracy`, `predictions`, `trust_level` |
| `scrape_tasks` | Scraping job tracker | `task_id`, `status`, `source`, `started_at` |
| `data_quarantine` | Failed validation | `match_id`, `reason`, `raw_data_json` |

---

## Go Middleware Server

**File**: `server/cmd/main.go`

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/health` | Health check (DB + Redis) |
| `GET` | `/api/v1/matches` | List cached matches |
| `GET` | `/api/v1/teams` | List teams |
| `POST` | `/api/v1/scrape/trigger` | Trigger scraping pipeline |

### Server Stack
- **Framework**: Gin (Go)
- **Database**: PostgreSQL 16 via pgxpool
- **Cache**: Redis 7 via go-redis
- **Port**: 8080

---

## Security & Compliance

### Data Privacy (Roadmap §6.2)
- Team names → internal UUIDs (no source-identifying data in transit)
- Raw HTML never persisted to disk
- ±0.5% noise injection prevents back-calculation of exact stats
- No PII collected or stored

### Input Sanitization (Roadmap §5.6.2)
- Injection pattern detection (LLM prompt markers, HTML, JS)
- URL stripping
- Turkish character normalization
- 200-character input limit
- Disallowed character removal

### Compliance (Roadmap §3.1)
- Banned words filter: `bahis`, `iddaa`, `kupon`, `odds`, `oran`, `bet`, `tip`, `gambling`, etc.
- No gambling-related terminology in any user-facing output
- Output length capped at 500 characters

---

## Data Flow Diagram

```
                    ┌──────────────┐
                    │  Turkish     │
                    │  Football    │
                    │  Websites    │
                    └──────┬───────┘
                           │ HTML (rate-limited, 5s/domain)
                           ▼
              ┌────────────────────────┐
              │  Go Middleware Server   │
              │  • Parse HTML          │
              │  • Store in PostgreSQL  │
              │  • Cache in Redis      │
              └────────────┬───────────┘
                           │ REST API (JSON)
                           ▼
              ┌────────────────────────┐
              │  AI Scraping Engine    │
              │  • fetch_matches()     │
              │  • fetch_teams()       │
              └────────────┬───────────┘
                           │ list[dict]
                           ▼
              ┌────────────────────────┐
              │  Data Proofreader      │
              │  • Range checks        │──── Quarantined data
              │  • Consistency checks  │     (data_quarantine table)
              │  • Plausibility checks │
              └────────────┬───────────┘
                           │ Validated data
                           ▼
              ┌────────────────────────┐
              │  Feature Engineering   │
              │  • 91 features         │
              │  • Rolling windows     │
              │  • Elo + Poisson xG    │
              │  • ±0.5% noise         │
              └────────────┬───────────┘
                           │ 1×91 numpy array
                           ▼
              ┌────────────────────────┐
              │  Feature Firewall      │
              │  • Type-specific       │
              │    range validation    │
              │  • NaN/Inf detection   │
              │  • Auto-clamp          │
              └────────────┬───────────┘
                           │ Validated features
                           ▼
              ┌────────────────────────┐
              │  GBDT Model (XGBoost)  │
              │  • predict_proba()     │
              │  • < 300ms SLA         │
              └────────────┬───────────┘
                           │ Analysis JSON
                           ▼
              ┌────────────────────────┐
              │  TRC Response Composer │
              │  • Verdict selection   │
              │  • Template filling    │
              │  • Compliance check    │
              │  • 500-char limit      │
              └────────────────────────┘
                           │
                           ▼
                   Turkish Response
```
