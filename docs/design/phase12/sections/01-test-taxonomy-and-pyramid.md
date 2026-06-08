# Phase 12.1 — Test taxonomy, pyramid & ownership

> Binding per-section detail for Phase 12 §12.1. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A6 (adversarial = only prompt injection), A7 (chaos =
> liveness). **Depends on:** §12.0.

### 12.1 The eleven test layers

Phase 12 formalises the layers the original stub sketched and adds the
ones it omitted (load, regression/golden, mutation). Each layer has a
**single owning lane** (§12.13), a **determinism contract**, and an
**example name** so the taxonomy is enforceable, not decorative.

| Layer | Kind | Owns | Lane | Example |
|---|---|---|---|---|
| **Unit** | Pure logic, no I/O | every package | fast (push) | `test_dixon_coles_grid_sums_to_one` |
| **Property** | Invariants under random input | every public type | fast (push) | `test_match_envelope_roundtrip_property` |
| **Contract** | Wire schemas / OpenAPI | bus topics + API | fast (push) | `test_predict_final_matches_schema` |
| **Integration** | Agent ↔ bus ↔ agent | swarm + storage | pr | `test_scraper_to_storage_happy_path` |
| **Adversarial** | Injection / payload abuse / homoglyph | every trust boundary | pr | `test_qa_resists_ignore_previous_instructions` |
| **Fuzz** | Coverage-guided random bytes | every parser/decoder | nightly | `fuzz_sec_input_sanitize` |
| **Load** | Throughput + latency budgets under RPS | API + NLP + predictor | nightly | `load_qa_p99_within_budget` |
| **Chaos** | Kill / slow / partition / corrupt | full stack | nightly | `chaos.redis-flap` |
| **Soak** | Long-run leak / drift / MTBF | every long-lived agent | nightly + weekly | `soak.swarm.24h` |
| **Regression/Golden** | Frozen-output byte-identity | NLP render, citations | pr | `test_nlp_audit_rerender_byte_identical` |
| **Mutation** | "Covered ⇒ asserted" | security/integrity hot paths | nightly | `mutmut run --paths-to-mutate ai/swarm/agents/sec` |

- [ ] The taxonomy table above is reproduced in
      [`TESTING_STRATEGY.md`](../../TESTING_STRATEGY.md) and the two
      copies are kept in sync by a lint (`xops/lint/test_taxonomy_sync.py`).
- [ ] Each layer name is a **closed enum** consumed by §12.14's run
      ledger (`layer ∈ {unit,property,contract,integration,adversarial,
      fuzz,load,chaos,soak,regression,mutation}`); an unknown layer
      label in a CI job fails the lint.

### 12.1.1 The pyramid (cost / count / cadence)

- [ ] **Shape contract.** The suite is a pyramid, not an hourglass: the
      bulk of assertions live in unit/property/contract (cheap,
      per-push); integration/adversarial/regression are the middle
      (per-PR); fuzz/load/chaos/soak/mutation are the thin, expensive
      apex (nightly+). A lint (`xops/lint/test_pyramid_shape.py`) warns
      when the apex-to-base ratio inverts (a sign the cheap layers are
      being skipped in favour of slow end-to-end ones).
- [ ] **No-skip-down rule.** A behaviour provable at a cheaper layer
      **must** have its proof there; an apex test may *additionally*
      exercise it end-to-end but never *instead*. Reviewers reject a
      chaos test that is really an un-unit-tested invariant in
      disguise.

### 12.1.2 Ownership map — every trust boundary has a catcher

Per AGENTS.md Rule 7 ("every public surface needs at least one
adversarial test") and the original stub's best instinct ("each entry
maps to the agent that must catch it. A miss = a failing test"):

| Trust boundary | Owning phase | Catcher agent/module | Catalogue family |
|---|---|---|---|
| HTTP request body / headers | 9 | `server/internal/sec` + gateway | P12-7.1, P12-9 |
| QA prompt (Turkish) | 10 | `swarm/agents/nlp` + `sec.input.v1` | P12-7.1, P12-10 |
| Scraped HTML / DOM | 7 | `sec.scrape.v1` | P12-7.2 |
| Bus envelope (cross-agent) | 3 | SDK `RequestIdDeduper` + schema gate | P12-3 |
| Rate-limit / burst / denylist | 7 | `sec.rate.v1` | P12-7.3 |
| Predictor input → NaN/Inf | 11 | predictor backend guards | P12-11 |
| Operator-console envelope | 8 | opsctl HMAC + audit chain | P12-8 |
| Backup / restore artifact | 8 | `maint.backup.v1` | P12-8 |
| Calibration / citation envelope | 5 | consensus + citation HMAC | P12-5 |
| Catalog / fixture lifecycle | 13 | league catalog gates | P12-13 |
| Emitter feed payload | 16 | feed signer + parity | P12-16 |

- [ ] Every row maps to **≥ 1** stable catalogue ID in §12.5; the
      §12.16 coupling matrix asserts no boundary is uncovered.
- [ ] **Catcher-of-record invariant.** Each adversarial corpus entry
      (§12.2) declares the `expected_catcher` (agent + `kind` of the
      `sec.alert.v1` / `degraded_reason` it must raise). A corpus entry
      whose catcher never fires is a failing test, surfaced by the
      §12.14 scorecard as an **undetected-attack** row — the single
      most important signal this phase produces.

### 12.1.3 Layer-to-doctrine binding

- [ ] **Tests-track-code (Rule 10).** Phase 12 does not relax it; it
      *operationalises* it: the §12.13 diff-coverage gate fails a PR
      that adds a public surface with no new test at the correct layer;
      a bug-fix PR with no regression test is rejected.
- [ ] **Smallest-model / determinism (Rule 4/5).** Fuzz + chaos harness
      code is itself CPU-only, dependency-light, and container-runnable;
      no GPU, no network egress beyond the chaos compose profile.
- [ ] **No fabricated data (Rule 3).** Synthetic adversarial payloads
      live only under `*/tests/` and `ai/tests/fixtures/adversarial/`;
      §12.2 forbids any chaos/fuzz path from leaking synthetic records
      into a production-shaped store.
