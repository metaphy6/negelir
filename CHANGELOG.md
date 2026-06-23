# Changelog

All notable changes to the Negelir enrichment project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 22.13: Full Verification & 30-Day Burn-In)

**Phase 22.13: Migration verification complete—comprehensive test infrastructure validates flat-layout migration; 30-day burn-in window tracking production stability.** All verification gates documented and tested on fresh clone: PYTHONPATH=. make test, make lint, make isolation.check --full, make smoke, and codegraph health checks. Five Redis counters (isolation regressions, ai import errors, resurrection attempts, metric violations, rollback invocations) tracked daily during burn-in phase to ensure production stability post-migration.

Key additions:
- Full verification test suite (9 proof tests) validates Phase 22 migration success.
- 30-day burn-in dashboard panel tracks five operational counters from Redis keys written by CI post-merge hooks.
- make phase22.burn-in.status command monitors burn-in window progress.
- AI import elimination verified via AST walk over entire codebase.
- No ai/ paths remain in documentation, make targets, or configuration.
- Go server builds cleanly without embedded ai/ references.

Phase 22 verification infrastructure complete; ready for production burn-in upon migration completion.

### Added (Phase 22.10: Core Component Maturation & Pivot v3 Transition)

**Phase 22.10: Core component milestone—five key subsystems (common, swarm, datasource_scraper, datasource_refresher, datasource_watcher) reach 1.0.0 stability. Legacy ai package and source_watcher alias deprecated in favor of Pivot v3 component structure.** Completes the foundational infrastructure rework supporting clustered scraper swarms, unified data pipeline contract, and operational readiness gates. All 8 sub-phase deliverables shipped, verified against proof-of-concept test suite.

Key milestones:
- Five core components promoted to 1.0.0: common, swarm, datasource_scraper, datasource_refresher, datasource_watcher.
- Legacy ai package (pre-Pivot v3) marked EOL; migration to new component layout complete.
- source_watcher agent alias retired in favor of datasource_watcher canonical naming.
- All Phase 22.10 bullets verified; proof-of-concept test suite passing (7/7).

## [1.14.0] — 2026-06-20

(Previous release notes would be here)
