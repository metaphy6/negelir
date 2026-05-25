"""Cross-phase regression: payload dataclasses must not drift from the
JSON Schemas that document the bus wire contract (ROADMAP §3.5).

Phase 4 surfaced the wire dataclasses in `ai/swarm/agents/payloads.py`;
Phase 3 mandates one JSON Schema per topic in
`ai/swarm/sdk/schemas/<topic>.json`. The third-pass audit found six
silent drifts (renamed keys, wrong scalar types, missing required
fields). This test exists to keep them honest.
"""
from __future__ import annotations

import pytest

from swarm.agents.payloads import (
    DenylistEvent,
    FreshnessEvent,
    MaintEvent,
    MatchStored,
    ModelTrained,
    NormalizedRecord,
    PredictApproved,
    PredictFinal,
    PredictRequest,
    PredictVote,
    ProofreaderVerdict,
    QaRequest,
    QaRequestV1,
    QuarantineSample,
    ScrapeClassified,
    ScrapeRaw,
    ScrapeRequest,
    SecAlert,
    derive_prediction_id,
)



def _example_scrape_request() -> dict:
    return ScrapeRequest(
        source="mackolik",
        target="/fixtures",
        league_id="tr_super_lig",
        competition_id=None,
        requested_at="2026-04-28T12:00:00+00:00",
        metadata={"priority": 1},
    ).as_dict()


def _example_scrape_raw() -> dict:
    return ScrapeRaw(
        source="mackolik",
        target="/fixtures",
        bytes_sha256="0" * 64,
        http_status=200,
        content_type="text/html",
        bytes_b64="",
        bytes_ref="",
        league_id="tr_super_lig",
        competition_id=None,
        fetched_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_scrape_classified() -> dict:
    return ScrapeClassified(
        raw=ScrapeRaw.from_dict(_example_scrape_raw()),
        label="fixture_list",
        confidence=0.9,
        classifier_id="rules.v1",
    ).as_dict()


def _example_normalized() -> dict:
    return NormalizedRecord(
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        source_match_id="m1",
        stable_id="abcdef0123456789",
        extractor_version="phase4.v1",
        payload={"home_team": "GS", "away_team": "FB"},
        captured_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_match_stored() -> dict:
    return MatchStored(
        record_id=1,
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        stable_id="abcdef0123456789",
        change_kind="created",
        stored_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_freshness() -> dict:
    return FreshnessEvent(
        event_id="abc123" * 6,
        record_id=1,
        source="mackolik",
        stable_id="abcdef0123456789",
        record_type="fixture",
        plane="schedule",
        change_kind="updated",
        diff={"score": [None, "1-0"]},
        emitted_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


from swarm.sdk.schemas import validate


def _example_predict_request() -> dict:
    return PredictRequest(
        request_id="req-1",
        match_id="match-abc",
        market="1x2",
        league_id="tr_super_lig",
        profile_id="tr_super_lig",
        requested_at="2026-04-28T12:00:00+00:00",
        qa_correlation_id="qa-corr-1",
        features={"home_elo": 1650.0, "away_elo": 1580.0},
        metadata={"source": "live_predictor_reactor"},
    ).as_dict()


def _example_predict_vote() -> dict:
    return PredictVote(
        request_id="req-1",
        match_id="match-abc",
        market="1x2",
        predictor_id="pred.elo.v1",
        distribution={
            "market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25},
            "score_grid": None,
        },
        confidence=0.65,
        produced_at="2026-04-28T12:00:01+00:00",
        features_version="v1",
        metadata={},
    ).as_dict()


def _example_predict_final() -> dict:
    return PredictFinal(
        request_id="req-1",
        prediction_id=derive_prediction_id(
            match_id="match-abc",
            market="1x2",
            request_id="req-1",
            calibration_version=1,
        ),
        match_id="match-abc",
        market="1x2",
        distribution={
            "market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25},
            "score_grid": None,
        },
        weights={"pred.elo.v1": 1.0},
        contributing_models=["pred.elo.v1"],
        calibration_version=1,
        swarm_confidence=0.65,
        degraded=False,
        degraded_reason="",
        produced_at="2026-04-28T12:00:02+00:00",
        league_id="tr_super_lig",
        profile_id="tr_super_lig",
    ).as_dict()


def _example_model_trained() -> dict:
    return ModelTrained(
        predictor_id="pred.elo.v1",
        profile_id="tr_super_lig",
        league_id="tr_super_lig",
        model_version="2026-04-28T12:00:00",
        trained_at="2026-04-28T12:00:00+00:00",
        metric="accuracy",
        metric_value=0.55,
        samples=120,
        metadata={"trigger": "freshness"},
    ).as_dict()


def _example_proofreader_verdict() -> dict:
    return ProofreaderVerdict(
        request_id="req-1",
        prediction_id=derive_prediction_id(
            match_id="match-abc",
            market="1x2",
            request_id="req-1",
            calibration_version=1,
        ),
        match_id="match-abc",
        market="1x2",
        proofreader_id="proof.sanity.v1",
        verdict="accept",
        score=0.92,
        checked_at="2026-04-28T12:00:03+00:00",
        flags=[],
        checks_run=["sanity.probs_sum_to_one", "sanity.no_nan"],
        rationale="",
        calibration_version=1,
    ).as_dict()


def _example_predict_approved() -> dict:
    final = _example_predict_final()
    return PredictApproved(
        request_id=final["request_id"],
        prediction_id=final["prediction_id"],
        match_id=final["match_id"],
        market=final["market"],
        approved_at="2026-04-28T12:00:04+00:00",
        approved_by=["proof.sanity.v1", "proof.consistency.v1"],
        verdict_count=3,
        quorum=2,
        final=final,
        calibration_version=int(final["calibration_version"]),
    ).as_dict()


def _example_maint_event() -> dict:
    return MaintEvent(
        kind="retrain_request",
        target="pred.elo.v1",
        reason="brier_floor",
        league_id="tr_super_lig",
        market="1x2",
        metric="brier",
        metric_value=0.34,
        threshold=0.30,
        sample_size=120,
        produced_at="2026-04-28T12:00:05+00:00",
    ).as_dict()


def _example_qa_request() -> dict:
    # Phase 7 §7.1 control-plane (raw, escalated by gateway).
    return QaRequest(
        request_id="qa-1",
        raw_text="Bugün Galatasaray nasıl oynadı?",
        ip="203.0.113.10",
        locale="tr",
        client_id=None,
        received_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_qa_request_v1() -> dict:
    # Phase 7 §7.1 data-plane (sanitized; sec_verdict ∈ {pass, sanitized}).
    return QaRequestV1(
        request_id="qa-1",
        sanitized_text="Bugün Galatasaray nasıl oynadı?",
        locale="tr",
        sec_verdict="pass",
        sec_steps_run=["nfc", "strip_control"],
        client_id=None,
        emitted_at="2026-04-28T12:00:00+00:00",
    ).as_dict()


def _example_sec_alert() -> dict:
    # Phase 7 §7.4 — known kind from KNOWN_SEC_ALERT_KINDS.
    return SecAlert(
        alert_id="alert-1",
        kind="prompt_injection_block",
        severity="warn",
        source="sec.input.v1",
        reason="Detected prompt-injection pattern in QA payload",
        produced_at="2026-04-28T12:00:00+00:00",
        subject="203.0.113.10",
        request_id="qa-1",
        client_id=None,
        ip="203.0.113.10",
        evidence_ref="0" * 64,
    ).as_dict()


def _example_sec_quarantine() -> dict:
    return QuarantineSample(
        quarantine_id="q-1",
        source="qa",
        raw_bytes_b64="SGVsbG8sIHdvcmxkIQ==",  # "Hello, world!"
        verdict="quarantine",
        reasons=["prompt_injection"],
        detected_at="2026-04-28T12:00:00+00:00",
        pii_redacted=False,
        client_id=None,
        ip="203.0.113.10",
        bytes_sha256="a" * 64,
    ).as_dict()


def _example_sec_denylist() -> dict:
    return DenylistEvent(
        event_id="evt-1",
        action="add",
        subject="203.0.113.10",
        reason="rate_burst",
        decided_at="2026-04-28T12:00:00+00:00",
        ttl_s=3600,
    ).as_dict()


_CASES: list[tuple[str, dict]] = [
    ("scrape.request", _example_scrape_request()),
    ("scrape.raw", _example_scrape_raw()),
    ("scrape.classified", _example_scrape_classified()),
    ("match.normalized", _example_normalized()),
    ("match.stored", _example_match_stored()),
    ("freshness.events.v1", _example_freshness()),
    ("predict.request", _example_predict_request()),
    ("predict.vote", _example_predict_vote()),
    ("predict.final", _example_predict_final()),
    ("models.events.v1", _example_model_trained()),
    ("predict.proofreader_verdict.v1", _example_proofreader_verdict()),
    ("predict.approved.v1", _example_predict_approved()),
    ("maint.event.v1", _example_maint_event()),
    # Phase 7 — Defense-agent envelopes (foundation; agents land in §7.1-7.3).
    ("qa.request", _example_qa_request()),
    ("qa.request.v1", _example_qa_request_v1()),
    ("sec.alert.v1", _example_sec_alert()),
    ("sec.quarantine.v1", _example_sec_quarantine()),
    ("sec.denylist.v1", _example_sec_denylist()),
]


@pytest.mark.parametrize("topic,payload", _CASES, ids=[t for t, _ in _CASES])
def test_dataclass_payload_satisfies_schema(topic: str, payload: dict) -> None:
    errors = validate(topic, payload)
    assert not errors, f"{topic}: schema drift detected:\n  " + "\n  ".join(errors)
