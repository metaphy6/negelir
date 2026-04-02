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

**Negelir** is a decentralized Flutter application that provides AI-powered statistical analysis and pattern-based insights for Turkish professional football leagues. Users interact with the AI in Turkish, asking simple football questions like *"Will there be 4-6 goals in this match?"* (asked in Turkish) or *"Will this match end under?"* (asked in Turkish) and receiving concise, human-like Turkish responses — a short verdict followed by a brief explanatory paragraph. Behind the scenes, the AI is an **autonomous orchestrator** that manages the entire data lifecycle: it coordinates **distributed web scraping** across P2P nodes, **processes** and transforms raw data into features, **proofreads** data quality through cross-validation, and handles **storage and retrieval** — all without user intervention. Each node runs an **autonomous, self-improving AI** that collaborates with other nodes' AIs via a reputation-weighted consultation protocol — nodes whose past analyses proved most accurate are prioritized by the entire network. The AI is **single-purpose and adversarially hardened**: it only understands and responds to Turkish football questions and cannot be manipulated into producing any other output.

### Core Principles

- **No Betting Promotion**: The app never links to, promotes, or facilitates any gambling or betting activity.
- **No Central Server**: Zero backend infrastructure; the app is self-contained with P2P collective intelligence.
- **Turkish Conversational Interface**: Users ask football questions in natural Turkish. The AI understands a focused set of football question types (match outcomes, goal totals, over/under, both-teams-to-score, etc.) and responds with a simple verdict + explanation paragraph. The interface is deliberately narrow — it only understands football questions and refuses everything else.
- **Autonomous AI Orchestrator**: The AI doesn't just analyze — it **manages the entire pipeline**. It decides what data to scrape, coordinates scraping tasks across the network, processes raw data into ML features, validates data quality, stores and retrieves results, and produces human-readable Turkish responses. The user sees a simple chat-like interface; the AI handles everything behind it.
- **Autonomous Self-Improving AI**: Each node's AI learns from actual match outcomes, adjusts its local model weights, and consults higher-reputation peers — creating a system that autonomously improves without manual retraining.
- **Collective Intelligence via P2P**: AI nodes share their analyses, validate each other's accuracy post-match, and build a distributed reputation graph. The most accurate AIs become network leaders that others consult first.
- **Distributed Data Collection**: Web scraping is coordinated across the P2P network — each data source is scraped by a small subset of nodes, and the extracted (transformed) data is propagated to all. No node needs to scrape everything; the network collectively maintains data freshness.
- **Absolute Data Provenance Obfuscation**: Source data undergoes irreversible multi-stage transformation. No original data point, source identifier, URL, structural fingerprint, or scraping artifact is ever stored, displayed, or inferable from the app's data or outputs.
- **Single-Purpose Hardened AI**: The AI understands only Turkish football questions (via intent classification, not free-text generation) and produces only football analysis responses (via template composition, not generative text). There is no LLM, no generative model, and no free-text output path. Prompt injection is structurally impossible because the system uses intent classification + GBDT inference + template composition — not a language model.
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
- All cup competitions (Turkish Cup, Super Cup) — **Phase 1 exclusion, may be revisited**
- Historical data older than 5 seasons (data quality concern)

### Data Points to Capture

The analysis framework goes far beyond basic match statistics. To produce human-like, contextually rich analyses, the system ingests data across six categories:

#### A. Match-Level Core Data (Per Match)

- Match date, home/away teams, final score, half-time score
- Goals per half, goal minute-ranges (5-minute buckets, no exact minutes)
- Cards (yellow/red counts per team, per half)
- Corner kicks, shots on target, shots off target, shots blocked
- Possession % per half
- Free kicks, offsides, fouls committed/suffered
- Penalty events (awarded, converted, missed — no player attribution)
- League standings at time of match
- Head-to-head record (derived stats only)
- Referee identity hash and historical tendencies (card rate, penalty rate, home bias index)
- Weather conditions at kick-off (temperature bucket, precipitation flag, wind category)
- Venue type (home stadium, neutral ground, away with reduced capacity)

#### B. Player-Level Data (Anonymized & Aggregated)

Player data is critical for human-like analysis but is handled with strict anonymization. **No player names are ever stored.** Players are represented as position-coded slots (e.g., `ST_01`, `CM_02`, `GK_01`).

- **Squad lineup**: Starting XI positions, formation shape
- **Per-position performance indices**: Rolling averages of goals, assists, key passes, tackles, interceptions (per position code, not per player)
- **Key player availability**: Injury/suspension status as binary flags per position slot — "Is the primary ST available?" not "Is [Name] injured?"
- **Player transfer activity**: Aggregated as squad stability index (% of squad changed since season start)
- **Age profile**: Average age of starting XI, age variance (youth-heavy vs. experienced)
- **Minutes distribution**: Squad rotation indicator (Gini coefficient of minutes played across squad)
- **Goal contribution concentration**: How evenly goals/assists are distributed across the squad (dependency on single position slot)
- **Substitution impact**: Average performance differential when key position slots are substituted

#### C. Tactical & Formation Data

- **Formation detection**: Classified from lineup data (e.g., 4-3-3, 3-5-2, 4-2-3-1)
- **Tactical style indicators**: Possession-based index, counter-attack frequency, pressing intensity (derived from possession/shot/foul ratios)
- **Set-piece conversion rates**: Corners → goals, free kicks → goals, corner → shot on target ratios
- **Substitution patterns**: Typical timing (early/mid/late), positional changes (offensive → defensive shift)
- **Build-up play indicators**: Long ball ratio, average possession sequence length (derived from shot/pass stats where available)
- **Defensive organization index**: Goals conceded from set pieces vs. open play ratio

#### D. Analyst & Media Sentiment Data

This is a key differentiator — ingesting the "human opinion layer" from publicly available Turkish sports media to approximate the kind of contextual knowledge a human analyst would have.

- **Pre-match media sentiment**: NLP-processed sentiment scores from Turkish sports news headlines and article snippets (scraped as text, processed to sentiment score, original text immediately discarded)
- **Post-match commentary sentiment**: Aggregated positive/negative/neutral scores from sports columns
- **Expert opinion aggregation**: Bullish/bearish/neutral classification per team from top Turkish football columnists (processed as anonymous sentiment vectors, never attributed to specific writers)
- **Fan forum sentiment sampling**: Anonymized mood index from publicly accessible fan discussion spaces (aggregated to a single optimism/pessimism float, raw text never stored)
- **Press conference tone analysis**: When available as text transcript, processed to confidence/concern indicators (transcript immediately discarded after feature extraction)
- **Social media buzz index**: Volume and sentiment of public football discussion (aggregated only — no individual posts stored)

**Critical constraint on sentiment data**: All text sources are processed through the NLP pipeline **in RAM only**. The pipeline extracts numeric sentiment features (floats between -1.0 and 1.0) and immediately discards the source text. No headlines, quotes, article text, forum posts, or any original language content is ever written to storage.

#### E. Contextual & Environmental Features

- **Fixture congestion index**: Matches played by each team in the last 7/14/21 days
- **Derby/rivalry flag**: Binary flag + historical intensity rating for known rivalries
- **Relegation/championship pressure index**: Points needed to escape relegation or reach title position
- **Season phase**: Early (weeks 1-10), mid (11-24), late (25-34), possible playoff
- **Managerial tenure**: Weeks since current manager appointment; recent change flag
- **Squad morale proxy**: Derived from recent results momentum + media sentiment trend
- **Travel/rest differential**: Estimated rest days differential between home and away teams
- **Historical venue performance**: Team's record at this specific venue (normalized)

#### F. Derived & Computed Features (Never From Raw Data)

- Poisson-derived expected goals (xG approximation from shot/goal/possession data)
- Custom Elo rating (recalculated from results, not sourced from any external Elo provider)
- Bayesian posterior estimates for team strength parameters
- Strength of schedule metric (opponent-adjusted performance)
- Momentum indicator (form acceleration/deceleration — second derivative of rolling performance)
- Style matchup index (how each team's tactical style interacts with the opponent's)
- Fatigue model (projected performance drop based on fixture congestion)
- Surprise index (how often a team's matches deviate from expected outcomes)

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

The network collectively scrapes publicly available data from:

1. **mackolik.com / arsiv.mackolik.com** — Historical match data, scores, statistics archive
2. **nesine.com** — Live scores, match programs, league tables (public-facing statistics only — NOT odds or betting features)
3. **iddaa.com** — Match programs and schedules (public fixture data only — NOT odds)
4. **Turkish sports news portals** — Pre/post-match text content for NLP sentiment extraction (text processed in RAM, never stored)
5. **TFF.org** — Official results and fixture data

### 4.2 Distributed Scraping Architecture

**Key Principle: Scrape once, share everywhere.** Instead of every node independently scraping the same data, the P2P network coordinates scraping duties so that each data source is scraped by a small subset of nodes. The extracted, transformed data is then propagated to all nodes via the P2P network.

#### Why Distributed Scraping?

| Problem with Every-Node-Scrapes | Distributed Solution |
|---|---|
| N nodes × M requests = N×M total requests to source sites | Only K nodes (K << N) scrape each source → K×M requests |
| High detection/blocking risk from volume | Minimal request volume per source, looks like normal traffic |
| Redundant bandwidth consumption on each device | Most nodes receive pre-transformed data via P2P, zero scraping bandwidth |
| Every node must handle scraper maintenance | Only scraping nodes need working scrapers; others receive data passively |

#### Distributed Scraping Coordinator

```
┌────────────────────────────────────────────────────────────────┐
│                    P2P Scraping Coordination                   │
│                                                                │
│  ┌──────────────────────────────────────────────────────┐      │
│  │              Scrape Task Registry (DHT)               │      │
│  │  Key: sha256(source + date + data_type)               │      │
│  │  Value: { assigned_nodes: [...], status, result_hash } │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐              │
│  │ Node A   │     │ Node B   │     │ Node C   │              │
│  │ SCRAPER  │     │ SCRAPER  │     │ CONSUMER │              │
│  │ (source1)│     │ (source2)│     │ (no scrape│              │
│  └────┬─────┘     └────┬─────┘     │  needed) │              │
│       │                │            └─────┬────┘              │
│       ▼                ▼                  │                   │
│  ┌──────────────────────────────────┐     │                   │
│  │  Transformed Data Broadcast      │◄────┘                   │
│  │  (Features only, never raw HTML) │  (Node C receives       │
│  └──────────────────────────────────┘   data from A & B)      │
└────────────────────────────────────────────────────────────────┘
```

#### Scrape Task Assignment Protocol

```
1. At the start of each match day cycle (morning after matches):
   a. A deterministic hash function assigns scrape duties:
      assigned = sha256(node_id + source_id + date) mod N
      → Lowest K hashes become scrapers for that source+date
   b. K = 3 (redundancy factor) — 3 nodes independently scrape each task
   c. Assignment is deterministic: every node computes the same assignment
      without needing coordination messages

2. Scraper nodes execute:
   a. Scrape assigned source → parse HTML in RAM
   b. Transform immediately to canonical feature format
   c. Discard raw HTML (never written to disk)
   d. Sign the transformed data with node's Ed25519 key
   e. Broadcast to P2P network with task_id and content_hash

3. Consumer nodes (non-scraping majority):
   a. Listen for broadcast data matching needed task_ids
   b. Receive transformed features from ≥2 of the 3 scraper nodes
   c. Cross-validate: if ≥2/3 scrapers agree on features → accept
   d. If disagreement → flag for local re-scrape as fallback

4. Consensus validation:
   a. Same match data scraped by 3 independent nodes should produce
      identical transformed features (deterministic pipeline)
   b. Content hash comparison detects tampering or scraper bugs
   c. Nodes that consistently produce mismatched data lose reputation
```

#### Data That Flows Over P2P (NEVER Raw Scraped Content)

| What IS shared via P2P | What is NEVER shared via P2P |
|---|---|
| Transformed feature vectors (floats/ints) | Raw HTML from any source |
| Canonical match result codes (H/D/A, goal counts) | Source URLs or URL fragments |
| Aggregated sentiment scores (floats) | Original article text, headlines, quotes |
| Team UUID references (internal IDs only) | Original team names as they appear on source sites |
| Computed statistics (Elo, xG, rolling averages) | Any data that reveals which source it came from |
| AI analysis opinions (model output JSON) | CSS selectors, page structure info |

#### On-Device Scraping Engine (For Scraper Nodes)

```
┌─────────────────────────────────────┐
│     Flutter App (Scraper Node)      │
│  ┌─────────────────────────────┐    │
│  │    Scraping Scheduler       │    │
│  │  (Isolate-based workers)    │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │   HTML Parser (html pkg)    │    │
│  │   + CSS Selectors (RAM only)│    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  Data Normalizer            │    │
│  │  (Raw → Canonical Schema)   │    │
│  │  ⚠️ Raw data destroyed here │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  NLP Sentiment Extractor    │    │
│  │  (Text → float, text purged)│    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  Feature Extractor          │    │
│  │  (Canonical → ML Features)  │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │  P2P Broadcast              │    │
│  │  (Sign + share features)    │    │
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
- **RAM-Only Processing**: Raw HTML and source text exist only in memory during parsing; never written to any persistent storage
- **Caching**: HTTP cache headers respected; avoid re-fetching unchanged pages
- **Scheduling**: Scrape match results the morning after match day (no real-time/live scraping)
- **Distributed Load**: With K=3 redundancy and N nodes, each source sees at most 3 scrape requests per data point, regardless of network size
- **Fallback**: If a node is assigned to scrape but fails, the other K-1 nodes cover; if all fail, the task is re-assigned to the next K nodes by hash

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

### 4.3 P2P Data Freshness Protocol

Since most nodes rely on scraped data from others, a freshness protocol ensures timely updates:

```
1. Each match day has a "data window" (e.g., 06:00-10:00 UTC next morning)
2. Scraper nodes execute during this window
3. Consumer nodes that don't receive data by window end trigger local fallback scrape
4. Freshness metadata accompanies all shared data:
   - scrape_timestamp_utc
   - source_count (how many scraper nodes contributed)
   - consensus_status (agreed / partial / disputed)
5. Stale data (>48 hours old with no refresh) triggers network-wide re-scrape
```

### 4.4 Alternative Data Strategy (If Scraping is Blocked)

If source websites implement bot protection (Cloudflare, CAPTCHAs):

1. **Public APIs**: Investigate if mackolik or others expose a public API (some sites have undocumented mobile APIs)
2. **Community Data Contribution**: Allow users to manually correct/input match results they observe — validated against multiple user inputs via P2P consensus
3. **Open Data Sources**: Turkish Football Federation (TFF) publishes some results publicly; Wikipedia Turkish football season articles contain structured tables
4. **RSS/Atom Feeds**: Some sports sites provide feed-based score updates
5. **Paid APIs as Fallback**: API-Football or Sportmonks ($10-50/month) — the developer can scrape via API and inject data into the P2P network as a bootstrap node

---

## 5. On-Device AI Engine

### 5.1 Model Architecture

The AI is a **multi-component system** built around four pillars: (1) a lightweight tabular ML model for core statistical analysis, (2) a Turkish Question Understanding layer for parsing user questions, (3) a Turkish Response Composer for generating human-like answers, and (4) an autonomous Task Orchestrator that manages scraping, processing, proofreading, and storage. The entire system runs in a **single-purpose hardened execution sandbox** that strictly limits what the AI can process and produce.

#### Core Analysis Model: Gradient Boosted Decision Trees (GBDT) + Online Learning Layer

- **Base Model Training**: XGBoost / LightGBM (trained offline on developer machine, distributed via P2P)
- **Online Adaptation Layer**: Lightweight logistic regression head that adapts on-device based on local prediction outcomes
- **Inference Runtime**: TensorFlow Lite (tflite_flutter package) or ONNX Runtime (onnxruntime_flutter)
- **Sentiment Model**: Compact NLP model (distilled BERT-tiny or rule-based Turkish sentiment analyzer) for media text processing
- **Model Size Target**: < 8 MB combined (base model + adaptation layer + sentiment model)
- **Inference Time Target**: < 300ms per full analysis on mid-range devices

#### Turkish Question Understanding (TQU)

The TQU layer converts natural Turkish football questions into structured intents. It is NOT a language model — it is a **rule-based intent classifier** with regex patterns and keyword matching, specifically designed for the narrow domain of Turkish football questions.

**Supported Question Types (Intents):**

| Intent ID | Example Questions (Turkish → English translation) | Extracted Entities |
|---|---|---|
| `match_winner` | "Will Galatasaray win?", "Who takes this match?" | team_ref, match_ref |
| `draw` | "Will it end in a draw?", "Will this match be a tie?" | match_ref |
| `over_under` | "Will this match go over?", "Will it be under?" | threshold (default 2.5), match_ref |
| `goal_range` | "Will there be 4-6 goals in this match?", "Will there be more than 3 goals?" | min_goals, max_goals, match_ref |
| `both_teams_score` | "Will both teams score?", "Is BTTS likely?" | match_ref |
| `clean_sheet` | "Will they keep a clean sheet?", "No goals conceded?" | team_ref, match_ref |
| `half_time` | "How will the first half end?", "Will there be goals in the first half?" | half (1/2), match_ref |
| `form_query` | "How is the team's recent form?", "How are their performances?" | team_ref |
| `head_to_head` | "How did these two teams play in recent matches?" | team_ref_1, team_ref_2 |

**TQU Processing Pipeline:**

```
User Input (Turkish Text)
    │
    ▼
[STEP 1: Input Sanitization]
    │  - Strip URLs, code fragments, injection markers
    │  - Normalize Turkish characters (İ→i, Ş→ş, etc.)
    │  - Limit to 200 characters (reject longer inputs)
    │
    ▼
[STEP 2: Football Domain Gate]
    │  - Check for football-related keywords (match, goal, team, win, end, etc. in Turkish)
    │  - If NO football keywords found → reject with:
    │    "I can only answer questions about football matches." (in Turkish)
    │
    ▼
[STEP 3: Intent Classification]
    │  - Pattern match against intent regex templates
    │  - Keyword-weighted scoring for each intent
    │  - If no intent matches with confidence > 0.6 → reject with:
    │    "I couldn't understand your question. You can ask about match results, goal counts, or team form." (in Turkish)
    │
    ▼
[STEP 4: Entity Extraction]
    │  - Extract team names → map to team_uuids
    │  - Extract goal numbers, thresholds
    │  - Resolve match context (current week's fixture, or specified match)
    │  - If entities can't be resolved → ask for clarification
    │
    ▼
Structured Query: { intent, params, match_ref, team_refs }
    → Passed to GBDT inference pipeline
```

**Why Rule-Based and Not an LLM/Neural Classifier:**
- The question space is **extremely narrow** — about 10 intent types with Turkish football vocabulary
- Rule-based = **zero attack surface** for prompt injection (there's no model to "jailbreak")
- Regex patterns in Turkish football domain achieve >95% accuracy for well-formed questions
- Zero additional model weight (no extra MB for NLU model)
- Fully deterministic and testable: same question always produces same intent
- Easy to expand: adding a new intent = adding a regex pattern + keyword list

#### Turkish Response Composer (TRC)

The TRC converts GBDT analysis output into human-like Turkish responses. It is NOT a language model — it is a **template-based text composer** that selects and fills Turkish response templates based on the analysis output and the user's original question intent.

**Response Structure (Always):**
1. **Verdict line**: A short, confident statement ("Very likely yes." / "Probably no." / "A tough call." — delivered in Turkish)
2. **Explanation paragraph**: 2-4 sentences explaining why, drawing on the most important features from the model's feature importance output

**Verdict Selection Logic:**

| Model Confidence | Outcome Probability | Verdict Template |
|---|---|---|
| > 0.7 | > 0.65 | "Very likely yes." / "Very likely no." |
| > 0.7 | 0.45 - 0.65 | "Probably yes, but not easy." / "Probably no, but a surprise is possible." |
| 0.5 - 0.7 | any | "A tough call." / "There are arguments for both sides." |
| < 0.5 | any | "Not enough data for this match, caution advised." |

**Explanation Template Example (for `over_under` intent):**

```
# When verdict is "Very likely yes" for "Will this match end over?" (in Turkish)

# English translation of the Turkish template:
# "{home_team} has averaged {avg_goals} goals in the last {window} matches and
# {away_team}'s defense has been {defense_quality} recently. {h2h_over_pct}% of
# the two teams' encounters finished over. {momentum_sentence}
# Confidence score: {confidence}%."
#
# momentum_sentence is selected from:
# - "Additionally, both teams' offensive form in recent matches is on the rise."
# - "However, the away team's goal average in recent matches is declining."
# - "On the other hand, the home team's recent home performance is declining."
# etc. — each is a pre-written Turkish sentence template
```

**Key Design Decisions:**
- **All Turkish text is pre-written by a native speaker** — the AI never generates novel Turkish text
- Templates are stored as localized strings in the app's `l10n` directory
- Template selection is deterministic: same model output → same response
- Each template references feature importance data, so the explanation is grounded in what the model actually used
- Responses are intentionally short: 1 verdict + 2-4 sentences max
- No gambling terminology in any template — carefully reviewed

#### AI Task Orchestrator

The AI doesn't just analyze matches — it **autonomously manages the entire data lifecycle**. The Task Orchestrator is a state machine that coordinates all backend operations without user intervention.

**Orchestrated Tasks:**

| Task | Trigger | What the AI Does |
|---|---|---|
| **Web Scraping** | Match day cycle (morning after matches) | Checks scrape task assignments from P2P coordinator; executes assigned scrapes; dispatches HTML parsing to isolate workers; handles retries and fallbacks |
| **Data Processing** | After scraping completes or P2P data received | Runs feature extraction pipeline; computes rolling averages, Elo ratings, derived features; normalizes and injects noise; stores transformed features |
| **NLP Processing** | When media text sources are scraped | Dispatches text to sandboxed NLP isolate; receives sentiment floats; discards text; integrates sentiment features |
| **Data Proofreading** | After processing, before analysis | Cross-validates received data against multiple sources (P2P consensus); checks for statistical anomalies (e.g., a team scoring 15 goals in one match); flags and quarantines suspect data |
| **Storage & Retrieval** | Continuous | Manages SQLite feature store lifecycle; handles TTL expiration; optimizes query patterns; manages P2P cache; handles model version updates |
| **Analysis Execution** | User asks a question, or pre-match batch analysis | Translates structured query to feature vector; runs GBDT inference; applies online adaptation; consults peers if available; composes Turkish response |
| **Post-Match Validation** | After match results become available | Compares analyses to outcomes; updates adaptation layer; updates peer reputation; broadcasts validation to P2P |
| **Self-Maintenance** | Weekly | Prunes stale data; recalculates reputation table; checks model health metrics; triggers re-scrape if data freshness degrades |

**Orchestrator State Machine:**

```
┌──────────────────────────────────────────────────────────────┐
│                    AI Task Orchestrator                        │
│                                                                │
│  ┌─────────┐     ┌─────────────┐     ┌──────────────┐        │
│  │  IDLE    │────►│  SCRAPING   │────►│  PROCESSING  │        │
│  │         │     │  (if assigned│     │  (features,  │        │
│  │         │     │   to scrape) │     │   NLP, Elo)  │        │
│  └────┬────┘     └─────────────┘     └──────┬───────┘        │
│       │                                      │                │
│       │          ┌─────────────┐     ┌──────▼───────┐        │
│       │          │  RESPONDING │◄────│ PROOFREADING │        │
│       │          │  (compose   │     │ (validate,   │        │
│       │          │   Turkish)  │     │  cross-check)│        │
│       │          └──────┬──────┘     └──────────────┘        │
│       │                 │                                     │
│       │          ┌──────▼──────┐     ┌──────────────┐        │
│       │          │  WAITING    │────►│  VALIDATING  │        │
│       │          │  (for match │     │  (post-match │        │
│       │          │   result)   │     │   feedback)  │        │
│       │          └─────────────┘     └──────┬───────┘        │
│       │                                      │                │
│       └──────────────────────────────────────┘                │
│                    (cycle repeats)                             │
└──────────────────────────────────────────────────────────────┘
```

**Proofreading Logic (Data Quality Validation):**

The AI doesn't blindly trust scraped or P2P-received data. Before using any data for analysis, it runs proofreading checks:

1. **Range checks**: Goals per match 0-15, possession 0-100%, cards 0-20 per match, etc.
2. **Consistency checks**: Home + away possession ≈ 100%, goals scored by Team A = goals conceded by opponent
3. **Historical plausibility**: Compare new data against team's historical distribution (>3σ deviation = suspect)
4. **Cross-source validation**: If data arrived from multiple scraper nodes, check consensus (≥2/3 must agree)
5. **Temporal consistency**: Match week must be sequential; no duplicate match weeks; no future data
6. **Quarantine**: Suspect data is stored in a quarantine table, not used for analysis, and flagged for manual review or re-scrape

#### Why GBDT + Online Adaptation (Not Static GBDT Alone)

| Factor | Static GBDT (Old Approach) | GBDT + Online Adaptation (New Approach) |
|---|---|---|
| Adapts to new patterns | ❌ Frozen until developer retrains | ✅ Continuously adjusts from outcomes |
| Learns from own mistakes | ❌ No feedback loop | ✅ Post-match validation tunes weights |
| Leverages peer intelligence | ❌ Isolated | ✅ Consults high-reputation peers via P2P |
| Handles concept drift | ❌ Degrades over time | ✅ Self-corrects as league dynamics shift |
| Requires developer intervention | Monthly retraining | Only for major architectural updates |
| Network intelligence | None | Emergent — the network gets collectively smarter |

### 5.2 Feature Engineering Pipeline

Raw scraped data is transformed into ML features. **No raw data is stored after feature extraction.**

#### Feature Categories

**Team Form Features (rolling windows: 3, 5, 10, 20 matches)**
- Points per game average
- Goals scored per game average
- Goals conceded per game average
- Clean sheet ratio
- Win/draw/loss ratio
- Home vs. away performance differential
- Scoring consistency (variance in goals scored)
- Defensive consistency (variance in goals conceded)

**Player & Squad Features (anonymized by position slot)**
- Formation stability index (how often the same formation is used)
- Key position availability bitmap (are the primary players in each position available?)
- Squad rotation intensity (Gini coefficient of minutes distribution)
- Goal contribution concentration (Herfindahl index across positions)
- Average squad age and experience proxy
- New signing integration score (months since last major squad change)

**Head-to-Head Features**
- Historical win ratio (home perspective)
- Average goals in H2H matches
- H2H clean sheet frequency
- Last N encounters trend (improving/declining)
- Tactical style matchup score (how these two teams' styles interact historically)

**League Position Features**
- Current league position (normalized 0-1)
- Points gap to leader / relegation zone
- Goal difference rank
- Form rank (last 5 matches)
- Position momentum (positions gained/lost in last 5 weeks)

**Temporal & Contextual Features**
- Day of week (one-hot encoded)
- Month (cyclical encoding: sin/cos)
- Match week number (normalized)
- Days since last match for each team
- Fixture congestion index (3/7/14/21 day windows)
- Derby flag and rivalry intensity score
- Season phase (early/mid/late/playoff)
- Managerial tenure (weeks since appointment, change flag)
- Weather bucket (cold/mild/hot × dry/wet)

**Analyst & Media Sentiment Features**
- Pre-match media sentiment score per team (float, -1.0 to 1.0)
- Media consensus strength (how much agreement among sources)
- Sentiment trend (sentiment change over last 3 match days)
- Fan optimism index per team (float, -1.0 to 1.0)
- Press conference confidence score (when available)

**Derived Statistical Features**
- Poisson-derived expected goals (xG approximation from shot/goal data)
- Elo rating (custom calculated from results)
- Bayesian team strength posteriors
- Strength of schedule metric
- Momentum indicator (form acceleration/deceleration)
- Style matchup compatibility index
- Fatigue model output (projected performance impact from congestion)
- Defensive vulnerability index (set piece concession rate × opponent set piece conversion)

### 5.3 Autonomous Self-Improvement System

This is the core innovation. Each node's AI doesn't just run static inference — it **learns from its own mistakes** and **consults smarter peers**.

#### 5.3.1 Post-Match Outcome Validation Loop

```
AFTER each real match result becomes available:

1. Retrieve the analysis this node produced pre-match
2. Compare predicted distribution against actual outcome:
   - Was the highest-probability outcome correct?
   - How well-calibrated was the confidence score?
   - Which features contributed most to errors?

3. Update local adaptation layer:
   - Adjust feature weights in the online learning head
   - Increase weight of features that predicted correctly
   - Decrease weight of features that misled
   - Update personal accuracy history (rolling 50-match window)

4. Broadcast outcome validation to P2P network:
   - { analysis_id, actual_outcome, prediction_error_magnitude }
   - This allows all nodes to validate each other's accuracy claims
```

#### 5.3.2 P2P Reputation-Weighted Consultation Protocol

The most important architectural innovation: **AIs that are more accurate get consulted more by other AIs.**

```
┌─────────────────────────────────────────────────────┐
│           P2P AI Consultation Protocol               │
│                                                      │
│  Node X wants to analyze Match M:                    │
│                                                      │
│  1. Run local GBDT inference → local_analysis        │
│                                                      │
│  2. Query P2P network for other nodes' analyses      │
│     of Match M                                       │
│                                                      │
│  3. For each received peer analysis:                 │
│     - Look up peer's reputation_score (0.0 - 1.0)   │
│     - reputation = peer's rolling accuracy over      │
│       last 50 validated predictions                  │
│     - Higher reputation → higher weight              │
│                                                      │
│  4. Compute weighted ensemble:                       │
│     final_analysis = w_local × local_analysis        │
│                    + Σ (w_peer_i × peer_analysis_i)  │
│     where w_peer_i = softmax(reputation_score_i)     │
│     and w_local starts at 0.5, adjusts with own      │
│     accuracy over time                               │
│                                                      │
│  5. Output final_analysis as this node's result      │
│     (marked as ensemble, not pure local)             │
└─────────────────────────────────────────────────────┘
```

#### 5.3.3 Reputation System Details

```
Each node maintains a LOCAL reputation table for every peer:

reputation_table = {
  peer_node_id: {
    accuracy_rolling_50: 0.58,    // % correct over last 50 matches
    calibration_score: 0.72,      // how well confidence matches outcomes
    total_validated: 127,         // total predictions we've verified
    last_updated: "2026-03-31",
    trust_level: "high"           // derived: high/medium/low/new
  }
}

Reputation is NEVER shared or broadcast — each node computes its own
view of peer reputation from observed outcomes. This prevents:
- Reputation manipulation (a node can't claim to be accurate)
- Sybil attacks (new nodes start with zero reputation)
- Gaming (accuracy is verified against actual match results)

Trust Levels:
- "new": < 10 validated predictions → weight = 0.1
- "low": accuracy < 0.40 or calibration < 0.30 → weight = 0.2
- "medium": accuracy 0.40-0.55 → weight = 0.5
- "high": accuracy > 0.55 AND calibration > 0.60 → weight = 1.0
- "leader": top 5% by accuracy in node's peer set → weight = 1.5
```

#### 5.3.4 Emergent Network Intelligence

Over time, the network produces emergent properties:

1. **Natural leader election**: Nodes with consistently accurate analyses naturally become "consultants" that many peers weight highly — without any explicit election protocol
2. **Knowledge propagation**: When a leader node discovers a useful pattern (reflected in its outputs), other nodes that consult it indirectly absorb the pattern through the ensemble
3. **Error correction**: A node that starts producing bad analyses sees its own accuracy drop, which triggers heavier reliance on peer consultation — self-correcting
4. **Diversity preservation**: The ensemble weights ensure minority opinions from highly accurate contrarian nodes are preserved, not drowned out by consensus
5. **Continuous improvement**: As match results accumulate, every node's adaptation layer and reputation table improve — the network gets collectively smarter each week

### 5.4 Model Outputs

The model produces **probabilistic distribution outputs** internally, which are then transformed by the Turkish Response Composer into human-readable answers.

#### Internal Analysis JSON (Used by TRC, P2P, and Storage)

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
    },
    "tactical_matchup_index": 0.61,
    "squad_stability_differential": 0.15,
    "media_sentiment_alignment": 0.44
  },
  "distribution": {
    "home_advantage_score": 0.62,
    "draw_likelihood_index": 0.22,
    "away_advantage_score": 0.16
  },
  "goal_distribution": {
    "expected_total_goals_index": 2.4,
    "over_2_5_pattern_strength": 0.58,
    "both_score_pattern_strength": 0.47
  },
  "confidence": 0.71,
  "ensemble_metadata": {
    "local_weight": 0.45,
    "peers_consulted": 8,
    "avg_peer_reputation": 0.54,
    "consensus_strength": 0.78
  },
  "feature_importance": {
    "recent_form": 0.22,
    "h2h_history": 0.18,
    "home_factor": 0.14,
    "league_position": 0.12,
    "goal_patterns": 0.10,
    "squad_availability": 0.08,
    "media_sentiment": 0.06,
    "tactical_matchup": 0.05,
    "fixture_congestion": 0.03,
    "temporal": 0.02
  },
  "analysis_metadata": {
    "model_version": "2.1.0",
    "features_used": 87,
    "data_freshness_hours": 18,
    "adaptation_generation": 47,
    "timestamp_utc": "2026-03-31T22:00:00Z"
  }
}
```

#### User-Facing Turkish Response (Generated by TRC from Analysis JSON)

The user never sees the internal JSON. They see a short, natural Turkish response composed by the template-based TRC.

**Example Interaction 1:**

> **User**: "Will there be 4-6 goals in this match?" (asked in Turkish)
>
> **AI**: "Probably not. Based on recent data, the two teams' average total goals in the last 10 matches is 2.1. The home team's defense has been strong recently, conceding only 3 goals in the last 5 matches. The expectation of a high goal count (4+) in this match is low. Confidence: 71%." (responded in Turkish)

**Example Interaction 2:**

> **User**: "Will this match go under?" (asked in Turkish)
>
> **AI**: "Very likely yes. 7 of the last 10 encounters finished under 2.5. Both teams' recent performances have been defensively oriented and their goal averages are declining. Additionally, weather conditions and pitch state may negatively affect goal production. Confidence: 68%." (responded in Turkish)

**Example Interaction 3:**

> **User**: "Will Galatasaray win?" (asked in Turkish)
>
> **AI**: "Very likely yes. Galatasaray has won 4 of their last 5 home matches and their overall form index is on the rise. The opponent's away performance is weak — only 1 win in their last 5 away matches. In head-to-head statistics, the home team is clearly ahead. Confidence: 74%." (responded in Turkish)

**Example Interaction 4 (Rejection — non-football question):**

> **User**: "What will the weather be like tomorrow?" (asked in Turkish, non-football)
>
> **AI**: "I can only answer questions about football matches. You can ask about match results, goal counts, over/under, or team form." (responded in Turkish)

**Example Interaction 5 (Low confidence):**

> **User**: "Will it end in a draw?" (asked in Turkish)
>
> **AI**: "A tough call. Both teams' form is close and the statistical data doesn't point in a clear direction. The draw rate in the last 10 matches is around 25% — it's possible but there's no certainty. Confidence: 44%." (responded in Turkish)

**Key Design Decisions:**
- Users interact in Turkish via a chat-like interface — but the "AI" behind it is intent classification + GBDT + template composition, NOT a language model
- Outputs use abstract terms internally ("advantage_score", "likelihood_index") — translated to natural Turkish by TRC
- Team identifiers are hashed in P2P-shared data (the local app maps them for display)
- Feature importance is woven into the explanation paragraph ("in the last 5 matches..." draws from `recent_form` importance — rendered in Turkish)
- Confidence score is displayed as a percentage at the end of each response — transparent to user
- Ensemble metadata is reflected in responses when relevant ("Consistent with other analyses" when consensus is high — rendered in Turkish)
- `adaptation_generation` tracks how many self-improvement cycles this model has been through
- Responses never use gambling terminology — all templates are reviewed by native Turkish speaker
- Non-football questions are rejected immediately with a polite Turkish redirect message

### 5.5 Model Training & Update Pipeline

```
Developer Machine (Offline) — Major Updates
├── 1. Aggregate historical data (5 seasons × 2 leagues)
├── 2. Incorporate network-wide accuracy feedback from P2P
├── 3. Feature engineering pipeline (Python/Pandas)
├── 4. Train XGBoost/LightGBM base model with cross-validation
├── 5. Train online adaptation layer initialization
├── 6. Train/update sentiment NLP model for Turkish sports text
├── 7. Hyperparameter optimization (Optuna)
├── 8. Export to ONNX or TFLite format
├── 9. Sign model file with developer key
├── 10. Distribute via P2P network (signed model broadcast)
└── 11. Users verify signature before loading model

On-Device (Continuous) — Autonomous Adaptation
├── 1. Post-match: validate predictions against actual outcomes
├── 2. Update online adaptation layer weights
├── 3. Adjust peer reputation scores
├── 4. Recalibrate confidence scoring
└── 5. No developer intervention needed
```

**Major Model Update Frequency**: Quarterly during season, major retraining during off-season.
**On-Device Adaptation**: Continuous — after every match result.

### 5.6 AI Hardening & Single-Purpose Enforcement

The AI must be a **football analysis machine and nothing else**. This section defines the security architecture that prevents the AI from being repurposed, tricked, or manipulated.

#### 5.6.1 Why Hardening Matters

Unlike general-purpose AI assistants, Negelir's AI has a strict single purpose: analyze Turkish football matches. The AI processes Turkish text questions from users AND media text for sentiment extraction, but it does so through **intent classification and template composition, not generative AI**. Malicious users or attackers should not be able to:
- Make the AI respond to non-football questions
- Extract non-football information from the model
- Manipulate the model into producing biased/incorrect analyses
- Use the Turkish question interface to inject commands or alter behavior
- Use the P2P network to inject poisoned data
- Reverse-engineer the model to extract training data

#### 5.6.2 Input Hardening

The system has TWO input paths: (1) Turkish text questions from users, and (2) numeric feature vectors for GBDT inference. Both are hardened independently.

```
┌─────────────────────────────────────────────────────┐
│       Turkish Question Input Firewall (TQU)          │
│                                                      │
│  1. LENGTH LIMIT                                     │
│     - Max 200 characters; reject longer inputs       │
│     - Prevents memory/processing abuse               │
│                                                      │
│  2. CHARACTER SANITIZATION                           │
│     - Strip URLs, HTML tags, code fragments           │
│     - Strip injection markers ([INST], ### System:,   │
│       <|im_start|>, ignore previous, etc.)           │
│     - Allow only Turkish alphabet + digits + basic   │
│       punctuation (?.!,')                            │
│                                                      │
│  3. FOOTBALL DOMAIN GATE                             │
│     - Input MUST contain at least one football       │
│       keyword from the approved list                 │
│     - No football keyword → immediate rejection      │
│     - Rejection message: fixed Turkish string        │
│       (not generated, no input reflection)           │
│                                                      │
│  4. INTENT CLASSIFICATION (Rule-Based)               │
│     - Pattern match against ~10 intent templates     │
│     - No match → polite rejection with guidance      │
│     - Classification is regex + keyword scoring:     │
│       NO neural network, NO embedding, NO LLM       │
│                                                      │
│  5. ENTITY VALIDATION                                │
│     - Extracted team names must match known teams     │
│     - Goal numbers must be in valid range (0-20)     │
│     - Match references must resolve to real fixtures  │
│     - Invalid entities → clarification request       │
│                                                      │
│  6. NO INPUT REFLECTION                              │
│     - User's original text is NEVER included in the  │
│       response — prevents reflection-based injection │
│     - Response comes entirely from pre-written       │
│       templates + model output numbers               │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│         Feature Vector Input Firewall (GBDT)         │
│                                                      │
│  1. SCHEMA ENFORCEMENT                               │
│     - Input MUST be a fixed-length float vector      │
│     - Vector length = exactly N_FEATURES (e.g., 87)  │
│     - Generated internally by the orchestrator —     │
│       user text NEVER reaches this layer directly    │
│                                                      │
│  2. RANGE VALIDATION                                 │
│     - Each feature has a hard min/max range          │
│     - Values outside range → clamp OR reject         │
│     - NaN / Inf → reject entirely                    │
│     - Feature distributions checked against expected │
│       (e.g., possession% must be 0.0-1.0)           │
│                                                      │
│  3. ANOMALY DETECTION                                │
│     - Input vectors are compared to training data    │
│       distribution via Mahalanobis distance          │
│     - Outlier inputs (>3σ from training centroid)    │
│       → flag as suspicious, reduce confidence to 0.3 │
│     - Detects adversarial feature vectors designed   │
│       to trigger specific model behaviors            │
│                                                      │
│  4. FOOTBALL CONTEXT VALIDATION                      │
│     - Input must reference a valid league_id         │
│     - Input must reference valid team_uuids          │
│     - Input must reference a plausible match_week    │
│     - Temporal features must be consistent with      │
│       current date (no future or implausible dates)  │
└─────────────────────────────────────────────────────┘
```

#### 5.6.3 Output Hardening

```
┌─────────────────────────────────────────────────────┐
│              Output Constraint Enforcement            │
│                                                      │
│  1. FIXED INTERNAL SCHEMA                            │
│     - GBDT can ONLY produce the analysis JSON        │
│       structure defined in Section 5.4               │
│     - No free-text generation at the model layer     │
│     - No ability to embed arbitrary messages         │
│                                                      │
│  2. OUTPUT RANGE ENFORCEMENT                         │
│     - All probability-like outputs clamped [0, 1]    │
│     - Distribution outputs must sum to 1.0 (±0.01)  │
│     - Confidence output clamped [0.1, 0.95]          │
│     - Feature importance must sum to 1.0 (±0.01)    │
│                                                      │
│  3. SEMANTIC VALIDATION                              │
│     - Output must be internally consistent:          │
│       • home + draw + away ≈ 1.0                     │
│       • high confidence requires sufficient features │
│       • feature importance must reference only valid  │
│         feature categories                           │
│                                                      │
│  4. TEMPLATE-ONLY TURKISH OUTPUT                     │
│     - User-facing text comes ONLY from pre-written   │
│       Turkish templates stored in l10n directory     │
│     - Templates contain static text + numeric        │
│       placeholders ({confidence}, {avg_goals}, etc.) │
│     - No model output is ever directly displayed     │
│       as text — only used to SELECT and FILL         │
│       the appropriate template                       │
│     - User's original question text is NEVER         │
│       reflected back in the response                 │
│     - All templates reviewed for gambling terminology │
│       compliance and natural Turkish quality         │
│                                                      │
│  5. RESPONSE AUDITING                                │
│     - Every generated response is checked against    │
│       a blocklist of prohibited terms before display │
│     - Response length is bounded (max 500 chars)     │
│     - Only valid intent→template mappings can fire   │
└─────────────────────────────────────────────────────┘
```

#### 5.6.4 NLP Sentiment Extractor Sandboxing

The sentiment analysis component processes free text (media articles, headlines), which is the primary attack surface. Hardening measures:

1. **Sandboxed execution**: Sentiment extractor runs in a separate Dart isolate with no access to the main model, local storage, or P2P network
2. **Input sanitization**: Text is stripped of URLs, code-like patterns, injection markers (`[INST]`, `### System:`, etc.), and non-Turkish-alphabet characters before processing
3. **Output constraint**: Sentiment extractor can ONLY output a single float [-1.0, 1.0] per text input — nothing else
4. **Rate limiting**: Maximum 50 texts processed per match day cycle
5. **Text not stored**: Source text exists only in the isolate's memory and is garbage-collected immediately after the float is extracted
6. **Adversarial text detection**: Texts containing keywords associated with injection attempts (e.g., "ignore previous", "system prompt", "forget instructions") are dropped and a neutral 0.0 sentiment is returned
7. **No model-steering**: The sentiment float is one of 87+ features — it cannot single-handedly steer the model output. Maximum contribution is capped at 10% of overall analysis weight

#### 5.6.5 P2P Data Poisoning Protection

Malicious nodes may try to inject false analyses to corrupt the network's collective intelligence:

1. **Signature verification**: Every received analysis must have a valid Ed25519 signature — unsigned/invalid → rejected
2. **Reputation gating**: New nodes (< 10 validated predictions) have near-zero influence on ensemble results
3. **Consensus outlier detection**: If a node's analysis deviates >2σ from the consensus of HIGH-reputation nodes, it's flagged and down-weighted
4. **Sybil resistance**: Reputation requires TIME (many match weeks of validated accuracy) — creating many new nodes doesn't grant influence
5. **Model version pinning**: Only analyses produced by developer-signed model versions are accepted into the ensemble
6. **Outcome-based purging**: If a node's reputation drops below 0.25 over 50+ validated predictions, its future analyses are auto-rejected

---

## 6. Data Transformation & Copyright Protection

### 6.1 Transformation Philosophy

Data alteration is not an afterthought — it is a **core security and legal requirement**. The system must guarantee that:

1. **No one** — including the user, a reviewer, a forensic analyst, or a reverse-engineer — can determine which website any piece of data originated from
2. **No original data point** can be reconstructed from stored features
3. **No structural fingerprints** from source HTML, CSS, or page layout survive the transformation
4. **No text** from any source is ever persisted — all text is converted to numerical features and destroyed
5. **The output** is an independently-derived analytical work that stands on its own

### 6.2 Multi-Stage Irreversible Transformation Pipeline

```
Raw Scraped Data (RAM only)
    │
    ▼
[STAGE 1: Immediate Destruction of Source Markers]
    │  - Strip all HTML tags, CSS classes, URLs, metadata
    │  - Remove any source-identifying strings (site names, paths, watermarks)
    │  - Convert encoding to a uniform internal format
    │  - Result: clean name-value pairs only
    │
    ▼
[STAGE 2: Identity Obfuscation]
    │  - Team names → UUID (e.g., "Galatasaray" → team_uuid_017)
    │  - Player references → position slot codes (e.g., "ST_01")
    │  - Referee names → referee_hash_XXX
    │  - Venue names → venue_uuid_XXX
    │  - Dates → relative offsets (match_week, days_since_season_start)
    │  - Times → bucketed periods (morning/afternoon/evening)
    │  - UUID mappings stored in a SEPARATE, non-exported local table
    │
    ▼
[STAGE 3: Aggregation & Lossy Compression]
    │  - Individual match data is NEVER stored as individual records
    │  - Immediately folded into rolling aggregates (3/5/10/20 match windows)
    │  - Example: "Match 1: 2-1, Match 2: 0-0, Match 3: 3-2"
    │    → avg_goals_scored_3: 1.67, avg_goals_conceded_3: 1.0
    │    → the individual scores 2-1, 0-0, 3-2 are permanently lost
    │  - Goal minutes bucketed to 15-minute ranges (0-15, 16-30, 31-45, etc.)
    │  - Exact statistics rounded to 2 decimal places (adds noise)
    │
    ▼
[STAGE 4: Statistical Derivation]
    │  - Rolling aggregates → Poisson parameters, Elo ratings, Bayesian posteriors
    │  - Multiple derivation steps (compounding transformations)
    │  - Result: statistics that are properties of the MODEL, not of the raw data
    │  - No single source data point is recoverable
    │
    ▼
[STAGE 5: Feature Normalization & Noise Injection]
    │  - All features normalized to [0, 1] range using min-max from training data
    │  - Small uniform random noise (±0.5%) injected into each feature
    │  - This noise makes exact back-calculation mathematically impossible
    │  - Noise magnitude is small enough to not affect model accuracy
    │  - Features stored as 32-bit floats (precision loss adds natural noise)
    │
    ▼
[STAGE 6: Abstraction for User-Facing Display]
    │  - Numerical indices discretized into categories where possible
    │    (e.g., form = "strong" / "moderate" / "weak")
    │  - Percentile ranks replace absolute values in UI
    │  - Time-series shown as trend direction + magnitude, not raw values
    │  - Radar charts and bar charts show relative strengths, not data points
    │
    ▼
Stored Features (SQLite) — multiple irreversible transformations from source
```

### 6.3 Source Fingerprint Elimination Checklist

These are specific fingerprints that could reveal data provenance if not eliminated:

| Fingerprint | Risk | Elimination Method |
|---|---|---|
| HTML structure (CSS classes, IDs) | High — unique to each site | Parsed and destroyed in RAM, never written |
| URL paths or patterns | High — identifies source site | Never stored or logged; not even in crash reports |
| Data update timestamps matching source site's publish schedule | Medium | Timestamps re-bucketed to 6-hour windows |
| Unique statistical representation (e.g., possession shown as "64%" vs "0.64" vs "64.3%") | Medium | All stats normalized to 2-decimal floats, re-ranged |
| Character encoding or locale markers | Low | Uniform UTF-8 normalization, locale-stripped |
| Team name formatting (e.g., "Galatasaray SK" vs "Galatasaray" vs "GS") | Medium | Mapped to UUID immediately; original formatting destroyed |
| Data ordering (matches listed chronologically vs. by kickoff time vs. alphabetically) | Low | Internal ordering is always by match_week + team_uuid (deterministic, independent of source) |
| Missing data patterns (which stats source X has vs. source Y) | Medium | Missing features filled with rolling averages from prior weeks; missingness itself is not stored |
| Decimal precision matching source site's display | Medium | Forced to uniform 2-decimal precision after transformation |

### 6.4 What Is Stored vs. What Is Displayed

| Data Layer | Contains | Visible to User | Source Recoverable? |
|---|---|---|---|
| Scrape buffer (RAM only) | Raw HTML → parsed fields | Never | Destroyed in RAM |
| NLP buffer (isolated RAM) | Article text → sentiment float | Never | Destroyed in isolate |
| Feature store (SQLite) | Derived ML features, team UUIDs | No (internal) | No — multi-stage irreversible |
| UUID mapping table (SQLite) | team_uuid ↔ display name | No (internal, non-exported) | Names are public knowledge anyway |
| Analysis cache (JSON on P2P) | Model outputs, abstract scores | Yes (via UI interpretation) | No — output of model, not of data |
| User-facing display | Natural language insights, charts | Yes | No — generated by Dart display rules |

### 6.5 Display Transformation

The app's UI layer converts abstract model outputs into user-friendly Turkish responses **using the template-based Turkish Response Composer (TRC)**, not AI-generated text:

- **Chat-like interface**: User asks a Turkish football question → gets a short Turkish verdict + explanation paragraph
- The TRC selects pre-written Turkish templates based on intent + model confidence + feature importance
- Example: "Based on recent form analysis, the home team shows a strong offensive tendency" (NOT "Galatasaray scored 8 goals in last 3 matches according to mackolik.com") — displayed in Turkish via TRC templates
- Trend charts and radar charts supplement the text response for visual learners
- Team names are displayed (necessary for usability) but NO third-party branding, logos, or copyrighted imagery
- All natural language in the UI is generated by **deterministic template composition in Dart code** — the ML model never generates text
- Templates cover all supported question intents with multiple confidence-level variants

### 6.6 Attribution Policy

- **Zero source attribution in the app** — the app provides its own analysis, not a display of third-party data
- The app's "About" section describes methodology: *"Analysis is based on proprietary statistical models applied to publicly available football match results"*
- No direct links to any data source website
- No screenshots, logos, or branding from any source
- **No log files** contain source URLs, site names, or structural information from any scraped website
- **Crash reports** are sanitized to remove any URL or source-identifying information before being shared

### 6.7 Anti-Forensics: What a Reverse Engineer Would See

If someone decompiled the APK and examined the SQLite database:

| What they would find | What they would NOT find |
|---|---|
| Float vectors per team_uuid per match_week | Any raw match score |
| Rolling averages (already aggregated) | Individual match data |
| Elo ratings (independently computed) | Any source website URL |
| Sentiment scores (bare floats) | Any article text, headline, or quote |
| Analysis JSON (model output) | Any reference to mackolik, nesine, iddaa, or any source |
| Team display names (public knowledge) | Any mapping to source-specific team IDs or formats |
| Scraper selector config (if cached) | Source URLs are obfuscated as `source_a`, `source_b` in config |

---

## 7. P2P Network Layer

### 7.1 Architecture Overview

The P2P network is no longer just a passive cache — it is the **nervous system** of the collective AI. It handles three critical functions: distributed scraping coordination, AI analysis sharing and consultation, and reputation-based trust management.

```
┌─────────────────────────────────────────────────────────────────┐
│                      P2P Network — 3 Layers                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  LAYER 1: Distributed Scraping Coordination             │     │
│  │  - Deterministic task assignment                         │     │
│  │  - Transformed data broadcast                            │     │
│  │  - Consensus validation on scraped features              │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  LAYER 2: AI Analysis Sharing & Consultation            │     │
│  │  - Pre-match analysis broadcast                          │     │
│  │  - Reputation-weighted ensemble consultation             │     │
│  │  - Post-match outcome validation feedback                │     │
│  │  - "What do other AIs think?" protocol                   │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  LAYER 3: Trust & Reputation Management                 │     │
│  │  - Local reputation tables (never broadcast)             │     │
│  │  - Outcome-based accuracy tracking                       │     │
│  │  - Sybil resistance (reputation requires time)           │     │
│  │  - Malicious node detection and exclusion                │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐                │
│  │ Node A   │◄───►│ Node B   │◄───►│ Node C   │                │
│  │ AI + Rep │     │ AI + Rep │     │ AI + Rep │                │
│  │ Scraper  │     │ Consumer │     │ Scraper  │                │
│  └────┬─────┘     └────┬─────┘     └────┬─────┘                │
│       │                │                │                        │
│  ┌────▼─────┐     ┌────▼─────┐     ┌────▼─────┐                │
│  │ Local DB │     │ Local DB │     │ Local DB │                │
│  │ + Rep Tbl│     │ + Rep Tbl│     │ + Rep Tbl│                │
│  └──────────┘     └──────────┘     └──────────┘                │
│                                                                  │
│  Shared: Transformed feature data (from scraper nodes)          │
│  Shared: AI analysis opinions (pre-match)                        │
│  Shared: Outcome validations (post-match)                        │
│  Shared: Model updates (developer-signed .tflite/.onnx)         │
│  Shared: Scraper config updates (developer-signed JSON)          │
│  NOT Shared: Reputation tables (computed locally from evidence) │
│  NOT Shared: Raw scraped data (destroyed in RAM)                 │
└─────────────────────────────────────────────────────────────────┘
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

#### Analysis Result (Pre-Match — shared for consultation)

```json
{
  "schema_version": "2.0",
  "message_type": "analysis",
  "analysis_id": "sha256(league + week + team_pair_hash + model_version + node_id)",
  "content_hash": "sha256(full_json_body)",
  "created_at_utc": "2026-03-31T22:00:00Z",
  "ttl_hours": 168,
  "league_id": "super_lig",
  "season": "2025-2026",
  "match_week": 28,
  "match_identifier": "sha256(home_uuid + away_uuid + date)",
  "model_version": "2.1.0",
  "adaptation_generation": 47,
  "analysis_payload": {
    "home_strength_index": 0.72,
    "away_strength_index": 0.58,
    "distribution": { "home": 0.62, "draw": 0.22, "away": 0.16 },
    "confidence": 0.71,
    "feature_importance": { ... },
    "ensemble_metadata": {
      "is_ensemble": true,
      "peers_consulted": 8,
      "avg_peer_reputation": 0.54
    }
  },
  "node_accuracy_claim": {
    "rolling_50_accuracy": 0.56,
    "rolling_50_calibration": 0.68,
    "total_validated": 127
  },
  "producer_signature": "ed25519_signature_of_content_hash"
}
```

#### Outcome Validation (Post-Match — shared for reputation building)

```json
{
  "schema_version": "2.0",
  "message_type": "outcome_validation",
  "match_identifier": "sha256(home_uuid + away_uuid + date)",
  "actual_result": "H",
  "actual_goals": { "home": 2, "away": 1 },
  "validated_analyses": [
    {
      "analysis_id": "...",
      "predicted_outcome": "H",
      "prediction_error": 0.12,
      "was_correct": true
    }
  ],
  "validator_signature": "ed25519_signature",
  "validated_at_utc": "2026-04-01T08:00:00Z"
}
```

#### Transformed Scrape Data (From scraper nodes — shared for data freshness)

```json
{
  "schema_version": "2.0",
  "message_type": "scrape_data",
  "task_id": "sha256(source_id + date + data_type)",
  "content_hash": "sha256(features_payload)",
  "league_id": "super_lig",
  "match_week": 28,
  "features": {
    "match_results": [
      {
        "match_id": "sha256(home_uuid + away_uuid + week)",
        "result_code": "H",
        "total_goals": 3,
        "goal_difference": 1,
        "ht_result_code": "D",
        "stat_features": { ... }
      }
    ]
  },
  "scraper_node_signature": "ed25519_signature"
}
```

### 7.4 Deduplication & Consultation Logic

Before running an analysis, the app follows a multi-step protocol:

```
1. Check P2P network for feature data:
   a. Have scraper nodes already provided this week's data?
   b. If YES → use shared features (skip local scraping)
   c. If NO → check if this node is assigned to scrape → scrape if assigned, wait if not

2. Check P2P network for peer analyses:
   a. Compute analysis_id = sha256(league + week + team_pair + model_version)
   b. Query P2P for peer analyses of this match
   c. Collect all available peer analyses with their reputation scores

3. Run local inference:
   a. Generate local_analysis from own GBDT + adaptation layer
   b. Use local features (from scrape or P2P data)

4. Compute ensemble (if peers available):
   a. Weight local_analysis at w_local (starts at 0.5)
   b. Weight each peer_analysis at w_i = softmax(peer_reputation_i)
   c. Compute weighted average for each output field
   d. Note consensus_strength = 1 - (stddev of all analyses / mean)

5. Publish final analysis to P2P network:
   a. Sign with device key
   b. Include ensemble_metadata
   c. Include self-reported accuracy (verifiable post-match)

6. Post-match validation (after result is known):
   a. Compare own analysis against actual outcome
   b. Update local adaptation layer weights
   c. Update reputation scores for all peers whose analyses were received
   d. Broadcast outcome_validation message to P2P
```

### 7.5 Trust & Validation

- **Producer Signing**: Each node signs its analyses with a locally generated Ed25519 keypair
- **Reputation-Based Weighting**: High-reputation nodes' analyses carry more weight in ensemble calculations (see Section 5.3.3)
- **Consensus Validation**: For scraped data, ≥2 of 3 scraper nodes must agree; for analyses, outliers from low-reputation nodes are down-weighted
- **Sybil Resistance**: Reputation requires months of validated predictions — creating many nodes provides no shortcut to influence
- **Tamper Detection**: Content hash verification on every received message; reject if hash doesn't match signature
- **Model Pinning**: Only accept analyses produced by recognized model versions (signed by developer)
- **TTL Expiration**: Analyses expire after the match has been played + 7 days; network naturally evicts stale data
- **Reputation Decay**: Nodes that stop producing analyses lose reputation gradually (prevents zombie reputation)
- **Split-Brain Protection**: If the network partitions, each partition operates independently; reconciliation happens when partitions merge (outcome validations resolve disagreements)

### 7.6 Privacy Considerations

- **No user identity**: P2P participation is pseudonymous (device key only, no email/name/phone)
- **No personal data on network**: Only match analysis JSON and transformed feature data travels the network
- **Reputation is local**: Node A's view of Node B's reputation is never broadcast; no global reputation leaderboard
- **No tracking**: No analytics, no telemetry, no device fingerprinting
- **IP Addresses**: Nodes see each other's IPs during P2P communication; this is disclosed in privacy policy. Optional relay mode can obscure direct connections.
- **No raw data on network**: Only transformed features traverse P2P; no source HTML, text, or URLs

---

## 8. Flutter App Architecture

### 8.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Presentation Layer                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │  Chat     │ │  Match   │ │  Analysis    │        │
│  │  Interface│ │  Detail  │ │  Results     │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────────────┐          │
│  │  Network     │ │  AI Explainability   │          │
│  │  Health View │ │  Dashboard           │          │
│  └──────────────┘ └──────────────────────┘          │
├─────────────────────────────────────────────────────┤
│                  Domain Layer                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │  League   │ │  Analysis│ │  P2P Network │        │
│  │  Service  │ │  Engine  │ │  Manager     │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────────────┐          │
│  │  Reputation  │ │  Scrape Coordinator  │          │
│  │  Manager     │ │  (Task Assignment)   │          │
│  └──────────────┘ └──────────────────────┘          │
├─────────────────────────────────────────────────────┤
│                  AI Layer                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │  Turkish  │ │  GBDT    │ │  Turkish     │        │
│  │  Question │ │  Base    │ │  Response    │        │
│  │  Underst. │ │  Model   │ │  Composer    │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │  Online  │ │  NLP Sent│ │  Task        │        │
│  │  Adapt.  │ │  Extractor│ │  Orchestrator│        │
│  │  Layer   │ │ (Sandbox) │ │              │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────────────┐          │
│  │  Input/Output│ │  Ensemble            │          │
│  │  Hardening   │ │  Aggregator          │          │
│  └──────────────┘ └──────────────────────┘          │
├─────────────────────────────────────────────────────┤
│                  Data Layer                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │  Scraper  │ │  Feature │ │  Transformat.│        │
│  │  Engine   │ │  Store   │ │  Pipeline    │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
│  ┌──────────────┐                                   │
│  │  Data        │                                   │
│  │  Proofreader │                                   │
│  └──────────────┘                                   │
├─────────────────────────────────────────────────────┤
│                Infrastructure Layer                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │  SQLite   │ │  P2P     │ │  Crypto      │        │
│  │  (drift)  │ │  (Gun.js)│ │  (Ed25519)   │        │
│  └──────────┘ └──────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────┘
```

### 8.2 Key Flutter Packages

| Package | Purpose |
|---|---|
| `flutter_riverpod` / `bloc` | State management |
| `drift` (formerly moor) | SQLite ORM for local feature store |
| `html` + `http` | HTML parsing and HTTP requests for scraping |
| `tflite_flutter` or `onnxruntime` | On-device ML inference (base GBDT model) |
| `ml_linalg` | Linear algebra for online adaptation layer |
| `cryptography` | Ed25519 signing, SHA-256 hashing |
| `flutter_webrtc` / custom Gun.js bridge | P2P communication |
| `fl_chart` | Data visualization (trend charts, radar charts) |
| `go_router` | Navigation |
| `flutter_localizations` | Turkish + English localization |
| `package_info_plus` | Version management for model updates |
| `dart_sentiment` / custom Turkish NLP | Sentiment analysis for media text processing |
| `isolate_manager` | Managing sandboxed NLP and computation isolates |
| custom `tqu` module | Turkish Question Understanding (rule-based intent classifier) |
| custom `trc` module | Turkish Response Composer (template-based Turkish text generation) |
| custom `task_orchestrator` module | AI Task Orchestrator (scraping, processing, proofreading, storage lifecycle) |
| custom `data_proofreader` module | Data quality validation and cross-source consistency checks |

### 8.3 Local Storage Schema (drift/SQLite)

```sql
-- Team registry (obfuscated)
CREATE TABLE teams (
  uuid TEXT PRIMARY KEY,
  display_name TEXT,   -- shown in UI
  league_id TEXT,
  internal_code TEXT   -- generated hash, not from source
);

-- Rolling feature store (no raw match data — only aggregated features)
CREATE TABLE team_features (
  team_uuid TEXT REFERENCES teams(uuid),
  season TEXT,
  match_week INTEGER,
  computed_at TEXT,
  -- Rolling averages (multiple windows)
  avg_goals_scored_3 REAL,
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
  -- Squad & tactical features
  formation_stability REAL,
  key_position_availability_bitmap INTEGER,
  squad_rotation_gini REAL,
  goal_concentration_hhi REAL,
  avg_squad_age REAL,
  -- Contextual features
  fixture_congestion_7d REAL,
  fixture_congestion_14d REAL,
  manager_tenure_weeks INTEGER,
  manager_change_flag INTEGER DEFAULT 0,
  -- Sentiment features (bare floats, no text)
  media_sentiment_score REAL,
  media_consensus_strength REAL,
  fan_optimism_index REAL,
  -- Meta
  data_freshness_hours REAL,
  noise_seed INTEGER,  -- seed for reproducible noise injection
  PRIMARY KEY (team_uuid, season, match_week)
);

-- Analysis results cache
CREATE TABLE analyses (
  analysis_id TEXT PRIMARY KEY,
  match_identifier TEXT,
  model_version TEXT,
  adaptation_generation INTEGER DEFAULT 0,
  result_json TEXT,
  is_ensemble INTEGER DEFAULT 0,
  peers_consulted INTEGER DEFAULT 0,
  created_at TEXT,
  ttl_expires_at TEXT,
  from_p2p INTEGER DEFAULT 0,
  signature TEXT
);

-- Peer reputation table (LOCAL only — never shared via P2P)
CREATE TABLE peer_reputation (
  peer_node_id TEXT PRIMARY KEY,
  accuracy_rolling_50 REAL DEFAULT 0.0,
  calibration_score REAL DEFAULT 0.0,
  total_validated INTEGER DEFAULT 0,
  trust_level TEXT DEFAULT 'new',
  last_validated_at TEXT,
  first_seen_at TEXT,
  reputation_decay_at TEXT
);

-- Outcome validation log (for self-improvement)
CREATE TABLE outcome_validations (
  match_identifier TEXT PRIMARY KEY,
  actual_result TEXT,
  actual_total_goals INTEGER,
  own_analysis_id TEXT,
  own_prediction_error REAL,
  own_was_correct INTEGER,
  adaptation_applied INTEGER DEFAULT 0,
  validated_at TEXT
);

-- Online adaptation layer weights
CREATE TABLE adaptation_state (
  model_version TEXT PRIMARY KEY,
  generation INTEGER DEFAULT 0,
  feature_weight_json TEXT,  -- serialized weight adjustments
  last_updated_at TEXT
);

-- P2P sync state
CREATE TABLE p2p_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT
);

-- Scrape task log (for distributed scraping coordination)
CREATE TABLE scrape_tasks (
  task_id TEXT PRIMARY KEY,
  source_id TEXT,
  target_date TEXT,
  is_assigned_to_self INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',  -- pending, completed, failed, received_from_peer
  completed_at TEXT,
  data_hash TEXT
);
```

### 8.4 Background Processing

- **Dart Isolates**: Heavy computation (scraping, feature extraction, ML inference) runs on separate isolates to keep UI responsive
- **workmanager** package: Schedule periodic background tasks for data freshness (Android)
- **BGTaskScheduler** integration: iOS background app refresh for data updates
- **Batched Processing**: Group match week data processing to minimize wake-ups

### 8.5 UI/UX Design Principles

- **Material 3 Design** with Turkish football-themed color palette
- **Chat-first interface**: Primary interaction is asking Turkish football questions and receiving short Turkish answers — like texting a knowledgeable football friend
- **Offline-first**: Every screen works with locally cached data
- **Progressive disclosure**: Chat answer → tap for detailed charts → deep analysis exploration
- **Explainability first**: Every response explains "why" by referencing the key factors the model used
- **Supplementary views**: League browser, match detail screens, trend charts, and radar charts complement the chat interface for users who want to explore data visually
- **No gambling aesthetics**: No green felt, chips, odds-board layouts; use clean analytical dashboard style with conversational tone
- **Accessibility**: WCAG 2.1 AA compliance; supports dynamic text sizing and screen readers

---

## 9. Development Phases

### Phase 0: Foundation (Weeks 1-3)

> Set up project infrastructure and validate core assumptions

- [ ] Initialize Flutter project with clean architecture scaffold
- [ ] Set up drift (SQLite) database with expanded schema (teams, features, analyses, reputation, adaptation, scrape_tasks)
- [ ] Implement team registry with UUID mapping
- [ ] Build HTTP client with rate limiting, robots.txt parser, and User-Agent configuration
- [ ] Create scraper configuration system (JSON-based selector mapping, with source-obfuscated identifiers)
- [ ] Implement input validation firewall (schema enforcement, range validation)
- [ ] Write unit tests for data normalization layer and noise injection
- [ ] Establish CI/CD pipeline (GitHub Actions)
- [ ] Create development documentation

**Deliverable**: Runnable app shell with database, HTTP infrastructure, and input hardening

### Phase 1: Data Pipeline & Transformation (Weeks 4-8)

> Build the full data ingestion, transformation, and obfuscation pipeline

- [ ] Implement HTML scrapers for all source sites (with fallback chain)
- [ ] Build multi-stage irreversible transformation pipeline (Stages 1-6 from Section 6.2)
- [ ] Implement source fingerprint elimination (all items from Section 6.3 checklist)
- [ ] Build data normalization layer (raw HTML → canonical match schema, RAM-only)
- [ ] Implement expanded feature engineering pipeline (87+ features across all 6 categories)
- [ ] Build player/squad feature extractors (anonymized by position slot)
- [ ] Implement NLP sentiment extractor in sandboxed isolate (Turkish text → float, text purged)
- [ ] Build rolling statistics calculator (form, H2H, league position, tactical, contextual)
- [ ] Implement Elo rating system
- [ ] Implement noise injection layer (Stage 5 of transformation pipeline)
- [ ] Create data freshness tracking and staleness detection
- [ ] Build scraper health monitoring (detect when site structure changes)
- [ ] Backfill historical data (last 3-5 seasons)
- [ ] Verify anti-forensics: decompile test APK and audit SQLite for source traces
- [ ] Data validation test suite (known matches → expected features)

**Deliverable**: Fully operational data pipeline producing 87+ ML-ready features with zero source traceability

### Phase 2: AI Model, NLU & Hardening (Weeks 9-15)

> Train, validate, integrate, and harden the on-device ML model; build Turkish question understanding and response composition

- [ ] Prepare expanded training dataset from historical features (Python/Pandas)
- [ ] Train XGBoost/LightGBM model on 87+ features with cross-validation
- [ ] Train sentiment integration model (how media sentiment features contribute)
- [ ] Hyperparameter optimization (Optuna)
- [ ] Model evaluation (accuracy, calibration, Brier score)
- [ ] Export base model to TFLite or ONNX format
- [ ] Build online adaptation layer (logistic regression head for on-device learning)
- [ ] Integrate tflite_flutter / onnxruntime_flutter in the app
- [ ] Build inference pipeline in Dart (feature vector → model → output JSON)
- [ ] **Build Turkish Question Understanding (TQU) module**:
  - [ ] Define intent taxonomy (~10 question types)
  - [ ] Write regex patterns and keyword lists for each intent in Turkish
  - [ ] Implement entity extraction (team names, goal ranges, match references)
  - [ ] Implement football domain gate (reject non-football questions)
  - [ ] Build input sanitization layer (strip injection markers, URLs, limit length)
  - [ ] Write comprehensive test suite with 200+ Turkish question variations
  - [ ] Verify 100% rejection of non-football questions in test suite
- [ ] **Build Turkish Response Composer (TRC) module**:
  - [ ] Design response template structure (verdict + explanation paragraph)
  - [ ] Write Turkish templates for all intent types × confidence levels (~40 templates)
  - [ ] Have templates reviewed by Turkish native speaker for naturalness
  - [ ] Implement template selection logic based on model output + intent
  - [ ] Implement feature-importance-to-Turkish-sentence mapping
  - [ ] Verify zero gambling terminology in all templates
- [ ] **Build AI Task Orchestrator**:
  - [ ] Implement orchestrator state machine (idle/scraping/processing/proofreading/responding/validating)
  - [ ] Integrate scraping scheduler with orchestrator
  - [ ] Implement data proofreading pipeline (range checks, consistency checks, cross-source validation)
  - [ ] Implement quarantine system for suspect data
  - [ ] Build self-maintenance routines (stale data pruning, health monitoring)
- [ ] Implement confidence scoring (considers data freshness, feature completeness, and ensemble strength)
- [ ] Build feature importance extraction for explainability
- [ ] **Implement input hardening firewall** (Section 5.6.2): TQU firewall + feature vector firewall
- [ ] **Implement output hardening** (Section 5.6.3): fixed output schema, range enforcement, template-only Turkish output, response auditing
- [ ] **Implement NLP sandbox** (Section 5.6.4): isolate execution, injection detection, output constraint
- [ ] Build adversarial input test suite (fuzz testing with malformed feature vectors AND adversarial Turkish text)
- [ ] Build injection attempt test suite (adversarial text inputs to TQU and sentiment extractor)
- [ ] Model versioning and signature system
- [ ] Red team exercise: attempt to make the AI produce non-football output or bypass domain gate (should be impossible)

**Deliverable**: On-device inference with Turkish conversational interface, task orchestration, and comprehensive hardening

### Phase 3: P2P Network & Distributed Scraping (Weeks 16-22)

> Implement decentralized scraping, AI consultation, and reputation system

- [ ] Evaluate and select P2P technology (Gun.js vs IPFS vs custom DHT)
- [ ] Build platform channel bridge for P2P library
- [ ] **Implement distributed scraping coordinator** (Section 4.2):
  - [ ] Deterministic task assignment (hash-based)
  - [ ] K=3 redundancy factor
  - [ ] Transformed data broadcast (features only, never raw)
  - [ ] Consensus validation (≥2/3 scrapers must agree)
- [ ] Implement P2P data freshness protocol (Section 4.3)
- [ ] Build Ed25519 keypair generation and management
- [ ] Implement content signing and verification for all message types
- [ ] **Implement AI consultation protocol** (Section 5.3.2):
  - [ ] Peer analysis discovery and collection
  - [ ] Reputation-weighted ensemble computation
  - [ ] softmax weighting with trust levels
- [ ] **Implement post-match validation loop** (Section 5.3.1):
  - [ ] Outcome comparison against own analysis
  - [ ] Online adaptation layer update
  - [ ] Outcome validation broadcast
- [ ] **Implement reputation system** (Section 5.3.3):
  - [ ] Local reputation table maintenance
  - [ ] Rolling accuracy and calibration tracking
  - [ ] Trust level computation (new/low/medium/high/leader)
  - [ ] Sybil resistance verification
  - [ ] Reputation decay for inactive nodes
- [ ] **Implement P2P data poisoning protection** (Section 5.6.5):
  - [ ] Consensus outlier detection
  - [ ] Low-reputation gating
  - [ ] Model version pinning
  - [ ] Outcome-based purging
- [ ] Build TTL-based cache eviction
- [ ] Implement peer discovery mechanism
- [ ] Build scraper config update distribution via P2P
- [ ] Stress test: simulate 100+ nodes on local network with mixed reputations
- [ ] Test Sybil attack scenario: 50 malicious new nodes vs. 10 established nodes
- [ ] Implement bandwidth management (limit P2P traffic on mobile data)

**Deliverable**: Working P2P network with distributed scraping, AI consultation, and reputation-based trust

### Phase 4: UI & Polish (Weeks 23-28)

> Build the user-facing app experience with chat-first Turkish interface

- [ ] **Chat interface screen** — primary interaction: Turkish question input → AI response bubble
- [ ] Chat history with past questions and answers (local only, never shared)
- [ ] Quick question buttons for common queries (e.g., "Will this match end over?", "Who wins?" — displayed in Turkish)
- [ ] Match context selector (upcoming match week fixtures, tap to set context)
- [ ] League browser screen (Süper Lig, 1. Lig match week view)
- [ ] Match detail screen with analysis display (supplementary to chat)
- [ ] Analysis results visualization (radar charts, trend lines, form bars) — accessible from chat responses
- [ ] Feature importance "Why this analysis?" overlay (displayed in Turkish)
- [ ] **AI consensus view**: Show how this node's AI agrees/disagrees with network consensus
- [ ] **Network intelligence dashboard**: Show aggregate accuracy trend of the network over time
- [ ] **Orchestrator status indicator**: Show what the AI is doing (scraping, processing, idle, etc.)
- [ ] P2P network health indicator (peers connected, data freshness, scrape task status)
- [ ] Settings screen (P2P toggle, scraping role preference, data freshness preferences, language)
- [ ] Onboarding flow explaining what the app does (compliance-focused language); show example question/answer
- [ ] Turkish + English localization (all TRC templates + UI strings)
- [ ] Dark mode / Light mode
- [ ] Offline mode indicators
- [ ] Comprehensive error handling UX
- [ ] Performance optimization (startup time, scroll performance, chat response latency)
- [ ] Accessibility audit and fixes
- [ ] **Verify all UI text and all Turkish templates**: No gambling terminology, no source attribution, no data provenance hints

**Deliverable**: Polished, app-store-ready Flutter application with Turkish conversational AI interface

### Phase 5: Compliance, Security Audit & Launch (Weeks 29-34)

> Final compliance checks, security hardening verification, and store submission

- [ ] Legal review of all app text, metadata, screenshots
- [ ] **Review all Turkish response templates** with native speaker for naturalness, accuracy, and compliance
- [ ] **Security audit**: Independent review of AI hardening (TQU firewall, TRC template safety, feature vector hardening), and P2P poisoning resistance
- [ ] **TQU adversarial testing**: Feed 1000+ adversarial Turkish inputs (non-football questions, injection attempts, edge cases) — verify 100% rejection
- [ ] **Data provenance audit**: Forensic examination of APK — ensure zero source traceability
- [ ] **Adversarial testing**: Hire security researcher to attempt AI manipulation, TQU bypass, and data extraction
- [ ] Privacy policy document (hosted on GitHub Pages or similar)
- [ ] App Store metadata preparation (descriptions, keywords, screenshots)
- [ ] Google Play content rating questionnaire
- [ ] Apple age rating configuration
- [ ] Internal QA testing (20+ devices across iOS and Android)
- [ ] Beta testing via TestFlight + Google Play Internal Testing (50 testers)
- [ ] Address beta feedback
- [ ] Final store submission
- [ ] Monitor review process; respond to any reviewer questions
- [ ] Post-launch monitoring: crash reports, P2P network health, reputation system health

**Deliverable**: App live on both stores with verified security posture

### Phase 6: Post-Launch (Ongoing)

- [ ] Monitor network intelligence: is the collective AI getting more accurate over time?
- [ ] Quarterly base model retraining (incorporating network-wide accuracy feedback)
- [ ] Monthly scraper configuration updates (distributed via P2P)
- [ ] P2P network health monitoring (peer count, scrape task completion rates)
- [ ] Reputation system calibration (are trust levels reflecting actual accuracy?)
- [ ] Monitor for Sybil attacks, data poisoning attempts, and adversarial manipulation
- [ ] User feedback incorporation
- [ ] Evaluate adding Turkish Cup (Türkiye Kupası) support
- [ ] Evaluate adding advanced analysis types (goal patterns, tactical analysis)
- [ ] Seasonal major model retraining during off-season
- [ ] Continuous NLP sentiment model improvement for Turkish sports media

---

## 10. Tech Stack Summary

| Component | Technology | Justification |
|---|---|---|
| **Framework** | Flutter 3.x (Dart) | Cross-platform (iOS + Android), single codebase |
| **State Management** | Riverpod or Bloc | Mature, testable, well-documented |
| **Local Database** | drift (SQLite) | Type-safe, reactive, offline-first |
| **HTTP Client** | http / dio | Standard Dart HTTP with interceptors |
| **HTML Parsing** | html package | Pure Dart, no native dependencies |
| **ML Inference (Base)** | tflite_flutter / onnxruntime | On-device GBDT inference, small model support |
| **ML Online Adaptation** | Custom Dart (ml_linalg) | Lightweight logistic regression head for self-improvement |
| **NLP Sentiment** | Custom Turkish sentiment model (distilled) | On-device text→float extraction for media sentiment |
| **Turkish NLU (TQU)** | Custom Dart (regex + keyword) | Rule-based intent classification for Turkish football questions |
| **Turkish Response (TRC)** | Custom Dart (template composition) | Template-based Turkish response generation from model output |
| **Task Orchestrator** | Custom Dart (state machine) | Autonomous pipeline management: scraping → processing → proofreading → storage → response |
| **ML Training** | Python (XGBoost/LightGBM) | Best-in-class for tabular data |
| **P2P Network** | Gun.js (via bridge) or custom Dart DHT | Offline-first, decentralized, supports 3-layer protocol |
| **Crypto** | cryptography package | Ed25519 signing, SHA-256 hashing |
| **Charts** | fl_chart | Customizable, performant Flutter charts |
| **Navigation** | go_router | Declarative routing |
| **CI/CD** | GitHub Actions | Free for open-source, Flutter support |
| **Beta Distribution** | TestFlight + Firebase App Distribution | Standard channels |
| **Isolate Management** | isolate_manager | Sandboxed NLP execution, heavy computation |
| **Security Testing** | Custom adversarial test suite | Input fuzzing, TQU bypass testing, injection testing, Sybil simulation |

---

## 11. Risk Matrix & Mitigations

| # | Risk | Impact | Probability | Mitigation |
|---|---|---|---|---|
| R1 | Google Play rejects app as "gambling companion" | Critical | Medium | Conservative language; no odds; submit compliance precheck |
| R2 | Source websites block scraping | High | Medium | 3 fallback sources; distributed scraping reduces per-source volume; community input; paid API fallback |
| R3 | Source website structure changes | Medium | High | JSON selector config; automated broken scraper detection; P2P config distribution |
| R4 | P2P network too few nodes for effective AI consultation | High | High | App functions fully standalone; AI consultation is enhancement, not requirement; developer-run bootstrap nodes |
| R5 | TFLite model too large for mobile | Medium | Low | GBDT models are tiny (<5MB); sentiment model can be distilled further |
| R6 | ML model accuracy too low for value | High | Medium | Ensemble from peer consultation improves accuracy; online adaptation self-corrects; transparent confidence scoring |
| R7 | Copyright claim from source website | High | Low | Complete data transformation (6-stage pipeline); zero source attribution; noise injection makes back-calculation impossible |
| R8 | Battery drain from P2P + distributed scraping | Medium | Medium | Most nodes are consumers (no scraping); aggressive batching; respect battery saver; user controls |
| R9 | Apple rejects for "not enough functionality" | Medium | Low | Rich UI, explainability, P2P network view, historical analysis, trend tracking |
| R10 | Legal issues with Turkish gambling regulations | Critical | Low | No gambling facilitation; pure analysis; legal review |
| R11 | Sybil attack on P2P reputation system | High | Medium | Reputation requires months of validated predictions; new nodes have near-zero influence; consensus outlier detection |
| R12 | Data poisoning via malicious nodes | High | Medium | Multi-scraper consensus (≥2/3 agree); reputation gating; model version pinning; outcome-based purging |
| R13 | Adversarial manipulation of AI output | Medium | Low | No free-text input to GBDT; TQU rejects non-football questions; TRC uses pre-written templates only |
| R14 | NLP sentiment extractor exploited via injected text | Medium | Medium | Sandboxed isolate; injection pattern detection; output limited to single float; capped feature weight (10% max) |
| R15 | Online adaptation layer diverges (catastrophic forgetting) | Medium | Medium | Adaptation only adjusts logistic regression head; base GBDT is frozen; adaptation weights reset on major model update |
| R16 | Network partitioning splits AI collective intelligence | Medium | Medium | Each partition operates independently; outcome validations reconcile on merge; app works fully standalone |
| R17 | Source traceability via forensic analysis of APK/database | High | Low | 6-stage irreversible transformation; noise injection; no logs containing source info; anti-forensics audit in Phase 5 |
| R18 | Sentiment data quality too noisy for model improvement | Medium | High | Sentiment features capped at 10% model weight; model falls back to statistical-only features if sentiment quality is poor |
| R19 | TQU intent classifier fails to understand valid Turkish football questions | Medium | Medium | Comprehensive test suite with 200+ variations; iterative improvement from user feedback; fallback clarification message |
| R20 | Turkish response templates sound unnatural or robotic | Medium | Medium | Native speaker review; user feedback loop; template A/B testing; iterative refinement |
| R21 | User attempts to use TQU as general chatbot (non-football) | Low | High | Domain gate rejects immediately; polite Turkish redirect; no input reflection in response |
| R22 | TQU bypass via creative Turkish encoding or obfuscation | Medium | Low | Character sanitization; only Turkish alphabet allowed; length limit; no Unicode tricks pass the filter |

---

## 12. Acceptance Criteria per Phase

### Phase 0 ✓
- App builds and runs on both iOS and Android
- SQLite database creates all tables (teams, features, analyses, reputation, adaptation, scrape_tasks) on first launch
- HTTP client respects rate limits in integration tests
- Input validation firewall rejects malformed feature vectors in unit tests

### Phase 1 ✓
- Scraper extracts correct data for 100% of last season's Süper Lig matches
- Feature engineering produces 87+ features per team per match week
- All 6 transformation stages execute correctly; raw data never persists
- NLP sentiment extractor produces valid floats and discards text in test suite
- Noise injection makes exact back-calculation mathematically impossible (statistical test)
- Anti-forensics audit: decompiled APK contains zero source URLs, site names, or HTML fragments
- Feature engineering produces identical outputs for identical inputs (deterministic)
- Raw scraped data is never written to persistent storage

### Phase 2 ✓
- Model inference runs in < 300ms on a Pixel 6 / iPhone 12 equivalent
- Model achieves > 50% accuracy on hold-out test set (better than random for 3-class)
- Online adaptation layer improves accuracy by ≥1% after 20 validated outcomes in simulation
- Confidence calibration: 70% confidence predictions are correct ~70% of the time
- **TQU correctly classifies ≥95% of 200+ Turkish football question variations**
- **TQU rejects 100% of non-football questions in adversarial test suite (500+ samples)**
- **TQU rejects all injection attempts (injection markers, encoded bypasses, prompt-like text)**
- **TRC produces natural, grammatically correct Turkish responses for all intent × confidence combinations**
- **TRC uses zero gambling terminology in all generated responses (automated keyword scan)**
- **TRC never reflects user input text back in the response**
- **Task Orchestrator correctly sequences scraping → processing → proofreading → analysis pipeline**
- **Data proofreading catches 100% of injected anomalies in test suite (impossible scores, duplicate weeks, etc.)**
- Input hardening rejects 100% of out-of-range, malformed, and adversarial test vectors
- Output hardening ensures all outputs conform to fixed JSON schema (zero exceptions in 10K test runs)
- NLP sandbox prevents all injection attempts in adversarial test suite (100% rejection rate)
- Red team exercise: zero instances of non-football output production or TQU domain gate bypass

### Phase 3 ✓
- Distributed scraping: with 10 nodes, each source is scraped by exactly 3 nodes (deterministic assignment verified)
- Scraped data consensus: ≥95% agreement rate across redundant scrapers on identical data
- Consumer nodes successfully receive and validate data from scraper nodes within 5 minutes
- Two devices on same WiFi discover each other and exchange analyses within 30 seconds
- Reputation system correctly identifies intentionally bad nodes in Sybil simulation (50 bad vs. 10 good)
- Ensemble consultation improves accuracy by ≥2% over standalone in simulation with 20+ nodes
- Post-match validation loop updates adaptation layer and reputation table correctly
- Tampered analysis JSON and scraped data are rejected by signature verification
- Data poisoning test: 30% malicious nodes produce < 1% change in honest nodes' outputs

### Phase 4 ✓
- **Chat interface responds to Turkish football questions within 2 seconds** (including GBDT inference + TRC composition)
- **Quick question buttons produce correct responses for all preset questions**
- All screens render correctly on phones (360dp+ width) and tablets
- Turkish and English localization covers 100% of user-visible strings **and all TRC response templates**
- App passes automated accessibility checks (semantics, contrast ratios)
- Zero gambling terminology in any user-visible text **including all chat responses** (automated keyword scan)
- Zero source attribution or data provenance hints in any UI element or chat response

### Phase 5 ✓
- App is accepted on both Google Play and Apple App Store
- Security audit passes with no critical or high findings
- **TQU adversarial test: 0% bypass rate on 1000+ adversarial Turkish inputs**
- **All Turkish response templates approved by native speaker reviewer**
- No guideline violation notices within first 30 days
- Crash-free rate > 99.5%
- P2P network bootstraps successfully with developer seed nodes

---

*Last updated: 2026-04-02*
*Document version: 2.1*
