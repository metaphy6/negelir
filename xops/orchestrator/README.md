# `xops/orchestrator/` — parallel ROADMAP phase coordinator

Coordinates the work of context-isolated subagents that implement
ROADMAP phases. **All chat-side glue lives in
[`.github/prompts/orchestrate.roadmap.prompt.md`](../../.github/prompts/orchestrate.roadmap.prompt.md)
and the `phase-implementer` / `phase-reviewer` / `phase-verifier`
chatmodes.** This Python package contains zero `git` calls and
zero `runSubagent` calls — it is a *coordinator*, not an executor.

## Why this exists

The ROADMAP has 400+ checkboxes across 20+ phases. Driving them
serially through one chat is slow and runs out of context. The
orchestrator lets you:

- **Filter** which phases are in scope
  (`INCLUDE=16  EXCLUDE=9.17.11`).
- **Claim** a phase atomically so a parallel orchestrator run
  cannot start the same work.
- **Track** the multi-pass review (implementer → reviewer →
  verifier) in a per-phase JSON state file.
- **Inspect** stuck phases and forcibly recover from a crashed
  agent.

## What lives where

| Path | Purpose |
|---|---|
| `roadmap.py` | Parse `docs/planning/ROADMAP.md` into a `PhaseNode` tree (root phase 0–N + R-prefixed pivot ids). |
| `selector.py` | Resolve `INCLUDE` / `EXCLUDE` filter tokens into a concrete leaf-phase list. |
| `locks.py` | Per-phase atomic file lock under `.orchestrator/locks/`. |
| `state.py` | Per-phase JSON state under `.orchestrator/state/` with the `pending → implementing → reviewing → verifying → completed` machine. |
| `cli.py` | `python3 -m xops.orchestrator.cli <subcmd>` — entry point invoked by `make orchestrate.*`. |
| `tests/` | Stdlib pytest covering all four contracts. |

## Make-target cheat sheet

```bash
make orchestrate.list                                    # tree + checkbox status
make orchestrate.plan INCLUDE=16 EXCLUDE=16.16,16.0      # what would run
make orchestrate.next INCLUDE=16                         # next un-claimed leaf
make orchestrate.slice PHASE=16.1                        # verbatim ROADMAP body
make orchestrate.claim PHASE=16.1                        # exit 0 ok / 8 busy / 2 unknown
make orchestrate.release PHASE=16.1                      # exit 0 ok / 9 missing
make orchestrate.locks                                   # who holds what
make orchestrate.state PHASE=16.1                        # multi-pass log
make orchestrate.advance PHASE=16.1 ROLE=reviewer \
    OUTCOME=ok STATUS=verifying NOTES="lgtm"             # record a pass
make orchestrate.unlock PHASE=16.1                       # operator: clear stale lock

# Full-project loop (implement everything, phase by phase, via CI)
make orchestrate.fullroadmap                             # dispatch CI loop for all open phases
make orchestrate.fullroadmap MODEL=gpt-5 EXCLUDE=9.17   # with overrides
make orchestrate.fullroadmap.status                      # show active session progress
make orchestrate.fullroadmap.drop                        # abort the active session
```

Pass `JSON=1` on any of the above for machine-readable output.

## Filter syntax

- Comma-separated ids: `INCLUDE=16,17.3,18`.
- Tokens are matched **exactly** against a phase id, or as a
  prefix followed by a dot. `16` matches `16` itself plus
  `16.1`, `16.2.3`, etc. `9.17` matches `9.17`, `9.17.11`, but
  **not** `9.170`.
- Default behaviour: `leaves_only=true` (skip non-leaf
  branches), `skip_complete=true` (skip phases whose
  checkboxes are all `[x]` or `[~]`). Override with
  `INCLUDE_BRANCHES=1` / `INCLUDE_COMPLETE=1`.
- Unknown tokens raise immediately — no silent typos.

## Lock semantics

- Implemented by atomic `os.open(..., O_CREAT | O_EXCL)`.
  Cross-process safe on POSIX and Windows; survives across
  short-lived CLI invocations (unlike `fcntl.flock`, which
  releases on fd close).
- A lock is **never** auto-released by a timeout. The human
  operator (the only one allowed to land git commits per
  `AGENTS.md` Rule 9) is the safety net. If an agent crashes
  and orphans a lock, run `make orchestrate.unlock PHASE=<id>`.
- Lock files contain a JSON header
  (`phase_id`, `claimer_id`, `claimed_at`, `host`, `pid`) so an
  operator can decide whether a stale lock is safe to clear.

## State machine

```
pending → implementing → reviewing → verifying → completed
                              ↘─────┐         ↗
                                    └→ blocked / failed / escalated / skipped
```

Every transition appends a `PassRecord(role, at, outcome, model,
notes, diff_summary)` to `passes[]` so the next agent (or human)
can reconstruct the entire history.

## Parallel-run discipline

- Two orchestrator runs may operate concurrently against the
  same repo. They must **not** claim the same phase — the lock
  guarantees this.
- They **may** race on shared mutable state (e.g. the same
  `phases.csv` row, the same checkbox in `ROADMAP.md`). The
  per-phase lock prevents this *for code edits inside one
  phase*. Cross-phase edits remain a human responsibility — the
  ROADMAP is structured so that sub-phases are independently
  shippable, but the reviewer/verifier chain is your last line
  of defence.
- The chatmodes are designed so the verifier always either
  releases the lock (on `ok`) or leaves it held (on
  `needs-changes`), so the implementer can keep iterating.

## What this package will *never* do

- **Run `git`.** Not `commit`, not `push`, not `status` if it
  would mutate. AGENTS.md Rule 9 is binding. The human runs
  `make git` to land work.
- **Call `runSubagent`.** Subagent dispatch is a chat-side
  primitive; this package sits underneath it.
- **Edit ROADMAP checkboxes or tracker rows.** Those are owned
  by the implementer chatmode and `make track.add` /
  `make version.bump`. The orchestrator is bookkeeping for the
  loop, not the project.

## Sandboxing for tests

The package uses module-level `LOCK_DIR` / `STATE_DIR` constants
that point at `<repo>/.orchestrator/`. Tests `monkeypatch` these
to a `tmp_path` so unit tests never touch the real on-disk state.
See [`tests/test_orchestrator.py`](tests/test_orchestrator.py).

## Full-project loop (`ci_full_roadmap.py`)

`ci_full_roadmap.py` manages a single **session cursor** that drives
the autonomous end-to-end CI loop:

```
[make orchestrate.fullroadmap]
    │ creates cursor, dispatches phase[0]
    ▼
[Copilot Coding Agent] implements phase, opens PR on agent/**
    │ pull_request opened
    ▼
[orchestrate-pr-review.yml] reviews + auto-merges PR
    │ pull_request closed+merged
    ▼
[continue-full-roadmap job] pops phase from cursor,
    dispatches orchestrate-full-roadmap.yml for phase[1]
    │ …
    ▼ (repeat until cursor empty)
[orchestrate-full-roadmap.yml] drops cursor, prints done
```

The cursor file lives at `.orchestrator/full-roadmap/<session_id>.json`
on the default branch. CLI commands:

```python
# Create
python3 -m xops.orchestrator.cli full-roadmap-save \
    --phases-remaining "8,9,10" --model claude-sonnet-4-5

# Read
python3 -m xops.orchestrator.cli full-roadmap-load --json

# Stamp dispatch (before dispatching phase)
python3 -m xops.orchestrator.cli full-roadmap-advance <phase_id>

# Record merge (after PR merges)
python3 -m xops.orchestrator.cli full-roadmap-complete <phase_id>

# Human-readable progress
python3 -m xops.orchestrator.cli full-roadmap-status

# Abort
python3 -m xops.orchestrator.cli full-roadmap-drop
```

At most one cursor is active at a time. `find_active_cursor()` scans
`.orchestrator/full-roadmap/*.json` and returns the first match.
