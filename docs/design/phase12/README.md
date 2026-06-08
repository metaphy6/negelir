# `docs/design/phase12/` — Phase 12 detail

> **Why this folder exists.** Phase 12 (Adversarial & Chaos Test
> Suite) is a **cross-cutting verification phase**: it does not own a
> runtime component, it asserts properties of every other component
> under adversarial input, fault injection, and long-run stress. The
> original ROADMAP §12 stub was ~60 lines (one taxonomy table, five
> corpus bullets, three chaos targets, two coverage gates) while
> sister phases registered **dozens** of `chaos.*` stubs against it as
> their single source of adversarial truth (Phase 5/7/8/9/10/11/13/16).
> That mismatch is the gap this folder closes. Content here is
> **binding** — the ROADMAP §12 stub is now a pointer that delegates
> to this folder.
>
> **Editing rules.**
> 1. Every `[ ]` / `[x]` checkbox flip lives in **this** folder, in
>    the per-section file that owns the item. The ROADMAP §12 stub
>    carries only the phase-rollup checkbox.
> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs
>    LEVEL=minor NOTE="..."` in the same commit (per AGENTS.md §6.1)
>    plus a tracker row (`make track.add PHASE=12 …`).
> 3. The **chaos catalogue** ([`../../testing/phase12_catalogue.md`](../../testing/phase12_catalogue.md))
>    is the single source of stable stub IDs. Cross-phase `chaos.*`
>    references are authoritative against
>    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the
>    owning `docs/design/*.md` anchors. Fix this folder if a claim
>    drifts — never silently re-plan a sister phase.
> 4. No rename of these files without explicit human request (URL
>    stability); no deletion of a binding `[ ]` item; no weakening of
>    a Definition-of-Done gate. A retired chaos-stub ID is never
>    re-used (see §12.5 ID lifecycle).

## What Phase 12 is (and is not)

- **Is:** the *enforcement* layer that turns prose resilience claims
  scattered across every phase into **executable, deterministic,
  CI-gated proof tests** — adversarial corpora, property/fuzz
  harnesses, fault injection, chaos drills, soak runs, and a
  coverage+mutation methodology. It owns the **single-source chaos
  catalogue**, the **fault-injection seam**, the **CI lane topology**,
  and the **no-`xfail` release rule**.
- **Is not:** a place where business logic lives, and **not** a
  one-shot phase that "completes" once and freezes. Phase 12 grows
  monotonically: every sister phase that lands a resilience surface
  registers a stable stub ID here and ships the matching proof test.
  The rollup flips only when every registered stub for an
  **already-shipped** owning phase is green (§12.17).

## Layout

| Source | File | Theme |
|---|---|---|
| §12.0 | [`sections/00-wrong-assumption-ledger.md`](sections/00-wrong-assumption-ledger.md) | Wrong-assumption ledger (retired by this phase) |
| §12.1 | [`sections/01-test-taxonomy-and-pyramid.md`](sections/01-test-taxonomy-and-pyramid.md) | Test taxonomy, pyramid & ownership |
| §12.2 | [`sections/02-adversarial-corpus-discipline.md`](sections/02-adversarial-corpus-discipline.md) | Adversarial corpus discipline (provenance, PII-scrub, rotation) |
| §12.3 | [`sections/03-property-based-and-fuzz-harness.md`](sections/03-property-based-and-fuzz-harness.md) | Property-based & fuzz harness (Hypothesis / Atheris / `go test -fuzz`) |
| §12.4 | [`sections/04-fault-injection-framework.md`](sections/04-fault-injection-framework.md) | Fault-injection framework (Toxiproxy / Pumba + in-process seam) |
| §12.5 | [`sections/05-chaos-catalogue-single-source-registry.md`](sections/05-chaos-catalogue-single-source-registry.md) | Chaos catalogue — single-source stub registry & ID lifecycle |
| §12.6 | [`sections/06-bus-and-network-chaos.md`](sections/06-bus-and-network-chaos.md) | Bus & network chaos (flap / partition / slow / reorder / duplicate) |
| §12.7 | [`sections/07-resource-exhaustion-and-performance-under-stress.md`](sections/07-resource-exhaustion-and-performance-under-stress.md) | Resource exhaustion & performance-under-stress (latency-budget gates) |
| §12.8 | [`sections/08-soak-and-endurance.md`](sections/08-soak-and-endurance.md) | Soak & endurance (leak detection, MTBF, long-run clock) |
| §12.9 | [`sections/09-data-integrity-and-corruption-injection.md`](sections/09-data-integrity-and-corruption-injection.md) | Data-integrity & corruption injection (checksum / HMAC / audit chain) |
| §12.10 | [`sections/10-security-chaos-and-abuse.md`](sections/10-security-chaos-and-abuse.md) | Security chaos & abuse (injection / homoglyph / cert / key-rotation) |
| §12.11 | [`sections/11-recovery-and-dr-drills.md`](sections/11-recovery-and-dr-drills.md) | Recovery & DR drills (restore / cold-start / spool drain / handover) |
| §12.12 | [`sections/12-coverage-and-mutation-methodology.md`](sections/12-coverage-and-mutation-methodology.md) | Coverage & mutation methodology (line+branch+mutation, diff-gate) |
| §12.13 | [`sections/13-ci-integration-lanes-and-flake-policy.md`](sections/13-ci-integration-lanes-and-flake-policy.md) | CI integration, lanes & flake policy (nightly soak, quarantine) |
| §12.14 | [`sections/14-chaos-observability-and-scorecard.md`](sections/14-chaos-observability-and-scorecard.md) | Chaos observability & resilience scorecard (MTTD / MTTR / run ledger) |
| §12.15 | [`sections/15-config-knobs-and-make-targets.md`](sections/15-config-knobs-and-make-targets.md) | Config knobs & make-target inventory (single-source config) |
| §12.16 | [`sections/16-cross-phase-coupling-matrix.md`](sections/16-cross-phase-coupling-matrix.md) | Cross-phase coupling matrix (closing audit) |
| §12.17 | [`sections/17-definition-of-done.md`](sections/17-definition-of-done.md) | Definition of Done (Phase 12) |

## Reading order

1. The ROADMAP §12 stub (`docs/planning/ROADMAP.md`) — goal,
   dependencies, wrong-assumption ledger summary, and rollup checkbox.
2. §12.0 (ledger) then §12.1 (taxonomy) — they frame everything else.
3. §12.5 (catalogue) + [`../../testing/phase12_catalogue.md`](../../testing/phase12_catalogue.md)
   — the stub registry every sister phase points at.
4. The section file relevant to the surface you are hardening. Later
   sub-sections assume earlier ones are in force; if a file's
   `Depends on` clause names another sub-section, re-read it first.
5. §12.17 (Definition of Done) — the gate that flips the ROADMAP
   rollup checkbox.

## Anchor docs (binding context)

- [`../TESTING_STRATEGY.md`](../TESTING_STRATEGY.md) — the project-wide
  testing doctrine Phase 12 enforces.
- [`../SECURITY.md`](../SECURITY.md) — the threat model the
  adversarial corpora target.
- [`../../testing/phase12_catalogue.md`](../../testing/phase12_catalogue.md)
  — the stable stub-ID registry.
- [`../SWARM.md`](../SWARM.md), [`../API.md`](../API.md),
  [`../COMPUTE_DEVICES.md`](../COMPUTE_DEVICES.md) — the surfaces
  under test (bus, gateway, compute).
