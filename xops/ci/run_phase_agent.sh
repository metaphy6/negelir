#!/usr/bin/env bash
# run_phase_agent.sh — invoke the configured LLM backend for one phase slice.
#
# Called by `.github/workflows/orchestrate-roadmap.yml` once per phase id.
# This script is intentionally a thin shim: it decides which backend to call
# based on $AGENT_BACKEND, formats the prompt from the orchestrator slice,
# and translates rate-limit / scope-violation outcomes into well-known exit
# codes that the workflow understands.
#
# Exit codes:
#   0   phase implemented + committed cleanly
#   10  rate-limit hit (workflow writes a resume cursor and exits 0)
#   20  scope violation (git_guard refused the diff)
#   30  agent escalation requested (no diff produced; human needed)
#   40  hard failure (test/lint gate red and unrecoverable in-loop)
#
# This script must remain side-effect free until it has parsed its env;
# every mutation it makes is guarded by AGENT_BACKEND being non-empty.

set -euo pipefail

: "${PHASE_ID:?PHASE_ID env var required}"
: "${MODEL:?MODEL env var required}"
: "${BRANCH:?BRANCH env var required}"
: "${AGENT_BACKEND:=copilot-issue}"

ALLOWED_MODELS=(
  auto
  claude-sonnet-4-5
  claude-opus-4-5
  gpt-5
  gpt-5-mini
  gpt-5-codex
)

model_ok=0
for m in "${ALLOWED_MODELS[@]}"; do
  if [[ "$m" == "$MODEL" ]]; then model_ok=1; break; fi
done
if [[ "$model_ok" -ne 1 ]]; then
  echo "run_phase_agent: model '$MODEL' is not in the CI allow-list" >&2
  printf '  allowed: %s\n' "${ALLOWED_MODELS[@]}" >&2
  exit 40
fi

echo "run_phase_agent: phase=$PHASE_ID model=$MODEL branch=$BRANCH backend=$AGENT_BACKEND" >&2

case "$AGENT_BACKEND" in
  copilot-issue)
    # Default backend: file (or update) a tracking issue assigned to
    # @copilot that references the phase slice. The Copilot Coding Agent
    # picks the issue up and opens its own PR; this workflow only sets
    # up the branch + scope guard, and exits 0. The auto-merge job
    # watches the PR and lands it when the gauntlet is green.
    SLICE_FILE="$(mktemp)"
    python3 -m xops.orchestrator.cli slice "$PHASE_ID" --out "$SLICE_FILE"
    TITLE="agent: Phase ${PHASE_ID} (run ${GITHUB_RUN_ID:-local})"
    BODY_FILE="$(mktemp)"
    {
      echo "Workflow run: ${GITHUB_SERVER_URL:-}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-local}"
      echo "Branch: \`$BRANCH\`"
      echo "Model: \`$MODEL\`"
      echo
      echo "## Scope"
      echo
      echo "Implement Phase **$PHASE_ID** per the slice below. Follow"
      echo "AGENTS.md Rule 11 (phase persistence) — drain every \`[ ]\`"
      echo "bullet in the named scope before handing back."
      echo
      echo "## Slice"
      echo
      echo '```markdown'
      cat "$SLICE_FILE"
      echo '```'
    } >"$BODY_FILE"
    if ! command -v gh >/dev/null 2>&1; then
      echo "run_phase_agent: gh CLI not available; cannot dispatch issue" >&2
      exit 40
    fi
    # Ensure required labels exist (no-op if already present).
    gh label create "agent-task"  --description "Dispatched to Copilot Coding Agent" --color "0075ca" --force 2>/dev/null || true
    gh label create "phase-$PHASE_ID" --description "Phase $PHASE_ID work item"       --color "e4e669" --force 2>/dev/null || true
    gh issue create \
      --title "$TITLE" \
      --body-file "$BODY_FILE" \
      --assignee "@copilot" \
      --label "agent-task,phase-$PHASE_ID" \
      >/dev/null
    rm -f "$SLICE_FILE" "$BODY_FILE"
    echo "run_phase_agent: dispatched Copilot Coding Agent for phase $PHASE_ID" >&2
    exit 0
    ;;

  noop)
    # Used by the workflow self-test — never touches anything external.
    echo "run_phase_agent: noop backend, nothing to do" >&2
    exit 0
    ;;

  *)
    echo "run_phase_agent: unknown AGENT_BACKEND='$AGENT_BACKEND'" >&2
    exit 40
    ;;
esac
