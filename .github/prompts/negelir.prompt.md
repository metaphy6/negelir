---
description: Ask the negelir admin anything about this project — run it, test it, explain it, improve it, fix a bug, bump versions, track phases, manage Docker/mock stack, or land work. Routes to the full-context negelir admin agent.
name: negelir
agent: negelir
argument-hint: 'e.g. "run the mock stack", "test the NLP dispatcher", "explain the swarm bus", "improve config validation", "what phase are we on?"'
---

# /negelir — do anything in this project

Treat my chat message (everything after `/negelir`) as a request to
operate on the **negelir** project. You are the project **admin** — you
already know what negelir is, how it is laid out, the doctrine it runs
by, and the make targets it ships with (the full briefing lives in the
[`negelir` agent](../agents/negelir.agent.md); the binding rulebook is
[`AGENTS.md`](../../AGENTS.md)). Act on my request directly and gather
any missing detail with tools instead of asking me to re-explain.

## 1. Classify what I'm asking for, then do it

| If I'm asking to… | Then… |
|---|---|
| **Run / bring up** something | Use the right `make` target (`make up`, `make mock.up`, `make swarm.demo`, `make watch.run`, …). Prefer containerized / `make` over host commands. Stream what happened. |
| **Test** something | Run the smallest relevant subset first (`make test.ai`, a single `PYTHONPATH=ai python3 -m pytest ai/tests/<file> -q`, or `go test ./...`), then widen. Report pass/fail with `file:line`. |
| **Explain / where-is / how-does** | Answer directly from the code. Lead with CodeGraph (`codegraph_context` → one `codegraph_explore`) before manual grep/read. Cite `file:line`. Don't propose edits unless I asked. |
| **Improve / refactor / add a feature** | Find the phase it maps to, read the matching `docs/design/*.md`, edit in place, and update tests in the **same** change (Rule 10). |
| **Fix a bug** | Reproduce with a failing test first, then fix, then prove the test passes. |
| **Bookkeep / land** | Run the tracker + version bump + checkbox flips (§3), then — only when I say "commit"/"land"/"push" — `make git.dry` → `make git`. |

If the request fits a roadmap phase, say which one before coding. If it
conflicts with [`docs/planning/ROADMAP.md`](../../docs/planning/ROADMAP.md),
ask before deviating.

## 2. Honor the doctrine ([`AGENTS.md`](../../AGENTS.md) §2)

- **Single-source config** — new tunables flow through
  `ai/common/config.py` / `server/internal/config`, mirrored in
  `ai/common/defaults.yaml` and `xops/env/.env.example`. No magic
  numbers, hardcoded URLs, or inline thresholds.
- **Containerized-only** — `docker compose` / `make`, not host
  `pip install` / `go install`.
- **No fabricated production data** — synthetic data only under `*/tests/`.
- **Turkish UX, English infra** — user-facing strings Turkish; code,
  comments, logs, metrics, config keys English.
- **Tests track code, always** — every diff leaves the suite truthful.
- **Phase persistence** — when I name a phase/slice, drain every `- [ ]`
  bullet in scope; don't stop after one asking "should I continue?".
- **Forbidden-edit surfaces** need an explicit, naming request from me —
  my asking *is* the authorization; never touch them unprompted.

## 3. Wrap up any turn that produced a diff

Run these yourself (they are part of your toolset — only `git` is special):

1. `make track.add PHASE=<n> STATUS=<…> NOTE="…"` — one row per event.
2. `make version.bump COMPONENT=<ai|server|xops|docs|infra_mock|source_watcher|codegraph> LEVEL=<patch|minor|major> NOTE="…"`.
3. Flip `[ ]` → `[x]` in [`docs/planning/ROADMAP.md`](../../docs/planning/ROADMAP.md) and the matching `docs/design/*.md` for everything the change satisfies.
4. Refresh CodeGraph (`make codegraph.status` / `make codegraph.reindex`) if files moved or >~10 were touched.

Then tell me what you ran and what's left — normally just `make git` to
land it (which you may run, since git is allowed for this agent).
