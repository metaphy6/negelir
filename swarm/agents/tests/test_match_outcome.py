"""Phase 5+ contract tests for `match.outcome.v1`.

The storage agent is the single producer; emits exactly when a
match_detail upsert lands a terminal status with both final scores
present. Dedup is provided by the upsert path (`unchanged` short-
circuits before any outcome computation).
"""
from __future__ import annotations

import pytest

from swarm.agents.payloads import (
    MatchOutcome,
    NormalizedRecord,
    TERMINAL_MATCH_STATUSES,
    derive_match_outcome,
)
from swarm.agents.storage import StorageAgent
from swarm.agents.topics import (
    FRESHNESS_EVENTS,
    MATCH_OUTCOME,
    MATCH_STORED,
)
from swarm.sdk.schemas import known_topics, validate
from swarm.sdk.types import Message


def _detail(
    *,
    src_id: str = "m1",
    status: str = "final",
    home: int = 2,
    away: int = 1,
    extra: dict | None = None,
) -> NormalizedRecord:
    payload = {
        "home_team": "GS",
        "away_team": "FB",
        "status": status,
        "final_home": home,
        "final_away": away,
    }
    if extra:
        payload.update(extra)
    return NormalizedRecord(
        record_type="match_detail",
        plane="live",
        source="mackolik",
        source_match_id=src_id,
        stable_id="stable-" + src_id,
        extractor_version="phase4.v1",
        payload=payload,
        league_id="tr_super_lig",
    )


def _msg(rec: NormalizedRecord) -> Message:
    return Message.new("match.normalized", rec.as_dict(), producer="test")


# ── Schema + derivation ────────────────────────────────────────


def test_schema_registered() -> None:
    assert "match.outcome.v1" in known_topics()


def test_derive_match_outcome_canonical() -> None:
    assert derive_match_outcome(final_home=2, final_away=1) == {
        "outcome_1x2": "H",
        "outcome_ou_2_5": "over",
        "outcome_btts": "yes",
    }
    assert derive_match_outcome(final_home=0, final_away=0) == {
        "outcome_1x2": "D",
        "outcome_ou_2_5": "under",
        "outcome_btts": "no",
    }
    assert derive_match_outcome(final_home=0, final_away=2) == {
        "outcome_1x2": "A",
        "outcome_ou_2_5": "under",
        "outcome_btts": "no",
    }
    # Boundary on OU: 1-2 => 3 goals -> over; 1-1 => 2 goals -> under.
    assert (
        derive_match_outcome(final_home=1, final_away=2)["outcome_ou_2_5"] == "over"
    )
    assert (
        derive_match_outcome(final_home=1, final_away=1)["outcome_ou_2_5"] == "under"
    )


def test_match_outcome_payload_validation_rejects_negative_scores() -> None:
    with pytest.raises(ValueError):
        MatchOutcome(
            match_id="m1", stable_id="s1", source="mackolik",
            final_home=-1, final_away=0, outcome_1x2="A",
            settled_at="2026-04-29T00:00:00+00:00",
        )


def test_match_outcome_payload_validation_rejects_bad_1x2() -> None:
    with pytest.raises(ValueError):
        MatchOutcome(
            match_id="m1", stable_id="s1", source="mackolik",
            final_home=1, final_away=0, outcome_1x2="X",
            settled_at="2026-04-29T00:00:00+00:00",
        )


# ── Storage agent emission ─────────────────────────────────────


def test_storage_emits_match_outcome_on_terminal_status() -> None:
    agent = StorageAgent()
    out = list(agent.handle(_msg(_detail())))
    topics = [m.envelope.topic for m in out]
    assert MATCH_STORED in topics
    assert FRESHNESS_EVENTS in topics
    assert MATCH_OUTCOME in topics

    outcome_msg = next(m for m in out if m.envelope.topic == MATCH_OUTCOME)
    errors = validate("match.outcome.v1", outcome_msg.payload)
    assert errors == [], errors

    mo = MatchOutcome.from_dict(outcome_msg.payload)
    assert mo.outcome_1x2 == "H"
    assert mo.outcome_ou_2_5 == "over"
    assert mo.outcome_btts == "yes"
    assert mo.league_id == "tr_super_lig"
    assert mo.record_id is not None


def test_storage_no_outcome_on_non_terminal_status() -> None:
    agent = StorageAgent()
    out = list(agent.handle(_msg(_detail(status="live"))))
    assert MATCH_OUTCOME not in [m.envelope.topic for m in out]


def test_storage_no_outcome_on_unchanged_repeat() -> None:
    """Single-emission contract: a re-scrape of the same final score
    returns `unchanged` from the store and emits no outcome message.
    Phase 6 drift consumers can therefore ledger by `(stable_id,
    settled_at)` or `record_id` without dedup gymnastics."""
    agent = StorageAgent()
    list(agent.handle(_msg(_detail())))
    out = list(agent.handle(_msg(_detail())))
    assert MATCH_OUTCOME not in [m.envelope.topic for m in out]


def test_storage_no_outcome_on_fixture_record() -> None:
    rec = NormalizedRecord(
        record_type="fixture",
        plane="schedule",
        source="mackolik",
        source_match_id="m9",
        stable_id="stable-m9",
        extractor_version="phase4.v1",
        payload={"status": "final", "final_home": 1, "final_away": 0},
    )
    out = list(StorageAgent().handle(_msg(rec)))
    assert MATCH_OUTCOME not in [m.envelope.topic for m in out]


def test_storage_no_outcome_when_scores_missing() -> None:
    rec = NormalizedRecord(
        record_type="match_detail",
        plane="live",
        source="mackolik",
        source_match_id="m10",
        stable_id="stable-m10",
        extractor_version="phase4.v1",
        payload={"status": "final"},  # no scores
    )
    out = list(StorageAgent().handle(_msg(rec)))
    assert MATCH_OUTCOME not in [m.envelope.topic for m in out]


def test_storage_accepts_nested_score_block() -> None:
    """Some extractors emit `score: {home, away}` instead of flat keys."""
    rec = NormalizedRecord(
        record_type="match_detail",
        plane="live",
        source="nesine",
        source_match_id="m11",
        stable_id="stable-m11",
        extractor_version="phase4.v1",
        payload={"status": "FT", "score": {"home": 0, "away": 3}},
    )
    out = list(StorageAgent().handle(_msg(rec)))
    outcome_msgs = [m for m in out if m.envelope.topic == MATCH_OUTCOME]
    assert len(outcome_msgs) == 1
    mo = MatchOutcome.from_dict(outcome_msgs[0].payload)
    assert (mo.final_home, mo.final_away, mo.outcome_1x2) == (0, 3, "A")


def test_terminal_status_set_is_lowercased() -> None:
    # Producers normalise to lowercase before lookup; the registry
    # itself must therefore contain lowercase entries.
    for s in TERMINAL_MATCH_STATUSES:
        assert s == s.lower()
