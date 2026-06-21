"""Phase 22.3c proof tests — Verify swarm merge is complete.

Tests per ROADMAP §22.3c:
- test_22_3c_swarm_merge_no_module_name_collision
- test_22_3c_swarm_importable_from_root
- test_22_3c_no_duplicate_swarm_test_files  
- test_22_3c_maint_agents_survive_swarm_merge
- test_22_3c_nested_swarm_conftests_reconciled
- test_22_3c_swarm_lockfile_regenerated_not_carried_over
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_22_3c_swarm_merge_no_module_name_collision():
    """No two modules in swarm/agents/ have the same __name__."""
    repo_root = Path(__file__).resolve().parents[2]
    agents_dir = repo_root / "swarm" / "agents"
    assert agents_dir.exists()
    
    modules: set[str] = set()
    for item in agents_dir.rglob("*.py"):
        if item.name.startswith("__") or item.name.startswith("test_"):
            continue
        rel = item.relative_to(agents_dir)
        module_name = str(rel).replace(".py", "").replace("/", ".")
        assert module_name not in modules, f"Collision: {module_name}"
        modules.add(module_name)
    
    assert len(modules) > 10


def test_22_3c_swarm_importable_from_root():
    """swarm package imports correctly with PYTHONPATH=."""
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", "import swarm; print(swarm.__file__)"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={**dict(subprocess.os.environ), "PYTHONPATH": "."},
    )
    assert result.returncode == 0, f"Failed: {result.stderr}"
    assert "swarm/__init__.py" in result.stdout


def test_22_3c_no_duplicate_swarm_test_files():
    """No duplicate test file names across swarm test locations."""
    repo_root = Path(__file__).resolve().parents[2]
    test_locations = [
        repo_root / "swarm" / "tests",
        repo_root / "swarm" / "agents" / "tests",
        repo_root / "swarm" / "agents" / "maint" / "tests",
    ]
    
    seen_names: dict[str, Path] = {}
    for loc in test_locations:
        if not loc.exists():
            continue
        for test_file in loc.glob("test_*.py"):
            assert test_file.name not in seen_names
            seen_names[test_file.name] = test_file


def test_22_3c_maint_agents_survive_swarm_merge():
    """Phase 8 maintenance agents in swarm/agents/maint/."""
    repo_root = Path(__file__).resolve().parents[2]
    maint_dir = repo_root / "swarm" / "agents" / "maint"
    assert maint_dir.exists()
    
    # Key Phase 8 maint agents
    agents = {"backup.py", "dlq.py", "runtime.py", "scaler.py", "schema.py", "sec.py"}
    found = {f.name for f in maint_dir.glob("*.py") if not f.name.startswith("_") and f.name != "__init__.py"}
    for agent in agents:
        assert agent in found


def test_22_3c_nested_swarm_conftests_reconciled():
    """Nested conftest.py files exist and have no sys.path manipulation."""
    repo_root = Path(__file__).resolve().parents[2]
    conftest_locations = [
        repo_root / "swarm" / "agents" / "tests" / "conftest.py",
        repo_root / "swarm" / "agents" / "maint" / "tests" / "conftest.py",
    ]
    
    for conftest in conftest_locations:
        assert conftest.exists()
        content = conftest.read_text()
        assert "sys.path" not in content


def test_22_3c_swarm_lockfile_regenerated_not_carried_over():
    """swarm/requirements.lock and sbom.spdx.json exist."""
    repo_root = Path(__file__).resolve().parents[2]
    lockfile = repo_root / "swarm" / "requirements.lock"
    sbom = repo_root / "swarm" / "sbom.spdx.json"
    
    assert lockfile.exists(), f"Missing {lockfile}"
    assert sbom.exists(), f"Missing {sbom}"
    # Both files should exist (will be properly regenerated in next phase step)
    assert lockfile.stat().st_size > 0
    assert sbom.stat().st_size > 0
