# Phase 13.20 — Time zone, scheduling correctness, DST

> Extracted from `docs/planning/ROADMAP.md` §13.20
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.20 Time zone, scheduling correctness, DST

> Kickoff times are notoriously mishandled across sources. Retires
> assumption §13.0 #21.

- [x] **UTC + IANA tz canonical storage.** `Fixture.kickoff_utc: datetime` + `venue.tz: str` (IANA name); never store local-only strings. `xops/lint/no_naive_datetime.py` refuses naive datetimes anywhere in `ai/`, `swarm/`, `server/`. Landed: lint + schema; proof test confirmed.
- [x] **DST-spring-forward fixture test.** `test_fixture_at_dst_transition.py` covers a kickoff scheduled at the non-existent local time during spring-forward (e.g. 03:30 in Istanbul on the cutover); resolver picks the next valid local time and logs the adjustment. Landed: test confirmed.
- [x] **DST-fall-back fixture test.** `test_fixture_at_dst_repeat.py` covers a kickoff at the repeated local hour in fall-back; resolver picks the first occurrence per IETF / `pytz` `is_dst` convention. Landed: test confirmed.
- [x] **Ramadan / late-night kickoff.** Iran Pro League / Saudi Pro League / TFF Cup matches scheduled for 22:30+ local during Ramadan are correctly attributed to the same calendar date in the league's official schedule (proof test `test_late_kickoff_date_attribution.py`). Landed: logic + test confirmed.
- [x] **`asof` query consistency.** All "matches today" queries are evaluated in the league's home tz unless an explicit `?tz=` is passed; Phase 9 API exposes the policy in OpenAPI. Landed: query logic + API docs; proof test confirmed.
- [x] **Tz database staleness check.** Container build asserts the bundled `tzdata` is no older than `cfg.tzdata_max_age_days` (default 180); CI fails on stale data. Landed: build check; proof test confirmed.
- [x] **Tz update protocol.** Bumping `tzdata` triggers a `make leagues.tz.replay` smoke that re-evaluates every fixture's `kickoff_utc` for kickoffs in the next 90 days; any drift > 0 emits `proof.flag.v1{kind=tz_update_drift, fixture_id, prior_utc, new_utc}` for ops review (proof test `test_tz_update_replay.py`). Landed: replay logic; proof test confirmed.
- [x] **Per-venue tz override.** A venue tz that disagrees with the country tz (border venues, year-round-DST jurisdictions like Iceland) carries `Venue.tz_override`; loader refuses `Venue.tz` to differ from country tz without an audited override (proof test `test_venue_tz_override_audited.py`). Landed: override field + lint; proof test confirmed.

#### 13.20.5 Venue plane

> Stadium capacity, pitch dimensions, surface, altitude — these
> matter for predictor features (altitude → travel-fatigue,
> artificial turf → injury-rate signal, capacity → home-advantage).
> Retires assumption §13.0 #31.

- [x] **`Venue` Reference-plane entity.** `(venue_id, name, city, country, tz, capacity, pitch_dim, surface, altitude_m, opened_year, demolished_year?)`; joined to fixtures via `Fixture.venue_id`. Landed: schema + loader; proof test confirmed.
- [x] **Venue completeness gate.** A league cannot promote past T2 if more than `cfg.league_venue_missing_max_pct` (default 5 %) of its fixtures lack a resolved venue. Landed: gate in readiness check; proof test confirmed.
- [x] **Neutral-venue declaration.** `Fixture.is_neutral_venue=true` requires `venue_id` to differ from both teams' `home_venue_id` (proof test `test_neutral_venue_consistency.py`). Landed: lint + test; proof test confirmed.
