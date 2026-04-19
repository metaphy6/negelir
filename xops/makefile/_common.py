"""Shared helpers for xops.makefile dispatchers."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, NoReturn, Optional, Sequence

# ── Paths ─────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Compose binary (allow override for podman-compose etc.) ───

_COMPOSE_OVERRIDE = os.environ.get("NEGELIR_COMPOSE")
if _COMPOSE_OVERRIDE:
    COMPOSE: List[str] = shlex.split(_COMPOSE_OVERRIDE)
else:
    COMPOSE = ["docker", "compose"]

# ── Pretty logger (emoji-prefixed; no third-party deps) ───────


def info(msg: str) -> None:
    print(f"ℹ️  {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"✅ {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"⚠️  {msg}", flush=True)


def err(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr, flush=True)


def step(msg: str) -> None:
    print(f"→ {msg}", flush=True)


# ── Process runners ───────────────────────────────────────────


def run(
    cmd: Sequence[str],
    *,
    check: bool = True,
    cwd: Optional[Path] = None,
    capture: bool = False,
    env: Optional[dict] = None,
) -> subprocess.CompletedProcess:
    """Run `cmd` as a subprocess (waits for completion)."""
    return subprocess.run(
        list(cmd),
        cwd=str(cwd or REPO_ROOT),
        check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=capture,
        env=env,
    )


def compose_run(
    *args: str, check: bool = True, env: Optional[dict] = None
) -> subprocess.CompletedProcess:
    """`docker compose <args>` as a subprocess. Use for orchestration."""
    return run([*COMPOSE, *args], check=check, env=env)


def exec_(cmd: Sequence[str]) -> NoReturn:
    """
    Replace the current process with `cmd`. Use for interactive commands
    (shells, log tailers) so the TTY, signals, and exit code pass through
    cleanly without an extra Python layer.
    """
    os.chdir(str(REPO_ROOT))
    args = list(cmd)
    binary = shutil.which(args[0]) or args[0]
    os.execvp(binary, args)  # noqa: S606 — intentional


def compose_exec(*args: str) -> NoReturn:
    """Like `compose_run` but `execvp`s into docker compose."""
    exec_([*COMPOSE, *args])


# ── Tiny dispatch helper ──────────────────────────────────────


def dispatch(
    argv: Sequence[str],
    commands: dict,
    *,
    script_name: str = "<script>",
) -> int:
    """
    Dispatch `argv[0]` to `commands[argv[0]]()`. Returns the exit code.
    Prints a usage message and returns 64 on bad input.
    """
    argv = list(argv)
    if len(argv) < 1 or argv[0] not in commands:
        names = "|".join(sorted(commands))
        err(f"usage: {script_name} {{{names}}} [args...]")
        return 64
    name = argv[0]
    try:
        result = commands[name](argv[1:])
        return int(result or 0)
    except subprocess.CalledProcessError as exc:
        err(f"command failed (exit {exc.returncode}): {' '.join(exc.cmd)}")
        return exc.returncode or 1
    except KeyboardInterrupt:
        warn("interrupted.")
        return 130
