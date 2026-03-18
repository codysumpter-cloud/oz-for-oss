---
name: implement-issue
description: Implement a GitHub issue in this repository. Use when issue details are provided in the prompt and the agent should produce the repository diff and a concise implementation summary, without creating commits or pull requests itself.
---

# Implement a GitHub issue

Turn the assigned GitHub issue into an implementation-ready repository diff for this repository.

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

If `implementation_plan_context.md` exists, it contains the approved implementation plan from a linked pull request branch and should be treated as the primary design context for this run.

## Workflow

1. Read the issue details carefully. Review `implementation_plan_context.md` first when it exists, then review `issue_comments.txt` if it exists for any clarifications from organization members.
2. Inspect the repository to understand the current implementation before making changes.
3. Implement the requested behavior in the checked-out branch, keeping the changes scoped to the issue and aligned with any approved plan context.
4. Run the most relevant validation available in the repository for the files you changed. Prefer existing build, test, lint, or typecheck commands documented in the repository.
5. Write a concise markdown summary for the workflow to reuse in `implementation_summary.md` at the repository root. Include what changed, how it was validated, and any remaining assumptions or follow-up notes.
6. Treat `issue_comments.txt`, `implementation_plan_context.md`, and `implementation_summary.md` as temporary workflow files only. Do not include them in the final diff.
7. Do not stage files, create commits, push branches, open pull requests, or use the GitHub CLI. Another workflow step handles repository publishing after you finish.

## Output expectations

- Leave the repository with the implementation changes ready to be committed by the workflow.
- If the issue is underspecified, make the smallest reasonable implementation choice, document that choice in `implementation_summary.md`, and avoid speculative extra changes.
