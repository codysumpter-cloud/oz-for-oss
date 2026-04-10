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
