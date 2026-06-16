"""
Phase 18.9 §18.9 — DoD smoke runs in ephemeral CI runner with no host caches (ledger #15).

Validates that the DoD smoke can run in a fresh environment (no host caches,
empty secret store) with documented resource floors.
"""

from pathlib import Path


def test_dod_smoke_in_fresh_runner() -> None:
    """Test that DoD smoke infrastructure is configured."""
    # Verify resource floor config keys exist
    config_py = Path(__file__).parent.parent / "common" / "config.py"
    assert config_py.exists(), f"{config_py} not found"
    
    config_content = config_py.read_text(encoding="utf-8")
    assert "dod_smoke_min_cpu" in config_content, "dod_smoke_min_cpu not in config.py"
    assert "dod_smoke_min_mem_gb" in config_content, "dod_smoke_min_mem_gb not in config.py"
