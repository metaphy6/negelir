# 📡 ENRICHMENT_DATA — supplemental data planes for richer prediction

> **Status:** Anchor doc for the **enrichment overlay** added on top
> of the original five data planes from
> [`DATA_PIPELINE.md`](DATA_PIPELINE.md). These are the
> heterogeneous, lower-velocity, indirect-influence sources whose
> signal compounds into better predictions: transfers, injuries,
> news, referees, weather, market movement, fixture congestion,
> stadium/pitch.
>
> **Companion docs:** [`DATA_PIPELINE.md`](DATA_PIPELINE.md) (the
> original five planes — Reference, Schedule, Live, Editorial,
> Market), [`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md) (per-plane
> change rules), [`COMPETITIONS.md`](COMPETITIONS.md) (which
> competitions need which enrichment), [`MONETIZATION.md`](MONETIZATION.md)
> (which enrichment-derived markets are tier-gated).

---

## 0. Why this doc exists

The first five planes (Reference, Schedule, Live, Editorial, Market)
cover *what happened on the pitch and what the market thinks of
it*. They miss the **off-pitch signal** that experienced punters and
domain experts read instinctively:

- A team's star striker just transferred out → **transfers plane**.
- The starting goalkeeper went into a boot for 6 weeks → **injuries
  plane**.
- A particular referee gives 25% more yellow cards than league
  average → **referees plane**.
- The match is at altitude / in pouring rain / on artificial turf →
  **weather + stadium planes**.
- The closing odds drift contradicts the opening odds by 30% →
  **market-movement enrichment** (a derived view of the existing
  Market plane).
- A team plays its 4th match in 11 days → **fixture congestion
  enrichment** (a derived view of the existing Schedule plane).

Each of these has a **different shape** — different cadence,
different sources, different staleness rules, different feature
extraction. Treating them as one giant "extra data" pile would
guarantee they leak into each other; modelling them as separate
overlays keeps the system disciplined.

The user's request explicitly named transfers, injuries, news,
cards. We extend that with **referee, weather, market-movement,
fixture-congestion, stadium/pitch** because these are well-known
indirect signals with established empirical effects, fit the same
overlay pattern with negligible extra design cost, and are required
for some of the higher-value markets (cards, corners, totals) that
[`MONETIZATION.md`](MONETIZATION.md) names as Premium-tier.

---

## 1. The enrichment overlay model

The original five planes are **first-class** — every record carries a
`plane` tag, gets a `stable_id`, lives in Postgres, and is
freshness-gated. Enrichment overlays come in two flavors:

### 1.1 New first-class planes

These are independent record streams that don't fit cleanly into
any of the original five. Each gets its own `record_type`, payload
schema, freshness rules, and Postgres table.

| # | Plane | Examples | Cadence | New `record_type`s |
|---|---|---|---|---|
| 6 | **Roster-state** | Transfers, contract changes, suspensions | Daily–weekly | `transfer`, `contract`, `suspension` |
| 7 | **Health** | Injuries, fitness reports, return-to-play estimates | Daily; spikes around team-news cycles | `injury`, `availability` |
| 8 | **Officials** | Referee assignments, referee history, VAR officials | Per-match (assigned 1-3 days pre-KO) + slow per-referee history | `referee_assignment`, `referee_profile` |
| 9 | **Environment** | Weather forecast + actuals, pitch condition, altitude | Hourly forecast → actual at KO + post-match | `weather_forecast`, `weather_actual`, `pitch_condition` |

> **Discipline reminder.** Per `DATA_PIPELINE.md` §1, the existing
> five planes (Reference / Schedule / Live / Editorial / Market) are
> not modified. The four new planes above are added with the same
> discipline: own `plane` tag, own `record_type` enum entries, own
> differs in `CONTENT_FRESHNESS.md` §7.

### 1.2 Derived enrichment views

These are not new records — they are **deterministic functions** over
existing planes, materialized as feature columns. They never enter
Postgres as their own table; they are computed in the feature store
and recomputed when the upstream record changes.

| Derived view | Source planes | Computation | Cache |
|---|---|---|---|
| **Market-movement** | Market (5) | First-tick odds vs closing-tick odds; drift % per market. **6 output fields**: `drift_1x2_home_pct`, `drift_1x2_draw_pct`, `drift_1x2_away_pct`, `drift_total_pct`, `implied_prob_shift_max`, `high_drift_flag` | Per fixture |
| **Fixture-congestion** | Schedule (2) + Live (3) | Days-since-last-match, matches-in-last-N-days, travel km between consecutive venues | Per team-day |
| **Card-context overlay** | Officials (8) + history aggregates from Live (3) | Referee mean cards/match × team mean cards/match, smoothed | Per fixture |
| **Public-narrative pressure** | Editorial (4) | Article volume × sentiment polarity in the 72h pre-KO | Per fixture |

Derived views are **idempotent reactors** (per
[`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md) §15). They re-run
when a source record's `event_id` shifts; they never write to the
source planes.

---

## 2. Plane 6 — Roster-state (transfers, contracts, suspensions)

### 2.1 Records

```python
class TransferPayload(TypedDict):
    transfer_id: str               # source-native ID; canonicalized
    player_id: str                 # FK to Reference plane
    from_team_id: str | None       # null = first pro contract
    to_team_id: str | None         # null = retirement / released
    transfer_window: Literal["summer", "winter", "emergency"]
    transfer_type: Literal["permanent", "loan", "loan_with_option", "free", "end_of_loan"]
    fee_eur: int | None            # null when undisclosed
    contract_until: str | None     # ISO date
    announced_at: str              # ISO-8601 UTC
    effective_at: str              # ISO-8601 UTC; can equal announced_at
    confidence: Literal["rumour", "agreed", "official"]  # editorial provenance

class ContractPayload(TypedDict):
    contract_id: str
    player_id: str
    team_id: str
    starts_at: str
    expires_at: str
    extension: bool                # True if this updates an existing contract

class SuspensionPayload(TypedDict):
    suspension_id: str
    player_id: str
    team_id: str
    competition_id: str            # suspensions are competition-scoped
    reason: Literal["accumulated_yellows", "red", "disciplinary", "doping"]
    matches_remaining: int
    starts_at: str
    expires_after_match_id: str | None
```

### 2.2 Cadence and sources

- **Daily refresh** during transfer windows (Jul 1 – Sep 1, Jan 1 –
  Feb 1 in Europe; per-confederation calendars).
- **Weekly refresh** outside windows.
- Sources: official club announcements (TFF, club sites), Mackolik
  transfer feed, Transfermarkt-shaped data (deferred to Phase 19
  for licensing reasons; mock-stack carries a synthetic seed for
  dev only).
- **Confidence** field is critical — rumours feed sentiment, only
  `confidence=official` mutates roster-state features used by the
  predictor.

### 2.3 Feature impact

- **Squad-strength delta** — recomputed on every official transfer.
  The predictor's `team_strength` feature uses
  `mean_player_rating(active_squad_at_match_date)`.
- **Cohesion penalty** — new arrivals have a decaying cohesion
  penalty (e.g. -0.05 to xG over their first 4 league appearances).
  Coefficient lives in `cfg.cohesion_penalty_curve`.
- **Departure shock** — a top-quartile-by-rating player leaving in
  the past 14 days adds `-cfg.departure_shock` to expected goals.

### 2.4 Freshness rules

- A transfer record with `confidence=rumour` → updates editorial
  sentiment only. No roster-state change.
- A transfer with `confidence=agreed` → mutates roster-state but
  predictor labels it provisional.
- `confidence=official` → final; roster delta lands in Postgres.

---

## 3. Plane 7 — Health (injuries, suspensions overlap)

### 3.1 Records

```python
class InjuryPayload(TypedDict):
    injury_id: str
    player_id: str
    team_id: str
    body_part: str                 # taxonomy in lexicon/injury_body_parts.yaml
    severity: Literal["minor", "moderate", "major", "season_ending", "career_threat"]
    diagnosed_at: str
    expected_return: str | None    # ISO date, null if unknown
    confidence: Literal["club_statement", "press", "rumour"]
    source_url_hash: str           # SHA-256(canonical_url.encode('utf-8')).hexdigest()
                                   # provenance fingerprint — raw URL never stored
                                   # canonical form per CONTENT_FRESHNESS.md §2.2

class AvailabilityPayload(TypedDict):
    availability_id: str
    player_id: str
    team_id: str
    fixture_id: str | None         # null = general availability, set = per-fixture
    status: Literal["fit", "doubtful", "out", "suspended", "international_duty", "rest"]
    asserted_at: str
    source_confidence: Literal["club_official", "manager_presser", "press", "rumour"]
```

### 3.2 Cadence and sources

- **Spikes around team-news windows**: 24-48h before KO is when
  managers hold pressers and lineups firm up.
- **Sources**: club sites (highest confidence), Mackolik injury
  list, Twitter-style press feeds (Phase 19 — out of scope for v1
  if ToS hostile; we treat editorial-plane articles as proxy).
- **Per-confederation calendars** for international windows: a
  player can be unavailable for their club for 2-3 weeks even when
  fully fit.

### 3.3 Feature impact

- Per-fixture squad availability vector → reduces `team_strength`
  feature by sum of unavailable players' ratings, weighted by
  starter-likelihood.
- **Availability uncertainty** as a feature: if 30% of a team's
  starting XI is `doubtful`, prediction confidence is widened
  (proofreader-side).
- Suspended-player-after-cards interaction with the cards market
  (Phase 13a — `over_2.5_cards` market is a Pro/Premium feature).

### 3.4 Freshness rules

- An `out` status from a `club_official` source overrides any other
  status in the past 24h.
- Stale `doubtful` statuses (> 36h with no update before KO)
  auto-decay to `fit` for prediction purposes — but the editorial
  flag stays "uncertain availability."
- Post-match: any player who appeared in the lineup → status
  retroactively set to `fit` for that fixture (truth-from-history).

---

## 4. Plane 8 — Officials (referees, VAR)

### 4.1 Records

```python
class RefereeAssignmentPayload(TypedDict):
    assignment_id: str
    fixture_id: str
    main_referee_id: str
    assistant_referee_ids: list[str]
    fourth_official_id: str | None
    var_referee_id: str | None
    avar_referee_id: str | None
    announced_at: str
    last_minute_change: bool       # if reassigned in 24h pre-KO

class RefereeProfilePayload(TypedDict):
    referee_id: str
    full_name: str
    nationality: str
    federation: str                # "TFF", "FA", "RFEF", "UEFA", ...
    licence_level: Literal["fifa", "uefa_elite", "uefa_first", "domestic_top", "domestic"]
    debut_year: int
    # Rolling, recomputed by a reactor on every officiated-fixture event:
    rolling_stats:
        matches_officiated_total: int
        matches_officiated_window: int  # last cfg.referee_window_matches (default 50)
        yellows_per_match: float
        reds_per_match: float
        penalties_per_match: float
        home_win_pct: float
        avg_added_time_min: float
```

### 4.2 Cadence and sources

- **Assignment**: 1-3 days pre-KO from the federation/UEFA/FIFA;
  occasional last-minute changes from injuries / suspensions.
- **Profile rolling stats**: recomputed by a reactor whenever a
  match the referee officiated has its `score` record finalized.
- Sources: TFF for TR matches, UEFA for European competitions, FIFA
  for international.

### 4.3 Feature impact

- **Cards market** — referee yellow/red rate is a strong feature.
- **Penalty market** — referee penalty rate, conditional on team
  attacking style.
- **Home-bias correction** — a referee with anomalous home-win
  history gets a per-fixture home-Elo nudge applied at predict
  time (clamped at `cfg.referee_home_bias_clamp`).

### 4.4 Freshness rules

- `last_minute_change=true` triggers a reactor that **invalidates**
  the per-fixture cards/penalty derived features (recomputed with
  the new referee).
- Profile rolling-stats reactor is debounced per
  [`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md) §15 — multiple
  match-finalize events for the same referee in one batch produce
  one recompute.

---

## 5. Plane 9 — Environment (weather, pitch)

### 5.1 Records

```python
class WeatherForecastPayload(TypedDict):
    forecast_id: str
    venue_id: str
    valid_at: str                  # the forecast's target time
    issued_at: str                 # when the forecast was issued
    horizon_hours: int             # valid_at - issued_at
    temp_c: float
    wind_kph: float
    wind_direction_deg: int
    precip_mm_per_hr: float
    humidity_pct: int
    visibility_km: float | None
    conditions: str                # "clear", "rain", "snow", "fog", "thunderstorm"

class WeatherActualPayload(TypedDict):
    actual_id: str
    venue_id: str
    observed_at: str
    # same fields as forecast minus issued_at/horizon_hours

class PitchConditionPayload(TypedDict):
    pitch_id: str
    venue_id: str
    surface: Literal["natural_grass", "hybrid", "artificial_turf", "indoor"]
    condition: Literal["pristine", "good", "worn", "muddy", "frozen", "playable_with_concerns"]
    last_match_at: str
    inspection_at: str
```

### 5.2 Cadence and sources

- **Forecast**: hourly, 24h-48h horizon. Source: a free weather
  API (Phase 19 may upgrade to a commercial provider with longer
  horizons; mock-stack carries a synthetic seed for dev).
- **Actual**: at KO ±15 min, post-match update.
- **Pitch**: per-fixture inspection record (often only created when
  there's a concern; default = `good`).

### 5.3 Feature impact

- **Goals market** — wind > `cfg.wind_threshold_kph` reduces xG,
  rain reduces shooting accuracy, frozen pitch reduces xG.
- **Cards market** — heavy rain → marginally more cards (slips,
  late challenges); empirical, calibrated per league.
- **Style-mismatch** — a passing team on a worn/wet pitch loses
  more xG than a counter-attacking team.

### 5.4 Freshness rules

- Forecast records older than 6h are stale and ignored.
- Actual record overrides the forecast for post-KO computations
  (e.g. live-prediction calibration in Phase 5b).

---

## 6. Derived views (no new tables)

### 6.1 Market-movement

```python
def market_movement(market_records: list[MarketRecord]) -> dict:
    opening = earliest_within(market_records, before=fixture.kickoff - 24h)
    closing = latest_before(market_records, fixture.kickoff)
    return {
        "drift_1x2_home_pct": pct_change(opening.home, closing.home),
        "drift_1x2_draw_pct": pct_change(opening.draw, closing.draw),
        "drift_1x2_away_pct": pct_change(opening.away, closing.away),
        "drift_total_pct": pct_change(opening.total, closing.total),
        "implied_prob_shift_max": max(abs_shift),
        "high_drift_flag": max(abs_shift) > cfg.drift_high_threshold,
    }
```

A high-drift flag is a **predictor input** (information aggregation
hypothesis: late money is informed money). The proofreader uses
`high_drift_flag` to widen confidence intervals when our prediction
contradicts a strong line move.

### 6.2 Fixture-congestion

```python
def congestion(team_id: str, fixture: Fixture) -> dict:
    history = fixtures_for(team_id, until=fixture.kickoff)
    last = history[-1] if history else None
    last_3 = history[-3:]
    return {
        "days_since_last_match": days_between(last.kickoff, fixture.kickoff),
        "matches_last_7d": count_in(history, days=7),
        "matches_last_14d": count_in(history, days=14),
        "travel_km_last_7d": sum_distance(last_3),
        "is_post_international_break": …,
    }
```

Empirical: teams playing within 3 days lose ~5-8% xG. Coefficient
in `cfg.congestion_xg_decay` (calibrated per league).

### 6.3 Card-context overlay

Applied only for the `over_2.5_cards`, `team_to_get_card`, and
`booking_points` markets. Combines the referee profile (§4) with
each team's rolling cards/match history. Pure data-flow; no new
record type.

### 6.4 Public-narrative pressure

Applied only when the editorial plane has at least
`cfg.narrative_min_articles` articles in the 72h pre-KO. Uses Phase
10 NLP sentiment outputs; aggregates to a single `narrative_score`
per fixture.

---

## 7. Source registry impact

`xops/mock/sources.py` gains entries for the new sources:

| Source | Real | Mock vhost | Planes covered |
|---|---|---|---|
| **TransfersFeed** | (provider TBD; mock stub for v1) | `transfers.local` | 6 (transfers, contracts) |
| **InjuryWatch** | mackolik injury page (real) + future commercial | `injuries.local` | 7 (injuries, availability) |
| **RefereeReg** | TFF + UEFA referees pages | `refereeing.local` | 8 (referee assignments + profiles) |
| **WeatherProv** | Open-Meteo style free API (real) + synthetic mock | `weather.local` | 9 (forecast + actual) |
| **PitchInspect** | hand-curated v1; mackolik fragments | `pitchwatch.local` | 9 (pitch conditions) |

Each follows the standard pattern:

1. Add the row to `xops/mock/sources.py`.
2. `make mock.capture` to seed (rate-limited; respects robots.txt).
3. Write the extractor under
   `datasource/scraper/extractors/<source>/`.
4. Write the differ under `datasource/refresher/diffs/<source>/`.
5. Wire the new `record_type`s into the storage agent's writer.

> **No bypassing the pipeline.** Even though weather and referee
> feel "external" / "metadata," they go through the same scrape →
> categorize → process → store loop as match data. AGENTS.md rule
> 3 holds.

---

## 8. Storage & retention

| Plane | Postgres table | Retention | Index hints |
|---|---|---|---|
| 6 transfers | `transfers` | indefinite | `(player_id, effective_at desc)` |
| 6 contracts | `contracts` | indefinite | `(player_id, expires_at)` |
| 6 suspensions | `suspensions` | until expiry + 90d | `(team_id, competition_id, expires_after_match_id)` |
| 7 injuries | `injuries` | indefinite (rich history matters) | `(player_id, diagnosed_at desc)` |
| 7 availability | `availability` | per-fixture: indefinite; general: rolling 90d | `(team_id, fixture_id)`, `(player_id, asserted_at desc)` |
| 8 referee_assignments | `referee_assignments` | indefinite | `(fixture_id)` unique |
| 8 referee_profiles | `referee_profiles` | indefinite | `(referee_id)` unique; rolling stats columns |
| 9 weather_forecasts | `weather_forecasts` | 30d (then summarized) | `(venue_id, valid_at)` |
| 9 weather_actuals | `weather_actuals` | indefinite | `(venue_id, observed_at)` |
| 9 pitch_conditions | `pitch_conditions` | indefinite | `(venue_id, inspection_at desc)` |

A migration `migrations/017_enrichment_planes.sql` lands these
schemas in Phase 21 (migrations `001–016` are already applied in
this repo; `004_pipeline.sql` occupies `004`, so the enrichment
schemas land at `017`).

---

## 9. Feature-flag gating

Each enrichment plane is **independently togglable** via
`cfg.enrichment_<plane>_enabled` flags. Default state:

| Plane | Dev | Test/CI | Prod (post-13a) | Supersedes v0.2 column(s) |
|---|---|---|---|---|
| 6 Roster-state | on | on | on | *(none — new signal)* |
| 7 Health | on | on | on | *(none — new signal)* |
| 8 Officials | on | on | on | *(none — new signal)* |
| 9 Environment | on | on | on | `temperature_bucket`, `precipitation_flag`, `wind_category`, `venue_type` |
| Derived: market-movement | on | on | on | *(none — new signal)* |
| Derived: fixture-congestion | on | on | on | `home_fixture_congestion_7d`, `away_fixture_congestion_7d`, `home_fixture_congestion_14d`, `away_fixture_congestion_14d` |
| Derived: card-context | on | on | tier-gated (Premium) per [`MONETIZATION.md`](MONETIZATION.md) | *(none — new signal)* |
| Derived: narrative-pressure | on | on | on | *(none — new signal)* |

> **Supersedes semantics.** When a plane is active, the enrichment-plane value **always wins** over the v0.2 synthetic formula for the superseded column. The v0.2 synthetic formula remains the fallback for when the plane is disabled (§21.9). The superseded columns are annotated `# DEPRECATED: superseded by enrichment plane <N>` in `ai/model/features.py` (§21.21) but are **not removed** — they preserve backward compatibility for consumers that load saved 120-feature models. Removal is deferred to Phase 22 (R4 cleanup).

Disabling a plane causes the predictor to fall back to its **last
known features** (no enrichment) and emits a `predictor.warning`
event so dashboards can flag the regression. Disabling is meant
for emergency response (e.g. a bad weather feed delivers garbage),
not a normal mode of operation.

---

## 10. Tier alignment (cross-reference)

Per [`MONETIZATION.md`](MONETIZATION.md) §4, enrichment-derived
markets land at:

| Market family | Tier | Required enrichment |
|---|---|---|
| 1X2, double-chance, BTTS, totals (basic) | **Free** | none beyond planes 1-5 |
| Asian handicap, exact-score, HT/FT | **Pro** | none beyond planes 1-5 |
| Cards (over/under, team), corners, fouls | **Pro** | Officials (8), congestion |
| Player-specific (anytime scorer, assists, shots) | **Premium** | Roster (6), Health (7) |
| Penalty / red-card, weather-sensitive (windy-day totals) | **Premium** | Officials (8), Environment (9) |
| Live in-play (Phase 5b, future) | **Premium** | All planes; latency guarantees |

Adding a new market requires (a) the enrichment plane it depends on
to exist, (b) a calibration profile that includes it, (c) a
tier-mapping row in `entitlements.yaml`.

---

## 11. NLP impact (Turkish-first)

The Turkish-aware Q&A layer must understand questions about every
new plane:

- **Transfers**: *"Galatasaray'a yeni transfer var mı?"* → query the
  `transfers` table for `to_team_id=tr_galatasaray` and
  `effective_at` in the future.
- **Injuries**: *"Mauro Icardi sakat mı?"* → query the `injuries`
  table for the latest non-resolved injury for player.
- **Referee**: *"Bugünkü maçın hakemi kim?"* → query
  `referee_assignments` for the fixture.
- **Weather**: *"Yağmur yağacak mı?"* → query the freshest
  `weather_forecast` for the venue.
- **Suspension**: *"X oyuncu kart cezalısı mı?"* → query active
  suspensions.

Intents added to the Phase 10 classifier:
`transfer_lookup`, `injury_lookup`, `availability_lookup`,
`referee_lookup`, `weather_lookup`, `suspension_lookup`. Each is a
single template-driven query — **no LLM**, per AGENTS.md rule #4.

---

## 12. Definition-of-Done for "enrichment"

> **Note.** This section is a condensed summary for quick reference. The canonical, authoritative Definition of Done is **ROADMAP §21.26** in `docs/planning/ROADMAP.md`. §21.26 extends and supersedes the checklist below. When the two diverge, §21.26 governs.
>
> **Feature count.** The total enrichment-column count is **27** (not 25 as earlier drafts stated). The market-movement derived view contributes 6 columns (`drift_1x2_home_pct`, `drift_1x2_draw_pct`, `drift_1x2_away_pct`, `drift_total_pct`, `implied_prob_shift_max`, `high_drift_flag`); earlier drafts omitted `drift_total_pct` and `implied_prob_shift_max`. `N_FEATURES` = 120 + 27 = **147**.

Per plane (#6, #7, #8, #9):

- [ ] Source row in `xops/mock/sources.py` with `make mock.capture`
      seed verified; TLS vhost cert issued by project CA.
- [ ] Extractor + differ committed and unit-tested (**≥ 7 tests, including ≥ 2 adversarial**; aligns with ROADMAP Phase 21 per-plane test floor).
- [ ] Postgres migration in `migrations/`; **migration down script** present; rollback test green.
- [ ] Storage-agent writer path added; unique-key collision tests pass; player-ID integrity guard present.
- [ ] **At least two** freshness rules in `CONTENT_FRESHNESS.md` §7 (one normal-cadence + one override rule — per ROADMAP §21.15 and §21.20).
- [ ] Feature columns added to `ai/model/features.py` `FEATURE_COLUMNS` and `N_FEATURES` auto-resolved in `ai/common/constants.py` (per ROADMAP §21.16; `N_FEATURES = len(FEATURE_COLUMNS)` — never a hardcoded literal).
- [ ] `record_type` enum entry added to `common/schemas/records.py` and corresponding JSONSchema added to `common/schemas/feeds/` (per ROADMAP §21.17).
- [ ] Predictor includes the feature behind the `cfg.enrichment_<plane>_enabled` flag; Redis cache layer tested; `msgpack` serialization used for cache values.
- [ ] Tier mapping row in `entitlements.yaml` for any market that depends on this plane.
- [ ] NLP intent + ≥ 5 sample TR queries in `ai/tests/fixtures/turkish_queries.yaml` (including ≥ 1 negation and ≥ 1 misspelling variant).
- [ ] Per-plane circuit breaker and DLQ wiring active (per ROADMAP §21.19); circuit-breaker state persisted in Redis (process restart does not reset an open breaker).
- [ ] Per-plane Prometheus metrics registered in `TelemetrySink` (per ROADMAP §21.30); alert rule present in `xops/monitoring/enrichment_alerts.yaml`.
- [ ] Smoke test exercises the plane end-to-end (`make smoke.enrichment` passes; per ROADMAP §21.31).
- [ ] Component bump on `enrichment_<plane>` chart key.

---

## 13. What this doc does **not** cover

- **Live in-play data** — already part of plane 3 (Live); enrichment
  here is pre-match-focused.
- **Betting-exchange data** (Betfair-style) — out of scope for v1;
  considered Phase 19 if licensing permits.
- **Fan attendance / atmosphere** — too noisy for v1; revisit when
  social-listening sources are licensed.
- **Tactical formations** — covered by lineup data (plane 3) plus
  manager profile (Reference plane); not a separate enrichment.

---

## 14. Reading order for new contributors

1. `DATA_PIPELINE.md` — the original five planes and the Record
   contract you must respect.
2. This doc up to §6 — the four new planes + four derived views.
3. `CONTENT_FRESHNESS.md` §7 — how to add a differ for the new
   record types. Also read §15 for the derived-view coalescing spec.
4. `MONETIZATION.md` §4 — how each enrichment-derived market is
   tier-gated.
5. ROADMAP Phase 21: start with §21.0 (config stubs and dependency
   ordering), then §21.26 (canonical Definition of Done). For
   observability requirements read §21.30; for end-to-end smoke tests
   read §21.31; for cross-plane consistency invariants read §21.29.
