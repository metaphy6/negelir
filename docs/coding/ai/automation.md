# 🤖 AI Automation Roadmap — VS Code Copilot Companion

> **Audience:** the human owner + future contributors configuring
> Copilot in this repo.
> **Scope:** **net-new automation surfaces** for VS Code + Copilot
> (Opus 4.7 heavy / Sonnet 4.5 daily) that aren't already governed
> by [`AGENTS.md`](../../../AGENTS.md) or [`CLAUDE.md`](../../../CLAUDE.md).
> **Out of scope** (already covered, do not duplicate here):
> - Doctrine, phase tracking, version bumps, file-touch etiquette,
>   xops/Make conventions, mock-data discipline → `AGENTS.md`.
> - Scraper-patcher harness, scope allow-lists, gauntlet rules,
>   forbidden patterns, security-critical paths → `CLAUDE.md` +
>   [`SCRAPER_PATCHER.md`](../../design/SCRAPER_PATCHER.md).
> - The Anthropic Agent SDK loop in any form.

This doc only adds **what the existing rulebooks don't yet cover**:
the Copilot configuration surface and the new categories of
development work it should automate.

---

## 0. The thesis

You already have rules for what AI may and may not do (`AGENTS.md`,
`CLAUDE.md`). You don't yet have a checked-in **operating layer**
for Copilot inside VS Code, and you don't yet have prompts /
modes for the **non-patcher** development work — test gaps,
performance hunts, dependency hygiene, refactoring radar, doc
freshness, release prep, contributor onboarding, observability
triage, RFC drafting.

This roadmap fills only those two gaps.

---

## 1. The Copilot configuration surface (mechanism, not policy)

Six file types in two folders. Policy lives in `AGENTS.md` /
`CLAUDE.md`; these files just *expose* that policy to Copilot.

| Surface | Path | Purpose |
|---|---|---|
| Repo system prompt | `.github/copilot-instructions.md` | One file that points Copilot at `AGENTS.md` and `CLAUDE.md` and tells it to obey them. **Don't restate doctrine — link to it.** |
| Path-scoped instructions | `.github/instructions/*.instructions.md` | Per-stack hints (`applyTo: "ai/**/*.py"`, `applyTo: "server/**/*.go"`, `applyTo: "Makefile,xops/makefile/**"`) — only the bits the doctrine doesn't already specify. |
| Slash-prompts | `.github/prompts/*.prompt.md` | Reusable verbs invoked as `/<name>`. The catalog in §3 below. |
| Chat modes | `.github/chatmodes/*.chatmode.md` | Personas (model + tool allow-list + system frame) for the new automation tasks in §3. |
| MCP servers | `.vscode/mcp.json` | Wrap existing repo tools (`make`, tracker CLI, version CLI, mock-stack helpers, `pytest`, `go test`, `docker compose logs`) so Copilot can act through reviewed entry points instead of raw shell. |
| Workspace settings | `.vscode/settings.json` | Enable prompt files, point at instruction folders, set terminal auto-approve list, pin commit-message generation rules. |

**Doctrine compatibility note.** The system prompt and every chat
mode must inherit `AGENTS.md` Rule 9 (no `git`) and the CLAUDE.md
forbidden-edit list. Copy the *links*, not the *contents*.

---

## 2. The five outcome categories this roadmap targets

These are the buckets into which every new prompt / mode below
maps. If a proposed automation doesn't move one of these, drop it.

| Category | What "good" looks like a year from now |
|---|---|
| **Quality drift** | Test coverage, doc accuracy, lint debt, dead code, and dependency staleness all trend *downward* week-over-week without scheduled human cleanups. |
| **Operability** | A nightly red CI, a slow endpoint, a noisy log line, or a flaky test arrives in chat with a triage already drafted. |
| **Velocity** | RFC → draft slice in one afternoon; release notes + ADRs + design-doc updates ship as side effects of merging code. |
| **Onboarding** | A new contributor opens the repo and a Copilot tour walks them through the doctrine, the Make surface, and the current phase in < 15 minutes. |
| **Innovation surface** | Standing prompts for "spot a refactor opportunity," "propose a new market type," "scan for cross-component duplication" run on demand and produce concrete, citation-backed proposals — not vibes. |

---

## 3. Net-new automation tasks (the catalog)

Everything in this section is **work the existing rulebooks do not
yet describe a workflow for.** Patcher-style scraper fixes are
explicitly excluded — `CLAUDE.md` already owns them.

Each row lists the slash-prompt name, the chat mode it expects, the
trigger, the model tier, and the deliverable. Implement in priority
order top-to-bottom; later rows depend on earlier infrastructure
(MCP servers, chat modes).

### 3.1 Quality-drift slash-prompts

| Prompt | Mode | Trigger | Model | Deliverable |
|---|---|---|---|---|
| `/test.gap <module>` | Test Author | on demand | Sonnet | Ranked list of public functions with no test, plus first valuable test draft. |
| `/test.regression <bug>` | Test Author | after a bug report | Sonnet | A failing test capturing the bug; stops before fix. |
| `/test.flake <test-id>` | Debugger | repeated CI flakes | Opus | Reproduction strategy (seed, ordering, time/locale dependency); proposes deterministic guard. |
| `/lint.debt <area>` | Doctrine Reader | weekly | Sonnet | Inventory of `# noqa`, `// nolint`, `type: ignore`, magic numbers; ordered by blast radius. |
| `/dead.symbols <area>` | Doctrine Reader | monthly | Sonnet | Symbols exported but never imported; never references-in-tests filter applied. |
| `/dup.scan <area>` | Doctrine Reader | quarterly | Opus | Cross-module duplication candidates with extraction sketch. |
| `/deps.stale` | Doctrine Reader | weekly cron | Sonnet | Diff of `requirements.txt` / `go.mod` against latest stable; flags CVEs first. |
| `/deps.cve` | Doctrine Reader | on GHSA notice | Opus | Per-dependency exposure map: which modules import the affected symbols. |
| `/i18n.audit` | Doctrine Reader | weekly | Sonnet | TR strings missing from `ai/common/locale_tr.yaml`; EN strings leaking into user-facing surfaces (Rule 6 enforcement). |

### 3.2 Operability slash-prompts

| Prompt | Mode | Trigger | Model | Deliverable |
|---|---|---|---|---|
| `/triage.ci` | Debugger | failed CI run | Opus | Reads MCP-fetched test output, classifies (flake / regression / env / fixture), drafts smallest fix. |
| `/triage.logs <service> <window>` | Debugger | log spike | Opus | Pulls logs via MCP `docker compose logs`, clusters errors, names the top 3 with file:line. |
| `/triage.slow <endpoint>` | Hardener | latency alert | Opus | Reads endpoint code + recent traces, lists the suspects (DB call, JSON marshal, lock contention) with citations. |
| `/triage.alert <prom-alert>` | Debugger | Prometheus webhook | Opus | Fetches the alert query + last 24h series via MCP, proposes a runbook step. |
| `/fixture.refresh <source>` | Doc Steward | manifest drift | Sonnet | Drives `make mock.capture` for one source, diffs the new bytes, writes a tracker note. |
| `/migration.preview <NNN>` | Doctrine Reader | before applying | Opus | Reads the SQL, lists every existing query that would change semantics, flags any reversible-vs-irreversible step. |

### 3.3 Velocity slash-prompts

| Prompt | Mode | Trigger | Model | Deliverable |
|---|---|---|---|---|
| `/rfc.draft <title>` | Feature Builder | new idea | Opus | Fills `.github/ISSUE_TEMPLATE/feature.md` with problem / non-goals / open questions; **no code**. |
| `/feature.plan` | Feature Builder | after `/rfc.draft` approved | Opus | 30-line implementation plan referencing affected files; stops for `/approve`. |
| `/feature.implement` | Feature Builder | after `/approve` | Opus | Writes code + tests + design-doc patch; stops before tracker / version bump (humans/AGENTS Rule). |
| `/adr.draft <decision>` | Doc Steward | architectural choice | Sonnet | New file under `docs/design/adr/NNNN-<slug>.md` using a fixed ADR template; cites the alternatives considered. |
| `/release.notes <range>` | Doc Steward | pre-release | Sonnet | Reads commit range + `phases.csv` + version chart; produces user-facing notes in TR + infra notes in EN (Rule 6). |
| `/changelog.fragment` | Doc Steward | post-merge | Sonnet | Drops a fragment under `docs/reports/changelog.d/` for the next release. |

### 3.4 Onboarding slash-prompts

| Prompt | Mode | Trigger | Model | Deliverable |
|---|---|---|---|---|
| `/tour.repo` | Doctrine Reader | new contributor | Sonnet | Walks `AGENTS.md` §1 reading order, shows where to find `make help`, lists the current phase from `phases.csv`. |
| `/tour.area <area>` | Doctrine Reader | first edit in area | Sonnet | Surfaces the matching `docs/design/*.md`, flags the open checkboxes in that area, shows last 5 commits touching the area. |
| `/tour.make` | Doctrine Reader | unfamiliar Make target | Sonnet | Resolves the target through `xops/makefile/*.py` and explains it without running anything. |

### 3.5 Innovation-surface slash-prompts

| Prompt | Mode | Trigger | Model | Deliverable |
|---|---|---|---|---|
| `/refactor.spot <area>` | Hardener | quarterly | Opus | One concrete refactor proposal with before/after sketch and a test plan; only one. |
| `/contract.diff <area>` | Doctrine Reader | before bumping a `minor` | Opus | Diffs the public surface against the previous tag; flags any silent breaking change that should be `major`. |
| `/research.market <name>` | Doctrine Reader | new market idea | Opus | Reads `ai/common/betting_markets.json` + competitor list; sketches the data + UX changes needed. |
| `/research.league <name>` | Doctrine Reader | new league request | Opus | Cross-checks `LEAGUE_CATALOG.md` readiness gates; outputs a "what's missing" list. |

---

## 4. Chat modes specific to the new tasks

Modes already implied by §3. Each is a `*.chatmode.md` file; only
the **net-new** ones are listed here. Modes the patcher already
implies (e.g. a "Patcher Mirror") are intentionally omitted —
`CLAUDE.md` is the source of truth for that role.

| Mode | Default model | Allowed tools | Used by |
|---|---|---|---|
| **Doctrine Reader** | Sonnet 4.5 | read-only file ops, no terminal | All §3.1, §3.2 (preview only), §3.4, §3.5 audits |
| **Test Author** | Sonnet 4.5 | edit + `runTests` (pytest, `go test`) | §3.1 test prompts |
| **Debugger** | **Opus 4.7** | edit + MCP (`make test.fast`, logs, traces) | §3.2 triage prompts, `/test.flake` |
| **Hardener** | **Opus 4.7** | edit + read-only terminal | `/triage.slow`, `/refactor.spot` |
| **Feature Builder** | **Opus 4.7** | edit + MCP (`runTests`, lint) | §3.3 plan/implement |
| **Doc Steward** | Sonnet 4.5 | edit limited to `docs/**` + MCP for `mock.capture` | §3.3 ADR/notes, §3.2 fixture refresh, post-merge sweeps |

Each mode's frontmatter must declare `model:` and the tool
allow-list. Inheritance: every mode loads
`.github/copilot-instructions.md`, which loads `AGENTS.md` and
(for the Debugger / Hardener / Patcher Mirror) `CLAUDE.md` by
reference. **No mode duplicates doctrine inline.**

---

## 5. MCP wrappers required (in priority order)

Only the wrappers needed by the §3 catalog. Skip anything the
existing patcher harness already needs — that's `CLAUDE.md`'s
problem.

1. **`make-allowlist`** — the read-only safe targets:
   `track.list`, `track.show`, `version.show`, `mock.verify`,
   `lint`, `test.fast`. Used by Doctrine Reader and Test Author.
2. **`make-edit`** — the edit-capable targets used by debugger /
   feature work: `test`, `test.ai`, `mock.capture`, `track.add`,
   `version.bump`. Behind a per-call confirmation in Debugger /
   Feature Builder modes.
3. **`logs`** — wraps `docker compose logs --since=<window>
   <service>` with output truncation and structured framing. Used
   by `/triage.logs`.
4. **`prom-query`** — read-only PromQL over the local stack
   (Phase 4 observability). Used by `/triage.alert`,
   `/triage.slow`. Skip if Phase 4 isn't live yet.
5. **`deps`** — wraps `pip-audit` + `go list -m -u all`. Used by
   `/deps.stale`, `/deps.cve`.

Each wrapper is a small Python script under `xops/mcp/<name>.py`
following the `xops/makefile/*` conventions
(`_common.dispatch()`-style). Log every invocation to a local
JSONL trace under `xops/mcp/.trace/` for after-the-fact review.

---

## 6. Phased delivery

Two short phases plus a maintenance phase. **Implementation order
matters** — later prompts assume earlier MCP wrappers.

### Phase A — Foundation (one focused afternoon)

1. `.github/copilot-instructions.md` that **only** says: read
   `AGENTS.md`, read `CLAUDE.md` if touching the patcher, prefer
   Sonnet 4.5 unless the active mode says Opus.
2. The three path-scoped instruction files (Python / Go / xops),
   each ≤ 30 lines. Stack-specific tips only — no doctrine.
3. `.vscode/settings.json` enabling prompt files + instruction
   folders + a deny list for `git`, `rm -rf`, ad-hoc `sudo`.
4. The `make-allowlist` MCP wrapper (§5.1) and the **Doctrine
   Reader** chat mode. This pair unlocks every read-only prompt
   in §3.1, §3.4, §3.5.

### Phase B — Working surface (over the next two weeks)

Land the prompts in this order; each "tier" is one sitting:

- **Tier 1** (operability + tests): Test Author + Debugger modes,
  `make-edit` MCP, then `/test.gap`, `/test.regression`,
  `/triage.ci`. This is the highest-ROI block — pays for itself on
  the first red-CI session.
- **Tier 2** (velocity): Feature Builder + Doc Steward modes, then
  `/rfc.draft`, `/feature.plan`, `/feature.implement`,
  `/adr.draft`, `/release.notes`.
- **Tier 3** (operability deep): `logs` + `prom-query` MCP wrappers
  (depend on Phase 4 stack), then `/triage.logs`, `/triage.alert`,
  `/triage.slow`.
- **Tier 4** (innovation): `/refactor.spot`, `/contract.diff`,
  `/research.market`, `/research.league`. Cheapest to add but only
  valuable once tiers 1–3 prove the surface works.

### Phase C — Maintenance (ongoing, monthly cadence)

Add to your monthly review:

- Sweep `xops/mcp/.trace/*.jsonl` and the chat history for prompts
  unused for ≥ 60 days. Retire or rewrite them.
- Run `/contract.diff` for the prior month's bumps; reconcile any
  silent breaking changes against the version chart.
- Refresh chat-mode `model:` frontmatter if Anthropic ships new
  tiers or pricing shifts the Sonnet-vs-Opus boundary.

No new ongoing-cron Copilot work. Anything that needs to *run on a
schedule without a human in the loop* belongs to the patcher
harness or a separate non-Copilot system, not this roadmap.

---

## 7. Boundaries — what this roadmap deliberately does **not** do

These are *not* gaps in the roadmap; they are intentional refusals.

- **Doctrine restatement.** `AGENTS.md` §2 and `CLAUDE.md` are the
  source. The Copilot system prompt must link, not copy.
- **Tracker / version-bump prose.** `AGENTS.md` §3 and §6.1 already
  mandate them. Don't paste the rules into prompts; let Copilot
  read `AGENTS.md`.
- **Forbidden-edit list.** `CLAUDE.md` enumerates the patcher's
  forbidden paths and the security-critical surfaces. Re-cite by
  link from `copilot-instructions.md`; don't fork the list.
- **Patcher work.** The scraper auto-patch loop, its scopes, its
  gauntlet, its escalation chain → `SCRAPER_PATCHER.md` +
  `CLAUDE.md`. The "Patcher Mirror" idea from earlier drafts is
  dropped — previewing the patcher's behavior is `CLAUDE.md`'s
  domain, not Copilot's.
- **Unattended automation.** Copilot is in-editor, human-driven.
  Anything described as "runs hourly" or "monitors continuously"
  belongs in the SDK harness or a separate service.
- **Auto-merge / auto-push / `git` of any kind.** Banned by
  `AGENTS.md` Rule 9.

---

## 8. Success metrics (measurable in 90 days)

Distinct from any metric `AGENTS.md` already enforces. Track in
your monthly review.

| Metric | Target |
|---|---|
| Slash-prompts in `.github/prompts/` invoked at least once / month | ≥ 70 % |
| Chat sessions defaulting to Opus when Sonnet would have sufficed | < 20 % |
| `/triage.ci` sessions producing a green diff first try | ≥ 50 % |
| `/test.gap` proposals merged within a week of generation | ≥ 30 % |
| ADRs landed via `/adr.draft` per quarter | ≥ 1 |
| New contributor → first merged PR (using `/tour.*`) | < 5 days |
| MCP wrappers with at least one trace per week | 100 % (else retire) |

---

## 9. Risk additions (only ones not already in `AGENTS.md`)

| Risk | Mitigation |
|---|---|
| **Prompt sprawl** | §6 Phase C monthly sweep + retire-or-rewrite. |
| **Chat-mode bit-rot when models version up** | `model:` frontmatter is the single point of update; CI lint that fails if a mode references a deprecated model name. |
| **MCP wrapper becoming a shadow Make** | Wrappers may only call existing `make` targets or stdlib code; reject any wrapper that re-implements logic. Reviewed in Phase C sweep. |
| **Copilot drifting to fabricate `git` commands despite Rule 9** | Workspace settings deny list explicitly lists `git`; chat-mode allow-lists never include it; `/wrap.up` style prompts always end with "you run the tracker + bump." |
| **Cost runaway from Opus modes** | Default tier in `copilot-instructions.md` is Sonnet; Opus is opt-in per-mode; per-month review of Opus session count. |

---

## 10. Where this fits

- **Below `AGENTS.md` and `CLAUDE.md` in priority.** This doc is
  the *Copilot operating layer*, not doctrine.
- **Implementation = a new ROADMAP phase.** Propose it as
  **Phase 22 — Copilot Companion** (per `AGENTS.md` §1, ask before
  adding). Until then, this is a proposal.
- **Versioning.** While `.github/prompts/` and `.github/chatmodes/`
  are small, they live under the `docs` component. When the
  catalog stabilizes, propose a `copilot_config` component in
  `xops/versioning/chart.json` so prompt regressions are
  bisectable per `AGENTS.md` §6.1.
- **Cross-link.** Once Phase A ships, add this doc under
  `AGENTS.md` §1.7 ("Domain anchor docs"). The patcher remains a
  separate, complementary system.

---

## 11. TL;DR

Things `AGENTS.md` and `CLAUDE.md` already cover are **not** in
this roadmap. What is:

1. The **Copilot configuration surface** (`.github/`, `.vscode/`)
   as plumbing.
2. **~25 new slash-prompts** spanning quality drift, operability
   triage, velocity (RFC → ADR → release notes), onboarding
   tours, and innovation scans.
3. **~6 chat modes** that pick the right model and tool allow-list
   per task.
4. **~5 MCP wrappers** that expose the existing `make` / log /
   metrics surface to Copilot through reviewed entry points.

Build them in the order in §6. Default to Sonnet. Use Opus only
where deep reasoning earns its cost. Inherit doctrine by link, not
by copy. Review monthly; retire what nobody used.
