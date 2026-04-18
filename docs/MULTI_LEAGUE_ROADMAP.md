# Roadmap: Multi-League Expansion

> **⚠️ DEPRECATED (2026-04-18):** This document is superseded by [ROADMAP.md](ROADMAP.md). Kept for historical reference only. Do not use for planning.

**Date:** 2026-04-18  
**Status:** Deprecated — merged into ROADMAP.md  
**Depends on:** [GLOBAL_EXPANSION_ASSESSMENT.md](GLOBAL_EXPANSION_ASSESSMENT.md) (feasibility study)

---

## Goal

Convert Negelir from a single-league Turkish Süper Lig system to a **multi-league football analysis platform** that can predict and report on any league listed on Mackolik, starting with the top 5 European leagues.

---

## Current Architecture Audit

### What's Already Multi-League Ready

| Component | Status | Notes |
|---|---|---|
| `LeagueConfig` dataclass | ✅ Ready | Stubs for EPL, Bundesliga, La Liga exist with per-league Elo, goal stats, derbies |
| `LEAGUE_REGISTRY` | ✅ Ready | `get_league_config(league_id)` dispatch works |
| DB schema (`league_id`) | ✅ Ready | `teams`, `raw_matches` tables already have `league_id TEXT NOT NULL` |
| Go server | ✅ Ready | Reads `league_id` dynamically from DB, no hardcoding |
| Feature schema (130 features) | ✅ Ready | All features are league-agnostic by design |
| Docker infrastructure | ✅ Ready | No league-specific container constraints |
| Locale loader | ✅ Ready | `NEGELIR_LOCALE` env var → `locale_{lang}.yaml`, fallback mechanism exists |
| Self-healing scraper | ✅ Ready | Selector versioning, failover chains, rate limiting are all generic |

### What's Hardcoded to Turkish

| Subsystem | Severity | Files Affected | Core Issue |
|---|---|---|---|
| **TQU** (Question Understanding) | Critical | 5 files | All regex patterns, suffixes, character folding, questions are Turkish |
| **TRC** (Response Composition) | Critical | 3 files | All verdict text, templates, explanations are Turkish strings |
| **NLP** (Sentiment) | High | 1 file | Positive/negative word lexicon is Turkish-only |
| **Scraper** (Mackolik) | High | 2 files | `GROUP_TURKEY=1`, `"Süper Lig"` filter, `tr.1.json` path |
| **Scraper** (real_data) | High | 1 file | `tr.1.json` URL, `T1` football-data path, Turkish team aliases |
| **Config** | Medium | 2 files | Season IDs, openfootball paths all default to Turkish |
| **Constants** | Medium | 1 file | All team maps, derbies loaded from single Turkish locale |
| **Model** (real_features) | Medium | 1 file | Hardcoded `data/tr_super_lig_real.json` path |
| **Backtest** | Low | 2 files | Turkish report strings, market question templates |
| **Migrations** | Low | 1 file | Seed data only contains Turkish teams |

---

## Phase 0: Foundation — League-Aware Data Layer

**Goal:** Make the data pipeline accept `league_id` as a first-class parameter everywhere.  
**Duration:** ~1 week  
**Risk:** Low — refactoring, no new features

### 0.1 Config: Per-League Data Source Registry

**File:** `ai/common/config.py`

Currently season IDs and data source paths are flat properties that return Turkish data:

```python
# Current — hardcoded Turkish
_mackolik_season_2025_2026: str = "70381"
openfootball_seasons → "2018-19,...,2025-26"  # tr.1.json
footballdata_uk_seasons → "2526:2025-26,..."  # /T1/ path
```

**Change to:** A `league_data_sources` property that returns source configs keyed by `league_id`:

```python
# Target structure
league_data_sources = {
    "tr_super_lig": {
        "mackolik_group_id": 1,
        "mackolik_seasons": {"2025/2026": 70381, ...},
        "openfootball_path": "tr.1.json",
        "footballdata_country": "T1",
        "footballdata_seasons": {"2526": "2025-26", ...},
    },
    "en_premier_league": {
        "mackolik_group_id": 2,   # TBD: discover from Mackolik
        "openfootball_path": "en.1.json",
        "footballdata_country": "E0",
        "footballdata_seasons": {"2526": "2025-26", ...},
    },
    ...
}
```

This can be driven by a `league_sources.yaml` config file or env-var-per-league pattern.

### 0.2 Mackolik Client: Parameterize Group ID

**File:** `ai/scraper/mackolik.py`

| Change | Current | Target |
|---|---|---|
| Class init | `GROUP_TURKEY = 1` (class constant) | `__init__(self, group_id: int, league_name_filter: str)` |
| `discover_seasons()` | Filters `"Süper Lig"` | Uses `self.league_name_filter` |
| All `params={"group": ...}` | Uses `self.GROUP_TURKEY` | Uses `self.group_id` |

Stat label parsing (`"Toplam Şut"`, `"Korner"`, etc.) stays Turkish — Mackolik's HTML is always Turkish regardless of which league is being viewed.

### 0.3 Real Data Scraper: League-Parameterized Paths

**File:** `ai/scraper/real_data.py`

| Change | Current | Target |
|---|---|---|
| OpenFootball URL | `f"{base}/{season}/tr.1.json"` | `f"{base}/{season}/{league_path}"` where `league_path` comes from config |
| football-data.co.uk | Uses `T1` (Turkey) | Uses per-league country code (`E0`, `D1`, `SP1`, `I1`, `F1`) |
| `_HISTORICAL_ALIASES` | 50+ Turkish team name aliases | Per-league alias dicts loaded from locale YAML |
| Cache file path | `data/tr_super_lig_real.json` | `data/{league_id}_real.json` |

### 0.4 Data Contracts: League-Aware Validation

**File:** `ai/scraper/data_contracts.py`

```python
# Current
lambda v, _: 18 <= v <= 21  # "Süper Lig has 18-21 teams"

# Target
lambda v, ctx: ctx.league_config.teams_count - 2 <= v <= ctx.league_config.teams_count + 2
```

### 0.5 Pipeline Runner: Remove Hardcoded Paths

**File:** `ai/pipeline/runner.py`

| Change | Current | Target |
|---|---|---|
| Cache paths | `"/data/tr_super_lig_real.json"` | `f"/data/{league_id}_real.json"` |
| `league_id` in match records | `"league_id": "super_lig"` | `"league_id": self.league_id` |
| Demo labels | `"Turkish Q&A Demo"` | `f"{league_config.league_name} Analysis"` |

### 0.6 Model: Real Features League Binding

**File:** `ai/model/real_features.py`

| Change | Current | Target |
|---|---|---|
| Cache paths | `data/tr_super_lig_real.json` | `data/{league_id}_real.json` |
| `DERBIES_SET` import | From Turkish constants | From `league_config.derbies` |
| `MACKOLIK_ID_MAP` import | From Turkish constants | From league-specific locale |

### 0.7 DB Seed Migration

**File:** New `migrations/004_multi_league_seeds.sql`

Add seed data for target leagues. The schema already supports `league_id` — only seed `INSERT` statements are missing for non-Turkish teams.

**Deliverable:** `make ai-pipeline --league en_premier_league` loads EPL data end-to-end.

---

## Phase 1: Bulk Data Import — Top 5 Leagues

**Goal:** Import 40,000+ historical matches from football-data.co.uk for EPL, Bundesliga, La Liga, Serie A, Ligue 1. Train a global model and compare accuracy.  
**Duration:** ~2 weeks  
**Risk:** Low — uses free, reliable, well-structured CSV source  
**Depends on:** Phase 0

### 1.1 football-data.co.uk Multi-League Downloader

**File:** `ai/scraper/real_data.py` (extend existing)

football-data.co.uk uses country codes in URL paths:

| League | Code | URL Pattern | Seasons Available |
|---|---|---|---|
| English Premier League | `E0` | `/mmz4281/{season}/E0.csv` | 1993-2026 (30+) |
| German Bundesliga | `D1` | `/mmz4281/{season}/D1.csv` | 1993-2026 (30+) |
| Spanish La Liga | `SP1` | `/mmz4281/{season}/SP1.csv` | 1993-2026 (30+) |
| Italian Serie A | `I1` | `/mmz4281/{season}/I1.csv` | 1993-2026 (30+) |
| French Ligue 1 | `F1` | `/mmz4281/{season}/F1.csv` | 1993-2026 (30+) |
| TFF 1. Lig | `T2` | `/mmz4281/{season}/T2.csv` | 2018-2026 |

Each CSV includes: date, home/away teams, FT/HT scores, shots, corners, fouls, cards, referee, and Bet365/Pinnacle odds.

**Task:** Add `download_league(league_id, country_code, seasons)` method that downloads, parses, and caches to `data/{league_id}_real.json`.

### 1.2 OpenFootball Multi-League Paths

OpenFootball has data for several leagues with different path conventions:

| League | Path | Available Seasons |
|---|---|---|
| English Premier League | `en.1.json` | 5+ seasons |
| German Bundesliga | `de.1.json` | 10+ seasons |
| Spanish La Liga | `es.1.json` | 5+ seasons |
| Italian Serie A | `it.1.json` | 5+ seasons |
| Turkish Süper Lig | `tr.1.json` | 5 seasons |

**Task:** Map `league_id` → OpenFootball path in config, use in `RealDataScraper`.

### 1.3 League-Specific LeagueConfig Tuning

**File:** `ai/common/league_config.py`

Fill in real empirical parameters for each league. The stubs exist but need validation:

| Parameter | TR | EPL | BUN | LIG | SER | L1 |
|---|---|---|---|---|---|---|
| `teams_count` | 19 | 20 | 18 | 20 | 20 | 18 |
| `rounds_per_season` | 38 | 38 | 34 | 38 | 38 | 34 |
| `league_avg_goals` | 2.65 | 2.70 | 2.90 | 2.55 | 2.60 | 2.55 |
| `elo_home_advantage` | 65 | 55 | 60 | 58 | 62 | 58 |
| `first_half_goal_pct` | 0.47 | 0.46 | 0.46 | 0.47 | 0.46 | 0.47 |
| `dixon_coles_rho` | -0.13 | -0.11 | -0.12 | -0.14 | -0.13 | -0.13 |

**Task:** Compute real values from the imported historical data. Add Italian Serie A and French Ligue 1 factories to `league_config.py`.

### 1.4 Per-League Elo Pools

**File:** `ai/model/real_features.py`

Currently `EloTracker` maintains one pool for all teams. With 800+ teams across 6 leagues, we need **separate pools per league**:

```python
class EloTracker:
    def __init__(self):
        self.ratings = {}        # Current: single dict
        
    # Target: per-league pools
    def __init__(self):
        self.pools: dict[str, dict[str, float]] = {}  # league_id → {team → elo}
```

Cross-league calibration (optional Phase 3): use Champions League / Europa League results to anchor leagues relative to each other.

### 1.5 Global Model Experiment

**Task:** Train XGBoost on all ~45,000 matches across 6 leagues. Add `league_id` as a categorical feature (one-hot or ordinal). Compare:

| Experiment | Training Data | Test Set | Metric |
|---|---|---|---|
| Baseline | TR only (~1,500) | TR last 10 weeks | Current ~54% |
| Global | All 6 leagues (~45,000) | TR last 10 weeks | ? |
| Global | All 6 leagues (~45,000) | EPL last 10 weeks | ? |
| Per-league | EPL only (~8,000) | EPL last 10 weeks | ? |

### 1.6 Backtest: Add `--league` Flag

**File:** `ai/backtest/evaluator.py`

```
python -m backtest.evaluator --weeks 10 --league en_premier_league
python -m backtest.evaluator --weeks 10 --league all  # compare across leagues
```

**Deliverable:** Accuracy comparison report across all 6 leagues. Go/no-go decision for Phase 2.

---

## Phase 2: Live Multi-League Scraping

**Goal:** Real-time match data from Mackolik for all target leagues, not just historical CSVs.  
**Duration:** ~3-4 weeks  
**Risk:** Medium — Mackolik rate limiting, league ID discovery  
**Depends on:** Phase 1 (need historical data first)

### 2.1 Mackolik League Discovery

**File:** `ai/scraper/mackolik.py`

Mackolik's `CompetitionHandler.aspx?op=groupYears` returns all available league groups. We need a one-time discovery script:

```python
def discover_all_leagues(self) -> dict[str, int]:
    """Discover all available league group IDs on Mackolik."""
    # Returns: {"Süper Lig": 1, "Premier Lig": 2, "La Liga": 7, ...}
```

**Task:** Build discovery, then hardcode the stable group IDs into league config (Mackolik group IDs rarely change).

### 2.2 Rate-Limited Parallel Scraping

Currently scraping 1 league → ~50 requests/week. With 6 leagues → ~300 requests/week.

**Constraints:**
- `SCRAPE_RATE_LIMIT_SECONDS=5` (current default, 5s between requests per domain)
- Mackolik `robots.txt` compliance
- Target: <500 requests/day total across all leagues

**Implementation:** Queue-based scraper with per-domain rate bucket:

```python
class MultiLeagueScraper:
    def __init__(self, leagues: list[str]):
        self.clients = {lid: MackolikClient(group_id=...) for lid in leagues}
    
    async def scrape_all(self):
        for league_id, client in self.clients.items():
            client.fetch_results(...)
            await asyncio.sleep(self.rate_limit)  # respect rate limit
```

### 2.3 Season Auto-Discovery Per League

**File:** `ai/common/season.py`

`detect_season()` is already league-agnostic in logic. It just needs to be called per league:

```python
for league_id in active_leagues:
    client = MackolikClient(group_id=league_sources[league_id].mackolik_group_id)
    seasons = client.discover_seasons()
    state = detect_season(seasons, client.fetch_results)
```

### 2.4 Stale Data Handling

Different leagues have different schedules:
- **European leagues:** Aug-May, winter break in Dec-Jan (Bundesliga), no break (EPL)
- **MLS:** Feb-Oct
- **Saudi:** Aug-May

The existing `SelfHealingEngine` already has a 7-day staleness threshold. Per-league scheduling awareness is a nice-to-have but not required — the staleness penalty handles it.

### 2.5 Team Name Normalization Per League

**File:** New locale files (e.g., `locale_en.yaml`, `locale_de.yaml`)

Mackolik uses Turkish-localized team names:

| Mackolik Name | Canonical Name |
|---|---|
| Bayern Münih | Bayern München |
| Atletico Madrid | Atlético Madrid |
| Bordo-Beyazlılar (contextual) | Trabzonspor |

**Task:** Create per-league team alias mappings in locale YAML files, loaded by `locale_loader.py`.

**Deliverable:** `make ai-pipeline --league en_premier_league` fetches live Mackolik data + historical CSVs, trains a model, runs inference.

---

## Phase 3: Multi-Locale NLP Stack

**Goal:** Enable question understanding and response composition in multiple languages (or at minimum, handle foreign team/league names within Turkish).  
**Duration:** ~4-6 weeks  
**Risk:** High — TQU and TRC are deeply Turkish  
**Depends on:** Phase 1 (can be parallelized with Phase 2)

### Decision: Multi-Language vs Turkish-Only with Multi-League

Two approaches:

| Approach | Effort | UX |
|---|---|---|
| **A) Turkish UI, all leagues** | Medium | User asks in Turkish about any league: *"Arsenal Liverpool maçını kim kazanır?"* |
| **B) Multi-language UI** | Very High | User asks in English about EPL, Turkish about Süper Lig |

**Recommendation:** Start with **Approach A** — Turkish UI with foreign league support. This is the İddaa use case (Turkish users betting on foreign leagues). Multi-language UI is a separate project.

### 3.1 TQU: Foreign Team Name Recognition

**File:** `ai/tqu/entities.py`, `ai/tqu/normalizer.py`

The normalizer strips Turkish suffixes (`-in`, `-de`, `-nın`, etc.) from team names. Foreign team names go through the same pipeline:

```
"Arsenal'ın maçı" → strip suffix → "Arsenal" → lookup in team registry
"Bayern Münih kazanır mı?" → strip suffix → "Bayern Münih" → lookup
```

**Task:** Extend `ALL_TEAM_NAMES` (loaded from locale) to include all tracked league teams. The Turkish suffix stripping already handles possessive forms on foreign names.

### 3.2 TQU: League Context Detection

New entity type: **league mention**

```python
LEAGUE_PATTERNS = {
    r"(?:premier\s*lig|ingiliz\s*ligi|epl)": "en_premier_league",
    r"(?:la\s*liga|ispanyol\s*ligi)": "es_la_liga",
    r"(?:bundesliga|alman\s*ligi)": "de_bundesliga",
    r"(?:serie\s*a|italyan\s*ligi)": "it_serie_a",
    r"(?:ligue\s*1|fransız\s*ligi)": "fr_ligue_1",
    r"(?:süper\s*lig|türk\s*ligi)": "tr_super_lig",
}
```

If no league is mentioned, infer from team names (Arsenal → EPL, Bayern → Bundesliga).

### 3.3 TRC: League-Aware Response Templates

**File:** `ai/trc/templates.py`

Templates are Turkish text with placeholders. They work for any league — the team names and stats are variables:

```python
# This already works for any league:
"Ev sahibi {home_team} son {n} maçta {wins} galibiyet aldı."
# → "Ev sahibi Arsenal son 5 maçta 4 galibiyet aldı."
```

**Additions needed:**
- League name in responses: *"Premier Lig'de Arsenal..."*
- League-specific context phrases: *"İngiltere'de oynanan bu maçta..."*

### 3.4 NLP Sentiment: Foreign League Coverage

**File:** `ai/nlp/sentiment.py`

Turkish sports media (Fanatik, Fotomaç, NTVSpor) also covers international football. The Turkish sentiment lexicon works for Turkish articles about foreign matches.

**For Phase 3, no change needed** — sentiment analysis stays Turkish since the user base and media sources are Turkish.

### 3.5 Backtest: Multi-League Report

**File:** `ai/backtest/evaluator.py`, `ai/backtest/bet_types.py`

Market question templates in `MARKET_QUESTIONS_TR` work for any league — they reference generic match concepts, not league-specific terms.

**Addition:** League name in report headers:

```
NEGELIR — KAPSAMLI BAHİS TAHMİN RAPORU
Premier Lig • Son 10 Hafta • 95 Maç • 18 Bahis Türü
```

**Deliverable:** User can ask *"Arsenal Liverpool maçını kim kazanır?"* and get a Turkish analysis powered by EPL data.

---

## Phase 4: Model Strategy — Global vs Per-League

**Goal:** Determine optimal model architecture for multi-league predictions.  
**Duration:** ~2-3 weeks  
**Risk:** Medium — requires experimentation  
**Depends on:** Phase 1 (needs accuracy data from global model experiment)

### 4.1 Experiment Matrix

| Strategy | Description | Pros | Cons |
|---|---|---|---|
| **Single global model** | One XGBoost on all leagues, `league_id` as feature | Simpler, more training data | May blur league-specific patterns |
| **Per-league models** | Separate XGBoost per league | Captures league specifics | Lower Turkish divisions lack data |
| **Hierarchical** | Global base + per-league fine-tuning | Best of both | Complex training pipeline |
| **League-as-feature** | One model, league is a one-hot input feature | Simple, lets model learn league effects | Needs enough data per league |

### 4.2 Decision Criteria

Choose **single global model with league-as-feature** if:
- Global model accuracy on Turkish data >= Turkish-only model accuracy - 2pp
- Global model accuracy on EPL >= 50%

Choose **per-league models** if:
- Per-league models beat global model by >5pp on their own league
- Each target league has >2,000 training matches

Choose **hierarchical** only if:
- Both above strategies underperform
- Clear evidence that league-specific patterns matter more than universal football patterns

### 4.3 Feature Engineering Updates

New features for multi-league context:

| Feature | Type | Description |
|---|---|---|
| `league_id_encoded` | Categorical (one-hot) | Which league this match belongs to |
| `league_avg_goals` | Float | League-specific average goals per match |
| `league_home_win_pct` | Float | League-specific home win percentage |
| `league_draw_pct` | Float | League-specific draw rate |
| `league_strength_tier` | Ordinal (1-5) | Overall league quality ranking |

### 4.4 Model Versioning

```
data/models/negelir_gbdt_v0.3.0.pkl      # Current: TR-only
data/models/negelir_gbdt_v0.4.0.pkl      # Phase 1: Global model
data/models/negelir_gbdt_v0.4.0_epl.pkl  # Phase 4: Per-league variant (if needed)
```

**Deliverable:** Chosen model strategy with accuracy benchmarks per league.

---

## Phase 5: Cup & Knockout Competitions

**Goal:** Handle Champions League, Europa League, domestic cups where league table context doesn't exist.  
**Duration:** ~2-3 weeks  
**Risk:** Medium — different data structure  
**Depends on:** Phase 2

### 5.1 Competition Type Classification

```python
class CompetitionType(Enum):
    LEAGUE = "league"       # Round-robin, standings exist
    CUP = "cup"            # Knockout, no standings
    GROUP_STAGE = "group"   # Group phase of cups (mini-league)
    FRIENDLY = "friendly"   # No competitive context
    QUALIFIER = "qualifier" # International qualifiers
```

### 5.2 Feature Fallbacks for Non-League Matches

| Feature | League Match | Cup Match | Fallback |
|---|---|---|---|
| League position | From standings | N/A | Use team's domestic league position |
| Points gap to leader | From standings | N/A | 0 (neutral) |
| Relegation pressure | From standings | N/A | 0 (neutral) |
| Season phase | Week / total weeks | Round (R32, QF, SF, F) | Map to early/mid/late |
| H2H | Domestic league H2H | Cross-league H2H (sparse) | Use Elo differential only |

### 5.3 Cross-League Elo Calibration

For Champions League: teams from different leagues meet. Elo pools are separate.

**Approach:** Use Champions League group stage results to compute a **league strength offset**:

```
EPL_offset = +50    (based on CL results)
Bundesliga_offset = +30
La Liga_offset = +45
Serie A_offset = +25
Süper Lig_offset = 0 (baseline)
```

When teams from different leagues meet:

```
effective_elo = domestic_elo + league_offset
```

**Deliverable:** Champions League match predictions using cross-calibrated Elo.

---

## Phase 6: Lower Turkish Divisions & Full İddaa Coverage

**Goal:** TFF 1. Lig, 2. Lig for domestic completeness + any remaining İddaa-listed leagues.  
**Duration:** ~3-4 weeks  
**Risk:** High — sparse data, diminishing returns  
**Depends on:** Phases 1-4

### 6.1 TFF 1. Lig

- football-data.co.uk: Available as `T2` (3+ seasons)
- Mackolik: Full coverage with different `GROUP_ID`
- Data quality: FT/HT scores reliable, stats sparse
- Team count: 18 teams, high promotion/relegation churn

### 6.2 Confidence-Gated Predictions

For leagues with insufficient data, refuse prediction rather than give bad ones:

```python
def can_predict(self, league_id: str, team_history: int) -> tuple[bool, str]:
    if team_history < 10:
        return False, "Yetersiz veri — bu takım için en az 10 maçlık geçmiş gerekli."
    if league_id in LOW_DATA_LEAGUES and team_history < 20:
        return False, "Bu lig için güvenilir tahmin üretmek için daha fazla veri gerekli."
    return True, ""
```

### 6.3 Dynamic Market Availability

Not all betting markets make sense for all leagues:

| Market | Top 5 Leagues | Lower Divisions | Cups |
|---|---|---|---|
| 1X2 | ✅ | ✅ | ✅ |
| Over/Under 2.5 | ✅ | ✅ | ✅ |
| Correct Score | ✅ | ⚠️ (low confidence) | ⚠️ |
| HT/FT | ✅ | ⚠️ | ✅ |
| Cards | ❌ (no data) | ❌ | ❌ |
| Clean Sheet | ✅ | ⚠️ | ✅ |

**Deliverable:** Full İddaa league coverage with per-league confidence gates.

---

## Implementation Order & Dependencies

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 5
  │              │            │
  │              └──→ Phase 4 ┘
  │              │
  └──────→ Phase 3
                 │
                 └──────────────→ Phase 6
```

| Phase | Name | Depends On | Duration | Risk |
|---|---|---|---|---|
| **0** | Foundation — League-Aware Data Layer | — | ~1 week | Low |
| **1** | Bulk Data Import — Top 5 Leagues | Phase 0 | ~2 weeks | Low |
| **2** | Live Multi-League Scraping | Phase 1 | ~3-4 weeks | Medium |
| **3** | Multi-Locale NLP Stack | Phase 0 | ~4-6 weeks | High |
| **4** | Model Strategy | Phase 1 | ~2-3 weeks | Medium |
| **5** | Cup & Knockout Competitions | Phase 2 | ~2-3 weeks | Medium |
| **6** | Lower Divisions & Full İddaa | Phases 1-4 | ~3-4 weeks | High |

**Total estimated effort:** 16-24 weeks (Phases 0-6)  
**Minimum viable multi-league (Phases 0-1):** 3 weeks

---

## File Change Inventory

### Phase 0 Changes (Foundation)

| File | Change Type | Description |
|---|---|---|
| `ai/common/config.py` | Modify | Add `league_data_sources` property, parameterize season/path configs |
| `ai/scraper/mackolik.py` | Modify | Accept `group_id` + `league_filter` in constructor |
| `ai/scraper/real_data.py` | Modify | Parameterize `tr.1.json` → `{league_path}`, `T1` → `{country_code}`, alias dicts |
| `ai/scraper/data_contracts.py` | Modify | League-aware team count validation |
| `ai/model/real_features.py` | Modify | Parameterize cache file paths, per-league Elo pools |
| `ai/pipeline/runner.py` | Modify | Accept `league_id`, remove hardcoded paths |
| `ai/common/constants.py` | Modify | Load constants per league, not just Turkish |

### Phase 1 Changes (Data Import)

| File | Change Type | Description |
|---|---|---|
| `ai/scraper/real_data.py` | Extend | `download_league()` for football-data.co.uk multi-league CSV |
| `ai/common/league_config.py` | Extend | Add `it_serie_a` and `fr_ligue_1` factories, tune parameters |
| `ai/model/trainer.py` | Modify | Accept multi-league training data, add `league_id` feature |
| `ai/model/features.py` | Extend | Add league context features (5 new features) |
| `ai/backtest/evaluator.py` | Extend | Add `--league` flag |
| `Makefile` | Extend | Per-league make targets |

### Phase 2 Changes (Live Scraping)

| File | Change Type | Description |
|---|---|---|
| `ai/scraper/mackolik.py` | Extend | `discover_all_leagues()` |
| `ai/common/season.py` | Modify | Per-league season detection loop |
| `ai/scheduler.py` | Modify | Multi-league scrape scheduling |
| New `ai/common/locale_en.yaml` | Create | EPL team names, aliases |
| New `ai/common/locale_de.yaml` | Create | Bundesliga team names, aliases |
| New `ai/common/locale_es.yaml` | Create | La Liga team names, aliases |
| `docker-compose.yml` | Modify | Add league env vars, `ACTIVE_LEAGUES` list |

### Phase 3 Changes (NLP)

| File | Change Type | Description |
|---|---|---|
| `ai/tqu/entities.py` | Extend | Foreign team name recognition |
| `ai/tqu/patterns.py` | Extend | League context detection patterns |
| `ai/trc/templates.py` | Extend | League-name-aware template variants |
| `ai/trc/composer.py` | Modify | Include league context in responses |
| `ai/backtest/bet_types.py` | Modify | League name in report headers |

---

## Milestones & Go/No-Go Gates

### Gate 1: After Phase 1
**Question:** Does more data help?

| Metric | Pass | Fail |
|---|---|---|
| Global model accuracy on Turkish data | ≥52% (within 2pp of current 54%) | <50% |
| Global model accuracy on EPL | ≥48% | <40% |
| Data import pipeline reliability | All 6 leagues loaded without error | >1 league fails |

**If pass:** Proceed to Phases 2-4.  
**If fail:** Stay single-league, use imported data only for research.

### Gate 2: After Phase 4
**Question:** Which model strategy works best?

| Metric | Pass | Fail |
|---|---|---|
| Best strategy beats Turkish-only baseline on TR data | Yes, or within 1pp | >3pp worse |
| Best strategy achieves >50% on each top-5 league | Yes | >2 leagues below 45% |

**If pass:** Proceed to Phases 5-6.  
**If fail:** Ship per-league models for leagues with enough data only.

---

## Risk Register

| # | Risk | Likelihood | Impact | Phase | Mitigation |
|---|---|---|---|---|---|
| R1 | Mackolik rate-limits at 6× scrape volume | High | Critical | 2 | 5s rate limit, per-domain buckets, aggressive caching |
| R2 | Global model accuracy drops on Turkish data | Medium | High | 1 | Keep Turkish-only model as fallback, A/B test |
| R3 | Elo pools diverge (no cross-league signal) | High | Medium | 1 | Separate pools by default, CL calibration in Phase 5 |
| R4 | football-data.co.uk data format changes | Low | Medium | 1 | Self-healing CSV parser, pin column names |
| R5 | Team name mismatch across sources | High | Medium | 0-2 | Per-league alias maps in locale YAML, fuzzy matching |
| R6 | Mackolik group IDs change per league | Low | Low | 2 | Annual rediscovery script, hardcode stable IDs |
| R7 | Lower-division data too sparse for meaningful predictions | High | Low | 6 | Confidence gating — refuse prediction below threshold |
| R8 | Scope creep — users demand player-level predictions | Medium | Medium | 3+ | Document supported scope clearly in app |
| R9 | Nesine scraping legal risk | High | Critical | Never | Do NOT scrape Nesine. Use Mackolik/TFF for İddaa match listings |
| R10 | N_FEATURES changes break model compatibility | Medium | High | 1 | Version features alongside model (v0.4.0 = 135 features) |

---

## Quick Reference: Data Source Codes

| League | football-data.co.uk | OpenFootball | Mackolik Group (est.) |
|---|---|---|---|
| Turkish Süper Lig | `T1` | `tr.1.json` | 1 |
| TFF 1. Lig | `T2` | — | TBD |
| English Premier League | `E0` | `en.1.json` | TBD |
| English Championship | `E1` | — | TBD |
| German Bundesliga | `D1` | `de.1.json` | TBD |
| German 2. Bundesliga | `D2` | — | TBD |
| Spanish La Liga | `SP1` | `es.1.json` | TBD |
| Spanish Segunda | `SP2` | — | TBD |
| Italian Serie A | `I1` | `it.1.json` | TBD |
| Italian Serie B | `I2` | — | TBD |
| French Ligue 1 | `F1` | `fr.1.json` | TBD |
| French Ligue 2 | `F2` | — | TBD |
| Dutch Eredivisie | `N1` | — | TBD |
| Portuguese Liga | `P1` | — | TBD |
| Belgian Pro League | `B1` | — | TBD |
| Scottish Premiership | `SC0` | — | TBD |
