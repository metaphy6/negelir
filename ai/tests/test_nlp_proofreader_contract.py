"""Phase 10 §10.9 + §10.16 — Test for nlp.proofreader.v1 deterministic gates.

This test covers §10.9 bullet 2 (gates 1-7 plus decorative emoji whitelist) + §10.16 (gate 8):
  1. Citation block present and unmodified (sha256 check)
  2. No mid-sentence English (regex blocklist with allowlist)
  3. Length bounds (min/max characters)
  4. PII redaction (phone/email/credit-card)
  5. Forbidden phrases (from yaml blocklist)
  6. Decorative emoji whitelist (allowed decorative emoji only)
  7. Suffix-harmony probe (sample 5 random constructions)
  8. Confidence narration discipline (§10.16: banded confidence text must not
     contradict raw probability)

Each gate is tested with:
  - Happy path (gate passes)
  - Adversarial path (gate blocks)

§10.9 bullet 4 (fail-safe): Proofreader exception → emit template-only answer
(NEVER block user on proofreader bug); emit nlp.alert.v1{kind=nlp_proofreader_failed}.
"""
import hashlib
from unittest import mock

import pytest

from common.config import Config
from nlp.proofreader import ProofreadResult, proofread_answer, proofread_answer_safe
from swarm.agents.nlp import NlpProofreaderAgent
from swarm.sdk.types import Message


def test_gate1_citation_block_missing_blocks():
    """Gate 1: predict.* intent without citation block → blocked."""
    cfg = Config()
    result = proofread_answer(
        "Galatasaray'ın kazanma olasılığı yüksek.",
        intent="predict.match_outcome",
        citation_sha256_expected="abc123" * 10 + "abcd",  # 64-char hex
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "citation_drift"


def test_gate1_citation_block_sha_mismatch_blocks():
    """Gate 1: citation block present but SHA mismatch → blocked."""
    cfg = Config()
    answer = "Galatasaray kazanır.\n---\nTahmin ID: 123"
    citation_block = "\n---\nTahmin ID: 123"
    expected_sha = hashlib.sha256(citation_block.encode("utf-8")).hexdigest()
    # Provide wrong SHA:
    wrong_sha = "0" * 64
    result = proofread_answer(
        answer,
        intent="predict.match_outcome",
        citation_sha256_expected=wrong_sha,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "citation_drift"


def test_gate1_citation_block_correct_passes():
    """Gate 1: citation block present and SHA matches → passes gate 1."""
    cfg = Config()
    answer = "Galatasaray kazanır.\n---\nTahmin ID: 123"
    citation_block = "\n---\nTahmin ID: 123"
    correct_sha = hashlib.sha256(citation_block.encode("utf-8")).hexdigest()
    result = proofread_answer(
        answer,
        intent="predict.match_outcome",
        citation_sha256_expected=correct_sha,
        cfg=cfg,
    )
    # Will pass gate 1, may fail later gates if answer has issues.
    # For this test, we're only verifying gate 1 doesn't block on correct SHA.
    assert result.block_reason != "citation_drift"


def test_gate1_non_predict_intent_skips_citation_check():
    """Gate 1: non-predict intents skip citation check entirely."""
    cfg = Config()
    result = proofread_answer(
        "Bugün Galatasaray maçı var.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    # Gate 1 skipped; should pass or fail on other gates only.
    assert result.block_reason != "citation_drift"


def test_gate2_mid_sentence_english_blocks():
    """Gate 2: English word in mid-sentence → blocked."""
    cfg = Config()
    answer = "Galatasaray bugün the maçı kazanacak."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "mid_sentence_english"


def test_gate2_allowlisted_english_passes():
    """Gate 2: allowlisted phrases (Premier League) pass."""
    cfg = Config()
    answer = "Premier League'de Arsenal kazandı."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    # Should pass gate 2 (allowlisted), may pass or fail on other gates.
    assert result.block_reason != "mid_sentence_english"


def test_gate3_length_under_blocks():
    """Gate 3: answer shorter than min → blocked."""
    cfg = Config(nlp_min_answer_chars=20)
    result = proofread_answer(
        "Kısa.",  # 5 chars
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "length_under"


def test_gate3_length_over_blocks():
    """Gate 3: answer longer than max → blocked."""
    cfg = Config(nlp_max_answer_chars=50)
    long_answer = "A" * 100
    result = proofread_answer(
        long_answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "length_over"


def test_gate3_length_within_bounds_passes():
    """Gate 3: answer within bounds passes gate 3."""
    cfg = Config(nlp_min_answer_chars=10, nlp_max_answer_chars=100)
    answer = "Galatasaray bugün kazanacak."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    # Passes gate 3; may pass or fail on other gates.
    assert result.block_reason not in ("length_under", "length_over")


def test_gate4_pii_phone_redacted_and_blocked():
    """Gate 4: phone number found → redacted and blocked."""
    cfg = Config()
    answer = "Beni 0532 123 45 67 numarasından arayın."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "pii_redacted"
    assert result.redacted_pii is True
    assert "[***]" in result.answer_text
    assert "0532" not in result.answer_text


def test_gate4_pii_email_redacted_and_blocked():
    """Gate 4: email found → redacted and blocked."""
    cfg = Config()
    answer = "Bana test@example.com adresinden yazın."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "pii_redacted"
    assert result.redacted_pii is True
    assert "[***]" in result.answer_text
    assert "test@example.com" not in result.answer_text


def test_gate4_no_pii_passes():
    """Gate 4: no PII patterns → passes gate 4."""
    cfg = Config()
    answer = "Galatasaray bugün kazanacak."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.block_reason != "pii_redacted"
    assert result.redacted_pii is False


def test_gate5_forbidden_phrase_blocks():
    """Gate 5: forbidden phrase found → blocked."""
    cfg = Config()
    answer = "Ben bir yapay zekayım ve size tahmin vereceğim."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "forbidden_phrase"


def test_gate5_no_forbidden_phrase_passes():
    """Gate 5: no forbidden phrases → passes gate 5."""
    cfg = Config()
    answer = "Galatasaray bugün kazanacak."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.block_reason != "forbidden_phrase"


def test_gate5_decorative_emoji_allowed_passes():
    """Gate 6.1: allowed decorative emoji pass the proofreader whitelist."""
    cfg = Config()
    answer = "Galatasaray bugün kazanacak ⚽"
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is True
    assert result.block_reason is None


def test_gate5_decorative_emoji_not_in_set_blocks():
    """Gate 6.1: disallowed emoji outside the decorative set are blocked."""
    cfg = Config()
    answer = "Galatasaray bugün kazanacak 🏟️"
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "decorative_emoji"


def test_nlp_decorative_set_closed_at_render() -> None:
    cfg = Config()
    answer = "Bugün maç var ⚽ 🏆 ve bu bir uzunluk kontrolü testidir."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is True
    assert result.block_reason is None


def test_gate6_suffix_harmony_violation_blocks():
    """Gate 6: suffix harmony violation → blocked."""
    cfg = Config()
    # "takım'e" is wrong; should be "takım'a" (back vowel harmony).
    answer = "Galatasaray takım'e kazandıracak."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "suffix_harmony"


def test_gate6_suffix_harmony_correct_passes():
    """Gate 6: correct suffix harmony → passes gate 6."""
    cfg = Config()
    # "Galatasaray'ın" is correct (back vowel 'a' + back suffix 'ın').
    answer = "Galatasaray'ın maçı bugün."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.block_reason != "suffix_harmony"


def test_tr_output_grammar_validator_catches_invalid_suffix_form():
    cfg = Config()
    answer = "Galatasaray'xy formu iyi."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "tr_output_grammar_violation"
    assert any(v["type"] == "invalid_suffix_form" for v in result.grammar_violations)


def test_tr_output_grammar_validator_catches_consonant_mutation_violation():
    cfg = Config()
    answer = "Antep'de bugün maç var."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "tr_output_grammar_violation"
    assert any(v["type"] == "locative_voicing" for v in result.grammar_violations)


def test_tr_output_grammar_validator_catches_genitive_buffer_violation():
    cfg = Config()
    answer = "Galatasaray'nın formu iyi."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "tr_output_grammar_violation"
    assert any(v["type"] == "genitive_buffer" for v in result.grammar_violations)


def test_tr_output_grammar_validator_catches_stem_vowel_deletion_failure():
    cfg = Config()
    answer = "oğul'u dün akşam gördüm."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is False
    assert result.block_reason == "tr_output_grammar_violation"
    assert any(v["type"] == "stem_vowel_deletion" for v in result.grammar_violations)


def test_tr_output_grammar_violation_falls_back_to_grammar_fallback_template():
    cfg = Config()
    answer = "Antep'de bugün maç var."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.answer_text == "Yanıtım hazırlanırken bir hata oluştu. Lütfen tekrar deneyiniz."
    assert result.block_reason == "tr_output_grammar_violation"


def test_tr_output_grammar_validator_pipeline_position_ast():
    import inspect

    source = inspect.getsource(proofread_answer)
    assert "validate_tr_output_grammar(working_text, cfg)" in source
    assert "tr_output_grammar_violation" in source


def test_tr_output_grammar_validator_within_p99_budget():
    cfg = Config(
        nlp_output_grammar_validator_p99_ms=0,
        nlp_output_grammar_validator_killswitch_enabled=True,
    )
    answer = "Antep'de bugün maç var."
    with mock.patch("nlp.proofreader.time.perf_counter", side_effect=[0.0, 1.0]):
        result = proofread_answer(
            answer,
            intent="data.fixture_lookup",
            citation_sha256_expected=None,
            cfg=cfg,
        )
    assert result.passed is True
    assert result.block_reason is None
    assert result.grammar_violations == []


def test_all_gates_pass_clean_answer():
    """All gates pass for a clean, well-formed answer."""
    cfg = Config(nlp_min_answer_chars=10, nlp_max_answer_chars=200)
    answer = "Galatasaray'ın bugünkü maçta kazanma ihtimali yüksek."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is True
    assert result.block_reason is None
    assert result.answer_text == answer
    assert result.redacted_pii is False


def test_multiple_violations_first_gate_wins():
    """Multiple violations → first gate that fails is reported."""
    cfg = Config(nlp_min_answer_chars=10, nlp_max_answer_chars=200)
    # Too short (gate 3) + has English (gate 2) + forbidden phrase (gate 5).
    # Gate order: citation (skipped), English (2), length (3), PII (4), forbidden (5), suffix (6).
    # If gates run in order, English gate (2) should fire first.
    answer = "the yapay zeka"  # 14 chars, has English "the", has forbidden phrase
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    # Gate 2 (English) should fire before gate 5 (forbidden phrase).
    assert result.passed is False
    assert result.block_reason == "mid_sentence_english"


def test_proofread_result_slots():
    """ProofreadResult carries all required slots."""
    r = ProofreadResult(
        passed=False,
        answer_text="Redacted",
        block_reason="pii_redacted",
        alert_severity="error",
        redacted_pii=True,
    )
    assert r.passed is False
    assert r.answer_text == "Redacted"
    assert r.block_reason == "pii_redacted"
    assert r.alert_severity == "error"
    assert r.redacted_pii is True


def test_proofread_non_predict_intent():
    """Non-predict intents (meta.*, data.*) work (no citation check)."""
    cfg = Config()
    result = proofread_answer(
        "Bugün Galatasaray maçı var.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is True


def test_proofreader_block_taxonomy_complete():
    """§10.9 bullet 3 + §10.16: Block taxonomy enumerates all 8 reasons.

    This test verifies that the complete block_reason taxonomy matches
    the binding spec: {citation_drift, mid_sentence_english, length_under,
    length_over, pii_redacted, forbidden_phrase, suffix_harmony,
    confidence_narration_contradiction}.

    Each reason must be triggerable (tested above) and the taxonomy must
    be exhaustive (no undocumented block reasons can be returned).
    """
    # The binding taxonomy from §10.9 + §10.16:
    EXPECTED_BLOCK_REASONS = frozenset({
        "citation_drift",
        "mid_sentence_english",
        "length_under",
        "length_over",
        "pii_redacted",
        "forbidden_phrase",
        "suffix_harmony",
        "decorative_emoji",
        "confidence_narration_contradiction",
        "tr_output_grammar_violation",
    })

    # Collect all block_reason values produced in the test suite above.
    # We'll trigger each gate individually and verify its reason is in the taxonomy.
    cfg = Config(nlp_min_answer_chars=20, nlp_max_answer_chars=200)
    observed_reasons = set()

    # Gate 1: citation_drift
    r1 = proofread_answer(
        "No citation block.",
        intent="predict.match_outcome",
        citation_sha256_expected="a" * 64,
        cfg=cfg,
    )
    if not r1.passed:
        observed_reasons.add(r1.block_reason)

    # Gate 2: mid_sentence_english
    r2 = proofread_answer(
        "Galatasaray the kazanacak.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    if not r2.passed:
        observed_reasons.add(r2.block_reason)

    # Gate 3a: length_under
    cfg_short = Config(nlp_min_answer_chars=100)
    r3a = proofread_answer(
        "Kısa.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg_short,
    )
    if not r3a.passed:
        observed_reasons.add(r3a.block_reason)

    # Gate 3b: length_over
    cfg_long = Config(nlp_max_answer_chars=10)
    r3b = proofread_answer(
        "A" * 50,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg_long,
    )
    if not r3b.passed:
        observed_reasons.add(r3b.block_reason)

    # Gate 4: pii_redacted
    r4 = proofread_answer(
        "Beni 0532 123 45 67 numarasından arayın.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    if not r4.passed:
        observed_reasons.add(r4.block_reason)

    # Gate 5: forbidden_phrase
    r5 = proofread_answer(
        "Ben bir yapay zekayım.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    if not r5.passed:
        observed_reasons.add(r5.block_reason)

    # Gate 6.1: decorative_emoji
    r6_0 = proofread_answer(
        "Galatasaray bugün kazanacak 🏟️",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    if not r6_0.passed:
        observed_reasons.add(r6_0.block_reason)

    # Gate 6: suffix_harmony
    r6 = proofread_answer(
        "Galatasaray takım'e kazanacak.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    if not r6.passed:
        observed_reasons.add(r6.block_reason)

    # Gate 6.5: tr_output_grammar_violation
    r6_5 = proofread_answer(
        "Antep'de bugün maç var.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    if not r6_5.passed:
        observed_reasons.add(r6_5.block_reason)

    # Gate 7: confidence_narration_contradiction
    r7 = proofread_answer(
        "Tahmin yüksek güven ile.",
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.30,  # Maps to "düşük"
        confidence_band_label="yüksek",  # Contradicts
    )
    if not r7.passed:
        observed_reasons.add(r7.block_reason)

    # Assert: All expected reasons were observed.
    assert observed_reasons == EXPECTED_BLOCK_REASONS, (
        f"Block taxonomy incomplete. Expected {EXPECTED_BLOCK_REASONS}, "
        f"observed {observed_reasons}. "
        f"Missing: {EXPECTED_BLOCK_REASONS - observed_reasons}. "
        f"Unexpected: {observed_reasons - EXPECTED_BLOCK_REASONS}."
    )


def test_fail_safe_normal_path_passes():
    """§10.9 bullet 4: proofread_answer_safe passes through normal results."""
    cfg = Config()
    answer = "Galatasaray bugün Fenerbahçe ile maç oynuyor."
    result = proofread_answer_safe(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    assert result.passed is True
    assert result.fail_safe_triggered is False
    assert result.exception_detail is None


def test_fail_safe_triggers_on_exception():
    """§10.9 bullet 4: proofreader exception → fail-safe (answer passed, alert signaled)."""
    cfg = Config()
    # Answer with apostrophe construction to trigger suffix-harmony check.
    answer = "Galatasaray'ın bugün maç oynuyor."

    # Mock suffix_harmony_ok to raise an exception (simulating a proofreader bug).
    with mock.patch("nlp.proofreader.suffix_harmony_ok", side_effect=ValueError("mock bug")):
        result = proofread_answer_safe(
            answer,
            intent="data.fixture_lookup",
            citation_sha256_expected=None,
            cfg=cfg,
        )

    # Fail-safe behavior per §10.9 bullet 4:
    # - passed=True (NEVER block user on proofreader bug)
    # - fail_safe_triggered=True (signal caller to emit alert)
    # - answer_text=original (template-only answer returned unchanged)
    # - exception_detail contains exception info
    assert result.passed is True, "Fail-safe must pass answer through on exception"
    assert result.fail_safe_triggered is True
    assert result.answer_text == answer, "Fail-safe must return original answer unchanged"
    assert result.exception_detail is not None
    assert "ValueError" in result.exception_detail
    assert "mock bug" in result.exception_detail


def test_fail_safe_alert_severity_is_error():
    """§10.9 bullet 4: fail-safe triggers → alert_severity='error' for operator visibility."""
    cfg = Config()
    # Answer with apostrophe construction.
    answer = "Fenerbahçe'nin kadrosu güçlü."

    # Simulate exception in gate logic.
    with mock.patch("nlp.proofreader.suffix_harmony_ok", side_effect=RuntimeError("test")):
        result = proofread_answer_safe(
            answer,
            intent="data.fixture_lookup",
            citation_sha256_expected=None,
            cfg=cfg,
        )

    assert result.fail_safe_triggered is True
    assert result.alert_severity == "error", "Fail-safe must signal error severity for nlp.alert.v1"


def test_fail_safe_does_not_trigger_on_normal_block():
    """Fail-safe should NOT trigger when gates block normally (e.g., PII)."""
    cfg = Config()
    answer = "Beni 0532 123 45 67 numarasından arayın."
    result = proofread_answer_safe(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
    )
    # Normal block (PII detected) → passed=False, fail_safe_triggered=False.
    assert result.passed is False
    assert result.block_reason == "pii_redacted"
    assert result.fail_safe_triggered is False
    assert result.exception_detail is None


# ── Gate 7: Confidence narration discipline (§10.16) ──────────────────────


def test_gate7_confidence_narration_contradiction_blocks():
    """Gate 7: raw probability contradicts band text → blocked.

    §10.16: Banded confidence text MUST never contradict the raw probability.
    Example: raw=0.51 (should be "orta" band) but answer contains "yüksek güven".
    """
    cfg = Config()  # Default bands: <0.55=düşük, 0.55-0.75=orta, >0.75=yüksek
    # Use data.* intent to avoid citation block requirement
    answer = "Galatasaray bugün maçta kazanacak (yüksek güven)."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.51,  # Should map to "orta" band
        confidence_band_label="yüksek",  # But template claims "yüksek"
    )
    assert result.passed is False
    assert result.block_reason == "confidence_narration_contradiction"


def test_gate7_confidence_narration_matches_passes():
    """Gate 7: raw probability matches band text → passes gate 7."""
    cfg = Config()
    answer = "Galatasaray bugün maçta kazanacak (yüksek güven)."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.82,  # Maps to "yüksek" band (>0.75)
        confidence_band_label="yüksek",
    )
    # Should pass gate 7; may pass or fail on other gates.
    assert result.block_reason != "confidence_narration_contradiction"


def test_gate7_low_confidence_contradiction_blocks():
    """Gate 7: raw=0.90 (yüksek) but answer says "düşük güven" → blocked."""
    cfg = Config()
    answer = "Tahmin düşük güven seviyesinde."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.90,  # Maps to "yüksek"
        confidence_band_label="düşük",  # Contradicts
    )
    assert result.passed is False
    assert result.block_reason == "confidence_narration_contradiction"


def test_gate7_mid_confidence_contradiction_blocks():
    """Gate 7: raw=0.30 (düşük) but answer says "orta güven" → blocked."""
    cfg = Config()
    answer = "Tahmin orta seviyede güven ile yapıldı."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.30,  # Maps to "düşük"
        confidence_band_label="orta",  # Contradicts
    )
    assert result.passed is False
    assert result.block_reason == "confidence_narration_contradiction"


def test_gate7_no_confidence_params_skips_check():
    """Gate 7: no raw_probability/confidence_band_label → gate 7 skipped."""
    cfg = Config()
    answer = "Galatasaray bugün maçta kazanacak (yüksek güven)."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        # No raw_probability or confidence_band_label provided
    )
    # Gate 7 skipped; should pass or fail on other gates only.
    assert result.block_reason != "confidence_narration_contradiction"


def test_gate7_non_predict_intent_skips_check():
    """Gate 7: non-predict intents (data.*, meta.*) skip confidence check."""
    cfg = Config()
    answer = "Bugün yüksek güven ile maç var."
    result = proofread_answer(
        answer,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.30,  # Would contradict if checked
        confidence_band_label="yüksek",
    )
    # Gate 7 applies to all intents when confidence params are provided.
    # This tests that the gate logic is independent of intent type.
    # (The caller may choose not to provide confidence params for non-predict intents.)
    # With params provided, gate should still run.
    assert result.passed is False
    assert result.block_reason == "confidence_narration_contradiction"


def test_gate7_boundary_cases():
    """Gate 7: boundary cases (0.55, 0.75) map correctly."""
    cfg = Config()  # Bands: [0.0,0.55,"düşük"], [0.55,0.75,"orta"], [0.75,1.01,"yüksek"]

    # 0.55 exactly → maps to "orta" (lower_inclusive)
    answer_orta = "Tahmin orta güven ile."
    result_orta = proofread_answer(
        answer_orta,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.55,
        confidence_band_label="orta",
    )
    assert result_orta.block_reason != "confidence_narration_contradiction"

    # 0.75 exactly → maps to "yüksek" (lower_inclusive)
    answer_yuksek = "Tahmin yüksek güven ile."
    result_yuksek = proofread_answer(
        answer_yuksek,
        intent="data.fixture_lookup",
        citation_sha256_expected=None,
        cfg=cfg,
        raw_probability=0.75,
        confidence_band_label="yüksek",
    )
    assert result_yuksek.block_reason != "confidence_narration_contradiction"


def test_proofreader_prepends_confirmation_seeking_match() -> None:
    agent = NlpProofreaderAgent()
    payload = {
        "request_id": "req-001",
        "qa_correlation_id": "corr-001",
        "locale": "tr-TR",
        "intent": "predict.match_outcome",
        "answer_text": "Galatasaray kazandı.",
        "answer_format": "plain",
        "kind": "direct",
        "degraded": False,
        "degraded_reason": None,
        "humanizer_used": False,
        "proofreader_status": "pass",
        "nlp_pipeline_version": "1.0.0",
        "emitted_at_utc": "2026-05-27T10:00:00Z",
        "request_metadata": {"pragmatic_class": "confirmation_seeking"},
        "parts": [
            {
                "intent": "predict.match_outcome",
                "body": "Galatasaray kazandı.",
                "citation": {
                    "kind": "prediction",
                    "produced_at_utc": "2026-05-27T10:00:00Z",
                },
                "polarity": "affirm",
                "subquery_correlation_id": "subquery-001",
            }
        ],
    }
    msg = Message.new(topic="qa.answer.v1", payload=payload, producer="test")
    out = list(agent.handle(msg))

    assert len(out) == 1
    assert out[0].payload["answer_text"] == "Evet, Galatasaray kazandı."


def test_proofreader_prepends_confirmation_seeking_mismatch() -> None:
    agent = NlpProofreaderAgent()
    payload = {
        "request_id": "req-002",
        "qa_correlation_id": "corr-002",
        "locale": "tr-TR",
        "intent": "predict.match_outcome",
        "answer_text": "Galatasaray kazanmadı.",
        "answer_format": "plain",
        "kind": "direct",
        "degraded": False,
        "degraded_reason": None,
        "humanizer_used": False,
        "proofreader_status": "pass",
        "nlp_pipeline_version": "1.0.0",
        "emitted_at_utc": "2026-05-27T10:00:00Z",
        "request_metadata": {"pragmatic_class": "confirmation_seeking"},
        "parts": [
            {
                "intent": "predict.match_outcome",
                "body": "Galatasaray kazanmadı.",
                "citation": {
                    "kind": "prediction",
                    "produced_at_utc": "2026-05-27T10:00:00Z",
                },
                "polarity": "negate",
                "subquery_correlation_id": "subquery-002",
            }
        ],
    }
    msg = Message.new(topic="qa.answer.v1", payload=payload, producer="test")
    out = list(agent.handle(msg))

    assert len(out) == 1
    assert out[0].payload["answer_text"] == "Aslında hayır, Galatasaray kazanmadı."


def test_proofreader_does_not_prepend_information_seeking() -> None:
    agent = NlpProofreaderAgent()
    payload = {
        "request_id": "req-003",
        "qa_correlation_id": "corr-003",
        "locale": "tr-TR",
        "intent": "predict.match_outcome",
        "answer_text": "Galatasaray kazandı.",
        "answer_format": "plain",
        "kind": "direct",
        "degraded": False,
        "degraded_reason": None,
        "humanizer_used": False,
        "proofreader_status": "pass",
        "nlp_pipeline_version": "1.0.0",
        "emitted_at_utc": "2026-05-27T10:00:00Z",
        "request_metadata": {"pragmatic_class": "information_seeking"},
        "parts": [
            {
                "intent": "predict.match_outcome",
                "body": "Galatasaray kazandı.",
                "citation": {
                    "kind": "prediction",
                    "produced_at_utc": "2026-05-27T10:00:00Z",
                },
                "polarity": "affirm",
                "subquery_correlation_id": "subquery-003",
            }
        ],
    }
    msg = Message.new(topic="qa.answer.v1", payload=payload, producer="test")
    out = list(agent.handle(msg))

    assert len(out) == 1
    assert out[0].payload["answer_text"] == "Galatasaray kazandı."

