"""
Negelir — Player registry + fuzzy player name resolution.
Phase 5: Dynamic player→team lookup replacing hardcoded _PLAYER_TEAMS.
Phase 13.4.5.2: On-loan dual eligibility for predictor lineup features.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from common.logger import get_logger
from tqu.normalizer import asciify

log = get_logger("tqu.player_registry")


@dataclass
class PlayerRecord:
    """A player tracked in the registry."""
    source_id: str
    name: str
    team_id: str
    position: str = ""
    active: bool = True
    eligibility: list[str] = field(default_factory=list)  # national_team_id list for Phase 13.4
    
    # Phase 13.4.5.2 — On-loan tracking
    on_loan_from: Optional[str] = None  # Parent club if on loan
    loan_end_date: Optional[str] = None  # ISO 8601 date when loan ends (YYYY-MM-DD)
    
    def is_on_loan(self) -> bool:
        """Check if player is currently on loan."""
        return self.on_loan_from is not None
    
    def eligible_at(self, date_str: str) -> list[str]:
        """
        Get list of clubs this player is eligible for on a given date.
        
        Per Phase 13.4.5.2: A player on loan retains eligibility for both
        the parent club and the loan club until loan_end_date (inclusive).
        
        Args:
            date_str: ISO 8601 date string (YYYY-MM-DD)
        
        Returns:
            List of eligible club team_ids for that date
        """
        if not self.is_on_loan():
            # Not on loan: eligible for current team only
            return [self.team_id]
        
        # On loan: check if loan is still active
        if self.loan_end_date is None:
            # No end date: assume permanent move
            return [self.team_id]
        
        try:
            fixture_date = datetime.fromisoformat(date_str).date()
            loan_end = datetime.fromisoformat(self.loan_end_date).date()
        except (ValueError, TypeError):
            # Invalid date: return only current team (conservative)
            return [self.team_id]
        
        if fixture_date <= loan_end:
            # Loan still active: eligible for both clubs
            return sorted([self.team_id, self.on_loan_from])
        else:
            # Loan expired: eligible for parent club only
            return [self.on_loan_from] if self.on_loan_from else [self.team_id]


@dataclass
class PlayerRef:
    """Resolved player reference from user text."""
    name: str
    team_id: str
    confidence: float = 1.0


class PlayerRegistry:
    """
    In-memory player registry for dynamic player→team resolution.
    Populated from scraper data; supports fuzzy matching.
    """

    def __init__(self):
        self._players: dict[str, PlayerRecord] = {}  # source_id → record
        self._name_index: dict[str, list[str]] = {}  # normalized_name → [source_ids]

    def add(self, player: PlayerRecord):
        """Add or update a player in the registry."""
        self._players[player.source_id] = player
        norm = self._normalize(player.name)
        self._name_index.setdefault(norm, [])
        if player.source_id not in self._name_index[norm]:
            self._name_index[norm].append(player.source_id)

    def lookup(self, name: str) -> PlayerRef | None:
        """
        Look up a player by name (exact or fuzzy).
        Returns PlayerRef with team_id, or None if not found.
        """
        norm = self._normalize(name)

        # Exact match
        if norm in self._name_index:
            for sid in self._name_index[norm]:
                p = self._players[sid]
                if p.active:
                    return PlayerRef(name=p.name, team_id=p.team_id)

        # Fuzzy match — Levenshtein on short names
        best_match = None
        best_dist = 999
        for indexed_name, source_ids in self._name_index.items():
            dist = self._levenshtein(norm, indexed_name)
            max_dist = 2 if len(norm) >= 6 else 1
            if dist <= max_dist and dist < best_dist:
                for sid in source_ids:
                    p = self._players[sid]
                    if p.active:
                        best_match = PlayerRef(
                            name=p.name, team_id=p.team_id,
                            confidence=1.0 - dist * 0.2
                        )
                        best_dist = dist

        return best_match

    def get_team_players(self, team_id: str) -> list[PlayerRecord]:
        """Get all active players for a team."""
        return [p for p in self._players.values() if p.team_id == team_id and p.active]

    def deactivate(self, source_id: str):
        """Mark a player as inactive (left team)."""
        if source_id in self._players:
            self._players[source_id].active = False

    @property
    def size(self) -> int:
        return len(self._players)

    @property
    def active_count(self) -> int:
        return sum(1 for p in self._players.values() if p.active)

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize for matching: lowercase, ASCII fold, strip spaces."""
        return asciify(name.lower().strip())

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """Compute Levenshtein edit distance."""
        if len(s1) < len(s2):
            return PlayerRegistry._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]


@dataclass
class Transfer:
    """Detected player transfer."""
    player_name: str
    source_id: str
    from_team: str | None
    to_team: str | None
    transfer_type: str = "transfer"  # transfer, loan, release


class TransferDetector:
    """
    Detects roster changes by comparing previous vs current snapshots.
    """

    def detect_changes(self, previous: dict[str, list[PlayerRecord]],
                       current: dict[str, list[PlayerRecord]]) -> list[Transfer]:
        """
        Compare previous roster snapshot vs current.
        Returns list of detected transfers.

        Args:
            previous: {team_id: [PlayerRecord, ...]}
            current:  {team_id: [PlayerRecord, ...]}
        """
        transfers = []

        # Build lookup: source_id → (team_id, player) for both snapshots
        prev_map: dict[str, tuple[str, PlayerRecord]] = {}
        for team_id, players in previous.items():
            for p in players:
                prev_map[p.source_id] = (team_id, p)

        curr_map: dict[str, tuple[str, PlayerRecord]] = {}
        for team_id, players in current.items():
            for p in players:
                curr_map[p.source_id] = (team_id, p)

        # Departures
        for sid, (old_team, player) in prev_map.items():
            if sid not in curr_map:
                transfers.append(Transfer(
                    player_name=player.name,
                    source_id=sid,
                    from_team=old_team,
                    to_team=None,
                    transfer_type="release",
                ))
            elif curr_map[sid][0] != old_team:
                transfers.append(Transfer(
                    player_name=player.name,
                    source_id=sid,
                    from_team=old_team,
                    to_team=curr_map[sid][0],
                    transfer_type="transfer",
                ))

        # New arrivals (not in previous at all)
        for sid, (new_team, player) in curr_map.items():
            if sid not in prev_map:
                transfers.append(Transfer(
                    player_name=player.name,
                    source_id=sid,
                    from_team=None,
                    to_team=new_team,
                    transfer_type="transfer",
                ))

        return transfers
