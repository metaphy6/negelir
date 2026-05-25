# Phase 16.5 — Swarm migration to feeds (R3.4) + isolation gate

> Extracted from `docs/planning/ROADMAP.md` §16.5
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 16.5 Swarm migration to feeds (R3.4) + isolation gate

- [ ] **Migration order (binding):** (1) `pred.elo.v1` (cheapest, smallest input set), (2) `pred.poisson.v1`, (3) `pred.xg.v1`, (4) `pred.market.v1`, (5) `consensus.v1`, (6) drift agent, (7) proofreader replicas. Each step gates on (a) **field-equal Records and prediction-equal-within-1e-9** parity test (ledger #1) against the DB-reading version on **8 weeks** of mock history (byte-equal is impossible because canonical re-projection drops Postgres-side defaults), (b) telemetry showing `feed_reader_lag_ms_p99 < cfg.feed_reader_max_lag_ms` (default 2000) for 24 h on the mock stack, (c) shadow window of `cfg.swarm_feeds_shadow_hours` (default 48 h) where both the DB and Feed paths run side-by-side and agree.
- [ ] **Parity harness CLI.** `xops/feeds/parity.py --predictor pred.elo.v1 --window 8w --record-tolerance field_equal --prediction-tolerance 1e-9` runs both backends on the same fixture set and reports drift; exit non-zero on any mismatch. Wired into `make test.feeds.parity`.
- [ ] **Field-equal definition** is documented in `docs/runbooks/feeds_parity.md`: two Records are field-equal iff their canonical-encoded payloads + envelope (excluding `extractor_version`, `raw_ref`, `captured_at` jitter ≤ `cfg.feeds_parity_captured_at_jitter_ms`) hash equal under `common.feeds.canonical.encode_normalized`.
- [ ] `swarm/tests/test_no_db_imports.py` — AST scan: no file under `swarm/` imports `psycopg`, `psycopg2`, `asyncpg`, `redis`, `aioredis`, or `sqlalchemy`. **Cornerstone swarm-isolation test.**
- [ ] `swarm/tests/test_no_bus_data_topics.py` — no file under `swarm/` subscribes to `scrape.raw` or `match.normalized` (those carry feed-pointer envelopes post-§16.10; the actual data must be loaded via `FeedReader`).
- [ ] **`FeatureSource` Protocol Feed backend** (Phase 5 §5.6 deferred → here): `swarm/predictors/features/source.py` exports `FeatureSource(Protocol)`; `FeedFeatureSource` implementation joins `feeds/snapshots/score`, `feeds/snapshots/lineup`, `feeds/snapshots/schedule` by `match_stable_id`. Predictor `predict()` signature unchanged. Parity test against the in-memory backend on the Phase 5 fixture set.
- [ ] **`CalibrationStore` Feed backend** (Phase 5 §5.4 deferred → here): `swarm/predictors/calibration/feed_store.py` reads `feeds/snapshots/calibration/asof=<latest>/...`. Re-uses the Protocol from Phase 5 verbatim; constructor injection only.
