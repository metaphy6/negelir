"""
Phase 18.9 §18.9 — DoD smoke resource floor documented in config (ledger #15).

Validates that cfg.dod_smoke_min_cpu (default 4) and cfg.dod_smoke_min_mem_gb
(default 8) are documented and enforced.
"""


from common.config import cfg


def test_dod_smoke_resource_floor_documented() -> None:
    """Test that resource floor config keys exist and have correct defaults."""
    assert hasattr(cfg, "dod_smoke_min_cpu"), "cfg.dod_smoke_min_cpu not found"
    assert hasattr(cfg, "dod_smoke_min_mem_gb"), "cfg.dod_smoke_min_mem_gb not found"
    
    # Verify defaults per ledger #15
    assert cfg.dod_smoke_min_cpu == 4, f"Expected dod_smoke_min_cpu=4, got {cfg.dod_smoke_min_cpu}"
    assert cfg.dod_smoke_min_mem_gb == 8, f"Expected dod_smoke_min_mem_gb=8, got {cfg.dod_smoke_min_mem_gb}"
    
    # Both should be integers
    assert isinstance(cfg.dod_smoke_min_cpu, int), "dod_smoke_min_cpu should be int"
    assert isinstance(cfg.dod_smoke_min_mem_gb, int), "dod_smoke_min_mem_gb should be int"
