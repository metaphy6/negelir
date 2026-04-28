#!/usr/bin/env python3
"""
`make scrape|bootstrap|train|train-model|backtest|ai.*`

All AI-container workloads. Each subcommand accepts an argparse-style
namespace built from the trailing argv, so the Makefile can pass
`--league`, `--weeks`, `--min-confidence`, `--markets` cleanly.

Env-var:
    MODE=demo  → `make ai.continuous` runs `main.py --demo --continuous`
    MODE=anything-else (or unset) runs `main.py --continuous`
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _common import REPO_ROOT, compose_exec, compose_run, dispatch, err, info, ok


# ── Helpers ───────────────────────────────────────────────────


def _require_league_data(league: str) -> None:
    cache = REPO_ROOT / "data" / f"{league}_real.json"
    if not cache.exists():
        err(
            f"Missing data/{league}_real.json. "
            f"Run 'make bootstrap LEAGUE={league}' first."
        )
        raise SystemExit(1)


def _ai(*args: str, league: str = None) -> None:
    """Run a one-shot `docker compose run --rm ai <args>`, exec'd through."""
    cmd = ["run", "--rm"]
    if league:
        cmd += ["-e", f"NEGELIR_DEFAULT_LEAGUE_ID={league}"]
    cmd += ["ai", *args]
    compose_exec(*cmd)


# ── Targets ───────────────────────────────────────────────────


def cmd_scrape(argv):
    p = argparse.ArgumentParser(prog="ai_commands.py scrape")
    p.add_argument("--league", default="super_lig")
    a = p.parse_args(argv)
    info(f"📥 Scraping real data for {a.league}…")
    _ai(
        "python", "-m", "scraper.real_data",
        "--league", a.league,
        "--output", f"/data/{a.league}_real.json",
        league=a.league,
    )


def cmd_bootstrap(argv):
    p = argparse.ArgumentParser(prog="ai_commands.py bootstrap")
    p.add_argument("--league", default="super_lig")
    p.add_argument("--min-matches", type=int, default=100)
    a = p.parse_args(argv)
    info(f"🚀 Bootstrapping real data for {a.league}…")
    compose_run(
        "run", "--rm",
        "-e", f"NEGELIR_DEFAULT_LEAGUE_ID={a.league}",
        "ai", "python", "-m", "scraper.real_data",
        "--league", a.league,
        "--output", f"/data/{a.league}_real.json",
    )
    compose_run(
        "run", "--rm",
        "-e", f"NEGELIR_DEFAULT_LEAGUE_ID={a.league}",
        "ai", "python", "-m", "proofreader.validator",
        "--input", f"/data/{a.league}_real.json",
        "--min-matches", str(a.min_matches),
    )
    ok(f"Bootstrap complete. {a.league} data is ready for training.")


def _train_with_mode(argv, mode: str):
    p = argparse.ArgumentParser()
    p.add_argument("--league", default="super_lig")
    a = p.parse_args(argv)
    _require_league_data(a.league)
    _ai(
        "python", "-m", "orchestrator.state_machine",
        "--mode", mode,
        "--league", a.league,
        league=a.league,
    )


def cmd_train_full(argv):  _train_with_mode(argv, "full-training")
def cmd_train_model(argv): _train_with_mode(argv, "model-only")


def cmd_ai_pipeline(_argv):
    _ai("python", "-m", "pipeline.runner")


def cmd_ai_demo(_argv):
    _ai("python", "-m", "pipeline.runner", "--demo")


def cmd_backtest(argv):
    p = argparse.ArgumentParser(prog="ai_commands.py backtest")
    p.add_argument("--weeks", type=int, default=3)
    p.add_argument("--min-confidence", type=float, default=None)
    p.add_argument("--markets", default=None)
    a = p.parse_args(argv)
    extra = []
    if a.min_confidence is not None:
        extra += ["--min-confidence", str(a.min_confidence)]
    if a.markets:
        extra += ["--markets", a.markets]
    _ai("python", "-m", "backtest.evaluator", "--weeks", str(a.weeks), *extra)


def cmd_swarm_backtest(argv):
    """Phase 5.5 — replay the live swarm chain over historical matches.

    Runs *outside* the ai container so the report files land directly
    under ``data/backtest/`` on the host. Exits non-zero if the swarm
    accuracy drops below ``cfg.backtest_swarm_floor_pct`` (CI gate).
    """
    p = argparse.ArgumentParser(prog="ai_commands.py swarm.backtest")
    p.add_argument("--weeks", type=int, default=int(os.environ.get("WEEKS", "3")))
    p.add_argument("--max-matches", type=int, default=200)
    a = p.parse_args(argv)
    import subprocess
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    rc = subprocess.call([
        "python3", os.path.join(here, "xops", "swarm_backtest.py"),
        "--weeks", str(a.weeks),
        "--max-matches", str(a.max_matches),
    ])
    if rc != 0:
        sys.exit(rc)


def cmd_ai_shell(_argv):
    _ai("bash")


def cmd_ai_continuous(_argv):
    mode = os.environ.get("MODE", "").strip().lower()
    if mode == "demo":
        _ai("python", "main.py", "--demo", "--continuous")
    else:
        _ai("python", "main.py", "--continuous")


COMMANDS = {
    # Daily verbs
    "scrape":      cmd_scrape,
    "bootstrap":   cmd_bootstrap,
    "train-full":  cmd_train_full,
    "train-model": cmd_train_model,
    "backtest":    cmd_backtest,
    "swarm.backtest": cmd_swarm_backtest,
    # ai.* domain
    "ai.pipeline":   cmd_ai_pipeline,
    "ai.demo":       cmd_ai_demo,
    "ai.shell":      cmd_ai_shell,
    "ai.continuous": cmd_ai_continuous,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="ai_commands.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
