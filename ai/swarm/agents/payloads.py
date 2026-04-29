"""Lightweight payload models for Phase 4 bus messages.

These are dict-shaped TypedDicts (no Pydantic at the bus boundary —
the SDK stays stdlib-only). Validation happens at agent boundaries
inside processors via `from_dict` constructors that raise on missing
keys. Schemas at ai/swarm/sdk/schemas/<topic>.json are the wire
contract; these classes are the in-process Python view.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# Plane + record-type vocabulary lives at module scope so it is not
# shadowed by dataclass field machinery (Python 3.13 made class-level
# constants on a dataclass appear in `asdict()` for some interpreter
# builds — moving them out makes the contract explicit).
_ALLOWED_PLANES: frozenset[str] = frozenset(
    {"reference", "schedule", "live", "editorial", "market"}
)
_ALLOWED_RECORD_TYPES: frozenset[str] = frozenset(
    {"fixture", "match_detail", "lineup", "odds"}
)


@dataclass(frozen=True)
class ScrapeRequest:
    """`scrape.request` payload — what the scheduler asks a scraper to fetch."""

    source: str                 # 'mackolik' | 'nesine' | 'tff' | 'openfootball'
    target: str                 # URL or scrape spec the source agent understands
    league_id: str | None = None
    competition_id: str | None = None
    requested_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScrapeRequest":
        return cls(
            source=str(data["source"]),
            target=str(data["target"]),
            league_id=data.get("league_id"),
            competition_id=data.get("competition_id"),
            requested_at=str(data.get("requested_at", "")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ScrapeRaw:
    """`scrape.raw` payload — the bytes a scraper produced.

    `bytes_b64` carries small payloads inline for testing; production
    will set `bytes_ref` (a content-addressed key) instead and leave
    `bytes_b64` empty. `bytes_sha256` is always populated.
    """

    source: str
    target: str
    bytes_sha256: str
    http_status: int
    content_type: str = ""
    bytes_b64: str = ""
    bytes_ref: str = ""
    league_id: str | None = None
    competition_id: str | None = None
    fetched_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScrapeRaw":
        return cls(
            source=str(data["source"]),
            target=str(data["target"]),
            bytes_sha256=str(data["bytes_sha256"]),
            http_status=int(data["http_status"]),
            content_type=str(data.get("content_type", "")),
            bytes_b64=str(data.get("bytes_b64", "")),
            bytes_ref=str(data.get("bytes_ref", "")),
            league_id=data.get("league_id"),
            competition_id=data.get("competition_id"),
            fetched_at=str(data.get("fetched_at", "")),
        )


@dataclass(frozen=True)
class ScrapeClassified:
    """`scrape.classified` payload — categorizer verdict + carry-through.

    `label` is one of:
      'fixture_list' | 'match_detail' | 'lineup' | 'odds' | 'irrelevant'
    """

    raw: ScrapeRaw
    label: str
    confidence: float
    classifier_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw.as_dict(),
            "label": self.label,
            "confidence": self.confidence,
            "classifier_id": self.classifier_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScrapeClassified":
        return cls(
            raw=ScrapeRaw.from_dict(data["raw"]),
            label=str(data["label"]),
            confidence=float(data["confidence"]),
            classifier_id=str(data["classifier_id"]),
        )


@dataclass(frozen=True)
class NormalizedRecord:
    """`match.normalized` payload — a Record per DATA_PIPELINE.md §4.

    The five-plane scope is enforced by `plane`. `payload` is a
    record-type-specific dict that the storage agent persists as
    JSONB; downstream projections read it.
    """

    record_type: str            # 'fixture'|'match_detail'|'lineup'|'odds'
    plane: str                  # 'reference'|'schedule'|'live'|'editorial'|'market'
    source: str
    source_match_id: str
    stable_id: str
    extractor_version: str
    payload: dict[str, Any]
    league_id: str | None = None
    competition_id: str | None = None
    canonical_version: int = 1
    raw_sha256: str = ""
    captured_at: str = ""

    def __post_init__(self) -> None:
        if self.plane not in _ALLOWED_PLANES:
            raise ValueError(
                f"plane={self.plane!r} not in {sorted(_ALLOWED_PLANES)}"
            )
        if self.record_type not in _ALLOWED_RECORD_TYPES:
            raise ValueError(
                f"record_type={self.record_type!r} not in "
                f"{sorted(_ALLOWED_RECORD_TYPES)}"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NormalizedRecord":
        return cls(
            record_type=str(data["record_type"]),
            plane=str(data["plane"]),
            source=str(data["source"]),
            source_match_id=str(data["source_match_id"]),
            stable_id=str(data["stable_id"]),
            extractor_version=str(data["extractor_version"]),
            payload=dict(data["payload"]),
            league_id=data.get("league_id"),
            competition_id=data.get("competition_id"),
            canonical_version=int(data.get("canonical_version", 1)),
            raw_sha256=str(data.get("raw_sha256", "")),
            captured_at=str(data.get("captured_at", "")),
        )


@dataclass(frozen=True)
class MatchStored:
    """`match.stored` payload — storage agent's confirmation."""

    record_id: int
    record_type: str
    plane: str
    source: str
    stable_id: str
    change_kind: str            # 'created'|'updated'|'unchanged'
    stored_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchStored":
        return cls(
            record_id=int(data["record_id"]),
            record_type=str(data["record_type"]),
            plane=str(data["plane"]),
            source=str(data["source"]),
            stable_id=str(data["stable_id"]),
            change_kind=str(data["change_kind"]),
            stored_at=str(data.get("stored_at", "")),
        )


@dataclass(frozen=True)
class FreshnessEvent:
    """`freshness.events.v1` payload — see CONTENT_FRESHNESS.md §15.

    ``event_id`` is **deterministic and content-derived** — recomputing
    it on the same logical change yields the same id. This is what
    makes reactor ledgers idempotent across upstream retries, multiple
    storage replicas, and operator replays (CONTENT_FRESHNESS §15.2).
    Use :py:meth:`derive_event_id` to compute it from the change tuple.
    """

    event_id: str
    record_id: int
    source: str
    stable_id: str
    record_type: str
    plane: str
    change_kind: str            # 'created'|'updated'|'invalidated'
    diff: dict[str, Any] = field(default_factory=dict)
    emitted_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FreshnessEvent":
        return cls(
            event_id=str(data["event_id"]),
            record_id=int(data["record_id"]),
            source=str(data["source"]),
            stable_id=str(data["stable_id"]),
            record_type=str(data["record_type"]),
            plane=str(data["plane"]),
            change_kind=str(data["change_kind"]),
            diff=dict(data.get("diff") or {}),
            emitted_at=str(data.get("emitted_at", "")),
        )

    @staticmethod
    def derive_event_id(
        *,
        source: str,
        stable_id: str,
        record_type: str,
        change_kind: str,
        diff: dict[str, Any],
    ) -> str:
        """Compute a deterministic event_id from the change tuple.

        The diff is hashed via canonical JSON (sorted keys) so the
        same logical change always yields the same id, regardless of
        Python dict iteration order.
        """
        import hashlib
        import json as _json

        diff_blob = _json.dumps(
            diff, sort_keys=True, separators=(",", ":"), default=str
        )
        digest = hashlib.sha256(
            f"{source}|{stable_id}|{record_type}|{change_kind}|{diff_blob}".encode("utf-8")
        ).hexdigest()
        return digest[:32]


__all__ = [
    "FreshnessEvent",
    "MatchOutcome",
    "MatchStored",
    "ModelTrained",
    "NormalizedRecord",
    "PredictFinal",
    "PredictRequest",
    "PredictVote",
    "ProofFlagKind",
    "ScrapeClassified",
    "ScrapeRaw",
    "ScrapeRequest",
    "TERMINAL_MATCH_STATUSES",
    "derive_match_outcome",
    "derive_prediction_id",
]


# ── Phase 5+ — terminal-state match outcomes ────────────────────
#
# The storage agent emits `match.outcome.v1` whenever a match_detail
# record reaches a terminal status with both final scores present.
# Phase 6 drift detector + proofreader consume this stream.
# Producer-side discipline: predictor / consensus agents must NOT
# publish to MATCH_OUTCOME (mirrors the freshness.events back-emission
# ban — outcomes are storage-side data, not prediction-side).


# Status strings recognised as "match has reached its final score".
# Sources differ on casing / vocabulary; keep the set narrow + lower
# every observed status before lookup. New statuses go through review.
TERMINAL_MATCH_STATUSES: frozenset[str] = frozenset({
    "final",
    "finished",
    "ft",
    "full_time",
    "full-time",
    "completed",
    "ended",
})


def derive_match_outcome(
    *,
    final_home: int,
    final_away: int,
) -> dict[str, str]:
    """Compute the canonical 1x2 / OU 2.5 / BTTS outcomes from a final score.

    Centralised so the storage agent, tests, and any future consumer
    that reconstructs the outcome tuple agree byte-for-byte.
    """
    if final_home > final_away:
        outcome_1x2 = "H"
    elif final_home < final_away:
        outcome_1x2 = "A"
    else:
        outcome_1x2 = "D"
    outcome_ou_2_5 = "over" if (final_home + final_away) > 2.5 else "under"
    outcome_btts = "yes" if (final_home > 0 and final_away > 0) else "no"
    return {
        "outcome_1x2": outcome_1x2,
        "outcome_ou_2_5": outcome_ou_2_5,
        "outcome_btts": outcome_btts,
    }


@dataclass(frozen=True)
class MatchOutcome:
    """`match.outcome.v1` payload — terminal-state ground truth.

    Emitted exactly once per `(source, source_match_id)` per terminal
    transition. Phase 6 drift agent treats `(stable_id, settled_at)`
    as the dedup key, so the storage agent's idempotent upsert path
    (which already short-circuits on `unchanged`) is the natural
    single-emission point.
    """

    match_id: str
    stable_id: str
    source: str
    final_home: int
    final_away: int
    outcome_1x2: str            # 'H' | 'D' | 'A'
    settled_at: str
    league_id: str | None = None
    competition_id: str | None = None
    outcome_ou_2_5: str | None = None  # 'over' | 'under'
    outcome_btts: str | None = None    # 'yes' | 'no'
    record_id: int | None = None

    def __post_init__(self) -> None:
        if self.final_home < 0 or self.final_away < 0:
            raise ValueError(
                f"MatchOutcome: final scores must be \u22650 "
                f"(got {self.final_home}-{self.final_away})"
            )
        if self.outcome_1x2 not in ("H", "D", "A"):
            raise ValueError(
                f"MatchOutcome.outcome_1x2={self.outcome_1x2!r} "
                "not in (H, D, A)"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchOutcome":
        return cls(
            match_id=str(data["match_id"]),
            stable_id=str(data["stable_id"]),
            source=str(data["source"]),
            final_home=int(data["final_home"]),
            final_away=int(data["final_away"]),
            outcome_1x2=str(data["outcome_1x2"]),
            settled_at=str(data["settled_at"]),
            league_id=data.get("league_id"),
            competition_id=data.get("competition_id"),
            outcome_ou_2_5=data.get("outcome_ou_2_5"),
            outcome_btts=data.get("outcome_btts"),
            record_id=(
                int(data["record_id"]) if data.get("record_id") is not None else None
            ),
        )


# ── proof.flag kind registry ─────────────────────────────────────
#
# Closed vocabulary for the cross-cutting `proof.flag` topic. Per
# pre-Phase-6 audit §B1/§D2: producers MUST pull `kind` from this
# registry rather than hard-coding strings, and the JSON schema's
# enum is generated from this set so the wire schema and code can
# never drift in opposite directions. Adding a new kind requires:
#   1. A new constant below.
#   2. The matching enum entry in
#      `ai/swarm/sdk/schemas/proof.flag.json`.
#   3. Coverage in `test_proof_flag_kinds.py`
#      (`test_registry_matches_schema_enum`).
#
# Cardinality is intentionally low — the topic stays one stream,
# but every producer's vocabulary is closed.


class ProofFlagKind(str):
    """String-subclass enum-like registry of valid `proof.flag` kinds.

    Plain `str` subclass (not `enum.Enum`) so call sites can keep
    writing the literal value into JSON payloads without an
    ``.value`` indirection while still benefitting from the
    registry guard via :py:meth:`all_kinds`.
    """

    # — Phase 4 scrape lifecycle —
    UPSTREAM_MISSING = "upstream_missing"
    DECODE_FAILED = "decode_failed"
    EMPTY_PARSE = "empty_parse"
    PARSER_EXCEPTION = "parser_exception"
    INVALID_RECORD = "invalid_record"
    LOW_CONFIDENCE_CLASSIFICATION = "low_confidence_classification"

    # — Phase 5 consensus —
    LATE_VOTE_DROPPED = "late_vote_dropped"
    CONSENSUS_NO_VOTES = "consensus_no_votes"
    CONSENSUS_OVERFLOW = "consensus_overflow"

    # — Phase 6 proofreader aggregator —
    # Quorum was reached (≥cfg.proofreader_quorum accept/warn votes) but
    # the aggregator's outbound publish was deduped by the ledger — i.e.
    # a re-emitted verdict tried to approve a prediction that was
    # already approved. Informational, not actionable.
    PROOFREADER_DUPLICATE_APPROVAL = "proofreader_duplicate_approval"
    # The window elapsed without enough accept/warn verdicts. The
    # candidate is dropped; no predict.approved.v1 is emitted. The
    # verdicts received (if any) are listed in `details.verdicts`.
    PROOFREADER_NO_QUORUM = "proofreader_no_quorum"
    # A verdict arrived after the aggregator already finalized
    # (approved or no-quorum) the candidate. Recorded so an operator
    # can see when a proofreader replica is consistently slow.
    PROOFREADER_LATE_VERDICT_DROPPED = "proofreader_late_verdict_dropped"
    # ≥1 reject vote landed and the aggregator therefore refused to
    # approve, even if the remaining accept/warn votes would have met
    # quorum. ROADMAP §6.1 contract: a single reject is fatal.
    PROOFREADER_REJECTED = "proofreader_rejected"
    # Pending-set saturated; oldest in-flight candidate evicted.
    # Mirrors the consensus_overflow pattern.
    PROOFREADER_OVERFLOW = "proofreader_overflow"

    @classmethod
    def all_kinds(cls) -> frozenset[str]:
        """Every declared kind. Used by the contract test + telemetry."""
        return frozenset(
            v
            for k, v in vars(cls).items()
            if k.isupper() and isinstance(v, str)
        )


# ── Phase 5 — predictor swarm + consensus payloads ──────────────


# Allowed market identifiers. Phase 5 starts narrow; Phase 6+ broaden.
_ALLOWED_MARKETS: frozenset[str] = frozenset(
    {"1x2", "ah", "ou_2_5", "btts"}
)


def derive_prediction_id(
    *,
    match_id: str,
    market: str,
    request_id: str,
    calibration_version: int | str,
) -> str:
    """Deterministic prediction id (Phase 10 NLP citation contract).

    Hashes the four identity fields per ROADMAP §5.2 / §5.5
    forward-test. Same inputs → same id, regardless of process or
    dict iteration order. Truncated to 32 hex chars to keep wire
    payloads compact while preserving collision resistance for our
    cardinality.
    """
    import hashlib

    blob = f"{match_id}|{market}|{request_id}|{calibration_version}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class PredictRequest:
    """`predict.request` payload — what the API/reactor asks predictors for.

    `request_id` is **generated by the requester** (API gateway in
    Phase 9, `LivePredictorReactor` here in Phase 5) and round-trips
    unchanged through `predict.vote` and `predict.final` so the
    Phase 9 RPC pattern can correlate the response.
    """

    request_id: str
    match_id: str
    market: str                       # see _ALLOWED_MARKETS
    league_id: str | None = None
    profile_id: str | None = None     # Phase 13a; defaults to league_id
    requested_at: str = ""
    features: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.market not in _ALLOWED_MARKETS:
            raise ValueError(
                f"market={self.market!r} not in {sorted(_ALLOWED_MARKETS)}"
            )
        if not self.request_id:
            raise ValueError("PredictRequest.request_id is required")
        if not self.match_id:
            raise ValueError("PredictRequest.match_id is required")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PredictRequest":
        return cls(
            request_id=str(data["request_id"]),
            match_id=str(data["match_id"]),
            market=str(data["market"]),
            league_id=data.get("league_id"),
            profile_id=data.get("profile_id"),
            requested_at=str(data.get("requested_at", "")),
            features=dict(data.get("features") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class PredictVote:
    """`predict.vote` payload — one predictor's contribution.

    `distribution.market_outcomes` is a dict of outcome → probability
    that sums to 1.0 (within float tolerance). `score_grid` is the
    optional 2D probability matrix for predictors that compute one
    (Dixon-Coles, XGB pair); `null` for Elo + market-feature models.
    """

    request_id: str
    match_id: str
    market: str
    predictor_id: str                 # e.g. "pred.elo.v1"
    distribution: dict[str, Any]      # {market_outcomes: dict, score_grid?: list}
    confidence: float                 # in [0, 1]
    produced_at: str = ""
    features_version: str = ""        # Phase 11 hint
    league_id: str | None = None      # round-tripped from PredictRequest
    profile_id: str | None = None     # round-tripped from PredictRequest (Phase 13a)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.market not in _ALLOWED_MARKETS:
            raise ValueError(
                f"market={self.market!r} not in {sorted(_ALLOWED_MARKETS)}"
            )
        if not self.predictor_id:
            raise ValueError("PredictVote.predictor_id is required")
        if not isinstance(self.distribution, dict):
            raise ValueError("PredictVote.distribution must be a dict")
        if "market_outcomes" not in self.distribution:
            raise ValueError(
                "PredictVote.distribution must contain 'market_outcomes'"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PredictVote":
        return cls(
            request_id=str(data["request_id"]),
            match_id=str(data["match_id"]),
            market=str(data["market"]),
            predictor_id=str(data["predictor_id"]),
            distribution=dict(data["distribution"]),
            confidence=float(data["confidence"]),
            produced_at=str(data.get("produced_at", "")),
            features_version=str(data.get("features_version", "")),
            league_id=data.get("league_id"),
            profile_id=data.get("profile_id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class PredictFinal:
    """`predict.final` payload — calibrated swarm consensus.

    Per ROADMAP §5.2:
      * Single-publication guaranteed for `(match_id, market, request_id)`.
      * `degraded=true` + `degraded_reason` when fewer than
        `cfg.consensus_min_voters` predictors voted (Phase 12 contract).
      * `prediction_id` derived via :func:`derive_prediction_id`.
      * `produced_at` is the publish wall-clock (Phase 10 citation).
    """

    request_id: str
    prediction_id: str
    match_id: str
    market: str
    distribution: dict[str, Any]      # {market_outcomes, score_grid?}
    weights: dict[str, float]         # predictor_id → weight used
    contributing_models: list[str]
    calibration_version: int
    swarm_confidence: float           # in [0, 1]
    degraded: bool = False
    degraded_reason: str = ""
    produced_at: str = ""
    league_id: str | None = None
    profile_id: str | None = None

    def __post_init__(self) -> None:
        if self.market not in _ALLOWED_MARKETS:
            raise ValueError(
                f"market={self.market!r} not in {sorted(_ALLOWED_MARKETS)}"
            )
        if not isinstance(self.distribution, dict):
            raise ValueError("PredictFinal.distribution must be a dict")
        if "market_outcomes" not in self.distribution:
            raise ValueError(
                "PredictFinal.distribution must contain 'market_outcomes'"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PredictFinal":
        return cls(
            request_id=str(data["request_id"]),
            prediction_id=str(data["prediction_id"]),
            match_id=str(data["match_id"]),
            market=str(data["market"]),
            distribution=dict(data["distribution"]),
            weights={str(k): float(v) for k, v in dict(data.get("weights") or {}).items()},
            contributing_models=[str(m) for m in (data.get("contributing_models") or [])],
            calibration_version=int(data.get("calibration_version", 0)),
            swarm_confidence=float(data["swarm_confidence"]),
            degraded=bool(data.get("degraded", False)),
            degraded_reason=str(data.get("degraded_reason", "")),
            produced_at=str(data.get("produced_at", "")),
            league_id=data.get("league_id"),
            profile_id=data.get("profile_id"),
        )


@dataclass(frozen=True)
class ModelTrained:
    """`models.events.v1` payload — TrainerReactor's notification.

    Lifecycle event the model registry / ops dashboards consume. The
    payload captures *which* predictor retrained, on *which* slice
    `(profile_id, league)`, and the post-training accuracy/holdout
    score so the consensus can refresh its weight on the next nightly
    rollup.
    """

    predictor_id: str
    profile_id: str
    league_id: str | None
    model_version: str
    trained_at: str
    metric: str = "accuracy"
    metric_value: float = 0.0
    samples: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelTrained":
        return cls(
            predictor_id=str(data["predictor_id"]),
            profile_id=str(data["profile_id"]),
            league_id=data.get("league_id"),
            model_version=str(data["model_version"]),
            trained_at=str(data["trained_at"]),
            metric=str(data.get("metric", "accuracy")),
            metric_value=float(data.get("metric_value", 0.0)),
            samples=int(data.get("samples", 0)),
            metadata=dict(data.get("metadata") or {}),
        )


# ── Phase 6 — proofreader & aggregator payloads ─────────────────


_ALLOWED_PROOFREADER_VERDICTS: frozenset[str] = frozenset({"accept", "warn", "reject"})


@dataclass(frozen=True)
class ProofreaderVerdict:
    """`predict.proofreader_verdict.v1` payload — single proofreader's
    decision on a `predict.final` candidate.

    Per ROADMAP §6.1: each proofreader runs an independent set of
    rule-based + statistical checks. ``flags`` ⊆ ``checks_run``; both
    are sets of stable, low-cardinality check ids (e.g.
    ``"sanity.probs_sum_to_one"``).
    """

    request_id: str
    prediction_id: str
    match_id: str
    market: str
    proofreader_id: str
    verdict: str                     # 'accept' | 'warn' | 'reject'
    score: float                     # in [0, 1]
    checked_at: str
    flags: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    rationale: str = ""
    calibration_version: int = 0

    def __post_init__(self) -> None:
        if self.verdict not in _ALLOWED_PROOFREADER_VERDICTS:
            raise ValueError(
                f"verdict={self.verdict!r} not in "
                f"{sorted(_ALLOWED_PROOFREADER_VERDICTS)}"
            )
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score={self.score!r} out of [0,1]")
        # checks_run must be a superset of flags — if a check fired
        # we must have run it. Cheap invariant; loud failure when
        # a producer drifts.
        if set(self.flags) - set(self.checks_run):
            raise ValueError(
                "ProofreaderVerdict.flags must be a subset of checks_run"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProofreaderVerdict":
        return cls(
            request_id=str(data["request_id"]),
            prediction_id=str(data["prediction_id"]),
            match_id=str(data["match_id"]),
            market=str(data["market"]),
            proofreader_id=str(data["proofreader_id"]),
            verdict=str(data["verdict"]),
            score=float(data["score"]),
            checked_at=str(data["checked_at"]),
            flags=[str(f) for f in (data.get("flags") or [])],
            checks_run=[str(c) for c in (data.get("checks_run") or [])],
            rationale=str(data.get("rationale", "")),
            calibration_version=int(data.get("calibration_version", 0)),
        )


@dataclass(frozen=True)
class PredictApproved:
    """`predict.approved.v1` payload — proofreader-aggregator output.

    Per Phase 6 cache-topology decision (Wave A.1): ``predict.final``
    is a CANDIDATE; ``predict.approved.v1`` is the post-quorum,
    user-visible decision. The cache subscribes here, never to
    ``predict.final`` directly. Carries the full ``predict.final``
    payload verbatim under ``final`` so consumers do not need a join.
    """

    request_id: str
    prediction_id: str
    match_id: str
    market: str
    approved_at: str
    approved_by: list[str]            # proofreader ids that voted accept
    verdict_count: int                # total verdicts received in window
    quorum: int                       # threshold this prediction crossed
    final: dict[str, Any]             # full PredictFinal payload, verbatim
    calibration_version: int = 0

    def __post_init__(self) -> None:
        if not self.approved_by:
            raise ValueError("PredictApproved.approved_by must be non-empty")
        if self.verdict_count < len(self.approved_by):
            raise ValueError(
                "verdict_count cannot be less than len(approved_by)"
            )
        if self.quorum < 1:
            raise ValueError(f"quorum must be >= 1; got {self.quorum}")
        if len(self.approved_by) < self.quorum:
            raise ValueError(
                f"approved_by ({len(self.approved_by)}) below quorum "
                f"({self.quorum}) — aggregator must not emit"
            )
        if not isinstance(self.final, dict) or "prediction_id" not in self.final:
            raise ValueError(
                "PredictApproved.final must be the full predict.final dict"
            )
        if self.final.get("prediction_id") != self.prediction_id:
            raise ValueError(
                "PredictApproved.prediction_id must equal final['prediction_id']"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PredictApproved":
        return cls(
            request_id=str(data["request_id"]),
            prediction_id=str(data["prediction_id"]),
            match_id=str(data["match_id"]),
            market=str(data["market"]),
            approved_at=str(data["approved_at"]),
            approved_by=[str(a) for a in (data.get("approved_by") or [])],
            verdict_count=int(data["verdict_count"]),
            quorum=int(data["quorum"]),
            final=dict(data["final"]),
            calibration_version=int(data.get("calibration_version", 0)),
        )


# ── Phase 6.3 — drift / maintenance event ──────────────────────


_ALLOWED_MAINT_KINDS: frozenset[str] = frozenset({
    "retrain_request",      # drift agent: predictor's Brier / KS-test tripped
    "recalibration_request",  # reserved for Phase 9 (calibration drift)
})

_ALLOWED_DRIFT_REASONS: frozenset[str] = frozenset({
    "brier_floor",   # rolling Brier breached `cfg.drift_accuracy_floor`
    "logloss_floor", # rolling log-loss breached the same floor
    "feature_ks",    # KS-test on input features rejected stationarity
})


@dataclass(frozen=True)
class MaintEvent:
    """`maint.event.v1` payload — drift / maintenance notification.

    The drift agent (Phase 6.3) emits `kind=retrain_request` when a
    predictor's rolling Brier/log-loss window crosses the floor, or
    when a feature-distribution KS-test rejects stationarity. The
    trainer subscribes to schedule a retrain; ops dashboards
    subscribe for the alert.

    `target` identifies the predictor (e.g. `"pred.elo.v1"`) so the
    trainer can scope its retrain. `reason` is a closed vocabulary
    from `_ALLOWED_DRIFT_REASONS` so dashboards can filter without
    parsing free-form strings.
    """

    kind: str
    target: str
    reason: str
    league_id: str | None = None
    market: str | None = None
    metric: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    sample_size: int = 0
    produced_at: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _ALLOWED_MAINT_KINDS:
            raise ValueError(
                f"MaintEvent.kind={self.kind!r} not in "
                f"{sorted(_ALLOWED_MAINT_KINDS)}"
            )
        if self.kind == "retrain_request" and self.reason not in _ALLOWED_DRIFT_REASONS:
            raise ValueError(
                f"MaintEvent(kind=retrain_request).reason={self.reason!r} "
                f"not in {sorted(_ALLOWED_DRIFT_REASONS)}"
            )
        if not self.target:
            raise ValueError("MaintEvent.target must be a non-empty string")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaintEvent":
        return cls(
            kind=str(data["kind"]),
            target=str(data["target"]),
            reason=str(data["reason"]),
            league_id=data.get("league_id"),
            market=data.get("market"),
            metric=str(data.get("metric", "")),
            metric_value=float(data.get("metric_value", 0.0)),
            threshold=float(data.get("threshold", 0.0)),
            sample_size=int(data.get("sample_size", 0)),
            produced_at=str(data.get("produced_at", "")),
        )
