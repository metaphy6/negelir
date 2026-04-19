#!/usr/bin/env python3
"""
`make scrape|bootstrap|train*|ai-pipeline|ai-train|ai-demo|ai-backtest*|
       ai-tqu-test|ai-shell|ai-continuous|ai-continuous-demo`

All AI-container workloads. Each subcommand accepts an argparse-style
namespace built from the trailing argv, so the Makefile can pass
`--league`, `--weeks`, `--min-confidence`, `--markets` cleanly.
"""

from __future__ import annotations

import argparse
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
    # Stage 1: scrape (subprocess so we can chain validate after)
    compose_run(
        "run", "--rm",
        "-e", f"NEGELIR_DEFAULT_LEAGUE_ID={a.league}",
        "ai", "python", "-m", "scraper.real_data",
        "--league", a.league,
        "--output", f"/data/{a.league}_real.json",
    )
    # Stage 2: validate
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


def cmd_ai_train(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--league", default="super_lig")
    a = p.parse_args(argv)
    _require_league_data(a.league)
    _ai("python", "-m", "model.trainer", league=a.league)


def cmd_ai_demo(_argv):
    _ai("python", "-m", "pipeline.runner", "--demo")


def cmd_ai_backtest(argv):
    p = argparse.ArgumentParser(prog="ai_commands.py ai-backtest")
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


def cmd_ai_tqu_test(_argv):
    _ai("python", "-m", "tqu.classifier")


def cmd_ai_shell(_argv):
    _ai("bash")


def cmd_ai_continuous(_argv):
    _ai("python", "main.py", "--continuous")


def cmd_ai_continuous_demo(_argv):
    _ai("python", "main.py", "--demo", "--continuous")


COMMANDS = {
    "scrape": cmd_scrape,
    "bootstrap": cmd_bootstrap,
    "train-full": cmd_train_full,
    "train-model": cmd_train_model,
    "ai-pipeline": cmd_ai_pipeline,
    "ai-train": cmd_ai_train,
    "ai-demo": cmd_ai_demo,
    "ai-backtest": cmd_ai_backtest,
    "ai-tqu-test": cmd_ai_tqu_test,
    "ai-shell": cmd_ai_shell,
    "ai-continuous": cmd_ai_continuous,
    "ai-continuous-demo": cmd_ai_continuous_demo,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="ai_commands.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
