# Negelir P2P Network

## Overview

Peer-to-peer network simulation enabling Negelir nodes to securely share their analyses.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    Node A     │◄───►│    Node B     │◄───►│    Node C     │
│ AI + Reputation│    │ AI + Reputation│    │ AI + Reputation│
└──────────────┘     └──────────────┘     └──────────────┘
        ▲                    ▲                    ▲
        └────────────────────┴────────────────────┘
                    Simulated Transport
```

## Components

### Node (`node/peer.py`)
- `PeerNode`: Node with its own AI model, reputation table, and unique identity
- `PeerAnalysis`: Analysis results shared over P2P
- `PeerReputationEntry`: Outcome-validated reputation record
- Trust levels: `new`, `low`, `medium`, `high`, `leader`

### Protocol (`protocol/`)
- `P2PMessage`: Schema-versioned JSON messages
- `MessageType`: ANALYSIS, OUTCOME_VALIDATION, SCRAPE_DATA, PEER_DISCOVERY, PING, PONG
- Content hash verification (SHA-256)
- TTL: 7 days

### Transport (`protocol/transport.py`)
- `SimulatedTransport`: In-memory message routing (asyncio queues)
- Point-to-point and broadcast messaging

### Reputation (`reputation/tracker.py`)
- 50-element sliding window accuracy
- Calibration score
- Network-wide reputation summary
- Rich reputation matrix visualization

### Simulation (`simulation/runner.py`)
5-phase simulation:
1. **Local analysis**: Each node generates predictions with its own GBDT model
2. **Sharing**: Analyses broadcast to all nodes
3. **Ensemble**: Reputation-weighted ensemble computed
4. **Outcome**: Match result simulated
5. **Validation**: Reputation tables updated

## Running

```bash
# With Docker
make p2p-simulate

# Parameters (.env)
P2P_NODE_COUNT=5              # Number of nodes
P2P_SIMULATION_MATCHES=10     # Simulation match count
```

## Sybil Resistance

- Deliberate bias node test (last node +0.3 bias)
- Reputation-based weighting (low reputation = low impact)
- Sliding window enables fast detection of malicious nodes
