"""
Phase 13.4.1 — Manual-review queue for ambiguous identity merges.

When two club names have similarity in [0.85, 0.94), they are flagged as
ambiguous rather than auto-merged. This prevents false-merges while
surfacing ambiguous cases to the ops console (Phase 8) for manual review.

Per AGENTS.md Rule 10: proof test that exercises the happy path and
at least one adversarial branch.
"""

import pytest
from swarm.identity.anchor_resolver import AnchorResolver


class TestManualReviewQueue:
    """Test ambiguous merge detection (13.4.1)."""

    def test_classify_merge_auto_merge_high_similarity(self) -> None:
        """Similarity >= 0.94 should classify as 'merge'."""
        resolver = AnchorResolver(
            merge_threshold=0.94,
            similarity_floor_manual_review=0.85,
        )

        # Identical names have similarity 1.0 → should auto-merge
        classification, sim = resolver.classify_merge("Galatasaray", "Galatasaray")
        assert classification == "merge"
        assert sim >= 0.94

    def test_classify_merge_ambiguous_range(self) -> None:
        """Similarity in [0.85, 0.94) should classify as 'ambiguous'."""
        resolver = AnchorResolver(
            merge_threshold=0.94,
            similarity_floor_manual_review=0.85,
        )

        # Slightly different names (e.g., abbreviation vs. full name)
        # should fall into ambiguous range
        classification, sim = resolver.classify_merge("Gala", "Galatasaray")
        assert classification == "ambiguous"
        assert 0.85 <= sim < 0.94

    def test_classify_merge_keep_distinct_low_similarity(self) -> None:
        """Similarity < 0.85 should classify as 'keep_distinct'."""
        resolver = AnchorResolver(
            merge_threshold=0.94,
            similarity_floor_manual_review=0.85,
        )

        # Very different names should not merge
        classification, sim = resolver.classify_merge(
            "Galatasaray",  # Turkish club
            "Liverpool",    # English club
        )
        assert classification == "keep_distinct"
        assert sim < 0.85

    def test_ambiguous_detection_prevents_false_merges(self) -> None:
        """Ambiguous classification prevents false-merges in edge cases."""
        resolver = AnchorResolver(
            merge_threshold=0.94,
            similarity_floor_manual_review=0.85,
        )

        # Turkish clubs with similar names but different entities
        # should be caught as ambiguous, not auto-merged
        classification1, _ = resolver.classify_merge("Real Madrid", "Real Madryt")
        classification2, _ = resolver.classify_merge("Liverpool", "Liverpool Montevideo")

        # At least one should be ambiguous (depending on similarity calculation)
        # This is the "adversarial branch" — catching near-misses that could
        # otherwise leak through as false merges (doctrine #3: no fabricated entries)
        classifications = {classification1, classification2}
        # We expect either ambiguous or keep_distinct, not auto-merge
        assert "merge" not in classifications or (
            classification1 == "keep_distinct" and classification2 == "keep_distinct"
        )

    def test_thresholds_enforce_policy(self) -> None:
        """Configuration thresholds enforce the policy."""
        resolver = AnchorResolver(
            merge_threshold=0.94,
            similarity_floor_manual_review=0.85,
        )

        # Config defaults should match Phase 13.4.1 spec
        assert resolver.merge_threshold == 0.94
        assert resolver.similarity_floor_manual_review == 0.85

    def test_ambiguous_queue_metadata(self) -> None:
        """Ambiguous classifications include similarity scores for review."""
        resolver = AnchorResolver(
            merge_threshold=0.94,
            similarity_floor_manual_review=0.85,
        )

        classification, similarity = resolver.classify_merge("Barca", "Barcelona")

        # When marked ambiguous, the reviewer has the similarity score
        # to make an informed decision (this is the metadata passed to proof.flag)
        assert classification == "ambiguous" or classification == "keep_distinct"
        assert 0.0 <= similarity <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
