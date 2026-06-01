# `docs/design/phase13/` — Phase 13 detail

> **Why this folder exists.** Phase 13 (League + Competition Expansion (split into 13a / 13b / 13c)) grew
> past ROADMAP's review threshold and was carved out into one file
> per sub-section, mirroring the Phase 10 pattern at
> [`../phase10/sections/`](../phase10/sections/). Content here is **binding**
> — the ROADMAP §13 stub is now a pointer that delegates to this
> folder.
>
> **Editing rules.**
> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in
>    the per-section file that owns the item. The ROADMAP §13
>    stub carries only the phase-rollup checkbox.
> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs
>    LEVEL=minor NOTE="..."` in the same commit (per AGENTS.md §6.1).
> 3. Cross-phase references are authoritative against
>    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the
>    matching `docs/design/*.md` anchors. Fix this folder if a claim
>    drifts — never silently re-plan a sister phase.
> 4. No rename of these files without explicit human request (URL
>    stability); no deletion of a binding `[ ]` item; no weakening
>    of a Definition-of-Done gate.

## Layout

| Source | File | Theme |
|---|---|---|
| §13.0 | [`sections/00-wrong-assumption-ledger.md`](sections/00-wrong-assumption-ledger.md) | Wrong-assumption ledger (retired by this phase) |
| §13.1 | [`sections/01-catalog-schema-authority.md`](sections/01-catalog-schema-authority.md) | Catalog & schema authority (one-time platform work; ships with 13a) |
| §13.2 | [`sections/02-competition-platform-competitionconfig-fixturepayloadv2-calibrationprofile.md`](sections/02-competition-platform-competitionconfig-fixturepayloadv2-calibrationprofile.md) | Competition platform — `CompetitionConfig`, `FixturePayloadV2`, `CalibrationProfile` |
| §13.3 | [`sections/03-per-league-preset-discipline-scaffolding.md`](sections/03-per-league-preset-discipline-scaffolding.md) | Per-league preset discipline + scaffolding |
| §13.4 | [`sections/04-cross-competition-identity-resolution.md`](sections/04-cross-competition-identity-resolution.md) | Cross-competition identity resolution (the Galatasaray problem) |
| §13.5 | [`sections/05-calibration-backfill-per-format-backtest-harness.md`](sections/05-calibration-backfill-per-format-backtest-harness.md) | Calibration backfill & per-format backtest harness |
| §13.6 | [`sections/06-mock-stack-source-coverage-onboarding.md`](sections/06-mock-stack-source-coverage-onboarding.md) | Mock-stack & source-coverage onboarding |
| §13.7 | [`sections/07-tier-promotion-gate.md`](sections/07-tier-promotion-gate.md) | Tier promotion gate (`xops/leagues/readiness.py`) |
| §13.8 | [`sections/08-demotion-post-promotion-watchdog.md`](sections/08-demotion-post-promotion-watchdog.md) | Demotion + post-promotion watchdog |
| §13.9 | [`sections/09-performance-efficiency-footprint.md`](sections/09-performance-efficiency-footprint.md) | Performance, efficiency, & footprint |
| §13.10 | [`sections/10-per-league-observability-slos.md`](sections/10-per-league-observability-slos.md) | Per-league observability & SLOs |
| §13.11 | [`sections/11-nlp-competition-gazetteer-q-a-intents.md`](sections/11-nlp-competition-gazetteer-q-a-intents.md) | NLP + competition gazetteer + Q&A intents (cross-cutting; ships per league with 13a/b/c) |
| §13.12 | [`sections/12-two-leg-tie-reactor-idempotency.md`](sections/12-two-leg-tie-reactor-idempotency.md) | Two-leg tie reactor & idempotency |
| §13.13 | [`sections/13-era-aware-rules-friendly-exclusion-enforcement.md`](sections/13-era-aware-rules-friendly-exclusion-enforcement.md) | Era-aware rules & friendly-exclusion enforcement |
| §13.14 | [`sections/14-international-squad-national-team-plane-integration.md`](sections/14-international-squad-national-team-plane-integration.md) | International squad / national-team plane integration (13a foundation; expanded 13c) |
| §13.15 | [`sections/15-reactor-isolation-per-league-startup-quarantine.md`](sections/15-reactor-isolation-per-league-startup-quarantine.md) | Reactor isolation & per-league startup quarantine |
| §13.17 | [`sections/17-fixture-lifecycle.md`](sections/17-fixture-lifecycle.md) | Fixture lifecycle (postpone / abandon / replay / awarded) |
| §13.18 | [`sections/18-mid-season-format-structure-mutation.md`](sections/18-mid-season-format-structure-mutation.md) | Mid-season format/structure mutation |
| §13.19 | [`sections/19-promotion-relegation-season-rollover.md`](sections/19-promotion-relegation-season-rollover.md) | Promotion / relegation & season rollover |
| §13.20 | [`sections/20-time-zone-scheduling-correctness-dst.md`](sections/20-time-zone-scheduling-correctness-dst.md) | Time zone, scheduling correctness, DST |
| §13.21 | [`sections/21-catalog-audit-log-cryptographic-signing.md`](sections/21-catalog-audit-log-cryptographic-signing.md) | Catalog audit log + cryptographic signing |
| §13.22 | [`sections/22-disaster-recovery-per-league-backup-restore.md`](sections/22-disaster-recovery-per-league-backup-restore.md) | Disaster recovery: per-league backup / restore |
| §13.23 | [`sections/23-fairness-bias-detection.md`](sections/23-fairness-bias-detection.md) | Fairness & bias detection |
| §13.24 | [`sections/24-data-residency-gdpr-kvkk-ccpa-per-league-country.md`](sections/24-data-residency-gdpr-kvkk-ccpa-per-league-country.md) | Data residency, GDPR / KVKK / CCPA per league country |
| §13.25 | [`sections/25-source-supply-chain-trust.md`](sections/25-source-supply-chain-trust.md) | Source supply-chain trust |
| §13.26 | [`sections/26-catalog-concurrency-atomic-two-phase-reload.md`](sections/26-catalog-concurrency-atomic-two-phase-reload.md) | Catalog concurrency & atomic two-phase reload |
| §13.27 | [`sections/27-backwards-compat-deprecation-policy.md`](sections/27-backwards-compat-deprecation-policy.md) | Backwards-compat & deprecation policy |
| §13.28 | [`sections/28-per-league-red-team-adversarial-corpus.md`](sections/28-per-league-red-team-adversarial-corpus.md) | Per-league red-team & adversarial corpus |
| §13.29 | [`sections/29-match-officials-registry.md`](sections/29-match-officials-registry.md) | Match-officials registry |
| §13.30 | [`sections/30-player-transfer-loan-plane.md`](sections/30-player-transfer-loan-plane.md) | Player transfer & loan plane |
| §13.31 | [`sections/31-weather-plane.md`](sections/31-weather-plane.md) | Weather plane |
| §13.32 | [`sections/32-suspension-card-accumulation-tracker.md`](sections/32-suspension-card-accumulation-tracker.md) | Suspension & card-accumulation tracker |
| §13.33 | [`sections/33-crowd-state-plane.md`](sections/33-crowd-state-plane.md) | Crowd-state plane |
| §13.34 | [`sections/34-per-league-predictor-warm-up.md`](sections/34-per-league-predictor-warm-up.md) | Per-league predictor warm-up |
| §13.35 | [`sections/35-federation-catalog-drift-watcher.md`](sections/35-federation-catalog-drift-watcher.md) | Federation-catalog drift watcher |
| §13.36 | [`sections/36-source-attribution-field-provenance-plane.md`](sections/36-source-attribution-field-provenance-plane.md) | Source-attribution & field-provenance plane |
| §13.37 | [`sections/37-currency-tax-sku-localisation.md`](sections/37-currency-tax-sku-localisation.md) | Currency, tax & SKU localisation |
| §13.38 | [`sections/38-competition-purity-filter.md`](sections/38-competition-purity-filter.md) | Competition-purity filter |
| §13.39 | [`sections/39-match-integrity-flag-plane.md`](sections/39-match-integrity-flag-plane.md) | Match-integrity flag plane |
| §13.40 | [`sections/40-cascade-postponement-withdrawal-reactor.md`](sections/40-cascade-postponement-withdrawal-reactor.md) | Cascade-postponement & withdrawal reactor |
| §13.41 | [`sections/41-league-rebrand-display-name-handover.md`](sections/41-league-rebrand-display-name-handover.md) | League rebrand & display-name handover |
| §13.42 | [`sections/42-catalog-time-travel-queries.md`](sections/42-catalog-time-travel-queries.md) | Catalog time-travel queries |
| §13.43 | [`sections/43-sandbox-league-lane.md`](sections/43-sandbox-league-lane.md) | Sandbox-league lane |
| §13.44 | [`sections/44-coefficient-derivation-plane.md`](sections/44-coefficient-derivation-plane.md) | Coefficient-derivation plane |
| §13.45 | [`sections/45-per-league-market-roster.md`](sections/45-per-league-market-roster.md) | Per-league market roster |
| §13.46 | [`sections/46-match-clock-semantics.md`](sections/46-match-clock-semantics.md) | Match-clock semantics |
| §13.47 | [`sections/47-data-portability-export.md`](sections/47-data-portability-export.md) | Data-portability export (GDPR Art 20 / KVKK) |
| §13.48 | [`sections/48-adversarial-corpus-rotation-growth-bound.md`](sections/48-adversarial-corpus-rotation-growth-bound.md) | Adversarial-corpus rotation & growth bound |
| §13.49 | [`sections/49-storage-independent-cold-start.md`](sections/49-storage-independent-cold-start.md) | Storage-independent cold-start |
| §13.50 | [`sections/50-multi-region-catalog-consistency.md`](sections/50-multi-region-catalog-consistency.md) | Multi-region catalog consistency |
| §13.51 | [`sections/51-tbd-opponent-placeholder-fixtures.md`](sections/51-tbd-opponent-placeholder-fixtures.md) | TBD-opponent placeholder fixtures |
| §13.52 | [`sections/52-per-competition-tiebreaker-rule-overlay.md`](sections/52-per-competition-tiebreaker-rule-overlay.md) | Per-competition tiebreaker rule overlay |
| §13.53 | [`sections/53-cross-competition-qualifier-flow-plane.md`](sections/53-cross-competition-qualifier-flow-plane.md) | Cross-competition qualifier-flow plane |
| §13.54 | [`sections/54-prediction-integrity-signed-envelopes.md`](sections/54-prediction-integrity-signed-envelopes.md) | Prediction integrity & signed envelopes |
| §13.55 | [`sections/55-per-league-per-source-scrape-budget.md`](sections/55-per-league-per-source-scrape-budget.md) | Per-league × per-source scrape budget |
| §13.56 | [`sections/56-per-season-market-roster-overlay.md`](sections/56-per-season-market-roster-overlay.md) | Per-season market roster overlay |
| §13.57 | [`sections/57-live-bracket-invariant-prover.md`](sections/57-live-bracket-invariant-prover.md) | Live bracket invariant prover |
| §13.58 | [`sections/58-penalty-shootout-plane.md`](sections/58-penalty-shootout-plane.md) | Penalty-shootout plane |
| §13.59 | [`sections/59-guest-team-membership-plane.md`](sections/59-guest-team-membership-plane.md) | Guest-team membership plane |
| §13.60 | [`sections/60-forward-backward-catalog-compatibility-rolling-deployment.md`](sections/60-forward-backward-catalog-compatibility-rolling-deployment.md) | Forward + backward catalog compatibility & rolling deployment |
| §13.61 | [`sections/61-per-league-canary-deployment.md`](sections/61-per-league-canary-deployment.md) | Per-league canary deployment |
| §13.62 | [`sections/62-adaptive-scrape-rate-limit.md`](sections/62-adaptive-scrape-rate-limit.md) | Adaptive scrape rate-limit |
| §13.63 | [`sections/63-per-league-calibration-mutation-audit.md`](sections/63-per-league-calibration-mutation-audit.md) | Per-league calibration mutation audit |
| §13.64 | [`sections/64-catalog-uniqueness-constraints.md`](sections/64-catalog-uniqueness-constraints.md) | Catalog uniqueness constraints |
| §13.65 | [`sections/65-cross-competition-prediction-consistency-oracle.md`](sections/65-cross-competition-prediction-consistency-oracle.md) | Cross-competition prediction-consistency oracle |
| §13.66 | [`sections/66-demotion-cascade-safety-prediction-revocation.md`](sections/66-demotion-cascade-safety-prediction-revocation.md) | Demotion-cascade safety + prediction revocation |
| §13.67 | [`sections/67-market-line-anomaly-detector.md`](sections/67-market-line-anomaly-detector.md) | Market-line anomaly detector |
| §13.68 | [`sections/68-catalog-driven-metric-label-lifecycle.md`](sections/68-catalog-driven-metric-label-lifecycle.md) | Catalog-driven metric label lifecycle |
| §13.16 | [`sections/16-cross-phase-coupling-matrix.md`](sections/16-cross-phase-coupling-matrix.md) | Cross-phase coupling matrix (closing audit; lint-gated) |

## Reading order

1. The ROADMAP §13 stub (`docs/planning/ROADMAP.md`) — goal,
   dependencies, and rollup checkbox.
2. The earliest section file relevant to the area you're modifying.
   Later sub-sections often assume earlier ones are in force; if a
   later file's `Depends on` clause names another sub-section,
   re-read it first.
3. The Definition-of-Done sub-section (the one whose title contains
   *Definition of Done* or matching `DoD` rollup) — this is the
   gate that flips the rollup checkbox in ROADMAP.
