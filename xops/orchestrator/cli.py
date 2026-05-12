"""Orchestrator CLI — entry point for `make orchestrate.*` Make targets.

Subcommands:

    list                  Print the phase tree with checkbox status.
    plan                  Show what `run` would dispatch (respects --include/--exclude).
    slice <PHASE>         Print the verbatim ROADMAP slice for one phase.
    claim <PHASE>         Acquire the per-phase lock (parallel-safe).
    release <PHASE>       Release the per-phase lock.
    locks                 List currently held locks.
    state [<PHASE>]       Show orchestrator state.
    advance <PHASE>       Update phase status / record a review pass.
    next                  Print the next un-claimed leaf id matching the filter.

The CLI is *only* a coordinator. It never invokes git, runSubagent, or any
mutation outside `.orchestrator/`. See AGENTS.md Rule 9.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import locks, state
from .roadmap import RoadmapTree, parse_roadmap
from .selector import parse_filter, select_phase_ids


# ── Output helpers ────────────────────────────────────────────


def _emit(obj: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, sort_keys=True))
    else:
        for k, v in obj.items():
            print(f"{k}: {v}")


def _err(msg: str, code: int = 1) -> None:
    print(f"orchestrator: {msg}", file=sys.stderr)
    sys.exit(code)


# ── Subcommand implementations ────────────────────────────────


def cmd_list(tree: RoadmapTree, args: argparse.Namespace) -> int:
    rows = []
    for pid in tree.order:
        node = tree.nodes[pid]
        if args.leaves_only and node.children:
            continue
        rows.append(
            {
                "id": pid,
                "depth": node.depth,
                "title": node.title,
                "open": node.open_boxes,
                "done": node.done_boxes,
                "deferred": node.deferred_boxes,
                "total": node.total_boxes,
                "complete": node.is_complete,
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 0
    for r in rows:
        bar = f"{r['done']}/{r['total']}"
        marker = "✔" if r["complete"] else " "
        indent = "  " * (r["depth"] - 2)
        print(f"{marker} {indent}{r['id']:<10} [{bar:>7}] {r['title']}")
    return 0


def _filtered(tree: RoadmapTree, args: argparse.Namespace) -> List[str]:
    return select_phase_ids(
        tree,
        include=parse_filter(args.include),
        exclude=parse_filter(args.exclude),
        leaves_only=not args.include_branches,
        skip_complete=not args.include_complete,
    )


def cmd_plan(tree: RoadmapTree, args: argparse.Namespace) -> int:
    ids = _filtered(tree, args)
    payload = {
        "include": parse_filter(args.include),
        "exclude": parse_filter(args.exclude),
        "leaves_only": not args.include_branches,
        "skip_complete": not args.include_complete,
        "count": len(ids),
        "phase_ids": ids,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"Planned phases ({len(ids)}):")
    for pid in ids:
        node = tree.nodes[pid]
        print(f"  - {pid:<10} {node.open_boxes}/{node.total_boxes} open  | {node.title}")
    return 0


def cmd_slice(tree: RoadmapTree, args: argparse.Namespace, source: str) -> int:
    node = tree.nodes.get(args.phase)
    if not node:
        _err(f"unknown phase {args.phase!r}", 2)
    body = tree.slice_text(args.phase, source)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"wrote {len(body)} bytes to {args.out}")
    else:
        sys.stdout.write(body)
    return 0


def cmd_claim(tree: RoadmapTree, args: argparse.Namespace) -> int:
    if args.phase not in tree.nodes:
        _err(f"unknown phase {args.phase!r}", 2)
    try:
        header = locks.try_claim(args.phase, claimer_id=args.claimer)
    except locks.LockBusy as exc:
        _err(str(exc), 8)
        return 8  # unreachable
    # Initialise / refresh state.
    st = state.load(args.phase) or state.PhaseState(
        phase_id=args.phase, title=tree.nodes[args.phase].title
    )
    if st.status in ("completed", "skipped"):
        # Re-claim of an already-finished phase: leave status, but log entry.
        pass
    else:
        state.transition(st, "implementing")
    state.save(st)
    _emit(
        {
            "phase_id": args.phase,
            "claimer_id": header.claimer_id,
            "status": st.status,
            "lock": str(locks.lock_path(args.phase)),
        },
        as_json=args.json,
    )
    return 0


def cmd_release(tree: RoadmapTree, args: argparse.Namespace) -> int:
    try:
        removed = locks.release(args.phase, force=args.force)
    except locks.LockMissing as exc:
        _err(str(exc), 9)
        return 9
    _emit({"phase_id": args.phase, "released": removed}, as_json=args.json)
    return 0


def cmd_locks(tree: RoadmapTree, args: argparse.Namespace) -> int:
    held = locks.list_held()
    if args.json:
        print(json.dumps([h.__dict__ for h in held], indent=2, sort_keys=True))
        return 0
    if not held:
        print("(no phases currently claimed)")
        return 0
    for h in held:
        print(f"  {h.phase_id:<10} by={h.claimer_id} pid={h.pid} host={h.host}")
    return 0


def cmd_state(tree: RoadmapTree, args: argparse.Namespace) -> int:
    if args.phase:
        st = state.load(args.phase)
        if not st:
            _emit({"phase_id": args.phase, "status": "pending"}, as_json=args.json)
            return 0
        if args.json:
            print(json.dumps(st.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"phase {st.phase_id}: {st.status}  ({len(st.passes)} pass(es))")
            for p in st.passes:
                print(f"  - {p.role:<11} outcome={p.outcome:<14} model={p.model}")
        return 0

    states = state.list_states()
    if args.json:
        print(json.dumps([s.to_dict() for s in states], indent=2, sort_keys=True))
        return 0
    if not states:
        print("(no orchestrator state recorded)")
        return 0
    for s in states:
        print(f"  {s.phase_id:<10} {s.status:<13} passes={len(s.passes)}")
    return 0


def cmd_advance(tree: RoadmapTree, args: argparse.Namespace) -> int:
    if args.phase not in tree.nodes:
        _err(f"unknown phase {args.phase!r}", 2)
    st = state.load(args.phase) or state.PhaseState(
        phase_id=args.phase, title=tree.nodes[args.phase].title
    )
    if args.role:
        state.record_pass(
            st,
            role=args.role,
            outcome=args.outcome or "ok",
            model=args.model or "",
            notes=args.notes or "",
            diff_summary=args.diff_summary or "",
        )
    if args.status:
        state.transition(st, args.status)
    if args.last_error:
        st.last_error = args.last_error
    state.save(st)
    _emit(
        {"phase_id": args.phase, "status": st.status, "passes": len(st.passes)},
        as_json=args.json,
    )
    return 0


def cmd_next(tree: RoadmapTree, args: argparse.Namespace) -> int:
    ids = _filtered(tree, args)
    held = {h.phase_id for h in locks.list_held()}
    for pid in ids:
        if pid in held:
            continue
        st = state.load(pid)
        if st and st.status in ("completed", "skipped", "escalated"):
            continue
        if args.json:
            print(json.dumps({"phase_id": pid}, indent=2, sort_keys=True))
        else:
            print(pid)
        return 0
    if args.json:
        print(json.dumps({"phase_id": None}, indent=2, sort_keys=True))
    else:
        print("(no eligible phase)")
    return 4  # nothing to do — orchestration loop should stop


# ── Argument parser ───────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestrator", description=__doc__)
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Subparser-level --json so it works in either position.
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    common_filter = argparse.ArgumentParser(add_help=False)
    common_filter.add_argument("--include", default="", help="comma-separated phase ids to include")
    common_filter.add_argument("--exclude", default="", help="comma-separated phase ids to exclude")
    common_filter.add_argument(
        "--include-branches", action="store_true",
        help="also include non-leaf phases (default: leaves only)",
    )
    common_filter.add_argument(
        "--include-complete", action="store_true",
        help="do not skip phases whose checkboxes are all green",
    )

    s = sub.add_parser("list", parents=[json_parent], help="list every phase with checkbox status")
    s.add_argument("--leaves-only", action="store_true")

    sub.add_parser("plan", parents=[json_parent, common_filter], help="dry-run the include/exclude filter")
    sub.add_parser("next", parents=[json_parent, common_filter], help="print the next eligible un-claimed phase")

    s = sub.add_parser("slice", parents=[json_parent], help="print the ROADMAP slice for one phase")
    s.add_argument("phase")
    s.add_argument("--out", help="write to this file instead of stdout")

    s = sub.add_parser("claim", parents=[json_parent], help="acquire the per-phase lock")
    s.add_argument("phase")
    s.add_argument("--claimer", default=None, help="explicit claimer id (else auto-uuid)")

    s = sub.add_parser("release", parents=[json_parent], help="release the per-phase lock")
    s.add_argument("phase")
    s.add_argument("--force", action="store_true", help="ignore missing-lock error")

    sub.add_parser("locks", parents=[json_parent], help="list currently held locks")

    s = sub.add_parser("state", parents=[json_parent], help="show orchestrator state for a phase or all phases")
    s.add_argument("phase", nargs="?")

    s = sub.add_parser("advance", parents=[json_parent], help="record a review pass and/or transition status")
    s.add_argument("phase")
    s.add_argument("--status", choices=state.STATUSES)
    s.add_argument("--role", choices=state.ROLES)
    s.add_argument("--outcome", help="ok / needs-changes / blocked / escalated")
    s.add_argument("--model", default="")
    s.add_argument("--notes", default="")
    s.add_argument("--diff-summary", default="")
    s.add_argument("--last-error", default="")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    tree, source = parse_roadmap()

    dispatch = {
        "list": cmd_list,
        "plan": cmd_plan,
        "next": cmd_next,
        "claim": cmd_claim,
        "release": cmd_release,
        "locks": cmd_locks,
        "state": cmd_state,
        "advance": cmd_advance,
    }
    if args.cmd == "slice":
        return cmd_slice(tree, args, source)
    return dispatch[args.cmd](tree, args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
