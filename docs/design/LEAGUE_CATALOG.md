# 🌍 LEAGUE_CATALOG — league registry, tiering, & expansion gating

> **Status:** Anchor doc for *which leagues we serve, when we serve
> them, and what readiness proves they belong on the production
> roster*.
>
> **Companion docs:** [`COMPETITIONS.md`](COMPETITIONS.md) (cup +
> tournament shape, separate axis from leagues),
> [`ENRICHMENT_DATA.md`](ENRICHMENT_DATA.md) (extra data planes),
> [`MONETIZATION.md`](MONETIZATION.md) (per-league feature gating).

---

## 0. Why this doc exists

Today the system runs one league well (Süper Lig) and the original
ROADMAP Phase 13 hand-waved at "top European leagues + cups." The
user request is now explicit: **>15 leagues in v1, every league on
mackolik/nesine in v2, plus cups and international tournaments.**

Just adding more entries to `LEAGUE_CONFIGS` doesn't scale. Without
explicit readiness gating, a half-calibrated league will silently
ship miscalibrated predictions to paying users. Without a tiering
model, every preset costs the same to maintain even when only ~20%
get traffic. Without a global catalog, the operations team has no
single place to look up "is the Korean K League 1 active in
production yet?".

This doc fixes that with three pieces:

1. **A tier system (T1/T2/T3)** that gates a league between research,
   beta, and GA on objective readiness criteria.
2. **A readiness checklist** every league must pass before it
   advances a tier — same shape for every league, no per-league
   exceptions.
3. **A single registry file** (`ai/common/league_catalog.yaml`)
   that the predictor swarm, the API, the NLP layer, and the
   monetization policy all read.

---

## 1. The three tiers

| Tier | Status | API behavior | Predictor behavior | UI hint (Flutter, Phase 15) |
|---|---|---|---|---|
| **T1 — GA** | Production. Calibrated. Full feature set. | All markets exposed; rate-limited per [`MONETIZATION.md`](MONETIZATION.md). | All predictors vote; consensus published; proofreader gates publication. | No banner. |
| **T2 — Beta** | Public but flagged. Lower confidence floor. | Predictions returned with `"tier": "beta"` and a stable error code if the requesting tier is Free (per `MONETIZATION.md`). | Predictors vote; consensus published; **proofreader publishes with widened CI bounds** (`cfg.proofreader_beta_ci_widen`). | Yellow "Beta" badge. |
| **T3 — Research** | Internal only. Not exposed via public API. | API returns `404 — league not in active catalog` to non-admin tokens. | Pipeline runs end-to-end; predictions stored for backtest; **never published**. | n/a (not visible). |

> **Doctrine link.** Tier is a property of the *league's calibration
> readiness*, not of the *user's subscription*. A Free user gets T1
> leagues only; a Pro user gets T1+T2; admin scopes (Phase 9.2) get
> T3 for QA. Confusing the two axes is the most common
> misunderstanding — see [`MONETIZATION.md`](MONETIZATION.md) §3.

---

## 2. Readiness checklist (T3 → T2 → T1)

Every league moves up the tiers by passing the same checklist.
Auto-tracked in `xops/leagues/readiness.py` against the per-league
fixture/result history; failures block the promotion.

### 2.1 T3 → T2 (research → beta)

**Data readiness:**

- [ ] At least **2 full seasons** of historical results in the
      Reference + Schedule + score Live planes.
- [ ] Mock-vhost seed coverage exists for at least one source per
      relevant plane (Reference + Schedule minimum; Market optional
      for T2).
- [ ] `LeagueConfig` preset committed; aliases populated; team-name
      map covers the current season's roster.
- [ ] At least one `CompetitionFormat` is associated (typically
      `round_robin` for the league + a `domestic_cup` competition).

**Model readiness:**

- [ ] Backtest log-loss within `cfg.league_promotion_logloss_max`
      of the system-wide baseline (default: ≤ 1.10× baseline).
- [ ] Brier score within `cfg.league_promotion_brier_max` (default:
      ≤ 0.225 for 1X2).
- [ ] No predictor vote cohort has a single-vote dominance > 60%
      (= no model is dominating because the others have nothing to
      predict from).

**Operational readiness:**

- [ ] Mock-stack `make mock.verify SOURCE=<league_source>` is green.
- [ ] Reactor isolation suite passes for the league's competitions.
- [ ] At least one proofreader unit test references the league's
      preset.

### 2.2 T2 → T1 (beta → GA)

**Calibration readiness:**

- [ ] **4 weeks of live beta traffic** with realized outcomes
      tracked. Beta predictions get logged but not re-graded; T1
      promotion uses these as a fresh out-of-sample window.
- [ ] Calibration plot deviation ≤ `cfg.league_calibration_max_deviation`
      (default: max 8 points absolute deviation across reliability
      bins).
- [ ] No drift event raised by the freshness watcher
      ([`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md)) in the past
      14 days for any of the league's data planes.

**NLP readiness:**

- [ ] TR gazetteer covers the league's team names + main player
      names; entity-extraction recall ≥ `cfg.nlp_promotion_recall_min`
      (default: 0.92) on a 50-query league-specific corpus.
- [ ] Foreign-name TR transliteration entries for non-Turkish team
      names ([`TURKISH_NLP.md`](TURKISH_NLP.md)).

**Operational readiness:**

- [ ] Per-league dashboard (Phase 11/12 telemetry) shows green for
      consecutive 7 days: ingest latency, prediction emission rate,
      DLQ depth, scraper success rate.
- [ ] One "competition gate" per `MONETIZATION.md` §4 referencing
      the league exists in `entitlements.yaml`.

### 2.3 Demotion

A T1 league **must** demote to T2 (and stay there ≥ 14 days) when:

- Calibration plot deviation exceeds the gate **on a 7-day window**.
- A scraper-patcher escalation (`patcher.unable`) for any of the
  league's sources stays open > 24 h.
- The `LeagueConfig` preset for the league is changed in any
  field other than `team_name_map` (the trainer must be re-validated).

Demotion is automatic and recorded in the tracker (`docs/tracking/`)
with the triggering reason. Re-promotion requires re-passing §2.2.

---

## 3. The catalog file

`ai/common/league_catalog.yaml` (v1):

```yaml
# Single source of truth for which leagues exist + their tier.
# Read by: predictor swarm (filter), API (entitlements), NLP gazetteer
# (which team-name lists to load), monetization (per-league SKU map).
#
# Adding a new league requires PR review by ops + ML; rows here are
# what `xops/leagues/readiness.py` checks against.

schema_version: 1

# T1 — GA (production)
- league_id: tr_super_lig
  name_en: "Turkish Süper Lig"
  name_tr: "Türkiye Süper Lig"
  country: TR
  confederation: UEFA
  tier: T1
  active_since: "2024-08-15"
  competitions:
    - competition_id: tr_super_lig_round_robin
    - competition_id: tr_super_lig_relegation_playoff
  source_coverage:
    reference: [openfootball, tff]
    schedule:  [mackolik, tff, nesine]
    live:      [mackolik]
    editorial: [mackolik]
    market:    [nesine]

# T1 — initial expansion (top-5)
- league_id: en_premier_league
  name_en: "English Premier League"
  name_tr: "İngiltere Premier Lig"
  country: GB-ENG
  confederation: UEFA
  tier: T1
  competitions:
    - competition_id: en_premier_league_round_robin
    - competition_id: en_fa_cup
    - competition_id: en_efl_cup
    - competition_id: en_community_shield
  source_coverage:
    reference: [openfootball]
    schedule:  [mackolik, nesine]
    market:    [nesine]

# (… es_la_liga, de_bundesliga, it_serie_a, fr_ligue_1 — same shape …)

# T1 — international/club cups
- league_id: uefa_champions_league
  name_en: "UEFA Champions League"
  name_tr: "UEFA Şampiyonlar Ligi"
  country: null
  confederation: UEFA
  tier: T2                      # promoted to T1 after Phase 13a beta window
  competitions:
    - competition_id: uefa_champions_league_qualifying
    - competition_id: uefa_champions_league_league_phase
    - competition_id: uefa_champions_league_knockout
  source_coverage:
    reference: [openfootball]   # historical
    schedule:  [mackolik, nesine]
    market:    [nesine]

# (… uefa_europa_league, uefa_conference_league, uefa_super_cup …)

# T2 — Phase 13b expansion (10 leagues)
- league_id: pt_primeira_liga
  tier: T2
  …
- league_id: nl_eredivisie
  tier: T2
  …
- league_id: br_serie_a
  tier: T2
  …
# (… ar_primera_division, mx_liga_mx, us_mls, jp_j_league,
#    kr_k_league_1, sa_pro_league, au_a_league_men …)

# T3 — Phase 19 long-tail (catalog only; NOT served)
- league_id: vn_v_league_1
  tier: T3
  …
# (… every league listed on mackolik/nesine bulletin pages …)
```

The catalog file is **gitignored only for `tier:` overrides during
hot-promotion testing**; the canonical version is committed and
CI-validated.

---

## 4. Initial roster (v1 — Phases 13a & 13b)

### 4.1 Phase 13a — top-5 EU + TR + UEFA + WC/Euro (T1/T2)

**Domestic leagues (T1):**
- 🇹🇷 Süper Lig (already T1)
- 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League
- 🇪🇸 La Liga
- 🇩🇪 Bundesliga
- 🇮🇹 Serie A
- 🇫🇷 Ligue 1

**Domestic cups (T2 → T1 after beta window):**
- Türkiye Kupası (TR)
- TFF Süper Kupa (TR)
- FA Cup (EN), EFL Cup (EN), Community Shield (EN)
- Copa del Rey (ES), Supercopa de España (ES)
- DFB-Pokal (DE), DFL-Supercup (DE)
- Coppa Italia (IT), Supercoppa Italiana (IT)
- Coupe de France (FR), Trophée des Champions (FR)

**Continental club (T2):**
- UEFA Champions League (qualifying + league phase + knockout)
- UEFA Europa League (qualifying + league phase + knockout)
- UEFA Conference League (qualifying + league phase + knockout)
- UEFA Super Cup (one-off)

**International (T2):**
- FIFA World Cup (group + knockout)
- UEFA EURO Championship (group + knockout)
- WC qualifiers (UEFA confederation; CONMEBOL et al. land in 13b/19)
- EURO qualifiers
- UEFA Nations League

### 4.2 Phase 13b — +10 most popular leagues (T2 with their domestic cups)

Selected by *(a)* mackolik/nesine bulletin coverage, *(b)* available
historical depth, *(c)* expected user demand. All start at T2 and
promote to T1 once §2.2 passes.

| # | League | Country | Why |
|---|---|---|---|
| 7 | Primeira Liga | 🇵🇹 PT | UCL pipeline, historical Süper Lig–PT linkages |
| 8 | Eredivisie | 🇳🇱 NL | UCL/UEL regulars, deep history |
| 9 | Pro League | 🇧🇪 BE | UCL/UEL regulars, mackolik bulletin coverage |
| 10 | Süper Lig 1 (Lig) | 🇹🇷 TR | TR 2nd tier — key for Türkiye Kupası identity resolution |
| 11 | Brasileirão Série A | 🇧🇷 BR | Largest non-EU league by user demand |
| 12 | Liga Profesional Argentina | 🇦🇷 AR | Conmebol pipeline |
| 13 | Liga MX | 🇲🇽 MX | CONCACAF pipeline |
| 14 | MLS | 🇺🇸 US | CONCACAF pipeline |
| 15 | J1 League | 🇯🇵 JP | AFC pipeline, mackolik coverage |
| 16 | K League 1 | 🇰🇷 KR | AFC pipeline, mackolik coverage |

Each gets its **headline domestic cup** alongside (e.g. Copa do Brasil,
Copa Libertadores at the continental level alongside Brasileirão).
Continental tournaments outside UEFA (Copa Libertadores, AFC
Champions League) land in **Phase 13c** to keep the cross-confederation
identity work scoped.

### 4.3 Phase 13c — non-UEFA continental + completeness pass

- 🌎 Copa Libertadores (CONMEBOL)
- 🌎 Copa Sudamericana (CONMEBOL)
- 🌎 Recopa Sudamericana
- 🌏 AFC Champions League Elite + Two
- 🌍 CAF Champions League
- ⚽ FIFA Club World Cup
- ⚽ FIFA Intercontinental Cup
- Copa América, AFCON, Asian Cup, Gold Cup
- WC qualifiers (all confederations)

---

## 5. Phase 19 — global long-tail (deferred, structurally ready)

Per user request #6: *"add all the football leagues like Korean or
Brazilian that're listed on mackolik.com and nesine.com alongside
world cups (eliminations and championships) … not implementing it
yet but revise and set the system ready for such change."*

The architecture must be *catalog-pluggable* now even if rows are
not added until later. Concretely:

- **Catalog-driven everything.** Every code site that branches on
  league reads `league_catalog.yaml` only — no `if league_id == "..."`
  ever. A unit test enforces this with an AST scan of `ai/` and
  `server/`.
- **Tier T3 has zero maintenance cost when empty.** No predictor
  retraining, no NLP gazetteer hit, no monetization SKU. Adding a
  T3 row is a single YAML edit; promoting it follows §2.
- **Source registry pluggable.** `xops/mock/sources.py` already has
  this shape; new sources for long-tail leagues
  (e.g. "kleague.com" for KR) can be added without touching the
  pipeline.
- **Identity strategy stays generic.** `stable_id` minting
  (CONTENT_FRESHNESS §2) does not bake in any country list. Korean
  team-name forms get the same fuzzy + anchor-set pipeline as
  English ones.

When Phase 19 fires, the work is: capture seeds → add a T3 row →
backtest → promote per §2. **No platform changes.** This is the
Pivot v3 promise: the architecture is the product, the leagues are
data.

---

## 6. Per-league `LeagueConfig` discipline

Existing `ai/common/league_config.py` already holds per-league
parameters. The expansion adds three rules to keep the file
maintainable as it grows past 30+ presets:

1. **One Python file per league** under
   `ai/common/leagues/<league_id>.py`, each exposing a single
   `CONFIG: LeagueConfig` constant. The aggregator
   `ai/common/leagues/__init__.py` builds `LEAGUE_CONFIGS = {…}`.
   Catches accidental cross-contamination (a typo in one preset
   only breaks one league).
2. **No new fields without a default.** Backwards compatibility
   gate: a new `LeagueConfig` field that is added must have a
   default value, and a triangle test ensures every existing preset
   still loads cleanly.
3. **Per-league overrides only.** Anything calculated from data
   (Elo per team, calibration tables) lives in Postgres, not in
   the preset. Presets carry **structural** facts (teams_count,
   format, derbies, name maps) only.

---

## 7. Monetization linkage (cross-reference)

Per [`MONETIZATION.md`](MONETIZATION.md), the entitlement engine
maps `(tier_of_subscriber, league_id, market_id) → allow|deny`.
Adding a league adds rows to `entitlements.yaml`:

```yaml
- league_id: jp_j_league
  free_tier_visible: true        # discovery: yes
  free_tier_predictions: false   # gated to Pro+
  pro_tier_predictions: true
  premium_tier_player_props: true
```

**The catalog and the entitlements file are linked by league_id only.**
A row missing in either breaks CI.

---

## 8. Testing matrix

`make test.leagues` (new target — Phase 13a) runs:

| Test | Per-league? | Gate |
|---|---|---|
| Preset loads | Yes | Mandatory all |
| Aliases resolve to canonical | Yes | Mandatory all |
| Catalog row exists for preset | Yes | Mandatory all |
| Backtest log-loss within tolerance | T1+T2 only | T2→T1 promotion |
| Calibration plot ≤ deviation gate | T1 only | T1 retention |
| Mock-stack seeds present | T1+T2 | Mandatory non-T3 |
| Entitlement row exists | T1+T2 | Mandatory non-T3 |
| NLP gazetteer covers team names | T1 only | T2→T1 promotion |
| Reactor idempotency for league competitions | T1+T2 | Mandatory non-T3 |

---

## 9. Definition-of-Done for "league expansion"

Per league added (regardless of which Phase 13 sub-track):

- [ ] Catalog row in `league_catalog.yaml` with starting tier T2 (or
      T3 if Phase 19).
- [ ] `LeagueConfig` preset committed at `ai/common/leagues/<league_id>.py`.
- [ ] Mock-stack seeds captured for at least Reference + Schedule
      planes (T2+).
- [ ] All §2 readiness gates for the starting tier pass.
- [ ] Entitlement row added (T1+T2; per [`MONETIZATION.md`](MONETIZATION.md)).
- [ ] Tracker row recording the league addition + starting tier.
- [ ] Component bump: a new `league_<league_id>` chart key seeded at
      `0.1.0` (so per-league regressions can be tracked separately
      from the preset aggregator).

---

## 10. Reading order for new contributors

1. This doc up to §3 — the tier system + the catalog file shape.
2. `COMPETITIONS.md` — leagues are one axis; competitions are
   another. Many leagues have multiple competitions.
3. `MONETIZATION.md` §3-§4 — how league tier + subscriber tier
   combine into a serve/deny decision.
4. `DATA_PIPELINE.md` §1-§4 — where each plane's data lives.
5. ROADMAP Phase 13 (a/b/c) and Phase 19 — the rollout plan.
