---
name: create-plan
description: Create an implementation plan from a GitHub issue in this repository. Use when an issue should be turned into a plan artifact stored under the repo's `plans/` directory and the agent should publish the resulting plan branch and pull request directly, while only committing the plan file.
---

# Create and publish a plan from a GitHub issue

Turn the assigned GitHub issue into a plan-only repository change for this repository and publish it directly.

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

## Workflow

1. Read the issue details carefully. If temporary context files such as `issue_comments.txt` exist, review them for clarifications and prior decisions, but treat them as scratch input only.
2. Inspect the repository to understand the current implementation and the likely scope of the requested work before writing the plan.
3. Create or update a single plan file at `plans/issue-<issue-number>.md`. Plans for this repository live under `plans/`.
4. Keep the plan concise and actionable. Include:
   - the problem or goal
   - the most relevant current-state observations from the codebase
   - the proposed changes
   - notable risks, dependencies, or open questions
5. Do not implement the feature or modify production code as part of this task.
6. Before publishing, make sure the only tracked file with staged changes is `plans/issue-<issue-number>.md`. If you accidentally modified any other tracked file, revert those changes before committing. Remove temporary context files instead of committing them.
7. Publish the result directly:
   - create or update the dedicated plan branch for the issue
   - commit only the plan file
   - push the branch
   - create or update the corresponding pull request
8. Use the pull request body and final response to summarize the plan and call out assumptions or open questions.

## Output expectations

- Publish a branch and pull request whose committed change is only the new or updated plan file.
- If the issue is underspecified, still produce the best possible plan and clearly capture assumptions or open questions in the plan file, pull request body, and final response.
