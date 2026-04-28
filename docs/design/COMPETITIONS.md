# 🏆 COMPETITIONS — competition taxonomy & format-aware modelling

> **Status:** Anchor doc for any competition that is **not** a plain
> league round-robin. Owns the format taxonomy, calibration overlays,
> knockout / two-leg / group-stage semantics, and the rules every
> predictor / proofreader / NLP layer must respect when a fixture
> belongs to a cup or international tournament.
>
> **Companion docs:** [`LEAGUE_CATALOG.md`](LEAGUE_CATALOG.md) (which
> competitions exist + readiness gating), [`DATA_PIPELINE.md`](DATA_PIPELINE.md)
> (Record contract — `competition` is a Reference-plane entity),
> [`ENRICHMENT_DATA.md`](ENRICHMENT_DATA.md) (per-format enrichment
> requirements e.g. neutral venue, leg aggregation).

---

## 0. Why this doc exists

Until now the system has implicitly assumed *"a fixture belongs to a
league which is a season-long round-robin."* That assumption is wrong
for **every cup, every UEFA tournament, every World Cup, every Super
Cup, every federation cup, every qualifier**. The wrongness shows up
as:

- Calibration: knockout matches have **higher upset variance** than
  league matches between the same teams; using league-trained
  Dixon-Coles ρ on a Champions League knockout yields
  systematically over-confident draws.
- Aggregation: a two-leg tie has **two `fixture` rows that share an
  outcome**. The "advanced to next round" outcome is a function of
  both fixtures, not either one alone. A pipeline that treats them
  independently double-counts and mis-prices "winner of tie" markets.
- Venue: cup finals, super cups, EURO/WC matches are at **neutral
  venues** — the home-advantage Elo bonus must be zeroed.
- Sample size: most cups have **a handful of matches per club per
  season**. A model that ignores per-competition tiering will drown
  cup-specific signal in league noise.
- NLP: a Turkish question like *"Galatasaray Türkiye Kupası'nda kime
  karşı oynayacak?"* requires the system to know "Türkiye Kupası" is
  a competition, not a free-form keyword.

This doc fixes all of that with **one new first-class entity
(`Competition`)** and a **format-aware modelling overlay** that the
predictor swarm consults whenever `fixture.competition_format !=
"round_robin"`.

---

## 1. The competition taxonomy

Competitions split along three orthogonal axes. Every concrete
competition (Süper Lig, Türkiye Kupası, UEFA Champions League, FIFA
World Cup, Euro qualifiers, …) is one point in this 3D space.

### 1.1 Axis A — format

| Format | Semantics | Examples | Calibration impact |
|---|---|---|---|
| `round_robin` | Each team plays every other N times in a single season-long table. | All top-5 league seasons, MLS regular season | Baseline (existing model) |
| `single_knockout` | Single-leg elimination, sometimes with extra-time + penalties. | Türkiye Kupası early rounds, UEFA Super Cup, EURO/WC knockout | Higher upset variance; ρ shrinks; "to_win_in_90" is a sub-market of "to_win_tie" |
| `two_leg_knockout` | Home-and-away, aggregate score (away-goals rule per era). | UCL/UEL/UECL knockout, several federation cups' later rounds | Tie-aware aggregation; second-leg draw probability spikes |
| `group_round_robin` | Mini round-robin within a group, top-N advance. | UCL/UEL/UECL group stage, EURO/WC group stage | Standings-aware features (need at least 1 point, etc.) |
| `group_then_knockout` | Composite format: groups → KO. | EURO, WC, UCL post-2024 league phase | Hybrid: group matches use group rules, KO uses KO rules |
| `multi_stage_qualifier` | Sequential rounds with seeded paths; many entrants, few advance. | UCL qualifying, EURO/WC qualifiers | Path-dependent prediction; prior-round result modulates next-round prior |
| `final_only` | Single match, often pre-announced venue, between fixed entrants. | UEFA Super Cup, FIFA Intercontinental | One-shot; no in-tournament form signal |
| `playoff_bracket` | Top-N from regular season play a single-/multi-leg KO. | MLS Cup, A-League finals | Regular-season form weight ↑; KO upset variance |

### 1.2 Axis B — scope

| Scope | Examples | Identity-resolution impact |
|---|---|---|
| `domestic_league` | Süper Lig, Premier League | One country; team identity stable across seasons |
| `domestic_cup` | Türkiye Kupası, FA Cup, Copa del Rey | Same country; lower-division entrants need cross-tier identity resolution |
| `domestic_super_cup` | TFF Süper Kupa, Community Shield, Supercopa de España | Single match between previous season's league + cup winners |
| `continental_club` | UCL, UEL, UECL, Copa Libertadores | Multi-country; team-name canonicalization across languages is critical |
| `continental_super_cup` | UEFA Super Cup, Recopa Sudamericana | Single match: continental club champion vs continental cup champion |
| `intercontinental_club` | FIFA Intercontinental Cup, Club World Cup | Cross-confederation; very few prior matches between participants |
| `international_friendly` | Pre-tournament friendlies | Excluded from training; flagged for sentiment/news only |
| `international_qualifier` | EURO/WC qualifiers, Nations League groups | National-team scope; player-club separation matters for injury data |
| `international_championship` | EURO finals, WC finals, Copa América, AFCON | National-team scope; tournament-bubble effects (squad fatigue, rotation) |

### 1.3 Axis C — venue policy

| Venue policy | Semantics | Home-advantage handling |
|---|---|---|
| `home_away` | One team plays at their own ground. | Standard `LeagueConfig.elo_home_advantage` applies. |
| `neutral` | Pre-announced neutral venue (most finals, EURO/WC). | Home advantage zeroed; nominal "home" team is administrative only. |
| `host_country` | Tournament played in N pre-announced cities; one team may be a *de facto* host. | Soft home advantage applied **only** to the host nation; bench for others. |
| `bubble` | Tournament played in a single venue/region (Lisbon UCL 2020, COVID-era). | Home advantage zeroed; **adds** a "no travel" calibration factor. |

> Every concrete competition exposes `(format, scope, venue_policy)`
> as a triple. The pipeline reads only this triple; it never branches
> on competition name.

---

## 2. The `Competition` Reference-plane entity

`Competition` is added to the `record_type` enum in
[`DATA_PIPELINE.md`](DATA_PIPELINE.md) §4. It already appeared in the
plane-1 list under "competitions" — this section makes its payload
schema concrete.

### 2.1 Payload schema (v1)

```python
class CompetitionPayload(TypedDict):
    competition_id: str            # canonical, e.g. "uefa_champions_league"
    name_en: str                   # "UEFA Champions League"
    name_tr: str                   # "UEFA Şampiyonlar Ligi"
    aliases: list[str]             # ["UCL", "Şampiyonlar Ligi", "Champion's League"]

    # Axis A — format
    format: Literal[
        "round_robin", "single_knockout", "two_leg_knockout",
        "group_round_robin", "group_then_knockout",
        "multi_stage_qualifier", "final_only", "playoff_bracket",
    ]

    # Axis B — scope
    scope: Literal[
        "domestic_league", "domestic_cup", "domestic_super_cup",
        "continental_club", "continental_super_cup",
        "intercontinental_club",
        "international_friendly",
        "international_qualifier", "international_championship",
    ]

    # Axis C — venue policy (default per scope; can be overridden per stage)
    default_venue_policy: Literal["home_away", "neutral", "host_country", "bubble"]

    # Tournament shape
    organizer: str                  # "TFF", "UEFA", "FIFA", "RFEF", ...
    confederation: str | None       # "UEFA", "CONMEBOL", "AFC", "CONCACAF", "CAF", "OFC", "FIFA"
    countries: list[str]            # ISO-3166 alpha-2; ["TR"] for domestic, ["TR","DE",...] for continental
    nationality_restricted: bool    # True for international_*; False for club competitions

    # Calibration overlays — one of these MUST resolve to a CalibrationProfile entry
    calibration_profile_id: str     # e.g. "knockout_continental_club"

    # Stage map (for composite formats)
    stages: list[CompetitionStage] | None

    # Lifecycle (Reference-plane standard)
    first_season: int | None        # year of first edition
    active: bool
    successor_competition_id: str | None  # e.g. UEFA Cup → UEFA Europa League
```

### 2.2 `CompetitionStage` (composite formats)

```python
class CompetitionStage(TypedDict):
    stage_id: str                   # "group_stage", "round_of_16", "quarterfinal", ...
    order: int                      # 0-indexed; stages run in order
    format: Literal[                # may differ from competition.format (composite)
        "round_robin", "single_knockout", "two_leg_knockout",
        "group_round_robin",
    ]
    legs: int                       # 1 for single, 2 for two-leg
    venue_policy: Literal["home_away", "neutral", "host_country", "bubble"]
    away_goals_rule_active: bool    # historical era-aware
    extra_time: bool
    penalties: bool
    seeding: Literal["draw", "bracket", "none"]
```

### 2.3 Why payload, not table

Per `DATA_PIPELINE.md` §4 hard rule 2: features are derived only from
`Record.payload`. Putting competition metadata anywhere else (e.g. a
hand-curated YAML the predictor reads at startup) would (a) bypass
the freshness pipeline when, e.g., UCL changes its format in 2024,
and (b) create a second source of truth. **The competition catalog
is just records, and updates flow through the same scrape → process
→ store loop as anything else.**

---

## 3. Fixture extension

`Record.payload` for `record_type="fixture"` gains four
competition-aware fields (additive; existing extractors keep working):

```python
class FixturePayloadV2(FixturePayloadV1):
    competition_id: str             # FK into Competition catalog
    competition_format: str         # denormalized for fast filtering
    stage_id: str | None            # which stage of a composite competition
    leg_index: int                  # 1 for single-leg, 1 or 2 for two-leg
    leg_of_id: str | None           # stable_id of the other fixture in the tie
    venue_policy: str               # "home_away" | "neutral" | "host_country" | "bubble"
    is_neutral_venue: bool          # convenience mirror of venue_policy != "home_away"
```

`leg_of_id` is the one new join. It pairs the two legs of a tie so
the proofreader can compute "winner of tie" markets idempotently
from either leg's payload.

---

## 4. CalibrationProfile — the format-aware overlay

The model **does not** branch on competition. It branches on
`CalibrationProfile`. A profile is a tiny YAML object that overlays
specific knobs on top of the base `LeagueConfig` for that match.

```yaml
# ai/common/calibration_profiles/knockout_continental_club.yaml
profile_id: knockout_continental_club
description: |
  UEFA Champions/Europa/Conference League knockout legs.
  Higher upset variance than league play; draw weight reduced for
  legs without a home/away advantage; cup-final neutral-venue zero.

# Multiplicative overlays applied to LeagueConfig at predict time.
elo_home_advantage_mult: 0.50    # halved for cup neutral effects
dixon_coles_rho_add: +0.05       # less low-scoring inflation in KO
draw_sample_weight_mult: 0.7     # KO draws are an artifact of regulation; weight ↓
poisson_max_goals_add: +1        # heavier tail for cup miracles
xg_elo_factor_range_mult: 1.10   # variance scale up
upset_prior: 0.03                # additive prior on the underdog 1X2 column

# When the venue policy is neutral/bubble, force home_advantage to zero
# regardless of the multiplier above.
zero_home_advantage_when_venue_in: ["neutral", "bubble"]

# Two-leg tie aggregation rules (only consulted when format=two_leg_knockout).
two_leg:
  away_goals_rule_active_until: 2021-05-31  # Pre-2021/22 UCL season
  aggregate_logic: "sum_goals"              # sum across legs
  penalty_shootout_modeled: true            # we predict shootout outcomes, not skip them
```

### 4.1 Resolution rule (deterministic)

For every fixture, the predictor resolves the calibration profile
in this order (first match wins):

1. `Competition.calibration_profile_id` (always set).
2. **Stage override:** if `Competition.stages[*].stage_id == fixture.stage_id`
   carries its own `calibration_profile_id`, that wins.
3. **Venue override:** if `fixture.venue_policy in {"neutral", "bubble"}`,
   the `zero_home_advantage_when_venue_in` clause activates regardless
   of which profile was selected.

This is intentionally hard-wired, deterministic, and unit-tested.
**No LLM picks a calibration profile.** Per AGENTS.md doctrine #4
("smallest model that works") — this is data, not inference.

### 4.2 Initial profile catalog

| Profile ID | Used for |
|---|---|
| `league_round_robin` | All `round_robin` league competitions (default — existing behavior). |
| `domestic_cup_early_round` | Cup early rounds with cross-tier mismatches (Türkiye Kupası R1-R3, FA Cup R1-R3). |
| `domestic_cup_late_round` | Cup quarters / semis / final. |
| `super_cup_one_off` | Single-match super cups (TFF, UEFA, Community Shield). |
| `knockout_continental_club` | UCL/UEL/UECL knockout legs. |
| `group_continental_club` | UCL/UEL/UECL group stage matches. |
| `qualifier_continental_club` | UCL/UEL/UECL qualifying rounds. |
| `international_group_stage` | EURO/WC/Copa América/AFCON group matches. |
| `international_knockout` | EURO/WC/Copa América/AFCON KO rounds. |
| `international_qualifier_competitive` | EURO/WC/Nations League qualifiers. |
| `international_friendly_excluded` | Friendlies — **predictor refuses to publish public predictions**; data captured for sentiment only. |

Adding a new profile is a YAML drop-in; no code change. The
`CalibrationProfileLoader` validates against a JSON Schema at boot
and refuses to start on an unknown profile_id.

---

## 5. Format-aware predictor behavior

The predictor swarm (Phase 5) reads `fixture.competition_format` and
applies the following rules. Each rule is a small, testable
deterministic transformation — **not a separate model**.

### 5.1 `round_robin`

Baseline. No change from current Phase 5 design.

### 5.2 `single_knockout`

- Apply calibration profile (typically `domestic_cup_*` or
  `international_knockout`).
- Add `extra_time_outcome` market: predict 1X2 within 90, then
  conditional on draw, predict ET winner / penalties.
- Refuse to emit "double chance — draw" market (semantically
  meaningless: a draw goes to ET, not the books).

### 5.3 `two_leg_knockout`

- Each fixture is predicted **independently** for its 90-minute 1X2.
- A separate **tie-level prediction** is computed by the proofreader
  (Phase 6) once both legs have predictions:

  ```
  P(tie_to_team_A) = Σ_{(a1,b1,a2,b2)} P(a1,b1 | leg1) · P(a2,b2 | leg2) · I[A_advances]
  ```

- The away-goals rule per `Competition.stages[*].away_goals_rule_active`
  is honored. Era-correctness matters: UCL pre-2021/22 vs post-2021/22
  use different aggregation logic.
- **Idempotency requirement (Pivot v3 reactor §15.2):** the tie
  prediction reactor is keyed on `tie_id = sorted(stable_id1, stable_id2)`
  so re-emitting after a leg correction does not double-publish.

### 5.4 `group_round_robin` and `group_then_knockout` (group portion)

- Each match: standard 1X2 prediction.
- Add **standings-aware features** (Phase 5 hardening):
  - `points_to_advance` — points the team needs from remaining
    fixtures to clinch top-N.
  - `must_win` flag — set if mathematically required.
  - `dead_rubber` flag — set if both teams' positions are decided.
- Profile `group_continental_club` / `international_group_stage`
  reduces draw-incentive penalty when both teams are
  comfortably-placed (the famous "draw deal" pattern in WC group
  finales). This is an empirical calibration, not a moral judgment.

### 5.5 `final_only`, `domestic_super_cup`, `continental_super_cup`

- Apply the `super_cup_one_off` profile.
- One-shot, neutral venue, ~12 months between editions: **no
  in-tournament form features**. Form features come from each team's
  **last-N-league-matches** window using the team's domestic season.
- Sentiment features get higher weight (Phase 10 NLP) — narrative
  matters more in one-offs.

### 5.6 `multi_stage_qualifier`

- Match-level prediction is straightforward.
- **Path-dependent prior:** the predictor takes the team's prior-round
  outcome as a feature (won-easily / won-narrow / lost). Implemented
  via a one-hot in the feature vector; **no architectural change**.
- Refuse to publish "to qualify for tournament" market until the
  team has played at least one round (cold-start protection).

### 5.7 `international_friendly`

- **Predictor refuses to publish.** The pipeline still ingests the
  fixture and any related editorial / market records (so sentiment
  and odds-context features stay current), but the predictor swarm
  does not vote and the API returns `409 Conflict — competition
  excluded from prediction publication` with a stable error code.
- This is enforced by a single check in
  `swarm/predictor/_publish_gate.py`; one rule, one place.

---

## 6. Identity & joins (cross-competition)

Cross-competition team identity is the hardest part of going
multi-tournament. The same club appears as:

| Identifier | Mackolik | TFF | UEFA | OpenFootball |
|---|---|---|---|---|
| `team_galatasaray_super_lig` | "Galatasaray" | "Galatasaray A.Ş." | "Galatasaray" | "Galatasaray SK" |
| `team_galatasaray_ucl` | "Galatasaray" | n/a | "Galatasaray İstanbul" | "Galatasaray" |

`stable_id` (CONTENT_FRESHNESS §2) **must collapse these**. Strategy:

1. Each `Team` record carries `aliases: list[str]` and one or more
   `external_ids: dict[source, id]`.
2. The identity resolver maintains an **anchor set per club**: the
   union of all string forms ever observed across all sources +
   all competitions. New observations join the anchor set after
   fuzzy-match + manual review for ambiguous cases.
3. `Player` records carry `eligibility: list[national_team_id]`
   so the international plane can join the same human across club
   and country.

> The fuzzy-match step is allowed to use a small embedding model
> (≤ 50 MB), but the **decision** to merge anchors is gated by a
> deterministic threshold in `cfg.identity_merge_threshold`. AGENTS.md
> rule #4 — smallest model that works.

---

## 7. NLP impact (TR/Turkish-first)

Per [`TURKISH_NLP.md`](TURKISH_NLP.md) the entity extractor reads a
gazetteer. Adding competitions adds:

- **Competition gazetteer** — `aliases` field of every `Competition`
  record auto-feeds the gazetteer. No hand-edit required.
- **Stage vocabulary** — Turkish forms: "yarı final" (semifinal),
  "çeyrek final" (quarterfinal), "son 16" (round of 16), "grup
  aşaması" (group stage). Maintained in `nlp/lexicon/stages.tr.yaml`.
- **Q&A intent expansion** — the intent classifier needs a
  `competition_lookup` intent ("Şampiyonlar Ligi'nde Türk takımları
  hangi gruptaymış?") in addition to existing `match_lookup`,
  `prediction_lookup`, `team_form`, etc.

Test corpus extension is tracked in `ROADMAP §10.4` as an addendum.

---

## 8. Data sources by competition

Different competitions are best served by different sources. The
mock-stack mirroring stays 1:1 with each upstream.

| Source | Best for | Worst for |
|---|---|---|
| Mackolik | Domestic TR competitions; TR-language coverage of UEFA tournaments; live | Long-tail leagues (incomplete) |
| Nesine | Bulletin (any competition listed); odds | Reference data (sparse) |
| TFF | TR domestic fixtures, referees, official names | Anything outside TR |
| OpenFootball | Historical reference for top-5 leagues, EURO, WC | Live, odds |
| **Future** UEFA.com | UCL/UEL/UECL official fixtures + stats | Domestic |
| **Future** FIFA.com | WC/qualifier official fixtures + squads | Anything else |
| **Future** ESPN/Soccerway/FBref | Long-tail leagues, deep stats | Latency, ToS |

> **Doctrine reminder.** Adding a new source is a `xops/mock/sources.py`
> entry, a seed capture, and a new extractor — **never** a special
> case in the predictor. See `DATA_SOURCE.md`.

---

## 9. Definition-of-Done for "competition support"

Per phase that touches competitions (see ROADMAP Phase 13a/b/c +
Phase 19 + Phase 20):

- [ ] Every active competition appears as a `Competition` record in
      Postgres with non-null `calibration_profile_id`.
- [ ] Every fixture from a covered competition has
      `competition_id`, `competition_format`, `venue_policy` populated.
      Schema-validation gate refuses fixtures missing any of these.
- [ ] Each `competition.format` value has at least one fixture in the
      backtest corpus and at least one passing predictor unit test.
- [ ] `make backtest COMPETITION=<id>` produces a calibration report
      whose log-loss is within `cfg.competition_calibration_tolerance`
      of the league baseline.
- [ ] Two-leg knockout coverage: tie-aggregation reactor passes the
      idempotency suite (replay 2 legs in any order → identical
      `prediction_final` for the tie).
- [ ] `make swarm-demo COMPETITION=<id>` prints a sample prediction
      with the calibration profile name in the rationale.
- [ ] NLP gazetteer carries the competition aliases; sample TR
      query "<competition_alias> nezaman?" resolves the intent
      correctly.
- [ ] Monetization tier check: per-tier feature flags (see
      [`MONETIZATION.md`](MONETIZATION.md) §4) include the
      competition's `tier` and the API gates appropriately.

---

## 10. What this doc does **not** cover

- **Per-league readiness gating** — see `LEAGUE_CATALOG.md`.
- **Player transfer / injury / referee / weather enrichment** — see
  `ENRICHMENT_DATA.md`.
- **Tier / feature-flag policy that decides which competitions a
  given subscriber sees** — see `MONETIZATION.md`.
- **Mock-stack capture mechanics for new sources** — see
  `MOCK_DATA_SERVER.md` and `DATA_SOURCE.md`.

---

## 11. Reading order for new contributors

1. This doc up to §5 — taxonomy and how the model becomes
   format-aware.
2. `LEAGUE_CATALOG.md` — how a competition gets onto the active list
   and what readiness it must demonstrate.
3. `DATA_PIPELINE.md` §4 (Record contract) — ground truth for the
   `Competition` payload schema.
4. `CONTENT_FRESHNESS.md` §2 (identity) — how the cross-competition
   `stable_id` is minted.
5. ROADMAP Phase 13 (a/b/c) and Phase 19 — how this lands in the
   plan.
