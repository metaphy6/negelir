# Phase 13.2 — Competition platform — `CompetitionConfig`, `FixturePayloadV2`, `CalibrationProfile`

> Extracted from `docs/planning/ROADMAP.md` §13.2
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.2 Competition platform — `CompetitionConfig`, `FixturePayloadV2`, `CalibrationProfile`

- [x] `common/schemas/competition.py` — `CompetitionPayload` + `CompetitionStage` TypedDicts per `COMPETITIONS.md` §2.1–§2.2; JSONSchema mirrored under `common/schemas/feeds/competition.v1.json` for Phase 16 emitter.
- [x] `Record.record_type` enum gains `"competition"` (confirmed in `DATA_PIPELINE.md` §4); reference-plane storage specified; schema versioning integrated. **Reference-plane storage (Postgres):** `competitions` table with columns `competition_id` (PK, text), `name_en`, `name_tr`, `format`, `scope`, `default_venue_policy`, `organizer`, `confederation`, `countries` (jsonb array), `nationality_restricted`, `calibration_profile_id`, `stages` (jsonb), `first_season`, `active`, `successor_competition_id`, `payload_version`, `created_at`, `updated_at`. Indexed on `(competition_id)` and `(scope, format)` for resolver queries (O(1) reference lookups per §13.1 footprint audit). Per `DATA_PIPELINE.md` §6 retention rule: forever (slow journal table). Identity strategy: `competition_id` is upstream-stable (CONTENT_FRESHNESS §2); canonicalization on `name_tr` changes or format mutations bumps `canonical_version`. **Backfill migration** (`migrations/016_competition_records.sql`): creates the `competitions` table, backfills seed competitions from `ai/common/league_catalog.yaml` (one row per row where `competitions` array non-empty), and backfills per-competition metadata from the COMPETITIONS.md §4.2 profile catalog (eleven seed profiles with format + venue_policy derivation). Idempotent: existing rows skipped (on-conflict-do-nothing). No records deleted (append-only audit trail per §13.26).
- [x] `FixturePayloadV2` (additive) lands with `competition_id`, `competition_format`, `stage_id`, `leg_index`, `leg_of_id`, `venue_policy`, `is_neutral_venue` per `COMPETITIONS.md` §3. Existing `FixturePayloadV1` extractors keep working via additive defaults.
- [x] **Schema-gate at ingest.** Storage refuses fixtures missing `competition_id` / `competition_format` / `venue_policy` for any source whose `LeagueRow.tier ∈ {T1, T2}`; T3 rows allow null with a warning that increments `negelir_fixture_competition_missing_total{league_id}`.
- [x] `ai/common/calibration_profiles/` directory populated with the eleven profiles from `COMPETITIONS.md` §4.2; each YAML validated against `ai/common/schemas/calibration_profile.schema.json` at boot.
- [x] `CalibrationProfileLoader` — refuses to start on unknown profile_id; refuses to start on a YAML whose `zero_home_advantage_when_venue_in` mentions an unknown `venue_policy`.
- [x] **Resolution rule (deterministic, no LLM).** `swarm/predictor/_calibration.py::resolve_profile(fixture, competition)` implements the three-step rule (`COMPETITIONS.md` §4.1). Proof tests:
  - `test_profile_resolution_priority.py` (stage > competition > default).
  - `test_neutral_venue_zeros_home_advantage.py` (regardless of profile).
  - `test_no_llm_in_calibration_resolver.py` (AST scan refuses any `from openai|anthropic|llm` import in `_calibration.py`).
- [x] **Per-format unit tests.** Each of the 8 `format` values has at least one happy-path predictor test using a synthetic fixture from `ai/tests/fixtures/competitions/`.
- [x] **Competition lifecycle FSM.** `Competition.status ∈ {planned, active, suspended, completed, cancelled}`; transitions are deterministic, append-only-audited, and refused if predictor inflight requests reference the competition (drains first per §13.26). Proof test `test_competition_status_fsm.py` covers every legal and illegal transition.
- [x] **Multi-stage composition gate.** A `group_then_knockout` competition refuses to advance to `knockout` stage until every group's `round_robin` is `completed` and the qualifier set is fully resolved (proof test `test_multistage_advance_gate.py`).
- [x] **Calibration-profile coverage matrix.** `xops/lint/calibration_coverage.py` asserts every `(competition_format, venue_policy)` pair used in the catalog has a resolved profile; missing pair = CI fail.
- [x] **Profile drift guard.** Editing a published calibration YAML bumps the profile's `schema_version` and forces a 14-day shadow window (§11.26) before promotion to live; lint refuses an in-place silent edit.
- [x] **`make swarm.demo COMPETITION=<id>`** prints a sample prediction with the calibration profile name in the rationale (DoD line, `COMPETITIONS.md` §9).
