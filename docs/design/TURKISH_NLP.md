# 🇹🇷 Turkish-First NLP

> Companion to Phase 10 of [`../planning/ROADMAP.md`](../planning/ROADMAP.md).
> **Audience:** Turkish-speaking users, often typing fast on mobile.
> **Reality of input:** missing diacritics, typos, slang, code-switching, mixed case.

## 🧪 Sample inputs we must handle

| Raw input | What it means | What we do |
|---|---|---|
| `bugun gs maci kacta` | "Bugün GS maçı kaçta?" | restore diacritics, expand `gs`, intent = `match.kickoff_time` |
| `Fenerbahce – Besiktas iddaa tahmin` | … | normalize team names, intent = `predict.1x2` |
| `derbi ms tahmini ne` | "derby maç sonucu tahmini ne" | slang `derbi` → today's derby fixture, intent = `predict.1x2` |
| `Galatasarayyy 1.5 ust nasil` | … | typo squashing, market = `au_1.5` |
| `bana onümüzdeki hafta süperliği özetle` | … | intent = `summary.next_week` (multi-fixture) |

## 🔧 Pipeline

```
raw → unicode NFC → control-char strip → Turkish lowercase
    → diacritic restoration (table + fastText fallback)
    → tokenization (Zemberek-py rules)
    → typo correction (edit-distance over team/player/league lexicon)
    → intent classifier (fastText, ≤ 20 MB)
    → entity extraction (gazetteer + small CRF)
    → confidence check (cfg.tqu_min_intent_conf)
        ├── high  → dispatch to predictor / data agent
        └── low   → "Did you mean?" reformulation
```

## 🗣️ Answer generation

- Default: **template-driven**, jinja2 with Turkish-aware suffix helpers (`{{ team | locative }}` → "Galatasaray'da").
- Optional: small Turkish LLM (≤ 1 B params, e.g. `Trendyol-LLM-1B-base`) **only** rephrases the templated answer when `cfg.tqu_humanize=true`.
- The LLM **never** decides the prediction. It rewrites a structured answer for tone.
- Output passes through a TR-quality proofreader agent (`proofreader.tr.v1`) that:
  - Validates suffix harmony.
  - Forbids mid-sentence English.
  - Flags answers shorter than `cfg.tqu_min_answer_chars` or longer than `cfg.tqu_max_answer_chars`.

## 📚 Lexicons

```
ai/nlp/lexicon/
├── teams.tr.yaml         # canonical + aliases (incl. typo'd forms)
├── players.tr.yaml
├── leagues.tr.yaml
├── markets.tr.yaml       # ms, au_2.5, kg, iy_ms, …
└── dialects.tr.yaml      # slang, regionalisms, common abbreviations
```

Lexicons are versioned, hot-reloadable on `SIGHUP`, and have a property test
that asserts every alias maps back to a canonical form.

### Conversational Context

Phase 10 §10.25 adds multi-turn state to the NLP plane. The system preserves
`qa.context.v1` across a bounded conversation window and may override stale
or blocked entities with `nlp.event.v1{kind=conversation_entity_overridden}`
when the conversational context no longer matches the current query.

- `qa.context.v1` is produced by `nlp.dispatcher.v1` and consumed by
  `nlp.intent.v1`.
- Context is cleared after a blocked entity or out-of-window turn, with an
  explicit `nlp.alert.v1{kind=conversation_context_cleared_after_block}`.
- The context model is intentionally bounded and recoverable; a stale slot is
  safer than silently trusting an old entity value.

### Streaming Response

Streaming response is offered as a skeleton-first SSE path.
The humanizer emits partial chunks while a mid-stream proofreader gate
validates each chunk before it is published to the client.

- Slow clients may trigger `nlp.event.v1{kind=streaming_client_slow_canceled}`.
- The runtime tracks chunk progress with `cfg.nlp_streaming_write_timeout_ms`
  and enforces `cfg.nlp_streaming_proofread_chunk_chars` for proofreader gates.
- The stream path is designed to degrade cleanly to a final answer if the
  stream is canceled or the proofreader rejects a chunk.

### Audit Re-render Bundles

Phase 10 §10.25 preserves the full audit trail needed to reproduce an answer
later. An audit bundle includes `qa.intent.v1`, `nlp.event.v1`, `nlp.alert.v1`,
and the rendered citation block.

- `make nlp.audit-rerender` regenerates an answer from the bundle and emits
  `nlp.event.v1{kind=nlp_audit_rerender_executed}` on success.
- Re-render bundles are normalized so they are byte-stable across the same
  input, humanizer model version, and proofreader contract.

### Lexicon Contributor Guide

Lexicon governance is a first-class Phase 10 path.
New lexicon alias PRs must be reviewed by at least two maintainers before
being merged, and high-leverage tables (`teams`, `players`, `leagues`)
are subject to stricter alias-delta review.

- Lexicon drift is monitored by `nlp_lexicon_coverage` telemetry.
- `TelemetrySink.record_nlp_lexicon_coverage` emits
  `nlp.alert.v1{kind=lexicon_coverage_below_floor}` when p50 coverage remains
  below `cfg.nlp_lexicon_coverage_p50_floor` for 30 minutes.
- Lexicon files older than `cfg.nlp_lexicon_max_age_days` may emit
  `nlp.alert.v1{kind=lexicon_stale}` and prompt an operator review.

### Holiday Calendar

Date resolution in the Turkish NLP plane uses a deterministic vendor table for
Hijri lookup plus a Diyanet override table for specific national holidays.

- `ai/nlp/dates/hijri.py` contains the vendored lookup used for Ramazan,
  Kurban Bayramı, and other lunar-calendar dates.
- `ai/nlp/dates/_diyanet_overrides.tr.yaml` contains the Diyanet-specific
  manual corrections used when the official calendar differs from the calculated
  Hijri date.
- The resolver also consults cached OpenFootball FIFA-window seed data for
  multi-year schedule context in holiday-aware queries.

## 📘 Rule tables for Turkish input robustness

Phase 10.22 embeds the robustness rules directly into the NLP design doc so
operator-facing examples and lockstep references are available alongside the
implementation.

- `ai/nlp/lexicon/_ascii_collisions.tr.yaml` — explicit allowlist for ASCII-
  based alias collisions, used when `Fenerbahce` and `Fener` could map to
  different canonical entries.
- `ai/nlp/lang_tr/particles.tr.yaml` — Turkish particle insertion and repair
  rules for inputs such as `gs'in` and `galatasarayda`.
- `ai/nlp/lang_tr/dialect.tr.yaml` — colloquial and abbreviation expansions
  (`yapicaz` → `yapacagiz`, `kanka` → `kanka`, `ms` → `mac_sonucu`).
- `ai/nlp/lexicon/dialects.tr.yaml` — entity-specific dialect aliases, kept
  disjoint from the general dialect table to prevent false-positive team
  matches.
- `ai/nlp/entities_negative.tr.yaml` — negative rules preventing ambiguous
  foreign names like `Bayer` from matching `Bayern Münih` unless the phrase
  context supports it.
- `make nlp.lexicon-build` — the Phase 10.22 build pipeline emits both the
  `*.tr.ascii.idx` search index and the PR-gated phonetic collision review at
  `ai/nlp/lexicon/_phonetic_review.md`.
- `cfg.nlp_lexicon_feed_*` and `make nlp.rotate-lexicon-key` — feed integrity,
  signature validation, and dual-acceptance key rotation for production lexicon
  swaps.

## Morphological Arbitration

Morphological arbitration resolves Turkish parse ambiguity in favour of
proper-noun interpretations when gazetteer evidence is strong. The system
emits `nlp.event.v1{kind=morph_parse_ambiguous}` for ambiguous parses, then
applies a proper-noun bypass path for `teams.tr.yaml`, `players.tr.yaml`, and
other closed canonical entries. This reduces false-negative entity resolution
in queries such as `galatasaray yenseydi` or `besiktas dua etse`.

## Voice-to-Text Tolerance

The voice-input path tolerates filler words, missing diacritics, and aggressive
capitalization. Voice-specific detection emits
`nlp.event.v1{kind=asr_input_auto_detected}` and the system strips filler tokens
before intent classification. A warning is published as
`nlp.alert.v1{kind=nlp_voice_path_diacritic_overaggressive}` when voice-path
diacritic restoration is too aggressive, so operators can tune the voice path
without breaking normal text input.

## Mobile-IME Awareness

Mobile-IME awareness uses `ai/nlp/lang_tr/ime/keyboard_confusables.tr.yaml` and
layout-aware repair logic to recover from Turkish keyboard slips, swipe input,
and autocorrect cascades. The IME path is intentionally non-blocking; it
emits diagnostic signals such as `autocorrect_cascade_repaired` while preserving
the original query semantics.

## Counterfactual & Modal-Aspect Firewall

Counterfactual queries and modal aspect constructions are handled by a safety
firewall that routes unsupported cases to safe fallback outcomes. Queries with
counterfactual past or evidential phrasing may produce events such as
`modality_routed_counterfactual`, `modality_routed_evidential_hearsay`, or
`modality_routed_obligative`. The firewall prevents unsupported modal inputs
from reaching predictor logic and instead returns an explicit unsupported
response when appropriate.

## Output Envelope Integrity

Output integrity is enforced by adding `qa.answer.v1.envelope_signature`,
`qa.answer.v1.envelope_signature_key_id`, and `qa.answer.v1.body_canonical_sha`.
The answer envelope is signed and verified across the gateway and audit paths.
Key rotation for answer envelope HMAC is operator-driven via
`make nlp.rotate-answer-hmac-key`, with a dual-acceptance grace window for key
rollover.

## 🚧 Wrong-Turkish Tolerance Catalogue

The Phase 10.24 catalogue documents every wrong-Turkish tolerance rule and
operator-facing worked example.

- **§10.24.1 Vowel-harmony-violation tolerance.** Recover malformed suffixes such
  as `Galatasarayda` → `Galatasaray'da`, `Fenerbahceye` → `Fenerbahçe'ye`, and
  `Ankaragucuya` → `Ankaragücü'ye`.
- **§10.24.2 Repeated-character & emphasis normalization.** Collapse
  `Galatasarayyy` → `Galatasaray`, `evetttt` → `evet`, and `bugunn` → `bugun`.
- **§10.24.3 Digit ↔ letter confusable folding.** Fold `3`/`1`/`2` into Turkish
  letters in noisy fan input such as `3stanbul`, `1nönü`, and `Fener2ahçe`.
- **§10.24.4 Turkish dotted/dotless i NFC corner case.** Normalize `Istanbul`
  / `istanbul` with Turkish-specific NFC treatment and preserve the difference
  between `ı` and `i` where it changes meaning.
- **§10.24.5 Run-on / multi-question input splitting.** Split `bugun gs maci kacta
  ne` into `bugun gs maci kacta` + `ne` so downstream intent classification
  does not produce a single incorrect combined intent.
- **§10.24.6 Negation-aware intent.** Detect negation in inputs like `kazandimi
  degil` and avoid misclassifying the query as an affirmative prediction.
- **§10.24.7 Compound / hyphenated club name handling.** Match
  `MKE Ankaragücü` and `Kayserispor-Çaykur` to canonical club names despite
  spacing and hyphen variants.
- **§10.24.8 Honorific / role-prefix normalization.** Normalize expressions such
  as `hoca`, `başkan`, and `yönetici` in queries like `hoca ne dedi`.
- **§10.24.9 Emoji / pictograph as semantic signal, never decision.** Treat
  `fenerbahçe❤️` as fan sentiment rather than a separate team token.
- **§10.24.10 Hashtag, @-mention, URL / HTML-entity hygiene.** Sanitize
  `#galatasaray`, `@fener`, and `malatya.com` without breaking intent or entity
  extraction.
- **§10.24.11 Decimal-comma / score-line numeric disambiguation.** Resolve
  `1-0` as a score-line query, `1,5` as a decimal market, and `2. gol` as an
  event phrase.
- **§10.24.12 Garden-path backtracking & abstention discipline.** Recover from
  ambiguous inputs such as `galatasaray besiktas mı` and defer to a safe
  clarification path where the semantic structure is uncertain.
- **§10.24.13 Empty / pathological / single-character input.** Handle `?`, `a`,
  and whitespace-only queries with canned Turkish guidance rather than guessing.

### Worked examples

- `bugun gs maci kacta` → ASCII alias index restores `gs` to `galatasaray`, then
  the intent classifier dispatches `match.kickoff_time`.
- `fenerbahce kupasi` → alias expansion matches the canonical team name and
  avoids an ASCII collision with `fener`.
- `bugun gs'in maci` → particle repair normalizes the possessive form before
  entity extraction.
- `yapicaz` → dialect rule expands to `yapacagiz` and preserves the original
  intent context.
- `Galatasaray score` → bilingual lexicon lookup handles the English token while
  still matching the Turkish team name.

## 🧪 Test corpus

`ai/tests/fixtures/turkish_queries.yaml` — at least 200 entries grouped:

- **Clean** (50): correct Turkish, full diacritics.
- **No diacritics** (50): "Fenerbahce", "Besiktas".
- **Typos** (40): keyboard slips, doubled letters.
- **Slang / dialect** (30): "derbi", "hoca", "tribün".
- **Code-switch** (15): mixed TR/EN.
- **Adversarial** (15): prompt injection, off-topic, abuse.

CI gates:

- ≥ 95 % intent accuracy on clean + no-diacritics + typos.
- 100 % "did-you-mean" for low-confidence cases (no silent guesses).
- 100 % rejection on adversarial entries.

## 🔄 Concurrency & Scalability

### Singleflight (§10.12, §10.21.4)

**Scope: per-pod only.** Cross-pod collapse is intentionally NOT implemented.

- Concurrent identical queries arriving at the same pod collapse to a single
  execution using in-process `threading.Event` (mirroring Go's `singleflight`).
- Cross-pod coordination via Redis lock was evaluated and rejected: the cost
  (one Redis round-trip per query) outweighs the benefit at v1 scale (< 1000 qps).
- At higher scale (> 5000 qps sustained), revisit cluster-scope singleflight
  as a circuit-breaker fallback, not the default path.

**Implementation:** `ai/swarm/sdk/singleflight.py`  
**AST guard:** `test_nlp_singleflight_does_not_use_redis` rejects `redis.lock`
import in singleflight and NLP dispatcher modules.

**Doctrine:** Each NLP pod independently collapses duplicate requests; no
shared state across pods. This trades marginal redundant work (when the same
query hits different pods simultaneously) for zero Redis dependency on the
hot path.

### Capacity model (§10.23.10)

**Purpose:** Give operators a concrete per-pod throughput ceiling so capacity
decisions are based on modelled behaviour, not guesswork.

- `throughput_pod = parallelism / avg_latency`
- Per-stage parallelism:
  - Normalize / lexicon / intent / entity / dispatcher = CPU-bound,
    parallelism = `cfg.nlp_intake_workers=8` (default; sized for 4 vCPU pod).
  - Humanizer = GPU-lease serialized, parallelism = `1` (per pod).
- Per-stage avg latency:
  - normalize 5ms
  - intent 25ms
  - entity 40ms
  - render 30ms
  - humanizer 300ms (when used)
  - proofreader 15ms
- Throughput ceiling (without humanizer): `8 / 0.115s ≈ 70 QPS`

### Output formatting (§10.23.5)

**Purpose:** Make Turkish answers accessible across device modes and
normalize rendering semantics so operator-facing output is deterministic.

- `answer_format=screen_reader` renders a single, emoji-free Turkish answer
  that is stable at the byte level for automated regression checks.
- `markdown_safe` is a production-safe variant that escapes inline HTML and
  preserves Turkish suffix forms.
- `plain` remains the default path for standard conversational output.

### Accessibility (§10.23.7)

**Purpose:** Ensure NLP output works for screen readers and other assistive
clients without changing the answer semantics.

- Screen-reader output strips decorative emoji, normalizes combining marks,
  and renders percent expressions as words.
- The same Turkish text is exposed in a deterministic, line-oriented form to
  support byte-stable comparison in operator smoke tests.

### Tenant-Fairness (§10.23.1)

**Purpose:** Prevent a noisy tenant from consuming all NLP intake capacity
while still keeping all tenants live in the same pod.

- Per-tenant intake slots are isolated by `cfg.nlp_per_tenant_inflight_max`.
- Deterministic round-robin dispatch across non-empty tenant queues keeps a
  noisy tenant from monopolizing concurrent NLP work.
- Tenant abuse detection emits `nlp_tenant_intake_abuse` when a tenant
  exceeds `cfg.nlp_tenant_abuse_qps_threshold` over the configured window.

**Outcome:** This section anchors the Phase 10 rollout guidance and makes the
new QM path visible in operator documentation.

**Outcome:** This section anchors operator guidance in `docs/design/TURKISH_NLP.md`
and closes the failure mode where capacity advice would otherwise be guessed.
