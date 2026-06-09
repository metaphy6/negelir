# Phase 13.11 — NLP + competition gazetteer + Q&A intents (cross-cutting; ships per league with 13a/b/c)

> Extracted from `docs/planning/ROADMAP.md` §13.11
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 13.11 NLP + competition gazetteer + Q&A intents (cross-cutting; ships per league with 13a/b/c)

- [x] **Gazetteer auto-feed.** Every `Competition` record's `aliases[]` and every `Team` record's `aliases[]` auto-feed the TR gazetteer; lint refuses hand-edited per-league gazetteer files.
- [x] **Stage vocabulary** (`nlp/lexicon/stages.tr.yaml`) — yarı final, çeyrek final, son 16, grup aşaması, ön eleme, play-off; covered by entity-extraction tests.
- [x] **Q&A intents** added to Phase 10 router: `competition_lookup`, `transfer_lookup`, `injury_lookup`, `referee_lookup`, `weather_lookup`, `suspension_lookup` (the latter five also referenced by Phase 21).
- [x] **TR transliteration.** Foreign team names transliterated per `TURKISH_NLP.md`; both `"Bayern"` and `"Bayern Münih"` resolve to `team_bayern_munich`. Test corpus: 50 queries per non-TR league at promotion time.
- [x] **Entity-extraction recall gate.** `≥ cfg.nlp_promotion_recall_min` (default 0.92) on the per-league test corpus — gates T2 → T1.
- [x] **TR lexicon canonicalisation.** Lint refuses two competition records with the same alias resolving to different `competition_id` (no ambiguous shortcuts).
- [x] **Locale-aware normalization.** Turkish dotless-ı / dotted-i, German umlauts, Spanish ñ, Portuguese ã — each handled by `unicodedata.normalize('NFC')` + lowercase per IETF BCP 47; proof test `test_unicode_normalization_round_trip.py` covers the top-5 EU + TR character sets.
- [x] **Right-to-left guard.** Arabic / Persian queries (Iran Pro League imported in 13c stretch) round-trip without bidi corruption; visible-string equality holds.
- [x] **Gazetteer regression corpus.** Each league's 50-query promotion corpus is committed under `ai/tests/fixtures/nlp/<league_id>/`; demotion corpus (queries that historically caused mis-resolution) is committed alongside and asserted to remain correctly resolved (`test_nlp_demotion_corpus.py`).
- [x] **Mixed-script handling.** Yugoslav-era clubs (Cyrillic + Latin transliterations), Greek (Olympiacos / Ολυμπιακός), Hebrew (Maccabi / מכבי), and CJK (J1 / K League / Super League) round-trip through the gazetteer; proof test `test_mixed_script_round_trip.py` covers the 5 script families currently in the catalog.
- [x] **Confusable-character defense.** Cyrillic 'а' vs Latin 'a', Greek 'Α' vs Latin 'A' do **not** auto-merge to the same `stable_id`; lint scans alias lists for confusable-mixed strings (`xops/lint/no_confusable_aliases.py`). Proof test `test_confusable_alias_distinct.py`.
- [x] **Gazetteer compile budget.** Per-league gazetteer compile ≤ `cfg.gazetteer_compile_max_ms` (default 50 ms) per row; full 50-league recompile ≤ 1.5 s; soak `bench/gazetteer_compile.py`.
