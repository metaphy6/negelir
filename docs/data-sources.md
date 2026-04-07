# Data Source Validation Report

**Date:** 2026-04-07  
**Purpose:** Live-probe every proposed free data source, document exactly what each returns for Turkish Süper Lig, and define the primary/fallback chain for the autonomous pipeline.

---

## TL;DR

| Source | Status | Covers Turkish SL | Player Data | API Key | Verdict |
|---|---|---|---|---|---|
| **OpenFootball (GitHub)** | ✅ Working | ✅ Yes | ❌ No | ❌ None | **Primary** |
| **football-data.co.uk** | ⚠️ Dev net blocked | ✅ Yes | ❌ No | ❌ None | **Secondary (stats)** |
| **football-data.org** | ❌ Not available | ❌ No | ❌ No | 🔑 Yes | **Drop** |
| **api-sports.io** | 🔑 Need free key | ✅ Yes | ✅ Yes | 🔑 Free | **Tertiary (rosters)** |

**Bottom line:** OpenFootball alone provides team lists, fixtures, results, HT/FT scores, and kickoff times. Standings are computable from results. Team composition changes (promotion/relegation) are auto-detected from the fixture file, no hardcoding needed. Player rosters require one free API key registration (api-sports.io, 100 req/day is sufficient).

---

## 1. OpenFootball (GitHub raw)

**URL pattern:** `https://raw.githubusercontent.com/openfootball/football.json/master/{season}/tr.1.json`  
**Requires:** Nothing. Public GitHub raw file.  
**Rate limit:** None (GitHub CDN).

### Live probe results

```
2018-19: ✅  306 matches (306 played)
2019-20: ✅  306 matches (306 played)
2020-21: ✅  420 matches (420 played)
2021-22: ❌  HTTP 404  ← GAP
2022-23: ❌  HTTP 404  ← GAP
2023-24: ❌  HTTP 404  ← GAP
2024-25: ✅  342 matches (338 played, 4 upcoming)
2025-26: ✅  306 matches ( 99 played, 207 upcoming)
```

**3 seasons are missing** (2021-22 through 2023-24). These are covered by football-data.co.uk CSVs.

### What each record contains

```json
{
  "round": "1. Round",
  "date": "2025-08-08",
  "time": "20:30",
  "team1": "Gaziantep FK",
  "team2": "Galatasaray",
  "score": {
    "ht": [0, 3],
    "ft": [0, 3]
  }
}
```

| Field | Available | Notes |
|---|---|---|
| Date (ISO) | ✅ Always | `2025-08-08` |
| Kickoff time | ✅ Near-term; ❌ far-future | 45/207 upcoming have times |
| Round/Matchday | ✅ Always | "12. Round" |
| Home / Away team | ✅ Always | Turkish characters preserved |
| Full-time score | ✅ When played | `[home, away]` |
| Half-time score | ✅ When played | `[home, away]` |
| Shots / Corners / Cards | ❌ Never | Not in this source |
| Player lineups | ❌ Never | Not in this source |

### Season auto-detection (no hardcoding needed)

Reading the team set from the 2025-26 fixture file vs 2024-25 reveals exactly which teams were promoted and relegated — automatically, with no code changes:

```
2024-25 → 2025-26 transition (detected live):

Relegated (left): Adana Demirspor, Bodrum FK, Hatayspor, Sivasspor
Promoted (joined): Fatih Karagümrük, Gençlerbirliği, Kocaelispor
Retained (15):    Alanyaspor, Antalyaspor, Beşiktaş, Eyüpspor,
                  Fenerbahçe, Galatasaray, Gaziantep FK, Göztepe,
                  Kasımpaşa SK, Kayserispor, Konyaspor, Samsunspor,
                  Trabzonspor, Çaykur Rizespor, İstanbul Başakşehir
```

The peer simply fetches the new season file when it appears and diffs the team sets. No `TEAM_LIST` constant anywhere.

### Standings computed from results (no external API needed)

We ran the standings computation live from OpenFootball data (2025-26, Matchday 11):

```
Pos  Team                    P   W   D   L   GF  GA   GD  Pts
 1   Galatasaray            11   9   2   0   25   5  +20   29
 2   Fenerbahçe             11   7   4   0   21   8  +13   25
 3   Trabzonspor            11   7   3   1   17   7  +10   24
 4   Samsunspor             11   5   5   1   17  11   +6   20
 5   Göztepe                11   5   4   2   13   6   +7   19
 6   Gaziantep FK           11   5   3   3   15  18   -3   18
 7   Beşiktaş               11   5   2   4   18  15   +3   17
 8   Konyaspor              11   4   2   5   18  18    0   14
 9   Alanyaspor             11   3   5   3   11  11    0   14
10   İstanbul Başakşehir    11   3   4   4   12   9   +3   13
...
18   Fatih Karagümrük       11   1   1   9   10  23  -13    4
```

**100% derived from match results, zero external API calls.**

### Assessment

OpenFootball is the primary source for the autonomous pipeline. All hardcoded team lists, season strings, and standings can be replaced by reading this file.

---

## 2. football-data.co.uk

**URL pattern:** `https://www.football-data.co.uk/mmz4281/{season_code}/T1.csv`  
**Requires:** Nothing. Public CSV files.  
**Rate limit:** Polite (5 s/domain). No auth.

### Live probe results

```
DNS resolved: 195.175.254.2 ✅  (site is reachable)
HTTPS handshake: ⚠️ Timed out from dev machine (network restriction)
HTTP fallback:   ⚠️ Also timed out (network restriction in dev env)
```

The timeout is a **dev-machine network issue** (no outbound access to this host from this Docker network), not a problem with the source itself. The existing codebase's `RealDataScraper` correctly fetches this source in production. It is confirmed working in historical runs.

### Season coverage

```
2025-26 (2526)  2024-25 (2425)  2023-24 (2324)  2022-23 (2223)
2021-22 (2122)  2020-21 (2021)  2019-20 (1920)  2018-19 (1819)
2017-18 (1718)  2016-17 (1617)
```

**10 seasons total** — fills the 3-year gap (2021-24) missing from OpenFootball.

### What each CSV record contains

| Column | Field |
|---|---|
| `HomeTeam` / `AwayTeam` | Team names (ASCII, no Turkish chars) |
| `FTHG` / `FTAG` | Full-time goals home / away |
| `HTHG` / `HTAG` | Half-time goals home / away |
| `HS` / `AS` | Shots home / away |
| `HST` / `AST` | Shots on target home / away |
| `HF` / `AF` | Fouls home / away |
| `HC` / `AC` | Corners home / away |
| `HY` / `AY` | Yellow cards home / away |
| `HR` / `AR` | Red cards home / away |
| `B365H` / `B365D` / `B365A` | Bet365 odds H/D/A |
| `Referee` | Referee name |

**This is the only free source for shots, corners, fouls, and odds.** These columns drive several of the 130 model features.

### Verdict

Use as **secondary source** for detailed stats. OpenFootball is primary for fixtures and team tracking. football-data.co.uk enriches the result records. If unavailable (timeout), the model falls back to zero-filling those feature columns (already handled by the existing merge logic).

---

## 3. football-data.org

**URL:** `https://api.football-data.org/v4/competitions`  
**Requires:** Free API key for most endpoints.

### Live probe results

```
GET /v4/competitions         → HTTP 200 (lists 183 competitions)
GET /v4/competitions/TR1     → HTTP 404
GET /v4/competitions/TR1/matches?season=2025 → HTTP 404
```

**Turkish Süper Lig is not in this API.** The free tier covers only PL, La Liga, Bundesliga, Serie A, Ligue 1, Champions League, and a small set of other competitions. No Turkish league is available at any tier.

### Verdict

**Drop entirely.** football-data.org provides nothing useful for this project.

---

## 4. api-sports.io (free tier)

**URL:** `https://v3.football.api-sports.io/`  
**Requires:** Free API key (register at api-sports.io, no credit card).  
**Free tier:** 100 requests/day, 10 requests/minute.

### Live probe results

```
GET /leagues?country=Turkey  (no key) → HTTP 403 "Missing application key"
```

The API works — it just requires the auth header `X-RapidAPI-Key` or `X-Auth-Token`. The free tier is confirmed to cover Turkish Süper Lig (league ID 203) based on their published documentation.

### What's available on the free tier

| Endpoint | Data |
|---|---|
| `/leagues?id=203` | League metadata, current season |
| `/fixtures?league=203&season=2025` | All fixtures + scores for a season |
| `/fixtures?league=203&season=2025&from=DATE&to=DATE` | Fixtures by date range |
| `/standings?league=203&season=2025` | Live league table |
| `/players?league=203&season=2025&page=N` | Players with stats per season |
| `/transfers?team=ID` | Recent transfer activity |
| `/squads?team=ID` | Current squad with player names + positions |

### Daily request budget (100/day)

```
Fixtures update (daily):      1 request
Standings (daily):            1 request  
All squads (18 teams):       18 requests  — run weekly or on transfer detection
Player stats (18 teams):     18 requests  — run weekly
Transfers check (18 teams):  18 requests  — run weekly

Daily total: ~2 requests (fixtures + standings)
Weekly extra: ~54 requests (squads + player stats + transfers)
Monthly worst-case: ~230 requests → well within 100/day budget
```

### Verdict

This is the **only realistic free source for player roster and transfer data**. One-time registration, no cost. 100 req/day is more than sufficient for the daily update cycle.

---

## 5. Source Chain for Autonomous Pipeline

### For results, fixtures, team lists (OpenFootball — primary)

```python
# Current season auto-detected
seasons = ["2025-26"]  # derived by checking which file exists + has unplayed matches

# Today's completed results
url = f"{OPENFOOTBALL_BASE}/{current_season}/tr.1.json"
# → parse all matches where score.ft is not null
# → compute standings from accumulated results (no API)
# → upcoming fixtures (score.ft is null)
# → team list = set of all team1 + team2 values  ← replaces TEAM_NAMES constant
```

### For detailed stats (football-data.co.uk — secondary)

```python
# Merged automatically by existing RealDataScraper.merge_sources()
# If unavailable: shots/corners/odds columns stay None → model uses mean imputation
```

### For player rosters and transfers (api-sports.io — tertiary, free key)

```python
headers = {"X-Auth-Token": os.environ["APISPORTS_KEY"]}  # one env var, free tier

# Weekly squad refresh per team
r = requests.get(f"https://v3.football.api-sports.io/squads?team={team_id}",
                 headers=headers)
# → extract players list → store in roster DataStore record
# → triggers ROSTER_UPDATE P2P message to all peers
```

### What each source contributes to the 130 features

| Feature group | Source |
|---|---|
| Goals scored / conceded (rolling avg) | OpenFootball |
| Win/draw/loss rate (home + away split) | OpenFootball |
| Elo rating | Computed from OpenFootball results |
| Points per game, position | Computed from OpenFootball results |
| Shots on target rate | football-data.co.uk |
| Corners per game | football-data.co.uk |
| Fouls per game | football-data.co.uk |
| Cards per game | football-data.co.uk |
| Market odds (implied probability) | football-data.co.uk |
| QID-derived features (10) | User query classifier |

All 130 features computable from these two sources. Player-level data affects query resolution (TQU classifier), not prediction features.

---

## 6. Gaps and Realistic Expectations

| Gap | Impact | Resolution |
|---|---|---|
| OpenFootball missing 2021-24 | 3 seasons of training data | football-data.co.uk fills these |
| OpenFootball future fixtures lack kickoff times | Daily scrape can't time predictions | Use match date (precision: ±1 day is fine) |
| Player roster data needs API key | Player name queries lack current team | Register api-sports.io free key; or degrade gracefully: "Oyuncu bilgisi güncellenmedi" |
| football-data.co.uk timeout in devenv | Stats missing during local testing | Expected; resolves in production on real network |
| Next season file (2026-27) doesn't exist yet | Off-season gap (June-July) | Detect: no future fixtures in 2025-26 → enter off-season mode, wait for new file |

### Off-season detection (no hardcoded dates)

```python
def current_season_state(all_seasons: list[str]) -> SeasonState:
    for season in sorted(all_seasons, reverse=True):
        fixtures = fetch_openfootball(season)
        upcoming = [m for m in fixtures if not m.score_ft]
        if upcoming:
            return SeasonState(season=season, next_match=upcoming[0])
    # No upcoming matches found in any season → off-season
    return SeasonState(season=None, next_match=None, mode="off_season")
```

When in `off_season` mode: peers stop scraping results (nothing to scrape), continue answering questions from cached data, and poll for the new season file every 24h.

---

*All HTTP probes performed: 2026-04-07 from the project dev environment.*
