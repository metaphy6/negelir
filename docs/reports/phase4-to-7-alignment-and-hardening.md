# Phase 4 → 7 Alignment, Hardening & Proof-Test Roadmap

> **Scope.** Cross-phase audit of Phases 4 (worker pipeline), 5
> (predictor swarm + consensus), 6 (proofreader + drift), and 7
> (defense agents — `sec.input.v1` / `sec.scrape.v1` / `sec.rate.v1`
> + Lua scripts + Go gateway library tier). Phase 7 is treated as
> security-critical: every finding is paired with a concrete fix
> action and at least one new proof test.
> **Date.** 2026-05-05.
> **Status.** Plan-only document. No code changes land in the same
> commit as this report — each finding becomes its own bumped
> patch (per `AGENTS.md` §6.1). Tracker rows go in as the work
> ships, one per finding.
> **Anchor docs read.** [`docs/planning/ROADMAP.md`](../planning/ROADMAP.md)
> §4–§7, [`docs/design/SECURITY.md`](../design/SECURITY.md),
> [`docs/design/CONTENT_FRESHNESS.md`](../design/CONTENT_FRESHNESS.md),
> [`docs/design/SWARM.md`](../design/SWARM.md), the four anchor
> sources under `ai/swarm/agents/sec/`, both Lua scripts under
> `infra/redis/lua/`, and `server/internal/sec/`.

---

## 0. TL;DR — what changed in this audit

The Phases 4–6 surface is **structurally sound**. The Phase 6
second-pass audit ([`phase6-second-pass.md`](phase6-second-pass.md))
already closed the meaningful gaps (perf on `_Window.popleft`,
telemetry watch-set, calibration-store-hit-once, bounded pending
maps, single-source replica roster). The Phase 4–6 boxes that
remain `[ ]` are all **explicitly Phase-9-DB-deferred** (Postgres
RecordStore, real predictor weights/calibration reads, KS-test
on feature plane, cross-source proofreader). Those are not bugs;
they are correct deferrals.

The Phase 7 surface is **substantially correct** post the v1.1.0
ZSET cardinality fix (Session I) and Bucket B (Go library tier).
What this audit found are **9 findings (F7.1–F7.9)** plus **3
cross-phase alignment items (A1–A3)** that range from
**latent-correctness** (a partial-locking pattern in
`SecScrapeAgent`) through **observability gaps** (no test that
validates the Lua sha pin survives a Redis-side `SCRIPT FLUSH`)
down to **knob-naming hygiene**. None of them require backing out
shipped behaviour; all are forward-compatible patches. **No
critical or error-severity finding** was identified.

The **8 proof-test additions** below (P1–P8, plus 3 forward-
deferred P9–P11) are the security floor: each fails-loud at
landing time if the corresponding invariant regresses.

---

## 1. Findings

Findings are numbered `F<phase>.<n>`. Severity ladder mirrors the
`SecAlertKind` enum:

| Severity | Meaning here |
|---|---|
| `info` | Hygiene / consistency. No correctness or security impact. |
| `warn` | Latent bug or observability gap. Will bite under load or during incident triage. |
| `error` | Functional gap that violates a documented binding contract. |
| `critical` | Reachable security or availability bug. **None found in this pass.** |

### F7.1 — `SecScrapeAgent` baseline mutation has partial locking *(warn)*

**File:** [`ai/swarm/agents/sec/scrape.py`](../../ai/swarm/agents/sec/scrape.py)
(lines ~360–520).

**Observation.** The agent takes `self._lock` for three things:
content-addressed dedup (line 367), `_baselines.pop` on operator
reset (line 545), and the read-only `current_baseline*` inspectors
(lines 583/588). The hot path in `_handle_scrape` — which calls
`self._baselines.setdefault(...)` and then **mutates** the
returned `_SourceBaseline` (Welford updates on `body_size` and
`inflate_ratio`, content-type histogram increments, SimHash
swap) — runs *outside* the lock.

**Why this is OK today:** `AgentRunner` is single-threaded
(`ai/swarm/sdk/runner.py` line 13 docstring), so two
`_handle_scrape` invocations cannot interleave on the same agent
instance.

**Why this is a problem tomorrow:** A `maint.event.v1{kind=
baseline_reset}` and a `scrape.raw` event hit the same handler
through the same single-threaded runner — but the inspector
helpers (`current_baseline_mean`, `current_baseline_simhash`)
are public, take the lock, and are *called from tests and from
the future telemetry agent* on a different thread. Holding the
lock in the inspectors but not in the writer is the worst of
both worlds: it implies the writer is safe to read concurrently
when it is not. A future operator running `swarmctl tail
sec.scrape.v1` from a separate Python process that connects to
the same in-process registry **will** observe a partially-updated
Welford state (`m2` updated before `mean`, etc.).

**Fix.** Either (a) take `self._lock` around the entire baseline
mutation block in `_handle_scrape`, or (b) drop the lock from the
inspector helpers and document the read-without-lock as
"snapshot may be stale by one update" with a torn-write guard
(read each scalar twice; retry on mismatch). Option (a) is
simpler and matches `SecRateAgent`'s pattern; the lock is held
for ~10 µs per scrape, well below the SLO.

**Proof test (new).** `test_sec_scrape_baseline_consistency_under_concurrent_inspection`
in `test_phase7_sec_agents.py`: spin up an inspector thread that
reads `current_baseline_mean(source)` in a tight loop while the
main thread drives 10 000 `scrape.raw` events. Assert the
inspector never sees `baseline.body_size.n == k+1` paired with
`mean` still at the value for `k` (Welford torn-write probe).

---

### F7.2 — `SecAlertDebouncer.max_buckets` shares the wrong knob *(info)*

**File:** [`ai/swarm/agents/sec/_alert.py`](../../ai/swarm/agents/sec/_alert.py)
(constructor); each agent's `__init__` (`input.py`, `scrape.py`,
`rate.py`).

**Observation.** Every agent constructs its debouncer with
`max_buckets=int(_cfg.sec_rate_max_subjects)`. That knob's
documented purpose (`xops/env/.env.example`) is the
**`sec.rate.v1` per-subject burst-window LRU cap** (default
100 000 — sized for IPv6 /64 subject space). Re-using it as the
debouncer's bucket cap means tuning the rate-agent's anti-spray
knob silently changes the alert-debounce eviction rate in the
unrelated `sec.input.v1` and `sec.scrape.v1` agents.

**Why it matters.** During incident response the operator may
*lower* `sec_rate_max_subjects` to free memory under attack
pressure; that would simultaneously truncate the debouncer cap
on the input agent, causing debounce-bucket churn and an alert
storm at exactly the wrong moment.

**Fix.** Add a dedicated `cfg.sec_alert_debouncer_max_buckets`
knob (default 4096 per agent, an order of magnitude below the
rate-subject cap because alert kinds × subjects is much smaller
than rate subjects). Triangle test will catch the addition;
existing config-sync test stays green.

**Proof test (new).** Extend `test_config_sync.py` already
covers presence; add `test_sec_alert_debouncer_uses_dedicated_cap`
in `test_phase7_sec_agents.py` that monkeypatches
`sec_rate_max_subjects=1` and asserts the debouncer for
`SecInputAgent` still has `max_buckets > 1`.

---

### F7.3 — `SecScrapeAgent` reuses `sec_scrape_max_pending` for two unrelated bounds *(info)*

**File:** [`ai/swarm/agents/sec/scrape.py`](../../ai/swarm/agents/sec/scrape.py)
lines 332/336.

**Observation.** Both `self._pending` (reserved for future async
scoring) and `self._dedup` (content-addressed dedup of
`scrape.raw` payloads) are sized by `cfg.sec_scrape_max_pending`.
These are different concerns with different correctness
implications: `_pending` controls memory under classifier
backpressure (none today); `_dedup` controls how long a replayed
scrape is recognized as a duplicate.

**Fix.** Introduce `cfg.sec_scrape_dedup_window` (default 4096,
sized for the cross-source replay window observed in the seed
corpus). Keep `_pending` on the existing knob; rename it in a
docstring sweep so the two are clearly distinguishable.

**Proof test (new).** `test_sec_scrape_dedup_and_pending_use_distinct_caps`
asserts the two knobs are independently tunable.

---

### F7.4 — Adjacent-pair SimHash drift is noisy; should be vs. baseline median *(warn)*

**File:** [`ai/swarm/agents/sec/scrape.py`](../../ai/swarm/agents/sec/scrape.py)
lines ~390 + ~485.

**Observation.** The SimHash drift check compares the **current**
sample's 64-bit fingerprint against `prev_simhash` — i.e., the
fingerprint of the immediately-preceding sample from the same
source. A site that legitimately A/B-tests its homepage will
ping-pong between two layouts; the adjacent-pair distance will
exceed the 12-bit default threshold on every flip, firing
`proof.flag{parse_failed}` to the patcher for nothing.

**Fix.** Maintain a small bounded ring (`cfg.
sec_scrape_simhash_ring_size`, default 8) of recent fingerprints
per source; trip drift only when the **minimum** Hamming
distance to *any* member exceeds the threshold. Same memory
class (8 × 8 B per source); fixes the A/B-test false positive.

**Proof test (new).** `test_sec_scrape_simhash_tolerates_legit_ab_test`
in `test_phase7_streaming_baseline.py`: drive A, B, A, B, A, B
(2-state oscillation, distance > 12) and assert zero
`proof.flag` emissions.

---

### F7.5 — No proof test asserts the Lua sha pin survives a *Redis-side* reload *(warn)*

**Files.** [`infra/redis/lua/sec_rate_check.lua`](../../infra/redis/lua/sec_rate_check.lua),
[`infra/redis/lua/sec_denylist_mutate.lua`](../../infra/redis/lua/sec_denylist_mutate.lua),
[`server/internal/sec/lua.go`](../../server/internal/sec/lua.go),
existing `test_phase7_lua_redis.py::test_lua_sha_matches_pinned_header`.

**Observation.** The existing test verifies that a fresh SHA1
over the script body matches the pinned `-- SHA256:` header. It
does **not** verify that after a `SCRIPT FLUSH` (Redis behaviour
on restart with no AOF/RDB), the gateway's `EVALSHA` correctly
falls back to `EVAL` and the *new* `SCRIPT LOAD` returns the
same SHA1 as the cached one. ROADMAP §7.3 makes this a binding
deployment-stability requirement.

**Fix.** Add an integration test that:

1. `SCRIPT LOAD`s the canonical body, captures SHA1.
2. Runs `SCRIPT FLUSH`.
3. Asserts the next `EVALSHA <cached-sha1> ...` returns
   `NOSCRIPT`.
4. Re-runs `SCRIPT LOAD` and asserts the returned SHA1 is
   byte-identical to step 1 (proves no Redis-side rewriting).
5. Asserts a subsequent `EVALSHA` succeeds.

**Proof test (new).** `test_lua_eval_sha_recovers_after_script_flush`
in `test_phase7_lua_redis.py` (skip-if-no-Redis).

---

### F7.6 — No proof test for the `now_ms` *replay* invariant on the v1.1.0 ZSET *(warn)*

**File:** [`infra/redis/lua/sec_denylist_mutate.lua`](../../infra/redis/lua/sec_denylist_mutate.lua)
v1.1.0; existing `test_phase7_lua_v110_cardinality.py`.

**Observation.** The existing 6-test suite proves: `now_ms`
mandatory, lazy ZSET eviction, cap recovery after natural expiry,
re-add overwrites the score, remove decrements truthfully, capped
flag carries the safety-net TTL. **It does not exercise the case
where the gateway's clock skews backwards** (e.g. NTP correction
of a 30 s drift).

**Why it matters.** If `now_ms` arrives smaller than a previous
call's `now_ms`, `ZREMRANGEBYSCORE -inf <past_now>` evicts
*nothing* it shouldn't (the comparison is correct), and re-adding
with a smaller `now_ms + ttl_s*1000` writes a smaller score,
making the entry expire *earlier* than the operator expects. Not
a security bug per se — the entry expires sooner, not later — but
operationally surprising and worth pinning so a v1.2.0 refactor
cannot regress to "use Redis's own `TIME`" without breaking this
test.

**Fix.** Add `test_sec_denylist_mutate_clock_rewind_safety` that
adds a subject at `now_ms=10_000`, then re-adds the same subject
at `now_ms=5_000` (5 s rewind), then asserts the ZSET score is
the *smaller* (5_000 + ttl_ms) value — proves the script has no
"max-of" smuggling that would let an attacker pin entries with
inflated TTLs.

---

### F7.7 — `SecInputAgent._handle_request` adds to dedup BEFORE classification *(info)*

**File:** [`ai/swarm/agents/sec/input.py`](../../ai/swarm/agents/sec/input.py)
lines ~340–350.

**Observation.** The dedup map is updated under the lock the
moment a `request_id` arrives. If a future change to `_classify`
ever raises (today it's `try`-wrapped — catches `Exception` —
but a future refactor might `raise SystemExit` for OOM
shielding), the request is silently lost on retry: the redelivery
hits dedup and short-circuits with no quarantine and no alert.

**Why it's currently OK.** `_classify` is exception-safe and the
classifier is `None` in v1. So the failure mode is not yet
reachable.

**Fix (preventive — lands when classifier is enabled in Phase 13).**
Move the dedup `add` to *after* a verdict has been computed
(success path), and use a separate "in-flight" set keyed on
`request_id` to short-circuit *concurrent* duplicate processing
within the same handle window. The current ordering is fine for
v1; the recommendation is to add a comment naming the constraint
so a Phase 13 reviewer knows why the order matters.

**Proof test (new — lands with the Phase 13 classifier).**
`test_sec_input_classifier_oom_does_not_silently_lose_request`
that injects a classifier raising `SystemExit`, redelivers the
same `request_id`, and asserts the redelivery produces *some*
verdict (either retry with a fresh classifier, or a debounced
`classifier_degraded` alert) — never a silent drop.

---

### F7.8 — `Phase 4 §4.4 storage`: `freshness.events.v1` payload boundary not enumerated in tests *(info)*

**File:** ROADMAP §4.4; `ai/swarm/agents/storage.py`;
`ai/swarm/agents/tests/test_storage_diff.py`.

**Observation.** The roadmap says "emits `freshness.events.v1`
with the plane-scoped diff for reactors — **never carries the
diff on `match.stored`** (per CONTENT_FRESHNESS §15.1)". The
existing tests verify `match.stored` does fire and reactors
consume it; the audit could not find an explicit *negative* test
that asserts `match.stored.payload` does NOT contain a `diff` /
`change_kind` / `previous_value` field.

**Fix.** Add a one-line negative test
`test_match_stored_payload_excludes_diff_fields` in
`test_storage_diff.py` that asserts the emitted `match.stored`
schema has no `diff` key — guards the boundary against a future
"convenience" PR that smuggles the diff to save a bus hop.

---

### F7.9 — `OPEN_ENUM_REGISTRY` covers only `sec.alert.v1`; no AST guard against new bypassers *(info)*

**Files.** [`ai/swarm/sdk/schemas/open_enum.py`](../../ai/swarm/sdk/schemas/open_enum.py)
lines 80–90 (`OPEN_ENUM_REGISTRY` tuple); existing
[`ai/swarm/agents/tests/test_phase7_open_enum.py`](../../ai/swarm/agents/tests/test_phase7_open_enum.py)
(4 tests already passing).

**Correction to earlier draft.** The open-enum helper, the
`OpenEnum` dataclass, the `OPEN_ENUM_REGISTRY` tuple, and the
producer/consumer/pattern/retired-knob test quartet **already
exist** and pin `sec.alert.v1` correctly. The gap is narrower
than first written.

**Observation (revised).** The registry literal in
`open_enum.py` carries a `# Future: Phase 8 will register
MaintEventKind here when the producer set widens beyond
{drift.v1}` comment — but nothing prevents a *new* schema with a
`kind` field from landing under `ai/swarm/sdk/schemas/` and
shipping without an `OPEN_ENUM_REGISTRY` entry. Today the four
phase-7 tests only iterate `OPEN_ENUM_REGISTRY`; they do not
prove the registry is *exhaustive* with respect to the schema
directory. A future Phase-6 drift-kind or Phase-8 maint-event
kind landing in a schema *without* a matching registry entry
would silently bypass the producer-AST and consumer-round-trip
guards.

**Fix.** (a) Promote the deferred `MaintEventKind` registry
entry now — `maint.event.v1`'s producer set is already bounded
by the §6.4-loosened allow-list test, so the `known` frozen-set
is well-defined and stable; (b) add an exhaustiveness test that
scans every `*.json` schema under `ai/swarm/sdk/schemas/` and
for every field whose JSON Schema declares `"x-enum-open":
true`, asserts `(topic, field)` appears in `OPEN_ENUM_REGISTRY`.
Failures name the missing schema/field pair.

**Proof test (new — added to existing file, not a new file).**
`test_open_enum_registry_is_exhaustive_over_schema_directory`
appended to `ai/swarm/agents/tests/test_phase7_open_enum.py`
(joins the existing 4-test suite).

---

## 2. Cross-phase alignment check (Phase 4 ↔ 5 ↔ 6 ↔ 7)

Findings here are **alignment** issues — they do not violate any
single phase's contract in isolation but they create friction at
the seam between phases.

### A1 — `request_id` lineage from gateway → consensus → aggregator → cache

ROADMAP §5 makes the gateway the `request_id` minter; §6 makes the
aggregator emit `predict.approved.v1` per `prediction_id`. The
aggregator's `prediction_id` is `sha256(match_id|market|request_id|
calibration_version)`. The Phase 9 client SDK that issues the QA
call needs to round-trip `request_id` from the *user's*
correlation header so client-side log analytics works. **No proof
test** in the current suite verifies the full
`X-Request-Id` → `qa.request.v1.request_id` →
`predict.request.request_id` → `predict.final.request_id` →
`predict.approved.v1.request_id` chain end-to-end. It is asserted
in pieces (§5 and §6) but not concatenated.

**Fix (lands with Phase 9 router).**
`test_request_id_e2e_chain_phase4_through_phase9` runs a synthetic
request through the entire stack and asserts byte-identical
propagation at each hop.

### A2 — `maint.event.v1` allowed-producers allow-list is enforceable, not enforced

ROADMAP §7.3 loosened the §6.4 "`drift.v1` is sole producer"
boundary test to "producers ⊆ `MAINT_EVENT_V1_ALLOWED_PRODUCERS`".
The Phase 7 closure landed the assertion via
`test_phase7_completion.py::test_maint_event_v1_producer_set_is_bounded_by_allow_list`,
which scans the registry. **It does not block PRs that add a
*new* producer that simply registers itself**: the allow-list is
edited in the same PR and the test goes green. The intent is
"adding a producer is a deliberate doctrine decision, requiring
a tracker row".

**Fix.** Add a CODEOWNERS-style guard: the test asserts that
*if* `MAINT_EVENT_V1_ALLOWED_PRODUCERS` differs from the value
recorded in `docs/design/SWARM.md`, the test fails with a
diagnostic that requires updating the design doc in the same
commit. Cheap; locks the doctrine to the doc.

### A3 — Defense-in-depth pre-conditions are documented, not regression-tested

ROADMAP §7 binding doctrine: `sec.input.v1` fail-open is **safe
only because** Phase 10 NLP answers from templates with no LLM
in the answer hot path. There is currently no test under
`ai/nlp/` that asserts the answer-generation path is template-only
(Phase 10 hasn't landed). When Phase 10 lands, **§7.1 fail-open
becomes unsafe** if a future Phase 10 PR introduces an LLM into
the hot path without the §7 author noticing.

**Fix (lands with Phase 10).** A meta-test in `test_doctrine.py`
that uses AST scan to assert no module under `ai/nlp/answers/`
imports `transformers` / `torch` / `vllm`. Cross-phase
fail-loud guard.

---

## 3. Performance & efficiency notes

These are not bugs — they are documented efficiency wins worth
tracking.

| Area | Current | Improved | Estimated win | Cost |
|---|---|---|---|---|
| `SecScrapeAgent` SimHash recompute | Full re-tokenize per sample | Reuse tokenized triples within batch via `lru_cache(maxsize=64)` keyed on `bytes_sha256` | ~30% fewer tokenizer passes on cross-source replay (mocksrv hits same content from 2+ vhosts) | One method-level decorator |
| `SecRateAgent._evictions` deque | Trimmed on every `_handle_alert` (correct but wasteful) | Trim opportunistically every Nth event (`N = max(1, len(_evictions) // 4)`) | <5% CPU; not significant unless eviction rate sustained > 1k/s | Adds a counter |
| Lua `sec_denylist_mutate.lua` `sweep_expired` | Called on every mutation | Already O(log N + M) and steady-state M=0; do not optimize | n/a | The "do nothing" win |
| `SecAlertDebouncer.decide` LRU | OrderedDict with `move_to_end` | Already optimal; do not optimize | n/a | The "do nothing" win |
| `_Welford.update` | Two-pass-equivalent population variance, single division | Already optimal | n/a | The "do nothing" win |

The "do nothing" rows are explicit so a future reviewer doesn't
re-discover them.

---

## 4. New proof-test inventory (consolidated)

| ID | Test name | File | Severity it guards |
|---|---|---|---|
| P1 | `test_sec_scrape_baseline_consistency_under_concurrent_inspection` | `test_phase7_sec_agents.py` | F7.1 (warn) |
| P2 | `test_sec_alert_debouncer_uses_dedicated_cap` | `test_phase7_sec_agents.py` | F7.2 (info) |
| P3 | `test_sec_scrape_dedup_and_pending_use_distinct_caps` | `test_phase7_sec_agents.py` | F7.3 (info) |
| P4 | `test_sec_scrape_simhash_tolerates_legit_ab_test` | `test_phase7_streaming_baseline.py` | F7.4 (warn) |
| P5 | `test_lua_eval_sha_recovers_after_script_flush` | `test_phase7_lua_redis.py` | F7.5 (warn) |
| P6 | `test_sec_denylist_mutate_clock_rewind_safety` | `test_phase7_lua_v110_cardinality.py` | F7.6 (warn) |
| P7 | `test_match_stored_payload_excludes_diff_fields` | `test_storage_diff.py` | F7.8 (info) |
| P8 | `test_open_enum_registry_is_exhaustive_over_schema_directory` | `test_phase7_open_enum.py` *(append to existing file — 4 tests already present)* | F7.9 (info) |
| P9 *(deferred)* | `test_sec_input_classifier_oom_does_not_silently_lose_request` | future Phase 13 PR | F7.7 (info) |
| P10 *(deferred)* | `test_request_id_e2e_chain_phase4_through_phase9` | future Phase 9 PR | A1 |
| P11 *(deferred)* | `test_doctrine_no_llm_in_nlp_answer_hot_path` | future Phase 10 PR | A3 |

Eight tests land now (P1–P8). Three (P9–P11) are explicit
forward-deferred entries with a phase tag.

---

## 5. Execution order (recommended)

Each row is one PR, one commit, one tracker row, one
`make version.bump`.

| # | PR | Component bump | Bump level | Notes |
|---|---|---|---|---|
| 1 | F7.1 fix + P1 | `swarm` | patch | Take lock around baseline mutation; baseline-consistency probe. |
| 2 | F7.2 fix + P2 | `swarm` | patch | New `cfg.sec_alert_debouncer_max_buckets` knob; triangle stays green. |
| 3 | F7.3 fix + P3 | `swarm` | patch | New `cfg.sec_scrape_dedup_window` knob; triangle stays green. |
| 4 | F7.4 fix + P4 | `swarm` | patch | SimHash ring-of-N; reduces patcher false positives. |
| 5 | F7.5 (P5) | `swarm` | patch | Test-only addition (`SCRIPT FLUSH` recovery); no code change. |
| 6 | F7.6 (P6) | `swarm` | patch | Test-only addition (clock-rewind safety); no code change. |
| 7 | F7.8 (P7) | `swarm` | patch | Test-only negative-payload assertion; no code change. |
| 8 | F7.9 fix + P8 | `swarm` | patch | Register `MaintEventKind` in `OPEN_ENUM_REGISTRY` + exhaustiveness AST test. **Patch, not minor**: the helper and test scaffolding already exist; this is a registry entry + one new test. |
| 9 | A2 fix | `docs` | patch | CODEOWNERS-style guard tying `MAINT_EVENT_V1_ALLOWED_PRODUCERS` to `SWARM.md`. |

After (8), `OPEN_ENUM_REGISTRY` is exhaustive over the schema
directory — any future `kind`-bearing schema that lands without
a registry entry fails the test at PR time.

The deferred items (P9, P10, P11) are tracked here so the next
agent landing Phase 9 / 10 / 13 finds them via grep.

---

## 6. What this audit explicitly did **not** flag

For the next reviewer's benefit — these were checked and ruled
out so a future audit doesn't re-discover and re-flag them:

- **`sec_rate_check.lua` PTTL=-2 race fall-through**. Already
  documented and tested against (`_python_reference_rate_check`
  mirror). Correct as-is.
- **GCRA cost=0 free-pass**. Already deliberate
  (`/v1/healthz` → cost 0). Test `costs_test.go::TestCostFor`
  pins it.
- **Password field passing through `sec.input.v1`**. Already
  carved out in Go gateway library tier (`PasswordPasses` runs
  zero transforms; `TestPasswordFieldBypassesNormalization` and
  `TestPasswordFieldStillEnforcesLengthCap` pin it). End-to-end
  wiring waits for Phase 9 router.
- **Telemetry watch-set Phase 6 + 7 union**. Both unions are
  asserted by named tests
  (`test_telemetry_watches_phase6_proofreader_drift_topics`,
  `test_telemetry_watches_phase7_topics`). Correct.
- **`maint.event.v1` producer-set boundary**. Loosened
  intentionally per ROADMAP §7.3; new boundary test pins the
  allow-list. The CODEOWNERS-style hardening above (A2) is a
  doctrine lock, not a correctness fix.
- **`consensus.v1` single-publication under Phase 14 multi-replica**.
  Explicitly out of scope until leader election lands.
  Documented in §5 forward contracts.

---

## 7. Closing note on Phase 7 specifically

Phase 7 is the only phase in this audit where a **silent**
failure has security consequences (a missed quarantine = an
unfiltered payload reaching the NLP layer; a runaway denylist =
a self-inflicted DoS). The fail-open doctrine is correct, but
fail-open is *only safe when combined with loud telemetry*. The
findings above are deliberately weighted toward **observability
and proof tests** rather than behavioural changes — the agents
behave correctly today; what they currently lack is the
regression-proof scaffolding that survives the next refactor.

Eight new tests (P1–P8) + one design-doc lock (A2) would close
every non-deferred item above. None of them require a feature
freeze; all are forward-compatible patches to a shipped surface.
Three more tests (P9–P11) are explicitly tagged for the phase
that unlocks them (Phase 9 router → A1; Phase 10 NLP → A3;
Phase 13 classifier → F7.7).
