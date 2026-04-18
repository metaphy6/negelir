# Phase 2 Live Bootstrap Evidence (All Available Leagues)

Date: 2026-04-18
Generated at (UTC): 2026-04-18T17:22:54Z

## 1. Scope

This document records a real end-to-end bootstrap run for all currently available league ids in the registry.

Bootstrap flow executed per league:
- scrape real matches into a league-specific JSON cache
- validate scraped matches with proofreader validator

## 2. Coverage

Leagues covered in this run:
- de_bundesliga
- en_premier_league
- es_la_liga
- tr_super_lig

## 3. Command Pattern Used

```bash
cd ai
python -m scraper.real_data --league <league_id> --seasons 5 --output ../data/<league_id>_real.json
python -m proofreader.validator --input ../data/<league_id>_real.json --min-matches 100
```

## 4. League-by-League Evidence

| League | Output file | Size (MB) | Matches | Seasons | Scrape sec | Validate sec | Validation summary | Exit codes |
|---|---|---:|---:|---:|---:|---:|---|---|
| de_bundesliga | data/de_bundesliga_real.json | 0.434 | 1449 | 5 | 96.70 | 0.63 | total=1449, quarantined=4, quarantine_rate=0.3%, warnings=1, errors=4 | scrape=0, validate=0 |
| en_premier_league | data/en_premier_league_real.json | 0.542 | 1811 | 5 | 91.34 | 0.77 | total=1811, quarantined=3, quarantine_rate=0.2%, warnings=0, errors=3 | scrape=0, validate=0 |
| es_la_liga | data/es_la_liga_real.json | 0.526 | 1780 | 5 | 91.10 | 0.74 | total=1780, quarantined=1, quarantine_rate=0.1%, warnings=1, errors=1 | scrape=0, validate=0 |
| tr_super_lig | data/tr_super_lig_real.json | 0.430 | 1469 | 5 | 95.44 | 0.68 | total=1469, quarantined=0, quarantine_rate=0.0%, warnings=0, errors=0 | scrape=0, validate=0 |

## 5. Aggregate Outcomes

- Total leagues: 4
- Total matches: 6509
- Total output bytes: 2,025,444 bytes
- Total output size: 1.932 MB
- Total scrape time: 374.58 sec
- Total validation time: 2.82 sec
- Total quarantined matches: 8
- Overall quarantine rate: 0.12%

## 6. Artifacts

Primary machine-readable artifact:
- docs/data/PHASE2_LIVE_BOOTSTRAP_RESULTS.json

Human-readable report updates:
- docs/data/PHASE2_SYNTHETIC_DATA_PURGE_REPORT.md (Section 8)
- docs/data/PHASE2_LIVE_BOOTSTRAP_EVIDENCE.md (this file)