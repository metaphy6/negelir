# GitHub Copilot — Repo Operating Layer

> This is the **operating layer** for Copilot inside VS Code. It is
> intentionally short. Doctrine and workflow live elsewhere — read
> them by reference, do not restate them here.

## 1. Read these first, in order, every session

1. [`AGENTS.md`](../AGENTS.md) — the rulebook (doctrine §2,
   phase-tracking §3, workflow §4, file etiquette §5, versioning
   §6.1). **Binding.**
2. [`CLAUDE.md`](../CLAUDE.md) — only if your turn touches the
   scraper-patcher harness, its scope contracts, or the gates that
   enforce them. Otherwise informational.
3. The matching `docs/design/*.md` for the area you are about to
   edit (see `AGENTS.md` §1.7 for anchors).
4. [`docs/coding/ai/automation.md`](../docs/coding/ai/automation.md)
   — the Copilot roadmap (this surface). Refer to it when a new
   prompt / mode / MCP wrapper is being added.

If the user request conflicts with `docs/planning/ROADMAP.md`,
**ask before deviating** (`AGENTS.md` §1).

## 2. Hard rules that bind every chat mode

- **Never run `git`** — `AGENTS.md` Rule 9. No `commit`, `push`,
  `pull`, `reset`, `rebase`, `tag`, `branch`, etc. The only entry
  point is `make git`, which is human-only.
- **Single-source config** — new tunables go through
  `ai/common/config.py` or `server/internal/config` and are
  documented in `xops/env/.env.example` (`AGENTS.md` Rule 1).
- **No fabricated production data** — synthetic data is allowed
  only inside `*/tests/` (`AGENTS.md` Rule 3).
- **Turkish UX, English infra** — code, comments, log messages,
  metric names, config keys are English; user-facing strings stay
  Turkish (`AGENTS.md` Rule 6).
- **Tracker + version bump in the same commit as code** —
  `AGENTS.md` §3 and §6.1. Run `make track.add` and
  `make version.bump` yourself at the end of every turn that
  produced a diff (Rule 9 — they are part of the agent's normal
  toolset). Tell the human what you ran.
- **Tests track code, always (`AGENTS.md` Rule 10).** New feature
  → new tests (happy + adversarial). Bug fix → regression test
  that fails before the fix. Refactor / rename / behaviour change
  → revise every existing test that touches the moved or changed
  surface in the **same diff**. Never weaken, skip, or delete a
  test to make the build green; a passing build with no test for
  new behaviour is a false positive.
- **Forbidden edits without explicit human request that names the
  file**:
  - `AGENTS.md`, `CLAUDE.md`, `docs/planning/ROADMAP.md`
  - `xops/versioning/**`, `docs/tracking/phases.csv` (use the CLI)
  - `.github/copilot-instructions.md`, `.github/instructions/**`,
    `.github/prompts/**`, `.github/chatmodes/**`, `.vscode/mcp.json`
  - Anything under `server/internal/auth/`,
    `server/internal/payment/`, or `*/crypto/`
  - The patcher's scope-restricted paths (see `CLAUDE.md`)

## 3. Default model selection

- **Default to Claude Sonnet 4.5** for read-only audits, test
  authoring, doc work, and onboarding tours.
- **Use Claude Opus 4.7** only for the three reasoning-heavy
  modes: Debugger, Hardener, Feature Builder.
- Each chat mode pins its default in frontmatter; do not override
  unless the task clearly demands deeper reasoning.

## 4. Working discipline

- **Read before editing.** Use file-reading tools, not `cat` over
  large terminal output (`AGENTS.md` §5).
- **Edit in place.** Do not create "v2" files when modifying
  existing ones.
- **Cite file:line.** Every claim about the codebase must reference
  a path and a line range. Refuse "vibe analysis."
- **No blanket `try/except` that returns `None` or a default.** If
  a parser branch genuinely needs a fallback, name it and add a
  test (`CLAUDE.md` forbidden patterns).
- **No hardcoded URLs, secrets, magic numbers.** Use config
  (`AGENTS.md` Rule 1).
- **No `*-latest` model IDs in code.** Always pin a specific
  version (`CLAUDE.md`).
- **Containerized only.** Tell the human to use `docker compose` /
  `make` targets, not `pip install` / `go install` on the host
  (`AGENTS.md` Rule 2).

## 5. Wrap-up checklist for any turn that produced a diff

End the turn by **running** these yourself (per `AGENTS.md` Rule 9
they are part of the agent toolset — `git` is the only restricted
surface), in order:

1. The relevant `make track.add PHASE=… STATUS=… NOTE="…"` line.
2. The relevant `make version.bump COMPONENT=… LEVEL=… NOTE="…"`
   line.
3. Any `[ ]` → `[x]` checkbox flips in `docs/planning/ROADMAP.md`
   or the touched `docs/design/*.md` (`AGENTS.md` §3.4).

Then briefly tell the human what you ran and what they still need
to do (which is normally just `make git` to land the commit).
