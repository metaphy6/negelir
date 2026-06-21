from __future__ import annotations

import shutil
import zoneinfo
from pathlib import Path

import pytest
import yaml


def test_config_has_nlp_zoneinfo_dir() -> None:
    from common.config import Config

    cfg = Config()

    assert hasattr(cfg, "nlp_zoneinfo_dir")
    assert cfg.nlp_zoneinfo_dir == ""


def test_nlp_zoneinfo_dir_in_env_example() -> None:
    env_example = Path("xops/env/.env.example").read_text(encoding="utf-8")
    assert "NEGELIR_NLP_ZONEINFO_DIR" in env_example


def test_chart_json_has_zoneinfo_file_pin() -> None:
    chart = Path("xops/versioning/chart.json")
    data = chart.read_text(encoding="utf-8")
    assert "zoneinfo_file" in data

    import json

    parsed = json.loads(data)
    entry = parsed["compatibility"]["data_files"]["zoneinfo_file"]
    assert entry["path"] == "zoneinfo/Europe/Istanbul"
    assert entry["sha256"] != ""


def test_zoneinfo_dir_validation_matches_chart_sha(tmp_path: Path) -> None:
    from common.config import Config

    candidate = None
    for path in zoneinfo.TZPATH:
        candidate_path = Path(path) / "Europe" / "Istanbul"
        if candidate_path.exists():
            candidate = candidate_path
            break
    assert candidate is not None, "System zoneinfo path must contain Europe/Istanbul"

    dest = tmp_path / "Europe"
    dest.mkdir(parents=True)
    shutil.copy2(candidate, dest / "Istanbul")

    cfg = Config()
    cfg.nlp_zoneinfo_dir = str(tmp_path)
    issues = cfg.validate()

    assert not issues, f"Zoneinfo validation failed: {issues}"


def test_nlp_zoneinfo_sha_pinned_at_boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common.config import Config

    candidate = None
    for path in zoneinfo.TZPATH:
        candidate_path = Path(path) / "Europe" / "Istanbul"
        if candidate_path.exists():
            candidate = candidate_path
            break
    assert candidate is not None, "System zoneinfo path must contain Europe/Istanbul"

    dest = tmp_path / "Europe"
    dest.mkdir(parents=True)
    shutil.copy2(candidate, dest / "Istanbul")

    cfg = Config()
    cfg.nlp_zoneinfo_dir = str(tmp_path)
    issues = cfg.validate()

    assert not issues, f"Zoneinfo SHA validation failed: {issues}"


def test_tr_format_clock_uses_custom_zoneinfo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common.config import cfg
    from common.text.tr_format import tr_format_clock

    candidate = None
    for path in zoneinfo.TZPATH:
        candidate_path = Path(path) / "America" / "New_York"
        if candidate_path.exists():
            candidate = candidate_path
            break
    assert candidate is not None, "System zoneinfo path must contain America/New_York"

    dest = tmp_path / "America"
    dest.mkdir(parents=True)
    shutil.copy2(candidate, dest / "New_York")
    monkeypatch.setattr(cfg, "nlp_zoneinfo_dir", str(tmp_path))
    monkeypatch.setattr(zoneinfo, "TZPATH", ())

    expected = tr_format_clock("2026-04-27T18:30:00Z", tz="America/New_York")
    assert expected == "14:30"


def test_locale_render_tz_table_has_tr_tr_default() -> None:
    path = Path("ai/nlp/lang_tr/locale_render_tz.tr.yaml")
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    assert data["entries"] == [
        {"locale": "tr-TR", "render_timezone": "Europe/Istanbul"}
    ]
