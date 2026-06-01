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
   edit (see `AGENTS.md` §1.7 for anchors). Long phases have been
   modularised — start at their per-phase folder when relevant:
   [`docs/design/phase8/README.md`](../docs/design/phase8/README.md)
   (ops console & maint agents),
   [`docs/design/phase9/README.md`](../docs/design/phase9/README.md)
   (Go REST API & identity),
   [`docs/design/phase10/sections/`](../docs/design/phase10/sections/)
   (NLP — uses `docs/design/phase10/sections/`),
   [`docs/design/phase16/README.md`](../docs/design/phase16/README.md)
   (emitter & feed contract, Pivot v3).
4. [`docs/coding/ai/automation.md`](../docs/coding/ai/automation.md)
   — the Copilot roadmap (this surface). Refer to it when a new
   prompt / mode / MCP wrapper is being added.
5. [`xops/orchestrator/README.md`](../xops/orchestrator/README.md)
   — only when delegating ROADMAP phases through the parallel
   loop (`/orchestrate.roadmap` prompt + `phase-implementer`
   / `phase-reviewer` / `phase-verifier` chatmodes). Otherwise
   informational.

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
4. **CodeGraph refresh** (per `AGENTS.md` §4 step 9 and
   `docs/guides/CODEGRAPH.md`):
   - Touched > ~10 files / added new public surface → `make codegraph.status`.
   - Big refactor / mass rename / files moved → `make codegraph.reindex`.
   - Periodically (cheap) → `make codegraph.check` and surface the
     output. `codegraph.upgrade` is **human-driven** — never run it
     yourself, just flag when an upgrade is available.

Then briefly tell the human what you ran and what they still need
to do (which is normally just `make git` to land the commit).

## 6. Phase persistence — do not stop mid-phase

When the human asks you to "implement Phase X", "finish §Y", "do
this sub-phase", "complete this slice" — or anything equivalent —
the work is **the entire named scope**, not the first bullet you
touched. This is `AGENTS.md` Rule 11 (Phase Persistence). It binds
every chat mode unless the user explicitly asks for partial work
("just bullet 3", "only the test for X", "stop after the schema").

**This rule applies equally to every backend model — Claude
Sonnet/Opus, GPT-5 / 5-Codex, Gemini, and any future addition.**
Empirically, GPT and Gemini sessions return partial work and ask
"should I continue?" far more often than Claude ones do. That is
a doctrine violation, not polite engineering. Treat the human's
phase request as a single, indivisible task — the human granted
permission once, by dispatching the work, and is not going to
re-grant it bullet-by-bullet.

Default-on behaviour:

- **Treat the named phase / sub-phase / slice as one task.** Loop
  internally over its `- [ ]` bullets in `docs/planning/ROADMAP.md`
  (and the matching `docs/design/*.md` checklist) until every
  bullet covered by the request is ticked **or** a real blocker is
  hit. Do not return control after the first satisfied bullet.
- **A "real blocker" is narrow.** Only these justify stopping:
  - Cross-phase need that would violate the forbidden-edits list
    (§2) — record `make track.add … STATUS=blocked NOTE="needs
    <other phase>"` and explain.
  - A failing test you cannot diagnose after a genuine attempt
    (not "this might take a while" — actual stuck).
  - Doctrine conflict with `AGENTS.md` §2 or `CLAUDE.md`.
  - The phase's DoD in `ROADMAP.md` Appendix B requires a human
    decision (e.g. operator key bootstrap, prod credential).
  - The human explicitly capped scope in the request.
- **None of these are blockers:** "the phase is large", "this will
  take many edits", "shall I continue?", "let me know if you want
  me to proceed", "I have completed part X — should I continue
  with Y?", "I'll pause here for review", "returning control to
  confirm direction", "the remaining bullets are similar; I can
  do them next turn". If you catch yourself writing any of those
  phrases — or any sentence that asks permission to continue work
  the user already requested — delete it and keep working.
- **Per-bullet bookkeeping still applies.** Every bullet you close
  still gets its own tracker row + version bump + checkbox flip
  (§5). You batch the *work*, not the bookkeeping.
- **Run the full relevant test subset between bullets**, not just
  at the end. A regression caught at bullet 4 must be fixed at
  bullet 4, before moving on.
- **Final summary, once the phase is genuinely drained:** report
  every bullet closed, the tracker rows + version bumps you ran,
  and which (if any) bullets are still `[ ]` with the explicit
  doctrine reason. Then — and only then — hand back to the human
  for `make git`.

If you are unsure whether a bullet is in scope, prefer to ship it
and tick it. Over-delivery inside the named phase is fine;
under-delivery and asking "should I continue?" is the failure mode
this rule exists to kill.
