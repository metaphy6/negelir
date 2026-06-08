# Phase 12.13 — CI integration, lanes & flake policy

> Binding per-section detail for Phase 12 §12.13. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A8 (everything runs per-push), A9 (`xfail` documents a
> weakness), A10 (determinism). **Depends on:** §12.1, §12.3, §12.4.

### 12.13 Lanes: match cost to cadence

Adversarial, fuzz, load, chaos, soak, and mutation have wildly different
cost/latency. Running them all per-push would make CI unusable and a
single flaky chaos test would block every merge. Phase 12 defines
**four lanes** with explicit membership.

| Lane | Trigger | Members | Budget | Blocks |
|---|---|---|---|---|
| **fast** | every push | unit, property, contract, lint, `fuzz.smoke` | ≤ 5 min | the push |
| **pr** | PR open/update | integration, adversarial, regression/golden, `test.chaos.inproc`, `coverage.diff` | ≤ 20 min | the merge |
| **nightly** | cron (self-hosted) | fuzz (Atheris/Go-fuzz), load, chaos (Toxiproxy/Pumba), mutation, `soak.nightly` | ≤ 90 min | the release gate |
| **weekly** | cron (self-hosted) | `soak.weekly` (24 h), `soak.gpu.heat`, full DR drills | report-gated | the release gate |

- [ ] Lane membership is a **single-source manifest**
      (`xops/ci/lanes.yaml`) consumed by the workflows; a test tagged
      with the wrong lane (e.g. a chaos test leaking into `fast`) fails
      a lint (`xops/lint/ci_lane_membership.py`).
- [ ] Lanes reuse the existing workflow conventions
      (`.github/workflows/`, e.g. `api-bench.yml`) and the CI carve-out
      rules in [`.github/instructions/ci-pipeline.instructions.md`](../../../../.github/instructions/ci-pipeline.instructions.md);
      chaos/soak run only on the self-hosted runner and only on
      `agent/**` branches or scheduled cron (never a fork PR).

### 12.13.1 The no-`xfail` release rule (binding)

- [ ] **Adversarial + chaos suites contain zero `xfail`** (§12.0 A9).
      A known weakness is a **release blocker**, not a documented
      `xfail`. A lint (`xops/lint/no_xfail_in_adversarial.py`) scans the
      adversarial/chaos test trees and fails on any `xfail` marker.
- [ ] **`skip` is allowed only for absence, not failure.** A test may
      `skip` only when a required device/credential/runner is not
      present in this lane (mirrors Phase 11 §11.41), and must carry a
      documented owner + the catalogue ID it would cover. A `skip` used
      to hide a failing assertion is forbidden and lint-caught
      (`skip` with no `reason=` referencing an absent resource fails).

### 12.13.2 Flake policy & quarantine

- [ ] **Flake budget.** A test that fails non-deterministically is
      **quarantined** (moved to a `quarantine` lane that runs but does
      not block) within one business day, with a tracked issue and an
      owner; it must be **fixed or deleted within
      `cfg.ci_flake_quarantine_max_days`** (default 14) — quarantine is
      a hospital, not a graveyard.
- [ ] **Root-cause, not retry.** Auto-retry of a failed test is
      **forbidden** in the adversarial/chaos lanes (a retry hides a real
      non-determinism bug, §12.0 A10). A flake is a determinism defect
      in the test or the system; both are fixed at the source.
- [ ] **Flake telemetry.** The §12.14 ledger records per-test
      pass/fail history; a test crossing `cfg.ci_flake_rate_threshold`
      (default 1 %) over a rolling window is auto-quarantined.

### 12.13.3 Chaos-in-CI safety rails

- [ ] **Profile gate** (§12.4.3): chaos targets refuse to run outside
      the chaos compose profile / a sanctioned CI branch. A proof
      (`test_chaos_refuses_default_profile`) asserts `make chaos.*`
      against the default profile exits non-zero.
- [ ] **Ephemeral everything.** Each nightly chaos job spins a fresh
      stack, runs, and tears down (§12.4.3 idempotent teardown); no
      chaos job shares state with another or with a human's dev stack.
- [ ] **Time-boxed.** Every chaos/soak job has a hard wall-clock cap;
      a hung job is killed and reported, never left holding the runner.

### 12.13.4 Determinism in CI

- [ ] The project-wide pinned Hypothesis `ci` profile (§12.3.2) is
      loaded and asserted.
- [ ] Injected clocks + seeded fault schedules (§12.4) mean a red
      nightly chaos run is reproducible locally from the seed printed in
      the log (`make chaos.run TEST=<id> SEED=<seed>`).
- [ ] CI prints, for every failed adversarial/chaos test, the
      catalogue ID + seed + the exact `make` invocation to reproduce.

### 12.13.5 Make / workflow targets

- [ ] `make ci.fast`, `make ci.pr`, `make ci.nightly`, `make ci.weekly`
      — thin dispatchers that select lane membership from
      `xops/ci/lanes.yaml` (via `xops/makefile/tests.py` extension).
- [ ] New workflows `.github/workflows/nightly-resilience.yml` and
      `weekly-soak.yml` (self-hosted) run the nightly/weekly lanes and
      publish the §12.14 scorecard artifact.
