#!/usr/bin/env python3
"""
nlp_eval_diff_present.py — Phase 10 §10.18 CI gate: eval-diff report required.

Enforces: any PR touching `ai/swarm/agents/nlp/**` or `ai/nlp/**` must include
a markdown diff report generated via `make nlp.eval-diff BASELINE=<sha>`.

The report is expected at `nlp_eval_diff_report.md` in the repo root.

Exit codes:
    0 = report present (or no NLP files touched)
    1 = report missing when required
    2 = bad CLI invocation
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_FILE = "nlp_eval_diff_report.md"


def main(argv: list[str] | None = None) -> int:
    """Check if nlp_eval_diff_report.md is present when NLP files are touched."""
    parser = argparse.ArgumentParser(
        description="CI gate: require eval-diff report for NLP changes"
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base ref to compare against (default: origin/main)",
    )
    args = parser.parse_args(argv)

    # Get changed files
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", args.base, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = result.stdout.strip().split("\n")
    except subprocess.CalledProcessError as e:
        print(f"Error: failed to get changed files: {e}", file=sys.stderr)
        return 2

    # Check if any NLP files were touched
    nlp_patterns = [
        "ai/swarm/agents/nlp/",
        "ai/nlp/",
    ]
    nlp_files_touched = any(
        any(pattern in f for pattern in nlp_patterns)
        for f in changed_files
        if f
    )

    if not nlp_files_touched:
        print("nlp_eval_diff_present: no NLP files touched — gate skipped")
        return 0

    # Check if report exists
    report_path = REPO_ROOT / REPORT_FILE
    if not report_path.exists():
        print(
            f"Error: {REPORT_FILE} missing. "
            "Run `make nlp.eval-diff BASELINE=<sha>` and commit the report.",
            file=sys.stderr,
        )
        return 1

    print(f"nlp_eval_diff_present: {REPORT_FILE} present — gate PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
