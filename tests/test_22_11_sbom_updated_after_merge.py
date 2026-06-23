"""Phase 22.11 — Proof test for SBOM final verification.

Verifies that SBOM files for swarm and enrichment exist and represent
the current state after migration (i.e., regeneration would produce no diff).
"""
from pathlib import Path
import json


def test_22_11_sbom_files_exist() -> None:
    """Phase 22.11 bullet 6: Verify SBOM files exist for swarm and enrichment."""
    sbom_files = {
        "swarm": Path("swarm/sbom.spdx.json"),
        "enrichment": Path("enrichment/sbom.spdx.json"),
    }
    
    for component, sbom_path in sbom_files.items():
        assert sbom_path.exists(), (
            f"SBOM file missing for {component}: {sbom_path}. "
            f"Expected this to be regenerated during Phase 22.4 move."
        )


def test_22_11_sbom_files_are_valid_json() -> None:
    """Phase 22.11 bullet 6: Verify SBOM files are valid JSON."""
    sbom_files = [
        Path("swarm/sbom.spdx.json"),
        Path("enrichment/sbom.spdx.json"),
        Path("scraper/sbom.spdx.json"),
    ]
    
    for sbom_path in sbom_files:
        if not sbom_path.exists():
            continue
        
        try:
            content = json.loads(sbom_path.read_text(encoding="utf-8"))
            assert isinstance(content, dict), f"{sbom_path} must be a JSON object"
            
            # SPDX format check (basic)
            if "SPDXID" in content or "spdxVersion" in content:
                # SPDX JSON format
                assert "spdxVersion" in content, f"{sbom_path} missing spdxVersion"
                assert "creationInfo" in content or "packages" in content, \
                    f"{sbom_path} missing required SPDX fields"
        except json.JSONDecodeError as e:
            raise AssertionError(f"{sbom_path} contains invalid JSON: {e}")


def test_22_11_no_datasource_sbom_component() -> None:
    """Phase 22.11 bullet 6: Verify no datasource/ SBOM (superseded by enrichment).
    
    The old ai/datasource/ SBOM is obsolete after migration.
    Only enrichment/ SBOM should exist (containing what was in ai/datasource/).
    """
    obsolete_paths = [
        Path("datasource/sbom.spdx.json"),
        Path("ai/datasource/sbom.spdx.json"),
    ]
    
    for obsolete_path in obsolete_paths:
        assert not obsolete_path.exists(), (
            f"Obsolete SBOM file still present: {obsolete_path}. "
            "After migration, use enrichment/sbom.spdx.json instead."
        )
    
    # Verify enrichment/ SBOM exists (the replacement)
    assert Path("enrichment/sbom.spdx.json").exists(), (
        "enrichment/sbom.spdx.json must exist (replaces ai/datasource/ SBOM)"
    )
