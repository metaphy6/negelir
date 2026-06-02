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
