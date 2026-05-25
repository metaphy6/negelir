# CI Orchestration — GitHub Actions guide

> Covers `orchestrate-roadmap.yml` (manual dispatch) and
> `orchestrate-resume.yml` (rate-limit scheduler).
>
> **Testing status:** the orchestrator CLI and `run_phase_agent.sh`
> (`noop` backend) were smoke-tested locally. The full GitHub Actions
> runs have **not** yet been triggered against a live repository — a
> first real run is needed to validate end-to-end behaviour. See
> [§5 Known gaps](#5-known-gaps).

---

## 1. Prerequisites

| What | Where |
|---|---|
| PAT with `repo` + `workflow` + `issues` scopes | Add as Actions secret named **`MASTER_TOKEN`** |
| Anthropic key (optional — for future direct-API backends) | Actions secret `ANTHROPIC_API_KEY` |
| Python 3.11 available on the runner | Provided by `actions/setup-python@v5` |
| `docs/planning/ROADMAP.md` on `main` | Already there |

The default `GITHUB_TOKEN` is **not** sufficient — it cannot dispatch
cross-workflow runs, which is how the resume scheduler re-triggers the
main workflow.

---

## 2. `orchestrate-roadmap.yml` — run phases manually

**How to trigger:** GitHub UI → _Actions_ → _orchestrate-roadmap_ → _Run workflow_.

### Inputs

| Input | Default | Description |
|---|---|---|
| `include` | _(empty = all eligible)_ | Comma-separated phase ids: `8,9,16` |
| `exclude` | _(empty)_ | Comma-separated phase ids to skip |
| `model` | `claude-sonnet-4-5` | LLM model for the agent loop. Options: `auto`, `claude-sonnet-4-5`, `claude-opus-4-5`, `gpt-5`, `gpt-5-mini`, `gpt-5-codex`. Use `auto` to let the provider route to whatever has capacity (recommended when a weekly cap on one model is suspected). |
| `agent_backend` | `copilot-issue` | How to invoke the agent (see below) |
| `resume_run_id` | _(empty)_ | Load a saved resume cursor instead of starting fresh |

### `agent_backend` options

| Value | Behaviour |
|---|---|
| `copilot-issue` | Creates a GitHub Issue assigned to `@copilot` for each phase; Copilot picks it up and opens a PR. This is the production path. |
| `noop` | Prints what it would do and exits 0. Use for smoke-testing the workflow machinery without burning API quota. |

### What happens step-by-step

1. **Resolve inputs** — if `resume_run_id` is set, load include/exclude/branch from the saved cursor; otherwise use the form inputs.
2. **Plan phases** — calls `xops.orchestrator.cli plan` to select eligible phases from the ROADMAP (skips already-completed, skips excluded).
3. **Prepare agent branch** — checks out or creates `agent/orchestrate-<run_id>` on origin.
4. **Dispatch agent per phase** — loops over planned phases, calls `xops/ci/run_phase_agent.sh`. Exit-code handling:
   - `0` → phase dispatched, continue.
   - `10` → rate-limited: saves a resume cursor (includes `Retry-After` backoff), commits it to `main`, exits the workflow with `0` (no failed run, no wasted minutes).
   - `20` → scope violation: logs an error, skips the phase, continues.
   - `30` → escalation needed: logs and skips.
   - `40` → hard failure: fails the workflow run.
5. **If a rate-limit cursor was saved**, it is committed to `.orchestrator/resume/` on `main` and picked up by the scheduler.

### Rate-limit handling — short-term vs weekly cap

The workflow distinguishes two flavours of 429 based on the
upstream's `Retry-After` value:

| Flavour | Signal | Action |
|---|---|---|
| **Short-term** (per-minute / hourly bucket) | `Retry-After` < 24h | Cursor saved with the *same* model. Backoff = `Retry-After` value, capped at 6h. Resume scheduler re-dispatches when the clock elapses. |
| **Weekly cap** (multi-day quota exhausted) | `Retry-After` >= 24h | Cursor saved with `model=auto` (overriding the original choice) so the resume run uses provider routing instead of waiting for the capped model to refill. The original choice is recorded in `cursor.reason`. |

No human action is required for either case. The fallback to `auto`
is logged visibly in the workflow run + the cursor `reason` field.

### What happens if resume runs and we're _still_ rate-limited?

The scheduler re-dispatches the original workflow; if `run_phase_agent.sh`
still gets a 429, it returns exit `10` again. The workflow saves a
fresh cursor with `retry_count + 1` and a new (exponentially
increasing) `not_before`. The scheduler will retry on its next 15-min
tick once that timestamp elapses. Hard caps:

- **Per-cursor max:** 8 retries. After that, `save_cursor` refuses
  and the workflow exits non-zero — a human must investigate (the
  failed run is visible in the Actions tab; cursor stays on `main`
  until you `make orchestrate.resume-drop RUN_ID=<id>`).
- **Per-attempt backoff cap:** 6 hours, matching the GitHub Actions
  job timeout. A weekly-cap `Retry-After` of e.g. 4 days is honoured
  by writing `not_before = now + 6h` and then retrying every 6h
  (each retry re-checks the upstream — if it's still capped, another
  6h cursor is written). The `auto` fallback above usually resolves
  this on the first retry by routing to a different model family.

### Wake-up timing: grace buffer + clock-skew retries

`not_before` is always set to **`base + Retry-After + 120s`** — the
2-minute grace buffer (`CLOCK_SKEW_GRACE_SECONDS`) absorbs NTP drift
between the GH runner, our scheduler, and the upstream provider so
the cron doesn't fire one second before the upstream window actually
clears.

If a wake-up dispatches the workflow but the upstream still says
rate-limited (clock skew, transient 503, runner boot lag), that's
counted as a **wake attempt**, not a real upstream retry. The cursor
carries a separate `wake_attempts` counter, capped at
`MAX_WAKE_ATTEMPTS = 5`. This keeps the `retry_count` budget (8)
honest — only actual upstream rate-limits eat from it. Exceeding the
wake cap also raises and pages a human.

### Concurrency

One run per `resume_run_id` (or `run_id` for fresh starts). A second
dispatch for the same run id will queue rather than cancel.

---

## 3. `orchestrate-resume.yml` — automatic rate-limit recovery

Runs every 15 minutes via cron (also dispatchable manually).

1. Checks out `main`.
2. Calls `xops.orchestrator.cli resume-list --ready-only` — returns cursors whose `not_before` epoch has elapsed.
3. For each ready cursor, calls `gh workflow run orchestrate-roadmap.yml` with the saved include/exclude/model/resume_run_id.
4. Drops the cursor file and commits the deletion to `main`.

**You do not need to do anything when a rate-limit happens.** The
scheduler will re-trigger the original run automatically. Max retries
per cursor: 8. Max backoff: 6 hours.

---

## 4. Useful commands

```bash
# See pending resume cursors locally
make orchestrate.resume-list

# See only the ones ready to fire right now
make orchestrate.resume-list READY=1

# Drop a cursor manually (e.g. if you cancelled a run)
make orchestrate.resume-drop RUN_ID=<run_id>

# Dry-run the plan locally (no agent dispatch)
python3 -m xops.orchestrator.cli plan --include "8,9" --json

# Test the shell script dispatch path without touching GitHub
AGENT_BACKEND=noop PHASE_ID=8 MODEL=claude-sonnet-4-5 \
    bash xops/ci/run_phase_agent.sh
```

---

## 5. Known gaps

These have **not** been validated in a live Actions environment yet —
the first real run will confirm or uncover issues:

| Gap | Risk | Mitigation |
|---|---|---|
| `copilot-issue` backend: Copilot may not auto-pick up the issue | Medium — depends on Copilot for Issues being enabled on the repo | Fallback: use a direct API backend when available, or assign the issue manually |
| Auto-merge gauntlet (§4 of ci-pipeline.instructions.md) requires PRs to pass CI before `--ff-only` merge | Low — gauntlet is CI-standard | First run will expose any missing status check names |
| Resume scheduler cron fires even when no cursors exist — harmless but spends a few seconds per tick | Low | Add a short-circuit exit once confirmed stable |
| `xops.orchestrator.cli plan --json` output format assumed by the workflow | Low — smoke-tested locally | Validate with `noop` backend on first run |

---

## 6. Secret setup checklist

- [ ] Create a PAT: _Settings → Developer settings → Personal access tokens (classic)_ → scopes: `repo`, `workflow`, `issues`.
- [ ] Add it as a repository secret: _Settings → Secrets → Actions_ → name it **`MASTER_TOKEN`** (exact name — other names will break the workflows).
- [ ] Optionally add `ANTHROPIC_API_KEY` for future direct-API backends.
- [ ] Run a first dispatch with `agent_backend=noop` and `include=` a single cheap phase to verify the plumbing before using `copilot-issue`.
