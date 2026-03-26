---
name: create-tech-spec
description: Create a technical spec from a GitHub issue in this repository. Use when an issue should be turned into a tech spec artifact stored under the repo's `specs/` directory and the agent should prepare file changes only, without creating commits or pull requests itself.
---

# Create a tech spec from a GitHub issue

Turn the assigned GitHub issue into a technical spec for this repository.

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

When available, the product spec at `specs/issue-<issue-number>/product.md` should be treated as the primary input for understanding the intended behavior. The tech spec translates that product intent into an implementation approach.

## Workflow

1. Read the issue details carefully. If a product spec exists at `specs/issue-<issue-number>/product.md`, read it first to understand the intended behavior. If `issue_comments.txt` exists, review it for clarifications and prior decisions.
2. Inspect the repository to understand the current implementation and the likely scope of the requested work before writing the spec.
3. Create or update a tech spec file at `specs/issue-<issue-number>/tech.md`. Tech specs for this repository live under `specs/`.
4. Keep the tech spec concise and actionable. Include:
   - the problem or goal
   - the most relevant current-state observations from the codebase
   - the proposed changes with file-level detail
   - notable risks, dependencies, or open technical questions
5. Do not implement the feature or modify production code as part of this task. Limit changes to the tech spec artifact and any minimal repository metadata needed to support it. Treat temporary context files such as `issue_comments.txt` as scratch input only and do not commit them.
6. Default behavior: do not stage files, create commits, push branches, open pull requests, or use the GitHub CLI. If the prompt explicitly says you are running in a cloud-environment workflow where the caller cannot read your local diff and instructs you to publish a named branch, you may commit and push exactly the requested spec changes to that branch, but still do not open or update the pull request yourself unless the prompt explicitly asks for it.
7. In your final response, provide a brief summary of the tech spec and call out any assumptions or open questions so the workflow can reuse that summary when creating the PR.

## Output expectations

- Leave the repository with the new or updated tech spec file ready to be committed by the workflow.
- If the issue is underspecified, still produce the best possible tech spec and clearly capture assumptions or open questions in the spec file and final response.
