"""
Negelir — Self-supervised schema classifier training.
Phase 7: Stores successful scrape→field mappings as training data.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from common.logger import get_logger

log = get_logger("scraper.schema_trainer")


@dataclass
class DOMSnapshot:
    """Simplified DOM snapshot for training data."""
    source: str
    endpoint: str
    tag_histogram: dict[str, int] = field(default_factory=dict)
    class_vocabulary: set[str] = field(default_factory=set)
    field_locations: dict[str, str] = field(default_factory=dict)  # field → selector
    snapshot_hash: str = ""


class SchemaTrainer:
    """
    Self-supervised training: successful scrapes with validated data
    become (DOM_snapshot, field_locations) training pairs.
    """

    def __init__(self):
        self._snapshots: list[DOMSnapshot] = []

    def record_snapshot(self, source: str, endpoint: str,
                        tag_histogram: dict[str, int],
                        class_vocabulary: set[str],
                        field_locations: dict[str, str]):
        """
        Store a successful (HTML → fields) mapping as training data.
        """
        snap_hash = hashlib.sha256(
            f"{source}:{endpoint}:{sorted(field_locations.items())}".encode()
        ).hexdigest()[:16]

        snapshot = DOMSnapshot(
            source=source,
            endpoint=endpoint,
            tag_histogram=tag_histogram,
            class_vocabulary=class_vocabulary,
            field_locations=field_locations,
            snapshot_hash=snap_hash,
        )
        self._snapshots.append(snapshot)
        log.info(f"Recorded schema snapshot: {source}/{endpoint} ({snap_hash})")

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def get_snapshots(self, source: str | None = None,
                      endpoint: str | None = None) -> list[DOMSnapshot]:
        """Retrieve stored snapshots, optionally filtered."""
        result = self._snapshots
        if source:
            result = [s for s in result if s.source == source]
        if endpoint:
            result = [s for s in result if s.endpoint == endpoint]
        return result

    def can_train(self, min_snapshots: int = 20) -> bool:
        """Check if enough snapshots exist for classifier training."""
        return len(self._snapshots) >= min_snapshots

    def augment(self, snapshot: DOMSnapshot, n_variants: int = 3) -> list[DOMSnapshot]:
        """
        Generate augmented training examples by mutating a snapshot.
        - Rename CSS classes
        - Modify tag histogram slightly
        """
        variants = []
        for i in range(n_variants):
            new_classes = {f"new_{cls}_{i}" for cls in snapshot.class_vocabulary}
            new_tags = {t: c + i for t, c in snapshot.tag_histogram.items()}
            variants.append(DOMSnapshot(
                source=snapshot.source,
                endpoint=snapshot.endpoint,
                tag_histogram=new_tags,
                class_vocabulary=new_classes,
                field_locations=snapshot.field_locations,
                snapshot_hash=f"aug_{snapshot.snapshot_hash}_{i}",
            ))
        return variants
