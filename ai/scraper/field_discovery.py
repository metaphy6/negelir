"""
Negelir — AI-driven field discovery in unknown DOM structures.
Phase 7: When a source redesigns, locate data fields using heuristics.
Three-layer cascade: text-pattern → structural similarity → ML classifier.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from ai.common.logger import get_logger

log = get_logger("scraper.field_discovery")


@dataclass
class FieldCandidate:
    """A discovered field location in the DOM."""
    field_type: str        # team_name, score, possession_pct, etc.
    selector: str          # CSS-like selector hint
    value: str             # extracted text value
    confidence: float      # 0.0-1.0


@dataclass
class DiscoveredSchema:
    """Set of discovered field mappings."""
    fields: dict[str, FieldCandidate] = field(default_factory=dict)
    confidence: float = 0.0
    discovery_layer: str = "heuristic"  # heuristic, structural, ml


# ── Field patterns for heuristic discovery ──

FIELD_PATTERNS = {
    "score": re.compile(r"^\d{1,2}$"),
    "possession_pct": re.compile(r"^%?\d{1,3}%?$"),
    "odds": re.compile(r"^\d+\.\d{1,2}$"),
    "date": re.compile(r"^\d{1,2}[./]\d{1,2}([./]\d{2,4})?$"),
    "match_stat_int": re.compile(r"^\d{1,4}$"),
}


class _TextExtractor(HTMLParser):
    """Extract all text nodes with their CSS class context."""

    def __init__(self):
        super().__init__()
        self.nodes: list[dict] = []
        self._current_classes: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        self._depth += 1
        classes = ""
        for attr, val in attrs:
            if attr == "class":
                classes = val or ""
        self._current_classes.append(classes)

    def handle_endtag(self, tag):
        self._depth = max(0, self._depth - 1)
        if self._current_classes:
            self._current_classes.pop()

    def handle_data(self, data):
        text = data.strip()
        if text:
            cls = self._current_classes[-1] if self._current_classes else ""
            self.nodes.append({"text": text, "classes": cls, "depth": self._depth})


class FieldDiscoveryEngine:
    """
    Locates data fields in an unknown DOM structure.
    Layer 1: Text-pattern heuristics (fast, most reliable).
    Layer 2 & 3: reserved for structural similarity + ML (future).
    """

    def discover_fields(self, html: str, expected_schema: dict,
                        context: dict | None = None) -> DiscoveredSchema | None:
        """
        Attempt to locate fields in expected_schema within the HTML.

        Args:
            html: Raw HTML of the changed page
            expected_schema: {"score": 2, "team_name": 2, ...} field→expected count
            context: {"team_registry": [...]} optional team names

        Returns:
            DiscoveredSchema or None if confidence too low.
        """
        context = context or {}
        candidates = self._heuristic_scan(html, expected_schema, context)

        conf = self._evaluate_candidates(candidates, expected_schema)
        if conf >= 0.6:
            return DiscoveredSchema(
                fields={c.field_type: c for c in candidates},
                confidence=conf,
                discovery_layer="heuristic",
            )

        return None

    def _heuristic_scan(self, html: str, expected_schema: dict,
                        context: dict) -> list[FieldCandidate]:
        """Walk DOM text nodes, apply FIELD_PATTERNS validators."""
        parser = _TextExtractor()
        try:
            parser.feed(html)
        except Exception:
            return []

        candidates = []
        team_registry = set(context.get("team_registry", []))

        for node in parser.nodes:
            text = node["text"]
            classes = node["classes"]

            # Team name check
            if "team_name" in expected_schema and text in team_registry:
                candidates.append(FieldCandidate(
                    "team_name", f".{classes}" if classes else "*",
                    text, 0.95
                ))
                continue

            # Pattern-based checks
            for field_type, pattern in FIELD_PATTERNS.items():
                if field_type in expected_schema and pattern.match(text):
                    # Extra validation for possession
                    if field_type == "possession_pct":
                        val = float(re.sub(r"[%,]", "", text))
                        if not (0 <= val <= 100):
                            continue
                    # Extra validation for odds
                    if field_type == "odds":
                        val = float(text)
                        if not (1.01 <= val <= 100.0):
                            continue
                    candidates.append(FieldCandidate(
                        field_type, f".{classes}" if classes else "*",
                        text, 0.8
                    ))
                    break

        return candidates

    @staticmethod
    def _evaluate_candidates(candidates: list[FieldCandidate],
                             expected_schema: dict) -> float:
        """Evaluate how well candidates cover the expected schema."""
        if not expected_schema:
            return 0.0
        found_types = set(c.field_type for c in candidates)
        covered = sum(1 for ft in expected_schema if ft in found_types)
        return covered / len(expected_schema)
