# Negelir AI Engine

## Overview

AI engine that analyzes Turkish football matches and produces Turkish-language responses to user questions.

## Modules

### TQU (Turkish Question Understanding)
Module that understands and classifies Turkish football questions.
- 10 intent types: `match_winner`, `draw`, `over_under`, `goal_range`, `both_teams_score`, `clean_sheet`, `half_time`, `form_query`, `head_to_head`, `score_predict`
- Input sanitization: injection prevention, Turkish character normalization
- Confidence threshold: 0.60

### TRC (Turkish Response Composer)
Module that transforms model outputs into Turkish responses.
- 7 verdict types: `strong_yes`, `likely_yes`, `uncertain`, `balanced`, `likely_no`, `strong_no`, `low_data`
- Template-based response generation
- Banned word filter (gambling/betting terminology)
- Maximum 500 characters

### Model (GBDT)
XGBoost gradient boosted decision tree model.
- 130 feature columns (form, Elo, H2H, league position, squad, context, temporal, sentiment, derived, weather, QID)
- GPU support (target RTX 4080, CUDA `gpu_hist`)
- CPU fallback (`hist`)
- Trained on real scraped data only — no synthetic data in production

### Scraper
Module for fetching data via the Go middleware server.
- Anonymous source configuration (CSS selectors)
- Rate limiting (5 seconds/request/domain)
- Health check

### NLP
Turkish sentiment analysis module.
- Rule-based sentiment (positive/negative word lists)
- Injection detection
- Batch analysis (max 50 texts/batch)

### Orchestrator
State machine-based pipeline manager.
- States: IDLE → SCRAPING → PROCESSING → PROOFREADING → RESPONDING → VALIDATING

### Proofreader
Data validation and quarantine module.
- Range checks (probability 0-1, goals 0-20)
- Consistency checks (total possession ≈ 100%, HT ≤ FT)
- Plausibility checks (total goals ≥ 10 → suspicious)

## Demo Mode

```bash
# With Docker
make ai-demo

# Direct execution
cd ai && python -m pipeline.runner
```

Runs full pipeline with 11 hardcoded Turkish questions:
1. "Who wins the Galatasaray - Fenerbahçe match?" (match_winner)
2. "Does Beşiktaş - Trabzonspor end in a draw?" (draw)
3. "Will there be over 2.5 goals in this match?" (over_under)
4. "How many goals will be scored?" (goal_range)
5. "Will both teams score?" (both_teams_score)
6. "Will Başakşehir keep a clean sheet?" (clean_sheet)
7. "What will the first half result be?" (half_time)
8. "How is Galatasaray's recent form?" (form_query)
9. "What are the head-to-head stats?" (head_to_head)
10. "What's the weather today?" (non-football → rejected)
11. `'; DROP TABLE teams; --` (injection → rejected)
