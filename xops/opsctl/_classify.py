"""xops.opsctl — destructive-operation classifier (Phase 8 §8.1).

A subcommand is "destructive" iff its effect is hard to revert by
re-running another opsctl command (e.g. wiping a quarantine sample,
restoring a backup over live data, dropping a denylist for a
critical-agent target). The classifier returns a stable token that
the publisher uses to gate behavior:

* ``Action.SAFE`` — no operator confirmation required.
* ``Action.CONFIRM`` — operator must pass ``--confirm`` (typed token).
* ``Action.REFUSE`` — operator-driven path forbidden in this profile
  (e.g. ``ops.dlq-replay --topic sec.alert.v1`` without
  ``--confirm-pii``).

This module is pure (no I/O, no env reads at import time) so it is
safe to call from tests without mocking. The critical-agent set is
sourced from :attr:`Config.opsctl_critical_agents_set` at the
caller site, NOT here, to keep the function injectable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional


class Action(Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    REFUSE = "refuse"


# Subcommand names that are ALWAYS destructive regardless of args.
# Adding a name here is a minor bump on the ``xops`` component.
ALWAYS_DESTRUCTIVE: FrozenSet[str] = frozenset({
    "quarantine-erase",
    "restore",
    "backup-rotate-key",
})


# Subcommand names that are NEVER destructive (read-only / advisory).
ALWAYS_SAFE: FrozenSet[str] = frozenset({
    "liveness",
    "spool-show",
    "allowlist-show",
    "scale-unpin",
})


@dataclass(frozen=True)
class ClassifyRequest:
    """Inputs to the destructive-op classifier.

    ``target_agent`` is set when the subcommand acts on a specific
    agent id (e.g. ``ops.maint-pause --agent sec.rate.v1``); critical
    agents (per ``cfg.opsctl_critical_agents_set``) bump otherwise-safe
    operations into the CONFIRM tier.
    """

    subcommand: str
    target_agent: Optional[str] = None
    critical_agents: FrozenSet[str] = frozenset()
    # Free-form flag bag for flag-driven destructiveness (e.g.
    # ``dlq_replay`` with ``drop=True`` is destructive). Keys are
    # subcommand-defined; the classifier only inspects keys it knows.
    flags: FrozenSet[str] = frozenset()


def classify(req: ClassifyRequest) -> Action:
    """Return the :class:`Action` tier for an opsctl invocation.

    The classifier is deterministic and side-effect-free.
    """
    name = req.subcommand
    if name in ALWAYS_DESTRUCTIVE:
        return Action.CONFIRM
    if name in ALWAYS_SAFE:
        return Action.SAFE
    # Critical-agent gate: any operation targeting a critical agent
    # bumps from SAFE to CONFIRM. The set is small (3 entries by
    # default) so set membership is the right primitive.
    if req.target_agent and req.target_agent in req.critical_agents:
        return Action.CONFIRM
    # Subcommand-flag-driven destructiveness (Phase 8 §8.1 destructive
    # set: scale=0, dlq-replay --drop, dlq-replay sec.* --confirm-pii).
    if name == "scale" and "replicas_zero" in req.flags:
        return Action.CONFIRM
    if name == "scale" and "reduction_over_50pct" in req.flags:
        return Action.CONFIRM
    if name == "dlq-replay" and "drop" in req.flags:
        return Action.CONFIRM
    if name == "dlq-replay" and "topic_sec" in req.flags and "confirm_pii" not in req.flags:
        return Action.REFUSE
    return Action.SAFE


__all__ = ["Action", "ClassifyRequest", "classify", "ALWAYS_DESTRUCTIVE", "ALWAYS_SAFE"]
