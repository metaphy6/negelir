# Phase 6 — Proofreader & Drift: Fresh-Eyes Audit + Implementation Roadmap

> **Status (2026-04-30):** ✅ **WAVE 5 SHIPPED.** F3-1 (retired
> `proofreader_replicas` env knob — roster lives in
> `swarm.agents.proofreader.replicas.PROOFREADER_POLICY_CLASSES`),
> F3-2 (ROADMAP §6.1, §6.3, §6.4, §6.5 updated), and F3-3
> (`proofreader_internal_error` payload now uses the canonical
> `agent` / `prediction_id` / `match_id` / `market` /
> `request_id` field set) all landed. Suite: **1003 passed,
> 15 skipped, 2 xfailed**. Bumps: `swarm` 0.17.2 → 0.18.0
> (minor — soft API break removing an env knob), `docs`
> 1.10.10 → 1.10.11 (patch).
>
> **Original status (audit pass):** DRAFT — awaiting human review.
> **No code edits have been made in this audit pass.** This document supersedes the
> earlier `phase6-implementation.md` draft (which was authored
> *before* its own findings were implemented and is therefore
> stale).
>
> **Audience:** the human + next agent who will land Wave 5 on
> Phase 6.
>
> **Method.** I re-read every Phase 6 source file *without
> trusting* the prior reports' verdicts. For each prior finding
> (F-1..F-10 first-pass, F2-1..F2-4 second-pass) I went to the
> code and confirmed whether the fix is *correctly* in place
> (not merely that something with the same name exists). Then I
> walked the code looking for issues neither pass caught.
>
> **Test baseline at audit start (verified, no edits):**
> - Full project suite (`make test`): **992 passed, 15 skipped, 2 xfailed**
> - AI tests only (`make test.ai`): **379 passed**
> - Swarm tests only (`ai/swarm/agents/tests` + `ai/swarm/tests`): **386 passed**
>
> **Decision asked of the human:** approve or push back on each
> of the three new findings (F3-1 to F3-3) and on the proposed
> Wave 5. Implementation will not start until you sign off.

---

## 1. Executive summary

Phase 6 is in **substantially better shape than the prior reports
suggest.** Every blocker / major from the first-pass audit
(`F-1..F-10`) and the second-pass audit (`F2-1..F2-4`) is
**actually shipped and correctly implemented** — not just
sketched. The pipeline runs end-to-end in the bootstrap smoke
test, the boundary-discipline tests cover all five rules, the
cache + telemetry are wired into `build_swarm()`, the
`flush_expired` tick fires, the duplicate-config-field shadow is
gone, and the replica-internal-exception path now emits
`warn + proof.flag` instead of the silent `reject` veto.

This pass found **three new issues** that neither prior pass
flagged. None of them is a blocker, but two are real correctness
hazards under non-default configuration:

| # | Severity | Shape |
|---|---|---|
| **F3-1** | **Major (operator footgun)** | `cfg.proofreader_replicas` is a tunable knob *and* drives `cfg.proofreader_quorum`, but the bootstrap hard-codes exactly 3 distinct policy classes and ignores the knob. Any value other than 3 silently breaks quorum (>3 → unreachable, <3 → late-verdict spam). |
| **F3-2** | **Minor (doc drift)** | ROADMAP §6.5 still has `[ ] drift_brier_ceiling alias` open — but what shipped (per F-3 fix) is a *separate* knob with different semantics, not an alias. The checkbox text describes a design that did not ship; either flip the box with revised text or close it and explain why. |
| **F3-3** | **Minor (operator UX)** | `proofreader_internal_error` proof.flag uses `source: <agent>` + `target: <prediction_id>` instead of the `agent` / `prediction_id` / `match_id` / `market` / `request_id` shape the other six Phase 6 proofreader flag kinds use. Dashboards filtering by `prediction_id` will miss internal-error entries. |

**Recommended Wave 5 (≈ 60-100 LoC + tests):** fix F3-1 by making
the bootstrap honour `cfg.proofreader_replicas` (or, alternative,
remove the knob and let quorum derive from the actual replica
count); harmonise the `proofreader_internal_error` flag fields;
revise the §6.5 checkbox text and tick it. Total estimate is
small because the heavy lifting from prior waves is already
complete.

---

## 2. Verification of prior findings

This is the value-add of the fresh-eye pass: confirming each
prior finding was *correctly* resolved, not merely "addressed."

### 2.1 First-pass audit (F-1 .. F-10)

| # | Severity | Status | Verified by |
|---|---|---|---|
| **F-1** | Blocker — no production swarm bootstrap | ✅ **Correctly fixed.** [`ai/swarm/bootstrap.py`](../../ai/swarm/bootstrap.py) `build_swarm()` constructs all Phase 5 + Phase 6 + Phase 4 consumer agents; smoke test in [`ai/swarm/tests/test_bootstrap.py`](../../ai/swarm/tests/test_bootstrap.py) drives an end-to-end `predict.request → predict.approved` cycle. | Read both files top-to-bottom; ran the test (passes). |
| **F-2** | Blocker — `flush_expired` never invoked | ✅ **Correctly fixed.** `AgentRunner` carries a `flush_interval_sec` and ticks `flush_expired()` on agents that expose it (the aggregator does). Test `test_runner_calls_flush_expired_for_aggregator_without_inbound_msg` confirms a `proofreader_no_quorum` flag fires after window elapse with no further inbound messages. | Read the test; confirmed tick logic in `AgentRunner`. |
| **F-3** | Blocker — `drift_accuracy_floor` declared twice | ✅ **Correctly fixed (Option A taken).** [`ai/common/config.py`](../../ai/common/config.py) line 262 keeps the legacy `drift_accuracy_floor` (env `NEGELIR_DRIFT_FLOOR`, default `0.35`) for the Phase 5 accuracy detector; line 418 introduces a *separate* `drift_brier_ceiling` (env `NEGELIR_DRIFT_BRIER_CEILING`, default `0.30`) for the Phase 6 swarm drift agent. [`ai/swarm/agents/drift.py`](../../ai/swarm/agents/drift.py) line 193 reads `_cfg.drift_brier_ceiling`; [`ai/model/drift.py`](../../ai/model/drift.py) line 31 still reads `cfg.drift_accuracy_floor`. No silent shadow. | Greps + line-by-line read. |
| **F-4** | Major — replica internal exception → `reject` (single-replica DoS) | ✅ **Correctly fixed.** [`ai/swarm/agents/proofreader/replicas.py`](../../ai/swarm/agents/proofreader/replicas.py) lines 92-122: exception is converted to `verdict="warn"` + a `proof.flag(kind=proofreader_internal_error)`. The new `ProofFlagKind.PROOFREADER_INTERNAL_ERROR` exists in `payloads.py` line 465 and the schema enum in `proof.flag.json` line 27. **But see F3-3 below — the flag's payload shape is inconsistent with siblings.** | Read replica `handle()`, payload registry, and schema. |
| **F-5** | Minor — `drift_accuracy_floor` is a misnomer | ✅ **Resolved by F-3.** The Phase 6 knob is now `drift_brier_ceiling`; the Phase 5 knob keeps the accuracy-floor name *because that detector genuinely measures accuracy* (lower = worse, trips when below floor) — verified by reading [`ai/model/drift.py`](../../ai/model/drift.py) `DriftDetector.check()`. The previous misnomer concern came from the duplicate-field shadow, which is gone. | Read the legacy detector. |
| **F-6** | Minor (doc) — `pre-phase6-actions.md` documents the wrong topic | ✅ **Correctly fixed.** [`docs/reports/pre-phase6-actions.md`](pre-phase6-actions.md) §1.2 / §1.3 now use `predict.proofreader_verdict.v1` and the correct schema path. | Grep + read. |
| **F-7** | Minor — market key case sensitivity | ✅ **Correctly fixed (with one residual gap, see below).** `PredictApproved.__post_init__` lowercases `market` (payloads.py line 806); `grid_consistency_check` uppercases the outcome dict before lookup (prediction_checks.py line 188). **Residual:** `PredictFinal.market` is *validated* against a lowercase-only `_ALLOWED_MARKETS` set (raises ValueError on uppercase) rather than normalised — this means an upstream typo crashes the predictor agent at the boundary instead of being silently coerced, which is *strictly better* than the soft-coerce shipped in `PredictApproved`. The two paths use different defenses (validate vs normalise) but both are safe; flagging only because the inconsistency may surprise the next maintainer. | Read both `__post_init__` blocks + check function. |
| **F-8** | Minor — per-replica thresholds cached at `__init__` | Acknowledged in code comments; no live-reload path was added (still requires restart). Acceptable per ROADMAP. | Read replica constructors. |
| **F-9** | Cosmetic — aggregator borrows `consensus_max_pending` | ✅ **Correctly fixed.** [`ai/common/config.py`](../../ai/common/config.py) line 366 introduces dedicated `proofreader_aggregator_max_pending` (env `NEGELIR_PROOFREADER_AGGREGATOR_MAX_PENDING`, default `4096`); aggregator constructor reads it. | Read config + aggregator `__init__`. |
| **F-10** | Cosmetic — single-instance assumption implicit | ✅ **Correctly fixed.** `bootstrap.py` defines `SINGLE_INSTANCE_AGENTS = {consensus.v1, proofreader_aggregator.v1, drift.v1}` and `_enforce_single_instance()` raises `SingleInstanceViolation` on duplicates. Three regression tests (`test_build_swarm_refuses_duplicate_*`) cover all three names. | Read bootstrap + tests. |

### 2.2 Second-pass audit (F2-1 .. F2-4)

| # | Severity | Status | Verified by |
|---|---|---|---|
| **F2-1** | Major (perf) — `DriftAgent._handle_outcome` linear scan | ✅ **Correctly fixed.** [`ai/swarm/agents/drift.py`](../../ai/swarm/agents/drift.py) lines 313-322: direct `self._pending.pop((outcome.match_id, "1x2"), None)`. O(1) regardless of pending-map size. | Read `_handle_outcome`. |
| **F2-2** | Major (alignment) — bootstrap omits Phase 4 consumers | ✅ **Correctly fixed.** `build_agents()` includes `CacheAgent()` and `TelemetryAgent.from_config(start_http=False)`; the `test_build_swarm_predict_request_lands_in_cache_backend` test asserts the approval lands in the cache backend (not just on the bus). | Read `build_agents()` + the cache-end-to-end test. |
| **F2-3** | Cosmetic — ROADMAP §4.5 stale checkbox | Not re-verified in this pass (out of scope of Phase 6 source); take prior pass on faith. |
| **F2-4** | Cosmetic — ROADMAP §4.7 stale checkboxes | Same as F2-3. |

**Verdict on prior reports:** every shipped fix is *correctly*
implemented — no half-fixes, no places where the test asserts X
but the code does Y. The prior reports themselves are however
**stale as documents** because they were written *before* their
own waves landed; reading them today gives a misleading picture
of "everything is broken." The prior `phase6-implementation.md`
should be archived or superseded by this one.

---

## 3. New findings (this pass)

### F3-1 — `proofreader_replicas` config knob does not drive bootstrap · **Major (operator footgun)**

**Shape.**

Two surfaces depend on the count of proofreader replicas:

1. [`ai/common/config.py`](../../ai/common/config.py) line 351:
   `proofreader_replicas: int = 3` (env `NEGELIR_PROOFREADER_REPLICAS`),
   with derived property `proofreader_quorum = ⌊N/2⌋+1`
   (line 523).
2. [`ai/swarm/bootstrap.py`](../../ai/swarm/bootstrap.py)
   `_build_proofreader_replicas()` *always* returns exactly three
   instances: one `SanityProofreader`, one `PlausibilityProofreader`,
   one `ConsistencyProofreader` — the knob is **not read**.

The bootstrap docstring acknowledges this:

> `cfg.proofreader_replicas` (default 3) is informational: the
> three classes are *distinct check policies*, not interchangeable
> copies.

**Why it matters (the footgun).** The aggregator's quorum is
derived from the knob, but the actual voter count is driven by
the bootstrap. They drift the moment an operator touches the env
var:

| Operator sets | Quorum becomes | Actual voters | Outcome |
|---|---|---|---|
| `=3` (default) | 2 | 3 | ✅ healthy |
| `=5` | 3 | 3 | ⚠️ approval still possible (3/3 accept) but a single `warn` from plausibility means 2 accepts can't satisfy quorum=3 → **silent no-quorum spam** |
| `=7` | 4 | 3 | ❌ **quorum mathematically unreachable**; every prediction times out as `proofreader_no_quorum` |
| `=1` | 1 | 3 | ⚠️ quorum reached after first vote, but the other two replicas vote *after* finalize → **`proofreader_late_verdict_dropped` flag spam on every prediction** |

None of these states crashes anything. They all silently degrade
the pipeline in ways an operator would only notice by reading
flag dashboards.

**Why neither prior pass caught it.** Both passes accepted the
"informational knob" docstring at face value. The boundary tests
only check class identity, not class count. The bootstrap smoke
test runs at the default and never varies the knob.

**Recommended fix.** Two options; pick one explicitly.

- **Option A (preferred): make the knob honest.** Have the
  bootstrap iterate `_cfg.proofreader_replicas` and spawn that
  many *of each* policy class (so `=2` → 2 sanity + 2 plausibility
  + 2 consistency = 6 voters). Quorum at `=2` becomes 2 (still
  ⌊2/2⌋+1=2 — wait, the property reads N=2, computes
  ⌊2/2⌋+1=2, so quorum=2 of 6 voters; not what the operator
  wants either). Actually this requires rethinking what the knob
  *means*: is it "voters per policy" or "total voters"? Probably
  voters-per-policy is the only honest reading.
- **Option B: remove the knob.** Replace
  `cfg.proofreader_replicas` with a constant
  `PROOFREADER_POLICY_COUNT = 3` defined alongside the policy
  classes. Quorum derives from the constant. Operators cannot
  drift the two; horizontal scaling moves to Phase 14 K8s
  consumer-group sharding (which doesn't change vote count
  anyway — it shards consumption, not policy diversity).
- **Option C (compromise): validate at boot.** Keep the knob,
  but `_enforce_single_instance` (or a sibling
  `_enforce_replica_count_matches_knob`) raises
  `BootstrapMismatch` if `len(_build_proofreader_replicas()) !=
  cfg.proofreader_replicas`. Forces operators to pin the env var
  to the actual replica count or fail-fast at startup.

**Recommendation: Option B** — it removes the footgun entirely
and matches the existing "three distinct policies" design
intent. The knob is currently a phantom feature.

**Diff:** ~30 LoC config + bootstrap + ~40 LoC test (covers the
quorum-derivation invariant and the no-knob assertion). No
schema change, no API change.

**Dependency:** none. Land alone.

---

### F3-2 — ROADMAP §6.5 last open item describes a design that did not ship · **Minor (doc drift)**

**Shape.** ROADMAP §6.5 list ends with:

> - [ ] **`drift_brier_ceiling` alias.** Add a forward-compatible
>   alias for `drift_accuracy_floor` at Phase 9 alongside the
>   Postgres lift to remove the naming-vs-semantics mismatch
>   without breaking existing env configs.

But what F-3 actually shipped is a **separate knob**, not an
alias. Today:

- `cfg.drift_accuracy_floor` (default 0.35, env `NEGELIR_DRIFT_FLOOR`)
  is the **Phase 5 accuracy-floor** for `ai/model/drift.py`'s
  `DriftDetector` (genuinely measures accuracy; lower-is-worse;
  trips below the floor).
- `cfg.drift_brier_ceiling` (default 0.30, env
  `NEGELIR_DRIFT_BRIER_CEILING`) is the **Phase 6 Brier ceiling**
  for `ai/swarm/agents/drift.py`'s `DriftAgent` (Brier score;
  lower-is-better; trips above the ceiling).

These are two genuinely different metrics, so an alias would have
been **wrong** (would lock the two to the same numeric value
forever). The current shape — two knobs, two semantics, two
detectors — is correct, but the ROADMAP checkbox text is wrong:
it asks for an alias that should not exist.

**Recommended fix.** Replace the bullet text with:

> - [x] **`drift_brier_ceiling` separate knob (not alias).** F-3
>   shipped a dedicated `cfg.drift_brier_ceiling` (default 0.30,
>   env `NEGELIR_DRIFT_BRIER_CEILING`) for the Phase 6 swarm
>   drift agent, leaving `cfg.drift_accuracy_floor` (default
>   0.35, env `NEGELIR_DRIFT_FLOOR`) bound to the Phase 5
>   accuracy detector in `ai/model/drift.py`. An alias would
>   have been wrong because the two detectors measure different
>   metrics with opposite "trip direction."

**Diff:** ~6 LoC ROADMAP edit + tracker note.

**Dependency:** none. Land alone.

---

### F3-3 — `proofreader_internal_error` flag uses inconsistent payload shape · **Minor (operator UX)**

**Shape.** All six Phase 6 proofreader flag kinds use the same
field set:

| Field | Used by |
|---|---|
| `agent` | producer agent name |
| `prediction_id` | the prediction this is about |
| `match_id` | which match |
| `market` | which market |
| `request_id` | which request |

Verified in [`ai/swarm/agents/proofreader/aggregator.py`](../../ai/swarm/agents/proofreader/aggregator.py)
for `proofreader_no_quorum`, `proofreader_rejected`,
`proofreader_late_verdict_dropped`,
`proofreader_duplicate_approval`, `proofreader_overflow`.

But `proofreader_internal_error` (emitted by replicas, not the
aggregator) uses a *different* shape — see
[`ai/swarm/agents/proofreader/replicas.py`](../../ai/swarm/agents/proofreader/replicas.py)
lines 110-122:

```python
flag_msg = Message.new(
    PROOF_FLAG,
    {
        "kind": ProofFlagKind.PROOFREADER_INTERNAL_ERROR,
        "source": self.name,                # ← should be `agent`
        "target": final.prediction_id,      # ← should be `prediction_id`
        "detail": …,
        "exception_type": …,
    },
    …
)
```

The schema (`proof.flag.json`) has `additionalProperties: true`
and only requires `kind`, so this validates — but operator
dashboards filtering "show me all proof.flag rows where
`prediction_id = X`" (the obvious operator query) will silently
miss internal-error entries because the prediction id is hidden
under `target`.

**Why neither prior pass caught it.** F-4's review focused on
"does the flag exist at all" (it does) and "does it block the
veto" (it does). Field-name harmonisation across the six kinds
was not part of the F-4 acceptance criteria.

**Recommended fix.** Restructure the flag payload to match its
six siblings:

```python
flag_msg = Message.new(
    PROOF_FLAG,
    {
        "kind": ProofFlagKind.PROOFREADER_INTERNAL_ERROR,
        "agent": self.name,
        "prediction_id": final.prediction_id,
        "match_id": final.match_id,
        "market": final.market,
        "request_id": final.request_id,
        "exception_type": type(exc).__name__,
        "detail": str(exc)[:512],
    },
    …
)
```

Add a parameterised test that asserts every Phase 6
`ProofFlagKind` produces a payload with `agent`,
`prediction_id`, `match_id`, `market`, `request_id` populated
(i.e. the operator-query invariant). This is the kind of
contract test that makes Wave 4-style polish stick.

**Diff:** ~15 LoC replica change + ~30 LoC test.

**Dependency:** none. Could land in the same wave as F3-1.

---

## 4. Cross-phase alignment recheck

| Contract | Counter-party | Aligned? | Notes |
|---|---|---|---|
| `predict.final` consumer | Phase 5 consensus produces it | ✅ | Aggregator + 3 replicas subscribe. |
| `predict.approved.v1` producer | Phase 4 cache + Phase 6 drift consume it | ✅ | Both wired in `build_agents()`. |
| `predict.approved.v1` cache invariant | Phase 9 API surface | ✅ | `test_build_swarm_predict_request_lands_in_cache_backend` asserts the cache backend has the approval. |
| `match.outcome.v1` producer | Phase 5 storage | ✅ | Boundary test enforces single producer. |
| `match.outcome.v1` consumer | Phase 6.3 drift | ✅ | Drift subscribes; F2-1 fix gives O(1) settle. |
| `maint.event.v1` producer | Phase 6.3 drift | ✅ | Boundary test enforces single producer. |
| `maint.event.v1` consumer (trainer) | Phase 5 TrainerReactor | ⚠️ | Telemetry observes; trainer-side wiring is Phase 5.5 work and is acknowledged as outside Phase 6. |
| `cfg.proofreader_quorum` derived from `proofreader_replicas` | Aggregator default | ⚠️ | Mathematically correct, **but disconnected from the actual replica count** — see **F3-1**. |
| `cfg.drift_accuracy_floor` (legacy) | `ai/model/drift.py` | ✅ | Restored to 0.35 by F-3 fix; legacy detector unaffected. |
| `cfg.drift_brier_ceiling` (Phase 6) | `ai/swarm/agents/drift.py` | ✅ | Reads the dedicated knob. |
| Single-instance invariant | `consensus.v1`, `proofreader_aggregator.v1`, `drift.v1` | ✅ | `_enforce_single_instance()` + 3 boundary tests. |
| `proof.flag` payload shape | Operator dashboards | ⚠️ | Six of seven Phase 6 kinds harmonised; **`proofreader_internal_error` uses the wrong field names** — see **F3-3**. |

---

## 5. Items the audit deliberately did NOT touch

These are out of scope for Phase 6 v1 but worth recording so the
next reviewer doesn't re-discover them:

- **Cross-source proofreader** (`flags=["cross_source.implied_prob_disagree"]`)
  — depends on Phase 9 odds plane.
- **Historical-prediction proofreader** — depends on a durable
  `predict.final` plane (Phase 9).
- **KS-test drift mode** (`MaintEvent.reason=feature_ks`) —
  needs a feature-vector plane (Phase 9 or Phase 16 emitter).
- **Per-predictor drift windows** — needs durable `predict.vote`
  plane.
- **Per-league plausibility cap** — Phase 13a `LeagueConfig`
  override.
- **`InMemoryBus._streams` deque compaction** — recorded as
  out-of-scope by the second-pass audit; production uses Redis
  Streams which compacts via `MAXLEN`.
- **Datasource (Phase 4 producers) bootstrap** — separate
  `datasource/` bootstrap due in Phase R1; today the
  scrape-side agents live alongside but are wired by other
  helpers (`xops/swarm_backtest.py` + tests).
- **Live-reload of replica thresholds** — F-8 acknowledged as
  doc-only.

---

## 6. Recommended Wave 5 — proposed scope

Dependency-ordered. Each item lists code change → test addition
→ tracker note → version bump.

### Wave 5.1 — F3-1: remove the phantom replica knob (or fix it)

1. Decide between Option A / B / C in §3 (recommend **Option B
   = remove the knob**).
2. If Option B:
   - Delete `proofreader_replicas` from
     [`ai/common/config.py`](../../ai/common/config.py) and from
     the triangle (`defaults.yaml`, `.env.example`).
   - Define `PROOFREADER_POLICY_COUNT = 3` as a module constant
     alongside the three replica classes.
   - Rewrite `proofreader_quorum` derived property to read the
     constant (or move it to a `bootstrap.QUORUM` constant).
   - Update `test_strict_mode_accepts_known_keys` (no impact
     since the env var goes away — but the
     `test_config_no_duplicate_fields` invariant added in Wave 1
     should still hold).
3. Add `test_proofreader_replica_count_matches_quorum_derivation`:
   `len(_build_proofreader_replicas()) == 3` and
   `bootstrap.derived_quorum() == ⌊3/2⌋+1 == 2`.
4. Tracker row + `swarm` patch bump + `docs` patch bump (this
   report).

**Risk:** medium-low. Removing a public env var is a soft API
break for operators who set it; mitigation is a tracker note +
release note. Today the knob does nothing useful, so the break
is theoretical.

---

### Wave 5.2 — F3-3: harmonise `proofreader_internal_error` payload shape

1. Edit the `flag_msg = Message.new(...)` block in
   [`ai/swarm/agents/proofreader/replicas.py`](../../ai/swarm/agents/proofreader/replicas.py)
   to use `agent` / `prediction_id` / `match_id` / `market` /
   `request_id` (keep `exception_type` and `detail` as
   internal-error-specific extras).
2. Add `test_all_phase6_proof_flag_kinds_carry_canonical_fields`:
   parameterised over the seven kinds, monkeypatch each
   emission path, assert the resulting payload has
   `agent` and `prediction_id` and `match_id` and `market`
   and `request_id` populated (operator-query invariant).
3. Tracker row + `swarm` patch bump.

**Risk:** very low. Schema is `additionalProperties: true` so
existing consumers keep working; the change is purely additive
(adds the canonical fields, drops the redundant `source` /
`target` aliases).

---

### Wave 5.3 — F3-2: revise the §6.5 ROADMAP checkbox

1. Replace the open `[ ] drift_brier_ceiling alias` bullet with
   the corrected closed `[x]` bullet from §3 above.
2. Tracker row + `docs` patch bump.

**Risk:** zero. Pure doc fix.

---

### Wave 5.4 — Optional polish (defer if budget tight)

- **Boundary-test extension:** assert that `cfg.proofreader_quorum`
  always evaluates to the actual voter count's
  `⌊N/2⌋+1` (catches future regressions of F3-1 if Option C is
  chosen instead of B).
- **Bootstrap log enrichment:** `_log.info(...)` line currently
  reports `(N agents wired, M single-instance)`; add a
  `voters: {predictors: 4, proofreaders: 3}` summary so
  operators see the actual count in startup logs.
- **F-7 residual:** `PredictFinal.__post_init__` *validates*
  rather than *normalises*; consider making the two payloads
  consistent (both validate, or both normalise). Prefer
  validate-only because soft-coerce can hide upstream bugs.

---

## 7. Acceptance criteria for marking Phase 6 "complete"

After Wave 5 lands, the following must all hold green
simultaneously:

1. `make test` passes (target: ≥ 998 passed; baseline 992).
2. `make test.ai` passes (target: ≥ 380; baseline 379).
3. Either:
   - `cfg.proofreader_replicas` no longer exists *and*
     `bootstrap.PROOFREADER_POLICY_COUNT == 3` is asserted by a
     test, **or**
   - the bootstrap honours `cfg.proofreader_replicas` and the
     drift between knob and actual voter count is impossible
     (Option A or C).
4. All seven `ProofFlagKind` values produce payloads with
   `agent` / `prediction_id` / `match_id` / `market` /
   `request_id` populated (parameterised contract test).
5. ROADMAP §6.5 has zero open bullets that describe shipped-but-
   different-design items.
6. `make track.add PHASE=6 STATUS=…` row exists for each Wave 5
   sub-wave, plus `make version.bump COMPONENT=swarm LEVEL=patch`
   for the code change and `COMPONENT=docs LEVEL=patch` for this
   report.
7. The earlier `phase6-implementation.md` and `phase6-second-pass.md`
   reports stay on disk as historical record but their executive
   summaries should be marked **superseded by `phase6-implementation.md`
   (this file)** in a one-line front-matter banner.

---

## 8. Self-review notes

I re-read this document end-to-end before publishing. Honest
flags:

- **Severity calibration.** F3-1 is **Major** because under any
  non-default `NEGELIR_PROOFREADER_REPLICAS` the pipeline
  silently degrades. It is *not* a Blocker because the default
  works correctly and most operators never touch the knob; the
  hazard is a configuration footgun, not a v1 ship blocker.
  F3-2 and F3-3 are honestly Minor — F3-3 is the kind of issue
  that shows up only when an operator builds a dashboard query
  and notices missing rows.
- **Things this audit did NOT verify.**
  - I did not run the full suite under non-default
    `NEGELIR_PROOFREADER_REPLICAS` to *demonstrate* F3-1's
    failure modes; the analysis is from reading the code +
    tracing the math. The proposed Wave 5.1 test would close
    that gap.
  - I did not re-verify F2-3 / F2-4 (ROADMAP §4.5 / §4.7
    checkbox flips) — those are out of Phase 6 scope and the
    second-pass report claimed them landed.
  - I did not run multi-process integration tests against
    Redis. The boundary tests + bootstrap smoke test cover
    the static topology and one in-process end-to-end run.
- **Things I assumed.** That `prediction_id` is content-derived
  (Phase 5 contract) — verified by reading
  `derive_prediction_id` in `payloads.py`. That the Phase 5
  consensus emits `market="1x2"` lowercase exclusively —
  enforced by `_ALLOWED_MARKETS` validation in `PredictFinal`.
- **Things I might be wrong about.** F3-1 Option A vs B vs C is
  a design call, not just a fix; reasonable people will argue
  for any of the three. My recommendation (B = remove) is the
  smallest possible change that closes the footgun, but if
  there is an unstated requirement to preserve the env var
  (e.g. a Phase 14 K8s scaling story I'm unaware of), then
  Option A or C is the right call. Please push back if so.
- **Diff-size estimates.** Coarse and optimistic, as before.
  Treat as relative ordering, not commitments.
- **What I deliberately left for the human to decide.** Each
  open question in §3 is a binary choice with consequences
  beyond the code — the audit names them but does not pick.

---

*End of audit. Awaiting human review of F3-1 / F3-2 / F3-3 and
sign-off on Wave 5 scope before any implementation begins.*
