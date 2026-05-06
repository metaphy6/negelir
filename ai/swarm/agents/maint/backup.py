"""Phase 8 §8.3 — `maint.backup.v1` reactor (vertical slice).

What this slice ships:

* **Cron-driven state machine.** A 5-field UTC cron (default
  ``0 3 * * *``) fires the dump → restore-verify → prune sequence
  through a duck-typed ``flush_expired()`` hook the
  :class:`AgentRunner` already drives on a steady cadence.
* **Operator-driven PII erasure.** Consumes
  ``maint.event.v1{kind=quarantine_erase}`` envelopes (per
  :data:`swarm.agents.maint._ack_routing._ACK_ROUTING_TABLE`),
  tombstones the matching ``quarantine_samples`` rows through a
  Protocol-typed store, and emits a sibling
  ``maint.event.v1{kind=pii_erased}`` audit event plus the
  expected ``maint.ack.v1``.
* **Disk-pressure guard.** Refuses to start a dump if free space <
  ``max(2*last_dump_size, min_free_gb*1GB)``; emits
  ``backup_completed{outcome=disk_pressure_skipped}``.
* **Wall-clock skew detection.** Backwards step >
  ``cfg.maint_backup_clock_step_back_alert_s`` skips this fire
  with ``backup_completed{outcome=skew_skipped}``.
* **Catch-up policy.** At most ONE make-up run when monotonic
  delta vs the last fire exceeds ``cfg.maint_backup_max_skew_h``
  hours (otherwise we wait for the next cron tick).
* **Safety floor.** When ``cfg.maint_backup_dry_run`` is true,
  every emit carries ``dry_run: true`` and NO destructive prune
  is executed (``would_delete_count`` instead).
* **PRUNE_ORDER discipline.** The destructive-prune phase runs
  exactly the order pinned in
  :data:`xops.maint.prune_order.PRUNE_ORDER`; ``--prune-only``
  invocations are refused (exit-code reservation per §8.3 prose).

What this slice DOES NOT ship (deferred, intentionally):

* Live ``pg_dump`` / ``age`` / ``pg_restore`` drivers — the agent
  talks to them via Protocol-typed adapters
  (:class:`DumpExecutor`, :class:`RestoreVerifier`,
  :class:`PrunerStorage`, :class:`QuarantineStore`); the v1 ships
  in-memory shims so the state machine is testable. The Phase R1
  datasource bootstrap will inject the real adapters.
* Cold-verify (separate-host restore) — same Protocol, separate
  adapter, tracked for §8.3 follow-up.
* ``ops.restore`` CLI (xops/opsctl) — separate change.
* ``sec.alert.v1`` emission for skew / disk-pressure — would
  require extending the closed ``sec.alert.v1.source`` enum to
  include ``maint.backup.v1`` (separate diff).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Protocol
from uuid import uuid4

from common.config import cfg as _cfg

# pylint: disable=relative-beyond-top-level
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck
from ..topics import MAINT_ACK, MAINT_EVENT
from ._ack_routing import KNOWN_MAINT_EVENT_KINDS

# Importing the cron module fails-soft on the cfg-validation path
# (early bootstrap) but is mandatory at agent construction — the
# constructor below re-raises any cron parse error so a typo cannot
# silently disable nightly backup.
from xops.backup.cron import CronExpr, CronSyntaxError, parse_cron, utc_now
from xops.maint.prune_order import PRUNE_ORDER


_log = logging.getLogger("swarm.agents.maint.backup")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid4().hex


def _gb_to_bytes(n: int | float) -> int:
    return int(n) * (1024 ** 3)


# ── Outcome / reason taxonomies ─────────────────────────────────────────
# Closed sets — extending requires a swarm minor bump so dashboards
# can colour the new bucket. Mirrors §8.3 prose.
BACKUP_OUTCOMES: frozenset[str] = frozenset({
    "ok",
    "verify_failed",
    "dump_failed",
    "encrypt_failed",
    "disk_pressure_skipped",
    "skew_skipped",
    "dry_run",
})

PRUNE_SKIP_REASONS: frozenset[str] = frozenset({
    "verify_failed",
    "disk_pressure",
    "skew_skipped",
    "prune_only_refused",
    "leader_lost",
})


# ── Protocol-typed adapters ─────────────────────────────────────────────
# The v1 vertical slice ships pure-Python shims. Live drivers
# (real pg_dump, age, pg_restore, Postgres) are injected by the
# Phase R1 datasource bootstrap.


class DumpExecutor(Protocol):
    """Take a logical Postgres dump. Returns (dump_bytes, encrypted_bytes)."""

    def dump(self, *, fire_window_id: str, dry_run: bool) -> tuple[int, int]:
        ...


class RestoreVerifier(Protocol):
    """Restore the latest dump into a scratch DB and return per-table
    row counts (and ``schema_migrations`` max version under the key
    ``"_schema_max_version"``). Empty mapping = verify failed."""

    def verify(self, *, fire_window_id: str) -> Mapping[str, int]:
        ...

    def sweep_orphans(self) -> tuple[str, ...]:
        """Return the list of orphan scratch databases that were
        dropped (empty when none)."""
        ...


class PrunerStorage(Protocol):
    """Run the destructive-prune phase honouring :data:`PRUNE_ORDER`.

    Returns ``{table: row_count_deleted}``; ``would_delete_count``
    semantics when ``dry_run=True`` (no rows actually removed)."""

    def prune(self, *, dry_run: bool) -> Mapping[str, int]:
        ...


class QuarantineStore(Protocol):
    """Right-to-erasure surface — tombstones rows for a client_id."""

    def erase(self, *, client_id: str) -> int:
        """Return the number of rows actually tombstoned."""
        ...


class DiskGauge(Protocol):
    """Returns (free_bytes, last_dump_size_bytes_or_zero)."""

    def sample(self) -> tuple[int, int]:
        ...


# ── In-memory shims (test-only by construction) ─────────────────────────


@dataclass
class NoopDumpExecutor:
    """No-op dump — claims to write a fixed-size envelope."""

    bytes_written: int = 1024

    def dump(self, *, fire_window_id: str, dry_run: bool) -> tuple[int, int]:
        if dry_run:
            return (0, 0)
        # encrypted_bytes is +16 bytes for the age header — close
        # enough for a smoke test.
        return (self.bytes_written, self.bytes_written + 16)


@dataclass
class NoopVerifier:
    """No-op verifier — always succeeds with a fixed table census."""

    summary: dict[str, int] = field(
        default_factory=lambda: {
            "matches": 0,
            "predict_final": 0,
            "_schema_max_version": 11,
        }
    )
    orphans: tuple[str, ...] = ()
    fail: bool = False

    def verify(self, *, fire_window_id: str) -> Mapping[str, int]:
        if self.fail:
            return {}
        return dict(self.summary)

    def sweep_orphans(self) -> tuple[str, ...]:
        return self.orphans


@dataclass
class InMemoryPrunerStorage:
    """In-memory pruner — counts virtual rows per table."""

    counts: dict[str, int] = field(default_factory=dict)

    def prune(self, *, dry_run: bool) -> Mapping[str, int]:
        if not self.counts:
            return {}
        if dry_run:
            return dict(self.counts)
        out = dict(self.counts)
        self.counts.clear()
        return out


@dataclass
class InMemoryQuarantineStore:
    """In-memory quarantine store — a `dict[client_id, row_count]`."""

    rows_per_client: dict[str, int] = field(default_factory=dict)

    def erase(self, *, client_id: str) -> int:
        return self.rows_per_client.pop(client_id, 0)


@dataclass
class StaticDiskGauge:
    """Static disk gauge — returns the configured (free, last_dump)."""

    free_bytes: int
    last_dump_bytes: int = 0

    def sample(self) -> tuple[int, int]:
        return (self.free_bytes, self.last_dump_bytes)


# ── Agent ───────────────────────────────────────────────────────────────


class MaintBackupAgent:
    """`maint.backup.v1` reactor.

    Subscribes ``maint.event.v1`` (kind=quarantine_erase). Publishes
    ``maint.event.v1`` (notifications: backup_started, backup_completed,
    backup_verify_orphan_swept, prune_started, prune_completed,
    prune_skipped, quarantine_pruned, pii_erased) and ``maint.ack.v1``
    (response to quarantine_erase).

    Construction is dependency-injected: every external surface
    (``pg_dump``, ``age``, ``pg_restore``, the destructive-prune
    SQL, the right-to-erasure SQL, the disk gauge) goes through a
    Protocol typed adapter. The default shims are no-ops so the
    agent is testable without a live Postgres; the Phase R1
    datasource bootstrap injects the real drivers.
    """

    name = "maint.backup.v1"
    subscribes: tuple[Topic, ...] = (MAINT_EVENT,)
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK)

    def __init__(
        self,
        *,
        dump: DumpExecutor | None = None,
        verifier: RestoreVerifier | None = None,
        pruner: PrunerStorage | None = None,
        quarantine: QuarantineStore | None = None,
        disk: DiskGauge | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_wall: Callable[[], datetime] | None = None,
        clock_mono_ns: Callable[[], int] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._dump = dump if dump is not None else NoopDumpExecutor()
        self._verifier = verifier if verifier is not None else NoopVerifier()
        self._pruner = pruner if pruner is not None else InMemoryPrunerStorage()
        self._quarantine = (
            quarantine if quarantine is not None else InMemoryQuarantineStore()
        )
        self._disk = disk if disk is not None else StaticDiskGauge(
            free_bytes=_gb_to_bytes(_cfg.maint_backup_min_free_gb) * 4,
        )
        self._clock_iso = clock_iso or _utc_iso
        self._clock_wall = clock_wall or utc_now
        self._clock_mono_ns = clock_mono_ns or (
            lambda: int(self._clock_wall().timestamp() * 1e9)
        )
        self._new_id = new_id or _new_id

        # Parse cron up-front so a typo refuses-to-start instead of
        # silently disabling the nightly backup.
        self._cron: CronExpr = parse_cron(str(_cfg.maint_backup_cron))
        # Fire-window tracking (see backup_started.fire_window_id).
        # Random pod-instance prefix so a leader flip after restart
        # cannot collide window ids in the audit ledger.
        self._pod_instance_id: str = uuid4().hex[:8]
        # The next fire moment we are armed for. ``None`` → arm on
        # first ``flush_expired()`` call (handles the cold-start case
        # without firing immediately).
        self._next_fire_at: datetime | None = None
        self._last_fire_wall: datetime | None = None
        self._last_fire_mono_ns: int | None = None
        self._catch_up_used: bool = False

    # ── Bus contract: handle quarantine_erase ───────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        """Route inbound `maint.event.v1{kind=quarantine_erase}` to the
        PII-erasure handler. Any other kind is ignored (other reactors
        own them; non-routing here keeps the boundary discipline)."""
        if msg.envelope.topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        kind = payload.get("kind")
        if kind != "quarantine_erase":
            return ()
        return list(self._handle_quarantine_erase(msg, payload))

    def _handle_quarantine_erase(
        self, msg: Message, payload: dict
    ) -> Iterable[Message]:
        request_id = str(payload.get("request_id") or "")
        target_client = str(payload.get("target") or "")
        if not request_id or not target_client:
            yield self._ack(
                msg,
                request_id=request_id or msg.envelope.message_id,
                accepted=False,
                reason="quarantine_erase missing request_id or target",
            )
            return
        row_count = int(self._quarantine.erase(client_id=target_client))
        erased_at = self._clock_iso()
        yield self._notify(
            "pii_erased",
            extra={
                "request_id": request_id,
                "client_id": target_client,
                "table": "quarantine_samples",
                "row_count": row_count,
                "erased_at": erased_at,
            },
        )
        if row_count == 0:
            yield self._ack(
                msg,
                request_id=request_id,
                accepted=True,
                reason="no rows matched",
                details={"row_count": 0, "client_id": target_client},
            )
            return
        yield self._ack(
            msg,
            request_id=request_id,
            accepted=True,
            reason=f"erased {row_count} rows",
            details={"row_count": row_count, "client_id": target_client},
        )

    # ── Cron tick: state machine ────────────────────────────────────────
    def flush_expired(self) -> Iterable[Message]:
        """Cron-tick entry point — called by :class:`AgentRunner` on a
        steady cadence (per its `flush_interval_sec` knob). We arm
        the next fire on first call, then fire whenever the current
        wall clock crosses :attr:`_next_fire_at`. Returns the list of
        messages to publish (empty when nothing is due)."""
        now_wall = self._clock_wall()
        if self._next_fire_at is None:
            from xops.backup.cron import next_fire_after
            self._next_fire_at = next_fire_after(self._cron, now_wall)
            return ()
        if now_wall < self._next_fire_at:
            return ()
        # Capture the fire moment + arm the next one BEFORE running
        # the state machine so a downstream raise cannot wedge the
        # cron schedule.
        fire_wall = self._next_fire_at
        from xops.backup.cron import next_fire_after
        self._next_fire_at = next_fire_after(self._cron, now_wall)
        return list(self._fire(fire_wall=fire_wall, now_wall=now_wall))

    def _fire(
        self, *, fire_wall: datetime, now_wall: datetime
    ) -> Iterable[Message]:
        """Run one iteration of the state machine (dump → verify →
        prune). Emits the corresponding `backup_*` and `prune_*`
        notification events and pushes nothing to MAINT_ACK (cron
        fires carry no operator request_id)."""
        fire_window_id = (
            f"{self._pod_instance_id}:{fire_wall.isoformat()}"
        )
        mono_ns = self._clock_mono_ns()

        # ── Catch-up policy ───────────────────────────────────────────
        # If the monotonic delta vs the last successful fire exceeds
        # `max_skew_h`, this fire is the make-up run. Coalesce: at
        # most ONE make-up per restart — subsequent missed windows
        # wait for their natural next-fire moment.
        catch_up = False
        if self._last_fire_wall is not None:
            delta_h = (now_wall - self._last_fire_wall).total_seconds() / 3600.0
            max_skew = float(_cfg.maint_backup_max_skew_h)
            if delta_h > max_skew and not self._catch_up_used:
                catch_up = True
                self._catch_up_used = True

        # ── Skew detection (backwards wall-clock step) ────────────────
        if self._last_fire_wall is not None:
            backward = (self._last_fire_wall - now_wall).total_seconds()
            if backward > float(_cfg.maint_backup_clock_step_back_alert_s):
                self._last_fire_wall = now_wall
                self._last_fire_mono_ns = mono_ns
                _log.warning(
                    "maint.backup.v1: backwards wall-clock step %.1fs "
                    "exceeded threshold; skipping fire window %s",
                    backward, fire_window_id,
                )
                yield self._notify(
                    "backup_completed",
                    extra={
                        "fire_window_id": fire_window_id,
                        "outcome": "skew_skipped",
                        "duration_ms": 0,
                    },
                )
                yield self._notify(
                    "prune_skipped",
                    extra={
                        "fire_window_id": fire_window_id,
                        "reason": "skew_skipped",
                    },
                )
                return

        dry_run = bool(_cfg.maint_backup_dry_run)

        # Sweep orphan scratch DBs from prior failed verify runs.
        orphans = tuple(self._verifier.sweep_orphans())
        if orphans:
            yield self._notify(
                "backup_verify_orphan_swept",
                extra={
                    "fire_window_id": fire_window_id,
                    "swept_dbs": list(orphans),
                },
            )

        # ── backup_started ───────────────────────────────────────────
        yield self._notify(
            "backup_started",
            extra={
                "fire_window_id": fire_window_id,
                "wall_clock_utc": fire_wall.isoformat(),
                "monotonic_ns_at_fire": int(mono_ns),
                "dry_run": dry_run,
                "catch_up": catch_up,
            },
        )
        start_mono_ns = mono_ns

        # ── Disk-pressure guard ───────────────────────────────────────
        free_bytes, last_dump_bytes = self._disk.sample()
        floor = max(
            2 * int(last_dump_bytes),
            _gb_to_bytes(_cfg.maint_backup_min_free_gb),
        )
        if free_bytes < floor:
            _log.warning(
                "maint.backup.v1: disk pressure free=%d < floor=%d; "
                "skipping fire %s",
                free_bytes, floor, fire_window_id,
            )
            yield self._notify(
                "backup_completed",
                extra={
                    "fire_window_id": fire_window_id,
                    "outcome": "disk_pressure_skipped",
                    "duration_ms": int(
                        (self._clock_mono_ns() - start_mono_ns) / 1_000_000
                    ),
                },
            )
            yield self._notify(
                "prune_skipped",
                extra={
                    "fire_window_id": fire_window_id,
                    "reason": "disk_pressure",
                },
            )
            self._last_fire_wall = now_wall
            self._last_fire_mono_ns = mono_ns
            return

        # ── Dump ──────────────────────────────────────────────────────
        dump_bytes, encrypted_bytes = self._dump.dump(
            fire_window_id=fire_window_id, dry_run=dry_run,
        )

        # ── Restore-verify ────────────────────────────────────────────
        verify_summary = dict(self._verifier.verify(fire_window_id=fire_window_id))
        if not verify_summary:
            yield self._notify(
                "backup_completed",
                extra={
                    "fire_window_id": fire_window_id,
                    "outcome": "verify_failed",
                    "duration_ms": int(
                        (self._clock_mono_ns() - start_mono_ns) / 1_000_000
                    ),
                    "dump_bytes": int(dump_bytes),
                    "encrypted_bytes": int(encrypted_bytes),
                },
            )
            yield self._notify(
                "prune_skipped",
                extra={
                    "fire_window_id": fire_window_id,
                    "reason": "verify_failed",
                },
            )
            self._last_fire_wall = now_wall
            self._last_fire_mono_ns = mono_ns
            return

        # ── Destructive prune (PRUNE_ORDER discipline) ────────────────
        yield self._notify(
            "prune_started",
            extra={
                "fire_window_id": fire_window_id,
                "prune_order": list(PRUNE_ORDER),
                "dry_run": dry_run,
            },
        )
        deleted_per_table_raw = self._pruner.prune(dry_run=dry_run)
        # Filter the pruner output through PRUNE_ORDER so the audit
        # ledger never sees an out-of-canon table — defensive.
        deleted_per_table = {
            t: int(deleted_per_table_raw.get(t, 0)) for t in PRUNE_ORDER
        }
        prune_extra: dict = {
            "fire_window_id": fire_window_id,
            "deleted_per_table": deleted_per_table,
            "dry_run": dry_run,
        }
        if dry_run:
            prune_extra["would_delete_count"] = sum(deleted_per_table.values())
        yield self._notify("prune_completed", extra=prune_extra)

        # ── backup_completed (ok) ─────────────────────────────────────
        outcome = "dry_run" if dry_run else "ok"
        yield self._notify(
            "backup_completed",
            extra={
                "fire_window_id": fire_window_id,
                "outcome": outcome,
                "duration_ms": int(
                    (self._clock_mono_ns() - start_mono_ns) / 1_000_000
                ),
                "dump_bytes": int(dump_bytes),
                "encrypted_bytes": int(encrypted_bytes),
                "verify_summary": dict(verify_summary),
                "dry_run": dry_run,
            },
        )
        self._last_fire_wall = now_wall
        self._last_fire_mono_ns = mono_ns

    # ── Emission helpers ────────────────────────────────────────────────
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

    def _notify(self, kind: str, *, extra: dict) -> Message:
        # Defence-in-depth: if a typo creeps into a callsite the
        # boundary test would catch it AT TEST TIME. This fires AT
        # AGENT TIME so we don't emit unknown kinds on a hot path.
        if kind not in KNOWN_MAINT_EVENT_KINDS:
            raise RuntimeError(
                f"maint.backup.v1: refusing to emit unknown kind={kind!r}"
            )
        payload: dict = {
            "kind": kind,
            "kind_schema_version": 1,
            "produced_at": self._clock_iso(),
        }
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
    "BACKUP_OUTCOMES",
    "PRUNE_SKIP_REASONS",
    "DiskGauge",
    "DumpExecutor",
    "InMemoryPrunerStorage",
    "InMemoryQuarantineStore",
    "MaintBackupAgent",
    "NoopDumpExecutor",
    "NoopVerifier",
    "PrunerStorage",
    "QuarantineStore",
    "RestoreVerifier",
    "StaticDiskGauge",
]
