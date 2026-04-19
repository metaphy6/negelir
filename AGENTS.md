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
6. The relevant `docs/design/*.md` for the area you are touching
   (`SWARM.md`, `CONFIGURATION.md`, `MOCK_DATA_SERVER.md`, `SECURITY.md`,
   `COMPUTE_DEVICES.md`, `LANGUAGE_CHOICES.md`, `TURKISH_NLP.md`,
   `TESTING_STRATEGY.md`).

If the user request conflicts with `ROADMAP.md`, **ask before deviating**.
Do not silently re-plan the project.

---

## 2. Non-negotiable doctrine

These come from `docs/README.md` and `ROADMAP.md` §Guiding Principles.
Every PR, every diff, every agent run must respect them:

| # | Rule | Concretely |
|---|---|---|
| 1 | **Single-source configuration** | New tunables go through `ai/common/config.py` (Python) or `server/internal/config` (Go) and are documented in `.env.example`. No magic numbers, no hardcoded URLs, no inline thresholds. |
| 2 | **Containerized only** | All run/test instructions assume `docker compose`. Never tell the user to `pip install` or `go install` on the host. |
| 3 | **No fabricated production data** | Synthetic data is only allowed inside `*/tests/`. Production code must never silently fall back to fake data. |
| 4 | **Smallest model that works** | Prefer deterministic code → scikit-learn / XGBoost → small transformers (≤ 100 MB) → mid LLMs only with explicit justification in the agent's `README`. |
| 5 | **Scale symmetry** | Same code path runs with 1 replica or 1000. State lives in Redis / Postgres, never in process memory. |
| 6 | **Turkish UX, English infra** | User-facing text & AI input/output in Turkish. Code, comments, log messages, metric names, config keys in English. |
| 7 | **Adversarial tests are first-class** | Every public surface (HTTP, bus topic, scrape callback) needs at least one fuzzing / injection / chaos test. |
| 8 | **Phase gates** | A phase ships only when its checklist in `ROADMAP.md` and the matching DoD in Appendix B are fully green. |
| 9 | **No P2P revival** | The P2P stack was deleted in Phase 0. The regression test `ai/tests/test_config_sync.py::test_p2p_module_removed` will fail if `p2p/` reappears. The replacement is the swarm-AI architecture (Phase 3+). |

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
make track-list
make track-show  PHASE=0
make track-add   PHASE=1 STATUS=in-progress NOTE="started config audit"
make track-export FORMAT=md   # or FORMAT=csv
```

### 3.3 Pairing tracker entries with code

- Land the tracker row in the **same commit** as the work it describes,
  so `git blame docs/tracking/phases.csv` matches the code timeline.
- Use `--subphase N` to mirror roadmap sub-section numbers
  (`1` → Phase 1.1, `2` → Phase 1.2, etc.). Empty subphase means a
  phase-level rollup event.
- When a sub-phase is `blocked`, also flip its checkbox in
  `docs/planning/ROADMAP.md` to `[~]` (in-progress) or leave `[ ]` and
  reference the tracker row in your response.

### 3.4 What **never** to do

- ❌ Edit `phases.csv` by hand for routine updates. Use the CLI.
- ❌ Delete or rewrite past rows. Append a corrective row instead.
- ❌ Mark a phase `completed` without verifying the DoD in
  `ROADMAP.md` Appendix B and the explicit checklist in that phase.
- ❌ Skip the tracker because the change "is small". Small changes
  inside a phase still warrant a `note`-action row.

---

## 4. Workflow checklist

Use this loop for every non-trivial change:

1. **Identify the phase.** Match the user's request to a roadmap phase
   (or sub-phase). If it doesn't fit, say so before coding.
2. **Read the phase's checklist** in `ROADMAP.md`. Pick the smallest
   sub-checkbox that the request advances.
3. **(If starting fresh)** Write a `start` tracker row.
4. **Make the change.** Respect the doctrine (§2). Touch only what the
   request requires.
5. **Verify.** Run the relevant tests. For Phase 0+ work, at minimum:
   ```bash
   PYTHONPATH=ai python3 -m pytest ai/tests/test_config_sync.py -q
   ```
6. **Tick the ROADMAP checkbox** if the sub-task is now complete.
7. **Write the tracker row** describing what shipped (or diverged /
   blocked / adapted). One row per event.
8. **Summarize.** Tell the user what changed, what tests ran, and what
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
- **No P2P, peers (in network sense), gossip, or multicast** in new code
  outside the regression test. The word `peer` is reused in the swarm
  agent context and is fine there.

---

## 6. Language- and stack-specific rules

| Stack | Source of truth | Tests | Notes |
|---|---|---|---|
| Python (AI / agents) | `ai/common/config.py` | `ai/tests/` (pytest) | 3.8+; stdlib preferred for tooling. |
| Go (server / mocksrv) | `server/internal/config` | `server/...` (`go test`) | Mirrors the Python config pattern. Two run modes: `MODE=api` and `MODE=mocksrv`. |
| Tooling / scripts | n/a | smoke-test in CI | Cross-platform (no bash-isms in shared scripts). |

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
.env.example                    # every env var, documented
ai/common/config.py             # Python config layer
server/internal/config/         # Go config layer (Phase 1.2)
xops/                           # all repo automation (CI/CD, deploy, …)
xops/makefile/                  # per-Makefile-target dispatchers
xops/makefile/_common.py        # shared helpers (compose runner, logger)
xops/makefile/git_helper.py     # `make git` driver — HUMAN-ONLY
xops/README.md                  # xops conventions & how to extend
```

```bash
# Daily commands you will use
make env                        # bootstrap .env from .env.example
make up / make down             # bring stack up/down
make test-ai                    # Python tests
make test                       # full suite (Python + Go)
make track-list                 # current phase status
make track-show PHASE=0         # full history for one phase
make track-add  PHASE=1 STATUS=in-progress NOTE="…"
```

---

## 8. When in doubt

- Re-read [`docs/planning/ROADMAP.md`](docs/planning/ROADMAP.md) before re-planning.
- Re-read [`docs/tracking/README.md`](docs/tracking/README.md) before touching the tracker.
- Ask the human before changing doctrine (§2) or skipping a phase gate.
- Prefer doing **less** and writing a clean tracker row over doing
  more and leaving an unclear trail.
