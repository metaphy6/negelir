"""Source-watcher agent (Phase 2.8).

Periodically diffs the live upstream sources against the seed corpus
manifest and proposes scoped updates to the mock stack and to the
scrapers' selectors. See ``docs/planning/ROADMAP.md`` Phase 2.8 for the
full DoD.

Modules:

* ``differ.py``      — pure, deterministic structural diffing.
* ``classifier.py``  — rule-based change classification (cosmetic vs
                       semantic vs schema-breaking).
* ``planner.py``     — turns a diff into an actionable update plan.
* ``agent.py``       — orchestration loop (run from the swarm SDK in
                       Phase 3+; today: callable-from-CLI scaffold).

Today this package is **scaffolding**. The interfaces are stable; the
real differ + classifier + LLM summarizer land in Phase 2.8 proper.
"""
