"""Tests for the Phase 10 empty-input floor gate (§10.24.13)."""
from __future__ import annotations

import json
from pathlib import Path

from common.config import cfg
from swarm.agents.nlp import NlpIntentAgent
from swarm.agents.topics import NLP_EVENT_V1, QA_ANSWER_V1, QA_REQUEST_V1
from swarm.sdk.types import Message

from nlp.normalize import _looks_like_fragment


def _make_qa_request_v1_msg(text: str, request_id: str = "req-001") -> Message:
    return Message.new(
        topic=QA_REQUEST_V1,
        payload={
            "request_id": request_id,
            "locale": "tr-TR",
            "sanitized_text": text,
            "sec_verdict": "pass",
            "emitted_at": "2026-06-03T12:00:00+00:00",
        },
        producer="sec.input.v1",
    )


def test_nlp_empty_input_returns_canned_help_no_pipeline() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert answer[0].payload["intent"] == "meta.help"
    assert answer[0].payload["kind"] == "meta.help"
    assert "Bana bir maç ya da takım sorabilirsin" in answer[0].payload["answer_text"]
    assert events[0].payload["kind"] == "empty_input_floor_response"


def test_nlp_whitespace_only_input_handled() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("   ", request_id="req-002")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]

    assert len(answer) == 1
    assert answer[0].payload["intent"] == "meta.help"
    assert answer[0].payload["kind"] == "meta.help"


def test_nlp_url_only_input_routes_meta_url_only_input() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("https://example.com/fb", request_id="req-008")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.url_only_input"
    assert answer[0].payload["intent"] == "meta.url_only_input"
    assert answer[0].payload["kind"] == "meta.url_only_input"
    assert "bağlantı" in answer[0].payload["answer_text"]


def test_nlp_partial_input_routes_meta_likely_partial_input() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("Gala", request_id="req-010")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert events[0].payload["kind"] == "partial_input_completion_offered"
    assert events[0].payload["completions"]
    assert answer[0].payload["intent"] == "meta.likely_partial_input"
    assert answer[0].payload["kind"] == "meta.likely_partial_input"
    assert "Belki" in answer[0].payload["answer_text"]
    assert events[0].payload["completions"][0] in answer[0].payload["answer_text"]


def test_nlp_single_emoji_intent_routes_meta_single_emoji_intent() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("⚽", request_id="req-011")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.single_emoji_intent"
    assert answer[0].payload["intent"] == "meta.single_emoji_intent"
    assert answer[0].payload["kind"] == "meta.single_emoji_intent"
    assert "emoji" in answer[0].payload["answer_text"].lower() or "sormak" in answer[0].payload["answer_text"].lower()


def test_nlp_structured_input_refusal_routes_meta_structured_input_refused() -> None:
    agent = NlpIntentAgent()
    out = list(
        agent.handle(
            _make_qa_request_v1_msg(
                "```json\n{\"query\": \"Galatasaray\"}\n```",
                request_id="req-009",
            )
        )
    )
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.structured_input_refused"
    assert answer[0].payload["intent"] == "meta.structured_input_refused"
    assert answer[0].payload["kind"] == "meta.structured_input_refused"


def test_nlp_structured_input_refusal_corpus() -> None:
    agent = NlpIntentAgent()
    corpus = [
        # JSON objects and arrays
        '{"query": "Galatasaray"}',
        '{"team": "Fenerbahçe", "date": "2026-06-07"}',
        '["Galatasaray", "Beşiktaş"]',
        '{"nested": {"key": "value"}}',
        '{"match": {"home": "Galatasaray", "away": "Fenerbahçe"}}',
        '{"players": ["Mert", "Arda"]}',
        '{"status": "ok", "count": 1}',
        '{"query": ""}',
        '{"team": null}',
        '{"venue": "Şükrü Saraçoğlu"}',

        # YAML examples (valid YAML documents)
        'team: Galatasaray\ndate: 2026-06-07',
        '- Galatasaray\n- Fenerbahçe\n- Beşiktaş',
        'query: Galatasaray\nlimit: 5',
        'venue: "Şükrü Saraçoğlu"\ncity: Istanbul',
        'flags: [yes, no]\nenabled: true',
        'match:\n  home: Galatasaray\n  away: Fenerbahçe',
        'coach: "Okan"\nassistant: "Volkan"',
        'players:\n  - Mert\n  - Arda',
        'metadata:\n  event: derby\n  round: 30',
        'settings:\n  debug: false\n  retries: 3',

        # XML examples
        '<match><home>Galatasaray</home><away>Fenerbahçe</away></match>',
        '<team>Galatasaray</team>',
        '<root><query>Maç tahmini</query></root>',
        '<schedule><date>2026-06-07</date></schedule>',
        '<players><player>Mert</player><player>Arda</player></players>',
        '<venue name="Şükrü Saraçoğlu"/>',
        '<city>Istanbul</city>',
        '<fixture><home>GS</home><away>FB</away></fixture>',
        '<data><value>42</value></data>',
        '<document><body>test</body></document>',

        # Markdown-fenced blocks
        '```yaml\\nteam: Galatasaray\\n```',
        '```json\\n{"query": "Galatasaray"}\\n```',
        '~~~json\\n{"team": "Fenerbahçe"}\\n~~~',
        '```xml\\n<root><team>Galatasaray</team></root>\\n```',
        '```text\\n- Galatasaray\\n- Beşiktaş\\n```',
        '```yaml\\n- home: Galatasaray\\n  away: Fenerbahçe\\n```',
        '```json\\n["Galatasaray", "Fenerbahçe"]\\n```',
        '```json\\n{"team": null}\\n```',
        '~~~yaml\\ncoach: Okan\\nassistant: Volkan\\n~~~',
        '```xml\\n<venue>Şükrü Saraçoğlu</venue>\\n```',
        '```json\\n{"query": ""}\\n```',
        '~~~xml\n<root><team>Galatasaray</team></root>\n~~~',
        '```notjson\\nfoo: bar\\n```',
    ]

    for index, text in enumerate(corpus, start=1):
        out = list(agent.handle(_make_qa_request_v1_msg(text, request_id=f"req-structured-{index:03d}")))
        answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
        events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

        assert len(answer) == 1, f"expected one answer for structured input corpus row {index}"
        assert len(events) == 1, f"expected one event for structured input corpus row {index}"
        assert events[0].payload["kind"] == "meta.structured_input_refused"
        assert answer[0].payload["intent"] == "meta.structured_input_refused"
        assert answer[0].payload["kind"] == "meta.structured_input_refused"


def test_nlp_single_char_input_handled() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("a", request_id="req-003")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.unsupported_too_short"
    assert any(m.payload["intent"] == "meta.help" for m in out if m.envelope.topic == QA_ANSWER_V1)


def test_nlp_all_punctuation_input_handled() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("!!!???", request_id="req-004")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.unsupported_too_short"
    assert any(m.payload["intent"] == "meta.help" for m in out if m.envelope.topic == QA_ANSWER_V1)


def test_nlp_fragment_input_detected() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("Galatasaray ve", request_id="req-006")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]

    assert len(events) == 1
    assert events[0].payload["kind"] == "meta.unsupported_fragment"
    assert len(answer) == 1
    assert answer[0].payload["intent"] == "meta.fragment_detected"
    assert answer[0].payload["kind"] == "meta.fragment_detected"
    assert "eksik kalmış" in answer[0].payload["answer_text"]


def test_nlp_fragment_negative_corpus_allowlist_passes() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("skor nasıl", request_id="req-007")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert all(event.payload["kind"] != "meta.unsupported_fragment" for event in events)


def test_nlp_fragment_positive_corpus_triggers_detector() -> None:
    path = Path(__file__).parent / "fixtures" / "fragment_positive_corpus.tr.json"
    with path.open("r", encoding="utf-8") as fh:
        positives = json.load(fh)

    assert len(positives) >= 25
    for text in positives:
        assert _looks_like_fragment(text, cfg=cfg), f"expected fragment detector to fire for: {text}"


def test_nlp_fragment_negative_corpus_fp_rate_below_three_percent() -> None:
    from nlp.normalize import _load_fragment_negative_corpus

    negatives = _load_fragment_negative_corpus()
    assert len(negatives) >= 30

    false_positives = [text for text in negatives if _looks_like_fragment(text, cfg=cfg)]
    assert len(false_positives) / len(negatives) <= 0.03, (
        f"fragment false positive rate too high: {len(false_positives)}/{len(negatives)}"
    )


def test_nlp_complete_query_with_postposition_does_not_floor() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("Galatasaray maçı ne zaman", request_id="req-007")))
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert all(event.payload["kind"] != "meta.unsupported_fragment" for event in events)


def test_nlp_greeting_input_returns_help_with_safe_echo() -> None:
    agent = NlpIntentAgent()
    out = list(agent.handle(_make_qa_request_v1_msg("selam", request_id="req-005")))
    answer = [m for m in out if m.envelope.topic == QA_ANSWER_V1]
    events = [m for m in out if m.envelope.topic == NLP_EVENT_V1]

    assert len(answer) == 1
    assert len(events) == 1
    assert answer[0].payload["intent"] == "meta.help"
    assert "Selam!" in answer[0].payload["answer_text"]
    assert events[0].payload["kind"] == "greeting_input_floor_response"


def test_nlp_greetings_table_is_closed_set() -> None:
    from nlp.normalize import _load_greetings

    greetings = _load_greetings()
    assert greetings == {
        "merhaba",
        "selam",
        "selamün aleyküm",
        "slm",
        "meraba",
        "merhabalar",
    }
