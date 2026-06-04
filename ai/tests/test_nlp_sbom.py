"""Phase 10 §10.23.12 SBOM emission helper.

This verifies `make nlp.sbom` exists and that the new command
writes a valid CycloneDX SBOM file containing direct/transitive
Python package metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from xops.makefile import nlp as nlp_mod


class _FakeDist:
    def __init__(
        self,
        name: str,
        version: str,
        requires: list[str],
        license_name: str = "MIT",
        summary: str = "Fake distribution for tests",
    ) -> None:
        self._metadata = {
            "Name": name,
            "License": license_name,
            "Summary": summary,
        }
        self.version = version
        self._requires = requires

    @property
    def metadata(self) -> dict[str, str]:
        return self._metadata

    @property
    def requires(self) -> list[str]:
        return self._requires


def test_nlp_sbom_target_exists() -> None:
    result = subprocess.run(
        ["make", "help"],
        cwd=".",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nlp.sbom" in result.stdout


def test_nlp_sbom_writes_cyclonedx_json(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    requirements_path = repo_root / "ai" / "requirements.txt"
    lexicon_dir = repo_root / "ai" / "nlp" / "lexicon"
    requirements_path.parent.mkdir(parents=True)
    lexicon_dir.mkdir(parents=True)
    requirements_path.write_text("requests==2.31.0\n", encoding="utf-8")
    (lexicon_dir / "sample.yaml").write_text("team: Galatasaray\n", encoding="utf-8")

    def fake_distributions() -> list[_FakeDist]:
        return [
            _FakeDist("requests", "2.31.0", ["urllib3>=1.26"]),
            _FakeDist("urllib3", "1.26.0", []),
        ]

    monkeypatch.setattr(nlp_mod, "REPO_ROOT", repo_root)
    monkeypatch.setattr(nlp_mod.importlib.metadata, "distributions", fake_distributions)

    assert nlp_mod.cmd_nlp_sbom([]) == 0
    output_path = repo_root / "data" / "nlp" / "sbom.json"
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["bomFormat"] == "CycloneDX"
    assert payload["specVersion"] == "1.5"
    assert any(comp.get("name") == "requests" for comp in payload["components"])
    assert any(comp.get("name") == "urllib3" for comp in payload["components"])
    assert any(comp.get("name") == "ai/nlp/lexicon/sample.yaml" for comp in payload["components"])
