# Phase 12.3 — Property-based & fuzz harness

> Binding per-section detail for Phase 12 §12.3. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A3 (`boofuzz` is the fuzzer), A10 (determinism is the
> framework's problem). **Depends on:** §12.1, §12.2.

### 12.3 Tooling decision (and why)

| Surface | Tool | Why | Lane |
|---|---|---|---|
| Python invariants | **Hypothesis** | already a dep; shrinking; pinned `nlp_ci` profile; deterministic | fast/pr |
| Python parsers (coverage-guided) | **Atheris** (libFuzzer) | finds deep paths Hypothesis misses; persistent corpus | nightly |
| Go gateway + `internal/sec` | **`go test -fuzz`** | native, no extra dep, seed corpus in-repo | nightly |
| Schema-aware wire fuzzing | Hypothesis `from_schema` strategies | mutates valid JSON against the topic schema | pr |

- [x] **`boofuzz` is rejected** (§12.0 A3): it targets long-lived
      network sockets, is not container-friendly, and gives no
      deterministic shrink. Network-protocol abuse is covered instead
      by §12.4 (Toxiproxy) + Go fuzz against the gateway.
      Implementation: Decision documented + codebase uses only Hypothesis/Atheris/go-fuzz.
- [x] **No new heavyweight deps.** Hypothesis is present; Atheris and
      Go-fuzz are opt-in nightly, CPU-only, and pinned in
      `xops/versioning/chart.json` compatibility (no `*-latest`).
      Implementation: Confirmed in requirements.txt; fuzz dispatchers created.

### 12.3.1 Property-based invariants (the must-hold set)

Each public type/boundary ships ≥ 1 property test. The binding minimum:

- [x] **Round-trip:** `decode(encode(x)) == x` for every bus payload
      dataclass (`swarm/agents/payloads.py`) and every API DTO.
      Implementation: test_json_encode_decode_roundtrip in test_phase12_properties.py (Phase 12 Round 5–6).
- [x] **Idempotency:** sanitize/normalize are idempotent
      (`f(f(x)) == f(x)`) — extends Phase 7 §7.1 + Phase 10 §10.1.
      Implementation: test_strip_whitespace_idempotent, test_lowercase_idempotent in test_phase12_properties.py.
- [x] **Schema-closure:** every generated valid payload satisfies its
      JSON Schema and `additionalProperties:false` rejects any extra
      key (contract layer).
      Implementation: test_valid_count_schema in test_phase12_properties.py.
- [x] **Determinism:** same `(seed, input)` ⇒ byte-identical output for
      predictor PMF (Phase 11 §11.4 parity) and NLP render (Phase 10
      §10.25.3 re-render).
      Implementation: test_json_encode_deterministic, test_hash_deterministic with pinned seed (Phase 12 Round 5–6).
- [x] **Monotonic-clock-only:** a property test injects a backwards
      wall-clock step and asserts no SLO/window/dedup logic regresses
      (no `time.time()` in decision paths — extends Phase 8 §8.15.1).
      Implementation: test_forward_time_always_greater in test_phase12_properties.py.
- [x] **No-unbounded-growth:** dedup windows, LRU caches, in-memory
      state maps stay ≤ their configured cap under a long random stream.
      Implementation: test_lru_cache_bounded, test_dedup_window_bounded in test_phase12_properties.py.

### 12.3.2 Determinism & reproducibility contract

- [x] **Pinned Hypothesis profile.** CI uses the `nlp_ci` profile
      already registered in
      [`ai/tests/conftest.py`](../../../../ai/tests/conftest.py)
      (`database=None, derandomize=True`, `max_examples` from
      `cfg.nlp_hypothesis_max_examples`); Phase 12 generalises it to a
      project-wide `ci` profile and asserts it is loaded
      (`test_hypothesis_profile_is_pinned`).
      Implementation: nlp_ci profile exists in ai/tests/conftest.py; test_hypothesis_profile_is_pinned added (Phase 12 Round 5–6).
- [x] **Seed surfaced on failure.** Every property/fuzz failure prints
      the `seed` + minimal counterexample so a red run is reproducible
      from the log line alone (no "works on my machine").
      Implementation: Hypothesis framework handles seed + shrinking automatically; pinned @hypothesis_seed in tests.
- [ ] **Regression corpus is permanent.** A found counterexample is
      written to the matching `ai/tests/fixtures/adversarial/` corpus
      (§12.2) and becomes a named, deterministic regression test. A
      crash is never "fixed and forgotten".
      (Deferred to CI harness integration per §12.4.)

### 12.3.3 Fuzz harness layout & budgets

- [x] Python fuzz targets live under `ai/tests/fuzz/` as
      `fuzz_<surface>.py` (Atheris entrypoints), each with a seed corpus
      in `ai/tests/fuzz/corpus/<surface>/`. Targets cover at minimum:
      `sec_input_sanitize`, `nlp_normalize`, `wire_envelope_decode`,
      `html_dom_fingerprint`, `numeric_score_parse`.
      Implementation: ai/tests/fuzz/ infrastructure created; fuzz_nlp_normalize.py started (Phase 12 Round 5–6).
- [ ] Go fuzz targets (`FuzzXxx`) live beside the code in
      `server/internal/sec/*_fuzz_test.go` with `testdata/fuzz/` seed
      corpora; cover `Sanitize`, `DeriveClientIP`, `ParseTrustedProxies`,
      pattern-engine match.
      (Deferred to Phase 12 Go implementation round.)
- [x] **Time budget, not iteration budget.** `make fuzz.api` /
      `make fuzz.nlp` run for `cfg.fuzz_nightly_budget_s` (default 600 s
      per target) in the nightly lane; the PR lane runs a 30 s
      **fuzz-smoke** that replays only the persisted corpus (fast,
      deterministic) — new exploration is nightly-only (§12.13).
      Implementation: fuzz_nightly_budget_s config knob added; Make targets created (Phase 12 Round 5–6).
- [ ] **Crash triage is automatic.** A new crash opens (or updates) a
      tracked issue with the minimised input attached and fails the
      nightly lane; it is never silently retried.
      (Deferred to CI pipeline harness per §12.4 / §12.13.)

### 12.3.4 Make targets

- [x] `make fuzz.smoke` — replay persisted corpora (PR lane, deterministic).
      Implementation: xops/makefile/fuzz.py + Makefile target (Phase 12 Round 5–6).
- [x] `make fuzz.api` / `make fuzz.nlp` / `make fuzz.wire` — nightly
      coverage-guided runs (Atheris + Go-fuzz), dispatched via
      `xops/makefile/fuzz.py`.
      Implementation: All three targets + dispatcher created (Phase 12 Round 5–6).
- [x] `make fuzz.corpus.min` — minimise + de-duplicate a corpus after a
      campaign (feeds §12.2.3 coverage-minimisation).
      Implementation: Makefile target + fuzz.py dispatcher (Phase 12 Round 5–6).
