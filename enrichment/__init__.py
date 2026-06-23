"""Negelir — Phase 21 enrichment planes and reactors.

Pivot v3 component: enrichment (moved from ai/datasource/enrichment/ in Phase 22.4).

Phase 21 implements 10 enrichment planes (roster-state, health, form, opponent,
venture, environment, market, narrative, external, institutional) that overlay
on the five-plane base data pipeline with supplemental context.

Public API: enrichment plane management, reactor orchestration, data overlay.
"""

__all__ = [
    "EnrichmentReactor",
    "EnrichmentPlanes",
    "ReactorWatchdog",
    "T3ResourceManager",
]
