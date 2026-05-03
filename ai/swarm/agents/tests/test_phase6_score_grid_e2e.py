"""Phase 6 — end-to-end regression for the predictor → consensus →
proofreader → aggregator → ``predict.approved.v1`` path with a real
grid-bearing vote.

Closes the coverage gap surfaced in the Phase 4–6 audit (B1): prior
proofreader fixtures hand-built ``score_grid`` as a list of
``{home, away, prob}`` dicts, but the live producers
(``DixonColesPredictor`` / ``XgbXgPredictor`` / ``ConsensusAgent``)
emit a 2D matrix ``grid[home][away]``. Without an end-to-end test
that runs both the live predictor and the live consistency
proofreader on the same payload, the shape contract drifted silently
and would have rejected ~100% of grid-bearing predictions in
production.

The test deliberately runs the **real** ``DixonColesPredictor`` so
that any future change to either side of the contract (predictor
output shape OR ``grid_consistency_check`` parser) trips this guard.
"""
from __future__ import annotations

from swarm.agents.consensus import ConsensusAgent
from swarm.agents.payloads import (
    PredictApproved,
    PredictFinal,
    PredictRequest,
    ProofreaderVerdict,
)
from swarm.agents.predictors import DixonColesPredictor
from swarm.agents.proofreader.aggregator import ProofreaderAggregatorAgent
from swarm.agents.proofreader.replicas import (
    ConsistencyProofreader,
    PlausibilityProofreader,
    SanityProofreader,
)
from swarm.agents.reactor import InMemoryLedger
from swarm.agents.topics import (
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PREDICT_REQUEST,
    PREDICT_VOTE,
    PROOF_FLAG,
    PROOFREADER_VERDICT,
)
from swarm.sdk.bus import InMemoryBus
from swarm.sdk.registry import AgentRegistry
from swarm.sdk.runner import AgentRunner
from swarm.sdk.types import Message


def _runner(bus, registry, agent):
    r = AgentRunner(
        agent=agent,
        bus=bus,
        registry=registry,
        max_in_flight=8,
        retry_budget=3,
        tick_sec=0.001,
    )
    r.register()
    return r


def _drain(runners, *, max_steps: int = 128) -> None:
    for _ in range(max_steps):
        progress = False
        for r in runners:
            if r.step():
                progress = True
        if not progress:
            return
    raise AssertionError("phase 6 e2e swarm did not quiesce")


def test_grid_bearing_prediction_reaches_predict_approved() -> None:
    """A real ``pred.dixon_coles.v1`` + ``pred.xgb_xg.v1`` vote must
    flow through consensus, all three proofreader replicas, and the
    aggregator, and emerge as exactly one ``predict.approved.v1`` —
    NOT be silently rejected by ``grid_consistency_check``.
    """
    bus = InMemoryBus()
    registry = AgentRegistry()

    clock = lambda: "2026-04-30T00:00:00+00:00"
    # A single grid-bearing predictor is enough to exercise the
    # contract; pairing two predictors with different features_version
    # would just generate consensus warning noise unrelated to the bug
    # under test.
    predictors = [DixonColesPredictor(clock=clock)]
    consensus = ConsensusAgent(
        expected_predictors=tuple(p.predictor_id for p in predictors),
        ledger=InMemoryLedger(),
        clock_ms=lambda: 0.0,
        clock_iso=clock,
        min_voters=1,
    )
    replicas = [
        SanityProofreader(),
        PlausibilityProofreader(),
        ConsistencyProofreader(),
    ]
    aggregator = ProofreaderAggregatorAgent(
        ledger=InMemoryLedger(), quorum=2, window_ms=200,
    )

    runners = [_runner(bus, registry, a) for a in (
        *predictors, consensus, *replicas, aggregator,
    )]

    try:
        req = PredictRequest(
            request_id="phase6-grid-e2e-1",
            match_id="TR1:Galatasaray-Fenerbahce",
            market="1x2",
            league_id="TR1",
            features={
                "home_advantage": 0.55,
                "home_xg": 1.4,
                "away_xg": 1.1,
            },
        )
        bus.publish(Message.new(
            PREDICT_REQUEST,
            req.as_dict(),
            producer="test.phase6.e2e",
            trace_id="trace-phase6-grid-e2e",
        ))
        _drain(runners)

        # The grid-bearing predictor voted.
        votes = bus.drain_topic(PREDICT_VOTE)
        assert len(votes) == 1, f"expected 1 vote, got {len(votes)}"
        for v in votes:
            grid = v.payload["distribution"]["score_grid"]
            assert isinstance(grid, list) and grid and isinstance(grid[0], list), (
                "live predictor emits 2D matrix; if this fails the "
                "contract has drifted again — see Phase 4-6 audit B1"
            )

        # Consensus emitted exactly one predict.final, carrying the
        # fused 2D score grid.
        finals = bus.drain_topic(PREDICT_FINAL)
        assert len(finals) == 1
        pf = PredictFinal.from_dict(finals[0].payload)
        assert pf.distribution["score_grid"] is not None
        assert isinstance(pf.distribution["score_grid"], list)
        assert isinstance(pf.distribution["score_grid"][0], list)

        # All three proofreader verdicts must be `accept` (or `warn`,
        # which still counts toward quorum). A `reject` here means the
        # consistency check is back to the wrong shape contract.
        verdicts = bus.drain_topic(PROOFREADER_VERDICT)
        assert len(verdicts) == 3, f"expected 3 verdicts, got {len(verdicts)}"
        for vm in verdicts:
            v = ProofreaderVerdict.from_dict(vm.payload)
            assert v.verdict in ("accept", "warn"), (
                f"{v.proofreader_id} returned {v.verdict!r} "
                f"(rationale={v.rationale!r}) — the score_grid shape "
                "contract between predictors/consensus and the "
                "consistency proofreader has drifted (Phase 4-6 audit B1)."
            )

        # The aggregator emits exactly one predict.approved.v1.
        approvals = bus.drain_topic(PREDICT_APPROVED)
        assert len(approvals) == 1, (
            f"expected exactly 1 predict.approved.v1 for the grid-bearing "
            f"prediction; got {len(approvals)}. This is the regression "
            "guard for Phase 4-6 audit B1."
        )
        approved = PredictApproved.from_dict(approvals[0].payload)
        assert approved.prediction_id == pf.prediction_id
        assert approved.final["distribution"]["score_grid"] is not None

        # The only proof.flag tolerated on the happy path is the
        # benign `proofreader_late_verdict_dropped` — once two
        # replicas accept and reach quorum, the aggregator emits
        # ``predict.approved.v1`` immediately and the third (in this
        # case the consistency replica's) verdict arrives "late".
        # That is by design and orthogonal to the audit B1 contract
        # we are guarding here. Anything else is an unexpected leak.
        flags = bus.drain_topic(PROOF_FLAG)
        unexpected = [
            f for f in flags
            if f.payload.get("kind") != "proofreader_late_verdict_dropped"
        ]
        assert unexpected == [], (
            f"unexpected proof.flag emissions: {unexpected}"
        )

    finally:
        for r in runners:
            r.deregister()
