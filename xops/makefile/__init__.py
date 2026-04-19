"""
xops.makefile — task scripts dispatched from the project Makefile.

Each module here owns one section of the Makefile. Make targets remain
the user-facing surface (Make handles dependency wiring); the modules
contain the actual cross-platform logic.

Layout
------
- _common.py     : shared helpers (compose runner, pretty logger, paths)
- env.py         : `make env`            — bootstrap .env from .env.example
- services.py    : `make build|up|up-detached|down|restart|ai|server|infra`
- ai_commands.py : `make scrape|bootstrap|train*|ai-*` (AI/training/backtest)
- server_api.py  : `make server-health|server-matches|server-teams|server-scrape`
- db.py          : `make db-migrate|db-seed|db-shell|db-reset|redis-shell`
- logs.py        : `make logs|logs-ai|logs-server`
- tests.py       : `make test|test-ai|test-integration`
- cleanup.py     : `make clean|clean-all|clean-data`
- status.py      : `make health|status|ports`
- git_helper.py  : `make git|git.dry`    — HUMAN-ONLY commit/push driver

Targets that are already thin Python wrappers (the `track-*` family
calls `docs/tracking/track.py` directly) and `help` (Makefile-native
self-scan) intentionally remain inline in the Makefile.

Conventions
-----------
- Stdlib only. Python 3.8+.
- One function per Make target; dispatched by a tiny `main(argv)` per module.
- Long-running interactive commands use `_common.compose_exec()` which
  hands the TTY off to `docker compose` via `os.execvp` (no extra layer).
- Multi-step orchestration uses `_common.compose_run()` (subprocess).
- All paths are derived from `_common.REPO_ROOT` — never CWD-dependent.
"""
