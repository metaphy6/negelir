"""Mackolik scraper agent (TR Süper Lig + others)."""
from __future__ import annotations

from ._base import ScraperAgentBase


class MackolikScraperAgent(ScraperAgentBase):
    source_key = "mackolik"
    real_host = "www.mackolik.com"
    mock_host = "mackolik.local"
