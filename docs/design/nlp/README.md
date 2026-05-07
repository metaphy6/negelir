# `docs/design/nlp/` — Phase 10 (Turkish-First NLP Layer) detail

> **Why this folder exists.** Phase 10 grew to ~8,500 lines across 34
> sub-sections after thirteen design passes and could no longer be
> reviewed in-place inside `docs/planning/ROADMAP.md`. The contract was
> carved out into per-addendum files so each can be reviewed,
> diff-reviewed, and CI-linked without dragging the rest of the roadmap
> through every cosmetic change. Content here is **binding** — ROADMAP
> §10 is now a slim pointer that delegates to this folder.
>
> **Anchor doc** (architectural narrative, lifecycle, glossary):
> [`../TURKISH_NLP.md`](../TURKISH_NLP.md). The anchor doc explains
> *what / why*; this folder enumerates the *binding `[ ]` checklist*.
>
> **Editing rules.**
> 1. Every checkbox flip lives in **this** folder (the per-section file
>    that owns the item). The ROADMAP §10 stub only carries the
>    phase-rollup checkbox, ticked once §10.20 DoD plus every addendum
>    DoD addition (§10.21..§10.34) are green.
> 2. Any non-trivial edit triggers `make version.bump COMPONENT=docs
>    LEVEL=minor NOTE="..."` in the same commit (per AGENTS.md §6.1).
> 3. Cross-phase references (Phase 5 / 7 / 8 / 9 / 11 / 12 / 13a / 14 /
>    16 / 19 / 20) are authoritative against
>    [`../../planning/ROADMAP.md`](../../planning/ROADMAP.md) and the
>    matching `docs/design/*.md` anchors. If a cross-phase claim here
>    drifts from the source, fix this file — never silently re-plan a
>    sister phase.
> 4. The intent / wire-schema versions called out per addendum (e.g.
>    `qa.intent.v1 schema_version=6`, `qa.answer.v1 schema_version=6`)
>    are the **post-split** state and are tracked in
>    `/memories/repo/negelir-status.md`. Bumping a schema requires the
>    Phase 7 cross-language byte-parity gate plus the §10.32.q breaking-
>    schema migration playbook.
> 5. Forbidden edits without explicit human request that names the
>    file: any rename of these files (URL stability), any deletion of a
>    binding `[ ]` item, any weakening of an integrity gate.
> 6. **Anti-literalism contract is binding on every implementer.**
>    The closed YAML tables, single illustrative inputs, and tuned
>    numeric defaults in §10.21..§10.34 are **witnesses of a class**,
>    not the class itself. Any agent implementing a §10.x section must
>    follow the rules in
>    [`.github/instructions/nlp-anti-literalism.instructions.md`](../../../.github/instructions/nlp-anti-literalism.instructions.md):
>    implement the rule (not the rows), derive the constants (don't
>    inline them), ship a family generator (not just per-row tests),
>    and test composition. A literalist implementation that satisfies
>    every named test in the spec is still a Phase 10 failure.

## Layout

| File | Source §10.X | Theme | Pass |
|---|---|---|---|
| [`sections/00-baseline.md`](sections/00-baseline.md) | §10.0–§10.20 | Surface contract: doctrine, normalize, lexicon, typo, intent, NER, dispatch, templates, humanizer, proofreader, degradation, schemas, perf, idempotency, observability, adversarial, calibration, multi-locale, eval, cfg knobs, DoD | 1st |
| [`sections/21-integrity-and-second-order-safety.md`](sections/21-integrity-and-second-order-safety.md) | §10.21 | Hardening, integrity, second-order safety (mirrors §9.17 pattern) | 2nd |
| [`sections/22-turkish-input-robustness.md`](sections/22-turkish-input-robustness.md) | §10.22 | "Messy Turkish" floor — input normalization beyond §10.1 | 3rd |
| [`sections/23-operability-rollout-serving.md`](sections/23-operability-rollout-serving.md) | §10.23 | Production-serving floor — rollout, canary, SLOs | 4th |
| [`sections/24-tr-input-completeness.md`](sections/24-tr-input-completeness.md) | §10.24 | Wrong-Turkish tolerance, exhaustive | 5th |
| [`sections/25-lifecycle-conversation-time-travel.md`](sections/25-lifecycle-conversation-time-travel.md) | §10.25 | Lifecycle, conversation, time-travel | 6th |
| [`sections/26-morphology-modality-counterfactual.md`](sections/26-morphology-modality-counterfactual.md) | §10.26 | Morphological correctness, input modality, counterfactual handling | 7th |
| [`sections/27-match-lifecycle-abuse-regulatory-operator.md`](sections/27-match-lifecycle-abuse-regulatory-operator.md) | §10.27 | Match-lifecycle, abuse-resilience, regulatory compliance, operator tooling | 8th |
| [`sections/28-authentic-turkish-floor.md`](sections/28-authentic-turkish-floor.md) | §10.28 | Authentic-Turkish floor: orthographic, structural, resource discipline | 9th |
| [`sections/29-deep-morph-telegraphic-silent-failure.md`](sections/29-deep-morph-telegraphic-silent-failure.md) | §10.29 | Deep-morphology, telegraphic-input, silent-failure floor | 10th |
| [`sections/30-conversational-completeness-intent-enum-classifier-bias.md`](sections/30-conversational-completeness-intent-enum-classifier-bias.md) | §10.30 | Conversational completeness, intent-enum closure, classifier-bias floor | 11th |
| [`sections/31-pragmatics-semantic-frame-final-mile.md`](sections/31-pragmatics-semantic-frame-final-mile.md) | §10.31 | Pragmatics, semantic-frame integrity, final-mile reliability | 12th |
| [`sections/32-discourse-pragmatic-dialectal-operational-resilience.md`](sections/32-discourse-pragmatic-dialectal-operational-resilience.md) | §10.32 | Discourse-pragmatic, dialectal, operational-resilience floor | 13th |
| [`sections/33-input-flawlessness-and-proof-tests.md`](sections/33-input-flawlessness-and-proof-tests.md) | §10.33 | Turkish input flawlessness — wrong-assumption sweep, missing proof tests, generic-and-broken-Turkish floor | 14th |
| [`sections/34-input-correctness-resilience-and-integrity.md`](sections/34-input-correctness-resilience-and-integrity.md) | §10.34 | **Input correctness + resilience + integrity — generic-broken-Turkish shapes (predictive-text overshoot, OCR/PDF paste, mid-word URL, half-typed-then-sent, mega-input, suffixed-emoji, comma-as-apostrophe, random-case, ambiguous date, client TZ, systematic-diacritic-loss), normalize-chain perf budget + DFA fast-path + zero-copy guarantee, in-flight stage timeouts, inbound checksum chain (gateway↔NLP integrity pair)** | **15th** |

## Reading order for a new contributor

1. **Anchor doc** ([`../TURKISH_NLP.md`](../TURKISH_NLP.md)) — narrative
   first. ≤ 30 minutes.
2. [`sections/00-baseline.md`](sections/00-baseline.md) — original
   contract. Covers the 21 sub-sections that define what Phase 10
   actually *is*.
3. The addendum that touches the area you're modifying. The addenda
   are stacked: each one assumes every prior addendum is in force.
4. The 14th-pass file
   ([`sections/33-input-flawlessness-and-proof-tests.md`](sections/33-input-flawlessness-and-proof-tests.md))
   when working on input correctness, normalize chains, lexicon edits,
   or any test corpus that touches "wrong" Turkish.
5. The 15th-pass file
   ([`sections/34-input-correctness-resilience-and-integrity.md`](sections/34-input-correctness-resilience-and-integrity.md))
   when working on generic-broken-Turkish shapes the prior passes did
   not enumerate, normalize-chain performance, in-flight degradation,
   or the inbound (gateway → NLP) integrity chain.

## Per-pass contract surface (cumulative)

After all 15 passes the binding surface includes (non-exhaustive):

- **Wire topics:** `qa.intent.v1`, `qa.answer.v1`, `nlp.event.v1`,
  `nlp.alert.v1`, `nlp.gossip.v1`, `nlp.prober.v1`,
  `qa.context_extension.v1`, `qa.intent.v1.attributed_claim` and the
  `meta.*` enum closure (≥ 19 reason codes, see §10.31 + §10.33;
  extended in §10.34 with `meta.empty_input`, `meta.control_only_input`,
  `meta.malformed_input`, `meta.url_only_input`, `meta.likely_partial_input`,
  `meta.multi_input_clarification_required`, `meta.date_disambiguation_required`,
  `meta.normalize_timeout`, `meta.classifier_timeout`).
- **Inbound integrity:** `qa.request.v1.inbound_checksum` field +
  per-pod `inbound_secret` rotation (§10.34.4) — symmetric pair with
  the §10.31.11 `qa.answer.v1.outbound_checksum`.
- **Cross-language byte-parity gates:** `tr_normalize_spec.json`,
  `proper_noun_apostrophe_spec.json`, `confusables_spec.json`,
  `pii_redaction_spec.json`, `intent_slo_classes.yaml`,
  `tr_keyboard_layouts.yaml` (added §10.33),
  `length_cap_spec.json`, `ocr_confusables_spec.json`,
  `paste_layout_spec.json`, `single_emoji_intent_spec.json`,
  `emoji_to_concept_spec.json`, `time_of_day_shorthand_spec.json`
  (all added §10.34, 1500-row parity floor).
- **Integrity gates:** intent.bin SHA pin (§10.21), citation HMAC
  (§10.21.8), envelope HMAC (§10.26.8), prediction-id determinism
  (§10.29.12), outbound checksum (§10.31.11), pipeline-version
  monotonicity (§10.29.13), per-pod salt + 128-bit cache prefix
  (§10.30.12), gossip divergence detection (§10.32.12), end-to-end
  charity-canonicalisation parity (§10.33).
- **Performance contract:** normalize-chain per-pass + total-p99 budgets
  in `normalize_perf_budgets.yaml` (§10.34.2, total p99 ≤ 12ms);
  single-pass DFA fast-path for clean input (zero-copy guarantee on
  no-op passes); per-stage timeout matrix (§10.34.3) producing
  `degraded_reason=stage_timeout:<stage>` instead of 5xx.
- **DoD aggregator:** §10.20 plus per-addendum DoD additions in §10.21
  through §10.34; rollup checkbox in ROADMAP §10 stub.
