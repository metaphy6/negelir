"""Tests for Turkish PII detection and redaction helpers."""
from __future__ import annotations

from common.security.tr_pii import (
    detect_tr_pii_spans,
    parse_redacted_tr_pii,
    redact_tr_pii,
)


def test_detects_valid_tc_kimlik() -> None:
    spans = detect_tr_pii_spans('lutfen tc kimligim 10000000146 yazmam')
    assert [span.kind for span in spans] == ['tc_kimlik']
    assert spans[0].start >= 0
    assert spans[0].end > spans[0].start


def test_redacts_phone_and_keeps_raw_absent() -> None:
    redacted, spans = redact_tr_pii('Arayın 0555-123-4567 lütfen')
    assert '0555-123-4567' not in redacted
    assert '[REDACTED:PHONE_TR:sha8=' in redacted
    assert len(spans) == 1
    assert spans[0].kind == 'phone_tr'


def test_parse_redacted_tr_pii_returns_kind_and_subject() -> None:
    text = 'Merhaba [REDACTED:TC_KIMLIK:sha8=deadbeef] selam'
    found = parse_redacted_tr_pii(text)
    assert found == [('tc_kimlik', 'deadbeef')]


def test_redact_tr_pii_is_idempotent() -> None:
    text = 'Arayın 0555-123-4567 lütfen'
    redacted, _ = redact_tr_pii(text)
    redacted_again, _ = redact_tr_pii(redacted)
    assert redacted_again == redacted
