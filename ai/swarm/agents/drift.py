"""Phase 6.3 — Drift agent (`drift.v1`).

Maintains rolling Brier / log-loss windows per
``(league_id, market)`` for the swarm's approved predictions. When a
window's mean metric breaches ``cfg.drift_accuracy_floor`` it emits
``maint.event.v1{kind=retrain_request}`` for every model that
contributed to the breached predictions, so the trainer can scope
its retrain.

State plane (v1): in-memory. Phase 9 lifts it to Postgres so the
agent survives a swarm restart without losing its window. The
contract here is the same — v2 just swaps the storage backend.

What this agent does NOT do:

* **Per-predictor Brier.** Consensus has already merged the
  individual predictor votes by the time we see ``predict.approved.v1``,
  so the metric we score is the swarm aggregate. ROADMAP §6.3
  carves out per-predictor metrics to v2 once the predict.vote bus
  is durably persisted; the contributing-models attribution we use
  here (every model that voted on a breached batch is named in the
  retrain_request) is the conservative-but-sound v1 substitute.
* **KS-test on feature distributions.** That branch needs the
  predictor's input feature vector on the bus, which Phase 5 keeps
  ephemeral inside the predictor process. ROADMAP §6.3 lists the
  KS-test as a separate trip condition; the wire format
  (`reason=feature_ks` in `MaintEvent`) is reserved here so the v2
  KS-test agent slots in without a schema migration.

Topology
--------

    consensus → predict.approved.v1 → drift.v1 (record predicted dist)
    storage   → match.outcome.v1    → drift.v1 (settle, compute Brier)
                                      drift.v1 → maint.event.v1

Idempotency: each ``(prediction_id, match_id)`` is settled at most
once; redelivered outcomes are silently ignored. The retrain
debounce (`cfg.trainer_debounce_sec`) lives on the trainer side —
this agent fires on every breach and lets the trainer collapse them.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from common.config import cfg as _cfg

from ..sdk.types import Message, Topic
from .payloads import MaintEvent, MatchOutcome, PredictApproved
from .topics import MAINT_EVENT, MATCH_OUTCOME, PREDICT_APPROVED

_log = logging.getLogger("swarm.agents.drift")


# ── 1X2 outcome encoding ──────────────────────────────────────


_OUTCOME_INDEX: dict[str, str] = {"H": "H", "D": "D", "A": "A"}


def _brier_score(probs: dict[str, float], realized: str) -> float:
    """3-class Brier for the 1X2 market: Σ (p_o − y_o)² over o∈{H,D,A}.

    `realized ∈ {H,D,A}`. Lower is better; perfect prediction = 0.
    Missing keys default to 0.0 (treated as "predictor said this
    outcome had probability zero" — punishes accordingly).
    """
    total = 0.0
    for outcome in ("H", "D", "A"):
        p = float(probs.get(outcome, 0.0))
        y = 1.0 if outcome == realized else 0.0
        total += (p - y) ** 2
    return total


# ── In-memory state ────────────────────────────────────────────


@dataclass
class _PendingPrediction:
    """Recorded `predict.approved.v1` waiting for its `match.outcome.v1`."""

    prediction_id: str
    match_id: str
    market: str
    league_id: str | None
    market_outcomes: dict[str, float]
    contributing_models: list[str]


@dataclass
class _Window:
    """Rolling Brier window per (league_id, market)."""

    brier: deque[float] = field(default_factory=deque)
    # Track the union of predictors that contributed to the entries
    # currently inside the window — when we trip, we emit a retrain
    # request for every one of them (we don't know which is the
    # culprit from the aggregate alone).
    models_in_window: set[str] = field(default_factory=set)


class DriftAgent:
    """Single instance. Subscribes PREDICT_APPROVED + MATCH_OUTCOME;
    publishes MAINT_EVENT on rolling-window floor breach."""

    name = "drift.v1"
    subscribes: tuple[Topic, ...] = (PREDICT_APPROVED, MATCH_OUTCOME)
    publishes: tuple[Topic, ...] = (MAINT_EVENT,)

    def __init__(
        self,
        *,
        clock_iso: Callable[[], str] | None = None,
        window_size: int | None = None,
        accuracy_floor: float | None = None,
    ) -> None:
        self._clock_iso = clock_iso or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self._window_size = (
            window_size if window_size is not None else _cfg.drift_window_size
        )
        if self._window_size < 1:
            raise ValueError(
                f"drift.v1: window_size must be >=1; got {self._window_size}"
            )
        self._floor = (
            accuracy_floor
            if accuracy_floor is not None
            else _cfg.drift_accuracy_floor
        )
        self._lock = threading.Lock()
        # Pending predictions waiting for outcomes. Keyed by
        # (match_id, market) because that's how the outcome stream
        # arrives — one outcome can settle multiple market predictions
        # for the same match.
        self._pending: dict[tuple[str, str], _PendingPrediction] = {}
        # One rolling window per (league_id, market). league_id may be
        # None for unscoped predictions; we treat that as its own
        # bucket rather than collapsing into a single global window.
        self._windows: dict[tuple[str | None, str], _Window] = {}
        # Settled outcomes — guards against redelivered MatchOutcome.
        self._settled: set[tuple[str, str]] = set()
        # Whether the *current* window for a (league, market) bucket is
        # already in a tripped state. Once tripped, we wait for the
        # window to roll a fresh full set before re-firing — otherwise
        # every additional outcome would emit a retrain_request and
        # spam the trainer.
        self._tripped: set[tuple[str | None, str]] = set()

    # ── Bus contract ───────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == PREDICT_APPROVED:
            return self._handle_approved(msg)
        if topic == MATCH_OUTCOME:
            return self._handle_outcome(msg)
        _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
        return ()

    # ── Inspection helpers (for tests / ops) ───────────────────
    def window_size(self, league_id: str | None, market: str) -> int:
        with self._lock:
            w = self._windows.get((league_id, market))
            return len(w.brier) if w else 0

    def mean_brier(self, league_id: str | None, market: str) -> float | None:
        with self._lock:
            w = self._windows.get((league_id, market))
            if not w or not w.brier:
                return None
            return sum(w.brier) / len(w.brier)

    # ── Handlers ───────────────────────────────────────────────
    def _handle_approved(self, msg: Message) -> Iterable[Message]:
        try:
            approved = PredictApproved.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.approved: %s", self.name, exc)
            return ()
        final = approved.final or {}
        dist = final.get("distribution", {})
        market_outcomes = dist.get("market_outcomes")
        if not isinstance(market_outcomes, dict):
            _log.warning(
                "%s: predict.approved %s missing market_outcomes; ignoring",
                self.name, approved.prediction_id,
            )
            return ()
        # The proofreader gauntlet has already vetted this, but defend
        # against a future producer drifting from contract.
        contributing = final.get("contributing_models") or []
        if not isinstance(contributing, list) or not contributing:
            _log.warning(
                "%s: predict.approved %s missing contributing_models; ignoring",
                self.name, approved.prediction_id,
            )
            return ()
        league_id = final.get("league_id")
        record = _PendingPrediction(
            prediction_id=approved.prediction_id,
            match_id=approved.match_id,
            market=approved.market,
            league_id=league_id,
            market_outcomes={str(k): float(v) for k, v in market_outcomes.items()},
            contributing_models=[str(m) for m in contributing],
        )
        with self._lock:
            self._pending[(approved.match_id, approved.market)] = record
        return ()

    def _handle_outcome(self, msg: Message) -> Iterable[Message]:
        try:
            outcome = MatchOutcome.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed match.outcome: %s", self.name, exc)
            return ()
        out: list[Message] = []
        with self._lock:
            # Settle every market we have for this match. Currently we
            # only score 1X2; other markets (over/under, BTTS) wait
            # for their realized labels to land in the outcome payload
            # (Phase 9). They sit in `_pending` until then.
            keys_to_score = [
                key for key in self._pending
                if key[0] == outcome.match_id and key[1] == "1x2"
            ]
            for key in keys_to_score:
                if (key[0], key[1]) in self._settled:
                    continue  # idempotent
                pending = self._pending.pop(key)
                self._settled.add(key)
                brier = _brier_score(pending.market_outcomes, outcome.outcome_1x2)
                bucket = (pending.league_id, pending.market)
                w = self._windows.setdefault(bucket, _Window())
                if len(w.brier) >= self._window_size:
                    w.brier.popleft()
                    # `models_in_window` is a coarse approximation —
                    # we don't reverse-track which model leaves with
                    # the popped sample. Acceptable for v1; the
                    # retrain target list is the union of recent
                    # contributors, which is the conservative pick.
                w.brier.append(brier)
                w.models_in_window.update(pending.contributing_models)

                # Trip check: only fire when the window is FULL — a
                # half-full window's mean is too noisy. Once tripped,
                # do not re-trip until the window has rolled
                # `window_size` fresh entries.
                if len(w.brier) >= self._window_size:
                    mean_b = sum(w.brier) / len(w.brier)
                    if mean_b > self._floor and bucket not in self._tripped:
                        out.extend(
                            self._emit_retrain_requests(
                                bucket=bucket,
                                window=w,
                                metric_value=mean_b,
                                trace_id=msg.envelope.trace_id,
                            )
                        )
                        self._tripped.add(bucket)
                    elif mean_b <= self._floor and bucket in self._tripped:
                        # Recovered — clear so future breaches re-fire.
                        self._tripped.discard(bucket)
        return out

    # ── Emission ───────────────────────────────────────────────
    def _emit_retrain_requests(
        self,
        *,
        bucket: tuple[str | None, str],
        window: _Window,
        metric_value: float,
        trace_id: str,
    ) -> list[Message]:
        league_id, market = bucket
        targets = sorted(window.models_in_window)
        produced_at = self._clock_iso()
        out: list[Message] = []
        for target in targets:
            event = MaintEvent(
                kind="retrain_request",
                target=target,
                reason="brier_floor",
                league_id=league_id,
                market=market,
                metric="brier",
                metric_value=metric_value,
                threshold=self._floor,
                sample_size=len(window.brier),
                produced_at=produced_at,
            )
            out.append(
                Message.new(
                    MAINT_EVENT,
                    event.as_dict(),
                    producer=self.name,
                    trace_id=trace_id,
                )
            )
        return out


__all__ = ["DriftAgent"]
