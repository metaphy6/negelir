"""
Phase 4 — Core Worker Agents.

This package hosts the SDK-driven agents that turn a `scrape.request`
into a normalized record in Postgres:

    scrape.request → scraper.<source>.v1 ─┐
                                          ├─→ scrape.raw → categorizer.v1
                                          │                       │
                                          │                       ▼
                                          │   scrape.classified → processor.<kind>.v1
                                          │                                │
                                          │                                ▼
                                          │   match.normalized → storage.v1
                                          │                              │
                                          │                              ▼
                                          │       match.stored → cache.v1
                                          │                              │
                                          └─────────── all topics ───────┴─→ telemetry.v1

Pivot v3 placement (post-R2):
  - scraper.<source>.v1, categorizer.v1, processor.<kind>.v1 → datasource/agents/
  - storage.v1, cache.v1, telemetry.v1, reactor.<name>.v1   → datasource/agents/ (storage),
                                                              swarm/agents/ (cache, reactors),
                                                              common/observability/ (telemetry)

For now, all live here under the transitional ai/ root; the package
namespace is shaped so the R2 move is `git mv` only.

Doctrine references: AGENTS.md §2 rules 1, 3, 6, 7;
design/DATA_PIPELINE.md (Record contract), design/CONTENT_FRESHNESS.md
(freshness events + reactor invariants).
"""
from __future__ import annotations
