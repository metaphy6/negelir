# ⚽ Negelir — Turkish Football Match Analysis & Prediction

> **Ne gelir?** *(Turkish: "What will come?")*
> A decentralized AI system that scrapes Turkish football data, analyzes matches with gradient-boosted decision trees, and answers questions in natural Turkish.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    🌐 Go Middleware Server                  │
│          REST API · Scrape Orchestration · Caching          │
├─────────────────────────────────────────────────────────────┤
│           ┌──────────────┐    ┌──────────────┐              │
│           │ 🐘 PostgreSQL│    │  🔴 Redis    │              │
│           │   Storage    │    │   Cache      │              │
│           └──────────────┘    └──────────────┘              │
├───────────────────────┬─────────────────────────────────────┤
│  🤖 AI Engine         │  📡 P2P Network                     │
│  Scraper → Proofreader│  5+ Nodes · Reputation Tracking     │
│  → Features → GBDT    │  Ensemble Predictions               │
│  → TQU → TRC          │  Turkish Q&A                        │
└───────────────────────┴─────────────────────────────────────┘
```

---

## 📦 Components

### 🤖 AI Engine (`ai/`)
The brain of Negelir. Processes Turkish football data through a multi-stage pipeline.

| Module | Purpose |
|--------|---------|
| 🕷️ `scraper/` | Web scraping engine with CSS selectors for 3 data sources |
| ✅ `proofreader/` | Data validation — range checks, completeness, anomaly detection |
| 📊 `model/` | XGBoost GBDT model with 91-feature engineering, Poisson xG ensemble |
| 🗣️ `tqu/` | **Turkish Question Understanding** — intent classification (9 intents), entity extraction, 1600+ question patterns |
| 🇹🇷 `trc/` | **Turkish Response Composer** — verdict selection, template-based Turkish answers |
| 💬 `nlp/` | Rule-based Turkish football sentiment analysis |
| 🔄 `orchestrator/` | State machine managing pipeline steps |
| 🧪 `tests/` | 58 unit tests covering sanitizer, classifier, Poisson, betting markets, cards, score prediction |

**9 Intent Types:**
`match_winner` · `draw` · `over_under` · `goal_range` · `both_teams_score` · `clean_sheet` · `half_time` · `form_query` · `head_to_head`

### 📡 P2P Network (`p2p/`)
Decentralized prediction network where multiple AI nodes collaborate.

| Module | Purpose |
|--------|---------|
| 🖥️ `node/` | `PeerNode` — local GBDT inference, prediction broadcasting |
| 📨 `protocol/` | Message types, simulated transport layer |
| ⭐ `reputation/` | Peer accuracy tracking, Sybil-resistant reputation matrix |
| 🏃 `simulation/` | Full network simulation with 5 nodes, 21 Turkish Q&A questions |

**Simulation Phases:** Network Setup → Web Scraping → Data Validation → P2P Analysis → Turkish Q&A → Reputation Matrix

### 🌐 Go Server (`server/`)
REST middleware built with Gin.

| Endpoint | Function |
|----------|----------|
| `GET /api/v1/health` | 💚 Health check |
| `POST /api/v1/scrape/trigger` | 🕷️ Trigger scraping pipeline |
| `GET /api/v1/matches` | ⚽ List cached matches |
| `GET /api/v1/teams` | 🏟️ Team registry |

### 🗄️ Database (`migrations/`)
PostgreSQL schema with 8 tables:
`teams` · `raw_matches` · `team_features` · `analyses` · `outcome_validations` · `peer_reputation` · `scrape_tasks` · `data_quarantine`

### 📁 Data (`data/`)
Runtime data directory (mounted as Docker volume):
- `models/` — Trained XGBoost `.pkl` model files
- Scraped match data (JSON)
- Historical Turkish Süper Lig fixtures

---

## 🚀 Quick Start

### Prerequisites
- 🐳 Docker & Docker Compose
- 🐧 Linux / macOS / WSL2

### 1️⃣ Start Everything
```bash
make up              # Build & start all services (foreground)
make up-detached     # Or run in background
```

### 2️⃣ Run AI Demo
```bash
make ai-demo         # Run 22 Turkish Q&A questions
make ai              # Run full pipeline (scrape → analyze → respond)
```

### 3️⃣ Run P2P Simulation
```bash
make p2p             # Single P2P simulation run
make p2p-simulate    # Same, via docker compose run
```

### 4️⃣ Continuous Mode 🔄
```bash
make ai-continuous        # AI pipeline loops every 30s (Ctrl+C to stop)
make ai-continuous-demo   # Demo questions loop every 30s
make p2p-continuous       # P2P simulation loops every 30s

# Custom interval:
SIMULATION_INTERVAL=60 make ai-continuous
```

### 5️⃣ Run Tests
```bash
make test            # All tests (AI + P2P)
make test-ai         # AI only (58 tests)
make test-p2p        # P2P only (24 tests)
```

---

## 🛠️ All Makefile Commands

| Command | Description |
|---------|-------------|
| **🏗️ Build & Run** | |
| `make build` | Build all Docker images |
| `make up` | Start all services (foreground) |
| `make up-detached` | Start all services (background) |
| `make down` | Stop & remove containers |
| `make restart` | Restart all services |
| `make status` | Show running containers |
| `make ports` | Show exposed ports |
| **🤖 AI** | |
| `make ai` | Run AI pipeline |
| `make ai-demo` | Run Turkish Q&A demo |
| `make ai-pipeline` | Full pipeline (scrape → respond) |
| `make ai-train` | Train GBDT model |
| `make ai-tqu-test` | Test TQU classifier |
| `make ai-continuous` | 🔄 Continuous AI pipeline |
| `make ai-continuous-demo` | 🔄 Continuous AI demo |
| `make ai-shell` | Shell into AI container |
| **📡 P2P** | |
| `make p2p` | Run P2P simulation |
| `make p2p-simulate` | Run P2P simulation (run --rm) |
| `make p2p-continuous` | 🔄 Continuous P2P simulation |
| `make p2p-shell` | Shell into P2P container |
| **🌐 Server** | |
| `make server` | Start Go server + deps |
| `make server-health` | Health check |
| `make server-scrape` | Trigger scraper |
| `make server-matches` | List cached matches |
| **🗄️ Database** | |
| `make infra` | Start PostgreSQL + Redis only |
| `make db-shell` | Open PostgreSQL CLI |
| `make db-reset` | ⚠️ Reset database |
| `make redis-shell` | Open Redis CLI |
| **📋 Logs** | |
| `make logs` | Tail all logs |
| `make logs-ai` | Tail AI logs |
| `make logs-p2p` | Tail P2P logs |
| `make logs-server` | Tail server logs |
| **🧪 Testing** | |
| `make test` | Run all tests |
| `make test-ai` | Run AI tests (58) |
| `make test-p2p` | Run P2P tests (24) |
| **🧹 Cleanup** | |
| `make clean` | Remove containers + images |
| `make clean-all` | ⚠️ Remove everything + volumes |
| `make clean-data` | Remove data files |

---

## 📊 Understanding the Logs

### 🤖 AI Pipeline Logs
```
⚽ Negelir AI Engine starting...          # Engine boot
🌐 Checking Go server health...           # Server connectivity
📄 Page 3/8: 45.2 KB → 4 matches parsed   # Web scraping progress
🗑️  All HTML discarded from memory         # RAM-only processing
📦 Model loaded: negelir_gbdt_v0.1.0.pkl  # GBDT model ready
📝 Duygu: +1.000 ← 'Galatasaray...'       # NLP sentiment score
🗣️  TQU input: 'Galatasaray kazanır mı?'  # Question received
🎯 Intent: match_winner (confidence: 0.70) # Classification result
⛔ Football context not detected           # Non-football rejected
🤖 Response: Büyük ihtimalle evet...       # Turkish AI response
✅ Demo complete! (1.5s, 22 questions)     # Pipeline finished
🔄 Cycle 2                                 # Continuous mode cycle
💤 Sleeping 30s before next cycle...       # Interval pause
```

### 📡 P2P Simulation Logs
```
🌐 NEGELIR P2P NETWORK SIMULATION         # Simulation start
📡 Creating 5 nodes...                     # Network setup
🕷️  Phase B: Simulated Web Scraping        # Data collection
✅ Data Quality: 3/3 valid                 # Validation pass
⚽ Analyzing match: GS vs FB              # AI inference per node
🗣️ Phase E: Turkish Q&A Pipeline          # Q&A through P2P
❓ Q1: "Galatasaray bu maçı kazanır mı?"   # Question routed
🧠 TQU → intent=match_winner              # Classification
🤖 TRC response composed (180 chars)       # Answer generated
📊 Final Reputation Matrix                 # Node accuracy report
⭐ Leader: 1  🟢 High: 3  🟡 Medium: 1     # Reputation summary
```

### 🌐 Go Server Logs
```
🟢 Server starting on :8080               # Server boot
📥 POST /api/v1/scrape/trigger             # Scrape request
📤 GET /api/v1/matches                     # Data request
💚 GET /api/v1/health                      # Health check
```

### 🔑 Key Log Symbols
| Symbol | Meaning |
|--------|---------|
| ⚽ | Match/football operation |
| 🎯 | Successful classification |
| ⛔ | Rejected (non-football or injection) |
| 🤖 | AI response output |
| 📊 | Statistics/metrics |
| ✅ | Success/complete |
| ⚠️ | Warning |
| ❌ | Error/failure |
| 🔄 | Continuous mode cycle |
| 💤 | Sleep between cycles |

---

## 🏛️ Data Pipeline Flow

```
   🌐 Turkish Football Sites
          │
          ▼
   🕷️ Scraper (CSS selectors, rate-limited)
          │
          ▼
   ✅ Proofreader (validation, anomaly detection)
          │
          ▼
   📊 Feature Engineering (91 dimensions)
          │
          ▼
   🧠 GBDT Model (XGBoost, Poisson xG ensemble)
          │
          ▼
   🗣️ TQU (intent + entity extraction)
          │
          ▼
   🇹🇷 TRC (Turkish response composition)
          │
          ▼
   💬 Natural Turkish Answer
```

---

## 🧠 AI Model Details

- **Algorithm:** XGBoost Gradient Boosted Decision Trees
- **Features:** 91 dimensions (Elo, form, xG, H2H, sentiment, venue, seasonal)
- **Ensemble:** 55% XGBoost + 45% Poisson xG model
- **Scoreline:** Poisson distribution for exact score prediction
- **Markets:** Over/Under (1.5, 2.5, 3.5), BTTS, Double Chance, DNB, Asian Handicap, Half-Time
- **Cards:** Foul-based yellow card estimation with derby multiplier

---

## 🛡️ Security & Compliance

- 🚫 **Injection Protection** — TQU sanitizer strips prompt injection attempts
- 🚫 **Banned Words** — Gambling terms (`bahis`, `iddaa`, `kupon`, etc.) never appear in output
- 🔒 **No Source Identification** — Team names mapped to internal UUIDs, no scraping source metadata exposed
- 🗑️ **RAM-Only Processing** — Raw HTML discarded immediately after parsing
- ✅ **Input Validation** — Length limits, URL stripping, HTML sanitization

---

## 📁 Project Structure

```
negelir/
├── 📄 README.md              ← You are here
├── 📄 docker-compose.yml     ← Service orchestration
├── 📄 Makefile               ← 39 commands
├── 📄 LICENSE
├── 🤖 ai/                    ← AI Engine (Python 3.11)
│   ├── main.py
│   ├── common/               ← Config, constants, logging
│   ├── scraper/              ← Web scraping + CSS selectors
│   ├── proofreader/          ← Data validation
│   ├── model/                ← XGBoost GBDT + features
│   ├── tqu/                  ← Turkish Question Understanding
│   ├── trc/                  ← Turkish Response Composer
│   ├── nlp/                  ← Sentiment analysis
│   ├── orchestrator/         ← Pipeline state machine
│   ├── pipeline/             ← End-to-end runner
│   └── tests/                ← 58 unit tests
├── 📡 p2p/                    ← P2P Network (Python 3.11)
│   ├── main.py
│   ├── node/                 ← PeerNode logic
│   ├── protocol/             ← Message types & transport
│   ├── reputation/           ← Accuracy tracking
│   ├── simulation/           ← Network simulator
│   └── tests/                ← 24 unit tests
├── 🌐 server/                 ← Go Middleware (Gin)
│   ├── cmd/main.go
│   └── Dockerfile
├── 🗄️ migrations/             ← PostgreSQL schema
│   └── 001_initial.sql
├── 📁 data/                   ← Runtime data (Docker volume)
│   └── models/               ← Trained model files
└── 📚 docs/                   ← Documentation
    ├── architecture.md
    ├── feasibility.md
    ├── roadmap.md
    ├── scraping.md
    └── setup.md
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_DB` | `negelir` | Database name |
| `POSTGRES_USER` | `negelir` | Database user |
| `POSTGRES_PASSWORD` | _(required, no default)_ | Database password — must be set in `.env` |
| `SERVER_PORT` | `8080` | Go server port |
| `P2P_NODE_COUNT` | `5` | Number of P2P nodes |
| `P2P_SIMULATION_MATCHES` | `10` | Matches per simulation |
| `SIMULATION_INTERVAL` | `30` | Seconds between continuous cycles |
| `AI_LOG_LEVEL` | `DEBUG` | AI logging verbosity |
| `AI_DEVICE` | `auto` | Compute device (cpu/cuda/auto) |

---

## 📜 License

See [LICENSE](LICENSE) for details.
