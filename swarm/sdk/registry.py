"""Agent registry + heartbeat tracker.

Two views are maintained against the bus's underlying store:

  - `agent_registry`  : hash of instance_id → AgentSpec (JSON)
  - `agent_heartbeats`: hash of instance_id → ISO-8601 UTC timestamp

For RedisStreamsBus the registry uses Redis hashes with a TTL on the
hash key (so a crashed agent eventually evaporates). For InMemoryBus
the registry is an in-process dict — fine for tests.

`is_stale(instance_id, heartbeat_sec)` returns True if the last heartbeat
is older than `3 × heartbeat_sec` (the standard "missed-3-beats = dead"
rule from §3.2 of the roadmap).
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .agent import AgentSpec

REGISTRY_KEY = "agent_registry"
HEARTBEAT_KEY = "agent_heartbeats"
DEAD_BEAT_MULTIPLIER = 3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat(timespec="seconds")


class AgentRegistry:
    """Backend-agnostic registry. Backed by Redis hash or in-process dict."""

    def __init__(self, backend: Any | None = None, ttl_sec: int = 30) -> None:
        # `backend` may be a redis.Redis client (duck-typed via `hset`) or
        # None for an in-process dict (tests).
        self._backend = backend
        self._ttl_sec = ttl_sec
        self._lock = threading.RLock()
        self._mem_registry: dict[str, str] = {}
        self._mem_heartbeats: dict[str, str] = {}

    # ── Registration ────────────────────────────────────────────────────
    def register(self, spec: AgentSpec) -> None:
        payload = json.dumps(_spec_to_jsonable(spec), sort_keys=True)
        with self._lock:
            if self._backend is None:
                self._mem_registry[spec.instance_id] = payload
                self._mem_heartbeats[spec.instance_id] = _utc_now_iso()
            else:
                self._backend.hset(REGISTRY_KEY, spec.instance_id, payload)
                self._backend.expire(REGISTRY_KEY, self._ttl_sec * 4)
                self._backend.hset(HEARTBEAT_KEY, spec.instance_id, _utc_now_iso())
                self._backend.expire(HEARTBEAT_KEY, self._ttl_sec * 4)

    def deregister(self, instance_id: str) -> None:
        with self._lock:
            if self._backend is None:
                self._mem_registry.pop(instance_id, None)
                self._mem_heartbeats.pop(instance_id, None)
            else:
                self._backend.hdel(REGISTRY_KEY, instance_id)
                self._backend.hdel(HEARTBEAT_KEY, instance_id)

    def heartbeat(self, instance_id: str) -> None:
        ts = _utc_now_iso()
        with self._lock:
            if self._backend is None:
                if instance_id in self._mem_registry:
                    self._mem_heartbeats[instance_id] = ts
            else:
                self._backend.hset(HEARTBEAT_KEY, instance_id, ts)
                self._backend.expire(HEARTBEAT_KEY, self._ttl_sec * 4)

    # ── Inspection ──────────────────────────────────────────────────────
    def all_specs(self) -> dict[str, AgentSpec]:
        with self._lock:
            raw = (
                dict(self._mem_registry)
                if self._backend is None
                else _hgetall_str(self._backend, REGISTRY_KEY)
            )
        return {iid: _spec_from_jsonable(json.loads(v)) for iid, v in raw.items()}

    def heartbeats(self) -> dict[str, str]:
        with self._lock:
            if self._backend is None:
                return dict(self._mem_heartbeats)
            return _hgetall_str(self._backend, HEARTBEAT_KEY)

    def is_stale(self, instance_id: str, heartbeat_sec: int) -> bool:
        beats = self.heartbeats()
        last = beats.get(instance_id)
        if last is None:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return True
        deadline = _utc_now() - timedelta(seconds=heartbeat_sec * DEAD_BEAT_MULTIPLIER)
        return last_dt < deadline


# ── helpers ─────────────────────────────────────────────────────────────


def _spec_to_jsonable(spec: AgentSpec) -> dict[str, Any]:
    d = asdict(spec)
    d["subscribes"] = list(spec.subscribes)
    d["publishes"] = list(spec.publishes)
    return d


def _spec_from_jsonable(data: dict[str, Any]) -> AgentSpec:
    return AgentSpec(
        name=str(data["name"]),
        instance_id=str(data["instance_id"]),
        subscribes=tuple(data.get("subscribes", [])),
        publishes=tuple(data.get("publishes", [])),
        pid=int(data.get("pid", 0)),
        started_at=str(data.get("started_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def _hgetall_str(client: Any, key: str) -> dict[str, str]:
    raw = client.hgetall(key) or {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        ks = k.decode() if isinstance(k, bytes) else str(k)
        vs = v.decode() if isinstance(v, bytes) else str(v)
        out[ks] = vs
    return out


def poll_heartbeats_from_host(
    host: str,
    port: int,
    timeout: float = 2.0,
) -> "tuple[bool, dict[str, str]]":
    """Attempt a Redis connection and return raw heartbeat data.

    Returns ``(available, beats)`` where *available* is ``False`` when
    Redis is unreachable (redis-py not installed, connection refused,
    timeout) and *beats* is an empty dict in that case.

    Lazy-imports ``redis`` so this module is importable without redis-py.
    Called by opsctl liveness to avoid a direct ``import redis`` in the
    ops-console boundary (opsctl must not import storage-mutator modules
    directly; only SDK seams may do so).
    """
    try:
        import redis as _r  # noqa: PLC0415
    except ImportError:
        return False, {}
    try:
        client = _r.Redis(
            host=host,
            port=port,
            socket_connect_timeout=timeout,
            socket_timeout=timeout,
        )
        client.ping()
    except Exception:  # noqa: BLE001
        return False, {}
    return True, _hgetall_str(client, HEARTBEAT_KEY)
