# CodeGraph — Local Semantic Code Intelligence

> **Status:** dev tooling, optional but installed across all four AI agent
> surfaces (VS Code Copilot, Claude Code, Cursor, Codex CLI). Tracked as
> a versioned component in `xops/versioning/chart.json` (`codegraph`).
> **Anchor:** `.codegraph/` (machine-local SQLite knowledge graph).

---

## What it is

[CodeGraph](https://www.npmjs.com/package/@colbymchenry/codegraph) is a
local MCP server that builds a tree-sitter knowledge graph of every
symbol in the repo and exposes it to AI agents through `codegraph_*`
tools (`search`, `callers`, `callees`, `impact`, `node`, `context`,
`explore`, `files`, `status`). It runs 100% locally — no external
services, no API keys, no telemetry.

**Why it's here:** negelir is large (Python `ai/`, Go `server/`, Make /
Python `xops/`, ~50 design docs, 17+ phases). Without an index, every
"how does X work" / "what would break" question costs the agent a
grep-fan-out. CodeGraph cuts those calls by ~70% on similar-sized
codebases (see codegraph's README benchmarks).

---

## Doctrine fit

This tool is a documented **exception** to AGENTS.md Rule 2
(containerized-only) on the same footing as VS Code itself or `git`:
it is a **dev-time host process**, not a runtime dependency. It does
not ship with the project, does not run in CI, does not affect any
container, and produces no artifact that ends up in `data/` or
`server/`. The repo's runtime stack is unchanged.

- Host requirement: Node.js 20–24 (codegraph blocks Node 25+).
- Index location: `.codegraph/codegraph.db` (machine-local, gitignored).
- Tracked config: `.codegraph/config.json` (committed; defines what to
  index).
- Versioned in `xops/versioning/chart.json` as the `codegraph`
  component so dependency bumps land through the standard
  `make version.bump` flow.

---

## Install / refresh

CodeGraph is invoked via `npx` — no global install, no `npm install -g`.
The MCP entries in this repo (see below) all spawn:

```bash
npx -y @colbymchenry/codegraph@0.8.0 serve --mcp [--path <workspace>]
```

Day-to-day, **drive everything through Make**. The dispatcher lives at
[`xops/makefile/codegraph.py`](../../xops/makefile/codegraph.py) and is
the single source of truth for the pinned version + wiring layout.

| Target | What it does | Who runs it |
|---|---|---|
| `make codegraph.status` | Cheap health check (`status` over the index). | Agents, after large diffs. |
| `make codegraph.reindex` | Full rebuild from scratch (`init -i` + `status`). | Agents, after big refactors / mass renames / file moves. |
| `make codegraph.check` | Print pinned vs latest on npm + audit all 4 wirings for drift. | Agents, periodically (cheap, network call only). |
| `make codegraph.upgrade [VERSION=x.y.z]` | Bump the pin across all 4 wiring files in lockstep, reindex, then prompt for the chart-version bump. | **Humans only** — it mutates committed files; agent must surface `check` output and let the human decide. |

---

## Keeping the pin up-to-date

The pinned version (`@0.8.0` today) is **deliberately explicit** in
every MCP wiring file. We **do not** use `@latest`. Reasons:

1. **Reproducibility.** Every developer + agent surface resolves to
   the same binary. `@latest` would silently drift across machines
   and across `npx` cache states.
2. **Network on every spawn.** `npx @pkg@latest` re-resolves the
   semver tag on every invocation. With four agent surfaces and
   stdio MCP processes that restart, this means an npm round-trip
   on nearly every agent session.
3. **Audit trail.** Pin bumps go through `make version.bump
   COMPONENT=codegraph` so they show up in `chart.json`'s
   changelog. `@latest` would route around this.
4. **Supply-chain hygiene.** Unpinned MCP servers are an obvious
   supply-chain vector; pinning lets us notice unexpected version
   changes (the [`codegraph.check`](#install--refresh) drift audit
   guards committed wirings).

**Instead, the upgrade flow is automated:**

```bash
# 1. See where we stand (agents may run this).
make codegraph.check
#    package:    @colbymchenry/codegraph
#    pinned:     0.8.0
#    latest:     0.9.1
#    → upgrade available (minor): 0.8.0 → 0.9.1

# 2. Human pulls the trigger.
make codegraph.upgrade
#    → patches .vscode/mcp.json, .mcp.json, .cursor/mcp.json,
#      docs/guides/CODEGRAPH.md in lockstep
#    → runs `init -i` to rebuild the index against the new binary
#    → prints the matching `make version.bump COMPONENT=codegraph …`
#      to record the change in chart.json

# 3. Record the bump (audit trail).
make version.bump COMPONENT=codegraph LEVEL=minor \
    NOTE="codegraph npm pin 0.8.0 → 0.9.1"

# 4. Land it.
make git
```

`upgrade` is **idempotent** — running it when already at latest
short-circuits with `✓ already at <pin> — nothing to do.`

**Pinning a specific version** (e.g. holding back from a bad release):

```bash
make codegraph.upgrade VERSION=0.8.7
```

**~/.codex/config.toml is user-global** — outside the repo, so the
upgrade script can only *warn* about it. When `check` / `upgrade`
detects drift there, they print the exact `sed` command to fix it.

**Optional: keep it always fresh.** Add a weekly cron / launchd /
systemd-timer entry that runs `make codegraph.check` and emails /
slacks the output. We deliberately do **not** auto-apply because
`upgrade` mutates committed config and must land through `make git`.

---

## MCP wiring

| Surface | File | Scope |
|---|---|---|
| VS Code (GitHub Copilot) | [`.vscode/mcp.json`](../../.vscode/mcp.json) | project (committed) |
| Claude Code | [`.mcp.json`](../../.mcp.json) | project (committed) |
| Cursor | [`.cursor/mcp.json`](../../.cursor/mcp.json) | project (committed) |
| Codex CLI | `~/.codex/config.toml` | user-global (not in repo) |

The first three are committed so every developer gets the same agent
behavior. Codex's TOML is global; install on a new machine with:

```bash
mkdir -p ~/.codex && cat > ~/.codex/config.toml <<'EOF'
[mcp_servers.codegraph]
command = "npx"
args = ["-y", "@colbymchenry/codegraph@0.8.0", "serve", "--mcp"]
EOF
```

---

## How agents should use it

Per the codegraph instructions template (auto-emitted into
`CLAUDE.md` when an agent runs `codegraph install` against the repo):

| Question | Tool |
|---|---|
| "Where is X defined?" / find symbol | `codegraph_search` |
| "What calls Y?" | `codegraph_callers` |
| "What does Y call?" | `codegraph_callees` |
| "What would break if I changed Z?" | `codegraph_impact` |
| Y's signature / source / docstring | `codegraph_node` |
| Focused context for a task/area | `codegraph_context` |
| Several related symbols at once | `codegraph_explore` |
| Files under a path | `codegraph_files` |
| Index health | `codegraph_status` |

**Rules of thumb:**

- Trust codegraph results — they come from a full AST parse; do not
  re-grep them.
- Don't chain `codegraph_search` + `codegraph_node` when one
  `codegraph_context` call would do.
- Index lag is ~500 ms behind writes; don't re-query immediately
  after editing in the same turn.
- Use native grep / read for **literal text** (string contents, log
  messages, comments) — codegraph is for **structural** questions.

---

## Patcher / sandbox boundary

Per the user's integration choice, codegraph **may** be exposed to the
Phase 17 scraper-patcher harness — see `CLAUDE.md` for the updated
allow-list. The patcher's hard scope, size, turn, and cost limits are
unchanged; codegraph is purely a read-only context source for the
patcher (no edits, no mutations).

---

## Maintenance

All routine maintenance goes through Make (see the
[Install / refresh](#install--refresh) table). Quick reference:

- **Reindex:** `make codegraph.reindex`
- **Status:** `make codegraph.status`
- **Check for updates:** `make codegraph.check`
- **Apply update:** `make codegraph.upgrade` (human-driven)
- **Uninstall:** delete `.codegraph/`, `.mcp.json`, `.cursor/mcp.json`,
  the `codegraph` block in `.vscode/mcp.json`, and the `codegraph`
  entry in `xops/versioning/chart.json` (then `make version.bump
  COMPONENT=docs LEVEL=patch NOTE="dropped codegraph"`).

### When agents should refresh the index

Per AGENTS.md §4 step 9, agents are expected to keep the index
honest as part of "done":

| Situation | Run |
|---|---|
| Edited a handful of files in one module | nothing — watcher debounces on save |
| Touched > ~10 files, added a new public surface, changed package layout | `make codegraph.status` |
| Big refactor / mass rename / `git rebase` that moved files | `make codegraph.reindex` |
| End of a multi-turn session, before handing back to the human | `make codegraph.status` |
| Periodically (low-priority, informational) | `make codegraph.check` |

The index lags writes by ~500 ms (watcher debounce). Don't query
immediately after editing in the same turn — the next turn will see
fresh data automatically.
