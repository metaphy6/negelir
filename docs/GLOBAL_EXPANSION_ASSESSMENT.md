# Assessment: Extending Predictions to All Mackolik/Nesine Matches

**Date:** 2026-04-16  
**Status:** Feasibility Assessment  
**Author:** Automated Analysis  

---

## Executive Summary

This document assesses the feasibility, risks, and trade-offs of extending Negelir's prediction capability from **Turkish Süper Lig only** to **all football matches listed on Mackolik and Nesine** — covering 40+ leagues, 800+ teams, and 15,000+ matches per season.

**Verdict:** Technically feasible with significant effort. The architecture was designed with multi-league in mind (`LeagueConfig` registry, league-agnostic features), but the entire data pipeline, scraping infrastructure, model training, and operational stack are currently hardcoded to a single league. Expansion is a **Phase 2 project**, not a parameter change.

---

## Current State

| Dimension | Current Scope |
|---|---|
| Leagues | 1 (Turkish Süper Lig) |
| Training data | ~1,469 real matches (5 seasons) |
| Teams tracked | ~30 Turkish teams |
| Scraper targets | Mackolik (TR only), OpenFootball, football-data.co.uk |
| Model | 1 XGBoost classifier, 130 features, trained on TR data |
| Locale | Turkish only (locale_tr.yaml) |
| Elo system | Single pool (~30 teams, 1500 base) |
| Betting markets | 20 types, all tested on Turkish matches |

### What Mackolik/Nesine Actually List

Mackolik covers **50+ competitions** including:

- **Top 5 leagues:** Premier League, La Liga, Bundesliga, Serie A, Ligue 1
- **Secondary leagues:** Eredivisie, Primeira Liga, Süper Lig, etc.
- **Lower divisions:** Championship, 2. Bundesliga, Serie B, Ligue 2, TFF 1. Lig
- **Cup competitions:** Champions League, Europa League, Conference League, FA Cup, Copa del Rey, DFB-Pokal
- **International:** World Cup qualifiers, Euro qualifiers, Nations League, friendlies
- **Exotic:** Saudi Pro League, MLS, J-League, A-League, Brazilian Série A

Nesine (İddaa) typically lists **300-500 matches per week** across ~40 leagues during peak season.

---

## Pros

### 1. Massively Larger Training Dataset
- Current: ~1,500 matches → Potential: **50,000+ matches/season** across all leagues
- More data = better generalization, especially for rare events (red cards, 5+ goals, upsets)
- Cross-league patterns (e.g., Serie A defensive style, Bundesliga high-scoring tendency) provide richer signal

### 2. Architecture Is Partially Ready
- `LeagueConfig` dataclass already exists with stubs for EPL, Bundesliga, La Liga
- 130 features are **league-agnostic** — no Turkish-specific features in the model
- `EloTracker`, `TeamStats`, `H2HTracker` are parameterized by team name, not league
- Self-healing scraper (selector versioning, failover chains) can accommodate new sources
- Docker infrastructure has no league-specific constraints

### 3. Broader User Appeal
- Turkish betting market (İddaa) covers international matches — users already bet on foreign leagues
- Covering all İddaa matches means the AI can answer **any question a user would actually ask**
- Network effects: more users → more diverse questions → better TQU training data

### 4. Model Generalization Benefits
- A model trained on diverse leagues may actually predict Turkish matches **better** by learning universal football patterns rather than overfitting to Süper Lig quirks
- Cross-league transfer learning: Premier League data can inform Turkish predictions

### 5. Competitive Differentiation
- Most free prediction tools focus on top 5 leagues; covering İddaa's full breadth (including lower Turkish divisions and obscure leagues) is a unique selling point

---

## Cons

### 1. Data Quality Varies Dramatically by League
- **Top 5 leagues:** Excellent data (detailed stats, xG, player-level data available)
- **Lower Turkish divisions (TFF 1. Lig, 2. Lig):** Sparse data, missing HT scores, no stats
- **Cup competitions:** Irregular schedules, knockout format breaks rolling averages
- **Friendlies/qualifiers:** No league context, meaningless form data
- Prediction quality will be **highly uneven** — great for EPL, terrible for Saudi 2nd division

### 2. Scraper Complexity Explosion
- Current: 1 Mackolik group ID, 1 set of parsers → Need: **50+ group IDs**, league-specific parsing
- Mackolik's `arsiv.mackolik.com` API uses different `GROUP_ID` per league — all need discovery
- `selectors.json` CSS selectors are version-pinned to Turkish page structure — other leagues may differ
- Rate limiting becomes critical: 50 leagues × 10 matchweeks × 10 matches = **5,000 pages/week** vs current ~50

### 3. Elo System Breaks Down
- Current Elo pool has ~30 teams that play each other regularly → meaningful ratings
- Expanding to 800+ teams across separate leagues creates **disconnected Elo pools**
- How to rate Galatasaray vs Manchester City? Cross-league calibration requires Champions League data or manual anchoring
- Promotion/relegation across leagues creates Elo discontinuities

### 4. Feature Engineering Gaps
- **H2H features** become sparse/empty for most matchups (teams rarely play cross-league)
- **League position features** are meaningless for cups, friendlies, qualifiers
- **Formation/tactical features** require per-team scout data that doesn't scale to 800+ teams
- **Sentiment features** from Turkish media won't cover foreign leagues
- **Derby detection** needs per-league derby definitions (currently only Turkish derbies in locale_tr.yaml)

### 5. Model Strategy Dilemma
- **Single global model:** Loses league-specific patterns (La Liga low-scoring vs Bundesliga high-scoring)
- **Per-league models:** Need sufficient training data per league (lower divisions won't have enough)
- **Hierarchical model:** Complex to build and maintain, adds inference latency
- Current 130-feature XGBoost is tuned for Turkish football — retuning for global data is non-trivial

### 6. Locale & Presentation
- All reports, questions, and templates are Turkish (locale_tr.yaml, TRC composer, TQU patterns)
- Team names need mapping for every league (Mackolik uses localized names: "Bayern Münih" not "Bayern Munich")
- Betting market names and question patterns are Turkish-specific

---

## Feasibility Analysis

### Phase 1: Low-Hanging Fruit (2-4 weeks)

| Task | Effort | Impact |
|---|---|---|
| Parameterize MackolikClient group ID | Small | Unlocks scraping any Mackolik league |
| Add football-data.co.uk CSVs for top 5 leagues | Small | +8,000 matches with full stats |
| Train a single global model on all available data | Medium | Test whether more data helps or hurts |
| Add `--league` flag to backtest evaluator | Small | Per-league accuracy comparison |

**Feasibility:** ✅ High — mostly configuration changes

### Phase 2: Multi-League Infrastructure (4-8 weeks)

| Task | Effort | Impact |
|---|---|---|
| Per-league Elo pools with cross-league calibration | Medium | Accurate strength ratings |
| League-specific `LeagueConfig` with real parameters | Medium | Per-league hyperparameters |
| Expand locale: team maps, derbies, names for top leagues | Large | Correct team identification |
| Season discovery for non-Turkish leagues on Mackolik | Medium | Automated multi-league scraping |
| Rate-limited parallel scraping (respect robots.txt) | Medium | Sustainable data collection |
| Database schema: league_id foreign key everywhere | Medium | Clean multi-league storage |

**Feasibility:** ⚠️ Medium — significant engineering, but no architectural blockers

### Phase 3: Full İddaa Coverage (8-16 weeks)

| Task | Effort | Impact |
|---|---|---|
| Implement Nesine scraper (currently phantom source) | Large | Real-time İddaa match listings |
| Handle cup/knockout competitions (no league table) | Medium | Champions League, FA Cup, etc. |
| Per-league model variants or hierarchical model | Large | Optimal per-league accuracy |
| International match handling (qualifiers, friendlies) | Medium | Full İddaa coverage |
| Lower Turkish divisions (TFF 1. Lig, 2. Lig, 3. Lig) | Medium | Domestic completeness |
| Multi-locale support (team names in native/TR forms) | Medium | Correct presentation |
| Dynamic market availability per league | Small | Not all markets make sense for all leagues |

**Feasibility:** ⚠️ Medium-Low — requires sustained effort and ongoing maintenance

---

## Risks

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Mackolik rate-limits or blocks** at higher scrape volume | High | Critical | Aggressive caching, request spacing (5s+), rotate user agents, fallback to football-data.co.uk |
| **Model accuracy drops** when trained on mixed-league data | Medium | High | League-specific model variants; at minimum, league as a feature input |
| **Elo pool contamination** from disconnected leagues | High | Medium | Separate Elo pools per league, cross-calibrate via European cup results only |
| **Stale data** for leagues with irregular schedules (cups, friendlies) | High | Medium | Staleness penalty (already exists at 7-day threshold), skip prediction for <5 match history |
| **Memory/disk growth** — 50× more matches in DB and cache | Medium | Low | PostgreSQL handles this fine; model size stays <8MB regardless |
| **Inference latency** increases with larger feature lookups | Low | Low | Feature extraction is O(team_history), not O(total_matches) |

### Legal / Compliance Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Mackolik ToS violation** at scale scraping | Medium | High | Respect robots.txt, rate-limit, cache aggressively, consider official API partnership |
| **Nesine scraping** — gambling operator, regulated entity | High | Critical | **Do NOT scrape Nesine directly.** Use İddaa match listings from public TFF or Mackolik sources instead |
| **Data redistribution** — serving scraped data via API | Medium | Medium | Only serve predictions/analysis, never raw scraped data |
| **KVKK (Turkish data protection)** — storing player names | Low | Low | Player names are public data; no personal data processing |

### Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Maintenance burden** — 50 leagues need ongoing selector updates | High | High | Self-healing scraper helps, but broken selectors for a league = silent failures |
| **Prediction quality variance** creates trust issues | Medium | High | Per-league accuracy badges; refuse prediction when confidence < threshold |
| **Scope creep** — users expect player-level, live, and pre-match data for all leagues | Medium | Medium | Clear scope boundaries; document supported vs unsupported leagues |

---

## Data Availability Matrix

| League | Mackolik | OpenFootball | football-data.co.uk | Stats Available | Feasibility |
|---|---|---|---|---|---|
| Turkish Süper Lig | ✅ Full | ✅ 5 seasons | ✅ 8 seasons | FT, HT, stats, odds | ✅ Already done |
| TFF 1. Lig | ✅ Full | ❌ | ✅ 3 seasons | FT, HT, basic odds | ⚠️ Less data |
| Premier League | ✅ Full | ✅ 5+ seasons | ✅ 10+ seasons | FT, HT, stats, odds | ✅ Rich data |
| La Liga | ✅ Full | ✅ 5+ seasons | ✅ 10+ seasons | FT, HT, stats, odds | ✅ Rich data |
| Bundesliga | ✅ Full | ✅ 10+ seasons | ✅ 10+ seasons | FT, HT, stats, odds | ✅ Rich data |
| Serie A | ✅ Full | ✅ 5+ seasons | ✅ 10+ seasons | FT, HT, stats, odds | ✅ Rich data |
| Ligue 1 | ✅ Full | ❌ | ✅ 10+ seasons | FT, HT, stats, odds | ✅ Rich data |
| Eredivisie | ✅ Partial | ❌ | ✅ 5+ seasons | FT, HT, basic odds | ⚠️ OK |
| Champions League | ✅ Full | ❌ | ✅ | FT, HT, odds | ⚠️ Knockout format issues |
| Saudi Pro League | ✅ Partial | ❌ | ❌ | FT only | ❌ Insufficient |
| MLS | ✅ Partial | ❌ | ❌ | FT only | ❌ Insufficient |

---

## Recommended Strategy

### Tier 1 — Expand Now (Low risk, high reward)
Add **Top 5 European leagues** using football-data.co.uk CSVs (free, reliable, 10+ seasons each). This gives ~40,000 additional training matches with full stats. Train a global model and compare accuracy to the Turkish-only model.

### Tier 2 — Expand When Tier 1 Proves Value
Parameterize the Mackolik scraper to support multiple group IDs. Add real-time scraping for Tier 1 leagues. Build per-league Elo pools. This covers **90% of İddaa match volume** (most bets are on top leagues).

### Tier 3 — Full Coverage (Only If Business Justifies)
Lower Turkish divisions, cups, international matches, exotic leagues. High maintenance cost, diminishing returns on prediction quality. Consider leaving these as "low confidence — insufficient data" markets rather than attempting full predictions.

### Do Not Pursue
- **Live/in-play predictions** — entirely different problem (real-time data feeds, sub-second inference)
- **Player-level predictions** (goalscorer, assists) — requires squad/lineup data not available at scale
- **Nesine direct scraping** — legal risk too high for a gambling-regulated platform

---

## Effort Estimate

| Scope | Effort | New Matches | Expected Accuracy |
|---|---|---|---|
| Current (TR Süper Lig only) | Done | ~1,500 | 54-67% (by market) |
| + Top 5 leagues (data only) | 2-3 weeks | +40,000 | 50-65% (cross-league) |
| + Mackolik multi-league scraping | +4-6 weeks | +10,000/season live | 55-70% (top leagues) |
| + Full İddaa coverage | +8-12 weeks | +15,000/season | 40-65% (varies wildly) |

---

## Decision Framework

Expand if:
- [x] Architecture supports it (LeagueConfig, league-agnostic features) — **yes**
- [ ] Sufficient free data sources exist for target leagues — **yes for top 5, no for exotic**
- [ ] Model accuracy improves or holds with more diverse data — **unknown, needs experiment**
- [ ] Scraping at scale is legally and technically sustainable — **technically yes, legally cautious**
- [ ] Maintenance cost is acceptable for a side project — **questionable for 40+ leagues**

**Recommendation:** Start with Tier 1 (football-data.co.uk bulk import for top 5 leagues, single global model experiment). If accuracy holds, proceed to Tier 2. Defer Tier 3 until there's a clear user demand signal.
