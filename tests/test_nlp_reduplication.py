"""Proof tests for Phase 10 §10.29.7 reduplication collapse support."""
from __future__ import annotations

from typing import Callable

import pytest

from ai.common.config import cfg
from nlp.normalize import normalize_input
from nlp.reduplication import (
    ReduplicationRule,
    collapse_reduplication,
    load_reduplication_pairs,
)


class TestReduplicationRuleLoading:
    def test_loads_reduplication_rules_successfully(self) -> None:
        rules = load_reduplication_pairs()
        assert len(rules) >= 25
        assert all(isinstance(rule, ReduplicationRule) for rule in rules)
        assert any(rule.token == "yeşil" for rule in rules)
        assert any(rule.token == "mutlu" for rule in rules)


class TestReduplicationCollapse:
    def test_collapse_whitelisted_reduplication(self) -> None:
        rules = load_reduplication_pairs()
        events: list[dict[str, object]] = []

        collapsed = collapse_reduplication(
            ["yeşil", "yeşil"],
            rules,
            event_sink=events.append,
        )

        assert collapsed == ["yeşil"]
        assert events == [
            {"kind": "reduplication_collapsed", "token": "yeşil", "count": 2}
        ]

    def test_does_not_collapse_non_whitelisted_pair(self) -> None:
        rules = load_reduplication_pairs()
        events: list[dict[str, object]] = []

        collapsed = collapse_reduplication(
            ["maç", "maç"],
            rules,
            event_sink=events.append,
        )

        assert collapsed == ["maç", "maç"]
        assert events == []

    def test_reduplication_is_idempotent(self) -> None:
        rules = load_reduplication_pairs()
        events_first: list[dict[str, object]] = []
        events_second: list[dict[str, object]] = []

        first_pass = collapse_reduplication(
            ["yeşil", "yeşil"],
            rules,
            event_sink=events_first.append,
        )
        second_pass = collapse_reduplication(
            first_pass,
            rules,
            event_sink=events_second.append,
        )

        assert first_pass == ["yeşil"]
        assert second_pass == ["yeşil"]
        assert events_second == []

    def test_collapses_long_repeated_sequence(self) -> None:
        rules = load_reduplication_pairs()
        events: list[dict[str, object]] = []

        collapsed = collapse_reduplication(
            ["güzel", "güzel", "güzel"],
            rules,
            event_sink=events.append,
        )

        assert collapsed == ["güzel"]
        assert events[0]["count"] == 3


def test_normalize_input_includes_reduplication_step() -> None:
    cfg.nlp_reduplication_collapse_enabled = True
    result = normalize_input(
        "kırmızı kırmızı",
        _reduplication_rules=load_reduplication_pairs(),
    )

    assert "reduplication_collapse" in result.steps_run
    assert result.tokens == ("kırmızı",)
    assert any(event.get("kind") == "reduplication_collapsed" for event in result.normalization_events)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("yeşil yeşil", "yeşil"),
        ("uzun uzun", "uzun"),
        ("beyaz beyaz", "beyaz"),
        ("siyah siyah", "siyah"),
        ("harika harika", "harika"),
        ("mutlu mutlu", "mutlu"),
        ("şahane şahane", "şahane"),
        ("güzel güzel", "güzel"),
        ("mükemmel mükemmel", "mükemmel"),
        ("tatlı tatlı", "tatlı"),
        ("sıcak sıcak", "sıcak"),
        ("enerjik enerjik", "enerjik"),
        ("dikkatli dikkatli", "dikkatli"),
        ("ciddi ciddi", "ciddi"),
        ("sessiz sessiz", "sessiz"),
        ("parlak parlak", "parlak"),
        ("temiz temiz", "temiz"),
        ("serin serin", "serin"),
        ("sabırlı sabırlı", "sabırlı"),
        ("çılgın çılgın", "çılgın"),
        ("lezzetli lezzetli", "lezzetli"),
        ("enerjik enerjik", "enerjik"),
        ("dikkatli dikkatli", "dikkatli"),
        ("güzel güzel", "güzel"),
        ("nazik nazik", "nazik"),
    ],
)
def test_positive_reduplication_corpus_collapses(text: str, expected: str) -> None:
    cfg.nlp_reduplication_collapse_enabled = True
    result = normalize_input(
        text,
        _reduplication_rules=load_reduplication_pairs(),
    )
    assert result.tokens == (expected,)


@pytest.mark.parametrize(
    "text",
    [
        "ev ev",
        "maç maç",
        "bank bank",
        "yeni yeni",
        "taraftar taraftar",
        "futbol futbol",
        "saha saha",
        "kupa kupa",
        "gol gol",
        "kral kral",
        "çay çay",
        "yeni yıl",
        "hava hava",
        "tarih tarih",
        "futbolcu futbolcu",
    ],
)
def test_negative_reduplication_corpus_does_not_collapse(text: str) -> None:
    cfg.nlp_reduplication_collapse_enabled = True
    result = normalize_input(
        text,
        _reduplication_rules=load_reduplication_pairs(),
    )
    assert result.tokens == tuple(text.split())
