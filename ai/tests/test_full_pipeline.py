"""
Negelir — Phase 3 §3.8 integration test.

Exercises the full TrainingPipeline against cached real data and verifies
the report contract (schema, verdict, on-disk artifacts, manifest, history).

Skips gracefully when no league cache is available so the test suite stays
green on developer machines that have not run `make bootstrap`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _find_real_league() -> str | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "data",  # repo/data
        here.parent.parent / "data",         # ai/../data fallback
    ]
    for data_dir in candidates:
        if not data_dir.is_dir():
            continue
        for path in sorted(data_dir.glob("*_real.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            matches = payload if isinstance(payload, list) else payload.get("matches", [])
            if isinstance(matches, list) and len(matches) >= 100:
                return path.stem.removesuffix("_real")
    return None


@pytest.mark.integration
def test_full_training_pipeline_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: run all 8 stages, validate report contract."""
    league = _find_real_league()
    if league is None:
        pytest.skip(
            "No cached real-league data found in data/*_real.json (need ≥100 matches). "
            "Run `make bootstrap LEAGUE=tr_super_lig` to enable this test."
        )

    # Isolate output dirs so we never touch /data or repo data/reports.
    repo_data = Path(__file__).resolve().parent.parent.parent / "data"
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    # Mutate the live cfg so already-imported modules see the override.
    from common.config import cfg
    monkeypatch.setattr(cfg, "model_dir", str(tmp_path / "models"))
    monkeypatch.setattr(cfg, "data_dir", str(repo_data))
    monkeypatch.setattr(cfg, "report_dir", str(tmp_path / "reports"))

    from pipeline.training_pipeline import TrainingPipeline
    from pipeline.training_artifacts import STAGE_ORDER

    stages_seen: list[str] = []

    def _on_end(stage: str, payload: dict) -> None:
        stages_seen.append(stage)

    pipeline = TrainingPipeline(
        league_id=league,
        verification_window_weeks=2,
        report_dir=str(tmp_path / "reports"),
        on_stage_end=_on_end,
    )

    report = pipeline.run()

    # ── Report contract ────────────────────────────────────────
    assert report.schema_version == 1
    assert report.verdict in {"PASS", "FAIL"}
    assert report.run_id
    assert report.league_id == league
    assert report.txt_path and Path(report.txt_path).is_file()
    assert report.json_path and Path(report.json_path).is_file()

    # JSON report parses and carries all stage sections.
    with open(report.json_path, "r", encoding="utf-8") as f:
        json_report = json.load(f)
    assert json_report["schema_version"] == 1
    assert json_report["verdict"] == report.verdict
    for section in ("scrape", "validate", "split", "train", "verify"):
        assert section in json_report["stages"], f"missing stage section: {section}"

    # ── Per-stage artifact sidecars ────────────────────────────
    run_dir = Path(report.txt_path).parent
    for stage in STAGE_ORDER:
        if stage == "report":
            continue  # report stage is the report itself
        sidecar = run_dir / f"{stage}.json"
        assert sidecar.is_file(), f"missing sidecar: {sidecar}"
        with open(sidecar, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload.get("stage") == stage

    # ── Manifest ───────────────────────────────────────────────
    manifest_path = run_dir / "manifest.json"
    assert manifest_path.is_file()
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["run_id"] == report.run_id
    assert manifest["league_id"] == league
    assert manifest["verdict"] == report.verdict
    assert isinstance(manifest["stage_durations_ms"], dict)

    # ── history.jsonl trend record ─────────────────────────────
    history_path = tmp_path / "reports" / "history.jsonl"
    assert history_path.is_file()
    last_line = history_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    last = json.loads(last_line)
    assert last["run_id"] == report.run_id
    assert last["verdict"] == report.verdict

    # ── latest_<league>.{txt,json} copies ──────────────────────
    assert (tmp_path / "reports" / f"latest_{league}.txt").is_file()
    assert (tmp_path / "reports" / f"latest_{league}.json").is_file()

    # ── Stage callbacks fired for every stage that ran ────────
    # Allow `report` to be absent from callbacks — it isn't a `_run_stage` invocation.
    for stage in ("scrape", "validate", "split"):
        assert stage in stages_seen, f"on_stage_end missed: {stage}"

    # ── Verify stage produced real holdout metrics ─────────────
    # The whole point of holdout-first design is that we can score the model
    # on data it has never seen. If verify got 0 coverage, the pipeline is broken.
    verify_section = json_report["stages"]["verify"]
    assert verify_section["coverage"] > 0.0, (
        "Verify stage produced 0 holdout coverage — feature extraction probably "
        "received only the holdout slice instead of the full chronological history."
    )
    assert verify_section["overall_acc"] > 0.0
