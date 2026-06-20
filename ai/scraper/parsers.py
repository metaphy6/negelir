"""
Negelir — HTML parsers for match data extraction.
Per roadmap §4.2: parse HTML in RAM, extract stats, destroy raw data.
"""

import re
from dataclasses import dataclass, field
from bs4 import BeautifulSoup
from ai.common.logger import get_logger

log = get_logger("scraper.parsers")


@dataclass
class ParsedMatch:
    home_team: str = ""
    away_team: str = ""
    home_score: int | None = None
    away_score: int | None = None
    ht_home_score: int | None = None
    ht_away_score: int | None = None
    match_date: str = ""
    stats: dict = field(default_factory=dict)
    # Card & discipline data (v0.2)
    home_yellows: int | None = None
    away_yellows: int | None = None
    home_reds: int | None = None
    away_reds: int | None = None


def parse_match_page(html: str, selectors: dict) -> list[ParsedMatch]:
    """
    Parse match data from HTML using configured CSS selectors.
    Per roadmap §4.2: HTML is processed in RAM and never stored.
    """
    matches = []

    try:
        soup = BeautifulSoup(html, "lxml")
        match_selector = selectors.get("match_row", "")

        for sel in match_selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            rows = soup.select(sel)
            for row in rows:
                match = _extract_match_from_row(row, selectors)
                if match and match.home_team and match.away_team:
                    matches.append(match)

    except Exception as e:
        log.error(f"HTML parse error: {e}")

    # RAM-only: soup and html go out of scope and are garbage collected
    log.info(f"📄 {len(matches)} matches parsed (HTML discarded from memory)")
    return matches


def _extract_match_from_row(row, selectors: dict) -> ParsedMatch | None:
    """Extract a single match from an HTML row element."""
    match = ParsedMatch()

    try:
        # Home team
        for sel in selectors.get("home_team", "").split(","):
            el = row.select_one(sel.strip())
            if el:
                match.home_team = el.get_text(strip=True)
                break

        # Away team
        for sel in selectors.get("away_team", "").split(","):
            el = row.select_one(sel.strip())
            if el:
                match.away_team = el.get_text(strip=True)
                break

        # Score
        for sel in selectors.get("score", "").split(","):
            el = row.select_one(sel.strip())
            if el:
                score_text = el.get_text(strip=True)
                score_match = re.match(r"(\d+)\s*[-:]\s*(\d+)", score_text)
                if score_match:
                    match.home_score = int(score_match.group(1))
                    match.away_score = int(score_match.group(2))
                break

        # Date
        for sel in selectors.get("date", "").split(","):
            el = row.select_one(sel.strip())
            if el:
                match.match_date = el.get_text(strip=True)
                break

        # Stats (possession, shots, cards, etc.)
        for stat_name in ["possession", "shots_on", "shots_off", "corners", "fouls",
                          "yellow_cards", "red_cards",
                          "home_yellows", "away_yellows", "home_reds", "away_reds"]:
            for sel in selectors.get(stat_name, "").split(","):
                sel = sel.strip()
                if not sel:
                    continue
                el = row.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    nums = re.findall(r"\d+", text)
                    if nums:
                        match.stats[stat_name] = int(nums[0])
                    break

    except Exception as e:
        log.debug(f"Row parse error: {e}")
        return None

    # Map card stats to dedicated fields
    if "home_yellows" in match.stats:
        match.home_yellows = match.stats.pop("home_yellows")
    if "away_yellows" in match.stats:
        match.away_yellows = match.stats.pop("away_yellows")
    if "home_reds" in match.stats:
        match.home_reds = match.stats.pop("home_reds")
    if "away_reds" in match.stats:
        match.away_reds = match.stats.pop("away_reds")

    return match
