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
        "xops/nlp/tests",
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
        "xops/nlp/tests",
        "xops/versioning/tests",
        "-m", "not slow",
    )


def cmd_ci_fast(_argv):
    """Phase 12 §12.13 — Fast lane (per-push): unit+property+contract+lint (<5min).
    
    Runs: unit tests, property-based tests, contract tests, fuzz.smoke, lint gates.
    Blocks: every push (gate to merge).
    """
    _pytest(
        "ai/tests",
        "-m", "unit or property or contract",
        "-q",
    )


def cmd_ci_pr(_argv):
    """Phase 12 §12.13 — PR lane (<20min): integration+adversarial+regression+diff-coverage.
    
    Runs: integration tests, adversarial corpus tests, regression/golden tests,
    in-process chaos, diff-coverage gate.
    Blocks: PR merge.
    """
    _pytest(
        "ai/tests",
        "-m", "integration or adversarial or regression_golden",
        "-q",
    )


def cmd_ci_nightly(_argv):
    """Phase 12 §12.13 — Nightly lane (<90min, self-hosted): fuzz+load+chaos+mutation+soak.
    
    Runs: coverage-guided fuzzing, load tests, realistic chaos scenarios,
    mutation testing (Tier-1), nightly soaks.
    Blocks: release gate.
    """
    _pytest(
        "ai/tests",
        "-m", "fuzz or load or chaos or mutation or soak_nightly",
        "-q",
    )


def cmd_ci_weekly(_argv):
    """Phase 12 §12.13 — Weekly lane (24h, self-hosted): full soaks+GPU heat+DR drills.
    
    Runs: 24h endurance soaks, GPU thermal soaks, full DR→restore→verify drills.
    Blocks: release gate.
    """
    _pytest(
        "ai/tests",
        "-m", "soak_weekly or soak_gpu_heat or dr_drill",
        "-q",
    )


COMMANDS = {
    "test": cmd_test,
    "test-ai": cmd_test_ai,
    "test-integration": cmd_test_integration,
    "test-fast": cmd_test_fast,
    "ci-fast": cmd_ci_fast,
    "ci-pr": cmd_ci_pr,
    "ci-nightly": cmd_ci_nightly,
    "ci-weekly": cmd_ci_weekly,
}


def main(argv=None):
    return dispatch(
        argv if argv is not None else sys.argv[1:],
        COMMANDS,
        script_name="tests.py",
    )


if __name__ == "__main__":
    raise SystemExit(main())
