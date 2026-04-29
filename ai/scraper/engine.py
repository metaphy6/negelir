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
    Sources are configured via environment variables (SCRAPE_SOURCE_1 through SCRAPE_SOURCE_5,
    SCRAPE_SOURCE_FALLBACK, SCRAPE_SOURCE_EXTRA).
    """

    def __init__(self):
        self.server_url = cfg.server_url
        self.rate_limit = cfg.scrape_rate_limit
        self.user_agent = cfg.scrape_user_agent
        self.sources = cfg.scrape_sources
        self._last_request_time: dict[str, float] = {}

        # Log active sources on init
        log.info(f"📡 Configured {len(self.sources)} data source(s):")
        for src in self.sources:
            log.info(f"   🔗 {src['label']}: {src['url']}")

    def fetch_matches_from_server(self, league_id: str | None = None, season: str | None = None) -> list[dict]:
        """
        Fetch match data from the Go middleware server.
        This is the preferred path — Go server caches data in PostgreSQL.
        """
        section_banner("Data Fetching: Go Server")
        resolved_league_id = league_id or cfg.default_league_id
        resolved_season = season or cfg.default_season
        url = f"{self.server_url}/api/v1/matches"
        params = {"league_id": resolved_league_id, "season": resolved_season}

        try:
            log.info(f"🌐 Connecting to Go server: {url}")
            resp = requests.get(url, params=params, timeout=cfg.server_fetch_timeout)
            resp.raise_for_status()
            data = resp.json()

            matches = data.get("matches", [])
            log.info(f"✅ Fetched {len(matches)} matches from Go server")
            return matches

        except requests.ConnectionError:
            # Expected when the Go server is down; pipeline falls back
            # to direct scrape. Logged at warning so ops can spot
            # extended outages but it does not bury the run.
            log.warning("⚠️  Could not connect to Go server — server may not be running")
            return []
        except requests.Timeout:
            log.warning("⚠️  Go server timeout")
            return []
        except requests.HTTPError as exc:
            # 4xx/5xx from the server — distinct from "unreachable".
            log.error(
                "Go server returned HTTP error",
                extra={"status": exc.response.status_code if exc.response else None,
                       "url": url},
            )
            return []
        except Exception:  # pragma: no cover — defensive
            # Pre-Phase-6 audit S1: surface unexpected failures with a
            # stack trace instead of a single-line warning. The
            # pipeline keeps falling back (returning []) so a transient
            # bug does not stall the run, but the trace is preserved
            # for triage.
            log.exception("Unexpected error fetching matches from Go server")
            return []

    def trigger_server_scrape(self) -> bool:
        """Tell the Go server to run its scraping pipeline."""
        url = f"{self.server_url}/api/v1/scrape/trigger"
        try:
            log.info("🔄 Triggering scrape on Go server...")
            resp = requests.post(url, timeout=cfg.scrape_trigger_timeout)
            if resp.status_code == 200:
                result = resp.json()
                log.info(f"✅ Scraping complete: {result.get('message', 'OK')}")
                return True
            else:
                log.warning(f"Scraping failed: HTTP {resp.status_code}")
                return False
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning(f"Scrape trigger network error: {exc}")
            return False
        except Exception:  # pragma: no cover — defensive
            # Pre-Phase-6 audit S1: log full trace for unexpected
            # failures so a regression in the trigger contract is
            # diagnosable from a single failed run.
            log.exception("Unexpected error triggering server scrape")
            return False

    def check_server_health(self) -> bool:
        """Check if the Go middleware server is healthy."""
        url = f"{self.server_url}/api/v1/health"
        try:
            resp = requests.get(url, timeout=cfg.health_check_timeout)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False
        except Exception:  # pragma: no cover — defensive
            log.exception("Unexpected error during Go server health check")
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
