"""Nesine scraper agent (TR bulletin / odds)."""
from __future__ import annotations

from ._base import ScraperAgentBase


class NesineScraperAgent(ScraperAgentBase):
    source_key = "nesine"
    real_host = "www.nesine.com"
    mock_host = "nesine.local"
