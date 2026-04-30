"""Phase 6.1 — Proofreader aggregator.

Consumes ``predict.proofreader_verdict.v1`` from each individual
proofreader replica plus ``predict.final`` (the candidate). Inside a
quorum window of ``cfg.proofreader_quorum_window_ms`` it counts
``accept`` and ``warn`` verdicts. When the count reaches
``cfg.proofreader_quorum`` (=⌊N/2⌋+1, where N=cfg.proofreader_replicas)
it publishes ``predict.approved.v1`` exactly once. A single ``reject``
vote is fatal — quorum is irrelevant if any replica rejected.

Topology (locked decision per docs/reports/pre-phase6-roadmap.md
§6 Wave A.1):

    predictors → consensus → predict.final ─┐
                                            ├→ proofreader_aggregator → predict.approved.v1 → cache.v1
    proofreaders × N → predict.proofreader_verdict.v1 ─┘

This agent is the SOLE producer of ``predict.approved.v1``; the
boundary-discipline test (Wave A.3) enforces that. It does NOT run
checks itself — the per-replica ProofreaderAgent (built in §6.2)
owns the rule logic via ``swarm.agents.proofreader.checks``.

Failure modes (each emits a proof.flag, never an exception that
kills the agent loop):

* ``proofreader_no_quorum``           — window elapsed without enough
                                        accept/warn votes.
* ``proofreader_rejected``            — at least one ``reject`` vote.
* ``proofreader_late_verdict_dropped`` — verdict arrived after finalize.
* ``proofreader_duplicate_approval``  — the ledger already saw this
                                        prediction_id (re-emit guard).
* ``proofreader_overflow``            — pending-set saturated, oldest
                                        candidate evicted.

Idempotency: keyed on ``prediction_id``. The ledger uses the same
``InMemoryLedger`` contract as Phase 4 reactors so a future Postgres-
backed ledger drops in without surgery.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from common.config import cfg as _cfg

from ...sdk.types import Message, Topic
from ..payloads import (
    PredictApproved,
    PredictFinal,
    ProofFlagKind,
    ProofreaderVerdict,
)
from ..reactor import InMemoryLedger, Ledger
from ..topics import (
    PREDICT_APPROVED,
    PREDICT_FINAL,
    PROOFREADER_VERDICT,
    PROOF_FLAG,
)

_log = logging.getLogger("swarm.agents.proofreader_aggregator")


# ── Internal pending-state ─────────────────────────────────────


@dataclass
class _Pending:
    """Per-(prediction_id) bookkeeping. ``final`` may be None until
    the ``predict.final`` candidate arrives — verdicts can theoretically
    land first if the proofreader bus path is shorter than the
    aggregator's. We hold them and finalize once both sides are known
    (or the window elapses)."""

    prediction_id: str
    request_id: str
    match_id: str
    market: str
    first_seen_ms: float
    final: PredictFinal | None = None
    verdicts: dict[str, ProofreaderVerdict] = field(default_factory=dict)

    def accept_warn_count(self) -> int:
        return sum(
            1 for v in self.verdicts.values()
            if v.verdict in ("accept", "warn")
        )

    def has_reject(self) -> bool:
        return any(v.verdict == "reject" for v in self.verdicts.values())

    def approvers(self) -> list[str]:
        # Stable, sorted for deterministic envelope contents.
        return sorted(
            v.proofreader_id for v in self.verdicts.values()
            if v.verdict in ("accept", "warn")
        )


# ── Aggregator agent ──────────────────────────────────────────


class ProofreaderAggregatorAgent:
    """Single instance per swarm. SOLE producer of predict.approved.v1."""

    name = "proofreader_aggregator.v1"
    subscribes: tuple[Topic, ...] = (PREDICT_FINAL, PROOFREADER_VERDICT)
    publishes: tuple[Topic, ...] = (PREDICT_APPROVED, PROOF_FLAG)

    def __init__(
        self,
        *,
        ledger: Ledger | None = None,
        clock_ms: Callable[[], float] | None = None,
        clock_iso: Callable[[], str] | None = None,
        window_ms: int | None = None,
        quorum: int | None = None,
        max_pending: int | None = None,
    ) -> None:
        self._ledger: Ledger = ledger or InMemoryLedger()
        self._clock_ms: Callable[[], float] = clock_ms or (
            lambda: datetime.now(timezone.utc).timestamp() * 1000.0
        )
        self._clock_iso: Callable[[], str] = clock_iso or (
            lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        self._window_ms = (
            window_ms if window_ms is not None
            else _cfg.proofreader_quorum_window_ms
        )
        self._quorum = quorum if quorum is not None else _cfg.proofreader_quorum
        if self._quorum < 1:
            raise ValueError(
                f"proofreader_aggregator.v1: quorum must be >=1; got {self._quorum}"
            )
        # Same default cap as consensus (cfg.consensus_max_pending).
        # The proofreader load is strictly ≤ consensus load so this is
        # never the bottleneck in practice; we still want the bound to
        # avoid unbounded memory on a stuck producer.
        self._max_pending = (
            max_pending if max_pending is not None else _cfg.consensus_max_pending
        )
        self._lock = threading.Lock()
        # Insertion-ordered for LRU eviction.
        self._pending: dict[str, _Pending] = {}
        # Overflow-eviction events buffered inside the lock; emitted
        # by the caller after the lock is released so we never publish
        # while holding `_lock`. Each entry is the evicted `_Pending`.
        self._overflow_buffer: list[_Pending] = []

    # ── Bus contract ───────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        topic = msg.envelope.topic
        if topic == PREDICT_FINAL:
            return self._handle_final(msg)
        if topic == PROOFREADER_VERDICT:
            return self._handle_verdict(msg)
        _log.warning("%s: unsubscribed topic %r delivered", self.name, topic)
        return ()

    # ── Window flush (runner / shutdown) ───────────────────────
    def flush_expired(self, *, now_ms: float | None = None) -> list[Message]:
        """Finalize candidates whose window elapsed. Used by the runner
        to advance time when no new message arrived to trigger
        ``handle()`` (mirrors ConsensusAgent.flush_expired)."""
        now = now_ms if now_ms is not None else self._clock_ms()
        ready: list[_Pending] = []
        with self._lock:
            for pid in list(self._pending.keys()):
                p = self._pending[pid]
                if (now - p.first_seen_ms) >= self._window_ms:
                    ready.append(p)
                    del self._pending[pid]
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

    # ── Handlers ───────────────────────────────────────────────
    def _handle_final(self, msg: Message) -> Iterable[Message]:
        try:
            final = PredictFinal.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed predict.final: %s", self.name, exc)
            return ()

        with self._lock:
            # Already approved? Drop silently (idempotency is handled
            # by the ledger; the candidate may simply be a re-emit).
            if self._ledger.already_processed(self.name, final.prediction_id):
                return ()
            p = self._pending.get(final.prediction_id)
            if p is None:
                self._evict_if_full_locked()
                p = _Pending(
                    prediction_id=final.prediction_id,
                    request_id=final.request_id,
                    match_id=final.match_id,
                    market=final.market,
                    first_seen_ms=self._clock_ms(),
                )
                self._pending[final.prediction_id] = p
            # Idempotent on the candidate too — multiple finals for the
            # same prediction_id keep the first one (deterministic).
            if p.final is None:
                p.final = final
            # See if quorum is already satisfied (verdicts may have
            # arrived before the candidate).
            finalize_out = self._maybe_finalize_locked(
                p, trace_id=msg.envelope.trace_id
            )
            overflow_out = self._drain_overflow_locked(msg.envelope.trace_id)
        return overflow_out + finalize_out

    def _handle_verdict(self, msg: Message) -> Iterable[Message]:
        try:
            verdict = ProofreaderVerdict.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning(
                "%s: malformed proofreader_verdict: %s", self.name, exc
            )
            return ()

        with self._lock:
            # Late verdict for an already-finalized candidate?
            if self._ledger.already_processed(self.name, verdict.prediction_id):
                return (
                    Message.new(
                        PROOF_FLAG,
                        {
                            "kind": ProofFlagKind.PROOFREADER_LATE_VERDICT_DROPPED,
                            "agent": self.name,
                            "proofreader_id": verdict.proofreader_id,
                            "prediction_id": verdict.prediction_id,
                            "match_id": verdict.match_id,
                            "market": verdict.market,
                            "request_id": verdict.request_id,
                        },
                        producer=self.name,
                        trace_id=msg.envelope.trace_id,
                    ),
                )
            p = self._pending.get(verdict.prediction_id)
            if p is None:
                # Verdict arrived before the candidate — track
                # provisionally. This is rare in practice (proofreaders
                # are downstream of consensus) but the bus does not
                # guarantee ordering across topics.
                self._evict_if_full_locked()
                p = _Pending(
                    prediction_id=verdict.prediction_id,
                    request_id=verdict.request_id,
                    match_id=verdict.match_id,
                    market=verdict.market,
                    first_seen_ms=self._clock_ms(),
                )
                self._pending[verdict.prediction_id] = p
            # One verdict per (proofreader_id, prediction_id). A re-emit
            # by the same replica overwrites in place — deterministic.
            p.verdicts[verdict.proofreader_id] = verdict

            finalize_out = self._maybe_finalize_locked(
                p, trace_id=msg.envelope.trace_id
            )
            overflow_out = self._drain_overflow_locked(msg.envelope.trace_id)
        return overflow_out + finalize_out

    # ── Internals ──────────────────────────────────────────────
    def _evict_if_full_locked(self) -> None:
        if len(self._pending) >= self._max_pending:
            evict_pid, evicted = next(iter(self._pending.items()))
            del self._pending[evict_pid]
            _log.warning(
                "%s: pending overflow — evicted prediction_id=%s",
                self.name, evict_pid,
            )
            # Buffer the eviction; the caller drains the buffer
            # *after* releasing `_lock` so we never publish from
            # inside it (mirrors the consensus-overflow pattern).
            self._overflow_buffer.append(evicted)

    def _drain_overflow_locked(self, trace_id: str) -> list[Message]:
        """Caller MUST hold `_lock` (we mutate `_overflow_buffer`),
        but the returned messages are emitted by the caller after
        the lock is released."""
        if not self._overflow_buffer:
            return []
        out: list[Message] = []
        for evicted in self._overflow_buffer:
            out.append(
                Message.new(
                    PROOF_FLAG,
                    {
                        "kind": ProofFlagKind.PROOFREADER_OVERFLOW,
                        "agent": self.name,
                        "prediction_id": evicted.prediction_id,
                        "match_id": evicted.match_id,
                        "market": evicted.market,
                        "request_id": evicted.request_id,
                        "verdict_count": len(evicted.verdicts),
                        "final_present": evicted.final is not None,
                    },
                    producer=self.name,
                    trace_id=trace_id or "",
                )
            )
        self._overflow_buffer.clear()
        return out

    def _maybe_finalize_locked(
        self, p: _Pending, *, trace_id: str
    ) -> list[Message]:
        # We need the candidate (predict.final) before we can publish;
        # verdicts alone never finalize.
        if p.final is None:
            return []
        # A reject vote is fatal regardless of quorum (§6.1 contract).
        if p.has_reject():
            del self._pending[p.prediction_id]
            return self._finalize(p, trace_id=trace_id)
        # Have we hit quorum?
        if p.accept_warn_count() >= self._quorum:
            del self._pending[p.prediction_id]
            return self._finalize(p, trace_id=trace_id)
        return []

    def _finalize(
        self, p: _Pending, *, trace_id: str | None
    ) -> list[Message]:
        # Single-publication guard. Mark first; the ledger contract
        # rejects double-marks idempotently.
        if self._ledger.already_processed(self.name, p.prediction_id):
            return [
                Message.new(
                    PROOF_FLAG,
                    {
                        "kind": ProofFlagKind.PROOFREADER_DUPLICATE_APPROVAL,
                        "agent": self.name,
                        "prediction_id": p.prediction_id,
                        "match_id": p.match_id,
                        "market": p.market,
                        "request_id": p.request_id,
                    },
                    producer=self.name,
                    trace_id=trace_id or "",
                )
            ]
        self._ledger.mark_processed(self.name, p.prediction_id)

        # Reject path — at least one reject vote.
        if p.has_reject():
            rejecters = sorted(
                v.proofreader_id for v in p.verdicts.values()
                if v.verdict == "reject"
            )
            return [
                Message.new(
                    PROOF_FLAG,
                    {
                        "kind": ProofFlagKind.PROOFREADER_REJECTED,
                        "agent": self.name,
                        "prediction_id": p.prediction_id,
                        "match_id": p.match_id,
                        "market": p.market,
                        "request_id": p.request_id,
                        "rejected_by": rejecters,
                        "verdict_count": len(p.verdicts),
                    },
                    producer=self.name,
                    trace_id=trace_id or "",
                )
            ]

        # Approval path — quorum reached, no reject votes.
        if p.final is not None and p.accept_warn_count() >= self._quorum:
            approvers = p.approvers()
            approved = PredictApproved(
                request_id=p.request_id,
                prediction_id=p.prediction_id,
                match_id=p.match_id,
                market=p.market,
                approved_at=self._clock_iso(),
                approved_by=approvers,
                verdict_count=len(p.verdicts),
                quorum=self._quorum,
                final=p.final.as_dict(),
                calibration_version=p.final.calibration_version,
            )
            return [
                Message.new(
                    PREDICT_APPROVED,
                    approved.as_dict(),
                    producer=self.name,
                    trace_id=trace_id or "",
                )
            ]

        # Window-elapsed path — neither approved nor rejected.
        return [
            Message.new(
                PROOF_FLAG,
                {
                    "kind": ProofFlagKind.PROOFREADER_NO_QUORUM,
                    "agent": self.name,
                    "prediction_id": p.prediction_id,
                    "match_id": p.match_id,
                    "market": p.market,
                    "request_id": p.request_id,
                    "verdict_count": len(p.verdicts),
                    "accept_warn_count": p.accept_warn_count(),
                    "quorum": self._quorum,
                    "final_present": p.final is not None,
                },
                producer=self.name,
                trace_id=trace_id or "",
            )
        ]


__all__ = ["ProofreaderAggregatorAgent"]
