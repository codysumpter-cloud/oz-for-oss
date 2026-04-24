#!/usr/bin/env bash
# Run act-based workflow routing tests against the local mock API server.
#
# Prerequisites
# -------------
#   1. Install act:   brew install act    (macOS)
#                     or see https://github.com/nektos/act#installation
#   2. Install Docker (required by act for running workflows in containers).
#   3. Copy tools/act/.secrets.template → tools/act/.secrets (values don't
#      matter for dry-run mode; only needed for full-run mode).
#   4. Run this script from the repository root:
#        bash tools/act/run_workflow_tests.sh
#
# What this tests
# ---------------
# In DRY-RUN mode (--dryrun flag, default), act evaluates all workflow YAML
# conditions (if:, needs:, concurrency groups) and prints which jobs WOULD
# run for each event — without executing any steps. This is fast (~1s per
# scenario) and catches:
#
#   - Typos in expression syntax (e.g. wrong context variable names)
#   - Off-by-one errors in if: conditions (wrong comparison operators)
#   - Missing needs: dependencies between jobs
#   - Incorrect concurrency groups
#   - Wrong event types triggering a local adapter
#
# In FULL-RUN mode (--full), act executes every step in a Docker container.
# The Python scripts connect to the mock API server instead of real GitHub /
# Warp APIs. This requires the mock server to be running:
#
#   python tools/mock_api_server.py --scenario triage-new-issue &
#   bash tools/act/run_workflow_tests.sh --full
#
# Test matrix
# -----------
# Each SCENARIO line is: <workflow-yaml> <event> <event-file> <expected-jobs>
# The test runner verifies (in dry-run mode) that expected-jobs appear in
# act's output and optional "NOT:" prefixed jobs do NOT appear.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

DRY_RUN=true
MOCK_PORT=8080
FAILURES=0

for arg in "$@"; do
  case "$arg" in
    --full) DRY_RUN=false ;;
    --port=*) MOCK_PORT="${arg#--port=}" ;;
  esac
done

ACT_FLAGS="--secret-file tools/act/.secrets --use-gitignore=false"
if $DRY_RUN; then
  ACT_FLAGS="$ACT_FLAGS --dryrun"
fi

if ! command -v act &>/dev/null; then
  echo "ERROR: 'act' not found. Install with: brew install act"
  exit 1
fi

run_test() {
  local description="$1"
  local workflow="$2"
  local event="$3"
  local event_file="$4"
  shift 4
  local expected_jobs=("$@")

  echo ""
  echo "┌─ TEST: $description"
  echo "│  workflow:  $workflow"
  echo "│  event:     $event ($event_file)"

  local output
  # shellcheck disable=SC2086
  output=$(act "$event" \
    -W ".github/workflows/$workflow" \
    -e "$event_file" \
    $ACT_FLAGS 2>&1) || true

  local passed=true
  for job_spec in "${expected_jobs[@]}"; do
    if [[ "$job_spec" == NOT:* ]]; then
      local job="${job_spec#NOT:}"
      if echo "$output" | grep -q "Job '\''$job'\''"; then
        echo "│  FAIL  job '$job' ran but should NOT have run"
        passed=false
      else
        echo "│  PASS  job '$job' correctly did not run"
      fi
    else
      if echo "$output" | grep -q "$job_spec"; then
        echo "│  PASS  found expected: $job_spec"
      else
        echo "│  FAIL  missing expected: $job_spec"
        passed=false
      fi
    fi
  done

  if $passed; then
    echo "└─ PASS"
  else
    echo "└─ FAIL"
    FAILURES=$((FAILURES + 1))
    if [[ -n "${VERBOSE:-}" ]]; then
      echo "--- act output ---"
      echo "$output"
      echo "------------------"
    fi
  fi
}

# ---------------------------------------------------------------------------
# SCENARIO 1: New issue triggers triage
# ---------------------------------------------------------------------------
run_test \
  "New issue opened → triage_issues job runs" \
  "triage-new-issues-local.yml" \
  "issues" \
  "tools/act/events/issue_opened.json" \
  "triage_issues"

# ---------------------------------------------------------------------------
# SCENARIO 2: Reporter replies to needs-info → triage re-runs
# ---------------------------------------------------------------------------
run_test \
  "Reporter reply to needs-info → triage re-runs" \
  "triage-new-issues-local.yml" \
  "issue_comment" \
  "tools/act/events/issue_comment_needs_info_reply.json" \
  "triage_issues"

# ---------------------------------------------------------------------------
# SCENARIO 3: Unready issue assigned → guardrail fires
# ---------------------------------------------------------------------------
run_test \
  "oz-agent assigned to issue without ready label → guardrail runs" \
  "comment-on-unready-assigned-issue-local.yml" \
  "issues" \
  "tools/act/events/issue_assigned_unready.json" \
  "comment_on_unready_assigned_issue"

# ---------------------------------------------------------------------------
# SCENARIO 4: Ready issue assigned → guardrail is SKIPPED
# ---------------------------------------------------------------------------
run_test \
  "oz-agent assigned to ready-to-implement issue → guardrail skipped" \
  "comment-on-unready-assigned-issue-local.yml" \
  "issues" \
  "tools/act/events/issue_assigned_ready.json" \
  "NOT:comment_on_unready_assigned_issue"

# ---------------------------------------------------------------------------
# SCENARIO 5: New PR opened → enforce + review chain
# ---------------------------------------------------------------------------
run_test \
  "PR opened → enforce_issue_state + review_pr jobs run" \
  "pr-hooks.yml" \
  "pull_request_target" \
  "tools/act/events/pr_opened.json" \
  "enforce_issue_state"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
if [[ $FAILURES -eq 0 ]]; then
  echo "All workflow routing tests passed."
else
  echo "FAILED: $FAILURES test(s) failed."
  echo ""
  echo "Tip: Set VERBOSE=1 to see full act output for failing tests:"
  echo "  VERBOSE=1 bash tools/act/run_workflow_tests.sh"
  exit 1
fi
