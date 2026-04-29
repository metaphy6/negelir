"""Pre-Phase-6 audit PERF3: schema parse caching.

`load(topic)` must hit the lru_cache on the second call so that the
hot validate() path doesn't re-read and re-parse the JSON file on
every bus message.
"""
from __future__ import annotations

from swarm.sdk import schemas as schema_mod


def test_load_is_cached():
    schema_mod._load_cached.cache_clear()
    schema_mod.load("predict.final")
    assert schema_mod._load_cached.cache_info().misses == 1
    schema_mod.load("predict.final")
    info = schema_mod._load_cached.cache_info()
    assert info.misses == 1, "second load must hit the cache"
    assert info.hits >= 1


def test_load_unknown_topic_still_raises():
    schema_mod._load_cached.cache_clear()
    try:
        schema_mod.load("does.not.exist")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("must raise for missing schema")
