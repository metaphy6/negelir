#!/usr/bin/env python3
"""
`make clean|clean.all` — destructive housekeeping.

Env-var:
    DATA=1   → `make clean.all` also wipes ./data (json caches, model files).
"""

from __future__ import annotations

import os
import shutil
import sys
import time

from _common import REPO_ROOT, compose_run, dispatch, info, ok, warn


def _wipe_data() -> None:
    info("Removing data/ contents…")
    data_dir = REPO_ROOT / "data"
    if not data_dir.exists():
        return
    keep = {".gitkeep"}
    for entry in data_dir.iterdir():
        if entry.name in keep:
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except OSError as exc:
            warn(f"Could not remove {entry}: {exc}")
    ok("data/ cleaned")


def cmd_clean(_argv):
    compose_run("down", "--rmi", "local", "--remove-orphans")
    return 0


def cmd_clean_all(_argv):
    wipe_data = os.environ.get("DATA", "").strip() not in ("", "0", "false", "False")
    target = "all data including database volumes" + (" AND ./data" if wipe_data else "")
    warn(f"This removes {target}. Press Ctrl+C within 3s to cancel.")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        warn("Aborted.")
        return 130
    compose_run("down", "-v", "--rmi", "local", "--remove-orphans")
    if wipe_data:
        _wipe_data()
    return 0


COMMANDS = {
    "clean": cmd_clean,
    "clean.all": cmd_clean_all,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="cleanup.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
