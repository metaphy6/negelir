# Generic User Input Handling — Analysis & Mitigation Report

**Date:** 2026-04-07  
**Scope:** End-to-end audit of how Negelir processes user questions, resolves match context, and relies on hardcoded data that will break when real-world conditions change (transfers, season rollover, team renaming, lineup rotation).

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Input Flow](#2-current-input-flow)
3. [Hardcoded Data Inventory](#3-hardcoded-data-inventory)
4. [Failure Scenarios](#4-failure-scenarios)
5. [Mitigation Roadmap](#5-mitigation-roadmap)
6. [Architecture Proposal](#6-architecture-proposal)
7. [Migration Priority](#7-migration-priority)

---

## 1. Executive Summary

The system processes Turkish football questions through a layered pipeline (TQU → Features → GBDT → TRC), but **critical integration points rely on static data baked into Python source files and JSON fixtures**. The three most dangerous categories are:

| Category | Staleness Window | Impact |
|---|---|---|
| Player rosters | Every transfer window (Jan, Jul) | Wrong team–player associations; misleading questions |
| Match fixtures & season | Every June/July | Entire prediction pipeline outputs stale data |
| Team name registry | Any rename, promotion, relegation | Entity extraction fails silently → fallback to synthetic |

The system currently has **no mechanism to detect or recover from stale data**. When a player transfers or a season rolls over, the system continues to serve answers confidently using outdated information — the worst failure mode for a prediction system.

---

## 2. Current Input Flow

```
User: "Icardi bu maçta gol atar mı?"
           │
           ▼
┌─────────────────────────────────────────────────┐
│  TQU Sanitizer  (tqu/sanitizer.py)              │
│  • Length check (MAX_INPUT_LENGTH = 200)         │
│  • Injection detection                          │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  TQU Normalizer  (tqu/normalizer.py)            │
│  • ASCII-fold Turkish chars                     │
│  • Dedup repeated chars                         │
│  • Strip suffixes (hardcoded list, 35 suffixes) │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  Domain Gate  (tqu/classifier.py)               │
│  • Check FOOTBALL_KEYWORDS (160+ from YAML)     │
│  • Check TEAM_MAP aliases (49 from YAML)        │
│  ⚠ "Icardi" isn't in either list — passes      │
│    only because "gol" and "atar" are keywords   │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  Intent Classifier  (tqu/classifier.py)         │
│  • 10 intent patterns (hardcoded Turkish regex) │
│  • Confidence threshold: 0.6                    │
│  → Intent: "score_predict" or "form_query"      │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  Entity Extraction  (tqu/entities.py)           │
│  • Team names → UUIDs via TEAM_MAP              │
│  • Numbers (goal thresholds)                    │
│  • Temporal refs (bugün, yarın, bu hafta)       │
│  ⚠ "Icardi" → NO MATCH (not in TEAM_MAP,       │
│    no player lookup table exists)               │
│  ⚠ "bu maçta" → NO MATCH_ID resolution         │
│    (no fixture schedule/date lookup)            │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  Feature Engineering  (model/features.py)       │
│  • 130 FEATURE_COLUMNS (hardcoded names)        │
│  • Synthetic ranges if real data unavailable    │
│  ⚠ No player-level features exist at all        │
│  ⚠ No dynamic fixture lookup → uses demo data   │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  Inference  (model/inference.py)                │
│  • XGBoost 3-class + Poisson ensemble           │
│  • Dixon-Coles correction (ρ = −0.13)           │
│  ⚠ Answers as if confident, even when match     │
│    context was never resolved                   │
└─────────────────┬───────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────┐
│  TRC Composer  (trc/composer.py + templates.py) │
│  • Verdict selection from 7 static keys         │
│  • Template fill from pre-written Turkish text  │
│  ⚠ Response never mentions that the player      │
│    or match couldn't be identified              │
└─────────────────────────────────────────────────┘
```

**Key failure:** The pipeline has no "I don't know this entity" path. Unresolved players and matches silently fall through to synthetic/demo features, and the system answers confidently with fabricated context.

---

## 3. Hardcoded Data Inventory

### 3.1 Player Rosters (Highest Churn)

**File:** `ai/tqu/questions.py` lines 503–513

```python
_PLAYER_TEAMS = {
    "Galatasaray":  ["Icardi", "Mertens", "Zaha", "Muslera"],
    "Fenerbahçe":   ["Dzeko", "Tadic", "Szymanski", "Livakovic"],
    "Beşiktaş":     ["Cenk Tosun", "Gedson", "Weghorst", "Günok"],
    "Trabzonspor":  ["Bakasetas", "Trezeguet", "Visca", "Uğurcan"],
}
```

**Problems:**
- Icardi left Galatasaray (Jan 2025). Weghorst left Beşiktaş. Mertens retired.
- Only 4 teams covered out of 19+.
- Names are used to generate demo/test questions — but the system cannot resolve `"Icardi"` back to a team at inference time because **no player→team lookup exists in entity extraction**.
- Player names appear ONLY in question generation, never in the prediction pipeline itself — meaning they're decorative, not functional.

### 3.2 Team Registry (Moderate Churn)

**Files and duplication count:**

| File | Purpose | Team Count | Synced? |
|---|---|---|---|
| `ai/common/locale_tr.yaml` | Canonical source (YAML) | 24 teams | Source of truth |
| `ai/tqu/questions.py:13–33` | Question generation | 22 teams + 6 derbies | ❌ Independent copy |
| `data/generate_match_data.py:24–32` | Synthetic data gen | 19 teams + strengths | ❌ Independent copy |
| `ai/scraper/real_data.py:75–122` | Scraper normalisation | 40+ name variants | ❌ Independent copy |
| `ai/common/league_config.py:47–59` | Derby definitions | 6 derbies | ❌ Independent copy |

**Five independent copies of team lists** that must be manually kept in sync. A team rename, promotion, or relegation requires edits in 5 files.

### 3.3 Match Context Resolution (Non-Existent)

The system has **zero ability** to resolve a user's question to a specific upcoming match:

- `"Bu maçta"` (in this match) → no match_id lookup
- `"Bu hafta sonu"` (this weekend) → temporal ref extracted but unused
- `"Galatasaray Fenerbahçe derbi"` → teams extracted but no fixture found
- `"Yarınki maç"` (tomorrow's match) → date parsed but no schedule queried

Entity extraction in `tqu/entities.py` captures team UUIDs and temporal references, but the pipeline runner in `pipeline/runner.py` never uses them to query a fixture database. Instead, it falls through to synthetic demo features.

### 3.4 Season & Configuration Constants

| Constant | File | Value | Update Frequency |
|---|---|---|---|
| `CURRENT_SEASON` | `ai/common/constants.py:8` | `"2025-2026"` | Annual (manual) |
| `MODEL_VERSION` | `ai/common/constants.py:7` | `"0.3.0"` | Per release |
| `N_FEATURES` | `ai/common/constants.py:10` | `130` | Per schema change |
| `XGB_WEIGHT` | `ai/model/inference.py:23` | `0.35` | Tuning-dependent |
| `DIXON_COLES_RHO` | `ai/model/inference.py:26` | `-0.13` | Tuning-dependent |
| `CONFIDENCE_THRESHOLD` | `ai/tqu/classifier.py:19` | `0.6` | Tuning-dependent |
| `LEAGUE_AVG_GOALS` | `data/generate_match_data.py:49` | `1.35` | Seasonal |
| `HOME_ADVANTAGE` | `data/generate_match_data.py:50` | `0.25` | Seasonal |

### 3.5 Response Templates (Low Churn, High Rigidity)

`ai/trc/templates.py` contains 120+ pre-written Turkish sentence templates across 8 intent types. These are authored by a native speaker (per roadmap §5.1) and don't change often, but they're **not parameterised by locale** and assume Turkish-only output permanently.

### 3.6 Scraper Selectors (External Dependency)

`ai/scraper/selectors.json` contains 50+ CSS selectors for 3 web sources. Any source-side HTML change silently breaks data ingestion. There's no selector health check or fallback parsing.

---

## 4. Failure Scenarios

### 4.1 Player Transfer Mid-Season

```
Trigger:  Icardi transfers to AC Milan (January window)
Timeline: Immediate on transfer day

What breaks:
  ✗ questions.py still generates "Icardi Galatasaray'da gol atar mı?"
  ✗ No player→team lookup exists, so even if user asks about Icardi
    at Milan, the system can't resolve him
  ✗ Test suite still uses old Icardi questions → tests pass but
    production questions are wrong

What doesn't break:
  ✓ Intent classification (football keyword "gol atar" still matches)
  ✓ Team extraction (if user names the team explicitly)
  ✓ Inference (doesn't use player features)

Impact: LOW (system still works, but demo/test quality degrades)
Reason: Player names are cosmetic — used only in question generation,
        never in the prediction pipeline itself.
```

### 4.2 Season Rollover

```
Trigger:  June 2026, new Süper Lig season starts
Timeline: 2-3 month gap (June-August)

What breaks:
  ✗ CURRENT_SEASON="2025-2026" → scrapers fetch wrong season
  ✗ data/tr_super_lig_2024_25.json is now 2 seasons old
  ✗ Elo ratings, form stats all reference expired data
  ✗ Promoted/relegated teams not in TEAM_MAP
  ✗ OPENFOOTBALL_SEASONS list in real_data.py missing new season

What doesn't break:
  ✓ Model architecture (schema unchanged if N_FEATURES holds)
  ✓ TQU classifier (intent patterns don't reference seasons)

Impact: HIGH (predictions use stale data; new teams unrecognised)
```

### 4.3 Generic Unresolvable Question

```
User: "Bu hafta sonu Galatasaray nasıl oynar?"

Current flow:
  1. Sanitised ✓
  2. Football context detected ("Galatasaray", "oynar") ✓
  3. Intent: "form_query" (confidence ~0.7) ✓
  4. Entities: team_ref="team_001", time_ref="bu hafta sonu" ✓
  5. Match resolution: ∅ (no fixture database)
  6. Features: synthetic/demo fallback (random seed=42)
  7. Inference: returns probabilities from random features
  8. Response: confident Turkish analysis based on fabricated data

The user gets a fluent, authoritative answer that is entirely
disconnected from reality because no actual match was resolved.
```

### 4.4 Team Rename / Merger / Promotion

```
Trigger:  Bodrum FK promoted to Süper Lig; Pendikspor relegated
Timeline: End of season

What breaks:
  ✗ questions.py _TEAMS list has wrong teams
  ✗ generate_match_data.py TEAMS and TEAM_STRENGTH outdated
  ✗ locale_tr.yaml may have the team but scraper can't match it
  ✗ real_data.py TEAM_NAME_MAP missing new source-side names
  ✗ Historical model trained on 19-team league, now 20 teams

Impact: MEDIUM (new team queries fail entity extraction)
```

---

## 5. Mitigation Roadmap

### Phase 1: Immediate — Single Source of Truth for Teams (1–2 days)

**Problem:** 5 independent team lists across 5 files.

**Fix:** All team-related data should derive from `locale_tr.yaml`.

| File | Current | Target |
|---|---|---|
| `tqu/questions.py` | `_TEAMS = [...]` hardcoded | `from common.constants import UUID_TO_NAME; _TEAMS = list(UUID_TO_NAME.values())` |
| `tqu/questions.py` | `_DERBIES = [...]` hardcoded | Load from `locale_tr.yaml` new `derbies:` section |
| `generate_match_data.py` | `TEAMS = [...]` hardcoded | Load from locale or accept as CLI arg |
| `scraper/real_data.py` | `TEAM_NAME_MAP = {...}` hardcoded | Extend `locale_tr.yaml` with `source_aliases:` per team |
| `league_config.py` | `DERBIES = frozenset(...)` hardcoded | Load from YAML `derbies:` section (same as above) |

**YAML extension needed in `locale_tr.yaml`:**
```yaml
teams:
  team_001:
    display_name: "Galatasaray"
    aliases: ["galatasaray", "gs", "cim bom", ...]
    source_aliases:              # NEW — scraper normalisation
      openfootball: "Galatasaray"
      footballdata_uk: "Galatasaray"
    strength:                    # NEW — replaces generate_match_data.py
      attack: 1.55
      defense: 0.80

derbies:                         # NEW — single source
  - ["team_001", "team_002"]     # GS vs FB
  - ["team_001", "team_003"]     # GS vs BJK
  - ["team_002", "team_003"]     # FB vs BJK
  - ["team_001", "team_004"]     # GS vs TS
  - ["team_002", "team_004"]     # FB vs TS
  - ["team_003", "team_004"]     # BJK vs TS
```

### Phase 2: Short-term — Dynamic Player Registry (3–5 days)

**Problem:** Player rosters hardcoded in `questions.py`; no player→team lookup in entity extraction; names go stale every transfer window.

**Fix:** Replace hardcoded player lists with a database-backed player registry.

**Design:**

```
PostgreSQL: players table
┌────────────┬──────────────┬──────────┬────────────┬────────────┐
│ player_id  │ display_name │ team_id  │ joined_at  │ left_at    │
├────────────┼──────────────┼──────────┼────────────┼────────────┤
│ p_001      │ Barış Yılmaz │ team_001 │ 2024-07-01 │ NULL       │
│ p_002      │ Icardi       │ team_001 │ 2023-09-10 │ 2025-01-15 │
│ p_003      │ Dzeko        │ team_002 │ 2023-07-01 │ NULL       │
└────────────┴──────────────┴──────────┴────────────┴────────────┘
```

**Entity extraction changes (`tqu/entities.py`):**
```python
# Current: only resolves team names
# Proposed: also resolve player names → team_id

def extract_entities(text: str) -> ExtractedEntities:
    # ... existing team extraction ...
    
    # NEW: Player lookup
    player_match = player_registry.fuzzy_match(text)
    if player_match:
        entities.player_ref = player_match.player_id
        # Infer team if not already found
        if not entities.team_refs:
            entities.team_refs.append(player_match.current_team_id)
```

**Question generation changes (`tqu/questions.py`):**
```python
# Current: _PLAYER_TEAMS = {"Galatasaray": ["Icardi", ...]}
# Proposed: load from DB at startup
_PLAYER_TEAMS = player_registry.get_current_rosters()
```

### Phase 3: Short-term — Match Context Resolution (3–5 days)

**Problem:** User says "bu maçta" or "yarınki maç" but no fixture database exists to resolve it.

**Fix:** Add a fixture resolution layer between entity extraction and feature engineering.

**Design:**

```
PostgreSQL: fixtures table
┌────────────┬──────────┬──────────┬────────────┬────────┬────────────┐
│ fixture_id │ home_id  │ away_id  │ kickoff_at │ status │ season     │
├────────────┼──────────┼──────────┼────────────┼────────┼────────────┤
│ fix_0401   │ team_001 │ team_002 │ 2026-04-12 │ sched  │ 2025-2026  │
│ fix_0402   │ team_003 │ team_004 │ 2026-04-12 │ sched  │ 2025-2026  │
└────────────┴──────────┴──────────┴────────────┴────────┴────────────┘
```

**Resolution logic (new module: `pipeline/resolver.py`):**

```python
def resolve_match(entities: ExtractedEntities) -> ResolvedMatch | None:
    """
    Given extracted entities (team refs + time ref), find the
    matching upcoming fixture.
    
    Resolution priority:
    1. Two teams + date range → exact fixture
    2. Two teams, no date → next upcoming fixture between them
    3. One team + date → team's next match on/near that date
    4. One team, no date → team's next match overall
    5. No teams → None (unresolvable)
    """
```

**Pipeline integration:**
```
classify() → extract_entities() → resolve_match() → load_features() → inference()
                                        │
                                        ├── Found → use real fixture data
                                        └── Not found → return "match not found" 
                                            response instead of fabricated answer
```

### Phase 4: Medium-term — Season Auto-Detection (1–2 days)

**Problem:** `CURRENT_SEASON` hardcoded; season rollover requires code change.

**Fix:**
```python
# Replace:
CURRENT_SEASON = "2025-2026"

# With:
def current_season() -> str:
    """Derive season string from current date.
    Turkish Süper Lig: August → May."""
    today = datetime.now()
    if today.month >= 8:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"
```

Also move `OPENFOOTBALL_SEASONS` in `scraper/real_data.py` from a hardcoded list to a dynamic query against the openfootball GitHub API (list directory contents).

### Phase 5: Medium-term — Confidence-Gated Responses (2–3 days)

**Problem:** System answers confidently even when match context was never resolved (falls through to synthetic features).

**Fix:** Add a resolution confidence score to the pipeline context:

```python
@dataclass
class PipelineContext:
    # Existing fields...
    
    # NEW: resolution quality indicators
    match_resolved: bool = False
    data_freshness_hours: float = float('inf')
    feature_source: str = "synthetic"  # "real" | "scraped" | "synthetic"
```

**Response gating in TRC composer:**
```python
if not ctx.match_resolved:
    return REJECTIONS["no_match"]  
    # "Bu maç için güncel veri bulunamadı. 
    #  Lütfen takım adlarını ve tarihi belirtin."

if ctx.data_freshness_hours > 72:
    verdict = prepend_warning(verdict)
    # "⚠ Veriler 3 günden eski olabilir. "
```

### Phase 6: Long-term — Scheduled Data Refresh (5+ days)

**Problem:** All data (fixtures, rosters, stats) is either hardcoded or scraped on-demand with no schedule.

**Fix:** Cron-based data pipeline:

```
┌─────────────────────────────────────────────────┐
│  Scheduler (cron / Celery / pg_cron)            │
│                                                 │
│  Every 6h:  Scrape fixture schedule updates     │
│  Every 12h: Scrape match results + stats        │
│  Every 24h: Update Elo ratings from results     │
│  Every week: Retrain model with fresh data      │
│  Transfer windows: Scrape roster changes        │
└─────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────┐
│  PostgreSQL (source of truth)                   │
│  • fixtures   — upcoming + completed matches    │
│  • players    — current rosters with history    │
│  • teams      — canonical names + aliases       │
│  • stats      — per-team rolling aggregates     │
│  • models     — versioned trained model blobs   │
└─────────────────────────────────────────────────┘
```

---

## 6. Architecture Proposal

### Current (Static)

```
User ──→ TQU ──→ [hardcoded patterns] ──→ [synthetic features] ──→ GBDT ──→ TRC
                         │                        │
                    Python source             random seed=42
                    (stale at deploy)         (fabricated)
```

### Proposed (Dynamic)

```
User ──→ TQU ──→ Entity Resolution ──→ Fixture Lookup ──→ Feature Hydration ──→ GBDT ──→ TRC
                       │                     │                    │
                  YAML + DB             PostgreSQL            Real stats
                  (live aliases)        (live schedule)       (scraped)
                       │                     │                    │
                       └─── All refresh on schedule, not at deploy ───┘
```

### Key Principle: Separate Code from Data

| Layer | Code (versioned, deployed) | Data (refreshed, runtime) |
|---|---|---|
| TQU | Intent regex patterns, pipeline logic | Team aliases, player names, keywords |
| Features | Column schema, engineering formulas | Elo ratings, form stats, fixture data |
| Inference | Model architecture, ensemble weights | Trained model weights (retrained weekly) |
| TRC | Template structure, verdict logic | Template text (localisable), team/player names |

---

## 7. Migration Priority

| # | Phase | Effort | Impact | Risk if Skipped |
|---|---|---|---|---|
| 1 | Single source of truth (teams) | 1–2 days | HIGH | 5 files drift apart silently |
| 2 | Match context resolution | 3–5 days | **CRITICAL** | System answers fabricated data confidently |
| 3 | Confidence-gated responses | 2–3 days | **CRITICAL** | Users can't tell real from synthetic answers |
| 4 | Dynamic player registry | 3–5 days | MEDIUM | Player questions decorative only; low real impact |
| 5 | Season auto-detection | 1–2 days | HIGH | System breaks every June |
| 6 | Scheduled data refresh | 5+ days | HIGH | Manual intervention needed for every data update |

**The single most dangerous issue is #2 + #3 combined**: the system confidently answers questions using fabricated synthetic data because it has no match resolution and no way to tell the user "I don't have real data for this match." Fixing these two together eliminates the most harmful failure mode.

---

*Report generated from codebase audit of commit state as of 2026-04-07.*
