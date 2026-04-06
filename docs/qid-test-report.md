# Negelir — QID (Query Intent Distribution) Test Report

**Date**: April 6, 2026  
**Model Version**: 0.3.0  
**Test Results**: 308 total tests (212 AI + 96 P2P) — all passing  
**Environment**: Docker Compose (Python 3.11, Go 1.23, PostgreSQL 16, Redis 7)

---

## 1. Feature Summary

The QID system treats *what humans choose to ask* as a predictive signal. When many
users ask about over/under before a match, that demand-side pattern itself carries
information — independent of any model's answer.

### Components Added

| Component | File | Purpose |
|---|---|---|
| QID Collector | `ai/qid/collector.py` | Thread-safe per-match query intent recording, distribution computation, broadcast/merge |
| Feature Expansion | `ai/model/features.py` | 10 new `qid_*` feature columns (N_FEATURES 120 → 130) |
| Pipeline Hook | `ai/pipeline/runner.py` | Records intents after TQU classification, injects QID features before GBDT inference |
| P2P Message Type | `p2p/protocol/messages.py` | New `QUERY_INTENT` message type for intent broadcasts |
| PeerNode QID | `p2p/node/peer.py` | `record_query_intent()`, `receive_query_intents()`, `get_query_intent_distribution()` |
| Simulation Integration | `p2p/simulation/runner.py` | QID recording in Phase E, broadcast/merge step, distribution logging |

### Data Flow

```
User question
  → TQU classify (intent_id, confidence)
  → QID collector.record(match_id, intent, confidence)
  → PeerNode broadcasts QUERY_INTENT payload to neighbors
  → Peers merge incoming query intents
  → collector.get_features(match_id) → 10-float vector
  → Injected into XGBoost feature vector (columns 120–129)
  → GBDT inference
```

### New Feature Columns (v0.3)

| Index | Column | Description |
|---|---|---|
| 120 | `qid_match_winner` | Share of queries about match winner |
| 121 | `qid_draw` | Share of queries about draw |
| 122 | `qid_over_under` | Share of queries about over/under goals |
| 123 | `qid_goal_range` | Share of queries about goal range |
| 124 | `qid_both_teams_score` | Share of queries about BTTS |
| 125 | `qid_clean_sheet` | Share of queries about clean sheets |
| 126 | `qid_half_time` | Share of queries about half-time |
| 127 | `qid_form_query` | Share of queries about team form |
| 128 | `qid_head_to_head` | Share of queries about H2H |
| 129 | `qid_score_predict` | Share of queries about exact score |

---

## 2. Test Execution

All tests were executed via `make test` (Docker Compose) with freshly rebuilt images.

### 2.1 AI Module — `make test-ai`

**Command**: `docker compose run --rm ai python -m pytest tests/ -v`  
**Result**: **212 passed** in 50.97s

| Test Class | Tests | Status |
|---|---|---|
| TestSanitizer | 7 | ✅ All pass |
| TestClassifier | 7 | ✅ All pass |
| TestPoissonHelpers | 12 | ✅ All pass |
| TestFeatureSpec | 3 | ✅ All pass |
| TestScorePrediction | 7 | ✅ All pass |
| TestBettingMarkets | 13 | ✅ All pass |
| TestCardEstimation | 6 | ✅ All pass |
| TestExtendedClassification | 5 | ✅ All pass |
| TestNormalizerAsciify | 3 | ✅ All pass |
| TestNormalizerDedup | 4 | ✅ All pass |
| TestNormalizerStemming | 5 | ✅ All pass |
| TestNormalizerFuzzyTeam | 6 | ✅ All pass |
| TestNormalizerClassifierIntegration | 8 | ✅ All pass |
| TestProofreader | 8 | ✅ All pass |
| TestHistoricalScenarios | 8 | ✅ All pass |
| TestBulkClassification | 5 | ✅ All pass |
| TestEntityExtraction | 8 | ✅ All pass |
| TestConstantsIntegrity | 5 | ✅ All pass |
| TestLeagueConfig | 7 | ✅ All pass |
| TestColloquialPatterns | 15 | ✅ All pass |
| TestAbbreviationResolution | 11 | ✅ All pass |
| TestScorePredictIntent | 7 | ✅ All pass |
| TestEntityExtensions | 6 | ✅ All pass |
| TestEloVenueXg | 4 | ✅ All pass |
| TestScoreBrackets | 4 | ✅ All pass |
| **TestQIDCollector** | **13** | ✅ All pass |
| **TestMatchQueryProfile** | **3** | ✅ All pass |
| **TestQIDFeatureColumnsExpansion** | **4** | ✅ All pass |

#### New QID Tests (20 total)

| Test | Validates |
|---|---|
| `test_record_and_retrieve` | Basic record + volume tracking |
| `test_unknown_intent_ignored` | Unknown intents silently dropped |
| `test_features_uniform_below_min_volume` | Returns uniform 0.1 vector when < 5 queries |
| `test_features_reflect_distribution` | High-volume intent gets proportionally higher feature value |
| `test_feature_vector_length_matches_buckets` | Always returns exactly 10 floats |
| `test_broadcast_and_merge` | Full round-trip: record → payload → merge on second collector |
| `test_broadcast_empty_match` | Returns `None` for matches with no data |
| `test_merge_empty_payload` | Handles empty/malformed payloads gracefully |
| `test_evict_match` | Match data cleanup works |
| `test_summary` | Summary dict structure correct |
| `test_max_records_cap` | Per-match record cap enforced (prevents memory blowup) |
| `test_record_batch` | Batch merge filters invalid intents |
| `test_all_match_ids` | Match ID listing correct |
| `test_empty_profile_distribution` | Empty profile returns all-zero distribution |
| `test_weighted_distribution` | Confidence-weighted distribution weights high-confidence queries more |
| `test_volume_property` | Volume property tracks record count |
| `test_feature_columns_count_130` | N_FEATURES = 130, FEATURE_COLUMNS has 130 entries |
| `test_qid_columns_present` | All 10 `qid_*` columns exist |
| `test_synthetic_dataset_shape` | Synthetic dataset generates (n, 130) DataFrame |
| `test_qid_synthetic_values_in_range` | QID synthetic values in [0, 0.5] (Dirichlet-like) |

### 2.2 P2P Module — `make test-p2p`

**Command**: `docker compose run --rm p2p python -m pytest tests/ -v`  
**Result**: **96 passed** in 50.55s

| Test Class | Tests | Status |
|---|---|---|
| TestP2PMessage | 6 | ✅ All pass |
| TestReputation | 8 | ✅ All pass |
| TestPeerNode | 8 | ✅ All pass |
| TestSimulation | 8 | ✅ All pass |
| TestDataRetention | 8 | ✅ All pass |
| TestAnalysisIntegration | 4 | ✅ All pass |
| TestDynamicChurn | 5 | ✅ All pass |
| TestTransportRealism | 11 | ✅ All pass |
| **TestPeerNodeQID** | **8** | ✅ All pass |
| **TestQueryIntentMessageType** | **2** | ✅ All pass |
| **TestScorePredictIntentRule** | **2** | ✅ All pass |

#### New P2P QID Tests (12 total)

| Test | Validates |
|---|---|
| `test_record_query_intent` | PeerNode stores intent records per match |
| `test_get_query_intent_payload` | Payload serialisation structure correct |
| `test_get_payload_returns_none_for_empty` | No payload for unknown matches |
| `test_receive_query_intents_from_peer` | Cross-node intent merge works |
| `test_receive_own_intents_ignored` | Own node's intents not double-counted on receive |
| `test_query_intent_distribution` | Confidence-weighted normalised distribution correct |
| `test_empty_distribution` | Zero distribution for unknown matches |
| `test_multi_node_aggregation` | 3-node aggregation: each records different intent, lead node sees all |
| `test_query_intent_enum_exists` | `MessageType.QUERY_INTENT` enum value = `"query_intent"` |
| `test_query_intent_message_serialises` | QUERY_INTENT messages survive `to_bytes()` → `from_bytes()` round-trip |
| `test_score_predict_classified` | Inline P2P classifier recognises "Skor tahmini ne?" |
| `test_kac_kac_classified` | Inline P2P classifier recognises "Maç kaç kaç biter?" |

---

## 3. End-to-End Validation

### 3.1 AI Demo Pipeline — `make ai-demo`

**Result**: ✅ 22 questions processed in 0.7s

- Model trained on 1000 synthetic matches × 130 features (v0.3.0)
- QID collector registered intents for each classified question
- QID feature injection into GBDT feature vector confirmed (no errors)
- Top-10 GBDT features: `form_diff`, `h2h_home_win_pct`, `home_elo`, `h2h_avg_goals`, `day_sin`
- Non-football questions correctly rejected (2/22)

### 3.2 P2P Simulation — `make p2p-simulate`

**Result**: ✅ 5-node simulation completed in 1.8s

QID integration in Phase E (Turkish Q&A Pipeline):

| Metric | Value |
|---|---|
| QID broadcasts sent | 35 |
| QID records merged across peers | 945 |
| Matches with QID data | 7 |
| Max volume per match (lead node) | 35 records |
| Transport messages (total) | 520 |
| Delivered | 500 |
| Dropped (packet loss) | 20 (3.8%) |
| Bytes serialized | 315,254 |
| Serde errors | 0 |
| Avg latency | 86.3ms |

Each of the 5 nodes recorded query intents for 7 matches during Q&A, then broadcast
their batches to all peers. After merge, the lead node held 35 records per match
(7 local + 28 from 4 peers × 7 each).

### 3.3 P2P Scaling Test — `make p2p-scale-test`

**Result**: ✅ 25-peer stress test completed in 19.8s

- 25 peers (including 2 Sybil nodes with biased models)
- 30 match rounds with real Süper Lig data
- Reputation convergence with Sybil detection
- QID aggregation scales linearly with peer count

### 3.4 Go Server — `make server-health`

**Result**: ✅ Healthy

```json
{
    "database": true,
    "redis": true,
    "status": "healthy",
    "version": "0.1.0"
}
```

---

## 4. Coverage Matrix

### Makefile Targets Exercised

| Target | Command | Status | Notes |
|---|---|---|---|
| `make build` | `docker compose build` | ✅ | All 3 images rebuilt (ai, p2p, server) |
| `make test` | AI + P2P pytest | ✅ | 308 tests, 0 failures |
| `make test-ai` | AI pytest in Docker | ✅ | 212 passed / 50.97s |
| `make test-p2p` | P2P pytest in Docker | ✅ | 96 passed / 50.55s |
| `make ai-demo` | AI demo pipeline | ✅ | 22 questions, 130 features, v0.3.0 |
| `make p2p-simulate` | P2P 5-node simulation | ✅ | QID broadcasts + merge working |
| `make p2p-scale-test` | 25-peer stress test | ✅ | 19.8s, Sybil detection functional |
| `make server-health` | Go server health check | ✅ | DB + Redis + API healthy |

### Makefile Targets Not Exercised

| Target | Reason |
|---|---|
| `make ai-pipeline` | Requires live scraping infrastructure (scraper sources) |
| `make ai-train` | Covered indirectly by ai-demo (trains on startup) |
| `make ai-continuous` | Long-running loop, not suited for CI report |
| `make p2p-continuous` | Long-running loop |
| `make p2p-churn-test` | Dynamic churn covered by TestDynamicChurn unit tests |
| `make server-scrape` | Requires configured scraping targets |
| `make db-*` / `make redis-*` | Infrastructure management, not testable in report |

---

## 5. Version History

| Version | Features | Tests |
|---|---|---|
| v0.1.0 | TQU + GBDT + P2P basics | 120 AI + 84 P2P = 204 |
| v0.1.1 | P2P realism (wire serde, latency, topology, real data) | 140 AI + 84 P2P = 224 |
| v0.2.0 | Colloquial patterns, score prediction, Elo-adjusted xG | 192 AI + 84 P2P = 276 |
| **v0.3.0** | **QID system (query intent distribution as features)** | **212 AI + 96 P2P = 308** |

### Test Growth: +32 new tests this version

- +20 AI tests (QID collector, profile, feature expansion)
- +12 P2P tests (PeerNode QID, message type, intent classification)

---

## 6. Known Limitations

1. **Bootstrapping volume**: In production, hundreds of queries per match are needed
   before the distribution becomes meaningful. Below `MIN_VOLUME` (5), the system
   returns a uniform 0.1 vector (no signal, no harm).

2. **No time decay**: All queries within a match are weighted equally regardless
   of when they arrive. A future improvement could exponentially decay older queries.

3. **Synthetic QID data**: For training, QID features are generated as uniform
   random in [0, 0.5]. Real distributions will be Dirichlet-shaped (summing to ~1.0
   with sparsity). Model retraining with real data is required for full signal extraction.

4. **P2P flood potential**: Every node broadcasts its full intent batch. At scale
   (100+ nodes), a summary/sketch approach (e.g., count-min sketch) would reduce
   bandwidth.
