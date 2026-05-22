"""Phase 8 §8.16.3 — backup-vs-prune strict state machine.

The ``maint.backup.v1`` agent's nightly tick is a **strict** three-phase
sequence:

    IDLE → DUMP → RESTORE_VERIFY → PRUNE → IDLE

Each phase emits its own ``maint.event.v1`` events and the machine refuses
to advance to the next phase if the prior one did not emit success.

**Operator overrides:**

* ``--skip-prune``: the dump + verify phases run normally; after a verified
  dump the machine transitions to IDLE (emitting ``prune_skipped``) instead
  of entering PRUNE.
* ``--prune-only``: **FORBIDDEN**.  Attempting to trigger it raises
  :class:`PruneOnlyForbiddenError` (exit code
  :data:`xops.opsctl._exit_codes.ExitCode.PRUNE_ONLY_FORBIDDEN` = 10).

This eliminates the misconfig where a standalone prune drops live data
before a dump has been taken.
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Any


class BackupPhase(Enum):
    IDLE = auto()
    DUMP = auto()
    RESTORE_VERIFY = auto()
    PRUNE = auto()


class PruneOnlyForbiddenError(RuntimeError):
    """Raised when ``--prune-only`` is requested.

    Exit code: :data:`xops.opsctl._exit_codes.ExitCode.PRUNE_ONLY_FORBIDDEN`
    (= 10).  A separate prune path without a preceding dump is never safe
    because it may delete live rows that have not yet been captured in a
    backup.
    """


class BackupStateMachineError(RuntimeError):
    """Raised when a state-machine guard rejects an invalid transition."""


class BackupStateMachine:
    """Strict state machine governing the backup → verify → prune sequence.

    The machine tracks the current phase and the emitted event history.
    Callers drive it via the transition methods; the machine appends
    *event dicts* to the internal :attr:`events` list that the caller
    can forward to ``maint.event.v1``.

    Typical flow::

        sm = BackupStateMachine()
        sm.start_dump()                   # IDLE → DUMP; backup_started
        sm.dump_complete(verified=True)   # DUMP → RESTORE_VERIFY → PRUNE
                                          # events: backup_completed, prune_started
        sm.prune_complete()               # PRUNE → IDLE; prune_completed

    Failed-dump flow::

        sm = BackupStateMachine()
        sm.start_dump()
        sm.dump_complete(verified=False)  # → IDLE; prune_skipped
        # prune phase was never entered

    skip-prune flow::

        sm = BackupStateMachine(skip_prune=True)
        sm.start_dump()
        sm.dump_complete(verified=True)   # → IDLE; prune_skipped
    """

    def __init__(self, skip_prune: bool = False) -> None:
        self._phase = BackupPhase.IDLE
        self._skip_prune = skip_prune
        self.events: list[dict[str, Any]] = []

    # ── public transition API ────────────────────────────────────────────

    @classmethod
    def prune_only(cls) -> None:
        """Raises :class:`PruneOnlyForbiddenError` unconditionally.

        Call-sites wiring the ``--prune-only`` CLI flag must call this
        method so the doctrinal refusal is centralised here and not
        scattered in the argument-parser handling.
        """
        raise PruneOnlyForbiddenError(
            "fail_safe_prune_order_invalid: --prune-only is FORBIDDEN "
            "(exit code PRUNE_ONLY_FORBIDDEN=10).  A prune without a "
            "preceding verified dump may silently delete live data.  "
            "Use --skip-prune to dump without pruning, or run a full cycle."
        )

    @property
    def phase(self) -> BackupPhase:
        return self._phase

    def start_dump(self) -> None:
        """IDLE → DUMP.  Emits ``backup_started``."""
        self._require_phase(BackupPhase.IDLE, "start_dump")
        self._phase = BackupPhase.DUMP
        self._emit("backup_started")

    def dump_complete(self, *, verified: bool) -> None:
        """DUMP → RESTORE_VERIFY (then immediately decide on PRUNE).

        If ``verified=True`` and ``skip_prune=False``: enters PRUNE and
        emits ``backup_completed`` + ``prune_started``.

        If ``verified=False`` **or** ``skip_prune=True``: transitions to
        IDLE and emits ``backup_completed`` + ``prune_skipped``.
        """
        self._require_phase(BackupPhase.DUMP, "dump_complete")
        self._phase = BackupPhase.RESTORE_VERIFY
        self._emit("backup_completed", verified=verified)

        if verified and not self._skip_prune:
            self._phase = BackupPhase.PRUNE
            self._emit("prune_started")
        else:
            reason = "dump_failed" if not verified else "skip_prune_flag"
            self._phase = BackupPhase.IDLE
            self._emit("prune_skipped", reason=reason)

    def start_prune(self) -> None:
        """No-op convenience: validates we are already in PRUNE phase.

        :meth:`dump_complete` already transitions to PRUNE and emits
        ``prune_started``; this method is available for callers that prefer
        an explicit guard before the actual DELETE work begins.
        """
        self._require_phase(BackupPhase.PRUNE, "start_prune")

    def prune_complete(self) -> None:
        """PRUNE → IDLE.  Emits ``prune_completed``."""
        self._require_phase(BackupPhase.PRUNE, "prune_complete")
        self._phase = BackupPhase.IDLE
        self._emit("prune_completed")

    # ── helpers ──────────────────────────────────────────────────────────

    def _require_phase(self, expected: BackupPhase, method: str) -> None:
        if self._phase is not expected:
            raise BackupStateMachineError(
                f"BackupStateMachine.{method}() called in phase "
                f"{self._phase.name!r} (expected {expected.name!r})"
            )

    def _emit(self, kind: str, **kwargs: Any) -> None:
        event: dict[str, Any] = {"kind": kind}
        event.update(kwargs)
        self.events.append(event)


__all__ = [
    "BackupPhase",
    "BackupStateMachine",
    "BackupStateMachineError",
    "PruneOnlyForbiddenError",
]
