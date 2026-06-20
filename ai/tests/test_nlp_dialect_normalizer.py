"""Phase 10 §10.32.4 regional/diaspora dialect normalization tests."""
from __future__ import annotations

from nlp.regional_dialect_normalize import (
    apply_regional_dialect_normalize,
    load_dialect_no_rewrite_canonicals,
    load_regional_dialect_rules,
)


class TestRegionalDialectRules:
    def test_rules_load_successfully(self) -> None:
        rules = load_regional_dialect_rules()
        assert any(rule.rule_id == "aegean_gidiyon" for rule in rules)
        assert any(rule.canonical == "futbolcu" for rule in rules)

    def test_allowlist_prevents_rewrite(self) -> None:
        canonicals = load_dialect_no_rewrite_canonicals()
        assert "galatasaray" in canonicals
        normalized, rewrites, alternatives = apply_regional_dialect_normalize("galatasaray", no_rewrite_canonicals=canonicals)
        assert normalized == "galatasaray"
        assert rewrites == ()
        assert alternatives == ()

    def test_audit_only_rewrite_preserves_no_alternative(self) -> None:
        normalized, rewrites, alternatives = apply_regional_dialect_normalize("haketiyon")
        assert normalized == "hak ediyorsun"
        assert rewrites and rewrites[0].audit_only is True
        assert alternatives == ()

    def test_non_audit_rewrite_emits_alternative(self) -> None:
        normalized, rewrites, alternatives = apply_regional_dialect_normalize("gidiyon")
        assert normalized == "gidiyorsun"
        assert rewrites and rewrites[0].audit_only is False
        assert alternatives == (("gidiyorsun", "gidiyon"),)


class TestNormalizePipelineRegionalDialect:
    def test_regional_dialect_step_runs_before_tokenization(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("gidiyon mac")
        assert "regional_dialect_normalize" in result.steps_run
        assert result.tokens[0] == "gidiyorsun"
        assert ("gidiyorsun", "gidiyon") in result.dialect_alternatives

    def test_regional_dialect_normalize_emits_pipeline_event(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("haketiyon mac")
        assert any(event.get("kind") == "dialect_normalized" for event in result.normalization_events)

    def test_dialect_rewrite_does_not_affect_allowlisted_canonical(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray")
        assert result.tokens == ("galatasaray",)
        assert result.dialect_alternatives == ()

    def test_audit_only_dialect_rewrite_emits_event(self) -> None:
        events: list[dict[str, object]] = []
        normalized, rewrites, alternatives = apply_regional_dialect_normalize(
            "haketiyon",
            event_sink=events.append,
        )

        assert normalized == "hak ediyorsun"
        assert rewrites and rewrites[0].audit_only is True
        assert alternatives == ()
        assert events == [
            {
                "kind": "dialect_normalized",
                "dialect_class": "aegean",
                "rule_id": "aegean_haketiyon",
                "original": "haketiyon",
                "canonical": "hak ediyorsun",
                "audit_only": True,
            }
        ]

    def test_nlp_dialect_class_min_recall_default(self) -> None:
        from ai.common.config import Config

        cfg = Config()
        assert cfg.nlp_dialect_class_min_recall == 0.8
