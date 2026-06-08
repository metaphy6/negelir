# Phase 12.5 — Chaos catalogue: single-source stub registry & ID lifecycle

> Binding per-section detail for Phase 12 §12.5. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A0 (deps), A2 (target naming), A12 (catalogue is a
> Phase 7 artifact). **Depends on:** §12.1, §12.4.

### 12.5 The catalogue is the contract

[`docs/testing/phase12_catalogue.md`](../../../testing/phase12_catalogue.md)
is the **single source of truth** for every chaos / adversarial stub in
the system. Sister phases register a stub here (a stable ID + a
property + the owning agent) *as they design the resilience surface*;
Phase 12 fills in the body (the actual proof test) *as it hardens*. This
section defines the registry's **schema, ID scheme, and lifecycle** so
the catalogue stays trustworthy as dozens of phases write into it.

- [ ] **Registry schema.** Each row is
      `{id, target, owning_phase, owning_section, property, expected_signal, status}`
      where `expected_signal` is the exact `sec.alert.v1{kind}` /
      `degraded_reason` / HTTP triple the system must emit, and
      `status ∈ {stub, implemented, retired}`.
- [ ] **`make chaos.list` reads the catalogue**, not a hand-maintained
      duplicate; a lint (`xops/lint/chaos_catalogue_sync.py`) asserts
      every `make chaos.*` target has a catalogue row and vice-versa.

### 12.5.1 ID scheme

- [ ] **Stable prefix `P12-<phase>-<seq>`.** The owning phase is encoded
      in the ID (`P12-7.1-A`, `P12-8-AA`, `P12-11-C`, `P12-13-D`,
      `P12-16-B`). IDs are **append-only**: once allocated, an ID is
      never re-numbered (test names reference it) and never re-used
      after retirement (§12.5.3).
- [ ] **Canonical target name is dot-style** (§12.0 A2):
      `chaos.<area>-<scenario>` (e.g. `chaos.redis-flap`,
      `chaos.kill-predictor`, `chaos.fixture-state-flap`). The legacy
      hyphen forms (`chaos-fill-dlq`) in the seeded draft are normalised
      by §12.5.4; the normalisation maps old→new in the catalogue header
      so external references resolve.

### 12.5.2 Per-phase families (cross-phase reconciliation)

The catalogue must enumerate **every** `chaos.*` referenced anywhere in
`docs/`. Today these families exist or are referenced; §12.5.4 fixes the
gaps:

| Family | Owning phase | Source of stubs | Status in draft |
|---|---|---|---|
| `P12-7.1/7.2/7.3/7.4` | 7 | sec.input/scrape/rate/alert | present |
| `P12-8-A … P12-8-AL` | 8 | maint/ops/backup chaos | present (1 table bug) |
| `P12-8-AM … P12-8-AT` | 10 | §10.27/§10.28 NLP chaos | present, **mis-prefixed** |
| `P12-10-*` | 10 | §10.0/§10.29–§10.32 NLP chaos | **missing** (referenced, not rowed) |
| `P12-5-*` | 5 | kill-predictor degraded-flag, citation forgery | **missing** |
| `P12-9-*` | 9 | §9.15 gateway chaos stubs | **missing** |
| `P12-11-*` | 11 | §11.10 `chaos.gpu.*` / `chaos.compute.*` | **missing** (referenced in §11.10) |
| `P12-13-*` | 13 | bracket/predictions-tamper/storage-deny/region-drift/rolling/quarantine | **missing** |
| `P12-16-*` | 16 | `feeds.chaos.run` family | **missing** |

- [ ] **Mis-prefix fix.** The §10-era stubs `P12-8-AM…AT` describe NLP
      surfaces, not maint surfaces; they keep their **IDs** (stability)
      but the catalogue annotates `owning_phase=10` and groups them
      under a clear "NLP chaos (registered under the 8-prefix for
      historical reasons)" note. No renumber.
- [ ] **Reconcile, do not invent.** Every added row points at an
      existing `chaos.*` reference in a sister `docs/design/*.md`; the
      §12.16 coupling matrix is the audit that no reference is orphaned
      and no row is fictional.

### 12.5.3 Lifecycle: stub → implemented → retired

- [ ] **stub.** Registered by the owning phase with `status=stub` and a
      `TBD — implementation pending Phase 12` body. A stub is **not**
      counted by the §12.17 rollup until its owning phase ships.
- [ ] **implemented.** Phase 12 lands the proof test; the body becomes
      the test path; `status=implemented`. The matching `make chaos.*`
      target is wired and `make chaos.list` shows it.
- [ ] **retired.** A scenario made obsolete by a design change is marked
      `status=retired` with the superseding ID; the row stays (history),
      the ID is **never re-used**, and the target is removed from
      `make chaos.list`. A retired stub may not silently vanish — that
      would let a real weakness slip back in unnoticed.

### 12.5.4 Catalogue repair (this phase's edit to the registry)

`docs/testing/phase12_catalogue.md` is fixed in the same change-set as
this section (see §12.5 tracker note):

- [ ] **Fix the malformed row** — the merged `… || P12-8-AM` cell at the
      end of the §8 table is split into two well-formed rows.
- [ ] **Re-frame the header** from "Phase 7 stubs" to "cross-phase
      Phase 12 registry" with the §12.5.1 ID scheme + the old→new target
      naming map.
- [ ] **Add the missing families** (`P12-5-*`, `P12-9-*`, `P12-11-*`,
      `P12-13-*`, `P12-16-*`) as cross-phase index sections that cite
      the owning §section, so the catalogue is actually the single
      source it claims to be.
- [ ] **Normalise target names** to dot-style without changing any ID.
- [ ] `make verify.chaos-catalogue` (new) asserts: no malformed rows,
      no duplicate IDs, every ID matches `P12-<phase>-<seq>`, every
      `status=implemented` row has a real test path, every `chaos.*`
      reference in `docs/` resolves to a row.

### 12.5.5 The "no-`xfail`, miss-is-a-failure" rule

- [ ] Once an owning phase has shipped, **every** `status=implemented`
      stub for it must be green; a regression flips the rollup red.
- [ ] An owning phase may **not** be marked complete in its own DoD
      while it has a `status=stub` row whose surface it has already
      shipped — the stub must be promoted to `implemented` (a real proof
      test) first. This closes the loophole where a phase ships a
      resilience surface and leaves the chaos proof permanently "TBD".
