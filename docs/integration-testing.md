# Integration Testing Guide

This document explains how to test the GitHub Actions workflows in this
repository without relying on a live GitHub repository or a real Warp API key.
It covers the full testing pyramid: from Python integration tests that run in
existing CI up to `act`-based workflow routing tests that exercise the YAML
`if:` conditions.

## The Testing Gap

The unit tests in `.github/scripts/tests/` cover individual Python functions in
isolation. They mock every external dependency (PyGitHub, oz_agent_sdk) at the
function level and assert on data transformations.

What the unit tests do **not** cover is the _outer loop_: the GitHub Actions
YAML workflows themselves. The YAML layer is responsible for:

- Routing GitHub events to the right job (e.g. "only run triage for non-bot
  comments on issues without the `triaged` label")
- Passing inputs and secrets correctly between jobs and reusable workflows
- Enforcing `needs:` dependencies (e.g. review only runs after enforcement
  passes)
- Calling the Python scripts with the right `PYTHONPATH` and environment
  variables

The gap this guide fills is between "unit test of a single function" and "manual
test on a live repo".

---

## Testing pyramid

```
          ┌────────────────────────────────────────┐
          │  End-to-end (live repo, real Warp API) │  <-- most expensive
          │  Manual or nightly scheduled           │
          ├────────────────────────────────────────┤
          │  act + mock_api_server.py              │  <-- YAML routing +
          │  Full-run mode                         │      script wiring
          ├────────────────────────────────────────┤
          │  act --dryrun                          │  <-- YAML if: conditions
          │  (no Docker needed for basic routing)  │      fast, no secrets
          ├────────────────────────────────────────┤
          │  Python integration tests              │  <-- full script execution
          │  .github/scripts/tests/integration/   │      mocked APIs, in CI
          ├────────────────────────────────────────┤
          │  Python unit tests                     │  <-- already in CI
          │  .github/scripts/tests/               │
          └────────────────────────────────────────┘
```

---

## Layer 1: Python Integration Tests (CI-compatible)

These tests live in `.github/scripts/tests/integration/` and run as part of the
existing `python -m unittest discover -s .github/scripts/tests` command in CI.

### What they test

- Full `main()` execution path of each workflow entrypoint script
- Correct parsing of GitHub event JSON from `GITHUB_EVENT_PATH`
- Correct reading of workspace config files (`.github/issue-triage/config.json`,
  `.github/STAKEHOLDERS`)
- GitHub API mutations: which labels were added/removed, what comments were
  posted, whether assignees were removed
- Behaviour driven by the agent result (triage labels, follow-up questions,
  duplicate detection, session link)

### What they mock

| External dependency | How it's mocked |
|---|---|
| PyGitHub `Github()` constructor | Patched to return `FakeGitHubClient` |
| `run_agent()` | Patched to return `FakeRunItem` |
| `poll_for_artifact()` | Patched to return a canned result dict |

The fake objects (`FakeGitHubClient`, `FakeRepo`, `FakeIssue`, `FakeComment`)
live in `support.py` and replicate only the PyGitHub surface the scripts
actually use — so any new `.get_*()` or `.create_*()` call added to a script
will cause the test to fail loudly rather than silently passing.

### Running integration tests locally

```bash
# From the repository root
PYTHONPATH=.github/scripts python -m unittest discover \
    -s .github/scripts/tests/integration \
    -p "test_*.py" \
    -v
```

### Adding a new integration test

1. Add a test class to an existing file (e.g. `test_triage_flow.py`) or create
   a new `test_<workflow>_flow.py` file.
2. Use `WorkspaceSetup` to create the temp workspace with config files and event
   JSON.
3. Create `FakeIssue` / `FakeRepo` objects with the required state.
4. Patch the module-level `Github`, `run_agent`, and `poll_for_artifact` names.
5. Run `main()` and assert on `issue.added_labels`, `issue._comments`, etc.

#### Minimal example

```python
from tests.integration.support import (
    FakeGitHubClient, FakeIssue, FakeRepo, FakeRunItem,
    WorkspaceSetup, issue_opened_event, triage_result_bug,
)

class MyNewTest(unittest.TestCase):
    def test_something(self):
        issue = FakeIssue(99, title="My test issue")
        repo  = FakeRepo(issues=[issue])
        client = FakeGitHubClient(repo)

        with WorkspaceSetup(event=issue_opened_event(number=99)) as ws:
            with (
                patch("triage_new_issues.Github", return_value=client),
                patch("triage_new_issues.run_agent", return_value=FakeRunItem()),
                patch("triage_new_issues.poll_for_artifact", return_value=triage_result_bug()),
                patch.dict(os.environ, ws.env({"TRIAGE_ISSUE_NUMBER": "99"}), clear=True),
            ):
                from triage_new_issues import main
                main()

        self.assertIn("bug", issue.added_labels)
```

### The boundary between Python tests and YAML tests

Some workflow behaviour is implemented in YAML `if:` conditions, not in Python.
For example, `comment-on-unready-assigned-issue-local.yml` only dispatches to
the Python script when the issue lacks `ready-to-spec` or
`ready-to-implement`. The Python script itself always posts the comment and
removes the assignee.

The integration test `test_label_filtering_is_a_yaml_concern` documents this
boundary explicitly: it shows that calling `main()` directly bypasses the YAML
guard.  Testing that the YAML guard works correctly is the job of the `act`
layer below.

---

## Layer 2: act --dryrun (YAML routing, no Docker required)

[nektos/act](https://github.com/nektos/act) runs GitHub Actions workflows
locally. In `--dryrun` mode it evaluates all YAML expressions and prints which
jobs _would_ run for a given event payload — without executing any steps.

This is the fastest way to catch mistakes in `if:` conditions and `needs:`
dependencies.

### Installation

```bash
# macOS
brew install act

# Linux (see https://github.com/nektos/act#installation)
curl -s https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash
```

Docker must be running. For dry-run mode, Docker is used only for evaluating
expressions, not for running steps.

### Running routing tests

The test script `tools/act/run_workflow_tests.sh` exercises every routing
scenario in dry-run mode:

```bash
# From the repository root
bash tools/act/run_workflow_tests.sh
```

Individual scenarios can also be run directly:

```bash
# Does a new issue trigger the triage job?
act issues \
    -W .github/workflows/triage-new-issues-local.yml \
    -e tools/act/events/issue_opened.json \
    --dryrun

# Is the guardrail skipped for a ready-to-implement issue?
act issues \
    -W .github/workflows/comment-on-unready-assigned-issue-local.yml \
    -e tools/act/events/issue_assigned_ready.json \
    --dryrun
```

### Interpreting dry-run output

When act prints `  ✓ Job 'triage_issues'` in the output, that job would have
run. When a job is absent, its `if:` condition evaluated to false. The test
script in `tools/act/run_workflow_tests.sh` checks for these markers
automatically.

### Supported event fixtures

| File | Event | Scenario |
|---|---|---|
| `tools/act/events/issue_opened.json` | `issues` | New issue opened |
| `tools/act/events/issue_comment_needs_info_reply.json` | `issue_comment` | Reporter replies to needs-info |
| `tools/act/events/issue_assigned_unready.json` | `issues` | oz-agent assigned, no ready label |
| `tools/act/events/issue_assigned_ready.json` | `issues` | oz-agent assigned, ready-to-implement |
| `tools/act/events/pr_opened.json` | `pull_request_target` | New PR opened |

Add new fixtures by copying an existing one and adjusting the payload. The
files follow the [GitHub webhook payload schema](https://docs.github.com/en/webhooks/webhook-events-and-payloads).

---

## Layer 3: act + mock_api_server.py (full workflow execution)

In full-run mode, act executes each step inside a Docker container. The
Python scripts run and make real HTTP calls — but those calls go to
`tools/mock_api_server.py` instead of `api.github.com` and `app.warp.dev`.

### Architecture

```
act (Docker container)
  → Python script
    → PyGitHub → http://localhost:8080/            (mock_api_server.py)
    → oz_agent_sdk → http://localhost:8080/warp-api (mock_api_server.py)
    → artifact download → http://localhost:8080/artifact-downloads/...
```

The mock server returns pre-configured responses for each test scenario and
logs every received request to `/tmp/mock_requests.jsonl`.

### Setup

```bash
# 1. Copy the secrets template
cp tools/act/.secrets.template tools/act/.secrets
# (Edit .secrets if you want real values, but fake values work for mock mode)

# 2. Start the mock server for the desired scenario
python tools/mock_api_server.py --scenario triage-new-issue &
MOCK_PID=$!

# 3. Run the workflows against the mock server
#    Point GITHUB_API_URL and WARP_API_BASE_URL at the mock
act issues \
    -W .github/workflows/triage-new-issues-local.yml \
    -e tools/act/events/issue_opened.json \
    --env GITHUB_API_URL=http://host.docker.internal:8080 \
    --env WARP_API_BASE_URL=http://host.docker.internal:8080/warp-api \
    --env WARP_ENVIRONMENT_ID=test-env \
    --no-skip-checkout

# 4. Check what API calls the script made
cat /tmp/mock_requests.jsonl | python -m json.tool

# 5. Stop the mock server
kill $MOCK_PID
```

> **Note on host networking**: On macOS and Linux, Docker containers can reach
> the host via `host.docker.internal`. On Linux this requires
> `--add-host host.docker.internal:host-gateway` in Docker. Act passes this
> automatically when the `--network host` flag is used, but check your Docker
> version.

### Available scenarios

| Scenario | Description |
|---|---|
| `triage-new-issue` | Issue opened → agent triages → labels applied |
| `needs-info-reply` | Reporter replies → re-triage succeeds |
| `unready-assigned` | oz-agent assigned → guardrail fires |

List all scenarios:

```bash
python tools/mock_api_server.py --list-scenarios
```

Add new scenarios by extending the `SCENARIOS` dict in `tools/mock_api_server.py`.

### Asserting on API calls

After a full run, inspect the request log to verify the scripts made the
expected calls:

```bash
# What labels were added?
jq 'select(.method == "POST" and (.path | test("labels")))' /tmp/mock_requests.jsonl

# What comments were posted?
jq 'select(.method == "POST" and (.path | test("comments")))' /tmp/mock_requests.jsonl

# Did the script call the Warp API?
jq 'select(.path | startswith("/warp-api"))' /tmp/mock_requests.jsonl
```

### Overriding PyGitHub's default API URL

PyGitHub uses `https://api.github.com` by default. To redirect it to the
mock server, pass `GITHUB_API_URL` to the workflow environment. The workflow
scripts already read `GH_TOKEN` from the environment and pass it to
`Github(auth=Auth.Token(token))`. To also override the API base URL, add:

```python
# In your workflow script (if not already present):
from github import Github, Auth
import os

api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
github = Github(base_url=api_url, auth=Auth.Token(token))
```

Alternatively, patch this in the workflow YAML with an environment variable
that the script reads before constructing the client.

---

## Layer 4: End-to-end tests (live repo)

For complete confidence, create a dedicated test repository (e.g.
`warpdotdev/oz-oss-testbed`) with the local adapter workflows installed. Use
GitHub Actions to:

1. Open a test issue with a known title/body.
2. Wait for the triage workflow to run (poll the GitHub API or use a webhook).
3. Assert the issue received the expected labels and a triage comment.

This is slow and costs real Warp API credits, so it is suitable for scheduled
nightly runs or manual verification before a release, not for every PR.

---

## Quick reference

| Goal | Command |
|---|---|
| Run Python integration tests | `PYTHONPATH=.github/scripts python -m unittest discover -s .github/scripts/tests/integration -v` |
| Run all tests (unit + integration) | `PYTHONPATH=.github/scripts python -m unittest discover -s .github/scripts/tests` |
| Run YAML routing tests (dry-run) | `bash tools/act/run_workflow_tests.sh` |
| Run YAML routing tests (verbose) | `VERBOSE=1 bash tools/act/run_workflow_tests.sh` |
| Start mock API server | `python tools/mock_api_server.py --scenario triage-new-issue` |
| List mock scenarios | `python tools/mock_api_server.py --list-scenarios` |
| Run full workflow with mock | See "Layer 3" section above |
| Check mock request log | `cat /tmp/mock_requests.jsonl \| python -m json.tool` |
