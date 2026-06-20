"""
Tests for Phase 13.4 — Cross-competition identity resolution (anchor resolver).

Proof tests for the AnchorResolver per 13.4 checklist:
- Maintains per-club anchor sets
- Merge decisions gated by cosine similarity threshold
- Idempotent merges (re-running on same set produces no-op)
- No false merges under threshold
"""

import pytest

from ai.swarm.identity import AnchorResolver


class TestAnchorResolverBasics:
    """Basic anchor set management and merge decisions."""

    def test_anchor_resolver_initialization(self):
        """Test that resolver initializes with correct thresholds."""
        resolver = AnchorResolver(merge_threshold=0.94, similarity_floor_manual_review=0.85)
        assert resolver.merge_threshold == 0.94
        assert resolver.similarity_floor_manual_review == 0.85

    def test_anchor_resolver_add_observation(self):
        """Test adding observations to an anchor set."""
        resolver = AnchorResolver()
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="mackolik",
            competition="tr_super_lig",
        )
        anchor = resolver.get_anchor_set("galatasaray_tr")
        assert anchor is not None
        assert "Galatasaray" in anchor.all_name_forms()

    def test_anchor_resolver_merge_same_form(self):
        """Test that identical name forms are always merged."""
        resolver = AnchorResolver()
        should_merge, sim = resolver.should_merge("Galatasaray", "Galatasaray")
        assert should_merge is True
        assert sim == pytest.approx(1.0, abs=1e-2)

    def test_anchor_resolver_no_merge_dissimilar(self):
        """Test that completely different names don't merge."""
        resolver = AnchorResolver(merge_threshold=0.94)
        should_merge, sim = resolver.should_merge("Galatasaray", "Liverpool")
        assert should_merge is False
        assert sim < 0.94

    def test_anchor_resolver_threshold_validation(self):
        """Test that invalid thresholds raise ValueError."""
        with pytest.raises(ValueError, match="merge_threshold must be"):
            AnchorResolver(
                merge_threshold=0.80,  # Less than similarity_floor (0.85)
                similarity_floor_manual_review=0.85,
            )

        with pytest.raises(ValueError, match="similarity_floor_manual_review"):
            AnchorResolver(similarity_floor_manual_review=0.5)  # Less than 0.85


class TestAnchorResolverIdempotency:
    """Test idempotent merge decisions (Phase 13.4 binding)."""

    def test_anchor_resolver_idempotent(self):
        """
        Test that re-running the resolver on the same anchor set produces
        identical merge decisions (no-op).

        Phase 13.4 binding: Idempotent merges (§13.4).
        """
        resolver = AnchorResolver(merge_threshold=0.94)

        # Add multiple observations for the same club
        resolver.add_observation(
            stable_id="real_madrid",
            name_form="Real Madrid",
            source="mackolik",
            competition="la_liga",
        )
        resolver.add_observation(
            stable_id="real_madrid",
            name_form="Real Madrid",
            source="nesine",
            competition="ucl",
        )

        # Idempotency check should pass
        assert resolver.idempotent_check() is True

    def test_anchor_resolver_duplicate_observations(self):
        """Test that duplicate observations don't duplicate anchor entries."""
        resolver = AnchorResolver()

        # Add same observation twice
        resolver.add_observation(
            stable_id="barcelona",
            name_form="Barcelona",
            source="mackolik",
            competition="la_liga",
        )
        resolver.add_observation(
            stable_id="barcelona",
            name_form="Barcelona",
            source="mackolik",
            competition="la_liga",
        )

        anchor = resolver.get_anchor_set("barcelona")
        # Should still have only one entry
        assert len(anchor.entries) == 1
        assert anchor.entries[0].name_form == "Barcelona"


class TestAnchorResolverCrosixCompetition:
    """Test cross-competition identity merging."""

    def test_anchor_resolver_cross_competition_joins(self):
        """
        Test that the same club observed in different competitions
        has a unified anchor set.

        Phase 13.4 binding: Merger decision union of all sources × competitions.
        """
        resolver = AnchorResolver()

        # Observe Galatasaray in Süper Lig
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="mackolik",
            competition="tr_super_lig",
        )

        # Observe same club in UCL
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="nesine",
            competition="ucl",
        )

        anchor = resolver.get_anchor_set("galatasaray_tr")
        assert anchor is not None

        # Both competitions should be in the anchor
        entries = anchor.entries
        assert len(entries) == 1  # Same name form
        assert "tr_super_lig" in entries[0].competitions
        assert "ucl" in entries[0].competitions

    def test_anchor_resolver_multi_source_multi_competition(self):
        """
        Test that multi-source × multi-competition observations are tracked.

        Phase 13.4 binding: Union of observed name forms across all sources ×
        all competitions.
        """
        resolver = AnchorResolver()

        # Multiple sources, multiple competitions
        sources_comps = [
            ("mackolik", "tr_super_lig"),
            ("nesine", "tr_super_lig"),
            ("tff", "turkiye_kupasi"),
            ("nesine", "ucl"),
        ]

        for source, competition in sources_comps:
            resolver.add_observation(
                stable_id="galatasaray_tr",
                name_form="Galatasaray",
                source=source,
                competition=competition,
            )

        anchor = resolver.get_anchor_set("galatasaray_tr")
        entry = anchor.entries[0]

        # All sources and competitions should be tracked
        assert "mackolik" in entry.sources
        assert "nesine" in entry.sources
        assert "tff" in entry.sources
        assert "tr_super_lig" in entry.competitions
        assert "turkiye_kupasi" in entry.competitions
        assert "ucl" in entry.competitions


class TestAnchorResolverCosineSimilarity:
    """Test cosine similarity computation and thresholds."""

    def test_anchor_resolver_cosine_similarity_identical(self):
        """Test that identical vectors have similarity 1.0."""
        resolver = AnchorResolver()
        sim = resolver.cosine_similarity(
            resolver._embed("test"),
            resolver._embed("test"),
        )
        assert sim == pytest.approx(1.0, abs=1e-2)

    def test_anchor_resolver_cosine_similarity_orthogonal(self):
        """Test that orthogonal vectors have low similarity."""
        resolver = AnchorResolver()
        import numpy as np

        a = np.array([1, 0, 0], dtype=np.float32)
        b = np.array([0, 1, 0], dtype=np.float32)
        sim = resolver.cosine_similarity(a, b)
        assert sim == pytest.approx(0.0, abs=1e-2)

    def test_anchor_resolver_cosine_similarity_normalized(self):
        """Test that cosine similarity is bounded in [0, 1]."""
        resolver = AnchorResolver()
        import numpy as np

        a = np.array([1, 2, 3], dtype=np.float32)
        b = np.array([4, 5, 6], dtype=np.float32)
        sim = resolver.cosine_similarity(a, b)
        assert 0.0 <= sim <= 1.0
