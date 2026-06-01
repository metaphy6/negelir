# Phase 11.16 — Vendor-bug registry & runtime quirks

> Extracted from `docs/planning/ROADMAP.md` §11.16
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 11.16 Vendor-bug registry & runtime quirks

- [ ] **`xops/compute/quirks.json`** — versioned ledger of known-bad tuples: `{vendor, driver_min, driver_max, runtime_min, runtime_max, kernel_min, kernel_max, symptom, workaround, owner, last_verified_at, source_url}`. Examples: cuDNN 9.0.x crash on Ampere with TF32 + non-contiguous strides; OpenVINO 2025.0 NPU crash on dynamic-batch reshape; ROCm 6.2 hipBLAS reduction-order regression.
- [ ] **Probe consults the quirks file.** A device whose `(driver, runtime)` tuple matches a `severity=block` quirk is refused (falls through to the routing alternate). `severity=warn` quirks emit `device.alert.v1{kind=known_quirk, ref}` and the workaround is auto-applied (e.g., disable a specific cuDNN algo).
- [ ] **Workarounds are testable.** Each `quirks.json` entry references a regression test (`ai/tests/quirks/test_<id>.py`) that demonstrates the bug on the affected tuple and the workaround's fix. Quirk entries without a test are blocked at lint.
- [ ] **Curation workflow.** Adding a quirk requires a tracker row + `make version.bump COMPONENT=ai LEVEL=patch`; removing one requires `last_verified_at < 90 days` and a passing test on a host where the bug used to fire. Stale quirks (no verification in 12 months) raise a CI warning.
