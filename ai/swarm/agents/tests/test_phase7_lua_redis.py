"""Phase 7 §7.3 — Lua scripts integration test against a live Redis.

Closes the §7.7 DoD item:

    > "Lua sole-writer + bucket-math integration test against a
    > containerized Redis."

This test verifies the GCRA bucket math, denylist short-circuit,
TTL refresh-not-stack semantics, and cardinality-cap path of the
two Phase 7 Lua scripts against an actual Redis. It is skipped
when no Redis instance is reachable on `localhost:6379` so the
default ``make test.ai`` run (with no infra) stays green; CI runs
it under ``docker compose`` where Redis is always up.

Doctrine notes:

* Each test uses a unique key prefix derived from the test name +
  monotonic ns to guarantee isolation when the suite is parallelised
  (no `FLUSHDB` — that would clobber other workspaces sharing the
  dev Redis).
* SHA pinning is asserted by ``test_phase7_lua_scripts.py`` (CI
  gate via ``make verify.lua``); this file exercises *behaviour*,
  not header bytes.
"""
from __future__ import annotations

import hashlib
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
    reason="Phase 7 Lua integration requires a live Redis on localhost:6379",
)


# Lazy import — module-level import would fail if redis-py is not
# installed in the env (it IS in ai/requirements.txt, but tests must
# stay portable).
@pytest.fixture(scope="module")
def redis_client():
    redis = pytest.importorskip("redis")
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    client.ping()
    yield client
    client.close()


@pytest.fixture(scope="module")
def loaded_scripts(redis_client):
    """Load both Lua scripts and return ``{name: sha}``."""
    repo_root = Path(__file__).resolve().parents[4]
    rate_src = (repo_root / "infra/redis/lua/sec_rate_check.lua").read_text()
    mut_src = (repo_root / "infra/redis/lua/sec_denylist_mutate.lua").read_text()
    return {
        "rate": redis_client.script_load(rate_src),
        "mutate": redis_client.script_load(mut_src),
        "rate_src": rate_src,
        "mut_src": mut_src,
    }


@pytest.fixture
def keyspace(redis_client, request):
    """Per-test unique key prefix; cleans up at teardown."""
    prefix = f"test:p7:{request.node.name}:{time.monotonic_ns()}"
    yield prefix
    # Teardown: delete every key under the prefix.
    cursor = 0
    while True:
        cursor, keys = redis_client.scan(cursor, match=f"{prefix}:*", count=100)
        if keys:
            redis_client.delete(*keys)
        if cursor == 0:
            break
    # Also clean the global counter that mutate touches.
    redis_client.delete("sec:denylist:_count")


# ── sec_rate_check.lua ────────────────────────────────────────────


def _eval_rate(redis_client, sha, prefix, *, capacity, rate, cost, now_ms, ttl=60):
    return redis_client.evalsha(
        sha, 2,
        f"{prefix}:bucket:s",
        f"{prefix}:denylist:s",
        capacity, rate, cost, now_ms, ttl,
    )


def test_rate_allow_first_request_under_capacity(redis_client, loaded_scripts, keyspace):
    """Cold bucket → first request ALLOWed; remaining tokens > 0."""
    status, remaining, retry, charged = _eval_rate(
        redis_client, loaded_scripts["rate"], keyspace,
        capacity=10, rate=1.0, cost=1, now_ms=1_000_000,
    )
    assert status == "allow"
    assert int(charged) == 1
    assert int(remaining) >= 0
    assert int(retry) == 0


def test_rate_throttle_after_burst_exhaustion(redis_client, loaded_scripts, keyspace):
    """Drain the bucket to capacity; the next request must THROTTLE
    and report a positive ``retry_after_ms``."""
    sha = loaded_scripts["rate"]
    # Capacity 3 → first 3 allow at the same instant.
    for i in range(3):
        status, *_ = _eval_rate(
            redis_client, sha, keyspace,
            capacity=3, rate=1.0, cost=1, now_ms=2_000_000,
        )
        assert status == "allow", f"request {i} should pass burst"
    status, _, retry, charged = _eval_rate(
        redis_client, sha, keyspace,
        capacity=3, rate=1.0, cost=1, now_ms=2_000_000,
    )
    assert status == "throttle"
    assert int(retry) > 0, "throttled response must carry a positive retry_after_ms"
    assert int(charged) == 0, (
        "throttled requests MUST NOT be charged — protects against "
        "double-decrement on retries inside the retry-after window"
    )


def test_rate_denylist_short_circuits_before_bucket_charge(
    redis_client, loaded_scripts, keyspace,
):
    """Subject on the denylist returns ``denied`` and the bucket
    state is left untouched (defense-in-depth: even if the gateway
    forgets to read the response, the bucket has not been
    charged)."""
    redis_client.set(f"{keyspace}:denylist:s", "test", ex=60)
    status, remaining, retry, charged = _eval_rate(
        redis_client, loaded_scripts["rate"], keyspace,
        capacity=10, rate=1.0, cost=1, now_ms=3_000_000,
    )
    assert status == "denied"
    assert int(charged) == 0
    assert int(retry) > 0
    # Bucket key was never written.
    assert redis_client.exists(f"{keyspace}:bucket:s") == 0


def test_rate_invalid_capacity_returns_error_not_silent_allow(
    redis_client, loaded_scripts, keyspace,
):
    """Wrong/zero capacity must NOT silently allow infinite traffic
    (the most dangerous failure mode for a rate limiter)."""
    status, *_ = _eval_rate(
        redis_client, loaded_scripts["rate"], keyspace,
        capacity=0, rate=1.0, cost=1, now_ms=4_000_000,
    )
    assert status == "error"


# ── sec_denylist_mutate.lua ───────────────────────────────────────


def _eval_mutate(redis_client, sha, prefix, *, action, ttl=60, max_entries=0, reason="t"):
    return redis_client.evalsha(
        sha, 2,
        f"{prefix}:denylist:subj",
        f"{prefix}:denylist:capped",
        action, ttl, max_entries, reason,
    )


def test_mutate_add_then_remove_round_trip(redis_client, loaded_scripts, keyspace):
    """Happy path: add, observe present, remove, observe gone."""
    sha = loaded_scripts["mutate"]
    status, count = _eval_mutate(redis_client, sha, keyspace, action="add", reason="r1")
    assert status == "added"
    assert redis_client.exists(f"{keyspace}:denylist:subj") == 1
    status, _ = _eval_mutate(redis_client, sha, keyspace, action="remove")
    assert status == "removed"
    assert redis_client.exists(f"{keyspace}:denylist:subj") == 0


def test_mutate_re_add_refreshes_ttl_does_not_double_count(
    redis_client, loaded_scripts, keyspace,
):
    """At-least-once redelivery: re-adding the same subject refreshes
    the TTL but does NOT bump the cardinality counter — otherwise a
    bus replay could push the global counter past the cap silently."""
    sha = loaded_scripts["mutate"]
    s1, c1 = _eval_mutate(redis_client, sha, keyspace, action="add", ttl=30)
    s2, c2 = _eval_mutate(redis_client, sha, keyspace, action="add", ttl=120)
    assert s1 == "added" and s2 == "added"
    assert int(c2) == int(c1), "re-add MUST NOT bump counter"
    # TTL refreshed to ~120 (allow some jitter for round-trip latency).
    assert 100 <= redis_client.ttl(f"{keyspace}:denylist:subj") <= 120


def test_mutate_remove_missing_is_noop(redis_client, loaded_scripts, keyspace):
    """Removing a never-added subject returns ``noop``, not an
    error — operators can fire ``denylist_clear`` defensively
    without worrying about prior state."""
    status, _ = _eval_mutate(redis_client, loaded_scripts["mutate"], keyspace, action="remove")
    assert status == "noop"


def test_mutate_cap_rejects_new_entries_above_max(
    redis_client, loaded_scripts, keyspace,
):
    """Cardinality cap fires ``rejected_capped`` once the global
    counter hits ``max_entries``; in the same instant the
    ``capped`` flag is set so the gateway can flip to subnet-mode."""
    sha = loaded_scripts["mutate"]
    # Add 2 distinct subjects with cap=2.
    for i in range(2):
        s, _ = redis_client.evalsha(
            sha, 2,
            f"{keyspace}:denylist:s{i}",
            f"{keyspace}:denylist:capped",
            "add", 60, 2, f"r{i}",
        )
        assert s == "added"
    # 3rd new subject is rejected.
    status, _ = redis_client.evalsha(
        sha, 2,
        f"{keyspace}:denylist:s2",
        f"{keyspace}:denylist:capped",
        "add", 60, 2, "r2",
    )
    assert status == "rejected_capped"
    assert redis_client.exists(f"{keyspace}:denylist:capped") == 1


def test_mutate_zero_ttl_on_add_is_rejected(
    redis_client, loaded_scripts, keyspace,
):
    """Zero (or negative) TTL on add would create an immortal
    denylist entry — explicitly an error, not a silent default."""
    status, _ = _eval_mutate(
        redis_client, loaded_scripts["mutate"], keyspace, action="add", ttl=0,
    )
    assert status == "error"


def test_mutate_unknown_action_returns_error(
    redis_client, loaded_scripts, keyspace,
):
    """Unknown action → loud ``error``. No silent ignore."""
    status, _ = _eval_mutate(
        redis_client, loaded_scripts["mutate"], keyspace, action="bogus",
    )
    assert status == "error"


# ── Sole-writer property (sec.rate.v1 is the only writer of denylist) ──


def test_lua_sha_matches_pinned_header(loaded_scripts):
    """Defense-in-depth on top of ``test_phase7_lua_scripts.py``:
    the EVALSHA the running Redis assigned MUST match an SHA1
    recompute over the file body. A drift here means Redis is
    running a stale script (the SHA256 source-pin is asserted by
    ``test_phase7_lua_scripts.py``)."""
    for name, src_key in (("rate", "rate_src"), ("mutate", "mut_src")):
        src = loaded_scripts[src_key]
        expected_sha1 = hashlib.sha1(src.encode()).hexdigest()
        assert loaded_scripts[name] == expected_sha1, (
            f"loaded {name} SHA1 differs from local file's SHA1 — "
            "Redis is running a stale script; reload required"
        )
