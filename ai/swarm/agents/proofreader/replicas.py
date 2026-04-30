"""Phase 6.2 — Per-replica proofreader agents.

Each agent subscribes to ``predict.final``, runs ONE check from
``prediction_checks.py``, and emits a ``predict.proofreader_verdict.v1``
that the aggregator (§6.1) tallies. Per-check, not per-replica: the
swarm runs one of each by default (so N=3 ≥ quorum=2 with the
default `proofreader_replicas`). Operators can spawn additional
replicas of any one for redundancy without changing this code.

Why one agent per check (not one agent that runs all three)?

* Failure isolation — a bug in plausibility cannot mute sanity.
* Scale symmetry (Doctrine §2 Rule 5) — operator can scale the
  expensive checks (future cross-source, historical) independently.
* Diversity — the §6.1 quorum is meaningful only if the verdicts
  come from independent code paths.

This module deliberately stays thin: each agent class is roughly 30
lines because all rule logic lives in `prediction_checks.py`. Adding a
new built-in check = add a function there + a 30-line subclass here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Iterable

from common.config import cfg as _cfg

from ...sdk.types import Message, Topic
from ..payloads import (
    PredictFinal,
    ProofFlagKind,
    ProofreaderVerdict,
)
from ..topics import PREDICT_FINAL, PROOF_FLAG, PROOFREADER_VERDICT
from .prediction_checks import (
    CheckResult,
    grid_consistency_check,
    plausibility_check,
    sanity_check,
)

_log = logging.getLogger("swarm.agents.proofreader")


# ── Base agent ────────────────────────────────────────────────


class _BaseProofreaderAgent:
    """Common dispatch shell: parse `predict.final`, call `_check`,
    emit one `predict.proofreader_verdict.v1`. Subclasses set `name`
    and implement `_check`."""

    name: str = "proofreader.base"
    subscribes: tuple[Topic, ...] = (PREDICT_FINAL,)
    # Replicas publish verdicts on every well-formed candidate, plus
    # a `proof.flag` (kind=`proofreader_internal_error`) on the rare
    # path where `_check` raises an unexpected exception. Listing
    # both topics keeps the boundary tests honest.
    publishes: tuple[Topic, ...] = (PROOFREADER_VERDICT, PROOF_FLAG)
    # Names of the checks this agent ran (for the `checks_run` field
    # in the verdict — operators see which rules fired).
    checks_run: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        clock_iso: Callable[[], str] | None = None,
    ) -> None:
        self._clock_iso = clock_iso or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    def handle(self, msg: Message) -> Iterable[Message]:
        if msg.envelope.topic != PREDICT_FINAL:
            _log.warning(
                "%s: unsubscribed topic %r delivered",
                self.name, msg.envelope.topic,
            )
            return ()
        try:
            final = PredictFinal.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.final: %s", self.name, exc)
            return ()

        # Phase-6 audit F-4: an unexpected exception inside `_check`
        # used to be swallowed and converted into `reject`. That made
        # *one* buggy replica fatal regardless of quorum (a single
        # reject vetoes approval), letting a code regression in
        # plausibility silently kill predictions that sanity +
        # consistency would have approved. The dispatch shell now
        # emits a `proof.flag` (kind=proofreader_internal_error) so
        # operators see the regression *and* a `warn` vote so the
        # candidate still has a path to quorum if the other replicas
        # accept. Warn counts toward quorum (matching today's
        # plausibility-warn semantics) — the flag carries the actual
        # signal so we don't lose the failure.
        flag_msg: Message | None = None
        try:
            verdict, score, details = self._check(final)
        except Exception as exc:  # noqa: BLE001 — agent must never crash bus
            _log.exception("%s: check raised; emitting warn + flag", self.name)
            verdict, score, details = (
                "warn",
                0.0,
                [f"{self.name}: internal check error ({type(exc).__name__})"],
            )
            flag_msg = Message.new(
                PROOF_FLAG,
                {
                    "kind": ProofFlagKind.PROOFREADER_INTERNAL_ERROR,
                    "source": self.name,
                    "target": final.prediction_id,
                    "detail": (
                        f"{self.name}: {type(exc).__name__}: {exc}"
                    )[:512],
                    "exception_type": type(exc).__name__,
                },
                producer=self.name,
                trace_id=msg.envelope.trace_id,
            )

        # `flags` ⊆ `checks_run` (payload invariant). When a check
        # fires (verdict ≠ accept) we list the rule IDs in flags;
        # the human-readable detail goes into rationale so dashboards
        # can show the reason without cluttering the structured field.
        rule_ids = list(self.checks_run) if verdict != "accept" else []
        rationale = "; ".join(details) if details else ""

        out = ProofreaderVerdict(
            request_id=final.request_id,
            prediction_id=final.prediction_id,
            match_id=final.match_id,
            market=final.market,
            proofreader_id=self.name,
            verdict=verdict,
            score=score,
            checked_at=self._clock_iso(),
            flags=rule_ids,
            checks_run=list(self.checks_run),
            rationale=rationale,
            calibration_version=final.calibration_version,
        )
        verdict_msg = Message.new(
            PROOFREADER_VERDICT,
            out.as_dict(),
            producer=self.name,
            trace_id=msg.envelope.trace_id,
        )
        if flag_msg is not None:
            return (verdict_msg, flag_msg)
        return (verdict_msg,)

    def _check(self, final: PredictFinal) -> CheckResult:  # pragma: no cover
        raise NotImplementedError


# ── Concrete replicas ─────────────────────────────────────────


class SanityProofreader(_BaseProofreaderAgent):
    """Probabilities are well-formed and sum to 1±ε.

    Threshold (`cfg.proofreader_sanity_eps`) is read once at
    construction; live config reloads require restarting the agent
    process. (Phase-6 audit F-8.)
    """

    name = "proofreader.sanity.v1"
    checks_run = ("sanity.probs_well_formed",)

    def __init__(self, *, eps: float | None = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self._eps = eps if eps is not None else _cfg.proofreader_sanity_eps

    def _check(self, final: PredictFinal) -> CheckResult:
        return sanity_check(final.distribution, eps=self._eps)


class PlausibilityProofreader(_BaseProofreaderAgent):
    """No single market outcome dominates beyond the configured cap.

    Threshold (`cfg.proofreader_plausibility_max_prob`) is read once
    at construction; live config reloads require restarting the agent
    process. (Phase-6 audit F-8.)
    """

    name = "proofreader.plausibility.v1"
    checks_run = ("plausibility.max_outcome_prob",)

    def __init__(
        self, *, max_outcome_prob: float | None = None, **kw: object
    ) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self._cap = (
            max_outcome_prob
            if max_outcome_prob is not None
            else _cfg.proofreader_plausibility_max_prob
        )

    def _check(self, final: PredictFinal) -> CheckResult:
        return plausibility_check(final.distribution, max_outcome_prob=self._cap)


class ConsistencyProofreader(_BaseProofreaderAgent):
    """If a `score_grid` is attached, its marginals match `market_outcomes`.

    Threshold (`cfg.proofreader_grid_consistency_tol`) is read once
    at construction; live config reloads require restarting the agent
    process. (Phase-6 audit F-8.)
    """

    name = "proofreader.consistency.v1"
    checks_run = ("consistency.score_grid_marginals",)

    def __init__(self, *, tol: float | None = None, **kw: object) -> None:
        super().__init__(**kw)  # type: ignore[arg-type]
        self._tol = (
            tol if tol is not None else _cfg.proofreader_grid_consistency_tol
        )

    def _check(self, final: PredictFinal) -> CheckResult:
        return grid_consistency_check(final.distribution, tol=self._tol)


__all__ = [
    "SanityProofreader",
    "PlausibilityProofreader",
    "ConsistencyProofreader",
]
