"""Proof tests for Phase 10 §10.22.9 offensive-language handling."""
from __future__ import annotations

from common import telemetry
from common.config import Config


def test_nlp_offensive_table_loaded_with_three_classes() -> None:
    from nlp.offensive import load_offensive_table

    table = load_offensive_table()
    assert table["saçmalık"] == "mild"
    assert table["oç"] == "slur"
    assert table["öldüreceğim"] == "severe_threat"
    assert {"mild", "slur", "severe_threat"}.issubset(set(table.values()))


def test_nlp_input_repair_metrics_emitted_for_confusables_and_slur(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    records: list[tuple[str, str, int]] = []

    class DummySink:
        def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
            records.append(("repair", repair_class, count))

        def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
            records.append(("density", str(repairs), token_count))

    monkeypatch.setattr(telemetry, "_sink", DummySink())

    result = normalize_input("Gal\u0430tasaray oç maç")

    assert any(call[1] == "confusables_folded" for call in records)
    assert any(call[1] == "slur_stripped" for call in records)
    assert any(call[0] == "density" for call in records)
    assert "oç" in result.slurs_stripped


def test_nlp_ascii_restored_metrics_recorded(monkeypatch) -> None:
    from nlp.normalize import normalize_input

    records: list[tuple[str, str, int]] = []

    class DummySink:
        def record_nlp_input_repair(self, repair_class: str, count: int = 1) -> None:
            records.append(("repair", repair_class, count))

        def record_nlp_input_repair_density(self, repairs: int, token_count: int) -> None:
            records.append(("density", str(repairs), token_count))

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

