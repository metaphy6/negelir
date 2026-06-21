"""
Proof test: Phase 13.4 — Idempotent merges.

Binding requirement: Re-running the resolver on the same anchor set is a no-op
(proof test per §13.4).

Requirement details:
- Running the merge algorithm on an already-merged anchor set produces zero
  additional merges.
- The anchor set structure remains unchanged after re-evaluation.
- All name forms within an anchor remain correctly classified as "should merge".
"""

import pytest

from ai.swarm.identity import AnchorResolver


class TestAnchorResolverIdempotent:
    """Proof that anchor resolver idempotent behavior holds."""

    def test_anchor_resolver_idempotent_no_changes(self):
        """
        Core idempotency proof: re-running the resolver on the same anchor
        set produces a no-op (zero mutations).

        Phase 13.4 binding: Idempotent merges.
        """
        resolver = AnchorResolver(merge_threshold=0.94)

        # Build a realistic anchor set: same club observed in multiple sources
        # and competitions
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="mackolik",
            competition="tr_super_lig",
        )
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="nesine",
            competition="tr_super_lig",
        )
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="tff",
            competition="turkiye_kupasi",
        )
        resolver.add_observation(
            stable_id="galatasaray_tr",
            name_form="Galatasaray",
            source="nesine",
            competition="ucl",
        )

        # Snapshot the anchor set before idempotency check
        anchor_before = resolver.get_anchor_set("galatasaray_tr")
        entries_before_count = len(anchor_before.entries)
        canonical_before = anchor_before.canonical_form

        # Run idempotency check (this validates internal merge decisions)
        is_idempotent = resolver.idempotent_check()

        # Verify: idempotent check must pass
        assert is_idempotent is True

        # Verify: anchor structure unchanged
        anchor_after = resolver.get_anchor_set("galatasaray_tr")
        assert len(anchor_after.entries) == entries_before_count
        assert anchor_after.canonical_form == canonical_before

    def test_anchor_resolver_idempotent_multiple_clubs(self):
        """
        Extended idempotency: multiple clubs in the store all remain idempotent.
        """
        resolver = AnchorResolver(merge_threshold=0.94)

        # Add observations for three different clubs
        clubs = [
            ("galatasaray_tr", "Galatasaray", ["mackolik", "nesine", "tff"]),
            ("barcelona_es", "Barcelona", ["mackolik", "nesine"]),
            ("liverpool_en", "Liverpool", ["nesine", "tff"]),
        ]

        for stable_id, name_form, sources in clubs:
            for source in sources:
                resolver.add_observation(
                    stable_id=stable_id,
                    name_form=name_form,
                    source=source,
                    competition="super_league",
                )

        # Snapshot counts
        snapshots = {}
        for stable_id, _, _ in clubs:
            anchor = resolver.get_anchor_set(stable_id)
            snapshots[stable_id] = len(anchor.entries)

        # Run idempotency check
        is_idempotent = resolver.idempotent_check()
        assert is_idempotent is True

        # Verify: all anchors unchanged
        for stable_id, _, _ in clubs:
            anchor = resolver.get_anchor_set(stable_id)
            assert len(anchor.entries) == snapshots[stable_id]

    def test_anchor_resolver_idempotent_returns_true_on_valid_merge(self):
        """
        Idempotency check must return True when all name forms in an anchor
        have similarity >= merge_threshold with each other.
        """
        resolver = AnchorResolver(merge_threshold=0.94)

        # Add a single observation (trivially idempotent)
        resolver.add_observation(
            stable_id="club_1",
            name_form="Club One",
            source="source_a",
            competition="comp_1",
        )

        is_idempotent = resolver.idempotent_check()
        assert is_idempotent is True

    def test_anchor_resolver_idempotent_cross_competition_consistency(self):
        """
        Idempotency holds even when the same club appears across many
        competitions and sources (cross-competition consistency).

        Phase 13.4 binding: Union of all observed name forms across all
        sources × all competitions remain idempotent.
        """
        resolver = AnchorResolver(merge_threshold=0.94)

        stable_id = "real_madrid_es"

        # Same club, many source × competition combinations
        observations = [
            ("mackolik", "la_liga"),
            ("nesine", "la_liga"),
            ("mackolik", "ucl"),
            ("nesine", "ucl"),
            ("tff", "la_liga"),
            ("openfootball", "ucl"),
            ("footballdata", "la_liga"),
        ]

        for source, competition in observations:
            resolver.add_observation(
                stable_id=stable_id,
                name_form="Real Madrid",
                source=source,
                competition=competition,
            )

        # Verify idempotency
        assert resolver.idempotent_check() is True

        # Verify all observations are tracked
        anchor = resolver.get_anchor_set(stable_id)
        entry = anchor.entries[0]
        # 5 unique sources: mackolik, nesine, tff, openfootball, footballdata
        assert len(entry.sources) == 5
        # 2 competitions: la_liga, ucl
        assert len(entry.competitions) == 2
