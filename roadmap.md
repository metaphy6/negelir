# Negelir — Technical Roadmap

> Turkish Football Match Analysis & Prediction App (Flutter + On-Device AI + P2P Network)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Scope & Target Leagues](#2-scope--target-leagues)
3. [Store Compliance Strategy](#3-store-compliance-strategy)
4. [Data Source Architecture](#4-data-source-architecture)
5. [On-Device AI Engine](#5-on-device-ai-engine)
6. [Data Transformation & Copyright Protection](#6-data-transformation--copyright-protection)
7. [P2P Network Layer](#7-p2p-network-layer)
8. [Flutter App Architecture](#8-flutter-app-architecture)
9. [Development Phases](#9-development-phases)
10. [Tech Stack Summary](#10-tech-stack-summary)
11. [Risk Matrix & Mitigations](#11-risk-matrix--mitigations)
12. [Acceptance Criteria per Phase](#12-acceptance-criteria-per-phase)

---

## 1. Project Overview

**Negelir** is a fully on-device, decentralized Flutter application that provides AI-powered statistical analysis and pattern-based insights for Turkish professional football leagues. The app collects publicly available match data, transforms and abstracts it through a proprietary statistical pipeline, and delivers pattern-based analysis to users. All computation happens on-device with no central server. Completed analyses are shared across a P2P network to eliminate redundant processing.

### Core Principles

- **No Betting Promotion**: The app never links to, promotes, or facilitates any gambling or betting activity.
- **No Central Server**: Zero backend infrastructure; the app is self-contained with P2P caching.
- **On-Device AI**: All inference happens locally; no user data leaves the device.
- **Data Provenance Obfuscation**: Source data is transformed into derived statistical features — original data is never stored or displayed.
- **Platform Compliance First**: Every feature is designed around Google Play & Apple App Store guidelines.

---

## 2. Scope & Target Leagues

### Included Leagues

| League | Turkish Name | Tier |
|---|---|---|
| Süper Lig | Trendyol Süper Lig | 1st Division |
| 1. Lig (TFF First League) | Trendyol 1. Lig | 2nd Division |

These are the two top-tier Turkish football leagues where legally regulated betting (İddaa) is offered by the state monopoly.

### Excluded from Scope

- 2. Lig, 3. Lig, regional/amateur leagues
- All non-Turkish leagues (no international matches)
- All cup competitions (Türkiye Kupası, Süper Kupa) — **Phase 1 exclusion, may be revisited**
- Historical data older than 5 seasons (data quality concern)

### Data Points to Capture (Per Match)

- Match date, home/away teams, final score, half-time score
- Goals per half, goal scorers (positions, minute-ranges only — no names stored directly)
- Cards (yellow/red counts, not individual player attributions)
- Corner kicks, shots on target, possession % (when available)
- League standings at time of match
- Head-to-head record (derived stats only)

---

## 3. Store Compliance Strategy

### 3.1 Google Play Compliance

**Key Policy: "Real-Money Gambling, Games, and Contests" (Policy 9877032)**

Google Play strictly prohibits apps that:
- Facilitate real-money gambling without a gambling license
- Provide "gambling or real money game, lottery, or tournament **support or companion functionality**" (e.g., wagering assistance, payouts, **sports score/odds/performance tracking**, or management of participation funds)
- Display ads for gambling services

**Critical Constraint — Guideline #8 from "Ads for Gambling" section:**
> "App must not provide gambling or real money game, lottery, or tournament support or companion functionality (for example, functionality that assists with wagering, payouts, **sports score/odds/performance tracking**, or management of participation funds)"

#### Compliance Approach

| Prohibited | Our Approach |
|---|---|
| Displaying betting odds | **Never display, reference, or derive from odds data** |
| Score/odds tracking for gambling | Frame as **statistical pattern analysis** for sports enthusiasts |
| Linking to betting sites | **Zero external links** to any betting or gambling site |
| Assisting with wagers | No wager tracking, bet slips, staking calculators, or any money-related features |
| Gambling ads | **No ads at all in MVP**; if ads are added later, gambling ad networks are blacklisted |

#### Positioning Strategy

- **App Category**: Sports (NOT Casino/Gambling)
- **Age Rating**: PEGI 3 / Everyone — absolutely no gambling content
- **App Description Language**: Use ONLY terms like "statistical analysis," "pattern recognition," "match insights," "performance trends," "historical data analysis"
- **NEVER use**: "prediction," "bet," "odds," "wager," "tip," "winner," "guaranteed," "sure," "profit," "earning," "İddaa," "bahis," "kupon"
- **Disclaimer**: Prominently display: *"This app is for informational and entertainment purposes only. It does not promote, facilitate, or encourage gambling or betting of any kind."*

### 3.2 Apple App Store Compliance

**Key Policies:**

- **Guideline 5.3.4**: Real money gaming apps require licenses, geo-restriction, and must be free. Our app is NOT a gambling app — it's a sports analytics tool.
- **Guideline 5.2.2 (Third-Party Sites/Services)**: "If your app uses, accesses, monetizes access to, or displays content from a third-party service, ensure that you are specifically permitted to do so under the service's terms of use." → We must transform data so thoroughly that the output is a derivative analytical work, not a display of third-party content.
- **Guideline 4.2 (Minimum Functionality)**: App must not be a repackaged website; it must provide genuine app-like value.
- **Guideline 2.3.1 (No Hidden Features)**: All functionality must be transparent and disclosed.
- **Guideline 1.4.5**: "Apps should not urge customers to participate in activities (like bets, challenges, etc.)"

#### Apple-Specific Measures

- Include a clear privacy policy (even though no data is collected centrally)
- Disclose AI/ML analysis methodology in app description
- Ensure the app provides standalone value — not just raw data display
- No push notifications that could be construed as "tips" or "picks"
- Turkish-language localization with careful terminology review

### 3.3 Universal Compliance Checklist

- [ ] No gambling terminology anywhere in UI, metadata, or marketing
- [ ] No external links to betting operators
- [ ] No odds display or odds-derived metrics
- [ ] Prominent "entertainment/informational purposes" disclaimer
- [ ] No push notifications with "prediction" style content
- [ ] No user accounts or personal data collection
- [ ] Privacy policy accessible from app and store listing
- [ ] Age-appropriate for all audiences
- [ ] No in-app purchases related to "premium predictions"
- [ ] All analysis framed as historical pattern recognition, not future guarantees

---

## 4. Data Source Architecture

### 4.1 Source Websites

The app scrapes publicly available data from:

1. **mackolik.com / arsiv.mackolik.com** — Historical match data, scores, statistics archive
2. **nesine.com** — Live scores, match programs, league tables (public-facing statistics only — NOT odds or betting features)
3. **iddaa.com** — Match programs and schedules (public fixture data only — NOT odds)

### 4.2 Web Scraping Strategy

#### On-Device Scraping Engine

```
┌─────────────────────────────────────┐
│         Flutter App (Device)        │
│  ┌─────────────────────────────┐    │
│  │    Scraping Scheduler       │    │
│  │  (Isolate-based workers)    │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │   HTML Parser (html pkg)    │    │
│  │   + CSS Selectors           │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  Data Normalizer            │    │
│  │  (Raw → Canonical Schema)   │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  Feature Extractor          │    │
│  │  (Canonical → ML Features)  │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  Local Storage (SQLite)     │    │
│  │  (Features only, no raw)    │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

#### Scraping Policies

- **Rate Limiting**: Maximum 1 request per 5 seconds per domain; exponential backoff on errors
- **User-Agent**: Transparent custom User-Agent identifying the app
- **robots.txt**: Respect robots.txt directives from each domain
- **Data Minimization**: Extract only statistical data points; never download images, branding, or editorial content
- **Caching**: HTTP cache headers respected; avoid re-fetching unchanged pages
- **Scheduling**: Scrape match results the morning after match day (no real-time/live scraping)
- **Fallback**: If a source is unavailable, degrade gracefully (show cached data age)

#### Scraper Selector Maintenance

Website structures change. The scraper uses a **selector configuration file** (JSON) that maps CSS selectors to data fields. This config is versioned and can be updated via the P2P network (signed by the developer's key to prevent tampering).

```json
{
  "version": "1.0.0",
  "sources": {
    "source_a": {
      "base_path": "/league/{league_id}/results",
      "selectors": {
        "match_row": "div.match-row",
        "home_team": ".home-team .name",
        "away_team": ".away-team .name",
        "score": ".score-cell",
        "date": ".match-date"
      }
    }
  }
}
```

### 4.3 Alternative Data Strategy (If Scraping is Blocked)

If source websites implement bot protection (Cloudflare, CAPTCHAs):

1. **Public APIs**: Investigate if mackolik or others expose a public API (some sites have undocumented mobile APIs)
2. **Community Data Contribution**: Allow users to manually correct/input match results they observe — validated against multiple user inputs via P2P consensus
3. **Open Data Sources**: Turkish Football Federation (TFF) publishes some results publicly; Wikipedia Turkish football season articles contain structured tables
4. **RSS/Atom Feeds**: Some sports sites provide feed-based score updates

---

## 5. On-Device AI Engine

### 5.1 Model Architecture

The AI is NOT a large language model or generative AI. It is a **lightweight tabular ML model** optimized for on-device inference.

#### Model Type: Gradient Boosted Decision Trees (GBDT)

- **Training Framework**: XGBoost / LightGBM (trained offline on developer machine)
- **Inference Runtime**: TensorFlow Lite (tflite_flutter package) or ONNX Runtime (onnxruntime_flutter)
- **Model Size Target**: < 5 MB per model file
- **Inference Time Target**: < 200ms per prediction on mid-range devices

#### Why GBDT Over Neural Networks

| Factor | GBDT | Neural Network |
|---|---|---|
| Small tabular datasets | Excellent | Poor (needs large data) |
| Interpretability | High (feature importance) | Low (black box) |
| Model size | Tiny (few MB) | Often large |
| On-device inference speed | Very fast | Depends on architecture |
| Training data required | ~500-2000 matches sufficient | Needs 10k+ |
| Flutter integration | Via TFLite/ONNX export | Same runtime |

### 5.2 Feature Engineering Pipeline

Raw scraped data is transformed into ML features. **No raw data is stored after feature extraction.**

#### Feature Categories

**Team Form Features (rolling windows: 5, 10, 20 matches)**
- Points per game average
- Goals scored per game average
- Goals conceded per game average
- Clean sheet ratio
- Win/draw/loss ratio
- Home vs. away performance differential

**Head-to-Head Features**
- Historical win ratio (home perspective)
- Average goals in H2H matches
- H2H clean sheet frequency
- Last N encounters trend (improving/declining)

**League Position Features**
- Current league position (normalized 0-1)
- Points gap to leader / relegation zone
- Goal difference rank
- Form rank (last 5 matches)

**Temporal Features**
- Day of week (one-hot encoded)
- Month (cyclical encoding: sin/cos)
- Match week number (normalized)
- Days since last match for each team

**Derived Statistical Features**
- Poisson-derived expected goals (xG approximation from shot/goal data)
- Elo rating (custom calculated from results)
- Strength of schedule metric
- Momentum indicator (form acceleration/deceleration)

### 5.3 Model Outputs

The model produces **probabilistic distribution outputs**, NOT deterministic predictions:

```json
{
  "analysis_id": "sha256_hash",
  "match_context": {
    "league": "super_lig",
    "week": 28,
    "teams_hash": "obfuscated_team_pair_id"
  },
  "pattern_analysis": {
    "home_strength_index": 0.72,
    "away_strength_index": 0.58,
    "historical_pattern_similarity": 0.65,
    "form_momentum": {
      "home": "ascending",
      "away": "stable"
    }
  },
  "distribution": {
    "home_advantage_score": 0.62,
    "draw_likelihood_index": 0.22,
    "away_advantage_score": 0.16
  },
  "confidence": 0.71,
  "feature_importance": {
    "recent_form": 0.28,
    "h2h_history": 0.22,
    "home_factor": 0.18,
    "league_position": 0.15,
    "goal_patterns": 0.12,
    "temporal": 0.05
  },
  "analysis_metadata": {
    "model_version": "1.2.0",
    "features_used": 47,
    "data_freshness_hours": 18,
    "timestamp_utc": "2026-03-31T22:00:00Z"
  }
}
```

**Key Design Decisions:**
- Outputs use abstract terms ("advantage_score", "likelihood_index") — never "prediction" or "probability of winning"
- Team identifiers are hashed in P2P-shared data (the local app maps them for display)
- Feature importance is exposed to the user as explainability ("Why this analysis?")
- Confidence score helps users understand reliability (low data = low confidence)

### 5.4 Model Training & Update Pipeline

```
Developer Machine (Offline)
├── 1. Aggregate historical data (5 seasons × 2 leagues)
├── 2. Feature engineering pipeline (Python/Pandas)
├── 3. Train XGBoost/LightGBM model
├── 4. Hyperparameter tuning (Optuna/cross-validation)
├── 5. Export to ONNX or TFLite format
├── 6. Sign model file with developer key
├── 7. Distribute via:
│     ├── App update (bundled in APK/IPA)
│     └── P2P network (signed model broadcast)
└── 8. Users verify signature before loading model
```

**Model Update Frequency**: Monthly during season, major retraining during off-season.

---

## 6. Data Transformation & Copyright Protection

### 6.1 Transformation Pipeline

The goal is to ensure that the data stored and displayed in the app is a **derivative analytical work** that cannot be reverse-engineered to reconstruct the original source data.

```
Raw Scraped Data → [STAGE 1: Normalization] → [STAGE 2: Aggregation] → [STAGE 3: Statistical Derivation] → [STAGE 4: Abstraction] → Stored Features
```

#### Stage 1: Normalization
- Team names mapped to internal UUIDs (e.g., "Galatasaray" → `team_uuid_017`)
- Dates converted to relative offsets (match_week, days_since_season_start)
- Scores converted to goal_difference, total_goals, result_code (H/D/A)

#### Stage 2: Aggregation
- Individual match scores are never stored; only rolling aggregates are kept
- Example: Instead of "Match 1: 2-1, Match 2: 0-0, Match 3: 3-2" → store "avg_goals_scored_last_3: 1.67, avg_goals_conceded_last_3: 1.0"

#### Stage 3: Statistical Derivation
- Raw stats → Poisson parameters, Elo ratings, Bayesian posterior estimates
- No single source data point is recoverable from derived statistics

#### Stage 4: Abstraction
- Numerical values are discretized into categories where possible (e.g., form = "strong" / "moderate" / "weak")
- Percentile ranks replace absolute values in user-facing displays
- Time-series data is represented as trend direction + magnitude, not raw values

### 6.2 What Is Stored vs. What Is Displayed

| Data Layer | Contains | Visible to User |
|---|---|---|
| Scrape buffer (RAM only) | Raw HTML → parsed fields | Never |
| Feature store (SQLite) | Derived ML features, team UUIDs | No (internal) |
| Analysis cache (JSON on P2P) | Model outputs, abstract scores | Yes (via UI interpretation) |
| User-facing display | Natural language insights, charts | Yes |

### 6.3 Display Transformation

The app's UI layer converts abstract model outputs into user-friendly insights without revealing data sources:

- "Based on recent form analysis, both teams show strong offensive patterns" (NOT "Galatasaray scored 8 goals in last 3 matches according to mackolik.com")
- Trend charts show normalized indices (0-100 scale) without axis labels that reference specific statistics
- Team names are displayed (necessary for usability) but NO third-party branding, logos, or copyrighted imagery

### 6.4 Attribution Policy

- **Zero source attribution in the app** — the app provides its own analysis, not a display of third-party data
- The app's "About" section describes methodology: *"Analysis is based on proprietary statistical models applied to publicly available football match results"*
- No direct links to any data source website
- No screenshots, logos, or branding from any source

---

## 7. P2P Network Layer

### 7.1 Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    P2P Network                       │
│                                                      │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐       │
│  │ Node A  │◄───►│ Node B  │◄───►│ Node C  │       │
│  │(Device) │     │(Device) │     │(Device) │       │
│  └────┬────┘     └────┬────┘     └────┬────┘       │
│       │               │               │             │
│  ┌────▼────┐     ┌────▼────┐     ┌────▼────┐       │
│  │ Local   │     │ Local   │     │ Local   │       │
│  │ SQLite  │     │ SQLite  │     │ SQLite  │       │
│  └─────────┘     └─────────┘     └─────────┘       │
│                                                      │
│  Shared: Analysis Results (JSON)                     │
│  Shared: Model Updates (signed .tflite/.onnx)       │
│  Shared: Scraper Config Updates (signed JSON)        │
└──────────────────────────────────────────────────────┘
```

### 7.2 Technology Stack

#### Primary: Gun.js (via WebView Bridge or FFI)

- **Gun.js** — Decentralized, offline-first graph database
- Supports real-time P2P sync via WebRTC and websockets
- Works offline; syncs when connectivity is available
- No central server required (but optional relay peers can improve discovery)
- SEA (Security, Encryption, Authorization) module for cryptographic signing
- Mature ecosystem with known Flutter integration patterns via platform channels

#### Alternative: IPFS + libp2p (Heavier, More Complex)

- IPFS for content-addressed storage of analysis JSON files
- libp2p for peer discovery and data exchange
- Heavier footprint; requires native compilation per platform
- Better for large-scale but likely overkill for this app

#### Fallback: Custom DHT via dart:io Sockets

- Lightweight Kademlia-style DHT implemented in pure Dart
- Minimal dependencies
- More development effort but smallest runtime footprint
- Suitable if Gun.js or IPFS prove too heavy for mobile

### 7.3 P2P Data Schema

Each analysis result is a JSON document stored and shared on the P2P network:

```json
{
  "schema_version": "1.0",
  "analysis_id": "sha256(league + week + team_pair_hash + model_version)",
  "content_hash": "sha256(full_json_body)",
  "created_at_utc": "2026-03-31T22:00:00Z",
  "ttl_hours": 168,
  "league_id": "super_lig",
  "season": "2025-2026",
  "match_week": 28,
  "match_identifier": "sha256(home_uuid + away_uuid + date)",
  "model_version": "1.2.0",
  "analysis_payload": {
    "home_strength_index": 0.72,
    "away_strength_index": 0.58,
    "distribution": { ... },
    "confidence": 0.71,
    "feature_importance": { ... }
  },
  "producer_signature": "ed25519_signature_of_content_hash"
}
```

### 7.4 Deduplication Logic

Before running an analysis, the app checks the P2P network:

```
1. Compute analysis_id = sha256(league + week + team_pair + model_version)
2. Query P2P network for analysis_id
3. IF found AND ttl not expired AND signature valid:
     → Use cached result (skip scrape + inference)
4. ELSE:
     → Run full pipeline (scrape → features → inference)
     → Sign result with device key
     → Publish to P2P network
```

### 7.5 Trust & Validation

- **Producer Signing**: Each node signs its analyses with a locally generated Ed25519 keypair
- **Consensus**: If multiple nodes produce analyses for the same match with the same model version, results should be nearly identical (deterministic model). Nodes can cross-validate by comparing outputs.
- **Reputation**: Nodes that consistently produce results matching consensus build implicit trust scores (stored locally, never shared)
- **Tamper Detection**: Content hash verification on every received analysis; reject if hash doesn't match
- **Model Pinning**: Only accept analyses produced by recognized model versions (signed by developer)
- **TTL Expiration**: Analyses expire after the match has been played + 7 days; network naturally evicts stale data

### 7.6 Privacy Considerations

- **No user identity**: P2P participation is pseudonymous (device key only, no email/name/phone)
- **No personal data on network**: Only match analysis JSON travels the network
- **No tracking**: No analytics, no telemetry, no device fingerprinting
- **IP Addresses**: Nodes see each other's IPs during P2P communication; this is disclosed in privacy policy. Optional relay mode can obscure direct connections.

---

## 8. Flutter App Architecture

### 8.1 High-Level Architecture

```
┌─────────────────────────────────────────────────┐
│                  Presentation Layer              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │  League   │ │  Match   │ │  Analysis    │    │
│  │  Browser  │ │  Detail  │ │  Results     │    │
│  └──────────┘ └──────────┘ └──────────────┘    │
├─────────────────────────────────────────────────┤
│                  Domain Layer                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │  League   │ │  Analysis│ │  P2P Cache   │    │
│  │  Service  │ │  Engine  │ │  Manager     │    │
│  └──────────┘ └──────────┘ └──────────────┘    │
├─────────────────────────────────────────────────┤
│                  Data Layer                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │  Scraper  │ │  Feature │ │  ML Model    │    │
│  │  Engine   │ │  Store   │ │  Runtime     │    │
│  └──────────┘ └──────────┘ └──────────────┘    │
├─────────────────────────────────────────────────┤
│                Infrastructure Layer              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │  SQLite   │ │  P2P     │ │  Crypto      │    │
│  │  (drift)  │ │  (Gun.js)│ │  (Ed25519)   │    │
│  └──────────┘ └──────────┘ └──────────────┘    │
└─────────────────────────────────────────────────┘
```

### 8.2 Key Flutter Packages

| Package | Purpose |
|---|---|
| `flutter_riverpod` / `bloc` | State management |
| `drift` (formerly moor) | SQLite ORM for local feature store |
| `html` + `http` | HTML parsing and HTTP requests for scraping |
| `tflite_flutter` or `onnxruntime` | On-device ML inference |
| `cryptography` | Ed25519 signing, SHA-256 hashing |
| `flutter_webrtc` / custom Gun.js bridge | P2P communication |
| `fl_chart` | Data visualization (trend charts, radar charts) |
| `go_router` | Navigation |
| `flutter_localizations` | Turkish + English localization |
| `package_info_plus` | Version management for model updates |

### 8.3 Local Storage Schema (drift/SQLite)

```sql
-- Team registry (obfuscated)
CREATE TABLE teams (
  uuid TEXT PRIMARY KEY,
  display_name TEXT,   -- shown in UI
  league_id TEXT,
  internal_code TEXT   -- generated hash, not from source
);

-- Rolling feature store (no raw match data)
CREATE TABLE team_features (
  team_uuid TEXT REFERENCES teams(uuid),
  season TEXT,
  match_week INTEGER,
  computed_at TEXT,
  -- Rolling averages
  avg_goals_scored_5 REAL,
  avg_goals_conceded_5 REAL,
  avg_goals_scored_10 REAL,
  avg_goals_conceded_10 REAL,
  points_per_game_5 REAL,
  points_per_game_10 REAL,
  clean_sheet_ratio_10 REAL,
  home_win_ratio_10 REAL,
  away_win_ratio_10 REAL,
  elo_rating REAL,
  form_index REAL,
  -- Meta
  data_freshness_hours REAL,
  PRIMARY KEY (team_uuid, season, match_week)
);

-- Analysis results cache
CREATE TABLE analyses (
  analysis_id TEXT PRIMARY KEY,
  match_identifier TEXT,
  model_version TEXT,
  result_json TEXT,
  created_at TEXT,
  ttl_expires_at TEXT,
  from_p2p INTEGER DEFAULT 0,
  signature TEXT
);

-- P2P sync state
CREATE TABLE p2p_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT
);
```

### 8.4 Background Processing

- **Dart Isolates**: Heavy computation (scraping, feature extraction, ML inference) runs on separate isolates to keep UI responsive
- **workmanager** package: Schedule periodic background tasks for data freshness (Android)
- **BGTaskScheduler** integration: iOS background app refresh for data updates
- **Batched Processing**: Group match week data processing to minimize wake-ups

### 8.5 UI/UX Design Principles

- **Material 3 Design** with Turkish football-themed color palette
- **Offline-first**: Every screen works with locally cached data
- **Progressive disclosure**: Summary → Detail → Deep Analysis flow
- **Explainability first**: Every analysis shows "why" (feature importance visualization)
- **No gambling aesthetics**: No green felt, chips, odds-board layouts; use clean analytical dashboard style
- **Accessibility**: WCAG 2.1 AA compliance; supports dynamic text sizing and screen readers

---

## 9. Development Phases

### Phase 0: Foundation (Weeks 1-3)

> Set up project infrastructure and validate core assumptions

- [ ] Initialize Flutter project with clean architecture scaffold
- [ ] Set up drift (SQLite) database with schema
- [ ] Implement team registry with UUID mapping
- [ ] Build HTTP client with rate limiting, robots.txt parser, and User-Agent configuration
- [ ] Create scraper configuration system (JSON-based selector mapping)
- [ ] Write unit tests for data normalization layer
- [ ] Establish CI/CD pipeline (GitHub Actions)
- [ ] Create development documentation

**Deliverable**: Runnable app shell with database and HTTP infrastructure

### Phase 1: Data Pipeline (Weeks 4-7)

> Build the full data ingestion and transformation pipeline

- [ ] Implement HTML scrapers for all 3 source sites (with fallback chain)
- [ ] Build data normalization layer (raw HTML → canonical match schema)
- [ ] Implement feature engineering pipeline (canonical → ML features)
- [ ] Build rolling statistics calculator (form, H2H, league position)
- [ ] Implement Elo rating system
- [ ] Create data freshness tracking and staleness detection
- [ ] Build scraper health monitoring (detect when site structure changes)
- [ ] Backfill historical data (last 3-5 seasons)
- [ ] Data validation test suite (known matches → expected features)

**Deliverable**: Fully operational data pipeline producing ML-ready features

### Phase 2: AI Model (Weeks 8-11)

> Train, validate, and integrate the on-device ML model

- [ ] Prepare training dataset from historical features (Python/Pandas)
- [ ] Train XGBoost/LightGBM model with cross-validation
- [ ] Hyperparameter optimization (Optuna)
- [ ] Model evaluation (accuracy, calibration, Brier score)
- [ ] Export model to TFLite or ONNX format
- [ ] Integrate tflite_flutter / onnxruntime_flutter in the app
- [ ] Build inference pipeline in Dart (feature vector → model → output JSON)
- [ ] Implement confidence scoring
- [ ] Build feature importance extraction for explainability
- [ ] Model versioning and signature system
- [ ] A/B testing framework for model comparison

**Deliverable**: On-device inference producing analysis JSON for any upcoming match

### Phase 3: P2P Network (Weeks 12-16)

> Implement decentralized analysis sharing

- [ ] Evaluate and select P2P technology (Gun.js vs IPFS vs custom DHT)
- [ ] Build platform channel bridge for P2P library
- [ ] Implement analysis deduplication (check P2P before running local analysis)
- [ ] Build Ed25519 keypair generation and management
- [ ] Implement content signing and verification
- [ ] Build TTL-based cache eviction
- [ ] Implement peer discovery mechanism
- [ ] Build scraper config update distribution via P2P
- [ ] Stress test: simulate 100+ nodes on local network
- [ ] Implement bandwidth management (limit P2P traffic on mobile data)

**Deliverable**: Working P2P network where analyses are shared and deduplicated

### Phase 4: UI & Polish (Weeks 17-21)

> Build the user-facing app experience

- [ ] League browser screen (Süper Lig, 1. Lig match week view)
- [ ] Match detail screen with analysis display
- [ ] Analysis results visualization (radar charts, trend lines, form bars)
- [ ] Feature importance "Why this analysis?" overlay
- [ ] Settings screen (P2P toggle, data freshness preferences, language)
- [ ] Onboarding flow explaining what the app does (compliance-focused language)
- [ ] Turkish + English localization
- [ ] Dark mode / Light mode
- [ ] Offline mode indicators
- [ ] Comprehensive error handling UX
- [ ] Performance optimization (startup time, scroll performance)
- [ ] Accessibility audit and fixes

**Deliverable**: Polished, app-store-ready Flutter application

### Phase 5: Compliance & Launch (Weeks 22-25)

> Final compliance checks and store submission

- [ ] Legal review of all app text, metadata, screenshots
- [ ] Privacy policy document (hosted on GitHub Pages or similar)
- [ ] App Store metadata preparation (descriptions, keywords, screenshots)
- [ ] Google Play content rating questionnaire
- [ ] Apple age rating configuration
- [ ] Internal QA testing (20+ devices across iOS and Android)
- [ ] Beta testing via TestFlight + Google Play Internal Testing (50 testers)
- [ ] Address beta feedback
- [ ] Final store submission
- [ ] Monitor review process; respond to any reviewer questions
- [ ] Post-launch monitoring: crash reports, P2P network health

**Deliverable**: App live on both stores

### Phase 6: Post-Launch (Ongoing)

- [ ] Weekly model retraining during active season
- [ ] Monthly scraper configuration updates
- [ ] P2P network health monitoring
- [ ] User feedback incorporation
- [ ] Evaluate adding Türkiye Kupası support
- [ ] Evaluate adding advanced analysis types (goal patterns, tactical analysis)
- [ ] Seasonal major model retraining during off-season

---

## 10. Tech Stack Summary

| Component | Technology | Justification |
|---|---|---|
| **Framework** | Flutter 3.x (Dart) | Cross-platform (iOS + Android), single codebase |
| **State Management** | Riverpod or Bloc | Mature, testable, well-documented |
| **Local Database** | drift (SQLite) | Type-safe, reactive, offline-first |
| **HTTP Client** | http / dio | Standard Dart HTTP with interceptors |
| **HTML Parsing** | html package | Pure Dart, no native dependencies |
| **ML Inference** | tflite_flutter / onnxruntime | On-device inference, small model support |
| **ML Training** | Python (XGBoost/LightGBM) | Best-in-class for tabular data |
| **P2P Network** | Gun.js (via bridge) or custom Dart DHT | Offline-first, decentralized |
| **Crypto** | cryptography package | Ed25519 signing, SHA-256 hashing |
| **Charts** | fl_chart | Customizable, performant Flutter charts |
| **Navigation** | go_router | Declarative routing |
| **CI/CD** | GitHub Actions | Free for open-source, Flutter support |
| **Beta Distribution** | TestFlight + Firebase App Distribution | Standard channels |

---

## 11. Risk Matrix & Mitigations

| # | Risk | Impact | Probability | Mitigation |
|---|---|---|---|---|
| R1 | Google Play rejects app as "gambling companion" | Critical | Medium | Conservative language; no odds; submit compliance precheck |
| R2 | Source websites block scraping | High | Medium | 3 fallback sources; community input; open data fallback |
| R3 | Source website structure changes | Medium | High | JSON selector config; automated broken scraper detection |
| R4 | P2P network too few nodes | Medium | High | App functions fully standalone; P2P is optimization only |
| R5 | TFLite model too large for mobile | Medium | Low | GBDT models are tiny (<5MB); quantization available |
| R6 | ML model accuracy too low for value | High | Medium | Ensemble models; Elo baseline; transparent confidence |
| R7 | Copyright claim from source website | High | Low | Complete data transformation; no source attribution; derivative work |
| R8 | Battery drain from P2P + scraping | Medium | Medium | Aggressive batching; respect battery saver; user controls |
| R9 | Apple rejects for "not enough functionality" | Medium | Low | Rich UI, explainability, historical analysis, trend tracking |
| R10 | Legal issues with Turkish gambling regulations | Critical | Low | No gambling facilitation; pure analysis; legal review |

---

## 12. Acceptance Criteria per Phase

### Phase 0 ✓
- App builds and runs on both iOS and Android
- SQLite database creates tables on first launch
- HTTP client respects rate limits in integration tests

### Phase 1 ✓
- Scraper extracts correct data for 100% of last season's Süper Lig matches
- Feature engineering produces identical outputs for identical inputs (deterministic)
- Raw scraped data is never written to persistent storage

### Phase 2 ✓
- Model inference runs in < 200ms on a Pixel 6 / iPhone 12 equivalent
- Model achieves > 50% accuracy on hold-out test set (better than random for 3-class)
- Confidence calibration: 70% confidence predictions are correct ~70% of the time

### Phase 3 ✓
- Two devices on same WiFi discover each other and sync analyses within 30 seconds
- A device receiving a P2P analysis for a match it hasn't analyzed skips local computation
- Tampered analysis JSON is rejected by signature verification

### Phase 4 ✓
- All screens render correctly on phones (360dp+ width) and tablets
- Turkish and English localization covers 100% of user-visible strings
- App passes automated accessibility checks (semantics, contrast ratios)

### Phase 5 ✓
- App is accepted on both Google Play and Apple App Store
- No guideline violation notices within first 30 days
- Crash-free rate > 99.5%

---

*Last updated: 2026-04-01*
*Document version: 1.0*
