# Phase 13.38 — Competition-purity filter

> Extracted from `docs/planning/ROADMAP.md` §13.38
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.38 Competition-purity filter

> Retires assumption §13.0 #45.

- [x] **`Competition.purity_class` enum.** `{competitive, exhibition, charity, testimonial, esports, youth_invitational}`; defaults documented per format.
- [x] **Predictor admission.** Only `competitive` (and `youth_invitational` scoped to age-cohort competitions) feeds predictor training and serving; lint refuses a profile mapping for non-competitive classes (proof test `test_only_competitive_feeds_predictor.py`).
- [x] **Sentiment / news bypass.** Sentiment + news pipelines (Phase 6 / Phase 21) consume non-competitive classes for context but flag them; UI badges "dostluk" / "yardımseverlik" / "vediasever" appropriately (TR UX).
- [x] **API tier surface.** `/v1/predictions` returns 409 for a non-competitive `competition_id` with `X-Reason: competition_class_excluded`.
- [x] **Migration.** Existing exhibitions / friendlies are bulk-classified at 13.0 ledger retirement; the migration is idempotent and tracker-row-audited.
