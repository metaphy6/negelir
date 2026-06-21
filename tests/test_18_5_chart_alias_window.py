"""Phase 18.5 §18.5 — Proof tests for rolling alias window (Bullet 1, ledger #8)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from xops.versioning import version as v


def _make_test_chart(with_alias: bool = True) -> dict:
    """Factory for test charts."""
    chart = {
        "schema": 1,
        "project": {"name": "test", "version": "1.0.0", "build": 0, "released": None},
        "components": {
            "datasource_watcher": {
                "version": "1.0.0",
                "description": "Watcher component.",
                "last_changed": "2026-06-15T00:00:00+00:00",
            },
        },
        "changelog": [],
    }
    
    if with_alias:
        chart["components"]["source_watcher"] = {
            "version": "3.0.3",
            "description": "Source-watcher AI agent (deprecated; use datasource_watcher).",
            "last_changed": "2026-05-21T00:00:00+00:00",
            "aliased_to": "datasource_watcher",
            "alias_eol_days": 90,
            "alias_note": "Renamed in Phase 22 R1; alias window 90 days from activation.",
        }
    
    return chart


class TestChartRenameCreatesAliasWindow:
    """Bullet 1, Test 1: Alias window is created and stored in chart."""
    
    def test_chart_rename_creates_alias_window(self) -> None:
        """Chart validates with alias metadata present."""
        chart = _make_test_chart(with_alias=True)
        
        # Should not raise
        v.validate_chart(chart)
        
        # Verify alias metadata is present
        assert "source_watcher" in chart["components"]
        assert chart["components"]["source_watcher"].get("aliased_to") == "datasource_watcher"
        assert chart["components"]["source_watcher"].get("alias_eol_days") == 90
    
    def test_chart_validates_without_alias(self) -> None:
        """Chart validates with or without alias metadata."""
        chart = _make_test_chart(with_alias=False)
        v.validate_chart(chart)
        assert "source_watcher" not in chart["components"]


class TestAliasResolvesInTrackShow:
    """Bullet 1, Test 2: Alias resolves via resolve_component_alias()."""
    
    def test_alias_resolves_to_canonical(self) -> None:
        """resolve_component_alias translates alias to canonical key."""
        chart = _make_test_chart(with_alias=True)
        
        canonical, is_alias = v.resolve_component_alias(chart, "source_watcher")
        assert canonical == "datasource_watcher"
        assert is_alias is True
    
    def test_canonical_key_returns_identity(self) -> None:
        """Canonical key returns itself with is_alias=False."""
        chart = _make_test_chart(with_alias=True)
        
        canonical, is_alias = v.resolve_component_alias(chart, "datasource_watcher")
        assert canonical == "datasource_watcher"
        assert is_alias is False
    
    def test_missing_key_raises_error(self) -> None:
        """Missing key raises VersionChartError."""
        chart = _make_test_chart(with_alias=True)
        
        with pytest.raises(v.VersionChartError, match="not found"):
            v.resolve_component_alias(chart, "nonexistent")
    
    def test_broken_alias_target_raises_error(self) -> None:
        """Alias pointing to non-existent target raises error."""
        chart = _make_test_chart(with_alias=True)
        chart["components"]["source_watcher"]["aliased_to"] = "unknown_target"
        
        with pytest.raises(v.VersionChartError, match="unknown target"):
            v.resolve_component_alias(chart, "source_watcher")


class TestAliasEolTranslatesInCli:
    """Bullet 1, Test 3: cmd_show marks aliases as deprecated."""
    
    def test_cmd_show_marks_deprecated_alias(self, capsys) -> None:
        """cmd_show output includes deprecation marker for aliases."""
        chart = _make_test_chart(with_alias=True)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            chart_path = Path(tmpdir) / "chart.json"
            chart_path.write_text(json.dumps(chart), encoding="utf-8")
            
            # Monkey-patch CHART_PATH
            original_path = v.CHART_PATH
            try:
                v.CHART_PATH = chart_path
                
                # Create minimal args
                class Args:
                    changelog = 0
                
                result = v.cmd_show(Args())
                assert result == 0
                
                captured = capsys.readouterr()
                # Should mark source_watcher as deprecated
                assert "⚠️  (deprecated)" in captured.out or "deprecated" in captured.out.lower()
            finally:
                v.CHART_PATH = original_path
