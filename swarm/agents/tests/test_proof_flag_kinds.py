"""Contract tests for the `proof.flag` kind registry.

Per pre-Phase 6 audit §B1 / §D2: the JSON-schema enum for
``proof.flag.kind`` and the in-code ``ProofFlagKind`` registry must
agree exactly. The validate() helper enforces enum at live emission;
these tests guard the registry side of that contract and confirm
every Phase 4/5 producer emits a registered kind that survives
schema validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm.agents.payloads import ProofFlagKind
from swarm.sdk.schemas import validate


SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "sdk"
    / "schemas"
    / "proof.flag.json"
)


def test_registry_matches_schema_enum() -> None:
    """Registry ↔ schema enum must agree exactly (no drift either direction)."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_enum = set(schema["properties"]["kind"]["enum"])
    registry = ProofFlagKind.all_kinds()
    missing_in_schema = registry - schema_enum
    missing_in_registry = schema_enum - registry
    assert not missing_in_schema, (
        f"ProofFlagKind values not declared in schema enum: {missing_in_schema}"
    )
    assert not missing_in_registry, (
        f"Schema enum values not declared in ProofFlagKind: {missing_in_registry}"
    )


@pytest.mark.parametrize("kind", sorted(ProofFlagKind.all_kinds()))
def test_every_registered_kind_validates(kind: str) -> None:
    """A minimal payload with each registered kind must satisfy the schema."""
    errors = validate("proof.flag", {"kind": kind})
    assert errors == [], f"unexpected validation errors for {kind}: {errors}"


def test_unregistered_kind_is_rejected() -> None:
    """Sanity: enum guard rejects a made-up kind."""
    errors = validate("proof.flag", {"kind": "definitely_not_a_real_kind"})
    assert any("not in declared enum" in e for e in errors), errors


def test_phase5_consensus_kinds_are_registered() -> None:
    """Regression for B1: the three Phase-5 consensus kinds were the
    actual drift the audit caught. Pin them explicitly so a future
    refactor can't drop the symbols silently."""
    assert ProofFlagKind.LATE_VOTE_DROPPED == "late_vote_dropped"
    assert ProofFlagKind.CONSENSUS_NO_VOTES == "consensus_no_votes"
    assert ProofFlagKind.CONSENSUS_OVERFLOW == "consensus_overflow"


def test_phase4_kinds_are_registered() -> None:
    """Regression for B1: don't drop Phase 4 kinds during refactors either."""
    assert ProofFlagKind.UPSTREAM_MISSING == "upstream_missing"
    assert ProofFlagKind.DECODE_FAILED == "decode_failed"
    assert ProofFlagKind.EMPTY_PARSE == "empty_parse"
    assert ProofFlagKind.PARSER_EXCEPTION == "parser_exception"
    assert ProofFlagKind.INVALID_RECORD == "invalid_record"
    assert ProofFlagKind.LOW_CONFIDENCE_CLASSIFICATION == "low_confidence_classification"


# ── F3-3: every Phase 6 PROOFREADER_* flag carries canonical fields ──
#
# Operator dashboards filter on `agent` / `prediction_id` / `match_id`
# / `market` / `request_id`. Phase-6 audit F3-3 caught the
# `proofreader_internal_error` kind using `source` / `target` aliases
# instead — silently hiding it from any `prediction_id = X` query.
# This contract test drives each of the six Phase 6 emission paths
# end-to-end and asserts the canonical field set is present in the
# resulting payload.

_PHASE6_PROOFREADER_KINDS: frozenset[str] = frozenset({
    ProofFlagKind.PROOFREADER_NO_QUORUM,
    ProofFlagKind.PROOFREADER_REJECTED,
    ProofFlagKind.PROOFREADER_LATE_VERDICT_DROPPED,
    ProofFlagKind.PROOFREADER_DUPLICATE_APPROVAL,
    ProofFlagKind.PROOFREADER_OVERFLOW,
    ProofFlagKind.PROOFREADER_INTERNAL_ERROR,
})

_CANONICAL_FIELDS: tuple[str, ...] = (
    "agent",
    "prediction_id",
    "match_id",
    "market",
    "request_id",
)


def _drive_phase6_proofreader_emissions() -> dict[str, dict]:
    """Drive every Phase 6 PROOFREADER_* emission path and return a
    `{kind: payload}` map. Built as a fixture-on-demand so the
    parameterized test below can fail per-kind."""
    from typing import Any

    from swarm.agents.payloads import (
        PredictFinal,
        ProofreaderVerdict,
    )
    from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
    from swarm.agents.proofreader.replicas import PlausibilityProofreader
    from swarm.agents.reactor import InMemoryLedger
    from swarm.agents.topics import (
        PREDICT_FINAL,
        PROOF_FLAG,
        PROOFREADER_VERDICT,
    )
    from swarm.sdk.types import Message

    def _final(prediction_id: str = "pid-canon") -> PredictFinal:
        return PredictFinal(
            request_id="req-canon",
            prediction_id=prediction_id,
            match_id="match-canon",
            market="1x2",
            distribution={"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}},
            weights={"pred.elo.v1": 1.0},
            contributing_models=["pred.elo.v1"],
            calibration_version=1,
            swarm_confidence=0.65,
            produced_at="2026-04-28T12:00:02+00:00",
            league_id="tr_super_lig",
            profile_id="tr_super_lig",
        )

    def _verdict(
        prediction_id: str,
        proofreader_id: str,
        verdict: str,
    ) -> ProofreaderVerdict:
        return ProofreaderVerdict(
            request_id="req-canon",
            prediction_id=prediction_id,
            match_id="match-canon",
            market="1x2",
            proofreader_id=proofreader_id,
            verdict=verdict,
            score=1.0,
            checked_at="2026-04-28T12:00:02+00:00",
            flags=[],
            checks_run=["x"],
            rationale="",
            calibration_version=1,
        )

    def _vmsg(v: ProofreaderVerdict) -> Message:
        return Message.new(PROOFREADER_VERDICT, v.as_dict(), producer="t")

    def _fmsg(f: PredictFinal) -> Message:
        return Message.new(PREDICT_FINAL, f.as_dict(), producer="t")

    payloads: dict[str, dict] = {}

    # ── proofreader_internal_error (replica-emitted) ──
    broken = PlausibilityProofreader()
    def _boom(_: Any) -> None:
        raise RuntimeError("F3-3 contract drive")
    broken._check = _boom  # type: ignore[assignment]
    out = list(broken.handle(_fmsg(_final("pid-internal"))))
    flags = [m.payload for m in out if m.envelope.topic == PROOF_FLAG]
    assert len(flags) == 1
    payloads[ProofFlagKind.PROOFREADER_INTERNAL_ERROR] = flags[0]

    # ── proofreader_rejected (one reject vote in aggregator) ──
    agg = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=2, window_ms=1_000_000,
    )
    final = _final("pid-rejected")
    list(agg.handle(_fmsg(final)))
    out = list(agg.handle(_vmsg(_verdict("pid-rejected", "p.sanity", "reject"))))
    rej = [
        m.payload for m in out
        if m.envelope.topic == PROOF_FLAG
        and m.payload["kind"] == ProofFlagKind.PROOFREADER_REJECTED
    ]
    assert len(rej) == 1
    payloads[ProofFlagKind.PROOFREADER_REJECTED] = rej[0]

    # ── proofreader_late_verdict_dropped (verdict after finalize) ──
    agg2 = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=1, window_ms=1_000_000,
    )
    final2 = _final("pid-late")
    list(agg2.handle(_fmsg(final2)))
    list(agg2.handle(_vmsg(_verdict("pid-late", "p.a", "accept"))))  # finalize
    out = list(agg2.handle(_vmsg(_verdict("pid-late", "p.b", "accept"))))
    late = [m.payload for m in out if m.envelope.topic == PROOF_FLAG]
    assert any(p["kind"] == ProofFlagKind.PROOFREADER_LATE_VERDICT_DROPPED for p in late)
    payloads[ProofFlagKind.PROOFREADER_LATE_VERDICT_DROPPED] = next(
        p for p in late
        if p["kind"] == ProofFlagKind.PROOFREADER_LATE_VERDICT_DROPPED
    )

    # ── proofreader_duplicate_approval (ledger marked between
    #    candidate-receipt and finalization; reachable via
    #    flush_all). The dup flag is the defensive idempotency guard
    #    inside `_finalize`; we synthesise that race deliberately. ──
    ledger = InMemoryLedger()
    agg3 = ProofreaderAggregatorAgent(
        ledger=ledger, quorum=1, window_ms=1_000_000,
    )
    list(agg3.handle(_fmsg(_final("pid-dup"))))
    ledger.mark_processed("proofreader_aggregator.v1", "pid-dup")
    out = agg3.flush_all()
    dup = [
        m.payload for m in out
        if m.envelope.topic == PROOF_FLAG
        and m.payload["kind"] == ProofFlagKind.PROOFREADER_DUPLICATE_APPROVAL
    ]
    assert len(dup) == 1
    payloads[ProofFlagKind.PROOFREADER_DUPLICATE_APPROVAL] = dup[0]

    # ── proofreader_overflow (pending map saturates) ──
    agg4 = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=2, window_ms=1_000_000, max_pending=1,
    )
    list(agg4.handle(_fmsg(_final("pid-evictable"))))
    out = list(agg4.handle(_fmsg(_final("pid-newcomer"))))
    ovf = [
        m.payload for m in out
        if m.envelope.topic == PROOF_FLAG
        and m.payload["kind"] == ProofFlagKind.PROOFREADER_OVERFLOW
    ]
    assert len(ovf) == 1
    payloads[ProofFlagKind.PROOFREADER_OVERFLOW] = ovf[0]

    # ── proofreader_no_quorum (window expired without quorum) ──
    clock_ms = [1_000_000.0]
    agg5 = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(),
        quorum=2,
        window_ms=50,
        clock_ms=lambda: clock_ms[0],
    )
    list(agg5.handle(_fmsg(_final("pid-noq"))))
    list(agg5.handle(_vmsg(_verdict("pid-noq", "p.a", "accept"))))
    clock_ms[0] += 200.0
    out = list(agg5.flush_expired(now_ms=clock_ms[0]))
    nq = [
        m.payload for m in out
        if m.envelope.topic == PROOF_FLAG
        and m.payload["kind"] == ProofFlagKind.PROOFREADER_NO_QUORUM
    ]
    assert len(nq) == 1
    payloads[ProofFlagKind.PROOFREADER_NO_QUORUM] = nq[0]

    return payloads


@pytest.mark.parametrize("kind", sorted(_PHASE6_PROOFREADER_KINDS))
def test_phase6_proofreader_kind_carries_canonical_fields(kind: str) -> None:
    """Phase-6 audit F3-3: every Phase 6 `proofreader_*` flag must
    carry the canonical field set (`agent`, `prediction_id`,
    `match_id`, `market`, `request_id`) so operator dashboards
    filtering on those names see every kind. Without this contract,
    a future kind silently regresses to `source` / `target` aliases
    and disappears from prediction-id queries.
    """
    payloads = _drive_phase6_proofreader_emissions()
    payload = payloads[kind]
    missing = [f for f in _CANONICAL_FIELDS if f not in payload]
    assert not missing, (
        f"{kind} payload missing canonical fields {missing}; got "
        f"keys={sorted(payload.keys())}"
    )
    # Defense-in-depth: the prior `source` / `target` aliases must
    # not return either.
    assert "source" not in payload, (
        f"{kind} payload still uses retired `source` alias"
    )
    assert "target" not in payload, (
        f"{kind} payload still uses retired `target` alias"
    )


def test_phase6_proofreader_kinds_set_matches_registry() -> None:
    """Pin: the parametric set above stays in sync with the
    `PROOFREADER_*` members of the registry. If a new kind is added
    to the registry, the F3-3 contract test must cover it too."""
    registry_phase6 = {
        v for v in ProofFlagKind.all_kinds() if v.startswith("proofreader_")
    }
    assert _PHASE6_PROOFREADER_KINDS == registry_phase6, (
        "Phase 6 PROOFREADER_* kinds drifted between registry and the "
        "F3-3 contract-test set; add the new kind to "
        "_PHASE6_PROOFREADER_KINDS and extend "
        "_drive_phase6_proofreader_emissions to cover it."
    )
