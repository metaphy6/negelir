"""
AnchorResolver — maintains per-club anchor sets for cross-competition identity.

Phase 13.4 binding: The resolver maintains a union of all observed name forms
for each club across sources and competitions. Merge decisions are gated by
cosine similarity over a ≤50 MB embedding model (doctrine #4).

The anchor set is immutable once persisted; updates are appended as new
observations of the same club under different name forms. This ensures
idempotency and auditability.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    import fasttext
except ImportError:
    fasttext = None


_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnchorSetEntry:
    """
    A single observation of a club under a name form.

    Attributes:
        name_form: The observed name (e.g., "Galatasaray", "Gala", "GS")
        sources: Frozenset of source keys that observed this name (e.g., {"mackolik", "nesine"})
        competitions: Frozenset of competition IDs where seen (e.g., {"tr_super_lig", "ucl"})
    """

    name_form: str
    sources: frozenset[str] = field(default_factory=frozenset)
    competitions: frozenset[str] = field(default_factory=frozenset)

    def stable_id(self) -> str:
        """Content-addressed ID for this entry (for audit trails)."""
        content = f"{self.name_form}:{sorted(self.sources)}:{sorted(self.competitions)}"
        return hashlib.sha256(content.encode()).hexdigest()[:8]


@dataclass
class AnchorSet:
    """
    Union of all observed name forms for a single club (stable_id).

    Attributes:
        stable_id: Canonical club identity (e.g., "galatasaray_tr")
        entries: List of AnchorSetEntry observations
        canonical_form: The preferred name form (usually the most frequently observed)
    """

    stable_id: str
    entries: list[AnchorSetEntry] = field(default_factory=list)
    canonical_form: Optional[str] = None

    def add_observation(
        self,
        name_form: str,
        source: str,
        competition: str,
    ) -> bool:
        """
        Add a new observation of this club under a name form.

        Returns True if a new entry was added, False if this observation
        was already present.

        Args:
            name_form: The observed name
            source: Source key that made the observation
            competition: Competition ID where observed
        """
        for entry in self.entries:
            if entry.name_form == name_form:
                # Entry exists; update sources and competitions
                new_sources = entry.sources | {source}
                new_competitions = entry.competitions | {competition}
                if new_sources != entry.sources or new_competitions != entry.competitions:
                    # Create updated entry
                    updated = AnchorSetEntry(
                        name_form=name_form,
                        sources=new_sources,
                        competitions=new_competitions,
                    )
                    idx = self.entries.index(entry)
                    self.entries[idx] = updated
                    return True
                return False

        # New entry
        new_entry = AnchorSetEntry(
            name_form=name_form,
            sources={source},
            competitions={competition},
        )
        self.entries.append(new_entry)

        # Update canonical if not set
        if self.canonical_form is None:
            self.canonical_form = name_form

        return True

    def all_name_forms(self) -> list[str]:
        """Return all observed name forms in this anchor set."""
        return [e.name_form for e in self.entries]


class AnchorResolver:
    """
    Maintains per-club anchor sets and decides whether to merge based on
    cosine similarity of embeddings.

    Phase 13.4 §13.4 binding: All club identity merges are gated by this
    threshold (default 0.94). Entries below 0.85 are flagged for manual
    review (maint.event.v1{kind=identity.merge.ambiguous}).
    """

    def __init__(
        self,
        merge_threshold: float = 0.94,
        similarity_floor_manual_review: float = 0.85,
        embedding_model: Optional[object] = None,
    ):
        """
        Initialize the anchor resolver.

        Args:
            merge_threshold: Cosine similarity threshold for auto-merge (default 0.94)
            similarity_floor_manual_review: Threshold for flagging ambiguous merges
                (default 0.85)
            embedding_model: Optional pre-loaded embedding model. If None, a fallback
                simple embedding is used.

        Raises:
            ValueError: If thresholds are not in [0.85, 1.0] or merge_threshold <
                similarity_floor_manual_review.
        """
        if not (0.85 <= similarity_floor_manual_review <= 1.0):
            raise ValueError(
                f"similarity_floor_manual_review must be in [0.85, 1.0], "
                f"got {similarity_floor_manual_review}"
            )
        if not (similarity_floor_manual_review <= merge_threshold <= 1.0):
            raise ValueError(
                f"merge_threshold must be >= similarity_floor_manual_review "
                f"({similarity_floor_manual_review}), got {merge_threshold}"
            )

        self.merge_threshold = merge_threshold
        self.similarity_floor_manual_review = similarity_floor_manual_review
        self.embedding_model = embedding_model

        # In-memory anchor store: stable_id → AnchorSet
        self._anchors: dict[str, AnchorSet] = {}

        _log.debug(
            "AnchorResolver initialized: merge_threshold=%.2f, "
            "manual_review_floor=%.2f",
            merge_threshold,
            similarity_floor_manual_review,
        )

    def _embed(self, text: str) -> np.ndarray:
        """
        Embed a text string into a fixed-size vector.

        If an embedding model is provided, use it. Otherwise fall back to a
        simple bag-of-characters embedding (deterministic, no external model).

        Args:
            text: The text to embed (e.g., club name)

        Returns:
            A 1D numpy array of embeddings
        """
        if self.embedding_model is not None:
            # Assume model has a get_sentence_vector() or similar method
            if hasattr(self.embedding_model, "get_sentence_vector"):
                return self.embedding_model.get_sentence_vector(text)
            elif hasattr(self.embedding_model, "encode"):
                # sentence-transformers style
                return self.embedding_model.encode(text)

        # Fallback: simple bag-of-character n-gram embedding
        # Normalize text for consistency
        normalized = text.lower().strip()

        # Build a 256-dim vector from character frequencies (0-127 ASCII)
        char_counts = np.zeros(128, dtype=np.float32)
        for ch in normalized:
            code = ord(ch) if ord(ch) < 128 else 63  # '?' for non-ASCII
            char_counts[code] += 1.0

        # L2 normalize
        norm = np.linalg.norm(char_counts)
        if norm > 0:
            char_counts = char_counts / norm
        else:
            # Empty string fallback
            char_counts[0] = 1.0

        return char_counts

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            a: First embedding vector
            b: Second embedding vector

        Returns:
            Cosine similarity in [0.0, 1.0]
        """
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(np.clip(dot / (norm_a * norm_b), 0.0, 1.0))

    def should_merge(self, name_a: str, name_b: str) -> tuple[bool, float]:
        """
        Decide whether two name forms should be merged into the same anchor.

        Returns:
            Tuple (should_merge, similarity) where should_merge is True if
            similarity >= merge_threshold, False otherwise. The similarity
            score is always returned.
        """
        embed_a = self._embed(name_a)
        embed_b = self._embed(name_b)
        similarity = self.cosine_similarity(embed_a, embed_b)

        should_merge = similarity >= self.merge_threshold

        _log.debug(
            "Merge decision: %r vs %r → similarity=%.3f, merge=%s",
            name_a,
            name_b,
            similarity,
            should_merge,
        )

        return should_merge, similarity

    def classify_merge(
        self, name_a: str, name_b: str
    ) -> tuple[str, float]:
        """
        Classify a potential merge into one of three categories.

        Returns:
            Tuple (classification, similarity) where classification is one of:
            - "merge": auto-merge (similarity >= merge_threshold)
            - "ambiguous": manual review needed (similarity in [0.85, 0.94))
            - "keep_distinct": do not merge (similarity < 0.85)

        Phase 13.4.1 binding: Ambiguous merges emit proof.flag instead of
        auto-merging, surfaced in the ops console (Phase 8).
        """
        embed_a = self._embed(name_a)
        embed_b = self._embed(name_b)
        similarity = self.cosine_similarity(embed_a, embed_b)

        if similarity >= self.merge_threshold:
            classification = "merge"
        elif similarity >= self.similarity_floor_manual_review:
            classification = "ambiguous"
        else:
            classification = "keep_distinct"

        _log.debug(
            "Merge classification: %r vs %r → similarity=%.3f, class=%s",
            name_a,
            name_b,
            similarity,
            classification,
        )

        return classification, similarity

    def add_observation(
        self,
        stable_id: str,
        name_form: str,
        source: str,
        competition: str,
    ) -> None:
        """
        Record an observation of a club under a name form.

        Args:
            stable_id: The canonical club identity
            name_form: The observed name form
            source: Source key that made the observation
            competition: Competition ID where observed
        """
        if stable_id not in self._anchors:
            self._anchors[stable_id] = AnchorSet(stable_id=stable_id)

        self._anchors[stable_id].add_observation(
            name_form=name_form,
            source=source,
            competition=competition,
        )

    def get_anchor_set(self, stable_id: str) -> Optional[AnchorSet]:
        """Retrieve the anchor set for a club by stable_id."""
        return self._anchors.get(stable_id)

    def all_anchor_sets(self) -> dict[str, AnchorSet]:
        """Return a copy of all anchor sets."""
        return dict(self._anchors)

    def idempotent_check(self) -> bool:
        """
        Verify idempotency: re-running the resolver on the current anchor set
        should produce identical merge decisions.

        This is a proof test (Phase 13.4 §13.4 idempotent merges).

        Returns:
            True if idempotency holds, False otherwise.
        """
        # For each anchor, recompute which name forms should merge with each other
        for stable_id, anchor_set in self._anchors.items():
            name_forms = anchor_set.all_name_forms()

            # Check that within the same anchor, all forms should merge with each other
            for i, name_a in enumerate(name_forms):
                for name_b in name_forms[i + 1 :]:
                    should_merge, sim = self.should_merge(name_a, name_b)
                    if not should_merge:
                        _log.warning(
                            "Idempotency violation: %r and %r in anchor %s "
                            "should merge (similarity %.3f) but don't",
                            name_a,
                            name_b,
                            stable_id,
                            sim,
                        )
                        return False

        return True
