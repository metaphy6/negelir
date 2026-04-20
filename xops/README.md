# `xops/` — DevOps & Tooling

This tree owns every piece of repo automation that isn't application
code: CI/CD, build/run helpers, deployment hooks, dev-stack drivers,
release tooling. Everything here is **stdlib-only Python (3.8+)** unless
explicitly noted, so contributors on Linux, macOS, or Windows can run
the same commands without installing anything beyond Python and
Docker.

## Layout

```
xops/
├── README.md            ← you are here
├── makefile/            ← scripts dispatched from the project Makefile
│   ├── __init__.py      ← module map + conventions
│   ├── _common.py       ← shared helpers (compose runner, logger, paths)
│   ├── env.py           ← `make env`
│   ├── services.py      ← `make build|up|up-detached|down|restart|ai|server|infra`
│   ├── ai_commands.py   ← `make scrape|bootstrap|train*|ai-*` (AI workloads)
│   ├── server_api.py    ← `make server-*`        (Go server REST helpers)
│   ├── db.py            ← `make db-*|redis-shell`
│   ├── logs.py          ← `make logs|logs-ai|logs-server`
│   ├── tests.py         ← `make test|test-ai|test-integration`
│   ├── cleanup.py       ← `make clean|clean-all|clean-data`
│   ├── status.py        ← `make health|status|ports`
│   ├── lint.py          ← `make lint`
│   ├── mock.py          ← `make mock.*`          (Phase 2 dev stack)
│   ├── hosts.py         ← `make hosts.*`         (Phase 2.3 /etc/hosts)
│   ├── version.py       ← `make version.*`       (SemVer chart CLI)
│   └── git_helper.py    ← `make git|git.dry`     (HUMAN-ONLY)
├── lint/                ← `xops.lint.*` rules consumed by `make lint`
│   └── no_magic.py      ← Phase 1.4 hardcode audit
├── mock/                ← Phase 2 mock-data helpers (host-side, stdlib only)
│   ├── manifest.py      ← seed-corpus schema + sha256 verifier
│   ├── verify.py        ← offline integrity check (runs in CI)
│   ├── capture.py       ← one-shot real-internet refresher (HUMAN-ONLY)
│   └── tests/           ← pytest suite
└── versioning/          ← centralized SemVer chart
    ├── chart.json       ← single source of truth — only mutated by version.py
    ├── version.py       ← CLI: show / bump / validate / components
    └── tests/           ← canonical-form guard + bump semantics tests
```

Future siblings of `makefile/` will hold scripts grouped by surface:
`xops/ci/` for GitHub-Actions helpers, `xops/deploy/` for cloud release
glue, `xops/release/` for changelog/version tooling, and so on. Each
sub-tree should follow the same convention: stdlib-only Python, one
module per logical area, dispatched by tiny `main(argv)` functions.

## Conventions

- **Stdlib only.** No third-party deps in `xops/` itself. The dev stack
  may install heavy libraries inside containers; tooling on the host
  must not require `pip install …`.
- **Python 3.8+.** Mirrors `docs/tracking/track.py`.
- **Cross-platform.** No bash-isms, no shell pipelines, no
  POSIX-only assumptions. Use `pathlib`, `subprocess`, `urllib`,
  `shutil`, `os.execvp` for TTY hand-off.
- **Make is the dependency graph; Python is the work.** The Makefile
  keeps target-to-target dependencies (`build: env`, etc.). Each Make
  target body is a one-line `@$(XOPS)/<module>.py <subcommand>` call.
- **One module per Makefile section** (matching the `# ── X ──` headers
  in the Makefile). Within a module, one function per Make target,
  dispatched by `_common.dispatch()`.
- **Read paths from `_common.REPO_ROOT`** — never CWD-dependent.
- **Compose binary is overridable** via the `NEGELIR_COMPOSE` env var
  (e.g. `NEGELIR_COMPOSE="podman-compose" make up`).

## What stays inline in the Makefile

Two sections deliberately remain inline rather than dispatching to
`xops/makefile/`:

1. **`track-list`/`track-show`/`track-add`/`track-export`** — already
   thin wrappers around the canonical tracker CLI at
   `docs/tracking/track.py`. Routing them through another Python script
   would add a layer with no value.
2. **`help`** — uses `grep` + `awk` over `$(MAKEFILE_LIST)` to
   self-scan target docstrings. That's a Makefile-native idiom that
   doesn't translate cleanly to Python.

## Adding a new Make target

1. Pick (or add) the right module under `xops/makefile/`.
2. Add a `cmd_<target>(argv)` function and register it in that module's
   `COMMANDS` dict.
3. Add a Make target that dispatches to it:

   ```makefile
   .PHONY: my-thing
   my-thing: env ## Short help text shown by `make help`
       @$(XOPS)/<module>.py my-thing [--flag $(MY_VAR)]
   ```
4. If the target needs its own variable, add a `MY_VAR ?= default` line
   near the top of the Makefile.
5. Run `make help` to confirm the new target appears.

## Adding a brand-new tooling area

For a new surface (e.g. CI helpers), create `xops/<area>/` with the
same `__init__.py` + `_common.py` + per-module structure. Document the
entry points in this README and any consuming workflow files.
