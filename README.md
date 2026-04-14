# oz-for-oss

`oz-for-oss` is a Python-first automation repository for Oz-backed GitHub workflows. Its primary output is the workflow and hub-action logic that triages issues, generates implementation plans, creates implementation diffs, enforces repository policy, and reviews pull requests.

## Primary artifacts

- `.github/workflows/` contains the GitHub Actions workflows that trigger Oz automation.
- `.github/scripts/` contains the Python entrypoints that those workflows execute.
- `.github/scripts/oz_workflows/` contains shared helpers for GitHub Actions outputs, environment loading, GitHub API access, artifact retrieval, and Oz client integration.
- `.github/issue-triage/` contains triage label definitions used during issue triage.
- `.github/STAKEHOLDERS` maps repository path patterns to subject-matter expert GitHub usernames, using CODEOWNERS-style syntax.
- `specs/` stores committed product and technical spec artifacts associated with issues, organized as `specs/GH{number}/product.md` and `specs/GH{number}/tech.md`.

## Workflow surface

This repository currently automates:

- issue triage
- product and tech spec creation
- issue implementation scaffolding
- PR issue-state enforcement
- PR review orchestration
- unready-assignment guidance for Oz

## Setting up a target repository

To use the `oz-for-oss` reusable workflows in another repository, you need a GitHub App installation, a set of GitHub Actions secrets and variables, and local adapter workflows that call the reusable layer.

### 1. Create and install a GitHub App

The workflows authenticate through a GitHub App rather than a personal access token. Create an app under your organization (or personal account) with these permissions:

**Repository permissions**

- **Contents** — Read & Write (checkout code, push branches)
- **Issues** — Read & Write (apply labels, post comments, manage assignees)
- **Pull requests** — Read & Write (open PRs, post reviews)

**Organization permissions**

- None required.

After creating the app, install it on every repository that will use the workflows. Note the **App ID** and generate a **private key** — both are needed in the next step.

### 2. Configure GitHub Actions secrets and variables

Add the following **secrets** to each target repository (or at the organization level):

| Secret | Description |
|---|---|
| `OZ_MGMT_GHA_APP_ID` | The numeric App ID of the GitHub App created above. |
| `OZ_MGMT_GHA_PRIVATE_KEY` | The PEM-encoded private key for that App. |
| `WARP_API_KEY` | Your Warp API key, used to invoke Oz agents. |

Optionally, set the following **repository variables** (not secrets) to customize agent behavior:

| Variable | Description |
|---|---|
| `WARP_AGENT_MODEL` | Override the default Oz model (e.g. a specific model identifier). |
| `WARP_AGENT_MCP` | MCP configuration for the agent, if any. |
| `WARP_ENVIRONMENT_ID` | Cloud environment UID for Oz agent runs. |

### 3. Add local adapter workflows

The reusable workflows in this repository are invoked via `workflow_call`. Your target repository needs thin local adapter workflows that map GitHub events to the reusable workflows.

Below is a minimal set of adapters. Copy these into `.github/workflows/` in your target repository and adjust the `uses:` ref as needed.

#### Issue triage

```yaml
# .github/workflows/triage-new-issues.yml
name: Triage New Issues
on:
  issues:
    types: [opened]
  issue_comment:
    types: [created]
  workflow_dispatch:
    inputs:
      issue_number:
        description: Issue number to triage
        required: false
        default: ''
        type: string
concurrency:
  group: triage-${{ github.event.issue.number || inputs.issue_number || github.run_id }}
  cancel-in-progress: false
jobs:
  triage:
    uses: warpdotdev/oz-for-oss/.github/workflows/triage-new-issues.yml@main
    with:
      issue_number: ${{ inputs.issue_number || '' }}
    secrets: inherit
```

#### Spec creation

```yaml
# .github/workflows/create-spec-from-issue.yml
name: Create Spec from Issue
on:
  issues:
    types: [assigned, labeled]
  issue_comment:
    types: [created]
concurrency:
  group: create-spec-${{ github.event.issue.number || github.run_id }}
  cancel-in-progress: false
jobs:
  create_spec:
    if: >-
      (
        github.event_name == 'issues' &&
        github.event.action == 'assigned' &&
        github.event.assignee.login == 'oz-agent' &&
        contains(github.event.issue.labels.*.name, 'ready-to-spec')
      ) || (
        github.event_name == 'issues' &&
        github.event.action == 'labeled' &&
        github.event.label.name == 'ready-to-spec' &&
        contains(github.event.issue.assignees.*.login, 'oz-agent')
      ) || (
        github.event_name == 'issue_comment' &&
        !github.event.issue.pull_request &&
        contains(github.event.issue.labels.*.name, 'ready-to-spec') &&
        contains(github.event.comment.body, '@oz-agent') &&
        contains(fromJSON('["COLLABORATOR","MEMBER","OWNER"]'), github.event.comment.author_association)
      )
    uses: warpdotdev/oz-for-oss/.github/workflows/create-spec-from-issue.yml@main
    secrets: inherit
```

#### Implementation

```yaml
# .github/workflows/create-implementation-from-issue.yml
name: Create Implementation from Issue
on:
  issues:
    types: [assigned, labeled]
  issue_comment:
    types: [created]
concurrency:
  group: create-impl-${{ github.event.issue.number || github.run_id }}
  cancel-in-progress: false
jobs:
  create_implementation:
    if: >-
      (
        github.event_name == 'issues' &&
        github.event.action == 'assigned' &&
        github.event.assignee.login == 'oz-agent' &&
        contains(github.event.issue.labels.*.name, 'ready-to-implement')
      ) || (
        github.event_name == 'issues' &&
        github.event.action == 'labeled' &&
        github.event.label.name == 'ready-to-implement' &&
        contains(github.event.issue.assignees.*.login, 'oz-agent')
      ) || (
        github.event_name == 'issue_comment' &&
        !github.event.issue.pull_request &&
        contains(github.event.issue.labels.*.name, 'ready-to-implement') &&
        contains(github.event.comment.body, '@oz-agent') &&
        contains(fromJSON('["COLLABORATOR","MEMBER","OWNER"]'), github.event.comment.author_association)
      )
    uses: warpdotdev/oz-for-oss/.github/workflows/create-implementation-from-issue.yml@main
    secrets: inherit
```

#### PR review and enforcement

If you want automated PR reviews and issue-state enforcement, add a `pr-hooks.yml` adapter. See [`.github/workflows/pr-hooks.yml`](.github/workflows/pr-hooks.yml) in this repository for the full example, which orchestrates `enforce-pr-issue-state.yml`, `run-tests.yml`, and `review-pull-request.yml` together.

For a simpler standalone review setup:

```yaml
# .github/workflows/review-pull-request.yml
name: Review Pull Request
on:
  pull_request_target:
    types: [opened, ready_for_review]
jobs:
  review:
    if: >-
      !github.event.pull_request.draft &&
      !startsWith(github.event.pull_request.head.ref, 'cherrypick')
    uses: warpdotdev/oz-for-oss/.github/workflows/review-pull-request.yml@main
    with:
      pr_number: ${{ github.event.pull_request.number }}
      trigger_source: pull_request_target
      requester: ${{ github.actor }}
    secrets: inherit
```

#### Unready-assignment guard

```yaml
# .github/workflows/comment-on-unready-assigned-issue.yml
name: Comment on Unready Assigned Issue
on:
  issues:
    types: [assigned]
jobs:
  guard:
    if: >-
      github.event.assignee.login == 'oz-agent' &&
      !contains(github.event.issue.labels.*.name, 'ready-to-spec') &&
      !contains(github.event.issue.labels.*.name, 'ready-to-implement')
    uses: warpdotdev/oz-for-oss/.github/workflows/comment-on-unready-assigned-issue.yml@main
    secrets: inherit
```

Each adapter is deliberately thin — it defines the GitHub event triggers and conditions, then delegates to the reusable workflow. Refer to the local adapter workflows in this repository (the `*-local.yml` files) for the full set of trigger conditions used here.

### 4. Bootstrap triage configuration (optional)

If you want the triage agent to apply area and status labels, run the `bootstrap-issue-config` skill on your target repository. This generates `.github/issue-triage/config.json` and `.github/STAKEHOLDERS`. See the [Bootstrapping triage configuration](#bootstrapping-triage-configuration) section for details.

## Local development

### Setup

```sh
python3 -m venv .venv
source .venv/bin/activate.fish
python -m pip install --upgrade pip
python -m pip install -r .github/scripts/requirements.txt
```

### Run tests

```sh
env PYTHONPATH=.github/scripts python -m unittest discover -s .github/scripts/tests
```

### Run workflow entrypoints locally

The scripts under `.github/scripts/` are designed to run inside GitHub Actions, so they expect the same event payload and environment variables that the workflows provide. For local debugging, point `PYTHONPATH` at `.github/scripts/`, provide the relevant GitHub Actions environment variables, and execute the entrypoint you want to inspect.

Common entrypoints include:

- `.github/scripts/triage_new_issues.py`
- `.github/scripts/create_spec_from_issue.py`
- `.github/scripts/create_implementation_from_issue.py`
- `.github/scripts/enforce_pr_issue_state.py`
- `.github/scripts/review_pr.py`

## Bootstrapping triage configuration

To set up or update the issue triage configuration for a repository, use the `bootstrap-issue-config` skill. This skill:

1. Fetches existing labels from the repository and classifies them into area, feature, and status categories.
2. Analyzes recent issues and issue templates to discover additional labels.
3. Generates or updates `.github/issue-triage/config.json` with label definitions (colors and descriptions).
4. Generates or updates `.github/STAKEHOLDERS` by inspecting CODEOWNERS, recent git contributors, and existing stakeholder information.
5. Creates any missing labels on the repository via the GitHub API.

The skill is idempotent — re-running it merges new discoveries with existing configuration rather than overwriting it.

The `config.json` file contains **only** label definitions. Stakeholder ownership is managed separately in the `.github/STAKEHOLDERS` file, which uses the same glob-based syntax as GitHub CODEOWNERS files.

## Repository conventions

- Production logic in this repository lives in the Python automation and workflow definitions, not in a shipping application binary or CLI.
- Shared workflow and hub-action helpers should live in `.github/scripts/oz_workflows/` so they can be reused by multiple workflow entrypoints.
- Workflow dependency installation is driven by `.github/scripts/requirements.txt`.
