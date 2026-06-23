"""
Negelir — Real feature extraction from live scraped match data.
Uses only scraped historical data for training features. League-agnostic:
the active league is selected via `cfg.default_league_id` and resolved through
`LeagueConfig` (seeded default: Turkish Süper Lig).

Sources supported:
  - MackolikClient (arsiv.mackolik.com: standings, results, fixtures, match stats)
  - RealDataScraper (openfootball + football-data.co.uk: scores, cards, shots, odds)
  - Local JSON cache under `data/<league_id>_real.json`

Feature pipeline:
  1. Scrape/load raw match data from all available sources
  2. Build per-team rolling statistics (Elo, form, goals, cards, etc.)
  3. Compute H2H features for each matchup
  4. Compute contextual features (derby, season phase, congestion)
  5. Output (X, y) DataFrames compatible with FEATURE_COLUMNS schema
"""

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from common.config import cfg

from common.constants import (
    MACKOLIK_ID_MAP,
    TEAM_STRENGTH,
    UUID_TO_NAME,
    N_FEATURES,
)
from common.logger import get_logger
from model.features import FEATURE_COLUMNS

log = get_logger("model.real_features")


# ── Elo system ───────────────────────────────────────────

class EloTracker:
    """Per-team Elo rating with home advantage."""

    def __init__(self, k: int = 32, home_advantage: float = 65.0, initial: float = 1500.0):
        self.k = k
        self.home_advantage = home_advantage
        self.initial = initial
        self._ratings: dict[str, float] = defaultdict(lambda: self.initial)

    def rating(self, team: str) -> float:
        return self._ratings[team]

    def update(self, home: str, away: str, home_goals: int, away_goals: int):
        r_h = self._ratings[home] + self.home_advantage
        r_a = self._ratings[away]
        e_h = 1.0 / (1.0 + 10.0 ** ((r_a - r_h) / 400.0))
        if home_goals > away_goals:
            s_h = 1.0
        elif home_goals == away_goals:
            s_h = 0.5
        else:
            s_h = 0.0
        goal_diff = abs(home_goals - away_goals)
        multiplier = math.log(max(goal_diff, 1) + 1)
        self._ratings[home] += self.k * multiplier * (s_h - e_h)
        self._ratings[away] += self.k * multiplier * ((1 - s_h) - (1 - e_h))


# ── Rolling stats tracker ────────────────────────────────

class TeamStats:
    """Rolling statistics for a single team."""

    def __init__(self):
        self.results: list[dict] = []  # chronological match records

    def add(self, record: dict):
        self.results.append(record)

    def _recent(self, n: int) -> list[dict]:
        return self.results[-n:] if len(self.results) >= n else self.results

    def avg_scored(self, n: int) -> float:
        recent = self._recent(n)
        return sum(r["gf"] for r in recent) / max(len(recent), 1)

    def avg_conceded(self, n: int) -> float:
        recent = self._recent(n)
        return sum(r["ga"] for r in recent) / max(len(recent), 1)

    def ppg(self, n: int) -> float:
        recent = self._recent(n)
        return sum(r["pts"] for r in recent) / max(len(recent), 1)

    def clean_sheet_pct(self, n: int) -> float:
        recent = self._recent(n)
        if not recent:
            return 0.0
        return sum(1 for r in recent if r["ga"] == 0) / len(recent)

    def win_ratio(self, n: int) -> float:
        recent = self._recent(n)
        if not recent:
            return 0.0
        return sum(1 for r in recent if r["pts"] == 3) / len(recent)

    def draw_ratio(self, n: int) -> float:
        recent = self._recent(n)
        if not recent:
            return 0.0
        return sum(1 for r in recent if r["pts"] == 1) / len(recent)

    def loss_ratio(self, n: int) -> float:
        recent = self._recent(n)
        if not recent:
            return 0.0
        return sum(1 for r in recent if r["pts"] == 0) / len(recent)

    def avg_yellows(self, n: int) -> float:
        recent = self._recent(n)
        vals = [r.get("yellows", 0) for r in recent if r.get("yellows") is not None]
        return sum(vals) / max(len(vals), 1) if vals else 2.0

    def avg_fouls(self, n: int) -> float:
        recent = self._recent(n)
        vals = [r.get("fouls", 0) for r in recent if r.get("fouls") is not None]
        return sum(vals) / max(len(vals), 1) if vals else 13.0

    def avg_ht_scored(self, n: int) -> float:
        recent = self._recent(n)
        vals = [r.get("ht_gf", 0) for r in recent if r.get("ht_gf") is not None]
        return sum(vals) / max(len(vals), 1) if vals else 0.5

    def avg_ht_conceded(self, n: int) -> float:
        recent = self._recent(n)
        vals = [r.get("ht_ga", 0) for r in recent if r.get("ht_ga") is not None]
        return sum(vals) / max(len(vals), 1) if vals else 0.5

    def scoring_consistency(self) -> float:
        recent = self._recent(10)
        goals = [r["gf"] for r in recent]
        if len(goals) < 2:
            return 0.5
        mean = sum(goals) / len(goals)
        var = sum((g - mean) ** 2 for g in goals) / len(goals)
        return 1.0 / (1.0 + math.sqrt(var))

    def venue_stats(self, is_home: bool, n: int = 10) -> tuple[float, float]:
        """Win% and PPG at home or away."""
        venue = [r for r in self.results if r.get("is_home") == is_home][-n:]
        if not venue:
            return 0.33, 1.0
        win_pct = sum(1 for r in venue if r["pts"] == 3) / len(venue)
        ppg = sum(r["pts"] for r in venue) / len(venue)
        return win_pct, ppg

    def draws_bayesian(self, prior_draws: float = 0.27, prior_n: float = 5) -> float:
        """Bayesian draw probability estimate."""
        recent = self._recent(20)
        if not recent:
            return prior_draws
        draws = sum(1 for r in recent if r["pts"] == 1)
        n = len(recent)
        return (prior_draws * prior_n + draws) / (prior_n + n)

    def goals_per_match_rate(self, n: int = 10) -> float:
        recent = self._recent(n)
        if not recent:
            return 1.35
        return sum(r["gf"] for r in recent) / len(recent)

    def sh_scoring_rate(self, n: int = 5) -> float:
        recent = self._recent(n)
        vals = [r["gf"] - r.get("ht_gf", 0) for r in recent if r.get("ht_gf") is not None]
        return sum(vals) / max(len(vals), 1) if vals else 0.5

    def sh_conceding_rate(self, n: int = 5) -> float:
        recent = self._recent(n)
        vals = [r["ga"] - r.get("ht_ga", 0) for r in recent if r.get("ht_ga") is not None]
        return sum(vals) / max(len(vals), 1) if vals else 0.5

    def last_match_date(self) -> str | None:
        if self.results:
            return self.results[-1].get("date")
        return None


# ── H2H tracker ──────────────────────────────────────────

class H2HTracker:
    """Head-to-head statistics between team pairs."""

    def __init__(self):
        self._records: dict[frozenset, list[dict]] = defaultdict(list)

    def add(self, home: str, away: str, home_goals: int, away_goals: int):
        key = frozenset([home, away])
        self._records[key].append({
            "home": home, "away": away,
            "hg": home_goals, "ag": away_goals,
        })

    def stats(self, team_a: str, team_b: str) -> dict:
        key = frozenset([team_a, team_b])
        records = self._records[key]
        if not records:
            return {
                "home_win_pct": 0.33, "draw_pct": 0.33, "avg_goals": 2.5,
                "over25_pct": 0.5, "bts_pct": 0.5, "count": 0, "avg_cards": 3.0,
            }
        n = len(records)
        home_wins = sum(1 for r in records if
                        (r["home"] == team_a and r["hg"] > r["ag"]) or
                        (r["away"] == team_a and r["ag"] > r["hg"]))
        draws = sum(1 for r in records if r["hg"] == r["ag"])
        total_goals = sum(r["hg"] + r["ag"] for r in records)
        over25 = sum(1 for r in records if r["hg"] + r["ag"] > 2.5)
        bts = sum(1 for r in records if r["hg"] > 0 and r["ag"] > 0)

        return {
            "home_win_pct": home_wins / n,
            "draw_pct": draws / n,
            "avg_goals": total_goals / n,
            "over25_pct": over25 / n,
            "bts_pct": bts / n,
            "count": n,
            "avg_cards": 3.0,  # H2H card data not tracked separately
        }


# ── Standings tracker ────────────────────────────────────

class StandingsTracker:
    """League standings built from results."""

    def __init__(self, n_teams: int = 19):
        self.n_teams = n_teams
        self._pts: dict[str, int] = defaultdict(int)
        self._gd: dict[str, int] = defaultdict(int)

    def update(self, home: str, away: str, home_goals: int, away_goals: int):
        self._gd[home] += home_goals - away_goals
        self._gd[away] += away_goals - home_goals
        if home_goals > away_goals:
            self._pts[home] += 3
        elif home_goals == away_goals:
            self._pts[home] += 1
            self._pts[away] += 1
        else:
            self._pts[away] += 3

    def position_norm(self, team: str) -> float:
        """Normalized position (0=leader, 1=last)."""
        ranked = sorted(self._pts, key=lambda t: (-self._pts[t], -self._gd[t]))
        if team not in ranked:
            return 0.5
        pos = ranked.index(team)
        return pos / max(len(ranked) - 1, 1)

    def goal_diff(self, team: str) -> int:
        return self._gd.get(team, 0)

    def pts_gap_leader(self, team: str) -> int:
        if not self._pts:
            return 0
        max_pts = max(self._pts.values())
        return max_pts - self._pts.get(team, 0)

    def pts_gap_relegation(self, team: str) -> int:
        if not self._pts:
            return 0
        ranked = sorted(self._pts.values(), reverse=True)
        relegation_line = ranked[min(self.n_teams - 4, len(ranked) - 1)] if len(ranked) > 3 else 0
        return self._pts.get(team, 0) - relegation_line

    def sos(self, team: str, elo_tracker: EloTracker) -> float:
        """Strength of schedule: average Elo of opponents faced."""
        if not self._pts or team not in self._pts:
            return 1500.0
        opponents = [t for t in self._pts if t != team]
        if not opponents:
            return 1500.0
        return sum(elo_tracker.rating(t) for t in opponents) / len(opponents)


# ── Main extraction ──────────────────────────────────────

def load_real_matches() -> list[dict]:
    """
    Load real match data from all available sources.
    Priority: Mackolik API (live) > local JSON cache > openfootball.
    Returns list of normalized match dicts.
    """
    matches = []

    # Source 1: Try Mackolik API for recent seasons
    try:
        from scraper.mackolik import MackolikClient
        client = MackolikClient(rate_limit=2)

        # Use season IDs from config (.env) to avoid slow discovery (41 seasons × 2s = 82s)
        # These are the Trendyol Süper Lig IDs from arsiv.mackolik.com
        KNOWN_SEASONS = cfg.mackolik_known_seasons

        for label, season_id in KNOWN_SEASONS.items():
            log.info(f"📥 Mackolik: Fetching {label} (ID {season_id})...")
            try:
                season_data = client.fetch_season(season_id)
                # Build team ID → name map from standings
                id_to_name = {}
                for st in season_data.standings:
                    id_to_name[st.team_id] = st.name

                for r in season_data.results:
                    home_name = id_to_name.get(r.home_id, MACKOLIK_ID_MAP.get(r.home_id, str(r.home_id)))
                    away_name = id_to_name.get(r.away_id, MACKOLIK_ID_MAP.get(r.away_id, str(r.away_id)))

                    # Parse HT score if available
                    ht_home, ht_away = 0, 0
                    if r.ht_score and "-" in r.ht_score:
                        parts = r.ht_score.split("-")
                        try:
                            ht_home, ht_away = int(parts[0].strip()), int(parts[1].strip())
                        except (ValueError, IndexError):
                            pass

                    matches.append({
                        "date": r.date,
                        "season": label,
                        "home": home_name,
                        "away": away_name,
                        "ft_home": r.ft_home,
                        "ft_away": r.ft_away,
                        "ht_home": ht_home,
                        "ht_away": ht_away,
                        "odds_home": r.odds_home if r.odds_home else None,
                        "odds_draw": r.odds_draw if r.odds_draw else None,
                        "odds_away": r.odds_away if r.odds_away else None,
                        "source": "mackolik",
                    })

                log.info(f"   ✅ {label}: {len(season_data.results)} results, {len(season_data.standings)} teams")
            except Exception as exc:
                log.warning(f"   ⚠️  {label}: {exc}")

    except ImportError:
        log.warning("MackolikClient not available, skipping")
    except Exception as exc:
        log.warning(f"Mackolik scraping failed: {exc}")

    # Source 2: local JSON cache
    league_id = cfg.default_league_id
    cache_paths = [
        os.path.join(cfg.data_dir, f"{league_id}_real.json"),
        os.path.join("data", f"{league_id}_real.json"),
    ]
    for path in cache_paths:
        if os.path.isfile(path):
            log.info(f"📥 Loading local cache: {path}")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("generated") is False:
                    for m in data.get("matches", []):
                        score = m.get("score", {})
                        ft = score.get("ft", [0, 0])
                        ht = score.get("ht", [0, 0]) or [0, 0]
                        stats = m.get("stats", {})
                        matches.append({
                            "date": m["date"],
                            "season": m.get("season", "unknown"),
                            "home": m["team1"],
                            "away": m["team2"],
                            "ft_home": ft[0],
                            "ft_away": ft[1],
                            "ht_home": ht[0] if ht else 0,
                            "ht_away": ht[1] if ht else 0,
                            "home_shots": stats.get("home_shots"),
                            "away_shots": stats.get("away_shots"),
                            "home_shots_on": stats.get("home_shots_on"),
                            "away_shots_on": stats.get("away_shots_on"),
                            "home_fouls": stats.get("home_fouls"),
                            "away_fouls": stats.get("away_fouls"),
                            "home_corners": stats.get("home_corners"),
                            "away_corners": stats.get("away_corners"),
                            "home_yellows": stats.get("home_yellows"),
                            "away_yellows": stats.get("away_yellows"),
                            "home_reds": stats.get("home_reds"),
                            "away_reds": stats.get("away_reds"),
                            "odds_home": stats.get("odds_home"),
                            "odds_draw": stats.get("odds_draw"),
                            "odds_away": stats.get("odds_away"),
                            "source": "cache",
                        })
                    log.info(f"   ✅ Cache: {len(data.get('matches', []))} matches")
            except Exception as exc:
                log.warning(f"   ⚠️  Cache load failed: {exc}")
            break

    # Source 3: openfootball (live)
    try:
        from scraper.real_data import RealDataScraper
        scraper = RealDataScraper(rate_limit=cfg.real_data_rate_limit)
        of_matches = scraper.scrape_openfootball()
        for m in of_matches:
            matches.append({
                "date": m.date,
                "season": m.season,
                "home": m.home,
                "away": m.away,
                "ft_home": m.ft_home,
                "ft_away": m.ft_away,
                "ht_home": m.ht_home,
                "ht_away": m.ht_away,
                "home_shots": m.home_shots,
                "away_shots": m.away_shots,
                "home_shots_on": m.home_shots_on,
                "away_shots_on": m.away_shots_on,
                "home_fouls": m.home_fouls,
                "away_fouls": m.away_fouls,
                "home_corners": m.home_corners,
                "away_corners": m.away_corners,
                "home_yellows": m.home_yellows,
                "away_yellows": m.away_yellows,
                "odds_home": m.odds_home,
                "odds_draw": m.odds_draw,
                "odds_away": m.odds_away,
                "source": "openfootball",
            })
        log.info(f"   ✅ openfootball: {len(of_matches)} matches")
    except Exception as exc:
        log.warning(f"openfootball scraping failed: {exc}")

    # Deduplicate by (date, home, away), preferring enriched records
    seen: dict[str, dict] = {}
    for m in matches:
        key = f"{m['date']}_{m['home']}_{m['away']}"
        existing = seen.get(key)
        if existing is None:
            seen[key] = m
        elif m.get("home_shots") and not existing.get("home_shots"):
            # Prefer record with stats
            seen[key] = m

    deduped = sorted(seen.values(), key=lambda m: m["date"])
    log.info(f"📊 Total real matches loaded: {len(deduped)} (deduped from {len(matches)})")
    return deduped


def _parse_date(date_str: str) -> datetime:
    """Parse date string to datetime."""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime(2020, 1, 1)  # fallback


def _is_derby(home: str, away: str) -> bool:
    """Check if this matchup is a derby (delegates to LeagueConfig)."""
    from common.league_config import turkish_super_lig
    return turkish_super_lig().is_derby(home, away)


def extract_real_dataset(
    min_history: int = 5,
    matches: list[dict] | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build a real training dataset from live-scraped match data.
    Each match becomes one training row with 130 features + 1 label.

    Only matches with at least `min_history` prior games per team are used,
    ensuring rolling features are meaningful.

    Returns:
        (X, y) where X is a DataFrame with FEATURE_COLUMNS, y is 0/1/2 class labels
    """
    if matches is None:
        matches = load_real_matches()
    if not matches:
        league_id = cfg.default_league_id
        raise RuntimeError(
            f"No real matches available for league '{league_id}'. "
            f"Run `make scrape --league {league_id}` first "
            f"(or `make bootstrap LEAGUE={league_id}`)."
        )

    log.info(f"🔧 Extracting features from {len(matches)} real matches...")

    # Initialize trackers
    elo = EloTracker()
    team_stats: dict[str, TeamStats] = defaultdict(TeamStats)
    h2h = H2HTracker()
    standings = StandingsTracker()

    rows = []
    labels = []

    for i, match in enumerate(matches):
        home = match["home"]
        away = match["away"]
        ft_home = match["ft_home"]
        ft_away = match["ft_away"]
        date = _parse_date(match["date"])

        home_stats = team_stats[home]
        away_stats = team_stats[away]

        # Only extract features if both teams have enough history
        if len(home_stats.results) >= min_history and len(away_stats.results) >= min_history:
            feature_vec = _build_feature_vector(
                home, away, date, match, elo, home_stats, away_stats, h2h, standings, i, len(matches)
            )
            rows.append(feature_vec)

            # Label: 0=home win, 1=draw, 2=away win
            if ft_home > ft_away:
                labels.append(0)
            elif ft_home == ft_away:
                labels.append(1)
            else:
                labels.append(2)

        # Update all trackers AFTER feature extraction (no look-ahead bias)
        elo.update(home, away, ft_home, ft_away)
        h2h.add(home, away, ft_home, ft_away)
        standings.update(home, away, ft_home, ft_away)

        # Compute points
        if ft_home > ft_away:
            h_pts, a_pts = 3, 0
        elif ft_home == ft_away:
            h_pts, a_pts = 1, 1
        else:
            h_pts, a_pts = 0, 3

        home_stats.add({
            "date": match["date"],
            "gf": ft_home, "ga": ft_away,
            "ht_gf": match.get("ht_home"), "ht_ga": match.get("ht_away"),
            "pts": h_pts, "is_home": True,
            "yellows": match.get("home_yellows"),
            "fouls": match.get("home_fouls"),
        })
        away_stats.add({
            "date": match["date"],
            "gf": ft_away, "ga": ft_home,
            "ht_gf": match.get("ht_away"), "ht_ga": match.get("ht_home"),
            "pts": a_pts, "is_home": False,
            "yellows": match.get("away_yellows"),
            "fouls": match.get("away_fouls"),
        })

    if not rows:
        league_id = cfg.default_league_id
        raise RuntimeError(
            f"No matches with sufficient history for league '{league_id}' "
            f"(min_history={min_history}, raw_matches={len(matches)}). "
            f"Run `make bootstrap LEAGUE={league_id}` to collect more data "
            "or lower NEGELIR_MIN_HISTORY."
        )

    # Pre-Phase-6 audit round-3 P2: surface silent dropout. Most matches
    # at the start of a season fail the `min_history` gate; if the ratio
    # is high the trainer is effectively training on the league's tail
    # only, and §6.3 backtest baselines will be skewed.
    dropped = len(matches) - len(rows)
    if dropped:
        ratio = dropped / max(len(matches), 1)
        msg = (
            f"min_history={min_history} dropped {dropped}/{len(matches)} "
            f"matches ({ratio:.1%}) before feature extraction"
        )
        if ratio > 0.30:
            log.warning("⚠️  " + msg)
        else:
            log.info(msg)

    X = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    y = pd.Series(labels, name="result_class")

    dist = y.value_counts(normalize=True).sort_index()
    log.info(f"📊 Real dataset: {len(X)} matches, {N_FEATURES} features, "
             f"H={dist.get(0, 0):.2f} D={dist.get(1, 0):.2f} A={dist.get(2, 0):.2f}")
    return X, y


def _build_feature_vector(
    home: str, away: str, date: datetime, match: dict,
    elo: EloTracker, home_stats: TeamStats, away_stats: TeamStats,
    h2h: H2HTracker, standings: StandingsTracker,
    match_idx: int, total_matches: int,
) -> list[float]:
    """Build a single 157-element feature vector for a match (base + QID + enrichment)."""

    helo = elo.rating(home)
    aelo = elo.rating(away)
    h2h_data = h2h.stats(home, away)

    # Team strength from locale (attack, defense multipliers)
    h_strength = TEAM_STRENGTH.get(home, (1.0, 1.0))
    a_strength = TEAM_STRENGTH.get(away, (1.0, 1.0))

    # xG approximation from Elo + strength
    home_xg = 1.35 * h_strength[0] / max(a_strength[1], 0.5) * (1 + (helo - 1500) / 2000)
    away_xg = 1.35 * a_strength[0] / max(h_strength[1], 0.5) * (1 + (aelo - 1500) / 2000)

    # Form index: weighted PPG
    home_form = 0.5 * home_stats.ppg(5) / 3.0 + 0.3 * home_stats.win_ratio(5) + 0.2 * (1 - home_stats.loss_ratio(5))
    away_form = 0.5 * away_stats.ppg(5) / 3.0 + 0.3 * away_stats.win_ratio(5) + 0.2 * (1 - away_stats.loss_ratio(5))

    # Venue stats
    h_venue_win, h_venue_ppg = home_stats.venue_stats(is_home=True)
    a_venue_win, a_venue_ppg = away_stats.venue_stats(is_home=False)

    # Derby flag
    derby = 1.0 if _is_derby(home, away) else 0.0

    # Season phase (0=early, 1=mid, 2=late, 3=final)
    season_progress = match_idx / max(total_matches - 1, 1)
    if season_progress < 0.25:
        season_phase = 0
    elif season_progress < 0.5:
        season_phase = 1
    elif season_progress < 0.75:
        season_phase = 2
    else:
        season_phase = 3

    # Match week (approximate)
    match_week_norm = season_progress

    # Temporal features
    day_of_year = date.timetuple().tm_yday
    day_sin = math.sin(2 * math.pi * day_of_year / 365)
    day_cos = math.cos(2 * math.pi * day_of_year / 365)
    month_sin = math.sin(2 * math.pi * date.month / 12)
    month_cos = math.cos(2 * math.pi * date.month / 12)

    # Rest days
    h_last = home_stats.last_match_date()
    a_last = away_stats.last_match_date()
    h_rest = (_parse_date(match["date"]) - _parse_date(h_last)).days if h_last else 7
    a_rest = (_parse_date(match["date"]) - _parse_date(a_last)).days if a_last else 7
    h_rest = min(max(h_rest, 1), 30)
    a_rest = min(max(a_rest, 1), 30)

    # Momentum (trend in last 5 games)
    h_recent3 = home_stats.ppg(3)
    h_recent5 = home_stats.ppg(5)
    h_momentum = h_recent3 - h_recent5
    a_recent3 = away_stats.ppg(3)
    a_recent5 = away_stats.ppg(5)
    a_momentum = a_recent3 - a_recent5

    # Low scoring likelihood
    avg_total = home_stats.avg_scored(10) + away_stats.avg_scored(10)
    low_scoring = 1.0 / (1.0 + math.exp(avg_total - 2.0))

    # Fixture congestion (approximate from rest days)
    h_congestion_7 = 1 if h_rest <= 4 else 0
    a_congestion_7 = 1 if a_rest <= 4 else 0
    h_congestion_14 = 2 if h_rest <= 3 else (1 if h_rest <= 5 else 0)
    a_congestion_14 = 2 if a_rest <= 3 else (1 if a_rest <= 5 else 0)

    # Style matchup: contrast of attack vs defense
    style_matchup = abs(h_strength[0] - a_strength[1]) + abs(a_strength[0] - h_strength[1])

    # Surprise index: recent results vs expected (Elo-based)
    h_expected = 1.0 / (1.0 + 10 ** ((1500 - helo) / 400))
    a_expected = 1.0 / (1.0 + 10 ** ((1500 - aelo) / 400))
    h_surprise = abs(home_stats.win_ratio(5) - h_expected)
    a_surprise = abs(away_stats.win_ratio(5) - a_expected)

    # Card factor for derbies
    derby_card_factor = 1.3 if derby else 1.0

    vec = [
        # Team form (rolling windows)
        home_stats.avg_scored(3), home_stats.avg_scored(5), home_stats.avg_scored(10),
        home_stats.avg_conceded(3), home_stats.avg_conceded(5), home_stats.avg_conceded(10),
        home_stats.ppg(5), home_stats.ppg(10), home_stats.clean_sheet_pct(10),
        home_stats.win_ratio(5), home_stats.draw_ratio(5), home_stats.loss_ratio(5),
        away_stats.avg_scored(3), away_stats.avg_scored(5), away_stats.avg_scored(10),
        away_stats.avg_conceded(3), away_stats.avg_conceded(5), away_stats.avg_conceded(10),
        away_stats.ppg(5), away_stats.ppg(10), away_stats.clean_sheet_pct(10),
        away_stats.win_ratio(5), away_stats.draw_ratio(5), away_stats.loss_ratio(5),
        # Elo & derived
        helo, aelo, helo - aelo,
        home_xg, away_xg, home_xg - away_xg,
        home_form, away_form, home_form - away_form,
        # H2H
        h2h_data["home_win_pct"], h2h_data["draw_pct"], h2h_data["avg_goals"],
        h2h_data["over25_pct"], h2h_data["bts_pct"], h2h_data["count"],
        # League position
        standings.position_norm(home), standings.position_norm(away),
        standings.position_norm(home) - standings.position_norm(away),
        standings.goal_diff(home), standings.goal_diff(away),
        standings.pts_gap_leader(home), standings.pts_gap_leader(away),
        standings.pts_gap_relegation(home), standings.pts_gap_relegation(away),
        # Squad & tactical (defaults — need roster data for real values)
        0.7, 0.7,  # formation_stability (home, away)
        0.5, 0.5,  # squad_rotation_gini (home, away)
        0.3, 0.3,  # goal_concentration (home, away)
        26.0, 26.0,  # avg_age (home, away) — default, needs roster
        # Contextual
        h_congestion_7, a_congestion_7,
        h_congestion_14, a_congestion_14,
        10.0, 10.0,  # manager_tenure — default
        0.0, 0.0,  # manager_change — default
        derby, season_phase,
        match_week_norm,
        # Temporal
        day_sin, day_cos, month_sin, month_cos,
        h_rest, a_rest, h_rest - a_rest,
        # Sentiment (default neutral — needs NLP scraping)
        0.0, 0.0,  # media_sentiment
        0.0, 0.0,  # fan_optimism
        0.0,  # media_consensus_strength
        # Derived
        style_matchup,
        h_rest - a_rest,  # fatigue_diff
        h_momentum, a_momentum,
        home_stats.scoring_consistency(), away_stats.scoring_consistency(),
        h_surprise, a_surprise,
        # Weather / venue (defaults)
        2.0, 0.0, 1.0,  # temperature_bucket, precipitation_flag, wind_category
        0.0,  # venue_type (0=neutral)
        # Card & discipline (v0.2)
        home_stats.avg_yellows(5), away_stats.avg_yellows(5),
        home_stats.avg_yellows(10), away_stats.avg_yellows(10),
        home_stats.avg_fouls(5), away_stats.avg_fouls(5),
        h2h_data["avg_cards"],
        derby_card_factor,
        # Half-time / second-half splits (v0.2)
        home_stats.avg_ht_scored(5), away_stats.avg_ht_scored(5),
        home_stats.sh_scoring_rate(5), away_stats.sh_scoring_rate(5),
        home_stats.avg_ht_conceded(5), away_stats.avg_ht_conceded(5),
        # Venue-specific performance (v0.2)
        h_venue_win, a_venue_win,
        h_venue_ppg, a_venue_ppg,
        # Draw & low-scoring tendencies (v0.2)
        home_stats.draws_bayesian(), away_stats.draws_bayesian(),
        low_scoring,
        # Strength of schedule (v0.2)
        standings.sos(home, elo), standings.sos(away, elo),
        # Second-half detail (v0.2)
        home_stats.sh_scoring_rate(5), away_stats.sh_scoring_rate(5),
        home_stats.sh_conceding_rate(5), away_stats.sh_conceding_rate(5),
        # Scoring patterns (v0.2)
        home_stats.goals_per_match_rate(), away_stats.goals_per_match_rate(),
        # QID features (v0.3) — zeroed, populated at inference time from swarm
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        # ── Enrichment Plane 6: Roster-state (Phase 21) ──
        # (zeroed during training; populated by swarm roster reactor at inference)
        0.0,  # squad_strength_delta
        0.0,  # cohesion_penalty
        0.0,  # departure_shock
        # ── Enrichment Plane 7: Health (Phase 21) ──
        0.0,  # squad_availability_score
        0.0,  # doubtful_ratio
        0.0,  # key_player_out_flag
        # ── Enrichment Plane 8: Officials (Phase 21) ──
        0.0,  # referee_yellows_per_match
        0.0,  # referee_reds_per_match
        0.0,  # referee_penalties_per_match
        0.0,  # referee_home_win_pct_adj
        # ── Enrichment Plane 9: Environment (Phase 21) ──
        1.0,  # wind_xg_factor (default: no wind penalty)
        1.0,  # rain_xg_factor (default: no rain penalty)
        0.0,  # surface_style_penalty
        1.0,  # pitch_condition_score (default: pristine)
        # ── Enrichment Derived View: Market-movement (Phase 21.5) ──
        0.0,  # drift_1x2_home_pct
        0.0,  # drift_1x2_draw_pct
        0.0,  # drift_1x2_away_pct
        0.0,  # drift_total_pct
        0.0,  # implied_prob_shift_max
        0.0,  # high_drift_flag
        # ── Enrichment Derived View: Fixture-congestion refined (Phase 21.5) ──
        0.0,  # home_travel_km_7d
        0.0,  # away_travel_km_7d
        0.0,  # congestion_diff_7d
        0.0,  # is_post_international_break
        # ── Enrichment Derived View: Card-context (Phase 21.5) ──
        0.0,  # combined_card_score
        0.0,  # referee_cards_per_match_smoothed
        # ── Enrichment Derived View: Narrative-pressure (Phase 21.5) ──
        0.0,  # narrative_score
    ]

    assert len(vec) == N_FEATURES, f"Feature vector length {len(vec)} != {N_FEATURES}"
    return vec
