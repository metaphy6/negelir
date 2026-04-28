"""Phase 4.1 — scraper agents (one per source)."""
from __future__ import annotations

from ._base import ScraperAgentBase
from .mackolik import MackolikScraperAgent
from .nesine import NesineScraperAgent
from .openfootball import OpenFootballScraperAgent
from .tff import TffScraperAgent

__all__ = [
    "MackolikScraperAgent",
    "NesineScraperAgent",
    "OpenFootballScraperAgent",
    "ScraperAgentBase",
    "TffScraperAgent",
]
