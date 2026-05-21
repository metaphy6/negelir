"""Phase 8 §8.7 + §8.8 — `maint.sec.v1` security maintenance reactor.

Combines two responsibilities (one agent, one process):

§8.7 — **pattern_allowlist false-positive feedback loop.** Listens
for ``maint.event.v1{kind=quarantine_clear}`` (operator confirms a
quarantined sample was a FP) and promotes the trigger pattern from
state ``p`` (pending) → ``a`` (active) in the
``pattern_allowlist`` table. After ``cfg.maint_sec_pattern_ttl_s``
the pattern transitions ``a`` → ``e`` (expired) and stops
suppressing the parent rule.

§8.8 — **denylist decimation.** A scheduled sweeper plus an
operator-driven ``denylist_decimate_now`` command. Both run the
same Lua atomic sweep (``infra/redis/lua/sec_denylist_decimate.lua``)
which evicts the bottom decile (oldest entries by score) when the
sorted set exceeds ``cfg.sec_denylist_decimate_threshold``. The Go
gateway has an embedded copy of the same script
(``server/internal/sec/embedded/``) so the parity test pins they
stay byte-equivalent.

Boundaries:

* Single-instance (advisory lock ``LOCK_MAINT_SEC_ALLOWLIST`` for
  the FP loop, ``LOCK_MAINT_SEC_DECIMATE`` for the sweeper).
* Storage adapter is dependency-injected (Postgres + Redis); v1
  ships in-memory shims for tests and a clear contract for the
  production driver to land in §8.7b.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol
from uuid import uuid4

from common.config import cfg as _cfg

from ...sdk.leader import Leader, SingleProcessLeader
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck
from ..topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from ._liveness import LivenessMixin
from ._pause_state import PauseState

_log = logging.getLogger("swarm.agents.maint.sec")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


# Allowed states for pattern_allowlist.state codec — see
# migrations/010_pattern_allowlist.sql for the column definition.
ALLOWED_PATTERN_STATES: frozenset[str] = frozenset({"p", "a", "e"})


# ── Storage adapter protocols ───────────────────────────────────────────
class PatternAllowlistStore(Protocol):
    """Per §8.7 binding — the FP loop talks to one of these."""

    def upsert_pending(self, pattern: str, *, qid: str, now_iso: str) -> bool: ...
    def promote_to_active(self, pattern: str, *, now_iso: str,
                          ttl_s: int) -> bool: ...
    def expire_due(self, *, now_iso: str) -> list[str]:
        """Return the list of patterns moved a→e in this sweep."""


class DenylistDecimator(Protocol):
    """Per §8.8 binding — the sweeper talks to one of these."""

    def cardinality(self) -> int: ...
    def decimate(self, *, now_ms: int, cap: int) -> dict:
        """Run the Lua atomic sweep. Returns at minimum
        ``{evicted_count, decile_size, new_zcard, cap_cleared}``."""


# ── In-memory test shims ────────────────────────────────────────────────
@dataclass
class InMemoryPatternStore:
    """Simple in-process implementation for tests + bootstrap.

    Real driver (Phase 8.7b) hits Postgres via psycopg with the
    advisory lock ``LOCK_MAINT_SEC_ALLOWLIST``.

    Thread-safety model (mirrors ``pg_advisory_lock`` semantics):
    ``_lock`` is acquired for any operation that touches *both*
    ``rows`` (the DB-row state) and ``_active_cache`` (the
    in-process active-pattern cache).  ``read_eval_snapshot``
    acquires the same lock so a concurrent ``promote_to_active``
    cannot produce a split state where the DB row says ``'a'`` but
    the cache has not yet been updated (or vice-versa)."""

    rows: dict[str, dict] = field(default_factory=dict)
    # pg_advisory_lock analogue — held while updating both `rows`
    # and `_active_cache` so readers always see a consistent pair.
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False, compare=False
    )
    # Application-level cache of currently-active patterns,
    # always kept in sync with rows[p]["state"] == "a" under _lock.
    _active_cache: set = field(
        default_factory=set, init=False, repr=False, compare=False
    )

    def upsert_pending(self, pattern: str, *, qid: str, now_iso: str) -> bool:
        row = self.rows.get(pattern)
        if row is None:
            self.rows[pattern] = {"state": "p", "qids": [qid], "ts": now_iso}
            return True
        if row["state"] in ("p", "a"):
            if qid not in row["qids"]:
                row["qids"].append(qid)
            return False
        # e → re-open as p
        row["state"] = "p"
        row["qids"] = [qid]
        row["ts"] = now_iso
        return True

    def promote_to_active(self, pattern: str, *, now_iso: str,
                          ttl_s: int) -> bool:
        with self._lock:
            row = self.rows.get(pattern)
            if row is None or row["state"] != "p":
                return False
            row["state"] = "a"
            row["promoted_at"] = now_iso
            row["ttl_s"] = ttl_s
            self._active_cache.add(pattern)
            return True

    def expire_due(self, *, now_iso: str) -> list[str]:
        """Mark active rows past their TTL as expired; prune pending rows
        older than ``cfg.maint_sec_pattern_pending_ttl_days``.

        Returns the list of patterns transitioned ``a`` → ``e`` (the
        production Postgres driver does an UPDATE/RETURNING; this
        shim mirrors the same semantics for tests).
        """
        from datetime import datetime, timezone
        now = datetime.fromisoformat(now_iso)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        pending_ttl_s = int(_cfg.maint_sec_pattern_pending_ttl_days) * 86_400
        expired: list[str] = []
        to_prune: list[str] = []
        for pattern, row in list(self.rows.items()):
            state = row.get("state")
            if state == "a":
                promoted_at = row.get("promoted_at")
                ttl_s = int(row.get("ttl_s") or 0)
                if promoted_at and ttl_s > 0:
                    promoted = datetime.fromisoformat(promoted_at)
                    if promoted.tzinfo is None:
                        promoted = promoted.replace(tzinfo=timezone.utc)
                    if (now - promoted).total_seconds() >= ttl_s:
                        row["state"] = "e"
                        expired.append(pattern)
            elif state == "p" and pending_ttl_s > 0:
                ts = row.get("ts")
                if ts:
                    created = datetime.fromisoformat(ts)
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if (now - created).total_seconds() >= pending_ttl_s:
                        to_prune.append(pattern)
        for pattern in to_prune:
            del self.rows[pattern]
        # Keep _active_cache consistent with newly-expired rows.
        with self._lock:
            for pattern in expired:
                self._active_cache.discard(pattern)
        return expired

    def read_eval_snapshot(self, pattern: str) -> "tuple[str, bool] | None":
        """Read ``(row_state, in_active_cache)`` under the advisory lock.

        Returns ``None`` if the pattern is not known.  A consistent
        snapshot always satisfies ``row_state == 'a' ↔ in_active_cache``.
        Used by ``sec.input.v1`` evaluation and the promote-race proof test.
        """
        with self._lock:
            row = self.rows.get(pattern)
            if row is None:
                return None
            return row["state"], pattern in self._active_cache

    def _reset_to_pending(self, pattern: str, *, qid: str, now_iso: str) -> None:
        """Test helper — atomically reset a pattern to ``pending`` and clear
        it from ``_active_cache`` (simulates a fresh operator cycle)."""
        with self._lock:
            row = self.rows.get(pattern)
            if row is None:
                self.rows[pattern] = {"state": "p", "qids": [qid], "ts": now_iso}
            else:
                row["state"] = "p"
                row["qids"] = [qid]
                row["ts"] = now_iso
                row.pop("promoted_at", None)
                row.pop("ttl_s", None)
            self._active_cache.discard(pattern)


@dataclass
class InMemoryDecimator:
    """Simple counting denylist for tests."""

    entries: dict[str, float] = field(default_factory=dict)
    last_evicted: int = 0

    def cardinality(self) -> int:
        return len(self.entries)

    def decimate(self, *, now_ms: int, cap: int) -> dict:
        if len(self.entries) <= cap:
            return {"evicted_count": 0, "decile_size": 0,
                    "new_zcard": len(self.entries),
                    "cap_cleared": False}
        decile = max(1, len(self.entries) // 10)
        # Evict oldest by score.
        ordered = sorted(self.entries.items(), key=lambda kv: kv[1])
        for k, _ in ordered[:decile]:
            del self.entries[k]
        self.last_evicted = decile
        return {"evicted_count": decile, "decile_size": decile,
                "new_zcard": len(self.entries),
                "cap_cleared": len(self.entries) <= cap}


# ── Agent ───────────────────────────────────────────────────────────────
class MaintSecAgent(LivenessMixin):
    """`maint.sec.v1` reactor — combines §8.7 FP loop + §8.8 decimator."""

    name = "maint.sec.v1"
    subscribes: tuple[Topic, ...] = (MAINT_EVENT, SEC_ALERT)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK)

    def __init__(
        self,
        *,
        pattern_store: PatternAllowlistStore | None = None,
        decimator: DenylistDecimator | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_ms: Callable[[], int] | None = None,
        new_id: Callable[[], str] | None = None,
        liveness_clock: Callable[[], float] | None = None,
        leader: Leader | None = None,
    ) -> None:
        self._patterns = pattern_store if pattern_store is not None else InMemoryPatternStore()
        self._decimator = decimator if decimator is not None else InMemoryDecimator()
        self._clock_iso = clock_iso or _utc_iso
        self._clock_ms = clock_ms
        self._new_id = new_id or _new_id
        # Bounded LRU dedup of (request_id) for at-least-once safety.
        self._req_lru: "OrderedDict[str, None]" = OrderedDict()
        # §8.13.5 pause/isolation matrix.
        self._pause = PauseState()
        self._leader: Leader = leader if leader is not None else SingleProcessLeader(name=self.name)
        # §8.8 hysteresis: epoch-ms of the last *successful* decimate.
        # Drives the global ``cfg.maint_sec_decimate_min_interval_s``
        # window; the denylist zset is one shared resource so the
        # signal is global, not per-subject.
        self._last_decimate_ms: int = 0
        # §8.8 alert-trigger dedup: bound the LRU of recently-seen
        # SecAlert ``alert_id`` values so the sweeper does not double-
        # fire on bus redeliveries.
        self._alert_lru: "OrderedDict[str, None]" = OrderedDict()
        self._liveness_init(liveness_clock=liveness_clock)

    # ── Bus contract ──────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        # Non-leader: observe only, do not publish.
        if not self._leader.is_leader():
            return ()
        topic = msg.envelope.topic
        if topic == SEC_ALERT:
            return list(self._handle_sec_alert(msg))
        if topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        kind = payload.get("kind")
        if kind == "quarantine_clear":
            return list(self._handle_quarantine_clear(msg, payload))
        if kind == "denylist_decimate_now":
            return list(self._handle_decimate(msg, payload))
        if kind == "maint_pause":
            return list(self._handle_pause(msg, payload, paused=True))
        if kind == "maint_resume":
            return list(self._handle_pause(msg, payload, paused=False))
        return ()

    # ── maint_pause / maint_resume (§8.13.5 idempotency matrix) ──
    def _handle_pause(self, msg: Message, payload: dict,
                      *, paused: bool) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target = str(payload.get("target") or "")
        if not request_id:
            return
        if target not in ("all", self.name):
            yield self._ack(msg, request_id, accepted=True, reason="not_targeted")
            return
        now_ns = self._now_ms() * 1_000_000
        self._pause.expire_if_due(now_ns)
        if paused:
            ttl_s = int(payload.get("ttl_s") or 0) or int(_cfg.maint_pause_default_ttl_s)
            res = self._pause.apply_pause(ttl_s=ttl_s, now_ns=now_ns)
        else:
            res = self._pause.apply_resume()
        details = None
        if res.deadline_ns is not None:
            details = {"ttl_s": (res.deadline_ns - now_ns) // 1_000_000_000}
        yield self._ack(msg, request_id, accepted=res.accepted,
                        reason=res.reason, details=details)

    def _seen(self, request_id: str) -> bool:
        if request_id in self._req_lru:
            return True
        self._req_lru[request_id] = None
        cap = max(64, int(_cfg.maint_sec_request_lru))
        while len(self._req_lru) > cap:
            self._req_lru.popitem(last=False)
        return False

    # ── §8.7 FP feedback ─────────────────────────────────────────
    def _handle_quarantine_clear(self, msg: Message,
                                 payload: dict) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        qid = str(payload.get("target") or "")
        if not request_id:
            return
        if self._seen(request_id):
            yield self._ack(msg, request_id, accepted=True, reason="dedup")
            return
        # The trigger pattern is supplied in `details.pattern` (the
        # ops console looks it up from the quarantine row); v1
        # tolerates absence by acking accepted-but-noop.
        details = payload.get("details") or {}
        pattern = str(details.get("pattern") or "")
        if not pattern:
            yield self._ack(msg, request_id, accepted=True,
                            reason="noop_no_pattern")
            return
        now_iso = self._clock_iso()
        promoted = False
        added = self._patterns.upsert_pending(pattern, qid=qid, now_iso=now_iso)
        # Promote-on-Nth-FP threshold; v1 promotes immediately when
        # the operator confirms (one FP is enough). Production may
        # require ``cfg.maint_sec_pattern_promote_threshold`` confirms.
        ttl_s = max(60, int(_cfg.maint_sec_pattern_ttl_s))
        promoted = self._patterns.promote_to_active(
            pattern, now_iso=now_iso, ttl_s=ttl_s
        )
        if added:
            yield self._notify("pattern_allowlist_pending",
                               target=pattern,
                               extra={"qid": qid})
        if promoted:
            yield self._notify("pattern_allowlist_added",
                               target=pattern,
                               extra={"qid": qid, "ttl_s": ttl_s})
        yield self._ack(msg, request_id, accepted=True,
                        reason="pattern_promoted" if promoted else "pattern_pending",
                        details={"pattern": pattern})

    # ── §8.8 decimation ─────────────────────────────────────────
    def _handle_decimate(self, msg: Message,
                         payload: dict) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        if not request_id:
            return
        if self._seen(request_id):
            yield self._ack(msg, request_id, accepted=True, reason="dedup")
            return
        target = str(payload.get("target") or "all")
        # §8.8 hysteresis gate — one decimate per
        # ``cfg.maint_sec_decimate_min_interval_s`` globally. The
        # zset is a single shared resource so per-subject hysteresis
        # is meaningless. Throttled calls ack accepted=true with a
        # diagnostic reason and emit ``denylist_decimate_throttled``
        # so operators see the suppression in the audit trail.
        now_ms = self._now_ms()
        window_ms = max(1, int(_cfg.maint_sec_decimate_min_interval_s)) * 1000
        elapsed_ms = now_ms - self._last_decimate_ms
        if self._last_decimate_ms > 0 and elapsed_ms < window_ms:
            cooldown_ms = window_ms - elapsed_ms
            yield self._notify(
                "denylist_decimate_throttled",
                target=target,
                extra={
                    "reason": "hysteresis",
                    "cooldown_ms": int(cooldown_ms),
                    "min_interval_s": int(_cfg.maint_sec_decimate_min_interval_s),
                    "trigger": "operator",
                },
            )
            yield self._ack(
                msg, request_id, accepted=True,
                reason="hysteresis_throttled",
                details={"cooldown_ms": int(cooldown_ms)},
            )
            return
        cap = max(1, int(_cfg.sec_denylist_max_entries))
        result = self._decimator.decimate(now_ms=now_ms, cap=cap)
        # Stamp the hysteresis epoch only when the decimator did
        # real work. A no-op call (ZCARD <= cap) leaves the gate
        # open so the *next* alert during real pressure is not
        # silently swallowed.
        if int(result.get("evicted_count") or 0) > 0:
            self._last_decimate_ms = now_ms
        yield self._notify("denylist_decimate",
                           target=target,
                           extra=dict(result))
        if result.get("cap_cleared"):
            yield self._notify("denylist_cap_cleared",
                               target=target,
                               extra={"new_zcard": result.get("new_zcard")})
        yield self._ack(msg, request_id, accepted=True,
                        reason="decimated",
                        details=dict(result))

    # ── §8.8 alert-triggered automatic decimate ───────────────────
    def _handle_sec_alert(self, msg: Message) -> Iterable[Message]:
        """Subscribe path for ``sec.alert.v1{kind=denylist_growth_anomaly,
        severity=critical}`` per ROADMAP §8.8. The alert fires when
        ``sec_denylist_mutate.lua`` returns ``rejected_capped``; the
        sweeper responds by running a single Lua decimate, gated by
        the same global hysteresis window as the operator path.

        Alert-triggered runs do not produce a ``maint.ack.v1`` — no
        ``request_id`` to correlate against (the producer is
        ``sec.rate.v1``, not the ops console). The audit trail is
        the ``denylist_decimate`` / ``denylist_decimate_throttled``
        notification on ``maint.event.v1``.
        """
        payload = msg.payload or {}
        if payload.get("kind") != "denylist_growth_anomaly":
            return
        if str(payload.get("severity") or "") != "critical":
            return
        alert_id = str(payload.get("alert_id") or "")
        if alert_id:
            if alert_id in self._alert_lru:
                return
            self._alert_lru[alert_id] = None
            cap_lru = max(64, int(_cfg.maint_sec_request_lru))
            while len(self._alert_lru) > cap_lru:
                self._alert_lru.popitem(last=False)
        target = str(payload.get("subject") or "all")
        now_ms = self._now_ms()
        window_ms = max(1, int(_cfg.maint_sec_decimate_min_interval_s)) * 1000
        elapsed_ms = now_ms - self._last_decimate_ms
        if self._last_decimate_ms > 0 and elapsed_ms < window_ms:
            yield self._notify(
                "denylist_decimate_throttled",
                target=target,
                extra={
                    "reason": "hysteresis",
                    "cooldown_ms": int(window_ms - elapsed_ms),
                    "min_interval_s": int(_cfg.maint_sec_decimate_min_interval_s),
                    "trigger": "alert",
                    "alert_id": alert_id,
                },
            )
            return
        cap = max(1, int(_cfg.sec_denylist_max_entries))
        result = self._decimator.decimate(now_ms=now_ms, cap=cap)
        if int(result.get("evicted_count") or 0) > 0:
            self._last_decimate_ms = now_ms
        extra = dict(result)
        extra["trigger"] = "alert"
        if alert_id:
            extra["alert_id"] = alert_id
        yield self._notify("denylist_decimate", target=target, extra=extra)
        if result.get("cap_cleared"):
            yield self._notify("denylist_cap_cleared",
                               target=target,
                               extra={"new_zcard": result.get("new_zcard")})

    # ── Periodic expiry tick ────────────────────────────────────
    def expire_tick(self) -> list[Message]:
        if not self._leader.is_leader():
            return []
        now_iso = self._clock_iso()
        expired = self._patterns.expire_due(now_iso=now_iso)
        return [
            self._notify("pattern_allowlist_expired",
                         target=p,
                         extra={"reason": "ttl"})
            for p in expired
        ]

    # ── Helpers ─────────────────────────────────────────────────
    def _now_ms(self) -> int:
        if self._clock_ms is not None:
            return self._clock_ms()
        import time as _t
        return int(_t.time() * 1000)

    def _ack(self, msg: Message, request_id: str, *, accepted: bool,
             reason: str, details: dict | None = None) -> Message:
        ack = MaintAck(
            request_id=request_id,
            accepted=accepted,
            accepted_by=self.name,
            processed_at=self._clock_iso(),
            attempt=int(msg.envelope.attempt or 1),
            reason=reason,
            details=details,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=msg.envelope.trace_id,
            topic=MAINT_ACK,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=ack.as_dict())

    def _notify(self, kind: str, *, target: str,
                extra: dict | None = None) -> Message:
        payload: dict = {
            "kind": kind,
            "target": target,
            "produced_at": self._clock_iso(),
        }
        if extra:
            payload.update(extra)
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=MAINT_EVENT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=payload)


__all__ = [
    "ALLOWED_PATTERN_STATES",
    "DenylistDecimator",
    "InMemoryDecimator",
    "InMemoryPatternStore",
    "MaintSecAgent",
    "PatternAllowlistStore",
]
