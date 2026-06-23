#!/usr/bin/env python3
"""`make hooks.*` — install / uninstall shared git hooks from xops/hooks/.

Shared hooks live in xops/hooks/ and are installed as symlinks (or copies on
Windows) into .git/hooks/.  Running `make hooks.install` is required once per
fresh clone so that the commit-msg Conventional Commits gate is active.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile._common import dispatch, info, ok, warn  # noqa: E402

HOOKS_SRC = REPO_ROOT / "xops" / "hooks"
HOOKS_DST = REPO_ROOT / ".git" / "hooks"

# Hooks provided by this repo (relative to xops/hooks/).
MANAGED_HOOKS = ("commit-msg",)


def _ensure_executable(path: Path) -> None:
    """Add owner-execute bit to *path* (no-op on Windows)."""
    if os.name == "nt":
        return
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def cmd_install(_argv: List[str]) -> int:
    if not HOOKS_DST.is_dir():
        warn(f"{HOOKS_DST} not found — is this a git repository?")
        return 1

    installed: list[str] = []
    skipped: list[str] = []

    for hook_name in MANAGED_HOOKS:
        src = HOOKS_SRC / hook_name
        dst = HOOKS_DST / hook_name

        if not src.exists():
            warn(f"source hook not found: {src}")
            continue

        if dst.exists() or dst.is_symlink():
            # Overwrite if it's already our symlink or stale
            if dst.is_symlink() and dst.resolve() == src.resolve():
                skipped.append(hook_name)
                continue
            dst.unlink()

        try:
            if os.name == "nt":
                shutil.copy2(src, dst)
            else:
                dst.symlink_to(src)
            _ensure_executable(dst)
            installed.append(hook_name)
        except OSError as exc:
            warn(f"could not install {hook_name}: {exc}")
            return 1

    for name in installed:
        ok(f"installed hook: {name}")
    for name in skipped:
        info(f"already installed: {name}")

    if not installed and not skipped:
        warn("no hooks were installed")
        return 1

    return 0


def cmd_uninstall(_argv: List[str]) -> int:
    removed: list[str] = []

    for hook_name in MANAGED_HOOKS:
        src = HOOKS_SRC / hook_name
        dst = HOOKS_DST / hook_name

        if not dst.exists() and not dst.is_symlink():
            info(f"not installed: {hook_name}")
            continue

        # Only remove hooks we own (symlink pointing to our src, or a copy).
        if dst.is_symlink() and dst.resolve() != src.resolve():
            warn(f"skipping {hook_name} — not managed by this repo")
            continue

        dst.unlink()
        removed.append(hook_name)

    for name in removed:
        ok(f"removed hook: {name}")

    return 0


def cmd_status(_argv: List[str]) -> int:
    for hook_name in MANAGED_HOOKS:
        src = HOOKS_SRC / hook_name
        dst = HOOKS_DST / hook_name

        if not dst.exists() and not dst.is_symlink():
            print(f"  {hook_name:<20} NOT installed")
        elif dst.is_symlink() and dst.resolve() == src.resolve():
            print(f"  {hook_name:<20} installed (symlink → xops/hooks/{hook_name})")
        elif dst.is_symlink():
            print(f"  {hook_name:<20} installed (symlink → EXTERNAL: {dst.resolve()})")
        else:
            print(f"  {hook_name:<20} installed (copy)")
    return 0


COMMANDS = {
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "status": cmd_status,
}


def main(argv: List[str]) -> int:
    return dispatch(argv, COMMANDS, script_name="hooks.py")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
