"""TFF (Türkiye Futbol Federasyonu) scraper agent."""
from __future__ import annotations

from ._base import ScraperAgentBase


class TffScraperAgent(ScraperAgentBase):
    source_key = "tff"
    real_host = "www.tff.org"
    mock_host = "tff.local"
