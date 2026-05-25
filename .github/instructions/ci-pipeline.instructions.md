---
description: CI-only operating rules for agent runs inside GitHub Actions. Binds the orchestrate-roadmap.yml + orchestrate-resume.yml workflows and any agent invoked from them.
applyTo: ".github/workflows/orchestrate-*.yml,xops/ci/**"
---

# `ci-pipeline` — agent-in-Actions operating rules

> **This file applies only when `$GITHUB_ACTIONS == 'true'`.** When you
> are reading this from a local VS Code chat (no `$GITHUB_ACTIONS` env
> set), [`AGENTS.md`](../../AGENTS.md) Rule 9 still binds you fully —
> no `git`, no auto-merge, the human runs `make git`. The exceptions
> below exist exclusively to let the orchestrator workflow make
> forward progress inside an unattended CI run.

## 1. Why these rules exist

The interactive ROADMAP loop assumes a human attendant who runs
`make git` at the end of every turn. CI has no attendant — the job
either lands its own work or wastes the whole run. So we relax
exactly **two** of the local rules, with hard scope guards:

1. **Rule 9 (no `git`)** is relaxed for branches matching
   `agent/**`. The pipeline may `checkout`, `add`, `commit`, `push`,
   and (under §4 gates) `merge --ff-only` into `main`. Everything
   else — force-push, rebase of `main`, tag creation, deletion of
   any ref — remains forbidden.
2. **§5 "no auto-merge"** is relaxed when *every* item in §4
   below is green. A red gate = no merge, period.

Everything else in [`AGENTS.md`](../../AGENTS.md) §2 still binds.
Especially:

- **Rule 1** (single-source config) — the workflow may not invent
  inline thresholds; tunables go through `xops/env/.env.example`.
- **Rule 3** (no fabricated production data) — synthetic data
  belongs inside `tests/` only.
- **Rule 10** (tests track code) — a CI commit that adds behaviour
  without adding tests fails its own gauntlet and will not be
  merged.

## 2. Branch policy

- Each `workflow_dispatch` opens (or re-uses) a single branch:
  `agent/phase-<phase-id>-<run-id>` (e.g. `agent/phase-8-12345`).
- The branch is created from `main` at workflow start and **never**
  rebased. If `main` advances during the run, the resume scheduler
  re-runs the gauntlet on the merged state before re-attempting
  auto-merge.
- The branch is deleted only after a successful merge **and** the
  resume cursor for its run-id is dropped. A failed run leaves the
  branch in place so a human can inspect / `make git` manually.
- Force-push is banned. The orchestrator workflow uses `git push`
  with no flags; any failure is an error, not a retry-with-force.

## 3. Commit discipline

Every commit the pipeline lands must:

1. Touch only files inside the phase's documented scope (see
   [`AGENTS.md`](../../AGENTS.md) §2 forbidden-edits list and the
   per-section file under `docs/design/phase<N>/sections/`).
2. Include the matching `make track.add` row and
   `make version.bump` from §6.1 — the gauntlet refuses any commit
   that mutates code without a paired tracker/version entry on the
   same commit.
3. Carry a commit message of the form:
   ```
   <component>: <phase id> <one-line summary>

   Phase: <id>  Pass: implementer|reviewer|verifier  Run: <gh-run-id>
   Tracker: <phases.csv row id>
   Version: <component>@<new-semver>
   ```
4. Be signed off by the bot identity configured for `MASTER_TOKEN`.
   No anonymous commits.

The `xops/ci/git_guard.py` script enforces (1) and (2) before every
`git commit`. It exits non-zero with a clear scope-violation
message; the workflow halts and writes a resume cursor with a
``scope-violation`` reason so a human can decide whether to widen
scope or revert.

## 4. Auto-merge gauntlet

Auto-merge into `main` requires **every** of these to be green on
the PR's head commit:

1. `make lint` (`xops/lint/`) — no new magic numbers, no hardcoded
   URLs, no `*-latest` model ids.
2. `make test.ai` — full Python suite passes.
3. `make test` — full polyglot suite (Go + Python) passes.
4. `make version.validate` — `xops/versioning/chart.json` round-trip
   matches; the commit bumped at least one component.
5. `xops/ci/git_guard.py --check-commit HEAD` — scope clean, no
   forbidden-path edits, paired tracker row present.
6. `xops/ci/changed_files_audit.py` — every `.md` checkbox flip
   from `[ ]` to `[x]` in `docs/planning/ROADMAP.md` or
   `docs/design/**/sections/**.md` has a corresponding `phases.csv`
   row referencing the same phase id.

Any red gate ⇒ the workflow refuses to merge, leaves the PR open,
files a tracking issue, and pages the operator (via
`MASTER_TOKEN` issue assignment). It does **not** rerun the
agent automatically — a red gauntlet is a real signal, not a flake.

## 5. Rate-limit handling (do not sleep)

When the upstream LLM (Copilot / Claude / etc.) returns a
rate-limit response (HTTP 429, or any vendor-specific token-bucket
exhaustion signal):

1. **Do not `sleep`** — that burns Actions minutes for no work.
2. Commit any in-progress work to the agent branch with a clear
   `WIP: phase <id> paused (rate-limit)` message. The
   `git_guard.py` allows WIP commits when their message starts with
   `WIP:` and they target the agent branch (never `main`).
3. Write a resume cursor:
   ```
   python3 -m xops.orchestrator.cli resume-save \
       --run-id "$GITHUB_RUN_ID" \
       --workflow-id orchestrate-roadmap.yml \
       --include "$INCLUDE" --exclude "$EXCLUDE" \
       --model "$MODEL" --branch "$BRANCH" \
       --last-completed-phase "$LAST_OK" \
       --next-phase "$NEXT_PHASE" \
       --retry-after "$RETRY_AFTER_SECONDS" \
       --reason "rate-limit: $VENDOR" \
       --retry-count "$RETRY_COUNT"
   ```
4. Commit the cursor file (`.orchestrator/resume/<run>.json`) on
   `main` via the resume-cursor PR helper (cursors live on `main`
   because the scheduler runs against the default branch).
5. Exit the job with code `0`. Do **not** fail the workflow — a
   rate-limit is operationally expected.

The `orchestrate-resume.yml` scheduler runs on cron every 15
minutes, reads `.orchestrator/resume/**`, and re-dispatches
`orchestrate-roadmap.yml` for every cursor whose `not_before` has
elapsed. After successful re-dispatch it drops the cursor.

`MAX_RETRIES` (default 8) is enforced by `ci_resume.save_cursor`.
Beyond that, the cursor write fails and the operator is paged.

## 6. Token & secret discipline

- The pipeline uses `MASTER_TOKEN` (Actions secret) for
  every `git push`, PR/issue mutation, and cross-workflow
  `workflow_dispatch`. The default `GITHUB_TOKEN` is insufficient
  because it cannot create cross-workflow dispatches.
- **Never** echo the token. Use `actions/checkout@v4` with
  `persist-credentials: false` plus explicit `git remote set-url`
  using `$MASTER_TOKEN` to avoid leaking into job logs.
- Anthropic / vendor API keys live in their own Actions secrets,
  scoped to the workflow that needs them.
- The repo's `xops/env/.env` is **never** read in CI — all values
  come from Actions secrets / inputs.

## 7. Model selection

- Default model: `claude-sonnet-4-5` (matches the
  `phase-implementer` / `phase-reviewer` chatmode pin for
  read-heavy work).
- The `model` `workflow_dispatch` input overrides the default. The
  resume cursor carries the chosen model verbatim so a re-armed
  run does not silently swap models.
- Any new model id must be added to the allow-list in
  `xops/ci/run_phase_agent.sh`; an unknown id fails fast.

## 8. Concurrency

- One run per phase at a time. Enforced by `concurrency:` key on
  the workflow + the orchestrator's per-phase lock
  (`make orchestrate.claim PHASE=<id>`).
- The scheduler workflow uses
  `concurrency: orchestrate-resume-scheduler` to prevent two cron
  ticks from racing on the same cursor.
- A run that crashes mid-claim must release the lock via
  `make orchestrate.release PHASE=<id>` in the workflow's
  `if: always()` cleanup step. A stuck lock is recovered only by
  human via `make orchestrate.unlock`.

## 9. What is still off-limits in CI

Even with the relaxations above, the pipeline will refuse to:

- Edit `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`,
  `xops/versioning/chart.json` (by hand), `docs/tracking/phases.csv`
  (by hand), `.github/instructions/**`, `.github/prompts/**`,
  `.github/chatmodes/**`, `.vscode/mcp.json`.
- Touch `server/internal/auth/`, `server/internal/payment/`, or
  `*/crypto/`.
- Run any `gh api` call that mutates org-level settings, secrets,
  branch-protection rules, or workflow files in `.github/workflows/`.
- Disable any CI gate (`--no-verify`, `pytest -x --skip`,
  `if: always()` over the gauntlet step, etc.).

A workflow run that needs any of the above must escalate via the
operator issue queue; it must not edit its way past the guard.
