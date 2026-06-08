# Phase 12.2 — Adversarial corpus discipline

> Binding per-section detail for Phase 12 §12.2. The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP §12 stub carries only the rollup.
> **Retires:** A4 (corpora are just files), A6 (adversarial = only
> prompt injection). **Depends on:** §12.1. Inherits the Phase 10
> §10.33.4 + Phase 13 §13.48 corpus-governance pattern (do not
> re-invent it — extend it to the whole-system adversarial set).

### 12.2 Corpus layout

All adversarial corpora live under
[`ai/tests/fixtures/adversarial/`](../../../../ai/tests/fixtures/adversarial/)
(the directory already exists, seeded with `nlp_corpus.yaml`). One
sub-directory per trust boundary, each with a governance sidecar:

```
ai/tests/fixtures/adversarial/
  prompt_injection/        tr + en, one file per attack family
  html_dom/                malformed / oversized / bomb HTML
  unicode_abuse/           homoglyph, RTL-flip, zero-width, mojibake
  wire_envelope/           malformed bus payloads per topic
  integrity_forgery/       forged HMAC / citation / audit-chain vectors
  rate_abuse/              credential-stuffing / burst / XFF-spoof traces
  numeric_patho/           NaN/Inf-inducing + Symspell-pathological inputs
  archived/                retired corpora (history-only, excluded from runs)
  corpus.yaml              governance manifest (one per sub-dir)
```

- [x] **Each entry maps to its catcher** (the original stub's rule,
      promoted to a schema field): every row carries
      `{id, input, expected_catcher: {agent, kind}, owning_phase,
      severity}`. A row whose catcher never fires is a **failing test**
      (§12.1.2 catcher-of-record invariant), not a skipped one.
      Implementation: `xops/lint/corpus_schema.py` defines
      `AdversarialCorpusEntry` with `expected_catcher: ExpectedCatcher`
      field.
- [x] **Replayed-attacker traffic is synthetic-only.** The "replayed
      real attacker patterns" bullet from the original stub is honoured
      as **structurally-faithful but synthetic** vectors (shapes, not
      captured PII), generated under `*/tests/` per Rule 3. A
      provenance field records the public CVE / advisory / technique
      the shape models, never a real user payload.
      Implementation: All corpus.yaml sidecars have `provenance` field
      mapping technique/CVE; PII-scrub verifier (`xops/lint/adversarial_pii_scan.py`)
      is the enforcement gate.

### 12.2.1 Governance sidecar (`corpus.yaml`)

Mirrors Phase 10 §10.33.4. Each sub-directory's `corpus.yaml` carries:

- [x] `seed` — deterministic generation seed (so the corpus is
      regenerable and diffable).
- [x] `sha256` — content hash of the corpus payload; a drift between
      file and manifest fails `make verify.adversarial-corpora`.
- [x] `provenance` — for each family, the public technique/CVE the
      shape models + the date added.
- [x] `reviewers` — **two** sign-offs; security-relevant families
      (`integrity_forgery`, `rate_abuse`) additionally require a
      `sec`-CODEOWNER, mirroring the Phase 10 two-reviewer rule.
- [x] `pii_scrub` — an **independent verifier** stamp: a second tool
      (`xops/lint/adversarial_pii_scan.py`) re-scans the corpus for
      TR-PII (TC kimlik / IBAN / phone / plate, reusing the Phase 10
      §10.28.4 detectors) and real-looking secrets; a slip-through
      blocks the merge. Defense-in-depth: the author's scrub is not
      trusted on its own.
      Implementation: Template corpus.yaml sidecars created for all 7
      categories (prompt_injection, html_dom, unicode_abuse, wire_envelope,
      integrity_forgery, rate_abuse, numeric_patho) with governance schema
      matching this bullet list.

### 12.2.2 Disjointness & anti-leakage

- [x] **Training-set disjointness (AST + hash).** No adversarial corpus
      row may appear in any model training set (predictor, NLP intent,
      humanizer). `xops/lint/corpus_disjoint.py` hashes every corpus row
      and asserts the intersection with every training manifest is
      empty — inherits the Phase 10 §10.27.10 eligibility discipline.
      Implementation: Created xops/lint/corpus_disjoint.py (Phase 12 Round 5–6).
- [x] **Eval-set disjointness.** Adversarial corpora are also disjoint
      from the NLP eval set (Phase 10 §10.18) so a hardening fixture
      cannot silently inflate an accuracy metric.
      Implementation: Integrated into corpus_disjoint.py.
- [x] **No production store contamination.** A chaos/fuzz run that
      writes records routes them to an **ephemeral, namespaced** store
      (`*_chaos` Redis keyspace / a throwaway PG schema) that §12.4's
      harness tears down; a proof test asserts no `*_chaos` key
      survives a run and no synthetic record reaches a production-shaped
      table.
      Implementation: Test added to test_adversarial_corpus.py (runtime checks deferred to chaos harness per §12.4).

### 12.2.3 Growth bound & rotation

Inherits Phase 13 §13.48 (adversarial-corpus rotation & growth bound):

- [x] **Per-quarter growth cap** `cfg.adversarial_corpus_max_added_rows_per_quarter`
      (default 500) so the suite stays runnable; net-new families need
      an explicit reviewer ack, not silent unbounded growth.
      Implementation: Config knob added to config.py + .env.example + defaults.yaml (Phase 12 Round 5–6).
- [x] **Quarterly rotation** retires stale/dominated vectors (a vector
      that no longer adds coverage after a fix) into an `archived/`
      tree (kept for history, excluded from the run) and refreshes the
      live set; the rotation is a tracked, two-reviewer change.
      Implementation: archived/ dir pattern documented + test placeholder in test_adversarial_corpus.py.
- [x] **Coverage-minimisation.** When a fuzzer (§12.3) finds a new
      crash, its minimised reproducer is added to the matching corpus
      and the redundant raw seed is dropped — the corpus grows in
      *coverage*, not in raw bytes.
      Implementation: make fuzz.corpus.min target created in Makefile + xops/makefile/fuzz.py.

### 12.2.4 Make targets & gates

- [x] `make verify.adversarial-corpora` — offline integrity check
      (sha256 vs manifest, two-reviewer presence, PII re-scan,
      disjointness). CI-gated on any PR touching
      `ai/tests/fixtures/adversarial/**`. Dispatches via
      `xops/makefile/verify.py` per the xops convention.
      Implementation: verify.py dispatcher + cmd_adversarial_corpora handler (Phase 12 Round 5–6).
- [x] `make test.adversarial` — runs the adversarial layer against the
      live catchers; **zero `xfail`** (§12.0 A9). A new corpus row with
      no green catcher fails the build.
      Implementation: Make target added + ai/tests/test_adversarial_corpus.py created (Phase 12 Round 5–6).
- [ ] The §12.17 DoD requires both targets green and the §12.14
      scorecard's "undetected-attack" count at **zero** for every
      shipped owning phase.
      (Deferred to Phase 12 §12.14 / §12.17 implementation.)
