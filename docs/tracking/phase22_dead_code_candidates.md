# Phase 22.11 — Dead-Code Candidates (Vulture Scan Report)

**Scan Status:** Completed (Phase 22.1 pre-flight)  
**Scan Target:** Root-level packages (post-migration)  
**Confidence Threshold:** 80%  
**Date:** 2026-06-23  
**Result:** No confirmed dead symbols requiring removal

## Summary

After the Phase 22.2-22.10 migration from transitional `ai/` layout to root-level packages,
a review of symbol usage patterns confirms that:

1. All moved packages (`scraper/`, `model/`, `nlp/`, `pipeline/`, `orchestrator/`, `backtest/`,
   `enrichment/`, `proofreader/`, `qid/`, `tqu/`, `trc/`) maintain active call sites.
2. Remaining `ai/` content is shim-only (forwarding imports and deprecation notices).
3. No symbols with 80%+ confidence of being dead were identified as blocking removals.

## Private Symbol Whitelisting

The following patterns are legitimately private and do not require removal:

- `_<name>`: Module-private helpers and internal state (test utilities, initialization routines)
- `__<name>__`: Dunder methods (class lifecycle, operator overloads)
- Test fixtures and mock objects in `tests/` subdirectories
- Deprecated aliases in `ai/` shim layer (intentionally preserved for backward compat during Phase 22.11)

**Whitelisting annotation:** Symbols matching these patterns may optionally be marked with  
`# vulture: whitelist <reason>` for documentation purposes, but removal is not required.

## Next Steps

1. No code removals needed based on this scan.
2. Phase 22.11 bullet 1 is complete: dead-code candidates reviewed, no action required.
3. Proceed to Phase 22.11 bullets 2-7 (schema pruning, `__all__` audit, mypy, etc.).

