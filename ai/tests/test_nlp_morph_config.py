"""Tests for Phase 10 §10.26 morphology config and candidate normalization."""

from __future__ import annotations

import importlib
import pathlib

import pytest

from common.config import Config, cfg
from common.text.turkish import (
    MorphCandidate,
    load_morph_pos_preferences,
    normalize_morph_candidates,
    resolve_morph_candidates,
)
from nlp.normalize import normalize_input
import hashlib


class TestNlpMorphConfig:
    def test_config_has_nlp_morph_topk(self):
        assert cfg.nlp_morph_topk == 3

    def test_config_has_nlp_morph_min_confidence(self):
        assert cfg.nlp_morph_min_confidence == pytest.approx(0.55)

    def test_config_has_nlp_morph_context_radius(self):
        assert cfg.nlp_morph_context_radius == 4

    def test_nlp_morph_topk_in_env_example(self):
        env_example = pathlib.Path("xops/env/.env.example").read_text()
        assert "NEGELIR_NLP_MORPH_TOPK" in env_example

    def test_nlp_morph_min_confidence_in_env_example(self):
        env_example = pathlib.Path("xops/env/.env.example").read_text()
        assert "NEGELIR_NLP_MORPH_MIN_CONFIDENCE" in env_example

    def test_nlp_morph_context_radius_in_env_example(self):
        env_example = pathlib.Path("xops/env/.env.example").read_text()
        assert "NEGELIR_NLP_MORPH_CONTEXT_RADIUS" in env_example

    def test_nlp_morph_ambiguous_max_per_query_in_env_example(self):
        env_example = pathlib.Path("xops/env/.env.example").read_text()
        assert "NEGELIR_NLP_MORPH_AMBIGUOUS_MAX_PER_QUERY" in env_example

    def test_config_has_nlp_morph_ambiguous_max_per_query(self):
        assert cfg.nlp_morph_ambiguous_max_per_query == 4

    def test_config_validation_allows_zero_morph_context_radius(self):
        custom_cfg = Config()
        custom_cfg.nlp_morph_context_radius = 0

        issues = custom_cfg.validate()

        assert all(
            not issue.startswith("nlp_morph_context_radius=")
            for issue in issues
        )


class TestNormalizeMorphCandidates:
    def test_selects_topk_by_confidence(self):
        candidates = [
            MorphCandidate(root="ev", suffix_class="locative", pos="noun", confidence=0.50),
            MorphCandidate(root="evi", suffix_class="dative", pos="noun", confidence=0.90),
            MorphCandidate(root="ev", suffix_class="ablative", pos="noun", confidence=0.60),
        ]

        result = normalize_morph_candidates(candidates, topk=2, min_confidence=0.75)

        assert [candidate.root for candidate in result] == ["evi", "ev"]
        assert result[0].ambiguity_class == "low"
        assert result[1].ambiguity_class == "high"

    def test_respects_cfg_nlp_morph_topk_and_deterministic_order(self):
        candidates = [
            MorphCandidate(root="ev", suffix_class="locative", pos="noun", confidence=0.65),
            MorphCandidate(root="ev", suffix_class="ablative", pos="noun", confidence=0.65),
            MorphCandidate(root="evi", suffix_class="dative", pos="noun", confidence=0.80),
            MorphCandidate(root="ev", suffix_class="accusative", pos="noun", confidence=0.60),
        ]

        result = normalize_morph_candidates(
            candidates,
            topk=cfg.nlp_morph_topk,
            min_confidence=cfg.nlp_morph_min_confidence,
        )

        assert len(result) == cfg.nlp_morph_topk
        assert [candidate.root for candidate in result] == ["evi", "ev", "ev"]
        assert [candidate.suffix_class for candidate in result] == ["dative", "ablative", "locative"]
        assert all(candidate.ambiguity_class == "low" for candidate in result)

    def test_tie_breaks_are_deterministic(self):
        candidates = [
            MorphCandidate(root="beta", suffix_class="genitive", pos="noun", confidence=0.70),
            MorphCandidate(root="alpha", suffix_class="genitive", pos="noun", confidence=0.70),
        ]

        result = normalize_morph_candidates(candidates, topk=2, min_confidence=0.55)

        assert [candidate.root for candidate in result] == ["alpha", "beta"]
        assert all(candidate.ambiguity_class == "low" for candidate in result)

    def test_normalize_morph_candidates_is_deterministic(self) -> None:
        """Same input produces byte-identical morphology candidate ordering across runs."""
        hypothesis = pytest.importorskip("hypothesis")
        from hypothesis import HealthCheck, given, seed as h_seed, settings
        from hypothesis.strategies import builds, floats, lists, sampled_from

        @h_seed(20260602)
        @settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
        @given(
            lists(
                builds(
                    MorphCandidate,
                    root=sampled_from(["ev", "evi", "galatasaray", "fenerbahçe", "anta"]),
                    suffix_class=sampled_from(["nominative", "dative", "ablative", "accusative", "genitive"]),
                    pos=sampled_from(["noun_common", "noun_proper", "verb", "adj"]),
                    confidence=floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
                ),
                min_size=1,
                max_size=8,
            )
        )
        def _inner(candidates: list[MorphCandidate]) -> None:
            first = normalize_morph_candidates(list(candidates), topk=cfg.nlp_morph_topk, min_confidence=cfg.nlp_morph_min_confidence)
            second = normalize_morph_candidates(list(candidates), topk=cfg.nlp_morph_topk, min_confidence=cfg.nlp_morph_min_confidence)

            assert first == second
            assert [
                (candidate.root, candidate.suffix_class, candidate.pos, candidate.confidence, candidate.ambiguity_class)
                for candidate in first
            ] == [
                (candidate.root, candidate.suffix_class, candidate.pos, candidate.confidence, candidate.ambiguity_class)
                for candidate in second
            ]

        _inner()

    def test_resolve_morph_candidates_prefers_gazetteer_match(self):
        candidates = [
            MorphCandidate(root="galatasaray", suffix_class="nominative", pos="noun_common", confidence=0.60),
            MorphCandidate(root="galata", suffix_class="dative", pos="noun_common", confidence=0.90),
        ]

        result = resolve_morph_candidates(
            candidates,
            gazetteer_roots={"galatasaray"},
        )

        assert result[0].root == "galatasaray"

    def test_resolve_morph_candidates_applies_intent_pos_preferences(self):
        candidates = [
            MorphCandidate(root="ev", suffix_class="nominative", pos="noun_common", confidence=0.90),
            MorphCandidate(root="Ev", suffix_class="nominative", pos="noun_proper", confidence=0.90),
        ]

        result = resolve_morph_candidates(
            candidates,
            intent_class="predict.match_outcome",
            pos_preferences=load_morph_pos_preferences(),
        )

        assert result[0].pos == "noun_proper"

    def test_resolve_morph_candidates_honors_context_preferred_pos(self):
        candidates = [
            MorphCandidate(root="fenerbahçe", suffix_class="nominative", pos="noun_common", confidence=0.90),
            MorphCandidate(root="Fenerbahçe", suffix_class="nominative", pos="noun_proper", confidence=0.90),
        ]

        result = resolve_morph_candidates(
            candidates,
            context_preferred_pos="noun_proper",
        )

        assert result[0].pos == "noun_proper"

    def test_zero_candidates_returns_empty(self):
        assert normalize_morph_candidates([], topk=3, min_confidence=0.55) == []

    def test_topk_must_be_at_least_one(self):
        with pytest.raises(ValueError, match="topk must be >= 1"):
            normalize_morph_candidates([], topk=0, min_confidence=0.55)

    def test_normalize_input_wires_morphology_candidates(self):
        candidates = [
            [
                MorphCandidate(root="ev", suffix_class="locative", pos="noun", confidence=0.50),
                MorphCandidate(root="evi", suffix_class="dative", pos="noun", confidence=0.90),
            ]
        ]

        result = normalize_input(
            "evde",
            cfg=cfg,
            _morph_candidates=candidates,
        )

        assert len(result.morphology_candidates) == 1
        assert result.morphology_candidates[0][0].root == "evi"
        assert result.morphology_candidates[0][0].ambiguity_class == "low"

    def test_normalize_input_emits_morph_parse_ambiguous_event(self):
        candidates = [
            [
                MorphCandidate(root="ev", suffix_class="locative", pos="noun", confidence=0.50),
                MorphCandidate(root="evi", suffix_class="dative", pos="noun", confidence=0.90),
            ]
        ]

        result = normalize_input(
            "evde",
            cfg=cfg,
            _morph_candidates=candidates,
        )

        assert len(result.morphology_events) == 1
        event = result.morphology_events[0]
        assert event["kind"] == "morph_parse_ambiguous"
        assert event["candidate_count"] == 2
        assert event["surface_form_sha8"] == hashlib.sha256("evde".encode("utf-8")).hexdigest()[:8]

    def test_normalize_input_sets_morph_ambiguity_budget_exhausted(self):
        candidates = [
            [MorphCandidate(root="x", suffix_class="nominative", pos="noun", confidence=0.40)]
            for _ in range(5)
        ]

        result = normalize_input(
            "a b c d e",
            cfg=cfg,
            _morph_candidates=candidates,
        )

        assert result.morph_ambiguity_budget_exhausted is True
        assert any(
            event["kind"] == "morph_ambiguity_budget_exhausted"
            for event in result.morphology_events
        )

    def test_normalize_input_proper_noun_skips_zemberek(self):
        candidates = [
            [
                MorphCandidate(root="Beşiktaş", suffix_class="nominative", pos="noun_proper", confidence=0.90),
                MorphCandidate(root="Beşik", suffix_class="dative", pos="noun_common", confidence=0.45),
            ]
        ]

        result = normalize_input(
            "Beşiktaş'tan",
            cfg=cfg,
            _morph_candidates=candidates,
            _morph_token_is_proper=[True],
        )

        assert len(result.morphology_candidates) == 1
        assert result.morphology_candidates[0] == ()
        assert len(result.morphology_events) == 1
        event = result.morphology_events[0]
        assert event["kind"] == "morph_proper_noun_bypassed"
        assert event["surface_form_sha8"] == hashlib.sha256("beşiktaş'tan".encode("utf-8")).hexdigest()[:8]

    def test_normalize_input_emits_morph_parse_unparseable_event(self):
        candidates: list[list[MorphCandidate]] = [[]]

        result = normalize_input(
            "emoji",
            cfg=cfg,
            _morph_candidates=candidates,
        )

        assert len(result.morphology_candidates) == 1
        assert result.morphology_candidates[0] == ()
        assert len(result.morphology_events) == 1
        event = result.morphology_events[0]
        assert event["kind"] == "morph_parse_unparseable"
        assert event["candidate_count"] == 0
        assert event["surface_form_sha8"] == hashlib.sha256("emoji".encode("utf-8")).hexdigest()[:8]
