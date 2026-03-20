---
name: implement-issue
description: Implement a GitHub issue in this repository. Use when issue details are provided in the prompt and the agent should publish the resulting implementation branch and pull request directly, while keeping commits scoped to the issue.
---

# Implement and publish a GitHub issue

Turn the assigned GitHub issue into an implementation-ready repository change for this repository and publish it directly.

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

If `implementation_plan_context.md` exists, it contains the approved implementation plan from a linked pull request branch and should be treated as the primary design context for this run.

## Workflow

1. Read the issue details carefully. Review `implementation_plan_context.md` first when it exists, then review `issue_comments.txt` if it exists for any clarifications from organization members.
2. Inspect the repository to understand the current implementation before making changes.
3. Implement the requested behavior, keeping the changes scoped to the issue and aligned with any approved plan context.
4. Run the most relevant validation available in the repository for the files you changed. Prefer existing build, test, lint, or typecheck commands documented in the repository.
5. Prepare a concise implementation summary that includes what changed, how it was validated, and any remaining assumptions or follow-up notes. Use that summary in the pull request body and final response.
6. Treat `issue_comments.txt`, `implementation_plan_context.md`, and `implementation_summary.md` as temporary workflow files only. Do not include them in the final commit.
7. Before publishing, review the final diff and make sure it contains only issue-scoped implementation changes plus any intentionally updated issue-specific plan file or repository metadata explicitly required by the task. Revert or remove accidental unrelated edits and temporary files.
8. Publish the result directly:
   - create or update the intended implementation branch for the issue
   - commit the final implementation changes
   - push the branch
   - create or update the corresponding pull request
9. If the prompt directs you to continue work on an existing plan PR branch, publish to that branch instead of creating a new PR.

## Output expectations

- Publish a branch and pull request containing the implementation changes for the issue.
- If the issue is underspecified, make the smallest reasonable implementation choice, document that choice in the pull request body and final response, and avoid speculative extra changes.
