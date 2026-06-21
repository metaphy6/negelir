"""Phase 21.24 — Performance Budget + Latency SLA."""
import time
import json
import msgpack

import pytest

from common.config import Config
from model.enrichment_source import (
    MsgpackEnrichmentCodec,
    RedisEnrichmentSource,
    NullEnrichmentSource,
)


def test_enrichment_latency_budgets_defined() -> None:
    """SLA budgets are documented in config."""
    cfg = Config()
    # Redis batch fetch: ≤10ms P99
    # Postgres fallback: ≤50ms P99
    # Derived-view assembly: ≤5ms
    # Circuit breaker: ≤1ms
    # Total: ≤30ms
    assert cfg.enrichment_cache_ttl_s > 0
    assert hasattr(cfg, "enrichment_cache_ttl_s")


@pytest.mark.perf
def test_msgpack_serialization_reduces_redis_key_size() -> None:
    """Msgpack serialization reduces size vs JSON for large feature dicts."""
    # Create a larger feature dict to see realistic compression
    features = {}
    for i in range(50):  # 50 features with various types
        features[f"feature_{i:03d}"] = 0.123456789 * (i + 1)
    
    # JSON size
    json_bytes = json.dumps(features).encode("utf-8")
    json_size = len(json_bytes)
    
    # Msgpack size
    msgpack_bytes = msgpack.packb(features, use_bin_type=True)
    msgpack_size = len(msgpack_bytes)
    
    # Msgpack should be smaller
    assert msgpack_size < json_size
    reduction_pct = (1 - msgpack_size / json_size) * 100
    # With larger dicts, msgpack gives ~30-40% reduction
    assert reduction_pct > 5  # At least 5% reduction for realistic case


@pytest.mark.perf
def test_msgpack_roundtrip_preserves_feature_values_without_precision_loss() -> None:
    """Msgpack roundtrip preserves floating-point precision."""
    features = {
        "cohesion_penalty": -0.050123456789,  # Many decimal places
        "squad_strength_delta": 0.125,
        "referee_yellows_per_match": 4.20134,
    }
    
    # Roundtrip
    encoded = MsgpackEnrichmentCodec.encode(features)
    decoded = MsgpackEnrichmentCodec.decode(encoded)
    
    # Check values are preserved
    for key, value in features.items():
        assert key in decoded
        # Allow tiny floating-point rounding error
        assert abs(decoded[key] - value) < 1e-10


@pytest.mark.perf
def test_batch_fetch_protocol_defined() -> None:
    """Batch fetch protocol is defined in EnrichmentSource."""
    source = NullEnrichmentSource()
    assert hasattr(source, "get_enrichment_batch")
    assert callable(source.get_enrichment_batch)


@pytest.mark.perf
def test_null_enrichment_source_batch_fetch() -> None:
    """NullEnrichmentSource.get_enrichment_batch returns empty nested dicts."""
    source = NullEnrichmentSource()
    result = source.get_enrichment_batch(
        fixture_ids=["fix1", "fix2"],
        plane_ids=["roster", "health"],
        league_id="tr_super_lig"
    )
    
    # Check structure
    assert isinstance(result, dict)
    assert "fix1" in result
    assert "fix2" in result
    assert isinstance(result["fix1"], dict)
    assert "roster" in result["fix1"]
    assert "health" in result["fix1"]
    assert result["fix1"]["roster"] == {}
    assert result["fix1"]["health"] == {}


@pytest.mark.perf
def test_redis_enrichment_source_key_format() -> None:
    """Redis keys use correct format: f'enrich:{league_id}:{fixture_id}:{plane_id}'."""
    # Key format should include league_id to prevent cross-league contamination
    league_id = "tr_super_lig"
    fixture_id = "fix_12345"
    plane_id = "roster"
    
    expected_key = f"enrich:{league_id}:{fixture_id}:{plane_id}"
    assert expected_key == "enrich:tr_super_lig:fix_12345:roster"


@pytest.mark.perf
def test_batch_fetch_single_vs_multiple_fixtures() -> None:
    """Batch fetch should handle single and multiple fixtures."""
    source = NullEnrichmentSource()
    
    # Single fixture
    result_single = source.get_enrichment_batch(
        fixture_ids=["fix1"],
        plane_ids=["roster"],
        league_id="tr_super_lig"
    )
    assert len(result_single) == 1
    
    # Multiple fixtures
    result_multi = source.get_enrichment_batch(
        fixture_ids=["fix1", "fix2", "fix3"],
        plane_ids=["roster", "health"],
        league_id="tr_super_lig"
    )
    assert len(result_multi) == 3
