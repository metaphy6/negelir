# Phase 2: Synthetic Data Purge Report

Date: 2026-04-18

## 1. Scope

This report audits and remediates Phase 2 requirements from ROADMAP.md:

- Remove synthetic/fake data generation from production code paths.
- Fail loudly when real data is missing.
- Provide an executable bootstrap path (scrape -> validate -> train).
- Keep synthetic generators only under tests/.

## 2. Deep Audit Findings (Before Fixes)

### 2.1 Trainer path

Findings:
- `ai/model/trainer.py` had no fallback to generated data anymore, but it still lacked:
  - minimum required training match gate using config,
  - operator-grade error context (league, raw count, usable count, required count).

Risk:
- Training could fail late with generic errors.

### 2.2 Pipeline runner cache path

Findings:
- `ai/pipeline/runner.py::_load_cached_matches()` returned `[]` on missing/unreadable cache.
- Pipeline scrape step accepted this and continued, making failures non-actionable.

Risk:
- Silent data absence and ambiguous runtime behavior.

### 2.3 P2P simulation startup

Findings:
- `p2p/simulation/runner.py` had hardcoded fallback matches.
- Analysis rounds injected additional fabricated matchups when processed data was empty.

Risk:
- P2P validation could run without real data, violating Phase 2 objective.

### 2.4 Synthetic generator location

Findings:
- `generate_synthetic_dataset` existed in production module `ai/model/features.py`.
- Tests imported this production symbol directly.

Risk:
- Production namespace contained test-only generators.

### 2.5 Operational path / bootstrap

Findings:
- Makefile had no `scrape`, `bootstrap`, or strict `train` precheck targets.
- Failure messages referenced scrape/bootstrap behavior not fully available in commands.
- No CI workflow enforced bootstrap before training.

Risk:
- First-run operator flow was incomplete.

## 3. Ordered Remediation Roadmap (Applied)

### Step 1: Harden trainer and extraction failures

- Add strict min-match gate (`cfg.training_min_matches`, default 100).
- Add actionable errors with league id and counts.
- Pass preloaded raw matches into extraction to keep counts deterministic.

### Step 2: Harden pipeline cache loading

- Make `_load_cached_matches()` return data or raise runtime error.
- Propagate error via `TaskResult(success=False, error=...)`.
- Include remediation commands in error text.

### Step 3: Remove P2P synthetic fallback behavior

- Remove hardcoded fallback match dict.
- Remove additional fabricated matchups in analysis rounds.
- Add startup gate requiring real cached matches and minimum count.

### Step 4: Quarantine synthetic generation under tests

- Remove generator from `ai/model/features.py`.
- Create `ai/tests/fixtures.py` as test-only synthetic data source.
- Update tests to import fixture generator from tests package.

### Step 5: Add executable bootstrap flow

- Add Make targets: `scrape`, `bootstrap`, `train`.
- Add validator CLI (`python -m proofreader.validator --input ... --min-matches ...`).
- Extend scraper CLI with `--league` and output path composition.

### Step 6: Add CI bootstrap gate

- Add workflow `.github/workflows/phase2-real-data-bootstrap.yml`:
  - install deps,
  - bootstrap real cache,
  - validate cache,
  - run train smoke test.

## 4. Applied Changes

### 4.1 Trainer / extraction

- `ai/model/trainer.py`
  - Enforced `cfg.training_min_matches` gate.
  - Added rich RuntimeError messages with league/raw/usable/required counts.

- `ai/model/real_features.py`
  - `extract_real_dataset(min_history=5, matches=None)` now accepts preloaded matches.
  - Cache path parameterized with `cfg.data_dir` + `cfg.default_league_id`.
  - Improved no-data / insufficient-history errors with remediation commands.

### 4.2 Pipeline runner

- `ai/pipeline/runner.py`
  - `_step_scrape()` now fails cleanly when cache load fails.
  - `_load_cached_matches()` now raises on missing/empty/broken cache.

### 4.3 P2P simulation

- `p2p/config.py`
  - Added `data_dir`, `default_league_id`, `simulation_min_real_matches`.

- `p2p/simulation/runner.py`
  - Removed hardcoded fallback match payloads.
  - Added `_require_real_matches()` startup gate.
  - Removed fabricated extra match rounds.
  - Added clear remediation text in errors.

### 4.4 Synthetic generator quarantine

- `ai/model/features.py`
  - Removed `generate_synthetic_dataset` from production module.
  - Kept runtime-safe helpers only (`inject_noise`, `extract_features_for_match`).

- `ai/tests/fixtures.py`
  - Added test-only `generate_synthetic_dataset`.

- `ai/tests/test_unit.py`
  - Updated synthetic dataset imports to test fixtures.
  - Stabilized incremental retrain test by mocking real-data extraction.

- `ai/tests/generate_test_data.py`
  - Added deterministic test fixture generator CLI.

### 4.5 Operator and CI wiring

- `Makefile`
  - Added `scrape`, `bootstrap`, `train` targets.
  - `ai-train` now aliases strict real-data `train` target.

- `ai/proofreader/validator.py`
  - Added CLI entrypoint for dataset validation and minimum match gate.

- `ai/scraper/real_data.py`
  - Added `--league` and `--seasons` CLI args, league-based output path.

- `.github/workflows/phase2-real-data-bootstrap.yml`
  - Added bootstrap-before-train CI workflow.

## 5. Strict Verification and Debug Evidence

## 5.1 Production grep gate

Command:

```bash
grep -RInE "synthetic|generate_synthetic|fake|generated[[:space:]]*[:=].*true" ai p2p --include='*.py' --exclude-dir=tests
```

Result:
- No matches in production paths.

## 5.2 First-run training guardrail

Command:

```bash
make train
```

Result:
- Fails fast with actionable message:
  - `Missing data/super_lig_real.json. Run 'make bootstrap LEAGUE=super_lig' first.`

## 5.3 Pipeline cache guardrail

Command (snippet):

```bash
python - <<'PY'
from pipeline.runner import PipelineRunner
try:
    PipelineRunner()._load_cached_matches()
except Exception as e:
    print(e)
PY
```

Result:
- Raises actionable runtime error including scrape/bootstrap commands.

## 5.4 P2P startup guardrail

Command (snippet):

```bash
python - <<'PY'
from simulation.runner import P2PSimulation
try:
    P2PSimulation().run()
except Exception as e:
    print(e)
PY
```

Result:
- Raises:
  - `P2P simulation requires real data ... found=0, required>=10 ...`
  - includes scrape/bootstrap instructions.

## 5.5 Full test suites

- AI:
  - `384 passed, 7 deselected`
- P2P:
  - `96 passed`

## 6. Phase 2 Completion Matrix

| Requirement | Status | Evidence |
|---|---|---|
| Zero synthetic in production paths | Complete | production grep gate returned no hits |
| Training fails without real data | Complete | `make train` fails fast with bootstrap instruction |
| P2P sim fails without real data | Complete | `P2PSimulation().run()` fails with actionable instruction |
| Bootstrap path exists | Complete | `make bootstrap` target added (`scrape` + `validator`) |
| Synthetic generator isolated to tests | Complete | moved to `ai/tests/fixtures.py` |
| CI includes bootstrap before train | Complete | workflow `phase2-real-data-bootstrap.yml` |

## 7. Notes and Residual Constraints

- `make` uses variable overrides (`LEAGUE=...`) rather than GNU option style `--league=...`.
  - Equivalent usage:
    - `make bootstrap LEAGUE=en_premier_league`
    - `make scrape LEAGUE=en_premier_league`
- Live bootstrap is now verified for all currently configured leagues (`tr_super_lig`, `en_premier_league`, `de_bundesliga`, `es_la_liga`).
- Adding new leagues still requires source mapping entries in `ai/common/league_config.py` (`openfootball_path`, `footballdata_country`).

## 8. Second Evidence Section: True End-to-End Live Bootstrap (All Available Leagues)

Run timestamp (UTC): `2026-04-18T17:22:54Z`

Evidence artifact:
- `docs/data/PHASE2_LIVE_BOOTSTRAP_RESULTS.json`

League-by-league results:

| League | Output file | File size (MB) | Match count | Seasons | Validation summary | Exit codes |
|---|---|---:|---:|---:|---|---|
| `de_bundesliga` | `data/de_bundesliga_real.json` | 0.434 | 1449 | 5 | total=1449, quarantined=4, quarantine_rate=0.3%, warnings=1, errors=4 | scrape=0, validate=0 |
| `en_premier_league` | `data/en_premier_league_real.json` | 0.542 | 1811 | 5 | total=1811, quarantined=3, quarantine_rate=0.2%, warnings=0, errors=3 | scrape=0, validate=0 |
| `es_la_liga` | `data/es_la_liga_real.json` | 0.526 | 1780 | 5 | total=1780, quarantined=1, quarantine_rate=0.1%, warnings=1, errors=1 | scrape=0, validate=0 |
| `tr_super_lig` | `data/tr_super_lig_real.json` | 0.430 | 1469 | 5 | total=1469, quarantined=0, quarantine_rate=0.0%, warnings=0, errors=0 | scrape=0, validate=0 |

Aggregate metrics from live run:
- Total leagues bootstrapped: 4
- Total real matches scraped: 6509
- Total output size: 2,025,444 bytes (1.932 MB)
- Total runtime: scrape=374.58s, validate=2.82s
- Overall quarantine count: 8 matches (8/6509 = 0.12%)

Conclusion:
- The requested true end-to-end live bootstrap path (`scrape -> validate`) has been executed successfully on every currently available league id in the registry.
