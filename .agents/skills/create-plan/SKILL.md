---
name: create-plan
description: Create a planning pull request from a GitHub issue in this repository. Use when an issue should be turned into an implementation plan, the plan should be stored under the repo's `plans/` directory, and the agent should open a draft PR with the plan instead of implementing code changes.
---

# Create a plan PR from a GitHub issue

Turn the assigned GitHub issue into a plan-only pull request for this repository.

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
6. Create a branch named `oz-agent/plan-issue-<issue-number>` from the checked out base branch.
7. Commit the plan with a message like `Add plan for issue #<issue-number>` and include `Co-Authored-By: Oz <oz-agent@warp.dev>` on its own line at the end of the commit message.
8. Push the branch and open a draft pull request against the repository's default branch. Use a title like `Plan issue #<issue-number>: <issue title>`.
9. In the PR body, summarize the plan briefly, link the issue with `Refs #<issue-number>`, and include `Co-Authored-By: Oz <oz-agent@warp.dev>` on its own line at the end.

## Output expectations

- Leave the repository with a draft PR that contains the new or updated plan file.
- If the issue is underspecified, still produce the best possible plan and clearly capture assumptions or open questions in the plan and PR body.
