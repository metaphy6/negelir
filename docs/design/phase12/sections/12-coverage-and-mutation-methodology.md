# Phase 12.12 — Coverage & mutation methodology

> Binding per-section detail for Phase 12 §12.12. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A1 (flat ≥ 85 % line coverage is sufficient), A11
> (coverage tooling already exists). **Depends on:** §12.1.

### 12.12 "Covered" must mean "asserted", and criticality must weigh

The original stub's "per-package line coverage ≥ 85 %" is criticality-
blind and gameable (a line is "covered" by executing it, even with no
assertion). Phase 12 replaces it with a **tiered, asserted, diff-aware**
model.

### 12.12.1 Tiered coverage targets

- [x] **Tier-1 (security / integrity / money / consensus).** Modules
      under `ai/swarm/agents/sec/`, `server/internal/sec/`,
      `server/internal/auth/`, `*/crypto/`, consensus
      (`ai/swarm/agents/predictors/` fusion), opsctl, backup, citation/
      HMAC paths: **≥ 95 % line AND ≥ 90 % branch**, plus **mutation
      score ≥ `cfg.coverage_mutation_min_score`** (default 0.80) on a
      curated module set.
- [x] **Tier-2 (ordinary business logic).** ≥ 85 % line. No mutation
      requirement, but diff-coverage (§12.12.3) still applies.
- [x] **Tier-3 (glue / generated / tooling).** No hard floor; excluded
      from the gate by an explicit allow-list (`xops/lint/coverage_tiers.py`)
      so the tier map is reviewed, not silently widened.
- [x] The tier map is a **single-source file** (`xops/coverage/tiers.yaml`)
      consumed by the gate; adding a module to a lower tier requires a
      reviewer ack (no silent down-tiering of a security path).

### 12.12.2 Branch coverage, not just line

- [x] Python coverage runs with `--branch` (a new `.coveragerc` /
      `pyproject` `[tool.coverage]` block — none exists today, §12.0
      A11); Go uses `go test -covermode=atomic`. The Tier-1 gate asserts
      **branch** coverage so an un-taken `else` on a security check is a
      gap, not a pass.

### 12.12.3 Diff-coverage gate (the per-PR enforcer of Rule 10)

- [x] **Every PR's changed lines** meet their tier floor
      (`make coverage.diff` compares against the merge-base). A PR that
      adds a public surface with no covering test **fails** — this is
      the mechanical enforcement of AGENTS.md Rule 10 ("tests track
      code, always").
- [x] A bug-fix PR must add a line that was **red before** the fix
      (regression-test presence is checkable: the new test must fail on
      the pre-fix tree). `make coverage.regression-proof` runs the new
      test against the reverted fix in CI and asserts it fails.

### 12.12.4 Mutation testing (covered ⇒ asserted)

- [x] **`mutmut` (Python) / `go-mutesting`-class (Go)** run nightly on
      the Tier-1 module set; a surviving mutant (a code change no test
      catches) below the threshold fails the nightly gate and lists the
      survivors as artifacts.
- [x] Mutation is **scoped + budgeted** (Tier-1 only, time-boxed
      `cfg.coverage_mutation_budget_s`) so it stays runnable; it is a
      nightly lane, never per-push (§12.13).
- [x] A survived mutant on a security/integrity assertion is treated as
      a §12.14 finding, not a metric footnote.

### 12.12.5 Anti-gaming guards

- [x] **No assertion-free tests.** A lint
      (`xops/lint/no_assertionless_test.py`) flags a test function with
      zero `assert` / `require` that nonetheless adds coverage — the
      classic "import to inflate coverage" trick.
- [x] **No coverage-pragma abuse.** `# pragma: no cover` /
      `//coverage:ignore` require an inline justification and are
      counted; a budget cap (`cfg.coverage_pragma_max_per_module`)
      prevents silently excluding hard paths. Lint: `xops/lint/coverage_pragma_budget.py`.
- [x] **Coverage cannot fall.** A ratchet (`make coverage.ratchet`)
      forbids a PR from lowering a module's coverage below its last
      landed value without an explicit reviewer ack (defeats slow
      erosion). Implemented in `xops/makefile/coverage.py` cmd_ratchet().

### 12.12.6 Make targets

- [x] `make coverage.report` (line+branch, HTML+JSON artifact),
      `make coverage.diff` (PR gate), `make coverage.regression-proof`,
      `make coverage.mutation` (nightly), `make coverage.ratchet` —
      dispatched via a new `xops/makefile/coverage.py`.
- [x] Coverage config + tier map land under single-source config
      (§12.15); the §12.17 DoD requires the Tier-1 gate green and the
      mutation score ≥ threshold on the curated set.
