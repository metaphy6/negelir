#!/usr/bin/env python3
"""`make backtest` — Phase 13.5 competition calibration backtest harness.

Targets:
    backtest            Run competition calibration backtest (single or --all).
    swarm.backtest      Phase 5.5 — replay swarm chain over historical matches.

This dispatcher handles the backtest command for per-competition calibration
validation. It supports:
  - Single competition: `make backtest COMPETITION=<id> [SEED=...] [WORKERS=...]`
  - All competitions: `make backtest --all` (respects cfg.backtest_concurrency_max)
  - Market backtest (legacy): `make backtest WEEKS=N [MARKETS=...] [MIN_CONFIDENCE=...]`

Output is written to data/backtest/competition/<id>/<asof>.json per §13.5.2.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ai"))

from xops.makefile._common import REPO_ROOT as _R, dispatch, err, info, ok, warn  # noqa: E402


def cmd_backtest(argv: List[str]) -> int:
    """
    Run competition calibration backtest (§13.5).
    
    Usage:
        ai_commands.py backtest --competition <id> [--seed <N>] [--workers <N>]
        ai_commands.py backtest --all [--workers <N>]
        ai_commands.py backtest --weeks <N> [--markets M1,M2] [--min-confidence X]
    
    Args:
        --competition <id>: Competition to backtest
        --seed <N>: Random seed for determinism (default: cfg.backtest_seed)
        --workers <N>: Parallel workers (default: 1)
        --all: Backtest all active competitions (respects cfg.backtest_concurrency_max)
        --weeks <N>: Legacy market backtest over N weeks
        --markets M1,M2: Legacy market list
        --min-confidence X: Legacy min confidence threshold
    
    Returns:
        0 on success, 1 on failure.
    """
    # Parse arguments
    competition = None
    seed = None
    workers = None
    all_competitions = False
    weeks = None
    markets = None
    min_confidence = None
    
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--competition" and i + 1 < len(argv):
            competition = argv[i + 1]
            i += 2
        elif arg == "--seed" and i + 1 < len(argv):
            seed = argv[i + 1]
            i += 2
        elif arg == "--workers" and i + 1 < len(argv):
            workers = argv[i + 1]
            i += 2
        elif arg == "--all":
            all_competitions = True
            i += 1
        elif arg == "--weeks" and i + 1 < len(argv):
            weeks = argv[i + 1]
            i += 2
        elif arg == "--markets" and i + 1 < len(argv):
            markets = argv[i + 1]
            i += 2
        elif arg == "--min-confidence" and i + 1 < len(argv):
            min_confidence = argv[i + 1]
            i += 2
        else:
            i += 1
    
    # Run in container via docker compose
    cmd: List[str] = [
        "docker", "compose",
        "--env-file", str(REPO_ROOT / "xops" / "env" / ".env"),
        "run", "--rm", "ai",
        "python", "-m", "backtest.competition_backtest",
    ]
    
    if competition:
        cmd.extend(["--competition", competition])
        if seed:
            cmd.extend(["--seed", seed])
        if workers:
            cmd.extend(["--workers", workers])
    elif all_competitions:
        cmd.append("--all")
        if workers:
            cmd.extend(["--workers", workers])
    elif weeks:
        # Legacy market backtest
        cmd = [
            "docker", "compose",
            "--env-file", str(REPO_ROOT / "xops" / "env" / ".env"),
            "run", "--rm", "ai",
            "python", "-m", "backtest.market_backtest",
            "--weeks", weeks,
        ]
        if markets:
            cmd.extend(["--markets", markets])
        if min_confidence:
            cmd.extend(["--min-confidence", min_confidence])
    else:
        err("usage: backtest [--competition <id> | --all | --weeks <N>]")
        return 1
    
    info(f"Running backtest: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)
        ok("Backtest completed successfully")
        return result.returncode
    except subprocess.CalledProcessError as exc:
        err(f"Backtest failed (exit {exc.returncode})")
        return exc.returncode or 1


def cmd_swarm_backtest(argv: List[str]) -> int:
    """
    Phase 5.5 — replay swarm chain over historical matches.
    
    Usage:
        ai_commands.py swarm.backtest --weeks <N>
    
    Args:
        --weeks <N>: Number of weeks to backtest (default: 3)
    
    Returns:
        0 on success, 1 on failure.
    """
    weeks = "3"  # default
    
    i = 0
    while i < len(argv):
        if argv[i] == "--weeks" and i + 1 < len(argv):
            weeks = argv[i + 1]
            i += 2
        else:
            i += 1
    
    cmd = [
        "docker", "compose",
        "--env-file", str(REPO_ROOT / "xops" / "env" / ".env"),
        "run", "--rm", "ai",
        "python", "-m", "backtest.swarm_backtest",
        "--weeks", weeks,
    ]
    
    info(f"Running swarm backtest: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)
        ok(f"Swarm backtest ({weeks} weeks) completed successfully")
        return result.returncode
    except subprocess.CalledProcessError as exc:
        err(f"Swarm backtest failed (exit {exc.returncode})")
        return exc.returncode or 1


COMMANDS = {
    "backtest": cmd_backtest,
    "swarm.backtest": cmd_swarm_backtest,
}


if __name__ == "__main__":
    exit_code = dispatch(sys.argv[1:], COMMANDS, script_name="ai_commands.py")
    sys.exit(exit_code)
