# Negelir — Architecture Documentation

## Overview

Negelir is an AI-powered system that analyzes football matches and produces pattern-based insights.
It supports multiple leagues through a pluggable `LeagueConfig` system.
The system consists of four main layers:

```
┌──────────────────────────────────────────────────────┐
│                    Flutter (future)                   │
├──────────────────────────────────────────────────────┤
│          Go Middleware Server  [dev-env only]         │
│        REST API • PostgreSQL • Redis                  │
├──────────────────────────────────────────────────────┤
│                   AI Engine (Python)                  │
│  TQU │ TRC │ GBDT Model │ Scraper │ NLP │ Pipeline   │
├──────────────────────────────────────────────────────┤
│               P2P Network (Python)                    │
│     Node │ Protocol │ Reputation │ Simulation         │
└──────────────────────────────────────────────────────┘
```

> **Note:** The Go server, PostgreSQL, and Redis are **local development tools only**.
> They exist for inspecting scraped data, checking AI feature payloads, and ad-hoc
> analysis during development. They are **not** part of the production architecture
> and will not be shipped as required production components.

## Component Details

### 1. AI Engine (`ai/`)

| Module | File | Description |
|--------|------|-------------|
| **TQU** | `tqu/classifier.py` | Classifies Turkish questions (9 intent types) |
| **TQU** | `tqu/sanitizer.py` | Input sanitization, injection prevention |
| **TQU** | `tqu/patterns.py` | Regex intent patterns |
| **TQU** | `tqu/entities.py` | Team name and entity extraction |
| **TRC** | `trc/composer.py` | Turkish response composition |
| **TRC** | `trc/templates.py` | Response templates (7 verdict types) |
| **TRC** | `trc/verdict.py` | Confidence × probability → verdict selection |
| **Model** | `model/trainer.py` | XGBoost GBDT training (GPU/CPU) |
| **Model** | `model/inference.py` | Inference and analysis |
| **Model** | `model/features.py` | 120 feature columns, synthetic data |
| **Model** | `model/device.py` | GPU/CPU auto-detection |
| **Common** | `common/league_config.py` | Multi-league config (TR, EN, DE, ES) |
| **Scraper** | `scraper/engine.py` | Data fetching via Go server |
| **Scraper** | `scraper/parsers.py` | HTML parsing (BeautifulSoup) |
| **NLP** | `nlp/sentiment.py` | Turkish sentiment analysis |
| **Orchestrator** | `orchestrator/state_machine.py` | State machine |
| **Proofreader** | `proofreader/validator.py` | Data validation and quarantine |
| **Pipeline** | `pipeline/runner.py` | End-to-end pipeline, demo mode |

### 2. Go Server (`server/`) — Local Development Only

> ⚠️ **Development environment only.** Not required in production.
> The AI engine scrapes data directly from its configured sources and operates
> fully standalone. The Go server and its backing stores (PostgreSQL, Redis)
> exist purely as a local inspection and caching layer.

- **Gin** HTTP framework
- PostgreSQL (`pgx/v5`) connection pool — stores raw scraped matches locally
- Redis caching layer — caches feature payloads for quick re-queries
- API Endpoints (development/inspection use only):
  - `GET /api/v1/health` — System health check
  - `GET /api/v1/matches` — Match list (returns data only if DB has been populated)
  - `GET /api/v1/matches/:id` — Match details
  - `GET /api/v1/teams` — Team list
  - `GET /api/v1/teams/:id` — Team details
  - `POST /api/v1/scrape/trigger` — Trigger scrape task
  - `GET /api/v1/features/:match_id` — Feature data

### 3. P2P Network (`p2p/`)

- **Node**: Each node has its own AI model, reputation table, and identity
- **Protocol**: JSON message format, content hash verification
- **Transport**: In-memory message routing for simulation (asyncio queues)
- **Reputation**: Outcome-validated reputation system (§5.3.3)
- **Simulation**: Multi-node simulation, 10-match rounds, reputation matrix

### 4. Database Schema

```
teams                → Team records (24 Super Lig + 1. Lig)
raw_matches          → Raw match data
team_features        → 91-dimensional feature vectors
analyses             → GBDT prediction results
outcome_validations  → Prediction validation records
peer_reputation      → P2P reputation table
scrape_tasks         → Data fetching tasks
data_quarantine      → Suspicious data quarantine
```

## Data Flow

```
# Production flow (AI engine only)
1. Scraper  → Live sources (mackolik.com → nesine → tff.org → openfootball → fallback)
2. Features → 130+ column generation from real match data
3. GBDT     → XGBoost + Dixon-Coles Poisson ensemble (GPU or CPU)
4. TQU      → Turkish question understanding + intent classification
5. TRC      → Template-based Turkish response composition
6. Proofreader → Data validation + quarantine
7. P2P      → Analysis sharing + reputation-weighted ensemble

# Local development only (optional)
8. Scraper  → Go Server → PostgreSQL (raw data inspection cache)
9. Redis    → Feature payload caching
```

## Prediction Model

- **XGBoost (GBDT)**: 3-class multi:softprob (Home/Draw/Away)
- **Poisson**: Dixon-Coles corrected for low-scoring matches (ρ = -0.13)
- **Ensemble**: 35% XGBoost + 65% Poisson (configurable per league)
- **Draw detection**: Multi-signal scoring (H-A gap, Bayesian, Poisson, Elo)
- **Features**: 120 columns across 6 categories (A-F)
- **Accuracy (Turkish Süper Lig)**: 41.2% 1X2, 68.1% DC1X, 78.8% AH-1.5

## Multi-League Support

League-specific parameters are extracted into `common/league_config.py`:
- Elo home advantage, first-half goal percentage, Dixon-Coles ρ
- Derby pairs, team counts, promotion/relegation slots
- XGBoost ensemble weight, draw detection thresholds
- Pre-built configs: Turkish Süper Lig, EPL, Bundesliga, La Liga

## Security

- SQL injection protection (parameterized queries)
- Input sanitization (XSS, injection pattern detection)
- Banned word filter (gambling/betting terminology)
- Input length limit (200 characters)
- Data quarantine mechanism
- P2P message hash verification
