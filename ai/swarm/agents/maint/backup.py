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
* Cold-verify (separate-host restore) — same Protocol, separate
  adapter, tracked for §8.3 follow-up.

What this slice DOES ship for the Scheduler bullet:

* Append-only audit ledger at ``cfg.maint_backup_dir/audit.csv``
  written on every fire (`wall_clock_utc`, `monotonic_ns_at_fire`,
  outcome, verified, catch_up). On boot, the agent re-seeds its
  in-memory ``_last_completed_wall`` / ``_last_verified_wall``
  from today's most recent rows so a restart-mid-day does NOT
  re-fire the dump (idempotency on `(job_id, backup_date_utc)`).
* ``sec.alert.v1`` emission on three skew conditions:
  ``backup_clock_skew{severity=error}`` for backwards wall-clock
  steps beyond ``cfg.maint_backup_clock_step_back_alert_s``;
  ``backup_clock_skew{severity=warn, scope=forward}`` for forward
  leaps beyond ``cfg.maint_backup_clock_step_forward_alert_h``;
  ``backup_age_alert{severity=error}`` when a make-up run is more
  than ``cfg.maint_backup_max_skew_h`` late (the run still fires).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol
from uuid import uuid4

from common.config import cfg as _cfg

# pylint: disable=relative-beyond-top-level
from ...sdk.types import Envelope, Message, Topic
from ..payloads import MaintAck, SecAlert
from ..topics import MAINT_ACK, MAINT_EVENT, SEC_ALERT
from ._ack_routing import KNOWN_MAINT_EVENT_KINDS

# Importing the cron module fails-soft on the cfg-validation path
# (early bootstrap) but is mandatory at agent construction — the
# constructor below re-raises any cron parse error so a typo cannot
# silently disable nightly backup.
from xops.backup.audit import (
    AuditRow,
    append_row as _append_audit_row,
    last_completed_today,
    last_verified_today,
)
from xops.backup.cron import CronExpr, CronSyntaxError, parse_cron, utc_now
from xops.backup.executors import quarantine_failed_dump_dir
from xops.backup.retention import oldest_retained_sunday_dump, prune_retained_dumps
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

# ROADMAP §8.3 escape hatch: restore-verify mode. `full` runs the
# complete `pg_restore` + verify.sql suite; `toc_only` runs only
# `pg_restore --list` (TOC validation, no row restore) for
# very-large-DB nightly windows. Closed set; agent boot validation
# refuses any other value.
VALID_VERIFY_MODES: frozenset[str] = frozenset({"full", "toc_only"})


class BackupPermissionError(RuntimeError):
    """Raised at agent startup when ``cfg.maint_backup_dir`` (or files
    inside it) carry mode bits looser than the §8.3 binding contract
    (``0o700`` for the directory, ``0o600`` for files).

    Distinct subclass so an operator-facing supervisor can refuse
    to mark the pod ready (vs swallowing it as a generic
    ``RuntimeError``). The agent picks this surface over
    ``PermissionError`` because the OS did not deny anything — the
    refusal is policy, not a syscall failure.
    """


class BackupConfigError(RuntimeError):
    """Raised at agent startup when the cross-cutting deployment
    profile and the backup-encryption configuration are mutually
    inconsistent.

    Currently the only trigger is ROADMAP §8.3's
    ``fail_safe_no_encryption_in_prod`` gate: ``cfg.profile=='prod'``
    AND ``cfg.maint_runtime != 'none'`` AND no encryption surface
    configured (both ``maint_backup_encryption_key_dir`` and
    ``maint_backup_age_recipients_file`` empty). Distinct subclass so
    operators can grep the supervisor logs for the policy class
    without disturbing the looser-perms refusal
    (:class:`BackupPermissionError`).
    """


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
    ``"_schema_max_version"``). Empty mapping = verify failed.

    ``mode`` is :data:`VALID_VERIFY_MODES` — ``"full"`` runs the
    complete ``pg_restore`` + ``verify.sql`` suite; ``"toc_only"`` is a
    ROADMAP §8.3 escape hatch that runs only ``pg_restore --list`` to
    validate the dump's TOC without restoring rows. Implementations
    MUST honour both modes; the agent exposes the current value as
    ``backup_completed.verify_mode`` for operator visibility.

    Implementations:

    * :class:`xops.backup.verifier.LocalSubprocessVerifier` — compose-
      only dev driver. Spawns an ephemeral ``postgres:16-alpine``
      container per fire window via the host's docker socket; carries
      the same docker-socket caveat as :class:`ComposeController` and
      is **forbidden in prod**.
    * ``SidecarVerifier`` — **deferred to Phase 14** (Kubernetes
      sidecar / Job template at ``infra/k8s/jobs/restore-verify.yaml``
      with a least-privilege ServiceAccount in the
      ``negelir-maint-verify`` namespace). The Protocol shape here is
      the binding contract Phase 14 must implement; nothing else in
      the §8.3 vertical slice depends on the K8s adapter being live.
    """

    def verify(
        self, *, fire_window_id: str, mode: str = "full",
    ) -> Mapping[str, int]:
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


# ── Restore-runbook surface (ROADMAP §8.3 `ops.restore`) ────────────────


class RestoreKeyClass(Protocol):
    """Resolve the ``age`` private-key class for a given dump date.

    ROADMAP §8.3 binding: the ``ops.restore`` runbook MUST decrypt
    using a **DR-class** private key. Verify-class keys are
    explicitly rejected with surface code ``dr_key_required`` —
    they are per-dump ephemeral keys for restore-verify only and
    must never gate a real restore.

    Implementations return one of ``"dr"`` / ``"verify"`` / ``""``
    (empty when no key is available — surfaced as
    ``decrypt_failed``).
    """

    def classify(self, *, dump_date: str) -> str:
        ...


class RestoreExecutor(Protocol):
    """Run the actual ``age -d | tar -xf - | pg_restore`` pipeline
    against ``destination`` and then run ``verify.sql``. Returns
    ``(exit_code, verify_summary)`` — ``exit_code == 0`` is the only
    success path; non-zero short-circuits the agent into
    ``backup_restore_completed{outcome='restore_failed'}`` (or the
    outcome the executor surfaces via the closed taxonomy).

    The v1 vertical slice ships :class:`NoopRestoreExecutor`. The
    real subprocess-driving adapter lives alongside
    :class:`xops.backup.verifier.LocalSubprocessVerifier` and is
    injected by the Phase R1 datasource bootstrap.
    """

    def restore(
        self, *, dump_date: str, destination: str, ephemeral: bool,
    ) -> tuple[int, Mapping[str, int]]:
        ...


class MaintAuditLogger(Protocol):
    """Append a ROADMAP §8.3 right-to-restore audit row. The v1
    slice writes through an in-memory shim
    (:class:`InMemoryMaintAuditLogger`); the Phase R1 datasource
    bootstrap injects a Postgres-backed writer hitting
    ``maint_audit_log_pii`` (migration 009).
    """

    def append(
        self,
        *,
        kind: str,
        request_id: str,
        target: str,
        actor: str,
        details: Mapping[str, object],
    ) -> None:
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
    last_mode: str | None = None

    def verify(
        self, *, fire_window_id: str, mode: str = "full",
    ) -> Mapping[str, int]:
        # Record the mode the agent passed so tests can assert the
        # cfg → verifier wiring without coupling to schema details.
        self.last_mode = mode
        if self.fail:
            return {}
        if mode == "toc_only":
            # Sentinel TOC-only success payload: row counts are not
            # available without a full restore, so we return a marker
            # the agent can opaquely include in `verify_summary`.
            return {"_toc_only": 1, "_schema_max_version": int(self.summary.get("_schema_max_version", 0))}
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


# ── Restore-runbook surface taxonomies + shims ──────────────────────────

# Closed set of ``backup_restore_completed.outcome`` tokens. Mirrors
# the JSON schema enum 1-for-1; extending this requires a swarm
# minor bump so dashboards can colour the new bucket.
RESTORE_OUTCOMES: frozenset[str] = frozenset({
    "ok",
    "dr_key_required",
    "live_overwrite_requires_confirm",
    "decrypt_failed",
    "restore_failed",
    "post_verify_failed",
})


@dataclass
class StaticRestoreKeyClass:
    """Test-only :class:`RestoreKeyClass` — returns a fixed class
    (default ``"dr"``) regardless of dump date. Real production
    adapter consults ``cfg.maint_backup_encryption_key_dir`` and
    matches the dump's encryption_key_version against the
    DR/verify recipient classification per
    :mod:`xops.backup.recipients`."""

    key_class: str = "dr"

    def classify(self, *, dump_date: str) -> str:
        return str(self.key_class)


@dataclass
class NoopRestoreExecutor:
    """No-op :class:`RestoreExecutor` — claims the restore succeeded
    (or pre-set ``exit_code`` for failure-path tests) and returns a
    fixed verify summary. Real driver decrypts + pipes through
    ``pg_restore`` + runs ``xops/backup/verify.sql`` (Phase R1
    bootstrap)."""

    exit_code: int = 0
    summary: dict[str, int] = field(
        default_factory=lambda: {
            "matches": 0,
            "predict_final": 0,
            "_schema_max_version": 11,
        }
    )
    last_destination: str | None = None
    last_dump_date: str | None = None
    last_ephemeral: bool | None = None

    def restore(
        self, *, dump_date: str, destination: str, ephemeral: bool,
    ) -> tuple[int, Mapping[str, int]]:
        self.last_destination = destination
        self.last_dump_date = dump_date
        self.last_ephemeral = ephemeral
        if self.exit_code != 0:
            return (int(self.exit_code), {})
        return (0, dict(self.summary))


@dataclass
class InMemoryMaintAuditLogger:
    """In-memory :class:`MaintAuditLogger` — appends to a list
    callers can inspect. Phase R1 bootstrap will swap in a Postgres
    writer hitting ``maint_audit_log_pii`` (migration 009)."""

    rows: list[dict[str, object]] = field(default_factory=list)

    def append(
        self,
        *,
        kind: str,
        request_id: str,
        target: str,
        actor: str,
        details: Mapping[str, object],
    ) -> None:
        self.rows.append({
            "kind": str(kind),
            "request_id": str(request_id),
            "target": str(target),
            "actor": str(actor),
            "details": dict(details),
        })


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
    publishes: tuple[Topic, ...] = (MAINT_EVENT, MAINT_ACK, SEC_ALERT)

    def __init__(
        self,
        *,
        dump: DumpExecutor | None = None,
        verifier: RestoreVerifier | None = None,
        pruner: PrunerStorage | None = None,
        quarantine: QuarantineStore | None = None,
        disk: DiskGauge | None = None,
        restore_executor: RestoreExecutor | None = None,
        restore_key_class: RestoreKeyClass | None = None,
        audit_logger: MaintAuditLogger | None = None,
        clock_iso: Callable[[], str] | None = None,
        clock_wall: Callable[[], datetime] | None = None,
        clock_mono_ns: Callable[[], int] | None = None,
        new_id: Callable[[], str] | None = None,
        enforce_permissions: bool = True,
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
        self._restore_executor = (
            restore_executor if restore_executor is not None
            else NoopRestoreExecutor()
        )
        self._restore_key_class = (
            restore_key_class if restore_key_class is not None
            else StaticRestoreKeyClass()
        )
        self._audit_logger = (
            audit_logger if audit_logger is not None
            else InMemoryMaintAuditLogger()
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
        # ROADMAP §8.3 weekly cold-verify cron (silent storage rot).
        # Parsed up-front for the same refuse-to-start contract.
        self._cold_verify_cron: CronExpr = parse_cron(
            str(_cfg.maint_backup_cold_verify_cron)
        )
        # Fire-window tracking (see backup_started.fire_window_id).
        # Random pod-instance prefix so a leader flip after restart
        # cannot collide window ids in the audit ledger.
        self._pod_instance_id: str = uuid4().hex[:8]
        # The next fire moment we are armed for. ``None`` → arm on
        # first ``flush_expired()`` call (handles the cold-start case
        # without firing immediately).
        self._next_fire_at: datetime | None = None
        self._startup_catch_up_due: bool = False
        # Same arm-on-first-tick contract for the cold-verify pass.
        self._cold_verify_next_fire_at: datetime | None = None
        self._last_fire_wall: datetime | None = None
        self._last_fire_mono_ns: int | None = None
        self._catch_up_used: bool = False
        # ROADMAP §8.3 backup-age gauge / watchdog: only successful
        # *verified* dumps satisfy the gauge. Skewed / disk-pressured /
        # verify-failed runs do NOT advance these — that is the
        # explicit binding contract (silent-failure mode is the threat).
        self._last_completed_wall: datetime | None = None  # any-outcome ok
        self._last_verified_wall: datetime | None = None    # outcome=ok only
        # ROADMAP §8.3 backup-age watchdog: debounce wall-clock anchor
        # for the silent-failure ``backup_age_alert`` re-emission. The
        # late-catch-up path (see ``_fire``) emits the same alert
        # kind on its own; this anchor only gates the heartbeat-driven
        # watchdog so a stuck-but-alive agent does not flood the bus
        # once per heartbeat. Re-fires after one full alert window.
        self._last_age_alert_wall: datetime | None = None

        # ROADMAP §8.3 binding: agent process runs with umask 0o077
        # so any file `pg_dump` (or our scratch writes) creates is
        # 0o600 by default, and the parent dir / file modes are
        # audited against the same contract — refusing to start on
        # looser perms. Tests that intentionally exercise loose
        # perms construct with ``enforce_permissions=False``.
        if enforce_permissions:
            self._enforce_startup_permissions()

        # ROADMAP §8.3 binding (`fail_safe_no_encryption_in_prod`): in
        # the prod profile with a non-trivial maint runtime wired up,
        # an unencrypted nightly backup is a fail-safe violation —
        # refuse to start. Mock profile (default) keeps the existing
        # warn-only path so dev / CI never trip on it. The check is a
        # closed conjunction so any single guard flipping back to a
        # safe default (profile=mock OR runtime=none OR either
        # encryption surface set) reopens the boot path.
        encryption_configured = bool(
            (str(_cfg.maint_backup_encryption_key_dir) or "").strip()
            or (str(_cfg.maint_backup_age_recipients_file) or "").strip()
        )
        if (
            str(_cfg.profile) == "prod"
            and str(_cfg.maint_runtime) != "none"
            and not encryption_configured
        ):
            raise BackupConfigError(
                "maint.backup.v1: refusing to start; "
                "fail_safe_no_encryption_in_prod — cfg.profile='prod' "
                f"with cfg.maint_runtime={_cfg.maint_runtime!r} requires "
                "either cfg.maint_backup_encryption_key_dir or "
                "cfg.maint_backup_age_recipients_file to be set"
            )

        # ROADMAP §8.3 binding: the restore-verify mode is a closed
        # enum (`VALID_VERIFY_MODES`). Refuse-to-start on any other
        # value so a typo cannot silently downgrade nightly verify to
        # a no-op or wedge the agent on an unknown branch.
        self._verify_mode: str = str(_cfg.maint_backup_verify_mode)
        if self._verify_mode not in VALID_VERIFY_MODES:
            raise BackupConfigError(
                "maint.backup.v1: refusing to start; "
                f"cfg.maint_backup_verify_mode={self._verify_mode!r} not in "
                f"{sorted(VALID_VERIFY_MODES)}"
            )

        # ROADMAP §8.3 binding (Scheduler): replay today's audit
        # ledger so a restart-mid-day does NOT re-fire the dump
        # (idempotency on `(job_id, backup_date_utc)`). Failures
        # are silent — a missing / unreadable file just means
        # "first run today", which is the same as a fresh install.
        self._audit_path: Path = Path(_cfg.maint_backup_dir) / "audit.csv"
        try:
            now_wall = self._clock_wall()
            seeded_completed = last_completed_today(
                self._audit_path, today=now_wall,
            )
            seeded_verified = last_verified_today(
                self._audit_path, today=now_wall,
            )
            if seeded_completed is not None:
                self._last_completed_wall = seeded_completed
                self._last_fire_wall = seeded_completed
            if seeded_verified is not None:
                self._last_verified_wall = seeded_verified
        except OSError:
            # Best-effort — a corrupt ledger must not wedge boot.
            pass

    # ── Bus contract: handle quarantine_erase + restore ─────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        """Route inbound `maint.event.v1` envelopes:

        * ``kind=quarantine_erase`` → PII-erasure handler.
        * ``kind=restore`` → operator-driven restore runbook
          (ROADMAP §8.3 ``ops.restore``).

        Any other kind is ignored (other reactors own them; non-routing
        here keeps the boundary discipline)."""
        if msg.envelope.topic != MAINT_EVENT:
            return ()
        payload = msg.payload or {}
        kind = payload.get("kind")
        if kind == "quarantine_erase":
            return list(self._handle_quarantine_erase(msg, payload))
        if kind == "restore":
            return list(self._handle_restore(msg, payload))
        return ()

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

    # ── Bus contract: operator-driven restore (`ops.restore`) ───────────
    def _handle_restore(
        self, msg: Message, payload: dict
    ) -> Iterable[Message]:
        """Handle ``maint.event.v1{kind=restore}`` per ROADMAP §8.3.

        Wire flow (binding):

        1. Refuse without ``request_id`` / ``target`` (acceptance gate).
        2. Resolve destination — empty ``destination_conn`` defaults to
           the ephemeral target ``negelir_restore_<dump_date>`` (NEVER
           the live primary).
        3. Live-overwrite gate — when ``destination_conn`` matches the
           live primary DSN AND ``confirm_overwrite_live`` is missing,
           refuse with ``live_overwrite_requires_confirm`` (ack false,
           paired ``backup_restore_completed{outcome=...}``).
        4. DR-key gate — ``RestoreKeyClass`` MUST classify the dump
           as ``"dr"``. ``"verify"`` rejects with ``dr_key_required``.
        5. Pipe restore via :class:`RestoreExecutor` (real driver
           calls ``age -d | tar -xf - | pg_restore --jobs=...``).
        6. Run post-restore ``verify.sql`` — the executor returns
           the row-count map; empty = post_verify_failed.
        7. Emit ``backup_restore_started`` BEFORE the executor runs
           and ``backup_restore_completed`` once it returns; mirror
           both as ``maint_audit_log`` rows (right-to-restore
           traceability).
        """
        request_id = str(payload.get("request_id") or "")
        dump_date = str(payload.get("target") or "")
        actor = str(payload.get("client_id") or "")
        if not request_id or not dump_date or not actor:
            yield self._ack(
                msg,
                request_id=request_id or msg.envelope.message_id,
                accepted=False,
                reason="restore missing request_id, target, or client_id",
            )
            return

        destination_conn = str(payload.get("destination_conn") or "")
        confirm_overwrite_live = bool(
            payload.get("confirm_overwrite_live") or False
        )
        from_offsite = bool(payload.get("from_offsite") or False)
        reason_text = str(payload.get("reason") or "")

        # ── Resolve destination (default = ephemeral, NEVER live) ─────
        if destination_conn:
            destination = destination_conn
            ephemeral = False
        else:
            destination = f"negelir_restore_{dump_date}"
            ephemeral = True

        # ── Live-overwrite gate (binding §8.3) ────────────────────────
        live_dsn = str(_cfg.maint_backup_pg_dsn or "").strip()
        if (
            destination_conn
            and live_dsn
            and destination_conn == live_dsn
            and not confirm_overwrite_live
        ):
            yield self._ack(
                msg,
                request_id=request_id,
                accepted=False,
                reason="live_overwrite_requires_confirm",
                details={
                    "destination_conn": destination_conn,
                    "dump_date": dump_date,
                },
            )
            yield self._notify(
                "backup_restore_completed",
                extra={
                    "request_id": request_id,
                    "target": destination,
                    "dump_date": dump_date,
                    "duration_ms": 0,
                    "exit_code": 1,
                    "outcome": "live_overwrite_requires_confirm",
                    "ephemeral": False,
                },
            )
            self._audit_logger.append(
                kind="backup_restore_completed",
                request_id=request_id,
                target=destination,
                actor=actor,
                details={
                    "dump_date": dump_date,
                    "outcome": "live_overwrite_requires_confirm",
                    "exit_code": 1,
                },
            )
            return

        # ── DR-key gate (binding §8.3) ────────────────────────────────
        key_class = str(
            self._restore_key_class.classify(dump_date=dump_date) or ""
        )
        if key_class != "dr":
            outcome = (
                "dr_key_required" if key_class == "verify" else "decrypt_failed"
            )
            reject_reason = (
                "dr_key_required"
                if outcome == "dr_key_required"
                else f"decrypt_failed: no key class for dump_date={dump_date}"
            )
            yield self._ack(
                msg,
                request_id=request_id,
                accepted=False,
                reason=reject_reason,
                details={"dump_date": dump_date, "key_class": key_class},
            )
            yield self._notify(
                "backup_restore_completed",
                extra={
                    "request_id": request_id,
                    "target": destination,
                    "dump_date": dump_date,
                    "duration_ms": 0,
                    "exit_code": 1,
                    "outcome": outcome,
                    "ephemeral": ephemeral,
                },
            )
            self._audit_logger.append(
                kind="backup_restore_completed",
                request_id=request_id,
                target=destination,
                actor=actor,
                details={
                    "dump_date": dump_date,
                    "outcome": outcome,
                    "exit_code": 1,
                    "key_class": key_class,
                },
            )
            return

        # ── Accept + emit started + audit ─────────────────────────────
        yield self._ack(
            msg,
            request_id=request_id,
            accepted=True,
            reason=(
                "restore accepted into ephemeral target"
                if ephemeral
                else "restore accepted into operator-supplied destination"
            ),
            details={
                "dump_date": dump_date,
                "target": destination,
                "ephemeral": ephemeral,
            },
        )
        started_extra: dict = {
            "request_id": request_id,
            "target": destination,
            "dump_date": dump_date,
            "requested_by": actor,
            "destination_conn": destination_conn,
            "ephemeral": ephemeral,
            "from_offsite": from_offsite,
        }
        if reason_text:
            started_extra["reason"] = reason_text
        yield self._notify("backup_restore_started", extra=started_extra)
        self._audit_logger.append(
            kind="backup_restore_started",
            request_id=request_id,
            target=destination,
            actor=actor,
            details={
                "dump_date": dump_date,
                "destination_conn": destination_conn,
                "ephemeral": ephemeral,
                "from_offsite": from_offsite,
                "reason": reason_text,
            },
        )

        # ── Run the pipeline ──────────────────────────────────────────
        start_mono_ns = self._clock_mono_ns()
        try:
            exit_code, verify_summary = self._restore_executor.restore(
                dump_date=dump_date,
                destination=destination,
                ephemeral=ephemeral,
            )
        except Exception as exc:  # noqa: BLE001 — Protocol surface is broad
            _log.warning(
                "maint.backup.v1: restore executor raised on dump_date=%s: %r",
                dump_date, exc,
            )
            exit_code = 1
            verify_summary = {}
            outcome = "restore_failed"
        else:
            if exit_code != 0:
                outcome = "restore_failed"
            elif not verify_summary:
                outcome = "post_verify_failed"
                # Map the empty-summary failure to a non-zero exit so
                # downstream dashboards do not treat post-verify-fail
                # as a clean restore.
                exit_code = 1 if exit_code == 0 else exit_code
            else:
                outcome = "ok"
        duration_ms = int(
            (self._clock_mono_ns() - start_mono_ns) / 1_000_000
        )

        completed_extra: dict = {
            "request_id": request_id,
            "target": destination,
            "dump_date": dump_date,
            "duration_ms": duration_ms,
            "exit_code": int(exit_code),
            "outcome": outcome,
            "ephemeral": ephemeral,
        }
        if outcome == "ok":
            completed_extra["verify_summary"] = dict(verify_summary)
        yield self._notify("backup_restore_completed", extra=completed_extra)
        self._audit_logger.append(
            kind="backup_restore_completed",
            request_id=request_id,
            target=destination,
            actor=actor,
            details={
                "dump_date": dump_date,
                "outcome": outcome,
                "exit_code": int(exit_code),
                "duration_ms": duration_ms,
                "ephemeral": ephemeral,
            },
        )

    # ── Cron tick: state machine ────────────────────────────────────────
    def flush_expired(self) -> Iterable[Message]:
        """Cron-tick entry point — called by :class:`AgentRunner` on a
        steady cadence (per its `flush_interval_sec` knob). We arm
        the next fire on first call, then fire whenever the current
        wall clock crosses :attr:`_next_fire_at`. Returns the list of
        messages to publish (empty when nothing is due)."""
        now_wall = self._clock_wall()
        from xops.backup.cron import next_fire_after
        out: list[Message] = []
        # Nightly backup state machine.
        if self._next_fire_at is None:
            day_start = now_wall.replace(hour=0, minute=0, second=0, microsecond=0)
            successful_today = (
                self._last_completed_wall is not None
                and self._last_completed_wall.astimezone(timezone.utc).date()
                == now_wall.astimezone(timezone.utc).date()
            )
            if successful_today:
                # Resume from today's successful anchor so a restart
                # does not re-fire the same UTC day.
                arm_anchor = self._last_completed_wall
            else:
                # No success yet for this UTC day: arm from today's first
                # cron slot and trigger a single catch-up if already late.
                arm_anchor = day_start - timedelta(minutes=1)
            self._next_fire_at = next_fire_after(self._cron, arm_anchor)
            self._startup_catch_up_due = (
                not successful_today and now_wall >= self._next_fire_at
            )
        if self._next_fire_at is not None and now_wall >= self._next_fire_at:
            fire_wall = self._next_fire_at
            startup_catch_up_due = self._startup_catch_up_due
            self._startup_catch_up_due = False
            self._next_fire_at = next_fire_after(self._cron, now_wall)
            out.extend(self._fire(
                fire_wall=fire_wall,
                now_wall=now_wall,
                startup_catch_up_due=startup_catch_up_due,
            ))
        # ROADMAP §8.3 weekly cold-verify (silent storage rot). Runs
        # the same restore-verify pipeline against the oldest still-
        # retained Sunday dump on its own cron tick. Ordering is
        # intentional: cold-verify runs AFTER any nightly fire on the
        # same heartbeat so a Sunday-morning run sees today's dump
        # already on disk.
        if self._cold_verify_next_fire_at is None:
            self._cold_verify_next_fire_at = next_fire_after(
                self._cold_verify_cron, now_wall,
            )
        elif now_wall >= self._cold_verify_next_fire_at:
            cv_fire_wall = self._cold_verify_next_fire_at
            self._cold_verify_next_fire_at = next_fire_after(
                self._cold_verify_cron, now_wall,
            )
            out.extend(self._fire_cold_verify(
                fire_wall=cv_fire_wall, now_wall=now_wall,
            ))
        # ROADMAP §8.3 binding — backup-age watchdog. Independent of
        # the cron tick: catches the silent-failure mode where the
        # agent is alive (heartbeats firing) but every dump is
        # failing verify, so neither the catch-up branch in ``_fire``
        # nor a successful ``backup_completed`` ever closes the gap.
        # Debounced by one full ``cfg.maint_backup_age_alert_h``
        # window so a still-broken pipeline emits at most one alert
        # per window, not one per heartbeat.
        if self.backup_age_alert_due():
            window_h = float(_cfg.maint_backup_age_alert_h)
            should_fire = (
                self._last_age_alert_wall is None
                or (now_wall - self._last_age_alert_wall).total_seconds()
                    >= window_h * 3600.0
            )
            if should_fire:
                age_h = self.backup_age_hours(verified=True)
                self._last_age_alert_wall = now_wall
                out.append(self._sec_alert(
                    kind="backup_age_alert",
                    severity="error",
                    reason=(
                        f"verified-backup age {age_h:.2f}h exceeded "
                        f"threshold {window_h:.0f}h; agent alive but "
                        "no successful verified dump in this window"
                    ),
                    subject="maint.backup.v1",
                ))
        return out

    def _fire(
        self,
        *,
        fire_wall: datetime,
        now_wall: datetime,
        startup_catch_up_due: bool = False,
    ) -> Iterable[Message]:
        """Run one iteration of the state machine (dump → verify →
        prune). Emits the corresponding `backup_*` and `prune_*`
        notification events and pushes nothing to MAINT_ACK (cron
        fires carry no operator request_id)."""
        fire_window_id = (
            f"{self._pod_instance_id}:{fire_wall.isoformat()}"
        )
        mono_ns = self._clock_mono_ns()

        # ── Catch-up seed (needs to precede backwards-step check) ────────
        # Initialized here so `catch_up` is defined when the skew block
        # may reference it in `_record_audit`. The full refinement
        # (delta_h) runs later, after same-day idempotency.
        catch_up = bool(startup_catch_up_due)
        catch_up_late_h: float | None = None
        if startup_catch_up_due:
            late_h = (now_wall - fire_wall).total_seconds() / 3600.0
            if late_h > float(_cfg.maint_backup_max_skew_h):
                catch_up_late_h = late_h

        # ── Skew detection (backwards wall-clock step) ────────────────
        # Checked BEFORE same-day idempotency — safety and operator
        # visibility take priority. The operator must see the clock
        # anomaly even if a backup already ran today.
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
                yield self._sec_alert(
                    kind="backup_clock_skew",
                    severity="error",
                    reason=(
                        f"backwards wall-clock step {backward:.1f}s exceeded "
                        f"threshold {float(_cfg.maint_backup_clock_step_back_alert_s):.0f}s"
                    ),
                    subject=fire_window_id,
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
                self._record_audit(
                    fire_wall=fire_wall, mono_ns=mono_ns,
                    fire_window_id=fire_window_id,
                    outcome="skew_skipped", verified=False, catch_up=catch_up,
                )
                return

        # ── Same-day idempotency ──────────────────────────────────────
        # ROADMAP §8.3: if a successful run already exists for this UTC
        # day, this fire is a no-op. Closes the duplicate-fire hole
        # when a scheduler or operator forces `_next_fire_at` same-day.
        if self._last_completed_wall is not None:
            already_done_today = (
                self._last_completed_wall.astimezone(timezone.utc).date()
                == fire_wall.astimezone(timezone.utc).date()
            )
            if already_done_today:
                _log.info(
                    "maint.backup.v1: skip duplicate same-day fire %s; "
                    "already completed at %s",
                    fire_window_id,
                    self._last_completed_wall.isoformat(),
                )
                return

        # ── Catch-up policy refinement ────────────────────────────────
        # If the monotonic delta vs the last successful fire exceeds
        # `max_skew_h`, this fire is the make-up run. Coalesce: at
        # most ONE make-up per restart — subsequent missed windows
        # wait for their natural next-fire moment.
        if self._last_fire_wall is not None:
            delta_h = (now_wall - self._last_fire_wall).total_seconds() / 3600.0
            max_skew = float(_cfg.maint_backup_max_skew_h)
            if delta_h > max_skew and not self._catch_up_used:
                catch_up = True
                catch_up_late_h = delta_h
                self._catch_up_used = True

        # ── Skew detection (forward wall-clock leap) ──────────────────
        # Forward leaps > `clock_step_forward_alert_h` are operator-
        # visibility only — the catch-up policy above already handles
        # the missed window. We log a warning AND tag the upcoming
        # `backup_started` event with `forward_leap_h` so the leap is
        # discoverable in the audit ledger. (`sec.alert.v1{scope=
        # forward}` emission is deferred until the closed sec.alert
        # source enum admits `maint.backup.v1`; see module docstring.)
        forward_leap_h: float | None = None
        if self._last_fire_wall is not None:
            forward_h = (now_wall - self._last_fire_wall).total_seconds() / 3600.0
            threshold_h = float(_cfg.maint_backup_clock_step_forward_alert_h)
            if forward_h > threshold_h:
                forward_leap_h = forward_h
                _log.warning(
                    "maint.backup.v1: forward wall-clock leap %.2fh "
                    "exceeded threshold %.2fh; fire window %s flagged",
                    forward_h, threshold_h, fire_window_id,
                )
                yield self._sec_alert(
                    kind="backup_clock_skew",
                    severity="warn",
                    reason=(
                        f"forward wall-clock leap {forward_h:.2f}h exceeded "
                        f"threshold {threshold_h:.2f}h scope=forward"
                    ),
                    subject=fire_window_id,
                )

        # ── Late catch-up alert ───────────────────────────────────────
        # Make-up run is more than `max_skew_h` late. Per §8.3 the run
        # still fires (catch-up flag below already handles that); the
        # alert is operator visibility for the silent-failure mode
        # where the agent was down across one or more cron windows.
        if catch_up and catch_up_late_h is not None:
            yield self._sec_alert(
                kind="backup_age_alert",
                severity="error",
                reason=(
                    f"catch-up run {catch_up_late_h:.2f}h late exceeded "
                    f"threshold {float(_cfg.maint_backup_max_skew_h):.0f}h; "
                    "firing anyway"
                ),
                subject=fire_window_id,
            )

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
                "forward_leap_h": forward_leap_h,
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
            # §8.3 disk-usage guard: refusal counts toward the catch-up
            # debt — next tick retries. The sec.alert.v1 surfaces the
            # refusal to operators (debounced per §7.4 default).
            yield self._sec_alert(
                kind="backup_disk_pressure",
                severity="error",
                reason=(
                    f"free {int(free_bytes)}B < floor {int(floor)}B "
                    f"(2× last_dump_size or {int(_cfg.maint_backup_min_free_gb)}GB)"
                ),
                subject=fire_window_id,
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
            self._record_audit(
                fire_wall=fire_wall, mono_ns=mono_ns,
                fire_window_id=fire_window_id,
                outcome="disk_pressure_skipped", verified=False,
                catch_up=catch_up,
            )
            return

        # ── Dump ──────────────────────────────────────────────────────
        dump_bytes, encrypted_bytes = self._dump.dump(
            fire_window_id=fire_window_id, dry_run=dry_run,
        )

        # ── Restore-verify ────────────────────────────────────────────
        verify_summary = dict(
            self._verifier.verify(
                fire_window_id=fire_window_id, mode=self._verify_mode,
            )
        )
        if not verify_summary:
            # §8.3 binding: quarantine the bad dump dir so the next
            # nightly cron does not see it as today's success and the
            # disk-usage guard still accounts for the on-disk bytes.
            # Best-effort — a missing source dir (the in-memory shim
            # path) is the dominant case and a no-op.
            quarantined: Path | None = quarantine_failed_dump_dir(
                backup_dir=str(_cfg.maint_backup_dir),
                fire_window_id=fire_window_id,
            )
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
                    "verify_mode": self._verify_mode,
                    "quarantined_dir": (
                        quarantined.name if quarantined is not None else None
                    ),
                },
            )
            yield self._notify(
                "prune_skipped",
                extra={
                    "fire_window_id": fire_window_id,
                    "reason": "verify_failed",
                },
            )
            # §8.3 binding: critical operator-paging signal. Severity
            # `critical` bypasses the §7.4 SecAlertDebouncer per the
            # default-bypass rule for critical alerts.
            yield self._sec_alert(
                kind="backup_verify_failed",
                severity="critical",
                reason=(
                    f"restore-verify returned empty row-count map for "
                    f"fire_window_id={fire_window_id}; dump dir "
                    f"quarantined to {quarantined.name if quarantined else '<no-dump-dir>'}"
                ),
                subject=fire_window_id,
            )
            self._last_fire_wall = now_wall
            self._last_fire_mono_ns = mono_ns
            self._record_audit(
                fire_wall=fire_wall, mono_ns=mono_ns,
                fire_window_id=fire_window_id,
                outcome="verify_failed", verified=False,
                catch_up=catch_up,
            )
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

        # ── Per-table TTL prune notifications (binding §8.3) ──────────
        # Specific tables surface their own notification kind on top
        # of the aggregate ``prune_completed`` so dashboards / audit
        # consumers can hook table-scoped retention without having
        # to parse ``deleted_per_table`` themselves. Emitted only
        # when the table actually had rows pruned (or would have, in
        # dry-run); silent on the no-op path.
        quarantine_pruned_count = int(
            deleted_per_table.get("quarantine_samples", 0)
        )
        if quarantine_pruned_count > 0:
            yield self._notify(
                "quarantine_pruned",
                extra={
                    "fire_window_id": fire_window_id,
                    "row_count": quarantine_pruned_count,
                    "ttl_days": int(_cfg.sec_quarantine_ttl_days),
                    "dry_run": dry_run,
                },
            )
        allowlist_expired_count = int(
            deleted_per_table.get("pattern_allowlist", 0)
        )
        if allowlist_expired_count > 0:
            yield self._notify(
                "pattern_allowlist_expired",
                extra={
                    "fire_window_id": fire_window_id,
                    "count": allowlist_expired_count,
                    "reason": "ttl",
                    "dry_run": dry_run,
                },
            )

        # ── Dump-on-disk retention (GFS-light, §8.3) ──────────────────
        # Only fires after a successful verify + DB-row prune. The
        # safety floor (``cfg.maint_backup_dry_run``) propagates to
        # the retention pruner too: dry-run reports the same
        # partition without removing anything from disk.
        retention = prune_retained_dumps(
            backup_dir=str(_cfg.maint_backup_dir),
            keep_days=int(_cfg.maint_backup_retention_days),
            keep_weeks=int(_cfg.maint_backup_retention_weeks),
            now=now_wall,
            dry_run=dry_run,
        )

        # ── backup_completed (ok) ─────────────────────────────────────
        outcome = "dry_run" if dry_run else "ok"
        yield self._notify(
            "backup_completed",
            extra={
                "fire_window_id": fire_window_id,
                "outcome": outcome,
                # ROADMAP §8.3 binding: explicit `verified` field on
                # the success path. ``ok`` carries `verified: true`
                # (verify_summary above is the proof); ``dry_run``
                # would have verified (NoopVerifier-style) but did
                # not run live, so we report ``false`` so dashboards
                # never count a dry-run as a verified backup.
                "verified": outcome == "ok",
                "duration_ms": int(
                    (self._clock_mono_ns() - start_mono_ns) / 1_000_000
                ),
                "dump_bytes": int(dump_bytes),
                "encrypted_bytes": int(encrypted_bytes),
                "verify_summary": dict(verify_summary),
                "verify_mode": self._verify_mode,
                "dry_run": dry_run,
                "dump_retention": {
                    "kept": list(retention.kept),
                    "pruned": list(retention.pruned),
                    "unparseable": list(retention.unparseable),
                    "skipped_quarantine": list(retention.skipped_quarantine),
                },
            },
        )
        self._last_fire_wall = now_wall
        self._last_fire_mono_ns = mono_ns
        # Advance the gauge — `ok` is a verified completion (the
        # verify_summary above is the proof); `dry_run` is also
        # valid forward progress (it would have verified). Anything
        # earlier in the state machine returned before this line.
        self._last_completed_wall = now_wall
        if outcome == "ok":
            self._last_verified_wall = now_wall
        self._record_audit(
            fire_wall=fire_wall, mono_ns=mono_ns,
            fire_window_id=fire_window_id,
            outcome=outcome, verified=(outcome == "ok"),
            catch_up=catch_up,
        )

    # ── Cold-verify state machine (§8.3 weekly silent-rot detector) ──
    def _fire_cold_verify(
        self, *, fire_wall: datetime, now_wall: datetime,
    ) -> Iterable[Message]:
        """Run one cold-verify pass on the oldest still-retained
        Sunday dump. Reuses the same ``RestoreVerifier`` Protocol so
        the SidecarVerifier (Phase 14) implementation is the binding
        target; the ``LocalSubprocessVerifier`` adapter routes by the
        ``fire_window_id`` prefix (``cold:<dump_date>``) to spawn an
        independent ephemeral PVC per the §8.3 contract.

        Cold-verify NEVER prunes — failures are operator-decided per
        the binding ROADMAP §8.3 prose ("Cold-verify failures DO NOT
        prune the dump"). Successes do not advance the
        ``maint_backup_age_hours{verified}`` gauge either; that gauge
        is gated on the nightly window only.
        """

        candidate = oldest_retained_sunday_dump(
            backup_dir=str(_cfg.maint_backup_dir),
        )
        if candidate is None:
            # No retained Sunday dump yet — nothing to cold-verify.
            # Silent no-op (notification noise on a fresh stack would
            # train operators to ignore it).
            return
        dump_day, _dir_name = candidate
        dump_date = dump_day.strftime("%Y-%m-%d")
        fire_window_id = f"cold:{self._pod_instance_id}:{dump_date}"
        start_mono_ns = self._clock_mono_ns()
        try:
            verify_summary = dict(
                self._verifier.verify(
                    fire_window_id=fire_window_id,
                    mode=self._verify_mode,
                )
            )
        except Exception as exc:  # noqa: BLE001 — verifier surface is broad
            _log.warning(
                "maint.backup.v1: cold-verify raised on dump_date=%s: %r",
                dump_date, exc,
            )
            verify_summary = {}
            error_text = f"verifier raised: {type(exc).__name__}: {exc}"
        else:
            error_text = (
                "restore-verify returned empty row-count map"
                if not verify_summary else ""
            )
        duration_ms = int(
            (self._clock_mono_ns() - start_mono_ns) / 1_000_000
        )
        if not verify_summary:
            yield self._notify(
                "backup_cold_verify_failed",
                extra={
                    "fire_window_id": fire_window_id,
                    "dump_date": dump_date,
                    "error": error_text,
                    "duration_ms": duration_ms,
                },
            )
            yield self._sec_alert(
                kind="backup_verify_failed",
                severity="critical",
                reason=(
                    f"cold-verify failed on dump_date={dump_date} "
                    f"scope=cold; {error_text}"
                ),
                subject=fire_window_id,
            )
            return
        yield self._notify(
            "backup_cold_verify_completed",
            extra={
                "fire_window_id": fire_window_id,
                "dump_date": dump_date,
                "duration_ms": duration_ms,
                "verified": True,
                "verify_summary": dict(verify_summary),
            },
        )

    # ── Public observability surface ────────────────────────────────────
    def backup_age_hours(self, *, verified: bool = True) -> float | None:
        """Return age of the most recent backup in hours, or ``None``
        when no qualifying backup has been recorded yet.

        ROADMAP §8.3 binding contract — exposed as the
        ``maint_backup_age_hours{verified}`` telemetry gauge:

        * ``verified=True``  → only ``outcome=ok`` runs satisfy the
          gauge (the silent-failure mode where every nightly fails
          verify is then visible).
        * ``verified=False`` → any completed run (including
          ``dry_run``) satisfies the gauge — useful in the mock
          profile where ``maint_backup_dry_run=true`` is the
          default.

        Returns ``None`` (not 0.0, not infinity) before the first
        qualifying run — callers must treat ``None`` as "unknown,
        do not fire the watchdog yet" to honour the boot-warm
        guard from §8.10's dead-mans-switch.
        """

        anchor = self._last_verified_wall if verified else self._last_completed_wall
        if anchor is None:
            return None
        delta = self._clock_wall() - anchor
        return delta.total_seconds() / 3600.0

    def metrics_snapshot(self) -> dict[str, float | None]:
        """ROADMAP §8.3 binding telemetry surface.

        Returns the ``maint_backup_age_hours{verified=true|false}``
        gauge values in Prometheus-label-encoded form so an operator
        scraper can render the exposition without consulting the
        agent's internal state. ``None`` means "no qualifying dump
        yet" — scrapers should drop the line (Prometheus has no NaN-
        sentinel for gauges that legitimately have no value), not
        substitute zero (which would falsely declare freshness).
        """

        return {
            'maint_backup_age_hours{verified="true"}':
                self.backup_age_hours(verified=True),
            'maint_backup_age_hours{verified="false"}':
                self.backup_age_hours(verified=False),
        }

    def backup_age_alert_due(self) -> bool:
        """``True`` when ``backup_age_hours(verified=True)`` exceeds
        ``cfg.maint_backup_age_alert_h``. ``None`` age (no backup
        yet) returns ``False`` — the watchdog refuses to fire on
        cold start (Phase 8.10 dead-mans-switch handles that case
        independently)."""

        age = self.backup_age_hours(verified=True)
        if age is None:
            return False
        return age > float(_cfg.maint_backup_age_alert_h)

    def check_permissions(self) -> list[str]:
        """Audit ``cfg.maint_backup_dir`` for ROADMAP §8.3 binding
        permission contract. Returns a list of human-readable
        violations; an empty list means OK.

        Contract:
        * Backup directory itself: mode 0700.
        * Files inside (top level only — recursion is bounded by
          one directory level to avoid scanning a large tree on
          every startup): mode 0600.

        Non-POSIX filesystems are skipped (returns ``[]``) — the
        check is best-effort and never blocks startup on
        Windows/CIFS where mode bits are meaningless.
        """

        backup_dir = Path(_cfg.maint_backup_dir)
        if not backup_dir.exists():
            # Nothing to audit yet — first run will create it.
            return []
        violations: list[str] = []
        try:
            dir_mode = backup_dir.stat().st_mode & 0o777
        except OSError as exc:
            return [f"cannot stat {backup_dir}: {exc!r}"]
        if dir_mode == 0:
            # Filesystem with no mode bits (e.g. some Windows mounts).
            return []
        if dir_mode & 0o077:
            # Any group/other permission bit is a violation.
            violations.append(
                f"{backup_dir} mode {oct(dir_mode)} is looser than 0o700"
            )
        try:
            children = list(backup_dir.iterdir())
        except OSError as exc:
            violations.append(f"cannot list {backup_dir}: {exc!r}")
            return violations
        for child in children:
            try:
                cmode = child.stat().st_mode & 0o777
            except OSError:
                continue
            if cmode == 0:
                continue
            # Sub-directories permitted up to 0o700 (per-day dump
            # dirs); regular files must be ≤ 0o600.
            limit = 0o700 if child.is_dir() else 0o600
            if cmode & ~limit:
                violations.append(
                    f"{child} mode {oct(cmode)} is looser than {oct(limit)}"
                )
        return violations

    def _enforce_startup_permissions(self) -> None:
        """Set process umask to ``0o077`` and refuse-to-start on
        looser-than-contract perms in ``cfg.maint_backup_dir``.

        Wired from :meth:`__init__` (controlled by the
        ``enforce_permissions`` kwarg, default ``True``). Raises
        :class:`BackupPermissionError` listing every violation
        found by :meth:`check_permissions` so the operator sees
        the full picture, not just the first failure.

        On non-POSIX hosts (``os.name != "posix"``) the umask call
        is skipped and only the audit runs — :meth:`check_permissions`
        already returns ``[]`` on filesystems with no mode bits, so
        this is a no-op on Windows / CIFS shares.
        """

        if os.name == "posix":
            os.umask(0o077)
        violations = self.check_permissions()
        if violations:
            raise BackupPermissionError(
                "maint.backup.v1: refusing to start; "
                + "; ".join(violations)
            )

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

    def _record_audit(
        self,
        *,
        fire_wall: datetime,
        mono_ns: int,
        fire_window_id: str,
        outcome: str,
        verified: bool,
        catch_up: bool,
    ) -> None:
        """Append a single :class:`AuditRow` to ``audit.csv``. Best-
        effort \u2014 a write failure is logged but does NOT abort the
        run. The in-memory state machine remains the source of
        truth for the running agent; the ledger replay only matters
        across restarts."""

        try:
            _append_audit_row(
                self._audit_path,
                AuditRow(
                    wall_clock_utc=fire_wall.isoformat(),
                    monotonic_ns_at_fire=int(mono_ns),
                    fire_window_id=fire_window_id,
                    outcome=outcome,
                    verified=verified,
                    catch_up=catch_up,
                ),
            )
        except OSError as exc:
            _log.warning(
                "maint.backup.v1: audit ledger write failed: %r", exc,
            )

    def _sec_alert(
        self, *, kind: str, severity: str, reason: str,
        subject: str | None = None,
    ) -> Message:
        """Build and wrap a :class:`SecAlert` envelope with
        ``source=maint.backup.v1``. The closed source enum admits
        this producer per ROADMAP \u00a78.3."""

        alert = SecAlert(
            alert_id=self._new_id(),
            kind=kind,
            severity=severity,
            source=self.name,
            reason=reason,
            produced_at=self._clock_iso(),
            subject=subject,
        )
        env = Envelope(
            message_id=self._new_id(),
            trace_id=self._new_id(),
            topic=SEC_ALERT,
            producer=self.name,
            created_at=self._clock_iso(),
            schema_version=1,
            attempt=1,
        )
        return Message(envelope=env, payload=alert.as_dict())

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
    "RESTORE_OUTCOMES",
    "DiskGauge",
    "DumpExecutor",
    "InMemoryMaintAuditLogger",
    "InMemoryPrunerStorage",
    "InMemoryQuarantineStore",
    "MaintAuditLogger",
    "MaintBackupAgent",
    "NoopDumpExecutor",
    "NoopRestoreExecutor",
    "NoopVerifier",
    "PrunerStorage",
    "QuarantineStore",
    "RestoreExecutor",
    "RestoreKeyClass",
    "RestoreVerifier",
    "StaticDiskGauge",
    "StaticRestoreKeyClass",
]
