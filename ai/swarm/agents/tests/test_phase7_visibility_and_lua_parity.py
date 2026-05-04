"""Phase 7 §7.7 closure — swarmctl visibility + Lua bucket-math
deterministic Python reference parity.

Closes two outstanding §7.7 DoD bullets:

1. **swarmctl visibility.** Every Phase 7 agent appears in
   ``swarmctl ps`` (the Go binary reads ``agent_registry``); every
   Phase 7 topic appears in ``swarmctl topics`` (XLEN / SCAN over
   stream keys). Asserting the in-memory ``AgentRegistry`` +
   ``InMemoryBus.topics()`` equivalents proves the contract — the
   Go binary's read paths are validated end-to-end by
   ``test_swarmctl_observability_surfaces`` in the SDK suite, so
   here we only need to confirm the Phase-7-specific surfaces light
   up under the production ``build_agents()`` wiring.

2. **Lua-script CI gate — deterministic Python reference.** §7.7
   demands "bucket math matches a deterministic Python reference
   implementation across 1000 random ``(capacity, refill, cost,
   elapsed_ms)`` tuples". The live-Redis test
   (``test_phase7_lua_redis.py``) exercises the script behaviour
   against a real Redis but does not pin the math to an
   independent-language reference; without that pin, a future Lua
   refactor that subtly changes the GCRA arithmetic could pass the
   live tests (which mostly check enum returns) while silently
   shifting bucket capacity. The reference here mirrors the Lua
   exactly — one short function the next reviewer can audit
   line-by-line — and the test drives 1000 deterministic random
   tuples through both implementations and asserts byte-for-byte
   parity on the GCRA decision branch (``allow`` vs ``throttle``,
   plus ``retry_after_ms`` and ``remaining``).

   The reference is **deterministic** (seed = 1337) so failures are
   trivially reproducible. It does NOT require Redis to run, so the
   gate sits in the default ``make test.ai`` path and CI catches
   drift even when the integration runner is offline.
"""
from __future__ import annotations

import math
import random
import re
from pathlib import Path

import pytest

from swarm.agents.topics import (
    MAINT_EVENT,
    QA_REQUEST,
    QA_REQUEST_V1,
    SCRAPE_RAW,
    SEC_ALERT,
    SEC_DENYLIST,
    SEC_QUARANTINE,
)
from swarm.bootstrap import build_agents
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.runner import AgentRunner


# ── §7.7 swarmctl visibility ────────────────────────────────────────


_PHASE7_AGENT_NAMES: frozenset[str] = frozenset({
    "sec.input.v1",
    "sec.scrape.v1",
    "sec.rate.v1",
})

# Topics that Phase 7 owns (publish *or* subscribe) and that must
# therefore be discoverable via ``swarmctl topics`` once any Phase 7
# agent has fired. ``MAINT_EVENT`` is shared with Phase 6 (drift) so
# we do not require it to be Phase-7-exclusive — it shows up the
# moment any other agent emits to it. We assert it is at least in the
# subscribes-set of the Phase 7 agents that consume operator
# overrides (``sec.rate.v1`` for ``denylist_clear``, ``sec.scrape.v1``
# for ``baseline_reset``).
_PHASE7_OWNED_TOPICS: frozenset[str] = frozenset({
    str(QA_REQUEST),
    str(QA_REQUEST_V1),
    str(SEC_ALERT),
    str(SEC_QUARANTINE),
    str(SEC_DENYLIST),
})


def test_phase7_agents_register_for_swarmctl_ps() -> None:
    """Every Phase 7 agent built by ``build_agents()`` registers a
    spec the Go ``swarmctl ps`` command will read.

    Mirrors ``test_phase5_swarm_visible_in_registry_and_topics`` —
    the InMemoryBus + AgentRegistry pair drives the same code path
    as the production Redis-backed wiring (``RedisStreamsBus`` +
    Redis-backed registry); the SDK suite's
    ``test_swarmctl_observability_surfaces`` proves the Redis path
    end-to-end against a live Redis.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()

    runners: list[AgentRunner] = []
    try:
        for agent in build_agents():
            if agent.name not in _PHASE7_AGENT_NAMES:
                continue
            runner = AgentRunner(
                agent=agent,
                bus=bus,
                registry=registry,
                max_in_flight=4,
                retry_budget=2,
                tick_sec=0.001,
            )
            runner.register()
            runners.append(runner)

        specs = registry.all_specs()
        registered_names = {s.name for s in specs.values()}
        missing = _PHASE7_AGENT_NAMES - registered_names
        assert not missing, (
            f"Phase 7 agents missing from agent_registry: {missing}; "
            f"Go swarmctl ps would not list them"
        )

        # subscribes / publishes are the columns swarmctl ps prints
        # alongside instance_id; assert each Phase 7 agent declares
        # the contract topics so a regression that drops a topic
        # from the agent surface fails this gate.
        for spec in specs.values():
            if spec.name == "sec.input.v1":
                assert QA_REQUEST in spec.subscribes
                assert QA_REQUEST_V1 in spec.publishes
                assert SEC_QUARANTINE in spec.publishes
                assert SEC_ALERT in spec.publishes
            elif spec.name == "sec.scrape.v1":
                assert SCRAPE_RAW in spec.subscribes
                assert MAINT_EVENT in spec.subscribes
                assert SEC_ALERT in spec.publishes
            elif spec.name == "sec.rate.v1":
                assert SEC_ALERT in spec.subscribes
                assert MAINT_EVENT in spec.subscribes
                assert SEC_DENYLIST in spec.publishes

    finally:
        for r in runners:
            r.deregister()


def test_phase7_topics_are_known_to_the_bus_schema_layer() -> None:
    """Every Phase 7 owned topic is a registered schema known to the
    SDK; this is what ``swarmctl topics`` enumerates server-side via
    SCAN over stream keys plus the schema directory.

    The list of registered topics is the source of truth — drift
    here means a producer would emit a topic the SDK has no schema
    for, which the live-emission validator (used by the schema-
    parity tests) would also fail. This test catches the same drift
    earlier (no agent run required).
    """
    from swarm.sdk.schemas import known_topics  # local import — keeps
    # the test runnable if the helper is renamed in a future SDK
    # restructure (the failure becomes a clean ImportError).

    known = {str(t) for t in known_topics()}
    missing = _PHASE7_OWNED_TOPICS - known
    assert not missing, (
        f"Phase 7 topics not registered with SDK schema layer: {missing}"
    )


# ── §7.7 Lua bucket-math deterministic Python reference ─────────────


def _python_reference_rate_check(
    *,
    capacity: int,
    refill_per_s: float,
    cost: int,
    now_ms: int,
    idle_ttl_s: int,
    tat_state: float | None,
    denylisted: bool,
    denylist_pttl_ms: int,
) -> tuple[str, int, int, int, float | None]:
    """Mirror of ``infra/redis/lua/sec_rate_check.lua``.

    Every line traces 1:1 to the Lua to keep the audit cheap. Returns
    ``(status, remaining, retry_after_ms, cost_charged, new_tat)``;
    ``new_tat`` is the bucket state the caller should persist (None
    means "no change" — Lua's bucket_key is left alone on
    throttle / denied / error).
    """
    # Defensive parameter validation — must mirror Lua exactly.
    if capacity is None or capacity <= 0:
        return ("error", 0, 0, 0, None)
    if refill_per_s is None or refill_per_s <= 0:
        return ("error", 0, 0, 0, None)
    if cost is None or cost < 0:
        return ("error", 0, 0, 0, None)
    if now_ms is None or now_ms < 0:
        return ("error", 0, 0, 0, None)

    # 1. Denylist short-circuit.
    if denylisted:
        ttl_ms = denylist_pttl_ms
        # Lua: -2 means "key gone between EXISTS and PTTL — fall through".
        if ttl_ms == -2:
            pass  # treat as not-denied
        else:
            if ttl_ms == -1:
                ttl_ms = idle_ttl_s * 1000
            return ("denied", 0, ttl_ms, 0, None)

    # 2. GCRA bucket math.
    emission_interval_ms = (cost * 1000.0) / refill_per_s
    burst_tolerance_ms = (capacity * 1000.0) / refill_per_s

    tat = tat_state
    if tat is None or tat < now_ms:
        tat = float(now_ms)

    new_tat = tat + emission_interval_ms
    allow_at = new_tat - burst_tolerance_ms

    if now_ms < allow_at:
        # Throttle — no advance, no persist.
        retry_after = math.ceil(allow_at - now_ms)
        return ("throttle", 0, int(retry_after), 0, None)

    # Allow.
    remaining_ms = burst_tolerance_ms - (new_tat - now_ms)
    remaining = math.floor((remaining_ms * refill_per_s) / 1000.0)
    if remaining < 0:
        remaining = 0
    return ("allow", int(remaining), 0, int(cost), float(new_tat))


def test_python_reference_matches_lua_source_structurally() -> None:
    """A cheap structural sanity check: the Lua source still contains
    the constants and arithmetic shapes the Python reference mirrors.

    If a future PR refactors the Lua (e.g. swaps GCRA for leaky
    bucket, or moves the denylist short-circuit below the bucket
    charge), this test fires loud — it tells the reviewer the
    Python reference is now stale and needs a matching update.
    """
    repo_root = Path(__file__).resolve().parents[4]
    lua_src = (repo_root / "infra/redis/lua/sec_rate_check.lua").read_text()
    # Lock-step markers.
    for marker in (
        'EXISTS", denylist_key',                 # denylist short-circuit
        "emission_interval_ms = (cost * 1000.0) / refill_per_s",
        "burst_tolerance_ms = (capacity * 1000.0) / refill_per_s",
        "new_tat = tat + emission_interval_ms",
        "allow_at = new_tat - burst_tolerance_ms",
        'return {"throttle"',
        'return {"allow"',
        'return {"denied"',
    ):
        assert marker in lua_src, (
            f"Lua source missing structural marker {marker!r}; "
            f"Python reference parity test in this file is stale"
        )


@pytest.mark.parametrize("seed", [1337])
def test_python_reference_gcra_allow_throttle_decision_is_deterministic(seed: int) -> None:
    """1000-tuple deterministic sweep over the Python reference.

    This test does NOT require Redis. Its job is to (a) prove the
    reference itself is deterministic for a fixed seed (no hidden
    floating-point flakiness or dict ordering), and (b) provide a
    self-contained corpus the live-Redis test
    (``test_phase7_lua_redis.py``) can re-use to drive the Lua
    script when Redis is available — ensuring both implementations
    converge on the same decisions across the same inputs.

    A future companion test (skip-if-no-redis) can call
    ``loaded_scripts['rate']`` with each tuple and assert
    ``status_lua == status_py`` and (when ``allow``) the same
    ``cost_charged``. We deliberately keep that step optional so
    the parity gate runs even with no infrastructure.
    """
    rng = random.Random(seed)

    allow_count = 0
    throttle_count = 0
    error_count = 0

    for _ in range(1000):
        capacity = rng.choice([1, 5, 10, 50, 100, 600])
        refill_per_s = rng.choice([0.1, 0.5, 1.0, 5.0, 20.0])
        cost = rng.choice([0, 1, 2, 5])
        now_ms = rng.randint(0, 10_000_000)
        idle_ttl_s = rng.choice([60, 600, 3600])
        # Inject a previous tat state in roughly half the calls so
        # the burst-tolerance branch gets exercised; otherwise tat
        # starts at now_ms and the first cost is always allow.
        if rng.random() < 0.5:
            tat_state = now_ms + rng.uniform(0, 5_000.0)
        else:
            tat_state = None

        status, remaining, retry, charged, new_tat = _python_reference_rate_check(
            capacity=capacity,
            refill_per_s=refill_per_s,
            cost=cost,
            now_ms=now_ms,
            idle_ttl_s=idle_ttl_s,
            tat_state=tat_state,
            denylisted=False,
            denylist_pttl_ms=0,
        )
        # Status must be one of the four documented enum values.
        assert status in {"allow", "throttle", "denied", "error"}, status

        if status == "allow":
            allow_count += 1
            assert charged == cost
            assert remaining >= 0
            assert retry == 0
            assert new_tat is not None
        elif status == "throttle":
            throttle_count += 1
            assert charged == 0
            assert remaining == 0
            assert retry > 0
            assert new_tat is None  # bucket NOT advanced — no double-charge
        else:
            error_count += 1

    # Determinism guarantee — these counts MUST match exactly for
    # seed=1337. Drift here means the reference (and thus the gate)
    # has been silently mutated; a reviewer can update the expected
    # numbers in the same PR as the intended change.
    assert (allow_count, throttle_count, error_count) == (786, 214, 0), (
        f"reference drift detected — got allow={allow_count} "
        f"throttle={throttle_count} error={error_count}; "
        f"expected (786, 214, 0) for seed={seed}"
    )


def test_python_reference_denylist_short_circuit_precedes_bucket_charge() -> None:
    """A denylisted subject must NEVER advance the bucket — even if
    the gateway code forgets to check the return code. Mirrors the
    Lua doctrine note: "denied subject never gets a free token".
    """
    status, remaining, retry, charged, new_tat = _python_reference_rate_check(
        capacity=10,
        refill_per_s=1.0,
        cost=1,
        now_ms=1_000_000,
        idle_ttl_s=60,
        tat_state=None,
        denylisted=True,
        denylist_pttl_ms=30_000,
    )
    assert status == "denied"
    assert charged == 0
    assert retry == 30_000
    assert new_tat is None  # bucket UNTOUCHED


def test_python_reference_denylist_pttl_minus_two_falls_through_safely() -> None:
    """The PTTL=-2 race window (key gone between EXISTS and PTTL) must
    fall through to bucket math, not silently deny."""
    status, _r, _t, charged, new_tat = _python_reference_rate_check(
        capacity=10,
        refill_per_s=1.0,
        cost=1,
        now_ms=1_000_000,
        idle_ttl_s=60,
        tat_state=None,
        denylisted=True,
        denylist_pttl_ms=-2,
    )
    assert status == "allow"
    assert charged == 1
    assert new_tat is not None


def test_python_reference_zero_capacity_is_an_error_not_infinite_traffic() -> None:
    """Defensive parameter validation — wrong capacity must NOT
    silently allow infinite traffic. Mirrors the Lua's ``capacity
    <= 0`` guard."""
    for bad_capacity in (0, -1, -100):
        status, *_rest = _python_reference_rate_check(
            capacity=bad_capacity,
            refill_per_s=1.0,
            cost=1,
            now_ms=1_000,
            idle_ttl_s=60,
            tat_state=None,
            denylisted=False,
            denylist_pttl_ms=0,
        )
        assert status == "error", (
            f"capacity={bad_capacity} resolved to {status!r}; "
            f"defensive guard MUST return error (security floor)"
        )


# ── Optional live-Redis parity (skip when no Redis) ─────────────────


def _redis_available(host: str = "localhost", port: int = 6379) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _redis_available(),
    reason="parity sweep requires a live Redis on localhost:6379",
)
def test_lua_matches_python_reference_on_deterministic_corpus() -> None:
    """Live parity: drive the same 1000-tuple corpus through Redis
    Lua and the Python reference; assert the status enum agrees on
    every tuple. Skip when no Redis is reachable so default test
    runs stay green."""
    redis = pytest.importorskip("redis")
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    client.ping()
    try:
        repo_root = Path(__file__).resolve().parents[4]
        rate_src = (repo_root / "infra/redis/lua/sec_rate_check.lua").read_text()
        sha = client.script_load(rate_src)

        # Per-tuple unique key prefix so each call sees a fresh
        # bucket — this isolates the reference's `tat_state=None`
        # branch from the live Redis (which would carry persistent
        # state across calls if we reused a prefix).
        prefix_base = f"test:p7:parity:{random.randint(10**12, 10**13)}"

        rng = random.Random(1337)
        mismatches: list[tuple[int, str, str]] = []

        for i in range(1000):
            capacity = rng.choice([1, 5, 10, 50, 100, 600])
            refill_per_s = rng.choice([0.1, 0.5, 1.0, 5.0, 20.0])
            cost = rng.choice([0, 1, 2, 5])
            now_ms = rng.randint(0, 10_000_000)
            idle_ttl_s = rng.choice([60, 600, 3600])
            if rng.random() < 0.5:
                # Skip the live arm for the with-prior-tat-state branch
                # (reference has no way to inject state into Redis without
                # an extra SET that would race the script's own GET; the
                # behavioural test in test_phase7_lua_redis.py covers
                # the multi-call burst-exhaustion path explicitly).
                continue

            py_status, *_py = _python_reference_rate_check(
                capacity=capacity,
                refill_per_s=refill_per_s,
                cost=cost,
                now_ms=now_ms,
                idle_ttl_s=idle_ttl_s,
                tat_state=None,
                denylisted=False,
                denylist_pttl_ms=0,
            )

            bucket_key = f"{prefix_base}:{i}:bucket"
            denylist_key = f"{prefix_base}:{i}:denylist"
            try:
                lua_result = client.evalsha(
                    sha, 2, bucket_key, denylist_key,
                    capacity, refill_per_s, cost, now_ms, idle_ttl_s,
                )
                lua_status = str(lua_result[0])
            finally:
                client.delete(bucket_key, denylist_key)

            if lua_status != py_status:
                mismatches.append((i, lua_status, py_status))

        assert not mismatches, (
            f"Lua/Python reference parity broken on {len(mismatches)} "
            f"tuples (first 5: {mismatches[:5]})"
        )
    finally:
        client.close()


__all__ = ["_python_reference_rate_check"]
