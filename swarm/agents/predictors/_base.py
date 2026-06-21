"""Predictor base class + CalibrationStore Protocol.

Every Phase 5 predictor is an Agent that:

  * subscribes to ``predict.request``
  * publishes ``predict.vote``
  * is **idempotent** on ``(match_id, market, request_id)`` — the
    same request always yields the same vote (no hidden RNG, no
    wall-clock features outside ``produced_at``).
  * runs CPU-only by default; Phase 11 may select GPU. The
    ``cpu_only`` parity test (per-predictor) must hold within
    log-loss ε = 1e-6 of whichever device is chosen.

The ``CalibrationStore`` Protocol is the consensus-side seam
(per ROADMAP §5.4). Phase 5 ships the in-memory backend; Phase 9
adds the Postgres backend; Phase 16 adds the FeedReader backend.
The consensus code reads through the Protocol only — it never
imports a concrete store.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from ...sdk.types import Message
from ..payloads import PredictRequest, PredictVote
from ..topics import PREDICT_REQUEST, PREDICT_VOTE

_log = logging.getLogger(__name__)


# ── CalibrationStore Protocol ──────────────────────────────────


@dataclass(frozen=True)
class CalibrationTable:
    """Isotonic table snapshot (one per `(profile_id, market, version)`)."""

    profile_id: str
    market: str
    version: int
    # Monotone non-decreasing pair: x[i] -> y[i]. Empty ⇒ identity.
    x: tuple[float, ...] = ()
    y: tuple[float, ...] = ()

    def apply(self, p: float) -> float:
        """Map raw probability ``p`` through the isotonic table.

        Empty table means "no calibration learned yet" — return the
        input unchanged. We use a step-function lookup (PAV is what
        produced ``y``); inputs outside ``x`` clamp to the endpoints.
        """
        if not self.x:
            return p
        if p <= self.x[0]:
            return self.y[0]
        if p >= self.x[-1]:
            return self.y[-1]
        # Binary search on x; small tables — linear is fine.
        lo, hi = 0, len(self.x) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.x[mid] < p:
                lo = mid + 1
            else:
                hi = mid
        return self.y[max(lo - 1, 0)]


class CalibrationStore(Protocol):
    """Consensus-side seam. Phase 16 swaps the backend, not the contract."""

    def latest(self, profile_id: str, market: str) -> CalibrationTable: ...

    def upsert(self, table: CalibrationTable) -> None: ...


class InMemoryCalibrationStore:
    """Default backend (tests + CI + `make swarm.demo`)."""

    def __init__(self) -> None:
        self._latest: dict[tuple[str, str], CalibrationTable] = {}

    def latest(self, profile_id: str, market: str) -> CalibrationTable:
        key = (profile_id, market)
        return self._latest.get(
            key,
            CalibrationTable(profile_id=profile_id, market=market, version=0),
        )

    def upsert(self, table: CalibrationTable) -> None:
        self._latest[(table.profile_id, table.market)] = table


# ── Predictor base ────────────────────────────────────────────


def softmax(scores: dict[str, float]) -> dict[str, float]:
    """Numerically stable softmax over a dict of outcome → logit."""
    if not scores:
        return {}
    m = max(scores.values())
    exps = {k: math.exp(v - m) for k, v in scores.items()}
    z = sum(exps.values())
    if z <= 0.0:
        # Degenerate case (shouldn't happen for finite logits) — fall
        # back to uniform so the consumer always sees a valid pmf.
        n = len(scores)
        return {k: 1.0 / n for k in scores}
    return {k: v / z for k, v in exps.items()}


@dataclass(frozen=True)
class PredictorContext:
    """Inputs the runtime hands to ``PredictorAgent.predict``.

    Kept separate from ``PredictRequest`` so subclasses can ignore
    payload bookkeeping (request_id, profile_id) and focus on the
    feature dict + market.
    """

    request: PredictRequest
    features: dict[str, Any]


# Markets every must-have predictor supports. Subclasses may narrow
# via :pyattr:`PredictorAgent.supported_markets`. Unsupported markets
# yield no vote (consensus simply sees one fewer voter).
_DEFAULT_SUPPORTED_MARKETS: tuple[str, ...] = (
    "1x2", "ah", "ou_2_5", "btts",
)


class PredictorAgent:
    """Common behavior for the Phase 5 predictor roster."""

    predictor_id: str = ""
    supported_markets: tuple[str, ...] = _DEFAULT_SUPPORTED_MARKETS
    features_version: str = "v1"
    name: str = ""  # bound in __init__ from predictor_id
    subscribes: tuple[str, ...] = (PREDICT_REQUEST,)
    publishes: tuple[str, ...] = (PREDICT_VOTE,)

    def __init__(self, *, clock: Any = None) -> None:
        if not self.predictor_id:
            raise ValueError(
                f"{type(self).__name__}: predictor_id class attr is required"
            )
        if not self.features_version:
            # Non-empty features_version is the consensus / Trainer-Reactor
            # contract: a vote with empty features_version is unattributable
            # to any model artifact and breaks Phase 6 calibration backfill
            # (audit §P4). Subclasses must override the base default.
            raise ValueError(
                f"{type(self).__name__}: features_version class attr is required"
            )
        # Use predictor_id as the agent name for swarmctl visibility.
        self.name = self.predictor_id
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            req = PredictRequest.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.request: %s", self.name, exc)
            return ()

        if req.market not in self.supported_markets:
            return ()  # silent — consensus tolerates fewer voters

        try:
            distribution, confidence = self.predict(
                PredictorContext(request=req, features=dict(req.features))
            )
        except Exception:  # noqa: BLE001 — runner converts to retry/DLQ
            _log.exception(
                "%s: predict() raised on request_id=%s",
                self.name, req.request_id,
            )
            raise

        # Belt-and-braces sanity. A buggy subclass would otherwise
        # poison consensus; reject here so the runner retries / DLQs.
        outcomes = distribution.get("market_outcomes")
        if not isinstance(outcomes, dict):
            raise ValueError(
                f"{self.name}: market_outcomes must be a dict"
            )
        if not outcomes:
            # Opt-in predictors (e.g. lgbm_market without odds) signal
            # "I have nothing to say" via an empty pmf. Treat that as a
            # silent abstention so consensus simply has one fewer voter.
            return ()
        s = sum(float(v) for v in outcomes.values())
        if not 0.99 <= s <= 1.01:
            raise ValueError(
                f"{self.name}: market_outcomes sums to {s:.4f}, not 1.0"
            )

        vote = PredictVote(
            request_id=req.request_id,
            match_id=req.match_id,
            market=req.market,
            predictor_id=self.predictor_id,
            distribution=distribution,
            confidence=float(confidence),
            produced_at=self._clock(),
            features_version=self.features_version,
            league_id=req.league_id,
            profile_id=req.profile_id,
            metadata={},
        )
        return (
            Message.new(
                PREDICT_VOTE,
                vote.as_dict(),
                producer=self.predictor_id,
                trace_id=msg.envelope.trace_id,
            ),
        )

    # ── Subclass override ───────────────────────────────────────────
    def predict(
        self, ctx: PredictorContext
    ) -> tuple[dict[str, Any], float]:
        """Return (distribution, confidence) for ``ctx``.

        ``distribution`` is ``{"market_outcomes": dict, "score_grid": list|None}``;
        ``market_outcomes`` is a probability dict that sums to 1.0;
        ``score_grid`` is the optional 2D probability matrix
        (Dixon-Coles + the XGB pair populate; Elo + market models
        leave ``None``). ``confidence`` is in [0, 1].
        """
        raise NotImplementedError


__all__ = [
    "CalibrationStore",
    "CalibrationTable",
    "InMemoryCalibrationStore",
    "PredictorAgent",
    "PredictorContext",
    "softmax",
]
