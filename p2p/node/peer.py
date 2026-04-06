"""
Negelir P2P — Peer node implementation.
Per roadmap §7: each node has its own AI, reputation table, and identity.
Includes content-addressed DataStore for P2P data retention.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.logging import RichHandler

_console = Console(force_terminal=True)


def get_p2p_logger(name: str) -> logging.Logger:
    level_str = os.getenv("AI_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_str, logging.DEBUG)
    logger = logging.getLogger(f"p2p.{name}")
    if not logger.handlers:
        handler = RichHandler(console=_console, show_time=True, show_path=False, markup=True)
        handler.setLevel(level)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger


log = get_p2p_logger("node.peer")


# ── Content-Addressed Data Store ──────────────────────────────────


@dataclass
class ScrapedRecord:
    """A single scraped data record shared across the P2P network."""
    data_hash: str
    source_node_id: str
    data_type: str  # "match", "team_stats", "odds", "referee"
    payload: dict
    timestamp: float = field(default_factory=time.time)
    ttl_hours: int = 168  # 7 days default

    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) / 3600 > self.ttl_hours


class DataStore:
    """
    Content-addressed data store for P2P data retention.

    Prevents redundant scraping by:
    1. Hashing every scraped record (SHA-256 of canonical payload).
    2. Storing records in a local dict keyed by content hash.
    3. Before scraping, peers query their local store (and propagate
       a manifest of hashes to neighbours so they can request missing data
       instead of re-scraping).

    Data flows:
        Scraper → local DataStore → SCRAPE_DATA broadcast → peer DataStores
    """

    def __init__(self, owner_id: str):
        self._owner_id = owner_id
        self._records: dict[str, ScrapedRecord] = {}  # hash → record
        self._seen_hashes: set[str] = set()  # fast dedup lookup
        self._log = get_p2p_logger(f"datastore.{owner_id[:8]}")

    # ── public API ────────────────────────────────────────

    @staticmethod
    def compute_hash(payload: dict, data_type: str) -> str:
        canonical = json.dumps({"type": data_type, "payload": payload}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    def has(self, data_hash: str) -> bool:
        return data_hash in self._seen_hashes

    def insert(self, data_type: str, payload: dict, source_node_id: str | None = None) -> ScrapedRecord | None:
        """Insert a record. Returns the record if new, None if duplicate."""
        h = self.compute_hash(payload, data_type)
        if h in self._seen_hashes:
            self._log.debug(f"⏭️  Duplicate skipped: {h[:12]}")
            return None
        rec = ScrapedRecord(
            data_hash=h,
            source_node_id=source_node_id or self._owner_id,
            data_type=data_type,
            payload=payload,
        )
        self._records[h] = rec
        self._seen_hashes.add(h)
        self._log.debug(f"📥 Stored: {data_type} {h[:12]} (total={len(self._records)})")
        return rec

    def get(self, data_hash: str) -> ScrapedRecord | None:
        return self._records.get(data_hash)

    def get_all(self, data_type: str | None = None) -> list[ScrapedRecord]:
        if data_type is None:
            return list(self._records.values())
        return [r for r in self._records.values() if r.data_type == data_type]

    def get_manifest(self) -> list[str]:
        """Return list of all content hashes (for sharing with peers)."""
        return list(self._seen_hashes)

    def missing_from(self, peer_manifest: list[str]) -> list[str]:
        """Return hashes in peer_manifest that we don't have."""
        return [h for h in peer_manifest if h not in self._seen_hashes]

    def merge_record(self, record: ScrapedRecord) -> bool:
        """Merge a record received from a peer. Returns True if new."""
        if record.data_hash in self._seen_hashes:
            return False
        # Verify hash integrity
        expected = self.compute_hash(record.payload, record.data_type)
        if expected != record.data_hash:
            self._log.warning(f"⚠️  Hash mismatch on merge: expected {expected[:12]}, got {record.data_hash[:12]}")
            return False
        if record.is_expired():
            self._log.debug(f"⏰ Expired record skipped: {record.data_hash[:12]}")
            return False
        self._records[record.data_hash] = record
        self._seen_hashes.add(record.data_hash)
        self._log.debug(f"🔄 Merged from peer {record.source_node_id[:8]}: {record.data_hash[:12]}")
        return True

    def evict_expired(self) -> int:
        """Remove expired records. Returns count evicted."""
        expired = [h for h, r in self._records.items() if r.is_expired()]
        for h in expired:
            del self._records[h]
            self._seen_hashes.discard(h)
        if expired:
            self._log.debug(f"🗑️  Evicted {len(expired)} expired records")
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._records)

    def to_summary(self) -> dict:
        by_type: dict[str, int] = {}
        for r in self._records.values():
            by_type[r.data_type] = by_type.get(r.data_type, 0) + 1
        return {"total": self.size, "by_type": by_type, "owner": self._owner_id[:8]}


@dataclass
class PeerAnalysis:
    """Analysis result shared over P2P (per roadmap §7.3)."""
    analysis_id: str
    node_id: str
    match_id: str
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    confidence: float
    model_version: str = "0.1.0"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "analysis_id": self.analysis_id,
            "node_id": self.node_id,
            "match_id": self.match_id,
            "distribution": {
                "home_win": self.home_win_prob,
                "draw": self.draw_prob,
                "away_win": self.away_win_prob,
            },
            "confidence": self.confidence,
            "model_version": self.model_version,
            "timestamp": self.timestamp,
        }

    @property
    def content_hash(self) -> str:
        data = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class PeerReputationEntry:
    """Per roadmap §5.3.3: local reputation entry for a peer."""
    peer_id: str
    accuracy_rolling_50: float = 0.0
    calibration_score: float = 0.0
    total_validated: int = 0
    trust_level: str = "new"  # new, low, medium, high, leader
    predictions: list = field(default_factory=list)

    def update_from_outcome(self, predicted_prob: float, was_correct: bool):
        self.predictions.append((predicted_prob, was_correct))
        # Keep rolling window of 50
        if len(self.predictions) > 50:
            self.predictions = self.predictions[-50:]

        self.total_validated = len(self.predictions)
        correct = sum(1 for _, c in self.predictions if c)
        self.accuracy_rolling_50 = correct / max(1, self.total_validated)

        # Calibration: how well confidence matches outcomes
        if self.total_validated > 5:
            cal_errors = [abs(p - (1.0 if c else 0.0)) for p, c in self.predictions]
            self.calibration_score = 1.0 - (sum(cal_errors) / len(cal_errors))

        # Trust level (per roadmap §5.3.3)
        if self.total_validated < 10:
            self.trust_level = "new"
        elif self.accuracy_rolling_50 < 0.40 or self.calibration_score < 0.30:
            self.trust_level = "low"
        elif self.accuracy_rolling_50 > 0.65 and self.calibration_score > 0.65 and self.total_validated >= 20:
            self.trust_level = "leader"
        elif self.accuracy_rolling_50 > 0.55 and self.calibration_score > 0.60:
            self.trust_level = "high"
        else:
            self.trust_level = "medium"


class PeerNode:
    """
    A single P2P peer node with its own AI model, reputation table, and identity.
    """

    def __init__(self, node_id: str, port: int = 0):
        self.node_id = node_id
        self.port = port
        self.reputation_table: dict[str, PeerReputationEntry] = {}
        self.analyses: dict[str, PeerAnalysis] = {}  # match_id → own analysis
        self.peer_analyses: dict[str, list[PeerAnalysis]] = {}  # match_id → list of peer analyses
        self.data_store = DataStore(owner_id=node_id)
        self.query_intents: dict[str, list[dict]] = {}  # match_id → list of intent records
        self.log = get_p2p_logger(f"node.{node_id[:8]}")

        # Simulated model bias (each node is slightly different)
        import random
        self.model_bias = random.gauss(0, 0.05)

    def produce_analysis(self, match_id: str, base_home_prob: float = 0.5) -> PeerAnalysis:
        """
        Simulate local GBDT inference with node-specific bias.
        In production, this calls the real GBDT model.
        """
        import random
        # Add node-specific noise to simulate different models
        noise = random.gauss(0, 0.08)
        home_prob = max(0.05, min(0.90, base_home_prob + self.model_bias + noise))
        draw_prob = max(0.05, min(0.40, 0.25 + random.gauss(0, 0.05)))
        away_prob = max(0.05, 1.0 - home_prob - draw_prob)

        # Normalize
        total = home_prob + draw_prob + away_prob
        home_prob /= total
        draw_prob /= total
        away_prob /= total

        confidence = max(0.3, min(0.95, abs(home_prob - away_prob) + 0.3 + random.gauss(0, 0.1)))

        analysis_id = hashlib.sha256(f"{self.node_id}:{match_id}".encode()).hexdigest()[:16]
        analysis = PeerAnalysis(
            analysis_id=analysis_id,
            node_id=self.node_id,
            match_id=match_id,
            home_win_prob=round(home_prob, 3),
            draw_prob=round(draw_prob, 3),
            away_win_prob=round(away_prob, 3),
            confidence=round(confidence, 3),
        )
        self.analyses[match_id] = analysis
        self.log.info(
            f"🧠 Analysis: {match_id[:8]} → "
            f"H={analysis.home_win_prob:.2f} D={analysis.draw_prob:.2f} "
            f"A={analysis.away_win_prob:.2f} (confidence: {analysis.confidence:.2f})"
        )
        return analysis

    def receive_peer_analysis(self, analysis: PeerAnalysis):
        """Receive an analysis from a peer node."""
        if analysis.node_id == self.node_id:
            return  # skip own

        if analysis.match_id not in self.peer_analyses:
            self.peer_analyses[analysis.match_id] = []
        self.peer_analyses[analysis.match_id].append(analysis)
        self.log.debug(f"📥 Analysis received from {analysis.node_id[:8]}: {analysis.match_id[:8]}")

    def compute_ensemble(self, match_id: str) -> PeerAnalysis | None:
        """
        Per roadmap §5.3.2: reputation-weighted ensemble.
        Combines local analysis with peer analyses weighted by reputation.
        """
        local = self.analyses.get(match_id)
        if not local:
            return None

        peers = self.peer_analyses.get(match_id, [])
        if not peers:
            return local

        # Softmax over reputation scores
        import math
        w_local = 0.5
        weights = []
        for pa in peers:
            rep = self.reputation_table.get(pa.node_id)
            if rep:
                trust_weights = {"new": 0.1, "low": 0.2, "medium": 0.5, "high": 1.0, "leader": 1.5}
                w = trust_weights.get(rep.trust_level, 0.1)
            else:
                w = 0.1  # unknown peer
            weights.append(w)

        # Normalize peer weights
        total_peer_w = sum(weights)
        if total_peer_w > 0:
            weights = [w / total_peer_w * (1 - w_local) for w in weights]
        else:
            weights = [0.0] * len(peers)

        # Weighted ensemble
        home = w_local * local.home_win_prob + sum(w * pa.home_win_prob for w, pa in zip(weights, peers))
        draw = w_local * local.draw_prob + sum(w * pa.draw_prob for w, pa in zip(weights, peers))
        away = w_local * local.away_win_prob + sum(w * pa.away_win_prob for w, pa in zip(weights, peers))

        # Normalize
        total = home + draw + away
        home /= total
        draw /= total
        away /= total

        confidence = max(0.3, min(0.95, local.confidence * 0.7 + 0.3 * (1 - abs(home - local.home_win_prob))))

        ensemble = PeerAnalysis(
            analysis_id=f"ens_{local.analysis_id}",
            node_id=self.node_id,
            match_id=match_id,
            home_win_prob=round(home, 3),
            draw_prob=round(draw, 3),
            away_win_prob=round(away, 3),
            confidence=round(confidence, 3),
        )

        self.log.info(
            f"🔀 Ensemble prediction ({len(peers)} nodes): {match_id[:8]} → "
            f"H={ensemble.home_win_prob:.2f} D={ensemble.draw_prob:.2f} "
            f"A={ensemble.away_win_prob:.2f}"
        )
        return ensemble

    def validate_outcome(self, match_id: str, actual_result: str):
        """
        Per roadmap §5.3.1: post-match outcome validation.
        Updates reputation for all peers whose analyses we received.
        """
        # Check own analysis
        own = self.analyses.get(match_id)
        if own:
            predicted = "H" if own.home_win_prob > max(own.draw_prob, own.away_win_prob) else (
                "D" if own.draw_prob > own.away_win_prob else "A"
            )
            was_correct = predicted == actual_result
            self.log.info(
                f"{'✅' if was_correct else '❌'} Own prediction: {predicted} vs actual: {actual_result}"
            )

        # Update peer reputations
        for pa in self.peer_analyses.get(match_id, []):
            predicted = "H" if pa.home_win_prob > max(pa.draw_prob, pa.away_win_prob) else (
                "D" if pa.draw_prob > pa.away_win_prob else "A"
            )
            was_correct = predicted == actual_result

            if pa.node_id not in self.reputation_table:
                self.reputation_table[pa.node_id] = PeerReputationEntry(peer_id=pa.node_id)

            prob_used = pa.home_win_prob if actual_result == "H" else (
                pa.draw_prob if actual_result == "D" else pa.away_win_prob
            )
            self.reputation_table[pa.node_id].update_from_outcome(prob_used, was_correct)

            rep = self.reputation_table[pa.node_id]
            self.log.debug(
                f"📊 {pa.node_id[:8]} reputation: "
                f"accuracy={rep.accuracy_rolling_50:.2f}, "
                f"trust={rep.trust_level}"
            )

    # ── Data Retention & Sharing ─────────────────────────

    def ingest_scraped_data(self, data_type: str, payload: dict) -> ScrapedRecord | None:
        """Ingest locally scraped data into this node's DataStore."""
        return self.data_store.insert(data_type, payload, source_node_id=self.node_id)

    def receive_scraped_data(self, record: ScrapedRecord) -> bool:
        """Receive scraped data from a peer. Returns True if new."""
        return self.data_store.merge_record(record)

    def needs_scrape(self, data_type: str, payload: dict) -> bool:
        """Check whether we already have this data (preventing redundant scraping)."""
        h = DataStore.compute_hash(payload, data_type)
        return not self.data_store.has(h)

    def get_data_manifest(self) -> list[str]:
        """Return our manifest of content hashes for sharing with peers."""
        return self.data_store.get_manifest()

    def request_missing_data(self, peer_manifest: list[str]) -> list[str]:
        """Given a peer's manifest, return the hashes we're missing."""
        return self.data_store.missing_from(peer_manifest)

    # ── Query Intent Distribution ────────────────────────

    def record_query_intent(self, match_id: str, intent_id: str, confidence: float) -> None:
        """Record a classified query intent for a match."""
        if match_id not in self.query_intents:
            self.query_intents[match_id] = []
        self.query_intents[match_id].append({
            "intent_id": intent_id,
            "confidence": round(confidence, 3),
            "source": self.node_id,
        })
        self.log.debug(f"📝 QID recorded: {match_id[:8]} intent={intent_id} conf={confidence:.2f}")

    def get_query_intent_payload(self, match_id: str) -> dict | None:
        """Build broadcast payload of query intent records for a match."""
        records = self.query_intents.get(match_id, [])
        if not records:
            return None
        return {
            "match_id": match_id,
            "node_id": self.node_id,
            "volume": len(records),
            "records": records,
        }

    def receive_query_intents(self, payload: dict) -> int:
        """Merge query intent records from a peer. Returns count added."""
        match_id = payload.get("match_id", "")
        records = payload.get("records", [])
        sender = payload.get("node_id", "unknown")
        if not match_id or not records or sender == self.node_id:
            return 0
        if match_id not in self.query_intents:
            self.query_intents[match_id] = []
        added = 0
        for r in records:
            self.query_intents[match_id].append({
                "intent_id": r["intent_id"],
                "confidence": r["confidence"],
                "source": sender,
            })
            added += 1
        self.log.debug(f"📥 QID merged {added} records from {sender[:8]} for {match_id[:8]}")
        return added

    def get_query_intent_distribution(self, match_id: str) -> dict[str, float]:
        """Compute normalised intent distribution for a match from all records."""
        _BUCKETS = [
            "match_winner", "draw", "over_under", "goal_range",
            "both_teams_score", "clean_sheet", "half_time",
            "form_query", "head_to_head", "score_predict",
        ]
        records = self.query_intents.get(match_id, [])
        counts: dict[str, float] = {b: 0.0 for b in _BUCKETS}
        for r in records:
            bid = r.get("intent_id", "")
            if bid in counts:
                counts[bid] += r.get("confidence", 1.0)
        total = max(0.01, sum(counts.values()))
        return {k: v / total for k, v in counts.items()}
