from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "xops" / "makefile"))
sys.path.insert(0, str(REPO_ROOT))

from xops.makefile import swarm  # noqa: E402


def test_swarm_demo_nlp_full_extension_checks() -> None:
    swarm._run_phase10_nlp_demo_full_extensions()
