# Phase 13.16 — Cross-phase coupling matrix (closing audit; lint-gated)

> Extracted from `docs/planning/ROADMAP.md` §13.16
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.16 Cross-phase coupling matrix (closing audit; lint-gated)

| Other phase | What Phase 13 owes | Where |
|---|---|---|
| Phase 2.8 | Per-source health & drift signals feed the source-watcher's classifier corpus; per-league × per-source freshness budget surfaces here | §13.6, §13.55, §13.62 |
| Phase 4 | New-source extractors per §13.6; rate-limit row per source; per-source TLS pin + ToS snapshot per §13.25; weather-source registry; integrity-authority registry; federation-canonical-URL crawl; adaptive AIMD scrape rate-limit; per-league × per-source token bucket | §13.6, §13.25, §13.31, §13.35, §13.39, §13.55, §13.62 |
| Phase 5 | `CalibrationProfile` resolver + per-format predictor branches; tie reactor; rules-variant overlay; cold-start widening for promoted clubs; per-league predictor warm-up; coefficient-derived priors; match-clock normalization; integrity / clash / purity / suspension publish-gates; signed prediction envelopes; cross-competition prediction-consistency oracle; demotion-cascade revoke; placeholder-fixture partial markets; live bracket invariant prover; penalty-shootout plane | §13.2, §13.12, §13.13, §13.13.5, §13.19, §13.32, §13.34, §13.38, §13.39, §13.44, §13.46, §13.46.5, §13.51, §13.54, §13.57, §13.58, §13.65, §13.66 |
| Phase 6 | Beta-tier widened CI; quorum honoured per league tier; per-league bias veto on T2→T1; cascade reactor; market-roster veto; field-provenance conflict resolution; per-season market-roster overlay; tiebreaker overlay consumed by standings recompute; market-line anomaly flag escalation | §13.7, §13.23, §13.36, §13.40, §13.45, §13.52, §13.56, §13.67 |
| Phase 7 | New-source `sec.input` quarantine; identity-resolver veto on poisoned anchors; fixture-lifecycle-abuse rate-limit; weather staleness drop; transfer-fee source-conflict hold; integrity-flag refusal; adaptive-scrape sustained-429 quarantine | §13.4, §13.6, §13.28, §13.30, §13.31, §13.39, §13.62 |
| Phase 8 | Per-league dashboard panels; demotion alert routing; per-league replica scaling; quarantine surfacing; identity-merge audit topic; officials assignment audit; cascade fan-out audit; warm-up audit; drift flag console; integrity flag console; sandbox metric isolation; per-region catalog-hash rollup; canary-deployment status; market-line anomaly panel; metric label tombstones | §13.4, §13.8, §13.10, §13.15, §13.29, §13.34, §13.35, §13.39, §13.40, §13.43, §13.50, §13.61, §13.67, §13.68 |
| Phase 9 | API tier header `X-League-Tier`; 404 for T3 to non-admin tokens; `Sunset` / `Deprecation` headers; `/healthz` carries `catalog_sha256` + `catalog_schema_version`; per-league inflight cap surfaces `503 + X-Reason: per_league_inflight_full`; warming-league header; integrity / clash refusal codes; data-portability endpoints; catalog `?asof=` time-travel; placeholder-fixture partial-market refusals; canary-deployment refusal codes; market-line anomaly admin endpoint | §13.1, §13.7, §13.9, §13.10, §13.27, §13.34, §13.39, §13.42, §13.46.5, §13.47, §13.51, §13.60, §13.61, §13.67 |
| Phase 10 | Gazetteer auto-feed; competition + transfer/injury/referee/weather/suspension intents; locale-aware Unicode normalization; rebrand alias auto-feed; mixed-script + confusable defense | §13.11, §13.41 |
| Phase 11 | Capacity admission preflight when scaling new replicas; embedding model footprint; per-league inflight cap; PII data-class routing for player + transfer + provenance + integrity; weight encryption for restricted league bundles; storage-independent cold-start contract; per-league bundle-key partitioning; rolling deployment compat; backtest concurrency under CPU governor | §13.5, §13.9, §13.10, §13.24, §13.30, §13.36, §13.49, §13.54, §13.60 |
| Phase 12 | Per-league adversarial corpus (§13.28) feeds the chaos suite; chaos-quarantine drill; corpus rotation + pinning policy; rolling-deployment chaos; storage-deny chaos; bracket-invariant chaos; tamper-detection chaos | §13.15, §13.28, §13.48, §13.49, §13.57, §13.60 |
| Phase 14 | Multi-region storage routing per `LeagueRow.data_residency`; per-jurisdiction VAT/portability overlays; multi-region catalog consistency + per-region quorum reload; canary-deployment per-region routing; per-region weather-source failover | §13.24, §13.31, §13.37, §13.47, §13.50, §13.61 |
| Phase 16 | `competition.v1` feed; per-league NDJSON shard naming; `manifest.json` per-league counts; `predict.invalidated.v1` re-shard contract; data-residency shard policy; market-roster declared per shard; field-provenance round-trip; cascade-invalidation re-shard; signed-envelope persistence; placeholder-fixture re-shard on materialisation; tombstone metric series archival | §13.2, §13.17, §13.24, §13.36, §13.40, §13.45, §13.51, §13.54, §13.68 |
| Phase 17 | Patcher artifact tagged with `league_id` + `competition_id`; per-league cool-down (cooldown days × log-loss-volatility multiplier from this league's calibration history); auto-quarantine on unresolved artifact; field-provenance required in diagnostic bundle; sandbox-relaxed scope contract; per-league bundle key for any patcher-touched bundle; calibration-mutation audit chain | §13.6, §13.8, §13.15, §13.36, §13.43, §13.54, §13.63 |
| Phase 19 | Catalog-pluggability AST scan; T3 zero-cost-when-empty; T2 dwell-time ceiling drives long-tail churn back to T3; rebrand handover; per-league canary deployment for long-tail incubation | §13.1, §13.10.5, §13.41, §13.61 |
| Phase 20 | Per-league entitlement row; default_tenant_class; per-tier quota; PII gating per jurisdiction; SKU-band lookup (no hardcoded prices); market-roster intersection per SKU; sandbox immunity; per-season market roster surfaces in entitlement view | §13.1, §13.9, §13.24, §13.37, §13.43, §13.45, §13.56 |
| Phase 21 | Per-format enrichment requirements (player markets need lineups + cards planes per `ENRICHMENT_DATA.md`); `Player.eligibility` join feeds injury / suspension / FIFA-window features; weather plane feeds match-conditions enrichment; officials registry feeds referee enrichment; penalty-shootout plane feeds first-taker-to-miss markets; qualifier-flow plane feeds drop-down "to win UEL" markets | §13.4.5, §13.11, §13.14, §13.29, §13.31, §13.32, §13.53, §13.58 |

`xops/lint/phase13_coupling_matrix.py` refuses a PR that touches a referenced sub-section without updating this table.

---

### 13a — Top-5 EU + TR + UEFA + WC/EURO (foundation expansion)

> **Sequencing.** §13.1 + §13.2 + §13.3 + §13.7 + §13.10 + §13.11 + §13.16 are **prerequisites for any 13a row** — they ship first and unlock the per-league grind. Each league row below is one tracker entry + one chart bump + one mock-seed capture + one preset file + one entitlement row + readiness-gate green.

**Domestic leagues (T1):**

- [x] 🇹🇷 Süper Lig — *seeded default since v2.0.0*
- [ ] 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League
- [ ] 🇪🇸 La Liga
- [ ] 🇩🇪 Bundesliga
- [ ] 🇮🇹 Serie A
- [ ] 🇫🇷 Ligue 1

**Domestic cups + super cups (T2 → T1 after 4-week beta window):**

- [ ] 🇹🇷 Türkiye Kupası (depends on TR Lig 1 anchor coverage §13.4), TFF Süper Kupa
- [ ] 🏴󠁧󠁢󠁥󠁮󠁧󠁿 FA Cup, EFL Cup, Community Shield
- [ ] 🇪🇸 Copa del Rey, Supercopa de España
- [ ] 🇩🇪 DFB-Pokal, DFL-Supercup
- [ ] 🇮🇹 Coppa Italia, Supercoppa Italiana
- [ ] 🇫🇷 Coupe de France, Trophée des Champions

**Continental club (T2):**

- [ ] 🇪🇺 UEFA Champions League (qualifying + league phase + knockout) — three competition rows sharing one `league_id`
- [ ] 🇪🇺 UEFA Europa League (qualifying + league phase + knockout)
- [ ] 🇪🇺 UEFA Conference League (qualifying + league phase + knockout)
- [ ] 🇪🇺 UEFA Super Cup (one-off; `final_only`)

**International (T2):**

- [ ] 🌍 FIFA World Cup (group + knockout — composite `group_then_knockout`)
- [ ] 🇪🇺 UEFA EURO Championship (group + knockout)
- [ ] 🌍 WC qualifiers (UEFA confederation only in 13a)
- [ ] 🇪🇺 EURO qualifiers
- [ ] 🇪🇺 UEFA Nations League

**13a Definition of Done:**

- [ ] **All §13.1–§13.16 platform sub-phases green.**
- [ ] **All new platform sub-phases §13.29–§13.48 green at least at the foundation level (registries seeded, schemas live, lint wired) — full per-league population continues into 13b / 13c.**
- [ ] **All new resilience / integrity sub-phases §13.49–§13.68 green at the platform level** (storage-independent cold-start proven, multi-region catalog quorum live, signed prediction envelopes wired, per-league × per-source token bucket live, adaptive scrape rate-limit live, catalog uniqueness + forward/backward compat lints green, canary-deployment lane live, calibration-mutation audit chain live, market-line anomaly detector wired in `internal_only` mode, metric-label tombstones live).
- [ ] Every domestic-league row above is T1 with calibration plot deviation ≤ `cfg.league_calibration_max_deviation` over a 4-week beta window.
- [ ] Every cup / continental / international row above is at least T2 with mock seeds + readiness report `pass` for T3→T2.
- [ ] Two-leg-tie idempotency + away-goals era-awareness verified end-to-end on a UCL knockout from the backtest corpus (one tie pre-2021/22, one post).
- [ ] `make test.leagues` green; `test_no_league_id_branching.py`, `test_catalog_roundtrip.py`, `test_catalog_entitlements_consistency.py`, `test_catalog_chart_consistency.py`, `test_no_llm_in_calibration_resolver.py`, `test_friendlies_never_published.py`, `test_one_bad_league_isolated_at_startup.py`, `test_no_hardcoded_era_constants.py`, `test_emitter_refuses_undeclared_market.py`, `test_integrity_flag_blocks_publish.py`, `test_cascade_reactor_idempotent.py`, `test_league_warming_fsm.py`, `test_catalog_asof_deterministic.py`, `test_catalog_loader_no_storage_imports.py`, `test_cold_start_under_storage_outage.py`, `test_drift_blocks_cross_region_routing.py`, `test_placeholder_fixture_partial_markets.py`, `test_tiebreaker_recompute_deterministic.py`, `test_qualifier_flow_no_cycles.py`, `test_predictions_tamper_detection.py`, `test_revision_requires_cause.py`, `test_per_league_key_isolation.py`, `test_scrape_bucket_partitions_correctly.py`, `test_scrape_fairness_floor.py`, `test_predictor_uses_season_roster.py`, `test_invariant_violation_blocks_publish.py`, `test_shootout_order_validation.py`, `test_guest_entry_no_anchor_pollution.py`, `test_rolling_deployment_catalog_compat.py`, `test_old_binary_refuses_new_field_write.py`, `test_adaptive_rate_bounded.py`, `test_adaptive_respects_robots_crawl_delay.py`, `test_catalog_alias_collision_within_country.py`, `test_cross_competition_consistency_threshold_well_chosen.py`, `test_demotion_cascade_idempotent.py` all green.
- [ ] Sandbox-league lane (§13.43) live; `make leagues.sandbox.smoke` part of CI.
- [ ] Per-league component keys at ≥ `0.1.0` in `xops/versioning/chart.json`; `project` umbrella bumped on the 13a milestone.

### 13b — +10 most popular non-Top-5 leagues (T2)

Each starts at T2 (publicly available with widened CI per `cfg.proofreader_beta_ci_widen`) and promotes to T1 once §13.7 passes.

- [ ] 🇵🇹 Primeira Liga
- [ ] 🇳🇱 Eredivisie
- [ ] 🇧🇪 Pro League
- [ ] 🇹🇷 TR Lig 1 (2nd tier — **prerequisite for Türkiye Kupası identity §13.4**; lands first in 13b)
- [ ] 🇧🇷 Brasileirão Série A
- [ ] 🇦🇷 Liga Profesional Argentina
- [ ] 🇲🇽 Liga MX
- [ ] 🇺🇸 MLS (regular season `round_robin` + `playoff_bracket` post-season — two competition rows)
- [ ] 🇯🇵 J1 League
- [ ] 🇰🇷 K League 1

**13b Definition of Done:**

- [ ] Every row above passes T3 → T2 readiness gate.
- [ ] TR Lig 1 anchor coverage ≥ `cfg.cup_identity_coverage_min` so Türkiye Kupası in 13a can promote to T1.
- [ ] Per-confederation identity (Conmebol, AFC, CONCACAF) anchor sets initialised; cross-confederation anchor join tested for at least one CONMEBOL ↔ UEFA player (e.g. an Argentine playing in La Liga).
- [ ] Headline domestic cup per league captured at least at T3 (full T2 promotion may slip into 13c).

### 13c — Continental + Completeness pass

- [ ] 🌎 CONMEBOL Libertadores, Sudamericana, Recopa
- [ ] 🌏 AFC Champions League Elite + Two
- [ ] 🌍 CAF Champions League
- [ ] ⚽ FIFA Club World Cup
- [ ] ⚽ FIFA Intercontinental Cup (`final_only`)
- [ ] 🌎 Copa América, AFCON, Asian Cup, Gold Cup
- [ ] 🌍 WC qualifiers (all confederations not in 13a — CONMEBOL, AFC, CAF, CONCACAF, OFC)

**13c Definition of Done:**

- [ ] Per-confederation source coverage live (fifa.com, conmebol, afc, caf, concacaf, ofc) per §13.6.
- [ ] `intercontinental_club` competitions modelled with `super_cup_one_off` calibration profile; sample prediction in the rationale (DoD line).
- [ ] National-team plane (§13.14) covers every confederation's qualifier path.
- [ ] All 13a / 13b cups still pass §13.7 — i.e. broadening the roster did not regress narrower competitions (proof test `test_13c_does_not_regress_13a_13b.py`).

### 13.x NLP per league (cross-cutting; applies to a / b / c)

> Operationalised by §13.11; this block kept for tracker continuity.

- [ ] Foreign team names get TR transliteration ("Bayern" → "Bayern Münih" with both forms accepted).
- [ ] Entity-extraction lexicons per league, merged at runtime via the gazetteer auto-feed (no hand-edited per-league files).
- [ ] Phase 10 `transfer_lookup` / `injury_lookup` / `referee_lookup` / `weather_lookup` / `suspension_lookup` intents land alongside `13a` (see Phase 21).
- [ ] Per-league entity-extraction recall ≥ `cfg.nlp_promotion_recall_min` on a 50-query corpus before T2 → T1 promotion.

### 13.DoD — overall Phase 13 Definition of Done

In addition to every per-section DoD above + Appendix B common DoD:

- [ ] Wrong-assumption ledger (§13.0) — every retired assumption has at least one passing proof test (both directions where applicable: bug demonstrated, then fix demonstrated).
- [ ] Cross-phase coupling matrix (§13.16) is complete; lint refuses a PR touching a referenced sub-section without updating the table.
- [ ] `xops/env/.env.example` documents every new key (`NEGELIR_LEAGUE_CATALOG_LOAD_MAX_MS`, `NEGELIR_LEAGUE_CATALOG_MAX_RSS_MB`, `NEGELIR_LEAGUE_PER_ROW_MAX_KB`, `NEGELIR_LEAGUE_BETA_MIN_DAYS`, `NEGELIR_LEAGUE_T2_MAX_DWELL_DAYS`, `NEGELIR_LEAGUE_DEMOTION_MIN_DAYS`, `NEGELIR_LEAGUE_DEMOTION_EVIDENCE_WINDOW_H`, `NEGELIR_LEAGUE_READINESS_REPORT_MAX_AGE_H`, `NEGELIR_LEAGUE_READINESS_REPORT_RETENTION`, `NEGELIR_LEAGUE_PROMOTION_LOGLOSS_MAX`, `NEGELIR_LEAGUE_PROMOTION_BRIER_MAX`, `NEGELIR_LEAGUE_CALIBRATION_MAX_DEVIATION`, `NEGELIR_LEAGUE_METRICS_CARDINALITY_BUDGET`, `NEGELIR_LEAGUE_VENUE_MISSING_MAX_PCT`, `NEGELIR_LEAGUE_ERROR_RATE_CIRCUIT_OPEN`, `NEGELIR_LEAGUE_ERROR_RATE_CIRCUIT_HALF_OPEN`, `NEGELIR_LEAGUE_RTO_MAX_MINUTES`, `NEGELIR_LEAGUE_RPO_MAX_MINUTES`, `NEGELIR_NLP_PROMOTION_RECALL_MIN`, `NEGELIR_PROOFREADER_BETA_CI_WIDEN`, `NEGELIR_IDENTITY_MERGE_THRESHOLD`, `NEGELIR_IDENTITY_FALSE_SPLIT_MAX_PER_WEEK`, `NEGELIR_CUP_IDENTITY_COVERAGE_MIN`, `NEGELIR_CUP_EARLY_ROUND_CALIBRATION_MAX_DEVIATION`, `NEGELIR_COMPETITION_CALIBRATION_TOLERANCE_<FORMAT>`, `NEGELIR_TIE_SOURCE_QUORUM`, `NEGELIR_FIXTURE_LIFECYCLE_QUORUM`, `NEGELIR_FIXTURE_INVALIDATION_RATE_MAX_PER_H`, `NEGELIR_SWARM_DLQ_MAX_LEN_PER_LEAGUE`, `NEGELIR_PREDICTOR_INFLIGHT_MAX_PER_LEAGUE`, `NEGELIR_COLD_START_WIDEN_FACTOR`, `NEGELIR_FATIGUE_WINDOW_H`, `NEGELIR_BIAS_RESIDUAL_THRESHOLD`, `NEGELIR_REFEREE_INTERACTION_MAX`, `NEGELIR_REFEREE_SHRINKAGE_LAMBDA`, `NEGELIR_REFEREE_MIN_MATCHES_FOR_FULL_WEIGHT`, `NEGELIR_ERA_DRIFT_TOLERANCE`, `NEGELIR_TZDATA_MAX_AGE_DAYS`, `NEGELIR_SOURCE_PIN_ROTATION_OVERLAP_H`, `NEGELIR_ROBOTS_RECHECK_H`, `NEGELIR_CATALOG_RELOAD_DRAIN_MAX_S`, `NEGELIR_CATALOG_RELOAD_PROPAGATION_MAX_S`, `NEGELIR_FIELD_REMOVAL_SHADOW_DAYS`, `NEGELIR_LEAGUE_CATALOG_READONLY`, `NEGELIR_LEAGUE_AUDIT_COMPACTION_DAYS`, `NEGELIR_LEAGUE_WEATHER_COVERAGE_MIN`, `NEGELIR_WEATHER_FRESHNESS_MAX_H`, `NEGELIR_ATTENDANCE_COVERAGE_T1_MIN`, `NEGELIR_LEAGUE_WARMUP_MIN_H`, `NEGELIR_LEAGUE_WARMUP_REPLAY_N`, `NEGELIR_LEAGUE_WARMUP_MAX_DIFF`, `NEGELIR_FEDERATION_DRIFT_CHECK_H`, `NEGELIR_SUSPENSION_CONFIDENCE_WIDEN`, `NEGELIR_CATALOG_ASOF_MAX_AGE_DAYS`, `NEGELIR_COEFFICIENT_DRIFT_MAX`, `NEGELIR_STOPPAGE_MAX_MIN`, `NEGELIR_CLASH_BUFFER_MIN`, `NEGELIR_GDPR_EXPORT_MAX_DAYS`, `NEGELIR_ADVERSARIAL_CORPUS_MAX_PER_FAMILY`, `NEGELIR_LEAGUE_AUDIT_BOOT_VERIFY_MAX_MS`, `NEGELIR_CATALOG_REGION_DRIFT_MAX_S`, `NEGELIR_CATALOG_RELOAD_REGION_QUORUM_PCT`, `NEGELIR_CATALOG_REGION_PROPAGATION_MAX_S`, `NEGELIR_PLACEHOLDER_STALE_GRACE_H`, `NEGELIR_BRACKET_SLOT_RESOLVE_MAX_H`, `NEGELIR_BRACKET_VIOLATION_RECOVERY_MAX_H`, `NEGELIR_PREDICTIONS_TAMPER_DETECTION_MAX_S`, `NEGELIR_DEMOTION_REVOKE_GRACE_MIN`, `NEGELIR_SCRAPE_PER_LEAGUE_FLOOR_PCT`, `NEGELIR_SCRAPE_BURST_FACTOR`, `NEGELIR_SCRAPE_BURST_WINDOW_S`, `NEGELIR_SCRAPE_AIMD_ALPHA`, `NEGELIR_SCRAPE_AIMD_BETA`, `NEGELIR_SCRAPE_MIN_RPS`, `NEGELIR_SCRAPE_MAX_RPS`, `NEGELIR_SCRAPE_DRIFT_COOLDOWN_MIN`, `NEGELIR_SHOOTOUT_SOURCE_QUORUM`, `NEGELIR_LEAGUE_PRESET_TOTAL_IMPORT_MAX_MS`, `NEGELIR_LEAGUE_PROPOSE_MAX_AGE_H`, `NEGELIR_LEAGUE_CANARY_PCT`, `NEGELIR_LEAGUE_CANARY_MIN_H`, `NEGELIR_LEAGUE_CANARY_DLQ_MAX`, `NEGELIR_LEAGUE_CANARY_CALIBRATION_MAX`, `NEGELIR_LEAGUE_CALIBRATION_READONLY`, `NEGELIR_CROSS_COMPETITION_CONSISTENCY_MAX_DELTA`, `NEGELIR_LINE_MOVEMENT_ANOMALY_PCT`, `NEGELIR_LINE_MOVEMENT_WINDOW_MIN`, `NEGELIR_LINE_MOVEMENT_ANOMALY_PERSISTENCE_MIN`, `NEGELIR_METRICS_CARDINALITY_ROLLING_DAYS`, `NEGELIR_GAZETTEER_COMPILE_MAX_MS`, `NEGELIR_BACKTEST_CONCURRENCY_MAX`, `NEGELIR_WEATHER_FAILOVER_MAX_S`) with defaults that match `ai/common/config.py`.
- [ ] `LEAGUE_CATALOG.md` updated with the new §11 SLO contract + error-budget policy and the §2 readiness checklist additions surfaced here (mock-corpus completeness gate, two-person T1 rule, dwell-time ceiling, venue-completeness gate, bias veto, weather-coverage gate, attendance-coverage gate, warm-up gate, federation-drift acknowledgement gate, market-roster declaration, canary-deployment phase, multi-region quorum, catalog uniqueness constraints, schema forward-compat policy).
- [ ] `COMPETITIONS.md` updated with the deterministic resolver tests, era-aware aggregation rules, rules-variant overlay (§13.13.5), competition lifecycle FSM (§13.2), match-clock semantics (§13.46), purity-class taxonomy (§13.38), per-competition tiebreaker rule overlay (§13.52), qualifier-flow plane (§13.53), live bracket invariants (§13.57), and penalty-shootout schema (§13.58).
- [ ] `make test.leagues` is part of `make test` and is green on the smallest CI lane; `make test.leagues.adversarial` (per-league corpus §13.28) green per league before T1 promotion.
- [ ] `make leagues.audit.verify` green; signed audit ledger has zero unsigned or chain-broken entries; merkle-chain across compactions verified.
- [ ] DR drill (`make leagues.dr.rehearse`) executed at least once per the umbrella milestone with RTO/RPO honoured.
- [ ] Sandbox smoke (`make leagues.sandbox.smoke`) green on the smallest CI lane and metric-isolated (zero entries against any production-tier league metric); offline variant (`OFFLINE=1`) green per §13.49 storage-independent contract.
- [ ] **Multi-region catalog quorum drill** (`make chaos.catalog.region-drift`) executed at least once per the umbrella milestone; cross-region traffic shaping refused while drift open per §13.50.
- [ ] **Rolling-deployment catalog soak** (`make chaos.rolling.catalog`) green per §13.60 — half v_{N-1} / half v_N replicas serve traffic for the full window with zero crashes.
- [ ] **Predictions audit** (`make predictions.audit.verify ASOF=<utc>`) green over the umbrella's last 7-day window; tamper-detection drill (`make chaos.predictions.tamper`) detects within `cfg.predictions_tamper_detection_max_s` per §13.54.
- [ ] **Adaptive-scrape AIMD soak**: 24 h soak under simulated upstream 429 storm shows refill rate stays within `[cfg.scrape_min_rps, cfg.scrape_max_rps]` and never exceeds `robots.txt` crawl-delay (per §13.62).
- [ ] Wrong-assumption ledger (§13.0) has 80 retired entries, every one with at least one passing proof test in this phase (lint-gated by `xops/lint/phase13_ledger.py`).
- [ ] `project` umbrella version bumped on each of the three milestones (13a, 13b, 13c) per AGENTS.md §6.1.

---
