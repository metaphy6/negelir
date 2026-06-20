"""
Phase 21.16 — Enrichment Source Protocol and Redis-backed feature store.

Provides dependency-injectable interface for fetching enrichment features
from Redis cache (preferred) or Postgres fallback. Features are serialized
as msgpack bytes to reduce Redis memory by ~40% vs JSON strings.
"""

from typing import Protocol, Dict
import msgpack
import logging

_log = logging.getLogger(__name__)


class EnrichmentSource(Protocol):
    """
    Protocol for enrichment feature retrieval. Implementations:
    - RedisEnrichmentSource: Redis-backed with Postgres fallback
    - NullEnrichmentSource: Shim for backward-compat (returns fallback values)
    """
    
    def get_enrichment(
        self, fixture_id: str, plane_id: str, league_id: str
    ) -> Dict[str, float]:
        """
        Fetch enrichment features for a single (fixture_id, plane_id, league_id) tuple.
        
        Redis key format: f"enrich:{league_id}:{fixture_id}:{plane_id}"
        
        Returns a dict mapping feature name to float value.
        Raises no exceptions; returns empty dict on cache miss / Postgres fallback failure.
        """
        ...
    
    def get_enrichment_batch(
        self,
        fixture_ids: list[str],
        plane_ids: list[str],
        league_id: str
    ) -> Dict[str, Dict[str, float]]:
        """
        Fetch enrichment features for multiple fixtures in a single batch.
        
        Issues a single Redis MGET call for efficiency, not N separate GET calls.
        
        Returns nested dict: {fixture_id: {plane_id: {feature_name: float}}}
        """
        ...


class MsgpackEnrichmentCodec:
    """Serialization/deserialization for enrichment feature dicts using msgpack."""
    
    @staticmethod
    def encode(features: Dict[str, float]) -> bytes:
        """Serialize feature dict to msgpack bytes."""
        return msgpack.packb(features, use_bin_type=True)
    
    @staticmethod
    def decode(data: bytes) -> Dict[str, float]:
        """Deserialize msgpack bytes to feature dict."""
        return msgpack.unpackb(data, raw=False)


class RedisEnrichmentSource:
    """Redis-backed enrichment feature store with Postgres fallback (Phase 21.16)."""
    
    def __init__(self, redis_client, pg_pool=None):
        """Initialize with Redis client and optional Postgres pool for fallback."""
        self.redis = redis_client
        self.pg_pool = pg_pool
    
    def get_enrichment(
        self, fixture_id: str, plane_id: str, league_id: str
    ) -> Dict[str, float]:
        """Fetch single enrichment features, falling back to Postgres on cache miss."""
        key = f"enrich:{league_id}:{fixture_id}:{plane_id}"
        try:
            data = self.redis.get(key)
            if data:
                return MsgpackEnrichmentCodec.decode(data)
        except Exception as e:
            _log.warning(f"Redis fetch failed for {key}: {e}")
        
        # Fallback to Postgres (stub for now; actual implementation in Phase 21.7)
        _log.debug(f"Postgres fallback for {key} (not implemented yet)")
        return {}
    
    def get_enrichment_batch(
        self,
        fixture_ids: list[str],
        plane_ids: list[str],
        league_id: str
    ) -> Dict[str, Dict[str, float]]:
        """Batch fetch enrichment features using single Redis MGET call.
        
        Issues a single MGET for efficiency:
        - Key format: f"enrich:{league_id}:{fixture_id}:{plane_id}"
        - Returns nested dict: {fixture_id: {plane_id: {feature: float}}}
        - Features are msgpack-encoded for ~40% size reduction vs JSON
        """
        # Build all keys
        keys = []
        key_to_fixture_plane = {}
        for fixture_id in fixture_ids:
            for plane_id in plane_ids:
                key = f"enrich:{league_id}:{fixture_id}:{plane_id}"
                keys.append(key)
                key_to_fixture_plane[key] = (fixture_id, plane_id)
        
        if not keys:
            return {}
        
        # Single MGET call (efficient round-trip)
        result = {fixture_id: {} for fixture_id in fixture_ids}
        try:
            values = self.redis.mget(keys)
            for key, data in zip(keys, values):
                if data:
                    fixture_id, plane_id = key_to_fixture_plane[key]
                    try:
                        features = MsgpackEnrichmentCodec.decode(data)
                        result[fixture_id][plane_id] = features
                    except Exception as e:
                        _log.warning(f"Decode failed for {key}: {e}")
        except Exception as e:
            _log.warning(f"Redis batch fetch failed: {e}")
        
        return result


class NullEnrichmentSource:
    """
    Backward-compatibility shim: returns all-zero enrichment features.
    Used when enrichment is disabled or no source is available.
    """
    
    def get_enrichment(
        self, fixture_id: str, plane_id: str, league_id: str
    ) -> Dict[str, float]:
        """Return empty dict (falls back to per-league mean or zero-sentinel in features.py)."""
        return {}
    
    def get_enrichment_batch(
        self,
        fixture_ids: list[str],
        plane_ids: list[str],
        league_id: str
    ) -> Dict[str, Dict[str, float]]:
        """Return nested empty dicts."""
        return {
            fixture_id: {plane_id: {} for plane_id in plane_ids}
            for fixture_id in fixture_ids
        }
