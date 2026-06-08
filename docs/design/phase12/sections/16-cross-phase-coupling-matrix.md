# Phase 12.16 — Cross-phase coupling matrix (closing audit)

> Binding per-section detail for Phase 12 §12.16. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A0 (deps are only 7+9). **Depends on:** §12.5. Mirrors
> the Phase 11 §11.46 coupling-matrix pattern: a single table that
> makes Phase 12's cross-cutting reach auditable and lint-enforced.

### 12.16 What Phase 12 asserts, per owning phase

Phase 12 owns no runtime surface; it **asserts** surfaces other phases
own. This matrix is the closing audit: every resilience surface a
sister phase ships must have a Phase 12 catalogue family + proof. A PR
that touches a referenced surface without updating this table (and the
catalogue) fails `xops/lint/phase12_coupling_sync.py`.

| Owning phase | Surface Phase 12 hardens | Catalogue family | Phase 12 §section |
|---|---|---|---|
| **3** (bus/SDK) | at-least-once, idempotent dedup, reclaim, namespace isolation | P12-3 | §12.6 |
| **4** (agents/storage) | upsert idempotency, registry/heartbeat, DLQ | P12-4 | §12.6, §12.9 |
| **5** (predictor/consensus) | kill-predictor degraded flag, citation HMAC, quorum-empty, replay | P12-5 | §12.9, §12.6, §12.11 |
| **6** (proofreader) | proofreader-block fail-safe, drift settle perf | P12-6 | §12.7, §12.9 |
| **7** (sec plane) | input/scrape/rate/alert defenses | P12-7.1/7.2/7.3/7.4 | §12.10, §12.2 |
| **8** (maint/ops) | DLQ, scaler, backup, opsctl, audit chain, leader | P12-8 | §12.9, §12.11, §12.6 |
| **9** (Go API) | RFC 7807 map, breakers, hedge, bulkhead, shed, identity | P12-9 | §12.7, §12.10, §12.6 |
| **10** (NLP) | injection, homoglyph, PII, lexicon swap, checksums, degraded matrix | P12-10 | §12.10, §12.9, §12.7 |
| **11** (compute) | gpu pull/thermal/oom/frag/ecc, NaN, oversubscribe, migration | P12-11 | §12.7, §12.11 |
| **13** (catalog) | bracket invariant, tamper, region drift, rolling deploy, quarantine | P12-13 | §12.9, §12.11 |
| **14** (K8s) | probe contract, node drain, lease, MIG, live migration | P12-14 | §12.11, §12.8 |
| **16** (emitter) | feed signing, parity, `feeds.chaos.run` family | P12-16 | §12.9 |
| **17** (patcher) | scope-escape refusal, gauntlet bypass attempts | P12-17 | §12.9, §12.10 |
| **19** (long-tail) | per-league no-branch under chaos | P12-13 | §12.6 |
| **20** (monetization) | tier-blind under chaos, entitlement edge-only | P12-20 | §12.10 |
| **21** (enrichment) | enrichment-plane backends inherit routing/chaos | P12-21 | §12.7, §12.11 |

### 12.16.1 Direction of authority

- [ ] **Owning phase wins on the surface contract.** If a sister
      phase's design doc and this matrix disagree about a degraded
      contract, the **owning phase** is authoritative; Phase 12 fixes
      its catalogue/test, never silently re-plans the sister phase
      (README editing rule 3).
- [ ] **Phase 12 wins on the test contract.** How the surface is proven
      (lane, determinism, no-`xfail`, ledger row) is Phase 12's call;
      an owning phase may not ship a resilience surface with a weaker
      proof discipline than §12.13 mandates.

### 12.16.2 The "ships-with-the-owner" rule

- [ ] A resilience surface's chaos proof **lands in the same milestone
      as the surface** — not deferred to a mythical "Phase 12 later".
      The owning phase registers the stub (§12.5 `status=stub`) at
      design time and promotes it to `implemented` when it ships the
      surface; its own DoD may not go green while a shipped surface
      still has a `stub` row (§12.5.5).
- [ ] This is the structural fix for the original gap: Phase 12 was a
      far-future bucket every phase pushed work into and never
      collected. The matrix + §12.5.5 rule make the proof a
      ship-blocker for the **owning** phase, so Phase 12 becomes the
      continuously-maintained aggregator it should always have been.

### 12.16.3 Lint enforcement

- [ ] `xops/lint/phase12_coupling_sync.py` asserts: (a) every `chaos.*`
      reference in any `docs/design/*.md` appears in this matrix and the
      §12.5 catalogue; (b) every matrix row's catalogue family exists;
      (c) no matrix row references a phase that does not exist. Run in
      the pr lane.
