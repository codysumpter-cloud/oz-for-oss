---
name: create-product-spec
description: Create a product spec from a GitHub issue in this repository. Use when an issue should be turned into a product spec artifact stored under the repo's `specs/` directory and the agent should prepare file changes only, without creating commits or pull requests itself.
---

# Create a product spec from a GitHub issue

Turn the assigned GitHub issue into a product spec for this repository.

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

## Workflow

1. Read the issue details carefully. If `issue_comments.txt` exists, review it for clarifications and prior decisions.
2. Inspect the repository to understand the current implementation and the likely scope of the requested work before writing the spec.
3. Create or update a product spec file at `specs/issue-<issue-number>/product.md`. Product specs for this repository live under `specs/`.
4. Keep the product spec focused on intended behavior and user-facing requirements. Include:
   - the problem or goal from the user's perspective
   - intended behavior and user-facing requirements
   - acceptance criteria
   - scope boundaries — what is in scope and what is explicitly out of scope
   - open product questions that need resolution before implementation
5. Do not include implementation details, file-level changes, or technical design — those belong in the tech spec.
6. Do not implement the feature or modify production code as part of this task. Limit changes to the product spec artifact. Treat temporary context files such as `issue_comments.txt` as scratch input only and do not commit them.
7. Default behavior: do not stage files, create commits, push branches, open pull requests, or use the GitHub CLI. If the prompt explicitly says you are running in a cloud-environment workflow where the caller cannot read your local diff and instructs you to publish a named branch, you may commit and push exactly the requested spec changes to that branch, but still do not open or update the pull request yourself unless the prompt explicitly asks for it.
8. In your final response, provide a brief summary of the product spec and call out any assumptions or open questions so the workflow can reuse that summary when creating the PR.

## Output expectations

- Leave the repository with the new or updated product spec file ready to be committed by the workflow.
- If the issue is underspecified, still produce the best possible product spec and clearly capture assumptions or open questions in the spec file and final response.
