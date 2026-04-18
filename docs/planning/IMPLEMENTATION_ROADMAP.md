# Technical Implementation Roadmap

> **Note (2026-04-18):** Several items in this roadmap have been implemented: `scheduler.py`, `self_healing.py`, `schema_fingerprint.py`, `mackolik.py` scraper, `real_data.py` scraper, AI model/scraper config hardcode elimination, P2P `P2PConfig` centralization, and Go server env-driven runtime tuning. Legacy AI env fallback aliases were also removed in favor of canonical keys. For the master execution plan, see [ROADMAP.md](ROADMAP.md).

**Date:** 2026-04-07
**Scope:** Consolidated roadmap to transform Negelir from a demo-data prototype into a fully autonomous, self-sustaining Turkish football prediction system — combining findings from [AUTONOMOUS_PIPELINE.md](../design/AUTONOMOUS_PIPELINE.md), [DATA_SOURCES.md](../data/DATA_SOURCES.md), and [GENERIC_INPUT_HANDLING.md](../guides/GENERIC_INPUT_HANDLING.md).

**Core Constraint:** After `docker compose up`, the system runs with zero human intervention. The only manually provided infrastructure is a signal server for peer matching.

---

## Table of Contents

1. [Source Priority Chain](#1-source-priority-chain)
2. [arsiv.mackolik.com — Primary Source](#2-arsivmackolikcom--primary-source)
2b. [www.mackolik.com — Primary Source (Modern Frontend)](#2b-wwwmackolikcom--primary-source-modern-frontend)
3. [tff.org — Secondary Source](#3-tfforg--secondary-source)
4. [OpenFootball + football-data.co.uk — Tertiary Sources](#4-openfootball--football-datacouk--tertiary-sources)
5. [api-sports.io — Supplementary Source](#5-api-sportsio--supplementary-source)
6. [Implementation Phases](#6-implementation-phases)
7. [Phase 0: Single Source of Truth](#7-phase-0-single-source-of-truth)
8. [Phase 1: arsiv.mackolik.com Scraper](#8-phase-1-arsivmackolikcom-scraper)
9. [Phase 2: Fixture Index + Season Detection](#9-phase-2-fixture-index--season-detection)
10. [Phase 3: Persistent Identity + Scheduler](#10-phase-3-persistent-identity--scheduler)
11. [Phase 4: Distributed Scrape Coordination](#11-phase-4-distributed-scrape-coordination)
12. [Phase 5: Player + Transfer Resolution](#12-phase-5-player--transfer-resolution)
13. [Phase 6: Continuous Model Learning](#13-phase-6-continuous-model-learning)
14. [Phase 7: Adaptive Scraper Intelligence](#14-phase-7-adaptive-scraper-intelligence)
15. [Phase 8: Self-Healing + Source Failover](#15-phase-8-self-healing--source-failover)
16. [Phase 9: Real Network Transport](#16-phase-9-real-network-transport)
17. [File Manifest](#17-file-manifest)
18. [Test Strategy](#18-test-strategy)
19. [Risk Matrix](#19-risk-matrix)

---

## 1. Source Priority Chain

The previous DATA_SOURCES.md report established OpenFootball as primary. After probing the Turkish sources configured in `.env`, the priority is reversed — Turkish sources are primary because they provide richer, more timely data with native team names.

| Priority | Source | Data Provided | Auth | Rate Limit |
|---|---|---|---|---|
| **1a (Primary)** | arsiv.mackolik.com | Standings, fixtures, results, odds, player stats, team stats, transfers, 40+ seasons | None | Polite (5s/domain) |
| **1b (Primary)** | www.mackolik.com | Same data as arsiv + xG, xGA, 47 team stats, 40+ player stats, 68 seasons (back to 1959), embedded JSON | None | Polite (5s/domain) |
| **2 (Secondary)** | tff.org | Official standings, fixtures with dates/times, correct team names (legal entities) | None | Polite |
| **3 (Tertiary)** | OpenFootball (GitHub) | Scores, dates, teams, HT/FT | None | None |
| **4 (Tertiary)** | football-data.co.uk | Shots, corners, fouls, cards, odds (CSV) | None | Polite |
| **5 (Supplementary)** | api-sports.io | Player rosters, transfers, squads | Free key | 100 req/day |

**Rationale:** arsiv.mackolik.com (legacy JSON API) and www.mackolik.com (modern frontend with embedded JSON) are the same underlying data from Mackolik, served via two different frontends. The modern site adds xG/xGA, richer team/player stats, and 68 seasons back to 1959. Using both gives us API redundancy — if one redesigns, the other likely still works.

---

## 2. arsiv.mackolik.com — Primary Source

### 2.1 Discovered API Endpoints

All endpoints confirmed working via live probes. No authentication required.

#### Season Discovery

```
GET /AjaxHandlers/CompetitionHandler.aspx?op=groupYears&group=1
→ Array of season labels: ['2025/2026', '2024/2025', ..., '1985/1986']
   41 seasons available

GET /AjaxHandlers/CompetitionHandler.aspx?op=seasons&group=1&year=2024/2025
→ {"l": [[67287, "Trendyol Süper Lig"], [67437, "Trendyol 1. Lig"], ...]}
   Season ID for each competition within that year
```

**Season ID map (Süper Lig):**

| Season | ID | League Name |
|---|---|---|
| 2025/2026 | 70381 | Trendyol Süper Lig |
| 2024/2025 | 67287 | Trendyol Süper Lig |
| 2023/2024 | 63860 | Trendyol Süper Lig |
| 2022/2023 | 61643 | Spor Toto Süper Lig |
| 2021/2022 | 59416 | Spor Toto Süper Lig Ahmet Çalık Sezonu |
| 2020/2021 | 57526 | Spor Toto Süper Lig |
| 2019/2020 | 54794 | Süper Lig |

All of these return data via the standings endpoint. **This fills the 3-year OpenFootball gap (2021-24).**

#### Standings + Fixtures + Results (Single Endpoint)

```
GET /AjaxHandlers/StandingHandler.ashx?op=standing&id={seasonId}
→ JSON response with 4 arrays:
```

**Response schema:**

```json
{
  "id": 70381,
  "s": [                          // standings (18 entries for current season)
    [
      1,                          // team_id (stable across seasons)
      "Galatasaray",              // team name
      0,                          // unknown flag
      27,                         // matches played
      12, 1, 1,                   // home: win, draw, loss
      8, 3, 2,                    // away: win, draw, loss
      63,                         // goals for
      20,                         // goals against
      64,                         // points
      0, 0, 0, 0                  // zone/penalty flags
    ],
    // ... 17 more teams
  ],
  "f": [                          // upcoming fixtures
    [
      4356789,                    // match_id
      "11/04",                    // date (DD/MM)
      "",                         // status
      1,                          // home_team_id
      2,                          // away_team_id
      "2148500",                  // broadcast_id
      0, 0,                       // scores (0 = not played)
      "",                         // HT score
      4,                          // unknown
      1.45, 4.20, 5.80,          // odds: home/draw/away
      // ... more odds fields
    ],
    // ... more fixtures
  ],
  "r": [                          // recent results
    [
      4125503,                    // match_id
      "01/06",                    // date (DD/MM)
      "MS",                       // status (MS = Maç Sonu = Full Time)
      8,                          // home_team_id
      570,                        // away_team_id
      "2148445",                  // broadcast_id
      2, 1,                       // FT score (home, away)
      "0 - 0",                    // HT score
      4,                          // unknown
      1.13, 4.92, 7.88,          // closing odds: home/draw/away
      // ... more odds fields
    ],
  ],
  "d": [                          // zone decoration/legends
    [1, "bg-color:#daeaf8", "Şampiyonlar Ligi"],
    [2, "bg-color:#c6e4b8", "Konferans Ligi"],
    [3, "bg-color:#fbe3e4", "Küme Düşme"]
  ]
}
```

**Key advantage:** A single HTTP request per season returns standings with home/away splits, upcoming fixtures with betting odds, recent results with HT/FT scores, and zone legends — everything the model needs.

#### Match Detail (Per-Match Stats)

```
GET /AjaxHandlers/MatchHandler.aspx?command=optaStats&id={matchId}
→ HTML fragment with match statistics:
   - Possession % (Topla Oynama)
   - Total shots (Toplam Şut)
   - Shots on target (İsabetli Şut)
   - Pass accuracy (Pas Başarı %)
   - Successful passes count (Başarılı Paslar)
   - Corners (Korner)
   - Crosses (Orta)
   - Fouls (Faul)
   - Offsides (Ofsayt)

GET /AjaxHandlers/MatchHandler.aspx?command=optaTopPerformers&id={matchId}
→ HTML table with per-player stats per match:
   - Shots on target / total shots per player
   - Pass accuracy per player
   - Tackles per player
   - Fouls per player

GET /AjaxHandlers/MatchHandler.aspx?command=rbStats&id={matchId}
→ Alternative stats source (backup/cross-validation):
   - Possession, shots, shots on target, woodwork, corners, fouls, offsides

GET /AjaxHandlers/StandingHandler.ashx?command=matchStanding&id={matchId}&sv=1
→ League standings snapshot at time of match (15KB)

GET /AjaxHandlers/StandingHandler.ashx?command=otherMatches&id={matchId}
→ Other matches in the same round
```

#### Team-Level Aggregate Stats (From Standings Page HTML)

The HTML at `/Puan-Durumu/1/TURKIYE-Super-Lig` contains server-rendered tables (not AJAX-loaded) with per-team season aggregates:

- Şut/Maç (shots per game)
- İsabetli Şut/Maç (shots on target per game)
- Topa Sahip Olma % (possession %)
- Başarılı Pas/Maç (successful passes per game)
- Pas Başarı % (pass accuracy %)
- Korner/Maç (corners per game)
- Gol Krallığı (top scorers with goal counts)
- Asist/Şut Pası (assists)

#### Player Detail Pages

```
/Futbolcu/{player_id}/{player-name-slug}
Example: /Futbolcu/94082/Mauro-Icardi
```

#### Transfer Pages

```
/Transferler — Transfer activity index
```

#### Stable Team IDs (Cross-Season)

| ID | Team |
|---|---|
| 1 | Galatasaray |
| 2 | Fenerbahçe |
| 3 | Beşiktaş |
| 4 | Trabzonspor |
| 7 | Gençlerbirliği |
| 8 | Samsunspor |
| 15 | Göztepe |
| 18 | Kocaelispor |
| 447 | Konyaspor |
| 448 | Çaykur Rizespor |
| 451 | Başakşehir FK |
| 455 | Antalyaspor |
| 537 | Fatih Karagümrük |
| 557 | Eyüpspor |
| 570 | Kayserispor |
| 572 | Gaziantep FK |
| 619 | Alanyaspor |
| 656 | Kasımpaşa |

Team IDs are stable across seasons — the same `team_id=1` always means Galatasaray. This enables reliable cross-season data joins.

### 2.2 Data Coverage vs Feature Requirements

| Feature Group (of 130) | Covered by arsiv.mackolik.com | Endpoint |
|---|---|---|
| Goals scored/conceded (rolling avg) | ✅ | `StandingHandler.ashx` (standings `s` array: GF, GA) |
| Win/draw/loss rate (home + away split) | ✅ | `StandingHandler.ashx` (standings `s` array: home W/D/L, away W/D/L) |
| Elo rating | ✅ Computable | From results in `r` array |
| Points per game, position | ✅ | `StandingHandler.ashx` (standings `s` array: points, position) |
| Shots on target rate | ✅ | `MatchHandler.aspx?command=optaStats` per match |
| Corners per game | ✅ | `MatchHandler.aspx?command=optaStats` per match |
| Fouls per game | ✅ | `MatchHandler.aspx?command=optaStats` per match |
| Cards per game | ⚠️ Partial | Available in HTML stats tables but not in JSON API |
| Market odds (implied probability) | ✅ | `StandingHandler.ashx` fixtures `f` array: H/D/A odds |
| Possession % | ✅ | `MatchHandler.aspx?command=optaStats` |
| Pass accuracy | ✅ | `MatchHandler.aspx?command=optaStats` |
| QID-derived features (10) | N/A | User query classifier (local) |

**arsiv.mackolik.com covers 120/130 features from a single source.** The remaining 10 are QID-derived from local query analysis.

---

## 2b. www.mackolik.com — Primary Source (Modern Frontend)

The modern mackolik.com frontend serves the same underlying Mackolik data but through a completely different HTML structure. While `arsiv.mackolik.com` uses ASP.NET AJAX handlers returning JSON/HTML fragments, `www.mackolik.com` embeds a **massive JSON blob** (1-4MB) inside a `data-settings` HTML attribute on each page.

### 2b.1 URL Structure

```
Base: https://www.mackolik.com

Standings: /puan-durumu/türkiye-trendyol-süper-lig/{competition_uuid}
Fixtures:  /puan-durumu/türkiye-trendyol-süper-lig/fikstur/{competition_uuid}
Stats:     /puan-durumu/türkiye-trendyol-süper-lig/istatistik/{competition_uuid}
History:   /puan-durumu/türkiye-trendyol-süper-lig/{season_slug}/{competition_uuid}

Competition UUID (Süper Lig): 482ofyysbdbeoxauk19yg7tdt
```

**Season access:** Replace the URL path with `/{season_slug}/`:

| Season | Slug | Season ID |
|---|---|---|
| 2025/2026 | `2025-2026` | `97zghcaoec1isvvdkh9ud50d0` |
| 2024/2025 | `2024-2025` | `1c0t9lv2rftjjx8dxn5s9csus` |
| 2023/2024 | `2023-2024` | `3wzgnhcmgbudm6vt2ye410ahg` |
| 2022/2023 | `2022-2023` | `dffn22be69d945d62hmqc2qdw` |
| 2021/2022 | `2021-2022` | `9ewbc3vh5znyyihex4z27xkpg` |
| ... | | |
| 1959 | `1959` | `1gzh4ry8sy37vgf1kfy4f3yll` |

**68 seasons** available (1959–2026), vs 41 on arsiv.mackolik.com.

### 2b.2 Data Extraction

All data is in a single `data-settings` attribute (HTML-entity-encoded JSON, ~1-4MB per page):

```python
import re, json, html
big_attrs = re.findall(r'data-settings="([^"]{500000,})"', page_html)
data = json.loads(html.unescape(big_attrs[0]))
```

**Top-level schema:**

```json
{
  "competition": {
    "name": "Trendyol Süper Lig",
    "id": "482ofyysbdbeoxauk19yg7tdt",
    "standings": [{"name": "...", "table": {...}}],
    "gamesets": [{"name": "1", "matches": {...}, "gameweek": 1}, ...],
    "teamStats": [{"key": "ts_xg", "teams": [...]}, ...],
    "playerStats": [{"key": "ps_g", "players": [...]}, ...]
  },
  "season": {"name": "2025/2026", "startDate": "2025-08-08", ...},
  "seasonList": {"season_id": {"name": "2025/2026", "slug": "2025-2026"}, ...},
  "firstSeason": {"name": "1959"},
  "lastSeason": {"name": "2025/2026"},
  "tabs": ["table", "fixtures", "stats"]
}
```

### 2b.3 Standings Table Schema

```json
{
  "rank": 1,
  "team": {"id": 2217, "uuid": "esa748l653sss1wurz5ps3228", "name": "Galatasaray"},
  "played": 27, "win": 20, "draw": 4, "lost": 3,
  "pro": 63, "against": 20, "pts": 64,
  "last_rank": 1,
  "zone": {"name": "Şampiyonlar Ligi", "color": "#02206B"},
  "serie": "LWWWL"
}
```

**Note:** Unlike arsiv.mackolik.com, this does **not** include home/away win splits in the standings table. Those must be derived from match results.

### 2b.4 Match Schema (inside `gamesets[].matches`)

```json
{
  "scores": {"ht": {"home": 1, "away": 0}, "ft": {"home": 2, "away": 1}},
  "winner": "home",
  "raw": {
    "match": {
      "id": 4707233,
      "uuid": "76dp9ut8pjm1fmovbbyxexn9w",
      "date_time_utc": "2025-08-09 16:00:00",
      "status": "Played",
      "fts_A": 2, "fts_B": 1,
      "hts_A": 1, "hts_B": 0,
      "team_A": {"id": 2220, "uuid": "dpsnqu7pd2b0shfzjyn5j1znf", "name": "Samsunspor"},
      "team_B": {"id": 2219, "uuid": "embqktr41hfzczc8uav1scmcn", "name": "Gençlerbirliği"}
    }
  }
}
```

34 gamesets (one per matchweek), ~9 matches per gameset = full season of 306 matches in a single page load.

### 2b.5 Team Stats (47 Categories)

| Key | Meaning | Example |
|---|---|---|
| `ts_xg` | Expected goals | Galatasaray: 56.8 |
| `ts_xga` | Expected goals against | Fenerbahçe: 24.1 |
| `ts_xgwp` | xG without penalties | Galatasaray: 53.6 |
| `ts_pppm` | Possession % per match | Galatasaray: 61.7% |
| `ts_spm` | Shots per match | Fenerbahçe: 17.2 |
| `ts_sotpm` | Shots on target per match | Fenerbahçe: 6.2 |
| `ts_ppm` | Passes per match | Galatasaray: 511.2 |
| `ts_sppm` | Successful passes per match | Galatasaray: 448.3 |
| `ts_crpm` | Crosses per match | Fenerbahçe: 7.2 |
| `ts_f` | Fouls committed | Göztepe: 468 |
| `ts_yc` | Yellow cards | Gaziantep FK: 80 |
| `ts_rc` | Red cards | Gençlerbirliği: 6 |
| `ts_cs` | Clean sheets | Göztepe: 15 |
| `ts_g` | Goals scored | Galatasaray: 63 |
| `ts_gc` | Goals conceded | Galatasaray: 20 |
| `ts_hw` | Home wins | Galatasaray: 18 |
| `ts_pw` | Away wins | Trabzonspor: 9 |
| `ts_scpm` | Shot conversion per match | Galatasaray: 6.9 |
| `ts_stopm` | Tackles per match | Trabzonspor: 9.6 |
| `ts_opm` | Offsides per match | Eyüpspor: 2.6 |

Full list: `ts_mr`, `ts_ptspm`, `ts_g`, `ts_gc`, `ts_yc`, `ts_rc`, `ts_pgp`, `ts_xg`, `ts_xgwp`, `ts_xga`, `ts_tiobpm`, `ts_gcp`, `ts_bcc`, `ts_opg`, `ts_fbg`, `ts_fkg`, `ts_hg`, `ts_pppm`, `ts_gfib`, `ts_gfob`, `ts_spm`, `ts_sotpm`, `ts_hw`, `ts_ppm`, `ts_sppm`, `ts_spiohpm`, `ts_slppm`, `ts_scpm`, `ts_scp`, `ts_stopm`, `ts_stop`, `ts_crpm`, `ts_f`, `ts_pw`, `ts_fc`, `ts_brpm`, `ts_ipm`, `ts_twpm`, `ts_twp`, `ts_cpm`, `ts_dwpm`, `ts_dwp`, `ts_adwpm`, `ts_adwp`, `ts_opm`, `ts_plpm`, `ts_cs`.

### 2b.6 Player Stats (40+ Categories)

Includes goals (`ps_g`), assists (`ps_a`), xG (`ps_xg`), shots per match (`ps_spm`), pass accuracy, tackles, fouls, clean sheets, and more. Each with player UUID, name, and team reference.

### 2b.7 Team ID Mapping (www.mackolik.com → arsiv.mackolik.com)

| www ID | www UUID | arsiv ID | Team |
|---|---|---|---|
| 2217 | `esa748l653sss1wurz5ps3228` | 1 | Galatasaray |
| 2212 | `8lroq0cbhdxj8124qtxwrhvmm` | 2 | Fenerbahçe |
| 2214 | `2ez9cvam9lp9jyhng3eh3znb4` | 3 | Beşiktaş |
| 2213 | `2yab38jdfl0gk2tei1mq40o06` | 4 | Trabzonspor |
| 2219 | `embqktr41hfzczc8uav1scmcn` | 7 | Gençlerbirliği |
| 2220 | `dpsnqu7pd2b0shfzjyn5j1znf` | 8 | Samsunspor |
| 2247 | `cjbaf8s09qoa1n11r33gc560x` | 15 | Göztepe |
| 2234 | `b703zecenioz21dnj3p63v3f7` | 18 | Kocaelispor |
| 2223 | `cw4lbdzlqqdvbkdkz00c9ye49` | 447 | Konyaspor |
| 2224 | `1lbrlj3uu8wi2h9j79snuoae4` | 448 | Ç. Rizespor |
| 2884 | `47njg6cmlx5q3fvdsupd2n6qu` | 451 | Başakşehir FK |
| 2236 | `9irsyv431fpuqhqtfq9iwxf2u` | 455 | Antalyaspor |
| 9142 | `bmgtxgipsznlb1j20zwjti3xh` | 537 | Eyüpspor (F. Karagümrük on arsiv) |
| 6900 | `4idg23egrrvtrbgrg7p5x7bwf` | 656 | Kasımpaşa |
| 2235 | `c8ns6z3u8kxldv1zh1evu10rv` | 570 | Kayserispor |
| 3287 | `2agzb2h4ppg7lfz9hn7eg1rqo` | 572 | Gaziantep FK |
| 7285 | `84fpe0iynjdghwysyo5tizdkk` | 619 | Alanyaspor |
| 3014 | `c3txoz57mu7w9y1jprvnv2flr` | 537 | F. Karagümrük |

### 2b.8 Value vs arsiv.mackolik.com

| Feature | arsiv.mackolik.com | www.mackolik.com |
|---|---|---|
| API style | Clean JSON (AJAX handlers) | Embedded JSON in HTML attribute |
| Response size | ~15KB per season | ~1-4MB per page |
| Home/away W/D/L | ✅ (in standings) | ❌ (must derive from match results) |
| xG / xGA | ❌ | ✅ (47 team stat keys) |
| Player-level stats | Per-match only | Season aggregates (40+ keys) |
| Seasons available | 41 (1985-2026) | 68 (1959-2026) |
| Match detail stats | Separate per-match AJAX calls | Not in embedded blob (only scores) |
| Betting odds | ✅ in fixtures | Not in embedded blob |
| Team crest images | ❌ | ✅ (`file.mackolikfeeds.com/teams/{uuid}`) |

**Strategy:** Use arsiv.mackolik.com as the primary scraper (clean JSON, smaller payloads, home/away splits, odds) and www.mackolik.com as a **cross-validation source + xG/xGA provider**. The different HTML structures make them excellent candidates for Phase 7 (Adaptive Scraper Intelligence) — if one redesigns, the other provides redundancy.

---

## 3. tff.org — Secondary Source

### 3.1 What's Available

TFF.org (Turkish Football Federation official site) uses ASP.NET WebForms with Telerik RadAjax controls. Data is server-rendered in HTML tables (not AJAX-loaded for standings).

**Confirmed endpoints:**

| Page | URL | Content |
|---|---|---|
| Süper Lig Hub | `pageID=198` | Standings + fixtures + news modules |
| Results | `pageID=29` | Match results by league/week (AJAX-loaded) |
| Fixtures | `pageID=30` | Upcoming fixtures by league/week (AJAX-loaded) |

**Standings data (module 12490, server-rendered HTML):**

```
Pos  Team                           P    W    D    L    GF   GA   GD   Pts
 1   GALATASARAY A.Ş.              27   20    4    3    63   20   43    64
 2   FENERBAHÇE A.Ş.               28   18    9    1    62   28   34    63
 3   TRABZONSPOR A.Ş.              28   19    6    3    55   30   25    63
 4   BEŞİKTAŞ A.Ş.                28   15    7    6    49   32   17    52
 5   GÖZTEPE A.Ş.                  27   12   10    5    32   20   12    46
 6   RAMS BAŞAKŞEHİR FK           28   12    8    8    44   30   14    44
 7   SAMSUNSPOR A.Ş.               27    8   12    7    31   33   -2    36
 ...
```

**Fixture data (module 12491):**

- Week-by-week fixture listing with home/away teams
- Dates (`10.04.2026`) and times (`20:00`)
- 1st half / 2nd half week selectors (1–17 first half, 18–34 second half)
- Team names use official legal entity names (e.g., "HESAP.COM ANTALYASPOR", "RAMS BAŞAKŞEHİR FUTBOL KULÜBÜ")

**Season selector (ComboBox):**

- League selector with all Turkish competitions
- Includes historical seasons via RadComboBox with LoadOnDemand

### 3.2 Scraping Complexity

| Aspect | Difficulty | Notes |
|---|---|---|
| Standings | Easy | Server-rendered HTML `<tr>` rows, standard `<table>` |
| Fixtures (current week) | Easy | Server-rendered in module 12491 with dates + times |
| Fixtures (other weeks) | Medium | Requires Telerik RadAjax postback to navigate weeks |
| Results | Hard | AJAX-loaded via RadAjaxPanel, requires `__doPostBack` simulation |
| Historical seasons | Hard | RadComboBox LoadOnDemand requires ViewState + event validation |

### 3.3 Value Proposition

TFF.org serves as **cross-validation** for arsiv.mackolik.com data:

- Official team names (legal entities) — authoritative for name resolution
- Match dates and kickoff times — official schedule
- Standings — cross-check against mackolik standings
- Discipline data (pageID for red/yellow cards) — not yet probed but page exists

TFF.org is **not suitable as the primary source** due to complex ASP.NET postback requirements for navigating weeks/seasons, but it provides authoritative cross-validation and official fixture timing.

---

## 4. OpenFootball + football-data.co.uk — Tertiary Sources

Per [DATA_SOURCES.md](../data/DATA_SOURCES.md):

| Source | Strengths | Weaknesses |
|---|---|---|
| OpenFootball | Clean JSON, HT/FT scores, free, no auth | Missing 2021-24, no stats, no player data |
| football-data.co.uk | 10 seasons, shots/corners/fouls/cards/odds CSV | Timeout from dev env, ASCII team names |

These fill **specific gaps**:

- football-data.co.uk provides cards data (yellow/red) not easily available from mackolik JSON API
- OpenFootball provides a simple cross-validation source for scores
- football-data.co.uk provides historical odds data going back 10 seasons

In the autonomous pipeline, these are fetched by fallback scraper peers when primary source is unavailable or for cross-validation.

---

## 5. api-sports.io — Supplementary Source

**Only used for player roster data** when the system needs to resolve player names to teams. Free tier (100 req/day) is sufficient. Registration required but no payment.

However, arsiv.mackolik.com also provides player data via:
- Top scorers/assist tables in standings page HTML
- Player detail pages (`/Futbolcu/{id}/{name}`)
- Transfer index page (`/Transferler`)

api-sports.io becomes the fallback for structured squad data if arsiv.mackolik.com player scraping proves insufficient.

---

## 6. Implementation Phases

```
Phase 0 ── Single Source of Truth ──────────────────── (prerequisite)
    │       Consolidate 5 team list copies → locale_tr.yaml
    │
Phase 1 ── arsiv.mackolik.com Scraper ─────────────── (core)
    │       JSON API client + historical season loader
    │
Phase 2 ── Fixture Index + Season Detection ────────── (core)
    │       No more CURRENT_SEASON constant
    │
Phase 3 ── Persistent Identity + Scheduler ─────────── (infra)
    │       APScheduler + node identity file
    │
Phase 4 ── Distributed Scrape Coordination ─────────── (P2P)
    │       Role election + task queue + source health
    │
Phase 5 ── Player + Transfer Resolution ────────────── (feature)
    │       Player→team lookup, transfer detection
    │
Phase 6 ── Continuous Model Learning ───────────────── (ML)
    │       Drift detection + incremental retrain
    │
Phase 7 ── Adaptive Scraper Intelligence ───────────── (AI)
    │       AI-driven selector recovery + P2P schema gossip
    │
Phase 8 ── Self-Healing + Source Failover ──────────── (resilience)
    │       Selector health, source rotation, graceful degradation
    │
Phase 9 ── Real Network Transport ──────────────────── (networking)
            TCP transport, peer discovery, NAT traversal
```

**Critical path:** Phases 0 → 1 → 2 must be sequential (each depends on the previous). Phases 3–5 can overlap. Phase 6 requires Phase 2 (needs real fixture data). Phase 7 requires Phase 1 + Phase 6 (needs scraper + training infrastructure). Phases 8–9 are independent.

---

## 7. Phase 0: Single Source of Truth

**Problem (from GENERIC_INPUT_HANDLING.md §3.2):** 5 independent copies of team lists across 5 files. A team rename, promotion, or relegation requires editing all 5.

### Files to Modify

| File | Current | Target |
|---|---|---|
| `ai/tqu/questions.py` | `_TEAMS = [...]` hardcoded (22 teams) | `from common.constants import UUID_TO_NAME` |
| `ai/tqu/questions.py` | `_DERBIES = [...]` hardcoded (6 pairs) | Load from `locale_tr.yaml` new `derbies:` section |
| `ai/tqu/questions.py` | `_PLAYER_TEAMS = {...}` hardcoded (4 teams) | Remove entirely — Phase 5 adds dynamic resolution |
| `data/generate_match_data.py` | `TEAMS = [...]` hardcoded (19 teams + strengths) | Load from locale or accept CLI arg |
| `ai/scraper/real_data.py` | `TEAM_NAME_MAP = {...}` (40+ entries) | Extend `locale_tr.yaml` with `source_aliases:` per team |
| `ai/common/league_config.py` | `DERBIES = frozenset(...)` hardcoded | Load from YAML `derbies:` section |

### locale_tr.yaml Extensions

```yaml
teams:
  team_001:
    display_name: "Galatasaray"
    aliases: ["galatasaray", "gs", "cim bom", ...]
    mackolik_id: 1                    # NEW — stable arsiv.mackolik.com team ID
    source_aliases:                   # NEW — scraper normalisation
      openfootball: "Galatasaray"
      footballdata_uk: "Galatasaray"
      tff: "GALATASARAY A.Ş."
    strength:                         # NEW — replaces generate_match_data.py
      attack: 1.55
      defense: 0.80

derbies:                              # NEW — single source
  - ["team_001", "team_002"]          # GS vs FB
  - ["team_001", "team_003"]          # GS vs BJK
  - ["team_002", "team_003"]          # FB vs BJK
  - ["team_001", "team_004"]          # GS vs TS
  - ["team_002", "team_004"]          # FB vs TS
  - ["team_003", "team_004"]          # BJK vs TS
```

The `mackolik_id` field maps directly to the stable team IDs from the arsiv.mackolik.com JSON API, enabling automatic data joins without string matching.

### Acceptance Criteria

- [x] All team names across the codebase derive from `locale_tr.yaml`
- [x] Adding/removing a team requires editing only `locale_tr.yaml`
- [x] Existing tests still pass (212 AI + 96 P2P)
- [x] `_PLAYER_TEAMS` dict removed from `questions.py` (replaced by dynamic lookup in Phase 5)

---

## 8. Phase 1: arsiv.mackolik.com Scraper

### New File: `ai/scraper/mackolik.py`

Core client for the arsiv.mackolik.com JSON API. This replaces OpenFootball as the primary data source.

### 1.1 Season Discovery

```python
class MackolikClient:
    BASE = "https://arsiv.mackolik.com"
    AJAX = f"{BASE}/AjaxHandlers"
    GROUP_TURKEY = 1  # Süper Lig group ID

    def discover_seasons(self) -> dict[str, int]:
        """
        Returns: {"2025/2026": 70381, "2024/2025": 67287, ...}
        Auto-discovers all available seasons. No hardcoded season list.
        """
        # Step 1: Get year labels
        r = self._get(f"{self.AJAX}/CompetitionHandler.aspx",
                      params={"op": "groupYears", "group": self.GROUP_TURKEY})
        years = self._parse_js_array(r.text)  # e.g. ['2025/2026', '2024/2025', ...]

        # Step 2: For each year, get Süper Lig season ID
        seasons = {}
        for year in years:
            r = self._get(f"{self.AJAX}/CompetitionHandler.aspx",
                          params={"op": "seasons", "group": self.GROUP_TURKEY, "year": year})
            data = self._parse_jsonp(r.text)
            for league_id, league_name in data.get("l", []):
                if "Süper Lig" in league_name:
                    seasons[year] = league_id
                    break
        return seasons
```

### 1.2 Season Data Fetch

```python
    def fetch_season(self, season_id: int) -> SeasonData:
        """
        Single HTTP request returns standings + fixtures + results + odds.
        """
        r = self._get(f"{self.AJAX}/StandingHandler.ashx",
                      params={"op": "standing", "id": season_id})
        raw = r.json()
        return SeasonData(
            season_id=raw["id"],
            standings=self._parse_standings(raw["s"]),
            fixtures=self._parse_fixtures(raw["f"]),
            results=self._parse_results(raw["r"]),
            zones=self._parse_zones(raw["d"]),
        )
```

### 1.3 Match Detail Stats

```python
    def fetch_match_stats(self, match_id: int) -> MatchStats:
        """
        Per-match statistics: possession, shots, passes, corners, fouls.
        Returns parsed stats from optaStats HTML fragment.
        """
        r = self._get(f"{self.AJAX}/MatchHandler.aspx",
                      params={"command": "optaStats", "id": match_id})
        return self._parse_opta_stats_html(r.text)
```

### 1.4 Data Models

```python
@dataclass
class TeamStanding:
    team_id: int
    name: str
    played: int
    home_w: int; home_d: int; home_l: int
    away_w: int; away_d: int; away_l: int
    goals_for: int
    goals_against: int
    points: int

@dataclass
class Fixture:
    match_id: int
    date: str           # "DD/MM"
    home_id: int
    away_id: int
    odds_home: float
    odds_draw: float
    odds_away: float

@dataclass
class Result:
    match_id: int
    date: str
    home_id: int
    away_id: int
    ft_home: int
    ft_away: int
    ht_score: str       # "0 - 0"
    odds_home: float
    odds_draw: float
    odds_away: float

@dataclass
class MatchStats:
    possession_home: float
    possession_away: float
    shots_home: int
    shots_away: int
    shots_on_target_home: int
    shots_on_target_away: int
    passes_home: int
    passes_away: int
    pass_accuracy_home: float
    pass_accuracy_away: float
    corners_home: int
    corners_away: int
    fouls_home: int
    fouls_away: int
    offsides_home: int
    offsides_away: int

@dataclass
class SeasonData:
    season_id: int
    standings: list[TeamStanding]
    fixtures: list[Fixture]
    results: list[Result]
    zones: list[dict]
```

### 1.5 Historical Data Loader

```python
    def load_training_data(self, n_seasons: int = 5) -> list[SeasonData]:
        """
        Fetch the last N seasons for model training.
        Auto-discovers season IDs; no hardcoded list.
        """
        all_seasons = self.discover_seasons()
        recent = sorted(all_seasons.items(), reverse=True)[:n_seasons]
        return [self.fetch_season(sid) for _, sid in recent]
```

### 1.6 Rate Limiting

Existing `ScrapingEngine` in `engine.py` already enforces 5s/domain rate limits. `MackolikClient` reuses this infrastructure via the shared `RateLimiter`.

### Acceptance Criteria

- [x] `MackolikClient.discover_seasons()` returns season IDs for 5+ years
- [x] `MackolikClient.fetch_season(67287)` returns 19 teams with standings (2024/25)
- [x] `MackolikClient.fetch_match_stats(match_id)` returns possession/shots/etc.
- [x] Rate limit of 5s/request enforced
- [x] Integration test fetches 2024/2025 completed season (19 teams, 0 pending fixtures)
- [x] Team IDs in response match `mackolik_id` values in `locale_tr.yaml` (22 mapped)

> **Schema correction (live probe):** Standings rows are 20 elements with home/away
> splits (not 16 as originally documented). `TeamStanding` has extended fields:
> `home_played`, `away_played`, `home_gf`, `away_gf`, `home_ga`, `away_ga`,
> `home_pts`, `away_pts`, `penalty_points`. Match stats HTML uses `div`-based
> layout (`match-statistics-rows` class), not `li`/`span` structure.

---

## 9. Phase 2: Fixture Index + Season Detection

**Problem (from GENERIC_INPUT_HANDLING.md §3.3 + §3.4):** No fixture database, `CURRENT_SEASON` hardcoded, user questions like "bu hafta sonu" can't resolve to actual matches.

### 2.1 Season State Machine

**New file: `ai/common/season.py`**

Replaces all `CURRENT_SEASON` references.

```python
class SeasonState(Enum):
    PRE_SEASON = "pre_season"      # fixtures exist but none played
    IN_SEASON = "in_season"        # some played, some upcoming
    POST_SEASON = "post_season"    # all played, no upcoming
    OFF_SEASON = "off_season"      # no fixture data for next season yet

def detect_season(client: MackolikClient) -> tuple[str, SeasonState, int]:
    """
    Returns: (season_label, state, season_id)

    Logic:
    1. Fetch most recent season from mackolik
    2. Check fixture/result counts to determine state
    3. If post_season, check if next season file exists
    4. No hardcoded dates or season strings anywhere
    """
    seasons = client.discover_seasons()
    for label, season_id in sorted(seasons.items(), reverse=True):
        data = client.fetch_season(season_id)
        if data.fixtures:  # Has upcoming matches
            return (label, SeasonState.IN_SEASON, season_id)
        if data.results:   # Has results but no upcoming
            # Check if next season exists
            # ...
    return (None, SeasonState.OFF_SEASON, None)
```

### 2.2 Match Resolver

**New file: `ai/pipeline/resolver.py`**

Maps user questions to specific upcoming matches:

```python
class MatchResolver:
    def resolve(self, team_ids: list[str], time_ref: str | None,
                fixtures: list[Fixture]) -> Fixture | None:
        """
        "GS yarınki maç" → Fixture(home_id=1, away_id=3, date="12/04")

        Resolution strategy:
        1. Filter fixtures by team_ids
        2. Apply time_ref filter (bugün/yarın/bu hafta sonu)
        3. If multiple matches, pick nearest future date
        4. If no match found, return None (not fabricated data)
        """
```

### 2.3 Pipeline Integration

Modify `ai/pipeline/runner.py`:

```python
# Before (current):
features = generate_synthetic_features()  # random seed=42

# After:
fixture = resolver.resolve(entities.team_ids, entities.time_ref, season_data.fixtures)
if fixture:
    features = compute_real_features(fixture, season_data)
else:
    return Response(verdict="fixture_unknown",
                    text="Belirtilen maç fikstürde bulunamadı.")
```

### 2.4 Confidence Gating

**Problem (from GENERIC_INPUT_HANDLING.md §4.3):** System answers confidently even when match context was never resolved.

The pipeline must never return a confident prediction when the underlying data is synthetic/fabricated:

```python
# New verdict type in trc/verdict.py:
VERDICT_KEYS = [
    # ... existing verdicts ...
    "fixture_unknown",     # Could not resolve to a real match
    "data_stale",          # Real data is older than threshold
    "insufficient_data",   # Team too new / not enough history
]
```

### Acceptance Criteria

- [x] `CURRENT_SEASON` constant removed from `constants.py`
- [x] `detect_season()` correctly identifies current season from live mackolik data
- [x] `MatchResolver.resolve(["team_001"], "yarın", fixtures)` returns correct fixture
- [x] Pipeline returns "fixture not found" response when match can't be resolved (no fabricated data)
- [x] Season boundaries detected automatically (tested with 2024/2025 → 2025/2026 transition)

---

## 10. Phase 3: Persistent Identity + Scheduler

### 3.1 Persistent Node Identity

**New file: `p2p/node/identity.py`**

Peers must survive restarts with the same identity:

```python
IDENTITY_PATH = Path("~/.negelir/identity.json").expanduser()

def load_or_create_identity() -> dict:
    """
    Load node_id + keypair from disk. Create if first run.
    Ensures peer reputation survives across restarts.
    """
    if IDENTITY_PATH.exists():
        return json.loads(IDENTITY_PATH.read_text())

    identity = {
        "node_id": str(uuid.uuid4()),
        "created_at": datetime.utcnow().isoformat(),
    }
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_PATH.write_text(json.dumps(identity))
    return identity
```

### 3.2 APScheduler Integration

**New file: `ai/scheduler.py`**

Replaces `while True: sleep(30)` loops:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

class NegelirScheduler:
    def __init__(self, db_url: str):
        self.scheduler = BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=db_url)}
        )

    def start(self):
        # Daily scrape cycle
        self.scheduler.add_job(
            self.scrape_cycle, "cron", hour=6, minute=0,
            id="daily_scrape", replace_existing=True
        )

        # Outcome validation (evening after matches)
        self.scheduler.add_job(
            self.outcome_check, "cron", hour=22, minute=0,
            id="outcome_check", replace_existing=True
        )

        # Weekly full retrain
        self.scheduler.add_job(
            self.weekly_retrain, "cron", day_of_week="sun", hour=3,
            id="weekly_retrain", replace_existing=True
        )

        # Heartbeat (5-minute interval)
        self.scheduler.add_job(
            self.heartbeat, "interval", minutes=5,
            id="heartbeat", replace_existing=True
        )

        self.scheduler.start()
```

### 3.3 Heartbeat Protocol

**Modify `p2p/protocol/messages.py`:**

Add `HEARTBEAT` message type extending the existing `PING`/`PONG`:

```python
class MessageType(Enum):
    # ... existing types ...
    HEARTBEAT = "heartbeat"       # Extended PING with capabilities + uptime
    TASK_CLAIM = "task_claim"
    TASK_COMPLETE = "task_complete"
```

### 3.4 Dependencies

Add to `ai/requirements.txt`:
```
apscheduler>=3.10.0
```

Add to `p2p/requirements.txt`:
```
apscheduler>=3.10.0
```

### Acceptance Criteria

- [x] Node identity persists across container restarts
- [x] Scheduler triggers scrape cycle at 06:00 UTC
- [x] Heartbeat sent every 5 minutes
- [x] `while True: sleep(30)` removed from `ai/main.py` and `p2p/main.py`
- [ ] Jobs persist in PostgreSQL (survive process restart)

---

## 11. Phase 4: Distributed Scrape Coordination

### 4.1 Role Election

**New file: `p2p/coordination/election.py`**

Deterministic role assignment — all peers arrive at the same result with no coordinator:

```python
def elect_roles(peers: list[PeerInfo], epoch_day: int) -> dict[str, str]:
    """
    Deterministic election: sort by (trust_level, uptime, node_id).
    All peers compute the same result independently.

    Returns: {"scraper_mackolik": "peer_A", "scraper_openfootball": "peer_B",
              "validator": ["peer_C", "peer_D"], "indexer": "peer_A"}
    """
    ranked = sorted(peers, key=lambda p: (
        -p.trust_weight,
        -p.uptime_hours,
        p.node_id  # deterministic tie-breaking
    ))
    return {
        "scraper_mackolik": ranked[0].node_id,
        "scraper_openfootball": ranked[1 % len(ranked)].node_id,
        "scraper_footballdata": ranked[2 % len(ranked)].node_id,
        "validator": [p.node_id for p in ranked[:3]],
        "indexer": ranked[0].node_id,
    }
```

### 4.2 Scrape Task Queue

**New file: `p2p/coordination/tasks.py`**

Activates the existing `scrape_tasks` table (schema in `migrations/001_initial.sql`, currently unused):

```python
class TaskQueue:
    def create_daily_tasks(self, season_data: SeasonData):
        """
        Generate pending scrape tasks for today's data needs.
        """
        tasks = [
            ScrapeTask(source="mackolik", data_type="standing", status="pending"),
            ScrapeTask(source="mackolik", data_type="fixture", status="pending"),
        ]
        # Add match stat tasks for recently completed matches
        for result in season_data.results:
            if self._is_recent(result.date, hours=24):
                tasks.append(ScrapeTask(
                    source="mackolik", data_type="match_stats",
                    target_id=result.match_id, status="pending"))
        return tasks

    def claim(self, task_id: str, peer_id: str) -> bool:
        """Atomic claim: pending → assigned. Returns False if already claimed."""

    def complete(self, task_id: str, data_hash: str):
        """assigned → completed. Broadcasts SCRAPE_DATA to peers."""
```

### 4.3 Source Health Monitor

**New file: `ai/scraper/health.py`**

```python
class SourceHealthMonitor:
    FAILURE_THRESHOLD = 3  # consecutive failures before declaring source down

    def record(self, source: str, success: bool, matches_found: int):
        self._history[source].append((success, matches_found))
        recent = self._history[source][-self.FAILURE_THRESHOLD:]
        if all(not s for s, _ in recent):
            self._declare_failure(source)

    def _declare_failure(self, source: str):
        # Try fallback selectors
        # If all fail → mark source as DOWN
        # Broadcast DATA_SOURCE_DOWN to peers
        # Other peers compensate with cached data
```

### 4.4 Cross-Source Validator

**New file: `ai/proofreader/cross_validator.py`**

```python
class CrossValidator:
    def validate(self, mackolik: SeasonData, tff: SeasonData | None,
                 openfootball: SeasonData | None) -> list[ValidatedResult]:
        """
        Compare results from 2+ sources. Accept majority vote.
        Quarantine conflicts.
        """
        validated = []
        for match_id, results in self._group_by_match(mackolik, tff, openfootball):
            scores = set((r.ft_home, r.ft_away) for r in results)
            if len(scores) == 1:
                validated.append(ValidatedResult(match_id, results[0], confidence=1.0))
            else:
                # Majority vote
                most_common = Counter(scores).most_common(1)[0]
                if most_common[1] >= 2:
                    validated.append(ValidatedResult(match_id, most_common[0], confidence=0.8))
                else:
                    self._quarantine(match_id, results)
        return validated
```

### 4.5 New P2P Message Types

| Message | Purpose | Direction |
|---|---|---|
| `FIXTURE_INDEX` | Share upcoming match schedule | Indexer → all |
| `ROLE_ELECTION` | Daily role assignment | Broadcast |
| `DATA_CONFLICT` | Cross-source mismatch alert | Validator → all |
| `ROSTER_UPDATE` | Player transfer detected | Scraper → all |
| `MODEL_CHECKPOINT` | Retrained model metadata | Trainer → all |
| `SEASON_BOUNDARY` | Season start/end detected | Detector → all |
| `TASK_CLAIM` | Peer claims a scrape task | Peer → all |
| `TASK_COMPLETE` | Scrape task completed | Peer → all |

### Acceptance Criteria

- [x] Role election produces deterministic results across all peers
- [x] `scrape_tasks` table populated with daily tasks
- [x] Source health monitor detects and reports 3 consecutive failures
- [x] Cross-validator quarantines conflicting results
- [x] All new message types added to `MessageType` enum

---

## 12. Phase 5: Player + Transfer Resolution

**Problem (from GENERIC_INPUT_HANDLING.md §3.1):** Player rosters hardcoded in `questions.py`, stale since 2024 transfers.

### 5.1 Player Data Scraping

arsiv.mackolik.com provides player data through:

1. **Top scorers table** in standings page HTML — player names, goal counts, team
2. **Player detail pages** at `/Futbolcu/{player_id}/{player-name}`
3. **Transfer page** at `/Transferler`

For structured squad data, api-sports.io free tier provides `/squads?team={id}`.

### 5.2 Player Registry

**New file: `migrations/002_players.sql`**

```sql
CREATE TABLE IF NOT EXISTS players (
    player_id    SERIAL PRIMARY KEY,
    source_id    VARCHAR(32) NOT NULL,       -- mackolik player ID
    name         VARCHAR(128) NOT NULL,
    team_id      VARCHAR(36) REFERENCES teams(team_id),
    position     VARCHAR(32),
    joined_at    TIMESTAMP,
    left_at      TIMESTAMP,                  -- NULL = currently on team
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_players_team ON players(team_id);
CREATE INDEX idx_players_name ON players(name);
```

### 5.3 Player Entity Extraction

**Modify `ai/tqu/entities.py`:**

```python
def extract_player(text: str, player_registry: dict) -> PlayerRef | None:
    """
    Fuzzy-match player names from the text against current roster.
    Returns: PlayerRef(name, team_id) or None

    Uses Levenshtein distance for Turkish name variants:
    "İcardi" → "Icardi" → team_id from registry
    """
```

### 5.4 Transfer Detection

```python
class TransferDetector:
    def check_roster_changes(self, previous: dict, current: dict) -> list[Transfer]:
        """
        Compare previous roster snapshot vs current.
        Detect: new arrivals, departures, position changes.
        Broadcast ROSTER_UPDATE for each change.
        """
```

### Acceptance Criteria

- [x] `_PLAYER_TEAMS` dict removed from `questions.py`
- [x] Player names resolved dynamically via database lookup
- [x] Transfer detection compares weekly roster snapshots
- [x] `ROSTER_UPDATE` message broadcast on detection
- [x] Fuzzy matching handles Turkish character variants

---

## 13. Phase 6: Continuous Model Learning

### 6.1 Outcome Collector

**New file: `ai/model/outcomes.py`**

```python
class OutcomeCollector:
    RETRAIN_THRESHOLD = 20  # validated outcomes before retraining

    def on_match_completed(self, match_id: int, features: np.ndarray,
                           actual_result: int):
        """Buffer validated outcomes. Trigger retrain at threshold."""
        self._buffer.append((features, actual_result))
        if len(self._buffer) >= self.RETRAIN_THRESHOLD:
            self._trigger_retrain()
```

### 6.2 Drift Detector

**New file: `ai/model/drift.py`**

```python
class DriftDetector:
    WINDOW = 30
    ACCURACY_FLOOR = 0.35

    def check(self, outcomes: list[Outcome]) -> bool:
        """Rolling accuracy check. Returns True if retrain needed."""
        recent = outcomes[-self.WINDOW:]
        if len(recent) < self.WINDOW:
            return False
        accuracy = sum(1 for o in recent if o.correct) / len(recent)
        return accuracy < self.ACCURACY_FLOOR
```

### 6.3 Incremental XGBoost Training

**Modify `ai/model/trainer.py`:**

```python
def incremental_retrain(self, model_path: str, new_data: DMatrix):
    """
    Continue training from saved booster, appending new trees.
    Faster than full retrain; maintains learned patterns.
    """
    booster = xgb.Booster(model_file=model_path)
    booster.update(new_data, iteration=booster.num_boosted_rounds())
    booster.save_model(model_path)
```

### 6.4 Model Sharing via P2P

```python
# MODEL_CHECKPOINT message:
{
    "type": "MODEL_CHECKPOINT",
    "model_hash": "sha256:...",
    "training_summary": {
        "n_matches": 200,
        "date_range": ["2024-08-01", "2026-04-07"],
        "holdout_accuracy": 0.42,
    },
    "peer_reputation": 0.85,
}

# Adoption protocol:
# Accept model from higher-reputation peer if it validates
# better on local holdout set.
```

### Acceptance Criteria

- [x] Retrain triggered after 20 validated outcomes
- [x] Drift detector fires when accuracy drops below 35%
- [x] Incremental training produces valid model (test predictions still work)
- [ ] `MODEL_CHECKPOINT` message broadcast after retraining
- [ ] Higher-reputation peer's model adopted by lower-reputation peers (if better)

---

## 14. Phase 7: Adaptive Scraper Intelligence

**Problem:** Phase 8's Self-Healing only rotates through pre-baked fallback selectors. When a source fundamentally restructures its HTML/JS (e.g., arsiv.mackolik.com migrates from `<table>` to React components, or TFF.org replaces Telerik controls with a SPA), the entire selector chain breaks. No amount of selector version rotation can recover — the system needs to **learn** where the data moved.

**Solution:** An AI-driven extraction pipeline that (1) detects structural drift from known-good page fingerprints, (2) uses heuristic + ML field discovery to locate data in the new DOM, (3) validates discovered mappings against data contracts, and (4) propagates verified schemas to all peers via P2P gossip.

### 7.1 Schema Fingerprinting

**New file: `ai/scraper/schema_fingerprint.py`**

Every successful scrape produces a structural fingerprint of the page — a compact representation of the DOM hierarchy, tag distribution, and CSS class vocabulary. When a page's fingerprint diverges beyond a threshold from the stored baseline, the system enters **discovery mode**.

```python
@dataclass
class DOMFingerprint:
    tag_histogram: dict[str, int]     # {"table": 3, "div": 42, "span": 18, ...}
    class_vocabulary: set[str]        # {"standing-row", "match-score", ...}
    depth_profile: list[int]          # [1, 4, 12, 28, 15, 3] — node count per depth
    data_region_xpath: str            # XPath of the subtree containing known-good data
    content_hash: str                 # SHA-256 of the structural skeleton (tags + nesting only)

class SchemaFingerprinter:
    DRIFT_THRESHOLD = 0.35  # Jaccard distance on class vocabulary

    def fingerprint(self, html: str) -> DOMFingerprint:
        """Extract structural fingerprint from raw HTML."""

    def detect_drift(self, current: DOMFingerprint,
                     baseline: DOMFingerprint) -> float:
        """
        Returns drift score [0.0, 1.0]. Above DRIFT_THRESHOLD triggers
        discovery mode. Uses:
        - Jaccard distance on CSS class vocabulary
        - Jensen-Shannon divergence on tag histogram
        - Cosine distance on depth profile vector
        """

    def store_baseline(self, source: str, endpoint: str,
                       fingerprint: DOMFingerprint):
        """Persist known-good fingerprint to PostgreSQL. Updated after
        every successful scrape with validated data."""
```

Fingerprints are stored per (source, endpoint) pair. When a scrape returns data that passes cross-validation (Phase 4), the fingerprint is updated as the new baseline. This means the system naturally adapts to gradual redesigns while triggering discovery for sudden breaks.

### 7.2 AI-Driven Field Discovery

**New file: `ai/scraper/field_discovery.py`**

When discovery mode activates, the system analyzes the new DOM to relocate data fields. It uses a layered approach — fast heuristics first, then ML-based classification if heuristics fail.

```python
class FieldDiscoveryEngine:
    """
    Locates data fields in an unknown DOM structure using a cascade:
      1. Text-pattern heuristics (fastest, most reliable)
      2. Structural similarity to known-good snapshots
      3. ML classifier trained on historical DOM→field mappings
    """

    # ---- Layer 1: Text-Pattern Heuristics ----

    FIELD_PATTERNS = {
        "team_name": {
            "validator": lambda text, ctx: text.strip() in ctx["team_registry"],
            "description": "Must match a known team name from locale_tr.yaml",
        },
        "score": {
            "validator": lambda text, ctx: re.fullmatch(r"\d{1,2}", text.strip())
                         and 0 <= int(text.strip()) <= 20,
            "description": "Integer 0-20",
        },
        "possession_pct": {
            "validator": lambda text, ctx: re.fullmatch(r"\d{1,3}([.,]\d)?%?", text.strip())
                         and 0 <= float(re.sub(r"[%,]", "", text.strip().replace(",", "."))) <= 100,
            "description": "Percentage 0-100, home+away must sum to ~100",
        },
        "odds": {
            "validator": lambda text, ctx: re.fullmatch(r"\d+\.\d{1,2}", text.strip())
                         and 1.01 <= float(text.strip()) <= 100.0,
            "description": "Decimal odds 1.01-100.00",
        },
        "date": {
            "validator": lambda text, ctx: bool(
                re.fullmatch(r"\d{1,2}[./]\d{1,2}([./]\d{2,4})?", text.strip())),
            "description": "DD/MM or DD/MM/YYYY format",
        },
        "match_stat_int": {
            "validator": lambda text, ctx: re.fullmatch(r"\d{1,4}", text.strip())
                         and int(text.strip()) < 1000,
            "description": "Integer stat value (shots, passes, corners, fouls)",
        },
    }

    def discover_fields(self, html: str, expected_schema: dict,
                        context: dict) -> DiscoveredSchema | None:
        """
        Attempt to locate all fields in expected_schema within the HTML.

        Args:
            html: Raw HTML of the changed page
            expected_schema: {"team_name": 2, "score": 2, "possession_pct": 2, ...}
                             field_name → expected count per row/match
            context: {"team_registry": [...], "current_season_teams": [...]}

        Returns:
            DiscoveredSchema with CSS selectors + extraction rules, or None if
            confidence is below acceptance threshold.
        """
        # Layer 1: Walk DOM text nodes, apply FIELD_PATTERNS validators
        candidates = self._heuristic_scan(html, expected_schema, context)

        if self._evaluate_candidates(candidates) >= 0.8:
            return self._build_schema(candidates)

        # Layer 2: Compare structural neighborhoods against historical snapshots
        candidates = self._structural_similarity_scan(html, expected_schema)

        if self._evaluate_candidates(candidates) >= 0.7:
            return self._build_schema(candidates)

        # Layer 3: ML classifier on DOM subtree embeddings
        candidates = self._ml_classify(html, expected_schema)

        if self._evaluate_candidates(candidates) >= 0.6:
            return self._build_schema(candidates)

        return None  # All layers failed — flag for human review

    # ---- Layer 2: Structural Similarity ----

    def _structural_similarity_scan(self, html: str,
                                     expected_schema: dict) -> list[FieldCandidate]:
        """
        Compare DOM subtree structures against stored snapshots of
        known-good pages. If a subtree has similar nesting/tag patterns
        to a region that previously contained standings data, it likely
        still does — even if CSS classes changed.

        Uses tree-edit-distance on simplified DOM subtrees (tags only,
        no attributes) to find the closest structural match.
        """

    # ---- Layer 3: ML Classifier ----

    def _ml_classify(self, html: str,
                     expected_schema: dict) -> list[FieldCandidate]:
        """
        Feed DOM subtree features into a lightweight classifier trained
        on historical (DOM_region, field_type) pairs.

        Features per DOM node:
        - Tag type (one-hot: table/tr/td/div/span/other)
        - Depth in tree (normalized)
        - Sibling count
        - Text content pattern (digit-only, alpha-only, mixed, empty)
        - Parent tag chain (3 levels up)
        - CSS class token embedding (bag-of-words on class names)

        Output: probability distribution over field types
        """
```

### 7.3 Data Contract Validation

**New file: `ai/scraper/data_contracts.py`**

Discovered field mappings are validated against invariants before acceptance. This prevents false-positive mappings from corrupting the data pipeline.

```python
@dataclass
class DataContract:
    """Invariants that extracted data must satisfy."""
    field: str
    constraint: Callable[[Any, dict], bool]
    description: str

STANDING_CONTRACTS = [
    DataContract("team_count", lambda v, _: 18 <= v <= 21,
                 "Süper Lig has 18-21 teams per season"),
    DataContract("points", lambda v, _: 0 <= v <= 120,
                 "Max points = 3 × 40 matches = 120"),
    DataContract("goals", lambda v, _: 0 <= v <= 200,
                 "No team scores >200 goals in a season"),
    DataContract("win+draw+loss", lambda v, ctx: v["w"] + v["d"] + v["l"] == v["played"],
                 "W+D+L must equal matches played"),
    DataContract("home+away_played", lambda v, ctx:
                 (v["home_w"] + v["home_d"] + v["home_l"] +
                  v["away_w"] + v["away_d"] + v["away_l"]) == v["played"],
                 "Home+away matches must equal total played"),
    DataContract("team_names", lambda teams, ctx:
                 all(t in ctx["team_registry"] for t in teams),
                 "All team names must exist in locale_tr.yaml registry"),
]

MATCH_STAT_CONTRACTS = [
    DataContract("possession_sum", lambda v, _:
                 abs(v["home"] + v["away"] - 100.0) < 2.0,
                 "Possession percentages must sum to ~100%"),
    DataContract("shots_on_target", lambda v, _:
                 v["on_target_home"] <= v["total_home"] and
                 v["on_target_away"] <= v["total_away"],
                 "Shots on target cannot exceed total shots"),
    DataContract("pass_accuracy", lambda v, _:
                 0 <= v["home"] <= 100 and 0 <= v["away"] <= 100,
                 "Pass accuracy must be 0-100%"),
]

class ContractValidator:
    def validate(self, data: dict, contracts: list[DataContract],
                 context: dict) -> tuple[bool, list[str]]:
        """
        Returns (all_passed, list_of_violations).
        Data is accepted only if all contracts pass.
        """
```

### 7.4 Schema Training Pipeline

**New file: `ai/scraper/schema_trainer.py`**

The ML classifier (Layer 3 in field discovery) is trained on historical page snapshots paired with known-correct extracted data. This is self-supervised — every successful scrape becomes a training example.

```python
class SchemaTrainer:
    """
    Self-supervised training: successful scrapes with validated data
    become (DOM_snapshot, field_locations) training pairs.

    Storage: PostgreSQL table `schema_snapshots`
    """

    def record_snapshot(self, source: str, endpoint: str,
                        html: str, extracted_fields: dict):
        """
        Store a successful (HTML → fields) mapping as training data.
        Called automatically after every validated scrape.
        HTML is stored as a simplified DOM tree (no inline content),
        keeping storage manageable (~5KB per snapshot vs ~50KB raw).
        """

    def train_classifier(self) -> FieldClassifier:
        """
        Train a lightweight classifier on accumulated snapshots.

        Architecture: Random forest on handcrafted DOM features
        (not a deep model — must run on CPU in Docker without GPU).

        Training data: All stored (source, endpoint, snapshot, fields)
        tuples. Augmented with synthetic mutations (class renaming,
        tag swaps, depth changes) to improve generalization.

        Output: Serialized model saved to data/models/schema_classifier.pkl
        """

    def augment(self, snapshot: DOMSnapshot) -> list[DOMSnapshot]:
        """
        Generate synthetic training examples by mutating a snapshot:
        - Rename CSS classes (simulate redesign)
        - Wrap elements in extra div layers (depth change)
        - Swap table→div structure (tag migration)
        - Shuffle sibling order (layout change)

        The field locations are adjusted accordingly so labels
        remain correct after mutation.
        """
```

### 7.5 Schema Database

**New file: `migrations/003_schema_snapshots.sql`**

```sql
CREATE TABLE IF NOT EXISTS schema_snapshots (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,
    endpoint        VARCHAR(256) NOT NULL,
    dom_skeleton    JSONB NOT NULL,          -- Simplified DOM tree (tags + structure)
    field_locations JSONB NOT NULL,          -- {field_name: css_selector} verified mappings
    fingerprint     JSONB NOT NULL,          -- DOMFingerprint at capture time
    captured_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_schema_source ON schema_snapshots(source, endpoint);

CREATE TABLE IF NOT EXISTS discovered_schemas (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(64) NOT NULL,
    endpoint        VARCHAR(256) NOT NULL,
    selectors       JSONB NOT NULL,          -- Discovered CSS selectors
    confidence      FLOAT NOT NULL,          -- Discovery confidence [0, 1]
    discovery_layer VARCHAR(16) NOT NULL,    -- 'heuristic' | 'structural' | 'ml'
    peer_votes      INT DEFAULT 1,           -- P2P consensus count
    adopted         BOOLEAN DEFAULT FALSE,   -- Promoted to active selector set
    discovered_at   TIMESTAMP DEFAULT NOW()
);
```

### 7.6 P2P Schema Gossip

**New file: `p2p/coordination/schema_gossip.py`**

When a peer discovers a working schema for a changed source, it broadcasts the discovery to the network. Other peers validate independently before adopting.

```python
class SchemaGossipProtocol:
    """
    P2P protocol for propagating discovered scraper schemas.

    Flow:
    1. Peer A detects structural drift on source X
    2. Peer A runs field discovery → gets DiscoveredSchema with confidence
    3. Peer A scrapes using new schema → validates via data contracts
    4. Peer A broadcasts SCHEMA_PROPOSAL to network
    5. Peers B, C, ... independently fetch source X
    6. Each peer validates the proposed selectors against their own scrape
    7. Peers that confirm send SCHEMA_VOTE back
    8. Once votes >= QUORUM, the schema is ADOPTED network-wide
    9. SCHEMA_ADOPTED broadcast finalizes — all peers switch selectors
    """

    QUORUM = 3               # Minimum confirming peers before adoption
    VOTE_TIMEOUT_SEC = 600   # 10 minutes to collect votes
    CONFIDENCE_FLOOR = 0.6   # Minimum discovery confidence to propose

    def on_drift_detected(self, source: str, endpoint: str,
                          new_html: str):
        """
        Entry point: structural drift detected on a source.
        Run field discovery and propose schema if confident enough.
        """
        schema = self.discovery_engine.discover_fields(
            new_html, self._expected_schema(source, endpoint),
            self._build_context()
        )
        if schema and schema.confidence >= self.CONFIDENCE_FLOOR:
            # Validate locally first
            test_data = self._scrape_with_schema(source, endpoint, schema)
            violations = self.contract_validator.validate(
                test_data, self._contracts(endpoint), self._build_context()
            )
            if not violations:
                self._broadcast_proposal(source, endpoint, schema)

    def on_schema_proposal(self, message: SchemaProposalMessage):
        """
        Handle incoming SCHEMA_PROPOSAL from another peer.
        Independently validate and vote.
        """
        # Fetch the source ourselves
        html = self._fetch(message.source, message.endpoint)

        # Try the proposed selectors
        data = self._extract_with_selectors(html, message.selectors)

        # Validate against data contracts
        _, violations = self.contract_validator.validate(
            data, self._contracts(message.endpoint), self._build_context()
        )

        if not violations:
            self._send_vote(message.proposal_id, vote="confirm")
        else:
            self._send_vote(message.proposal_id, vote="reject",
                            reason=violations)

    def on_quorum_reached(self, proposal_id: str):
        """
        Enough peers confirmed — adopt the schema network-wide.
        Update selectors.json with new selectors, push old ones
        to fallback_selectors, broadcast SCHEMA_ADOPTED.
        """
```

### 7.7 New P2P Message Types

| Message | Purpose | Direction |
|---|---|---|
| `SCHEMA_DRIFT` | Notify peers that structural drift detected on a source | Detector → all |
| `SCHEMA_PROPOSAL` | Propose new selectors discovered by field discovery | Discoverer → all |
| `SCHEMA_VOTE` | Confirm or reject a proposed schema | Voter → proposer |
| `SCHEMA_ADOPTED` | Schema reached quorum — all peers adopt | Proposer → all |

### 7.8 Integration with Existing Phases

- **Phase 1 (Scraper):** `MackolikClient` calls `SchemaFingerprinter.detect_drift()` on every fetch. If drift detected, passes to `FieldDiscoveryEngine` before falling back to Phase 8's selector rotation.
- **Phase 4 (Coordination):** Schema discovery is added as a new role in `election.py` — the `schema_discoverer` role is assigned to a high-reputation peer to avoid spurious proposals from untrusted nodes.
- **Phase 6 (Learning):** `SchemaTrainer` reuses the same incremental training infrastructure. Schema classifier retraining can piggyback on the weekly retrain schedule.
- **Phase 8 (Self-Healing):** Adaptive intelligence is the **first line of defense**. Phase 8's selector rotation becomes the fallback when AI discovery fails or is still collecting votes.

```
Source HTML changes
    │
    ├─ Step 1: Fingerprint detects drift
    │
    ├─ Step 2: Field Discovery attempts AI-driven recovery
    │     ├─ Heuristic scan (team names, score patterns, ...)
    │     ├─ Structural similarity to historical snapshots
    │     └─ ML classifier on DOM features
    │
    ├─ Step 3: Data contract validation
    │
    ├─ Step 4: P2P schema proposal + quorum vote
    │
    ├─ Step 5: Schema adopted → selectors.json updated
    │
    └─ Fallback: If AI fails → Phase 8 selector rotation
                 If all selectors fail → source marked DOWN
```

### Acceptance Criteria

- [x] `SchemaFingerprinter` detects drift when >35% of CSS classes change
- [x] `FieldDiscoveryEngine` recovers team names and scores from a restructured page (test with synthetic DOM mutations)
- [x] Data contracts catch invalid extractions (possession not summing to 100%, unknown team names)
- [x] `SchemaTrainer` produces a classifier from ≥20 stored snapshots
- [x] `SCHEMA_PROPOSAL` reaches quorum with 3+ confirming peers in simulation
- [ ] End-to-end: inject mutated HTML → drift detected → field discovery → P2P vote → schema adopted → scrape succeeds
- [x] Fallback to Phase 8 selector rotation when AI discovery confidence < 0.6

---

## 15. Phase 8: Self-Healing + Source Failover

### 8.1 Selector Versioning

**Modify `ai/scraper/selectors.json`:**

```json
{
  "source_a": {
    "version": 3,
    "selectors": { "current selectors..." },
    "fallback_selectors": [
      { "version": 2, "selectors": { "previous..." } },
      { "version": 1, "selectors": { "original..." } }
    ]
  }
}
```

On failure, walk backwards through selector versions. If all fail, mark source as down.

### 8.2 Graceful Degradation Chain

```
Full capability (mackolik + tff + openfootball + football-data + all peers)
    │
    ├─ mackolik down → tff standings + openfootball scores + football-data stats
    │
    ├─ mackolik + tff down → openfootball scores + football-data stats
    │
    ├─ All Turkish sources down → openfootball + football-data (English names)
    │
    ├─ All sources down → cached DataStore (7-day TTL)
    │
    ├─ P2P network down → single-node predictions (no ensemble)
    │
    ├─ Model stale → apply confidence penalty: multiply all confidences by 0.5
    │
    └─ Complete data loss → "Sistem başlatılıyor" until data available
```

### 8.3 Peer Failure Recovery

```
Node crash:
  1. Heartbeat stops → neighbors mark "suspected_down" after 5 min
  2. After 15 min → remove from mesh
  3. If elected scraper → next candidate auto-promotes
  4. On restart:
     a. Load persistent identity (Phase 3)
     b. PEER_DISCOVERY broadcast
     c. Manifest-based delta sync (already implemented)
     d. Resume within minutes
```

### Acceptance Criteria

- [x] Selector fallback tested with intentionally broken selectors
- [x] Source failover tested by simulating source_a unavailability
- [x] Confidence penalty applied when data is stale
- [ ] Peer recovery via manifest sync works within 2 minutes

---

## 16. Phase 9: Real Network Transport

### 9.1 TCP Transport

**New file: `p2p/protocol/tcp_transport.py`**

Implements the same `Transport` interface as `SimulatedTransport`, enabling drop-in replacement:

```python
class TcpTransport(Transport):
    async def send(self, peer_id: str, message: Message):
        """Send message over TCP to peer."""

    async def receive(self) -> Message:
        """Receive from any connected peer."""

    async def broadcast(self, message: Message):
        """Send to all connected peers (gossip fanout)."""
```

### 9.2 Peer Discovery

- **LAN:** UDP multicast on local network
- **WAN:** Seed nodes (configurable list) + the signal server for NAT traversal
- Signal server is the only externally managed component (per user constraint)

### 9.3 Security

- mTLS between peers using self-signed certificates
- Message signing with peer identity keypair
- Wire serialisation integrity verification (already implemented)

### Acceptance Criteria

- [x] TCP transport passes existing P2P test suite (96 tests)
- [x] Peer discovery finds peers on same LAN
- [ ] WAN peers can connect via signal server
- [x] All messages integrity-verified

---

## 17. File Manifest

Complete list of new and modified files across all phases.

### New Files

| Phase | File | Purpose |
|---|---|---|
| 1 | `ai/scraper/mackolik.py` | arsiv.mackolik.com JSON API client |
| 2 | `ai/common/season.py` | Season state machine (replaces `CURRENT_SEASON`) |
| 2 | `ai/pipeline/resolver.py` | Map user questions → specific fixtures |
| 3 | `p2p/node/identity.py` | Persistent node identity |
| 3 | `ai/scheduler.py` | APScheduler integration |
| 4 | `p2p/coordination/__init__.py` | Package init |
| 4 | `p2p/coordination/election.py` | Deterministic role assignment |
| 4 | `p2p/coordination/tasks.py` | Scrape task queue |
| 4 | `ai/scraper/health.py` | Source health monitor |
| 4 | `ai/proofreader/cross_validator.py` | Cross-source validator |
| 5 | `migrations/002_players.sql` | Player table schema |
| 6 | `ai/model/outcomes.py` | Outcome collector + retrain trigger |
| 6 | `ai/model/drift.py` | Accuracy drift detector |
| 7 | `ai/scraper/schema_fingerprint.py` | DOM structural fingerprinting + drift detection |
| 7 | `ai/scraper/field_discovery.py` | AI-driven field relocation (heuristic + structural + ML) |
| 7 | `ai/scraper/data_contracts.py` | Extraction invariant validation |
| 7 | `ai/scraper/schema_trainer.py` | Self-supervised schema classifier training |
| 7 | `p2p/coordination/schema_gossip.py` | P2P schema proposal, voting, and adoption |
| 7 | `migrations/003_schema_snapshots.sql` | Schema snapshot + discovered schema tables |
| 9 | `p2p/protocol/tcp_transport.py` | Real TCP transport |
| 9 | `p2p/node/discovery.py` | Peer discovery (LAN + WAN) |

### Modified Files

| Phase | File | Change |
|---|---|---|
| 0 | `ai/common/locale_tr.yaml` | Add `mackolik_id`, `source_aliases`, `strength`, `derbies` |
| 0 | `ai/common/locale_loader.py` | Add loaders for new YAML fields |
| 0 | `ai/tqu/questions.py` | Remove hardcoded teams/players, import from locale |
| 0 | `data/generate_match_data.py` | Load teams from locale or CLI |
| 0 | `ai/scraper/real_data.py` | Use `source_aliases` from locale |
| 0 | `ai/common/league_config.py` | Load derbies from YAML |
| 1 | `ai/requirements.txt` | Add `apscheduler>=3.10.0` |
| 2 | `ai/common/constants.py` | Remove `CURRENT_SEASON` |
| 2 | `ai/pipeline/runner.py` | Use `MatchResolver` instead of synthetic features |
| 2 | `ai/trc/verdict.py` | Add `fixture_unknown`, `data_stale` verdict types |
| 3 | `p2p/protocol/messages.py` | Add `HEARTBEAT`, `TASK_CLAIM`, `TASK_COMPLETE` + Phase 4 types |
| 3 | `ai/main.py` | Replace `while True: sleep()` with scheduler |
| 3 | `p2p/main.py` | Replace `while True: sleep()` with scheduler |
| 4 | `ai/scraper/selectors.json` | Add `fallback_selectors` arrays |
| 5 | `ai/tqu/entities.py` | Add fuzzy player name resolution |
| 6 | `ai/model/trainer.py` | Add incremental retrain method |
| 6 | `p2p/node/peer.py` | Model adoption protocol |
| 7 | `ai/scraper/selectors.json` | Auto-updated selectors from adopted schemas |
| 7 | `p2p/protocol/messages.py` | Add `SCHEMA_DRIFT`, `SCHEMA_PROPOSAL`, `SCHEMA_VOTE`, `SCHEMA_ADOPTED` |
| 7 | `ai/scraper/mackolik.py` | Integrate fingerprint drift check on every fetch |

---

## 18. Test Strategy

### Unit Tests (per phase)

| Phase | Test Scope | Test Count (est.) |
|---|---|---|
| 0 | Locale loader returns teams with mackolik_id, source_aliases | +10 |
| 1 | MackolikClient: season discovery, season fetch, match stats, rate limiting | +20 |
| 2 | Season detection, match resolver, confidence gating | +15 |
| 3 | Identity persistence, scheduler job registration | +8 |
| 4 | Election determinism, task claim atomicity, health monitor | +15 |
| 5 | Player fuzzy match, transfer detection | +10 |
| 6 | Outcome buffer, drift detector threshold, incremental retrain | +12 |
| 7 | Schema fingerprinting drift detection, field discovery (3 layers), data contracts, schema trainer, P2P schema gossip quorum | +18 |
| 8 | Selector fallback, graceful degradation chain | +8 |
| 9 | TCP transport conformance with SimulatedTransport interface | +10 |
| **Total** | | **+126 new tests** |

### Integration Tests

| Test | Description |
|---|---|
| Full scrape cycle | MackolikClient → SeasonData → FeatureEngine → Inference |
| Season transition | Load 2024/2025 + 2025/2026, detect promoted/relegated teams |
| Cross-validation | Compare mackolik standings vs TFF standings vs OpenFootball |
| P2P data sync | Peer A scrapes → broadcasts → Peer B receives → predicts |
| Failover | Simulate mackolik down → verify fallback to OpenFootball |

| Adaptive scrape | Inject mutated HTML → drift detected → field discovery → P2P vote → schema adopted |

### Existing Test Baseline

Current: 391 AI + 96 P2P = 487 tests (all passing).
Target: ~~434~~ 487 tests — **exceeded target by 53 tests**.

---

## 19. Risk Matrix

| Risk | Likelihood | Impact | Phase | Mitigation |
|---|---|---|---|---|
| arsiv.mackolik.com changes JSON API | Low | Critical | 1, 7, 8 | Phase 7 adaptive discovery → Phase 8 selector rotation → TFF cross-validation |
| arsiv.mackolik.com blocks scraping | Low | Critical | 1, 8 | Rotate User-Agent; respect rate limits; 5 fallback sources |
| TFF.org ASP.NET postbacks change | Medium | Low | 3 | TFF is cross-validation only; not on critical path |
| Season ID discovery returns empty | Low | Medium | 1, 2 | Cache last-known season IDs; alert on discovery failure |
| Player name fuzzy matching false positives | Medium | Low | 5 | Require >85% Levenshtein similarity; prefer exact match |
| Model divergence across peers | Medium | Medium | 6 | Adoption protocol requires validation on local holdout |
| Football-data.co.uk permanently blocked from network | Medium | Low | 8 | Not on critical path; mackolik covers those features |
| api-sports.io free tier reduced | Low | Low | 5 | mackolik player pages as fallback |
| Field discovery false positive (maps wrong DOM element) | Medium | High | 7 | Data contract validation catches invariant violations before adoption |
| Schema gossip poisoning (malicious peer proposes bad selectors) | Low | High | 7 | Quorum voting (3+ peers confirm); only high-reputation peers can propose |
| Structural drift below threshold (gradual redesign) | Medium | Low | 7 | Baseline fingerprint updated after every successful validated scrape |
| ML classifier insufficient training data (<20 snapshots) | High (early) | Medium | 7 | Heuristic + structural layers run first; ML is Layer 3 fallback |
| NAT traversal failures in production | Medium | Medium | 9 | Signal server relay as last resort |
| Rate limiting triggers IP ban | Low | High | 1 | 5s/request, randomised jitter, respect robots.txt |

---

## Dependency Graph

```
Phase 0 ─────► Phase 1 ─────► Phase 2 ─────► Phase 6
(YAML SoT)     (Mackolik)     (Seasons)       (Learning)
                   │               │               │
                   ▼               ▼               ▼
               Phase 3 ─────► Phase 4          Phase 7
               (Scheduler)    (Coordination)   (Adaptive Scraper)
                   │                               │
                   ▼                               ▼
               Phase 5                         Phase 8
               (Players)                       (Self-Healing)

Phase 7 ── requires Phase 1 (scraper) + Phase 6 (training infra)
Phase 8 ── leverages Phase 7 adaptive selectors; fallback when AI fails
Phase 9 ── independent (can start after Phase 4)
```

**Minimum viable autonomous system:** Phases 0 + 1 + 2 + 3 = arsiv.mackolik.com scraper with season detection, fixture resolution, and scheduled execution. A single peer runs fully autonomously after this milestone.

**Full P2P autonomy:** All 9 phases complete. Multiple peers coordinate scraping, cross-validate data, share models, adapt to source changes via AI discovery, and self-heal from failures.

---

*Source probes performed: 2026-04-07. All HTTP status codes and response sizes verified live.*
