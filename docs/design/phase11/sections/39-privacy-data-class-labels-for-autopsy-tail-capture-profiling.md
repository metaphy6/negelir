# Phase 11.39 — Privacy data-class labels for autopsy / tail-capture / profiling

> Extracted from `docs/planning/ROADMAP.md` §11.39
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/nlp/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.39 Privacy data-class labels for autopsy / tail-capture / profiling

> **Why this exists.** §11.9 / §11.28 / §11.11 say "scrubbed of
> inputs/outputs". That binary is wrong: some inputs (public match
> events) are fine to capture verbatim; some (any tenant prompt) must
> never leave the host. Without an explicit class, the safe default is
> "drop everything", which neuters debuggability.

- [ ] **`data_class` on every request.** Set at the API edge: `public` (no PII, fine to capture), `tenant_internal` (capture metadata only — input lengths, hashes), `pii` (capture nothing beyond timing + provenance). Defaults to `pii` on missing.
- [ ] **Capture matrix.** Autopsy (§11.9), tail-capture (§11.28), shadow-diff (§11.26), and quarantine (§11.4) each declare which classes they capture and at what fidelity. Lint refuses a capture sink without a declared matrix.
- [ ] **Sink isolation.** `pii`-class captures route to `cfg.compute_capture_sink_pii` (encrypted at rest, separate retention) — never the default sink. Misrouted capture refuses to write and emits `sec.alert.v1{kind=capture_class_mismatch, severity=critical}`.
- [ ] **Phase 16/17 binding.** The Emitter (Phase 16) and patcher (Phase 17) inherit the same `data_class` label on any compute-side capture they emit; their CPU-only build tag is unaffected.
