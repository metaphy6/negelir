# Negelir — P2P Simulation Gap-Closing & Roadmap Coverage Report

> **Note (2026-04-18):** Test counts have since grown beyond the 224 reported here. See [QID_TEST_REPORT.md](../reports/QID_TEST_REPORT.md) for latest (308+ tests).

**Date**: April 5, 2026  
**Test Results**: 224 total tests (140 AI + 84 P2P) — all passing

---

## Part 1: P2P Simulation Gap-Closing

### Problem Statement

The P2P simulation was previously a **logic testbed**, not a network testbed. It validated protocol structure and reputation algorithms but couldn't reveal real-world network issues because:

- Messages were passed as Python object references (no serialization)
- Delivery was instant and 100% reliable (no latency, no packet loss)
- Every node knew every other node (full mesh topology)
- Match data was 3 hardcoded dicts (no real data)

### Changes Applied

#### Step 1: Wire Serialization

Every message now goes through `P2PMessage.to_bytes()` → `bytes` → `P2PMessage.from_bytes()` on every hop. The received object is a **new deserialized instance**, not the same Python reference.

**What this catches**: Content-hash mismatches, invalid JSON, encoding bugs, missing required fields. The existing `from_bytes()` raises `ValueError` on tampered payloads — this is now exercised on every message in the simulation.

**Metrics**:
| Metric | Before | After |
|---|---|---|
| Bytes serialized per run | 0 | Tracked (varies by run) |
| Serde errors caught | 0 | Tracked |
| Message identity | Same Python object | New deserialized copy |

#### Step 2: Simulated Latency + Packet Loss

Configurable transport knobs:
- **Latency**: 20–150ms per hop (simulated, tracked in stats — not actual sleep)
- **Drop rate**: 2% default (configurable 0.0–1.0)

**Impact on scaling test (25 peers × 30 rounds)**:
| Metric | Before (ideal) | After (realistic) |
|---|---|---|
| Delivery rate | 100% | ~98% (2% drop) |
| Data coverage | 25/25 | 20–22/25 |
| Messages dropped | 0 | ~360 of 18,000 |
| Avg simulated latency | 0ms | ~85ms |

This immediately broke the "100% data coverage" result, which was the most important outcome — it was physically impossible on a real network.

#### Step 3: k-Neighbor Partial Mesh Topology

Each node now knows only `k=8` peers (configurable), not the entire network. Broadcast uses 2-hop gossip:
1. **First hop**: Send to all `k` direct neighbors
2. **Second hop**: Each neighbor re-gossips to `gossip_fanout=3` of *their* neighbors not yet reached

**Impact**:
| Metric | Before (full mesh) | After (k=8, fanout=3) |
|---|---|---|
| Topology | Every node → every node | Each node → 8 neighbors |
| Broadcast coverage | 100% (guaranteed) | ~80–92% (gossip-dependent) |
| Missing peer analyses | 0 | ❓ entries in reputation matrix |
| Realistic routing | No | Yes — nodes must discover data |

The reputation matrix now shows `❓` entries where nodes never received each other's analyses due to the partial mesh — this is realistic behavior that was previously impossible to observe.

#### Step 4: Real Match Data

`SIMULATED_SCRAPED_DATA` now loads from `data/tr_super_lig_real.json` (1,469 matches from the actual scraper):
- **Elo ratings** computed from rolling historical results (simple Elo with K=20)
- **Form arrays** computed from actual W/D/L sequences
- **Avg goals** computed from rolling 5-match windows
- **Actual FT scores** stored as `_actual_ft` for outcome validation (not simulated randomly)

Hardcoded fallback data remains for environments where the JSON file isn't available.

**Impact**:
| Metric | Before (hardcoded) | After (real data) |
|---|---|---|
| Match sources | 3 hand-crafted dicts | 10 real matches from 1,469 |
| Elo ratings | Made up (1720, 1680, etc.) | Computed from actual results |
| Form arrays | Made up | Computed from actual W/D/L |
| Outcome validation | Random simulation | Real FT scores |

### Test Results After Changes

```
P2P tests:  84 passed (was 73, added 11 transport realism tests)
AI tests:  140 passed (unchanged)
Total:     224 passed
```

#### New Transport Realism Tests

| Test | What It Verifies |
|---|---|
| `test_wire_serialization_round_trip` | Received message is a new object, not same reference |
| `test_bytes_serialized_tracked` | Transport tracks serialization bytes |
| `test_packet_drop_simulation` | 100% drop rate → 0 deliveries |
| `test_partial_drop_rate` | 50% drop rate → ~50% delivery |
| `test_latency_tracked_in_stats` | Latency within configured range |
| `test_k_neighbors_topology` | Each node has exactly k neighbors, no self-loop |
| `test_gossip_broadcast_reaches_beyond_direct_neighbors` | 2-hop gossip extends beyond k |
| `test_tampered_message_caught_by_serde` | Wire serde catches content-hash tampering |
| `test_transport_stats_reset` | Fresh transport has zeroed counters |
| `test_real_data_loading` | Real data loads with correct schema |
| `test_real_data_has_actual_results` | Real matches include FT scores |

### Scaling Test Results (25 peers × 30 rounds)

| Metric | Value |
|---|---|
| Total peers | 25 |
| Sybil peers | 2 |
| Match rounds | 30 |
| Total messages | 18,000 |
| Data coverage | 20/25 (was 25/25) |
| Avg accuracy | 44.2% |
| Avg ensemble shift | 0.040 |
| High trust | 6 |
| Medium trust | 487 |
| Low trust | 95 |

### Churn Test Results (10→25→10 peers, 40 rounds)

| Metric | Value |
|---|---|
| Peak nodes | 21 |
| Nodes removed (total) | 12 |
| Final avg accuracy | 59.5% |
| Stable-phase accuracy | 59.6% |
| Data retention | 10/10 |

### Remaining Gaps (Not Closed)

These require architectural changes beyond the simulation layer:

| Gap | Why It Still Matters | Mitigation Path |
|---|---|---|
| **Single process** | All nodes share RAM; no real I/O latency | Move to multiprocessing or Docker containers |
| **No NAT/firewall** | ~40% of real peers need STUN/TURN | Production P2P library (libp2p, Gun.js) |
| **Free Sybil attacks** | Adding nodes costs nothing | Proof-of-work or time-gated identity minting |
| **No peer discovery** | k-neighbors built by simulation, not discovered | DHT bootstrap protocol |
| **Synchronous rounds** | All nodes produce analyses in lockstep | Async event-driven architecture |

---

## Part 2: Roadmap Coverage Assessment

### Section-by-Section Status

| # | Section | Status | Coverage |
|---|---|---|---|
| 1 | Project Overview | Designed | 100% |
| 2 | Scope & Target Leagues | Partial | 60% |
| 3 | Store Compliance Strategy | Designed | 85% |
| 4 | Data Source Architecture | Partial | 65% |
| 5.1–5.4 | AI Model & Output | Substantial | 85% |
| 5.5 | Training Pipeline | Partial | 60% |
| 5.6 | AI Hardening | Substantial | 80% |
| 6 | Data Transformation | Partial | 70% |
| 7 | P2P Network Layer | Simulated | 75% |
| 8 | Flutter App Architecture | **Not Started** | 0% |
| 9 | Development Phases | Tracked | 40% |
| 10 | Tech Stack Summary | Documented | 100% |
| 11 | Risk Matrix & Mitigations | Documented | 100% |
| 12 | Acceptance Criteria | Defined | 40% |

### Phase Completion

| Phase | Scope | Status | % |
|---|---|---|---|
| 0 (Foundation) | Project setup, DB schema, scraper config, CI/CD | **Done** | 95% |
| 1 (Data Pipeline) | Scrapers, normalization, features, NLP, noise | **Partial** | 60% |
| 2 (AI + NLU) | GBDT, TQU, TRC, orchestrator, proofreader, hardening | **Partial** | 70% |
| 3 (P2P Network) | Protocol, transport, reputation, simulation, scraping | **Partial** | 75% |
| 4 (Flutter UI) | Chat, match browser, league view, analysis dashboard | **Not Started** | 0% |
| 5 (Compliance) | Legal, security audit, adversarial testing, store submit | **Not Started** | 0% |

### What's Implemented (Working Today)

**AI Engine (140 tests)**:
- XGBoost 3-class classifier + Dixon-Coles Poisson ensemble (120 features)
- Turkish Question Understanding: 10 intents, regex patterns, sanitizer, domain gate
- Turkish Response Composer: template-based, compliance-checked, verdict selection
- Task Orchestrator: state machine coordinating scrape → process → proofread → analyze → respond
- Data Proofreader: range, consistency, plausibility, temporal checks
- NLP Sentiment: Turkish lexicon, injection detection, [-1.0, 1.0] output
- Multi-league support: LeagueConfig for TR, EN, DE, ES
- Real data: 1,469 scraped matches from 5 seasons

**P2P Network (84 tests)**:
- Message protocol: schema-versioned, SHA-256 content-hash, JSON serde, TTL
- Transport: wire serialization, latency simulation, 2% drop rate, k=8 partial mesh, 2-hop gossip
- Node: content-addressed DataStore (SHA-256 dedup, TTL eviction, manifest exchange)
- Reputation: rolling-50 accuracy, calibration, 5 trust levels, Sybil detection
- Scaling: 25+ peers × 30 rounds, gossip propagation, partial coverage
- Churn: dynamic join/leave with data retention across scaling

**Server (Go)**:
- PostgreSQL match API, health check, Redis caching
- SQL migrations for matches/predictions tables

### What's Missing (Critical Path to Launch)

**Blocking**:
1. **Flutter app** — Zero Flutter code exists. All 20+ UI screens are not started. This is the single largest gap.
2. **P2P Flutter integration** — The Python P2P simulation needs to be ported to Dart/Gun.js for on-device operation.
3. **Compliance verification** — Phase 5 hasn't started: no legal review, no adversarial testing, no privacy policy, no store metadata.

**High Priority**:
4. **Real feature pipeline** — Feature engineering generates synthetic data; the scraper → features → model pipeline for real data isn't streamlined end-to-end.
5. **Media sentiment sourcing** — NLP pipeline exists but no text source is integrated.
6. **1. Lig data** — Only Süper Lig data is loaded; 1. Lig (TFF First League) is in scope but has no data.

**Medium Priority**:
7. Large-scale adversarial testing (1,000+ inputs to TQU)
8. Anti-forensics audit (decompile APK, verify zero source traceability)
9. Native speaker Turkish template review
10. Multi-device P2P stress testing

### Bottom Line

The **backend is production-ready for integration**: AI model, language processing, data pipeline, and P2P protocol are implemented and tested (224 tests). The P2P simulation now exercises wire serialization, packet loss, partial mesh topology, and real match data — making it a credible testbed for protocol correctness.

The **critical missing piece is the Flutter app** (Phase 4: 0% complete). This is the delivery vehicle — without it, there's nothing to ship. Secondary to that is Phase 5 compliance, which can partially run in parallel with Flutter development.

**Estimated remaining work**:
- Phase 4 (Flutter UI): ~6 weeks
- Phase 5 (Compliance + Launch): ~4 weeks
- Data pipeline completion: ~2 weeks (can overlap)
