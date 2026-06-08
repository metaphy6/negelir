# Phase 12.0 — Wrong-assumption ledger

> Binding per-section detail for Phase 12 §12.0. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> Mirrors the Phase 11 §11.0 / Phase 13 §13.0 ledger pattern: every
> assumption the original ROADMAP §12 stub baked in is retired here so
> no future agent re-introduces it. Each retired assumption must end
> the phase with **at least one passing proof test in both directions**
> (the bug demonstrated, then the fix demonstrated) per §12.17.

### 12.0 Assumptions this phase explicitly retires

- [x] **A0 — "Phase 12 depends only on Phase 7 + Phase 9."** ❌ →
      ✅ Phase 12 is a **cross-cutting verification phase**. It asserts
      properties of the bus/SDK (Phase 3), worker agents + storage
      (Phase 4), predictor swarm + consensus (Phase 5), proofreader
      (Phase 6), security plane (Phase 7), maint/ops plane (Phase 8),
      Go API (Phase 9), Turkish NLP (Phase 10), and compute (Phase 11);
      and it **co-evolves** with Phases 13/14/16/17/19/20/21, each of
      which registers `chaos.*` stubs against the §12.5 catalogue. The
      dependency model is "the surface under test must exist", not "two
      named phases". The rollup (§12.17) gates only on stubs whose
      **owning phase has shipped**.
- [ ] **A1 — "A flat ≥ 85 % line-coverage gate is sufficient."** ❌ →
      ✅ Line coverage is necessary but not sufficient and is
      criticality-blind. §12.12 replaces the flat number with a
      **tiered, criticality-weighted** model (security/integrity/money
      paths ≥ 95 % line **and** branch; ordinary paths ≥ 85 % line),
      a **diff-coverage** gate on every PR, and **mutation testing** on
      the highest-leverage modules so that "covered" implies "asserted",
      not merely "executed".
- [ ] **A2 — "`make chaos-redis-flap` (hyphen) is the target style."**
      ❌ → ✅ The repo standardised on **dot-style** make targets
      (`mock.up`, `version.bump`, `codegraph.status`); verb-noun
      aliases were retired (repo simplification, 2026-04-20). Every
      Phase 12 target is dot-style: `chaos.redis-flap`,
      `chaos.kill-predictor`, `test.adversarial`, `soak.nightly`,
      `fuzz.api`, `coverage.report`. The §12.5 catalogue is the
      single source of canonical target names; the stale hyphen forms
      in the existing catalogue draft are normalised by this phase.
- [ ] **A3 — "`boofuzz` is the fuzzer."** ❌ → ✅ `boofuzz` is a
      network-protocol fuzzer that assumes a long-lived target socket
      and does not fit the containerized, deterministic, CI-gated
      doctrine (Rule 2). §12.3 standardises on **Hypothesis** (already
      a dependency, property-based, shrinking, derandomized CI profile),
      **Atheris** (coverage-guided, libFuzzer-backed, opt-in nightly
      for the Python hot paths), and **`go test -fuzz`** (native, for
      the Go gateway + sec library). Each fuzzer persists a **seed
      corpus** so a found crash becomes a permanent regression test.
- [ ] **A4 — "Adversarial fixtures are just files."** ❌ → ✅ Every
      corpus is **governed** like production data-adjacent material:
      per-corpus `corpus.yaml` (seed, sha256, provenance, two-reviewer
      sign-off, independent PII-scrub verifier), a growth bound, a
      quarterly rotation, and a disjointness guard against any training
      set (§12.2). This inherits the Phase 10 §10.33.4 / Phase 13 §13.48
      corpus discipline rather than re-inventing it.
- [ ] **A5 — "Chaos tools (`pumba`/`toxiproxy`) named ⇒ chaos lab
      designed."** ❌ → ✅ Naming a tool is not a contract. §12.4
      defines **where** faults are injected (a single in-process
      `FaultInjector` seam plus Toxiproxy for network and Pumba for
      container lifecycle), **how** they are made deterministic
      (seeded, named, replayable), and **how blast radius is
      contained** (chaos runs only against the chaos compose profile /
      `agent/**` CI branches, never shared infra), so a chaos test is
      reproducible and safe, not a coin flip.
- [ ] **A6 — "Adversarial = prompt injection at the API."** ❌ →
      ✅ "Adversarial" spans **every trust boundary**: HTML/DOM at the
      scraper (Phase 7 §7.2), bus envelopes between agents (Phase 3),
      message schemas (contract), forged HMAC/citation/audit chains
      (integrity), homoglyph/RTL/PII in Turkish input (Phase 10),
      NaN-inducing inputs at the predictor (Phase 11 §11.10), and
      operator-console envelopes (Phase 8). §12.1's taxonomy and §12.5's
      catalogue enumerate them per owning agent — **a miss is a failing
      test**, not a "known issue".
- [ ] **A7 — "Chaos asserts liveness (it didn't crash)."** ❌ →
      ✅ Every chaos drill asserts a **named, documented degraded-mode
      contract**: no message loss, no double-processing, a specific
      `degraded=true` + `degraded_reason`, a specific structured HTTP
      status (never an unhandled 5xx where graceful degradation is
      specified), and a bounded **MTTD/MTTR**. "It came back up" is not
      a pass; "it degraded exactly as specified and recovered within
      budget" is (§12.14).
- [ ] **A8 — "Coverage/soak/chaos can run on every push."** ❌ →
      ✅ These have very different cost/latency profiles. §12.13 defines
      **lanes**: fast unit/contract on every push; adversarial +
      fuzz-smoke on PR; mutation + Atheris + chaos + soak nightly on a
      self-hosted runner; long heat-soak on a slower cadence. A flaky
      chaos test in the fast lane would block all work — lane
      separation is a reliability requirement, not an optimisation.
- [ ] **A9 — "`xfail` documents a known weakness."** ❌ → ✅ For the
      adversarial + chaos suites a known weakness is a **release
      blocker, not a `xfail`**. §12.13 forbids `xfail` in these suites;
      a property that cannot yet hold is either fixed or the feature is
      withheld. `skip` is permitted **only** for "hardware/credential
      not present in this lane" with a documented owner (mirrors the
      Phase 11 §11.41 rule), never for "the assertion fails".
- [ ] **A10 — "Determinism is the test framework's problem."** ❌ →
      ✅ Adversarial/fuzz/chaos are the **most** prone to flakiness.
      §12.3 + §12.4 mandate: pinned Hypothesis profile
      (`database=None, derandomize=True`, already in
      [`ai/tests/conftest.py`](../../../../ai/tests/conftest.py)),
      injected monotonic clocks (no wall-clock in assertions), seeded
      fault schedules, and a fixed RNG seed surfaced in every failure
      so a red run is reproducible from the log line alone.
- [ ] **A11 — "Coverage tooling already exists."** ❌ → ✅ There is no
      `.coveragerc` / `pyproject` coverage config, no `make coverage`,
      no `xops/makefile/chaos.py`, no `docker-compose.chaos.yml` today.
      Phase 12 **introduces** them under the single-source-config and
      `xops/` dispatch conventions (§12.15), rather than assuming a
      harness that is not there.
- [ ] **A12 — "The chaos catalogue is a Phase 7 artifact."** ❌ →
      ✅ [`docs/testing/phase12_catalogue.md`](../../../testing/phase12_catalogue.md)
      was seeded from Phase 7 stubs and still carries a formatting
      defect (a merged `… || P12-8-AM` table cell) and §10-era stubs in
      mixed naming. §12.5 promotes it to the **cross-phase single
      source**, fixes the malformed row, normalises target names to
      dot-style, and extends it with the Phase 5/9/11/13/16 families it
      is missing — **without** renaming any existing stable ID.

### 12.0.1 Ledger discipline

- [ ] Each retired assumption A0–A12 is cross-referenced from the
      section that operationalises it (the `Retires:` line at the top
      of §12.1–§12.16).
- [ ] §12.17 DoD asserts every A-row has both-direction proof coverage;
      a retired assumption with no failing-then-passing proof is an
      incomplete phase, not a green one.
- [ ] New wrong assumptions discovered while hardening a sister phase
      are appended here (next free `A<n>`) in the same commit that adds
      the matching proof — never silently fixed.
