# oz-for-oss

`oz-for-oss` is a Python-first automation repository for Oz-backed GitHub workflows. Its primary output is the workflow and hub-action logic that triages issues, generates implementation plans, creates implementation diffs, enforces repository policy, and reviews pull requests.

## Primary artifacts

- `.github/workflows/` contains the GitHub Actions workflows that trigger Oz automation.
- `.github/python/` contains the Python entrypoints that those workflows execute.
- `.github/python/oz_workflows/` contains shared helpers for GitHub Actions outputs, environment loading, GitHub API access, transport comments, and Oz client integration.
- `.github/issue-triage/` contains triage labels and stakeholder routing configuration.
- `plans/` stores committed implementation plan artifacts associated with issues.

## Workflow surface

This repository currently automates:

- issue triage
- implementation-plan creation
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
python -m pip install -r .github/python/requirements.txt
```

### Run tests

```sh
env PYTHONPATH=.github/python python -m unittest discover -s .github/python/tests
```

### Run workflow entrypoints locally

The scripts under `.github/python/` are designed to run inside GitHub Actions, so they expect the same event payload and environment variables that the workflows provide. For local debugging, point `PYTHONPATH` at `.github/python`, provide the relevant GitHub Actions environment variables, and execute the entrypoint you want to inspect.

Common entrypoints include:

- `.github/python/triage_new_issues.py`
- `.github/python/create_plan_from_issue.py`
- `.github/python/create_implementation_from_issue.py`
- `.github/python/enforce_pr_issue_state.py`
- `.github/python/review_pr.py`

## Repository conventions

- Production logic in this repository lives in the Python automation and workflow definitions, not in a shipping application binary or CLI.
- Shared workflow and hub-action helpers should live in `.github/python/oz_workflows/` so they can be reused by multiple workflow entrypoints.
- Workflow dependency installation is driven by `.github/python/requirements.txt`.
