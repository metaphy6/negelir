"""Phase 4.3 — Processor agents.

A processor consumes `scrape.classified` for a specific label, parses
the bytes into a `NormalizedRecord`, and emits `match.normalized`.
Validation failures → `proof.flag` with the violation list.

Parsing is intentionally minimal at this phase — Phase 4 ships a
working pipeline; the deep extractors live in `ai/scraper/*` and are
imported by these processors as the work matures (Phases 5–8 grow
them). For now, the JSON path covers openfootball and a tiny HTML
heuristic covers the rest, giving the swarm.demo an end-to-end run.

Doctrine: AGENTS.md §2 rule 3 (no fabricated data) — when parsing
yields nothing recognizable, we flag, never fabricate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from ..sdk.types import Message
from .payloads import NormalizedRecord, ProofFlagKind, ScrapeClassified
from .topics import MATCH_NORMALIZED, PROOF_FLAG, SCRAPE_CLASSIFIED

_log = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_PLANE_BY_TYPE: dict[str, str] = {
    "fixture": "schedule",
    "match_detail": "live",
    "lineup": "live",
    "odds": "market",
}

EXTRACTOR_VERSION = "phase4.v1"


# ── Base ─────────────────────────────────────────────────────────


class ProcessorAgentBase:
    """Shared decode + envelope handling.

    Subclasses set ``label`` (the categorizer label they consume) and
    ``record_type`` (the canonical kind they produce), and override
    ``parse()`` to turn body bytes into one or more record payloads.
    """

    label: str = ""
    record_type: str = ""

    publishes: tuple[str, ...] = (MATCH_NORMALIZED, PROOF_FLAG)
    subscribes: tuple[str, ...] = (SCRAPE_CLASSIFIED,)

    def __init__(self) -> None:
        if not self.label or not self.record_type:
            raise ValueError(
                f"{type(self).__name__}: label and record_type are required"
            )
        self.name = f"processor.{self.record_type}.v1"

    # ── Bus contract ────────────────────────────────────────────────
    def handle(self, msg: Message) -> Iterable[Message]:
        try:
            classified = ScrapeClassified.from_dict(msg.payload)
        except (KeyError, TypeError, ValueError) as exc:
            _log.warning("%s: malformed scrape.classified: %s", self.name, exc)
            return ()

        if classified.label != self.label:
            return ()  # not ours

        body, decode_err = self._decode(classified.raw.bytes_b64)
        if decode_err is not None:
            # Distinguish decode failure from empty parse: the former
            # is an upstream encoding bug, the latter is a parser-fit
            # problem. Lumping both into `empty_parse` blinds operators.
            return (
                self._flag(
                    msg, classified, kind=ProofFlagKind.DECODE_FAILED, detail=decode_err
                ),
            )
        try:
            parsed = list(self.parse(body, classified))
        except Exception as exc:  # noqa: BLE001
            return (
                self._flag(
                    msg,
                    classified,
                    kind=ProofFlagKind.PARSER_EXCEPTION,
                    detail=str(exc),
                ),
            )

        if not parsed:
            return (
                self._flag(
                    msg,
                    classified,
                    kind=ProofFlagKind.EMPTY_PARSE,
                    detail=f"label={classified.label} target={classified.raw.target}",
                ),
            )

        out: list[Message] = []
        captured_at = _utc_now_iso()
        for source_match_id, payload in parsed:
            stable_id = self._stable_id(classified.raw.source, source_match_id)
            try:
                rec = NormalizedRecord(
                    record_type=self.record_type,
                    plane=_PLANE_BY_TYPE[self.record_type],
                    source=classified.raw.source,
                    source_match_id=str(source_match_id),
                    stable_id=stable_id,
                    extractor_version=EXTRACTOR_VERSION,
                    payload=payload,
                    league_id=classified.raw.league_id,
                    competition_id=classified.raw.competition_id,
                    raw_sha256=classified.raw.bytes_sha256,
                    captured_at=captured_at,
                )
            except ValueError as exc:
                out.append(
                    self._flag(
                        msg, classified, kind=ProofFlagKind.INVALID_RECORD, detail=str(exc)
                    )
                )
                continue
            out.append(
                Message.new(
                    MATCH_NORMALIZED,
                    rec.as_dict(),
                    producer=self.name,
                    trace_id=msg.envelope.trace_id,
                )
            )
        return out

    # ── Subclass overrides ──────────────────────────────────────────
    def parse(
        self, body: str, classified: ScrapeClassified
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        """Return an iterable of (source_match_id, payload) tuples."""
        raise NotImplementedError

    # ── Helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _decode(b64: str) -> tuple[str, str | None]:
        """Returns (body, error). ``error`` is ``None`` on success.

        An empty inline payload is *not* an error — it just means the
        producer used ``bytes_ref`` (Phase 4.1's content-addressed
        path). Parsers that need bytes will yield nothing and trip
        ``empty_parse`` instead.
        """
        if not b64:
            return "", None
        try:
            data = base64.b64decode(b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            return "", f"base64 decode failed: {exc}"
        try:
            return data.decode("utf-8"), None
        except UnicodeDecodeError:
            # Latin-1 is lossless — substring tests still work and
            # the proofreader can flag mojibake separately.
            return data.decode("latin-1", errors="replace"), None

    @staticmethod
    def _stable_id(source: str, source_match_id: str) -> str:
        # Cross-source resolution lives in Phase 9 QID. For now the
        # stable_id is a deterministic hash so the storage upsert key
        # is stable and idempotent within a single source.
        h = hashlib.sha1(f"{source}:{source_match_id}".encode("utf-8"))
        return h.hexdigest()[:16]

    def _flag(
        self,
        msg: Message,
        classified: ScrapeClassified,
        *,
        kind: str,
        detail: str,
    ) -> Message:
        return Message.new(
            PROOF_FLAG,
            {
                "kind": kind,
                "detail": detail,
                "source": classified.raw.source,
                "target": classified.raw.target,
                "label": classified.label,
                "processor": self.name,
            },
            producer=self.name,
            trace_id=msg.envelope.trace_id,
        )


# ── Concrete processors ─────────────────────────────────────────


class FixtureProcessorAgent(ProcessorAgentBase):
    label = "fixture_list"
    record_type = "fixture"

    def parse(
        self, body: str, classified: ScrapeClassified
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        # JSON path (openfootball).
        if (classified.raw.content_type or "").startswith("application/json"):
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return
            for match in _iter_openfootball_matches(data):
                source_match_id = (
                    f"{match.get('date', '?')}_"
                    f"{match.get('team1', '?')}_vs_"
                    f"{match.get('team2', '?')}"
                )
                yield source_match_id, {
                    "date": match.get("date"),
                    "home_team": match.get("team1"),
                    "away_team": match.get("team2"),
                    "score": match.get("score") or {},
                }
            return

        # HTML fallback: very loose — find <tr>…vs…</tr> rows. Real
        # extractors live in ai/scraper/parsers.py and replace this in
        # later phases.
        for idx, m in enumerate(re.finditer(
            r"([A-ZĞÜŞİÖÇ][\w .-]{2,40})\s*[-–vs]\s*([A-ZĞÜŞİÖÇ][\w .-]{2,40})",
            body,
        )):
            home, away = m.group(1).strip(), m.group(2).strip()
            yield f"row_{idx}_{home}_vs_{away}", {
                "home_team": home,
                "away_team": away,
                "raw_html_index": idx,
            }


class MatchDetailProcessorAgent(ProcessorAgentBase):
    label = "match_detail"
    record_type = "match_detail"

    def parse(
        self, body: str, classified: ScrapeClassified
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        # Extract a single (home, away, score) triple if present.
        m = re.search(
            r"([A-ZĞÜŞİÖÇ][\w .-]{2,40})\s+(\d+)\s*[-–]\s*(\d+)\s+([A-ZĞÜŞİÖÇ][\w .-]{2,40})",
            body,
        )
        if not m:
            return
        home = m.group(1).strip()
        away = m.group(4).strip()
        home_score = int(m.group(2))
        away_score = int(m.group(3))
        smid = f"{home}_vs_{away}"
        yield smid, {
            "home_team": home,
            "away_team": away,
            "home_score": home_score,
            "away_score": away_score,
        }


class LineupProcessorAgent(ProcessorAgentBase):
    label = "lineup"
    record_type = "lineup"

    def parse(
        self, body: str, classified: ScrapeClassified
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        # Look for player-list shaped content.
        names = re.findall(r"\b\d{1,2}\.\s*([A-ZĞÜŞİÖÇ][\w .-]{2,40})", body)
        if len(names) < 11:
            return
        smid = f"lineup_{classified.raw.target}"
        yield smid, {"players": names[:22]}


class OddsProcessorAgent(ProcessorAgentBase):
    label = "odds"
    record_type = "odds"

    def parse(
        self, body: str, classified: ScrapeClassified
    ) -> Iterable[tuple[str, dict[str, Any]]]:
        # Match a 1X2 triple of decimal odds.
        m = re.search(
            r"(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})", body
        )
        if not m:
            return
        smid = f"odds_{classified.raw.target}"
        yield smid, {
            "1": float(m.group(1)),
            "X": float(m.group(2)),
            "2": float(m.group(3)),
        }


# ── Helpers ─────────────────────────────────────────────────────


def _iter_openfootball_matches(data: Any) -> Iterable[dict[str, Any]]:
    """Walk the openfootball JSON structure and yield match dicts.

    The schema is `{"name": ..., "matches": [...]}` for newer files
    and `{"name": ..., "rounds": [{"matches": [...]}, ...]}` for
    older ones. Both are supported.
    """
    if not isinstance(data, dict):
        return
    if isinstance(data.get("matches"), list):
        for m in data["matches"]:
            if isinstance(m, dict):
                yield m
    if isinstance(data.get("rounds"), list):
        for rd in data["rounds"]:
            if isinstance(rd, dict) and isinstance(rd.get("matches"), list):
                for m in rd["matches"]:
                    if isinstance(m, dict):
                        yield m


__all__ = [
    "EXTRACTOR_VERSION",
    "FixtureProcessorAgent",
    "LineupProcessorAgent",
    "MatchDetailProcessorAgent",
    "OddsProcessorAgent",
    "ProcessorAgentBase",
]
