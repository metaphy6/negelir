# 🤖 AGENTS.md — Instructions for AI Coding Assistants

> **Audience:** any AI coding assistant (GitHub Copilot, Claude Code,
> Cursor, Aider, Codex, etc.) working in this repository.
> **Scope:** project conventions, workflow, doctrine, and **mandatory**
> phase-tracking discipline. This file is the rulebook — read it before
> touching anything.

---

## 1. Read this first, in order

1. `README.md` — what the project is and how to run it.
2. [`docs/README.md`](docs/README.md) — documentation index.
3. [`docs/planning/ROADMAP.md`](docs/planning/ROADMAP.md) — **the** plan.
   Single source of truth. Supersedes every other planning artifact.
4. [`docs/tracking/README.md`](docs/tracking/README.md) — tracker schema,
   state machine, CLI usage.
5. [`xops/README.md`](xops/README.md) — repo automation layout (Makefile
   dispatch scripts, CI/CD glue, deployment helpers).
6. [`xops/versioning/chart.json`](xops/versioning/chart.json) +
   [`xops/versioning/version.py`](xops/versioning/version.py) — the
   centralized SemVer chart. **Every meaningful change to a tracked
   component must include a `make version.bump` in the same commit.**
   See §6.1 below for the rule.
7. The relevant `docs/design/*.md` for the area you are touching.
   **Pivot v3 anchor docs** (binding for any cross-component change):
   [`COMPONENT_LAYOUT.md`](docs/design/COMPONENT_LAYOUT.md) (the
   four-component map), [`DATA_PIPELINE.md`](docs/design/DATA_PIPELINE.md)
   (the five-plane data scope + Record contract),
   [`DATA_SOURCE.md`](docs/design/DATA_SOURCE.md) (the six datasource
   sub-components), [`EMITTER.md`](docs/design/EMITTER.md) (the
   datasource → swarm feed contract; Phase 16),
   [`SCRAPER_PATCHER.md`](docs/design/SCRAPER_PATCHER.md) (the auto-patch
   loop; Phase 17 — binding contract for the patcher harness).
   **Domain anchor docs** (binding for league / competition / data /
   commercial work): [`ARCHITECTURE.md`](docs/design/ARCHITECTURE.md)
   (top-level system map), [`LEAGUE_CATALOG.md`](docs/design/LEAGUE_CATALOG.md)
   (which leagues we serve and the readiness gates per Phase 13/19),
   [`COMPETITIONS.md`](docs/design/COMPETITIONS.md) (non-league formats:
   knockouts, two-leg ties, group stages),
   [`ENRICHMENT_DATA.md`](docs/design/ENRICHMENT_DATA.md) (Phase 21
   enrichment overlays on the five base data planes),
   [`MONETIZATION.md`](docs/design/MONETIZATION.md) (Phase 20 tier
   model, built-but-dormant — edge-only enforcement at the Go API).
   **Go REST API anchor docs** (binding for Phase 9 surfaces):
   [`API.md`](docs/design/API.md) (binding contract for all Phase 9 routes,
   auth, rate limits, cache, and swarm shim; Phase 9 §9.13),
   [`docs/guides/api_runbook.md`](docs/guides/api_runbook.md) (operator
   surfaces: key rotation, cert renewal, token revocation).
   Other per-area docs: `SWARM.md`, `CONFIGURATION.md`,
   `MOCK_DATA_SERVER.md`, `SECURITY.md`, `COMPUTE_DEVICES.md`,
   `LANGUAGE_CHOICES.md`, `TURKISH_NLP.md`, `TESTING_STRATEGY.md`,
   `CONTENT_FRESHNESS.md`, `SWARM_NETWORK.md`.
8. [`CLAUDE.md`](CLAUDE.md) — operating brief for the
   scraper-patcher harness (cached as L1 context per
   `SCRAPER_PATCHER.md` §12.5). Required reading **only** if you are
   modifying the patcher, its scope contracts, or the gates that
   enforce them; otherwise informational.

If the user request conflicts with `ROADMAP.md`, **ask before deviating**.
Do not silently re-plan the project.

---

## 2. Non-negotiable doctrine

These come from `docs/README.md` and `ROADMAP.md` §Guiding Principles.
Every PR, every diff, every agent run must respect them:

| # | Rule | Concretely |
|---|---|---|
| 1 | **Single-source configuration** | New tunables go through `ai/common/config.py` (Python) or `server/internal/config` (Go) and are documented in `xops/env/.env.example`. No magic numbers, no hardcoded URLs, no inline thresholds. |
| 2 | **Containerized only** | All run/test instructions assume `docker compose`. Never tell the user to `pip install` or `go install` on the host. *Sanctioned dev-time host exception:* the CodeGraph MCP server (`npx -y @colbymchenry/codegraph` — node 20–24) is treated as host-installed dev tooling on the same footing as VS Code itself; it produces no runtime artifact and is wired only into agent surfaces. See [`docs/guides/CODEGRAPH.md`](docs/guides/CODEGRAPH.md). |
| 3 | **No fabricated production data** | Synthetic data is only allowed inside `*/tests/`. Production code must never silently fall back to fake data. |
| 4 | **Smallest model that works** | Prefer deterministic code → scikit-learn / XGBoost → small transformers (≤ 100 MB) → mid LLMs only with explicit justification in the agent's `README`. |
| 5 | **Scale symmetry** | Same code path runs with 1 replica or 1000. State lives in Redis / Postgres, never in process memory. |
| 6 | **Turkish UX, English infra** | User-facing text & AI input/output in Turkish. Code, comments, log messages, metric names, config keys in English. |
| 7 | **Adversarial tests are first-class** | Every public surface (HTTP, bus topic, scrape callback) needs at least one fuzzing / injection / chaos test. |
| 8 | **Phase gates** | A phase ships only when its checklist in `ROADMAP.md` and the matching DoD in Appendix B are fully green. |
| 9 | **Git is the only AI-restricted surface** | AI assistants must not invoke `git` (commit, push, pull, reset, rebase, stash, tag, branch operations, remote changes, etc.) on the user's behalf. **Everything else is open for agent use** — running tests, `docker compose`, `make` (including the bookkeeping targets `make track.add` / `make version.bump` / `make version.validate`, the mock-data targets `make mock.capture` / `make mock.up` / `make mock.down`, the CodeGraph maintenance targets `make codegraph.status` / `make codegraph.reindex` / `make codegraph.check` (read/refresh only — `codegraph.upgrade` mutates committed wirings and is human-driven), and the sanctioned `sudo` callers `make hosts.install` / `make hosts.uninstall` / `make mock.trust` / `make mock.untrust` / `make mock.setup`), rendering certs, editing files in place, etc. The agent is expected to run the tracker + version-bump commands itself as part of completing a change, not to suggest them and wait. **System-level changes are permitted when they are scoped to making the project work** (installing a missing dev dependency the project needs, writing a hosts entry the mock stack relies on, etc.) provided they (a) do not weaken security, (b) do not destabilise the host, and (c) are reversible. System maintenance unrelated to the project (upgrading unrelated packages, changing global firewall rules, touching other users' files) still defers to the human. The dedicated driver `xops/makefile/git_helper.py` remains the human-only entry point for scripted git flows. **CI carve-out (narrow):** when `$GITHUB_ACTIONS == 'true'` *and* the working branch matches `agent/**`, the pipeline may `git checkout / add / commit / push` and (only when every gate in [`.github/instructions/ci-pipeline.instructions.md`](.github/instructions/ci-pipeline.instructions.md) §4 is green) `git merge --ff-only` into `main`. Force-push, rebase of `main`, tag creation, ref deletion, and any branch outside `agent/**` remain forbidden. This carve-out is binding only on `.github/workflows/orchestrate-*.yml` runs and any script invoked from them; local chat sessions still observe the unrestricted form. |
| 10 | **Tests track code, always** | Every code change must leave the test suite **truthful**. Concretely: (a) **new feature / public surface** → add tests that exercise the happy path *and* at least one adversarial branch (Rule 7); (b) **bug fix** → add a regression test that fails before the fix and passes after — no exceptions; (c) **refactor / rename / signature change** → update every test that touches the moved surface in the same commit (no leaving stale fixtures or skipped tests behind); (d) **behaviour change** → revise existing assertions so they reflect the new contract, not the old one. **Never weaken or delete a test to make a build green.** If an existing test was wrong, fix it and explain why in the tracker row. If you cannot reach a test you should have written, leave the change out and say so — a passing build with no test for new behaviour is a false positive. Run `make test.ai` (or the relevant subset) before declaring done. |
| 11 | **Phase persistence — do not stop mid-phase** | When the human asks you to implement / finish / complete a phase, sub-phase, or slice, the work is the **entire named scope**. Loop internally over every `- [ ]` bullet in that scope (in `docs/planning/ROADMAP.md` and the matching `docs/design/*.md` checklists) until they are all `[x]` or a *real* blocker is hit. Real blockers are narrow: cross-phase forbidden-edit, doctrine conflict, an actually-stuck failing test, a DoD item that requires a human decision (operator key, prod credential), or the human capped scope in the request. **Not** blockers: "this is large", "many edits", "shall I continue?", "I finished part X — proceed with Y?". Per-bullet bookkeeping (tracker row + version bump + checkbox flip per §3.4 / §6.1) still happens for every bullet — you batch the *work*, not the bookkeeping. Final summary once the phase is genuinely drained: list every bullet closed, every command you ran, and any `[ ]` still open with the explicit doctrine reason. Then hand back for `make git`. The chat-mode equivalent of this rule lives in [`.github/copilot-instructions.md`](.github/copilot-instructions.md) §6 and binds every Copilot session by default. |

---

## 3. Phase-tracking discipline (mandatory)

This repo treats roadmap progress as a first-class artifact. The append-only
log lives at [`docs/tracking/phases.csv`](docs/tracking/phases.csv) and is
managed exclusively through [`docs/tracking/track.py`](docs/tracking/track.py).

### 3.1 When to write a tracker entry

Write a row **immediately** in any of these situations:

| Situation | Status | Example note |
|---|---|---|
| Starting a phase / sub-phase | `in-progress` | `"Phase 1.1 config audit kickoff"` |
| Finishing a phase / sub-phase per its DoD | `completed` | `"All checkboxes green; CI passing"` |
| Shipped, but design changed materially | `diverged` | `"Used Redis pubsub instead of NATS"` |
| Re-shaped scope mid-flight, still active | `adapted` | `"Split predictor swarm work into 5a/5b"` |
| Cannot proceed without external input | `blocked` | `"Awaiting decision on TR NLP backend"` |
| Phase abandoned | `cancelled` | `"Removed from scope per stakeholder"` |
| Lightweight progress note inside a phase | `in-progress` (with `--action note`) | `"Wired bus interface; agent SDK still TBD"` |

If you make multiple meaningful edits in a session, write **multiple** rows
— one per event. Do not coalesce.

### 3.2 How to write entries

Always go through the CLI (it stamps UTC time and validates status):

```bash
# Linux / macOS
python3 docs/tracking/track.py start 1 --note "Begin config audit"
python3 docs/tracking/track.py complete 1 --subphase 2 --note "Go config landed"
python3 docs/tracking/track.py diverge 5 --note "Used Redis pubsub" \
    --divergence "Smaller blast radius for 1.0; revisit at 100 agents"

# Windows
py -3 docs\tracking\track.py start 1 --note "Begin config audit"
```

Or via Makefile shortcuts (recommended — picks the right Python launcher):

```bash
make track.list
make track.show  PHASE=0
make track.add   PHASE=1 STATUS=in-progress NOTE="started config audit"
make track.export FORMAT=md   # or FORMAT=csv
```

> Legacy `verb-noun` aliases (`track-list`, `db-seed`, `train-full`, …)
> still dispatch to the new names but print a deprecation warning.

### 3.3 Pairing tracker entries with code

- The agent writes the tracker row itself (via `make track.add` or
  `python3 docs/tracking/track.py`) as part of finishing the change.
  Do not leave it as a TODO for the human.
- Land the tracker row in the **same commit** as the work it describes,
  so `git blame docs/tracking/phases.csv` matches the code timeline.
- Use `--subphase N` to mirror roadmap sub-section numbers
  (`1` → Phase 1.1, `2` → Phase 1.2, etc.). Empty subphase means a
  phase-level rollup event.
- When a sub-phase is `blocked`, also flip its checkbox in
  `docs/planning/ROADMAP.md` to `[~]` (in-progress) or leave `[ ]` and
  reference the tracker row in your response.

### 3.4 Mandatory: tick the ROADMAP and design-doc checkboxes

The tracker is the **timeline** (when something happened); the
checkboxes in `docs/planning/ROADMAP.md` and the relevant
`docs/design/*.md` files are the **state** (what is currently done).
Both must agree at the end of every change.

For every checklist item your work satisfies — no matter how small —
flip its `[ ]` to `[x]` **in the same commit** as the implementing
code and the tracker row. This is non-negotiable:

- ✅ Always re-read the affected phase / design-doc section before
  declaring done. Tick **every** item that is now true, not just the
  one you started with.
- ✅ If a checklist item is *partially* satisfied, leave it `[ ]` and
  add a note in your tracker row + response explaining what's left.
  Do not invent a `[~]` half-state in the ROADMAP unless the item is
  explicitly `blocked` (per §3.3).
- ✅ If you discover a checklist item is **already complete** but
  unticked from a prior session, tick it and mention this in your
  summary.
- ❌ Never tick an item without verifying it. "Compiles" is not
  "done" — the DoD in `ROADMAP.md` Appendix B is the bar.
- ❌ Never tick the phase-rollup checkbox in §0 ("Phase X — …") unless
  every sub-checkbox under that phase and its DoD are green.

The ROADMAP and design docs are the contract the next agent reads
first. Stale checkboxes mislead them and waste budget. Treat ticking
as part of "done", same as tests and version bumps.

### 3.5 What **never** to do

- ❌ Edit `phases.csv` by hand for routine updates. Use the CLI.
- ❌ Delete or rewrite past rows. Append a corrective row instead.
- ❌ Mark a phase `completed` without verifying the DoD in
  `ROADMAP.md` Appendix B and the explicit checklist in that phase.
- ❌ Skip the tracker because the change "is small". Small changes
  inside a phase still warrant a `note`-action row.

---

## 4. Workflow checklist

Use this loop for every non-trivial change. **When the human asks
you to "implement Phase X", "finish §Y", "do this sub-phase", or
similar, you run the loop once per `- [ ]` bullet covered by the
request and only stop when every covered bullet is `[x]` or a real
blocker (Rule 11) is hit. The steps below describe one bullet; do
not return control to the human after a single bullet if more open
bullets remain in the named scope.**

1. **Identify the phase.** Match the user's request to a roadmap phase
   (or sub-phase). If it doesn't fit, say so before coding.
2. **Read the phase's checklist** in `ROADMAP.md`. Pick the smallest
   sub-checkbox that the request advances. (On a "drain this phase"
   request: list every `- [ ]` in scope first, then iterate.)
3. **(If starting fresh)** Write a `start` tracker row.
4. **Make the change.** Respect the doctrine (§2). Touch only what the
   request requires.
5. **Update the tests in the same diff (Rule 10).** New surface →
   add tests; bug fix → add a regression test that fails before the
   fix; refactor / rename / behaviour change → revise every
   affected existing test so it asserts the new contract. Never
   weaken or delete a test to make a build green.
6. **Verify.** Run the relevant tests. For Phase 0+ work, at minimum:
   ```bash
   PYTHONPATH=ai python3 -m pytest ai/tests/test_config_sync.py -q
   ```
7. **Tick the ROADMAP checkboxes** (§3.4) — flip every `[ ]` your work
   now satisfies to `[x]`, not just the one you originally targeted.
   Re-scan the whole sub-phase; you will often have completed adjacent
   items as a side effect. Do the same for any `docs/design/*.md`
   checklists touched by the change.
8. **Write the tracker row** describing what shipped (or diverged /
   blocked / adapted). One row per event.
9. **Refresh CodeGraph if needed.** If the change moved/renamed files,
   added a new public surface, or touched > ~10 files, run
   `make codegraph.status`. If the structure looks stale (or after
   a big refactor / mass rename / `git rebase` that moved files), run
   `make codegraph.reindex` so the next agent has an accurate index.
   Both are part of the agent toolset (Rule 9). Periodically (or
   when an upgrade is plausible) run `make codegraph.check` and
   surface the result in your summary — the human runs
   `make codegraph.upgrade` to actually bump the pin.
10. **Summarize.** Tell the user what changed, what tests ran, and what
    the next sub-phase would be.

---

## 5. File-touch etiquette

- **Read before editing.** Use the file-reading tool, not `cat` over
  large terminal output.
- **Edit in place.** Do not create new "v2" files when modifying
  existing ones.
- **No documentation files unless asked.** Don't create
  `CHANGES.md` / `MIGRATION_NOTES.md` / per-phase summaries — the
  tracker + ROADMAP are the record.
- **Cross-platform.** Anything you add to the `Makefile`, scripts,
  or tooling must work on Linux, macOS, and Windows. The tracker CLI
  is the reference example (stdlib-only, ANSI auto-detect, ISO-8601 UTC).
- **All repo automation lives under `xops/`.** Per-Makefile-target logic
  goes in `xops/makefile/<module>.py` (one module per Makefile section,
  one function per target, dispatched via `_common.dispatch()`); CI/CD
  helpers go in `xops/ci/`; deploy glue in `xops/deploy/`; etc. Do **not**
  create a top-level `scripts/` folder — that name is too generic and
  was retired in favour of `xops/`. See [`xops/README.md`](xops/README.md)
  for the full convention. Make targets stay as one-line dispatchers
  (`@$(XOPS)/<module>.py <subcommand>`); Make owns the dependency graph,
  Python owns the work.
- **Adding a new Make target.** (1) Pick or add the right module under
  `xops/makefile/`. (2) Add `cmd_<target>(argv)` and register it in that
  module's `COMMANDS` dict. (3) Add a one-line Make target that calls
  `@$(XOPS)/<module>.py <target>`. (4) Confirm via `make help`.
- **Phase 2 mock-data discipline.** All scrapers in dev / CI must
  resolve to the mock vhosts (`mackolik.local`, `nesine.local`,
  `tff.local`, `openfootball.local`) via `NEGELIR_SCRAPE_PROFILE=mock`.
  **Never** point a test at a real upstream at test runtime. Refresh
  the seed corpus via `make mock.capture` (agents may run this; it is
  rate-limited and respects `robots.txt` via the source registry);
  validate with `make mock.verify`. Any change to the seed corpus must
  keep `infra/mock/seeds/manifest.json` in sync — the verify test will
  fail on drift.
- **Source-watcher classifications stay deterministic.** Per ROADMAP
  §2.8 doctrine, the classifier rules in
  `ai/swarm/source_watcher/classifier.py` must remain LLM-free. Any
  Phase 8 LLM hook is narration only — it must not change the rule
  outputs. Tests guard this.

---

## 6. Language- and stack-specific rules

| Stack | Source of truth | Tests | Notes |
|---|---|---|---|
| Python (AI / agents) | `ai/common/config.py` | `ai/tests/` (pytest) | 3.8+; stdlib preferred for tooling. |
| Go (server / mocksrv) | `server/internal/config` | `server/...` (`go test`) | Mirrors the Python config pattern. Two run modes: `MODE=api` and `MODE=mocksrv`. |
| Tooling / scripts | n/a | smoke-test in CI | Cross-platform (no bash-isms in shared scripts). |

### 6.1 Versioning discipline (mandatory)

Every main component carries an explicit SemVer in
[`xops/versioning/chart.json`](xops/versioning/chart.json). The umbrella
`negelir` project also carries a SemVer plus a `build` counter that
increments on every component bump.

**The rule:** *any* PR / commit that meaningfully changes a tracked
component **must include a matching `make version.bump`** in the same
commit. "Meaningful" is anything that would be visible to another
developer, contributor, or downstream consumer (new features, bug
fixes, behavior changes, API/interface changes, migration steps). Pure
docstring tweaks or typo fixes inside a single component don't require
a bump.

**The agent runs the bump itself.** `make version.bump` is part of the
agent's normal toolset (Rule 9). Do not ask the human to run it after
the fact — bump as part of finishing the change, in the same turn as
the code edit and the tracker row.

**Levels** (standard SemVer):

| Level | Use when… |
|---|---|
| `patch` | Internal fix or refactor; no API change. |
| `minor` | New feature or new public surface that is backward-compatible. |
| `major` | Breaking change to a public surface (CLI flags, config keys, message schemas, on-disk formats). |

**How to bump:**

```bash
make version.bump COMPONENT=ai LEVEL=patch NOTE="fixed off-by-one in retrain trigger"
make version.bump COMPONENT=infra_mock LEVEL=minor NOTE="Phase 2 scaffolding landed"
make version.bump COMPONENT=project LEVEL=minor NOTE="Phase 2 dev stack live"   # umbrella
```

**Components** (initial set; add new keys by hand-editing `chart.json`
and re-running `make version.validate` — once added, *only* the CLI
may touch the version):

```
ai              — Python AI pipeline (scrapers, model, NLP, orchestrator)
server          — Go REST API + mocksrv binary
xops            — Repo automation
docs            — Roadmap, design docs, tracking, guides
infra_mock      — Mock-data dev stack (Phase 2)
source_watcher  — Source-watcher AI agent (Phase 2.8)
codegraph       — Local CodeGraph MCP server pin (dev tooling)
```

**Hard rules:**

- ❌ Never edit `chart.json` by hand for routine bumps. The
  `test_chart_is_canonical` round-trip test will fail and CI will
  block the merge.
- ✅ The `build` counter is the project's monotonic heartbeat — every
  component bump nudges it. Use it in release artifacts.
- ✅ Bumping `project` resets `build` to `0` automatically.

---

## 7. Quick reference

```bash
# What's where
docs/README.md                  # documentation index
docs/planning/ROADMAP.md        # the plan (single source of truth)
docs/tracking/phases.csv        # append-only progress log
docs/tracking/track.py          # tracker CLI (stdlib only)
docs/tracking/README.md         # tracker schema + CLI usage
docs/design/                    # per-area design docs
docs/guides/SETUP.md            # local dev setup
.env.example                    # legacy path — moved to xops/env/.env.example
xops/env/.env.example           # canonical env-var template (every key documented)
xops/env/.env                   # active values (gitignored)
xops/env/README.md              # env-folder conventions
ai/common/config.py             # Python config layer
server/internal/config/         # Go config layer (Phase 1.2)
xops/                           # all repo automation (CI/CD, deploy, …)
xops/makefile/                  # per-Makefile-target dispatchers
xops/makefile/_common.py        # shared helpers (compose runner, logger)
xops/makefile/git_helper.py     # `make git` driver — HUMAN-ONLY
xops/versioning/chart.json      # centralized SemVer chart (single source)
xops/versioning/version.py      # version CLI (used by `make version.*`)
xops/makefile/codegraph.py      # `make codegraph.*` dispatcher (status/reindex/check/upgrade)
xops/mock/                      # Phase 2 mock-data helpers (manifest, verify, capture)
infra/mock/                     # Phase 2 mock-data root (CA, certs, seeds, nginx vhosts)
ai/swarm/source_watcher/        # Phase 2.8 source-drift detector (deterministic core)
xops/README.md                  # xops conventions & how to extend
docs/guides/CODEGRAPH.md        # CodeGraph MCP dev tooling (Node host process)
.codegraph/                     # CodeGraph local index (DB gitignored, config tracked)
.vscode/mcp.json .mcp.json .cursor/mcp.json  # MCP wirings (codegraph + future)
```

```bash
# Daily commands you will use
make env                        # bootstrap xops/env/.env from xops/env/.env.example
make up / make down             # bring stack up/down
make test.ai                    # Python tests
make test                       # full suite (Python + Go)
make track.list                 # current phase status
make track.show PHASE=0         # full history for one phase
make track.add  PHASE=1 STATUS=in-progress NOTE="…"
make version.show               # show project + component versions
make version.bump COMPONENT=<key> LEVEL=<patch|minor|major> NOTE="..."
make codegraph.status           # cheap health check of the local code index
make codegraph.reindex          # rebuild after big refactors / mass renames
make codegraph.check            # pinned vs latest on npm + wiring drift audit
make codegraph.upgrade          # [HUMAN] bump pin across all 4 wirings [VERSION=…]
make mock.verify                # offline integrity check of Phase 2 seed corpus
make hosts.preview              # list mock hostnames
```

---

## 8. When in doubt

- Re-read [`docs/planning/ROADMAP.md`](docs/planning/ROADMAP.md) before re-planning.
- Re-read [`docs/tracking/README.md`](docs/tracking/README.md) before touching the tracker.
- Ask the human before changing doctrine (§2) or skipping a phase gate.
- Prefer doing **less** and writing a clean tracker row over doing
  more and leaving an unclear trail.
