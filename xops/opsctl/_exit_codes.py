"""xops.opsctl exit codes (Phase 8 §8.1, §8.13, §8.14, §8.15).

Each code maps to a single, distinguishable operator failure mode so
runbooks + the dead-mans-switch alerter can act without parsing
stderr. Adding a new code is a minor bump on the ``xops`` component.

Ranges:
  * 0           — success
  * 1           — generic failure (unexpected exception; CLI bug)
  * 2..63       — operator-recoverable failures
  * 64..127     — usage errors (mirrors sysexits.h EX_USAGE et al.)

Code 64 (``BAD_USAGE``) is reserved for argparse-level failures so
operator scripts can distinguish "I typed the command wrong" from
"the system rejected my well-formed request".
"""
from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    GENERIC_FAILURE = 1

    # Phase 8 §8.1 baseline (envelope publish flow).
    HARD_TIMEOUT = 2
    """No acks received within ``opsctl_ack_timeout_ms``."""

    PARTIAL_ACK_TIMEOUT = 3
    """At least one but not all of expected_ack_set acked in time."""

    BUS_DOWN_SPOOLED = 4
    """Publish failed; envelope written to opsctl_spool_dir for later
    replay via ``make ops.spool-flush``."""

    NO_CONSUMER_FOR_KIND = 5
    """Kind is known but ``expected_ack_set`` is empty (either truly
    unbound or pending a future-phase consumer landing). Distinct
    from a generic argparse failure so runbooks can branch on it."""

    UNKNOWN_KIND = 6
    """Kind discriminator is not present in
    :data:`ai.swarm.agents.maint._ack_routing._ACK_ROUTING_TABLE`.
    Bound by the docstring of that module — do NOT renumber."""

    # Phase 8 §8.13.2 reserved (storage cap exhausted).
    MAINT_STORAGE_FULL = 11
    REQUIRES_RESUME_FIRST = 7

    # Phase 8 §8.14.10 reserved (spool flush concurrency guard).
    SPOOL_FLUSH_ALREADY_RUNNING = 8

    # Phase 8 §8.15.4 reserved (operator HMAC key revocation).
    OPSCTL_KEY_REVOKED = 9

    # Phase 8 §8.13.6 reserved (backup state-machine forbids prune-only).
    PRUNE_ONLY_FORBIDDEN = 10

    # Phase 8 §8.14.4 — opsctl ACL user mismatch (boot-time safety gate).
    # The opsctl process authenticated to Redis with a user other than
    # ``negelir_opsctl``.  Using the application user's full-access
    # credentials would defeat the per-subcommand ACL restriction.
    FAIL_SAFE_WRONG_REDIS_USER = 12

    BAD_USAGE = 64
    """argparse / required-arg-missing failures."""


__all__ = ["ExitCode"]
