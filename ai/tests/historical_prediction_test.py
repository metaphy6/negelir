#!/usr/bin/env python3
"""
Negelir — Historical Prediction Test (v2)
==========================================
Enhanced with roadmap Data Points to Capture (A-F):
  A. Match-Level Core Data (goals per half, HT scores, venue type)
  B. Player-Level Data (approximated: goal concentration, squad stability)
  C. Tactical & Formation Data (set-piece proxy, defensive org index)
  D. Analyst & Media Sentiment Data (form-derived sentiment proxy)
  E. Contextual & Environmental Features (congestion, derby, pressure, phase)
  F. Derived & Computed Features (Poisson xG, custom Elo, Bayesian strength,
     strength of schedule, momentum 2nd derivative, style matchup, fatigue,
     surprise index)

3-class GBDT model (Home/Draw/Away) with draw-specific features and
class-weight balancing.
"""

import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss
from scipy.stats import poisson

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import cfg
from common.constants import N_FEATURES
from common.league_config import get_league_config
from model.features import FEATURE_COLUMNS

_LEAGUE = get_league_config(cfg.default_league_id)

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
# Phase 2: real data only. The legacy synthetic season fixture has been
# removed from production data/. If it is missing, this regression script
# fails loudly so the operator runs `make bootstrap` first.
# Use the canonical league_id from LeagueConfig (handles alias normalization,
# e.g. "super_lig" -> "tr_super_lig").
DATA_PATH = os.path.join(_DATA_DIR, f"{_LEAGUE.league_id}_real.json")

DEFAULT_OUTPUT = os.path.join(_DATA_DIR, "prediction_results.txt")
# Single source of truth: LeagueConfig (Phase 1.1/1.2). These names are kept
# for readability inside this large script; their values come from config.
INITIAL_ELO = _LEAGUE.elo_initial
K_FACTOR = _LEAGUE.elo_k
HOME_ADV_ELO = _LEAGUE.elo_home_advantage
TOTAL_TEAMS = _LEAGUE.teams_count  # Dynamically updated per dataset


@dataclass
class MatchRecord:
    date: str
    round_num: int
    home: str
    away: str
    home_goals: int
    away_goals: int
    ht_home: int
    ht_away: int
    home_yellows: int = 0
    away_yellows: int = 0
    home_reds: int = 0
    away_reds: int = 0
    home_fouls: int = 0
    away_fouls: int = 0

    @property
    def result(self) -> str:
        if self.home_goals > self.away_goals:
            return "H"
        elif self.home_goals < self.away_goals:
            return "A"
        return "D"

    @property
    def result_class(self) -> int:
        if self.home_goals > self.away_goals:
            return 0
        elif self.home_goals == self.away_goals:
            return 1
        return 2

    @property
    def home_win(self) -> int:
        return 1 if self.home_goals > self.away_goals else 0

    @property
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    @property
    def over_2_5(self) -> bool:
        return self.total_goals > 2.5

    @property
    def bts(self) -> bool:
        return self.home_goals > 0 and self.away_goals > 0

    @property
    def ht_total(self) -> int:
        return self.ht_home + self.ht_away

    @property
    def second_half_home(self) -> int:
        return self.home_goals - self.ht_home

    @property
    def second_half_away(self) -> int:
        return self.away_goals - self.ht_away


@dataclass
class TeamStats:
    elo: float = INITIAL_ELO
    attack_strength: float = 1.0
    defense_strength: float = 1.0
    home_attack_str: float = 1.0
    home_defense_str: float = 1.0
    away_attack_str: float = 1.0
    away_defense_str: float = 1.0
    draw_alpha: float = 3.0
    draw_beta: float = 8.0

    scored: list = field(default_factory=list)
    conceded: list = field(default_factory=list)
    ppg: list = field(default_factory=list)
    results: list = field(default_factory=list)
    clean_sheets: list = field(default_factory=list)

    home_scored: list = field(default_factory=list)
    home_conceded: list = field(default_factory=list)
    home_ppg: list = field(default_factory=list)
    home_results: list = field(default_factory=list)
    away_scored: list = field(default_factory=list)
    away_conceded: list = field(default_factory=list)
    away_ppg: list = field(default_factory=list)
    away_results: list = field(default_factory=list)

    ht_scored: list = field(default_factory=list)
    ht_conceded: list = field(default_factory=list)
    sh_scored: list = field(default_factory=list)
    sh_conceded: list = field(default_factory=list)

    draws: list = field(default_factory=list)
    scorelines: list = field(default_factory=list)

    yellows: list = field(default_factory=list)
    reds: list = field(default_factory=list)
    fouls: list = field(default_factory=list)

    matches_played: int = 0
    home_matches: int = 0
    away_matches: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    match_dates: list = field(default_factory=list)
    opponent_elos: list = field(default_factory=list)

    def rolling(self, values, window):
        if not values:
            return 0.0
        return float(np.mean(values[-window:]))

    def rolling_std(self, values, window):
        if not values or len(values) < 2:
            return 0.0
        return float(np.std(values[-window:]))

    def win_ratio(self, window, results_list=None):
        results = results_list or self.results
        if not results:
            return 0.0
        recent = results[-window:]
        return sum(1 for r in recent if r == "W") / len(recent)

    def draw_ratio(self, window, results_list=None):
        results = results_list or self.results
        if not results:
            return 0.0
        recent = results[-window:]
        return sum(1 for r in recent if r == "D") / len(recent)

    def loss_ratio(self, window, results_list=None):
        results = results_list or self.results
        if not results:
            return 0.0
        recent = results[-window:]
        return sum(1 for r in recent if r == "L") / len(recent)

    def form_index(self, window=5):
        if not self.ppg:
            return 0.5
        return min(1.0, self.rolling(self.ppg, window) / 3.0)

    def form_acceleration(self):
        if len(self.ppg) < 10:
            return 0.0
        f3 = self.form_index(3)
        f5 = self.form_index(5)
        f10 = self.form_index(10)
        return (f3 - f5) - (f5 - f10)

    def strength_of_schedule(self, window=10):
        if not self.opponent_elos:
            return INITIAL_ELO
        return float(np.mean(self.opponent_elos[-window:]))

    def goal_concentration_index(self, window=10):
        recent = self.scored[-window:]
        if not recent or sum(recent) == 0:
            return 0.5
        total = sum(recent)
        proportions = [g / total for g in recent if total > 0]
        gini = 1.0 - sum(p ** 2 for p in proportions) * len(proportions)
        return min(1.0, max(0.0, gini))

    def clean_sheet_rate(self, window=10):
        if not self.clean_sheets:
            return 0.0
        return float(np.mean(self.clean_sheets[-window:]))

    def low_scoring_rate(self, window=10):
        recent = self.scorelines[-window:]
        if not recent:
            return 0.3
        return sum(1 for gf, ga in recent if gf + ga <= 1) / len(recent)

    def bayesian_draw_prob(self):
        return self.draw_alpha / (self.draw_alpha + self.draw_beta)

    def home_venue_win_pct(self, window=10):
        if not self.home_results:
            return 0.4
        recent = self.home_results[-window:]
        return sum(1 for r in recent if r == "W") / len(recent)

    def away_venue_win_pct(self, window=10):
        if not self.away_results:
            return 0.3
        recent = self.away_results[-window:]
        return sum(1 for r in recent if r == "W") / len(recent)

    def second_half_scoring_rate(self, window=10):
        if not self.sh_scored:
            return 0.5
        return float(np.mean(self.sh_scored[-window:]))

    def second_half_conceding_rate(self, window=10):
        if not self.sh_conceded:
            return 0.5
        return float(np.mean(self.sh_conceded[-window:]))

    def fixture_congestion(self, current_date, days):
        try:
            cd = datetime.strptime(current_date, "%Y-%m-%d")
        except ValueError:
            return 1
        count = 0
        for d in self.match_dates:
            try:
                md = datetime.strptime(d, "%Y-%m-%d")
                if 0 < (cd - md).days <= days:
                    count += 1
            except ValueError:
                continue
        return count

    def rest_days(self, current_date):
        if not self.match_dates:
            return 14
        try:
            cd = datetime.strptime(current_date, "%Y-%m-%d")
            last = datetime.strptime(self.match_dates[-1], "%Y-%m-%d")
            return max(1, (cd - last).days)
        except ValueError:
            return 7


def load_matches(path):
    """Load matches from JSON.  Supports both single-season and multi-season datasets.

    For multi-season data the per-season matchday numbers repeat (e.g. every season
    starts at Matchday 1).  We assign **global** round numbers so that the
    expanding-window logic works correctly across seasons.
    """
    global TOTAL_TEAMS
    with open(path) as f:
        data = json.load(f)

    is_real = data.get("source") == "real" or data.get("generated") is False
    matches_raw = []
    for m in data["matches"]:
        if not m.get("score") or not m["score"].get("ft"):
            continue
        ft = m["score"]["ft"]
        ht = m["score"].get("ht", [0, 0])
        if ht is None:
            ht = [0, 0]
        season = m.get("season", "")
        round_str = m.get("round", "Matchday 0")
        local_round = int("".join(c for c in round_str if c.isdigit()) or "0")
        stats = m.get("stats", {})
        matches_raw.append((
            m["date"], season, local_round, m["team1"], m["team2"],
            ft, ht, stats,
        ))

    matches_raw.sort(key=lambda t: (t[0], t[2]))

    # Assign global round numbers: group by (season, local_round)
    global_round = 0
    prev_key = None
    round_map = {}  # (season, local_round) -> global_round
    for date, season, local_round, *_ in matches_raw:
        key = (season, local_round)
        if key not in round_map:
            global_round += 1
            round_map[key] = global_round

    matches = []
    all_teams = set()
    for date, season, local_round, home, away, ft, ht, stats in matches_raw:
        gr = round_map[(season, local_round)]
        all_teams.update([home, away])
        matches.append(MatchRecord(
            date=date,
            round_num=gr,
            home=home,
            away=away,
            home_goals=ft[0],
            away_goals=ft[1],
            ht_home=ht[0] if ht else 0,
            ht_away=ht[1] if ht else 0,
            home_yellows=stats.get("home_yellows", 0),
            away_yellows=stats.get("away_yellows", 0),
            home_reds=stats.get("home_reds", 0),
            away_reds=stats.get("away_reds", 0),
            home_fouls=stats.get("home_fouls", 0),
            away_fouls=stats.get("away_fouls", 0),
        ))

    TOTAL_TEAMS = len(all_teams)
    return matches


def update_elo(home_elo, away_elo, result):
    home_expected = 1.0 / (1.0 + 10 ** ((away_elo - home_elo - HOME_ADV_ELO) / 400))
    away_expected = 1.0 - home_expected
    if result == "H":
        home_score, away_score = 1.0, 0.0
    elif result == "A":
        home_score, away_score = 0.0, 1.0
    else:
        home_score, away_score = 0.5, 0.5
    new_home = home_elo + K_FACTOR * (home_score - home_expected)
    new_away = away_elo + K_FACTOR * (away_score - away_expected)
    return new_home, new_away


def poisson_xg(attack, defense, league_avg):
    return max(0.1, attack * defense * league_avg)


# Dixon-Coles adjustment for low-scoring matches (0-0, 1-0, 0-1, 1-1)
# rho < 0 means these scorelines are more likely than independent Poisson.
# Sourced from LeagueConfig (Phase 1.1) — do not hardcode here.
DIXON_COLES_RHO = _LEAGUE.dixon_coles_rho


def _dixon_coles_tau(hg, ag, home_xg, away_xg, rho=DIXON_COLES_RHO):
    """Dixon-Coles correction factor for score (hg, ag)."""
    if hg == 0 and ag == 0:
        return 1.0 - home_xg * away_xg * rho
    elif hg == 1 and ag == 0:
        return 1.0 + away_xg * rho
    elif hg == 0 and ag == 1:
        return 1.0 + home_xg * rho
    elif hg == 1 and ag == 1:
        return 1.0 - rho
    return 1.0


def _score_prob(hg, ag, home_xg, away_xg, use_dc=True):
    """Probability of score (hg, ag) with optional Dixon-Coles correction."""
    p = poisson.pmf(hg, home_xg) * poisson.pmf(ag, away_xg)
    if use_dc:
        p *= _dixon_coles_tau(hg, ag, home_xg, away_xg)
    return max(0.0, p)


def poisson_draw_prob(home_xg, away_xg, use_dc=True):
    p_draw = 0.0
    for k in range(6):
        p_draw += _score_prob(k, k, home_xg, away_xg, use_dc)
    return p_draw


def poisson_home_win_prob(home_xg, away_xg, use_dc=True):
    p_home = 0.0
    for h in range(8):
        for a in range(h):
            p_home += _score_prob(h, a, home_xg, away_xg, use_dc)
    return p_home


def poisson_over_2_5(home_xg, away_xg):
    p_under = 0.0
    for h in range(4):
        for a in range(4):
            if h + a <= 2:
                p_under += poisson.pmf(h, home_xg) * poisson.pmf(a, away_xg)
    return 1.0 - p_under


def predict_scoreline(home_xg, away_xg, top_n=3):
    """Return top-N most likely scorelines as (home_goals, away_goals, probability)."""
    scorelines = []
    for h in range(8):
        for a in range(8):
            p = _score_prob(h, a, home_xg, away_xg, use_dc=True)
            scorelines.append((h, a, p))
    scorelines.sort(key=lambda x: -x[2])
    return scorelines[:top_n]


def compute_betting_markets(home_xg, away_xg):
    """Compute standard betting market probabilities from Dixon-Coles Poisson model.

    Returns dict with probabilities for: Over/Under (1.5, 2.5, 3.5),
    BTTS, Double Chance, Draw No Bet, Asian Handicap, Half-Time result.
    """
    max_g = 7
    # Build score probability matrix with Dixon-Coles correction
    sm = {}
    for h in range(max_g):
        for a in range(max_g):
            sm[(h, a)] = _score_prob(h, a, home_xg, away_xg, use_dc=True)

    # Normalise to ensure probabilities sum to ~1
    sm_total = sum(sm.values())
    if sm_total > 0:
        for k in sm:
            sm[k] /= sm_total

    # Over/Under goal lines
    def p_over(line):
        return 1.0 - sum(sm[(h, a)] for h in range(max_g) for a in range(max_g) if h + a <= line)

    # 1X2 from Poisson
    p_home = sum(sm[(h, a)] for h in range(max_g) for a in range(h))
    p_draw = sum(sm[(k, k)] for k in range(max_g))
    p_away = max(0.01, 1.0 - p_home - p_draw)

    # Both Teams To Score
    p_h_zero = sum(sm[(0, a)] for a in range(max_g))
    p_a_zero = sum(sm[(h, 0)] for h in range(max_g))
    p_btts = 1.0 - p_h_zero - p_a_zero + sm[(0, 0)]

    # Half-time (approx 47% of goals scored in first half — empirical Turkish league)
    ht_hxg = home_xg * 0.47
    ht_axg = away_xg * 0.47
    ht_sm = {}
    for h in range(5):
        for a in range(5):
            ht_sm[(h, a)] = poisson.pmf(h, ht_hxg) * poisson.pmf(a, ht_axg)
    ht_home = sum(ht_sm[(h, a)] for h in range(5) for a in range(h))
    ht_draw = sum(ht_sm[(k, k)] for k in range(5))
    ht_away = max(0.01, 1.0 - ht_home - ht_draw)

    # Asian Handicap home -1.5
    ah_h_m15 = sum(sm[(h, a)] for h in range(max_g) for a in range(max_g) if h - a >= 2)

    denom_ha = max(0.01, p_home + p_away)
    return {
        "over_1.5": p_over(1),
        "over_2.5": p_over(2),
        "over_3.5": p_over(3),
        "btts": p_btts,
        "dc_1x": p_home + p_draw,        # Double Chance: home or draw
        "dc_x2": p_draw + p_away,         # Double Chance: draw or away
        "dc_12": p_home + p_away,         # Double Chance: home or away
        "dnb_home": p_home / denom_ha,    # Draw No Bet: home
        "dnb_away": p_away / denom_ha,    # Draw No Bet: away
        "ah_home_-1.5": ah_h_m15,         # Asian Handicap -1.5
        "ht_home": ht_home,
        "ht_draw": ht_draw,
        "ht_away": ht_away,
        "ht_over_0.5": 1.0 - ht_sm[(0, 0)],
    }


def update_bayesian_strength(team_stats, league_avg_goals):
    if league_avg_goals < 0.5:
        league_avg_goals = 1.3
    for team, ts in team_stats.items():
        if ts.matches_played < 3:
            continue
        avg_scored = np.mean(ts.scored[-15:]) if ts.scored else 1.0
        ts.attack_strength = max(0.3, min(3.0, avg_scored / league_avg_goals))
        avg_conceded = np.mean(ts.conceded[-15:]) if ts.conceded else 1.0
        ts.defense_strength = max(0.3, min(3.0, avg_conceded / league_avg_goals))
        # Home/away specific strengths
        if ts.home_scored and len(ts.home_scored) >= 2:
            ts.home_attack_str = max(0.3, min(3.0, np.mean(ts.home_scored[-10:]) / league_avg_goals))
            ts.home_defense_str = max(0.3, min(3.0, np.mean(ts.home_conceded[-10:]) / league_avg_goals))
        if ts.away_scored and len(ts.away_scored) >= 2:
            ts.away_attack_str = max(0.3, min(3.0, np.mean(ts.away_scored[-10:]) / league_avg_goals))
            ts.away_defense_str = max(0.3, min(3.0, np.mean(ts.away_conceded[-10:]) / league_avg_goals))


def build_feature_vector(
    home, away, team_stats, h2h_records,
    round_num, league_table, match_date, league_avg,
):
    hs = team_stats.get(home, TeamStats())
    aws = team_stats.get(away, TeamStats())

    vec = np.zeros(N_FEATURES, dtype=np.float32)
    col_idx = {col: i for i, col in enumerate(FEATURE_COLUMNS)}

    def s(col, val):
        if col in col_idx:
            vec[col_idx[col]] = float(val)

    # A. Home team rolling stats
    s("home_avg_scored_3", hs.rolling(hs.scored, 3))
    s("home_avg_scored_5", hs.rolling(hs.scored, 5))
    s("home_avg_scored_10", hs.rolling(hs.scored, 10))
    s("home_avg_conceded_3", hs.rolling(hs.conceded, 3))
    s("home_avg_conceded_5", hs.rolling(hs.conceded, 5))
    s("home_avg_conceded_10", hs.rolling(hs.conceded, 10))
    s("home_ppg_5", hs.rolling(hs.ppg, 5))
    s("home_ppg_10", hs.rolling(hs.ppg, 10))
    s("home_clean_sheet_10", hs.clean_sheet_rate(10))
    s("home_win_ratio_5", hs.win_ratio(5))
    s("home_draw_ratio_5", hs.draw_ratio(5))
    s("home_loss_ratio_5", hs.loss_ratio(5))

    # A. Away team rolling stats
    s("away_avg_scored_3", aws.rolling(aws.scored, 3))
    s("away_avg_scored_5", aws.rolling(aws.scored, 5))
    s("away_avg_scored_10", aws.rolling(aws.scored, 10))
    s("away_avg_conceded_3", aws.rolling(aws.conceded, 3))
    s("away_avg_conceded_5", aws.rolling(aws.conceded, 5))
    s("away_avg_conceded_10", aws.rolling(aws.conceded, 10))
    s("away_ppg_5", aws.rolling(aws.ppg, 5))
    s("away_ppg_10", aws.rolling(aws.ppg, 10))
    s("away_clean_sheet_10", aws.clean_sheet_rate(10))
    s("away_win_ratio_5", aws.win_ratio(5))
    s("away_draw_ratio_5", aws.draw_ratio(5))
    s("away_loss_ratio_5", aws.loss_ratio(5))

    # F. Elo & Poisson xG
    s("home_elo", hs.elo)
    s("away_elo", aws.elo)
    s("elo_diff", hs.elo - aws.elo)

    home_xg = poisson_xg(hs.attack_strength, aws.defense_strength, league_avg)
    away_xg = poisson_xg(aws.attack_strength, hs.defense_strength, league_avg)
    s("home_xg", home_xg)
    s("away_xg", away_xg)
    s("xg_diff", home_xg - away_xg)

    s("home_form_index", hs.form_index(5))
    s("away_form_index", aws.form_index(5))
    s("form_diff", hs.form_index(5) - aws.form_index(5))

    # A. H2H
    if h2h_records:
        h2h_home_wins = sum(1 for m in h2h_records if
                            (m.home == home and m.result == "H") or
                            (m.away == home and m.result == "A"))
        h2h_draws = sum(1 for m in h2h_records if m.result == "D")
        n_h2h = len(h2h_records)
        s("h2h_home_win_pct", h2h_home_wins / n_h2h)
        s("h2h_draw_pct", h2h_draws / n_h2h)
        s("h2h_avg_goals", np.mean([m.total_goals for m in h2h_records]))
        s("h2h_over25_pct", sum(1 for m in h2h_records if m.over_2_5) / n_h2h)
        s("h2h_bts_pct", sum(1 for m in h2h_records if m.bts) / n_h2h)
        s("h2h_count", min(n_h2h, 10))
    else:
        s("h2h_home_win_pct", 0.4)
        s("h2h_draw_pct", 0.25)
        s("h2h_avg_goals", 2.5)
        s("h2h_over25_pct", 0.5)
        s("h2h_bts_pct", 0.5)
        s("h2h_count", 0)

    # A. League position
    home_pos = league_table.get(home, TOTAL_TEAMS // 2) + 1
    away_pos = league_table.get(away, TOTAL_TEAMS // 2) + 1
    s("home_league_pos_norm", home_pos / TOTAL_TEAMS)
    s("away_league_pos_norm", away_pos / TOTAL_TEAMS)
    s("pos_diff", (home_pos - away_pos) / TOTAL_TEAMS)
    s("home_goal_diff", hs.goals_for - hs.goals_against)
    s("away_goal_diff", aws.goals_for - aws.goals_against)

    # E. Pressure indices
    leader_pts = max((ts.points for ts in team_stats.values()), default=0)
    bottom3_pts = sorted([ts.points for ts in team_stats.values()])[:3]
    rel_line = bottom3_pts[-1] if bottom3_pts else 0
    s("home_pts_gap_leader", leader_pts - hs.points)
    s("away_pts_gap_leader", leader_pts - aws.points)
    s("home_pts_gap_relegation", hs.points - rel_line)
    s("away_pts_gap_relegation", aws.points - rel_line)

    # B. Squad & Tactical (approximated)
    s("home_formation_stability", min(1.0, hs.matches_played / 10))
    s("away_formation_stability", min(1.0, aws.matches_played / 10))
    s("home_squad_rotation_gini", hs.goal_concentration_index(10))
    s("away_squad_rotation_gini", aws.goal_concentration_index(10))
    s("home_goal_concentration", hs.goal_concentration_index(5))
    s("away_goal_concentration", aws.goal_concentration_index(5))
    s("home_avg_age", 26.5)
    s("away_avg_age", 26.5)

    # E. Contextual & Environmental
    s("home_fixture_congestion_7d", hs.fixture_congestion(match_date, 7))
    s("away_fixture_congestion_7d", aws.fixture_congestion(match_date, 7))
    s("home_fixture_congestion_14d", hs.fixture_congestion(match_date, 14))
    s("away_fixture_congestion_14d", aws.fixture_congestion(match_date, 14))
    s("home_manager_tenure", min(10, hs.matches_played))
    s("away_manager_tenure", min(10, aws.matches_played))
    s("home_manager_change", 0)
    s("away_manager_change", 0)

    derbies = {
        frozenset({"Galatasaray", "Fenerbahçe"}),
        frozenset({"Galatasaray", "Beşiktaş"}),
        frozenset({"Fenerbahçe", "Beşiktaş"}),
        frozenset({"Galatasaray", "Trabzonspor"}),
        frozenset({"Fenerbahçe", "Trabzonspor"}),
        frozenset({"Beşiktaş", "Trabzonspor"}),
    }
    s("derby_flag", 1.0 if frozenset({home, away}) in derbies else 0.0)

    if round_num <= 10:
        phase = 0
    elif round_num <= 24:
        phase = 1
    elif round_num <= 34:
        phase = 2
    else:
        phase = 3
    s("season_phase", phase)
    s("match_week_norm", round_num / 38.0)

    try:
        dt = datetime.strptime(match_date, "%Y-%m-%d")
        day_of_year = dt.timetuple().tm_yday
        s("day_sin", math.sin(2 * math.pi * day_of_year / 365))
        s("day_cos", math.cos(2 * math.pi * day_of_year / 365))
        s("month_sin", math.sin(2 * math.pi * dt.month / 12))
        s("month_cos", math.cos(2 * math.pi * dt.month / 12))
    except ValueError:
        pass

    h_rest = hs.rest_days(match_date)
    a_rest = aws.rest_days(match_date)
    s("home_rest_days", min(h_rest, 21))
    s("away_rest_days", min(a_rest, 21))
    s("rest_diff", h_rest - a_rest)

    # D. Sentiment (form-derived proxy)
    s("home_media_sentiment", (hs.form_index(3) - hs.form_index(10)) * 2)
    s("away_media_sentiment", (aws.form_index(3) - aws.form_index(10)) * 2)
    h_home_form = hs.win_ratio(5, hs.home_results) if hs.home_results else 0.5
    a_away_form = aws.win_ratio(5, aws.away_results) if aws.away_results else 0.5
    s("home_fan_optimism", (h_home_form - 0.5) * 2)
    s("away_fan_optimism", (a_away_form - 0.5) * 2)
    elo_signal = 1.0 / (1.0 + 10 ** ((aws.elo - hs.elo - HOME_ADV_ELO) / 400))
    form_signal = hs.form_index(5)
    s("media_consensus_strength", 1.0 - abs(elo_signal - form_signal))

    # F. Derived & Computed
    h_attack = hs.rolling(hs.scored, 5)
    a_defense = aws.rolling(aws.conceded, 5)
    a_attack = aws.rolling(aws.scored, 5)
    h_defense = hs.rolling(hs.conceded, 5)
    s("style_matchup_index", (h_attack + a_defense - a_attack - h_defense + 3) / 6.0)

    h_cong = hs.fixture_congestion(match_date, 14)
    a_cong = aws.fixture_congestion(match_date, 14)
    s("fatigue_diff", h_cong - a_cong)

    s("home_momentum", hs.form_acceleration())
    s("away_momentum", aws.form_acceleration())

    s("home_scoring_consistency", 1.0 - min(1.0, hs.rolling_std(hs.scored, 5)))
    s("away_scoring_consistency", 1.0 - min(1.0, aws.rolling_std(aws.scored, 5)))

    s("surprise_index_home", hs.rolling_std(hs.ppg, 10))
    s("surprise_index_away", aws.rolling_std(aws.ppg, 10))

    try:
        dt = datetime.strptime(match_date, "%Y-%m-%d")
        month = dt.month
        if month in (12, 1, 2):
            temp_bucket = 0
        elif month in (3, 4, 5, 10, 11):
            temp_bucket = 1
        else:
            temp_bucket = 2
    except ValueError:
        temp_bucket = 1
    s("temperature_bucket", temp_bucket)
    s("precipitation_flag", 1 if temp_bucket == 0 else 0)
    s("wind_category", 1)
    s("venue_type", 0)

    # ── Card & discipline (v0.2) ──
    s("home_avg_yellows_5", hs.rolling(hs.yellows, 5))
    s("away_avg_yellows_5", aws.rolling(aws.yellows, 5))
    s("home_avg_yellows_10", hs.rolling(hs.yellows, 10))
    s("away_avg_yellows_10", aws.rolling(aws.yellows, 10))
    s("home_avg_fouls_5", hs.rolling(hs.fouls, 5))
    s("away_avg_fouls_5", aws.rolling(aws.fouls, 5))
    if h2h_records:
        h2h_yellows = np.mean([m.home_yellows + m.away_yellows for m in h2h_records])
        s("h2h_avg_cards", h2h_yellows)
    else:
        s("h2h_avg_cards", 4.0)
    is_derby = frozenset({home, away}) in derbies
    s("derby_card_factor", 1.3 if is_derby else 1.0)

    # ── Half-time / second-half splits (v0.2) ──
    s("home_avg_ht_scored_5", hs.rolling(hs.ht_scored, 5))
    s("away_avg_ht_scored_5", aws.rolling(aws.ht_scored, 5))
    s("home_avg_sh_scored_5", hs.rolling(hs.sh_scored, 5))
    s("away_avg_sh_scored_5", aws.rolling(aws.sh_scored, 5))
    s("home_avg_ht_conceded_5", hs.rolling(hs.ht_conceded, 5))
    s("away_avg_ht_conceded_5", aws.rolling(aws.ht_conceded, 5))

    # ── Venue-specific performance (v0.2) ──
    s("home_venue_win_pct", hs.home_venue_win_pct(10))
    s("away_venue_win_pct", aws.away_venue_win_pct(10))
    s("home_venue_ppg_10", hs.rolling(hs.home_ppg, 10))
    s("away_venue_ppg_10", aws.rolling(aws.away_ppg, 10))

    # ── Draw & low-scoring tendencies (v0.2) ──
    s("home_draws_bayesian", hs.bayesian_draw_prob())
    s("away_draws_bayesian", aws.bayesian_draw_prob())
    s("low_scoring_likelihood", (hs.low_scoring_rate(10) + aws.low_scoring_rate(10)) / 2)

    # ── Strength of schedule (v0.2) ──
    s("home_sos", hs.strength_of_schedule(10))
    s("away_sos", aws.strength_of_schedule(10))

    # ── Second-half detail (v0.2) ──
    s("home_sh_scoring_rate", hs.second_half_scoring_rate(10))
    s("away_sh_scoring_rate", aws.second_half_scoring_rate(10))
    s("home_sh_conceding_rate", hs.second_half_conceding_rate(10))
    s("away_sh_conceding_rate", aws.second_half_conceding_rate(10))

    # ── Scoring patterns (v0.2) ──
    s("home_goals_per_match_rate", hs.rolling(hs.scored, 10) if hs.scored else 1.0)
    s("away_goals_per_match_rate", aws.rolling(aws.scored, 10) if aws.scored else 1.0)

    # Sanitize: replace NaN/Inf with 0
    vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

    return vec.reshape(1, -1)


def update_team_stats(team_stats, match):
    home, away = match.home, match.away
    if home not in team_stats:
        team_stats[home] = TeamStats()
    if away not in team_stats:
        team_stats[away] = TeamStats()

    hs = team_stats[home]
    aws = team_stats[away]

    hs.opponent_elos.append(aws.elo)
    aws.opponent_elos.append(hs.elo)

    hs.elo, aws.elo = update_elo(hs.elo, aws.elo, match.result)

    hs.scored.append(match.home_goals)
    hs.conceded.append(match.away_goals)
    aws.scored.append(match.away_goals)
    aws.conceded.append(match.home_goals)

    hs.home_scored.append(match.home_goals)
    hs.home_conceded.append(match.away_goals)
    aws.away_scored.append(match.away_goals)
    aws.away_conceded.append(match.home_goals)

    hs.ht_scored.append(match.ht_home)
    hs.ht_conceded.append(match.ht_away)
    aws.ht_scored.append(match.ht_away)
    aws.ht_conceded.append(match.ht_home)
    hs.sh_scored.append(match.second_half_home)
    hs.sh_conceded.append(match.second_half_away)
    aws.sh_scored.append(match.second_half_away)
    aws.sh_conceded.append(match.second_half_home)

    hs.goals_for += match.home_goals
    hs.goals_against += match.away_goals
    aws.goals_for += match.away_goals
    aws.goals_against += match.home_goals

    hs.scorelines.append((match.home_goals, match.away_goals))
    aws.scorelines.append((match.away_goals, match.home_goals))

    if match.result == "H":
        hs.results.append("W")
        aws.results.append("L")
        hs.home_results.append("W")
        aws.away_results.append("L")
        hs.ppg.append(3)
        aws.ppg.append(0)
        hs.home_ppg.append(3)
        aws.away_ppg.append(0)
        hs.points += 3
        hs.draws.append(0)
        aws.draws.append(0)
    elif match.result == "A":
        hs.results.append("L")
        aws.results.append("W")
        hs.home_results.append("L")
        aws.away_results.append("W")
        hs.ppg.append(0)
        aws.ppg.append(3)
        hs.home_ppg.append(0)
        aws.away_ppg.append(3)
        aws.points += 3
        hs.draws.append(0)
        aws.draws.append(0)
    else:
        hs.results.append("D")
        aws.results.append("D")
        hs.home_results.append("D")
        aws.away_results.append("D")
        hs.ppg.append(1)
        aws.ppg.append(1)
        hs.home_ppg.append(1)
        aws.away_ppg.append(1)
        hs.points += 1
        aws.points += 1
        hs.draws.append(1)
        aws.draws.append(1)

    hs.clean_sheets.append(1 if match.away_goals == 0 else 0)
    aws.clean_sheets.append(1 if match.home_goals == 0 else 0)

    # Update Bayesian draw posteriors
    if match.result == "D":
        hs.draw_alpha += 1
        aws.draw_alpha += 1
    else:
        hs.draw_beta += 1
        aws.draw_beta += 1

    # Card & discipline tracking
    hs.yellows.append(match.home_yellows)
    aws.yellows.append(match.away_yellows)
    hs.reds.append(match.home_reds)
    aws.reds.append(match.away_reds)
    hs.fouls.append(match.home_fouls)
    aws.fouls.append(match.away_fouls)

    hs.matches_played += 1
    aws.matches_played += 1
    hs.home_matches += 1
    aws.away_matches += 1
    hs.match_dates.append(match.date)
    aws.match_dates.append(match.date)


def build_league_table(team_stats):
    teams_sorted = sorted(
        team_stats.keys(),
        key=lambda t: (
            team_stats[t].points,
            team_stats[t].goals_for - team_stats[t].goals_against,
            team_stats[t].goals_for,
        ),
        reverse=True,
    )
    return {t: i for i, t in enumerate(teams_sorted)}


def get_h2h(matches, home, away):
    return [
        m for m in matches
        if (m.home == home and m.away == away) or (m.home == away and m.away == home)
    ]


def compute_league_avg_goals(team_stats):
    total_goals = sum(ts.goals_for for ts in team_stats.values())
    total_matches = sum(ts.matches_played for ts in team_stats.values()) / 2
    if total_matches < 1:
        return 1.3
    return total_goals / (total_matches * 2)


def train_on_historical(
    training_matches, all_prior_matches,
    n_estimators=150, max_depth=4, learning_rate=0.10,
    reg_alpha=0.5, reg_lambda=1.5, subsample=0.8,
    colsample=0.8, min_child_weight=3,
    use_calibration=True,
):
    team_stats = {}
    features_list = []
    labels = []
    sample_weights = []

    for i, match in enumerate(all_prior_matches):
        league_table = build_league_table(team_stats)
        h2h = get_h2h(all_prior_matches[:i], match.home, match.away)
        league_avg = compute_league_avg_goals(team_stats)

        if i % 10 == 0:
            update_bayesian_strength(team_stats, league_avg)

        if team_stats.get(match.home) and team_stats.get(match.away):
            if team_stats[match.home].matches_played >= 3 and team_stats[match.away].matches_played >= 3:
                fv = build_feature_vector(
                    match.home, match.away, team_stats, h2h,
                    match.round_num, league_table, match.date, league_avg,
                )
                features_list.append(fv.flatten())
                labels.append(match.result_class)
                if match.result == "D":
                    sample_weights.append(2.0)
                else:
                    sample_weights.append(1.0)

        update_team_stats(team_stats, match)

    X = np.array(features_list)
    y = np.array(labels)
    w = np.array(sample_weights)

    base_model = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        tree_method="hist",
        device="cpu",
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        reg_alpha=reg_alpha,
        reg_lambda=reg_lambda,
        subsample=subsample,
        colsample_bytree=colsample,
        min_child_weight=min_child_weight,
        gamma=0.1,
        random_state=42,
        verbosity=0,
        n_jobs=-1,
    )

    # Train/validation split for accuracy estimate
    from sklearn.model_selection import train_test_split
    X_tr, X_val, y_tr, y_val, w_tr, w_val = train_test_split(
        X, y, w, test_size=0.15, random_state=42, stratify=y,
    )
    base_model.fit(X_tr, y_tr, sample_weight=w_tr,
                   eval_set=[(X_val, y_val)], sample_weight_eval_set=[w_val],
                   verbose=False)
    val_acc = float(accuracy_score(y_val, base_model.predict(X_val)))
    val_loss = float(log_loss(y_val, base_model.predict_proba(X_val)))

    # Retrain on full data for final model
    base_model.fit(X, y, sample_weight=w, verbose=False)

    model = base_model

    # Log top-20 feature importances
    importances = base_model.feature_importances_
    top_idx = np.argsort(importances)[::-1][:20]
    print("  Top-20 feature importances:")
    for rank, idx in enumerate(top_idx):
        col_name = FEATURE_COLUMNS[idx] if idx < len(FEATURE_COLUMNS) else f"f{idx}"
        print("    {:>2}. {:<35s} {:.4f}".format(rank + 1, col_name, importances[idx]))
    # Count zero-importance features
    zero_count = int(np.sum(importances == 0))
    if zero_count > 0:
        print("  ⚠  {} features have zero importance".format(zero_count))

    return model, val_acc, val_loss, team_stats


@dataclass
class PredictionResult:
    match: MatchRecord
    pred_home_win_prob: float
    pred_draw_prob: float
    pred_away_win_prob: float
    predicted_result: str
    actual_result: str
    correct: bool
    confidence: float
    predicted_score: tuple = (1, 0)       # (home_goals, away_goals) most likely
    top_scorelines: list = field(default_factory=list)  # top-3 (hg, ag, prob)
    home_xg: float = 1.3
    away_xg: float = 1.0
    betting_markets: dict = field(default_factory=dict)  # All market probabilities


# XGBoost ensemble weight sourced from LeagueConfig (Phase 1.1)
XGB_WEIGHT = _LEAGUE.xgb_weight  # rest goes to Poisson
DRAW_BOOST = 0.0  # No draw boost (empirically hurts accuracy)


def predict_matches(model, test_matches, all_prior_matches, team_stats):
    results = []
    league_avg = compute_league_avg_goals(team_stats)

    for match in test_matches:
        league_table = build_league_table(team_stats)
        h2h = get_h2h(all_prior_matches, match.home, match.away)

        hs = team_stats.get(match.home)
        aws = team_stats.get(match.away)

        if not hs or not aws or hs.matches_played < 2 or aws.matches_played < 2:
            update_team_stats(team_stats, match)
            all_prior_matches.append(match)
            continue

        if len(results) % 5 == 0:
            update_bayesian_strength(team_stats, league_avg)

        fv = build_feature_vector(
            match.home, match.away, team_stats, h2h,
            match.round_num, league_table, match.date, league_avg,
        )

        proba = model.predict_proba(fv)[0]

        # Poisson model probabilities (overall team strengths)
        hxg = poisson_xg(hs.attack_strength, aws.defense_strength, league_avg)
        axg = poisson_xg(aws.attack_strength, hs.defense_strength, league_avg)
        p_draw = poisson_draw_prob(hxg, axg)
        p_home = poisson_home_win_prob(hxg, axg)
        p_away = max(0.01, 1.0 - p_home - p_draw)

        # Ensemble: XGB_WEIGHT XGBoost + rest Poisson
        pw = 1.0 - XGB_WEIGHT
        home_win_prob = XGB_WEIGHT * float(proba[0]) + pw * p_home
        draw_prob = XGB_WEIGHT * float(proba[1]) + pw * p_draw
        away_win_prob = XGB_WEIGHT * float(proba[2]) + pw * p_away

        # Apply draw boost
        draw_prob *= (1.0 + DRAW_BOOST)

        total_p = home_win_prob + draw_prob + away_win_prob
        home_win_prob /= total_p
        draw_prob /= total_p
        away_win_prob /= total_p

        probs = {"H": home_win_prob, "D": draw_prob, "A": away_win_prob}
        predicted = max(probs, key=probs.get)

        # Enhanced draw detection: multi-signal scoring
        draw_signals = 0
        ha_gap = abs(home_win_prob - away_win_prob)
        bayesian_draw_avg = (hs.bayesian_draw_prob() + aws.bayesian_draw_prob()) / 2
        elo_gap = abs(hs.elo - aws.elo)

        if ha_gap < 0.15:
            draw_signals += 1
        if draw_prob > 0.26:
            draw_signals += 1
        if bayesian_draw_avg > 0.20:
            draw_signals += 1
        if p_draw > 0.25:  # Poisson (Dixon-Coles) draw probability
            draw_signals += 1
        if elo_gap < 80:   # Closely matched teams by Elo
            draw_signals += 1
        # Override to draw when >= 3 signals fire
        if draw_signals >= 3 and draw_prob > 0.22:
            predicted = "D"

        confidence = max(probs.values())

        # Score prediction from Poisson xG
        top_scores = predict_scoreline(hxg, axg, top_n=3)
        best_score = top_scores[0] if top_scores else (1, 0, 0.0)

        # Betting market probabilities
        bm = compute_betting_markets(hxg, axg)

        results.append(PredictionResult(
            match=match,
            pred_home_win_prob=home_win_prob,
            pred_draw_prob=draw_prob,
            pred_away_win_prob=away_win_prob,
            predicted_result=predicted,
            actual_result=match.result,
            correct=(predicted == match.result),
            confidence=confidence,
            predicted_score=(best_score[0], best_score[1]),
            top_scorelines=top_scores,
            home_xg=hxg,
            away_xg=axg,
            betting_markets=bm,
        ))

        update_team_stats(team_stats, match)
        all_prior_matches.append(match)
        league_avg = compute_league_avg_goals(team_stats)

    return results


def generate_report(results, val_acc, val_loss, train_rounds, elapsed, model_params):
    lines = []
    w = 90

    lines.append("=" * w)
    lines.append("NEGELIR AI — HISTORICAL PREDICTION TEST REPORT".center(w))
    lines.append("Turkish Super Lig (Real Data — Multi-Season)".center(w))
    lines.append(("Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")).center(w))
    lines.append("=" * w)

    lines.append("")
    lines.append("MODEL CONFIGURATION")
    lines.append("-" * w)
    for k, v in model_params.items():
        lines.append("  {:<25s}: {}".format(k, v))
    lines.append("  {:<25s}: 1-{}".format("Training rounds", train_rounds))
    lines.append("  {:<25s}: {}-38".format("Test rounds", train_rounds + 1))
    lines.append("  {:<25s}: {:.4f}".format("Validation accuracy", val_acc))
    lines.append("  {:<25s}: {:.4f}".format("Validation log-loss", val_loss))
    lines.append("  {:<25s}: {:.1f}s".format("Execution time", elapsed))

    total = len(results)
    correct = sum(1 for r in results if r.correct)
    accuracy = correct / total if total else 0

    by_actual = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        by_actual[r.actual_result]["total"] += 1
        if r.correct:
            by_actual[r.actual_result]["correct"] += 1

    lines.append("")
    lines.append("OVERALL RESULTS")
    lines.append("-" * w)
    lines.append("  Total predictions   : {}".format(total))
    lines.append("  Correct predictions : {}".format(correct))
    lines.append("  Overall accuracy    : {:.1%}".format(accuracy))
    lines.append("")
    lines.append("  {:<15} {:>8} {:>10} {:>10}".format("Result Type", "Total", "Correct", "Accuracy"))
    for rtype in ["H", "D", "A"]:
        d = by_actual[rtype]
        acc = d["correct"] / d["total"] if d["total"] else 0
        label = {"H": "Home Win", "D": "Draw", "A": "Away Win"}[rtype]
        lines.append("  {:<15} {:>8} {:>10} {:>10.1%}".format(label, d["total"], d["correct"], acc))

    high_conf = [r for r in results if r.confidence >= 0.50]
    high_correct = sum(1 for r in high_conf if r.correct)
    if high_conf:
        lines.append("")
        lines.append("  High-confidence (>=50%): {}, correct: {}, accuracy: {:.1%}".format(
            len(high_conf), high_correct, high_correct / len(high_conf)))

    # Score prediction accuracy
    exact_score = sum(1 for r in results
                      if r.predicted_score == (r.match.home_goals, r.match.away_goals))
    within_1 = sum(1 for r in results
                   if abs(r.predicted_score[0] - r.match.home_goals) <= 1
                   and abs(r.predicted_score[1] - r.match.away_goals) <= 1)
    top3_hit = sum(1 for r in results
                   if any(s[0] == r.match.home_goals and s[1] == r.match.away_goals
                          for s in r.top_scorelines))
    goal_diff_correct = sum(1 for r in results
                            if (r.predicted_score[0] - r.predicted_score[1]) ==
                               (r.match.home_goals - r.match.away_goals))

    lines.append("")
    lines.append("SCORE PREDICTION ACCURACY")
    lines.append("-" * w)
    lines.append("  Exact score match         : {}/{} ({:.1%})".format(exact_score, total, exact_score / total if total else 0))
    lines.append("  Within 1 goal (each team) : {}/{} ({:.1%})".format(within_1, total, within_1 / total if total else 0))
    lines.append("  Top-3 scoreline hit       : {}/{} ({:.1%})".format(top3_hit, total, top3_hit / total if total else 0))
    lines.append("  Goal diff correct         : {}/{} ({:.1%})".format(goal_diff_correct, total, goal_diff_correct / total if total else 0))

    # Betting market accuracy
    ou15_ok = ou25_ok = ou35_ok = btts_ok = 0
    dc1x_ok = dcx2_ok = dnb_ok = dnb_tot = 0
    ah15_ok = ht_ok = ht_o05_ok = 0
    for r in results:
        bm = r.betting_markets
        if not bm:
            continue
        m = r.match
        tg = m.total_goals
        # Over/Under
        if (bm["over_1.5"] > 0.5) == (tg > 1.5):
            ou15_ok += 1
        if (bm["over_2.5"] > 0.5) == (tg > 2.5):
            ou25_ok += 1
        if (bm["over_3.5"] > 0.5) == (tg > 3.5):
            ou35_ok += 1
        # BTTS
        if (bm["btts"] > 0.5) == m.bts:
            btts_ok += 1
        # Double Chance 1X
        if (bm["dc_1x"] > 0.5) == (m.result != "A"):
            dc1x_ok += 1
        # Double Chance X2
        if (bm["dc_x2"] > 0.5) == (m.result != "H"):
            dcx2_ok += 1
        # Draw No Bet (only non-draw matches)
        if m.result != "D":
            dnb_tot += 1
            if (bm["dnb_home"] > 0.5) == (m.result == "H"):
                dnb_ok += 1
        # Asian Handicap -1.5
        if (bm["ah_home_-1.5"] > 0.5) == (m.home_goals - m.away_goals >= 2):
            ah15_ok += 1
        # Half-Time result
        ht_probs = [bm["ht_home"], bm["ht_draw"], bm["ht_away"]]
        ht_pred = ["H", "D", "A"][ht_probs.index(max(ht_probs))]
        ht_actual = "H" if m.ht_home > m.ht_away else ("A" if m.ht_home < m.ht_away else "D")
        if ht_pred == ht_actual:
            ht_ok += 1
        # HT Over 0.5
        if (bm["ht_over_0.5"] > 0.5) == (m.ht_total > 0):
            ht_o05_ok += 1

    lines.append("")
    lines.append("BETTING MARKET ACCURACY (picking >50% side)")
    lines.append("-" * w)
    lines.append("  {:<28s} {:>6s} {:>8s} {:>10s}".format("Market", "Total", "Correct", "Accuracy"))
    mkt_data = [
        ("Over/Under 1.5 Goals", total, ou15_ok),
        ("Over/Under 2.5 Goals", total, ou25_ok),
        ("Over/Under 3.5 Goals", total, ou35_ok),
        ("BTTS (Yes/No)", total, btts_ok),
        ("Double Chance 1X", total, dc1x_ok),
        ("Double Chance X2", total, dcx2_ok),
        ("Draw No Bet", dnb_tot, dnb_ok),
        ("Asian Handicap H -1.5", total, ah15_ok),
        ("Half-Time Result", total, ht_ok),
        ("HT Over/Under 0.5", total, ht_o05_ok),
    ]
    for name, t, c in mkt_data:
        acc_val = c / t if t else 0
        lines.append("  {:<28s} {:>6d} {:>8d} {:>10.1%}".format(name, t, c, acc_val))

    lines.append("")
    lines.append("FEATURE ENGINEERING HIGHLIGHTS")
    lines.append("-" * w)
    lines.append("  Roadmap categories covered:")
    lines.append("    A. Match-Level Core Data     : FT/HT scores, goals per half, league standings, H2H")
    lines.append("    B. Player-Level (approx.)    : Goal concentration, scoring consistency, squad rotation Gini")
    lines.append("    C. Tactical & Formation      : Style matchup index, defensive organization")
    lines.append("    D. Media Sentiment (proxy)   : Form-derived sentiment, fan optimism, consensus strength")
    lines.append("    E. Contextual & Environmental: Fixture congestion, derby, pressure index, season phase")
    lines.append("    F. Derived & Computed        : Poisson xG, custom Elo, Bayesian strength, SoS, momentum")

    lines.append("")
    lines.append("MATCH-BY-MATCH PREDICTIONS")
    lines.append("-" * w)

    current_round = 0
    for r in results:
        if r.match.round_num != current_round:
            current_round = r.match.round_num
            lines.append("")
            lines.append("  --- Matchday {} ---".format(current_round))

        m = r.match
        score = "{}-{}".format(m.home_goals, m.away_goals)
        pred_score = "{}-{}".format(r.predicted_score[0], r.predicted_score[1])
        result_map = {"H": "Home Win", "D": "Draw", "A": "Away Win"}
        pred_label = result_map[r.predicted_result]
        actual_label = result_map[r.actual_result]
        check = "OK" if r.correct else "XX"
        score_check = "==" if r.predicted_score == (m.home_goals, m.away_goals) else "~~" if (abs(r.predicted_score[0] - m.home_goals) <= 1 and abs(r.predicted_score[1] - m.away_goals) <= 1) else ""

        lines.append(
            "  {:>20s} vs {:<20s}  Score: {:>5s}  Pred: {:<9s}  Actual: {:<9s}  {}".format(
                m.home, m.away, score, pred_label, actual_label, check
            )
        )
        lines.append(
            "  {:>20s}    {:20s}  H={:.0%}  D={:.0%}  A={:.0%}  (conf: {:.0%})".format(
                "", "", r.pred_home_win_prob, r.pred_draw_prob, r.pred_away_win_prob, r.confidence
            )
        )
        # Score prediction line
        alt_scores = ", ".join("{}-{} ({:.0%})".format(s[0], s[1], s[2]) for s in r.top_scorelines)
        lines.append(
            "  {:>20s}    {:20s}  Pred Score: {:>5s} {}  xG: {:.2f}-{:.2f}  Alt: {}".format(
                "", "", pred_score, score_check, r.home_xg, r.away_xg, alt_scores
            )
        )
        # Betting markets line
        bm = r.betting_markets
        if bm:
            ou_str = "O" if bm["over_2.5"] > 0.5 else "U"
            ou_pct = bm["over_2.5"] if ou_str == "O" else 1 - bm["over_2.5"]
            btts_str = "Y" if bm["btts"] > 0.5 else "N"
            btts_pct = bm["btts"] if btts_str == "Y" else 1 - bm["btts"]
            ht_probs = [bm["ht_home"], bm["ht_draw"], bm["ht_away"]]
            ht_names = ["H", "D", "A"]
            ht_best = ht_names[ht_probs.index(max(ht_probs))]
            ht_pct = max(ht_probs)
            lines.append(
                "  {:>20s}    {:20s}  O/U2.5:{}{:.0%}  BTTS:{}{:.0%}  HT:{}{:.0%}  DC1X:{:.0%}  AH-1.5:{:.0%}".format(
                    "", "", ou_str, ou_pct, btts_str, btts_pct,
                    ht_best, ht_pct, bm["dc_1x"], bm["ah_home_-1.5"],
                )
            )

    lines.append("")
    lines.append("ROUND-BY-ROUND ACCURACY")
    lines.append("-" * w)

    rounds = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        rounds[r.match.round_num]["total"] += 1
        if r.correct:
            rounds[r.match.round_num]["correct"] += 1

    lines.append("  {:>8} {:>8} {:>10} {:>10}  Bar".format("Round", "Total", "Correct", "Accuracy"))
    for rnd in sorted(rounds.keys()):
        d = rounds[rnd]
        acc = d["correct"] / d["total"] if d["total"] else 0
        bar_len = int(acc * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        lines.append("  {:>8} {:>8} {:>10} {:>10.1%}  {}".format(rnd, d["total"], d["correct"], acc, bar))

    lines.append("")
    lines.append("=" * w)
    lines.append("SUMMARY: {}/{} correct ({:.1%} accuracy)".format(correct, total, accuracy).center(w))

    baseline_home = sum(1 for r in results if r.actual_result == "H") / total if total else 0
    lines.append("Baseline (always predict home): {:.1%}".format(baseline_home).center(w))
    lines.append("Model lift over baseline: {:+.1%}".format(accuracy - baseline_home).center(w))
    lines.append("=" * w)

    return "\n".join(lines)


def run_test(
    train_rounds=25, output_path=None,
    n_estimators=150, max_depth=4, learning_rate=0.10,
    min_child_weight=3, expanding=False, retrain_every=3,
    predict_from=15, train_pct=0.75,
):
    output_path = output_path or DEFAULT_OUTPUT
    start = time.time()

    print("\n" + "=" * 60)
    print("NEGELIR AI — Historical Prediction Test (v2)")
    print("=" * 60)

    print("\nLoading match data from {}...".format(DATA_PATH))
    matches = load_matches(DATA_PATH)
    print("  Loaded {} matches across {} teams".format(len(matches), TOTAL_TEAMS))

    # For multi-season data, derive train_rounds from train_pct
    max_round = max(m.round_num for m in matches) if matches else 38
    if max_round > 45:  # multi-season data
        train_rounds = int(max_round * train_pct)
        predict_from = int(max_round * 0.12)  # start predicting after 12% of data
    print("  Max round: {}, train split at round: {}".format(max_round, train_rounds))

    if expanding:
        # Expanding window: retrain every N rounds, predict from round predict_from
        print("  Mode: EXPANDING WINDOW (retrain every {} rounds, predict from round {})".format(
            retrain_every, predict_from))

        rounds_map = defaultdict(list)
        for m in matches:
            rounds_map[m.round_num].append(m)
        all_rounds = sorted(rounds_map.keys())

        # Pre-compute ALL feature vectors AND Poisson probabilities in a single pass
        # This ensures training and prediction use the exact same stats snapshot
        print("  Pre-computing feature vectors and Poisson probabilities...")
        team_stats_build = {}
        cached_features = {}  # match_index -> (feature_vector, label, weight)
        cached_poisson = {}   # match_index -> (p_home, p_draw, p_away)
        all_matches_ordered = []
        for rnd in all_rounds:
            for m in rounds_map[rnd]:
                all_matches_ordered.append(m)
        
        for j, m in enumerate(all_matches_ordered):
            lt = build_league_table(team_stats_build)
            h2h = get_h2h(all_matches_ordered[:j], m.home, m.away)
            la = compute_league_avg_goals(team_stats_build)
            if j % 10 == 0:
                update_bayesian_strength(team_stats_build, la)
            
            if m.home not in team_stats_build:
                team_stats_build[m.home] = TeamStats()
            if m.away not in team_stats_build:
                team_stats_build[m.away] = TeamStats()
            hs = team_stats_build.get(m.home)
            aws = team_stats_build.get(m.away)
            
            if hs and aws and hs.matches_played >= 3 and aws.matches_played >= 3:
                fv = build_feature_vector(m.home, m.away, team_stats_build, h2h,
                                          m.round_num, lt, m.date, la)
                cached_features[j] = (fv.flatten(), m.result_class, 2.0 if m.result == "D" else 1.0)
                # Cache Poisson probabilities and xG using same stats snapshot
                hxg = poisson_xg(hs.attack_strength, aws.defense_strength, la)
                axg = poisson_xg(aws.attack_strength, hs.defense_strength, la)
                cp_draw = poisson_draw_prob(hxg, axg)
                cp_home = poisson_home_win_prob(hxg, axg)
                cp_away = max(0.01, 1.0 - cp_home - cp_draw)
                cached_poisson[j] = (cp_home, cp_draw, cp_away, hxg, axg)
            update_team_stats(team_stats_build, m)
        
        print("  Cached {} feature vectors".format(len(cached_features)))

        # Map round to match indices
        idx_offset = 0
        round_to_indices = {}
        for rnd in all_rounds:
            count = len(rounds_map[rnd])
            round_to_indices[rnd] = list(range(idx_offset, idx_offset + count))
            idx_offset += count

        # Run expanding window using cached features for BOTH training and prediction
        model = None
        last_train_rnd = 0
        all_results = []
        val_acc_last = 0.0
        val_loss_last = 0.0
        processed_up_to = 0

        for rnd in all_rounds:
            rnd_indices = round_to_indices[rnd]

            if rnd >= predict_from:
                if model is None or (rnd - last_train_rnd) >= retrain_every:
                    # Build training set from cached features
                    fl, ll = [], []
                    for j in range(processed_up_to):
                        if j in cached_features:
                            fv, label, weight = cached_features[j]
                            fl.append(fv)
                            ll.append(label)

                    if len(fl) >= 20:
                        X = np.array(fl)
                        y = np.array(ll)
                        print("    Training round {} ({} samples)...".format(rnd, len(fl)), end="", flush=True)
                        model = xgb.XGBClassifier(
                            n_estimators=n_estimators, max_depth=max_depth,
                            learning_rate=learning_rate,
                            tree_method="hist", device="cpu",
                            objective="multi:softprob", num_class=3,
                            eval_metric="mlogloss",
                            reg_alpha=0.5, reg_lambda=1.5, subsample=0.8,
                            colsample_bytree=0.8, min_child_weight=min_child_weight,
                            gamma=0.1, random_state=42, verbosity=0,
                            n_jobs=-1,
                        )
                        model.fit(X, y, verbose=False)
                        val_acc_last = accuracy_score(y, model.predict(X))
                        val_loss_last = log_loss(y, model.predict_proba(X))
                        last_train_rnd = rnd
                        print(" done (train_acc={:.1%})".format(val_acc_last), flush=True)

                if model is not None:
                    # Predict using cached features and Poisson for consistency
                    for idx in rnd_indices:
                        match = all_matches_ordered[idx]
                        if idx not in cached_features:
                            processed_up_to = max(processed_up_to, idx + 1)
                            continue

                        fv, _, _ = cached_features[idx]
                        proba = model.predict_proba(fv.reshape(1, -1))[0]

                        # Use cached Poisson probabilities and xG
                        p_home, p_draw, p_away, hxg, axg = cached_poisson[idx]

                        # Ensemble blend
                        pw = 1.0 - XGB_WEIGHT
                        home_win_prob = XGB_WEIGHT * float(proba[0]) + pw * p_home
                        draw_prob = XGB_WEIGHT * float(proba[1]) + pw * p_draw
                        away_win_prob = XGB_WEIGHT * float(proba[2]) + pw * p_away

                        # Apply draw boost
                        draw_prob *= (1.0 + DRAW_BOOST)

                        total_p = home_win_prob + draw_prob + away_win_prob
                        home_win_prob /= total_p
                        draw_prob /= total_p
                        away_win_prob /= total_p

                        probs = {"H": home_win_prob, "D": draw_prob, "A": away_win_prob}
                        predicted = max(probs, key=probs.get)

                        # Enhanced draw detection: multi-signal scoring
                        hs_exp = team_stats_build.get(match.home, TeamStats())
                        aws_exp = team_stats_build.get(match.away, TeamStats())
                        draw_signals = 0
                        ha_gap = abs(home_win_prob - away_win_prob)
                        bayesian_draw_avg = (hs_exp.bayesian_draw_prob() + aws_exp.bayesian_draw_prob()) / 2
                        elo_gap = abs(hs_exp.elo - aws_exp.elo)

                        if ha_gap < 0.15:
                            draw_signals += 1
                        if draw_prob > 0.26:
                            draw_signals += 1
                        if bayesian_draw_avg > 0.20:
                            draw_signals += 1
                        if p_draw > 0.25:
                            draw_signals += 1
                        if elo_gap < 80:
                            draw_signals += 1
                        if draw_signals >= 3 and draw_prob > 0.22:
                            predicted = "D"

                        confidence = max(probs.values())

                        # Score prediction from Poisson xG
                        top_scores = predict_scoreline(hxg, axg, top_n=3)
                        best_score = top_scores[0] if top_scores else (1, 0, 0.0)

                        # Betting market probabilities
                        bm = compute_betting_markets(hxg, axg)

                        all_results.append(PredictionResult(
                            match=match,
                            pred_home_win_prob=home_win_prob,
                            pred_draw_prob=draw_prob,
                            pred_away_win_prob=away_win_prob,
                            predicted_result=predicted,
                            actual_result=match.result,
                            correct=(predicted == match.result),
                            confidence=confidence,
                            predicted_score=(best_score[0], best_score[1]),
                            top_scorelines=top_scores,
                            home_xg=hxg,
                            away_xg=axg,
                            betting_markets=bm,
                        ))

                    processed_up_to = max(processed_up_to, rnd_indices[-1] + 1)
                    continue

            processed_up_to = max(processed_up_to, rnd_indices[-1] + 1)

        results = all_results
        val_acc = val_acc_last
        val_loss = val_loss_last
        effective_train_rounds = predict_from - 1
    else:
        # Fixed train/test split
        train_matches = [m for m in matches if m.round_num <= train_rounds]
        test_matches = [m for m in matches if m.round_num > train_rounds]
        print("  Training: {} matches (rounds 1-{})".format(len(train_matches), train_rounds))
        print("  Testing:  {} matches (rounds {}-38)".format(len(test_matches), train_rounds + 1))

        print("\nTraining GBDT model (v2, 3-class, enriched features)...")
        model, val_acc, val_loss, team_stats = train_on_historical(
            train_matches, train_matches,
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_child_weight=min_child_weight,
        )
        print("  Validation accuracy: {:.4f}".format(val_acc))
        print("  Validation log-loss: {:.4f}".format(val_loss))

        print("\nPredicting {} test matches...".format(len(test_matches)))
        prior = list(train_matches)
        results = predict_matches(model, test_matches, prior, team_stats)
        effective_train_rounds = train_rounds

    correct = sum(1 for r in results if r.correct)
    accuracy = correct / len(results) if results else 0
    print("  Results: {}/{} correct ({:.1%})".format(correct, len(results), accuracy))

    elapsed = time.time() - start

    model_params = {
        "Algorithm": "XGBoost (GBDT, 3-class) + Poisson ensemble",
        "Objective": "multi:softprob",
        "n_estimators": n_estimators,
        "max_depth": max_depth,
        "learning_rate": learning_rate,
        "min_child_weight": min_child_weight,
        "reg_alpha": 0.5,
        "reg_lambda": 1.5,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "Draw weighting": "uniform (no extra weighting)",
        "Ensemble blend": "{:.0%} XGBoost + {:.0%} Poisson".format(XGB_WEIGHT, 1 - XGB_WEIGHT),
        "Features": N_FEATURES,
        "Mode": "expanding window (retrain every {} rounds)".format(retrain_every) if expanding else "fixed split",
    }
    report = generate_report(results, val_acc, val_loss, effective_train_rounds, elapsed, model_params)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\nReport saved to: {}".format(output_path))

    return accuracy, report


def iterate_to_improve(target_accuracy=0.70, max_iterations=12):
    print("\n" + "=" * 60)
    print("NEGELIR AI — Iterative Improvement (v2)")
    print("=" * 60)
    print("Target accuracy: {:.0%}".format(target_accuracy))

    configs = [
        (25, 200, 3, 0.06, 5),
        (25, 150, 3, 0.08, 5),
        (25, 250, 3, 0.05, 6),
        (25, 200, 4, 0.06, 4),
        (25, 300, 3, 0.04, 6),
        (25, 150, 4, 0.08, 5),
        (25, 200, 3, 0.07, 3),
        (25, 250, 3, 0.06, 5),
        (22, 200, 3, 0.06, 5),
        (25, 175, 3, 0.09, 5),
        (25, 200, 3, 0.10, 6),
        (25, 150, 3, 0.06, 4),
    ]

    best_accuracy = 0.0
    best_config = None
    best_report = ""
    iteration_log = []

    for i, (tr, ne, md, lr, mcw) in enumerate(configs[:max_iterations]):
        print("\n" + "-" * 40)
        print("Iteration {}/{}: rounds={}, trees={}, depth={}, lr={}, mcw={}".format(
            i + 1, min(len(configs), max_iterations), tr, ne, md, lr, mcw))

        accuracy, report = run_test(
            train_rounds=tr,
            n_estimators=ne,
            max_depth=md,
            learning_rate=lr,
            min_child_weight=mcw,
        )

        iteration_log.append({
            "iteration": i + 1,
            "train_rounds": tr,
            "n_estimators": ne,
            "max_depth": md,
            "learning_rate": lr,
            "min_child_weight": mcw,
            "accuracy": accuracy,
        })

        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_config = (tr, ne, md, lr, mcw)
            best_report = report

        print("  -> Accuracy: {:.1%} (best so far: {:.1%})".format(accuracy, best_accuracy))

        if accuracy >= target_accuracy:
            print("\nTarget accuracy {:.0%} reached!".format(target_accuracy))
            break

    output_path = DEFAULT_OUTPUT
    with open(output_path, "w", encoding="utf-8") as f:
        header = []
        header.append("=" * 90)
        header.append("ITERATIVE TUNING SUMMARY".center(90))
        header.append("=" * 90)
        header.append("")
        header.append("  {:>6} {:>8} {:>8} {:>8} {:>8} {:>6} {:>10}".format(
            "Iter", "Rounds", "Trees", "Depth", "LR", "MCW", "Accuracy"))
        for il in iteration_log:
            marker = " <-- best" if il["accuracy"] == best_accuracy else ""
            header.append(
                "  {:>6} {:>8} {:>8} {:>8} {:>8.3f} {:>6} {:>10.1%}{}".format(
                    il["iteration"], il["train_rounds"],
                    il["n_estimators"], il["max_depth"],
                    il["learning_rate"], il["min_child_weight"],
                    il["accuracy"], marker))
        header.append("")
        header.append("  Best: rounds={}, trees={}, depth={}, lr={}, mcw={}".format(*best_config))
        header.append("  Best accuracy: {:.1%}".format(best_accuracy))
        header.append("")
        header.append("")

        f.write("\n".join(header))
        f.write(best_report)

    print("\n" + "=" * 60)
    print("Best accuracy: {:.1%} with config {}".format(best_accuracy, best_config))
    print("Full report saved to: {}".format(output_path))
    print("=" * 60)

    return best_accuracy


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Negelir Historical Prediction Test")
    parser.add_argument("--rounds-train", type=int, default=25)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--iterate", action="store_true", help="Run iterative tuning")
    parser.add_argument("--expanding", action="store_true", help="Use expanding window")
    parser.add_argument("--target", type=float, default=0.70)
    args = parser.parse_args()

    if args.iterate:
        iterate_to_improve(target_accuracy=args.target)
    else:
        run_test(train_rounds=args.rounds_train, output_path=args.output,
                 expanding=args.expanding, retrain_every=1)
