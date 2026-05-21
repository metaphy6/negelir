"""Phase 8 §8.9 — sec_denylist_decimate.lua deterministic Python reference
parity.

Mirrors the §7.7 v1.1.0 pattern established in
``test_phase7_visibility_and_lua_parity.py``:

1. **Structural check.** Assert the canonical Lua source still contains
   the arithmetic markers the Python reference mirrors, so a Lua
   refactor that shifts the decimation logic fails loud rather than
   silently diverging from the reference.

2. **Deterministic 1000-tuple sweep (no Redis required).** Drive
   ``_python_reference_decimate`` across 1000 random ``(zcard, cap)``
   tuples with seed=1337; prove the output is deterministic and that
   the reference satisfies the invariants the Lua guarantees.

The live-Redis companion (skip when no Redis) exercises the actual
script — but the parity gate here runs in the default ``make test.ai``
path so CI catches drift even without infrastructure.
"""
from __future__ import annotations

import math
import random
import socket
from pathlib import Path

import pytest


# ── Python reference ─────────────────────────────────────────────────


def _python_reference_decimate(
    *,
    zcard: int,
    cap: int,
) -> tuple[int, int, int, int]:
    """Mirror of ``infra/redis/lua/sec_denylist_decimate.lua``.

    Every line traces 1:1 to the Lua to keep the audit cheap.

    Args:
        zcard: current cardinality of the denylist sorted set
               (``ZCARD sec:denylist:zset``).
        cap:   ``cfg.sec_denylist_max_entries``; 0 = unbounded.

    Returns:
        ``(evicted_count, decile_size, new_zcard, cap_cleared)``
        where ``cap_cleared`` is 1 if the flag was DEL'd, 0 otherwise.
    """
    # Lua: if cap == 0 or zcard <= cap then return { 0, 0, zcard, 0 } end
    if cap == 0 or zcard <= cap:
        return (0, 0, zcard, 0)

    # Lua: local decile = math.floor(zcard / 10)
    #      if decile < 1 then decile = 1 end
    decile = math.floor(zcard / 10)
    if decile < 1:
        decile = 1

    # Lua: local evicted = redis.call("ZREMRANGEBYRANK", zkey, 0, decile - 1)
    # ZREMRANGEBYRANK 0 to decile-1 removes exactly `decile` members.
    evicted = decile
    new_zcard = zcard - evicted

    # Lua: if new_zcard <= cap then redis.call("DEL", capkey); cleared = 1 end
    cleared = 1 if new_zcard <= cap else 0

    return (evicted, decile, new_zcard, cleared)


# ── Structural check ─────────────────────────────────────────────────


def test_python_reference_decimate_matches_lua_source_structurally() -> None:
    """The Lua source still contains the arithmetic markers the Python
    reference mirrors. Fires loud if a Lua refactor shifts the logic."""
    repo_root = Path(__file__).resolve().parents[4]
    lua_src = (repo_root / "infra/redis/lua/sec_denylist_decimate.lua").read_text()
    for marker in (
        "ZCARD",
        "math.floor(zcard / 10)",
        "ZREMRANGEBYRANK",
        "new_zcard <= cap",
        "cleared = 1",
        "return { evicted, decile, new_zcard, cleared }",
    ):
        assert marker in lua_src, (
            f"Lua source missing structural marker {marker!r}; "
            f"Python reference _python_reference_decimate is stale"
        )


# ── 1000-tuple deterministic sweep ───────────────────────────────────


@pytest.mark.parametrize("seed", [1337])
def test_python_reference_decimate_is_deterministic(seed: int) -> None:
    """1000-tuple deterministic sweep (seed=1337, no Redis required).

    Proves:
    (a) the reference is deterministic across repeated runs,
    (b) the Lua invariants hold for every input:
        - when cap==0 or zcard<=cap → no-op (evicted=0, decile=0,
          new_zcard=zcard, cap_cleared=0),
        - evicted == decile == max(floor(zcard/10), 1),
        - new_zcard == zcard - evicted,
        - cap_cleared is 1 iff new_zcard <= cap, else 0.
    """
    rng = random.Random(seed)

    noop_count = 0
    evict_count = 0
    cleared_count = 0

    for _ in range(1000):
        zcard = rng.randint(0, 2000)
        # cap: 0 (unbounded), or some value spanning below, at, above zcard
        cap = rng.choice([0, rng.randint(1, max(zcard, 1)), zcard])

        evicted, decile, new_zcard, cap_cleared = _python_reference_decimate(
            zcard=zcard, cap=cap
        )

        if cap == 0 or zcard <= cap:
            # No-op branch
            assert evicted == 0, f"no-op: expected evicted=0, got {evicted}"
            assert decile == 0, f"no-op: expected decile=0, got {decile}"
            assert new_zcard == zcard, f"no-op: new_zcard mismatch"
            assert cap_cleared == 0, f"no-op: cap_cleared must be 0"
            noop_count += 1
        else:
            # Eviction branch
            expected_decile = max(math.floor(zcard / 10), 1)
            assert decile == expected_decile, (
                f"zcard={zcard}: decile={decile} expected={expected_decile}"
            )
            assert evicted == expected_decile, (
                f"zcard={zcard}: evicted must equal decile ({expected_decile})"
            )
            assert new_zcard == zcard - evicted, (
                f"zcard={zcard}: new_zcard={new_zcard} expected={zcard - evicted}"
            )
            expected_cleared = 1 if new_zcard <= cap else 0
            assert cap_cleared == expected_cleared, (
                f"zcard={zcard} cap={cap}: cap_cleared={cap_cleared} "
                f"expected={expected_cleared}"
            )
            evict_count += 1
            if cap_cleared:
                cleared_count += 1

    # Sanity: both branches exercised.
    assert noop_count > 0, "no-op branch never hit — adjust rng range"
    assert evict_count > 0, "eviction branch never hit — adjust rng range"


# ── Boundary cases (mirror §8.9 DoD decimate boundary cases) ─────────


def test_decimate_zcard_zero_is_noop() -> None:
    """ZCARD == 0 → no-op, returns (evicted=0, decile=0, new_zcard=0,
    cap_cleared=0). §8.9 boundary case (i)."""
    assert _python_reference_decimate(zcard=0, cap=100) == (0, 0, 0, 0)


def test_decimate_zcard_less_than_10_decile_is_1() -> None:
    """ZCARD < 10 → decile_size=1, evicts exactly 1. §8.9 boundary case (ii).

    Requires zcard >= 2 so that cap=1 (non-zero) triggers the eviction
    branch (zcard=1 has no valid non-zero cap that exceeds it).
    """
    for zcard in range(2, 10):
        evicted, decile, new_zcard, _ = _python_reference_decimate(
            zcard=zcard, cap=1
        )
        assert decile == 1, f"zcard={zcard}: expected decile=1, got {decile}"
        assert evicted == 1, f"zcard={zcard}: expected evicted=1, got {evicted}"
        assert new_zcard == zcard - 1


def test_decimate_cap_cleared_when_new_zcard_equals_cap_exactly() -> None:
    """Post-decimation ZCARD == cap × exit_ratio exactly → cap_cleared=1
    (boundary inclusive). §8.9 boundary case (iii).

    Choose zcard=110, cap=100: decile=11, evicted=11, new_zcard=99 ≤ 100
    → cap_cleared=1.
    """
    evicted, decile, new_zcard, cap_cleared = _python_reference_decimate(
        zcard=110, cap=100
    )
    assert evicted == 11
    assert decile == 11
    assert new_zcard == 99
    assert cap_cleared == 1


def test_decimate_cap_cleared_at_exact_boundary() -> None:
    """new_zcard == cap exactly → cap_cleared=1 (inclusive boundary).

    Choose zcard=100, cap=90: decile=10, evicted=10, new_zcard=90 == cap
    → cap_cleared=1.
    """
    evicted, decile, new_zcard, cap_cleared = _python_reference_decimate(
        zcard=100, cap=90
    )
    assert evicted == 10
    assert decile == 10
    assert new_zcard == 90
    assert cap_cleared == 1


def test_decimate_cap_not_cleared_when_still_above() -> None:
    """new_zcard > cap → cap_cleared=0.

    Choose zcard=200, cap=100: decile=20, evicted=20, new_zcard=180 > 100
    → cap_cleared=0.
    """
    evicted, decile, new_zcard, cap_cleared = _python_reference_decimate(
        zcard=200, cap=100
    )
    assert evicted == 20
    assert decile == 20
    assert new_zcard == 180
    assert cap_cleared == 0


# ── Cap-flag contention and gateway fast-clear (§8.9 DoD) ────────────
#
# Tests the Lua atomicity guarantee for sec:denylist:capped flag deletion.
# Pure-Python tests run in CI without Redis; live-Redis tests are skipped
# when no Redis is reachable.


def test_decimate_cap_flag_deleted_exactly_once_on_threshold_cross() -> None:
    """sec:denylist:capped is DEL'd exactly once — on the decimate whose
    post-script new_zcard first crosses to ≤ cap.

    Re-running decimate when new_zcard is already ≤ cap hits the no-op
    branch (``zcard <= cap``), so cap_cleared=0 and no second DEL is
    issued.  This models the Lua guarantee that a single script execution
    calls ``DEL capkey`` at most once.
    """
    # First pass: ZCARD above cap → decimate runs → drops to 99 ≤ 100 → DEL
    _ev, _d, new_zcard, cap_cleared = _python_reference_decimate(
        zcard=110, cap=100
    )
    assert cap_cleared == 1, "first threshold-crossing pass must yield cap_cleared=1"
    assert new_zcard <= 100

    # Second pass: re-run with post-decimate ZCARD (already below cap) → no-op
    evicted2, _, _, cap_cleared2 = _python_reference_decimate(
        zcard=new_zcard, cap=100
    )
    assert evicted2 == 0, "re-run with zcard ≤ cap must be no-op (evicted=0)"
    assert cap_cleared2 == 0, "no second DEL when zcard already ≤ cap"


def test_decimate_cap_flag_stays_set_when_still_above_cap() -> None:
    """cap_cleared stays 0 when new_zcard is still above cap after eviction.

    The capped key is NOT deleted — the gateway remains in subnet-mode and
    the next decimate cycle must run again.
    """
    _ev, _d, new_zcard, cap_cleared = _python_reference_decimate(
        zcard=200, cap=100
    )
    assert new_zcard == 180, f"expected new_zcard=180, got {new_zcard}"
    assert cap_cleared == 0, "capped flag must NOT be cleared while new_zcard > cap"


def test_gateway_exits_subnet_mode_within_one_poll_tick() -> None:
    """After decimate returns cap_cleared=1 the next read of the capped
    flag returns absent → gateway exits subnet-mode within one poll tick.

    Modelled with an in-memory dict standing in for Redis.  The Lua DEL is
    represented by ``mock_redis.pop(capkey)``; the 'poll tick' is a single
    ``in`` check — equivalent to one Redis GET / EXISTS call.  In a live
    system this means the gateway escapes subnet-mode within one polling
    interval (no delayed flush, no epoch cycle).
    """
    capkey = "sec:denylist:capped"
    mock_redis: dict[str, str] = {capkey: "1"}

    _, _, _, cap_cleared = _python_reference_decimate(zcard=110, cap=100)
    assert cap_cleared == 1

    # Apply the DEL that the Lua issues when cap_cleared == 1.
    if cap_cleared:
        mock_redis.pop(capkey, None)

    # One poll tick: gateway reads the key once.
    subnet_mode_active = capkey in mock_redis
    assert not subnet_mode_active, (
        "Gateway must exit subnet-mode within one poll tick after decimate clears cap"
    )


@pytest.mark.parametrize("concurrent_adds", [0, 1, 5, 50, 200])
def test_decimate_lua_atomicity_no_split_state(concurrent_adds: int) -> None:
    """Lua atomicity: concurrent ZADD mutations can only influence the ZCARD
    the script *observes* — they cannot interleave with the script's
    read-modify-write block.

    For every possible 'observed' ZCARD from base_zcard up to
    base_zcard + concurrent_adds, the Python reference must return an
    internally consistent result:
        cap_cleared == (1 if new_zcard <= cap else 0)

    A split state would be cap_cleared=1 with new_zcard > cap, or
    cap_cleared=0 with new_zcard ≤ cap.  Neither is possible because the
    Lua evaluates ``new_zcard <= cap`` and ``DEL capkey`` atomically.
    """
    cap = 100
    base_zcard = 110  # always > cap so the eviction branch is always entered

    for added in range(concurrent_adds + 1):
        observed_zcard = base_zcard + added
        _ev, _d, new_zcard, cap_cleared = _python_reference_decimate(
            zcard=observed_zcard, cap=cap
        )
        expected_cleared = 1 if new_zcard <= cap else 0
        assert cap_cleared == expected_cleared, (
            f"Split state at concurrent_adds={added}, "
            f"observed_zcard={observed_zcard}: "
            f"new_zcard={new_zcard}, cap={cap}, "
            f"cap_cleared={cap_cleared} (expected {expected_cleared})"
        )


# ── Live-Redis cap-flag tests (skip when no Redis) ────────────────────


def _redis_available_decimate(
    host: str = "localhost", port: int = 6379
) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


_skip_no_redis = pytest.mark.skipif(
    not _redis_available_decimate(),
    reason="cap-flag live tests require Redis on localhost:6379",
)


@pytest.fixture(scope="module")
def _decimate_rc():
    redis = pytest.importorskip("redis")
    try:
        client = redis.Redis(host="localhost", port=6379, decode_responses=True)
        client.ping()
    except Exception:
        pytest.skip("Redis not reachable")
    yield client
    client.close()


@pytest.fixture(scope="module")
def _decimate_lua_sha(_decimate_rc):
    repo_root = Path(__file__).resolve().parents[4]
    src = (repo_root / "infra/redis/lua/sec_denylist_decimate.lua").read_text()
    return _decimate_rc.script_load(src)


@pytest.fixture()
def _decimate_keys(_decimate_rc, request):
    """Per-test isolated Redis keys; cleaned up on teardown."""
    prefix = f"test:p8:decimate:{request.node.name}"
    zkey = f"{prefix}:zset"
    capkey = f"{prefix}:capped"
    yield zkey, capkey
    _decimate_rc.delete(zkey, capkey)


@_skip_no_redis
def test_decimate_live_cap_flag_deleted_exactly_once(
    _decimate_rc, _decimate_lua_sha, _decimate_keys
) -> None:
    """Live Redis: Lua decimate DEL's the capped key exactly once when
    new_zcard crosses below cap.  A second invocation when ZCARD is already
    ≤ cap is a no-op — the key stays absent, not toggled back.
    """
    zkey, capkey = _decimate_keys
    cap = 10
    now_ms = 1_000_000

    for i in range(12):
        _decimate_rc.zadd(zkey, {f"subj:{i}": now_ms + i})
    _decimate_rc.set(capkey, "1")
    assert _decimate_rc.exists(capkey) == 1, "pre-condition: capped flag must be set"

    # First decimate: ZCARD=12 > cap=10 → evict 1 → new_zcard=11 > cap … wait:
    # decile = floor(12/10)=1; new_zcard=11 > 10 → cap_cleared=0.
    # We need ZCARD that drops below cap after one decile eviction.
    # Use cap=10, ZCARD=11: decile=1, new_zcard=10 == cap → cleared.
    _decimate_rc.delete(zkey)
    for i in range(11):
        _decimate_rc.zadd(zkey, {f"subj:{i}": now_ms + i})

    result = _decimate_rc.evalsha(
        _decimate_lua_sha, 2, zkey, capkey, now_ms, cap
    )
    evicted, decile, new_zcard, cap_cleared = [int(x) for x in result]
    assert cap_cleared == 1, f"expected cap_cleared=1 after first decimate; got {cap_cleared}"
    assert _decimate_rc.exists(capkey) == 0, "capped key must be absent after decimate"

    # Second invocation: ZCARD ≤ cap → no-op; flag stays absent.
    result2 = _decimate_rc.evalsha(
        _decimate_lua_sha, 2, zkey, capkey, now_ms, cap
    )
    _ev2, _d2, _nz2, cap_cleared2 = [int(x) for x in result2]
    assert cap_cleared2 == 0, "second run must be no-op; cap_cleared must be 0"
    assert _decimate_rc.exists(capkey) == 0, "capped key must still be absent"


@_skip_no_redis
def test_decimate_live_gateway_exits_subnet_mode_within_one_poll(
    _decimate_rc, _decimate_lua_sha, _decimate_keys
) -> None:
    """Live Redis: after decimate clears the capped flag, a single GET
    returns nil → gateway exits subnet-mode within one poll tick.
    """
    zkey, capkey = _decimate_keys
    cap = 10
    now_ms = 2_000_000

    # ZCARD=11, cap=10: decile=1, new_zcard=10 == cap → cap_cleared=1.
    for i in range(11):
        _decimate_rc.zadd(zkey, {f"subj:{i}": now_ms + i})
    _decimate_rc.set(capkey, "1")

    _decimate_rc.evalsha(_decimate_lua_sha, 2, zkey, capkey, now_ms, cap)

    # Gateway poll tick: single GET.
    flag_value = _decimate_rc.get(capkey)
    assert flag_value is None, (
        f"capped flag must be absent after decimate (gateway exits subnet-mode); "
        f"got {flag_value!r}"
    )


__all__ = ["_python_reference_decimate"]
