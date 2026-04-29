---
description: Python AI pipeline conventions (ai/**)
applyTo: 'ai/**/*.py'
---

# Python (`ai/**`) — stack-specific tips

Doctrine lives in [`AGENTS.md`](../../AGENTS.md). This file only adds
the Python-specific bits.

## Tests

- Tests live in `ai/tests/` (pytest). Never under a top-level `tests/`.
- Run with `PYTHONPATH=ai python3 -m pytest ai/tests/<file>.py -q`
  or `make test.ai`. Do **not** suggest `pip install` on the host
  (containers own dependencies — `AGENTS.md` Rule 2).
- Synthetic data goes in `ai/tests/fixtures.py` or
  `ai/tests/generate_test_data.py`. Production code never falls
  back to fake data (`AGENTS.md` Rule 3).
- New parser branches require a matching test
  (`AGENTS.md` Rule 7).
- **Rule 10 — tests track code.** Any change you make under
  `ai/**` must update `ai/tests/**` in the same diff: add tests
  for new surfaces, add a regression test for every bug fix,
  revise existing assertions when behaviour or signatures change.
  Never weaken or skip a test to make `make test.ai` green.
- Use `pytest.mark.parametrize` for table-style cases.

## Config & constants

- Tunables go through `ai/common/config.py` and
  `xops/env/.env.example`. No magic numbers, no hardcoded URLs.
- Locale strings (Turkish UX) live in `ai/common/locale_tr.yaml`
  and load via `ai/common/locale_loader.py`.
- League / season metadata: `ai/common/league_config.py` and
  `ai/common/season.py`.

## Logging & telemetry

- Use `ai/common/logger.py`; never `print` from production code.
- Metrics via `ai/common/telemetry.py`. Metric names in English
  (`AGENTS.md` Rule 6).

## Source-watcher discipline

- Classifier rules in `ai/swarm/source_watcher/classifier.py` are
  **deterministic** and LLM-free (`AGENTS.md` §5 / ROADMAP §2.8).
  Any LLM hook is narration only — it must not change rule outputs.

## Style

- Python 3.8+ compatible (stdlib preferred for tooling per
  `AGENTS.md` §6).
- Type hints on public surfaces; `from __future__ import annotations`
  at the top of new modules.
- No bare `except:`; no blanket `except Exception` that swallows.
