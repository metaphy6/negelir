# Phase 10 §10.34 — Turkish input correctness, resilience, and end-to-end integrity (binding addendum, 15th pass)

> **Provenance.** Authored on the second Phase-10 review pass after the
> 14-file split, in response to the user-driven prompt: *"review and
> revise this phase thoroughly … enrich the phase and its sub-phases for
> features, improvements, performance, efficiency, stability,
> reliability, and integrity. I particularly look for error-prone and
> flawless Turkish input processing for generic and wrong Turkish
> language uses."*
>
> §10.33 (14th pass) explicitly left a 15th pass on the table in
> [`33-input-flawlessness-and-proof-tests.md`](33-input-flawlessness-and-proof-tests.md)
> §10.33.8 ("Open questions / explicit non-goals … so a hypothetical
> 15th pass starts with the right scope"). §10.34 is that pass.
>
> **Why a 15th pass after fourteen?** The §10.0–§10.33 contract is
> exhaustive on *recognising* messy Turkish (typo, dialect, bidi
> attack, mojibake, slur obfuscation, voice fillers, telegraphic
> input, sarcasm, quotative chains, pro-drop, and so on). It is **not**
> exhaustive on five orthogonal classes that turn an otherwise correct
> recognition pipeline into a wrong, slow, or unstable answer:
>
> 1. **Generic-broken-Turkish input shapes** the prior passes did not
>    enumerate — predictive-text overshoot, OCR/photo-source artefacts,
>    PDF-paste ligatures, mid-word URL pastes, half-typed-then-sent,
>    multi-paragraph mega-input with the question buried at the end,
>    Turkish-suffix-on-emoji, comma-as-apostrophe, suffixed-number
>    redundant restatement (`3 üç`), keyboard-layout-language confusion
>    (US-keyboard typed Turkish without diacritic-restore signal), and
>    random-case noise that the §10.28.8 ALL-CAPS gate does not catch.
> 2. **Performance & efficiency** — the normalize chain has grown to
>    11 ordered passes (§10.1 + §10.21.5 confusables + §10.22 format
>    strip + §10.28.1 consonant tolerance + §10.28.2 assimilation +
>    §10.29.1 geminate + §10.29.7 reduplication + §10.30.10 obfuscated
>    slur + §10.32.4 dialect + §10.33.3 mojibake + §10.33.3 charity).
>    Naïvely, that is `O(n × passes)` per request. Without an explicit
>    perf contract the chain quietly regresses each pass. §10.34 lands
>    a normalize-chain perf budget, a single-pass DFA fast-path for
>    the 80%-clean-Turkish-no-action case, and zero-copy guarantees
>    where the pass is a no-op.
> 3. **Stability under degenerate input** — empty input is handled
>    (§10.24 trail), but single-codepoint input, surrogate-pair-split
>    input across the §10.1 length cap, U+0000 NUL injection, and
>    "control-char-only" input still reach Symspell / CRF / Zemberek
>    in a state those libraries did not anticipate. The pipeline does
>    not crash today (Phase 7 sanitize covers the worst), but it spends
>    real CPU on rubbish and emits ambiguous downstream events.
> 4. **Reliability under partial-component failure mid-request** —
>    §10.10 degradation matrix is exhaustive on *between-request*
>    failures (lexicon down at request start, classifier missing,
>    predict timeout). It is silent on *within-request* failures: CRF
>    process crashes mid-decode, Symspell `mmap`'d page faults under
>    container OOM-throttle, humanizer subprocess returns malformed
>    JSON after token quota burn. Today these surface as 5xx; §10.34
>    pins the per-stage failure → degraded-with-disclosure path so
>    no `qa.request.v1` ever produces a 5xx for an in-pipeline
>    component fault.
> 5. **End-to-end integrity** — §10.31.11 ships an *outbound* checksum
>    proofreader → gateway. There is no symmetric *inbound* integrity
>    chain gateway → NLP. A compromised middleware (or a buggy one)
>    can mutate `qa.request.v1` between Phase 7 sec sanitize and
>    Phase 10 normalize, and §10.21.8 envelope HMAC alone does not
>    catch this (the mutation is upstream of the envelope sign). §10.34
>    closes the loop with an inbound checksum + the §10.31.11 outbound
>    checksum forming a verifiable pre/post pair.
>
> **Mirrors the §10.33 / §9.17 pattern:** prior addenda are the surface
> contract; §10.34 is the *correctness-and-resilience-proof floor*
> underneath. Every `[ ]` here is binding for Phase 10 DoD (added as
> §10.20 DoD item 32). New cfg knobs land alongside §10.19 (in
> [`00-baseline.md`](00-baseline.md)) in the same triangle commit.
>
> **Cross-pass contract (binding).** §10.34 must not silently re-spec
> any prior addendum. When §10.34 strengthens a prior assumption, it
> says so by section number and references the prior text verbatim.
> When §10.34 adds a *new* surface (new wire field, new closed table,
> new gate), it must land in the **same** triangle commit as the
> matching cfg knob in §10.19, the matching DoD bullet in this file
> §10.34.DoD, the matching `make verify.*` target, and (where the new
> surface is cross-language) the matching Phase 7 / Phase 9 byte-parity
> spec under `ai/common/text/` (or its post-Pivot path).

## 10.34.1 Generic-broken-Turkish input shapes (binding)

Each item below names a real-world input shape that prior passes did
not enumerate, the empirical counter-example, the binding correction,
and the proof test. Tests live in
`ai/swarm/agents/nlp/tests/generic_broken_turkish/`.

- [x] **Predictive-text overshoot.** iOS/Android keyboards aggressively
      auto-complete partial Turkish words to nearest dictionary entry,
      often producing a syntactically-valid but semantically-wrong
      sentence (`Galatasaray onları yendi mi` ⇒ keyboard auto-finishes
      to `Galatasaray onları yendir mi` after the user typed `yend`).
      §10.33.3 charity-canonicalization handles violation of vowel
      harmony but not real-word-substitution overshoot. **Correction:**
      add a closed `predictive_text_known_overshoot.tr.yaml` table
      (≥ 50 entries, harvested from a 1000-row mobile-input corpus)
      mapping known overshoot pairs to a per-pair *did-you-mean*
      offer. Runs in §10.1 step 7d AFTER charity AFTER reduplication
      BEFORE classifier; cap `nlp_predictive_overshoot_max_per_query=2`;
      original token preserved in `entities[].morph.predictive_overshoot`.
      Per-pair telemetry `nlp.event.v1{kind=predictive_overshoot_offered}`.
      **Test:** `test_predictive_overshoot_known_pairs` exercises the
      50-row corpus and asserts each row produces the offered correction
      AND the user's original is preserved in the audit field.

- [ ] **OCR / photo-source artefacts.** Users paste from screenshots,
      PDFs, or photos of betting slips. The pasted text contains the
      classic OCR confusion classes — `0/O`, `1/l/I/!`, `5/S`, `8/B`,
      `rn/m`, soft-hyphen line-breaks (`Gala-\nbsaray`), and ligatures
      (`ﬁnal`, `ﬂora`). None are caught by §10.21.5 confusables (which
      handles cross-script not within-script OCR). **Correction:** new
      §10.1 step 6.6 `ocr_confusion_repair` runs ONLY when the input
      contains at least one ligature codepoint OR ≥ 1 soft-hyphen OR
      `nlp_ocr_repair_force=true` (default `false` so we do not pay
      the cost on every clean keyboard input); table-driven via
      `ocr_confusables.tr.yaml` (≥ 30 confusion classes); each
      candidate substitution is admitted only if the resulting token
      is in the lexicon AND the original is not (defends against
      `1-1` score being miscanonicalised to `l-l`). Soft-hyphen + `\n`
      sequence collapsed to nothing. Ligatures expanded
      (`ﬁ`→`fi`, `ﬂ`→`fl`, `ﬃ`→`ffi`, …). **Tests:**
      `test_ocr_ligature_expand` (40 rows), `test_ocr_softhyphen_collapse`
      (25 rows), `test_ocr_no_repair_on_clean_input` (1000 rows assert
      zero invocations + zero allocs).

- [ ] **PDF-paste artefacts (distinct from OCR).** PDF copy-paste
      preserves original layout — line-breaks mid-sentence, NBSP as
      space, U+2028 line separator, U+2029 paragraph separator, hard
      hyphenation at line ends, and **column tear** (`Galatasaray\n
      Fenerbahçe` where the second column was a different team). NBSP
      is already handled (§10.33.3); the rest are not.
      **Correction:** §10.1 step 6.5 `paste_layout_normalize` collapses
      U+2028, U+2029, U+000C (form feed) to U+000A; collapses
      `<word>-\n<word>` (hard hyphen at line break) to `<word><word>`
      iff the joined form is in the lexicon; rejects column-tear
      (≥ 2 newlines + ≥ 2 known-team mentions on different lines)
      and routes to `meta.multi_input_clarification_required` (NEW
      meta intent — closed Turkish disambiguation). Cap
      `nlp_paste_max_newlines=4`; over-cap routes to the run-on-multi-q
      splitter at §10.24.5. **Tests:** `test_paste_layout_unicode_breaks`
      (30 rows), `test_paste_hard_hyphen_join_only_when_lexical` (40
      rows half lexical / half not), `test_paste_column_tear_routes_meta`
      (20 rows).

- [ ] **Mid-word URL paste.** `Galatasarayhttps://example.com/maçı` —
      the user copied a partial URL and concatenated it inadvertently.
      §10.33.3 `nlp_strip_urls` handles standalone URLs but not URLs
      glued to a token. **Correction:** before §10.33.3 URL strip,
      run a URL boundary detector that splits at the URL boundary
      (`http`/`https`/`ftp`/`www\.` start), strips the URL portion,
      and feeds the residue back into normalize. If the residue is
      empty AND the URL was the whole input → `meta.url_only_input`
      template (closed Turkish "Sadece bir bağlantı gönderdiniz; metin
      olarak ne sormak istediğinizi yazar mısınız?"). **Tests:**
      `test_url_glued_to_token_split` (40 rows), `test_url_only_input`
      (15 rows).

- [ ] **Half-typed-then-sent.** User types `Gala` and accidentally hits
      send (mobile fat-finger on the send button). Today the pipeline
      classifies this as low-confidence + offers did-you-mean, but the
      did-you-mean offer is wasteful — the user was almost certainly
      mid-typing a famous club. **Correction:** detect via composite
      heuristic (token count = 1 AND token is a strict prefix of ≥ 1
      lexicon entry AND lexicon entry is in §10.0 top-100-frequency
      tier AND classifier confidence < `nlp_low_confidence_floor`);
      route to NEW `meta.likely_partial_input` template ("`Gala`
      yazdınız — *Galatasaray* mı demek istediniz, yoksa başka bir
      şey mi?") with at most 3 closed completions ranked by frequency.
      Bypasses generic did-you-mean. Telemetry
      `nlp.event.v1{kind=partial_input_completion_offered}`.
      **Tests:** `test_partial_input_offer_top3_completions` (50 rows),
      `test_partial_input_no_offer_when_token_too_short` (asserts
      `len < nlp_partial_input_min_token_len=3` skips the path).

- [ ] **Multi-paragraph mega-input with question at end.** Users paste
      news articles, betting forum posts, or chat-history dumps and
      append `bence Galatasaray kazanır mı?` at the bottom. §10.1 step
      0 length cap drops the **head** of the input (or the tail —
      undefined today!). **Correction:** §10.1 step 0a (NEW, before
      length cap) detects multi-paragraph input (≥ 3 paragraph
      separators OR length > `nlp_megainput_min_chars=1500`); extracts
      the **last paragraph** as the question candidate; preserves the
      preceding text in `entities[].context_dump_sha256` (sha256 only,
      never raw — PII discipline) for audit. If the last paragraph is
      itself > length cap, falls back to standard length-cap behaviour
      with telemetry `nlp.event.v1{kind=megainput_tail_extracted,
      context_dump_chars=<n>}`. AST guard `test_megainput_never_persists_raw_dump`.
      **Tests:** `test_megainput_extracts_last_paragraph` (35 rows),
      `test_megainput_short_input_unchanged` (200 rows clean input
      assert zero step-0a invocations).

- [ ] **Turkish-suffix-on-emoji.** `⚽nın`, `🟡🔴'a`, `🦅cilik` — users
      treat emoji as a noun and suffix-mark them. §10.33.3 strips
      emoji wholesale, which destroys the suffix evidence. **Correction:**
      promote suffixed-emoji to a *typed entity* — detect emoji + apostrophe
      + Turkish suffix; map closed `emoji_to_concept.tr.yaml` (≥ 30
      entries: `⚽`→`maç`/`futbol`, `🟡🔴`→`Galatasaray`,
      `🟢🟡`→`Bursaspor`, `🦅`→`Beşiktaş`, …); produce a typed entity
      with `kind=concept_via_emoji, original_emoji=<codepoint>, canonical=<concept>`;
      then strip the emoji as before. Confidence cap 0.65 — never used
      as sole entity; always offered for confirmation. **Tests:**
      `test_emoji_with_suffix_promoted_to_concept` (30 rows),
      `test_emoji_without_suffix_still_stripped` (50 rows assert
      §10.33.3 path unchanged).

- [ ] **Apostrophe-replaced-by-comma / dot / backtick.** Cheap mobile
      keyboards autocorrect `'` to `,` for half a key press; some
      Turkish layouts put `.` where US layouts put `'`. The §10.32.5
      apostrophe-suffix repair assumes the apostrophe is *missing*,
      not *substituted*. **Correction:** extend the §10.32.5 spec
      with a punctuation-substitution rule: if `,` or `.` or `\``
      appears between a known proper-noun prefix and a Turkish suffix
      sequence, treat as if it were `'` and emit
      `nlp.event.v1{kind=apostrophe_punctuation_substituted, found=<char>}`.
      **Tests:** `test_apostrophe_comma_substitute` (60 rows),
      `test_apostrophe_backtick_substitute` (30 rows),
      `test_apostrophe_substitute_negative_does_not_fire_in_lists`
      (30 rows: `Galatasaray, Fenerbahçe, Beşiktaş` — comma after
      proper noun is a list separator, not an apostrophe substitute;
      heuristic: must be IMMEDIATELY followed by a Turkish-suffix
      character class with no space).

- [ ] **Number-spelled-twice (redundant restatement).** `3 üç maç`,
      `1 bir gol`, `2-1 iki bir biten maç` — the user repeats the
      digit as a word for emphasis or speech-to-text artefact. §10.32.7
      handles digit-with-suffix; this is digit followed by its
      number-word twin. **Correction:** detect via closed
      `numeric_redundant_restatement.tr.yaml` (closed bijective
      `digit ↔ number_word` table + adjacency rule); collapse to the
      digit form and drop the word; emit
      `nlp.event.v1{kind=numeric_redundant_collapsed}`. **Tests:**
      `test_numeric_redundant_collapse` (40 rows),
      `test_numeric_non_redundant_preserved` (40 rows: `3 maçlık seri`
      contains digit + non-restating word, must NOT collapse).

- [ ] **Random-case noise (beyond ALL-CAPS).** `gAlAtAsArAy MaÇı`,
      `gALATASARAY`, `Galatasaray FENERBAHÇE`. §10.28.8 covers
      ALL-CAPS shouting; mixed-case with > 30% case flips inside
      tokens is not covered. **Correction:** detect via per-token
      `case_flips_per_char` ratio > `nlp_random_case_threshold=0.30`;
      casefold the offending tokens (Turkish locale, §10.33.1) BEFORE
      gazetteer match; preserve the original-case form in
      `entities[].original_text` (mirrors §10.21.5 audit trail);
      disable §10.5 capitalization-as-entity-hint on those tokens
      (mirrors §10.28.8 / §10.26.2 voice path). Telemetry
      `nlp.event.v1{kind=random_case_normalized}`. **Tests:**
      `test_random_case_intra_token_folded` (40 rows),
      `test_random_case_inter_token_unaffected_when_each_is_titled`
      (40 rows assert proper Title Case is left alone).

- [ ] **Single-emoji-only input.** `⚽?`, `🟡🔴`, `🤔`. Today routes to
      did-you-mean. **Correction:** new §10.4 step `single_emoji_intent`
      runs before classifier; closed `single_emoji_intent.tr.yaml`
      (≥ 20 entries: `⚽` → "Bugünkü maçlar?" disambiguation,
      `🟡🔴` → "Galatasaray hakkında ne sormak istiyorsunuz?",
      `🤔` → ack template); each entry produces a closed Turkish
      clarification offer (NEVER auto-routes to a real intent).
      **Tests:** `test_single_emoji_clarification_offered` (20 rows).

- [ ] **Ambiguous date format.** `3/4/2025` is April 3 in TR convention
      (DD/MM/YYYY) but March 4 in US convention. The §10.5 CRF date
      extractor today picks one silently. **Correction:** when both
      readings are valid (both ≤ 12), do NOT silently pick — emit
      `nlp.event.v1{kind=date_format_ambiguous}` and route to
      `meta.date_disambiguation_required` (NEW meta intent) with the
      two candidate dates rendered Turkish ("3 Nisan 2025" vs
      "4 Mart 2025"). When one reading > 12 (`13/4/2025`), the
      disambiguation is unique → use it without ambiguity. **Tests:**
      `test_date_ambiguous_routes_disambiguation` (30 rows),
      `test_date_unambiguous_picks_unique` (60 rows),
      `test_date_dotted_form_unambiguous` (`3.4.2025` is TR-only by
      convention, picks DD.MM.YYYY without ambiguity, 30 rows).

- [ ] **Time-of-day shorthand.** `aks` for `akşam`, `sbh` for `sabah`,
      `öğl` for `öğle`, `gec` for `gece`. The §10.5 CRF time extractor
      relies on full forms. **Correction:** closed
      `time_of_day_shorthand.tr.yaml` (≥ 15 entries) folded in §10.1
      step 7c.5 BEFORE CRF; original preserved in audit. **Tests:**
      `test_time_shorthand_expanded` (15 rows × 2 contexts each = 30).

- [ ] **Implicit user time-zone.** User in Berlin types `bugün` at
      00:30 local time = 22:30 UTC = still "yesterday" in
      Europe/Istanbul where the system computes "bugün". §10.26.4
      pins Europe/Istanbul as the system clock. **Correction:** if
      `request_metadata.client_tz` is present (Phase 9 forwards from
      the `Accept-Datetime` or a custom `X-Client-TZ` header), resolve
      `bugün`/`dün`/`yarın` against it; otherwise default to
      Europe/Istanbul AND emit
      `nlp.event.v1{kind=client_tz_assumed_default}` so a downstream
      product surface can prompt for time-zone confirmation if the
      query produces an empty data set. AST guard
      `test_nlp_client_tz_never_logs_or_caches_geolocation`
      (`client_tz` is NOT geolocation but adjacent — discipline keeps
      it strictly time-only). **Tests:**
      `test_relative_date_resolves_against_client_tz` (40 rows × 4
      time-zones), `test_relative_date_default_when_tz_absent`
      (20 rows).

- [ ] **Turkish-keyboard-layout language confusion.** US-keyboard
      users typing Turkish without a TR keyboard produce inputs with
      no diacritics AT ALL (not even occasional ones — §10.22 §10.33
      assume sporadic loss). The §10.3 diacritic restorer handles
      sporadic loss but degrades on systematic loss because the
      diacritic-restore table cannot disambiguate every plain-ASCII
      token. **Correction:** detect "systematic loss" via
      `non_ascii_ratio < nlp_systematic_diacritic_loss_threshold=0.02`
      AND token count > 3; switch the diacritic restorer from
      "frequency tie-break" to "lexicon-vs-LeagueCatalog tie-break"
      (prefer the candidate that matches a known proper-noun); cap
      `nlp_systematic_loss_max_lookups=20` (vs. baseline 8). Tag the
      request with `request_metadata.input_class=systematic_diacritic_loss`
      so the proofreader can prepend a one-time disclosure
      ("Türkçe karakter olmadan yazdığınızı varsayıyorum…") on the
      first turn of a conversation. **Tests:**
      `test_systematic_diacritic_loss_detected_and_classified` (60
      rows of all-ASCII Turkish), `test_sporadic_loss_unchanged_path`
      (200 rows assert §10.3 baseline path).

- [ ] **Comma-separated multi-entity query without conjunction.**
      `Galatasaray, Fenerbahçe maçları` — comma + space + space-less
      proper noun is a Turkish coordinated-noun construction §10.32.6
      handles only with `ile`/`ve`/`veya`. **Correction:** extend
      §10.29.8 coordinator detector with comma-as-coordinator rule:
      ≥ 2 known proper nouns separated by `, ` with no conjunction →
      treat as `ve`-coordination; produces multi-entity fan-out per
      §10.29.8. Defends against the alternative misreading
      ("Galatasaray, Fenerbahçe'nin rakibidir" = vocative + comment).
      Disambiguation rule: if the second proper noun is followed by
      a Turkish suffix that requires the first noun as antecedent,
      treat as vocative+comment (NO fan-out). **Tests:**
      `test_comma_coordinator_fans_out` (30 rows),
      `test_comma_vocative_does_not_fan_out` (20 rows).

## 10.34.2 Performance, efficiency, and stability (binding)

The normalize chain has grown to 11 ordered passes across §10.1 +
§10.21 + §10.22 + §10.28 + §10.29 + §10.30 + §10.32 + §10.33. Without
an explicit perf contract it quietly regresses each addendum. §10.34.2
lands the contract.

- [ ] **Normalize-chain perf budget (binding).** Per-pass p50/p99
      budgets in `normalize_perf_budgets.yaml` (closed table; CODEOWNERS
      = nlp-curator + Go owner because Phase 7 sec-sanitize must obey
      the same budgets on its parity passes). Per-pass budgets sum to
      a total `nlp_normalize_total_budget_p99_ms=12` (vs. the §10.1
      original 5ms — addenda took us to 11 passes; we cap at 12ms p99
      so the §10.31.12 `slo_fast` 250ms budget retains headroom). Per
      pass: NFC ≤ 0.3ms, locale-cased lowercase ≤ 0.2ms, format-char
      strip ≤ 0.4ms, confusables ≤ 0.6ms, mojibake (no-op fast path)
      ≤ 0.05ms / (recovery path) ≤ 1.0ms, OCR repair (gated, default
      no-op fast path) ≤ 0.05ms / (gated path) ≤ 0.8ms, paste-layout
      ≤ 0.2ms, charity ≤ 1.5ms, geminate ≤ 0.4ms, dialect ≤ 0.6ms,
      typo (Symspell) ≤ 3.0ms, idiom expand ≤ 0.5ms. **Test:**
      `test_normalize_per_pass_budgets` runs each pass standalone over
      the §10.18 evaluation harness golden corpus and asserts p99.
      Regression CI gate on PRs touching `ai/swarm/agents/nlp/normalize/**`.

- [ ] **Single-pass DFA fast-path for clean input.** Empirically ~80%
      of input is already NFC + Turkish-locale-lowercase + no
      confusables + no format chars + no mojibake + no ligatures + no
      bidi controls + no paste artefacts. Today every request runs
      every pass. **Correction:** new
      `ai/swarm/agents/nlp/normalize/fast_path.py` runs a single-pass
      DFA scan that asserts `clean_input_invariant`: every codepoint
      is in the cleanest pass-through class (printable ASCII OR
      printable Turkish OR ASCII space/punct). On match, skip every
      transformation pass and emit
      `nlp.event.v1{kind=normalize_fast_path_taken}`. On any miss, fall
      back to the full chain. Cap the fast-path codepoint scan at
      `nlp_fast_path_max_chars=cfg.nlp_input_max_len` (no point-of-no-return
      — the scan is `O(n)` and bounded by the same cap). **Test:**
      `test_normalize_fast_path_matches_full_chain` runs the full
      §10.18 corpus through both paths and asserts byte-identical
      output on the clean subset (zero divergence) AND zero allocs
      on fast-path beyond the input string (`testing.AllocsPerRun`
      analogue: `tracemalloc.get_traced_memory()` delta < 256 bytes).

- [ ] **Zero-copy guarantee on no-op passes.** When a pass detects no
      action is needed (e.g. mojibake recovery on input that decodes
      cleanly the first time), it MUST return the same string object
      (`s is input`), not a copy. Today some passes do `s.translate({})`
      or `''.join(s)` which silently allocates. **Correction:** every
      normalize pass exposes a `def changed(s: str) -> bool` predicate
      called BEFORE the transformation. Linter rule
      `xops/lint/no_unconditional_string_translate.py` AST-rejects
      bare `.translate(...)`/`.join(...)` inside `nlp/normalize/**`
      without a preceding `if changed(s)` guard. **Test:**
      `test_normalize_zero_copy_on_clean_input` walks the §10.18
      clean subset and asserts `id(out) == id(inp)` after each
      no-action pass.

- [ ] **CRF / Symspell / Zemberek model warm-mmap.** Today these are
      loaded on first request (cold-start path). §10.21.9 covers
      6-stage boot but the readiness probe at stage 6 only asserts
      *loaded* not *warm-mmapped* — the OS may still page-fault on
      first read. **Correction:** stage 6+ adds `mlock`-ish warm-touch:
      iterate every page of the loaded model files (`os.posix_madvise`
      with `MADV_WILLNEED` then a 1-byte read per page). Cap
      `nlp_model_warm_touch_max_pages=cfg.nlp_pod_rss_max_mb * 256`
      so a too-large model on a too-small pod cannot OOM during boot.
      On cap exceeded → emit
      `nlp.alert.v1{kind=model_warm_touch_capped, severity=warn}` and
      proceed (warm-touch is a perf optimisation, not a correctness
      gate). **Test:** `test_model_first_request_no_page_fault_p99`
      runs a 100-request burst right after readiness=200 and asserts
      p99 < 1.5× steady-state (today p99 is ~5× steady-state on
      first 50 requests).

- [ ] **Stability: empty + single-codepoint + surrogate-split input.**
      §10.24 covers empty/whitespace at the application layer but
      degenerate input still reaches Symspell / CRF / Zemberek at the
      tokenizer layer. **Correction:** new `ai/swarm/agents/nlp/normalize/degenerate_input.py`
      hard-rejects, before *any* pass, input matching: `len(s) == 0`,
      `len(s.strip()) == 0`, `len(s) == 1 AND s in unicodedata.category("C*")`,
      `s contains a lone surrogate (U+D800..U+DFFF)`, `s contains U+0000`.
      All five cases route to closed Turkish refusal templates
      (`meta.empty_input`, `meta.control_only_input`,
      `meta.malformed_input`); none ever invoke Symspell / CRF /
      Zemberek. AST guard `test_nlp_degenerate_input_short_circuits_before_normalize`.
      **Tests:** `test_degenerate_empty` (5 rows × 5 cases),
      `test_degenerate_lone_surrogate` (10 rows: each surrogate
      codepoint variant), `test_degenerate_nul_byte` (5 rows),
      `test_degenerate_control_only` (10 rows: every `Cc` codepoint
      family).

- [ ] **Stability: surrogate-pair split across length cap.** The
      §10.1 step 0 length cap operates on `len(s)` (codepoint count
      in Python, but byte count if the Phase 7 sec layer measures
      bytes). If the cap falls between the high and low surrogate of
      a non-BMP character, the resulting string is malformed.
      **Correction:** length cap MUST snap to the nearest codepoint
      boundary (always lowering) AND nearest grapheme-cluster boundary
      (lowering by ≤ 4 codepoints). Cap snap behaviour pinned in
      `ai/common/text/length_cap_spec.json` (cross-language byte-parity
      with Phase 7 sec layer; refuse boot on SHA mismatch). **Test:**
      `test_length_cap_never_splits_surrogate_or_grapheme` walks a
      200-row corpus of inputs whose nominal-cap-position falls inside
      a surrogate pair OR inside a `(letter, combining)` cluster and
      asserts the output is well-formed.

- [ ] **Stability: Symspell pathological-input cap.** Symspell edit
      distance 2 on a 30-char token produces a candidate explosion
      (~30² = 900 candidates per token). §10.3 caps lookups per query
      at 8 but a single very-long token with no spaces (mobile no-space
      compound — see §10.28.3) bypasses the per-query cap because it
      counts as 1 lookup. **Correction:** add per-token edit budget
      cap: token `len > nlp_typo_long_token_threshold=18` automatically
      lowers edit budget to 1 (was 2); `len > 24` lowers to 0 (typo
      pass skipped; falls through to compound-splitter §10.28.3 first).
      Telemetry `nlp.event.v1{kind=typo_long_token_budget_clamped}`.
      **Tests:** `test_typo_long_token_budget_clamp` (30 rows),
      `test_typo_pathological_input_under_5ms` (15 rows of 50-char
      no-space tokens, each must complete in < 5ms).

- [ ] **Lexicon load: bounded hash collision under malicious aliases.**
      A lexicon contributor (Phase 13a) could insert ≥ 200 aliases
      that all collide on the hash bucket the gazetteer uses; lookup
      degrades from `O(1)` to `O(n)` per token. **Correction:** boot-time
      `test_lexicon_alias_hash_distribution` asserts the per-bucket
      load factor stays below `nlp_lexicon_max_collision_load=8`; on
      violation, emit `nlp.alert.v1{kind=lexicon_collision_load_high,
      severity=error}` and refuse the lexicon swap (keeps prior
      generation). **Test:** the test itself plus a synthetic
      adversarial fixture (`tests/fixtures/adversarial_collision_lexicon.yaml`)
      that the loader must reject.

## 10.34.3 Reliability under partial-component failure (binding)

§10.10 degradation matrix is exhaustive on between-request failures.
§10.34.3 closes the within-request gaps.

- [ ] **In-flight stage timeout (per-stage budget).** Each pipeline
      stage gets a timeout from `nlp_stage_budgets_ms.yaml` (closed
      table, CODEOWNERS = nlp-curator). On timeout, the stage's output
      degrades to a closed default + `qa.answer.v1.degraded=true` +
      `degraded_reason=stage_timeout:<stage>` + telemetry
      `nlp.event.v1{kind=stage_timeout_degraded}`. NEVER 5xx. Stage
      list (binding): `normalize`, `idiom_expand`, `intent_classify`,
      `entity_extract`, `pragmatic_class`, `dispatch`, `template_render`,
      `humanize` (already breaker'd §10.8), `proofreader_input_gates`,
      `proofreader_output_grammar` (§10.31.8), `outbound_sign`. Defaults:
      normalize timeout ⇒ raw input forwarded with
      `meta.normalize_timeout` template; intent_classify timeout ⇒
      `meta.classifier_timeout` (closed Turkish); template_render
      timeout ⇒ pre-baked safe template; outbound_sign timeout ⇒
      block ship + critical alert (integrity > availability for the
      sign step). **Test:** `test_stage_timeout_matrix` injects a
      timeout at each stage (10 rows) and asserts `qa.answer.v1.degraded=true`
      + correct `degraded_reason` + 200 (never 5xx).

- [ ] **CRF subprocess crash mid-decode.** `python-crfsuite` is in-process
      but `pycrfsuite` calls into a C extension that can SIGSEGV under
      malformed model files (e.g. §10.34.2 mmap page-fault during
      eviction). **Correction:** wrap CRF decode in
      `multiprocessing.Process` with `nlp_crf_subprocess_enabled=true`
      (default `false` at v1 — opt-in escape hatch); on crash, fall
      back to gazetteer-only entity extraction + emit
      `nlp.alert.v1{kind=crf_subprocess_crashed, severity=error}` +
      `qa.answer.v1.degraded=true, degraded_reason=crf_unavailable`.
      The opt-in default is `false` at v1 because subprocess-per-request
      is too expensive; the flag exists so an operator can enable it
      during a known-bad model rollout. **Test:**
      `test_crf_subprocess_crash_degrades_gracefully` mocks
      `pycrfsuite.Tagger.tag` to raise `MemoryError` and asserts the
      degraded path.

- [ ] **Symspell mmap page-fault under OOM throttle.** Container OOM
      throttle (cgroup `memory.high` reached) causes mmap'd pages to
      be reclaimed; next access page-faults at 50–500ms latency.
      **Correction:** wrap Symspell lookup in a `signal.setitimer`
      stage timeout (covered by §10.34.3 stage timeout above) AND
      monitor cgroup `memory.pressure` via Phase 11 device probe — if
      pressure > `nlp_memory_pressure_alert_threshold=0.5` for > 30s,
      emit `nlp.alert.v1{kind=memory_pressure_high, severity=warn}`
      and disable typo correction (gracefully — input passes through
      as-is) for `nlp_memory_pressure_typo_disable_s=60`. **Test:**
      `test_typo_disabled_under_memory_pressure_alert` (synthetic
      pressure injection via fakefs cgroup).

- [ ] **Humanizer subprocess returns malformed JSON after token quota
      burn.** §10.8 humanizer sub-process is supposed to return a
      JSON envelope with the rephrased text. Under a token quota burn
      it sometimes returns truncated JSON. **Correction:** on
      `json.JSONDecodeError`, log the first 256 bytes of the response
      (PII-sha256'd via §10.21.7), increment
      `nlp.event.v1{kind=humanizer_malformed_response}`, fall back
      to template-only output (humanizer-bypassed). NEVER raise
      JSONDecodeError to the caller. **Test:**
      `test_humanizer_malformed_json_falls_back_to_template` (10 rows
      of malformed responses).

- [ ] **Lexicon-swap mid-request.** A `nlp.lexicon-deploy` (§10.27.9)
      lands while a request is in-flight. The request started with
      gen N, the dispatcher is using gen N+1 mid-response. Audit
      `lexicon_snapshot_sha` is now ambiguous. **Correction:** every
      request captures the lexicon-pointer snapshot at §10.1 step 0
      and HOLDS that snapshot for the duration of the request (refcount
      via §10.21.2 retain-2 mechanism). Audit field
      `request_lexicon_sha` records the held snapshot, not "current".
      **Test:** `test_lexicon_swap_mid_request_audit_uses_held_sha`
      (synchronously triggers a swap mid-request via a barrier; asserts
      the audit row records the pre-swap SHA).

- [ ] **Catastrophic regex backtracking.** Any closed pattern table
      (`injection_patterns.yaml`, `obfuscated_slur.yaml`,
      `idioms.tr.yaml`, `score_notation_conventions.yaml`, …) added
      across the 14 prior passes can introduce a catastrophic-backtracking
      regex (RE2 only handles linear patterns; Python `re` does NOT
      use RE2 by default). **Correction:** boot-time
      `test_no_catastrophic_backtracking_patterns` walks every closed
      pattern file and runs each pattern against a synthetic
      adversarial input (`a` × N for N ∈ {10, 100, 1000, 10000}); any
      pattern whose run time scales worse than O(N²) is rejected at
      boot via `nlp.alert.v1{kind=pattern_catastrophic_backtracking,
      severity=critical}` and the pattern table swap is refused
      (keeps prior generation). **Test:** the boot-time test plus a
      synthetic adversarial fixture
      (`tests/fixtures/adversarial_backtracking_pattern.yaml`).

- [ ] **Spool replay reliability.** §10.13 covers bus-down spooling
      but not the "spool flushed during a partial bus recovery"
      scenario where bus accepts the publish but the broker drops it
      silently (no NACK, just no consumer ever sees it). **Correction:**
      spool replay records the publish-confirmed sequence number from
      the broker (`MULTI/EXEC` reply's stream entry ID). On replay
      success, the spool entry is moved to `data/nlp/spool/.replayed/`
      with the broker entry-ID stamped; a periodic
      `nlp.alert.v1{kind=spool_replay_unconsumed, severity=warn}`
      fires if the stream entry ID is not consumed by any group within
      `nlp_spool_replay_consumed_grace_s=60`. **Test:**
      `test_spool_replay_unconsumed_alerts_within_grace`.

- [ ] **Graceful shutdown drains in-flight humanizer subprocesses.**
      §10.21.9 covers shutdown drain for the main process but not the
      humanizer subprocesses. **Correction:** SIGTERM to main →
      send SIGTERM to every active humanizer subprocess → wait
      `nlp_humanizer_shutdown_grace_s=5` for graceful exit → send
      SIGKILL to stragglers. Spool any unfinished humanize result
      under `data/nlp/spool/humanizer/` for the next pod's reactor
      to pick up (or drop with `nlp.alert.v1{kind=humanizer_shutdown_dropped}`
      if the request_id deduper says the answer was already shipped
      template-only). **Test:**
      `test_graceful_shutdown_drains_humanizer_subprocesses`.

## 10.34.4 End-to-end integrity: inbound checksum chain (binding)

§10.31.11 ships an outbound checksum proofreader → gateway. There is
no symmetric inbound integrity. §10.34.4 closes the loop.

- [ ] **Inbound checksum field on `qa.request.v1`.** Phase 9 gateway
      computes `inbound_checksum = sha256(canonical_json(body excluding self) || inbound_secret_per_pod)`
      after Phase 7 sec sanitize and BEFORE publishing to the bus.
      Field is added to `qa.request.v1` schema additively
      (`schema_version=4` → `5` once §10.32.18 lands). NLP verifies
      the checksum at §10.1 step 0; mismatch → drop request +
      `nlp.alert.v1{kind=inbound_checksum_mismatch, severity=critical}` +
      RFC 7807 `504` to gateway. `inbound_secret_per_pod` rotates on
      §7 sec rotation 90-day cadence; key-id stamped per §10.21.8
      pattern. **Test:** `test_inbound_checksum_mismatch_drops_request`
      (synthetic mutation of the body between gateway sign and NLP
      verify).

- [ ] **Inbound + outbound form a verifiable pair.** Audit row records
      both `inbound_checksum` (verified) AND `outbound_checksum`
      (signed) so a forensic complaint trace (§10.27.3) can prove
      the request body the user sent matches the answer body the
      user received with no in-pipeline mutation. **Test:**
      `test_audit_records_both_checksums_for_pair_replay`.

- [ ] **Per-pod-secret rotation: two-key window.** During the 24h
      grace window after `make nlp.rotate-inbound-key`, NLP accepts
      both the old and the new key; gateway publishes with the new
      key. After the grace window, old-key checksums are rejected.
      Mirrors the §10.21.8 citation HMAC rotation pattern verbatim.
      **Test:** `test_inbound_checksum_dual_key_window` (asserts both
      old-key and new-key requests succeed during the window; only
      new-key after).

- [ ] **AST guard: NLP never reads `inbound_secret` from anywhere
      other than `cfg.nlp_inbound_secret_path` (mode 0400).** Mirrors
      §10.21.8 + §10.31.11 secret-handling discipline. **Test:**
      `test_nlp_inbound_secret_only_read_from_cfg_path` (AST scan).

## 10.34.5 New cross-language byte-parity specs

Six new specs land under `ai/common/text/` (or post-Pivot path), each
mirroring the §10.21.5 / §10.29.11 / §10.32.5 / §10.33.5 pattern:

- [ ] `length_cap_spec.json` (§10.34.2 surrogate / grapheme snap rules).
- [ ] `ocr_confusables_spec.json` (§10.34.1 OCR repair table).
- [ ] `paste_layout_spec.json` (§10.34.1 PDF / paste layout chars).
- [ ] `single_emoji_intent_spec.json` (§10.34.1 single-emoji map).
- [ ] `emoji_to_concept_spec.json` (§10.34.1 suffixed-emoji map).
- [ ] `time_of_day_shorthand_spec.json` (§10.34.1).

For each: Python NLP and Go gateway boot-probe SHA + refuse on mismatch
with `nlp.alert.v1{kind=cross_lang_spec_sha_mismatch, severity=critical}`.
`make verify.nlp-cross-lang-parity` extends to a 1500-row corpus
covering all six new specs (was 1000 rows in §10.33.5).

## 10.34.6 Adversarial corpus discipline (extends §10.33.4)

Each new closed table introduced in §10.34.1 + §10.34.4 ships its own
`corpus.yaml` per the §10.33.4 discipline:

- [ ] `predictive_text_known_overshoot.tr.yaml` (≥ 50 rows;
      reviewers = nlp-curator + nlp-domain-football)
- [ ] `ocr_confusables.tr.yaml` (≥ 30 rows; reviewers = nlp-curator)
- [ ] `paste_layout_spec.json` corpus (≥ 50 rows; reviewers = nlp-curator)
- [ ] `single_emoji_intent.tr.yaml` (≥ 20 rows; reviewers = nlp-curator + nlp-compliance,
      since emoji-to-concept can encode unintended slurs)
- [ ] `emoji_to_concept.tr.yaml` (≥ 30 rows; reviewers = nlp-curator + nlp-domain-football)
- [ ] `time_of_day_shorthand.tr.yaml` (≥ 15 rows; reviewers = nlp-curator)
- [ ] `numeric_redundant_restatement.tr.yaml` (≥ 40 rows; reviewers = nlp-curator)
- [ ] `apostrophe_punctuation_substituted.tr.yaml` (≥ 90 rows;
      reviewers = nlp-curator)

`make verify.nlp-corpora` extends to all 8 new corpora; per-corpus
regression budget `nlp_corpus_drift_threshold_pct=1.0` (mirrors §10.33).

## 10.34.7 New cfg knob inventory (≥ 20 knobs)

All land alongside §10.19 (in `00-baseline.md`) in the same triangle
commit:

- `nlp_predictive_overshoot_max_per_query=2`
- `nlp_ocr_repair_force=false`
- `nlp_paste_max_newlines=4`
- `nlp_megainput_min_chars=1500`
- `nlp_partial_input_min_token_len=3`
- `nlp_random_case_threshold=0.30`
- `nlp_systematic_diacritic_loss_threshold=0.02`
- `nlp_systematic_loss_max_lookups=20`
- `nlp_normalize_total_budget_p99_ms=12`
- `nlp_fast_path_max_chars=cfg.nlp_input_max_len`  # alias, not a knob
- `nlp_typo_long_token_threshold=18`
- `nlp_lexicon_max_collision_load=8`
- `nlp_model_warm_touch_max_pages=cfg.nlp_pod_rss_max_mb * 256`
- `nlp_crf_subprocess_enabled=false`
- `nlp_memory_pressure_alert_threshold=0.5`
- `nlp_memory_pressure_typo_disable_s=60`
- `nlp_humanizer_shutdown_grace_s=5`
- `nlp_spool_replay_consumed_grace_s=60`
- `nlp_inbound_secret_path=` (env-only, mode-0400)
- `nlp_inbound_checksum_required=warn` (default warn at v1; enforce
  post-Phase-14, mirroring §10.29.12 / §10.21.8 rollout pattern)
- `nlp_inbound_secret_max_age_days=90`

## 10.34.8 New event / alert kinds (open-enum, mirrors §7.4 doctrine)

`nlp.event.v1` kinds:

- `predictive_overshoot_offered`
- `paste_layout_normalized`
- `megainput_tail_extracted`
- `partial_input_completion_offered`
- `apostrophe_punctuation_substituted`
- `numeric_redundant_collapsed`
- `random_case_normalized`
- `date_format_ambiguous`
- `client_tz_assumed_default`
- `normalize_fast_path_taken`
- `typo_long_token_budget_clamped`
- `stage_timeout_degraded`
- `humanizer_malformed_response`
- `humanizer_shutdown_dropped`

`nlp.alert.v1` kinds:

- `model_warm_touch_capped` (warn)
- `lexicon_collision_load_high` (error)
- `crf_subprocess_crashed` (error)
- `memory_pressure_high` (warn)
- `pattern_catastrophic_backtracking` (critical)
- `spool_replay_unconsumed` (warn)
- `inbound_checksum_mismatch` (critical)

Producer-set bound test (§10.21 pattern) re-asserted: NLP plane only.
Each carries `event_correlation_id` per §8.16.9 + §10.32.18.

## 10.34.9 Cross-phase notes (informational)

- **Phase 7 (security input plane).** §10.34.4 inbound checksum is the
  primary new contract: the gateway is the producer, NLP is the
  consumer. The two implementations share `inbound_secret_path`
  resolution rules but never share the secret in memory across
  language boundaries. §10.34.2 `length_cap_spec.json` is shared.
  §10.34.5 adds 6 new spec SHA pins to the existing Phase 7 boot
  parity gate.
- **Phase 8 (operator console).** Visualisation surfaces for the new
  event/alert kinds; no new opsctl subcommands required.
- **Phase 9 (API gateway).** Implements `inbound_checksum` computation
  and adds an outbound RFC 7807 `504` mapping for
  `inbound_checksum_mismatch`. Per-intent SLO classes (§10.31.12)
  absorb the new degraded paths under existing `slo_fast` budget.
- **Phase 11 (compute).** §10.34.2 model warm-touch and §10.34.3
  memory-pressure paths integrate with the device probe;
  CPU-only AST guard re-asserted on the new normalize fast-path
  module.
- **Phase 13a (LeagueCatalog + lexicon).** §10.34.2 lexicon collision
  load gate adds a build-time check on the lexicon emitter pipeline;
  Phase 13a inherits as an additional promotion gate.
- **Phase 14 (K8s).** Stage timeouts (§10.34.3) deepen the readiness
  contract: a pod with an *enforced* (not warn) `stage_timeout_degraded`
  rate above `nlp_stage_timeout_max_pct=2.0` for `60s` flips
  readiness=503 (capacity-shed signal, not crash).
- **Phase 16 (datasource → swarm emitter).** No new feeds. The
  lexicon-promotion canary gate (§10.31.15) absorbs the §10.34.2
  collision-load test unchanged.
- **Phase 19 (league readiness) / Phase 20 (monetization).** No
  interaction (NLP remains league-blind + tier-blind per §10.0
  doctrine; AST guards in §10.34.1 random-case + systematic-diacritic
  paths re-asserted).

## 10.34.DoD Definition of Done (binding additions)

Adds DoD item 32 to §10.20 (in `00-baseline.md`). This file is the
authority for that item.

- [ ] All `[ ]` items in §10.34.1–§10.34.4 ticked.
- [ ] All 6 new cross-language specs in §10.34.5 ship with both
      Python and Go boot-probe SHAs and refuse boot on mismatch.
- [ ] All 8 new corpora in §10.34.6 ship with `corpus.yaml` two-reviewer
      signoff per §10.33.4 discipline.
- [ ] `make verify.nlp-cross-lang-parity` green at the new 1500-row
      corpus floor.
- [ ] `make verify.nlp-corpora` green for all `~22` cumulative §10.33 +
      §10.34 corpora (per-corpus drift threshold ≤ 1.0%).
- [ ] `make nlp.bench` (in §10.20 DoD item 9) extended to assert the
      §10.34.2 normalize-chain perf budgets per pass + total p99 ≤ 12ms.
- [ ] All ≥ 20 cfg knobs in §10.34.7 land in the same triangle commit
      as the §10.34 code (Python `ai/common/config.py` + `defaults.yaml`
      + `xops/env/.env.example` + Go `server/internal/config/config.go`
      sync test green).
- [ ] All new `nlp.event.v1` and `nlp.alert.v1` kinds (§10.34.8) added
      to `KNOWN_NLP_EVENT_KINDS` / `KNOWN_NLP_ALERT_KINDS` open-enum
      registries; producer-set bound test re-asserted.
- [ ] `qa.request.v1` schema bumped additively from v4 → v5 for the
      `inbound_checksum` field (§10.34.4); `qa.answer.v1` schema bumped
      additively for the `degraded_reason=stage_timeout:<stage>`
      enum extension (§10.34.3); both bumps land per §10.32.17
      breaking-schema migration playbook (additive paths skip the
      90-day window).
- [ ] Tracker row (`make track.add PHASE=10 STATUS=in-progress
      NOTE="Phase 10 §10.34 15th-pass — input correctness + resilience
      + integrity"`) and `make version.bump COMPONENT=docs LEVEL=minor`
      land in the same commit as this file (per AGENTS.md §3 + §6.1).
- [ ] ROADMAP §10 stub table extended with the 15th-pass row pointing
      here.
- [ ] `docs/design/nlp/README.md` table + cumulative surface block
      extended with the 15th-pass row.
- [ ] §10.20 DoD aggregator gains item 32 referencing §10.34.DoD.

## 10.34.10 Open questions / explicit non-goals (so a 16th pass starts with the right scope)

- **Voice-modality ASR replacement remains out of scope.** §10.34
  refines the input-correctness floor for *what arrives*; replacing
  the upstream ASR is a separate phase.
- **Translation of foreign-language input remains out of scope.**
  §10.33.1 closed-apology routing is unchanged.
- **LLM-augmented disambiguation remains out of scope.** Every
  disambiguation in §10.34 is closed-table or lexicon-driven.
- **Per-user-personalised charity normalization is explicitly out of
  scope** (would require per-user model state, breaks the §10.0
  league-blind + tier-blind doctrine and the §10.27.5 operator-preview
  "no per-user state" invariant).
- **Cross-language input (single message containing TR + EN clauses
  with full-sentence boundaries, distinct from §10.33.1 diaspora
  code-mixing at the morpheme level) is reserved for a future pass.**
  At v1, multi-clause cross-language input routes via
  `meta.code_switched_unsupported_at_v1` per §10.33.1.
