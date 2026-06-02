"""Phase 10 §10.22.8 — Code-switch mixed-language handling proofs."""
from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
import yaml

from common.text.turkish import buffer_consonant, strip_proper_noun_suffix
from nlp.entity import EntityExtractor
from nlp.lexicon_loader import LexiconStore
from nlp.normalize import normalize_input

TEST_ROOT = Path(__file__).parent
NLP_ROOT = TEST_ROOT.parent / "nlp"
SWARM_NLP_ROOT = TEST_ROOT.parent.parent / "swarm" / "agents" / "nlp"


def test_nlp_code_switch_corpus_has_at_least_30_rows() -> None:
    """The code-switch fixture corpus covers at least 30 mixed-language entries."""
    corpus_path = TEST_ROOT / "fixtures" / "turkish_code_switch.yaml"
    assert corpus_path.is_file(), f"Code-switch corpus missing: {corpus_path}"

    data = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    entries = data.get("corpus", [])
    assert isinstance(entries, list), "Code-switch corpus must contain a list of corpus entries"
    assert len(entries) >= 30, f"Expected at least 30 code-switch rows, got {len(entries)}"


def _write_minimal_team_lexicon(lexdir: Path) -> None:
    lexicon_path = lexdir / "teams.tr.yaml"
    lexicon_path.write_text(
        """_meta:
  schema_version: 1
  lexicon_version: 1.0.0
  generated_at_utc: '2026-06-02T00:00:00Z'
  generator: test
entries:
- canonical_id: manchester_city
  names:
  - Manchester City
  - Manchester City FC
  aliases:
  - Man City
  - manchester city
""",
        encoding="utf-8",
    )


def test_nlp_code_switch_manchester_city_resolves_to_canonical() -> None:
    """English team names in mixed Turkish input resolve through the gazetteer."""
    with TemporaryDirectory() as tmpdir:
        lexdir = Path(tmpdir) / "lexicon"
        lexdir.mkdir(parents=True, exist_ok=True)
        _write_minimal_team_lexicon(lexdir)

        store = LexiconStore(lexdir)
        store.maybe_reload()
        assert store.is_loaded, "LexiconStore failed to load the NLP lexicon snapshot"

        normalized = normalize_input("Manchester City formdaymış")
        extractor = EntityExtractor(store=store)
        result = extractor.extract(normalized.tokens, raw_tokens=normalized.tokens)

        team_ids = [span.canonical_id for span in result.spans if span.kind == "team"]
        assert "manchester_city" in team_ids, (
            f"Expected Manchester City to resolve to manchester_city, got {team_ids}"
        )


def test_nlp_english_pluralized_galatasaraylar_recovers_to_galatasaray() -> None:
    """Turkish plural noise on a proper noun still recovers the base team name."""
    stem, suffix_class = strip_proper_noun_suffix("galatasaraylar", assume_proper=True)
    assert stem == "galatasaray"
    assert suffix_class == "plural"


def test_nlp_foreign_stem_buffer_override_for_manchester_city() -> None:
    """Foreign-stem overrides must select the correct buffer consonant for English names."""
    assert buffer_consonant("Manchester City", "dative") == "y"


def test_nlp_no_translation_dependency_in_nlp_sources() -> None:
    """NLP runtime sources must not import or call external translation packages."""
    violations: list[str] = []

    for root in (NLP_ROOT, SWARM_NLP_ROOT):
        for path in sorted(root.rglob("*.py")):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in {"googletrans", "deep_translator", "translation"}:
                            violations.append(f"{path}:{node.lineno} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module in {"googletrans", "deep_translator", "translation"}:
                        violations.append(f"{path}:{node.lineno} imports from {module}")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in {"translate", "translation"}:
                        violations.append(
                            f"{path}:{node.lineno} calls {node.func.id}()"
                        )

    assert violations == [], (
        "Translation dependency detected in NLP sources; remove external translation imports/calls. "
        + "; ".join(violations)
    )
