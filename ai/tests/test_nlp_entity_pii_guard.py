"""Phase 10 §10.5 — PII guard at extraction.

Verifies that CRF spans whose joined token text matches a PII pattern
(phone number, e-mail, credit card) are:
  * removed from ExtractionResult.spans (not published in qa.intent.v1)
  * collected in ExtractionResult.pii_dropped (so the caller can emit
    nlp.alert.v1{kind=pii_detected_in_input, severity=warn})

Also covers the detect_pii() helper from ai/common/security/patterns.py
and verifies that non-PII CRF spans pass through unaffected.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from common.security.patterns import (
    PII_PHONE_RE,
    PII_EMAIL_RE,
    PII_CREDIT_CARD_RE,
    PII_PATTERNS,
    detect_pii,
)
from nlp.entity import (
    EntityExtractor,
    EntitySpan,
    ExtractionResult,
    CrfExtractor,
)
from nlp.lexicon_loader import LexiconStore


# -- detect_pii() unit tests -----------------------------------------------

class TestDetectPii:

    @pytest.mark.parametrize("text", [
        "0532 123 45 67",
        "05321234567",
        "+90 532 123 45 67",
        "+905321234567",
        "0090 532 123 45 67",
        "0090 212 555 01 23",
    ])
    def test_phone_detected(self, text):
        assert detect_pii(text) == "phone"

    @pytest.mark.parametrize("text", [
        "user@example.com",
        "foo.bar+tag@domain.co.uk",
        "test123@test.org",
    ])
    def test_email_detected(self, text):
        assert detect_pii(text) == "email"

    @pytest.mark.parametrize("text", [
        "4111 1111 1111 1111",
        "4111111111111111",
        "5500 0000 0000 0004",
        "3714 496353 98431",
        "6011 0009 9013 9424",
        "4222 2222 2222 2",
    ])
    def test_credit_card_detected(self, text):
        assert detect_pii(text) == "credit_card"

    @pytest.mark.parametrize("text", [
        "Galatasaray",
        "mac tahmini",
        "bugun saat 21:30",
        "2-0",
        "99",
        "",
        "1234",
    ])
    def test_safe_text_not_flagged(self, text):
        assert detect_pii(text) is None

    def test_pii_patterns_tuple_has_three_entries(self):
        assert len(PII_PATTERNS) == 3
        kinds = [k for k, _ in PII_PATTERNS]
        assert kinds == ["phone", "email", "credit_card"]


# -- ExtractionResult.pii_dropped field ------------------------------------

def test_extraction_result_has_pii_dropped_field():
    span = EntitySpan(0, 1, "date", "", 1.0, "", "crf")
    result = ExtractionResult(spans=[], ambiguous=[], pii_dropped=[span])
    assert result.pii_dropped == [span]


def test_extraction_result_pii_dropped_defaults_to_empty():
    span = EntitySpan(0, 1, "team", "gs", 1.0, "1.0", "gazetteer")
    result = ExtractionResult(spans=[span], ambiguous=[])
    assert result.pii_dropped == []


# -- EntityExtractor integration: PII spans are dropped -------------------

def _make_empty_store(tmp_path):
    lexdir = tmp_path / "lex"
    lexdir.mkdir()
    return LexiconStore(lexdir, max_rss_mb=0)


def _make_crf_that_returns(spans):
    mock_crf = MagicMock(spec=CrfExtractor)
    mock_crf.extract.return_value = spans
    return mock_crf


class TestPiiGuardIntegration:

    def test_phone_span_dropped(self, tmp_path):
        store = _make_empty_store(tmp_path)
        phone_span = EntitySpan(0, 4, "money_amount", "", 1.0, "", "crf")
        crf = _make_crf_that_returns([phone_span])
        extractor = EntityExtractor(store=store, crf=crf)
        tokens = ["0532", "123", "45", "67"]
        result = extractor.extract(tokens)
        assert result.spans == []
        assert len(result.pii_dropped) == 1
        assert result.pii_dropped[0] is phone_span

    def test_email_span_dropped(self, tmp_path):
        store = _make_empty_store(tmp_path)
        email_span = EntitySpan(0, 1, "ordinal", "", 1.0, "", "crf")
        crf = _make_crf_that_returns([email_span])
        extractor = EntityExtractor(store=store, crf=crf)
        tokens = ["user@example.com"]
        result = extractor.extract(tokens)
        assert result.spans == []
        assert result.pii_dropped == [email_span]

    def test_credit_card_span_dropped(self, tmp_path):
        store = _make_empty_store(tmp_path)
        cc_span = EntitySpan(0, 4, "score", "", 1.0, "", "crf")
        crf = _make_crf_that_returns([cc_span])
        extractor = EntityExtractor(store=store, crf=crf)
        tokens = ["4111", "1111", "1111", "1111"]
        result = extractor.extract(tokens)
        assert result.spans == []
        assert result.pii_dropped == [cc_span]

    def test_non_pii_crf_span_kept(self, tmp_path):
        store = _make_empty_store(tmp_path)
        date_span = EntitySpan(0, 1, "date", "", 1.0, "", "crf")
        crf = _make_crf_that_returns([date_span])
        extractor = EntityExtractor(store=store, crf=crf)
        tokens = ["bugun"]
        result = extractor.extract(tokens)
        assert result.spans == [date_span]
        assert result.pii_dropped == []

    def test_mixed_pii_and_safe_spans(self, tmp_path):
        store = _make_empty_store(tmp_path)
        safe_span = EntitySpan(0, 1, "date", "", 1.0, "", "crf")
        pii_span = EntitySpan(2, 6, "money_amount", "", 1.0, "", "crf")
        crf = _make_crf_that_returns([safe_span, pii_span])
        extractor = EntityExtractor(store=store, crf=crf)
        tokens = ["bugun", "saat", "0532", "123", "45", "67"]
        result = extractor.extract(tokens)
        assert result.spans == [safe_span]
        assert result.pii_dropped == [pii_span]

    def test_empty_input_no_pii_dropped(self, tmp_path):
        store = _make_empty_store(tmp_path)
        crf = _make_crf_that_returns([])
        extractor = EntityExtractor(store=store, crf=crf)
        result = extractor.extract([])
        assert result.pii_dropped == []

    def test_adversarial_no_false_positive_on_score(self, tmp_path):
        store = _make_empty_store(tmp_path)
        score_span = EntitySpan(0, 1, "score", "", 1.0, "", "crf")
        crf = _make_crf_that_returns([score_span])
        extractor = EntityExtractor(store=store, crf=crf)
        tokens = ["2-0"]
        result = extractor.extract(tokens)
        assert result.spans == [score_span]
        assert result.pii_dropped == []
