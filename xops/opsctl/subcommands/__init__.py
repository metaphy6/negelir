"""xops.opsctl subcommand registry (Phase 8 §8.1).

Each subcommand is a single module exposing two callables:

  ``add_parser(subparsers) -> argparse.ArgumentParser``
      register the CLI sub-parser; the function MUST set
      ``parser.set_defaults(func=run)`` so the dispatcher can route.

  ``run(args, *, bus=None) -> int``
      perform the operation; return one of the
      :class:`~xops.opsctl._exit_codes.ExitCode` values.

The ``bus`` kwarg is injected by tests; production
``__main__`` constructs a real bus and passes it through.
"""
from __future__ import annotations

from . import (
    allowlist_approve,
    allowlist_extend,
    allowlist_rehash,
    allowlist_show,
    backup_now,
    backup_rotate_key,
    nlp_flame_capture,
    nlp_kill_pattern,
    baseline_reset,
    bootstrap_allowlist_key,
    bootstrap_key,
    verify_key_id,
    denylist_clear,
    denylist_decimate_now,
    dlq_replay,
    dlq_show,
    dlq_resume,
    dlq_unfreeze,
    liveness,
    maint_pause,
    maint_resume,
    quarantine_clear,
    quarantine_erase,
    restore,
    retrain_approve,
    rotate_allowlist_key,
    revoke_key,
    rotate_key,
    scale,
    scale_pin,
    scale_unpin,
    spool_flush,
    spool_show,
)

# Iteration order is the order subcommands appear in `opsctl --help`.
SUBCOMMANDS = (
    liveness,
    denylist_clear,
    denylist_decimate_now,
    baseline_reset,
    quarantine_clear,
    quarantine_erase,
    spool_flush,
    spool_show,
    maint_pause,
    maint_resume,
    scale,
    scale_pin,
    scale_unpin,
    dlq_show,
    dlq_replay,
    dlq_unfreeze,
    retrain_approve,
    backup_now,
    backup_rotate_key,
    restore,
    allowlist_extend,
    allowlist_approve,
    nlp_flame_capture,
    allowlist_show,
    allowlist_rehash,
    rotate_allowlist_key,
    dlq_resume,
    bootstrap_allowlist_key,
    bootstrap_key,
    revoke_key,
    rotate_key,
    verify_key_id,
    nlp_kill_pattern,
)

__all__ = [
    "SUBCOMMANDS",
    "bootstrap_key",
    "allowlist_approve",
    "allowlist_extend",
    "allowlist_rehash",
    "allowlist_show",
    "backup_now",
    "backup_rotate_key",
    "baseline_reset",
    "bootstrap_allowlist_key",
    "denylist_clear",
    "denylist_decimate_now",
    "dlq_replay",
    "dlq_show",
    "dlq_resume",
    "dlq_unfreeze",
    "liveness",
    "maint_pause",
    "maint_resume",
    "quarantine_clear",
    "quarantine_erase",
    "restore",
    "retrain_approve",
    "rotate_allowlist_key",
    "revoke_key",
    "rotate_key",
    "scale",
    "scale_pin",
    "scale_unpin",
    "spool_flush",
    "spool_show",
    "verify_key_id",
    "nlp_flame_capture",
    "nlp_kill_pattern",
]
