# Phase 13.24 — Data residency, GDPR / KVKK / CCPA per league country

> Extracted from `docs/planning/ROADMAP.md` §13.24
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.24 Data residency, GDPR / KVKK / CCPA per league country

> Retires assumption §13.0 #25.

- [ ] **`LeagueRow.data_residency`** enum maps to a Phase 16 emitter shard policy: `{eu, tr, americas, apac, mea}`; storage routing per shard.
- [ ] **PII isolation for player records.** `Player` entities (in §13.4 / Phase 21) carry `country_of_residence`; PII fields (DOB, contract value) gated per jurisdiction at the API edge (Phase 9 + Phase 11 §11.39 `data_class=pii`).
- [ ] **Right-to-be-forgotten per player.** `make players.forget PLAYER_ID=<id>` redacts PII without breaking historical fixture records (predictions stand, lineups carry an opaque `player_<sha8>` token); proof test `test_player_forget_preserves_fixtures.py`.
- [ ] **TR KVKK compliance row.** Turkish Süper Lig + TR Lig 1 + national team carry KVKK acknowledgement; per Phase 9 OpenAPI an admin-token client sees the full surface, others see redacted.
- [ ] **Audit topic for PII access.** Every PII read emits `sec.audit.v1{kind=pii_read, player_id, actor_token_sha8, league_id}` (per Phase 11 §11.39); rate-limit on per-actor PII reads.
