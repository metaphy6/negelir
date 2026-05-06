"""Phase 8 §8.15.3 — Postgres advisory-lock key registry.

Every cross-process advisory lock taken in the maintenance plane
gets a UNIQUE int8 key. Collisions are silent corruption, so the
keys live here as an enum-like dict and a uniqueness test pins the
contract.

Conventions:

* Keys are int8 (Postgres ``bigint``) so they fit
  :func:`pg_try_advisory_lock`/`pg_try_advisory_xact_lock`.
* The high bit is reserved (we stay in [1, 2^31) to keep room for
  future per-tenant prefixing).
* Names are ``UPPER_SNAKE``; callers reference the symbol, never
  the integer.
* Adding a new lock = add a row + bump ``swarm`` minor.
"""
from __future__ import annotations

from typing import Final


# §8.5 DLQ supervisor — only one replica replays poison messages at a time.
LOCK_MAINT_DLQ_REPLAY: Final[int] = 8_001

# §8.6 schema sentinel — Detector B PG-column scan holds this while
# walking ``information_schema.columns``.
LOCK_MAINT_SCHEMA_SCAN: Final[int] = 8_002

# §8.7 sec maintenance — pattern_allowlist FP-loop promotion sweep
# (state codec p→a→e). Single-writer to keep the codec linear.
LOCK_MAINT_SEC_ALLOWLIST: Final[int] = 8_003

# §8.8 denylist decimation — sweeper holds while running the Lua
# atomic eviction over the Redis sorted set; serializes with itself.
LOCK_MAINT_SEC_DECIMATE: Final[int] = 8_004

# §8.14 audit-log pruner — partition rotation + drop-old runs under
# this key so two cron pods don't double-drop.
LOCK_MAINT_AUDIT_PRUNE: Final[int] = 8_005

# §8.2 scaler — leader-only decision emission. The Phase 14 K8s
# lease driver will use this as the lease key when both deployments
# share a Postgres instance.
LOCK_MAINT_SCALER_LEADER: Final[int] = 8_006


# Single source of truth — the uniqueness test reads ALL_LOCK_KEYS.
ALL_LOCK_KEYS: dict[str, int] = {
    "LOCK_MAINT_DLQ_REPLAY": LOCK_MAINT_DLQ_REPLAY,
    "LOCK_MAINT_SCHEMA_SCAN": LOCK_MAINT_SCHEMA_SCAN,
    "LOCK_MAINT_SEC_ALLOWLIST": LOCK_MAINT_SEC_ALLOWLIST,
    "LOCK_MAINT_SEC_DECIMATE": LOCK_MAINT_SEC_DECIMATE,
    "LOCK_MAINT_AUDIT_PRUNE": LOCK_MAINT_AUDIT_PRUNE,
    "LOCK_MAINT_SCALER_LEADER": LOCK_MAINT_SCALER_LEADER,
}


def ensure_unique(registry: dict[str, int] | None = None) -> bool:
    """Validate that every registered advisory-lock key value is unique.

    Per ROADMAP §8.15.3 binding: callers (boot validation in any
    agent that uses advisory locks) invoke this once at startup to
    refuse a duplicate-key configuration loud rather than ship a
    silent collision into prod. Returns ``True`` on success; raises
    ``ValueError`` listing the offending entries on collision.
    """
    src = registry if registry is not None else ALL_LOCK_KEYS
    seen: dict[int, list[str]] = {}
    for name, value in src.items():
        seen.setdefault(int(value), []).append(name)
    dupes = {v: names for v, names in seen.items() if len(names) > 1}
    if dupes:
        raise ValueError(
            "duplicate advisory-lock key value(s): "
            + ", ".join(f"{v} → {names}" for v, names in sorted(dupes.items()))
        )
    return True


__all__ = [
    "ALL_LOCK_KEYS",
    "LOCK_MAINT_AUDIT_PRUNE",
    "LOCK_MAINT_DLQ_REPLAY",
    "LOCK_MAINT_SCALER_LEADER",
    "LOCK_MAINT_SCHEMA_SCAN",
    "LOCK_MAINT_SEC_ALLOWLIST",
    "LOCK_MAINT_SEC_DECIMATE",
    "ensure_unique",
]
