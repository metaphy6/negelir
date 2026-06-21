from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
import yaml

from nlp.quotative import detect_quotative_frame
from swarm.agents.nlp import NlpDispatcherAgent
from swarm.agents.topics import DATA_REQUEST_V1, NLP_EVENT_V1, PREDICT_REQUEST_V1, QA_INTENT_V1
from swarm.sdk.types import Message


def test_detects_direct_quote_marker_frame() -> None:
    detection = detect_quotative_frame("hocan diyor ki yarın 3-0 bitecekmiş")
    assert detection is not None
    assert detection.frame_class == "direct_quote_marker"
    assert detection.confidence >= 0.70
    assert detection.negated is False


def test_detects_social_media_attribution_frame() -> None:
    detection = detect_quotative_frame("twitter'da yazıyorlar galatasaray şampiyon")
    assert detection is not None
    assert detection.frame_class == "social_media_attribution"
    assert detection.confidence >= 0.70


def test_detects_negative_quotative_with_negation() -> None:
    detection = detect_quotative_frame("hic kimse demedi ki galatasaray kazanir")
    assert detection is not None
    assert detection.frame_class == "attributed_source"
    assert detection.negated is True


def test_nlp_quotative_frames_sha_pinned() -> None:
    with open("xops/versioning/chart.json", "r", encoding="utf-8") as fh:
        chart = json.load(fh)

    compat = chart.get("compatibility", {})
    data_files = compat.get("data_files", {})
    assert "quotative_frames" in data_files, "quotative_frames missing from chart.json compatibility"

    entry = data_files["quotative_frames"]
    assert entry["path"] == "ai/nlp/lang_tr/quotative_frames.tr.yaml"
    assert "sha256" in entry
    assert entry["cardinality"] == 4

    raw = yaml.safe_load(Path("ai/nlp/lang_tr/quotative_frames.tr.yaml").read_text(encoding="utf-8"))
    frame_classes = raw["frame_classes"]
    payload = {
        "frame_classes": {
            name: {
                "confidence": entry["confidence"],
                "patterns": entry["patterns"],
            }
            for name, entry in sorted(frame_classes.items())
        }
    }
    expected_sha = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert entry["sha256"] == expected_sha, "Chart SHA must match canonical quotative_frames digest"


def test_aspectual_stack_rules_chart_entry_is_pinned() -> None:
    with open("xops/versioning/chart.json", "r", encoding="utf-8") as fh:
        chart = json.load(fh)

    compat = chart.get("compatibility", {})
    data_files = compat.get("data_files", {})
    assert "aspectual_stacks" in data_files, "aspectual_stacks missing from chart.json compatibility"

    entry = data_files["aspectual_stacks"]
    assert entry["path"] == "ai/nlp/lang_tr/aspectual_stacks.tr.yaml"
    assert "sha256" in entry
    assert entry["cardinality"] == 6

    raw = yaml.safe_load(Path("ai/nlp/lang_tr/aspectual_stacks.tr.yaml").read_text(encoding="utf-8"))
    payload = {
        "stack_rules": [
            {
                "inner_aspect": rule["inner_aspect"],
                "outer_aspect": rule["outer_aspect"],
                "modality_class": rule["modality_class"],
                "confidence": rule["confidence"],
                "patterns": rule["patterns"],
            }
            for rule in raw["stack_rules"]
        ]
    }
    expected_sha = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert entry["sha256"] == expected_sha, "Chart SHA must match canonical aspectual_stacks digest"


def test_nlp_quotative_runs_in_pinned_order() -> None:
    source = inspect.getsource(NlpDispatcherAgent.handle)
    assert "detect_quotative_frame(normalized_text)" in source
    assert "if intent.startswith(\"predict.\")" in source
    assert source.index("detect_quotative_frame(normalized_text)") < source.index("if intent.startswith(\"predict.\")")


_GOLDEN_QUOTATIVE_CORPUS: list[tuple[str, str]] = [
    # direct_quote_marker examples
    ("hocan diyor ki yarın 3-0 bitecekmiş", "attributed_claim"),
    ("fenerbahçe dedi ki şampiyon olacak", "attributed_claim"),
    ("yazar der ki maç ertelendi", "attributed_claim"),
    ("site soyle yaziyor kazanmak için", "attributed_claim"),
    ("haber soyle diyor birlikte olacağız", "attributed_claim"),
    ("o soyle demis bugun oynamayacak", "attributed_claim"),
    ("arkadasim diyor ki bu sefer kazaniriz", "attributed_claim"),
    ("onlar dedi ki ben kazanacağım", "attributed_claim"),
    ("yazar der ki fırsat kaçmaz", "attributed_claim"),
    ("gazeteci soyle yaziyor sansimiz az", "attributed_claim"),
    # attributed_source examples
    ("e gore fenerbahçe kazanacak", "attributed_claim"),
    ("e gore galatasaray lider", "attributed_claim"),
    ("in dedigine gore mac ertelendi", "attributed_claim"),
    ("un aciklamasina gore sakat var", "attributed_claim"),
    ("unun kaynaklarina gore avantajimiz var", "attributed_claim"),
    ("in dedigine gore favori biziz", "attributed_claim"),
    ("un aciklamasina gore hakem hatali", "attributed_claim"),
    ("unun kaynaklarina gore transfer var", "attributed_claim"),
    ("in dedigine gore mac zor", "attributed_claim"),
    ("un dedigine gore puan kaybi yok", "attributed_claim"),
    # evidential_hearsay_compound examples
    ("mis bilinen bir haber", "attributed_claim"),
    ("miş bilinen bir iddia", "attributed_claim"),
    ("mus bilinen rapor", "attributed_claim"),
    ("muş bilinen sonuç", "attributed_claim"),
    ("müş bilinen veriler", "attributed_claim"),
    ("bilinen mis haber", "attributed_claim"),
    ("soylenen mis haber", "attributed_claim"),
    ("söylenen miş iddia", "attributed_claim"),
    ("iddia edilen mus rapor", "attributed_claim"),
    ("bilinen muş bir olay", "attributed_claim"),
    # social_media_attribution examples
    ("twitter'da yazıyorlar galatasaray şampiyon", "event_only"),
    ("sosyal medyada diyorlar fenerbahçe kazanacak", "event_only"),
    ("forumda yazıyorlar mac bugun", "event_only"),
    ("internette soyle yaziyorlar yeni star", "event_only"),
    ("twitterda yaziyorlar mac var", "event_only"),
    # negative quotative examples
    ("hic kimse demedi ki galatasaray kazanir", "attributed_claim"),
    ("kimse demedi ki mac bugun kazanacak", "attributed_claim"),
    ("hic kimse soylemedi ki fenerbahce lider olacak", "attributed_claim"),
    ("biri demedi ki mac iptal", "attributed_claim"),
    ("biri nasil demedi ki takim kazanacak", "attributed_claim"),
]


def _make_intent_msg(normalized_text: str) -> Message:
    request_id = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]
    qa_correlation_id = hashlib.sha256((normalized_text + "-corr").encode("utf-8")).hexdigest()[:16]
    return Message.new(
        topic=QA_INTENT_V1,
        payload={
            "request_id": request_id,
            "qa_correlation_id": qa_correlation_id,
            "intent": "predict.match_outcome",
            "entities": [],
            "intent_model_version": "1.0.0",
            "intent_calibration_version": "1.0.0",
            "normalized_text": normalized_text,
            "locale": "tr-TR",
            "emitted_at": "2026-05-27T10:00:00+00:00",
        },
    )


def test_nlp_quotative_golden_corpus_never_routes_predict() -> None:
    agent = NlpDispatcherAgent(
        clock_iso=lambda: "2026-05-27T10:00:00+00:00",
        new_id=lambda: "test-corr-id",
    )

    for text, expected in _GOLDEN_QUOTATIVE_CORPUS:
        results = list(agent.handle(_make_intent_msg(text)))
        assert all(
            r.envelope.topic != PREDICT_REQUEST_V1 for r in results
        ), f"Predict leaked for quotative example: {text!r}"
        assert len(results) > 0, f"No routing result for quotative example: {text!r}"
        if expected == "attributed_claim":
            assert any(
                r.envelope.topic == DATA_REQUEST_V1
                and r.payload["kind"] == "attributed_claim"
                for r in results
            ), f"Expected attributed_claim route for quotative example: {text!r}"
        else:
            assert any(
                r.envelope.topic == NLP_EVENT_V1 for r in results
            ), f"Expected event for social media example: {text!r}"


def test_nlp_quotative_hypothesis_non_predict_routing() -> None:
    hypothesis = pytest.importorskip("hypothesis")
    settings = pytest.importorskip("hypothesis.settings")
    st = pytest.importorskip("hypothesis.strategies")

    frame_prefixes = st.sampled_from([
        "hocan diyor ki",
        "fenerbahçe dedi ki",
        "yazar der ki",
        "site soyle yaziyor",
        "haber soyle diyor",
        "o soyle demis",
        "arkadasim diyor ki",
        "onlar dedi ki",
        "yazar der ki",
        "gazeteci soyle yaziyor",
        "be gore",
        "fenerbahçe'nin dedigine gore",
        "rakibin kaynaklarina gore",
        "kazanmış bilinen",
        "geldi miş söylenen",
        "twitter'da yazıyorlar",
        "sosyal medyada yazıyorlar",
        "forumda yazıyorlar",
        "internette yazıyorlar",
        "hic kimse demedi ki",
    ])
    predict_clauses = st.sampled_from([
        "yarın 3-0 bitecekmiş",
        "galatasaray kazanacak",
        "fenerbahçe şampiyon",
        "maç geç başlayacak",
        "takım lider olacak",
        "kartal maçı kazanacak",
    ])
    intents = st.sampled_from([
        "predict.match_outcome",
        "predict.match_outcome.conditional",
        "predict.over_under",
        "predict.btts",
        "predict.handicap",
        "predict.score_grid",
    ])

    @hypothesis.given(prefix=frame_prefixes, clause=predict_clauses, intent=intents)
    @hypothesis.settings(max_examples=200)
    def inner(prefix: str, clause: str, intent: str) -> None:
        agent = NlpDispatcherAgent(
            clock_iso=lambda: "2026-05-27T10:00:00+00:00",
            new_id=lambda: "test-corr-id",
        )
        text = f"{prefix} {clause}"
        results = list(agent.handle(_make_intent_msg(text)))
        assert all(
            r.envelope.topic != PREDICT_REQUEST_V1 for r in results
        ), f"Predict leaked for quotative compound: {text!r}"

    inner()
