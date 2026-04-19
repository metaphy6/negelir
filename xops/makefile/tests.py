#!/usr/bin/env python3
"""`make test|test-ai|test-integration` — pytest inside the AI container."""

from __future__ import annotations

import sys

from _common import REPO_ROOT, compose_exec, dispatch

WORKSPACE_DIR = "/workspace"
TEST_PYTHONPATH = f"{WORKSPACE_DIR}/ai"


def _pytest(*targets: str) -> None:
    compose_exec(
        "run", "--rm",
        "-v", f"{REPO_ROOT}:{WORKSPACE_DIR}",
        "-w", WORKSPACE_DIR,
        "-e", f"PYTHONPATH={TEST_PYTHONPATH}",
        "ai", "python", "-m", "pytest", *targets, "-v",
    )


def cmd_test(_argv):             _pytest("ai/tests")
def cmd_test_ai(_argv):          _pytest("ai/tests")
def cmd_test_integration(_argv): _pytest("ai/tests/test_full_pipeline.py", "-s")


COMMANDS = {
    "test": cmd_test,
    "test-ai": cmd_test_ai,
    "test-integration": cmd_test_integration,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="tests.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
