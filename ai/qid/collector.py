"""
Negelir QID — Query Intent Distribution Collector.
Tracks what humans ask about each match and computes intent frequency
distributions as demand-side sentiment features.

Insight: *what* people choose to ask is a predictive signal independent
of any model's answer.  High over/under query share before a match
signals the market expects goals.

Usage:
    collector = QueryIntentCollector()
    collector.record("match_001", "over_under", 0.85)
    collector.record("match_001", "match_winner", 0.70)
    features = collector.get_features("match_001")
"""

import time
import threading
from dataclasses import dataclass, field

from common.logger import get_logger

log = get_logger("qid.collector")

# Canonical intent buckets that map to feature columns.
# Order matters — indices correspond to FEATURE_COLUMNS offsets.
INTENT_BUCKETS: list[str] = [
    "match_winner",
    "draw",
    "over_under",
    "goal_range",
    "both_teams_score",
    "clean_sheet",
    "half_time",
    "form_query",
    "head_to_head",
    "score_predict",
]

N_INTENT_BUCKETS = len(INTENT_BUCKETS)

# Minimum queries before the distribution is considered meaningful.
MIN_VOLUME = 5


@dataclass
class QueryRecord:
    """A single recorded query classification."""
    intent_id: str
    confidence: float
    timestamp: float = field(default_factory=time.time)
    source: str = "local"  # "local" | "peer"


@dataclass
class MatchQueryProfile:
    """Aggregated query profile for one match."""
    match_id: str
    records: list[QueryRecord] = field(default_factory=list)

    @property
    def volume(self) -> int:
        return len(self.records)

    def intent_distribution(self) -> dict[str, float]:
        """Return normalised intent frequency distribution."""
        if not self.records:
            return {b: 0.0 for b in INTENT_BUCKETS}
        counts: dict[str, int] = {b: 0 for b in INTENT_BUCKETS}
        for r in self.records:
            if r.intent_id in counts:
                counts[r.intent_id] += 1
        total = max(1, sum(counts.values()))
        return {k: v / total for k, v in counts.items()}

    def confidence_weighted_distribution(self) -> dict[str, float]:
        """Confidence-weighted intent distribution (higher-confidence
        queries contribute more)."""
        if not self.records:
            return {b: 0.0 for b in INTENT_BUCKETS}
        weights: dict[str, float] = {b: 0.0 for b in INTENT_BUCKETS}
        for r in self.records:
            if r.intent_id in weights:
                weights[r.intent_id] += r.confidence
        total = max(0.01, sum(weights.values()))
        return {k: v / total for k, v in weights.items()}


class QueryIntentCollector:
    """
    Thread-safe collector for query intent observations.

    Each node (local or P2P) feeds classified queries here.
    Before inference the model extracts a 10-feature intent distribution
    vector for the match being predicted.
    """

    def __init__(self, max_records_per_match: int = 5000):
        self._profiles: dict[str, MatchQueryProfile] = {}
        self._max_records = max_records_per_match
        self._lock = threading.Lock()

    # ── Recording ────────────────────────────────────────

    def record(self, match_id: str, intent_id: str, confidence: float,
               source: str = "local") -> None:
        """Record one classified query for a match."""
        if intent_id not in INTENT_BUCKETS:
            return  # unknown intent — ignore silently
        with self._lock:
            if match_id not in self._profiles:
                self._profiles[match_id] = MatchQueryProfile(match_id=match_id)
            profile = self._profiles[match_id]
            if len(profile.records) >= self._max_records:
                return  # cap per match
            profile.records.append(
                QueryRecord(intent_id=intent_id, confidence=confidence, source=source)
            )

    def record_batch(self, match_id: str, records: list[dict]) -> int:
        """Merge a batch of records (e.g. received from P2P peer).
        Each dict: {"intent_id": str, "confidence": float, "source": str}.
        Returns count of records actually added."""
        added = 0
        for r in records:
            intent_id = r.get("intent_id", "")
            confidence = float(r.get("confidence", 0.0))
            source = r.get("source", "peer")
            if intent_id in INTENT_BUCKETS:
                self.record(match_id, intent_id, confidence, source=source)
                added += 1
        return added

    # ── Retrieval ────────────────────────────────────────

    def get_profile(self, match_id: str) -> MatchQueryProfile | None:
        with self._lock:
            return self._profiles.get(match_id)

    def get_features(self, match_id: str) -> list[float]:
        """
        Return the 10-float intent distribution feature vector for a match.
        Returns uniform (0.1 each) if insufficient volume.
        Order matches INTENT_BUCKETS.
        """
        with self._lock:
            profile = self._profiles.get(match_id)
        if profile is None or profile.volume < MIN_VOLUME:
            return [1.0 / N_INTENT_BUCKETS] * N_INTENT_BUCKETS
        dist = profile.confidence_weighted_distribution()
        return [dist[b] for b in INTENT_BUCKETS]

    def get_volume(self, match_id: str) -> int:
        with self._lock:
            profile = self._profiles.get(match_id)
        return profile.volume if profile else 0

    def get_all_match_ids(self) -> list[str]:
        with self._lock:
            return list(self._profiles.keys())

    def to_broadcast_payload(self, match_id: str) -> dict | None:
        """Serialise local query records for a match into a P2P payload."""
        with self._lock:
            profile = self._profiles.get(match_id)
        if profile is None or profile.volume == 0:
            return None
        return {
            "match_id": match_id,
            "volume": profile.volume,
            "records": [
                {"intent_id": r.intent_id, "confidence": round(r.confidence, 3),
                 "source": r.source}
                for r in profile.records
            ],
        }

    def merge_peer_payload(self, payload: dict) -> int:
        """Merge a broadcast payload from a peer.  Returns records added."""
        match_id = payload.get("match_id", "")
        records = payload.get("records", [])
        if not match_id or not records:
            return 0
        # Tag all incoming records as 'peer'
        for r in records:
            r["source"] = "peer"
        return self.record_batch(match_id, records)

    # ── Housekeeping ─────────────────────────────────────

    def evict_match(self, match_id: str) -> None:
        """Remove all data for a match (post-analysis cleanup)."""
        with self._lock:
            self._profiles.pop(match_id, None)

    def summary(self) -> dict:
        with self._lock:
            return {
                "matches_tracked": len(self._profiles),
                "total_records": sum(p.volume for p in self._profiles.values()),
                "profiles": {
                    mid: {"volume": p.volume, "distribution": p.intent_distribution()}
                    for mid, p in self._profiles.items()
                },
            }
