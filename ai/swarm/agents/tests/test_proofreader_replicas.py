"""Tests for `ai/swarm/agents/proofreader/replicas.py` (§6.2)."""
from __future__ import annotations

from typing import Any

from swarm.agents.payloads import PredictFinal, ProofFlagKind, ProofreaderVerdict
from swarm.agents.proofreader.replicas import (
    ConsistencyProofreader,
    PlausibilityProofreader,
    SanityProofreader,
    _BaseProofreaderAgent,
)
from swarm.agents.topics import (
    PREDICT_FINAL,
    PROOF_FLAG,
    PROOFREADER_VERDICT,
    SCRAPE_REQUEST,
)
from swarm.sdk.types import Message


def _final(distribution: dict[str, Any]) -> PredictFinal:
    return PredictFinal(
        request_id="req-1",
        prediction_id="pid-1",
        match_id="match-abc",
        market="1x2",
        distribution=distribution,
        weights={"pred.elo.v1": 1.0},
        contributing_models=["pred.elo.v1"],
        calibration_version=1,
        swarm_confidence=0.65,
        produced_at="2026-04-28T12:00:02+00:00",
        league_id="tr_super_lig",
        profile_id="tr_super_lig",
    )


def _msg(d: dict[str, Any]) -> Message:
    return Message.new(PREDICT_FINAL, _final(d).as_dict(), producer="consensus")


# ── Contract / dispatch ───────────────────────────────────────


def test_replicas_have_distinct_names_and_correct_topics() -> None:
    for cls in (SanityProofreader, PlausibilityProofreader, ConsistencyProofreader):
        a = cls()
        assert a.subscribes == (PREDICT_FINAL,)
        # Phase-6 audit (F-4): replicas now publish on PROOF_FLAG too,
        # for the `proofreader_internal_error` failure-isolation path.
        assert a.publishes == (PROOFREADER_VERDICT, PROOF_FLAG)
        assert a.name.startswith("proofreader.")
    names = {
        SanityProofreader().name,
        PlausibilityProofreader().name,
        ConsistencyProofreader().name,
    }
    assert len(names) == 3


def test_replica_ignores_unsubscribed_topic() -> None:
    a = SanityProofreader()
    out = list(a.handle(Message.new(SCRAPE_REQUEST, {}, producer="t")))
    assert out == []


def test_replica_drops_malformed_predict_final() -> None:
    a = SanityProofreader()
    out = list(a.handle(Message.new(PREDICT_FINAL, {"oops": True}, producer="t")))
    assert out == []


# ── Sanity replica ────────────────────────────────────────────


def test_sanity_replica_accepts_well_formed() -> None:
    a = SanityProofreader(eps=0.01)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.25, "A": 0.25}})))
    assert len(out) == 1
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.proofreader_id == "proofreader.sanity.v1"
    assert v.verdict == "accept"
    assert v.flags == []
    assert v.checks_run == ["sanity.probs_well_formed"]
    assert v.rationale == ""
    assert v.calibration_version == 1


def test_sanity_replica_rejects_bad_sum() -> None:
    a = SanityProofreader(eps=0.01)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.3}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "reject"
    # Structured: flags carries the rule_id (subset of checks_run).
    assert v.flags == ["sanity.probs_well_formed"]
    # Human: rationale carries the detail.
    assert "differs from 1.0" in v.rationale


# ── Plausibility replica ──────────────────────────────────────


def test_plausibility_replica_warns_on_dominant_outcome() -> None:
    a = PlausibilityProofreader(max_outcome_prob=0.85)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.92, "D": 0.05, "A": 0.03}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "warn"
    assert v.score < 1.0
    assert v.flags == ["plausibility.max_outcome_prob"]
    assert "exceeds cap" in v.rationale


def test_plausibility_replica_accepts_balanced() -> None:
    a = PlausibilityProofreader(max_outcome_prob=0.85)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "accept"


# ── Consistency replica ───────────────────────────────────────


def test_consistency_replica_accepts_when_no_grid() -> None:
    a = ConsistencyProofreader(tol=0.05)
    out = list(a.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "accept"


def test_consistency_replica_rejects_diverging_marginals() -> None:
    a = ConsistencyProofreader(tol=0.05)
    out = list(a.handle(_msg({
        "market_outcomes": {"H": 0.7, "D": 0.2, "A": 0.1},
        "score_grid": [
            [0.5, 0.2],
            [0.3, 0.0],
        ],
    })))
    v = ProofreaderVerdict.from_dict(out[0].payload)
    assert v.verdict == "reject"
    assert v.flags == ["consistency.score_grid_marginals"]


# ── Bus-loop integration: replicas → aggregator → predict.approved ──


def test_three_replicas_produce_quorum_for_aggregator() -> None:
    """End-to-end without a real bus: feed `predict.final` into all
    three replicas, collect their verdicts, feed them + the candidate
    into the aggregator. Default config (replicas=3, quorum=2) should
    produce one `predict.approved.v1` for a clean prediction."""
    from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
    from swarm.agents.reactor import InMemoryLedger
    from swarm.agents.topics import PREDICT_APPROVED

    final_msg = _msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})
    replicas = [
        SanityProofreader(),
        PlausibilityProofreader(),
        ConsistencyProofreader(),
    ]
    verdict_msgs: list[Message] = []
    for r in replicas:
        verdict_msgs.extend(r.handle(final_msg))
    assert len(verdict_msgs) == 3
    # All three accept on a clean distribution.
    assert all(
        ProofreaderVerdict.from_dict(m.payload).verdict == "accept"
        for m in verdict_msgs
    )

    agg = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=2, window_ms=200,
    )
    out: list[Message] = []
    out.extend(agg.handle(final_msg))
    for vm in verdict_msgs:
        out.extend(agg.handle(vm))

    approvals = [m for m in out if m.envelope.topic == PREDICT_APPROVED]
    assert len(approvals) == 1


# ── F-4: replica internal exception → warn + flag (not reject) ──


def _broken_replica_factory(klass: type[_BaseProofreaderAgent]):
    """Return an instance of `klass` whose `_check` always raises."""
    inst = klass()

    def _boom(_final):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic regression for F-4 audit")

    inst._check = _boom  # type: ignore[assignment]
    return inst


def test_replica_internal_exception_emits_warn_vote_and_flag() -> None:
    """Phase-6 audit (F-4): a `_check` exception used to become a
    `reject` vote, which (combined with the reject-veto rule) let one
    buggy replica DoS the whole pipeline. The shell now emits a
    `proof.flag` AND a `warn` vote so the candidate still has a path
    to quorum if the other replicas accept.
    """
    broken = _broken_replica_factory(PlausibilityProofreader)
    out = list(broken.handle(_msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})))
    # Exactly one verdict + one flag.
    assert len(out) == 2
    by_topic = {m.envelope.topic: m for m in out}
    assert PROOFREADER_VERDICT in by_topic
    assert PROOF_FLAG in by_topic

    v = ProofreaderVerdict.from_dict(by_topic[PROOFREADER_VERDICT].payload)
    assert v.verdict == "warn"
    assert v.score == 0.0
    assert v.proofreader_id == "proofreader.plausibility.v1"
    assert "internal check error" in v.rationale
    # `flags` ⊆ `checks_run` invariant — warn is non-accept so the
    # rule id is listed.
    assert v.flags == ["plausibility.max_outcome_prob"]

    flag = by_topic[PROOF_FLAG].payload
    assert flag["kind"] == ProofFlagKind.PROOFREADER_INTERNAL_ERROR
    # Phase-6 audit F3-3: payload uses the canonical Phase 6 field
    # set (`agent` / `prediction_id` / `match_id` / `market` /
    # `request_id`) shared with every other proof.flag kind so
    # operator dashboards filtering on `prediction_id` see this
    # kind too. The prior `source` / `target` aliases hid it.
    assert flag["agent"] == "proofreader.plausibility.v1"
    assert flag["prediction_id"] == "pid-1"
    assert flag["match_id"] == "match-abc"
    assert flag["market"] == "1x2"
    assert flag["request_id"] == "req-1"
    assert "source" not in flag
    assert "target" not in flag
    assert flag["exception_type"] == "RuntimeError"
    assert "synthetic regression" in flag["detail"]


def test_buggy_replica_does_not_veto_when_others_accept() -> None:
    """Doctrine-shape test: with a broken plausibility replica, sanity
    + consistency must still get the candidate to quorum (warn counts
    toward quorum, matching today's plausibility-warn semantics).
    Previously the broken replica's reject vote killed the candidate
    regardless of the other two votes.
    """
    from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
    from swarm.agents.reactor import InMemoryLedger
    from swarm.agents.topics import PREDICT_APPROVED

    final_msg = _msg({"market_outcomes": {"H": 0.5, "D": 0.3, "A": 0.2}})
    replicas: list[_BaseProofreaderAgent] = [
        SanityProofreader(),
        _broken_replica_factory(PlausibilityProofreader),
        ConsistencyProofreader(),
    ]
    verdict_msgs: list[Message] = []
    flag_msgs: list[Message] = []
    for r in replicas:
        for m in r.handle(final_msg):
            (flag_msgs if m.envelope.topic == PROOF_FLAG else verdict_msgs).append(m)
    # 3 verdicts (1 warn from broken replica + 2 accept) + 1 flag.
    assert len(verdict_msgs) == 3
    assert len(flag_msgs) == 1

    agg = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=2, window_ms=200,
    )
    out: list[Message] = []
    out.extend(agg.handle(final_msg))
    for vm in verdict_msgs:
        out.extend(agg.handle(vm))
    approvals = [m for m in out if m.envelope.topic == PREDICT_APPROVED]
    assert len(approvals) == 1, (
        "Buggy replica must not veto the prediction when the other two "
        "replicas accept (F-4 regression guard)."
    )


# ── F3-1: replica roster is the single source of truth ───────


def test_proofreader_policy_classes_lists_all_three_distinct_policies() -> None:
    """Phase-6 audit F3-1: the replica roster lives in
    `PROOFREADER_POLICY_CLASSES` (one entry per distinct check
    policy: sanity, plausibility, consistency). The list is the
    single source of truth for the swarm's voter count; the bootstrap
    iterates it and `cfg.proofreader_quorum` derives from its length.
    Pin the contents so a future refactor cannot drop a policy
    without flipping this test red.
    """
    from swarm.agents.proofreader.replicas import PROOFREADER_POLICY_CLASSES

    assert PROOFREADER_POLICY_CLASSES == (
        SanityProofreader,
        PlausibilityProofreader,
        ConsistencyProofreader,
    )


def test_proofreader_quorum_derives_from_policy_roster_length() -> None:
    """Phase-6 audit F3-1: `cfg.proofreader_quorum` must equal
    ⌊len(PROOFREADER_POLICY_CLASSES)/2⌋+1 so the aggregator's quorum
    cannot drift from the actual voter count. Pinning this invariant
    closes the operator-footgun the audit identified (the retired
    `NEGELIR_PROOFREADER_REPLICAS` knob silently broke quorum at any
    value other than 3).
    """
    from common.config import cfg as _cfg
    from swarm.agents.proofreader.replicas import PROOFREADER_POLICY_CLASSES

    n = len(PROOFREADER_POLICY_CLASSES)
    expected = (n // 2) + 1
    assert _cfg.proofreader_quorum == expected
    # And concretely at v1: 3 policies → quorum=2.
    assert n == 3
    assert _cfg.proofreader_quorum == 2


def test_bootstrap_replica_count_matches_policy_roster() -> None:
    """Phase-6 audit F3-1: the bootstrap's `_build_proofreader_replicas`
    must spawn exactly one instance of every policy class in the
    roster — no more, no less. Without this, the aggregator's quorum
    derivation (above) would be a math identity disconnected from the
    runtime voter count.
    """
    from swarm.agents.proofreader.replicas import PROOFREADER_POLICY_CLASSES
    from swarm.bootstrap import _build_proofreader_replicas

    built = _build_proofreader_replicas()
    assert [type(a) for a in built] == list(PROOFREADER_POLICY_CLASSES)


def test_no_standalone_proofreader_replicas_env_knob() -> None:
    """Phase-6 audit F3-1: the standalone `NEGELIR_PROOFREADER_REPLICAS`
    env knob (and its `cfg.proofreader_replicas` field) was retired
    because it was disconnected from the actual replica roster. A
    future maintainer reintroducing it would re-open the operator
    footgun this audit closed.
    """
    from common.config import cfg as _cfg

    assert not hasattr(_cfg, "proofreader_replicas"), (
        "`cfg.proofreader_replicas` was retired by Phase-6 audit F3-1; "
        "reintroducing it re-opens the footgun where the aggregator's "
        "quorum and the bootstrap's voter count drift silently. The "
        "replica roster lives in PROOFREADER_POLICY_CLASSES."
    )

