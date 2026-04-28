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

    _ALLOWED_PLANES = frozenset(
        {"reference", "schedule", "live", "editorial", "market"}
    )
    _ALLOWED_TYPES = frozenset(
        {"fixture", "match_detail", "lineup", "odds"}
    )

    def __post_init__(self) -> None:
        if self.plane not in self._ALLOWED_PLANES:
            raise ValueError(
                f"plane={self.plane!r} not in {sorted(self._ALLOWED_PLANES)}"
            )
        if self.record_type not in self._ALLOWED_TYPES:
            raise ValueError(
                f"record_type={self.record_type!r} not in "
                f"{sorted(self._ALLOWED_TYPES)}"
            )

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("_ALLOWED_PLANES", None)
        d.pop("_ALLOWED_TYPES", None)
        return d

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
        )


@dataclass(frozen=True)
class FreshnessEvent:
    """`freshness.events.v1` payload — see CONTENT_FRESHNESS.md §15."""

    record_id: int
    plane: str
    record_type: str
    change_kind: str            # 'created'|'updated'|'invalidated'
    diff_summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FreshnessEvent":
        return cls(
            record_id=int(data["record_id"]),
            plane=str(data["plane"]),
            record_type=str(data["record_type"]),
            change_kind=str(data["change_kind"]),
            diff_summary=dict(data.get("diff_summary") or {}),
        )


__all__ = [
    "FreshnessEvent",
    "MatchStored",
    "NormalizedRecord",
    "ScrapeClassified",
    "ScrapeRaw",
    "ScrapeRequest",
]
