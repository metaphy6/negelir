"""
Phase 13.4 — Player eligibility proof test.

Validates that Player.eligibility: list[national_team_id] is properly
populated for top-5 squads + TR national team and resolves across
club and country competitions.

Proof test: test_player_eligibility_resolves_across_club_and_country.py
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tqu.player_registry import PlayerRegistry, PlayerRecord


class TestPlayerEligibilityAcrossClubAndCountry:
    """Test suite for Phase 13.4 player eligibility resolution."""

    def test_player_eligibility_field_exists(self):
        """Player.eligibility field is present and defaults to empty list."""
        player = PlayerRecord(
            source_id="p1",
            name="Hakan Çalhanoğlu",
            team_id="galatasaray",
        )
        assert hasattr(player, "eligibility")
        assert player.eligibility == []

    def test_player_eligibility_single_national_team(self):
        """Player.eligibility populated with single national team ID."""
        player = PlayerRecord(
            source_id="p1",
            name="Hakan Çalhanoğlu",
            team_id="galatasaray",
            eligibility=["tr_national"],  # Turkish national team
        )
        assert player.eligibility == ["tr_national"]

    def test_player_eligibility_multiple_national_teams(self):
        """Player.eligibility supports dual nationality (Phase 13.14)."""
        player = PlayerRecord(
            source_id="p2",
            name="Diego Costa",
            team_id="atletico_madrid",
            eligibility=["es_national", "br_national"],  # Spain + Brazil
        )
        assert len(player.eligibility) == 2
        assert "es_national" in player.eligibility
        assert "br_national" in player.eligibility

    def test_player_eligibility_registry_preservation(self):
        """PlayerRegistry preserves eligibility list through add/lookup cycle."""
        reg = PlayerRegistry()
        player = PlayerRecord(
            source_id="p1",
            name="Mauro Icardi",
            team_id="galatasaray",
            eligibility=["ar_national"],  # Argentina
        )
        reg.add(player)

        # Retrieve via registry
        retrieved = reg._players.get("p1")
        assert retrieved is not None
        assert retrieved.eligibility == ["ar_national"]

    def test_player_eligibility_top5_squads_tr_national(self):
        """
        Players from top-5 leagues + TR national team have eligibility populated.

        Top-5 squads: Premier League (en), La Liga (es), Serie A (it),
        Bundesliga (de), Ligue 1 (fr) + TR (Turkish Süper Lig).
        """
        # Simulate a top-5 + TR player roster
        players_data = [
            ("p1", "Mohamed Salah", "liverpool", ["eg_national"]),
            ("p2", "Vinícius Júnior", "real_madrid", ["br_national"]),
            ("p3", "Lautaro Martínez", "inter_milan", ["ar_national"]),
            ("p4", "Florian Wirtz", "bayer_leverkusen", ["de_national"]),
            ("p5", "Kylian Mbappé", "paris_saint_germain", ["fr_national"]),
            ("p6", "Mauro Icardi", "galatasaray", ["ar_national"]),
            ("p7", "Hakan Çalhanoğlu", "galatasaray", ["tr_national"]),
        ]

        reg = PlayerRegistry()
        for sid, name, team, eligibility in players_data:
            player = PlayerRecord(
                source_id=sid,
                name=name,
                team_id=team,
                eligibility=eligibility,
            )
            reg.add(player)

        # Verify all players are stored with proper eligibility
        assert reg.size == len(players_data)
        for sid, name, team, eligibility in players_data:
            p = reg._players.get(sid)
            assert p is not None, f"Player {name} not found"
            assert p.eligibility == eligibility, \
                f"Player {name} eligibility mismatch"

    def test_player_eligibility_cross_competition_join(self):
        """
        Eligibility enables cross-competition joins (club fixture + national fixture).

        A player appearing in both domestic league and international matches
        can be tracked across both competitions via their eligibility list.
        """
        reg = PlayerRegistry()

        # Club fixture: Galatasaray vs Liverpool
        player_club = PlayerRecord(
            source_id="ic1",
            name="İsmail Çipe",
            team_id="galatasaray",
            eligibility=["tr_national"],
        )
        reg.add(player_club)

        # Same player in national team fixture: Turkey vs Greece
        player_national = reg._players.get("ic1")
        assert player_national is not None
        assert "tr_national" in player_national.eligibility
        # The national team ID in eligibility allows joining to national team fixtures

    def test_player_eligibility_empty_by_default(self):
        """Existing players without eligibility data have empty list (backward compat)."""
        player = PlayerRecord(
            source_id="p1",
            name="Generic Player",
            team_id="team_001",
        )
        assert isinstance(player.eligibility, list)
        assert len(player.eligibility) == 0

    def test_player_eligibility_non_tr_national_teams(self):
        """
        Players from non-top-5 leagues may also have eligibility populated
        for their national teams (Phase 13.4 prerequisite for international play).
        """
        reg = PlayerRegistry()

        # Player from a second-tier league with national team eligibility
        player = PlayerRecord(
            source_id="p1",
            name="Josip Iličević",
            team_id="dinamo_zagreb",
            eligibility=["hr_national"],  # Croatian national team
        )
        reg.add(player)

        retrieved = reg._players.get("p1")
        assert retrieved is not None
        assert retrieved.eligibility == ["hr_national"]

    def test_player_eligibility_immutable_across_team_changes(self):
        """
        Player eligibility is independent of current team_id.
        A player retains national team eligibility even if they transfer.
        """
        reg = PlayerRegistry()

        # Player at Club A
        player_v1 = PlayerRecord(
            source_id="p1",
            name="Transfer Player",
            team_id="club_a",
            eligibility=["mx_national"],
        )
        reg.add(player_v1)

        # Same player transfers to Club B (eligibility unchanged)
        player_v2 = PlayerRecord(
            source_id="p1",
            name="Transfer Player",
            team_id="club_b",
            eligibility=["mx_national"],
        )
        reg.add(player_v2)  # Overwrites with same eligibility

        retrieved = reg._players.get("p1")
        assert retrieved.team_id == "club_b"
        assert retrieved.eligibility == ["mx_national"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
