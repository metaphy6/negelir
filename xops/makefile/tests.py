#!/usr/bin/env python3
"""`make test|test-ai|test-integration` — pytest inside the AI container."""

from __future__ import annotations

import sys

from _common import REPO_ROOT, compose_exec, dispatch, run

WORKSPACE_DIR = "/workspace"
TEST_PYTHONPATH = f"{WORKSPACE_DIR}/ai"
SWARM_DISPATCHER = REPO_ROOT / "xops" / "makefile" / "swarm.py"


def _pytest(*targets: str) -> None:
    compose_exec(
        "run", "--build", "--rm",
        "-v", f"{REPO_ROOT}:{WORKSPACE_DIR}",
        "-w", WORKSPACE_DIR,
        "-e", f"PYTHONPATH={TEST_PYTHONPATH}",
        "ai", "python", "-m", "pytest", *targets, "-v",
    )


def _swarm_demo(*, live: bool = False) -> None:
    cmd = [sys.executable, str(SWARM_DISPATCHER), "demo-live" if live else "demo"]
    run(cmd)


def cmd_test(_argv):
    """Full suite: AI, xops (incl. mock manifest contract), swarm agents, versioning."""
    _pytest(
        "ai/tests",
        "ai/swarm",
        "xops/mock/tests",
        "xops/versioning/tests",
    )


def cmd_test_ai(_argv):
    _swarm_demo()
    _pytest("ai/tests")


def cmd_test_integration(_argv):
    _swarm_demo(live=True)
    _pytest("ai/tests/test_full_pipeline.py", "-s")


def cmd_test_fast(_argv):
    """Fast loop: full suite minus `slow`-marked tests (parity sweeps,
    full-pipeline end-to-end). Intended for the inner dev loop;
    `make test` and CI still run everything."""
    _pytest(
        "ai/tests",
        "ai/swarm",
        "xops/mock/tests",
        "xops/versioning/tests",
        "-m", "not slow",
    )


COMMANDS = {
    "test": cmd_test,
    "test-ai": cmd_test_ai,
    "test-integration": cmd_test_integration,
    "test-fast": cmd_test_fast,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="tests.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
