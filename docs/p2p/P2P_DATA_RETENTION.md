# P2P Data Retention & Network Resilience

> How the Negelir P2P network retains scraped and processed data to prevent redundant scraping, and how it handles dynamic peer scaling.

---

## Table of Contents

1. [Overview](#overview)
2. [Content-Addressed Data Store](#content-addressed-data-store)
3. [Data Flow: Scrape → Store → Propagate](#data-flow)
4. [Deduplication Mechanism](#deduplication-mechanism)
5. [Manifest Exchange Protocol](#manifest-exchange-protocol)
6. [Data Survival During Churn](#data-survival-during-churn)
7. [Dynamic Peer Scaling](#dynamic-peer-scaling)
8. [Security Considerations](#security-considerations)
9. [Test Results](#test-results)
10. [Architecture Diagram](#architecture-diagram)

---

## Overview

The Negelir P2P network ensures that **scraped data is shared across all peers** so that only one node needs to scrape a given piece of data. This is achieved through:

- A **content-addressed `DataStore`** on each peer node
- **`SCRAPE_DATA` message broadcasts** via the P2P transport layer
- **SHA-256 hash-based deduplication** that prevents the same data from being stored or scraped twice
- **Manifest exchange** that lets joining peers identify and request only missing data

---

## Content-Addressed Data Store

Each `PeerNode` has a `DataStore` instance (`node.data_store`). The store is a local key-value map keyed by the **SHA-256 content hash** of each record.

### `ScrapedRecord` Structure

```python
@dataclass
class ScrapedRecord:
    data_hash: str          # SHA-256 of canonical (data_type + payload), truncated to 32 hex chars
    source_node_id: str     # ID of the node that originally scraped this data
    data_type: str          # "match", "team_stats", "odds", "referee", etc.
    payload: dict           # The actual scraped data
    timestamp: float        # Unix timestamp when the record was created
    ttl_hours: int          # Time-to-live (default: 168 hours = 7 days)
```

### Hash Computation

```python
canonical = json.dumps({"type": data_type, "payload": payload}, sort_keys=True)
data_hash = sha256(canonical.encode()).hexdigest()[:32]
```

The hash is computed from a **deterministic JSON serialization** (`sort_keys=True`) of the data type and payload, ensuring that identical data always produces the same hash regardless of which node scraped it.

---

## Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Node A     │     │   Node B     │     │   Node C     │
│  (scraper)   │     │              │     │              │
│              │     │              │     │              │
│ 1. Scrape    │     │              │     │              │
│    data      │     │              │     │              │
│    ↓         │     │              │     │              │
│ 2. Compute   │     │              │     │              │
│    hash      │     │              │     │              │
│    ↓         │     │              │     │              │
│ 3. Check     │     │              │     │              │
│    DataStore │     │              │     │              │
│    (new? ✓)  │     │              │     │              │
│    ↓         │     │              │     │              │
│ 4. Store     │     │              │     │              │
│    locally   │     │              │     │              │
│    ↓         │     │              │     │              │
│ 5. Broadcast ├────►│ 6. Receive   │     │              │
│    SCRAPE_   │     │    msg       │     │              │
│    DATA      ├────►│    ↓         ├────►│ 6. Receive   │
│              │     │ 7. Verify    │     │    msg       │
│              │     │    hash      │     │    ↓         │
│              │     │    ↓         │     │ 7. Verify    │
│              │     │ 8. Store     │     │    hash      │
│              │     │    locally   │     │    ↓         │
│              │     │              │     │ 8. Store     │
│              │     │              │     │    locally   │
└──────────────┘     └──────────────┘     └──────────────┘
```

### Step-by-Step

1. **Node A scrapes** data from an external source (e.g., openfootball, football-data.co.uk)
2. **Computes SHA-256 hash** of the canonical `{type, payload}` JSON
3. **Checks local DataStore** — if hash exists, the scrape is skipped (`needs_scrape()` returns `False`)
4. **Stores the record** in its local DataStore
5. **Broadcasts a `SCRAPE_DATA` message** to all connected peers via the transport layer
6. **Peer nodes receive** the `SCRAPE_DATA` message
7. **Peers verify** the hash integrity (recompute hash from payload and compare)
8. **Peers store** the record in their own DataStore (if new; duplicates are rejected)

### SCRAPE_DATA Message Format

```json
{
  "schema_version": "2.0",
  "message_type": "scrape_data",
  "sender_id": "a1b2c3d4",
  "payload": {
    "data_hash": "4f8b2a...",
    "data_type": "match",
    "payload": { "home_team": "Galatasaray", "away_team": "Fenerbahçe", ... },
    "source_node_id": "a1b2c3d4"
  },
  "timestamp": 1748983200.0,
  "ttl_hours": 168,
  "content_hash": "..."
}
```

---

## Deduplication Mechanism

Deduplication occurs at **three levels**:

### 1. Scrape Prevention (Pre-Scrape Check)

Before any node initiates a scrape, it checks:

```python
if node.needs_scrape("match", payload):
    # Actually scrape from external source
    record = node.ingest_scraped_data("match", payload)
else:
    # Skip — we already have this data
    pass
```

### 2. Local Insert Dedup

When `DataStore.insert()` is called, it checks `_seen_hashes`:

```python
def insert(self, data_type, payload, source_node_id=None):
    h = self.compute_hash(payload, data_type)
    if h in self._seen_hashes:
        return None  # duplicate — no-op
    # ... store and return the new record
```

### 3. Peer Merge Dedup

When receiving data from a peer via `merge_record()`:

```python
def merge_record(self, record):
    if record.data_hash in self._seen_hashes:
        return False  # already have it
    # Verify hash integrity
    expected = self.compute_hash(record.payload, record.data_type)
    if expected != record.data_hash:
        return False  # tampered — reject
    if record.is_expired():
        return False  # expired — reject
    # Store
    self._records[record.data_hash] = record
    return True
```

---

## Manifest Exchange Protocol

When a new peer joins the network, it doesn't need to re-scrape everything. Instead:

1. **New node requests manifests** from existing peers (list of content hashes)
2. **Computes the diff** — which hashes it's missing
3. **Requests only the missing records** from peers

```python
# On the new node:
peer_manifest = existing_node.get_data_manifest()  # List of hashes
missing = new_node.request_missing_data(peer_manifest)  # Hashes I don't have

# Fetch only missing records
for hash in missing:
    record = existing_node.data_store.get(hash)
    new_node.receive_scraped_data(record)
```

This is bandwidth-efficient: manifests are just lists of 32-character hex strings, and only missing data is transferred.

---

## Data Survival During Churn

### Peer Departure

When a peer leaves the network:
- Its data remains in the `DataStore` instances of **all other peers** that received it
- No data is lost unless **all** peers holding that data leave simultaneously
- The `_removed_nodes` list tracks departed peers for audit purposes

### Peer Arrival

When a new peer joins:
- `_sync_data_to_node()` is called automatically
- A random existing peer donates its full DataStore to the newcomer
- The new node's `merge_record()` only accepts records it doesn't already have

### Churn Test Results (10→25→10 peers over 40 rounds)

| Phase | Rounds | Nodes | Data Coverage |
|-------|--------|-------|---------------|
| Ramp Up | 1-10 | 10→21 | 100% always |
| Peak + Churn | 11-20 | ~18-21 | 100% always |
| Ramp Down | 21-30 | 21→10 | 100% always |
| Stable Recovery | 31-40 | 10 | 100% always |

**Key finding:** Data retention is 100% across all churn phases — no data loss occurred even when 12 nodes were removed.

---

## Dynamic Peer Scaling

### Adding Peers at Runtime

```python
sim = P2PSimulation()
sim.node_count = 5
sim._create_nodes()

# Later, add more peers:
new_node = sim.add_node()
# Data is automatically synced from existing peers
```

### Removing Peers at Runtime

```python
removed = sim.remove_node()  # Removes a random non-lead node
# Or remove a specific node:
sim.remove_node(specific_node)
```

### CLI Usage

```bash
# Standard simulation (uses P2P_NODE_COUNT env var, default 5)
python -m simulation.runner

# Scaling test with 25 peers
python -m simulation.runner --scale-test --nodes=25

# Churn test (10→25→10 with dynamic join/leave)
python -m simulation.runner --churn-test

# Docker
P2P_NODE_COUNT=25 docker compose up p2p
```

---

## Security Considerations

### Hash Integrity Verification

Every `merge_record()` recomputes the SHA-256 hash from the payload and compares it to the claimed `data_hash`. Tampered records are **silently rejected**.

### TTL Expiry

Records have a default TTL of 168 hours (7 days). Expired records are:
- Rejected on merge (`merge_record()` checks `is_expired()`)
- Evictable via `data_store.evict_expired()`

### Sybil Resistance

Malicious nodes cannot flood the network with duplicate data because:
- Content-addressed hashing means the same data always maps to the same key
- Duplicate inserts are no-ops
- The reputation system independently down-weights inaccurate peers

---

## Test Results

### Scaling Test: 25 Peers × 30 Rounds

| Metric | Value |
|--------|-------|
| Total peers | 25 |
| Sybil peers | 2 |
| Total P2P messages | 18,000 |
| Messages/round | 600 |
| Avg accuracy | 42.5% |
| Data coverage | 25/25 (100%) |
| Medium trust peers | 408 |

### Scaling Test: 50 Peers × 10 Rounds

Successfully completed with 0 crashes, all ensembles valid (probabilities sum to 1.0).

### Churn Test: 10→25→10

| Metric | Value |
|--------|-------|
| Peak nodes | 21 |
| Nodes removed | 12 |
| Final avg accuracy | 58.5% |
| Stable-phase accuracy | 58.4% |
| Data retention | 10/10 (100%) |

### Unit Test Coverage (73 tests)

- 12 DataStore & retention tests
- 5 peer data retention integration tests
- 3 transport unregister tests
- 6 scaling tests (20, 25, 30, 50 peers)
- 5 dynamic churn tests (join, leave, simultaneous, data survival)
- 42 existing protocol/node/reputation/consensus tests

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     NEGELIR P2P NETWORK                         │
│                                                                 │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │  Node 1   │  │  Node 2   │  │  Node 3   │  │  Node N   │   │
│  │           │  │           │  │           │  │           │   │
│  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │   │
│  │ │DataSt.│ │  │ │DataSt.│ │  │ │DataSt.│ │  │ │DataSt.│ │   │
│  │ │ h→rec │ │  │ │ h→rec │ │  │ │ h→rec │ │  │ │ h→rec │ │   │
│  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │   │
│  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │   │
│  │ │AI Mod.│ │  │ │AI Mod.│ │  │ │AI Mod.│ │  │ │AI Mod.│ │   │
│  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │   │
│  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │  │ ┌───────┐ │   │
│  │ │Rep.Tbl│ │  │ │Rep.Tbl│ │  │ │Rep.Tbl│ │  │ │Rep.Tbl│ │   │
│  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │  │ └───────┘ │   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘   │
│        │               │               │               │        │
│        └───────────────┴───────┬───────┴───────────────┘        │
│                                │                                 │
│                    ┌───────────┴───────────┐                    │
│                    │  SimulatedTransport   │                    │
│                    │  (message bus)        │                    │
│                    │                       │                    │
│                    │  ANALYSIS       ───►  │                    │
│                    │  SCRAPE_DATA    ───►  │                    │
│                    │  OUTCOME_VALID. ───►  │                    │
│                    │  PEER_DISCOVERY ───►  │                    │
│                    └───────────────────────┘                    │
│                                                                 │
│  Dynamic Scaling:                                               │
│    add_node()  → register + sync data from existing peers       │
│    remove_node() → unregister (data persists on other peers)    │
└─────────────────────────────────────────────────────────────────┘
```
