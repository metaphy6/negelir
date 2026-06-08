"""
Phase 12.1.2 — Trust boundary → catcher mapping.

This module encodes the canonical mapping of trust boundaries to their 
owning agents/catchers. It is the single source of truth for §12.1.2 
and is referenced by:
- The §12.2 adversarial corpus schema (expected_catcher validation)
- The §12.5 chaos catalogue (catcher coverage audit)
- The §12.16 cross-phase coupling matrix (boundary coverage check)
"""

from dataclasses import dataclass
from typing import List

@dataclass
class TrustBoundary:
    """A single trust boundary with its owning catcher(s)."""
    name: str  # e.g. "HTTP request body / headers"
    owning_phase: int  # e.g. 9
    catcher_agent: str  # e.g. "server/internal/sec" 
    catcher_module: str  # e.g. "RequestValidator"
    catalogue_families: List[str]  # e.g. ["P12-7.1", "P12-9"]
    description: str


# §12.1.2 Canonical trust boundaries and their catchers
TRUST_BOUNDARIES = [
    TrustBoundary(
        name="HTTP request body / headers",
        owning_phase=9,
        catcher_agent="server/internal/sec",
        catcher_module="GatewayRequestValidator",
        catalogue_families=["P12-7.1", "P12-9"],
        description="Validate incoming HTTP requests before routing to swarm."
    ),
    TrustBoundary(
        name="QA prompt (Turkish)",
        owning_phase=10,
        catcher_agent="swarm/agents/nlp",
        catcher_module="sec.input.v1",
        catalogue_families=["P12-7.1", "P12-10"],
        description="Detect prompt injection, homoglyph attacks, RTL-flip abuse."
    ),
    TrustBoundary(
        name="Scraped HTML / DOM",
        owning_phase=7,
        catcher_agent="swarm/agents/sec",
        catcher_module="sec.scrape.v1",
        catalogue_families=["P12-7.2"],
        description="Detect malformed/oversized/bomb HTML from upstream sources."
    ),
    TrustBoundary(
        name="Bus envelope (cross-agent)",
        owning_phase=3,
        catcher_agent="swarm/sdk",
        catcher_module="RequestIdDeduper + SchemaGate",
        catalogue_families=["P12-3"],
        description="Validate bus envelope structure, deduplicate by request_id."
    ),
    TrustBoundary(
        name="Rate-limit / burst / denylist",
        owning_phase=7,
        catcher_agent="swarm/agents/sec",
        catcher_module="sec.rate.v1",
        catalogue_families=["P12-7.3"],
        description="Enforce rate limits, detect credential stuffing, manage denylist."
    ),
    TrustBoundary(
        name="Predictor input → NaN/Inf",
        owning_phase=11,
        catcher_agent="model/predictor",
        catcher_module="PredictorBackendGuards",
        catalogue_families=["P12-11"],
        description="Guard predictor against NaN/Inf/pathological numeric inputs."
    ),
    TrustBoundary(
        name="Operator-console envelope",
        owning_phase=8,
        catcher_agent="xops/opsctl",
        catcher_module="OpsctlHMACValidator + AuditChain",
        catalogue_families=["P12-8"],
        description="Validate operator console API requests with HMAC + audit chain."
    ),
    TrustBoundary(
        name="Backup / restore artifact",
        owning_phase=8,
        catcher_agent="swarm/agents/maint",
        catcher_module="maint.backup.v1",
        catalogue_families=["P12-8"],
        description="Validate backup integrity and restore safety."
    ),
    TrustBoundary(
        name="Calibration / citation envelope",
        owning_phase=5,
        catcher_agent="swarm/agents/predictor",
        catcher_module="ConsensusValidator + CitationHMAC",
        catalogue_families=["P12-5"],
        description="Validate consensus calibration and citation HMAC signatures."
    ),
    TrustBoundary(
        name="Catalog / fixture lifecycle",
        owning_phase=13,
        catcher_agent="ai/common",
        catcher_module="LeagueCatalogGates",
        catalogue_families=["P12-13"],
        description="Validate league catalog mutations and fixture lifecycle."
    ),
    TrustBoundary(
        name="Emitter feed payload",
        owning_phase=16,
        catcher_agent="datasource/emitter",
        catcher_module="FeedSigner + ParityValidator",
        catalogue_families=["P12-16"],
        description="Validate emitter feed signatures and parity with source."
    ),
]


def validate_trust_boundaries() -> bool:
    """Validation rules for trust boundaries (lint helper)."""
    seen_names = set()
    seen_phases = {}
    
    for tb in TRUST_BOUNDARIES:
        # Every boundary has a unique name
        assert tb.name not in seen_names, f"Duplicate boundary: {tb.name}"
        seen_names.add(tb.name)
        
        # Phase-to-boundary is many-to-many, but each phase appears ≥ once
        if tb.owning_phase not in seen_phases:
            seen_phases[tb.owning_phase] = []
        seen_phases[tb.owning_phase].append(tb.name)
        
        # Every catalogue family starts with P12-
        for family in tb.catalogue_families:
            assert family.startswith("P12-"), f"Invalid catalogue family: {family} in {tb.name}"
    
    return True


if __name__ == "__main__":
    print("Trust boundaries registered:")
    for tb in TRUST_BOUNDARIES:
        print(f"  {tb.name} (Phase {tb.owning_phase}, {tb.catcher_agent})")
    validate_trust_boundaries()
    print("✓ All trust boundaries valid")
