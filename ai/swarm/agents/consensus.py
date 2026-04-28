"""Phase 5.2 — `consensus.v1` agent.

Collects ``predict.vote`` messages per ``(match_id, market, request_id)``
key, fuses them into a calibrated probability distribution, and
publishes exactly one ``predict.final``. Late votes after the
single-publication checkpoint are dropped with a ``proof.flag``
(``kind=late_vote_dropped``); the quorum-empty path emits
``proof.flag`` (``kind=consensus_no_votes``) with **no**
``predict.final``.

Closing the window
------------------

The bus is poll-driven and our handlers are sync, so there is no
implicit clock-tick that closes a window. Two paths trigger fusion:

  * **All expected predictors voted** — the moment the last expected
    voter's ``predict.vote`` arrives, ``handle`` finalizes immediately
    (no idle wait). Tests + the seed demo rely on this.
  * **`flush_expired(now=...)`** — a runner / scheduler calls this
    periodically; any in-flight key whose first vote is older than
    ``cfg.consensus_window_ms`` is finalized with whatever votes
    landed (possibly zero ⇒ ``consensus_no_votes``).

Single-publication is enforced by a Phase 4.7-style ``Ledger`` keyed
on the deterministic ``prediction_id``.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from common.config import cfg as _cfg

from ..sdk.types import Message, Topic
from .payloads import (
    PredictFinal,
    PredictRequest,
    PredictVote,
    derive_prediction_id,
)
from .reactor import InMemoryLedger, Ledger
from .topics import PREDICT_FINAL, PREDICT_VOTE, PROOF_FLAG
from .predictors._base import (
    CalibrationStore,
    CalibrationTable,
    InMemoryCalibrationStore,
)

_log = logging.getLogger(__name__)


# Markets share their canonical outcome ordering — used to align
# heterogeneous votes before fusing.
_MARKET_OUTCOMES: dict[str, tuple[str, ...]] = {
    "1x2": ("H", "D", "A"),
    "ah": ("home", "away"),
    "ou_2_5": ("over", "under"),
    "btts": ("yes", "no"),
}


@dataclass
class _PendingFusion:
    """Per-key accumulator. One per ``(match_id, market, request_id)``."""

    match_id: str
    market: str
    request_id: str
    league_id: str | None = None
    profile_id: str | None = None
    first_seen_ms: float = 0.0
    votes: list[PredictVote] = field(default_factory=list)
    voters: set[str] = field(default_factory=set)
    # Cached on first vote so consensus only hits the calibration store
    # once per (match, market, request) — not once per vote handle.
    # Cache the *table itself*, not just the version: ``_finalize`` needs
    # ``cal.apply(...)`` which is otherwise a second store call (the
    # ROADMAP §5.2 "single calibration-store hit per request" claim).
    prediction_id: str | None = None
    calibration_version: int = 0
    calibration_table: "CalibrationTable | None" = None


def _fuse_distributions(
    votes: list[PredictVote],
    weights: dict[str, float],
    market: str,
) -> dict[str, float]:
    """Weighted average of compatible market_outcomes pmfs.

    Skips outcomes a vote doesn't list (so a Dixon-Coles 1X2 vote and
    an Elo 1X2 vote are still fused even if one names them with extra
    keys). Returns a normalized pmf.
    """
    outcomes = _MARKET_OUTCOMES.get(market, ())
    fused: dict[str, float] = {o: 0.0 for o in outcomes}
    z = 0.0
    for v in votes:
        w = max(0.0, weights.get(v.predictor_id, 1.0))
        if w <= 0.0:
            continue
        pmf = v.distribution.get("market_outcomes") or {}
        for o in outcomes:
            fused[o] += w * float(pmf.get(o, 0.0))
        z += w
    if z > 0.0:
        for o in fused:
            fused[o] /= z
    s = sum(fused.values())
    if s > 0.0:
        for o in fused:
            fused[o] /= s
    return fused


def _fuse_score_grids(votes: list[PredictVote]) -> list[list[float]] | None:
    """Average score grids across votes that produced one.

    None when no contributing vote carried a grid (Phase 6.2
    consistency check is skipped for those markets).
    """
    grids: list[list[list[float]]] = []
    for v in votes:
        g = v.distribution.get("score_grid")
        if g and isinstance(g, list) and g and isinstance(g[0], list):
            grids.append(g)
    if not grids:
        return None
    rows = len(grids[0])
    cols = len(grids[0][0])
    out = [[0.0] * cols for _ in range(rows)]
    for g in grids:
        for i in range(rows):
            for j in range(cols):
                out[i][j] += float(g[i][j])
    n = float(len(grids))
    s = 0.0
    for i in range(rows):
        for j in range(cols):
            out[i][j] /= n
            s += out[i][j]
    if s > 0.0:
        for i in range(rows):
            for j in range(cols):
                out[i][j] /= s
    return out


class ConsensusAgent:
    """Phase 5.2 fusion + calibration agent."""

    name = "consensus.v1"
    subscribes: tuple[Topic, ...] = (PREDICT_VOTE,)
    publishes: tuple[Topic, ...] = (PREDICT_FINAL, PROOF_FLAG)

    def __init__(
        self,
        *,
        expected_predictors: Iterable[str],
        ledger: Ledger | None = None,
        calibration_store: CalibrationStore | None = None,
        weights: dict[str, float] | None = None,
        clock_ms: callable | None = None,
        clock_iso: callable | None = None,
        window_ms: int | None = None,
        min_voters: int | None = None,
        min_confidence: float | None = None,
        max_pending: int | None = None,
    ) -> None:
        self._expected: tuple[str, ...] = tuple(expected_predictors)
        if not self._expected:
            raise ValueError(
                "consensus.v1: expected_predictors must list at least one"
            )
        self._ledger: Ledger = ledger or InMemoryLedger()
        self._calibration: CalibrationStore = (
            calibration_store or InMemoryCalibrationStore()
        )
        self._weights: dict[str, float] = dict(weights or {})
        self._clock_ms = clock_ms or (
            lambda: datetime.now(timezone.utc).timestamp() * 1000.0
        )
        self._clock_iso = clock_iso or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self._window_ms = (
            window_ms if window_ms is not None else _cfg.consensus_window_ms
        )
        self._min_voters = (
            min_voters if min_voters is not None else _cfg.consensus_min_voters
        )
        self._min_confidence = (
            min_confidence
            if min_confidence is not None
            else _cfg.consensus_min_confidence
        )
        self._max_pending = (
            max_pending
            if max_pending is not None
            else _cfg.consensus_max_pending
        )
        self._lock = threading.Lock()
        # Insertion-ordered dict doubles as an LRU for overflow eviction.
        self._pending: dict[tuple[str, str, str], _PendingFusion] = {}

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            vote = PredictVote.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.vote: %s", self.name, exc)
            return ()

        # ── Per-vote confidence floor (SWARM.md consensus algo step 2).
        # Below-threshold votes are dropped silently — consensus simply
        # has one fewer voter. We log + flag at debug so a misbehaving
        # predictor is observable without spamming proof.flag.
        if vote.confidence < self._min_confidence:
            _log.debug(
                "%s: dropping low-confidence vote predictor=%s conf=%.3f < %.3f",
                self.name, vote.predictor_id, vote.confidence,
                self._min_confidence,
            )
            return ()

        key = (vote.match_id, vote.market, vote.request_id)
        overflow_flags: list[Message] = []

        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                # Pending-set bound: evict oldest insertion + flag.
                if len(self._pending) >= self._max_pending:
                    evict_key, evicted = next(iter(self._pending.items()))
                    del self._pending[evict_key]
                    overflow_flags.append(
                        Message.new(
                            PROOF_FLAG,
                            {
                                "kind": "consensus_overflow",
                                "agent": self.name,
                                "match_id": evicted.match_id,
                                "market": evicted.market,
                                "request_id": evicted.request_id,
                                "max_pending": self._max_pending,
                            },
                            producer=self.name,
                            trace_id=msg.envelope.trace_id,
                        )
                    )
                pending = _PendingFusion(
                    match_id=vote.match_id,
                    market=vote.market,
                    request_id=vote.request_id,
                    league_id=vote.league_id,
                    profile_id=vote.profile_id,
                    first_seen_ms=self._clock_ms(),
                )
                self._pending[key] = pending
            elif pending.profile_id is None and vote.profile_id is not None:
                # First vote without context, second with — keep it.
                pending.profile_id = vote.profile_id
                pending.league_id = pending.league_id or vote.league_id

            # Lazily compute + cache prediction_id AND the calibration
            # table once context is known. _finalize reuses both — this
            # is what enforces "single calibration-store hit per request"
            # (ROADMAP §5.2).
            if pending.prediction_id is None:
                profile_id = self._resolve_profile(pending)
                cal = self._calibration.latest(profile_id, pending.market)
                pending.calibration_table = cal
                pending.calibration_version = cal.version
                pending.prediction_id = derive_prediction_id(
                    match_id=pending.match_id,
                    market=pending.market,
                    request_id=pending.request_id,
                    calibration_version=cal.version,
                )
            prediction_id = pending.prediction_id

            # ── Single-publication / late-vote guard ───────────────
            if self._ledger.already_processed(self.name, prediction_id):
                # Drop pending bookkeeping; already finalized.
                self._pending.pop(key, None)
                return (
                    *overflow_flags,
                    Message.new(
                        PROOF_FLAG,
                        {
                            "kind": "late_vote_dropped",
                            "agent": self.name,
                            "predictor_id": vote.predictor_id,
                            "match_id": vote.match_id,
                            "market": vote.market,
                            "request_id": vote.request_id,
                            "prediction_id": prediction_id,
                        },
                        producer=self.name,
                        trace_id=msg.envelope.trace_id,
                    ),
                )

            # Idempotency: if the same predictor re-votes for the same
            # request, accept the latest (it's a deterministic re-emit
            # by the runner). Don't double-count.
            if vote.predictor_id in pending.voters:
                # Replace the prior vote in-place so weights stay sane.
                for i, v in enumerate(pending.votes):
                    if v.predictor_id == vote.predictor_id:
                        pending.votes[i] = vote
                        break
            else:
                pending.votes.append(vote)
                pending.voters.add(vote.predictor_id)

            all_in = pending.voters >= set(self._expected)
            if not all_in:
                return tuple(overflow_flags)

            # All expected voters in → finalize now.
            del self._pending[key]

        return [*overflow_flags, *self._finalize(pending, msg.envelope.trace_id)]

    # ── Window flush (called by runner / test) ──────────────────────
    def note_request(self, req: "PredictRequest") -> None:
        """Tell consensus a request is in flight before any vote arrives.

        Required for the §5.2 quorum-empty path: if every predictor
        crashes or DLQs, no vote ever lands and there'd be nothing
        for ``flush_expired`` to find. Calling ``note_request`` on
        emission gives the window a starting timestamp so the
        ``consensus_no_votes`` proof.flag actually fires.

        Also seeds ``profile_id``/``league_id`` so the calibration
        store can be queried correctly even when no vote ever lands.
        """
        key = (req.match_id, req.market, req.request_id)
        with self._lock:
            if key in self._pending:
                return  # already tracking this key
            self._pending[key] = _PendingFusion(
                match_id=req.match_id,
                market=req.market,
                request_id=req.request_id,
                league_id=req.league_id,
                profile_id=req.profile_id,
                first_seen_ms=self._clock_ms(),
            )

    def flush_expired(self, *, now_ms: float | None = None) -> list[Message]:
        """Finalize keys whose window elapsed; return outbound messages."""
        now = now_ms if now_ms is not None else self._clock_ms()
        ready: list[_PendingFusion] = []
        with self._lock:
            for key in list(self._pending.keys()):
                p = self._pending[key]
                if (now - p.first_seen_ms) >= self._window_ms:
                    ready.append(p)
                    del self._pending[key]

        out: list[Message] = []
        for p in ready:
            out.extend(self._finalize(p, trace_id=None))
        return out

    def flush_all(self) -> list[Message]:
        """Force-finalize every pending key (test helper / shutdown)."""
        with self._lock:
            keys = list(self._pending.keys())
            ready = [self._pending.pop(k) for k in keys]
        out: list[Message] = []
        for p in ready:
            out.extend(self._finalize(p, trace_id=None))
        return out

    # ── Internals ───────────────────────────────────────────────────
    def _resolve_profile(self, pending: _PendingFusion) -> str:
        """Phase 13a will resolve via CompetitionConfig. Until then we
        prefer the explicit ``profile_id`` carried on the request/vote
        (set by API gateway / LivePredictorReactor); fall back to
        ``league_id`` (Phase 5 default per ROADMAP §5.4); and finally
        to the literal ``"default"`` so the calibration table lookup
        is always well-defined.
        """
        return pending.profile_id or pending.league_id or "default"

    def _finalize(
        self,
        pending: _PendingFusion,
        trace_id: str | None,
    ) -> list[Message]:
        # Resolve calibration once if not already cached (the
        # quorum-empty path may finalize without ever computing it).
        if pending.prediction_id is None:
            profile_id = self._resolve_profile(pending)
            cal = self._calibration.latest(profile_id, pending.market)
            pending.calibration_table = cal
            pending.calibration_version = cal.version
            pending.prediction_id = derive_prediction_id(
                match_id=pending.match_id,
                market=pending.market,
                request_id=pending.request_id,
                calibration_version=cal.version,
            )
        prediction_id = pending.prediction_id

        # Mark first — single-publication is the primary invariant.
        # Subsequent votes for this prediction_id will be dropped.
        if self._ledger.already_processed(self.name, prediction_id):
            return []  # someone else (concurrent flush) finalized
        self._ledger.mark_processed(self.name, prediction_id)

        # Quorum-empty: no votes at all → no predict.final, only flag.
        if not pending.votes:
            return [
                Message.new(
                    PROOF_FLAG,
                    {
                        "kind": "consensus_no_votes",
                        "agent": self.name,
                        "match_id": pending.match_id,
                        "market": pending.market,
                        "request_id": pending.request_id,
                        "prediction_id": prediction_id,
                    },
                    producer=self.name,
                    trace_id=trace_id or "",
                ),
            ]

        market = pending.market
        weights = {v.predictor_id: self._weights.get(v.predictor_id, 1.0)
                   for v in pending.votes}
        raw_pmf = _fuse_distributions(pending.votes, weights, market)

        # Calibration: apply isotonic per outcome, then renormalize so
        # we still publish a valid pmf. Reuse the table cached on the
        # pending key so we hit the calibration store exactly once per
        # request (ROADMAP §5.2 invariant).
        profile_id = self._resolve_profile(pending)
        cal = pending.calibration_table or self._calibration.latest(
            profile_id, market
        )
        calibrated = {o: cal.apply(p) for o, p in raw_pmf.items()}
        z = sum(calibrated.values())
        if z > 0.0:
            calibrated = {o: p / z for o, p in calibrated.items()}
        else:
            calibrated = raw_pmf

        score_grid = _fuse_score_grids(pending.votes)

        swarm_confidence = float(
            sum(v.confidence for v in pending.votes) / len(pending.votes)
        )

        degraded = len(pending.voters) < self._min_voters
        if degraded:
            degraded_reason = (
                f"only {len(pending.voters)}/{len(self._expected)} predictors voted "
                f"(min_voters={self._min_voters})"
            )
        else:
            degraded_reason = ""

        final = PredictFinal(
            request_id=pending.request_id,
            prediction_id=prediction_id,
            match_id=pending.match_id,
            market=market,
            distribution={
                "market_outcomes": calibrated,
                "score_grid": score_grid,
            },
            weights=weights,
            contributing_models=sorted(pending.voters),
            calibration_version=cal.version,
            swarm_confidence=swarm_confidence,
            degraded=degraded,
            degraded_reason=degraded_reason,
            produced_at=self._clock_iso(),
            league_id=pending.league_id,
            profile_id=profile_id,
        )
        return [
            Message.new(
                PREDICT_FINAL,
                final.as_dict(),
                producer=self.name,
                trace_id=trace_id or "",
            ),
        ]


__all__ = ["ConsensusAgent"]
