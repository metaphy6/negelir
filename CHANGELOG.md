# Changelog

All notable changes to the Negelir enrichment project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 21: Enrichment Planes Complete)

**Phase 21.27–21.31: Final enrichment infrastructure—reactor monitoring, REST query endpoints, cross-plane validation, observability, and end-to-end smoke tests.** Enrichment planes (roster, health, officials, environment) now transition to production readiness with automated watchdog monitoring, direct query APIs, consistency invariants, and Prometheus alerting. All four planes are integrated into predictions, tier-gated per subscription level, and validated through comprehensive smoke tests against a live stack.

Key additions:
- Derived-view reactor watchdog: monitors heartbeat keys, escalates stalls to Phase 8 maint supervisor.
- Four new REST endpoints: `/v1/enrichment/{roster,health,officials,environment}` with tier-gating and jurisdiction-awareness.
- Five cross-plane consistency invariants with auto-heal for suspension↔availability sync.
- Prometheus metrics and alert rules for all enrichment planes.
- End-to-end smoke test suite; excluded from fast test runs.

All 31 Phase 21 bullets are complete; enrichment_roster, enrichment_health, enrichment_officials, enrichment_environment components reach 1.0.0.

## [1.14.0] — 2026-06-20

(Previous release notes would be here)
