# Phase 12.17 — Definition of Done (Phase 12)

> Binding per-section detail for Phase 12 §12.17. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Depends on:** every prior §12.x. In addition to Appendix B common
> DoD.

### 12.17 Phase-completion gates

Because Phase 12 is cross-cutting (§12.0 A0), "done" is **per owning
phase**: the rollup flips only when every catalogue stub whose owning
phase has **shipped** is `status=implemented` and green. A future
phase's stub staying `stub` does not block the rollup; a shipped
phase's stub staying `stub` does.

#### Framework (must all be green before any owning-phase gate counts)

- [ ] **Taxonomy & lanes (§12.1, §12.13).** The eleven-layer taxonomy is
      reflected in `xops/ci/lanes.yaml`; the lane lint + pyramid-shape
      lint are wired; `make ci.fast|pr|nightly|weekly` exist and select
      membership from the manifest.
- [ ] **No-`xfail` rule (§12.0 A9, §12.13.1).** `xops/lint/no_xfail_in_adversarial.py`
      is green across the adversarial/chaos trees; every `skip` carries
      an absent-resource reason + owner + catalogue ID.
- [ ] **Corpus governance (§12.2).** `make verify.adversarial-corpora` is
      green; every corpus has a two-reviewer + independent-PII-scrub
      sidecar; the training/eval disjointness lint passes.
- [ ] **Fuzz harness (§12.3).** `make fuzz.smoke` (pr) deterministic and
      green; `make fuzz.api|nlp|wire` run nightly; the pinned project
      Hypothesis `ci` profile is asserted; a found crash becomes a
      persisted regression seed.
- [ ] **Fault-injection seam (§12.4).** `FaultInjector` ships,
      `test_fault_injector_is_noop_in_prod` + the prod-path AST guard
      are green; `docker-compose.chaos.yml` (Toxiproxy + Pumba) comes up
      via `make chaos.up`; the profile-gate + idempotent-teardown proofs
      pass.
- [ ] **Catalogue integrity (§12.5).** `docs/testing/phase12_catalogue.md`
      malformed row fixed, header re-framed, target names normalised to
      dot-style, missing families added; `make verify.chaos-catalogue`
      green (no dup IDs, every `chaos.*` reference resolves, every
      `implemented` row has a real test path).
- [ ] **Coverage & mutation (§12.12).** Branch coverage on; tiered gate
      (`xops/coverage/tiers.yaml`) wired; `make coverage.diff` blocks an
      under-covered PR; Tier-1 mutation score ≥ `cfg.coverage_mutation_min_score`
      nightly; anti-gaming + ratchet lints green.
- [ ] **Scorecard (§12.14).** `make chaos.scorecard` renders from the
      append-only PII-clean ledger; MTTD/MTTR budgets are gates; the
      degraded-mode catalogue (`docs/testing/degraded_modes.md`) exists
      and every chaos `expected_signal` validates against it.
- [ ] **Config single-source (§12.15).** Every Phase 12 knob is in
      `ai/common/config.py` + `xops/env/.env.example` (+ Go mirror where
      consumed) and covered by the triangle / `TestEnvSync`; the
      dot-style-only target lint is green.

#### Per-owning-phase gates (count only for **shipped** phases)

- [ ] **Bus/SDK (§12.6, Phase 3).** redis-flap / partition / reorder /
      duplicate / corrupt / dlq-poison / key-collision drills green at
      both planes; at-least-once + idempotent + namespace-isolation
      re-proven under fault.
- [ ] **Sec plane (§12.10, Phase 7).** Every P12-7.x stub `implemented`
      and green; injection corpus 100 % blocked (zero `xfail`);
      homoglyph/RTL/oversize/slur drills green; fail-open proven.
- [ ] **Maint/ops (§12.9, §12.11, Phase 8).** Every shipped P12-8-* stub
      `implemented`; audit-chain-break, opsctl-forgery, backup-corruption,
      leader-split-brain, restore-version-skew drills green; restore +
      leader-handover MTTR within budget.
- [ ] **Go API (§12.7, §12.10, Phase 9).** Latency-budget load gate green
      (baseline-compared); breaker/hedge/bulkhead/shed drills green;
      credential-stuffing / XFF-spoof / token-replay blocked; every
      RFC 7807 degraded row driven by a chaos test.
- [ ] **NLP (§12.9, §12.10, Phase 10).** Every shipped P12-10-* /
      §10-era stub `implemented`; checksum-chain (inbound/outbound/
      envelope/citation) tamper drills green; lexicon-swap-staggered,
      tr-pii-flood, runaway-normalize, compound-flood within budget;
      the §10.10 9-row degradation matrix each driven by a chaos test
      with **no 5xx** where graceful degradation is specified.
- [ ] **Compute (§12.7, §12.11, Phase 11).** Every §11.10 row has a
      `chaos.gpu.*` / `chaos.compute.*` drill (already enumerated in
      §11.10) registered as a P12-11-* stub and green; NaN-input,
      oversubscribe, fragmentation, ECC, migration drills green;
      24 h heat-soak report ≤ 30 days old.
- [ ] **Catalog & later phases (Phase 13/14/16/17/19/20/21).** As each
      ships, its registered stubs are promoted to `implemented` and the
      §12.16 coupling-matrix + sync lint stay green; the owning phase's
      DoD may not go green while it has a `stub` row for a shipped
      surface (§12.5.5).

#### Wrong-assumption ledger (binding)

- [ ] **§12.0 satisfied.** Every retired assumption A0–A12 has at least
      one passing proof test in **both directions** (the bug
      demonstrated, then the fix demonstrated); a retired assumption
      with no such proof is an incomplete phase, not a green one.

#### Soak & release evidence

- [ ] **Soak (§12.8).** Nightly soak green; the weekly 24 h soak +
      heat-soak report is ≤ `cfg.soak_report_max_age_days`; no resource
      drift beyond tolerance; MTBF not regressed vs last green baseline.
- [ ] **Release gate.** The latest §12.14 scorecard is attached to the
      release with **zero undetected** attacks/faults for every shipped
      owning phase and MTTD/MTTR within budget; the resilience trend has
      not regressed beyond `cfg.chaos_trend_regression_pct`.

#### Bookkeeping (AGENTS.md §3 + §6.1)

- [ ] Tracker rows recorded for every meaningful slice
      (`make track.add PHASE=12 …`); `make version.bump COMPONENT=docs`
      for design edits, `COMPONENT=xops`/`ai` for harness/code, each in
      the same commit as the work.
- [ ] `docs/design/TESTING_STRATEGY.md` + `docs/testing/phase12_catalogue.md`
      kept in sync with this folder (taxonomy-sync + catalogue-sync
      lints green).
- [ ] **Rollup flips only when** every framework gate is green **and**
      every shipped owning-phase gate is green; an unshipped phase's
      open stubs are tracked, not blocking.
