# 🧭 Phase tracking

A tiny CSV-backed log of where each roadmap phase stands, with a
cross-platform CLI to read/write entries.

- **Single source of truth:** [`phases.csv`](phases.csv).
- **Driver:** [`track.py`](track.py) — Python 3.8+ standard library only.
  No third-party deps, no network access. Runs the same on Linux, macOS,
  and Windows.
- **Roadmap reference:** [`../planning/ROADMAP.md`](../planning/ROADMAP.md).

---

## 📐 CSV schema

| Column | Required | Notes |
|---|---|---|
| `timestamp` | ✅ | ISO-8601 UTC, set automatically (e.g. `2026-04-19T12:34:56+00:00`). |
| `phase` | ✅ | Roadmap phase number, `0`–`15`. |
| `subphase` | ⛔ | Optional sub-tag, e.g. `0.2`. Empty for phase-level rollups. |
| `status` | ✅ | See *State machine* below. |
| `action` | ⛔ | Short verb (`start`, `complete`, `diverge`, `cancel`, `adapt`, `block`, `note`, `seed`). |
| `notes` | ⛔ | Free-form: what was done, what shipped, what regressed. |
| `divergence` | ⛔ | Free-form: how reality deviated from the plan, and why. |

The file is **append-only**. Editing past rows by hand is fine, but
prefer adding a new row so the timeline stays intact.

### State machine

```
   not-started ──▶ in-progress ──▶ completed
                       │  ▲
                       │  └─── adapted (re-shaped, still active)
                       ▼
                    blocked  ──┐
                       │       ▼
                       └──▶ diverged / cancelled
```

| Status | When to use |
|---|---|
| `not-started` | Seeded only; no work begun. |
| `in-progress` | Actively being worked on. |
| `completed` | Definition of Done met (see roadmap Appendix B). |
| `diverged` | Shipped, but materially different from the planned design. |
| `adapted` | Scope reshaped mid-flight; still aiming at the original goal. |
| `cancelled` | Phase abandoned. |
| `blocked` | Cannot progress without external input/decision. |

> **`completed` is a high bar.** A row with `status=completed` means
> the phase or sub-phase's full DoD checklist (in `ROADMAP.md`
> Appendix B *and* the per-section `- [ ]` list) is `[x]` and the
> relevant tests pass. **Never** write a `completed` row to "close
> out" partially-shipped work — that violates `AGENTS.md` Rule 11
> (Phase Persistence). If you ran out of context or budget mid-phase
> but the bullets you actually closed are real, write
> `in-progress` rows for those bullets and let the next session
> resume. The only legitimate non-`completed` terminal rows are
> `blocked` (with a concrete external dependency in the note) and
> `cancelled` / `diverged` (with stakeholder approval).

---

## 🛠 CLI usage

The CLI is invoked the same way on every platform — only the launcher differs.

| Platform | Launcher |
|---|---|
| Linux / macOS | `python3 docs/tracking/track.py …` |
| Windows (Python launcher) | `py -3 docs\tracking\track.py …` |
| Windows (PATH `python`) | `python docs\tracking\track.py …` |

Or via the Makefile (which picks the right launcher automatically):

```bash
make track.list
make track.show PHASE=0
make track.add  PHASE=1 STATUS=in-progress NOTE="started config audit"
```

### Subcommands

| Command | Purpose |
|---|---|
| `list` | One row per phase, latest status, last-updated timestamp. |
| `show <phase>` | Full ordered history for one phase. |
| `add --phase N --status STATUS [--note … --divergence … --action … --subphase …]` | Generic append. |
| `start <phase> [--note …]` | Shortcut for `--status in-progress --action start`. |
| `complete <phase> [--note …]` | Shortcut for `--status completed --action complete`. |
| `diverge <phase> --note … [--divergence …]` | Shortcut for `--status diverged`. |
| `adapt <phase> [--note …]` | Shortcut for `--status adapted`. |
| `cancel <phase> [--note …]` | Shortcut for `--status cancelled`. |
| `block <phase> [--note …]` | Shortcut for `--status blocked`. |
| `export [--format csv\|md]` | Dump full log to stdout (default `md`). |

### Examples

```bash
# What's the current state of every phase?
python3 docs/tracking/track.py list

# Drill into Phase 0
python3 docs/tracking/track.py show 0

# Mark Phase 1 started
python3 docs/tracking/track.py start 1 --note "Config dataclass audit kickoff"

# Record a divergence on Phase 5
python3 docs/tracking/track.py diverge 5 \
    --note "Used Redis pubsub instead of NATS" \
    --divergence "Smaller blast radius for now; revisit at 100 agents"

# Snapshot the log to a markdown file
python3 docs/tracking/track.py export --format md > /tmp/tracker.md
```

---

## 🤝 Contribution rules

- **One row = one event.** Don't backfill a row with a "summary"; add a new one.
- **Notes are short.** Prose belongs in `docs/design/` or commit messages.
- **Status changes are atomic.** Land them in the same commit as the work
  they describe so `git blame` matches the tracker timeline.
- **Don't delete rows.** Append a `cancelled` or `adapted` row instead — the
  history is the point.
