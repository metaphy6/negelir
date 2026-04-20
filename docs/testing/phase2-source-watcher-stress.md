# Phase 2.8 — Source-Watcher Adversarial Stress Report

> **Trigger:** zero confidence in the watcher's ability to handle real
> upstream drift. Phase 2.8 was marked done with synthetic happy-path
> tests only; this audit re-opens it with adversarial scenarios that
> mirror what websites actually do to scrapers.
>
> **Outcome:** 16 distinct issues catalogued; 19-scenario stress harness
> built; 7 of the 19 scenarios genuinely failed first sweep, exposing
> blind spots a release would have shipped. 17 now pass green; 2 are
> documented as known limitations awaiting Phase 8 LLM and an
> identity-aware list differ.
>
> **Bumped:** `source_watcher` 1.3.0 → 1.4.0 (minor — new classifier
> rules); `xops` 1.3.1 → 1.3.2 (patch — `_fetch_seed` now records
> `_sha256` and `_status`).

---

## 1. Audit findings

Read of [`ai/swarm/source_watcher/`](../../ai/swarm/source_watcher) +
[`xops/makefile/watch.py`](../../xops/makefile/watch.py) surfaced 16
issues, ranked by impact.

| # | Severity | Where | What | Status |
|---|---|---|---|---|
| A | critical | `watch._fetch_seed` HTML branch | Captured `{_raw_len, _suffix}` only — total DOM rewrite at identical byte count was invisible. | **fixed** (now captures `_sha256` + `_status` from `<file>.headers.json`). |
| B | high | `classifier` | Tiny `_raw_len` deltas (e.g. 1 byte) classified as SEMANTIC, triggering refresh-fixtures. | **fixed** (raw_len ratio < 1% → COSMETIC). |
| C | medium | `classifier` | No notion of "fields the scraper actually uses" — every change weighted equally. | open (Phase 8 hook: per-scraper field manifest). |
| D | high | `classifier` | `1 → "1"` (lossless coercion) classified as SCHEMA_BREAKING. | **fixed** (`type_changed` where `str(old)==str(new)` → SEMANTIC). |
| E | medium | `differ` | Positional list diff: row reorder/heterogeneous-schema row shift trips false add/remove cascades. | partial — **xfail S9** documents the limitation; full fix needs identity-aware list diff. |
| F | high | `_fetch_seed` + `classifier` | Cloudflare 200+challenge body invisible (status was fine, byte count moved a lot). | **fixed** (raw_len drop > 80% with status==200 → SCHEMA_BREAKING). |
| G | high | `_fetch_seed` | HTTP status not part of snapshot — 200→503 with cached body slipped through. | **fixed** (`_status` now sidecar-loaded; `_status >= 500` rule added). |
| H | low | `snapshot_store._TS_RE` | Same-second collision filename `<ts>-<digest6>.json` rejected by `list_snapshots` regex. | open (Phase 2.8.6 follow-up; harmless until two snapshots land in the same second). |
| I | low | `snapshot_store` | No retention on `infra/mock/seeds/history/`. | open (backlog). |
| J | medium | `planner` | Severity is `worst_severity` rollup; one real break can be drowned by 200 cosmetic diffs in the same payload. | mitigated (bulk-truncation rule promotes the *parent* path so the rollup catches it); full per-field prioritization deferred to Phase 8. |
| K | high | `watch.run` end-to-end | Reads disk seeds, not live `mocksrv` — no end-to-end coverage of the serving stack. | open (next backlog item; tracked separately). |
| L | – | – | Stale "HUMAN-ONLY" string in mocksrv 404. | already fixed in prior session. |
| M | medium | `_fetch_seed` | Permanent 4xx becomes "valid seed" forever-stale. | open (needs `_status` consult on capture path; detect-and-skip in `mock.capture`). |
| N | low | `manifest` | `captured_at` vs file mtime drift. | benign; document only. |
| O | medium | CI | No CI gate firing watcher against tampered corpus. | open (phase 2.8.6 follow-up — wire `make watch.run` against `make mock.tamper`). |
| P | – | `summarizer.py` | Zero callers — dead code until Phase 8. | flagged; left in place per Phase 8 design intent. |

---

## 2. Stress harness

[`ai/swarm/source_watcher/tests/test_drift_stress.py`](../../ai/swarm/source_watcher/tests/test_drift_stress.py)
parametrizes 19 adversarial scenarios across two domains (JSON via the
real openfootball seed, and HTML/status via a synthetic envelope that
mirrors what `_fetch_seed` now captures). Each scenario asserts both
**severity** and **must-include actions**.

### Scenario verdicts (final)

| ID | Domain | What it simulates | Expected | Got | Verdict |
|---|---|---|---|---|---|
| S1_identical               | json | re-snapshot, no change | cosmetic + skip | cosmetic + skip | ✅ |
| S2_whitespace_only         | json | reformatted JSON | cosmetic + skip | cosmetic + skip | ✅ |
| S3_added_field             | json | new optional field | semantic + parity+refresh | ✅ | ✅ |
| S4_removed_required        | json | required field gone | schema_breaking + ticket+page | ✅ | ✅ |
| S5_type_flip_score         | json | `[2,1]` → `"2-1"` | schema_breaking | ✅ | ✅ |
| S6_number_to_string        | json | `0` → `"0"` (lossless) | semantic | ✅ | ✅ |
| S7_match_reorder           | json | row reorder | semantic | ✅ | ✅ |
| S8_added_match             | json | new match appended | semantic | ✅ | ✅ |
| **S9_removed_match**       | json | drop oldest match | semantic | schema_breaking | **xfail (known limitation)** |
| S10_diacritic_loss         | json | `ş`→`s` encoding loss | semantic | ✅ | ✅ |
| **S11_id_collision**       | json | swap two teams (silent corruption) | schema_breaking + page | semantic | **xfail (known limitation)** |
| S12_silent_truncation      | json | matches list 306 → 2 | schema_breaking + ticket+page | ✅ | ✅ |
| S13_envelope_wrap          | json | `{matches:…}` → `{data:{matches:…}}` | schema_breaking | ✅ | ✅ |
| S14_locale_swap            | json | ISO → US dates | semantic | ✅ | ✅ |
| H1_html_byte_identical     | html | re-snapshot, no change | cosmetic + skip | ✅ | ✅ |
| H2_html_one_byte           | html | nbsp tweak | cosmetic | ✅ | ✅ |
| H3_html_dom_overhaul_same_size | html | full DOM rewrite, identical bytes (BLIND SPOT) | schema_breaking + page | ✅ | ✅ |
| H4_html_cloudflare_chal    | html | 200 OK + CF challenge body | schema_breaking + page | ✅ | ✅ |
| ST1_status_200_to_503      | html | upstream flips to 503 | schema_breaking + page | ✅ | ✅ |

**Result:** 17 / 19 active scenarios pass green. 2 xfail strict — they
exist precisely so the day Phase 8 LLM (S11) or identity-aware diff
(S9) ships, the suite turns red and forces an honest re-evaluation.

---

## 3. Fixes shipped in this audit

### 3.1 `xops/makefile/watch.py::_fetch_seed`

Before: HTML/non-JSON branches captured only `{_raw_len, _suffix}`.

After: every target — JSON or not — gets `_raw_len`, `_suffix`,
`_sha256` (over the captured bytes), and `_status` (read from the
`<file>.headers.json` sidecar; defaults to 200 if missing). JSON
targets still parse-and-emit the body verbatim; the probe envelope is
only used as a fallback when JSON parsing fails.

This brings real captures into the scope of the new HTML classifier
rules below.

### 3.2 `ai/swarm/source_watcher/classifier.py`

Five new rules:

1. **HTML status.** Any `*._status` diff whose new value is outside
   `[200, 300)` → SCHEMA_BREAKING ("upstream status N at …"). Forces
   `ACTION_PAGE_HUMAN` via the existing planner mapping.
2. **HTML raw_len delta.** `*._raw_len` diff whose absolute ratio is
   < 1% → COSMETIC. Drop ≥ 80% with status==200 → SCHEMA_BREAKING
   (Cloudflare-style soft block).
3. **HTML sha256 swap.** `*._sha256` *changed* (not added/removed)
   while the sibling `*._raw_len` did not change → SCHEMA_BREAKING
   ("content swap at identical byte count"). When raw_len did move,
   sha256 inherits raw_len's severity.
4. **Lossless type coercion.** `type_changed` where
   `str(old) == str(new)` → SEMANTIC ("lossless type coercion").
5. **List vs dict removals.** `removed` whose path ends `]` is a
   list element → SEMANTIC. Dict-key `removed` stays SCHEMA_BREAKING.
6. **Bulk truncation escalation** (cross-diff pass). > 5 list-element
   removals from the same parent path promote *all* of them to
   SCHEMA_BREAKING with reason
   `bulk list truncation at <parent> (N elements removed)`. Catches
   S12 (306 → 2).

### 3.3 Test harness fix

`pytest.param(...)` returns a `ParameterSet` which **is** a NamedTuple,
so `isinstance(entry, tuple)` is True for both. `_build_params` now
discriminates with `hasattr(entry, "values") and hasattr(entry, "marks")`.
Same-payload scenarios (S1, S2, H1) bypass the `snapshot_store` dedup
by handling `prev is None or prev.sha256 == last.sha256` as an empty
diff list.

---

## 4. Known limitations (do not silently fix)

These ship as **`xfail(strict=True)`** so they cannot regress quietly.

### S9 — positional list diff with heterogeneous row schemas

Dropping the oldest match shifts every subsequent index by one. Most
real-world lists contain optional fields (e.g. `score.ht` is absent
on a few matches). Position-based pairing then sees `removed`/`added`
on those optional dict keys, which the classifier (correctly,
narrowly) treats as schema-breaking.

**Fix path:** identity-aware list diff (LCS over a per-source identity
key like `date+team1+team2`). Tracked as Phase 2.8.6 follow-up.

### S11 — entity swap (silent corruption)

Swapping `matches[0].team1` ↔ `matches[1].team1` produces two `changed`
diffs of equal weight. No deterministic rule can distinguish that from
a benign team rename without semantic understanding of "the same match
should keep the same teams".

**Fix path:** Phase 8 LLM narrator + cross-source proofreader voting.

### Other open items (not stress-harness-visible)

- **K** — watcher reads disk, not live `mocksrv`. End-to-end coverage
  via a `watch.live` target still pending.
- **M** — `mock.capture` should refuse to overwrite a 200-body seed
  with a 4xx body.
- **O** — CI gate that fires `make watch.run` against a tampered
  corpus to assert the page-human path actually trips on red.
- **I** — retention policy on `infra/mock/seeds/history/`.
- **J** — per-field prioritization (vs. `worst_severity` rollup).

---

## 5. Numbers

| Metric | Before audit | After audit |
|---|---:|---:|
| watcher tests | 0 stress scenarios | 19 (17 pass + 2 xfail strict) |
| classifier rules | 4 (kind-only) | 9 (kind + path-aware + cross-diff) |
| HTML probe fields | 2 (`_raw_len`, `_suffix`) | 4 (+`_sha256`, +`_status`) |
| full Python suite | 156 pass | **173 pass, 8 skip, 2 xfail** |

---

## 6. Doctrine compliance

- §2 #4 *smallest model that works* — every rule is deterministic
  (`O(diffs)` cross-diff pass, no ML).
- §2 #7 *adversarial tests are first-class* — the stress harness now
  guards every classifier rule and every blind spot we know about.
- §2 #8 *phase gates* — Phase 2 §2.8 stays green; the two xfails
  document the gap between "ships today" and "needs Phase 8".
- §6.1 *versioning discipline* — `source_watcher` minor bump (new
  rules), `xops` patch bump (`_fetch_seed` enhancement). Two commits,
  two scopes.
