"""
xops.makefile — task scripts dispatched from the project Makefile.

Each module here owns one section of the Makefile. Make targets remain
the user-facing surface (Make handles dependency wiring); the modules
contain the actual cross-platform logic.

Layout
------
- _common.py     : shared helpers (compose runner, pretty logger, paths)
- env.py         : `make env`            — bootstrap xops/env/.env from xops/env/.env.example
- services.py    : `make up|down|restart|ai|server|infra`           (DETACH=1 backgrounds `up`)
- ai_commands.py : `make scrape|bootstrap|train|train-model|backtest|ai.*`
- server_api.py  : `make api ENDPOINT=… METHOD=…`
- db.py          : `make db.migrate|db.seed|db.shell|db.reset|cache.shell`
- logs.py        : `make logs`           (SVC=ai|server|… for one service)
- tests.py       : `make test|test.ai|test.integration`
- cleanup.py     : `make clean|clean.all`           (DATA=1 also wipes ./data)
- status.py      : `make health|status|ports`
- mock.py        : `make mock.*`
- hosts.py       : `make hosts.install|uninstall|status|preview`
- watch.py       : `make watch.run|watch.history|watch.sources`
- version.py     : `make version.show|bump|validate`
- lint.py        : `make lint`
- git_helper.py  : `make git|git.dry`    — HUMAN-ONLY commit/push driver

Targets that are already thin Python wrappers (the `track.*` family
calls `docs/tracking/track.py` directly) and `help` (Makefile-native
self-scan) intentionally remain inline in the Makefile.

Convention
----------
Daily verbs stay flat: env, up, down, restart, logs, test, lint, train,
scrape, bootstrap, backtest, help. Everything else is `domain.action`.
Legacy `verb-noun` aliases (db-seed, ai-train, etc.) print a
deprecation warning and dispatch to the new name; slated for removal
one release after the rename ships.

Conventions
-----------
- Stdlib only. Python 3.8+.
- One function per Make target; dispatched by a tiny `main(argv)` per module.
- Long-running interactive commands use `_common.compose_exec()` which
  hands the TTY off to `docker compose` via `os.execvp` (no extra layer).
- Multi-step orchestration uses `_common.compose_run()` (subprocess).
- All paths are derived from `_common.REPO_ROOT` — never CWD-dependent.
"""
