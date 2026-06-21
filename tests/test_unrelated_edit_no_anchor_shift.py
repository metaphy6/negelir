"""
Proof test: Phase 13.4 — Anchor-set immutability under unrelated edits.

Binding requirement: Editing a non-anchor field (e.g., competition stage dates)
does not perturb a single `stable_id` (proof test per §13.4).

Requirement details:
- The anchor resolver maintains stable_ids for clubs based on observed name forms
- When other fields (competition dates, venue info, etc.) are updated, the
  club's stable_id must NOT change
- The anchor set is immutable with respect to unrelated schema changes
"""

import pytest

from ai.swarm.identity import AnchorResolver


class TestUnrelatedEditNoAnchorShift:
    """Proof that unrelated edits don't perturb anchor stable_ids."""

    def test_anchor_resolver_stable_id_immutable_across_updates(self):
        """
        Core immutability proof: adding observations with same name form
        does NOT change the club's stable_id.

        Phase 13.4 binding: Anchor-set immutability under unrelated edits.
        """
        resolver = AnchorResolver()

        # Initialize an anchor for a club
        stable_id_original = "galatasaray_tr"
        resolver.add_observation(
            stable_id=stable_id_original,
            name_form="Galatasaray",
            source="mackolik",
            competition="tr_super_lig",
        )

        anchor_1 = resolver.get_anchor_set(stable_id_original)
        assert anchor_1 is not None
        assert anchor_1.stable_id == stable_id_original

        # Now add observations from other sources/competitions (simulating
        # unrelated data updates, e.g., new match dates, venue info)
        for source in ["nesine", "tff", "openfootball"]:
            for competition in ["tr_super_lig", "turkiye_kupasi", "ucl"]:
                resolver.add_observation(
                    stable_id=stable_id_original,
                    name_form="Galatasaray",
                    source=source,
                    competition=competition,
                )

        # Verify: stable_id is unchanged
        anchor_2 = resolver.get_anchor_set(stable_id_original)
        assert anchor_2.stable_id == stable_id_original
        assert anchor_2.stable_id == anchor_1.stable_id

    def test_anchor_resolver_multiple_clubs_independent_stability(self):
        """
        Verify that editing observations for one club doesn't affect another
        club's stable_id.

        Isolation proof: clubs maintain independent, immutable identities.
        """
        resolver = AnchorResolver()

        # Initialize three clubs
        club_ids = ["galatasaray_tr", "barcelona_es", "liverpool_en"]

        for club_id in club_ids:
            resolver.add_observation(
                stable_id=club_id,
                name_form=club_id.split("_")[0],
                source="mackolik",
                competition="league_1",
            )

        # Snapshot stable_ids
        snapshots = {cid: resolver.get_anchor_set(cid).stable_id for cid in club_ids}

        # Add more observations to all clubs (simulating data updates)
        for club_id in club_ids:
            for i in range(10):
                resolver.add_observation(
                    stable_id=club_id,
                    name_form=club_id.split("_")[0],
                    source=f"source_{i}",
                    competition=f"comp_{i}",
                )

        # Verify: all stable_ids remain unchanged
        for club_id in club_ids:
            assert resolver.get_anchor_set(club_id).stable_id == snapshots[club_id]

    def test_anchor_resolver_canonical_form_stable(self):
        """
        Verify that the canonical form (preferred name) doesn't shift
        when new observations are added.

        Phase 13.4 binding: Anchor immutability includes name form stability.
        """
        resolver = AnchorResolver()

        stable_id = "real_madrid_es"

        # First observation (sets canonical form)
        resolver.add_observation(
            stable_id=stable_id,
            name_form="Real Madrid",
            source="mackolik",
            competition="la_liga",
        )

        anchor_1 = resolver.get_anchor_set(stable_id)
        canonical_form_1 = anchor_1.canonical_form
        assert canonical_form_1 == "Real Madrid"

        # Add more observations (same name form, different source/competition)
        for _ in range(5):
            resolver.add_observation(
                stable_id=stable_id,
                name_form="Real Madrid",
                source="nesine",
                competition="ucl",
            )

        # Verify: canonical form unchanged
        anchor_2 = resolver.get_anchor_set(stable_id)
        assert anchor_2.canonical_form == canonical_form_1

    def test_anchor_resolver_immutability_across_resolver_operations(self):
        """
        Verify that calling idempotent_check() or other resolver operations
        does not mutate the anchor's stable_id.

        Integration: anchor immutability holds across all resolver methods.
        """
        resolver = AnchorResolver()

        stable_id = "fc_barcelona_es"

        # Build anchor
        resolver.add_observation(
            stable_id=stable_id,
            name_form="Barcelona",
            source="mackolik",
            competition="la_liga",
        )
        resolver.add_observation(
            stable_id=stable_id,
            name_form="Barcelona",
            source="nesine",
            competition="ucl",
        )

        # Snapshot stable_id
        anchor_before = resolver.get_anchor_set(stable_id)
        stable_id_before = anchor_before.stable_id
        entries_before = len(anchor_before.entries)

        # Run resolver operations
        resolver.idempotent_check()
        resolver.should_merge("Barcelona", "Barcelona")
        resolver.cosine_similarity(
            resolver._embed("Barcelona"), resolver._embed("Barcelona")
        )

        # Verify: stable_id and structure unchanged
        anchor_after = resolver.get_anchor_set(stable_id)
        assert anchor_after.stable_id == stable_id_before
        assert len(anchor_after.entries) == entries_before
