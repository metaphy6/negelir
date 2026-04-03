# P2P Network, Simulation, Proofreading & Consensus

Detailed technical documentation of how Negelir's decentralized AI nodes
collaborate, validate data, reach consensus, and build reputation.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Peer Nodes](#2-peer-nodes)
3. [Message Protocol](#3-message-protocol)
4. [Transport Layer](#4-transport-layer)
5. [Simulation Phases](#5-simulation-phases)
6. [Data Proofreading](#6-data-proofreading)
7. [Consensus Mechanism](#7-consensus-mechanism)
8. [Reputation System](#8-reputation-system)
9. [Sybil Resistance](#9-sybil-resistance)
10. [Turkish Q&A Through P2P](#10-turkish-qa-through-p2p)
11. [Configuration](#11-configuration)
12. [Log Interpretation](#12-log-interpretation)

---

## 1. Architecture Overview

```
                    ┌────────────────────────────────────┐
                    │     Simulated Transport Layer       │
                    │   (asyncio queues, in-memory bus)   │
                    └──────────┬──────────┬──────────────┘
                               │          │
        ┌──────────────────────┼──────────┼──────────────────────┐
        │                      │          │                      │
   ┌────▼────┐  ┌──────▼──────▼──┐  ┌────▼────┐  ┌──────────┐  │
   │ Node 1  │  │   Node 2       │  │ Node 3  │  │ Node 4   │  │
   │ (Lead)  │  │   (Normal)     │  │ (Normal)│  │ (Normal) │  │
   │         │  │                │  │         │  │          │  │
   │ ┌─────┐ │  │ ┌─────┐       │  │ ┌─────┐ │  │ ┌─────┐  │  │
   │ │GBDT │ │  │ │GBDT │       │  │ │GBDT │ │  │ │GBDT │  │  │
   │ │Model│ │  │ │Model│       │  │ │Model│ │  │ │Model│  │  │
   │ └─────┘ │  │ └─────┘       │  │ └─────┘ │  │ └─────┘  │  │
   │ ┌─────┐ │  │ ┌─────┐       │  │ ┌─────┐ │  │ ┌─────┐  │  │
   │ │Rep. │ │  │ │Rep. │       │  │ │Rep. │ │  │ │Rep. │  │  │
   │ │Table│ │  │ │Table│       │  │ │Table│ │  │ │Table│  │  │
   │ └─────┘ │  │ └─────┘       │  │ └─────┘ │  │ └─────┘  │  │
   └─────────┘  └───────────────┘  └─────────┘  └──────────┘  │
        │                                               ┌──────▼──┐
        │                                               │ Node 5  │
        │                                               │ (Sybil  │
        │                                               │  Test)  │
        │                                               │ +0.3    │
        │                                               │  bias   │
        │                                               └─────────┘
        └──────────────────────────────────────────────────────────┘
```

Each node is an **independent AI agent** with:
- Its own GBDT model (same architecture, slight random bias to simulate real-world variance)
- Its own local reputation table (each node scores every other node independently)
- A unique cryptographic identity (SHA-256 hash of node seed)

The last node is deliberately biased (+0.3 home_prob) to test Sybil resistance.

---

## 2. Peer Nodes

**File:** `p2p/node/peer.py`

### PeerNode

Each `PeerNode` instance represents one participant in the network.

```python
class PeerNode:
    node_id: str          # SHA-256 hash (16 chars), unique identity
    port: int             # Simulated port
    model_bias: float     # Random Gaussian(0, 0.05) — models aren't identical
    reputation_table: {}  # peer_id → PeerReputationEntry
    analyses: {}          # match_id → own PeerAnalysis
    peer_analyses: {}     # match_id → [PeerAnalysis from others]
```

### PeerAnalysis

The prediction object shared between nodes:

| Field | Type | Description |
|-------|------|-------------|
| `analysis_id` | str | SHA-256 hash of `node_id:match_id` |
| `node_id` | str | Producer identity |
| `match_id` | str | Target match hash |
| `home_win_prob` | float | P(home win), 0.05–0.90 |
| `draw_prob` | float | P(draw), 0.05–0.40 |
| `away_win_prob` | float | P(away win), derived |
| `confidence` | float | Model confidence, 0.30–0.95 |
| `content_hash` | str | SHA-256 of serialized JSON (integrity check) |

**Normalization:** All three probabilities always sum to 1.0.

### Local Inference

```
produce_analysis(match_id, base_home_prob):
    1. home_prob = base_home_prob + model_bias + Gaussian(0, 0.08)
    2. draw_prob = 0.25 + Gaussian(0, 0.05)
    3. away_prob = 1 - home - draw
    4. Normalize to sum=1
    5. confidence = |home - away| + 0.3 + Gaussian(0, 0.1)
    6. Return PeerAnalysis with content_hash
```

This deliberately injects noise so each node produces slightly different predictions,
simulating independent models trained on overlapping-but-not-identical data.

---

## 3. Message Protocol

**File:** `p2p/protocol/messages.py`

### Message Types

| Type | Purpose | Payload |
|------|---------|---------|
| `ANALYSIS` | Share a match prediction | PeerAnalysis dict |
| `OUTCOME_VALIDATION` | Share actual match result | match_id + result |
| `SCRAPE_DATA` | Share scraped match data | raw match dict |
| `PEER_DISCOVERY` | Announce presence | node_id + port |
| `PING` / `PONG` | Liveness check | timestamp |

### P2PMessage Structure

```json
{
    "schema_version": "2.0",
    "message_type": "analysis",
    "sender_id": "a1b2c3d4e5f6g7h8",
    "payload": { ... },
    "timestamp": 1712150400.0,
    "ttl_hours": 168,
    "content_hash": "sha256..."
}
```

**Integrity:** On deserialization, `content_hash` is recomputed and compared.
If it doesn't match, a `ValueError` is raised — tampered messages are rejected.

**Expiry:** Messages older than `ttl_hours` (default 7 days) are discarded.

---

## 4. Transport Layer

**File:** `p2p/protocol/transport.py`

### SimulatedTransport

In-memory message bus using `asyncio.Queue` per node.

```
SimulatedTransport
    ├── register_node(node_id) → creates inbox Queue
    ├── send(sender, target, msg) → direct delivery
    ├── broadcast(sender, msg) → deliver to all except sender
    └── get_pending(node_id) → drain inbox (non-blocking)
```

**Production upgrade path:** Replace `asyncio.Queue` with TCP sockets or
libp2p. The `PeerNode` API stays the same — only transport changes.

---

## 5. Simulation Phases

**File:** `p2p/simulation/runner.py`

The simulation runs 7 phases sequentially:

### Phase A — Network Setup

```
For i in 0..NODE_COUNT:
    node_id = SHA256("node_{i}_negelir")[:16]
    Create PeerNode(node_id, port=9000+i)
    Register on transport
Last node gets model_bias = +0.3 (Sybil test)
```

### Phase B — Simulated Web Scraping

Simulates fetching from 3 Turkish football data sources:
- Source A (Statistics): 12 pages, ~180ms rate limit
- Source B (Live Scores): 8 pages, ~220ms rate limit
- Source C (Archive): 15 pages, ~150ms rate limit

Per page: 30–80 KB HTML fetched, 2–4 matches parsed, HTML discarded from RAM.

Output: Performance summary table (pages, KB, time, speed per source).

### Phase C — Data Processing & Validation (Proofreading)

For each of 3 scraped matches:

1. **Range checks** — possession 0–100, shots 0–40
2. **Consistency check** — home + away possession ≈ 100 (±5 tolerance)
3. **Plausibility check** — Elo in range 800–2200
4. **Feature extraction** — 87 dimensions per match

Matches passing all checks proceed. Failed matches are **quarantined** (not used for analysis).
A batch fails if >30% of matches are quarantined.

Output: Validation summary table (match, status, features, Elo, form).

### Phase D — P2P Match Analysis Rounds

For each match (3 scraped + 7 extra synthetic for reputation building):

```
1. Each node produces local GBDT analysis
2. Each node broadcasts its PeerAnalysis via transport
3. Each node receives and stores peer analyses
4. Each node computes reputation-weighted ensemble
5. Match result is simulated from true probabilities
6. Each node validates outcome and updates reputation tables
```

### Phase E — Turkish Q&A Pipeline

21 Turkish questions (7 per match) routed through the P2P network:

```
Question → TQU (intent classification)
         → Retrieve scraped match data
         → Get lead node's ensemble prediction
         → TRC (compose Turkish answer)
         → Display rich panel
```

### Phase F — Reputation Matrix

Rich table showing how each node views every other node:
accuracy, trust level, calibration score.

### Phase G — Summary

Network-wide stats: node count, average accuracy, trust level distribution.

---

## 6. Data Proofreading

**File:** `ai/proofreader/validator.py`

The proofreader sits between scraping and AI inference. It ensures no garbage
data reaches the GBDT model.

### Validation Pipeline

```
Raw scraped data
    │
    ├─► Range Checks
    │   goals: 0–15, possession: 0–100, shots: 0–40
    │   corners: 0–25, fouls: 0–40, yellows: 0–10, reds: 0–5
    │
    ├─► Consistency Checks
    │   home_possession + away_possession ≈ 100%
    │   shots_on ≤ total_shots
    │
    ├─► Historical Plausibility
    │   Elo: 800–2200
    │   Form values within expected range
    │
    └─► Result
        ├── ✅ Valid → proceed to feature engineering
        ├── ⚠️ Warnings → proceed with caution flags
        └── ❌ Errors → quarantined (excluded from analysis)
```

### Batch Validation

When processing multiple matches:
- Each match validated independently
- If >30% quarantined → entire batch flagged as invalid
- Quarantined matches are logged but never used for predictions

### Integration with P2P

In the P2P simulation (Phase C), proofreading validates each scraped match
**before** any node processes it. This means:

1. All nodes work from the **same validated dataset** — bad data is removed
   upstream, not per-node.
2. Validation warnings are logged centrally so operators can see data quality
   trends.
3. If a match is quarantined, no node receives it — no wasted computation or
   corrupted predictions.

---

## 7. Consensus Mechanism

Negelir uses **reputation-weighted ensemble** (not voting) for consensus.

### Why Not Majority Voting?

In match prediction, probabilities matter. A node saying "60% home win" and
another saying "52% home win" agree on direction but disagree on magnitude.
Majority voting discards this nuance. Weighted averaging preserves it.

### Ensemble Algorithm

```
For a given match_id on a specific node:

1. local_weight = 0.50 (always trust own model at 50%)

2. For each peer analysis:
   a. Look up peer's trust_level in local reputation table
   b. Map to weight:
      new:    0.1
      low:    0.2
      medium: 0.5
      high:   1.0
      leader: 1.5
   c. Unknown peers get 0.1

3. Normalize peer weights so sum = 0.50 (the other half)

4. Weighted average:
   home_prob = 0.50 × local.home + Σ(w_i × peer_i.home)
   draw_prob = 0.50 × local.draw + Σ(w_i × peer_i.draw)
   away_prob = 0.50 × local.away + Σ(w_i × peer_i.away)

5. Normalize to sum = 1.0

6. Confidence = 0.7 × local_confidence + 0.3 × agreement_factor
   where agreement_factor = 1 - |ensemble_home - local_home|
```

### Key Properties

- **Self-trust floor:** Every node trusts itself at 50% — no single peer or
  coalition can override a node's own model.
- **Proportional influence:** Higher-reputation peers have more influence.
  A "leader" node contributes 15× more than an unknown peer.
- **Convergence:** Over time, honest nodes converge because their ensemble
  predictions become more similar, reinforcing mutual reputation.
- **Divergence detection:** If ensemble home_prob differs greatly from
  local home_prob, confidence drops — the node "knows" there's disagreement.

### Example

```
Node A (local):   H=0.60  D=0.25  A=0.15  (weight: 0.50)
Node B (high):    H=0.55  D=0.28  A=0.17  (raw weight: 1.0)
Node C (medium):  H=0.58  D=0.26  A=0.16  (raw weight: 0.5)
Node D (new):     H=0.70  D=0.20  A=0.10  (raw weight: 0.1)
Node E (Sybil):   H=0.85  D=0.10  A=0.05  (raw weight: 0.2)

Normalized peer weights (sum to 0.50):
  B: 1.0/1.8 × 0.50 = 0.278
  C: 0.5/1.8 × 0.50 = 0.139
  D: 0.1/1.8 × 0.50 = 0.028
  E: 0.2/1.8 × 0.50 = 0.056

Ensemble from A's perspective:
  home = 0.50×0.60 + 0.278×0.55 + 0.139×0.58 + 0.028×0.70 + 0.056×0.85
       = 0.300 + 0.153 + 0.081 + 0.020 + 0.048
       = 0.601

Note: Despite Node E (Sybil) claiming H=0.85, the ensemble barely moves
because E's low reputation weight (0.056) limits its influence.
```

---

## 8. Reputation System

**Files:** `p2p/node/peer.py` (PeerReputationEntry), `p2p/reputation/tracker.py`

### How Reputation Works

Each node maintains its own **local** reputation table. There is no global
reputation authority — this is deliberate for decentralization.

### Per-Peer Entry

| Field | Description |
|-------|-------------|
| `accuracy_rolling_50` | Correct predictions / total (rolling 50 window) |
| `calibration_score` | How well confidence maps to outcomes (1.0 = perfect) |
| `total_validated` | Number of validated predictions |
| `trust_level` | Derived tier (see below) |
| `predictions` | Rolling window of (prob, was_correct) tuples |

### Trust Level Criteria

| Level | Conditions |
|-------|-----------|
| `new` | < 10 validated predictions |
| `low` | accuracy < 0.40 OR calibration < 0.30 |
| `medium` | Default for nodes with 10+ validations |
| `high` | accuracy > 0.55 AND calibration > 0.60 |
| `leader` | accuracy > 0.65 AND calibration > 0.65 AND 20+ validated |

### Outcome Validation Flow

After each match result is known:

```
For each peer analysis we received for this match:
    1. Determine what the peer predicted (argmax of H/D/A)
    2. Compare to actual result
    3. Get the probability the peer assigned to the actual outcome
    4. Call update_from_outcome(prob_for_actual, was_correct)
    5. Recalculate rolling accuracy, calibration, trust level
```

### Calibration Score

Measures how well a node's stated confidence matches reality:

```
For each prediction:
    error = |stated_probability - (1.0 if correct else 0.0)|

calibration_score = 1.0 - mean(errors)
```

A perfectly calibrated node that says "70% home" would have home win
70% of the time. Under-confident or over-confident nodes score lower.

---

## 9. Sybil Resistance

### What Is a Sybil Attack?

A malicious actor creates many fake nodes to outvote honest nodes.

### How Negelir Resists It

1. **Reputation-weighted, not vote-counted:** Creating 100 nodes doesn't help
   if they all have `new` or `low` trust (weight = 0.1 or 0.2).

2. **Self-trust floor (50%):** Even if all peers are Sybil, a node still
   trusts itself at 50%.

3. **Outcome-based validation:** You can't fake match results. After each
   match, every node independently checks who was right. Biased Sybil nodes
   will have lower accuracy and quickly drop to `low` trust.

4. **Deliberate Sybil test node:** The simulation injects Node 5 with
   `model_bias = +0.3` (always predicts home win too high). Over 10+ matches,
   this node's reputation drops to `low` and its influence on ensemble
   predictions becomes negligible (weight 0.2 vs. honest nodes at 0.5–1.5).

5. **Sliding window (50):** Recent accuracy matters more than historical.
   A Sybil node that was honest initially but turns malicious is detected
   within ~10 matches.

### Example: Sybil Node Degradation

```
Match  1: Sybil predicts H=0.90 (actual: H) → correct (lucky)
Match  2: Sybil predicts H=0.85 (actual: D) → wrong
Match  3: Sybil predicts H=0.88 (actual: A) → wrong
Match  5: Sybil predicts H=0.82 (actual: H) → correct (lucky again)
...
Match 10: accuracy = 0.30, trust = "low"
Match 20: accuracy = 0.25, trust = "low", weight = 0.2

Meanwhile honest nodes: accuracy ~0.55, trust = "high", weight = 1.0
Honest ensemble barely notices the Sybil.
```

---

## 10. Turkish Q&A Through P2P

### Flow

```
User asks: "Galatasaray bu maçı kazanır mı?"
    │
    ▼
TQU (intent classification)
    intent = "match_winner"
    confidence = 0.75
    │
    ▼
Retrieve match data from Phase B/C
    home_elo = 1720, away_elo = 1680
    home_form = [W, W, D, W, L]
    h2h = 3-1 for home
    │
    ▼
Lead node's ensemble prediction
    H=0.601  D=0.258  A=0.141
    (reputation-weighted across 5 nodes)
    │
    ▼
TRC (Turkish Response Composer)
    "Büyük ihtimalle evet. Galatasaray son 5 maçta 3 galibiyet
     almış, Elo puanı 1720. Kafa kafaya 3-1 Galatasaray lehine.
     Ev sahibi kazanma olasılığı: %60. Güven: %72."
```

### Intent → Answer Mapping

| Intent | Answer Template Factors |
|--------|------------------------|
| `match_winner` | home/away probs, form, Elo, h2h record |
| `draw` | draw_prob, Elo gap, h2h draws, power balance |
| `over_under` | avg goals scored/conceded, h2h avg goals |
| `goal_range` | goal averages, expected low-high range |
| `both_teams_score` | avg scored per team, threshold 0.8+ |
| `clean_sheet` | avg conceded, historical clean sheet rate |
| `half_time` | (generic analysis) |
| `form_query` | form array, Elo, sentiment scores |
| `head_to_head` | h2h record, avg goals, historical wins |

---

## 11. Configuration

All parameters are configurable via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `P2P_NODE_COUNT` | 5 | Number of peer nodes in simulation |
| `P2P_BASE_PORT` | 9000 | Starting port for simulated nodes |
| `P2P_SIMULATION_MATCHES` | 10 | Extra synthetic matches for reputation building |
| `SIMULATION_INTERVAL` | 30 | Seconds between continuous simulation cycles |
| `AI_LOG_LEVEL` | DEBUG | Log verbosity (DEBUG, INFO, WARNING) |

### Running

```bash
# Single run
make p2p
make p2p-simulate

# Continuous (Ctrl+C to stop)
make p2p-continuous

# Custom config
P2P_NODE_COUNT=10 P2P_SIMULATION_MATCHES=20 make p2p
```

---

## 12. Log Interpretation

### Phase A (Network Setup)
```
📡 Creating 5 nodes...
🖥️  Node 1: a1b2c3d4 (port: 9000)     ← honest node
⚠️  Node 5: e5f6g7h8: deliberate bias  ← Sybil test node
```

### Phase B (Web Scraping)
```
🕷️  Web scraping starting (3 sources, rate-limited)...
📄 Page 3/12: 45.2 KB → 4 matches parsed (HTML discarded ✓)
🏁 Total: 35 pages, 1920 KB, 850ms
```

### Phase C (Proofreading)
```
✅ Possession consistent: 100%          ← passed
⚠️  home_elo: 2500 (suspicious)        ← plausibility warning
🔒 Match quarantined                    ← excluded from analysis
```

### Phase D (P2P Rounds)
```
⚽ Match 1: Galatasaray vs Fenerbahçe
🧠 Analysis: a1b2c3d4 → H=0.58 D=0.26 A=0.16 (confidence: 0.72)
📥 Analysis received from e5f6g7h8     ← peer sharing
🔀 Ensemble prediction (4 nodes): H=0.60 D=0.26 A=0.14
🏆 Result: Galatasaray won
✅ Own prediction: H vs actual: H       ← correct
❌ Own prediction: H vs actual: D       ← wrong
📊 e5f6g7h8 reputation: accuracy=0.30, trust=low  ← Sybil degrading
```

### Phase E (Turkish Q&A)
```
❓ Q1: "Galatasaray bu maçı kazanır mı?"
🧠 TQU → intent=match_winner, confidence=0.75
🤖 TRC response composed (180 chars)
```

### Phase G (Summary)
```
📡 Node count: 5
📈 Average accuracy: 52.3%
⭐ Leader: 1  🟢 High: 3  🟡 Medium: 0  🔴 Low: 1  🆕 New: 0
```

The `🔴 Low: 1` is the Sybil test node — the system correctly identified it.
