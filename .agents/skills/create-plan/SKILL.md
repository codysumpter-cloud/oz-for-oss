---
name: create-plan
description: Create an implementation plan from a GitHub issue in this repository. Use when an issue should be turned into a plan artifact stored under the repo's `plans/` directory and the agent should prepare file changes only, without creating commits or pull requests itself.
---

# Create a plan diff from a GitHub issue

Turn the assigned GitHub issue into a plan-only repository diff for this repository.

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

## Workflow

1. Read the issue details carefully. If `issue_comments.txt` exists, review it for clarifications and prior decisions.
2. Inspect the repository to understand the current implementation and the likely scope of the requested work before writing the plan.
3. Create or update a single plan file at `plans/issue-<issue-number>.md`. Plans for this repository live under `plans/`.
4. Keep the plan concise and actionable. Include:
   - the problem or goal
   - the most relevant current-state observations from the codebase
   - the proposed changes
   - notable risks, dependencies, or open questions
5. Do not implement the feature or modify production code as part of this task. Limit changes to the plan artifact and any minimal repository metadata needed to support it. Treat temporary context files such as `issue_comments.txt` as scratch input only and do not commit them.
6. Default behavior: do not stage files, create commits, push branches, open pull requests, or use the GitHub CLI. If the prompt explicitly says you are running in a cloud-environment workflow where the caller cannot read your local diff and instructs you to publish a named branch, you may commit and push exactly the requested plan changes to that branch, but still do not open or update the pull request yourself unless the prompt explicitly asks for it.
7. In your final response, provide a brief summary of the plan and call out any assumptions or open questions so the workflow can reuse that summary when creating the PR.

## Output expectations

- Leave the repository with the new or updated plan file ready to be committed by the workflow.
- If the issue is underspecified, still produce the best possible plan and clearly capture assumptions or open questions in the plan file and final response.
