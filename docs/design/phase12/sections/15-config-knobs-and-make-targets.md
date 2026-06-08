# Phase 12.15 — Config knobs & make-target inventory

> Binding per-section detail for Phase 12 §12.15. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A2 (target naming), A11 (harness already exists).
> **Depends on:** all prior §12.x. Single-source-config (Rule 1):
> every knob below goes through `ai/common/config.py` +
> `xops/env/.env.example` and is covered by the triangle test.

### 12.15 New config knobs (single-source)

All Phase 12 tunables are documented here and land with their owning
section. No magic numbers in chaos/coverage code (Rule 1).

| Knob | Default | Owning § |
|---|---|---|
| `fault_injection_enabled` | `false` | §12.4 |
| `chaos_redis_flap_s` | `5` | §12.6 |
| `chaos_net_added_latency_ms` | `500` | §12.6 |
| `chaos_mttd_budget_ms` | `2000` | §12.14 |
| `chaos_trend_regression_pct` | `10.0` | §12.14 |
| `load_regression_tolerance` | `1.10` | §12.7 |
| `fuzz_nightly_budget_s` | `600` | §12.3 |
| `adversarial_corpus_max_added_rows_per_quarter` | `500` | §12.2 |
| `soak_resource_drift_pct` | `2.0` | §12.8 |
| `soak_report_max_age_days` | `30` | §12.8 |
| `dr_restore_max_min` | `30` | §12.11 |
| `coverage_mutation_min_score` | `0.80` | §12.12 |
| `coverage_mutation_budget_s` | `1800` | §12.12 |
| `coverage_pragma_max_per_module` | `5` | §12.12 |
| `ci_flake_quarantine_max_days` | `14` | §12.13 |
| `ci_flake_rate_threshold` | `0.01` | §12.13 |

- [x] Every knob has a `NEGELIR_*` mirror in `xops/env/.env.example`
      with a one-line doc, and the triangle test
      (`ai/tests/test_config_sync.py`) is extended to cover them.
- [ ] Go-side knobs (any consumed by the gateway load/chaos harness) are
      mirrored in `server/internal/config` and covered by the Go
      `TestEnvSync`, per the cross-language single-source doctrine.

### 12.15.1 Make-target inventory (dot-style, single source)

All targets are **dot-style** (§12.0 A2) and dispatch via
`xops/makefile/<module>.py` per AGENTS.md §5 (Make owns the graph,
Python owns the work). The chaos catalogue (§12.5) is the single source
of `chaos.*` names; this table is the operator-facing index.

| Target | Purpose | Dispatcher |
|---|---|---|
| `make test.adversarial` | adversarial layer (zero `xfail`) | `tests.py` |
| `make test.chaos.inproc` | in-process `FaultInjector` scenarios | `tests.py` |
| `make chaos.up` / `chaos.down` | chaos compose profile up/down | `chaos.py` |
| `make chaos.run TEST=<id>` | one catalogue scenario (realistic plane) | `chaos.py` |
| `make chaos.list` | print catalogue (single source) | `chaos.py` |
| `make chaos.<scenario>` | named drills (§12.6/§12.7/§12.9–§12.11) | `chaos.py` |
| `make chaos.scorecard` / `chaos.trend` | resilience report (§12.14) | `chaos.py` |
| `make fuzz.smoke` / `fuzz.api` / `fuzz.nlp` / `fuzz.wire` | property/coverage fuzz | `fuzz.py` |
| `make fuzz.corpus.min` | minimise corpus | `fuzz.py` |
| `make load.api` / `load.nlp` / `load.predictor` | latency-budget load (§12.7) | `bench.py` |
| `make soak.nightly` / `soak.weekly` / `soak.report` | endurance (§12.8) | `chaos.py` (`soak` subcmd) |
| `make coverage.report` / `coverage.diff` / `coverage.mutation` / `coverage.ratchet` / `coverage.regression-proof` | coverage+mutation (§12.12) | `coverage.py` |
| `make verify.adversarial-corpora` | corpus governance gate (§12.2) | `verify.py` |
| `make verify.chaos-catalogue` | catalogue integrity gate (§12.5) | `verify.py` |
| `make verify.integrity-coverage` | every integrity primitive has a tamper test (§12.9) | `verify.py` |
| `make ci.fast` / `ci.pr` / `ci.nightly` / `ci.weekly` | lane dispatchers (§12.13) | `tests.py` |

- [x] **New dispatchers** introduced by this phase:
      `xops/makefile/chaos.py`, `xops/makefile/fuzz.py`,
      `xops/makefile/coverage.py`, plus drivers under `xops/chaos/` and
      `ai/tests/fuzz/`. Each registers its commands in a `COMMANDS`
      dict per the xops convention; `make help` lists them.
- [ ] **New compose file** `docker-compose.chaos.yml` (Toxiproxy +
      Pumba, §12.4) and **new coverage config** (`.coveragerc` /
      `pyproject` `[tool.coverage]`, §12.12) — neither exists today
      (§12.0 A11).
- [x] A lint (`xops/lint/chaos_targets_dot_style.py`) rejects any
      hyphen-style `chaos-*` / `soak-*` target name re-introduced by a
      future PR.

### 12.15.2 Versioning

- [ ] Phase 12 work bumps `COMPONENT=docs` for design changes and, once
      implementation lands, `COMPONENT=xops` (new dispatchers/drivers)
      and `COMPONENT=ai` (fault seam, fuzz targets) per AGENTS.md §6.1,
      each in the same commit as the code + tracker row.
- [ ] Tool pins (Toxiproxy, Pumba, Atheris, mutmut image digests) land
      in `xops/versioning/chart.json` compatibility — **no `*-latest`**
      (CLAUDE.md).
