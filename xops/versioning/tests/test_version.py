"""Tests for ``xops.versioning.version`` (stdlib-only, runs under pytest)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from xops.versioning import version as v  # noqa: E402


# ── Pure helpers ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,level,expected",
    [
        ("1.0.0", "patch", "1.0.1"),
        ("1.0.0", "minor", "1.1.0"),
        ("1.0.0", "major", "2.0.0"),
        ("2.3.4", "patch", "2.3.5"),
        ("2.3.4", "minor", "2.4.0"),
        ("2.3.4", "major", "3.0.0"),
    ],
)
def test_bump_semver(current: str, level: str, expected: str) -> None:
    assert v.bump_semver(current, level) == expected


@pytest.mark.parametrize("bad", ["", "1", "1.2", "1.2.x", "v1.2.3", "1.2.3.4"])
def test_parse_semver_rejects_garbage(bad: str) -> None:
    with pytest.raises(v.VersionChartError):
        v.parse_semver(bad)


def test_bump_semver_rejects_unknown_level() -> None:
    with pytest.raises(v.VersionChartError):
        v.bump_semver("1.0.0", "bogus")


# ── Chart I/O ─────────────────────────────────────────────────


def test_chart_loads_and_validates() -> None:
    chart = v.load_chart()
    assert chart["project"]["name"] == "negelir"
    assert "ai" in chart["components"]
    assert "source_watcher" in chart["components"]
    assert "infra_mock" in chart["components"]


def test_chart_is_canonical(tmp_path: Path) -> None:
    """The on-disk chart must round-trip through save_chart byte-for-byte.

    Guards against hand edits that change indentation, key order, or
    trailing newline. Forces every change to go through the CLI.
    """
    original = v.CHART_PATH.read_text(encoding="utf-8")
    chart = json.loads(original)
    rewritten = json.dumps(chart, indent=2, ensure_ascii=False) + "\n"
    assert original == rewritten, (
        "chart.json is not in canonical form. Run "
        "`python3 xops/versioning/version.py validate` after editing, "
        "or better: only edit through `make version.bump`."
    )


# ── Bump operation ────────────────────────────────────────────


def _fresh_chart() -> dict:
    """A pristine in-memory chart so tests don't depend on live versions."""
    return {
        "schema": 1,
        "project": {
            "name": "negelir",
            "version": "1.0.0",
            "build": 0,
            "last_changed": "2030-01-01T00:00:00+00:00",
        },
        "components": {
            "ai": {"version": "1.0.0", "description": "Python AI", "last_changed": "2030-01-01T00:00:00+00:00"},
            "server": {"version": "1.0.0", "description": "Go server", "last_changed": "2030-01-01T00:00:00+00:00"},
            "xops": {"version": "1.0.0", "description": "Repo automation", "last_changed": "2030-01-01T00:00:00+00:00"},
            "docs": {"version": "1.0.0", "description": "Docs", "last_changed": "2030-01-01T00:00:00+00:00"},
            "infra_mock": {"version": "1.0.0", "description": "Mock infra", "last_changed": "2030-01-01T00:00:00+00:00"},
            "source_watcher": {"version": "1.0.0", "description": "Source watcher", "last_changed": "2030-01-01T00:00:00+00:00"},
        },
        "changelog": [],
    }


def test_bump_component_increments_build_and_stamps(tmp_path: Path) -> None:
    chart = _fresh_chart()
    starting_build = chart["project"]["build"]
    entry = v.bump_component(
        chart, component="ai", level="patch", note="unit test", timestamp="2030-01-01T00:00:00+00:00"
    )
    assert entry["from"] == "1.0.0"
    assert entry["to"] == "1.0.1"
    assert chart["components"]["ai"]["version"] == "1.0.1"
    assert chart["components"]["ai"]["last_changed"] == "2030-01-01T00:00:00+00:00"
    assert chart["project"]["build"] == starting_build + 1
    assert chart["changelog"][-1] == entry


def test_bump_project_resets_build(tmp_path: Path) -> None:
    chart = _fresh_chart()
    v.bump_component(chart, "ai", "patch")
    v.bump_component(chart, "xops", "patch")
    assert chart["project"]["build"] >= 2
    v.bump_component(chart, "project", "minor")
    assert chart["project"]["build"] == 0
    assert chart["project"]["version"] == "1.1.0"


def test_bump_unknown_component_raises() -> None:
    chart = _fresh_chart()
    with pytest.raises(v.VersionChartError):
        v.bump_component(chart, "nonexistent", "patch")


def test_save_then_load_round_trip(tmp_path: Path) -> None:
    chart = _fresh_chart()
    v.bump_component(chart, "ai", "minor", note="round trip test")
    out = tmp_path / "chart.json"
    v.save_chart(chart, path=out)
    reloaded = v.load_chart(path=out)
    assert reloaded["components"]["ai"]["version"] == "1.1.0"
    assert reloaded["changelog"][-1]["note"] == "round trip test"
