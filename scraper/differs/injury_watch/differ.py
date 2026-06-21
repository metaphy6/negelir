"""Phase 21.2 — Injury & availability differ.

Diff key: (player_id, fixture_id, status, source_confidence)
Higher-confidence source wins.

Per ENRICHMENT_DATA.md §3.4 and ROADMAP §21.2:
- Confidence-override rule: club_official in past 24h overrides all
- Stale-decay rule: doubtful older than 36h before KO → fit (prediction-time)
- Post-match reactor: lineup confirmed → retroactive fit
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, List, Tuple

from common.config import cfg
from common.logger import get_logger
from common.schemas.records import AvailabilityPayload

log = get_logger("scraper.differs.injury_watch")


CONFIDENCE_RANK = {
    "club_official": 4,
    "manager_presser": 3,
    "press": 2,
    "rumour": 1,
}
"""Confidence ranking for availability status. Higher = more trusted."""


@dataclass
class InjuryDiffer:
    """Differs availability records with confidence-override rule.
    
    Per ROADMAP §21.2:
    - Diff key: (player_id, fixture_id, status, source_confidence)
    - Higher-confidence source overrides lower
    - club_official in past 24h overrides all (bullet 4)
    - Stale-decay applied at prediction time (bullet 5)
    - Post-match reactor is idempotent (bullet 6)
    """

    def compute_diff_key(self, payload: AvailabilityPayload) -> Tuple[str, Optional[str], str, str]:
        """Compute the diff key for an availability payload.
        
        Returns: (player_id, fixture_id, status, source_confidence)
        """
        return (
            payload["player_id"],
            payload["fixture_id"],
            payload["status"],
            payload["source_confidence"],
        )

    def should_override_existing(
        self,
        new_payload: AvailabilityPayload,
        existing_payloads: List[AvailabilityPayload],
    ) -> bool:
        """Determine if new payload should override existing ones.
        
        Applies the confidence-override rule (bullet 4):
        A club_official status in the past 24h overrides all other statuses
        for the same player + fixture, regardless of recency.
        """
        new_confidence = new_payload["source_confidence"]
        new_asserted_at = datetime.fromisoformat(new_payload["asserted_at"].replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=new_asserted_at.tzinfo)
        time_since = now - new_asserted_at

        # If new status is club_official and within 24h, it always wins
        if new_confidence == "club_official" and time_since <= timedelta(hours=24):
            return True

        # Check if any existing payload is club_official within 24h
        for existing in existing_payloads:
            if existing["source_confidence"] == "club_official":
                existing_asserted = datetime.fromisoformat(
                    existing["asserted_at"].replace("Z", "+00:00")
                )
                if now - existing_asserted <= timedelta(hours=24):
                    # Existing club_official still valid; only override if new is also club_official
                    return new_confidence == "club_official"

        # No valid club_official found; use confidence ranking
        if not existing_payloads:
            return True

        max_existing_confidence = max(
            CONFIDENCE_RANK.get(p["source_confidence"], 0) for p in existing_payloads
        )
        return CONFIDENCE_RANK.get(new_confidence, 0) > max_existing_confidence

    def compute_stale_decay(
        self, payload: AvailabilityPayload, fixture_kickoff: Optional[str]
    ) -> AvailabilityPayload:
        """Apply stale-decay rule for doubtful status (bullet 5).
        
        If status is 'doubtful' and older than 36h before KO,
        status decays to 'fit' for prediction purposes.
        Editorial flag stays 'uncertain' in the response (not altered here).
        
        Returns modified payload, or original if no decay applies.
        """
        if payload["status"] != "doubtful" or not fixture_kickoff:
            return payload

        asserted_at = datetime.fromisoformat(payload["asserted_at"].replace("Z", "+00:00"))
        kickoff = datetime.fromisoformat(fixture_kickoff.replace("Z", "+00:00"))
        hours_before_ko = (kickoff - asserted_at).total_seconds() / 3600

        if hours_before_ko > 36:
            # Status is stale; decay to fit
            payload = payload.copy()
            payload["status"] = "fit"  # type: ignore
            log.info(
                f"Stale decay applied: player {payload['player_id']} "
                f"{hours_before_ko:.1f}h before KO → fit"
            )

        return payload

    def post_match_retroactive_fit(
        self,
        payload: AvailabilityPayload,
        starting_xi_player_ids: List[str],
        substitutes_player_ids: List[str],
    ) -> AvailabilityPayload:
        """Apply post-match truth correction (bullet 6).
        
        After lineup confirmed: any player in starting_xi or substitutes
        is retroactively set to 'fit' for that fixture.
        Reactor is idempotent — re-running is a no-op.
        
        Returns modified payload, or original if no match.
        """
        if payload["status"] == "fit":
            # Already fit; idempotent no-op
            return payload

        if payload["player_id"] not in starting_xi_player_ids and \
           payload["player_id"] not in substitutes_player_ids:
            # Player not in lineup
            return payload

        # Player appeared in lineup → retroactively set to fit
        payload = payload.copy()
        old_status = payload["status"]
        payload["status"] = "fit"  # type: ignore
        log.info(
            f"Post-match retroactive fit: player {payload['player_id']} "
            f"appeared in lineup; {old_status} → fit"
        )

        return payload
