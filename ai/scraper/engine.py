"""
Negelir — Scraping engine.
Per roadmap §4.2: rate-limited, robots.txt-respecting, RAM-only processing.
In PoC mode: fetches from Go middleware server to avoid quota issues.
"""

import json
import os
import time

import requests

from common.config import cfg
from common.logger import get_logger, section_banner
from scraper.parsers import parse_match_page, ParsedMatch

log = get_logger("scraper.engine")

# Load selector config
_SELECTORS_PATH = os.path.join(os.path.dirname(__file__), "selectors.json")
with open(_SELECTORS_PATH) as f:
    SELECTOR_CONFIG = json.load(f)


class ScrapingEngine:
    """
    Coordinates data fetching — either from the Go middleware server (preferred)
    or directly from sources (fallback, rate-limited).
    """

    def __init__(self):
        self.server_url = cfg.server_url
        self.rate_limit = cfg.scrape_rate_limit
        self.user_agent = cfg.scrape_user_agent
        self._last_request_time: dict[str, float] = {}

    def fetch_matches_from_server(self, league_id: str = "super_lig", season: str = "2025-2026") -> list[dict]:
        """
        Fetch match data from the Go middleware server.
        This is the preferred path — Go server caches data in PostgreSQL.
        """
        section_banner("Data Fetching: Go Server")
        url = f"{self.server_url}/api/v1/matches"
        params = {"league_id": league_id, "season": season}

        try:
            log.info(f"🌐 Connecting to Go server: {url}")
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            matches = data.get("matches", [])
            log.info(f"✅ Fetched {len(matches)} matches from Go server")
            return matches

        except requests.ConnectionError:
            log.warning("⚠️  Could not connect to Go server — server may not be running")
            return []
        except requests.Timeout:
            log.warning("⚠️  Go server timeout")
            return []
        except Exception as e:
            log.error(f"Go server error: {e}")
            return []

    def fetch_teams_from_server(self) -> list[dict]:
        """Fetch team data from Go server."""
        url = f"{self.server_url}/api/v1/teams"
        try:
            log.info(f"🌐 Fetching team data: {url}")
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            teams = data.get("teams", [])
            log.info(f"✅ {len(teams)} teams fetched")
            return teams
        except Exception as e:
            log.warning(f"Failed to fetch team data: {e}")
            return []

    def trigger_server_scrape(self) -> bool:
        """Tell the Go server to run its scraping pipeline."""
        url = f"{self.server_url}/api/v1/scrape/trigger"
        try:
            log.info("🔄 Triggering scrape on Go server...")
            resp = requests.post(url, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                log.info(f"✅ Scraping complete: {result.get('message', 'OK')}")
                return True
            else:
                log.warning(f"Scraping failed: HTTP {resp.status_code}")
                return False
        except Exception as e:
            log.warning(f"Scrape trigger error: {e}")
            return False

    def check_server_health(self) -> bool:
        """Check if the Go middleware server is healthy."""
        url = f"{self.server_url}/api/v1/health"
        try:
            resp = requests.get(url, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _respect_rate_limit(self, domain: str):
        """Per roadmap §4.2: max 1 request per 5 seconds per domain."""
        last = self._last_request_time.get(domain, 0)
        elapsed = time.time() - last
        if elapsed < self.rate_limit:
            wait = self.rate_limit - elapsed
            log.debug(f"⏱️  Rate limit: {wait:.1f}s waiting ({domain})")
            time.sleep(wait)
        self._last_request_time[domain] = time.time()
