"""Phase 10 §10.22.8 — Code-switch mixed-language handling proofs."""
from __future__ import annotations

import ast
import datetime
import os
import time
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


def test_lexicon_reload_skips_true_file_touches(tmp_path: Path) -> None:
    """Touching a lexicon file without content changes should not trigger a swap."""
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir(parents=True, exist_ok=True)
    _write_minimal_team_lexicon(lexdir)

    times = [0.0]
    def clock_mono() -> float:
        return times[0]

    store = LexiconStore(
        lexdir,
        reload_s=0,
        max_rss_mb=0,
        clock_mono=clock_mono,
        clock_wall=lambda: times[0],
    )
    store.maybe_reload()
    assert store.is_loaded
    first_generation = store._generation_counter
    first_version = store.lexicon_version_id

    # Update the file timestamp without changing content.
    path = lexdir / "teams.tr.yaml"
    os.utime(path, (times[0] + 1.0, times[0] + 1.0))
    times[0] += 1.0

    alerts = store.maybe_reload()
    assert alerts == []
    assert store._generation_counter == first_generation
    assert store.lexicon_version_id == first_version


def test_lexicon_swap_at_utc_delays_activation(tmp_path: Path) -> None:
    """Lexicon snapshots with future swap_at_utc are validated but not activated."""
    lexdir = tmp_path / "lexicon"
    lexdir.mkdir(parents=True, exist_ok=True)
    _write_minimal_team_lexicon(lexdir)

    times = [0.0]
    def clock_mono() -> float:
        return times[0]

    def clock_wall() -> float:
        return times[0]

    store = LexiconStore(
        lexdir,
        reload_s=0,
        max_rss_mb=0,
        clock_mono=clock_mono,
        clock_wall=clock_wall,
    )
    store.maybe_reload()
    assert store.is_loaded
    base_generation = store._generation_counter

    path = lexdir / "teams.tr.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    meta = data.setdefault("_meta", {})
    assert isinstance(meta, dict)
    meta["swap_at_utc"] = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    alerts = store.maybe_reload()
    assert alerts == []
    assert store._generation_counter == base_generation

    time.sleep(1.1)
    alerts = store.maybe_reload()
    assert any(str(alert.get("kind")) == "lexicon_swap_late" for alert in alerts)
    assert store._generation_counter == base_generation + 1


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
