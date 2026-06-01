---
description: Master mode — implement every open ROADMAP phase end-to-end via the CI loop. Dispatches orchestrate-full-roadmap.yml which chains implement → PR review → auto-merge → next phase until the entire project is done. No INCLUDE= required. Works with every model backend.
mode: agent
tools: ['codebase', 'search', 'runCommands', 'problems', 'changes', 'githubRepo']
agents: []
---

# Full-Project Drain (CI master mode)

You are the **trigger** for an autonomous CI loop that implements
every open phase in `docs/planning/ROADMAP.md` from start to
finish without human intervention.

## What you do (exactly this, in order, then stop)

1. **Print the open-phase list** so the user can see what will run:
   ```bash
   make orchestrate.list
   ```
   Highlight any phases already at `completed` (they will be skipped).

2. **Run the full-roadmap status check** — abort if a session is
   already active:
   ```bash
   python3 -m xops.orchestrator.cli full-roadmap-status
   ```
   If a cursor exists, tell the user the session id and remaining
   phases, and ask whether to cancel it (`full-roadmap-drop`) or
   continue. This is the **one and only question** you are allowed
   to ask. Do not ask about model, parallelism, phase ranges, etc.

3. **Dispatch the CI loop** via the GitHub CLI:
   ```bash
   gh workflow run orchestrate-full-roadmap.yml \
       --ref main \
       -f model="$MODEL" \
       -f exclude="$EXCLUDE" \
       -f max_phases="$MAX_PHASES"
   ```
   Use these defaults unless the user specified otherwise in their
   request:
   - `MODEL=claude-sonnet-4-5`
   - `EXCLUDE=""` (empty — include all open phases)
   - `MAX_PHASES=200`

4. **Print the CI loop architecture** so the user understands what
   is about to happen (one paragraph, not a tutorial):

   > The CI loop will implement **Phase N** first. The Copilot
   > Coding Agent will open a PR on `agent/phase-N-fullroadmap-<session>`.
   > `orchestrate-pr-review.yml` will run the §4 gauntlet, approve,
   > and auto-merge when clean — or request changes and re-tag
   > `@copilot` if fixes are needed. Once the PR merges, the
   > `continue-full-roadmap` job automatically dispatches
   > `orchestrate-full-roadmap.yml` for Phase N+1, and so on until
   > all phases are done. Monitor progress at:
   > `gh run list --workflow orchestrate-full-roadmap.yml`

5. **Print the monitoring commands** the user can run:
   ```bash
   # Live progress
   python3 -m xops.orchestrator.cli full-roadmap-status

   # Watch workflow runs
   gh run list --workflow orchestrate-full-roadmap.yml --limit 20

   # Watch open agent PRs
   gh pr list --search "head:agent/"

   # Abort the loop at any time (prevents next phase dispatch):
   python3 -m xops.orchestrator.cli full-roadmap-drop
   git add .orchestrator/full-roadmap && git commit -m "ci: abort full-roadmap session" && git push origin main
   ```

6. **Stop.** You do not loop locally. You do not run subagents.
   You do not wait. The CI does the work.

## Hard rules

- **Do not run `git`.** The CI does all git operations.
- **Do not use `runSubagent`** — this is a CI-delegated run, not
  a local subagent loop. The implementer, reviewer, and verifier
  run *inside GitHub Actions*, not here.
- **Do not implement anything yourself.** Your only job is to
  trigger the CI loop and hand back.
- **Do not ask about model, parallelism, or phase ranges** unless
  the user explicitly mentioned them. Defaults are good enough.
- **Do not loop.** Print status commands and stop.

## When the user asks to monitor / check progress

Run these and report:

```bash
python3 -m xops.orchestrator.cli full-roadmap-status
gh run list --workflow orchestrate-full-roadmap.yml --limit 10
gh pr list --search "head:agent/" --json number,title,state,url \
    | python3 -c 'import json,sys; [print(f"#{r[\"number\"]} {r[\"state\"]:8} {r[\"title\"]}") for r in json.load(sys.stdin)]'
```

## When the user asks to abort

```bash
python3 -m xops.orchestrator.cli full-roadmap-drop --json
git add .orchestrator/full-roadmap
git diff --cached --quiet || git commit -m "ci: abort full-roadmap session"
git push origin main
# Cancel any in-progress workflow runs:
gh run list --workflow orchestrate-full-roadmap.yml --status in_progress \
    --json databaseId -q '.[].databaseId' \
    | xargs -r -I{} gh run cancel {}
```

## When the user wants to run a SPECIFIC phase through the full loop

Use `orchestrate-full-roadmap.yml` with a single-phase list:

```bash
gh workflow run orchestrate-full-roadmap.yml \
    --ref main \
    -f model="claude-sonnet-4-5" \
    -f exclude="$(python3 -m xops.orchestrator.cli plan --json \
        | python3 -c 'import json,sys; ids=json.load(sys.stdin)["phase_ids"]; print(",".join(i for i in ids if i != "DESIRED_PHASE"))')" \
    -f max_phases=1
```

Substitute `DESIRED_PHASE` with the user's specified phase id.

## What you MUST NOT do

- Start implementing phases locally via `runSubagent("phase-implementer", …)`
- Say "I will now implement Phase X" — that is the CI's job
- Ask "should I continue?" or "shall I dispatch?" after step 2
  (the user invoked this prompt precisely to say yes)
- Create PRs yourself via `gh pr create`
- Ask any follow-up questions after the one allowed in step 2
