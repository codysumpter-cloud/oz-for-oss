---
name: implement-issue
description: Implement a GitHub issue in this repository by applying the local shared `implement-specs` workflow with Oz-specific issue, spec-context, and summary-file handling. Use when issue details are provided in the prompt and the agent should produce the repository diff and a concise implementation summary, without creating commits or pull requests itself unless a cloud workflow explicitly asks for it.
---

# implement-issue

Implement a GitHub issue for this repository.

## Overview

This skill is a thin Oz wrapper around the local shared implementation skills:

- `.agents/skills/implement-specs/SKILL.md`
- `.agents/skills/spec-driven-implementation/SKILL.md`

Use those shared local skills as the base behavior unless this wrapper overrides them. Keep the same core model:

- approved product intent is the source of truth for user-facing behavior
- approved tech design is the source of truth for implementation shape
- specs and code should stay aligned as implementation evolves

The Oz-specific differences are:

- the primary input is a GitHub issue, not a Linear-driven Warp feature workflow
- approved spec context may be supplied in `spec_context.md`
- issue discussion may be supplied in `issue_comments.txt`
- the workflow expects a reusable markdown summary in `implementation_summary.md`

## Inputs

Expect issue details in the prompt, including the issue number, title, description, labels, assignees, and optional prior discussion captured in `issue_comments.txt`.

If `spec_context.md` exists, it contains the approved spec context (product spec and/or tech spec) from a linked pull request branch and should be treated as the primary design context for this run.

## Workflow

1. Start from the local shared `implement-specs` behavior. Treat approved spec material as the source of truth for behavior and implementation shape.
2. Read the issue details carefully. Review `spec_context.md` first when it exists, then review `issue_comments.txt` if it exists for clarifications from organization members.
3. Inspect the repository to understand the current implementation before making changes.
4. Implement the requested behavior in the checked-out branch, keeping the changes scoped to the issue and aligned with any approved spec context.
5. Keep specs aligned with implementation. If the checked-out branch contains corresponding spec files under `specs/GH<issue-number>/` and the implementation reveals material changes to behavior, edge cases, validation expectations, or technical design, update the relevant spec files in the same diff instead of leaving them stale.
6. Do not let unresolved issue comments silently override approved spec context. If a comment suggests a different direction than the approved plan, make the smallest reasonable implementation choice and capture the discrepancy in `implementation_summary.md`.
7. Do not include issue number references (e.g. `(#N)`, `Refs #N`) in commit messages. The issue is already linked in the PR body, the branch name, and the linked issue itself.
8. Run the most relevant validation available in the repository for the files you changed. Prefer existing build, test, lint, or typecheck commands documented in the repository.
9. Write a concise markdown summary for the workflow to reuse in `implementation_summary.md` at the repository root. Include what changed, how it was validated, and any remaining assumptions, spec updates, or follow-up notes.
10. Treat `issue_comments.txt`, `spec_context.md`, and `implementation_summary.md` as temporary workflow files only. Do not include them in the final diff.
11. Default behavior: do not stage files, create commits, push branches, open pull requests, or use the GitHub CLI. If the prompt explicitly says you are running in a cloud-environment workflow where the caller cannot read your local diff and instructs you to publish a named branch, you may commit and push exactly the requested implementation changes to that branch, but still do not open or update the pull request yourself unless the prompt explicitly asks for it.

## Output expectations

- Leave the repository with the implementation changes ready to be committed by the workflow.
- If the issue is underspecified, make the smallest reasonable implementation choice, document that choice in `implementation_summary.md`, and avoid speculative extra changes.
