"""
Negelir P2P — Schema gossip protocol for propagating discovered scraper schemas.
Phase 7: When a peer discovers a working schema for a changed source,
it broadcasts the discovery for P2P consensus before network-wide adoption.
"""

import time
import uuid
from dataclasses import dataclass, field

from common.logger import get_logger
from config import p2p_cfg

log = get_logger("coordination.schema_gossip")


@dataclass
class SchemaProposal:
    """A proposed set of selectors discovered by a peer."""
    proposal_id: str = ""
    source: str = ""
    endpoint: str = ""
    selectors: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    discovery_layer: str = "heuristic"
    proposer_id: str = ""
    created_at: float = field(default_factory=time.time)
    votes_for: int = 0
    votes_against: int = 0
    adopted: bool = False
    voters: set[str] = field(default_factory=set)


class SchemaGossipProtocol:
    """
    P2P protocol for propagating discovered scraper schemas.

    Flow:
    1. Peer detects structural drift on a source
    2. Peer runs field discovery → gets DiscoveredSchema with confidence
    3. Peer validates via data contracts locally
    4. Peer broadcasts SCHEMA_PROPOSAL to network
    5. Other peers independently validate the proposed selectors
    6. Peers that confirm send SCHEMA_VOTE
    7. Once votes >= QUORUM, the schema is ADOPTED network-wide
    """

    def __init__(
        self,
        quorum: int | None = None,
        vote_timeout_sec: int | None = None,
        confidence_floor: float | None = None,
    ):
        self.quorum = quorum if quorum is not None else p2p_cfg.schema_quorum
        self.vote_timeout_sec = (
            vote_timeout_sec if vote_timeout_sec is not None else p2p_cfg.schema_vote_timeout_sec
        )
        self.confidence_floor = (
            confidence_floor if confidence_floor is not None else p2p_cfg.schema_confidence_floor
        )
        self._proposals: dict[str, SchemaProposal] = {}
        self._adopted: list[SchemaProposal] = []

    def create_proposal(self, source: str, endpoint: str,
                        selectors: dict[str, str], confidence: float,
                        discovery_layer: str, proposer_id: str) -> SchemaProposal | None:
        """
        Create a new schema proposal if confidence meets floor.
        Returns the proposal or None if confidence too low.
        """
        if confidence < self.confidence_floor:
            log.info(f"Proposal rejected: confidence {confidence:.2f} < floor {self.confidence_floor}")
            return None

        proposal = SchemaProposal(
            proposal_id=uuid.uuid4().hex[:12],
            source=source,
            endpoint=endpoint,
            selectors=selectors,
            confidence=confidence,
            discovery_layer=discovery_layer,
            proposer_id=proposer_id,
            votes_for=1,  # proposer votes for own proposal
            voters={proposer_id},
        )
        self._proposals[proposal.proposal_id] = proposal
        log.info(f"Schema proposal created: {proposal.proposal_id} for {source}/{endpoint}")
        return proposal

    def cast_vote(self, proposal_id: str, voter_id: str,
                  confirm: bool) -> bool:
        """
        Cast a vote on a proposal. Returns True if quorum reached.
        A peer can only vote once per proposal.
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            log.warning(f"Vote on unknown proposal: {proposal_id}")
            return False

        if proposal.adopted:
            return True  # already adopted

        if voter_id in proposal.voters:
            log.info(f"Duplicate vote from {voter_id} on {proposal_id}")
            return proposal.votes_for >= self.quorum

        proposal.voters.add(voter_id)
        if confirm:
            proposal.votes_for += 1
        else:
            proposal.votes_against += 1

        if proposal.votes_for >= self.quorum:
            self._adopt(proposal)
            return True

        return False

    def _adopt(self, proposal: SchemaProposal):
        """Mark proposal as adopted once quorum is reached."""
        proposal.adopted = True
        self._adopted.append(proposal)
        log.info(
            f"Schema ADOPTED: {proposal.proposal_id} for "
            f"{proposal.source}/{proposal.endpoint} "
            f"({proposal.votes_for} votes, layer={proposal.discovery_layer})"
        )

    def get_proposal(self, proposal_id: str) -> SchemaProposal | None:
        return self._proposals.get(proposal_id)

    def get_adopted(self) -> list[SchemaProposal]:
        return list(self._adopted)

    def is_expired(self, proposal_id: str) -> bool:
        """Check if a proposal has timed out without reaching quorum."""
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            return True
        if proposal.adopted:
            return False
        return (time.time() - proposal.created_at) > self.vote_timeout_sec

    @property
    def pending_count(self) -> int:
        return sum(
            1 for p in self._proposals.values()
            if not p.adopted and not self.is_expired(p.proposal_id)
        )
