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

# ── Project env file (single source of truth) ─────────────────
# Every `docker compose` invocation made through compose_run/compose_exec
# is auto-prefixed with `--env-file xops/env/.env` so Compose's own
# variable substitution (ports, healthchecks, the POSTGRES_PASSWORD
# guard) sees the same values the containers do via env_file:.
# Override with NEGELIR_ENV_FILE=/abs/path/to/other.env if needed.

_ENV_FILE_OVERRIDE = os.environ.get("NEGELIR_ENV_FILE")
ENV_FILE: Path = (
    Path(_ENV_FILE_OVERRIDE).resolve()
    if _ENV_FILE_OVERRIDE
    else REPO_ROOT / "xops" / "env" / ".env"
)
ENV_EXAMPLE: Path = REPO_ROOT / "xops" / "env" / ".env.example"


def _compose_with_env() -> List[str]:
    """COMPOSE base + --env-file (only if the file actually exists).

    The file existence check lets `make env` run before any other target
    without Docker complaining about a missing env-file.
    """
    if ENV_FILE.is_file():
        return [*COMPOSE, "--env-file", str(ENV_FILE)]
    return list(COMPOSE)

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
    """`docker compose --env-file xops/env/.env <args>` as a subprocess."""
    return run([*_compose_with_env(), *args], check=check, env=env)


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
    exec_([*_compose_with_env(), *args])


# ── sudo helpers ──────────────────────────────────────────────


def is_root() -> bool:
    """True when the current process already has root privileges (POSIX only)."""
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0


def sudo_run(
    cmd: Sequence[str],
    *,
    reason: str = "",
    check: bool = True,
    stdin: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run ``cmd`` under ``sudo`` only when the current EUID is not root.

    On Windows this raises ``RuntimeError`` — the Make targets that call
    this print a clearer message before getting here. ``stdin`` (if
    provided) is piped into the command (used for ``sudo tee`` writes).

    Per AGENTS.md §10, only the mock-stack provisioning targets
    (``hosts.install``, ``hosts.uninstall``, ``mock.trust``,
    ``mock.untrust``) are permitted callers.
    """
    if os.name == "nt":
        raise RuntimeError(
            "sudo_run is POSIX-only. On Windows run Make from an elevated shell."
        )
    if is_root():
        full = list(cmd)
    else:
        if reason:
            info(f"sudo: {reason}")
        full = ["sudo", *cmd]
    return subprocess.run(
        full,
        check=check,
        input=stdin,
        text=stdin is not None,
        cwd=str(REPO_ROOT),
    )


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
