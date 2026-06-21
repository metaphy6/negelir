"""openfootball scraper agent (MIT-licensed JSON datasets)."""
from __future__ import annotations

from ._base import ScraperAgentBase


class OpenFootballScraperAgent(ScraperAgentBase):
    source_key = "openfootball"
    real_host = "raw.githubusercontent.com"
    mock_host = "openfootball.local"
