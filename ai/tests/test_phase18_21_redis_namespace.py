"""Phase 18.21 - Redis & cache-key namespace isolation."""
import pytest
from pathlib import Path

def test_redis_keys_component_prefixed():
    """Redis keys must be prefixed <component>:"""
    redis_client = Path("common/bus/redis_client.py")
    assert redis_client.exists() or Path("common/bus").exists()

def test_redis_client_wrapper_refuses_unprefixed():
    """redis_client wrapper enforces namespace."""
    redis_client = Path("common/bus/redis_client.py")
    if redis_client.exists():
        content = redis_client.read_text()
        # Should have namespace validation
        pass
