# Agents platform in `oz-for-oss`

`oz-for-oss` is organized around Oz-backed GitHub automation. The repository does not define one monolithic agent. Instead, it defines a set of specialized agents and guardrails that are wired into GitHub Actions, Python workflow entrypoints, and local repository skills.

At a high level, the stack looks like this:

1. A top-level workflow in `.github/workflows/*-local.yml` listens for GitHub events in this repository.
2. That workflow usually delegates to a reusable `workflow_call` workflow in `.github/workflows/*.yml`.
3. The reusable workflow runs a Python entrypoint from `.github/scripts/`.
4. The Python entrypoint assembles repository context, invokes Oz, and applies the result back to GitHub.
5. When the task is repository-specific, the Oz run is grounded in local skills under `.agents/skills/`.

This document describes the repository's agent behaviors, the events that trigger them, what each one does, and how they fit together in the OSS management workflow.

## System roles

The agent system in this repository covers five stages of the contribution lifecycle:

- **Issue intake:** understand new issues, normalize them, and decide whether more information is needed.
- **Issue clarification:** answer follow-up comments on already triaged issues that are not ready for execution.
- **Spec creation:** turn approved, ready issues into committed product and technical specs.
- **Implementation:** create or update implementation branches and pull requests for issues that are ready to build.
- **PR governance and review:** enforce issue-state policy, review pull requests, respond to PR comments, and periodically improve the review skills from human feedback.

## Architectural split: local entrypoints vs reusable workflows

The repository uses two workflow layers:

- **Local entrypoint workflows** such as `triage-new-issues-local.yml` and `create-spec-from-issue-local.yml` define the actual GitHub triggers for this repository.
- **Reusable workflows** such as `triage-new-issues.yml` and `create-spec-from-issue.yml` hold the shared execution logic and can be called from other repositories.

When reading the trigger descriptions below, the trigger normally comes from the `*-local.yml` workflow, while the behavior is implemented in the reusable workflow plus its Python script.

## Agent catalog

### 1. Issue triage agent

**Entry workflows**

- `.github/workflows/triage-new-issues-local.yml`
- `.github/workflows/triage-new-issues.yml`

**Primary script and skills**

- `.github/scripts/triage_new_issues.py`
- `.agents/skills/triage-issue/SKILL.md`
- `.agents/skills/dedupe-issue/SKILL.md`

**Triggers**

- New issue opened.
- Hourly scheduled scan for recent untriaged issues.
- Issue comment created on a non-PR issue when:
  - the issue is not yet triaged and an organization member mentions `@oz-agent`, or
  - the issue is labeled `needs-info`, the original reporter replies, and the reply does not mention `@oz-agent`.
- Manual `workflow_dispatch` with an explicit issue number or lookback window.

**Behavior**

- Selects the issue or batch of recent untriaged issues to process.
- Loads triage labels from `.github/issue-triage/config.json`.
- Loads ownership hints from `.github/STAKEHOLDERS`.
- Discovers issue-template context when present.
- Collects existing issue comments and recent open issues for duplicate detection.
- Runs Oz with the local `triage-issue` skill and explicitly asks it to use the `dedupe-issue` skill.
- Validates the structured `triage_result.json` output.
- Applies the result back to GitHub by updating managed labels, rewriting the visible issue body, and syncing managed follow-up or duplicate comments when needed.

**Role in the workflow**

This is the intake and normalization agent. It turns a raw issue into structured repository state that downstream automation can trust: labels, repro confidence, likely area, follow-up questions, and a cleaner issue body.

### 2. Triaged-issue response agent

**Entry workflows**

- `.github/workflows/respond-to-triaged-issue-comment-local.yml`
- `.github/workflows/respond-to-triaged-issue-comment.yml`

**Primary script and skill**

- `.github/scripts/respond_to_triaged_issue_comment.py`
- `.agents/skills/triage-issue/SKILL.md`

**Triggers**

- Issue comment created on a non-PR issue when:
  - the comment mentions `@oz-agent`,
  - the issue is already labeled `triaged`, and
  - the issue is not labeled `ready-to-spec` or `ready-to-implement`.

**Behavior**

- Adds an `eyes` reaction to the triggering comment.
- Gathers the current issue body, original report, and visible issue discussion.
- Runs Oz to produce a concise inline analysis response in `issue_response.json`.
- Posts the analysis back as the workflow progress comment text.
- Does **not** rewrite the issue body or change labels.

**Role in the workflow**

This agent handles the gap between initial triage and execution readiness. It gives maintainers and reporters a way to ask clarifying questions without retriggering full issue mutation.

### 3. Spec creation agent

**Entry workflows**

- `.github/workflows/create-spec-from-issue-local.yml`
- `.github/workflows/create-spec-from-issue.yml`

**Primary script and skills**

- `.github/scripts/create_spec_from_issue.py`
- `.agents/skills/spec-driven-implementation/SKILL.md`
- `.agents/skills/create-product-spec/SKILL.md`
- `.agents/skills/create-tech-spec/SKILL.md`
- shared writing skills referenced by the wrapper:
  - `.agents/skills/write-product-spec/SKILL.md`
  - `.agents/skills/write-tech-spec/SKILL.md`

**Triggers**

- Issue assigned to `oz-agent` while already labeled `ready-to-spec`.
- `ready-to-spec` label added to an issue already assigned to `oz-agent`.
- Organization member mentions `@oz-agent` on a non-PR issue already labeled `ready-to-spec`.

**Behavior**

- Assigns the issue to `oz-agent`.
- Collects issue details plus prior organization-member comments.
- Runs a spec-first Oz workflow that creates:
  - `specs/issue-<number>/product.md`
  - `specs/issue-<number>/tech.md`
- If a spec diff is produced, commits it to `oz-agent/spec-issue-<number>` and pushes the branch.
- Creates or updates a non-draft pull request for the spec branch.

**Role in the workflow**

This agent converts a triaged, approved issue into durable design artifacts. It is the handoff from issue discussion into explicit product and implementation intent.

### 4. Implementation agent

**Entry workflows**

- `.github/workflows/create-implementation-from-issue-local.yml`
- `.github/workflows/create-implementation-from-issue.yml`

**Primary script and skills**

- `.github/scripts/create_implementation_from_issue.py`
- `.agents/skills/implement-issue/SKILL.md`
- `.agents/skills/implement-specs/SKILL.md`
- `.agents/skills/spec-driven-implementation/SKILL.md`

**Triggers**

- Issue assigned to `oz-agent` while already labeled `ready-to-implement`.
- `ready-to-implement` label added to an issue already assigned to `oz-agent`.
- Organization member mentions `@oz-agent` on a non-PR issue already labeled `ready-to-implement`.

**Behavior**

- Assigns the issue to `oz-agent`.
- Resolves relevant spec context from approved spec PRs or checked-in files under `specs/`.
- Refuses to start if related spec PRs exist but none are labeled `plan-approved`.
- Runs Oz to implement the issue on:
  - the approved spec PR branch when one exists, or
  - a fresh `oz-agent/implement-issue-<number>` branch otherwise.
- Runs repository validation through the implementation skill.
- Pushes changes and either:
  - updates the existing approved spec PR, or
  - creates or updates a draft implementation PR.

**Role in the workflow**

This is the build agent. It turns ready issues and approved plan context into repository diffs while keeping specs and code aligned.

### 5. PR issue-state enforcement agent

**Entry workflows**

- `.github/workflows/pr-hooks.yml`
- `.github/workflows/enforce-pr-issue-state.yml`

**Primary script**

- `.github/scripts/enforce_pr_issue_state.py`

**Triggers**

- Pull request opened, reopened, or marked ready for review through `pull_request_target`.
- The enforcement path is skipped on `synchronize` updates and for organization-member PR authors.

**Behavior**

- Determines whether the PR is a spec PR or an implementation PR based on changed files.
- Looks for an explicitly linked issue in the PR body.
- Verifies that the linked issue is in the correct ready state:
  - `ready-to-spec` for spec work, unless the PR is already labeled `plan-approved`
  - `ready-to-implement` for implementation work
- If no explicit issue link is found, runs Oz to match the PR against open ready issues.
- Automatically closes PRs that do not match a valid ready issue and leaves an explanatory status comment.
- Emits an `allow_review` output that gates the rest of the PR pipeline.

**Role in the workflow**

This agent is the policy gatekeeper. It prevents review and merge work from starting on PRs that bypass the repository's issue readiness model.

### 6. Pull request review agent

**Entry workflows**

- `.github/workflows/pr-hooks.yml`
- `.github/workflows/review-pull-request.yml`

**Primary script and skills**

- `.github/scripts/review_pr.py`
- `.agents/skills/review-pr/SKILL.md`
- `.agents/skills/review-spec/SKILL.md`
- `.agents/skills/check-impl-against-spec/SKILL.md`

**Triggers**

- Automatically after PR issue-state enforcement passes for:
  - opened PRs,
  - reopened PRs,
  - PRs marked ready for review.
- Automatically on `pull_request_target` `synchronize` events after tests run.
- On demand through `pr-hooks.yml` when:
  - a PR comment contains `/oz-review`, or
  - a PR comment contains `@oz-agent /review`.
- Manual `workflow_dispatch` with a PR number and optional review focus.

**Behavior**

- Resolves spec context associated with the PR.
- Chooses `review-spec` when every changed file is under `specs/`; otherwise chooses `review-pr`.
- Runs Oz in cloud-review mode, requiring it to materialize `pr_description.txt`, annotated `pr_diff.txt`, and `spec_context.md` when available.
- Receives structured `review.json` output through a temporary transport comment.
- Posts the final GitHub review with summary text and any inline comments.

**Role in the workflow**

This agent is the repository reviewer. It provides first-pass automated review for both design PRs and code PRs, with optional spec-compliance checks when spec context exists.

### 7. PR comment implementation responder

**Entry workflow**

- `.github/workflows/respond-to-pr-comment.yml`

**Primary script and skill**

- `.github/scripts/respond_to_pr_comment.py`
- `.agents/skills/implement-issue/SKILL.md`

**Triggers**

- New `issue_comment` on a pull request.
- New `pull_request_review_comment`.
- In both cases, the comment must:
  - mention `@oz-agent`,
  - come from a collaborator, member, or owner, and
  - not come from `github-actions[bot]`.

**Behavior**

- Adds an `eyes` reaction to the triggering comment.
- Collects the triggering comment plus either full PR discussion context or the specific review-thread context.
- Resolves spec context for the PR.
- Runs Oz against the current PR head branch using the implementation skill.
- If code changes are produced, commits and pushes them to the existing PR branch.
- Does not open a new PR or update PR metadata.

**Role in the workflow**

This agent lets maintainers turn PR discussion directly into follow-up code changes. It is the iterative change loop after an implementation PR already exists.

### 8. Review-skill maintenance agent

**Entry workflows**

- `.github/workflows/update-pr-review-local.yml`
- `.github/workflows/update-pr-review.yml`

**Primary script and skill**

- `.github/scripts/update_pr_review.py`
- `.agents/skills/update-pr-review/SKILL.md`

**Triggers**

- Weekly schedule every Monday at 09:00 UTC.
- Manual `workflow_dispatch` with an optional lookback window.

**Behavior**

- Aggregates recent PR review feedback over the requested lookback period.
- Separates evidence from code PRs and spec PRs.
- Uses that evidence to refine:
  - `.agents/skills/review-pr/SKILL.md`
  - `.agents/skills/review-spec/SKILL.md`
- If changes are warranted, commits them to `oz-agent/update-pr-review`, pushes the branch, opens a PR, and tags `@captainsafia`.

**Role in the workflow**

This is the meta-improvement agent. It closes the loop by using human reviewer feedback to improve future automated reviews.

### 9. Unready-assignment guardrail

**Entry workflows**

- `.github/workflows/comment-on-unready-assigned-issue-local.yml`
- `.github/workflows/comment-on-unready-assigned-issue.yml`

**Primary script**

- `.github/scripts/comment_on_unready_assigned_issue.py`

**Triggers**

- Issue assigned to `oz-agent` without either `ready-to-spec` or `ready-to-implement`.

**Behavior**

- Posts a progress comment explaining that the issue is not ready for Oz to work on.
- Removes the `oz-agent` assignee from the issue.

**Role in the workflow**

This is a lightweight guardrail rather than a generative agent. Its purpose is to keep the issue queue clean and reinforce the repository's ready-state labeling model.

## End-to-end OSS workflow

The agents form a staged pipeline:

1. **New issue arrives** → the triage agent classifies it, labels it, rewrites the issue body, and asks follow-up questions if needed.
2. **Discussion continues on a triaged issue** → the triaged-issue response agent answers clarifying `@oz-agent` mentions without mutating issue state.
3. **Maintainers mark the issue ready for design** → the spec creation agent writes `product.md` and `tech.md`, pushes a branch, and opens a spec PR.
4. **Spec is approved** → the implementation agent uses approved spec context to produce code changes and create or update an implementation PR.
5. **PR enters review** → the enforcement agent checks issue readiness, then the review agent performs automated PR review.
6. **Maintainers ask for changes in the PR** → the PR comment responder pushes follow-up changes onto the existing branch.
7. **Human feedback accumulates over time** → the review-skill maintenance agent updates the review skills so later reviews improve.

## Repository files that define the platform

The most important source files for understanding or changing the platform are:

- `.github/workflows/` for event triggers and orchestration
- `.github/scripts/` for workflow entrypoints and GitHub mutations
- `.github/scripts/oz_workflows/` for shared Oz and GitHub helpers
- `.agents/skills/` for repository-specific agent behavior
- `.github/issue-triage/config.json` for the triage label taxonomy
- `.github/STAKEHOLDERS` for ownership hints used during triage

## Design principles visible in the current implementation

Several platform-level principles show up repeatedly across the agents:

- **Skills are task-specific.** Triage, spec writing, implementation, review, and review-skill updates each use dedicated skills instead of one generic prompt.
- **GitHub state is the control plane.** Labels, assignees, comments, PR state, and branch names are the main coordination primitives.
- **Specs are first-class artifacts.** The implementation flow is designed to prefer approved spec context and to keep specs and code aligned.
- **Repository policy is enforced before review.** PRs are not treated as valid work unless they map back to issues in the correct ready state.
- **Agent output is structured when possible.** JSON transport files such as `triage_result.json`, `issue_response.json`, and `review.json` are used to keep automation deterministic.
- **The system is self-improving.** The review-skill maintenance flow updates the review instructions from real reviewer feedback.
