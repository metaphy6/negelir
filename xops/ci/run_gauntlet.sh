#!/usr/bin/env bash
# run_gauntlet.sh — execute the §4 auto-merge gauntlet on the current
# checkout. Used by `.github/workflows/orchestrate-pr-review.yml` to
# decide whether an open agent PR is mergeable.
#
# Order matches `.github/instructions/ci-pipeline.instructions.md` §4:
#   1. make lint
#   2. make test.ai
#   3. make test
#   4. make version.validate
#   5. xops/ci/git_guard.py --check-commit HEAD
#   6. xops/ci/changed_files_audit.py (best-effort if present)
#
# Exit codes:
#   0   every gate green
#   1   one or more gates red (full stderr from the offending gate
#       is on this script's stderr)
#
# Each gate's stderr is preserved verbatim so the calling workflow can
# embed it in the PR review comment.

set -uo pipefail

RESULT=0
FAIL_LIST=()

run_gate() {
  local name="$1"
  shift
  echo "::group::gauntlet: $name"
  if "$@"; then
    echo "::endgroup::"
    echo "gauntlet[$name]: green" >&2
  else
    local rc=$?
    echo "::endgroup::"
    echo "gauntlet[$name]: RED (rc=$rc)" >&2
    FAIL_LIST+=("$name")
    RESULT=1
  fi
}

run_gate lint              make lint
run_gate test.ai           make test.ai
run_gate test              make test
run_gate version.validate  make version.validate
run_gate git_guard         python3 xops/ci/git_guard.py --check-commit HEAD

if [[ -x xops/ci/changed_files_audit.py ]]; then
  run_gate changed_files_audit python3 xops/ci/changed_files_audit.py
else
  echo "gauntlet[changed_files_audit]: skipped (script absent)" >&2
fi

if [[ "$RESULT" -ne 0 ]]; then
  echo "gauntlet: FAILED gates: ${FAIL_LIST[*]}" >&2
  exit 1
fi

echo "gauntlet: all green" >&2
exit 0
