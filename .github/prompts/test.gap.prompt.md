---
description: Find untested code paths in the named module.
mode: ask
---

For the file, folder, or current selection I name, find **untested
code paths** in the matching `ai/tests/` (or `server/...` test)
files.

Method:

1. Identify each public function / method / handler in the target.
2. Cross-reference it against the test files using
   `grep_search` for the symbol name and
   `vscode_listCodeUsages` for callers.
3. Report each public surface with one of:
   - **Tested** — cite the test file:line that exercises it
   - **Untested** — no test references it
   - **Partially tested** — name the branches not covered
4. Flag any test that calls a real upstream (must use `mocksrv`
   or fixtures per [`AGENTS.md`](../../AGENTS.md) §5 mock-data
   discipline).
5. Flag any production code path that silently falls back to
   synthetic data (Rule 3 violation).

End with a prioritized list of the 5 highest-value tests to add,
each with a one-line rationale. Do **not** write the tests in
this turn — leave that for the default agent mode.
