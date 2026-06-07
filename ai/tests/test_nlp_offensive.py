"""Proof tests for Phase 10 §10.22.9 offensive-language handling."""
from __future__ import annotations

import yaml

from common import telemetry
from common.config import Config


def test_nlp_offensive_table_loaded_with_three_classes() -> None:
    from nlp.offensive import load_offensive_table

    table = load_offensive_table()
    assert table["saçmalık"] == "mild"
    assert table["oç"] == "slur"
    assert table["öldüreceğim"] == "severe_threat"
    assert {"mild", "slur", "severe_threat"}.issubset(set(table.values()))


def test_obfuscated_slur_patterns_load_from_yaml() -> None:
    from nlp.offensive import load_offensive_obfuscated_patterns

    patterns = load_offensive_obfuscated_patterns()
    assert any(p.pattern == "o.ç" for p in patterns)
    assert any(p.canonical == "amk" for p in patterns)


def test_obfuscated_slur_routes_through_offensive_gate(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    result = normalize_input("o.ç maç")

    assert "oç" not in result.tokens
    assert "<STRIPPED>" in result.tokens


def test_obfuscated_slur_detected_after_confusables_fold(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    result = normalize_input("Gal\u0430tasaray o.ç maç")

    assert "o.ç" not in result.tokens
    assert "<STRIPPED>" in result.tokens


def test_obfuscated_slur_table_min_coverage_per_canonical() -> None:
    from nlp.offensive import load_offensive_obfuscated_patterns

    patterns = load_offensive_obfuscated_patterns()
    counts: dict[str, int] = {}
    for pattern in patterns:
        counts[pattern.canonical] = counts.get(pattern.canonical, 0) + 1

    assert all(count >= 2 for count in counts.values()), (
        "Each canonical slur must have at least two obfuscation patterns."
    )


def test_obfuscated_slur_negation_event_emitted(tmp_path: "Path") -> None:
    from nlp.offensive import replace_obfuscated_slurs

    payload = {
        "_meta": {
            "schema_version": 1,
            "generated_at_utc": "2026-01-01T00:00:00Z",
            "generator": "test",
        },
        "entries": [
            {
                "pattern": "o.ç",
                "canonical": "amk",
                "context_negation_regex": "3 üst",
            }
        ],
    }
    path = tmp_path / "offensive_obfuscated.tr.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    events: list[dict[str, object]] = []
    result = replace_obfuscated_slurs(
        "o.ç 3 üst",
        path=path,
        event_sink=events.append,
    )

    assert result == "o.ç 3 üst"
    assert events == [{"kind": "obfuscated_slur_negated", "pattern_id": "offensive_obfuscated.tr.yaml:0"}]


def test_obfuscated_slur_context_negation_vetoes_match(tmp_path: "Path") -> None:
    from nlp.offensive import replace_obfuscated_slurs

    payload = {
        "_meta": {
            "schema_version": 1,
            "generated_at_utc": "2026-01-01T00:00:00Z",
            "generator": "test",
        },
        "entries": [
            {
                "pattern": "o.ç",
                "canonical": "amk",
                "context_negation_regex": "3 üst",
            }
        ],
    }
    path = tmp_path / "offensive_obfuscated.tr.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = replace_obfuscated_slurs("o.ç 3 üst", path=path)

    assert result == "o.ç 3 üst"


def test_obfuscated_slur_patterns_do_not_cross_word_boundaries() -> None:
    from nlp.offensive import replace_obfuscated_slurs

    assert replace_obfuscated_slurs("bence besiktas berabere mi") == "bence besiktas berabere mi"
    assert replace_obfuscated_slurs("https://example.com/fb maç") == "https://example.com/fb maç"


def test_nlp_input_repair_metrics_emitted_for_confusables_and_slur(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    records: list[tuple[str, str, int]] = []

    class DummySink:
        def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
            records.append(("repair", repair_class, count))

        def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
            records.append(("density", str(repairs), token_count))

        def record_nlp_politeness_class(self, politeness_class: str) -> None:
            records.append(("politeness", politeness_class))

    monkeypatch.setattr(telemetry, "_sink", DummySink())

    result = normalize_input("Gal\u0430tasaray oç maç")

    assert any(call[1] == "confusables_folded" for call in records)
    assert any(call[1] == "slur_stripped" for call in records)
    assert any(call[0] == "density" for call in records)
    assert any(token in {"oç", "amk"} for token in result.slurs_stripped)


def test_nlp_ascii_restored_metrics_recorded(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    records: list[tuple[str, str, int]] = []

    class DummySink:
        def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
            records.append(("repair", repair_class, count))

        def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
            records.append(("density", str(repairs), token_count))

        def record_nlp_politeness_class(self, politeness_class: str) -> None:
            records.append(("politeness", politeness_class))

    monkeypatch.setattr(telemetry, "_sink", DummySink())

    def mock_diacritic_restore(text: str) -> str:
        return text.replace("mac", "maç")

    normalize_input("galatasaray mac", _diacritic_restore=mock_diacritic_restore)

    assert any(call[1] == "ascii_restored" for call in records)
    assert any(call[0] == "density" for call in records)


def test_nlp_repair_counters_increment_per_class(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    records: list[tuple[str, str, int]] = []

    class DummySink:
        def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
            records.append(("repair", repair_class, count))

        def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
            records.append(("density", str(repairs), token_count))

        def record_nlp_politeness_class(self, politeness_class: str) -> None:
            records.append(("politeness", politeness_class))

    monkeypatch.setattr(telemetry, "_sink", DummySink())

    normalize_input("galatasarayda oç maç")

    repair_classes = {call[1] for call in records if call[0] == "repair"}
    assert {"particle_repaired_de_da", "slur_stripped"}.issubset(repair_classes)
    assert any(call[0] == "density" for call in records)


def test_nlp_repair_density_metric_bounded_in_clean_slice(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    records: list[tuple[str, str, int]] = []

    class DummySink:
        def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
            records.append(("repair", repair_class, count))

        def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
            records.append(("density", repairs, token_count))

        def record_nlp_politeness_class(self, politeness_class: str) -> None:
            records.append(("politeness", politeness_class))

    monkeypatch.setattr(telemetry, "_sink", DummySink())

    normalize_input("galatasaray maç")

    assert all(call[0] != "repair" for call in records)
    assert any(call == ("density", 0, 2) for call in records)


def test_nlp_slur_token_stripped_before_classifier() -> None:
    from nlp.dialect_normalize import _DialectNormalizer

    normalizer = _DialectNormalizer()
    result = normalizer.normalize(["oç", "maç"])

    assert "<STRIPPED>" in result.tokens
    assert "oç" in result.slurs_stripped
    assert "maç" in result.tokens


def test_nlp_mild_offensive_does_not_strip() -> None:
    from nlp.offensive import strip_offensive_slurs

    tokens, stripped = strip_offensive_slurs(["saçmalık", "maç"])
    assert tokens == ["saçmalık", "maç"]
    assert stripped == []


def test_nlp_offensive_table_matches_english_football_abuse() -> None:
    from nlp.offensive import contains_offensive_phrase

    assert contains_offensive_phrase("They choked in the 90th minute")
    assert contains_offensive_phrase("The team bottled it")
    assert contains_offensive_phrase("We parked the bus in the last half")


def test_nlp_proofreader_blocks_slur_in_rendered_answer() -> None:
    from nlp.proofreader import proofread_answer

    cfg = Config()
    result = proofread_answer(
        "Bu cevapta oç kelimesi var.",
        intent="meta.help",
        citation_sha256_expected=None,
        cfg=cfg,
    )

    assert result.passed is False
    assert result.block_reason == "forbidden_phrase"

