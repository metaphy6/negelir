# Autonomous Self-Sustaining Data Pipeline — Architecture Report

**Date:** 2026-04-07  
**Scope:** Design for a zero-intervention Negelir system that auto-adapts to season rollovers, player transfers, fixture schedule changes, and data source drift — all coordinated through the existing P2P network.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current Infrastructure Audit](#2-current-infrastructure-audit)
3. [Target Architecture](#3-target-architecture)
4. [Peer Role Specialisation](#4-peer-role-specialisation)
5. [Autonomous Data Lifecycle](#5-autonomous-data-lifecycle)
6. [P2P Coordination Protocol](#6-p2p-coordination-protocol)
7. [Self-Healing Mechanisms](#7-self-healing-mechanisms)
8. [Model Continuous Learning](#8-model-continuous-learning)
9. [Implementation Blueprint](#9-implementation-blueprint)
10. [Technology Choices](#10-technology-choices)
11. [Risk Analysis](#11-risk-analysis)

---

## 1. Problem Statement

The current system requires manual intervention at every boundary:

| Event | Current Response | Required Response |
|---|---|---|
| Season rolls over (June) | Edit `CURRENT_SEASON` in Python source, redeploy | Auto-detect from calendar + first fixture date |
| Player transfers (Jan/Jul) | Edit `_PLAYER_TEAMS` dict, redeploy | Auto-discover from daily roster scrape |
| Team promoted/relegated | Edit 5 files with team lists, redeploy | Auto-update team registry from league table API |
| Source HTML changes | Edit `selectors.json`, redeploy | Detect failure, rotate to backup source/selector |
| Match week advances | Nothing — demo data is static | Scrape new fixtures, compute features, predict |
| Model drifts | Nothing — retrain manually | Detect drift via outcome validation, retrigger training |

**Goal:** After `docker compose up`, the system runs indefinitely with zero human intervention. Every peer in the P2P network participates in data collection, validation, and model evolution.

---

## 2. Current Infrastructure Audit

### What Already Exists and Works

| Component | Status | File(s) |
|---|---|---|
| Content-addressed DataStore (SHA-256 dedup) | Production-ready | `p2p/node/peer.py` |
| Manifest-based delta sync between peers | Implemented | `p2p/simulation/runner.py` |
| SCRAPE_DATA P2P message type | Defined + transported | `p2p/protocol/messages.py` |
| Wire serialisation + integrity verification | Working | `p2p/protocol/transport.py` |
| Reputation-weighted ensemble predictions | Working (7 phases) | `p2p/simulation/runner.py` |
| Outcome validation + trust level updates | Working | `p2p/node/peer.py` |
| PostgreSQL schema: `scrape_tasks` table | Schema exists, **never used in code** | `migrations/001_initial.sql` |
| Go server `/api/v1/scrape/trigger` endpoint | Endpoint exists, **stub only** | `server/cmd/main.go` |
| `RealDataScraper` (OpenFootball + football-data.co.uk) | Fetches real CSVs + JSON | `ai/scraper/real_data.py` |
| Rate-limited HTML scraping engine | Working, 5s/domain | `ai/scraper/engine.py` |
| Team name normalisation (40+ mappings) | Working but static | `ai/scraper/real_data.py` |
| Docker Compose with PG + Redis + Go + Python | Working | `docker-compose.yml` |
| `--continuous` mode (sleep-loop) | Working but naive | `ai/main.py`, `p2p/main.py` |

### What's Missing

| Gap | Description |
|---|---|
| **Scheduled task execution** | No cron, no Celery, no APScheduler — only `while True: sleep(30)` |
| **Distributed scrape coordination** | `scrape_tasks` table exists but no code assigns/claims tasks |
| **Fixture resolution** | No upcoming-match database; can't map "next GS game" to a real date |
| **Roster tracking** | No `players` table; no roster scraping |
| **Season detection** | `CURRENT_SEASON` hardcoded; no calendar logic |
| **Selector health monitoring** | If CSS selectors break, scraper silently returns 0 matches |
| **Model retraining trigger** | Model trained once at startup; no drift detection |
| **Real network transport** | P2P uses in-memory queues; no TCP/UDP for cross-machine peers |
| **Persistent peer identity** | Nodes get new IDs every restart; no identity file |

---

## 3. Target Architecture

### High-Level Overview

```
                        ┌──────────────────────────────┐
                        │        Internet/Sources       │
                        │  OpenFootball  football-data  │
                        │  football-data.org  API-Foot  │
                        └────────┬────────┬────────────┘
                                 │        │
              ┌──────────────────┴────────┴──────────────────┐
              │              SCRAPER PEERS                    │
              │  (Elected by reputation; rotate daily)        │
              │  ┌────────┐  ┌────────┐  ┌────────┐         │
              │  │ Peer A │  │ Peer B │  │ Peer C │         │
              │  │src: OF │  │src: UK │  │src: API│         │
              │  └───┬────┘  └───┬────┘  └───┬────┘         │
              │      │           │           │               │
              │      └─────SCRAPE_DATA───────┘               │
              │              (P2P broadcast)                  │
              └──────────────────┬───────────────────────────┘
                                 │
              ┌──────────────────┴───────────────────────────┐
              │           ALL PEERS (N nodes)                 │
              │                                               │
              │  ┌─────────────────────────────────────┐     │
              │  │ DataStore (content-addressed)        │     │
              │  │ • Fixtures (upcoming schedule)       │     │
              │  │ • Results (completed matches)        │     │
              │  │ • Rosters (current team lineups)     │     │
              │  │ • Stats (team rolling aggregates)    │     │
              │  └─────────────────────────────────────┘     │
              │                    │                          │
              │  ┌─────────────────┴──────────────────┐      │
              │  │ Local Feature Engine                 │     │
              │  │ • Compute 130-col vectors from data  │     │
              │  │ • Detect season/week boundaries      │     │
              │  │ • Update Elo ratings incrementally    │     │
              │  └─────────────────┬──────────────────┘      │
              │                    │                          │
              │  ┌─────────────────┴──────────────────┐      │
              │  │ Local GBDT (XGBoost)                │      │
              │  │ • Predict upcoming matches           │      │
              │  │ • Retrain when drift detected        │      │
              │  └─────────────────┬──────────────────┘      │
              │                    │                          │
              │         ANALYSIS broadcast (P2P)             │
              │         OUTCOME_VALIDATION (P2P)             │
              │         Reputation updates (local)           │
              └──────────────────────────────────────────────┘
```

### Core Principle: Every Peer Is Autonomous

No single coordinator node. Every peer independently:
1. Knows what time it is → derives current season and match week
2. Checks its DataStore → knows what data it has and what's stale
3. Claims scrape tasks → fetches data it's missing (or receives it from peers)
4. Computes features → from local DataStore, no central DB needed
5. Runs inference → local GBDT model
6. Shares results → P2P broadcast
7. Validates outcomes → updates reputation table
8. Retrains model → when outcome data accumulates enough corrections

---

## 4. Peer Role Specialisation

Not all peers should scrape all sources simultaneously. The P2P network elects **scraper roles** to avoid redundant fetches and respect rate limits.

### 4.1 Role Types

| Role | Count | Responsibility | Election Criteria |
|---|---|---|---|
| **Scraper** | 1 per source | Fetch data from assigned source daily | Highest reputation + uptime |
| **Validator** | 2–3 | Cross-check scraped data across sources | Medium+ reputation |
| **Indexer** | 1 | Maintain canonical fixture index | Highest reputation (leader) |
| **Learner** | All | Retrain local model from shared data | Everyone |
| **Responder** | All | Answer user questions from local model | Everyone |

### 4.2 Election Protocol

```
Every 24h (midnight UTC, or first peer to detect new day):

1. ROLE_ELECTION message broadcast:
   {
     "type": "ROLE_ELECTION",
     "epoch_day": 20587,          // days since Unix epoch
     "candidates": {
       "scraper_openfootball": ["peer_A", "peer_B"],
       "scraper_footballdata": ["peer_C", "peer_D"],
       "validator": ["peer_E", "peer_F", "peer_G"],
       "indexer": ["peer_A"]
     }
   }

2. Each peer deterministically selects winners:
   - Sort candidates by: (trust_level_weight, uptime_hours, node_id)
   - Top-1 per scraper source, top-3 for validator, top-1 for indexer
   - Tie-breaking: lexicographic node_id (deterministic)

3. All peers arrive at the same assignment (no central authority).

4. If elected scraper goes offline → next candidate auto-promotes
   (detected via PING/PONG timeout after 5 min)
```

### 4.3 Redundancy

- If elected scraper fails to produce data within 2 hours of expected scrape time, the next-ranked candidate takes over.
- Validators compare data from 2+ sources for the same match. Mismatches go to `data_quarantine`.
- If all scrapers for a source fail, peers fall back to stale-but-cached DataStore records (TTL 7 days) and log a `DATA_STALE` warning.

---

## 5. Autonomous Data Lifecycle

### 5.1 Daily Scrape Cycle

```
 06:00 UTC ─── SCRAPE CYCLE START ───────────────────────────
 │
 ├─ Indexer peer:
 │   1. Fetch upcoming fixture list for current match week
 │   2. Broadcast FIXTURE_INDEX message:
 │      {fixtures: [{home: "team_001", away: "team_002",
 │                   kickoff: "2026-04-12T19:00Z", week: 30}, ...]}
 │   3. All peers store in DataStore (type: "fixture")
 │
 ├─ Scraper peers (per source):
 │   1. Fetch completed match results (yesterday + any missed)
 │   2. Fetch updated league standings
 │   3. Fetch roster changes (if source provides)
 │   4. Package as ScrapedRecord(s), broadcast SCRAPE_DATA
 │   5. All peers receive, dedup via content hash, merge
 │
 ├─ Validator peers:
 │   1. Wait for 2+ sources to report same match_week results
 │   2. Cross-check: FT score, HT score, cards, corners
 │   3. Mismatches → quarantine + alert via DATA_CONFLICT message
 │   4. Matches → mark as "validated" in DataStore
 │
 └─ All peers:
     1. Recompute rolling features for teams with new data
     2. Update Elo ratings from validated results
     3. Run inference on upcoming fixtures
     4. Broadcast ANALYSIS for next match week
     5. Store everything locally (DataStore + SQLite/PG)

 22:00 UTC ─── OUTCOME VALIDATION ───────────────────────────
 │
 ├─ Scraper peers:
 │   Fetch today's match results (live scores, final whistle)
 │
 └─ All peers:
     1. Compare own predictions vs actual outcomes
     2. Broadcast OUTCOME_VALIDATION
     3. Update peer reputation tables
     4. Flag model drift if accuracy < threshold over last 20 matches
```

### 5.2 Season Boundary Detection

No hardcoded `CURRENT_SEASON`. Instead:

```python
def detect_season(fixtures: list[Fixture]) -> SeasonState:
    """
    Derive season state from fixture data, not calendar constants.

    Logic:
    1. Find latest fixture with a result → that's the current season
    2. If no fixtures have results and all are in the future
       → new season hasn't started yet
    3. If latest result date was > 60 days ago and it's June-August
       → season ended, wait for new fixture index
    4. Extract season string from fixture metadata
    """

    # SEASON ROLLOVERS DETECTED AUTOMATICALLY:
    # - Old season's fixtures all have results → season_complete=True
    # - New season's fixtures appear in source → season transitions
    # - No manual edit needed anywhere
```

### 5.3 Transfer Window Tracking

Player rosters tracked as a new `data_type` in `ScrapedRecord`:

```python
# New ScrapedRecord types:
"fixture"        # Upcoming match schedule
"result"         # Completed match with scores + stats
"roster"         # Current squad list per team
"standing"       # League table (positions, points, GD)
"transfer"       # Player movement (from_team, to_team, date)
```

Roster scraping runs daily during transfer windows (Jan 1–31, Jul 1–Aug 31) and weekly otherwise. Every peer maintains a local player→team mapping derived from the latest `roster` records in its DataStore.

### 5.4 Data Type Lifecycle

```
                  ┌─────────┐
                  │ Scraped  │  (raw from source, unvalidated)
                  └────┬────┘
                       │ validator cross-check
                       ▼
                  ┌─────────┐
                  │Validated │  (2+ sources agree, or single trusted source)
                  └────┬────┘
                       │ feature engine processes
                       ▼
                  ┌─────────┐
                  │ Feature  │  (130-col vector stored per team×week)
                  └────┬────┘
                       │ model consumes
                       ▼
                  ┌─────────┐
                  │ Analysis │  (prediction + confidence, broadcast to peers)
                  └────┬────┘
                       │ outcome arrives
                       ▼
                  ┌─────────┐
                  │ Outcome  │  (actual result, error computed, reputation updated)
                  └────┬────┘
                       │ enough outcomes accumulated
                       ▼
                  ┌───────────┐
                  │ Retrained │  (model weights updated from real outcomes)
                  └───────────┘
```

---

## 6. P2P Coordination Protocol

### 6.1 New Message Types

Extending the existing `MessageType` enum:

| Message | Purpose | Broadcast Frequency |
|---|---|---|
| `FIXTURE_INDEX` | Share upcoming match schedule | Daily (indexer only) |
| `ROSTER_UPDATE` | Player transfer or squad change | On detection |
| `ROLE_ELECTION` | Daily role assignment | Every 24h |
| `DATA_CONFLICT` | Cross-source mismatch alert | On detection |
| `MODEL_CHECKPOINT` | Share retrained model hash | On retraining |
| `SEASON_BOUNDARY` | Season start/end detection | On detection |
| `HEARTBEAT` | Extended PING with capabilities | Every 5 min |

These join the existing types: `ANALYSIS`, `OUTCOME_VALIDATION`, `SCRAPE_DATA`, `PEER_DISCOVERY`, `QUERY_INTENT`, `PING`/`PONG`.

### 6.2 Distributed Scrape Task Queue

Activating the existing `scrape_tasks` table (schema is already in `migrations/001_initial.sql`, never used in code):

```
┌─────────────────────────────────────────────────────────────┐
│ scrape_tasks (PostgreSQL — each peer has local copy)        │
│                                                             │
│  task_id │ source_id      │ data_type │ date      │ status  │
│  ────────┼────────────────┼───────────┼───────────┼──────── │
│  t_001   │ openfootball   │ result    │ 2026-04-06│ pending │
│  t_002   │ footballdata   │ result    │ 2026-04-06│ assigned│
│  t_003   │ openfootball   │ fixture   │ 2026-04-12│ done    │
│  t_004   │ footballdata   │ roster    │ 2026-04-07│ pending │
└─────────────────────────────────────────────────────────────┘

Lifecycle:
  pending  → elected scraper claims it → assigned
  assigned → scraper fetches data, broadcasts SCRAPE_DATA → completed
  assigned → scraper fails (timeout 2h) → pending (re-election)
  completed→ validator cross-checks → validated
```

### 6.3 Data Freshness Protocol

Every peer tracks data freshness per team per data type:

```python
@dataclass
class FreshnessEntry:
    team_id: str
    data_type: str           # "result" | "fixture" | "roster" | "standing"
    last_updated: float      # Unix timestamp
    source_count: int        # how many sources confirmed this data
    content_hash: str        # latest data hash

# Staleness thresholds:
FRESHNESS_THRESHOLDS = {
    "result":   6 * 3600,    # 6 hours after match day
    "fixture": 24 * 3600,    # 24 hours
    "roster":   7 * 86400,   # 7 days (daily during transfer window)
    "standing": 12 * 3600,   # 12 hours
}
```

When a peer detects stale data, it broadcasts a `SCRAPE_REQUEST` to the elected scraper for that source. If the elected scraper doesn't respond within 30 minutes, any peer with bandwidth can volunteer.

---

## 7. Self-Healing Mechanisms

### 7.1 Selector Failure Detection

```python
class SelectorHealthMonitor:
    """
    After every scrape attempt, check whether selectors are still working.
    If a source returns 0 matches for 3 consecutive attempts, declare
    selector failure and rotate to backup selectors.
    """

    def check_health(self, source_id: str, matches_found: int):
        self._history[source_id].append(matches_found)

        recent = self._history[source_id][-3:]
        if len(recent) == 3 and all(m == 0 for m in recent):
            self._declare_failure(source_id)

    def _declare_failure(self, source_id: str):
        # 1. Try backup selector set (selectors_v2.json)
        # 2. If backup also fails → broadcast DATA_SOURCE_DOWN
        # 3. Other peers compensate by serving cached data
        # 4. Log event for operator awareness (optional webhook)
```

### 7.2 Source Rotation

Each source in `selectors.json` carries multiple selector versions:

```json
{
  "source_a": {
    "version": 3,
    "selectors": { "..." },
    "fallback_selectors": [
      { "version": 2, "selectors": { "..." } },
      { "version": 1, "selectors": { "..." } }
    ]
  }
}
```

If the current version fails, the scraper walks backwards through fallbacks. If all fail, the source is marked as down and the system relies on remaining sources + peer caches.

### 7.3 Peer Failure Recovery

```
Node crash:
  1. Peer stops sending HEARTBEAT
  2. After 5 min: neighbors mark it as "suspected_down"
  3. After 15 min: remove from mesh topology
  4. If it was an elected scraper → next candidate auto-promotes
  5. When node restarts:
     a. Load persistent identity (node_id from file, not re-generated)
     b. PEER_DISCOVERY broadcast to rejoin mesh
     c. Manifest exchange → delta-sync missing records
     d. Resume normal operation within minutes
```

### 7.4 Data Conflict Resolution

When validators detect conflicting data from 2+ sources:

```
Source A says: GS 2 - 1 FB
Source B says: GS 2 - 1 FB    → MATCH ✓ → validated
Source C says: GS 3 - 1 FB    → CONFLICT → quarantine

Resolution strategy (automated):
  1. Majority vote: 2/3 agree → accept majority (GS 2-1 FB)
  2. Source reputation: Weight by historical source accuracy
  3. Recency: More recent scrape wins ties
  4. If unresolvable → quarantine, wait for next scrape cycle
```

---

## 8. Model Continuous Learning

### 8.1 Incremental Retraining

The model doesn't need a full retrain on the entire dataset every time. XGBoost supports incremental updates:

```python
class ContinuousTrainer:
    """
    Accumulate validated outcomes. When enough new data arrives,
    retrain the model incrementally.
    """

    RETRAIN_THRESHOLD = 20  # matches with validated outcomes

    def on_outcome_validated(self, match_id, features, actual_label):
        self._buffer.append((features, actual_label))

        if len(self._buffer) >= self.RETRAIN_THRESHOLD:
            self._retrain()

    def _retrain(self):
        # Option A: Full retrain with all historical data (weekly)
        # Option B: Incremental — continue training from saved model
        #   xgb_model = xgb.Booster(model_file="current.model")
        #   xgb_model.update(new_dmatrix, iteration=current_round+1)

        # After retrain: broadcast MODEL_CHECKPOINT to peers
        # Peers with lower reputation adopt higher-reputation peer's model
```

### 8.2 Drift Detection

```python
class DriftDetector:
    """
    Monitor prediction accuracy over a rolling window.
    If accuracy drops below threshold, trigger retraining.
    """

    WINDOW = 30            # last 30 validated matches
    ACCURACY_FLOOR = 0.35  # below this → drift alarm
    CALIBRATION_FLOOR = 0.25

    def check(self) -> bool:
        recent = self._outcomes[-self.WINDOW:]
        accuracy = sum(1 for o in recent if o.was_correct) / len(recent)

        if accuracy < self.ACCURACY_FLOOR:
            log.warning("Model drift: accuracy %.2f < %.2f",
                       accuracy, self.ACCURACY_FLOOR)
            return True  # trigger retrain
        return False
```

### 8.3 Model Sharing via P2P

After retraining, a peer broadcasts a `MODEL_CHECKPOINT` message containing:
- Model hash (SHA-256 of serialised weights)
- Training data summary (N matches, date range, accuracy on holdout)
- Peer's reputation score

Other peers decide whether to adopt the new model:
```
if sender.trust_level in ("leader", "high")
   and sender.accuracy > my_accuracy + 0.05:
    request_model_weights(sender)  # transfer via SCRAPE_DATA message
    validate_on_local_holdout_set()
    if validation_accuracy >= my_current_accuracy:
        adopt_model()
```

---

## 9. Implementation Blueprint

### Phase 1: Persistent Peer Identity + Scheduler (Week 1)

**Goal:** Peers survive restarts and execute tasks on schedule.

| Task | File(s) | Description |
|---|---|---|
| Persistent node identity | `p2p/node/identity.py` (new) | Save/load `node_id` + keypair to `~/.negelir/identity.json` |
| APScheduler integration | `ai/scheduler.py` (new) | Daily scrape at 06:00 UTC, outcome check at 22:00, model retrain weekly |
| Heartbeat protocol | `p2p/protocol/messages.py` | Add `HEARTBEAT` message type, 5-min interval |
| Task claim protocol | `p2p/protocol/messages.py` | Add `TASK_CLAIM` / `TASK_COMPLETE` messages |

**APScheduler chosen over alternatives because:**
- Pure Python, runs inside existing Docker container
- Supports cron-style + interval triggers
- Job persistence via PostgreSQL (uses existing DB)
- No external service needed (unlike Celery + broker)

### Phase 2: Fixture Index + Season Detection (Week 2)

**Goal:** System knows what matches are upcoming without hardcoded data.

| Task | File(s) | Description |
|---|---|---|
| Fixture scraper | `ai/scraper/fixtures.py` (new) | Fetch upcoming match schedule from OpenFootball + football-data |
| Season state machine | `ai/common/season.py` (new) | Auto-detect current season from fixture dates, no `CURRENT_SEASON` constant |
| `FIXTURE_INDEX` message | `p2p/protocol/messages.py` | Broadcast fixture list to all peers |
| Match resolver | `ai/pipeline/resolver.py` (new) | Map user's question ("GS yarınki maç") → specific fixture_id |

### Phase 3: Distributed Scrape Coordination (Week 3)

**Goal:** Peers elect scrapers, claim tasks, avoid duplicate fetches.

| Task | File(s) | Description |
|---|---|---|
| Role election | `p2p/coordination/election.py` (new) | Deterministic role assignment based on reputation + uptime |
| Scrape task queue | `p2p/coordination/tasks.py` (new) | Activate the existing `scrape_tasks` table; peers claim and complete tasks |
| Source health monitor | `ai/scraper/health.py` (new) | Track consecutive failures, rotate selectors |
| Cross-source validator | `ai/proofreader/cross_validator.py` (new) | Compare 2+ sources for same match, quarantine conflicts |

### Phase 4: Roster Tracking + Player Resolution (Week 4)

**Goal:** Player transfers detected and propagated automatically.

| Task | File(s) | Description |
|---|---|---|
| Roster scraper | `ai/scraper/rosters.py` (new) | Fetch current squads from football-data.org API |
| Player registry (DB) | `migrations/002_players.sql` (new) | `players` table with team_id, joined_at, left_at |
| Player entity extraction | `ai/tqu/entities.py` (modify) | Fuzzy-match player names → team_id |
| `ROSTER_UPDATE` message | `p2p/protocol/messages.py` | Broadcast player movements to peers |

### Phase 5: Continuous Model Learning (Week 5)

**Goal:** Model retrains automatically from accumulated real outcomes.

| Task | File(s) | Description |
|---|---|---|
| Outcome collector | `ai/model/outcomes.py` (new) | Buffer validated outcomes; trigger retrain at threshold |
| Drift detector | `ai/model/drift.py` (new) | Rolling accuracy/calibration monitoring |
| Incremental trainer | `ai/model/trainer.py` (modify) | Support XGBoost incremental update from saved booster |
| `MODEL_CHECKPOINT` message | `p2p/protocol/messages.py` | Share retrained model metadata + weights via P2P |
| Model adoption protocol | `p2p/node/peer.py` (modify) | Accept model from higher-reputation peer if it validates better |

### Phase 6: Real Network Transport (Week 6+)

**Goal:** Replace simulated transport with real TCP for cross-machine peers.

| Task | File(s) | Description |
|---|---|---|
| TCP transport | `p2p/protocol/tcp_transport.py` (new) | asyncio TCP server/client implementing same `Transport` interface |
| Peer discovery (LAN) | `p2p/node/discovery.py` (new) | UDP multicast for local network; seed nodes for WAN |
| NAT traversal | `p2p/protocol/nat.py` (new) | STUN/TURN or relay peers for nodes behind NAT |
| TLS encryption | `p2p/protocol/tls.py` (new) | mTLS between peers using self-signed certs |

---

## 10. Technology Choices

### 10.1 Scheduler: APScheduler (not Celery, not Airflow)

| Option | Verdict | Reason |
|---|---|---|
| **APScheduler** | **Selected** | Embedded in Python process; uses existing PostgreSQL for job store; no extra container/service; cron + interval triggers |
| Celery + Redis | Rejected | Requires separate worker process + broker management; overkill for peer-local scheduling |
| Airflow / Prefect | Rejected | DAG orchestrators designed for data engineering teams; massive overhead for a P2P node |
| systemd timers | Rejected | Host-level; doesn't work inside Docker container |
| pg_cron | Future option | Good for DB-level triggers (e.g., materialise feature views), but Python logic needs APScheduler |

### 10.2 Transport: asyncio TCP (not libp2p, not gRPC)

| Option | Verdict | Reason |
|---|---|---|
| **asyncio TCP** | **Selected** | Same language (Python); exact same `Transport` interface as current simulated transport; minimal code change |
| libp2p (Python) | Future option | Mature peer discovery + NAT traversal, but heavy dependency; consider if asyncio TCP proves insufficient |
| gRPC | Rejected | RPC semantics don't fit broadcast/gossip model; adds protobuf compilation step |
| ZeroMQ | Rejected | Additional C dependency; asyncio TCP is sufficient |

### 10.3 Data Sources: Multi-Source with Fallback Chain

| Source | Data Available | API Key? | Rate Limit | Role |
|---|---|---|---|---|
| OpenFootball (GitHub raw) | Scores, dates, teams | No | None (raw files) | Primary — results |
| football-data.co.uk (CSV) | Cards, shots, fouls, corners, odds | No | Polite (5s/req) | Primary — stats |
| football-data.org (REST) | Match details, lineups, standings | Yes (free) | 10 req/min | Secondary — rosters, fixtures |
| API-Football (RapidAPI) | Everything (real-time scores) | Yes (paid) | Tier-dependent | Future — live data |
| Transfermarkt | Transfers, market values, squads | No (scrape) | Aggressive anti-scrape | Future — transfers |

**Minimum viable:** OpenFootball + football-data.co.uk covers results and stats. Football-data.org adds rosters and fixture schedules. No paid APIs required for the autonomous loop.

### 10.4 Model: XGBoost Incremental (not online learning)

| Option | Verdict | Reason |
|---|---|---|
| **XGBoost incremental** | **Selected** | Already in stack; `Booster.update()` appends trees to existing booster; fast (seconds) |
| River (online ML) | Rejected | Requires rewriting model; online learning less accurate than batch for tabular data |
| Full retrain weekly | Complement | Run full retrain on Sunday with all history; incremental updates mid-week |
| Neural network | Rejected | No advantage over GBDT for ≤130 tabular features; slower inference |

---

## 11. Risk Analysis

### 11.1 What Can Still Go Wrong

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| All free data sources shut down | Low | Critical | Monitor health; maintain 3+ sources; cache 7 days of data |
| Peers collude to inject false data | Low | High | Reputation system + cross-source validation; quarantine unverified data |
| Selector rot across all sources simultaneously | Low | High | Multiple fallback selector versions; alert on 3 consecutive failures |
| Model catastrophically drifts | Medium | Medium | Drift detector triggers retrain; peers share models; worst case: fall back to prior checkpoint |
| Season format changes (playoff added, team count changes) | Low | Medium | Season state machine derives from fixture data, not hardcoded rules |
| Transfer window not detected | Medium | Low | Calendar-based heuristic (Jan/Jul) as trigger; daily roster check as backup |
| Network partition (peers can't reach each other) | Medium | Low | Each peer operates independently; P2P is additive, not required |

### 11.2 Graceful Degradation Hierarchy

When components fail, the system degrades gracefully rather than crashing:

```
Full capability (all sources + all peers + model up to date)
    │
    ├─ Source A down → use Sources B + C (reduced stat coverage)
    │
    ├─ All sources down → serve from cached DataStore (up to 7-day TTL)
    │
    ├─ P2P network down → single-node predictions (no ensemble, no reputation)
    │
    ├─ Model stale → retrain from cached data; if impossible, serve with
    │                 confidence penalty (multiply all confidences by 0.5)
    │
    ├─ Fixture index stale → can't resolve "next match"; respond with
    │                         "Fixtür verisi güncel değil" (fixture data not current)
    │
    └─ Complete data loss → retrain from scratch on next source availability;
                            serve "Sistem başlatılıyor" until ready
```

### 11.3 Autonomous vs Manual — Side by Side

| Scenario | Previous Report (Manual) | This Report (Autonomous P2P) |
|---|---|---|
| Season rollover | Edit `CURRENT_SEASON`, redeploy | Season state machine detects from fixture dates |
| Player transfer | Edit `_PLAYER_TEAMS`, redeploy | Daily roster scrape propagated via P2P `ROSTER_UPDATE` |
| Team promoted | Edit 5 files, redeploy | New team appears in scraped standings; auto-added to registry |
| Source breaks | Edit `selectors.json`, redeploy | Selector health monitor rotates to fallback; peers compensate |
| Model drifts | Notice manually, retrain, redeploy | Drift detector triggers automatic incremental retrain |
| New match week | Nothing (static demo data) | Elected indexer fetches fixtures; scraper peers fetch results |
| Node crashes | Restart manually | HEARTBEAT timeout → re-election; node recovers identity on restart |

---

*Report generated 2026-04-07. Implementation blueprint targets 6-phase rollout, one phase per week, with each phase independently testable and deployable.*
