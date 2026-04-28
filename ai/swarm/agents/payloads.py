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
    "MatchStored",
    "NormalizedRecord",
    "ScrapeClassified",
    "ScrapeRaw",
    "ScrapeRequest",
]
