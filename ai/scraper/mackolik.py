"""
Negelir — arsiv.mackolik.com JSON API Client.
Phase 1: Core data source for Turkish Süper Lig scraping.

Endpoints:
  - CompetitionHandler.aspx: season discovery (years + season IDs)
  - StandingHandler.ashx: standings, fixtures, results, odds (single request)
  - MatchHandler.aspx: per-match stats (possession, shots, corners, etc.)

All data is processed in RAM and never written to disk.
Rate limiting follows the 5s/domain policy from ScrapingEngine.
"""

import json
import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from common.config import cfg
from common.logger import get_logger

log = get_logger("scraper.mackolik")


# ── Data Models ──────────────────────────────────────────

@dataclass
class TeamStanding:
    team_id: int
    name: str
    played: int
    home_w: int
    home_d: int
    home_l: int
    away_w: int
    away_d: int
    away_l: int
    goals_for: int
    goals_against: int
    points: int
    # Extended fields from live API (home/away splits)
    home_played: int = 0
    away_played: int = 0
    home_gf: int = 0
    away_gf: int = 0
    home_ga: int = 0
    away_ga: int = 0
    home_pts: int = 0
    away_pts: int = 0
    penalty_points: int = 0


@dataclass
class Fixture:
    match_id: int
    date: str
    home_id: int
    away_id: int
    odds_home: float = 0.0
    odds_draw: float = 0.0
    odds_away: float = 0.0


@dataclass
class Result:
    match_id: int
    date: str
    home_id: int
    away_id: int
    ft_home: int
    ft_away: int
    ht_score: str = ""
    odds_home: float = 0.0
    odds_draw: float = 0.0
    odds_away: float = 0.0


@dataclass
class MatchStats:
    possession_home: float = 0.0
    possession_away: float = 0.0
    shots_home: int = 0
    shots_away: int = 0
    shots_on_target_home: int = 0
    shots_on_target_away: int = 0
    passes_home: int = 0
    passes_away: int = 0
    pass_accuracy_home: float = 0.0
    pass_accuracy_away: float = 0.0
    corners_home: int = 0
    corners_away: int = 0
    fouls_home: int = 0
    fouls_away: int = 0
    offsides_home: int = 0
    offsides_away: int = 0


@dataclass
class SeasonData:
    season_id: int
    standings: list[TeamStanding] = field(default_factory=list)
    fixtures: list[Fixture] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)
    zones: list[dict] = field(default_factory=list)


# ── Client ───────────────────────────────────────────────

class MackolikClient:
    """Client for arsiv.mackolik.com JSON API."""

    BASE = cfg.scrape_mackolik_archive
    AJAX = f"{BASE}/AjaxHandlers"
    # Backward compatibility for legacy tests/callers.
    GROUP_TURKEY = cfg.mackolik_group_id

    def __init__(
        self,
        rate_limit: float | None = None,
        group_id: int | None = None,
        league_name_filter: str | None = None,
        http_timeout: int | None = None,
    ):
        self._rate_limit = rate_limit if rate_limit is not None else cfg.scrape_rate_limit
        self.group_id = group_id if group_id is not None else cfg.mackolik_group_id
        self.league_name_filter = (
            league_name_filter if league_name_filter is not None else cfg.mackolik_league_name_filter
        )
        self._league_name_filter_norm = self._fold_turkish(self.league_name_filter)
        self._http_timeout = http_timeout if http_timeout is not None else cfg.mackolik_http_timeout
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = cfg.scrape_user_agent

    # ── Public API ───────────────────────────────────────

    def discover_seasons(self) -> dict[str, int]:
        """
        Auto-discover all available Süper Lig seasons.
        Returns: {"2025/2026": 70381, "2024/2025": 67287, ...}
        """
        # Step 1: Get year labels
        r = self._get(
            f"{self.AJAX}/CompetitionHandler.aspx",
            params={"op": "groupYears", "group": self.group_id},
        )
        if r is None:
            return {}
        years = self._parse_js_array(r.text)
        log.info(f"Discovered {len(years)} year(s)")

        # Step 2: For each year, get Süper Lig season ID
        seasons: dict[str, int] = {}
        for year in years:
            r = self._get(
                f"{self.AJAX}/CompetitionHandler.aspx",
                params={"op": "seasons", "group": self.group_id, "year": year},
            )
            if r is None:
                continue
            data = self._parse_jsonp(r.text)
            for league_id, league_name in data.get("l", []):
                if self._league_name_filter_norm in self._fold_turkish(str(league_name)):
                    seasons[year] = league_id
                    break

        log.info(f"Resolved {len(seasons)} Süper Lig season ID(s)")
        return seasons

    def fetch_season(self, season_id: int) -> SeasonData:
        """
        Fetch standings + fixtures + results + odds for a season.
        Single HTTP request returns everything.
        """
        r = self._get(
            f"{self.AJAX}/StandingHandler.ashx",
            params={"op": "standing", "id": season_id},
        )
        if r is None:
            return SeasonData(season_id=season_id)

        try:
            raw = r.json()
        except (json.JSONDecodeError, ValueError) as exc:
            log.error(f"JSON decode error for season {season_id}: {exc}")
            return SeasonData(season_id=season_id)

        return SeasonData(
            season_id=raw.get("id", season_id),
            standings=self._parse_standings(raw.get("s", [])),
            fixtures=self._parse_fixtures(raw.get("f", [])),
            results=self._parse_results(raw.get("r", [])),
            zones=self._parse_zones(raw.get("d", [])),
        )

    def fetch_match_stats(self, match_id: int) -> MatchStats | None:
        """
        Fetch per-match statistics (possession, shots, corners, etc.).
        Returns None on failure.
        """
        r = self._get(
            f"{self.AJAX}/MatchHandler.aspx",
            params={"command": "optaStats", "id": match_id},
        )
        if r is None:
            return None
        return self._parse_opta_stats_html(r.text)

    def load_training_data(self, n_seasons: int = 5) -> list[SeasonData]:
        """
        Fetch the last N seasons for model training.
        Auto-discovers season IDs; no hardcoded list.
        """
        all_seasons = self.discover_seasons()
        recent = sorted(all_seasons.items(), reverse=True)[:n_seasons]
        result = []
        for label, sid in recent:
            log.info(f"Fetching season {label} (ID {sid})...")
            data = self.fetch_season(sid)
            log.info(
                f"  {label}: {len(data.standings)} teams, "
                f"{len(data.results)} results, {len(data.fixtures)} fixtures"
            )
            result.append(data)
        return result

    # ── HTTP Layer ───────────────────────────────────────

    def _get(self, url: str, params: dict | None = None) -> requests.Response | None:
        """Rate-limited HTTP GET."""
        elapsed = time.time() - self._last_request
        if elapsed < self._rate_limit:
            wait = self._rate_limit - elapsed
            time.sleep(wait)
        self._last_request = time.time()

        try:
            resp = self._session.get(url, params=params, timeout=self._http_timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            log.warning(f"Request failed: {url} — {exc}")
            return None

    @staticmethod
    def _fold_turkish(value: str) -> str:
        """Normalize Turkish characters for robust case-insensitive matching."""
        table = str.maketrans("çğıöşü", "cgiosu")
        return value.lower().translate(table)

    # ── Parsers ──────────────────────────────────────────

    @staticmethod
    def _parse_js_array(text: str) -> list[str]:
        """
        Parse a JavaScript array response like: ['2025/2026','2024/2025',...]
        arsiv.mackolik.com returns JS array literals (not valid JSON).
        """
        # Extract quoted strings from the JS array
        return re.findall(r"'([^']+)'", text)

    @staticmethod
    def _parse_jsonp(text: str) -> dict:
        """
        Parse JSONP or plain JSON response.
        arsiv.mackolik.com sometimes wraps in callback functions.
        """
        # Try plain JSON first
        text = text.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Try extracting JSON from JSONP wrapper: callback({...})
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass

        log.warning(f"Could not parse response: {text[:200]}")
        return {}

    @staticmethod
    def _parse_standings(rows: list) -> list[TeamStanding]:
        """
        Parse standings array from StandingHandler response.
        Actual schema (20 elements per row):
          [0] team_id, [1] name,
          [2] home_played, [3] away_played,
          [4] home_w, [5] away_w, [6] home_d, [7] away_d,
          [8] home_l, [9] away_l,
          [10] home_gf, [11] away_gf, [12] home_ga, [13] away_ga,
          [14] home_pts, [15] away_pts,
          [16] zone_flag, [17] penalty_points,
          [18] str1, [19] str2
        """
        standings = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 16:
                continue
            try:
                home_played = int(row[2])
                away_played = int(row[3])
                home_w = int(row[4])
                away_w = int(row[5])
                home_d = int(row[6])
                away_d = int(row[7])
                home_l = int(row[8])
                away_l = int(row[9])
                home_gf = int(row[10])
                away_gf = int(row[11])
                home_ga = int(row[12])
                away_ga = int(row[13])
                home_pts = int(row[14])
                away_pts = int(row[15])
                penalty = int(row[17]) if len(row) > 17 and row[17] else 0

                standings.append(TeamStanding(
                    team_id=int(row[0]),
                    name=str(row[1]),
                    played=home_played + away_played,
                    home_w=home_w,
                    home_d=home_d,
                    home_l=home_l,
                    away_w=away_w,
                    away_d=away_d,
                    away_l=away_l,
                    goals_for=home_gf + away_gf,
                    goals_against=home_ga + away_ga,
                    points=home_pts + away_pts + penalty,
                    home_played=home_played,
                    away_played=away_played,
                    home_gf=home_gf,
                    away_gf=away_gf,
                    home_ga=home_ga,
                    away_ga=away_ga,
                    home_pts=home_pts,
                    away_pts=away_pts,
                    penalty_points=penalty,
                ))
            except (ValueError, IndexError) as exc:
                log.warning(f"Skipping malformed standing row: {exc}")
        return standings

    @staticmethod
    def _parse_fixtures(rows: list) -> list[Fixture]:
        """
        Parse fixtures array from StandingHandler response.
        Each row: [match_id, date, status, home_id, away_id, broadcast_id,
                    score_h, score_a, ht_score, flag, odds_h, odds_d, odds_a, ...]
        """
        fixtures = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 5:
                continue
            try:
                odds_h = float(row[10]) if len(row) > 10 and row[10] else 0.0
                odds_d = float(row[11]) if len(row) > 11 and row[11] else 0.0
                odds_a = float(row[12]) if len(row) > 12 and row[12] else 0.0
                fixtures.append(Fixture(
                    match_id=int(row[0]),
                    date=str(row[1]),
                    home_id=int(row[3]),
                    away_id=int(row[4]),
                    odds_home=odds_h,
                    odds_draw=odds_d,
                    odds_away=odds_a,
                ))
            except (ValueError, IndexError) as exc:
                log.warning(f"Skipping malformed fixture row: {exc}")
        return fixtures

    @staticmethod
    def _parse_results(rows: list) -> list[Result]:
        """
        Parse results array from StandingHandler response.
        Each row: [match_id, date, status, home_id, away_id, broadcast_id,
                    ft_h, ft_a, ht_score, flag, odds_h, odds_d, odds_a, ...]
        """
        results = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 8:
                continue
            try:
                odds_h = float(row[10]) if len(row) > 10 and row[10] else 0.0
                odds_d = float(row[11]) if len(row) > 11 and row[11] else 0.0
                odds_a = float(row[12]) if len(row) > 12 and row[12] else 0.0
                results.append(Result(
                    match_id=int(row[0]),
                    date=str(row[1]),
                    home_id=int(row[3]),
                    away_id=int(row[4]),
                    ft_home=int(row[6]),
                    ft_away=int(row[7]),
                    ht_score=str(row[8]) if len(row) > 8 else "",
                    odds_home=odds_h,
                    odds_draw=odds_d,
                    odds_away=odds_a,
                ))
            except (ValueError, IndexError) as exc:
                log.warning(f"Skipping malformed result row: {exc}")
        return results

    @staticmethod
    def _parse_zones(rows: list) -> list[dict]:
        """Parse zone decoration/legend array."""
        zones = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 3:
                continue
            zones.append({
                "id": row[0],
                "style": str(row[1]),
                "name": str(row[2]),
            })
        return zones

    @staticmethod
    def _parse_opta_stats_html(html_text: str) -> MatchStats:
        """
        Parse optaStats HTML fragment into MatchStats.
        Actual HTML structure from arsiv.mackolik.com:
          <div class="match-statistics-rows">
            <div class="team-1-statistics-text">%73</div>
            <div class="statistics-title-text">Topla Oynama</div>
            <div class="team-2-statistics-text">%27</div>
          </div>
        """
        stats = MatchStats()
        if not html_text or not html_text.strip():
            return stats

        try:
            soup = BeautifulSoup(html_text, "lxml")
        except Exception:
            return stats

        # Mapping of Turkish stat labels to (home_attr, away_attr, parser)
        _STAT_MAP = {
            "Topla Oynama": ("possession_home", "possession_away", "pct"),
            "Toplam Şut": ("shots_home", "shots_away", "int"),
            "İsabetli Şut": ("shots_on_target_home", "shots_on_target_away", "int"),
            "Başarılı Paslar": ("passes_home", "passes_away", "int"),
            "Pas Başarı": ("pass_accuracy_home", "pass_accuracy_away", "pct"),
            "Korner": ("corners_home", "corners_away", "int"),
            "Faul": ("fouls_home", "fouls_away", "int"),
            "Ofsayt": ("offsides_home", "offsides_away", "int"),
        }

        # Find all stat rows (match-statistics-rows or match-statistics-rows-2)
        for row_div in soup.find_all("div", class_=re.compile(r"match-statistics-rows")):
            title_div = row_div.find("div", class_="statistics-title-text")
            if not title_div:
                continue
            title = title_div.get_text(strip=True)

            for label, (home_attr, away_attr, parser) in _STAT_MAP.items():
                if label in title:
                    home_div = row_div.find("div", class_="team-1-statistics-text")
                    away_div = row_div.find("div", class_="team-2-statistics-text")
                    if home_div and away_div:
                        left = home_div.get_text(strip=True)
                        right = away_div.get_text(strip=True)
                        if parser == "pct":
                            setattr(stats, home_attr, _parse_pct(left))
                            setattr(stats, away_attr, _parse_pct(right))
                        else:
                            setattr(stats, home_attr, _parse_int(left))
                            setattr(stats, away_attr, _parse_int(right))
                    break

        return stats


def _parse_pct(s: str) -> float:
    """Parse '55%' → 55.0"""
    m = re.search(r"([\d.]+)", s)
    return float(m.group(1)) if m else 0.0


def _parse_int(s: str) -> int:
    """Parse '12' → 12"""
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else 0
