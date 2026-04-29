# `xops/mcp/` — Model Context Protocol wrappers

> Status: **Phase A scaffolding** — see
> [`docs/coding/ai/automation.md`](../../docs/coding/ai/automation.md) §5.

This folder hosts the project's MCP (Model Context Protocol) server
wrappers. Each wrapper exposes a **narrow, audited** set of repo
capabilities to Copilot (and any other MCP-aware client) over
stdio JSON-RPC.

## Why MCP?

VS Code Copilot's `chat.tools.terminal.autoApprove` (configured in
[`.vscode/settings.json`](../../.vscode/settings.json)) handles the
**read-only** safe Make targets just fine. MCP wrappers exist for
the cases where we want:

- Structured input/output (JSON, not parsed terminal text).
- Per-call audit trails (every invocation logged to
  `xops/mcp/.trace/<YYYY-MM-DD>.jsonl`).
- A typed allow-list that survives users editing their VS Code
  settings.

## Current servers

| File | Status | Purpose |
|---|---|---|
| `make_allowlist.py` | **stub** | Read-only Make targets (`track.list`, `track.show`, `version.show`, `lint`, `mock.verify`, `help`, `status`, `health`, `hosts.preview`, `mock.sources`). |

## Implementation notes

The current `make_allowlist.py` is a scaffolding stub. A full
stdio MCP server requires either the official
[`mcp` Python SDK](https://pypi.org/project/mcp/) (added as an
xops-only dependency, not vendored into `ai/requirements.txt`) or
a hand-rolled JSON-RPC loop using stdlib only.

Per [`AGENTS.md`](../../AGENTS.md) §5, the scaffolding follows the
**dispatcher pattern** used by the rest of `xops/`:

```python
from xops.makefile._common import dispatch

def cmd_serve(argv): ...
def cmd_list_tools(argv): ...

COMMANDS = {"serve": cmd_serve, "list-tools": cmd_list_tools}

if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:], COMMANDS, script_name=__file__))
```

The server is registered (currently disabled with a leading `_`) in
[`.vscode/mcp.json`](../../.vscode/mcp.json). Removing the
underscore activates it.

## Hard rules

- MCP tools never call **any** mutating Make target. The allow-list
  matches the read-only set in
  [`.vscode/settings.json`](../../.vscode/settings.json).
- MCP tools never invoke `git` (`AGENTS.md` Rule 9).
- Every invocation is logged to `.trace/` (gitignored).
- New tools require a doctrine update in
  [`docs/coding/ai/automation.md`](../../docs/coding/ai/automation.md) §5.
