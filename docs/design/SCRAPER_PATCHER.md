# `patcher` + `gitops` — The Auto-Patching Scraper Loop

> **Status:** Canonical design. **Implementation is roadmap Phase R3
> onward — nothing is built yet.**
> **Audience:** Anyone reviewing whether it's safe to let an AI agent
> edit this repo, open PRs, and auto-merge them. If you're nervous,
> this doc is for you.
> **Doctrine:** AGENTS.md §2 rules 1, 3, 4, 5, 7, 8, 9.
> **Sibling docs:** [`COMPONENT_LAYOUT.md`](COMPONENT_LAYOUT.md),
> [`DATA_SOURCE.md`](DATA_SOURCE.md),
> [`CONTENT_FRESHNESS.md`](CONTENT_FRESHNESS.md),
> [`TESTING_STRATEGY.md`](TESTING_STRATEGY.md).

This document specifies the two components that together form the
project's **auto-patching scraper loop**:

- [`datasource/patcher`](#3-patcher-the-code-author) — proposes code,
  schema, and migration edits in response to a scraping failure.
- [`datasource/gitops`](#5-gitops-the-pr-driver) — opens PRs, tracks
  review, and auto-merges after a 7-day cool-down when the 5-gate
  policy is green.

Together they produce a closed loop: a source changes → `watcher` or
`refresher` flags it → `patcher` writes a fix → `gitops` ships it. The
loop has guardrails. Those guardrails are the point of this doc.

---

## 1. Guarantees the loop makes (read these twice)

1. **Scope-bounded edits only.** Every PR touches at most the files
   in one of the four declared **scopes** (§4.2). Anything else
   fails the scope gate.
2. **Tests pass or nothing merges.** The loop cannot bypass CI. Not
   with `--no-verify`, not with an admin override, not ever.
3. **The 7-day clock is human-pausable.** Any labeled `hold` comment
   resets the clock and keeps it paused.
4. **Every PR is squash-merged** with a standardized trailer that
   records: failure artifact URL, patcher version, model used, diff
   size, the five gate evaluations, and the merging actor (`gitops`).
5. **Shadow regression kills the merge.** Before auto-merge fires,
   the loop runs the candidate against a shadow predictor cohort on
   the last 72 h of real traffic. >2 % divergence → merge blocked,
   ticket opened, human paged.
6. **Post-merge regression triggers auto-revert.** If the first 24 h
   after merge show >5 % parity-test regression, the `gitops`
   worker opens a revert PR immediately and pages a human.
7. **`git` is AI-restricted** (AGENTS.md §2 rule 9) for normal
   agents. The `gitops` worker is the *only* AI component granted
   git capabilities, scoped via a narrow GitHub App token with zero
   access outside the Negelir repo.
8. **No direct pushes to `main`.** Even in an emergency rollback,
   `gitops` opens a PR and merges through the normal path. This
   keeps `git log main` cleanly reviewable.
9. **AI is downstream of deterministic detection.** No LLM runs on
   a schedule, a heartbeat, or its own initiative. The patcher is
   only invoked in response to a failure artifact produced by a
   non-AI detector (watcher, refresher, parse_failure, parity, etc.
   per §2). If deterministic detection says nothing is wrong,
   nothing is called and nothing is billed. Verified by
   `test_no_ai_without_artifact.py` (§12.14).

If any of the above is ever violated in production, that is a **P0
security incident** and the loop is disabled by a single feature
flag (`NEGELIR_PATCHER=0`) pushed through the config layer.

---

## 2. Failure artifacts (the input)

The patcher only wakes on a **failure artifact**. A failure artifact
is a structured object produced by one of:

| Producer | Trigger | Artifact kind |
|---|---|---|
| `datasource/watcher` | `schema_breaking` verdict | `structural_drift` |
| `datasource/refresher` | `source.degraded` after `N` ticks with no new Records | `content_stall` |
| `datasource/pipeline` | Pydantic validation fails on parsed output | `parse_failure` |
| `datasource/pipeline` | Selector returns empty for `>P90` of pages for 1 h | `extractor_empty` |
| CI | Parity test on the mock stack fails for the current `main` scraper code against a refreshed seed | `parity_failure` |

Artifact shape (`common/schemas/patcher/artifacts.json`):

```json
{
  "artifact_id": "art_2026-04-20T19:45_mackolik_abc123",
  "kind": "parse_failure",
  "source_key": "mackolik",
  "plane": "schedule",
  "detected_at": "2026-04-20T19:45:11Z",
  "detector": "datasource.pipeline.processor.schedule",
  "raw_sample_ref": "s3://seeds/mackolik/20260420/fixtures/0001.html",
  "error": {"type": "ValidationError",
            "path": "$.payload.kickoff_utc",
            "message": "datetime not in ISO-8601"},
  "recent_records_count_24h": 0,
  "severity": "schema_breaking",
  "related_watcher_event": "watcher_evt_2026-04-20T19:41_..."
}
```

Artifacts are persisted to `postgres.patcher_artifacts` (append-only)
and to `feeds/ops/artifacts/<date>/<artifact_id>.json`. This is the
patcher's only input.

---

## 3. `patcher` — the code author

**Path:** `datasource/patcher/`
**Language:** Python 3.12 + Anthropic Agent SDK (see §12)
**Runtime:** single process; `NEGELIR_PATCHER=1` required to run.
**Resource:** no GPU dependency — the patcher container does not
compete with predictor training for the dev rig's GPU.

### 3.1 The loop

```
 failure artifact
        │
        ▼
 1. pre-flight: fetch raw bytes, re-run parser, confirm the failure
        │
        ▼
 2. context build: read relevant source files into a bounded window
        │
        ▼
 3. LLM call: produce a unified diff covering ONE scope (see §4.2)
        │
        ▼
 4. apply diff in a clean workdir (never the live checkout)
        │
        ▼
 5. run the "patcher test gauntlet" (§4.3)
        │
        ├─ fail → loop to 3 with retry budget (default 3 attempts)
        │        if still failing → emit `patcher.unable` + human page
        │
        ▼
 6. bundle diff + tests + artifact references → hand off to `gitops`
```

### 3.2 Guardrails on the LLM step

The model is untrusted. The runner is trusted. Every LLM output is
filtered before it touches a file system:

1. **Parse the unified diff.** Non-parsing output is discarded; one
   retry allowed; second failure → escalate to human.
2. **Check scope.** Every touched path must match the declared
   scope's allow-list (§4.2). One stray file = diff rejected.
3. **Check size.** Total diff ≤ `cfg.patcher_max_diff_lines` (default
   400 added + 400 removed). Over the limit = diff rejected.
4. **Check forbidden patterns.** Regex veto for `subprocess.`,
   `os.system`, `eval(`, `exec(`, `__import__`, network literals
   outside config, secrets-shaped strings, any edit under
   `xops/versioning/`, `AGENTS.md`, `docs/planning/`.
5. **Check config drift.** If the diff adds a new env var, it must
   also update `xops/env/.env.example` and `ai/common/config.py`.
   The `no_magic.py` lint gate runs on the patched tree.

Only diffs passing all five filters enter step 4 of the loop.

### 3.3 Sandboxed execution

The diff is applied in a container built from the project's image,
mounted read-only for the rest of the repo and read-write only for
`/workspace`. Tests run inside this sandbox. The sandbox has no
network except to `mocksrv` (for parity-testing live upstreams is
not allowed — real hosts are off-limits to the patcher by IP
allow-list on the sandbox network).

### 3.4 What the patcher may edit

Declared as **scopes**. The artifact `kind` picks the scope.

### 3.5 Proof tests for the patcher itself

- `datasource/patcher/tests/test_diff_must_parse.py` — simulated LLM
  output that is not a valid diff fails fast with `patcher.reject`.
- `datasource/patcher/tests/test_scope_enforcement.py` — a diff that
  touches a file outside the declared scope is rejected.
- `datasource/patcher/tests/test_size_enforcement.py` — a diff over
  `cfg.patcher_max_diff_lines` is rejected.
- `datasource/patcher/tests/test_forbidden_patterns.py` — a diff
  that introduces `subprocess.`, `eval(`, or a hardcoded URL is
  rejected.
- `datasource/patcher/tests/test_sandbox_isolation.py` — a diff that
  tries to open `api.github.com` inside the sandbox fails at the
  network layer.
- `datasource/patcher/tests/test_retry_budget.py` — three failed
  attempts → `patcher.unable` emitted exactly once; no infinite loop.
- `datasource/patcher/tests/test_idempotent_on_artifact_id.py` —
  submitting the same artifact twice produces one PR (by
  `artifact_id` → PR mapping in `postgres.patcher_prs`).

---

## 4. Scopes — the four things the patcher may change

### 4.1 Why scopes

"Touch any file to fix anything" is too much rope. Every failure kind
maps to exactly one scope, and the scope's allow-list is enforced
before the diff is even tested. This makes reviews fast and
post-hoc audits mechanical.

### 4.2 The four scopes

| Scope | Allow-list (glob) | Triggered by artifact kind | Typical diff |
|---|---|---|---|
| **`extractor`** | `datasource/scraper/extractors/<source>/**.py`; `datasource/scraper/selectors.json`; `datasource/scraper/tests/fixtures/<source>/**` | `parse_failure`, `extractor_empty`, `structural_drift` | Selector rewrite; new parsing branch; new fixture to cover the breakage |
| **`schema`** | `common/schemas/records.py`; `common/schemas/feeds/*.json`; `common/schemas/tests/**` | `parse_failure` with `path` in a missing field | New optional field on a payload schema; registry update to mark new version `active` |
| **`migration`** | `migrations/NNN_*.sql` (next free N); `common/schemas/records.py` if column change reflects envelope | `parse_failure` where the DB column can't hold the new value | Additive migration (`ADD COLUMN`, `CREATE INDEX`, never `DROP`) |
| **`fixture`** | `infra/mock/seeds/<source>/**`; `infra/mock/seeds/manifest.json` | `parity_failure` only | Refresh the seed to current upstream bytes (captured through `make mock.capture`, not fabricated by the LLM) |

Each scope has a matching `scope:<name>` label applied to the PR.

### 4.3 The patcher test gauntlet

Every candidate diff runs this gauntlet in the sandbox. **Every
gate must pass** before the diff leaves the patcher.

| # | Gate | Command | Purpose |
|---|---|---|---|
| 1 | Lint | `make lint` | No new magic numbers, no hardcoded URLs, style passes |
| 2 | Type | `mypy --strict` on touched modules | No new type holes |
| 3 | Unit tests | `make test.fast` | Nothing else broke |
| 4 | Parity | `make test.parity SOURCE=<source>` | The extractor now produces the expected Records on the seed that failed, AND on all previously-green seeds for that source |
| 5 | Isolation | `make test.isolation` | Scope boundary not violated (§4.2) |

If all five are green, the diff bundles into a patcher output:

```json
{
  "bundle_id": "bundle_2026-04-20T20:02_mackolik_abc123",
  "artifact_id": "art_2026-04-20T19:45_mackolik_abc123",
  "scope": "extractor",
  "diff_bytes": "<unified diff>",
  "gauntlet": {
    "lint": "pass", "type": "pass", "unit": "pass",
    "parity": "pass", "isolation": "pass"
  },
  "patcher_version": "0.3.1",
  "model": "qwen2.5-coder-7b-instruct@2026-03",
  "prompt_sha256": "<hash>",
  "total_tokens": 18421
}
```

### 4.4 Which LLM

**Superseded by §12.** Phase 17 ships with the Anthropic Agent SDK
(Haiku → Sonnet → Opus tiered). The local-model alternative
(qwen2.5-coder, deepseek-coder) is retained as a fallback design
should Anthropic become unavailable or doctrine change. See §12 for
the canonical model-provider design.

### 4.5 Deferred fifth scope — `detector_tuning`

**Status:** Designed but disabled in Phase 17. Activated in a later
sub-phase (R3.x) only after we have ≥ 100 false-positive artifacts
labeled by humans and a per-detector FP rate baseline.

When deterministic detectors (watcher, refresher, parse_failure
threshold rules) produce false positives, the patcher could in
principle help by tuning the detector's threshold constants. This
scope makes that possible **without** letting the patcher edit
detector logic.

| Allow-list (glob) | Triggered by | Typical diff |
|---|---|---|
| `datasource/watcher/thresholds/*.yaml`, `datasource/refresher/thresholds/*.yaml`, `datasource/pipeline/profiles/<source>.yaml` | Human applies `false-positive` label to a patcher PR; after `cfg.detector_fp_count >= 5` for that detector in the last 30 days, the next FP triggers a `detector_tuning` artifact | Threshold relaxation; per-source exception (e.g. "TFF press releases sometimes empty during off-season") |

**Mandatory extra gauntlet step for this scope:**

5. **True-positive corpus replay.** The modified detector is run
   against every artifact in the last 90 days that led to a merged
   patcher PR (i.e. a real bug was fixed). The detector **must
   still flag every one of them**. Missing a single past true
   positive → diff rejected, no exceptions.
6. **False-positive corpus replay.** The modified detector is run
   against artifacts marked `false-positive`. It should now flag
   strictly fewer of them. Same-or-more → diff rejected.

Threshold constants live in YAML config files (not in code) so the
allow-list is a tight glob, the diff is small and human-readable,
and the modification is reversible by editing one number.

**Why deferred:** detector tuning is the highest-trust scope (it
weakens detection sensitivity by definition). We need real FP data
before we can responsibly automate it. Until then, false positives
are handled by the FP feedback loop (§12.10) and human-applied
threshold tweaks.

---

## 5. `gitops` — the PR driver

**Path:** `datasource/gitops/`
**Language:** Python 3.12
**Runtime:** single process. **Only component with a GitHub token.**

### 5.1 GitHub credentials

A dedicated **GitHub App** is registered for the project. Scopes:

- `Contents: Read & write` on this repo only.
- `Pull requests: Read & write` on this repo only.
- `Checks: Read` on this repo only.
- No organization scope. No user scope. No write access anywhere else.

Token lifetime: ≤ 60 minutes, rotated via installation-token exchange
on every use. The App's private key lives in `xops/env/.env` as
`NEGELIR_GITOPS_GITHUB_APP_KEY` (user-provided; not in git).

### 5.2 PR lifecycle

```
 patcher bundle
        │
        ▼
 1. create branch: patcher/<artifact_id>
 2. apply diff, commit with standardized message
 3. push branch
 4. open PR with standardized title + body + labels
 5. watch PR (poll every `cfg.gitops_poll_min`, default 15 min)
        │
        ├─ reviewer merges → record merge provenance, done
        ├─ reviewer closes → record `closed_by_human`, done
        ├─ `hold` label added → reset 7-day clock, keep watching
        ├─ 7 days elapsed AND 5-gate green → auto-merge (§6)
        └─ post-merge regression → auto-revert (§7)
```

### 5.3 Branch + PR formatting

- Branch: `patcher/<artifact_id>`
- Commit: squash; message follows Conventional Commits:
  ```
  fix(<source>): <short description>

  Auto-generated by datasource/patcher v<semver> in response to
  artifact <artifact_id>.

  Scope: <extractor|schema|migration|fixture>
  Gauntlet: lint pass, type pass, unit pass, parity pass, isolation pass
  Model: <model_id>
  Patcher-Bundle-ID: <bundle_id>
  ```
- PR title: `[patcher] <source>: <artifact.error.message | 80 chars>`
- PR body: artifact JSON (pretty), gauntlet report, diff summary,
  shadow regression result (once run — see §6.4).
- Labels: `patcher`, `source:<source>`, `scope:<scope>`,
  `severity:<severity>`.

### 5.4 Proof tests

- `datasource/gitops/tests/test_pr_open.py` (VCR fixtures for
  `api.github.com`) — bundle in → PR opened with the correct
  labels and body.
- `datasource/gitops/tests/test_hold_label_resets_clock.py` — a
  `hold` label applied at day 5 resets the cool-down; removal at
  day 9 restarts it.
- `datasource/gitops/tests/test_no_force_push.py` — any attempt to
  push with `--force` fails (branch protection on `main` is also a
  real-world safety net).
- `datasource/gitops/tests/test_token_scope.py` — rejects tokens
  that have broader scope than the allow-list.
- `datasource/gitops/tests/test_no_direct_push_to_main.py` —
  guarantee §1.8: every gitops push targets a `patcher/<artifact_id>`
  branch; any code path that would push refs/heads/main (or `master`,
  or any protected branch from `cfg.gitops_protected_branches`) raises
  before invoking the GitHub API. Complements GitHub branch protection
  with an in-process assertion so the regression is visible in CI, not
  only in production.
- `datasource/gitops/tests/test_squash_trailer_format.py` —
  guarantee §1.4: the commit message produced for the squash-merge
  contains the full standardized trailer block (`Scope:`,
  `Gauntlet:`, `Model:`, `Patcher-Bundle-ID:`) with non-empty values
  in the documented order. A property-style fuzz over 50 random
  bundle inputs ensures no field is dropped or re-ordered.
- `datasource/gitops/tests/test_only_gitops_holds_token.py` —
  guarantee §1.7: a grep over the repo asserts that
  `NEGELIR_GITOPS_GITHUB_APP_KEY` is read only from
  `datasource/gitops/**` and that no other component imports a
  GitHub client library or sets `GH_TOKEN` / `GITHUB_TOKEN`.

---

## 6. The 5-gate auto-merge policy

At `clock_start + 7 days` (calendar days, UTC), `gitops` evaluates
the **5-gate policy**. All five must be green and no `hold` label
present; otherwise merge is skipped for another polling cycle and a
comment is posted explaining which gate is red.

### 6.1 Gate 1 — CI green

`main`-targeted CI run for the PR head commit is green. No skipped
required checks. No pending checks.

### 6.2 Gate 2 — Review signal

At least one of:

- An explicit `LGTM` comment from a human reviewer, OR
- Zero `request-changes` reviews AND the PR has been open for ≥ 7 days
  (the cool-down itself counts as "no objections").

A single `request-changes` review that has not been dismissed blocks
the gate until dismissed by its author.

### 6.3 Gate 3 — Scope & size

- Scope label present and matches the bundle's `scope`.
- `git diff --numstat` matches the bundle's declared size ± 0 lines
  (exact match — no drift allowed between `patcher` output and the
  final PR).

### 6.4 Gate 4 — Shadow regression

The `gitops` worker asks `server/internal` to spin up a **shadow
predictor cohort** running the patched extractor, and compares its
output over the last 72 h of mock-replay traffic against the current
`main` predictor cohort.

- `| Δ log-loss |` ≤ `cfg.gitops_shadow_logloss_threshold` (default
  0.002).
- `| Δ ECE |` ≤ `cfg.gitops_shadow_ece_threshold` (default 0.005).
- No plane shows `>2 %` record-count divergence.

If any threshold fails, the gate is red and a `shadow-regression`
label is applied. Only a human can dismiss this label.

### 6.5 Gate 5 — No active incident

If there is any open `incident:*` label on the repo, or if the
`observability` stack reports the project in a degraded state
(SLO burn rate > 1 h), the gate stays red until the incident clears.
This exists so we never ship patches during a firefight.

### 6.6 Merge

When all five gates are green, `gitops` executes:

- Squash merge via the GitHub API.
- Commit trailer appended (see §5.3).
- Tracker row written via `make track.add` (tracker is the one
  channel `gitops` is allowed to write to outside code).
- `patcher.merged` event published.

### 6.7 Proof tests

- `test_five_gates_all_green.py` — happy path, merge fires.
- `test_five_gates_any_red_blocks.py` — each gate independently
  blocks; merge does not fire.
- `test_hold_label_blocks_indefinitely.py` — `hold` applied at day
  6 keeps blocking at day 30; removal re-starts the 7-day clock.
- `test_shadow_regression_blocks.py` — an injected 3 % log-loss
  delta produces a red Gate 4.
- `test_active_incident_blocks.py` — an `incident:api` label on the
  repo produces a red Gate 5 even if all others are green.

---

## 7. Post-merge regression watchdog

The first 24 h after an auto-merge is the riskiest window. `gitops`
runs a **post-merge watchdog**:

- Subscribe to `freshness.events.v1` and `swarm.drift` streams.
- Compute per-source parity-pass rate vs. the 7-day baseline.
- If parity-pass rate drops by `> cfg.gitops_regression_threshold`
  (default 5 %) in any contiguous 1 h window, open a revert PR
  (`Revert: <original PR title>`) and page a human.

### 7.1 Proof tests

- `test_regression_triggers_revert.py` — inject a fake parity drop,
  assert a revert PR is opened within 5 min (fake clock).
- `test_revert_has_same_scope.py` — revert PR carries the scope
  label of the original.

---

## 8. Kill switches

In priority order:

1. **`NEGELIR_PATCHER=0`** — config flag. Stops `patcher` from
   consuming artifacts. Existing PRs remain open.
2. **`NEGELIR_GITOPS_AUTOMERGE=0`** — keeps opening PRs but never
   auto-merges. Humans still review as usual.
3. **GitHub App suspension** — most forceful. Revokes the token at
   GitHub's side; the loop cannot act even if the container is
   running.

All three are documented in `xops/env/.env.example` and verified in
`test_kill_switches.py`.

---

## 9. Security posture

| Threat | Mitigation |
|---|---|
| LLM produces a backdoor (e.g. `if user == 'x': skip_auth`) | Scope-bounded diff never touches auth code; forbidden-pattern scan; mandatory human review on first 10 PRs per source (ramp-up); post-merge shadow cohort |
| LLM leaks secrets into a diff | Secrets-shaped-string regex veto at patcher-side; repo-level secret-scan on every PR push |
| Compromised GitHub App token | 60-minute token lifetime; allow-list of repo-scoped permissions; GitHub audit log integrated to `observability` |
| Sandbox escape during gauntlet | Sandbox network blocks all egress except to `mocksrv`; read-only repo mount except `/workspace` |
| Malicious `hold`-label griefing (reviewer pauses indefinitely) | Audit log of label operations; a label-only pause beyond 30 days auto-escalates to a human-review ticket for the patcher owner team |
| Race between patcher retries | `test_idempotent_on_artifact_id.py` + Postgres unique key on `patcher_prs.artifact_id` |
| Model drift introduces systemic bias | Weekly retro: per-`patcher.merged`, parity-pass delta recorded; if delta median trends negative over 4 weeks, auto-pause and escalate |

---

## 10. Phased rollout (overview)

High-level cross-reference to ROADMAP Phase 17 / R3. The **canonical,
refined sub-phase table that includes the Anthropic-tier ramp** lives
at §12.15. This section is the operator-facing one-pager.

| Sub-phase | Capability | Blast radius |
|---|---|---|
| R3.a | Artifact schema + detectors wired; no patcher yet | Zero |
| R3.b | `patcher` in dry-run mode: produces bundles, stores them, never hands to `gitops`; **no API calls** | Zero |
| R3.b' | First $5 of real Anthropic spend, Tier-1 (Haiku) only against mock-stack artifacts | Bounded |
| R3.c | `gitops` opens PRs; auto-merge **disabled** (`NEGELIR_GITOPS_AUTOMERGE=0`); Haiku + Sonnet enabled | Humans decide |
| R3.d | Auto-merge enabled with 30-day cool-down + mandatory human review on first 10 per source; Opus enabled | Bounded |
| R3.e | Cool-down relaxed to 7 days once 50 consecutive patcher PRs merged without post-merge regression | Target state |
| R3.f | Revert watchdog live | Target state |

Every step is config-flag gated; rollbacks are a one-line change to
`xops/env/.env`. See §12.15 for the canonical (model-aware) version of
this table.

---

## 11. Operator runbook pointers

This section is intentionally a stub. The operator-facing runbooks
(how to disable the loop in an incident, how to read the cost ledger,
how to revert a bad merge by hand) live in `docs/guides/PATCHER_OPS.md`
and will land alongside Phase 17 R3.b. Until then the canonical
emergency procedure is:

1. Flip `NEGELIR_PATCHER=0` in `xops/env/.env` (kill switch §8.1).
2. Optional: flip `NEGELIR_GITOPS_AUTOMERGE=0` to keep PRs open
   without merging (kill switch §8.2).
3. Most forceful: suspend the GitHub App from the GitHub UI
   (kill switch §8.3).

All three are exercised by `test_kill_switches.py` (§17.7).

---

## 12. Model providers (Anthropic Agent SDK)

> **Supersedes §4.4.** This section is the canonical model-provider
> design for Phase 17. The local-model alternative remains documented
> as a contingency.

### 12.1 Why Anthropic Agent SDK

The patcher's value is bounded above by the *quality of the diff
proposed* and bounded below by the *cost per artifact*. Anthropic's
Agent SDK gives us:

- **Frontier coder quality** (Sonnet 4.5 / Opus 4.x) for the hard
  cases — schema deltas, novel selector patterns, edge-case parsers.
- **The same harness Copilot uses for its Claude modes** — multi-turn
  iterate-edit-test-observe loops, file-edit tools, structured tool
  use, content-block separation. We are *not* re-implementing that.
- **Prompt caching** — the project's stable context (CLAUDE.md,
  per-scope guidance, doctrine) is sent once per cache window and
  costs ~10 % of normal input tokens for the rest of the window.
- **No GPU dependency** — the patcher container does not compete
  with predictor training for the dev rig's GPU.

The trade-off is an external dependency on `api.anthropic.com`,
non-determinism per call, and per-token cost. The mitigations are
the rest of this section.

### 12.2 Three-tier model routing (harness-driven)

The patcher does **not** ask the model to choose its own tier. A
deterministic classifier in the patcher harness picks the tier from
observable signals (artifact `scope`, `severity`, `retry_count`,
budget remaining). The model has exactly one narrow self-escalation
tool (`request_escalation`, see §12.4).

| Tier | Model (env-var-pinned) | When chosen |
|---|---|---|
| **1 — Haiku** | `NEGELIR_PATCHER_TIER1_MODEL` (e.g. `claude-haiku-4-5-<date>`) | `scope=extractor` AND `severity=normal` AND `retry_count=0` AND budget OK |
| **2 — Sonnet** | `NEGELIR_PATCHER_TIER2_MODEL` (e.g. `claude-sonnet-4-5-<date>`) | `scope in {schema, migration}` OR Tier-1 retry OR Tier-1 self-escalated OR `severity=high` |
| **3 — Opus** | `NEGELIR_PATCHER_TIER3_MODEL` (e.g. `claude-opus-4-<date>`) | Tier-2 gauntlet failed twice OR `scope=detector_tuning` (when enabled) OR Tier-2 self-escalated |
| **Unable** | n/a | Tier-3 gauntlet failed → `patcher.unable` event, human paged |

Models are pinned by exact ID (never `*-latest`). The pin is recorded
in every bundle trailer.

### 12.3 Diagnostic bundle (the input to the model)

A failure artifact (§2) is the *trigger*. The **diagnostic bundle**
is what's actually sent to the model. The deterministic
`datasource/*` workers assemble it before any API call so the model
spends tokens on *fixing* the problem, not on *discovering* it.

The bundle is a structured JSON document plus a set of file
references. It lives at
`feeds/ops/bundles/<bundle_id>/diagnostic.json` and contains:

| Field | Source | Why |
|---|---|---|
| `artifact` | the artifact JSON (§2) | Ground truth: what fired |
| `reproduction` | output of pre-LLM reproduction check (§12.9) | Did we re-confirm the failure? |
| `failing_sample` | bytes of the URL/page/payload that failed (≤ 200 KB; truncated with marker if larger; full bytes referenced via path) | What the parser saw |
| `passing_samples` | up to 3 most recent green seeds for the same `(source, plane)` | Anti-pattern context |
| `recent_records` | last 5 successful Records from `(source, plane)` | "What good output looks like" |
| `failing_code_excerpt` | content of the parser file with ±20 lines around the failure point | The code likely to need editing |
| `git_history` | last 10 commits touching the failing file (hash, author, date, subject) | Has this been touched recently? Was it an earlier fix? |
| `similar_past_artifacts` | up to 3 past artifacts with same `(source, kind)` in last 30 days, plus their resolution (merged PR diff, or FP label, or `patcher.unable`) | **Past-success seeding** (§12.8) |
| `scope_assignment` | `extractor` / `schema` / `migration` / `fixture` / `detector_tuning` with rationale | Tells the model what files it may edit |
| `forbidden_patterns` | the regex list that will be applied post-hoc | Lets the model avoid known-rejected patterns up front |
| `gauntlet_commands` | exact `make` / `pytest` invocations the gauntlet will run | Lets the model run them itself during the session |
| `budget_remaining_usd` | live snapshot | Lets the model bias toward fewer tool turns when budget is tight |

Hard cap on bundle size: `cfg.patcher_bundle_max_kb` (default 256
KB). Anything larger is referenced as a file path the model can
`Read` on demand.

The bundle is built by `datasource/patcher/bundle_builder.py` (no
LLM involvement). Its content is deterministic given the artifact +
repo state.

### 12.4 Tool allow-list (locked)

The Agent SDK session is configured with **only** these tools.
Anything else is refused at the SDK's `can_use_tool` callback.

| Tool | Constraint |
|---|---|
| `Read(path)` | Path must be under sandbox cwd; symlink traversal blocked |
| `Edit(path, old, new)` | Path must match the scope's allow-list (§4.2) glob |
| `Write(path, content)` | Same scope enforcement; no overwrite of files outside scope |
| `Bash("pytest ...")` | Regex-pinned: `^pytest( -[a-z]+)*( [a-zA-Z0-9_/.\-:]+)*$` |
| `Bash("make ...")` | Regex-pinned to a closed list: `make lint`, `make test.fast`, `make test.parity SOURCE=<known-source>` |
| `request_escalation(reason: str)` | The single self-escalation tool. Promotes the same artifact to the next tier and ends the current session. |

**Explicitly disabled:** general `Bash`, `WebFetch`, `WebSearch`,
all `mcp__*` families, any tool that opens a network socket. The
sandbox network policy (egress allow-list: `mocksrv` +
`api.anthropic.com` only) is the second line of defense.

### 12.5 Context layering & prompt caching

Three layers of context, mapped onto Anthropic's prompt cache so
the stable parts are paid for once per cache window.

| Layer | Source | Cache TTL | Rebuilt when |
|---|---|---|---|
| **L1 — Repo context** | `CLAUDE.md` at repo root | 1 hour (extended) | `CLAUDE.md` changes |
| **L2 — Scope context** | `xops/patcher/context/scope_<name>.md` for the assigned scope | 1 hour | The scope file changes |
| **L3 — Diagnostic bundle** | Per-artifact `diagnostic.json` + referenced files | Not cached | Every call |

The system prompt for an Agent SDK session is constructed as:

```
[L1 — cached]   CLAUDE.md content
[L2 — cached]   scope_<name>.md content
[L3 — fresh]    "You are operating on this artifact:" + diagnostic.json
```

L1 + L2 typically run 15–25k tokens. After the first call in a
window, those 15–25k tokens cost ~1.5–2.5k token-equivalents of
input — order-of-magnitude saving. L3 is small (a few KB) and
per-artifact.

**`CLAUDE.md` content** (anchor, repo root):

- Project doctrine summary (links to AGENTS.md §2 — does not
  duplicate)
- Component layout summary (links to COMPONENT_LAYOUT.md)
- Record + Feed contract pointer (DATA_PIPELINE.md, EMITTER.md)
- The patcher's invariants from §1 of this doc, restated as
  imperatives for the model
- Pointer to per-scope context files
- Pointer to the diagnostic bundle for the current artifact

**Per-scope files** (`xops/patcher/context/`):

- `scope_extractor.md` — scraper layout, selector conventions,
  fixture file naming, parser entry points
- `scope_schema.md` — Record/Feed schema rules, additive-only
  policy, deprecation lifecycle (EMITTER §4)
- `scope_migration.md` — migration file numbering, no-DROP rule,
  reversibility expectations
- `scope_fixture.md` — `make mock.capture` workflow, manifest sync
  rules
- `scope_detector_tuning.md` — (when activated) threshold YAML
  layout, true/false positive corpus locations

### 12.6 Cost management

Six mechanisms, in order of impact:

1. **Pre-LLM reproduction check (§12.9).** Skips the API entirely
   for non-reproducible failures. Estimated savings: 30–50 % of
   artifacts in steady state.
2. **Diagnostic bundle (§12.3).** Removes the model's "discovery"
   round-trips. Estimated savings: 40–60 % of tokens per session.
3. **Aggressive prompt caching (§12.5).** Stable context billed at
   ~10 %. Estimated savings: 70–85 % of input tokens at typical
   session volume.
4. **Tier routing (§12.2).** Easy artifacts on Haiku
   (5–15× cheaper than Opus). Estimated steady-state mix: 70 %
   Haiku, 20 % Sonnet, 10 % Opus.
5. **Past-success seeding (§12.3 `similar_past_artifacts`).** When a
   near-identical past artifact was fixed by diff X, the bundle
   includes that diff as a starting hypothesis. Cuts model
   exploration time for recurring breakages.
6. **Deduplication & per-source cooldown (§12.7).** Prevents the
   same break from triggering N parallel sessions.

**Hard caps (config-driven, enforced in `bundle_builder.py` and the
session runner):**

| Config key | Default | Behavior at threshold |
|---|---|---|
| `NEGELIR_PATCHER_MONTHLY_USD_CAP` | `20.00` | Patcher pauses; outstanding artifacts queue; human paged |
| `NEGELIR_PATCHER_PER_ARTIFACT_USD_CAP` | `0.50` | Current session aborted; artifact marked `patcher.unable` (cost) |
| `NEGELIR_PATCHER_PER_DAY_USD_CAP` | `5.00` | Patcher pauses for the day; resumes at UTC 00:00 |
| `NEGELIR_PATCHER_BUNDLE_MAX_KB` | `256` | Bundle truncated; oversized fields reference files |
| `NEGELIR_PATCHER_MAX_AGENT_TURNS` | `25` | Session aborted; artifact retried with next tier or marked unable |
| `NEGELIR_PATCHER_USE_BATCHES` | `false` | When `true`, non-urgent artifacts route through Anthropic Batch API (50 % discount, 24 h turnaround). Default off for R&D; flip on at production volume. |

The cost ledger lives in Postgres
(`postgres.patcher_cost_ledger`, append-only) and is reconciled
nightly against Anthropic's usage API.

### 12.7 Deduplication & per-source cooldown

| Mechanism | Trigger | Effect |
|---|---|---|
| **Artifact dedup** | New artifact whose `(source, plane, error_signature)` matches an open or recently-closed bundle within `cfg.patcher_dedup_window_min` (default 60 min) | Attach to the existing bundle as a duplicate; do not open a new session |
| **Per-source cooldown** | Patcher has run ≥ `cfg.patcher_source_cooldown_max` (default 3) sessions for a single source in the last hour | Quarantine that source's new artifacts for `cfg.patcher_source_cooldown_min` (default 60 min); page a human if quarantine extends > 4 h |
| **Global rate limit** | Patcher has run ≥ `cfg.patcher_global_rate_max` (default 20) sessions in the last hour | Pause new sessions for 15 min; protects against detector storms |

These prevent the most likely cost-runaway scenarios: a single
upstream change triggering hundreds of artifacts, or a noisy
detector firing in a loop.

### 12.8 Past-success seeding

When the diagnostic bundle's `similar_past_artifacts` field
contains a previously-merged fix, that fix's diff is included in
the system prompt as:

> *"A similar artifact was previously fixed by the following diff.
> If the same approach applies here, prefer it; if not, explain why
> in your first message and propose a different fix."*

This is the single highest-leverage prompt technique for recurring
breakages (e.g. Mackolik changes the same selector class twice in a
month). Empirically reduces Tier-1 turn count by ~40 % on recurring
artifacts.

The "similar" comparison is deterministic: same `source`, same
`plane`, same `kind`, error message edit-distance < 0.3. No LLM
involved in the matching.

### 12.9 Pre-LLM reproduction check

Before any session opens, the patcher harness re-runs the parser
that produced the artifact against the cited `raw_sample_ref`.

- **Reproduces** → continue to bundle build + session.
- **Does not reproduce** → artifact downgraded to
  `false_positive_self_resolved`; logged; no API call; no PR.
  Counts toward the per-detector FP rate (§12.10).

Cost: zero API tokens. Catches the common case where an upstream
fixed itself between detection and patcher run.

### 12.10 FP feedback loop (deferred sub-phase)

When a human applies a `false-positive` label to a patcher PR, or
when a `patcher.unable` artifact is marked FP by a human, the
detector that produced the artifact gets a counter increment in
`postgres.detector_fp_stats`. Two automated responses:

- When a detector's rolling 100-artifact FP rate exceeds
  `cfg.detector_fp_warn_threshold` (default 0.5), `gitops` posts a
  comment on the next PR from that detector and pages a human.
- When the rate exceeds `cfg.detector_fp_quarantine_threshold`
  (default 0.7) for two consecutive weeks, that detector's
  artifacts auto-route to **dry-run mode** (bundle stored, no PR
  opened) until a human intervenes.

Quarantine bounds blast radius without disabling detection.
Combined with the `detector_tuning` scope (§4.5), this gives the
system a path to reduce FPs over time *without* the patcher being
allowed to silently weaken detection.

### 12.11 Security additions

| Threat | Mitigation |
|---|---|
| **Prompt injection via scraped HTML** | Failing samples are passed to the SDK as `document` content blocks (Anthropic's structured-content type), never inlined into instructional text. Forbidden-pattern scan still applies post-hoc. |
| **Token exfiltration via tool output** | Anthropic API key never appears in any tool input/output; sandbox env is scrubbed of `NEGELIR_PATCHER_ANTHROPIC_KEY` before the session starts. |
| **Anthropic API key leakage** | Key lives only in `xops/env/.env`; injected into the patcher container via env (never command line); rotated quarterly; one key per environment (dev/staging/prod). |
| **Malicious tool-call shaping** | Tool allow-list (§12.4) is the perimeter. New tools require a doc + a proof test before they can be enabled. |
| **Cost runaway via prompt-injection** | Per-artifact cap (§12.6) bounds the worst case. A single attacker-crafted page cannot cost more than `$0.50`. |

### 12.12 Determinism & audit trail

- **Model pinning.** Every bundle records the exact model ID used
  (e.g. `claude-haiku-4-5-20260317`). `*-latest` aliases are
  forbidden.
- **Session trace.** Every Agent SDK turn (request, tool calls,
  responses) is appended to
  `feeds/ops/bundles/<bundle_id>/trace.jsonl`. Enables post-hoc
  audit and regression replay.
- **Cost record.** Every session writes a `cost.json` next to the
  trace with input tokens (cached + uncached), output tokens, USD
  cost, model ID, tier.
- **Bundle trailer in commit messages.** Per §5.3, the squash
  commit includes `Model: <id> | Tier: <n> | Tokens-In: <n>
  (cached: <n>) | Tokens-Out: <n> | Cost-USD: <amount> |
  Bundle-ID: <id>`.

### 12.13 Batch API (noted, default off)

Anthropic's Message Batches API offers a 50 % discount with up to
24 h turnaround. Suitable for non-urgent artifacts:
`severity != schema_breaking` AND `artifact.detected_at > 1 h ago`.

Default `NEGELIR_PATCHER_USE_BATCHES=false`. Rationale: during
R&D and early production, fast feedback per-artifact is more
valuable than the cost saving. Flip to `true` when monthly volume
makes the discount material (rough threshold: > 200 artifacts/month).

### 12.14 Proof tests

Required to ship Phase 17 sub-phase by sub-phase. All in
`datasource/patcher/tests/` unless noted.

- `test_no_ai_without_artifact.py` — patcher startup with empty
  `patcher_artifacts` table makes zero Anthropic API calls in 60 s.
- `test_classifier_routing.py` — every `(scope, severity,
  retry_count)` tuple routes to the expected tier (table-driven).
- `test_request_escalation_promotes_one_tier.py` — Tier-1 calling
  `request_escalation` lands the artifact at Tier-2, not Tier-3.
- `test_tool_allow_list.py` — attempting `Bash("curl ...")`,
  `WebFetch`, `WebSearch`, or any `mcp__*` is refused.
- `test_diagnostic_bundle_built.py` — bundle contains all required
  fields; size ≤ cap; no LLM was invoked during build.
- `test_pre_llm_reproduction_skips_api.py` — non-reproducing
  artifact is downgraded to `false_positive_self_resolved`; zero
  API calls.
- `test_budget_caps.py` — monthly, daily, per-artifact caps each
  pause/abort cleanly when injected ledger crosses threshold.
- `test_dedup_window.py` — duplicate artifact within window
  attaches to existing bundle; outside window opens new session.
- `test_per_source_cooldown.py` — 4th artifact for one source in
  one hour quarantines that source.
- `test_cache_hit_rate.py` — 10 consecutive same-window sessions
  produce ≥ 60 % cache hit rate (against a recorded VCR cassette).
- `test_cost_ledger_accuracy.py` — ledger total within 1 % of
  Anthropic usage API report after a recorded session batch.
- `test_model_pin_enforced.py` — `*-latest` model IDs rejected at
  patcher startup.
- `test_prompt_injection_separated.py` — failing sample bytes are
  passed as `document` content block, never as text content.
- `test_session_trace_recorded.py` — every session produces a
  `trace.jsonl` with one line per Agent SDK turn.
- `test_past_success_seeded.py` — a recurring artifact's bundle
  contains the previous merged diff in `similar_past_artifacts`.
- `test_quarantine_on_high_fp.py` — a detector with > 0.7 FP rate
  for 2 weeks auto-routes to dry-run.
- `test_batch_api_off_by_default.py` — `NEGELIR_PATCHER_USE_BATCHES`
  defaults to `false` and the real-time path is exercised.

### 12.15 Phased rollout (refines §10)

| Sub-phase | Capability | Tier enabled | Real money? |
|---|---|---|---|
| R3.a | Detectors + artifacts | none | no |
| R3.b | Patcher dry-run; diagnostic bundle built; **no API calls** | none | no |
| R3.b' | Patcher dry-run; **Tier-1 only** against mock artifacts | Haiku | yes (capped at $5) |
| R3.c | PRs opened; auto-merge off; tier routing live | Haiku + Sonnet | yes (capped at $10) |
| R3.d | Auto-merge with 30-day cool-down; first 10/source human-only | Haiku + Sonnet + Opus | yes (capped at $20 — your starting budget) |
| R3.e | Cool-down → 7 days after 50 clean merges | full | scales with volume |
| R3.f | Post-merge revert watchdog | full | scales with volume |
| R3.g | (Deferred) `detector_tuning` scope enabled | full | scales with volume |
| R3.h | (Deferred) Batch API enabled when volume justifies | full | reduces unit cost |

---

## 13. Open questions

- **Migration scope escalation.** What if a `schema` scope PR also
  needs a `migration`? Current answer: the patcher splits it into
  two PRs (schema first, then migration); they are linked via
  `Patcher-Chain-ID` trailer. Alternative (atomic multi-scope PR)
  is a Phase 14 consideration.
- **Cross-source patches.** If `mackolik` and `tff` share a bug
  through a common utility module, a fix touches two scopes. Today
  we require the common utility to be under `common/` (which is not
  an allowed scope) or to have its own dedicated scope. We haven't
  ruled on this yet; tracked in an R3.x sub-phase TBD.
- **Custom model adaptation.** Anthropic's Agent SDK does not expose
  fine-tuning. Once we have ≥ 500 merged patcher PRs, the cheap
  alternative is **prompt-side adaptation** — generate a curated
  "recurring patterns" digest from the PR history and inject it into
  the L2 scope context (§12.5). The expensive alternative is moving
  off Anthropic to a fine-tunable model (qwen2.5-coder /
  deepseek-coder family); this is the same fallback design the
  pre-Pivot-v3 §4.4 documented and stays as a contingency only.
  Decision deferred until the corpus is large enough.
- **Whether the patcher can ever touch `swarm/*`.** Current answer:
  **no**. The patcher is a scraping-loop component, not a model-
  editing component. If we ever want an "auto-retrainer" of models,
  it lives in a different doc and a different component.
