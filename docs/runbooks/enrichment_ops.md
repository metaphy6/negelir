# Enrichment Operational Runbook

## Overview

Phase 21 enrichment planes (roster, health, officials, environment) require constant monitoring. This runbook covers all alert scenarios and remediation steps.

## Alert Rules

### EnrichmentPlaneScrapeErrorRate
- **Condition**: >20% scrape errors over 10 minutes
- **Severity**: warning
- **First Response**:
  1. Check upstream service status
  2. Review extractor logs: `make logs.enrichment PLANE=<plane>`
  3. Verify network connectivity
- **Escalation**: If persistent, restart scraper: `docker compose restart enrichment-scraper`

### EnrichmentPlaneStale
- **Condition**: No fresh data for >1 hour
- **Severity**: warning
- **First Response**:
  1. Check if upstream source is available
  2. Verify API credentials are valid
  3. Check HTTP request timeouts

### EnrichmentCircuitBreakerOpen
- **Condition**: Circuit breaker in open state for >2 minutes
- **Severity**: critical
- **First Response**:
  1. Investigate root cause in extractor logs
  2. Verify downstream storage (Postgres) health
  3. Allow cooldown period for automatic recovery (5min default)

### EnrichmentDLQDepthHigh
- **Condition**: >100 events in DLQ
- **Severity**: warning
- **First Response**:
  1. Investigate DLQ events: `make enrichment.dlq.inspect`
  2. Address underlying storage/feed issues
  3. Phase 8 supervisor will auto-drain over time

### EnrichmentReactorStalled
- **Condition**: Derived-view reactor not run in >2 minutes
- **Severity**: critical
- **First Response**:
  1. Check reactor logs for hang/crash
  2. Verify upstream event bus has messages
  3. Restart reactor: `make enrichment.reactor.restart VIEW=<view>`

### EnrichmentCacheHitRateLow
- **Condition**: <70% hit rate over 10 minutes
- **Severity**: warning
- **First Response**:
  1. Monitor Redis memory usage
  2. Check for Redis connectivity issues
  3. Consider increasing cache TTL

## Post-Incident Checklist

- [ ] Update RCA in ticket
- [ ] Review logs for data corruption
- [ ] Verify consistency invariants passed (§21.29)
- [ ] Run smoke test: `make smoke.enrichment`
