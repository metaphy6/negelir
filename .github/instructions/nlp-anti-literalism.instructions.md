---
description: Anti-literalism contract for Phase 10 NLP design docs (docs/design/nlp/**) — applies whenever implementing or testing NLP code that traces back to a §10.x spec.
applyTo: 'ai/swarm/agents/nlp/**,ai/nlp/**,ai/swarm/source_watcher/**,ai/tests/**nlp**,ai/tests/**normalize**,ai/tests/**intent**,ai/tests/**entity**,ai/tests/**humanizer**,ai/tests/**proofreader**,docs/design/nlp/**'
---

# Phase 10 NLP — Anti-literalism contract

Doctrine lives in [`AGENTS.md`](../../AGENTS.md). The Phase 10 binding
specs live in [`docs/design/nlp/sections/`](../../docs/design/nlp/sections/)
across 15 design passes (§10.0–§10.34, ~8,500 lines). This file
only adds the rules that prevent **literalist** implementations of
those specs.

## 1. The literalism trap (read first)

The Phase 10 design docs are *dense with concrete examples*: closed
YAML tables with 20–120 rows, single illustrative inputs
(`Galatasarayhttps://...`, `⚽nın`, `3 üç maç`, `Galatasaray,da`,
`aks/sbh/öğl/gec`), and tuned magic constants
(`nlp_partial_input_min_token_len=3`, `nlp_paste_max_newlines=4`,
`case_flips_per_char>0.30`, `non_ascii_ratio<0.02`,
`token>18 → edit_budget=1`). Each example is a **witness of a class**,
not the class itself. The named constants are **calibrated points on
a curve**, not magic.

A literalist implementation hard-codes the witnesses, passes the
exact rows in the YAML, and ships. It will satisfy every named test
in the spec and still be wrong on the 80% of real Turkish input the
spec couldn't enumerate.

**You must not produce a literalist implementation.** Every Phase 10
deliverable must demonstrate that it generalizes beyond the
witnesses given in the spec.

## 2. Hard rules — every rule below is enforceable in code review

### 2.1 Rules, not rows

When a §10.x section provides a closed YAML table:

- ✅ Read the **principle** the table embodies (e.g. "Turkish
  predictive engines aggressively complete on prefix ≥3"; "Smart
  punctuation pasted from word processors should fold to ASCII
  apostrophes/quotes/dashes/ellipses").
- ✅ Implement the **rule** (a function, regex class, classifier,
  or generator), then load the YAML as the *seed corpus + audit
  trail* for that rule.
- ❌ Never implement an `if token in {literal_row_1, literal_row_2, …}`
  cascade keyed on the YAML rows. The YAML is the *test corpus*; the
  code is the *generalisation*.
- ✅ If the principle cannot be stated in ≤200 words, that is a
  signal you have not understood the section yet — re-read or ask,
  do not start coding.

### 2.2 Constants are derived, never magic

When a §10.x section names a numeric threshold
(`nlp_partial_input_min_token_len=3`, etc.):

- ✅ Treat the value as a **default** wired through
  `ai/common/config.py` + `ai/common/defaults.yaml` +
  `xops/env/.env.example` + Go `server/internal/config` (the
  triangle commit, AGENTS.md Rule 1).
- ✅ Add a one-line comment at the cfg site stating *what the
  threshold guards against* and *which corpus / percentile the
  default was calibrated on* (e.g. `# p95 of paragraph-separator
  count in pii-clean fan input corpus v3, sha=…`). If the spec
  did not say, infer the most defensible derivation and write it
  down — do **not** ship the number with no justification.
- ❌ Do not inline the numeric anywhere in code or tests.
- ✅ Tests must parametrise around the threshold (cases at
  `value-1`, `value`, `value+1`) and at least one case at
  `value × 2` to demonstrate the rule still holds out-of-band.

### 2.3 Family generators, not single witnesses

When a §10.x section gives ≤10 example inputs for a "shape" (e.g.
the 15 generic-broken-Turkish shapes in §10.34.1):

- ✅ Implement a **Hypothesis strategy** (or equivalent generator)
  under `ai/tests/strategies/nlp/<shape>.py` that produces the
  shape's *family* — the YAML witnesses must be a strict subset of
  what the strategy can generate.
- ✅ Add a property test that runs ≥200 generated cases per shape
  per release and asserts the invariant the spec demanded
  (e.g. "every generated mid-word-URL paste produces
  `meta.url_only_input` *or* successfully splits into a real
  entity").
- ❌ A YAML-row-only test does not satisfy the DoD. Per-row tests
  are *audit fixtures* and additional coverage; they are never the
  only coverage.

### 2.4 Composition is mandatory

Phase 10 sections describe features in isolation. Real Turkish
input combines them. Any new module must include:

- ✅ At least one **composition test** that combines the new
  feature with two unrelated previously-shipped features (pick
  the two most plausible co-occurrences and document why).
- ✅ For §10.34.1's 15 shapes specifically: the
  `BrokenInputClassifier` (or its equivalent) must return a
  `set[ShapeClass]`, never a single `ShapeClass`. The composition
  matrix in `ai/tests/test_nlp_broken_input_composition.py` must
  enumerate at minimum all 15 *singletons* + ≥30 *pairs* (sampled
  by traffic-likelihood, not alphabetical).
- ❌ A long `if elif` cascade that handles only one shape per
  request is a literalism failure even if every individual `if`
  branch passes its row tests.

### 2.5 No silent fallback to "matched a witness"

If your code only handles the inputs that exactly match witnesses
from the spec and falls through to a default for everything else,
you must:

- ✅ Raise the unhandled input as a `meta.unmatched_*` event with
  enough context for §10.18 observability to surface it as a
  *generalisation gap*.
- ❌ Never silently return `None`, an empty intent, or
  `clarification_required` for inputs the spec's class clearly
  covered but your implementation didn't.

### 2.6 Spec changes during implementation

If, while implementing a §10.x section, you discover the
specification's witnesses or constants are wrong, *under-specified*,
or contradict another section:

- ✅ Stop coding. Open a tracker note with `--action note` and
  `STATUS=in-progress`, citing the section and the conflict.
- ✅ Propose an additive addendum (e.g. §10.35) per the
  Phase 10 additive-only doctrine (`docs/design/nlp/README.md`
  editing rules). Never silently re-spec a prior pass.
- ❌ Do not patch the principle by hand-editing the example list
  in an existing §10.x file. The spec history is part of the
  contract.

### 2.7 DoD wording you must satisfy

When the §10.x DoD says "≥1 AST guard" or "≥1 proof test", read
that as: **≥1 AST guard *and* ≥1 property-based test that does
not reference any specific YAML row by string match**. The AST
guard pins the witness; the property test pins the rule. Both are
required.

## 3. Self-check before declaring done

Before writing the tracker row for any Phase 10 implementation
turn, answer these in your summary message:

1. **What is the rule?** State, in ≤2 sentences, the principle
   the §10.x section actually demands. If you cannot, you have
   not generalised.
2. **What is the family?** Name the generator (Hypothesis
   strategy, regex class, automaton) that produces the family,
   and where it lives in the tree.
3. **What is the corpus?** Cite the YAML/JSON file (with sha) you
   used as the seed/audit set, and confirm it is *not* the only
   coverage.
4. **What is the composition?** Name the two existing features
   you composed with, and where the composition test lives.
5. **What was derived?** For every numeric default you wired,
   state the corpus + percentile that justifies it.

If any of those answers is "the spec didn't say" or "just the
examples in the doc", treat the work as **not done** — extend the
generator, derive the constant, or escalate via a tracker note.

## 4. Why this is binding

Phase 10 controls the *only* user-facing surface in Turkish. A
literalist implementation will silently fail on the 80% of real
input the spec couldn't enumerate, and the §10.18 observability
floor will catch it only after users complain. The rules above
exist so that the model's gravitational pull toward "implement
exactly what's in the example" is replaced by a gravitational
pull toward "implement the rule the example illustrates".

These rules apply to every file under `applyTo` above, every
Phase 10 PR, and every agent (Copilot, Claude, Cursor, Aider,
Codex). They cannot be waived by an agent on its own; only a
human can mark a §10.x deliverable done with a literalist
implementation, and only with an explicit tracker row stating
why.
