#!/usr/bin/env python3
"""
Generate realistic Turkish Super Lig match data for historical prediction testing.

Uses known team strength tiers + Poisson score generation + realistic
card/discipline patterns. Output: data/tr_super_lig_2024_25.json

This is a PoC data generator, NOT real scraped data.
Teams and strength values are loaded from ai/common/locale_tr.yaml (single source of truth).
"""

import json
import math
import os
import random
import sys
from datetime import datetime, timedelta

import numpy as np
from scipy.stats import poisson

# ── Load teams from locale YAML (single source of truth) ─
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "ai"))

import yaml

def _load_teams_from_locale():
    locale_path = os.path.join(_PROJECT_ROOT, "ai", "common", "locale_tr.yaml")
    with open(locale_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    teams = []
    strength = {}
    derby_uuids = data.get("derbies", [])
    uuid_to_name = {}
    for uuid, info in data.get("teams", {}).items():
        name = info.get("display_name")
        if not name:
            continue
        uuid_to_name[uuid] = name
        s = info.get("strength")
        if s:
            teams.append(name)
            strength[name] = (s.get("attack", 1.0), s.get("defense", 1.0))
    derbies = set()
    for pair in derby_uuids:
        if len(pair) == 2:
            a = uuid_to_name.get(pair[0])
            b = uuid_to_name.get(pair[1])
            if a and b:
                derbies.add(frozenset((a, b)))
    return teams, strength, derbies

SEED = 2024
random.seed(SEED)
np.random.seed(SEED)

TEAMS, TEAM_STRENGTH, DERBIES = _load_teams_from_locale()

LEAGUE_AVG_GOALS = 1.35  # Per team per match (Turkish league average ~2.7 total)
HOME_ADVANTAGE = 0.25    # Extra xG for home team


def generate_fixtures():
    """Generate a full season fixture list (each pair plays twice: home & away)."""
    n = len(TEAMS)
    fixtures = []
    
    # Round-robin: each team plays every other team twice
    pairs = []
    for i in range(n):
        for j in range(n):
            if i != j:
                pairs.append((TEAMS[i], TEAMS[j]))
    
    # Shuffle and assign to matchdays
    random.shuffle(pairs)
    
    # 38 matchdays, ~9-10 games each (19 teams: 9 games + 1 bye per week)
    matchday = 1
    games_per_week = n // 2  # 9 games
    
    # Track each team's last assigned matchday to avoid double-booking
    team_last_md = {t: 0 for t in TEAMS}
    assigned = set()
    
    for md in range(1, 39):
        games_this_week = []
        teams_used = set()
        
        for home, away in pairs:
            if (home, away) in assigned:
                continue
            if home in teams_used or away in teams_used:
                continue
            # Make sure some spacing between first and second leg
            if (away, home) in assigned:
                # This is the return leg — ensure at least 8 rounds gap
                first_leg_md = next((m for m, h, a in fixtures if h == away and a == home), None)
                if first_leg_md is not None and md - first_leg_md < 8:
                    continue
            
            games_this_week.append((md, home, away))
            teams_used.add(home)
            teams_used.add(away)
            assigned.add((home, away))
            
            if len(games_this_week) >= games_per_week:
                break
        
        fixtures.extend(games_this_week)
    
    # Assign any remaining unassigned pairs
    remaining = [(h, a) for h, a in pairs if (h, a) not in assigned]
    md = max(f[0] for f in fixtures) if fixtures else 1
    for home, away in remaining:
        md += 1
        fixtures.append((md, home, away))
    
    return fixtures


def simulate_match(home, away, matchday):
    """Simulate a single match using Poisson model with realistic parameters."""
    h_att, h_def = TEAM_STRENGTH[home]
    a_att, a_def = TEAM_STRENGTH[away]
    
    is_derby = frozenset({home, away}) in DERBIES
    
    # Expected goals
    home_xg = LEAGUE_AVG_GOALS * h_att * a_def + HOME_ADVANTAGE
    away_xg = LEAGUE_AVG_GOALS * a_att * h_def
    
    # Add some randomness
    home_xg *= np.random.uniform(0.75, 1.25)
    away_xg *= np.random.uniform(0.75, 1.25)
    
    home_xg = max(0.3, home_xg)
    away_xg = max(0.2, away_xg)
    
    # Generate goals from Poisson
    home_goals = int(np.random.poisson(home_xg))
    away_goals = int(np.random.poisson(away_xg))
    
    # Cap at reasonable values
    home_goals = min(home_goals, 7)
    away_goals = min(away_goals, 6)
    
    # Half-time: ~47% of goals in first half
    ht_home = sum(1 for _ in range(home_goals) if random.random() < 0.47)
    ht_away = sum(1 for _ in range(away_goals) if random.random() < 0.47)
    
    # Stats
    total_goals = home_goals + away_goals
    home_poss = int(np.clip(np.random.normal(
        50 + 5 * (h_att - a_att), 8), 30, 70))
    
    home_shots_on = max(1, int(np.random.poisson(max(1, home_xg * 2.5))))
    away_shots_on = max(0, int(np.random.poisson(max(1, away_xg * 2.5))))
    home_shots_off = max(0, int(np.random.poisson(max(1, home_xg * 2.0))))
    away_shots_off = max(0, int(np.random.poisson(max(1, away_xg * 2.0))))
    
    home_corners = max(0, int(np.random.poisson(max(1, 3.0 + h_att))))
    away_corners = max(0, int(np.random.poisson(max(1, 2.5 + a_att))))
    
    # Fouls and cards
    base_fouls = 13 if not is_derby else 16
    home_fouls = max(5, int(np.random.poisson(base_fouls)))
    away_fouls = max(5, int(np.random.poisson(base_fouls + 1)))  # away teams foul slightly more
    
    # Cards from fouls: ~1 yellow per 3.5 fouls
    card_rate = 3.2 if is_derby else 3.5
    home_yellows = max(0, min(6, int(np.random.poisson(home_fouls / card_rate))))
    away_yellows = max(0, min(6, int(np.random.poisson(away_fouls / card_rate))))
    
    # Red cards: rare, more likely in derbies
    home_reds = 1 if random.random() < (0.06 if is_derby else 0.03) else 0
    away_reds = 1 if random.random() < (0.06 if is_derby else 0.03) else 0
    
    return {
        "home_goals": home_goals,
        "away_goals": away_goals,
        "ht_home": ht_home,
        "ht_away": ht_away,
        "home_poss": home_poss,
        "away_poss": 100 - home_poss,
        "home_shots_on": home_shots_on,
        "away_shots_on": away_shots_on,
        "home_shots_off": home_shots_off,
        "away_shots_off": away_shots_off,
        "home_corners": home_corners,
        "away_corners": away_corners,
        "home_fouls": home_fouls,
        "away_fouls": away_fouls,
        "home_yellows": home_yellows,
        "away_yellows": away_yellows,
        "home_reds": home_reds,
        "away_reds": away_reds,
        "is_derby": is_derby,
    }


def generate_dataset():
    fixtures = generate_fixtures()
    
    # Sort by matchday
    fixtures.sort(key=lambda x: x[0])
    
    # Assign dates: season starts mid-August 2024
    start_date = datetime(2024, 8, 16)
    matches = []
    
    current_md = 0
    current_date = start_date
    
    for md, home, away in fixtures:
        if md != current_md:
            if current_md > 0:
                # ~7 days between matchdays, with some variation
                gap = random.choice([6, 7, 7, 7, 8])
                current_date += timedelta(days=gap)
            current_md = md
        else:
            # Same matchday: games spread over 2-3 days
            current_date += timedelta(hours=random.choice([0, 0, 24, 24, 48]))
        
        result = simulate_match(home, away, md)
        
        match_record = {
            "date": current_date.strftime("%Y-%m-%d"),
            "round": f"Matchday {md}",
            "team1": home,
            "team2": away,
            "score": {
                "ft": [result["home_goals"], result["away_goals"]],
                "ht": [result["ht_home"], result["ht_away"]],
            },
            "stats": {
                "home_possession": result["home_poss"],
                "away_possession": result["away_poss"],
                "home_shots_on": result["home_shots_on"],
                "away_shots_on": result["away_shots_on"],
                "home_shots_off": result["home_shots_off"],
                "away_shots_off": result["away_shots_off"],
                "home_corners": result["home_corners"],
                "away_corners": result["away_corners"],
                "home_fouls": result["home_fouls"],
                "away_fouls": result["away_fouls"],
                "home_yellows": result["home_yellows"],
                "away_yellows": result["away_yellows"],
                "home_reds": result["home_reds"],
                "away_reds": result["away_reds"],
            },
        }
        matches.append(match_record)
    
    dataset = {
        "league": "Turkish Super Lig",
        "season": "2024-2025",
        "generated": True,
        "seed": SEED,
        "total_matches": len(matches),
        "teams": TEAMS,
        "matches": matches,
    }
    
    return dataset


def main():
    print("Generating Turkish Super Lig 2024-25 match data...")
    dataset = generate_dataset()
    
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tr_super_lig_2024_25.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    
    # Stats
    total = len(dataset["matches"])
    home_wins = sum(1 for m in dataset["matches"] if m["score"]["ft"][0] > m["score"]["ft"][1])
    draws = sum(1 for m in dataset["matches"] if m["score"]["ft"][0] == m["score"]["ft"][1])
    away_wins = total - home_wins - draws
    total_goals = sum(m["score"]["ft"][0] + m["score"]["ft"][1] for m in dataset["matches"])
    total_yellows = sum(m["stats"]["home_yellows"] + m["stats"]["away_yellows"] for m in dataset["matches"])
    total_reds = sum(m["stats"]["home_reds"] + m["stats"]["away_reds"] for m in dataset["matches"])
    
    print(f"  Total matches: {total}")
    print(f"  Home wins: {home_wins} ({home_wins/total:.1%})")
    print(f"  Draws:     {draws} ({draws/total:.1%})")
    print(f"  Away wins: {away_wins} ({away_wins/total:.1%})")
    print(f"  Avg goals/match: {total_goals/total:.2f}")
    print(f"  Avg yellows/match: {total_yellows/total:.1f}")
    print(f"  Avg reds/match: {total_reds/total:.2f}")
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
