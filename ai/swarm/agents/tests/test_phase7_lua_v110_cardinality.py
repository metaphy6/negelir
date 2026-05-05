"""Phase 7 §7.3 — sec_denylist_mutate.lua v1.1.0 cardinality-drift fix.

The v1.0.0 design tracked cardinality with a plain `INCR/DECR` counter
(`sec:denylist:_count`). When a denylist entry's TTL expired naturally
inside Redis, the counter was NOT decremented — over time the counter
overstated the true cardinality, the cap flag flipped on permanently,
and the gateway over-blocked legitimate users via subnet-mode.

v1.1.0 replaces the counter with a sorted set keyed by expiration
timestamp. Lazy `ZREMRANGEBYSCORE` on every mutation drops members
whose score is in the past, so `ZCARD` is always truthful.

These tests run against a live Redis (skipped when none is reachable);
they are the regression guard for the v1.0.0 → v1.1.0 jump.
"""
from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest


def _redis_available(host: str = "localhost", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_available(),
    reason="Phase 7 Lua v1.1.0 regression requires a live Redis on localhost:6379",
)


@pytest.fixture(scope="module")
def redis_client():
    redis = pytest.importorskip("redis")
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    client.ping()
    yield client
    client.close()


@pytest.fixture(scope="module")
def mutate_sha(redis_client):
    repo_root = Path(__file__).resolve().parents[4]
    src = (repo_root / "infra/redis/lua/sec_denylist_mutate.lua").read_text()
    return redis_client.script_load(src)


@pytest.fixture
def keyspace(redis_client, request):
    prefix = f"test:p7:v110:{request.node.name}:{time.monotonic_ns()}"
    yield prefix
    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor, match=f"{prefix}:*", count=100)
        if keys:
            redis_client.delete(*keys)
        if cursor == 0:
            break
    # The ZSET tracker is a global key not under our prefix; clean it
    # here too so a parallel test run sees a fresh tracker. The legacy
    # v1.0.0 counter is also cleaned defensively.
    redis_client.delete("sec:denylist:_zset")
    redis_client.delete("sec:denylist:_count")


def _add(redis_client, sha, prefix, subj, *, ttl, max_entries, now_ms):
    return redis_client.evalsha(
        sha, 2,
        f"{prefix}:denylist:{subj}",
        f"{prefix}:denylist:capped",
        "add", ttl, max_entries, "r", now_ms,
    )


def _remove(redis_client, sha, prefix, subj, *, now_ms):
    return redis_client.evalsha(
        sha, 2,
        f"{prefix}:denylist:{subj}",
        f"{prefix}:denylist:capped",
        "remove", 0, 0, "r", now_ms,
    )


# ── v1.1.0 contract — cardinality stays truthful ──────────────────


def test_v110_add_requires_now_ms(redis_client, mutate_sha, keyspace):
    """v1.1.0 makes ``now_ms`` (ARGV[5]) mandatory on add — without
    it, ZSET scores are meaningless and lazy eviction breaks. This
    is a hard error, not a silent default."""
    status, _ = redis_client.evalsha(
        mutate_sha, 2,
        f"{keyspace}:denylist:s",
        f"{keyspace}:denylist:capped",
        "add", 60, 0, "r", 0,  # now_ms=0
    )
    assert status == "error"


def test_v110_zset_tracker_lazily_evicts_expired_entries(
    redis_client, mutate_sha, keyspace,
):
    """Add 5 entries with short TTL. Wait for them to expire in Redis.
    The next add must see the cardinality back to 1 (just the new
    one), NOT 6 — the lazy ZREMRANGEBYSCORE drops the dead members.

    This is the v1.0.0 → v1.1.0 regression: with the old counter, the
    next add would have observed cardinality=5 (stale) and the cap
    check would have wrongly rejected once max_entries was reached.
    """
    sha = mutate_sha
    now_ms = int(time.time() * 1000)
    # 1-second TTL so we don't have to mock time.
    for i in range(5):
        s, count = _add(
            redis_client, sha, keyspace, f"s{i}",
            ttl=1, max_entries=0, now_ms=now_ms,
        )
        assert s == "added"
        assert int(count) == i + 1
    # Wait for natural Redis TTL expiry. 1.2s gives a ~0.2s margin.
    time.sleep(1.2)
    # Now add a fresh subject with a future-ts now_ms so the lazy
    # sweep evicts the 5 stale members.
    future_ms = now_ms + 2_000
    s, count = _add(
        redis_client, sha, keyspace, "s_fresh",
        ttl=60, max_entries=0, now_ms=future_ms,
    )
    assert s == "added"
    assert int(count) == 1, (
        f"expected ZSET to evict 5 expired entries before counting; "
        f"got cardinality={count} (drift bug — v1.0.0 regression)"
    )


def test_v110_cap_recovers_after_natural_expiry(
    redis_client, mutate_sha, keyspace,
):
    """The v1.0.0 bug: cap reached → counter inflated forever → all
    future adds rejected even after entries naturally expire. This
    test proves v1.1.0 recovers — once the lazy sweep drains the
    ZSET below the cap, new entries are accepted and the cap-flag
    no longer trips on those adds."""
    sha = mutate_sha
    now_ms = int(time.time() * 1000)
    # Fill to cap with short TTL.
    for i in range(3):
        s, _ = _add(
            redis_client, sha, keyspace, f"s{i}",
            ttl=1, max_entries=3, now_ms=now_ms,
        )
        assert s == "added"
    # 4th must reject and set the capped flag.
    s, _ = _add(
        redis_client, sha, keyspace, "s_overflow",
        ttl=60, max_entries=3, now_ms=now_ms,
    )
    assert s == "rejected_capped"
    assert redis_client.exists(f"{keyspace}:denylist:capped") == 1
    # Wait for the original 3 to expire in Redis.
    time.sleep(1.2)
    # New add with future now_ms — sweep should drop the 3 stale
    # members so cap (3) is no longer hit.
    future_ms = now_ms + 2_000
    s, count = _add(
        redis_client, sha, keyspace, "s_recovered",
        ttl=60, max_entries=3, now_ms=future_ms,
    )
    assert s == "added", (
        f"expected v1.1.0 lazy eviction to free the cap after natural "
        f"expiry; got status={s}, count={count} — cardinality drift "
        f"regression"
    )
    assert int(count) == 1


def test_v110_zset_score_overwritten_on_re_add(
    redis_client, mutate_sha, keyspace,
):
    """Re-adding the same subject overwrites the ZSET score (later
    expiry wins, matching SET ... EX semantics). Cardinality stays
    at 1; no double-counting under at-least-once redelivery."""
    sha = mutate_sha
    now_ms = int(time.time() * 1000)
    s1, c1 = _add(
        redis_client, sha, keyspace, "subj",
        ttl=30, max_entries=0, now_ms=now_ms,
    )
    s2, c2 = _add(
        redis_client, sha, keyspace, "subj",
        ttl=120, max_entries=0, now_ms=now_ms,
    )
    assert s1 == "added" and s2 == "added"
    assert int(c1) == int(c2) == 1, "re-add MUST NOT bump cardinality"
    # ZSET score must reflect the LATER expiry (now_ms + 120000).
    score = redis_client.zscore("sec:denylist:_zset", f"{keyspace}:denylist:subj")
    assert score is not None
    expected_min = now_ms + 119_500  # tolerate sub-second jitter
    assert score >= expected_min, (
        f"expected ZSET score to reflect refreshed TTL (~{now_ms + 120_000}); "
        f"got {score} — re-add did not overwrite score"
    )


def test_v110_remove_decrements_zset_truthfully(
    redis_client, mutate_sha, keyspace,
):
    """Remove drops the ZSET member as well as the keyed entry. The
    cardinality reported on the next operation reflects the drop."""
    sha = mutate_sha
    now_ms = int(time.time() * 1000)
    _add(redis_client, sha, keyspace, "a", ttl=60, max_entries=0, now_ms=now_ms)
    _add(redis_client, sha, keyspace, "b", ttl=60, max_entries=0, now_ms=now_ms)
    s, count = _remove(redis_client, sha, keyspace, "a", now_ms=now_ms)
    assert s == "removed"
    assert int(count) == 1
    # Remove the same one again — must be noop with truthful count.
    s, count = _remove(redis_client, sha, keyspace, "a", now_ms=now_ms)
    assert s == "noop"
    assert int(count) == 1


def test_v110_capped_flag_carries_safety_ttl(
    redis_client, mutate_sha, keyspace,
):
    """The capped flag set on cap-trip must carry a TTL so a process
    crash mid-recovery doesn't leave the gateway in subnet-mode
    forever. The Lua locks this at 300 s."""
    sha = mutate_sha
    now_ms = int(time.time() * 1000)
    for i in range(2):
        _add(redis_client, sha, keyspace, f"s{i}", ttl=60, max_entries=2, now_ms=now_ms)
    s, _ = _add(redis_client, sha, keyspace, "s2", ttl=60, max_entries=2, now_ms=now_ms)
    assert s == "rejected_capped"
    ttl = redis_client.ttl(f"{keyspace}:denylist:capped")
    assert 0 < ttl <= 300, f"capped flag must carry a bounded TTL; got {ttl}"


def test_v110_mutate_clock_rewind_safety(
    redis_client, mutate_sha, keyspace,
):
    """F7.6 (P6): if ``now_ms`` rewinds (NTP step-back, mocksrv
    fixture replay), a re-add of the same subject MUST overwrite
    the ZSET score with the new (smaller) ``now_ms + ttl_ms``.

    Pre-fix risk: a smuggled ``ZADD GT`` (or a Lua ``max(old, new)``)
    would silently keep the older, larger score, extending the
    effective TTL beyond what the caller requested. That breaks
    the cap-cardinality guarantee (lazy ZREMRANGEBYSCORE would
    not evict the entry until the stale score elapsed) and hides
    config errors from operators.

    Contract: unconditional overwrite — newest call wins,
    monotonicity of ``now_ms`` is the caller's responsibility.
    """
    sha = mutate_sha
    forward_ms = 1_000_000_000
    rewound_ms = forward_ms - 500_000  # 500s rewind
    s1, _ = _add(
        redis_client, sha, keyspace, "subj",
        ttl=600, max_entries=0, now_ms=forward_ms,
    )
    s2, _ = _add(
        redis_client, sha, keyspace, "subj",
        ttl=600, max_entries=0, now_ms=rewound_ms,
    )
    assert s1 == "added" and s2 == "added"
    score = redis_client.zscore("sec:denylist:_zset", f"{keyspace}:denylist:subj")
    expected = rewound_ms + 600_000
    assert score == pytest.approx(expected, abs=1_000), (
        f"ZSET score after clock-rewind re-add = {score}; expected ~{expected} "
        "(unconditional overwrite). Got the older/larger score → suggests "
        "ZADD GT or max(old,new) smuggled in; cap-cardinality contract "
        "broken."
    )
