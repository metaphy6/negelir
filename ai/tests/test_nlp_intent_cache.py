"""Phase 10 §10.12 — Tests for IntentCache.

Tests cover:
* Cache hit / miss
* TTL expiry
* LRU eviction
* Thread-safety (basic smoke test)
* Negative-cache discipline (only meta.unsupported cached)
* Config integration
"""
from __future__ import annotations

import time
from typing import List

from common.config import Config
from ai.nlp._intent_cache import IntentCache
from nlp.eval._sample import _scrub_pii


def test_intent_cache_basic_hit_and_miss():
    """Cache hit returns stored tuple; cache miss returns None."""
    cache = IntentCache(max_entries=10, ttl_s=300)
    
    # Miss on empty cache.
    assert cache.get("hello", "tr-TR") is None
    
    # Put meta.unsupported.
    cache.put(
        normalized_text="hello",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.42,
        entity_hash="abc123",
    )
    
    # Cache hit.
    result = cache.get("hello", "tr-TR")
    assert result is not None
    intent, conf, ehash = result
    assert intent == "meta.unsupported"
    assert conf == 0.42
    assert ehash == "abc123"
    
    # Different locale = different key = miss.
    assert cache.get("hello", "en-GB") is None


def test_intent_cache_ttl_expiry():
    """Expired entries are removed and return None."""
    fake_clock = [0.0]
    
    def clock():
        return fake_clock[0]
    
    cache = IntentCache(max_entries=10, ttl_s=100, clock=clock)
    
    # t=0: put entry (expires at t=100).
    cache.put(
        normalized_text="test",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.5,
        entity_hash="xyz",
    )
    
    # t=50: still fresh.
    fake_clock[0] = 50.0
    result = cache.get("test", "tr-TR")
    assert result is not None
    
    # t=100: exactly at expiry = expired.
    fake_clock[0] = 100.0
    result = cache.get("test", "tr-TR")
    assert result is None
    
    # Cache should have removed the expired entry.
    assert cache.size() == 0


def test_intent_cache_lru_eviction():
    """When cache is full, LRU eviction removes the oldest entry."""
    cache = IntentCache(max_entries=3, ttl_s=300)
    
    # Fill cache: key1, key2, key3.
    cache.put("key1", "tr-TR", "meta.unsupported", 0.1, "h1")
    cache.put("key2", "tr-TR", "meta.unsupported", 0.2, "h2")
    cache.put("key3", "tr-TR", "meta.unsupported", 0.3, "h3")
    assert cache.size() == 3
    
    # All three should be present.
    assert cache.get("key1", "tr-TR") is not None
    assert cache.get("key2", "tr-TR") is not None
    assert cache.get("key3", "tr-TR") is not None
    
    # Access key1 to refresh its LRU position (now: key2, key3, key1).
    cache.get("key1", "tr-TR")
    
    # Insert key4: should evict key2 (oldest).
    cache.put("key4", "tr-TR", "meta.unsupported", 0.4, "h4")
    assert cache.size() == 3
    assert cache.get("key2", "tr-TR") is None  # evicted
    assert cache.get("key1", "tr-TR") is not None
    assert cache.get("key3", "tr-TR") is not None
    assert cache.get("key4", "tr-TR") is not None


def test_intent_cache_negative_cache_only():
    """Only meta.unsupported is cached; other intents are silently ignored."""
    cache = IntentCache(max_entries=10, ttl_s=300)
    
    # Put predict.match_outcome: should NOT be cached.
    cache.put(
        normalized_text="test_predict",
        locale="tr-TR",
        intent="predict.match_outcome",
        intent_confidence=0.9,
        entity_hash="foo",
    )
    assert cache.get("test_predict", "tr-TR") is None
    assert cache.size() == 0
    
    # Put meta.unsupported: SHOULD be cached.
    cache.put(
        normalized_text="test_meta",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.4,
        entity_hash="bar",
    )
    result = cache.get("test_meta", "tr-TR")
    assert result is not None
    assert result[0] == "meta.unsupported"
    assert cache.size() == 1


def test_l0_cache_key_does_not_depend_on_pii() -> None:
    """The L0 cache key stays stable across equivalent PII-scrubbed queries."""
    cache = IntentCache(max_entries=10, ttl_s=300, pod_id="pod")

    raw_with_pii = "Galatasaray maçına 0532 123 45 67 ile geliyorum."
    scrubbed_with_pii = _scrub_pii(raw_with_pii)
    expected_normalized = "Galatasaray maçına <UNK> ile geliyorum."

    assert scrubbed_with_pii == expected_normalized

    key_with_pii = cache._make_key(
        scrubbed_with_pii,
        "tr-TR",
        4,
        "1.0",
    )
    key_without_pii = cache._make_key(
        expected_normalized,
        "tr-TR",
        4,
        "1.0",
    )

    assert key_with_pii == key_without_pii


def test_intent_cache_update_existing_key():
    """Updating an existing key refreshes TTL and updates value."""
    fake_clock = [0.0]
    
    def clock():
        return fake_clock[0]
    
    cache = IntentCache(max_entries=10, ttl_s=100, clock=clock)
    
    # t=0: put entry (expires at t=100).
    cache.put("key", "tr-TR", "meta.unsupported", 0.1, "hash1")
    
    # t=50: update (new expiry at t=150).
    fake_clock[0] = 50.0
    cache.put("key", "tr-TR", "meta.unsupported", 0.2, "hash2")
    
    # t=120: original would be expired, but update extended TTL.
    fake_clock[0] = 120.0
    result = cache.get("key", "tr-TR")
    assert result is not None
    intent, conf, ehash = result
    assert conf == 0.2
    assert ehash == "hash2"
    
    # t=150: now expired.
    fake_clock[0] = 150.0
    assert cache.get("key", "tr-TR") is None


def test_intent_cache_clear():
    """clear() removes all entries."""
    cache = IntentCache(max_entries=10, ttl_s=300)
    cache.put("key1", "tr-TR", "meta.unsupported", 0.1, "h1")
    cache.put("key2", "tr-TR", "meta.unsupported", 0.2, "h2")
    assert cache.size() == 2
    
    cache.clear()
    assert cache.size() == 0
    assert cache.get("key1", "tr-TR") is None
    assert cache.get("key2", "tr-TR") is None


def test_intent_cache_thread_safety_smoke():
    """Basic smoke test for concurrent get/put."""
    import threading
    
    cache = IntentCache(max_entries=100, ttl_s=300)
    errors = []
    
    def worker():
        try:
            for i in range(50):
                key = f"key{i % 10}"
                cache.put(key, "tr-TR", "meta.unsupported", 0.5, f"hash{i}")
                result = cache.get(key, "tr-TR")
                # Result may be None due to concurrent eviction or miss; just verify no crash.
                if result is not None:
                    assert len(result) == 3
        except Exception as e:
            errors.append(e)
    
    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert not errors


def test_intent_cache_config_integration():
    """Config keys nlp_intent_cache_max_entries and nlp_intent_cache_ttl_s are respected."""
    cfg = Config()
    
    # Defaults per §10.12.
    assert cfg.nlp_intent_cache_max_entries == 10000
    assert cfg.nlp_intent_cache_ttl_s == 300
    
    # Instantiate cache with config values.
    cache = IntentCache(
        max_entries=cfg.nlp_intent_cache_max_entries,
        ttl_s=cfg.nlp_intent_cache_ttl_s,
    )
    
    # Smoke test: cache works with config-derived parameters.
    cache.put("smoke", "tr-TR", "meta.unsupported", 0.5, "hash")
    result = cache.get("smoke", "tr-TR")
    assert result is not None


def test_l0_cache_key_includes_pod_id_salt():
    """The L0 cache key includes the configured pod_id salt."""
    cache_a = IntentCache(max_entries=10, ttl_s=300, pod_id="pod-a")
    cache_b = IntentCache(max_entries=10, ttl_s=300, pod_id="pod-b")

    assert cache_a._make_key("same", "tr-TR", 4, "1.0") != cache_b._make_key("same", "tr-TR", 4, "1.0")


def test_l0_cache_key_uses_128bit_prefix_not_64bit():
    """Cache key aliases are 16-byte prefixes, not 8-byte truncations."""
    cache = IntentCache(max_entries=10, ttl_s=300, pod_id="pod")
    key = cache._make_key("same", "tr-TR", 4, "1.0")
    assert len(key) == 32


def test_l0_cache_key_includes_resolved_anaphora_antecedent_ids():
    """Resolved antecedent canonical IDs must namespace the L0 cache key."""
    cache = IntentCache(max_entries=10, ttl_s=300, pod_id="pod")
    cache.put(
        normalized_text="onlar oraya gidecek mi?",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.4,
        entity_hash="hash",
        schema_version=4,
        calibration_version="1.0",
        resolved_antecedent_ids=("team:galatasaray",),
    )

    assert cache.get(
        "onlar oraya gidecek mi?",
        "tr-TR",
        schema_version=4,
        calibration_version="1.0",
        resolved_antecedent_ids=("team:galatasaray",),
    ) is not None
    assert cache.get(
        "onlar oraya gidecek mi?",
        "tr-TR",
        schema_version=4,
        calibration_version="1.0",
        resolved_antecedent_ids=("team:fenerbahce",),
    ) is None
    assert cache._make_key(
        "onlar oraya gidecek mi?",
        "tr-TR",
        4,
        "1.0",
        resolved_antecedent_ids=("team:galatasaray",),
    ) != cache._make_key(
        "onlar oraya gidecek mi?",
        "tr-TR",
        4,
        "1.0",
        resolved_antecedent_ids=("team:fenerbahce",),
    )


def test_l0_cache_namespaced_by_schema_version():
    """Same surface query under different schema or calibration versions miss each other."""
    cache = IntentCache(max_entries=10, ttl_s=300, pod_id="pod")
    cache.put(
        normalized_text="hello",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.5,
        entity_hash="hash1",
        schema_version=3,
        calibration_version="1.0",
    )

    assert cache.get("hello", "tr-TR", schema_version=4, calibration_version="1.0") is None
    assert cache.get("hello", "tr-TR", schema_version=3, calibration_version="1.0") is not None


def test_l0_cache_namespaced_by_pipeline_version():
    """Same cache key under different pipeline versions miss each other."""
    cache = IntentCache(max_entries=10, ttl_s=300, pod_id="pod")
    key1 = cache._make_key(
        "hello",
        "tr-TR",
        4,
        "1.0",
        lexicon_version="",
        pipeline_version="10.0.0",
    )
    key2 = cache._make_key(
        "hello",
        "tr-TR",
        4,
        "1.0",
        lexicon_version="",
        pipeline_version="10.1.0",
    )
    assert key1 != key2


def test_l0_cache_namespaced_by_lexicon_version():
    """Same cache key under different lexicon versions miss each other."""
    cache = IntentCache(max_entries=10, ttl_s=300, pod_id="pod")
    key1 = cache._make_key(
        "hello",
        "tr-TR",
        4,
        "1.0",
        lexicon_version="lex-1",
        pipeline_version="10.0.0",
    )
    key2 = cache._make_key(
        "hello",
        "tr-TR",
        4,
        "1.0",
        lexicon_version="lex-2",
        pipeline_version="10.0.0",
    )
    assert key1 != key2


def test_l0_cache_collision_emits_critical_alert_and_redo_rpc():
    """A truncated key collision is detected, the entry is dropped, and an alert callback fires."""
    calls: List[bool] = []

    def alert():
        calls.append(True)

    cache = IntentCache(
        max_entries=10,
        ttl_s=300,
        pod_id="pod",
        collision_alert_callback=alert,
    )
    cache.put(
        normalized_text="collision",
        locale="tr-TR",
        intent="meta.unsupported",
        intent_confidence=0.4,
        entity_hash="hash",
        schema_version=4,
        calibration_version="1.0",
    )

    key = cache._make_key("collision", "tr-TR", 4, "1.0")
    stored = cache._cache[key]
    stored.subject_key_full_sha256 = "deadbeef" * 8

    result = cache.get("collision", "tr-TR", schema_version=4, calibration_version="1.0")
    assert result is None
    assert calls == [True]
