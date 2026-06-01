"""Phase 10 §10.21.14 — make swarm.demo.nlp extension checks.

Verifies the new demo extension helper runs all required NLP scenarios and
that the command wiring executes base demo + extension checks in order.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _load_swarm_makefile_module():
    """Import xops/makefile/swarm.py with sibling _common resolution."""
    repo_root = Path(__file__).resolve().parents[2]
    makefile_dir = str(repo_root / "xops" / "makefile")
    if makefile_dir not in sys.path:
        sys.path.insert(0, makefile_dir)
    from xops.makefile import swarm as swarm_make

    return swarm_make


def test_swarm_demo_nlp_extensions_cover_phase10_21_14_paths() -> None:
    """Runs the extension helper and expects all scenario assertions to hold."""
    swarm_make = _load_swarm_makefile_module()
    swarm_make._run_phase10_nlp_demo_extensions()


def test_swarm_demo_nlp_command_runs_base_then_extensions(monkeypatch) -> None:
    """Command wiring: demo-nlp must execute base demo then extension checks."""
    swarm_make = _load_swarm_makefile_module()
    calls: list[str] = []

    def _fake_demo(_league: str) -> int:
        calls.append("base")
        return 0

    def _fake_extensions() -> None:
        calls.append("extensions")

    monkeypatch.setattr(swarm_make, "_run_demo", _fake_demo)
    monkeypatch.setattr(swarm_make, "_run_phase10_nlp_demo_extensions", _fake_extensions)

    rc = swarm_make.cmd_demo_nlp([])
    assert rc == 0
    assert calls == ["base", "extensions"]
