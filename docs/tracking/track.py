#!/usr/bin/env python3
"""
Negelir — phase tracker CLI.

Cross-platform (Linux / macOS / Windows). Python 3.8+ standard library only.
No third-party deps; no network access; UTF-8 throughout; CSV uses
``newline=""`` per :pep:`PEP 305 <305>` recommendation so Excel-on-Windows
and POSIX `csv` agree.

The phase log lives at ``docs/tracking/phases.csv`` next to this file.

Columns
-------
``timestamp``   — ISO-8601 UTC, set automatically when adding a row.
``phase``       — Roadmap phase number (0–15).
``subphase``    — Optional sub-phase (e.g. ``0.2``); blank for phase-level rows.
``status``      — One of: ``not-started``, ``in-progress``, ``completed``,
                  ``diverged``, ``cancelled``, ``adapted``, ``blocked``.
``action``      — Short verb describing the entry (e.g. ``start``, ``complete``,
                  ``note``, ``diverge``, ``cancel``, ``adapt``, ``seed``).
``notes``       — Free-form what-was-done text.
``divergence``  — Free-form note when status implies a deviation from plan.

Usage
-----
::

    python3 docs/tracking/track.py list
    python3 docs/tracking/track.py show 0
    python3 docs/tracking/track.py add --phase 1 --status in-progress \\
        --note "started config audit"
    python3 docs/tracking/track.py complete 0 --note "Phase 0 cleanup landed"
    python3 docs/tracking/track.py diverge 5 --note "swap NATS for Redis pubsub" \\
        --divergence "smaller blast radius for now"
    python3 docs/tracking/track.py export --format md > tracker.md

On Windows, replace ``python3`` with ``py -3`` or ``python``.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent / "phases.csv"
COLUMNS = ("timestamp", "phase", "subphase", "status", "action",
           "notes", "divergence")
VALID_STATUSES = {
    "not-started", "in-progress", "completed",
    "diverged", "cancelled", "adapted", "blocked",
}

# ── tiny ANSI helpers (auto-disabled on non-TTY / Windows w/o color) ──
def _supports_color() -> bool:
    return sys.stdout.isatty() and sys.platform != "win32"


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


_STATUS_COLOR = {
    "completed":  "32",   # green
    "in-progress": "36",  # cyan
    "not-started": "37",  # white
    "diverged":   "33",   # yellow
    "adapted":    "33",
    "blocked":    "31",   # red
    "cancelled":  "31",
}


# ── IO ────────────────────────────────────────────────────────
def _ensure_csv() -> None:
    if CSV_PATH.exists():
        return
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(COLUMNS)


def _read_rows() -> list[dict]:
    _ensure_csv()
    with CSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _append_row(row: dict) -> None:
    _ensure_csv()
    # Normalize and clamp keys to declared columns.
    payload = {col: (row.get(col) or "") for col in COLUMNS}
    with CSV_PATH.open("a", encoding="utf-8", newline="") as fh:
        csv.DictWriter(fh, fieldnames=COLUMNS).writerow(payload)


def _now_iso() -> str:
    # 2026-04-19T12:34:56+00:00 — sortable, locale-free.
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── command handlers ──────────────────────────────────────────
def cmd_add(args: argparse.Namespace) -> int:
    if args.status not in VALID_STATUSES:
        print(f"error: status must be one of: {sorted(VALID_STATUSES)}",
              file=sys.stderr)
        return 2
    _append_row({
        "timestamp":  _now_iso(),
        "phase":      str(args.phase),
        "subphase":   args.subphase or "",
        "status":     args.status,
        "action":     args.action or "note",
        "notes":      args.note or "",
        "divergence": args.divergence or "",
    })
    print(f"✔ recorded phase {args.phase}"
          + (f".{args.subphase}" if args.subphase else "")
          + f" → {args.status}")
    return 0


def _shortcut(args: argparse.Namespace, *, status: str, action: str) -> int:
    args.status = status
    args.action = action
    return cmd_add(args)


def cmd_complete(args: argparse.Namespace) -> int:
    return _shortcut(args, status="completed", action="complete")


def cmd_start(args: argparse.Namespace) -> int:
    return _shortcut(args, status="in-progress", action="start")


def cmd_diverge(args: argparse.Namespace) -> int:
    if not args.divergence and not args.note:
        print("error: --divergence or --note is required", file=sys.stderr)
        return 2
    return _shortcut(args, status="diverged", action="diverge")


def cmd_cancel(args: argparse.Namespace) -> int:
    return _shortcut(args, status="cancelled", action="cancel")


def cmd_adapt(args: argparse.Namespace) -> int:
    return _shortcut(args, status="adapted", action="adapt")


def cmd_block(args: argparse.Namespace) -> int:
    return _shortcut(args, status="blocked", action="block")


def cmd_list(args: argparse.Namespace) -> int:
    rows = _read_rows()
    if not rows:
        print("(no entries)")
        return 0

    # Last status per (phase, subphase). Empty subphase = phase-level rollup.
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["phase"], r["subphase"])
        latest[key] = r

    # Roll up per phase: prefer the most recent phase-level row; fall back to
    # the most recent row regardless of subphase.
    phases: dict[str, dict] = {}
    for (phase, sub), r in sorted(latest.items(), key=lambda kv: kv[1]["timestamp"]):
        if phase not in phases or sub == "":
            phases[phase] = r

    print(f"{'PHASE':<6} {'STATUS':<13} {'UPDATED':<26} NOTE")
    print("-" * 80)
    for phase in sorted(phases, key=lambda p: int(p) if p.isdigit() else 99):
        r = phases[phase]
        status = _c(f"{r['status']:<13}", _STATUS_COLOR.get(r["status"], "0"))
        ts = r["timestamp"][:19].replace("T", " ")
        note = r["notes"][:60]
        print(f"{phase:<6} {status} {ts:<26} {note}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    rows = [r for r in _read_rows() if r["phase"] == str(args.phase)]
    if not rows:
        print(f"(no entries for phase {args.phase})")
        return 0
    print(f"=== Phase {args.phase} — {len(rows)} entr"
          f"{'y' if len(rows) == 1 else 'ies'} ===")
    for r in rows:
        sub = f".{r['subphase']}" if r["subphase"] else ""
        head = f"[{r['timestamp']}] {args.phase}{sub} → {r['status']} ({r['action']})"
        print(_c(head, _STATUS_COLOR.get(r["status"], "0")))
        if r["notes"]:
            print(f"    note:       {r['notes']}")
        if r["divergence"]:
            print(f"    divergence: {r['divergence']}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    rows = _read_rows()
    if args.format == "csv":
        # Rewrite to stdout for piping. CSV is already UTF-8 on disk.
        writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return 0

    # markdown
    print("| Timestamp | Phase | Sub | Status | Action | Notes | Divergence |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        cells = [
            r["timestamp"], r["phase"], r["subphase"], r["status"],
            r["action"],
            (r["notes"] or "").replace("|", "\\|"),
            (r["divergence"] or "").replace("|", "\\|"),
        ]
        print("| " + " | ".join(cells) + " |")
    return 0


# ── parser ────────────────────────────────────────────────────
def _add_common_args(p: argparse.ArgumentParser, *, require_phase: bool = True) -> None:
    p.add_argument("phase", type=int, nargs=None if require_phase else "?",
                   help="Roadmap phase number (0–15).")
    p.add_argument("--subphase", default="",
                   help="Optional sub-phase tag, e.g. '0.2'.")
    p.add_argument("--note", default="",
                   help="Free-form note (what was done).")
    p.add_argument("--divergence", default="",
                   help="Free-form divergence note (deviation from the plan).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="track.py",
        description="Negelir phase tracker — append-only CSV log + reporting CLI.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Append a custom entry with explicit --status.")
    _add_common_args(p_add)
    p_add.add_argument("--status", required=True,
                       help=f"One of: {sorted(VALID_STATUSES)}")
    p_add.add_argument("--action", default="note",
                       help="Short verb (default: 'note').")
    p_add.set_defaults(func=cmd_add)

    p_start = sub.add_parser("start", help="Mark a phase 'in-progress'.")
    _add_common_args(p_start)
    p_start.set_defaults(func=cmd_start)

    p_complete = sub.add_parser("complete", help="Mark a phase 'completed'.")
    _add_common_args(p_complete)
    p_complete.set_defaults(func=cmd_complete)

    p_diverge = sub.add_parser("diverge", help="Record a divergence from the plan.")
    _add_common_args(p_diverge)
    p_diverge.set_defaults(func=cmd_diverge)

    p_cancel = sub.add_parser("cancel", help="Mark a phase 'cancelled'.")
    _add_common_args(p_cancel)
    p_cancel.set_defaults(func=cmd_cancel)

    p_adapt = sub.add_parser("adapt", help="Mark a phase 'adapted' (re-shaped scope).")
    _add_common_args(p_adapt)
    p_adapt.set_defaults(func=cmd_adapt)

    p_block = sub.add_parser("block", help="Mark a phase 'blocked'.")
    _add_common_args(p_block)
    p_block.set_defaults(func=cmd_block)

    p_list = sub.add_parser("list", help="Show latest status per phase.")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show full history for one phase.")
    p_show.add_argument("phase", type=int)
    p_show.set_defaults(func=cmd_show)

    p_export = sub.add_parser("export", help="Dump the log to stdout (csv|md).")
    p_export.add_argument("--format", choices=("csv", "md"), default="md")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
