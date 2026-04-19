#!/usr/bin/env python3
"""`make clean|clean-all|clean-data` — destructive housekeeping."""

from __future__ import annotations

import sys
import time

from _common import REPO_ROOT, compose_run, dispatch, info, ok, warn


def cmd_clean(_argv):
    compose_run("down", "--rmi", "local", "--remove-orphans")
    return 0


def cmd_clean_all(_argv):
    warn("This removes ALL data including database volumes. Press Ctrl+C within 3s to cancel.")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        warn("Aborted.")
        return 130
    compose_run("down", "-v", "--rmi", "local", "--remove-orphans")
    return 0


def cmd_clean_data(_argv):
    info("Removing data/ contents…")
    data_dir = REPO_ROOT / "data"
    if not data_dir.exists():
        return 0
    keep = {".gitkeep"}
    for entry in data_dir.iterdir():
        if entry.name in keep:
            continue
        try:
            if entry.is_dir():
                # Recursive remove via shutil — keep stdlib only
                import shutil
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as exc:
            warn(f"Could not remove {entry}: {exc}")
    ok("data/ cleaned")
    return 0


COMMANDS = {
    "clean": cmd_clean,
    "clean-all": cmd_clean_all,
    "clean-data": cmd_clean_data,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="cleanup.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
