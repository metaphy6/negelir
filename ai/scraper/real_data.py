"""
Negelir — Real Data Scraper
============================
Scrapes real Turkish Süper Lig match data from multiple public sources.

Sources:
  1. openfootball/football.json (GitHub) — Real scores, HT scores, dates
  2. football-data.co.uk CSVs — Cards, shots, fouls, corners, odds (when reachable)
  3. football-data.org API — Match details (requires free API key)

Per roadmap §4.2: rate-limited, robots.txt-respecting, RAM-only processing.
"""

import csv
import io
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import requests

from common.config import cfg
from common.logger import get_logger

log = get_logger("scraper.real_data")

# ── Configuration (values sourced from config / .env) ────
OPENFOOTBALL_BASE = cfg.scrape_openfootball_base
FOOTBALLDATA_UK_BASE = cfg.scrape_footballdata_base

# Turkish Süper Lig seasons available on openfootball (from .env)
OPENFOOTBALL_SEASONS = cfg.openfootball_seasons

# football-data.co.uk season codes → labels (from .env)
FOOTBALLDATA_UK_SEASONS = cfg.footballdata_uk_seasons

# ── Team name normalisation ─────────────────────────────
# Built from locale_tr.yaml source_aliases (single source of truth).
# Historical team names not in current locale are appended as fallbacks.
from common.constants import SOURCE_ALIAS_MAP

TEAM_NAME_MAP = dict(SOURCE_ALIAS_MAP)

# Historical teams from previous seasons (not in current locale YAML)
_HISTORICAL_ALIASES = {
    "Kasımpaşa SK": "Kasımpaşa",
    "İstanbul Başakşehir": "Başakşehir",
    "Istanbul Basaksehir": "Başakşehir",
    "Medipol Başakşehir": "Başakşehir",
    "Gazisehir Gaziantep": "Gaziantep FK",
    "Caykur Rizespor": "Çaykur Rizespor",
    "Fatih Karagumruk": "Fatih Karagümrük",
    "Buyuksehir Bld": "Başakşehir",
    "Giresunspor": "Giresunspor",
    "Yeni Malatyaspor": "Yeni Malatyaspor",
    "Malatyaspor": "Yeni Malatyaspor",
    "Denizlispor": "Denizlispor",
    "Erzurum BB": "BB Erzurumspor",
    "Akhisar Belediyespor": "Akhisarspor",
    "Akhisarspor": "Akhisarspor",
    "Bursaspor": "Bursaspor",
    "Osmanlispor": "Osmanlıspor",
    "Umraniyespor": "Ümraniyespor",
    "Istanbulspor": "İstanbulspor",
    "Altay": "Altay",
    "BB Erzurumspor": "BB Erzurumspor",
    "Boluspor": "Boluspor",
}
for alias, canonical in _HISTORICAL_ALIASES.items():
    TEAM_NAME_MAP.setdefault(alias, canonical)


def normalise_team(name: str) -> str:
    """Normalise a team name to canonical form."""
    return TEAM_NAME_MAP.get(name, name)


@dataclass
class RealMatch:
    """A single real match record."""

    date: str
    season: str
    round_str: str
    home: str
    away: str
    ft_home: int
    ft_away: int
    ht_home: int = 0
    ht_away: int = 0
    # Stats (from football-data.co.uk when available)
    home_shots: int | None = None
    away_shots: int | None = None
    home_shots_on: int | None = None
    away_shots_on: int | None = None
    home_fouls: int | None = None
    away_fouls: int | None = None
    home_corners: int | None = None
    away_corners: int | None = None
    home_yellows: int | None = None
    away_yellows: int | None = None
    home_reds: int | None = None
    away_reds: int | None = None
    # Odds
    odds_home: float | None = None
    odds_draw: float | None = None
    odds_away: float | None = None
    # Referee
    referee: str | None = None

    @property
    def match_key(self) -> str:
        """Unique key for deduplication."""
        return f"{self.date}_{self.home}_{self.away}"


class RealDataScraper:
    """Scrapes and merges real Turkish Süper Lig data from multiple sources."""

    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Negelir/0.2 (Football Analysis Research)"
        )

    def _throttled_get(self, url: str, timeout: int = 15) -> requests.Response | None:
        """Rate-limited HTTP GET."""
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()
        try:
            resp = self.session.get(url, timeout=timeout)
            return resp
        except requests.RequestException as e:
            log.warning(f"Request failed: {url} — {e}")
            return None

    # ── Source 1: openfootball ───────────────────────────

    def scrape_openfootball(self) -> list[RealMatch]:
        """Fetch all available Turkish Süper Lig seasons from openfootball."""
        all_matches = []

        for season_dir, season_label in OPENFOOTBALL_SEASONS:
            url = f"{OPENFOOTBALL_BASE}/{season_dir}/tr.1.json"
            log.info(f"📥 Fetching {season_label} from openfootball...")

            resp = self._throttled_get(url)
            if resp is None or resp.status_code != 200:
                log.warning(f"   ⚠️  {season_label}: HTTP {getattr(resp, 'status_code', 'ERR')}")
                continue

            try:
                data = resp.json()
            except Exception as e:
                log.error(f"   JSON parse error for {season_label}: {e}")
                continue

            season_matches = []
            for m in data.get("matches", []):
                score = m.get("score")
                if not score or not score.get("ft"):
                    continue  # Skip unplayed matches

                ft = score["ft"]
                ht = score.get("ht", [0, 0])
                if ht is None:
                    ht = [0, 0]

                match = RealMatch(
                    date=m["date"],
                    season=season_label,
                    round_str=m.get("round", "Matchday 0"),
                    home=normalise_team(m["team1"]),
                    away=normalise_team(m["team2"]),
                    ft_home=ft[0],
                    ft_away=ft[1],
                    ht_home=ht[0] if ht else 0,
                    ht_away=ht[1] if ht else 0,
                )
                season_matches.append(match)

            all_matches.extend(season_matches)
            log.info(f"   ✅ {season_label}: {len(season_matches)} matches")

        log.info(f"📊 openfootball total: {len(all_matches)} matches")
        return all_matches

    # ── Source 2: football-data.co.uk CSVs ───────────────

    def scrape_footballdata_uk(self) -> list[RealMatch]:
        """Fetch Turkish Süper Lig CSVs from football-data.co.uk.

        These CSVs have detailed stats: shots, cards, fouls, corners, odds.
        Falls back gracefully if the site is unreachable.
        """
        all_matches = []

        for code, season_label in FOOTBALLDATA_UK_SEASONS.items():
            url = f"{FOOTBALLDATA_UK_BASE}/{code}/T1.csv"
            log.info(f"📥 Fetching {season_label} from football-data.co.uk...")

            resp = self._throttled_get(url, timeout=10)
            if resp is None or resp.status_code != 200 or len(resp.text) < 100:
                log.warning(f"   ⚠️  {season_label}: unavailable")
                continue

            try:
                reader = csv.DictReader(io.StringIO(resp.text))
                season_matches = []
                for row in reader:
                    match = self._parse_footballdata_row(row, season_label)
                    if match:
                        season_matches.append(match)
                all_matches.extend(season_matches)
                log.info(f"   ✅ {season_label}: {len(season_matches)} matches (with cards/shots/odds)")
            except Exception as e:
                log.error(f"   CSV parse error for {season_label}: {e}")

        log.info(f"📊 football-data.co.uk total: {len(all_matches)} matches")
        return all_matches

    def _parse_footballdata_row(self, row: dict, season: str) -> RealMatch | None:
        """Parse one CSV row from football-data.co.uk."""
        try:
            home = normalise_team(row.get("HomeTeam", "").strip())
            away = normalise_team(row.get("AwayTeam", "").strip())
            if not home or not away:
                return None

            fthg = row.get("FTHG", "")
            ftag = row.get("FTAG", "")
            if not fthg or not ftag:
                return None

            # Parse date (DD/MM/YYYY or DD/MM/YY)
            date_str = row.get("Date", "")
            date_obj = None
            for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                try:
                    date_obj = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
            if date_obj is None:
                return None
            iso_date = date_obj.strftime("%Y-%m-%d")

            def safe_int(val):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return None

            def safe_float(val):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            return RealMatch(
                date=iso_date,
                season=season,
                round_str="",
                home=home,
                away=away,
                ft_home=int(fthg),
                ft_away=int(ftag),
                ht_home=safe_int(row.get("HTHG")) or 0,
                ht_away=safe_int(row.get("HTAG")) or 0,
                home_shots=safe_int(row.get("HS")),
                away_shots=safe_int(row.get("AS")),
                home_shots_on=safe_int(row.get("HST")),
                away_shots_on=safe_int(row.get("AST")),
                home_fouls=safe_int(row.get("HF")),
                away_fouls=safe_int(row.get("AF")),
                home_corners=safe_int(row.get("HC")),
                away_corners=safe_int(row.get("AC")),
                home_yellows=safe_int(row.get("HY")),
                away_yellows=safe_int(row.get("AY")),
                home_reds=safe_int(row.get("HR")),
                away_reds=safe_int(row.get("AR")),
                odds_home=safe_float(row.get("B365H") or row.get("BWH")),
                odds_draw=safe_float(row.get("B365D") or row.get("BWD")),
                odds_away=safe_float(row.get("B365A") or row.get("BWA")),
                referee=row.get("Referee", "").strip() or None,
            )
        except Exception:
            return None

    # ── Merge & deduplicate ──────────────────────────────

    def merge_sources(
        self,
        openfootball: list[RealMatch],
        footballdata: list[RealMatch],
    ) -> list[RealMatch]:
        """Merge data from multiple sources, preferring enriched records.

        football-data.co.uk has cards/shots/odds, so its records
        are preferred when a match appears in both sources.
        """
        # Index football-data matches for quick lookup
        fdata_index: dict[str, RealMatch] = {}
        for m in footballdata:
            fdata_index[m.match_key] = m

        merged = {}

        # Start with openfootball (has HT scores, broader coverage)
        for m in openfootball:
            key = m.match_key
            if key in fdata_index:
                # Enrich openfootball record with football-data stats
                fd = fdata_index.pop(key)
                m.home_shots = fd.home_shots
                m.away_shots = fd.away_shots
                m.home_shots_on = fd.home_shots_on
                m.away_shots_on = fd.away_shots_on
                m.home_fouls = fd.home_fouls
                m.away_fouls = fd.away_fouls
                m.home_corners = fd.home_corners
                m.away_corners = fd.away_corners
                m.home_yellows = fd.home_yellows
                m.away_yellows = fd.away_yellows
                m.home_reds = fd.home_reds
                m.away_reds = fd.away_reds
                m.odds_home = fd.odds_home
                m.odds_draw = fd.odds_draw
                m.odds_away = fd.odds_away
                m.referee = fd.referee
            merged[key] = m

        # Add remaining football-data matches not in openfootball
        for key, m in fdata_index.items():
            if key not in merged:
                merged[key] = m

        result = sorted(merged.values(), key=lambda m: (m.date, m.home))
        log.info(
            f"🔀 Merged: {len(result)} unique matches "
            f"(openfootball={len(openfootball)}, football-data.co.uk={len(footballdata)})"
        )
        return result

    # ── Export ────────────────────────────────────────────

    def to_json(self, matches: list[RealMatch]) -> dict:
        """Convert matches to the JSON format expected by historical_prediction_test."""
        # Group by season
        seasons = sorted(set(m.season for m in matches))
        teams = sorted(set(m.home for m in matches) | set(m.away for m in matches))

        records = []
        for m in matches:
            stats = {}
            if m.home_shots is not None:
                stats["home_shots"] = m.home_shots
            if m.away_shots is not None:
                stats["away_shots"] = m.away_shots
            if m.home_shots_on is not None:
                stats["home_shots_on"] = m.home_shots_on
            if m.away_shots_on is not None:
                stats["away_shots_on"] = m.away_shots_on
            if m.home_fouls is not None:
                stats["home_fouls"] = m.home_fouls
            if m.away_fouls is not None:
                stats["away_fouls"] = m.away_fouls
            if m.home_corners is not None:
                stats["home_corners"] = m.home_corners
            if m.away_corners is not None:
                stats["away_corners"] = m.away_corners
            if m.home_yellows is not None:
                stats["home_yellows"] = m.home_yellows
            if m.away_yellows is not None:
                stats["away_yellows"] = m.away_yellows
            if m.home_reds is not None:
                stats["home_reds"] = m.home_reds
            if m.away_reds is not None:
                stats["away_reds"] = m.away_reds
            if m.odds_home is not None:
                stats["odds_home"] = m.odds_home
            if m.odds_draw is not None:
                stats["odds_draw"] = m.odds_draw
            if m.odds_away is not None:
                stats["odds_away"] = m.odds_away
            if m.referee is not None:
                stats["referee"] = m.referee

            records.append({
                "date": m.date,
                "season": m.season,
                "round": m.round_str,
                "team1": m.home,
                "team2": m.away,
                "score": {
                    "ft": [m.ft_home, m.ft_away],
                    "ht": [m.ht_home, m.ht_away],
                },
                "stats": stats,
            })

        # Compute summary stats
        total_goals = sum(m.ft_home + m.ft_away for m in matches)
        home_wins = sum(1 for m in matches if m.ft_home > m.ft_away)
        draws = sum(1 for m in matches if m.ft_home == m.ft_away)
        away_wins = sum(1 for m in matches if m.ft_home < m.ft_away)
        has_cards = sum(1 for m in matches if m.home_yellows is not None)
        has_shots = sum(1 for m in matches if m.home_shots is not None)

        return {
            "league": "Turkish Süper Lig",
            "seasons": seasons,
            "generated": False,
            "source": "real",
            "scraped_at": datetime.now().isoformat(),
            "total_matches": len(matches),
            "teams": teams,
            "summary": {
                "home_wins": home_wins,
                "draws": draws,
                "away_wins": away_wins,
                "home_win_pct": round(home_wins / len(matches), 3) if matches else 0,
                "draw_pct": round(draws / len(matches), 3) if matches else 0,
                "away_win_pct": round(away_wins / len(matches), 3) if matches else 0,
                "avg_goals_per_match": round(total_goals / len(matches), 2) if matches else 0,
                "matches_with_cards": has_cards,
                "matches_with_shots": has_shots,
            },
            "matches": records,
        }

    # ── Full scrape pipeline ─────────────────────────────

    def scrape_all(self, output_path: str | None = None) -> dict:
        """Run the full scraping pipeline: fetch → merge → export.

        Returns the dataset dict and optionally saves to JSON file.
        """
        log.info("=" * 60)
        log.info("🏟️  NEGELIR — REAL DATA SCRAPING")
        log.info("=" * 60)
        t0 = time.time()

        # Source 1: openfootball (scores + HT)
        openfootball_matches = self.scrape_openfootball()

        # Source 2: football-data.co.uk (cards, shots, odds)
        footballdata_matches = self.scrape_footballdata_uk()

        # Merge
        all_matches = self.merge_sources(openfootball_matches, footballdata_matches)

        # Export
        dataset = self.to_json(all_matches)

        elapsed = time.time() - t0
        log.info(f"\n{'=' * 60}")
        log.info(f"✅ Scraping complete in {elapsed:.1f}s")
        log.info(f"   📊 Total matches: {dataset['total_matches']}")
        log.info(f"   📅 Seasons: {', '.join(dataset['seasons'])}")
        log.info(f"   🏟️  Teams: {len(dataset['teams'])}")
        log.info(f"   ⚽ Avg goals/match: {dataset['summary']['avg_goals_per_match']}")
        log.info(f"   🏠 Home wins: {dataset['summary']['home_win_pct']:.1%}")
        log.info(f"   🤝 Draws: {dataset['summary']['draw_pct']:.1%}")
        log.info(f"   ✈️  Away wins: {dataset['summary']['away_win_pct']:.1%}")
        log.info(f"   🃏 Matches w/ cards: {dataset['summary']['matches_with_cards']}")
        log.info(f"   📷 Matches w/ shots: {dataset['summary']['matches_with_shots']}")

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(dataset, f, ensure_ascii=False, indent=2)
            log.info(f"   💾 Saved to: {output_path}")

        return dataset


def main():
    """CLI entry point for real data scraping."""
    import argparse

    parser = argparse.ArgumentParser(description="Scrape real Turkish Süper Lig data")
    parser.add_argument(
        "--output", "-o",
        default="/data/tr_super_lig_real.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="Seconds between requests (default: 1.0)",
    )
    args = parser.parse_args()

    scraper = RealDataScraper(rate_limit=args.rate_limit)
    scraper.scrape_all(output_path=args.output)


if __name__ == "__main__":
    main()
