---
description: Make + xops automation conventions
applyTo: 'Makefile,xops/makefile/**,xops/mock/**,xops/lint/**,xops/versioning/**,xops/mcp/**'
---

# Make + xops — automation conventions

Doctrine lives in [`AGENTS.md`](../../AGENTS.md) §5. This file
restates only the bits that bite when editing Make / xops.

## The dispatcher pattern

- Make targets are **one-line dispatchers** to a Python module
  under `xops/makefile/<module>.py`:
  ```make
  .PHONY: foo.bar
  foo.bar: ## what it does
      @$(XOPS)/<module>.py bar
  ```
- One module per Makefile section, one `cmd_<target>(argv)`
  function per target, registered in that module's `COMMANDS`
  dict, dispatched via `_common.dispatch()`.
- Make owns the dependency graph; Python owns the work.
  Do not put non-trivial logic in the Makefile.

## Cross-platform

- Anything in `Makefile` or `xops/makefile/**` must work on Linux,
  macOS, and Windows (`AGENTS.md` §5).
- No bash-isms in shared scripts. Use `pathlib`, `subprocess`,
  `shutil` — never `os.system`.
- Stdlib-only for tooling unless absolutely necessary
  (`AGENTS.md` §6).

## Adding a new target

1. Pick or create the right module under `xops/makefile/`.
2. Add `cmd_<target>(argv)` and register it in `COMMANDS`.
3. Add a one-line Make target calling
   `@$(XOPS)/<module>.py <target>`.
4. Confirm via `make help`.

## Sanctioned `sudo` callers

Per `AGENTS.md` Rule 9, only these five targets may call `sudo`:
`make hosts.install`, `make hosts.uninstall`, `make mock.trust`,
`make mock.untrust`, `make mock.setup`. They are scoped to writing
`/etc/hosts` and installing the local dev root CA — both reversible
by their `*.uninstall` / `*.untrust` counterparts. The agent **may**
run them itself when the dev stack needs them; VS Code will prompt
for confirmation since they are intentionally **not** in the
`.vscode/settings.json` auto-approve list. Do not introduce new
`sudo` callers without a doctrine update.

## Forbidden surfaces

- `xops/makefile/git_helper.py` and `make git` are **human-only**
  (`AGENTS.md` Rule 9). Never call them from agent flows.
- `xops/versioning/chart.json` is **never** edited by hand —
  always go through `make version.bump` (`AGENTS.md` §6.1).

## Style

- New modules start with `from __future__ import annotations`
  and the standard imports + `dispatch` shape used by sibling
  modules (`xops/makefile/version.py` is a clean reference).
- Prefer `_common.run()` / `_common.compose_run()` over raw
  `subprocess.run`.
- Use `_common.info() / ok() / warn() / err() / step()` for
  console output — they normalize the emoji prefix.
