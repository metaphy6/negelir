# Phase 8.4 — Source-watcher SDK + LLM-summarizer graduation

> Extracted from `docs/planning/ROADMAP.md` §8.4
> as part of the phase-split modularization (mirrors the Phase 10
> pattern at `docs/design/phase10/sections/`). The `[ ]`/`[x]` state
> below is **binding**; the ROADMAP carries only the rollup.

### 8.4 Source-watcher SDK + LLM-summarizer graduation

> Phase 2.8 source-watcher migrates from `scheduler.py` cron loop to the swarm SDK. The deterministic differ + classifier stay authoritative; the LLM summarizer flips from `enabled=False` stub to a real client behind a model-pin gate.

- [x] **Summarizer graduation.** `cfg.source_watcher_summarizer_enabled` flips to `true` only when ALL of:
  - A non-`*-latest` model ID is configured at `cfg.source_watcher_summarizer_model_id` (CLAUDE.md doctrine — `*-latest` rejected at config validation).
  - The configured model is reachable from the agent's network namespace (probed at startup; failure → `enabled=False` runtime override + `sec.alert.v1{kind=summarizer_unreachable, severity=warn}`).
  - The deterministic differ has produced at least one non-empty `UpdatePlan` (the summarizer never narrates an empty diff).
- [x] **Boundary test (binding).** AST-and-runtime scan asserting `summarizer.summarize(plan)` cannot mutate `plan.classification`, `plan.severity`, or `plan.fields_changed`. Returns Turkish narration string only. Existing test extended; failure on a future attempt to widen the summarizer's authority.
- [x] **Cost cap (two-tier).** Per-call ceiling `cfg.source_watcher_summarizer_max_tokens_per_call` (default 4096 — clamps `max_tokens` on the API request itself, prevents a single bursty diff from eating the daily budget) AND per-day ledger `cfg.source_watcher_summarizer_max_tokens_per_day` (default 50 000). Either overflow → fall back to deterministic plan-derived string + `sec.alert.v1{kind=summarizer_cost_capped, severity=warn, scope=<per_call|per_day>}` (debounced daily per scope). Day boundaries are UTC midnight; counter persisted at `data/maint/summarizer_ledger.json` (mode 0600, atomic write via temp+rename) so restarts within a day do not reset the budget.
- [x] **Versioning.** `source_watcher` chart key bumps `1.x → 2.0.0` on this graduation (per ROADMAP §2.8 note). The `swarm` chart key bumps minor for the §8.x landings.
