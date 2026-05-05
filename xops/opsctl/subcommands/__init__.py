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

from . import denylist_clear, liveness, quarantine_erase

# Iteration order is the order subcommands appear in `opsctl --help`.
SUBCOMMANDS = (liveness, denylist_clear, quarantine_erase)

__all__ = ["SUBCOMMANDS", "denylist_clear", "liveness", "quarantine_erase"]
