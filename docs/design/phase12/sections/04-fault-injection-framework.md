# Phase 12.4 — Fault-injection framework

> Binding per-section detail for Phase 12 §12.4. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A5 (naming a tool ≠ a designed lab), A10 (determinism),
> A11 (harness already exists). **Depends on:** §12.1.

### 12.4 Two injection planes, one contract

Faults are injected at exactly two planes so a chaos test is both
**realistic** and **deterministic**:

1. **In-process seam — `FaultInjector`** (`ai/swarm/sdk/fault.py`,
   new). A single, test-only seam wrapped around every external call
   the SDK already mediates (bus publish/read, Redis get/set, RPC,
   storage write). It is a **no-op in production** (gated by
   `cfg.fault_injection_enabled=false`, AST-guarded so it can never be
   reached on a prod build tag) and, in tests, applies a **seeded,
   named fault schedule**: `delay`, `drop`, `error`, `corrupt`,
   `reorder`, `duplicate`, `partition`.
2. **Out-of-process — Toxiproxy + Pumba** for the integration/chaos
   compose profile (real Redis/PG/network), so the same scenario is
   also provable against real infrastructure, not just the in-memory
   bus.

- [ ] The same scenario ID (§12.5) runs at **both** planes where
      applicable: the in-process plane in the fast/pr lane (deterministic,
      cheap), the out-of-process plane in the nightly chaos lane
      (realistic). Divergence between the two is itself a finding.

### 12.4.1 `FaultInjector` contract

- [ ] **Deterministic schedule.** A fault schedule is
      `{seed, faults:[{target, op, after_n_calls|after_ms, payload?}]}`;
      given the same seed the same calls fail in the same order. No
      wall-clock, no `random()` without the injected seed.
- [ ] **Named, not magic.** Every injected fault carries a `name` that
      appears in the test and in the §12.14 run ledger, so a failure is
      traceable to the exact fault that caused it.
- [ ] **Production-safe.** `test_fault_injector_is_noop_in_prod` asserts
      the seam is inert unless `cfg.fault_injection_enabled` is true; an
      AST guard (`xops/lint/no_fault_injection_in_prod_paths.py`)
      forbids importing the schedule API outside `*/tests/` and
      `xops/chaos/`.
- [ ] **Blast-radius containment.** Injected faults only touch the
      **namespaced chaos resources** (§12.2.2): a `*_chaos` Redis
      keyspace, a throwaway PG schema, an isolated bus instance. A proof
      test asserts a fault schedule cannot reach a non-chaos namespace.

### 12.4.2 Toxiproxy / Pumba wiring (containerized doctrine)

- [ ] **New `docker-compose.chaos.yml`** layers Toxiproxy between every
      agent and Redis/PG, and runs Pumba as a sidecar that can
      `kill`/`pause`/`netem` named containers. Brought up by
      `make chaos.up` / torn down by `make chaos.down` (dispatched via
      `xops/makefile/chaos.py`), mirroring the `make mock.up/down`
      pattern.
- [ ] **Toxiproxy toxics** map 1:1 onto `FaultInjector` ops: `latency`,
      `down`, `timeout`, `slicer` (corrupt), `limit_data`. A scenario
      declares which toxic it needs; the harness applies and removes it
      deterministically around the assertion window.
- [ ] **Pumba scope.** Container-lifecycle chaos (`chaos.kill-predictor`,
      `chaos.kill-humanizer`, leader-pod kill for split-brain drills) is
      Pumba-driven against the chaos profile only — **never** against a
      shared dev stack or any non-`agent/**` branch in CI (§12.13
      safety rail).
- [ ] Tool versions pinned in `xops/versioning/chart.json` compatibility
      (Toxiproxy, Pumba images by digest — no `*-latest`, per CLAUDE.md).

### 12.4.3 Safety rails (chaos must not become an outage)

- [ ] **Profile gate.** Chaos targets refuse to run unless
      `COMPOSE_PROFILE=chaos` (or `$GITHUB_ACTIONS` on an `agent/**`
      branch); `make chaos.*` against the default profile exits non-zero
      with a clear message. This is the single most important guard:
      a chaos drill can never touch the user's real `make up` stack.
- [ ] **Auto-heal timeout.** Every injected fault carries a
      `max_duration_s`; the harness force-removes the toxic / un-pauses
      the container after the window even if the test crashes, so a
      hung test never leaves the stack degraded.
- [ ] **Idempotent teardown.** `make chaos.down` is idempotent and
      sweeps any leftover toxics, paused containers, and `*_chaos`
      namespaces; a proof test (`test_chaos_teardown_is_clean`) asserts
      a post-teardown stack is byte-identical to pre-chaos.

### 12.4.4 Make targets

- [ ] `make chaos.up` / `make chaos.down` — bring the chaos compose
      profile up/down.
- [ ] `make chaos.run TEST=<id>` — run one catalogue scenario by stable
      ID (§12.5) at the realistic plane; emits a §12.14 ledger row.
- [ ] `make chaos.list` — print the catalogue (single source:
      [`docs/testing/phase12_catalogue.md`](../../../testing/phase12_catalogue.md)).
- [ ] `make test.chaos.inproc` — run the in-process `FaultInjector`
      scenarios in the pr lane (deterministic, no compose).
