# Issue #191: Workflows should tolerate plan being approved after ready-to-implement label added

## Tech Spec

### Problem

When `plan-approved` is added to a spec PR after the associated issue already has `ready-to-implement`, the implementation workflow is never triggered. The implementation workflow only fires on `ready-to-implement` label events (via `create-implementation-from-issue-local.yml`). When it fires and finds unapproved spec PRs, it no-ops and never retries. Adding `plan-approved` later does not re-trigger the workflow because no GitHub Actions workflow listens to PR label events for this purpose.

The product spec requires: (1) a new GitHub Actions workflow trigger on `plan-approved` being added to a PR, (2) a Python script that resolves the associated issue and checks whether `ready-to-implement` is present, and (3) dispatching the existing implementation workflow when conditions are met.

### Relevant code

- `.github/workflows/create-implementation-from-issue-local.yml (1-39)` — existing workflow that triggers on `ready-to-implement` label and `oz-agent` assignment. This is the workflow we want to re-dispatch.
- `.github/workflows/create-implementation-from-issue.yml (1-76)` — reusable workflow that runs the implementation agent. Called by the local workflow.
- `.github/scripts/create_implementation_from_issue.py (70-84)` — the no-op guard that blocks implementation when spec PRs exist but none are labeled `plan-approved`.
- `.github/scripts/oz_workflows/helpers.py (759-791)` — `find_matching_spec_prs()` which separates spec PRs into approved and unapproved lists based on the `plan-approved` label.
- `.github/scripts/oz_workflows/helpers.py (806-849)` — `resolve_spec_context_for_issue()` which builds the spec context used by the implementation workflow.
- `.github/scripts/oz_workflows/helpers.py (916-950)` — `resolve_issue_number_for_pr()` which determines the associated issue number from a PR's branch name, changed files, and body references.
- `.github/scripts/oz_workflows/helpers.py (953-957)` — `is_spec_only_pr()` which checks whether all changed files live under `specs/`.

### Current state

The issue-to-implementation lifecycle is driven by two GitHub Actions workflows:

1. **`create-spec-from-issue-local.yml`**: Triggers on `ready-to-spec` label. Runs an agent that creates spec PRs on `oz-agent/spec-issue-{N}` branches.
2. **`create-implementation-from-issue-local.yml`**: Triggers on `ready-to-implement` label (or `oz-agent` assignment when label is present, or `@oz-agent` comment when label is present). Runs an agent that creates implementation PRs.

The implementation script (`create_implementation_from_issue.py`) calls `resolve_spec_context_for_issue()`, which calls `find_matching_spec_prs()` to find spec PRs matching the issue. If unapproved spec PRs exist but no approved ones and no local spec files, the script posts a no-op comment and returns without running the agent.

There is no mechanism to retry the implementation workflow when the spec PR's approval state changes. The `plan-approved` label is only checked passively during an already-triggered implementation run — it is never a trigger itself.

The `resolve_issue_number_for_pr()` function already exists and can determine the associated issue from a PR. It checks the branch name for patterns like `spec-issue-{N}` or `implement-issue-{N}`, spec file paths like `specs/GH{N}/product.md`, and body references. This logic can be reused in the new workflow.

### Proposed changes

#### 1. New workflow file: `.github/workflows/trigger-implementation-on-plan-approved-local.yml`

Add a new GitHub Actions workflow that triggers when `plan-approved` is labeled on a pull request:

```yaml
name: Trigger Implementation on Plan Approved (Local)
on:
  pull_request_target:
    types: [labeled]
concurrency:
  group: trigger-impl-plan-approved-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: false
jobs:
  trigger_implementation:
    if: >-
      github.event.label.name == 'plan-approved' &&
      github.event.pull_request.state == 'open'
    permissions:
      contents: read
      issues: write
      pull-requests: read
    uses: ./.github/workflows/trigger-implementation-on-plan-approved.yml
    secrets: inherit
```

The workflow uses `pull_request_target` (not `pull_request`) because `plan-approved` is added to spec PRs by reviewers, and `pull_request_target` runs in the context of the base branch, which is needed for accessing secrets. The `if` condition filters to only the `plan-approved` label being added and only for open PRs.

#### 2. New reusable workflow file: `.github/workflows/trigger-implementation-on-plan-approved.yml`

Add a reusable workflow that runs the Python script:

```yaml
name: Trigger Implementation on Plan Approved
on:
  workflow_call:
    secrets:
      OZ_MGMT_GHA_APP_ID:
        required: true
      OZ_MGMT_GHA_PRIVATE_KEY:
        required: true
      WARP_API_KEY:
        required: true
```

This workflow checks out the repo and shared workflow code, installs Python dependencies, and runs a new Python script `trigger_implementation_on_plan_approved.py`. It follows the same step structure as the existing `create-implementation-from-issue.yml` (app token creation, repo checkout, workflow code checkout, GCP auth, Python setup, dependency install, script execution).

#### 3. New Python script: `.github/scripts/trigger_implementation_on_plan_approved.py`

This script is the core logic. It:

1. Loads the `pull_request_target` event payload.
2. Checks that the labeled label is `plan-approved` and the PR is open (defense in depth beyond the YAML condition).
3. Checks that the sender is not a bot/automation user via `is_automation_user()`.
4. Resolves the associated issue number using `resolve_issue_number_for_pr()`.
5. If no associated issue is found, exits silently.
6. Fetches the associated issue and checks that it has the `ready-to-implement` label and `oz-agent` in its assignees.
7. If conditions are met, calls the same implementation logic by dispatching the `create-implementation-from-issue` workflow via the GitHub API (`workflow_dispatch` or by directly invoking the reusable workflow).

**Approach for dispatching the implementation workflow:**

Rather than duplicating the implementation logic or using `workflow_dispatch` (which requires a separate dispatch trigger on the implementation workflow), the cleanest approach is to have the new script synthesize the necessary environment and call the existing `create_implementation_from_issue.main()` directly. The event payload needed by the implementation script has an `issue` key and a `repository` key — the new script can construct this from the PR's associated issue data.

However, this approach has a coupling risk: the implementation script reads the event payload from `GITHUB_EVENT_PATH`, which is set by GitHub Actions to the `pull_request_target` event, not an `issues` event. The implementation script expects `event["issue"]`.

**Recommended approach:** The new script constructs a temporary event JSON file containing the issue data in the format expected by `create_implementation_from_issue.py`, sets `GITHUB_EVENT_PATH` to that file, and calls `create_implementation_from_issue.main()`. This reuses all existing implementation logic (spec context resolution, branch naming, PR creation, progress comments) without duplication.

Pseudocode:
```python
def main() -> None:
    owner, repo = repo_parts()
    event = load_event()
    pr = event["pull_request"]

    if pr.get("state") != "open":
        return
    if is_automation_user(event.get("sender")):
        return

    with closing(Github(auth=Auth.Token(require_env("GH_TOKEN")))) as client:
        github = client.get_repo(repo_slug())
        pr_obj = github.get_pull(int(pr["number"]))
        files = list(pr_obj.get_files())
        changed_files = [str(f.filename) for f in files]
        issue_number = resolve_issue_number_for_pr(github, owner, repo, pr_obj, changed_files)
        if not issue_number:
            return

        issue = github.get_issue(issue_number)
        labels = {label.name for label in issue.labels}
        assignees = {a.login for a in issue.assignees}

        if "ready-to-implement" not in labels:
            return
        if "oz-agent" not in assignees:
            return

        # Build a synthetic event payload for the implementation workflow
        synthetic_event = {
            "issue": {
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": [{"name": label.name} for label in issue.labels],
                "assignees": [{"login": a.login} for a in issue.assignees],
            },
            "repository": event["repository"],
            "sender": event.get("sender", {}),
        }

        # Write synthetic event to a temp file and point GITHUB_EVENT_PATH to it
        tmp_event_path = Path(tempfile.mktemp(suffix=".json"))
        tmp_event_path.write_text(json.dumps(synthetic_event), encoding="utf-8")
        os.environ["GITHUB_EVENT_PATH"] = str(tmp_event_path)

        # Run the implementation workflow
        from create_implementation_from_issue import main as run_implementation
        run_implementation()
```

This approach is clean because:
- It reuses 100% of the existing implementation logic.
- The implementation script's no-op guard (`should_noop`) will now correctly find the approved spec PR because `plan-approved` has already been added.
- Branch naming, spec context resolution, PR creation, and progress comments all work identically.

#### 4. Concurrency considerations

The new workflow uses its own concurrency group keyed on the PR number. The implementation workflow it dispatches uses a concurrency group keyed on the issue number (from `create-implementation-from-issue-local.yml`). Since the new script calls `create_implementation_from_issue.main()` inline rather than dispatching a separate workflow run, both concurrency groups apply — the outer one from the plan-approved workflow prevents concurrent plan-approved triggers on the same PR, and the implementation logic itself is protected by the issue-level group if triggered separately.

If `ready-to-implement` is added and the no-op fires, then `plan-approved` is added shortly after, the implementation will run from the plan-approved trigger. If `plan-approved` is added first and `ready-to-implement` is added shortly after, the standard trigger will run and find the approved spec context. There is no race condition that produces duplicate runs because:
- The no-op case does not create a branch or PR.
- The plan-approved trigger only fires when `ready-to-implement` is already present.
- If both happen simultaneously, GitHub's concurrency group on the issue number ensures only one implementation run proceeds.

### End-to-end flow

**Scenario: `ready-to-implement` first, `plan-approved` second**

1. Reviewer adds `ready-to-implement` to issue #N.
2. `create-implementation-from-issue-local.yml` fires.
3. `create_implementation_from_issue.py` calls `resolve_spec_context_for_issue()`.
4. `find_matching_spec_prs()` returns unapproved spec PRs (no `plan-approved` label).
5. `should_noop` is true → posts no-op comment → returns.
6. Reviewer adds `plan-approved` to the spec PR.
7. `trigger-implementation-on-plan-approved-local.yml` fires.
8. `trigger_implementation_on_plan_approved.py` runs:
   a. Resolves associated issue #N from the PR.
   b. Checks issue has `ready-to-implement` and `oz-agent` assigned → both true.
   c. Constructs synthetic event and calls `create_implementation_from_issue.main()`.
9. `create_implementation_from_issue.py` calls `resolve_spec_context_for_issue()`.
10. `find_matching_spec_prs()` now returns the spec PR in the approved list.
11. Implementation proceeds normally.

**Scenario: `plan-approved` first, `ready-to-implement` second (no change)**

1. Reviewer adds `plan-approved` to the spec PR.
2. `trigger-implementation-on-plan-approved-local.yml` fires.
3. Script resolves issue #N but it lacks `ready-to-implement` → exits silently.
4. Reviewer adds `ready-to-implement` to issue #N.
5. Standard trigger fires and succeeds (spec is already approved).

### Risks and mitigations

**Risk: Duplicate implementation runs if both labels are added near-simultaneously.**
Mitigation: The implementation workflow's concurrency group (`create-implementation-issue-{N}`) serializes runs per issue. If the no-op run completes before the plan-approved trigger runs, the plan-approved trigger will proceed. If they overlap, the concurrency group queues them. The no-op case does not produce a branch, so the subsequent run starts fresh.

**Risk: Synthetic event payload missing fields expected by the implementation script.**
Mitigation: The synthetic event includes the exact fields read by `create_implementation_from_issue.py`: `event["issue"]` (number, title, body, labels, assignees), `event["repository"]` (default_branch), and `event.get("comment")` (absent, which is handled). The `event.get("sender")` is passed through from the PR event for co-author resolution.

**Risk: The `resolve_issue_number_for_pr` function fails to find the issue.**
Mitigation: The function already handles multiple resolution strategies (branch name, spec file paths, body references). For spec PRs created by the existing workflow, the branch name `oz-agent/spec-issue-{N}` reliably matches. If resolution fails, the script exits silently — this is acceptable since the user can manually re-trigger.

**Risk: `pull_request_target` event type exposes secrets to untrusted code.**
Mitigation: The workflow checks out the base branch code, not the PR branch. The Python script only reads the PR metadata (number, files, labels) and the issue metadata — it does not check out or execute PR branch code. This follows the same security pattern used by `pr-hooks.yml`.

### Testing and validation

**Unit tests for the new script:**
- Test that the script exits silently when the associated issue does not have `ready-to-implement`.
- Test that the script exits silently when `oz-agent` is not assigned to the issue.
- Test that the script exits silently when `resolve_issue_number_for_pr` returns `None`.
- Test that the script exits silently when the sender is a bot.
- Test that the script calls `create_implementation_from_issue.main()` with a correctly constructed synthetic event when all conditions are met.

**Integration-level validation:**
- Verify that adding `plan-approved` to a spec PR whose issue has `ready-to-implement` and `oz-agent` triggers the implementation workflow.
- Verify that the implementation run uses the approved spec context.
- Verify that the standard `ready-to-implement` trigger still works correctly (regression).

**Workflow YAML validation:**
- Confirm the `pull_request_target` trigger with `labeled` type and the `plan-approved` filter is correct.
- Confirm the concurrency group prevents duplicate runs on the same PR.

### Follow-ups

- Consider cleaning up the no-op progress comment when the retrigger succeeds. The initial "I did not start implementation because…" comment may be confusing once the implementation PR exists.
- Consider whether the `plan-approved` trigger should also handle the case where `oz-agent` is not yet assigned (auto-assign and trigger), though the product spec currently scopes this to only checking existing assignments.
- If the `trigger-implementation-on-plan-approved` pattern proves useful, the same approach could handle other out-of-order label scenarios in the future.
