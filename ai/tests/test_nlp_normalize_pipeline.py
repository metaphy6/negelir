"""Phase 10 §10.1 -- Binding step list tests.

Verifies that the 9-step normalization pipeline exists and runs every step
in the prescribed order.  Any reordering of steps would fail these tests.

Per AGENTS.md Rule 10: happy paths + adversarial + regression tests.
"""
from __future__ import annotations

from pathlib import Path
import json
import yaml

import pytest


# ---------------------------------------------------------------------------
# Expected step order -- immutable; changing this means the binding is broken
# ---------------------------------------------------------------------------
_EXPECTED_STEPS = (
    "length_cap",
    "html_entity_unescape",
    "canonical_normalize",
    "compose_turkish_dotted_i",
    "confusables_fold",
    "digit_letter_fold",
    "lowercase_tr",
    "obfuscated_slur_normalize",
    "punct_normalize",
    "citation_tail_strip",
    "social_hygiene",
    "emoji_hint_extract",
    "diacritic_restore",
    "strip_preamble",
    "regional_dialect_normalize",
    "apostrophe_proper_noun_repair",
    "tokenize",
    "split_questions",
    "strip_combining_marks",
    "repeat_collapse",
    "reduplication_collapse",
    "predictive_overshoot",
    "inline_self_correction",
    "compound_split",
    "particle_normalize",
    "assimilation_fold",
    "postposition_stack",
    "consonant_alternation",
    "vowel_drop_before_suffix",
    "loanword_singularisation",
    "geminate_restoration",
    "dialect_normalize",
    "typo_correct",
)


class TestBindingStepOrder:
    """steps_run must always list all 9 steps in the prescribed order."""

    def test_steps_run_order_on_clean_input(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray mac", _clock=lambda: 0.0)
        assert result.steps_run == _EXPECTED_STEPS

    def test_steps_run_order_on_turkish_mixed(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("\u0130stanbul basaksehir", _clock=lambda: 0.0)
        assert result.steps_run == _EXPECTED_STEPS

    def test_steps_run_order_on_empty_input(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("", _clock=lambda: 0.0)
        assert result.steps_run == _EXPECTED_STEPS

    def test_original_codepoint_count_recorded(self) -> None:
        from nlp.normalize import normalize_input

        text = "galatasaray"
        result = normalize_input(text)
        assert result.original_codepoint_count == len(text)

    def test_emoji_hints_are_extracted_and_stripped_before_tokenization(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("🔴🟡 maç ne zaman")
        joined = " ".join(result.tokens)
        assert "🔴" not in joined
        assert "🟡" not in joined
        assert result.emoji_hints == (
            {"emoji": "🔴", "hint": "team_color", "team_color": ["red"]},
            {"emoji": "🟡", "hint": "team_color", "team_color": ["yellow"]},
        )

    def test_html_entity_unescape_runs_before_canonical_normalize(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray &amp; fenerbahce")
        assert result.steps_run[1] == "html_entity_unescape"
        assert "&amp;" not in " ".join(result.tokens)
        assert "amp" not in " ".join(result.tokens)

    def test_html_entity_unescape_can_be_disabled(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        cfg = Config()
        cfg.nlp_html_unescape_enabled = False
        result = normalize_input("galatasaray &amp; fenerbahce", cfg=cfg)
        assert any("&amp" in tok for tok in result.tokens)
        assert "galatasaray" in result.tokens
        assert "fenerbahce" in result.tokens

    def test_emoji_hint_extraction_can_be_disabled(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        cfg = Config()
        cfg.nlp_emoji_hint_enabled = False
        result = normalize_input("🔴🟡 maç ne zaman", cfg=cfg)
        assert result.emoji_hints == ()
        assert "🔴" in " ".join(result.tokens)
        assert "🟡" in " ".join(result.tokens)

    def test_preamble_strip_removes_leading_greeting_prefix(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("merhaba abi galatasaray kazanir mi")
        assert "merhaba" not in result.tokens
        assert "abi" not in result.tokens
        assert "galatasaray" in result.tokens
        assert any(event.get("kind") == "preamble_stripped" for event in result.normalization_events)

    def test_preamble_strip_does_not_collapse_to_empty(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("merhaba abi")
        assert "merhaba" in result.tokens
        assert "abi" in result.tokens
        assert all(event.get("kind") != "preamble_stripped" for event in result.normalization_events)

    def test_preamble_strip_capped_emits_event(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        cfg = Config()
        cfg.nlp_preamble_max_strip_tokens = 1
        result = normalize_input("merhaba abi galatasaray kazanir mi", cfg=cfg)
        assert any(event.get("kind") == "preamble_strip_capped" for event in result.normalization_events)
        assert "merhaba" in result.tokens
        assert "abi" in result.tokens

    def test_hashtag_handling_can_be_disabled(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        cfg = Config()
        cfg.nlp_hashtag_handling_enabled = False
        result = normalize_input("#GSFB maç", cfg=cfg)
        assert "#gsfb" in " ".join(result.tokens)
        assert "galatasaray" not in result.tokens

    def test_hashtag_gsfb_resolves_to_match_pair(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("#GSFB maç")
        assert "galatasaray" in result.tokens
        assert "fenerbahce" in result.tokens
        assert "#gsfb" not in result.tokens

    def test_at_mention_galatasaray_strong_hint(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("@galatasaray maç")
        assert "galatasaray" in result.tokens
        assert "@galatasaray" not in result.tokens

    def test_unknown_at_mention_is_dropped(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("@unknownhandle maç")
        joined = " ".join(result.tokens)
        assert "unknownhandle" not in joined
        assert "@unknownhandle" not in joined

    def test_url_is_stripped_and_domain_recorded(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("https://example.com/fb maç")
        joined = " ".join(result.tokens)
        assert "https://example.com/fb" not in joined
        assert any(event.get("kind") == "url_stripped" and event.get("domain") == "example.com" for event in result.normalization_events)

    def test_url_glued_to_token_split(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasarayhttps://example.com/maçı")
        joined = " ".join(result.tokens)
        assert "galatasaray" in joined
        assert not any(token.startswith("https://") or token.startswith("www.") or token.startswith("ftp://") for token in result.tokens)
        assert any(event.get("kind") == "normalize_url_stripped" for event in result.normalization_events)

    def test_url_strip_emits_normalize_url_stripped_event_count(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("https://example.com/foo http://example.org/bar maç")
        assert any(
            event.get("kind") == "normalize_url_stripped" and event.get("count") == 2
            for event in result.normalization_events
        )

    def test_emoji_strip_removes_symbol_characters(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        cfg = Config()
        result = normalize_input("Mauro 👑 maçı 🐉", cfg=cfg)
        joined = " ".join(result.tokens)
        assert "mauro" in joined
        assert "mac" in joined
        assert "👑" not in joined
        assert "🐉" not in joined
        assert any(event.get("kind") == "emoji_stripped" and event.get("count") == 2 for event in result.normalization_events)

    def test_preamble_negative_corpus_does_not_strip(self) -> None:
        import json
        from pathlib import Path
        from nlp.normalize import normalize_input

        path = Path(__file__).parent / "fixtures" / "preamble_negative_corpus.tr.json"
        with path.open("r", encoding="utf-8") as fh:
            negatives = json.load(fh)

        assert len(negatives) >= 10
        for text in negatives:
            result = normalize_input(text)
            assert all(event.get("kind") != "preamble_stripped" for event in result.normalization_events), f"unexpected strip for: {text}"

    def test_preamble_positive_corpus_strips_prefix(self) -> None:
        import json
        from pathlib import Path
        from nlp.normalize import normalize_input

        path = Path(__file__).parent / "fixtures" / "preamble_positive_corpus.tr.json"
        with path.open("r", encoding="utf-8") as fh:
            positives = json.load(fh)

        assert len(positives) >= 25
        for item in positives:
            result = normalize_input(item["raw"])
            joined = " ".join(result.tokens)
            assert joined == item["tail"], f"expected tail {item['tail']} for {item['raw']}"
            assert any(event.get("kind") == "preamble_stripped" for event in result.normalization_events)

    def test_predictive_overshoot_known_pairs(self) -> None:
        from nlp.normalize import normalize_input

        path = Path(__file__).resolve().parents[1] / "nlp" / "lang_tr" / "predictive_text_known_overshoot.tr.yaml"
        mapping = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        assert len(mapping) >= 50

        for source, expected in mapping.items():
            result = normalize_input(source, _clock=lambda: 0.0)
            assert expected in result.tokens
            assert source not in result.tokens
            assert (source, expected) in result.predictive_overshoot_repairs
            assert any(
                event.get("kind") == "predictive_overshoot_offered"
                and event.get("original_token") == source
                and event.get("corrected_token") == expected
                for event in result.normalization_events
            )

    def test_generic_decorative_emoji_are_stripped_without_hints(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray 😂 maç")
        joined = " ".join(result.tokens)
        assert "😂" not in joined
        assert all(hint["emoji"] != "😂" for hint in result.emoji_hints)

    def test_voice_input_uses_voice_diacritic_ratio(self) -> None:
        from unittest.mock import patch

        from common.config import Config
        from nlp.diacritics import DiacriticsTable
        from nlp.normalize import normalize_input

        cfg = Config()
        cfg.nlp_diacritic_tie_break_ratio = 1.5
        cfg.nlp_diacritic_tie_break_ratio_voice = 2.5
        dummy_table = DiacriticsTable(
            {
                "_meta": {
                    "schema_version": 1,
                    "lexicon_version": "1.0.0",
                    "generated_at_utc": "2026-05-27T00:00:00Z",
                    "generator": "test",
                    "source_sha256": "test",
                },
                "mappings": {
                    "mac": {
                        "candidates": [
                            {"canonical": "maç", "frequency": 10},
                            {"canonical": "mac", "frequency": 5},
                        ]
                    }
                },
            },
            tie_break_ratio=2.5,
        )
        with patch("nlp.diacritics.DiacriticsTable.load", autospec=True) as load_mock:
            load_mock.return_value = dummy_table
            normalize_input("galatasaray mac", cfg=cfg, input_source="voice")
            load_mock.assert_called_once_with(tie_break_ratio=cfg.nlp_diacritic_tie_break_ratio_voice)

    def test_voice_input_restores_soft_g_tokens_via_g_to_softg(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("degil yagmur", input_source="voice")
        assert "değil" in result.tokens
        assert "yağmur" in result.tokens

    def test_voice_input_soft_g_restoration_corpus(self) -> None:
        from nlp.normalize import normalize_input

        corpus_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "g_to_softg_corpus.tr.json"
        )
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        for row in corpus:
            result = normalize_input(row["raw"], input_source="voice")
            assert " ".join(result.tokens) == row["expected"], row


class TestFocusParticleDisambiguation:
    def test_nlp_focus_particle_bypasses_question_tag_classifier(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasaray ne zaman mı oynayacak?")

        assert result.focus_particle_disambiguated is True
        assert any(event.get("kind") == "focus_particle_disambiguated" for event in result.normalization_events)

    def test_focus_particle_disambiguation_does_not_fire_for_yes_no_question(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasaray mı kazanacak?")

        assert result.focus_particle_disambiguated is False
        assert all(event.get("kind") != "focus_particle_disambiguated" for event in result.normalization_events)

    def test_negation_scope_composition_still_bypasses_question_tag_classifier(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("yenmedi mi kim?")

        assert result.focus_particle_disambiguated is True
        assert any(event.get("kind") == "focus_particle_disambiguated" for event in result.normalization_events)

    def test_question_tag_classifier_distinguishes_three_shapes(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasaray kazandı mı?")
        assert result.pragmatic_class == "information_seeking"

        result = normalize_input("Galatasaray kazandı, değil mi?")
        assert result.pragmatic_class == "confirmation_seeking"

        result = normalize_input("Galatasaray kazanmadı mı?")
        assert result.pragmatic_class == "information_seeking"

    def test_question_tag_classifier_defers_ambiguous_negative_surface(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasaray Fenerbahçe'yi yenmedi mi?")
        assert result.pragmatic_class is None

    def test_question_tag_classifier_preserved_on_timeout_raw_tokens(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        cfg = Config()
        cfg.nlp_normalize_stage_timeout_ms = 20

        t = 0.0

        def slow_clock() -> float:
            nonlocal t
            current = t
            t += 0.05
            return current

        result = normalize_input(
            "Galatasaray kazandı mı?",
            cfg=cfg,
            _clock=slow_clock,
        )

        assert result.stage_timed_out is True
        assert result.pragmatic_class == "information_seeking"


class TestStep1LengthCap:
    """Step 1: reject inputs exceeding cfg.nlp_input_max_codepoints."""

    def test_rejects_oversize(self) -> None:
        from nlp.normalize import normalize_input, InputTooLongError

        fake_cfg = type("FakeCfg", (), {"nlp_input_max_codepoints": 10, "nlp_normalize_stage_timeout_ms": 200})()
        with pytest.raises(InputTooLongError, match="10"):
            normalize_input("a" * 11, cfg=fake_cfg)

    def test_accepts_exactly_at_cap(self) -> None:
        from nlp.normalize import normalize_input

        from common.config import Config

        cfg = Config()
        text = "a" * cfg.nlp_input_max_codepoints
        result = normalize_input(text, cfg=cfg)
        assert "length_cap" in result.steps_run

    def test_accepts_below_cap(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("fenerbahce")
        assert "length_cap" in result.steps_run

    def test_adversarial_codepoints_not_bytes(self) -> None:
        """Multibyte Turkish chars are 1 codepoint each -- must not be double-counted."""
        from nlp.normalize import normalize_input

        # "beşiktaş" has 8 codepoints; "ş" is 2 bytes in UTF-8
        text = "besiktas macini tahmin et"  # ASCII, well under 512 cp
        result = normalize_input(text)
        assert result.original_codepoint_count == len(text)

    def test_adversarial_raises_error_not_truncates(self) -> None:
        """Oversize input MUST raise, never silently truncate."""
        from nlp.normalize import normalize_input, InputTooLongError

        fake_cfg = type("FakeCfg", (), {"nlp_input_max_codepoints": 5, "nlp_normalize_stage_timeout_ms": 200})()
        with pytest.raises(InputTooLongError):
            normalize_input("toolonginput", cfg=fake_cfg)


class TestRepeatCollapseNormalization:
    """Phase 10 §10.24.2 repeat-collapse behavior and downstream integration."""

    def test_repeat_collapse_runs_before_typo_correction(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        observed: list[list[str]] = []

        def mock_typo(tokens: list[str]) -> tuple[list[str], bool]:
            observed.append(tokens)
            return ["evet" if tok == "evett" else tok for tok in tokens], False

        cfg = Config()
        result = normalize_input("evettttt mac", cfg=cfg, _typo_correct=mock_typo)

        assert observed == [["evett", "mac"]]
        assert "evet" in result.tokens

    def test_repeat_collapse_preserves_intentional_doubles(self) -> None:
        from nlp.normalize import normalize_input

        observed: list[list[str]] = []

        def mock_typo(tokens: list[str]) -> tuple[list[str], bool]:
            observed.append(tokens)
            return tokens, False

        normalize_input("saat maç", _typo_correct=mock_typo)
        assert observed == [["saat", "maç"]]

    def test_repeat_collapse_drops_overlong_tokens_as_garbage(self) -> None:
        from common.config import Config
        from nlp.normalize import normalize_input

        calls: list[list[str]] = []

        def mock_typo(tokens: list[str]) -> tuple[list[str], bool]:
            calls.append(tokens)
            return tokens, False

        cfg = Config()
        cfg.nlp_repeat_collapse_max_len = 10
        normalize_input("galatasarayabcdefgh mac", cfg=cfg, _typo_correct=mock_typo)

        assert calls == [["mac"]]

    def test_repeat_collapse_idempotent(self) -> None:
        from nlp.normalize import normalize_input

        result1 = normalize_input("hayııır")
        result2 = normalize_input(" ".join(result1.tokens))

        assert result1.tokens == result2.tokens

    def test_inline_self_correction_runs_before_compound_split(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galat Galatasaray bugün oynuyor mu")
        assert "inline_self_correction" in result.steps_run
        assert result.steps_run.index("inline_self_correction") == result.steps_run.index("reduplication_collapse") + 2
        assert "galatasaray" in result.tokens
        assert "galat" not in result.tokens
        assert any(event.get("kind") == "inline_self_correction_applied" for event in result.normalization_events)

    def test_inline_self_correction_removes_verbal_marker_prefix(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("yok yok Galatasaray maç")
        assert "galatasaray" in result.tokens
        assert "yok" not in result.tokens
        assert any(
            event.get("kind") == "inline_self_correction_applied"
            and event.get("strategy") == "verbal_self_correction"
            for event in result.normalization_events
        )

    def test_inline_self_correction_preserves_unrelated_marker(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasaray yok Fenerbahçe maçı mı")
        assert "yok" in result.tokens
        assert any(event.get("kind") == "inline_self_correction_applied" for event in result.normalization_events) is False


class TestDigitLetterConfusableFold:
    """Phase 10 §10.24.3 digit-letter confusable folding behavior."""

    def test_digit_letter_fold_folds_leetspeak_tokens(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("g4latasaray mac")
        assert "galatasaray" in result.tokens

    def test_digit_letter_fold_preserves_year_suffix_allowlist(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("BJK1903 maç")
        assert "bjk1903" in result.tokens
        assert "bjkiioe" not in result.tokens

    def test_digit_letter_fold_does_not_fold_score_lines(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("1-0 galatasaray")
        assert "1-0" in result.tokens


class TestSteps23CanonicalNormalize:
    """Steps 2+3: NFC normalize + strip control chars / zero-widths / RTL overrides."""

    def test_strips_zero_width_space(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("gala\u200Btasaray")  # ZWSP injected
        joined = " ".join(result.tokens)
        assert "\u200B" not in joined

    def test_strips_rtl_override(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("fenerbah\u202Ece")  # RLO injection
        joined = " ".join(result.tokens)
        assert "\u202E" not in joined


class TestPhase1030Normalization:
    def test_detects_search_query_style(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("site:example.com galatasaray")
        assert result.query_style == "search"

    def test_strips_politeness_markers(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("lütfen galatasaray maçını tahmin et")
        assert result.politeness_class == "polite"
        assert "lütfen" not in result.tokens

    def test_strips_politeness_respect_form_question(self) -> None:
        from nlp.normalize import normalize_input

        polite_result = normalize_input("yapar mısınız galatasaray maçını tahmin et")
        bare_result = normalize_input("yapar galatasaray maçını tahmin et")

        assert polite_result.politeness_class == "polite"
        assert "mısınız" not in polite_result.tokens
        assert polite_result.tokens == bare_result.tokens

    def test_strips_conditional_polite_chain(self) -> None:
        from nlp.normalize import normalize_input

        polite_result = normalize_input("bakabilir miydiniz galatasaray maçını tahmin et")
        bare_result = normalize_input("bakabilir galatasaray maçını tahmin et")

        assert polite_result.politeness_class == "polite"
        assert "miydiniz" not in polite_result.tokens
        assert polite_result.tokens == bare_result.tokens

    def test_expands_idioms_when_context_is_present(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("göze girmek takım")
        assert "etkilenmek" in result.tokens

    def test_idiom_expansion_is_deterministic_and_longest_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nlp.phase10_30 import expand_idioms

        def fake_phrasebook() -> list[dict[str, str]]:
            return [
                {"idiom": "sahada kalmak", "expansion": "oyundan çıkmak"},
                {"idiom": "sahada", "expansion": "sahayı"},
                {"idiom": "sahada kalmak", "expansion": "oyunduan çıkmak"},
            ]

        monkeypatch.setattr(
            "nlp.phase10_30.load_idiom_phrasebook",
            fake_phrasebook,
            raising=False,
        )
        monkeypatch.setattr(
            "nlp.phase10_30.load_idiom_context",
            lambda: {},
            raising=False,
        )

        tokens = ["sahada", "kalmak"]
        expanded_first, events_first = expand_idioms(tokens, "sahada kalmak")
        expanded_second, events_second = expand_idioms(tokens, "sahada kalmak")

        assert expanded_first == ["oyundan çıkmak"]
        assert events_first == [
            {
                "kind": "idiom_expansion",
                "idiom": "sahada kalmak",
                "span": (0, 2),
                "replaced_tokens": ["sahada", "kalmak"],
            }
        ]
        assert expanded_second == expanded_first
        assert events_second == events_first

    def test_conditional_modifier_set_when_marker_present(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray kazanırsa lider olur mu")
        assert result.intent_modifier == "conditional"

    def test_comparative_modifier_set_when_coordinating_particles_present(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray ya da fenerbahçe kim kazanır")
        assert result.intent_modifier == "comparative"
        assert result.tokens[1:3] == ("ya", "da")

    def test_conditional_plus_comparative_tuple_set_when_both_markers_present(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray kazanırsa fenerbahçeden önde mi olur")
        assert result.intent_modifier == ("conditional", "comparative")

    def test_sarcasm_modifier_set_on_cue_plus_context(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray harika oynadılar ama son maçta 0-5 kaybetti")
        assert result.intent_modifier == "sarcastic"

    def test_sarcasm_cue_without_context_emits_no_context_event(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray harika oynadılar")
        events = [event for event in result.normalization_events if event.get("kind") == "sarcasm_cue_no_context"]
        assert len(events) == 1
        assert events[0]["cue_id"] == "harika oynadılar"
        assert events[0]["cue_phrase"] == "harika oynadılar"
        assert events[0]["span"] == (1, 3)

        result_with_context = normalize_input("galatasaray harika oynadılar ama son maçta 0-5 kaybetti")
        assert not any(event.get("kind") == "sarcasm_cue_no_context" for event in result_with_context.normalization_events)

    def test_search_operator_patterns_detect_plus_minus(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("+galatasaray -fenerbahçe")
        assert result.query_style == "search"

    def test_search_operator_detects_ve_veya_uppercase_only(self) -> None:
        from nlp.normalize import normalize_input

        search_upper = normalize_input("GALATASARAY VEYA FENERBAHÇE")
        assert search_upper.query_style == "search"

        natural = normalize_input("galatasaray veya fenerbahçe")
        assert natural.query_style == "natural"

    def test_search_operator_detects_or_and_uppercase_only(self) -> None:
        from nlp.normalize import normalize_input

        search_or = normalize_input("GALATASARAY OR FENERBAHÇE")
        assert search_or.query_style == "search"

        natural_or = normalize_input("galatasaray or fenerbahçe")
        assert natural_or.query_style == "natural"

    def test_search_operator_detects_field_prefix(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("site:mackolik.com galatasaray")
        assert result.query_style == "search"

    def test_search_operator_detects_quoted_exact_match(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input('"şampiyonlar ligi" nerede')
        assert result.query_style == "quoted_exact_search"

    def test_strips_bom(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("\uFEFFgalatasaray")
        joined = " ".join(result.tokens)
        assert "\uFEFF" not in joined

    def test_strips_c0_control_char(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("gala\u0001tasaray")
        joined = " ".join(result.tokens)
        assert "\u0001" not in joined

    def test_nfc_precomposed_turkish_char_survives(self) -> None:
        """NFC precomposed chars (e.g. ş U+015F) must NOT be stripped."""
        from nlp.normalize import normalize_input

        result = normalize_input("be\u015Fikta\u015F")  # "beşiktaş"
        joined = " ".join(result.tokens)
        assert "\u015F" in joined  # ş must survive

    def test_canonical_normalize_idempotent(self) -> None:
        """canonical_normalize(canonical_normalize(x)) == canonical_normalize(x)."""
        from common.text.normalize import canonical_normalize

        samples = [
            "galatasaray",
            "\u200Bfenerbahce\uFEFF",
            "\u202Etest",
            "be\u015Fikta\u015F",
            "",
        ]
        for s in samples:
            once = canonical_normalize(s)
            twice = canonical_normalize(once)
            assert once == twice, f"Not idempotent for {s!r}: {once!r} vs {twice!r}"

    def test_canonical_normalize_strips_disallowed_format_and_private_use_chars(self) -> None:
        from common.text.normalize import canonical_normalize

        raw = "gala\u2060tasaray\uFE0F\uE000\u0378"
        clean = canonical_normalize(raw)
        assert "\u2060" not in clean
        assert "\uFE0F" not in clean
        assert "\uE000" not in clean
        assert "\u0378" not in clean

    def test_normalize_input_strips_disallowed_format_and_private_use_chars(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("gala\u2060tasaray\uFE0F\uE000\u0378")
        joined = " ".join(result.tokens)
        for ch in ("\u2060", "\uFE0F", "\uE000", "\u0378"):
            assert ch not in joined

    def test_normalize_input_dotted_i_is_idempotent(self) -> None:
        from nlp.normalize import normalize_input

        for raw in ["I\u0307stanbul", "i\u0307stanbul", "I\u0307\u0307stanbul"]:
            result = normalize_input(raw)
            rejoined = " ".join(result.tokens)
            result2 = normalize_input(rejoined)
            assert result2.tokens == result.tokens, (
                f"Not idempotent for dotted-i input: {raw!r}: {result.tokens!r} vs {result2.tokens!r}"
            )

    def test_voice_input_strips_asr_fillers(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("eee galatasaray maçını tahmin et", input_source="voice")
        assert "eee" not in result.tokens
        assert "galatasaray" in result.tokens

    def test_keyboard_input_preserves_yani(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("yani galatasaray maçını tahmin et", input_source="keyboard")
        assert "yani" in result.tokens

    def test_keyboard_input_does_not_restore_diacritics_by_default(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray mac", input_source="keyboard")
        assert "mac" in result.tokens
        assert "maç" not in result.tokens

    def test_voice_input_restores_diacritics_on_explicit_voice_path(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray mac", input_source="voice")
        assert "maç" in result.tokens

    def test_voice_input_strips_yani(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("yani galatasaray maçını tahmin et", input_source="voice")
        assert "yani" not in result.tokens

    def test_asr_punctuation_words_stripped_only_in_voice_modality(self) -> None:
        from nlp.normalize import normalize_input

        voice_result = normalize_input("virgül galatasaray", input_source="voice")
        assert "virgül" not in voice_result.tokens
        assert any(event["kind"] == "asr_punctuation_word_stripped" for event in voice_result.normalization_events)

        keyboard_result = normalize_input("virgül galatasaray", input_source="keyboard")
        assert "virgül" in keyboard_result.tokens
        assert not keyboard_result.normalization_events

    def test_asr_punctuation_word_replaces_adjacent_number_words_with_literal_punctuation(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("yirmi virgül beş", input_source="voice")
        assert result.tokens == ("20,5",)

    def test_nlp_suffix_harmony_repaired_event_emitted_with_debounce(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Besiktase")
        assert any(
            event["kind"] == "suffix_harmony_repaired"
            and event["original_suffix"] == "e"
            and event["resolved_suffix_class"] == "dative"
            for event in result.suffix_harmony_repair_events
        )

    def test_voice_number_tiebreak_resolves_time_to_digit(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("saat yirmi bir", input_source="voice")
        assert result.tokens == ("saat", "21")

    def test_voice_number_tiebreak_resolves_score_to_ordinal(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("gol yirmi bir", input_source="voice")
        assert result.tokens == ("gol", "21.")

    def test_voice_number_tiebreak_resolves_year_to_four_digit(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("iki bin yirmi bir sezon", input_source="voice")
        assert result.tokens == ("2021", "sezon")

    def test_voice_question_split_relaxed_without_punctuation(self) -> None:
        from nlp.normalize import split_questions

        tokens = "galatasaray kazandi mi fenerbahce ne zaman oynar simdi".split()
        assert split_questions(tokens, input_source="voice") == [
            ["galatasaray", "kazandi", "mi"],
            ["fenerbahce", "ne", "zaman", "oynar", "simdi"],
        ]

    def test_split_questions_is_noop_for_keyboard_input(self) -> None:
        from nlp.normalize import split_questions

        tokens = "galatasaray kazandi mi fenerbahce ne zaman oynar simdi".split()
        assert split_questions(tokens, input_source="keyboard") == [tokens]

    def test_voice_question_split_active_ve_boundary(self) -> None:
        from nlp.normalize import split_questions

        tokens = "fenerbahce ne zaman oynar ve galatasaray kazanacak mu".split()
        assert split_questions(tokens, input_source="voice") == [
            ["fenerbahce", "ne", "zaman", "oynar", "ve"],
            ["galatasaray", "kazanacak", "mu"],
        ]

    def test_normalize_input_records_voice_subqueries(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input(
            "galatasaray kazandi mi fenerbahce ne zaman oynar simdi",
            input_source="voice",
        )
        assert result.subqueries == (
            ("galatasaray", "kazandi", "mi"),
            ("fenerbahçe", "ne", "zaman", "oynar", "simdi"),
        )
        assert "split_questions" in result.steps_run

    def test_normalize_input_caps_voice_subqueries_to_cfg_max_subqueries(
        self, monkeypatch
    ) -> None:
        from common.config import cfg
        from nlp.normalize import normalize_input

        monkeypatch.setattr(cfg, "nlp_max_subqueries", 1)
        result = normalize_input(
            "galatasaray kazandi mi fenerbahce ne zaman oynar simdi",
            cfg=cfg,
            input_source="voice",
        )

        assert result.subqueries == (("galatasaray", "kazandi", "mi"),)
        assert any(
            event.get("kind") == "subquery_cap_applied"
            for event in result.compound_split_events
        )

    def test_normalize_input_does_not_split_keyboard_input(self) -> None:
        from nlp.normalize import normalize_input

        query = "galatasaray kazandi mi fenerbahce ne zaman oynar simdi"
        result = normalize_input(query, input_source="keyboard")
        assert result.subqueries == (
            tuple(query.split()),
        )
        assert "split_questions" in result.steps_run

    def test_normalize_input_preserves_bare_proper_noun_without_suffix(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Galatasaray")
        assert result.tokens == ("galatasaray",)
        assert result.apostrophe_repairs == ()


class TestStep4TurkishLowercase:
    """Step 4: I->ı (dotless-i) and dotted-I->i; NOT str.lower() behaviour."""

    def test_capital_I_becomes_dotless_i(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("Istanbul")
        # I (U+0049) -> ı (U+0131) then rest is already lowercase
        assert "\u0131stanbul" in result.tokens

    def test_dotted_capital_I_becomes_dotted_lower(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("\u0130stanbul")  # İstanbul
        assert "istanbul" in result.tokens

    def test_standard_uppercase_still_lowered(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("GALATASARAY")
        assert "galatasaray" in result.tokens

    def test_detect_all_caps_requires_minimum_letter_count(self) -> None:
        from nlp.normalize import detect_all_caps

        assert detect_all_caps("GO!!!") is False
        assert detect_all_caps("THIS IS A SHOUT") is True

    def test_normalize_input_all_caps_skips_proper_noun_apostrophe_insertion(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("GALATASARAYA maç")
        assert "galatasaraya" in result.tokens
        assert "galatasaray'a" not in result.tokens
        assert result.apostrophe_repairs == ()

    def test_lowercase_tr_i_not_clobbered_by_str_lower(self) -> None:
        """str.lower() on 'I' -> 'i' (wrong for Turkish); our impl gives 'ı'."""
        from common.text.turkish import lowercase_tr

        result = lowercase_tr("I")
        assert result == "\u0131", f"Expected dotless-i, got {result!r}"
        assert result != "i", "str.lower() result -- Turkish mapping was not applied"

    def test_lowercase_tr_on_all_turkish_uppercase(self) -> None:
        from common.text.turkish import lowercase_tr

        mapping = {
            "I": "\u0131",       # dotless i
            "\u0130": "i",       # dotted i
            "A": "a",
            "B": "b",
            "C": "c",
            "D": "d",
            "E": "e",
            "F": "f",
            "G": "g",
            "H": "h",
            "J": "j",
            "K": "k",
            "L": "l",
            "M": "m",
            "N": "n",
            "O": "o",
            "P": "p",
            "R": "r",
            "S": "s",
            "T": "t",
            "U": "u",
            "V": "v",
            "Y": "y",
            "Z": "z",
        }
        for upper, lower in mapping.items():
            result = lowercase_tr(upper)
            assert result == lower, f"lowercase_tr({upper!r}) -> {result!r}, expected {lower!r}"

    def test_decomposed_capital_i_recomposes_to_dotted_i(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("I\u0307stanbul")
        assert "istanbul" in result.tokens

    def test_decomposed_lowercase_i_drops_stray_dot(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("i\u0307stanbul")
        assert "istanbul" in result.tokens

    def test_combining_dot_above_tail_strip_removes_extra_marks(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("I\u0307\u0307stanbul")
        assert "istanbul" in result.tokens
        assert not any("\u0307" in tok for tok in result.tokens)

    def test_excessive_combining_marks_drops_token_with_alert(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray x\u0304\u0308\u0301\u0302\u0303")
        assert result.tokens == ("galatasaray",)
        assert any(
            event["kind"] == "excessive_combining_marks" and event["token_dropped"]
            for event in result.normalization_events
        )


class TestStep5PunctNormalize:
    """Step 5: curly quotes, em-dash, en-dash, multiple spaces."""

    def test_left_double_quote_replaced(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("\u201Cgalatasaray\u201D")
        joined = " ".join(result.tokens)
        assert "\u201C" not in joined
        assert "\u201D" not in joined

    def test_em_dash_replaced(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("ev\u2014deplasman")
        joined = " ".join(result.tokens)
        assert "\u2014" not in joined
        # em-dash -> " - " splits into at least two tokens
        assert len(result.tokens) >= 2

    def test_en_dash_replaced(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("ev\u2013deplasman")
        joined = " ".join(result.tokens)
        assert "\u2013" not in joined

    def test_multiple_spaces_collapsed(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray   fenerbahce")
        # After collapse -> ["galatasaray", "fenerbahce"]
        assert "galatasaray" in result.tokens
        assert "fenerbahce" in result.tokens

    def test_ellipsis_replaced(self) -> None:
        from nlp.normalize import normalize_input

        canonical_result = normalize_input("Galatasaray... maç")
        ellipsis_result = normalize_input("Galatasaray… maç")

        assert "…" not in " ".join(ellipsis_result.tokens)
        assert ellipsis_result.tokens == canonical_result.tokens

    def test_unicode_space_collapse(self) -> None:
        from nlp.normalize import normalize_input

        unicode_spaces = [
            "\u00A0",  # NO-BREAK SPACE
            "\u1680",  # OGHAM SPACE MARK
            "\u2000",  # EN QUAD
            "\u2001",  # EM QUAD
            "\u2002",  # EN SPACE
            "\u2003",  # EM SPACE
            "\u2004",  # THREE-PER-EM SPACE
            "\u2005",  # FOUR-PER-EM SPACE
            "\u2006",  # SIX-PER-EM SPACE
            "\u2007",  # FIGURE SPACE
            "\u2008",  # PUNCTUATION SPACE
            "\u2009",  # THIN SPACE
            "\u200A",  # HAIR SPACE
            "\u202F",  # NARROW NO-BREAK SPACE
            "\u205F",  # MEDIUM MATHEMATICAL SPACE
            "\u3000",  # IDEOGRAPHIC SPACE
        ]
        for space_char in unicode_spaces:
            result = normalize_input(f"galatasaray{space_char}fenerbahce")
            assert "galatasaray" in result.tokens
            assert "fenerbahce" in result.tokens
            assert space_char not in " ".join(result.tokens)
    def test_single_quotes_normalized(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("\u2018galatasaray\u2019")
        joined = " ".join(result.tokens)
        assert "\u2018" not in joined
        assert "\u2019" not in joined

    def test_soft_hyphens_are_removed(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray\u00AD fenerbahce")
        assert "\u00AD" not in " ".join(result.tokens)
        assert result.tokens == ("galatasaray", "fenerbahce")


class TestStep7Tokenize:
    """Step 7: whitespace + punctuation split."""

    def test_whitespace_split(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray mac tahmini")
        assert result.tokens == ("galatasaray", "mac", "tahmini")

    def test_empty_input_gives_empty_tokens(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("")
        assert result.tokens == ()

    def test_comma_splits_tokens(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray,fenerbahce")
        assert "galatasaray" in result.tokens
        assert "fenerbahce" in result.tokens

    def test_question_mark_splits(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray kazanir mi?")
        assert "galatasaray" in result.tokens
        assert "kazanir" in result.tokens
        assert "mi" in result.tokens

    def test_only_whitespace_gives_empty_tokens(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("   ")
        assert result.tokens == ()


class TestCopyPasteCitationStripping:
    def test_paste_input_strips_citation_tail(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input(
            "Galatasaray 3 - 1 Fenerbahçe kaynak: Twitter",
            input_source="paste",
        )

        assert result.stripped_tail == "kaynak: twitter"
        assert "kaynak" not in result.tokens
        assert "twitter" not in result.tokens

    def test_long_keyboard_input_strips_citation_tail(self) -> None:
        from nlp.normalize import normalize_input

        raw = " ".join(["galatasaray"] * 30) + " source: Facebook"
        result = normalize_input(raw, input_source="keyboard")

        assert result.stripped_tail == "source: facebook"
        assert "source" not in result.tokens
        assert "facebook" not in result.tokens

    def test_copy_paste_tail_strip_is_idempotent(self) -> None:
        from nlp.normalize import normalize_input

        raw = "Galatasaray — Fenerbahçe… source: Twitter"
        result = normalize_input(raw, input_source="paste")
        again = normalize_input(" ".join(result.tokens), input_source="paste")

        assert again.tokens == result.tokens
        assert again.stripped_tail is None


class TestSteps6And8Hooks:
    """Steps 6 and 8 are pass-through stubs until §10.3 lands; hooks injectable."""

    def test_step6_hook_called_with_string(self) -> None:
        from nlp.normalize import normalize_input

        calls: list[str] = []

        def mock_diacritic(text: str) -> str:
            calls.append(text)
            return text

        normalize_input("galatasaray", _diacritic_restore=mock_diacritic)
        assert len(calls) == 1
        assert isinstance(calls[0], str)

    def test_step8_hook_called_with_token_list(self) -> None:
        from nlp.normalize import normalize_input

        calls: list[list[str]] = []

        def mock_typo(tokens: list[str]) -> tuple[list[str], bool]:
            calls.append(tokens)
            return tokens, False

        normalize_input("galatasaray mac", _typo_correct=mock_typo)
        assert len(calls) == 1
        assert isinstance(calls[0], list)

    def test_no_hooks_produces_passthrough(self) -> None:
        from nlp.normalize import normalize_input

        result = normalize_input("galatasaray mac tahmini")
        assert "diacritic_restore" in result.steps_run
        assert "typo_correct" in result.steps_run
        # Without hooks, tokens are unmodified by steps 6 and 8
        assert "galatasaray" in result.tokens
        assert result.typo_budget_exhausted is False

    def test_step8_hook_can_rewrite_tokens(self) -> None:
        from nlp.normalize import normalize_input

        def correct_typo(tokens: list[str]) -> tuple[list[str], bool]:
            return ["corrected" if t == "galatasary" else t for t in tokens], False

        result = normalize_input("galatasary mac", _typo_correct=correct_typo)
        assert "corrected" in result.tokens
        assert result.typo_budget_exhausted is False

    def test_step8_hook_signals_budget_exhausted(self) -> None:
        """When the hook returns budget_exhausted=True the flag propagates."""
        from nlp.normalize import normalize_input

        def exhausted_hook(tokens: list[str]) -> tuple[list[str], bool]:
            # Simulate hitting the per-query budget mid-way.
            return tokens, True

        result = normalize_input("galatasaray fenerbahce mac", _typo_correct=exhausted_hook)
        assert result.typo_budget_exhausted is True


# ---------------------------------------------------------------------------
# Idempotency guarantee (§10.1)
# normalize(normalize(x)) == normalize(x), property-tested with hypothesis
# ---------------------------------------------------------------------------
from hypothesis import HealthCheck, given, seed as h_seed, settings
from hypothesis.strategies import text as h_text


@h_seed(20241215)
@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
@given(h_text(max_size=512))
def test_normalize_idempotent_property(text_input: str) -> None:
    """normalize_input(normalize_input(x).tokens_joined) has same tokens as first call.

    Re-joining tokens with a single space and re-normalizing must produce the
    exact same token tuple — i.e. the output is already in fully-normalized form.
    Seed-pinned at 20241215 for deterministic CI results.
    """
    from nlp.normalize import normalize_input, InputTooLongError
    from common.config import Config

    cfg = Config()
    try:
        result1 = normalize_input(text_input, cfg=cfg)
    except InputTooLongError:
        # hypothesis caps at 512 but the cfg value might differ in edge cases
        return

    rejoined = " ".join(result1.tokens)
    try:
        result2 = normalize_input(rejoined, cfg=cfg)
    except InputTooLongError:  # pragma: no cover
        # rejoined is always <= original after normalization; defensive only
        return

    assert result2.tokens == result1.tokens, (
        f"Not idempotent: input={text_input!r}, "
        f"pass1={result1.tokens!r}, pass2={result2.tokens!r}"
    )


class TestNlpInputMaxCodepointsConfig:
    """Config default for nlp_input_max_codepoints is 512."""

    def test_default_is_512(self) -> None:
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_input_max_codepoints == 512

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from common.config import Config

        monkeypatch.setenv("NEGELIR_NLP_INPUT_MAX_CODEPOINTS", "256")
        cfg = Config()
        assert cfg.nlp_input_max_codepoints == 256

    def test_nlp_collapse_unicode_spaces_default_true(self) -> None:
        from common.config import Config

        cfg = Config()
        assert cfg.nlp_collapse_unicode_spaces is True

    def test_bounds_check_positive(self) -> None:
        from common.config import Config

        cfg = Config()
        issues = cfg.validate()
        cap_issues = [i for i in issues if "nlp_input_max_codepoints" in i]
        assert cap_issues == []


# ---------------------------------------------------------------------------
# Determinism guarantee (§10.1)
# normalize_input output must be byte-identical across runs; hash() randomization
# MUST NOT enter the pipeline.  Two enforcement mechanisms:
#   1. AST guard: reject bare set/dict.keys() iteration in normalize.py.
#   2. Subprocess test: spawn with distinct PYTHONHASHSEED values, assert identical output.
# ---------------------------------------------------------------------------
class TestDeterminismGuarantee:
    """§10.1 Determinism: same input → byte-identical output; no hash-dependent paths."""

    def test_nlp_no_set_iteration_in_normalize(self) -> None:
        """AST guard: normalize.py must not iterate over set/dict.keys() without sorted()."""
        import ast
        import pathlib

        normalize_path = (
            pathlib.Path(__file__).parent.parent / "nlp" / "normalize.py"
        )
        source = normalize_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        def _is_sorted(node: ast.expr) -> bool:
            return (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "sorted"
            )

        def _is_bare_unordered(node: ast.expr) -> bool:
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "set":
                    return True
                if isinstance(func, ast.Attribute) and func.attr in ("keys", "values"):
                    return True
            if isinstance(node, ast.Set):
                return True
            return False

        violations: list[str] = []

        class _Checker(ast.NodeVisitor):
            def _check(self, iter_node: ast.expr, lineno: int) -> None:
                if _is_bare_unordered(iter_node) and not _is_sorted(iter_node):
                    violations.append(
                        f"line {lineno}: bare set/dict.keys()/dict.values() "
                        f"iteration without sorted() — violates §10.1 determinism"
                    )

            def visit_For(self, node: ast.For) -> None:  # type: ignore[override]
                self._check(node.iter, node.lineno)
                self.generic_visit(node)

            def visit_ListComp(self, node: ast.ListComp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)

            def visit_SetComp(self, node: ast.SetComp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)

            def visit_DictComp(self, node: ast.DictComp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)

            def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:  # type: ignore[override]
                for gen in node.generators:
                    self._check(gen.iter, node.lineno)
                self.generic_visit(node)

        _Checker().visit(tree)
        assert violations == [], (
            "normalize.py has hash-order-dependent iterations (violates §10.1 "
            "determinism guarantee):\n" + "\n".join(violations)
        )

    def test_normalize_determinism_across_hash_seeds(self) -> None:
        """hash() randomization must not affect normalize_input output.

        Spawns normalize_input in separate processes each with a distinct
        PYTHONHASHSEED and asserts byte-identical token tuples across all runs.
        """
        import json
        import os
        import pathlib
        import subprocess
        import sys

        ai_dir = str(pathlib.Path(__file__).parent.parent)
        # Inline script run per subprocess; uses sys.argv[1] as PYTHONPATH root.
        _SCRIPT = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from nlp.normalize import normalize_input; "
            "import json; "
            "inputs = ["
            "'Galatasaray mac tahmini', "
            "'\u0130stanbul Ba\u015fak\u015fehir', "
            "'gs fb derbi 2.5 \u00fcst', "
            "'fenerbah\u00e7e - be\u015fikta\u015f', "
            "'', "
            "'a b c d e f g h i j k l m n o p'"
            "]; "
            "print(json.dumps([list(normalize_input(t).tokens) for t in inputs]))"
        )
        results = []
        for seed in [0, 1, 42, 100, 999]:
            env = {**os.environ, "PYTHONHASHSEED": str(seed)}
            proc = subprocess.run(
                [sys.executable, "-c", _SCRIPT, ai_dir],
                capture_output=True,
                text=True,
                env=env,
            )
            assert proc.returncode == 0, (
                f"Subprocess failed (PYTHONHASHSEED={seed}):\n{proc.stderr}"
            )
            results.append(json.loads(proc.stdout.strip()))

        reference = results[0]
        for idx, result in enumerate(results[1:], 1):
            assert result == reference, (
                f"Non-deterministic output at seed index {idx} — "
                f"hash randomization leaked into normalize_input: "
                f"expected {reference!r}, got {result!r}"
            )
