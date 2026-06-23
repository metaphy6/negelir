"""Phase 22.10 — Versioning finalization and 1.0.0 promotions proof tests."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = REPO_ROOT / "xops" / "versioning" / "chart.json"


def test_22_10_ai_chart_key_eol() -> None:
    """Verify ai chart key is marked eol."""
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    ai_component = chart["components"].get("ai", {})
    assert "eol_marker" in ai_component, "ai component should have eol_marker"
    assert ai_component.get("eol_marker"), "ai eol_marker should not be empty"


def test_22_10_source_watcher_alias_eol() -> None:
    """Verify source_watcher alias is marked eol."""
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    sw_component = chart["components"].get("source_watcher", {})
    assert "aliased_to" in sw_component, "source_watcher should have aliased_to"
    assert sw_component.get("aliased_to") == "datasource_watcher"
    assert "eol_marker" in sw_component, "source_watcher should have eol_marker"


def test_22_10_each_1_0_0_component_has_public_api_doc() -> None:
    """Verify each component reaching 1.0.0 has PUBLIC_API.md."""
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    components_to_check = [
        ("datasource_scraper", REPO_ROOT / "scraper"),
        ("datasource_watcher", REPO_ROOT / "ai" / "datasource" / "watcher"),
        ("datasource_refresher", REPO_ROOT / "ai" / "datasource" / "refresher"),
        ("swarm", REPO_ROOT / "swarm"),
        ("common", REPO_ROOT / "common"),
    ]
    
    for comp_key, comp_path in components_to_check:
        comp_data = chart["components"].get(comp_key, {})
        if comp_data.get("version", "").startswith("1."):
            public_api = comp_path / "PUBLIC_API.md"
            assert public_api.exists(), f"{comp_key} at v1.0.0+ should have {public_api}"


def test_22_10_each_1_0_0_component_has_compat_tests() -> None:
    """Verify each component reaching 1.0.0 has test_public_api_compat.py."""
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    components_to_check = [
        ("datasource_scraper", REPO_ROOT / "scraper" / "tests"),
        ("datasource_watcher", REPO_ROOT / "ai" / "datasource" / "watcher" / "tests"),
        ("datasource_refresher", REPO_ROOT / "ai" / "datasource" / "refresher" / "tests"),
        ("swarm", REPO_ROOT / "swarm" / "tests"),
        ("common", REPO_ROOT / "common" / "tests"),
    ]
    
    for comp_key, test_path in components_to_check:
        comp_data = chart["components"].get(comp_key, {})
        if comp_data.get("version", "").startswith("1."):
            compat_test = test_path / "test_public_api_compat.py"
            assert compat_test.exists(), f"{comp_key} at v1.0.0+ should have {compat_test}"


def test_22_10_version_bump_list_uses_real_chart_keys() -> None:
    """Verify the 1.0.0 bumps used real chart keys (not aliases or non-existent)."""
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    # Check that the bumped components exist and are at 1.0.0
    bumped_components = {
        "datasource_scraper": "1.0.0",
        "datasource_refresher": "1.0.0",
        "datasource_watcher": "1.0.0",
        "swarm": "1.0.0",
        "common": "1.0.0",
    }
    
    for key, expected_version in bumped_components.items():
        assert key in chart["components"], f"component {key} should exist"
        actual_version = chart["components"][key]["version"]
        assert actual_version == expected_version, \
            f"component {key} should be {expected_version}, got {actual_version}"


def test_22_10_patcher_gitops_bumps_deferred_to_phase17() -> None:
    """Verify datasource_patcher and datasource_gitops are still 0.x.x (deferred)."""
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    patcher_version = chart["components"].get("datasource_patcher", {}).get("version", "")
    gitops_version = chart["components"].get("datasource_gitops", {}).get("version", "")
    
    assert patcher_version.startswith("0."), \
        f"datasource_patcher should be 0.x.x (deferred to Phase 17), got {patcher_version}"
    assert gitops_version.startswith("0."), \
        f"datasource_gitops should be 0.x.x (deferred to Phase 17), got {gitops_version}"


def test_22_10_version_chart_round_trips() -> None:
    """Verify chart.json is valid after all bumps."""
    # This just checks that the chart can be loaded and is structurally sound
    with CHART_PATH.open() as fh:
        chart = json.load(fh)
    
    # Basic structure validation
    assert "schema" in chart
    assert "project" in chart
    assert "components" in chart
    assert "changelog" in chart
    
    # Verify all components have required fields
    for name, data in chart["components"].items():
        assert "version" in data, f"component {name} missing version"
        assert "description" in data, f"component {name} missing description"
        assert "last_changed" in data, f"component {name} missing last_changed"
