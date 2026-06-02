"""Proof tests for Phase 10 §10.32.3 postposition stack detection."""
from __future__ import annotations

import pytest

from nlp.normalize import normalize_input
from nlp.postposition_stack import (
    detect_postposition_stacks,
    load_postposition_stack_rules,
)


class TestPostpositionStackRuleLoading:
    def test_rules_load_successfully(self) -> None:
        rules = load_postposition_stack_rules()
        assert len(rules) == 12
        assert {rule.rule_id for rule in rules} == {
            "karşı_karşıya",
            "kadar_gibi",
            "göre_kadar",
            "göre_gibi",
            "kadar_nazaran",
            "ile_beraber",
            "ile_birlikte",
            "yle_beraber",
            "yle_birlikte",
            "için_karşı",
            "den_dolayı",
            "dolayı_yüzünden",
        }


@pytest.mark.parametrize(
    "text, expected_class, expected_role",
    [
        ("Galatasaray'a karşı karşıya", "vs_marker", "opponent"),
        ("Beşiktaş kadar gibi", "comparison_marker", None),
        ("Fenerbahçe ile beraber", "instrumental_marker", "companion"),
        ("Trabzon den dolayı", "causal_marker", None),
    ],
)
class TestNormalizeInputPostpositionStackDetection:
    def test_recognises_closed_stack(self, text: str, expected_class: str, expected_role: str | None) -> None:
        result = normalize_input(text)
        assert "postposition_stack" in result.steps_run
        assert len(result.postposition_stack_matches) == 1
        match = result.postposition_stack_matches[0]
        assert match.stack_class == expected_class
        assert match.role == expected_role

    def test_no_unknown_for_valid_stack(self, text: str, expected_class: str, expected_role: str | None) -> None:
        result = normalize_input(text)
        assert len(result.postposition_stack_unknowns) == 0


class TestPostpositionStackUnknownDetection:
    def test_unknown_marker_pair_does_not_modify_tokens(self) -> None:
        result = normalize_input("Galatasaray'a karşı gibi")
        assert result.tokens == ("galatasaray'a", "karşı", "gibi")
        assert len(result.postposition_stack_unknowns) == 1
        unknown = result.postposition_stack_unknowns[0]
        assert unknown.tokens == ("karşı", "gibi")

    def test_detect_postposition_stacks_returns_unknown_when_pair_is_unlisted(self) -> None:
        matches, unknowns = detect_postposition_stacks(["karşı", "gibi"])
        assert not matches
        assert len(unknowns) == 1
        assert unknowns[0].tokens == ("karşı", "gibi")
