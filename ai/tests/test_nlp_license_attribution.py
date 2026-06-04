"""Test Phase 10 §10.23.12 — nlp.license-attribution generator."""

from __future__ import annotations

from pathlib import Path

from xops.makefile import nlp as nlp_mod


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_nlp_license_attribution_target_exists() -> None:
    from subprocess import run

    result = run(
        ["make", "help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nlp.license-attribution" in result.stdout


def test_nlp_license_attribution_report_generated_in_build(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    lexicon_dir = repo_root / "ai" / "nlp" / "lexicon"
    lexicon_dir.mkdir(parents=True)
    (lexicon_dir / "teams.tr-TR.yaml").write_text(
        "- canonical_id: galatasaray_sk\n  aliases:\n    - Galatasaray\n",
        encoding="utf-8",
    )

    monkeypatch = __import__("pytest").MonkeyPatch()
    try:
        monkeypatch.setattr(nlp_mod, "REPO_ROOT", repo_root)
        assert nlp_mod.cmd_nlp_license_attribution([]) == 0
    finally:
        monkeypatch.undo()

    output_path = repo_root / "data" / "nlp" / "build_reports" / "license_attribution.md"
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "# NLP License Attribution Report" in content
    assert "`ai/nlp/lexicon/teams.tr-TR.yaml`" in content
    assert "OpenFootball-derived alias content" in content
