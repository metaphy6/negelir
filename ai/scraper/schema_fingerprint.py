"""
Negelir — DOM structural fingerprinting + drift detection.
Phase 7: Detects when a source website redesigns by comparing
structural page fingerprints against stored baselines.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser

from common.logger import get_logger

log = get_logger("scraper.schema_fingerprint")


@dataclass
class DOMFingerprint:
    """Structural fingerprint of an HTML page."""
    tag_histogram: dict[str, int] = field(default_factory=dict)
    class_vocabulary: set[str] = field(default_factory=set)
    depth_profile: list[int] = field(default_factory=list)
    content_hash: str = ""


class _FingerprintParser(HTMLParser):
    """HTML parser that builds a structural fingerprint."""

    def __init__(self):
        super().__init__()
        self.tags = Counter()
        self.classes = set()
        self.depth = 0
        self.depth_counts = Counter()
        self._void_tags = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        self.tags[tag] += 1
        self.depth += 1
        self.depth_counts[self.depth] += 1
        for attr, val in attrs:
            if attr == "class" and val:
                for cls in val.split():
                    self.classes.add(cls)

    def handle_endtag(self, tag):
        if tag not in self._void_tags:
            self.depth = max(0, self.depth - 1)


class SchemaFingerprinter:
    """
    Builds and compares structural fingerprints of HTML pages.
    Drift threshold triggers discovery mode.
    """

    DRIFT_THRESHOLD = 0.35  # Jaccard distance on class vocabulary

    def fingerprint(self, html: str) -> DOMFingerprint:
        """Extract structural fingerprint from raw HTML."""
        parser = _FingerprintParser()
        try:
            parser.feed(html)
        except Exception:
            pass

        # Build depth profile
        max_depth = max(parser.depth_counts.keys(), default=0)
        depth_profile = [parser.depth_counts.get(d, 0) for d in range(1, max_depth + 1)]

        # Content hash: structural skeleton
        skeleton = "|".join(f"{t}:{c}" for t, c in sorted(parser.tags.items()))
        content_hash = hashlib.sha256(skeleton.encode()).hexdigest()[:16]

        return DOMFingerprint(
            tag_histogram=dict(parser.tags),
            class_vocabulary=set(parser.classes),
            depth_profile=depth_profile,
            content_hash=content_hash,
        )

    def detect_drift(self, current: DOMFingerprint, baseline: DOMFingerprint) -> float:
        """
        Returns drift score [0.0, 1.0].
        Primarily uses Jaccard distance on CSS class vocabulary.
        """
        if not baseline.class_vocabulary and not current.class_vocabulary:
            return 0.0
        if not baseline.class_vocabulary or not current.class_vocabulary:
            return 1.0

        intersection = baseline.class_vocabulary & current.class_vocabulary
        union = baseline.class_vocabulary | current.class_vocabulary
        jaccard = 1.0 - len(intersection) / len(union) if union else 0.0
        return jaccard

    def is_drifted(self, current: DOMFingerprint, baseline: DOMFingerprint) -> bool:
        """Check if drift exceeds threshold."""
        return self.detect_drift(current, baseline) > self.DRIFT_THRESHOLD

    _baselines: dict[tuple[str, str], DOMFingerprint] = {}

    def store_baseline(self, source: str, endpoint: str, fingerprint: DOMFingerprint):
        """Store known-good fingerprint (in-memory for now)."""
        self._baselines[(source, endpoint)] = fingerprint

    def get_baseline(self, source: str, endpoint: str) -> DOMFingerprint | None:
        """Retrieve stored baseline."""
        return self._baselines.get((source, endpoint))
